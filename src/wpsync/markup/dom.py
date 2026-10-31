"""A small HTML tree for converting and comparing post content.

Markup is parsed with html5lib, which follows the HTML parsing rules browsers
use, so the tree is what a reader's browser builds.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import html5lib

VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
RAW_TEXT_TAGS = frozenset({"script", "style"})
PRESERVED_WHITESPACE_TAGS = frozenset({"pre", "textarea", "script", "style"})
BLOCK_TAGS = frozenset(
    """address article aside blockquote caption col colgroup dd details dialog div
    dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr
    li main menu nav ol p pre section summary table tbody td tfoot th thead tr
    ul""".split()
)
"""Elements browsers display as blocks, so whitespace around their edges is hidden."""
TAG_ALIASES = {"b": "strong", "i": "em"}
EDGE_SPACE_TAGS = frozenset({"strong", "em"})
EMPTY_FORMATTING_TAGS = frozenset({"strong", "em", "b", "i", "span"})
WHITESPACE = re.compile(r"[ \t\n\r\f]+")
HTML_SPACE = " \t\n\r\f"
NO_BREAK_SPACE = "\xa0"
LAYOUT_STYLE = re.compile(r"(?:^|;)\s*(?:white-space|display)\s*:", re.IGNORECASE)
NAMESPACE_PREFIXES = {
    "http://www.w3.org/1999/xlink": "xlink",
    "http://www.w3.org/XML/1998/namespace": "xml",
    "http://www.w3.org/2000/xmlns/": "xmlns",
}


@dataclass
class Element:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class Comment:
    text: str


Node = Element | Comment | str

_PARSER = html5lib.HTMLParser(namespaceHTMLElements=False)


def _local_name(name: str) -> str:
    if not name.startswith("{"):
        return name
    namespace, local = name[1:].split("}", 1)
    prefix = NAMESPACE_PREFIXES.get(namespace)
    return f"{prefix}:{local}" if prefix else local


def _append_node(nodes: list[Node], node: Node) -> None:
    if isinstance(node, str) and nodes and isinstance(nodes[-1], str):
        nodes[-1] += node
    elif node != "":
        nodes.append(node)


def _children(element: ET.Element) -> list[Node]:
    nodes: list[Node] = []
    _append_node(nodes, element.text or "")
    for child in element:
        if child.tag is ET.Comment:
            nodes.append(Comment(child.text or ""))
        else:
            attrs = {_local_name(name): value for name, value in child.attrib.items()}
            nodes.append(Element(_local_name(child.tag), attrs, _children(child)))
        _append_node(nodes, child.tail or "")
    return nodes


def parse_html(markup: str) -> list[Node]:
    return _children(_PARSER.parseFragment(markup))


def _escape_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attribute(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace("\n", "&#10;")
    )


def start_tag(element: Element) -> str:
    attributes = "".join(
        f' {name}="{_escape_attribute(value)}"' for name, value in element.attrs.items()
    )
    return f"<{element.tag}{attributes}>"


def preserves_whitespace(element: Element) -> bool:
    """Whether whitespace in and around the element may be displayed as written."""
    return element.tag in PRESERVED_WHITESPACE_TAGS or bool(
        LAYOUT_STYLE.search(element.attrs.get("style", ""))
    )


def serialize(nodes: list[Node], *, preserve_whitespace: bool = False) -> str:
    """Serialize without line breaks outside elements that preserve whitespace."""
    out = []
    for node in nodes:
        if isinstance(node, str):
            text = node if preserve_whitespace else node.replace("\n", " ")
            out.append(_escape_text(text))
        elif isinstance(node, Comment):
            if node.text.strip(HTML_SPACE):
                out.append(f"<!--{node.text}-->")
        elif node.tag in VOID_TAGS:
            out.append(start_tag(node)[:-1] + " />")
        else:
            preserve = preserve_whitespace or preserves_whitespace(node)
            if node.tag in RAW_TEXT_TAGS:
                inner = "".join(
                    child for child in node.children if isinstance(child, str)
                )
            else:
                inner = serialize(node.children, preserve_whitespace=preserve)
            out.append(f"{start_tag(node)}{inner}</{node.tag}>")
    return "".join(out)


def to_html(nodes: list[Node]) -> str:
    return serialize(trim_block_whitespace(nodes))


def is_block(node: Node) -> bool:
    return (
        isinstance(node, Element)
        and node.tag in BLOCK_TAGS
        and not LAYOUT_STYLE.search(node.attrs.get("style", ""))
    )


def _breaks_line(node: Node | None) -> bool:
    """Whitespace next to a block or a line break is not displayed."""
    return is_block(node) or (isinstance(node, Element) and node.tag == "br")


def trim_block_whitespace(
    nodes: list[Node], *, block_context: bool = True
) -> list[Node]:
    """Drop whitespace that cannot affect display, and spacing made of markup.

    Browsers do not display whitespace around block elements or at the start
    and end of a line, including inside inline elements at those positions.
    Blank paragraphs and repeated line breaks are how authors force vertical
    space in WordPress, which is not content: Markdown has no use for them.
    """
    result: list[Node] = []
    for node in nodes:
        if isinstance(node, Element) and not preserves_whitespace(node):
            children = trim_block_whitespace(
                node.children, block_context=is_block(node)
            )
            if is_block(node):
                children = _trim_breaks(children)
            if node.tag == "p" and not node.attrs:
                result.extend(Element("p", {}, part) for part in _paragraphs(children))
                continue
            node = Element(node.tag, node.attrs, children)
        result.append(node)
    result = _strip_after_breaks(result, block_context, leading=True)
    result.reverse()
    result = _strip_after_breaks(result, block_context, leading=False)
    result.reverse()
    return [node for node in result if not _displays_nothing(node)]


def _displays_nothing(node: Node) -> bool:
    """Plain formatting with nothing inside, or a plain paragraph of blank lines."""
    if not isinstance(node, Element) or node.attrs:
        return False
    if node.tag in EMPTY_FORMATTING_TAGS:
        return not node.children
    return node.tag == "p" and all(_is_filler(child) for child in node.children)


def _is_break(node: Node) -> bool:
    return node == Element("br")


def _is_filler(node: Node) -> bool:
    """Spaces, line breaks, or plain formatting holding only those."""
    if isinstance(node, str):
        return not node.strip(HTML_SPACE + NO_BREAK_SPACE)
    return (
        isinstance(node, Element)
        and not node.attrs
        and (
            node.tag == "br"
            or (
                node.tag in EMPTY_FORMATTING_TAGS
                and all(_is_filler(child) for child in node.children)
            )
        )
    )


def _trim_breaks(children: list[Node]) -> list[Node]:
    start, end = 0, len(children)
    while start < end and _is_break(children[start]):
        start += 1
    while end > start and _is_break(children[end - 1]):
        end -= 1
    return children[start:end]


def _paragraphs(children: list[Node]) -> list[list[Node]]:
    """Split a paragraph's content at blank lines made of repeated line breaks."""
    parts: list[list[Node]] = [[]]
    filler: list[Node] = []
    for child in children:
        if _is_filler(child):
            filler.append(child)
            continue
        if sum(_is_break(node) for node in filler) > 1:
            parts.append([])
        else:
            parts[-1].extend(filler)
        filler = []
        parts[-1].append(child)
    parts[-1].extend(filler)
    return parts


def _strip_after_breaks(
    nodes: list[Node], block_context: bool, *, leading: bool
) -> list[Node]:
    kept: list[Node] = []
    for node in nodes:
        previous = kept[-1] if kept else None
        if (previous is None and block_context) or _breaks_line(previous):
            node = _strip_edge(node, leading=leading)
        if node != "":
            kept.append(node)
    return kept


def _strip_edge(node: Node, *, leading: bool) -> Node:
    if isinstance(node, str):
        return node.lstrip(HTML_SPACE) if leading else node.rstrip(HTML_SPACE)
    if (
        not isinstance(node, Element)
        or is_block(node)
        or preserves_whitespace(node)
        or not node.children
    ):
        return node
    children = list(node.children)
    index = 0 if leading else -1
    children[index] = _strip_edge(children[index], leading=leading)
    return Element(node.tag, node.attrs, [child for child in children if child != ""])


Canonical = tuple


def _canonical_attrs(attrs: dict[str, str], ignored_classes: frozenset[str]) -> tuple:
    items = []
    for name, value in attrs.items():
        if name == "class":
            classes = sorted(set(value.split()) - ignored_classes)
            if not classes:
                continue
            value = " ".join(classes)
        items.append((name, value))
    return tuple(sorted(items))


def _canonical_children(
    nodes: list[Node], ignored_classes: frozenset[str], preserve: bool
) -> list[Canonical]:
    out: list[Canonical] = []
    for node in nodes:
        if isinstance(node, str):
            _append_text(out, node if preserve else WHITESPACE.sub(" ", node))
        elif isinstance(node, Comment):
            # Comments are never displayed; only their words matter.
            text = WHITESPACE.sub(" ", node.text).strip()
            if text:
                out.append(("comment", text))
        else:
            tag = TAG_ALIASES.get(node.tag, node.tag)
            attrs = _canonical_attrs(node.attrs, ignored_classes)
            inner = _canonical_children(
                node.children, ignored_classes, preserve or preserves_whitespace(node)
            )
            if tag == "pre":
                inner = _trim_trailing_newline(inner)
            if tag == "span" and not attrs:
                for child in inner:
                    if child[0] == "text":
                        _append_text(out, child[1])
                    else:
                        out.append(child)
            elif tag in EDGE_SPACE_TAGS and not attrs and not preserve:
                lead, inner, trail = _edge_spaces(inner)
                _append_text(out, lead)
                out.append(("element", tag, attrs, tuple(inner)))
                _append_text(out, trail)
            else:
                out.append(("element", tag, attrs, tuple(inner)))
    return out


def _append_text(out: list[Canonical], text: str) -> None:
    if not text:
        return
    if out and out[-1][0] == "text":
        out[-1] = ("text", out[-1][1] + text)
    else:
        out.append(("text", text))


def _edge_spaces(inner: list[Canonical]) -> tuple[str, list[Canonical], str]:
    """Spaces at the edges of plain bold or italic text display as if outside it."""
    inner = list(inner)
    lead = trail = ""
    if inner and inner[0][0] == "text" and inner[0][1].startswith(" "):
        lead = " "
        inner[0] = ("text", inner[0][1].lstrip(" "))
    if inner and inner[-1][0] == "text" and inner[-1][1].endswith(" "):
        trail = " "
        inner[-1] = ("text", inner[-1][1].rstrip(" "))
    return lead, [node for node in inner if node != ("text", "")], trail


def _trim_trailing_newline(children: list[Canonical]) -> list[Canonical]:
    """A single line break at the very end of `<pre>` is not displayed."""
    if not children:
        return children
    children = list(children)
    last = children[-1]
    if last[0] == "text":
        text = last[1].removesuffix("\n")
        children[-1] = ("text", text)
        return [child for child in children if child != ("text", "")]
    if last[0] == "element":
        children[-1] = (*last[:3], tuple(_trim_trailing_newline(list(last[3]))))
    return children


def canonical(
    nodes: list[Node], ignored_classes: frozenset[str] = frozenset()
) -> Canonical:
    """A comparable form that is equal when two trees display the same."""
    return tuple(
        _canonical_children(trim_block_whitespace(nodes), ignored_classes, False)
    )
