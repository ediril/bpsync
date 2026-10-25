"""The post Markdown dialect, rendered to HTML trees and converted back.

The dialect is CommonMark with pipe tables, Pandoc-style attributes
(`[text]{.class}`, `{key=value}` after links and images, `{.class}` before a
block) and fenced divs (`::: {.class}`). The converter is the inverse of the
renderer: it writes only constructs the renderer reads back to the same tree,
and raises `Unconvertible` for anything else.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.attrs import attrs_block_plugin, attrs_plugin
from mdit_py_plugins.attrs.parse import parse as parse_attrs
from mdit_py_plugins.container import container_plugin

from wpsync.markup.dom import (
    BLOCK_TAGS,
    VOID_TAGS,
    Comment,
    Element,
    Node,
    parse_html,
    serialize,
    start_tag,
)


class Unconvertible(Exception):
    """An element with no Markdown form that renders back identically."""


def _render_div(self, tokens, index, options, env) -> str:  # noqa: ANN001
    token = tokens[index]
    if token.nesting < 0:
        return "</div>\n"
    info = token.info.strip()
    attrs = parse_attrs(info)[1] if info.startswith("{") else {}
    return start_tag(Element("div", dict(attrs))) + "\n"


def _parser() -> MarkdownIt:
    parser = (
        MarkdownIt("commonmark", {"html": True})
        .enable("table")
        .use(attrs_plugin, spans=True)
        .use(attrs_block_plugin)
        .use(container_plugin, name="div", validate=lambda *_: True, render=_render_div)
    )
    parser.normalizeLink = lambda url: url  # type: ignore[method-assign]
    parser.normalizeLinkText = lambda text: text  # type: ignore[method-assign]
    parser.add_render_rule("softbreak", lambda *_: " ")
    return parser


PARSER = _parser()


TokenTransform = Callable[[list[Token]], list[Token]]


def render(markdown: str, transform: TokenTransform | None = None) -> list[Node]:
    """Render Markdown, letting a platform rewrite the parsed tokens first."""
    tokens = PARSER.parse(markdown)
    if transform is not None:
        tokens = transform(tokens)
    return parse_html(PARSER.renderer.render(tokens, PARSER.options, {}))


def render_inline(token: Token) -> list[Node]:
    return parse_html(PARSER.renderer.render([token], PARSER.options, {}))


# Converting HTML trees to Markdown -------------------------------------------

ESCAPED = re.compile(r"([\\`*{}<]|\](?=[(\[{:]))")
LOOSE_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")
ENTITY_LIKE = re.compile(r"&(?=#?[A-Za-z0-9]+;)")
LINE_START = re.compile(r"^(?:([#>+=|-])|(\d+)([.)]))", re.M)
TYPE_ONE_TAGS = frozenset({"pre", "script", "style", "textarea"})
TYPE_SIX_TAGS = BLOCK_TAGS - {
    "audio",
    "canvas",
    "embed",
    "object",
    "picture",
    "svg",
    "video",
}


def _escape(text: str) -> str:
    text = ESCAPED.sub(r"\\\1", text)
    text = LOOSE_UNDERSCORE.sub(r"\\_", text)
    return ENTITY_LIKE.sub(r"\\&", text)


def _escape_line_starts(markdown: str) -> str:
    def escape(match: re.Match[str]) -> str:
        return "\\" + match[1] if match[1] else f"{match[2]}\\{match[3]}"

    return LINE_START.sub(escape, markdown)


def _attribute_list(attrs: dict[str, str]) -> str:
    parts = []
    for name, value in attrs.items():
        if name == "class":
            parts.extend(f".{cls}" for cls in value.split())
        elif name == "id" and re.fullmatch(r"[A-Za-z][\w-]*", value):
            parts.append(f"#{value}")
        elif re.fullmatch(r"[\w-]+", value):
            parts.append(f"{name}={value}")
        else:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'{name}="{escaped}"')
    return "{" + " ".join(parts) + "}"


def _attributes(attrs: dict[str, str]) -> str:
    return _attribute_list(attrs) if attrs else ""


class Converter:
    """Converts HTML trees to the dialect, dropping the given bookkeeping classes."""

    def __init__(self, ignored_classes: frozenset[str] = frozenset()) -> None:
        self.ignored_classes = ignored_classes
        self.in_link = False

    def attrs(self, element: Element) -> dict[str, str]:
        attrs = dict(element.attrs)
        if "class" in attrs:
            classes = [
                cls for cls in attrs["class"].split() if cls not in self.ignored_classes
            ]
            if classes:
                attrs["class"] = " ".join(classes)
            else:
                del attrs["class"]
        return attrs

    # Inline content ------------------------------------------------------

    def inline(self, nodes: Sequence[Node]) -> str:
        return "".join(self._inline_node(node) for node in nodes)

    def _inline_node(self, node: Node) -> str:
        if isinstance(node, str):
            return _escape(re.sub(r"[ \t\n\r\f]+", " ", node))
        if isinstance(node, Comment):
            return f"<!--{node.text}-->"
        attrs = self.attrs(node)
        match node.tag:
            case "strong" | "b" | "em" | "i" if not attrs:
                marker = "**" if node.tag in ("strong", "b") else "*"
                inner = self.inline(node.children)
                stripped = inner.strip(" ")
                if not stripped:
                    return inner
                lead = inner[: len(inner) - len(inner.lstrip(" "))]
                trail = inner[len(inner.rstrip(" ")) :]
                return f"{lead}{marker}{stripped}{marker}{trail}"
            case "code" if not attrs and all(isinstance(c, str) for c in node.children):
                return _code_span("".join(node.children))  # type: ignore[arg-type]
            case "a" if "href" in attrs:
                href = attrs.pop("href")
                title = attrs.pop("title", None)
                # Bracketed spans cannot nest inside link text.
                self.in_link = True
                try:
                    text = self.inline(node.children)
                finally:
                    self.in_link = False
                return f"[{text}]({_destination(href, title)})" + _attributes(attrs)
            case "img" if "src" in attrs:
                src = attrs.pop("src")
                alt = attrs.pop("alt", "")
                title = attrs.pop("title", None)
                return f"![{_escape(alt)}]({_destination(src, title)})" + _attributes(
                    attrs
                )
            case "br" if not attrs:
                return "\\\n"
            case "span" if not attrs:
                return self.inline(node.children)
            case "span" if not self.in_link:
                return f"[{self.inline(node.children)}]{_attribute_list(attrs)}"
        return self.raw_inline(node)

    def raw_inline(self, element: Element) -> str:
        tag = start_tag(element)
        if element.tag in VOID_TAGS:
            return tag
        return f"{tag}{self.inline(element.children)}</{element.tag}>"

    # Blocks --------------------------------------------------------------

    def block(self, node: Node) -> str:
        if isinstance(node, str) or isinstance(node, Comment):
            raise Unconvertible("text outside a block")
        attrs = self.attrs(node)
        tag = node.tag
        if tag == "p":
            body = _escape_line_starts(self.inline(node.children)).strip(" ")
            if not body:
                raise Unconvertible("empty paragraph")
            return _with_block_attrs(attrs, body)
        if re.fullmatch(r"h[1-6]", tag):
            body = _escape_line_starts(self.inline(node.children)).strip(" ")
            if "\n" in body:
                raise Unconvertible("line break in heading")
            if body.endswith("#"):
                body = body[:-1] + "\\#"
            return _with_block_attrs(attrs, f"{'#' * int(tag[1])} {body}".rstrip())
        if tag in ("ul", "ol"):
            return self.list(node, attrs)
        if tag == "blockquote":
            inner = self.blocks(node.children)
            quoted = "\n".join(
                f"> {line}" if line else ">" for line in inner.split("\n")
            )
            return _with_block_attrs(attrs, quoted)
        if tag == "pre":
            return self.code_block(node, attrs)
        if tag == "hr":
            return _with_block_attrs(attrs, "---")
        if tag == "table":
            return _with_block_attrs(attrs, self.table(node))
        if tag == "div":
            inner = self.blocks(node.children)
            fence = ":" * (3 + _div_depth(node.children))
            opening = f"{fence} {_attribute_list(attrs)}" if attrs else fence
            return f"{opening}\n{inner}\n{fence}"
        raise Unconvertible(f"<{tag}>")

    def blocks(self, nodes: Sequence[Node]) -> str:
        children = [
            node for node in nodes if not (isinstance(node, str) and not node.strip())
        ]
        if not children:
            raise Unconvertible("empty container")
        return "\n\n".join(self.block_or_raw(child) for child in children)

    def block_or_raw(self, node: Node) -> str:
        try:
            return self.block(node)
        except Unconvertible:
            return raw_block(node)

    def list(self, element: Element, attrs: dict[str, str]) -> str:
        start = 1
        if element.tag == "ol" and "start" in attrs:
            if not attrs["start"].isdigit():
                raise Unconvertible("list start")
            start = int(attrs.pop("start"))
        items = [
            child
            for child in element.children
            if not (isinstance(child, str) and not child.strip())
        ]
        if not items or any(
            not isinstance(item, Element) or item.tag != "li" for item in items
        ):
            raise Unconvertible("list content")
        loose = any(
            isinstance(child, Element) and child.tag == "p"
            for item in items
            for child in item.children  # type: ignore[union-attr]
        )
        lines = []
        for offset, item in enumerate(items):
            assert isinstance(item, Element)
            if self.attrs(item):
                raise Unconvertible("list item attributes")
            marker = f"{start + offset}. " if element.tag == "ol" else "- "
            body = self.loose_item(item) if loose else self.tight_item(item)
            first, *rest = body.split("\n")
            indent = " " * len(marker)
            lines.append((marker + first).rstrip())
            lines.extend(indent + line if line else "" for line in rest)
            if loose and offset < len(items) - 1:
                lines.append("")
        return _with_block_attrs(attrs, "\n".join(lines))

    def tight_item(self, item: Element) -> str:
        children = list(item.children)
        nested = []
        while children and (
            (isinstance(children[-1], Element) and children[-1].tag in ("ul", "ol"))
            or (isinstance(children[-1], str) and not children[-1].strip())
        ):
            node = children.pop()
            if isinstance(node, Element):
                nested.insert(0, node)
        if any(
            isinstance(child, Element) and child.tag in BLOCK_TAGS for child in children
        ):
            raise Unconvertible("block inside a tight list item")
        text = _escape_line_starts(self.inline(children)).strip(" ")
        parts = [text] + [self.block(child) for child in nested]
        return "\n".join(parts)

    def loose_item(self, item: Element) -> str:
        return self.blocks(item.children)

    def code_block(self, pre: Element, attrs: dict[str, str]) -> str:
        children = [child for child in pre.children]
        if attrs or len(children) != 1 or not isinstance(children[0], Element):
            raise Unconvertible("preformatted text")
        code = children[0]
        code_attrs = self.attrs(code)
        language = ""
        if code_attrs:
            match = re.fullmatch(r"language-(\S+)", code_attrs.get("class", ""))
            if len(code_attrs) != 1 or not match:
                raise Unconvertible("code attributes")
            language = match[1]
        if code.tag != "code" or not all(isinstance(c, str) for c in code.children):
            raise Unconvertible("preformatted markup")
        text = "".join(code.children).removesuffix("\n")  # type: ignore[arg-type]
        longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
        fence = "`" * max(3, longest + 1)
        return f"{fence}{language}\n{text}\n{fence}"

    def table(self, table: Element) -> str:
        sections = [c for c in table.children if isinstance(c, Element)]
        if [s.tag for s in sections] not in (["thead", "tbody"], ["thead"]):
            raise Unconvertible("table layout")
        rows = [
            [cell for cell in row.children if isinstance(cell, Element)]
            for section in sections
            for row in section.children
            if isinstance(row, Element)
        ]
        header, body = rows[0], rows[1:]
        width = len(header)
        if any(len(row) != width for row in body):
            raise Unconvertible("ragged table")
        if any(cell.tag != "th" for cell in header) or any(
            cell.tag != "td" for row in body for cell in row
        ):
            raise Unconvertible("table cells")
        alignments = [self.cell_alignment(cell) for cell in header]
        if any(
            self.cell_alignment(cell) != alignments[i]
            for row in body
            for i, cell in enumerate(row)
        ):
            raise Unconvertible("mixed column alignment")
        delimiter = {"": "---", "left": ":---", "center": ":---:", "right": "---:"}
        lines = [
            self.table_row(header),
            "| " + " | ".join(delimiter[a] for a in alignments) + " |",
        ]
        lines.extend(self.table_row(row) for row in body)
        return "\n".join(lines)

    def cell_alignment(self, cell: Element) -> str:
        attrs = self.attrs(cell)
        style = attrs.pop("style", "")
        if attrs:
            raise Unconvertible("table cell attributes")
        if not style:
            return ""
        match = re.fullmatch(r"text-align:\s*(left|center|right)", style)
        if not match:
            raise Unconvertible("table cell style")
        return match[1]

    def table_row(self, cells: list[Element]) -> str:
        texts = []
        for cell in cells:
            if any(
                isinstance(c, Element) and c.tag in BLOCK_TAGS for c in cell.children
            ):
                raise Unconvertible("block inside a table cell")
            text = self.inline(cell.children).strip(" ")
            if "\n" in text:
                raise Unconvertible("line break in a table cell")
            texts.append(text.replace("|", "\\|"))
        return "| " + " | ".join(texts) + " |"


def raw_block(node: Node) -> str:
    """Markdown that carries a node through unchanged as an HTML block.

    Bare text cannot start an HTML block, so it is prefixed with an empty
    comment, which starts a block that ends on that line.
    """
    if isinstance(node, Comment):
        return f"<!--{node.text.replace(chr(10), ' ')}-->"
    html = serialize([node]).replace("\n", "&#10;")
    if not isinstance(node, Element):
        return f"<!---->{html}"
    if node.tag in TYPE_ONE_TAGS | TYPE_SIX_TAGS or node.tag in VOID_TAGS:
        return html
    # A line holding only an opening tag starts an HTML block that runs to the
    # next blank line; the newline after it is not displayed.
    opening = start_tag(node)
    return f"{opening}\n{html[len(opening) :]}"


def _with_block_attrs(attrs: dict[str, str], body: str) -> str:
    return f"{_attribute_list(attrs)}\n{body}" if attrs else body


def _div_depth(nodes: Sequence[Node]) -> int:
    depths = [
        1 + _div_depth(node.children)
        for node in nodes
        if isinstance(node, Element) and node.tag == "div"
    ]
    nested = [
        _div_depth(node.children)
        for node in nodes
        if isinstance(node, Element) and node.tag != "div"
    ]
    return max(depths + nested + [0])


def _code_span(text: str) -> str:
    if "\n" in text:
        raise Unconvertible("line break in inline code")
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    if text.startswith(("`", " ")) or text.endswith(("`", " ")):
        text = f" {text} "
    return f"{fence}{text}{fence}"


def _destination(url: str, title: str | None) -> str:
    if re.search(r"[\s()<>\\]", url) or not url:
        url = "<" + re.sub(r"([<>\\])", r"\\\1", url) + ">"
    if title is None:
        return url
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    return f'{url} "{escaped}"'
