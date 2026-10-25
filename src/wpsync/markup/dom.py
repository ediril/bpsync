"""A small HTML tree for converting and comparing post content."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
RAW_TEXT_TAGS = frozenset({"script", "style"})
PRESERVED_WHITESPACE_TAGS = frozenset({"pre", "textarea", "script", "style"})
BLOCK_TAGS = frozenset(
    """address article aside blockquote caption col colgroup dd details dialog div
    dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr
    li main menu nav ol p pre section summary table tbody td tfoot th thead tr ul
    audio canvas embed iframe object picture svg video""".split()
)
"""Elements whose surrounding and edge whitespace does not affect display."""
TAG_ALIASES = {"b": "strong", "i": "em"}
EDGE_SPACE_TAGS = frozenset({"strong", "em"})
WHITESPACE = re.compile(r"[ \t\n\r\f]+")


@dataclass
class Element:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class Comment:
    text: str


Node = Element | Comment | str


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("")
        self.stack = [self.root]

    def _append(self, node: Node) -> None:
        children = self.stack[-1].children
        if isinstance(node, str) and children and isinstance(children[-1], str):
            children[-1] += node
        else:
            children.append(node)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, {name: value or "" for name, value in attrs})
        self._append(element)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._append(Element(tag, {name: value or "" for name, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        self._append(data)

    def handle_comment(self, data: str) -> None:
        self._append(Comment(data))


def parse_html(markup: str) -> list[Node]:
    builder = _TreeBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root.children


def _escape_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attribute(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def start_tag(element: Element) -> str:
    attributes = "".join(
        f' {name}="{_escape_attribute(value)}"' for name, value in element.attrs.items()
    )
    return f"<{element.tag}{attributes}>"


def serialize(nodes: list[Node], *, preserve_whitespace: bool = False) -> str:
    """Serialize without line breaks outside elements that preserve whitespace."""
    out = []
    for node in nodes:
        if isinstance(node, str):
            text = node if preserve_whitespace else node.replace("\n", " ")
            out.append(_escape_text(text))
        elif isinstance(node, Comment):
            if node.text.strip():
                out.append(f"<!--{node.text.replace(chr(10), ' ')}-->")
        elif node.tag in VOID_TAGS:
            out.append(start_tag(node)[:-1] + " />")
        else:
            preserve = preserve_whitespace or node.tag in PRESERVED_WHITESPACE_TAGS
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
    return isinstance(node, Element) and node.tag in BLOCK_TAGS


def _breaks_line(node: Node | None) -> bool:
    """Whitespace next to a block or a line break is not displayed."""
    return isinstance(node, Element) and (node.tag in BLOCK_TAGS or node.tag == "br")


def trim_block_whitespace(
    nodes: list[Node], *, block_context: bool = True
) -> list[Node]:
    """Drop whitespace that cannot affect display.

    Browsers do not display whitespace around block elements or at the start
    and end of a line, including inside inline elements at those positions.
    """
    result: list[Node] = []
    for node in nodes:
        if isinstance(node, Element) and node.tag not in PRESERVED_WHITESPACE_TAGS:
            children = trim_block_whitespace(
                node.children, block_context=node.tag in BLOCK_TAGS
            )
            node = Element(node.tag, node.attrs, children)
        result.append(node)
    result = _strip_after_breaks(result, block_context, leading=True)
    result.reverse()
    result = _strip_after_breaks(result, block_context, leading=False)
    result.reverse()
    return result


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
        return node.lstrip(" \t\n\r\f") if leading else node.rstrip(" \t\n\r\f")
    if (
        not isinstance(node, Element)
        or node.tag in BLOCK_TAGS
        or node.tag in PRESERVED_WHITESPACE_TAGS
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
            text = node if preserve else WHITESPACE.sub(" ", node)
            if out and out[-1][0] == "text":
                out[-1] = ("text", out[-1][1] + text)
            elif text:
                out.append(("text", text))
        elif isinstance(node, Comment):
            if node.text.strip():
                out.append(("comment", node.text.strip()))
        else:
            tag = TAG_ALIASES.get(node.tag, node.tag)
            attrs = _canonical_attrs(node.attrs, ignored_classes)
            inner = _canonical_children(
                node.children,
                ignored_classes,
                preserve or node.tag in PRESERVED_WHITESPACE_TAGS,
            )
            if tag == "pre":
                inner = _trim_preformatted(inner)
            if tag == "span" and not attrs:
                for child in inner:
                    if child[0] == "text" and out and out[-1][0] == "text":
                        out[-1] = ("text", out[-1][1] + child[1])
                    else:
                        out.append(child)
            elif tag in EDGE_SPACE_TAGS and not preserve:
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
    """Spaces at the edges of bold or italic text display as if outside it."""
    inner = list(inner)
    lead = trail = ""
    if inner and inner[0][0] == "text" and inner[0][1].startswith(" "):
        lead = " "
        inner[0] = ("text", inner[0][1].lstrip(" "))
    if inner and inner[-1][0] == "text" and inner[-1][1].endswith(" "):
        trail = " "
        inner[-1] = ("text", inner[-1][1].rstrip(" "))
    return lead, [node for node in inner if node != ("text", "")], trail


def _trim_preformatted(children: list[Canonical]) -> list[Canonical]:
    """Browsers do not display one leading or trailing newline in `<pre>`."""

    def edit(nodes: list[Canonical], index: int, trim) -> list[Canonical]:  # noqa: ANN001
        if not nodes:
            return nodes
        node = nodes[index]
        nodes = list(nodes)
        if node[0] == "text":
            text = trim(node[1])
            nodes[index] = ("text", text)
            return [n for n in nodes if n != ("text", "")]
        if node[0] == "element":
            nodes[index] = (*node[:3], tuple(edit(list(node[3]), index, trim)))
        return nodes

    children = edit(children, 0, lambda text: text.removeprefix("\n"))
    return edit(children, -1, lambda text: text.removesuffix("\n"))


def canonical(
    nodes: list[Node], ignored_classes: frozenset[str] = frozenset()
) -> Canonical:
    """A comparable form that is equal when two trees display the same."""
    return tuple(
        _canonical_children(trim_block_whitespace(nodes), ignored_classes, False)
    )
