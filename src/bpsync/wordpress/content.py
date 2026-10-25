"""Post content: WordPress HTML to the post Markdown dialect and back."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from markdown_it.token import Token

from bpsync.markup.dom import (
    Comment,
    Element,
    Node,
    canonical,
    parse_html,
    to_html,
    trim_block_whitespace,
)
from bpsync.markup.markdown import (
    Converter,
    Unconvertible,
    raw_block,
    render,
    render_inline,
)
from bpsync.wordpress.autop import autop

EDITOR_CLASSES = frozenset(
    {
        "wp-block-heading",
        "wp-block-list",
        "wp-block-quote",
        "wp-block-code",
        "wp-block-separator",
        "has-alpha-channel-opacity",
        "wp-block-paragraph",
    }
)
"""Classes the block editor adds to unstyled elements."""

STATIC_BLOCKS = frozenset(
    "core/" + name
    for name in """paragraph heading list list-item quote code preformatted separator
    image gallery table html columns column group spacer pullquote verse buttons
    button details freeform more nextpage media-text cover audio video file""".split()
)
"""Blocks whose stored HTML is what WordPress displays."""

DELIMITER = re.compile(
    r"<!--\s+(?P<closer>/)?wp:(?P<namespace>[a-z][a-z0-9_-]*/)?"
    r"(?P<name>[a-z][a-z0-9_-]*)\s+(?P<attrs>\{.*?\}\s+)?(?P<void>/)?-->",
    re.DOTALL,
)
WP_IMAGE_CLASS = re.compile(r"wp-image-(\d+)")
SIZE_CLASS = re.compile(r"size-([\w-]+)")


@dataclass(frozen=True)
class MediaImage:
    id: str
    url: str
    size: str


class Media(Protocol):
    """The media table: how Markdown image sources map to library images."""

    def remember(self, url: str, media_id: str, size: str) -> str:
        """Record a library image found on pull; return its Markdown source."""
        ...

    def lookup(self, src: str) -> MediaImage | None:
        """The library image a Markdown source refers to, if any."""
        ...


@dataclass(frozen=True)
class Conversion:
    markdown: str
    kept: tuple[str, ...]
    """Descriptions of elements kept as HTML."""


def is_block_content(raw: str) -> bool:
    return "<!-- wp:" in raw


# Push ----------------------------------------------------------------------


def render_html(markdown: str, media: Media) -> str:
    return to_html(_render(markdown, media))


def _render(markdown: str, media: Media) -> list[Node]:
    return render(markdown, lambda tokens: _present(tokens, media))


def _present(tokens: list[Token], media: Media) -> list[Token]:
    """Use WordPress's presentation for Markdown images and tables.

    Only tokens from Markdown syntax change; HTML written in the Markdown passes
    through as it is.
    """
    presented: list[Token] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        window = tokens[index : index + 3]
        if [t.type for t in window] == ["paragraph_open", "inline", "paragraph_close"]:
            children = [
                c
                for c in window[1].children or []
                if not (c.type == "text" and not c.content.strip())
            ]
            if len(children) == 1 and children[0].type == "image":
                image = render_inline(children[0])[0]
                assert isinstance(image, Element)
                presented.append(_html_token(to_html([_image_figure(image, media)])))
                index += 3
                continue
        if token.type == "table_open":
            presented.append(_html_token('<figure class="wp-block-table">'))
        presented.append(token)
        if token.type == "table_close":
            presented.append(_html_token("</figure>"))
        index += 1
    return presented


def _html_token(html: str) -> Token:
    token = Token("html_block", "", 0)
    token.content = html + "\n"
    return token


def _image_figure(image: Element, media: Media) -> Element:
    attrs = dict(image.attrs)
    title = attrs.pop("title", None)
    figure_classes = ["wp-block-image"]
    library = media.lookup(attrs["src"])
    if library is not None:
        attrs["src"] = library.url
        figure_classes.append(f"size-{library.size}")
    figure_classes.extend(attrs.pop("class", "").split())
    if library is not None:
        attrs["class"] = f"wp-image-{library.id}"
    children: list[Node] = [Element("img", attrs)]
    if title:
        children.append(Element("figcaption", {"class": "wp-element-caption"}, [title]))
    return Element("figure", {"class": " ".join(figure_classes)}, children)


# Pull ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Original:
    nodes: list[Node]
    label: str


def to_markdown(raw: str, media: Media) -> Conversion:
    originals = (
        _block_originals(raw) if is_block_content(raw) else _classic_originals(raw)
    )
    converter = Converter(EDITOR_CLASSES)
    fragments = [_convert(original, converter, media) for original in originals]
    kept = {index for index, fragment in enumerate(fragments) if fragment is None}
    for index in kept:
        fragments[index] = _raw(originals[index])
    _separate_adjacent_lists(fragments)  # type: ignore[arg-type]
    expected = [_comparable(original.nodes) for original in originals]
    while True:
        rendered = _comparable(_render("\n\n".join(fragments), media))  # type: ignore[arg-type]
        index = _first_difference(rendered, expected)
        if index is None:
            break
        if index in kept:
            raise AssertionError(f"kept HTML for {originals[index].label} changed")
        kept.add(index)
        fragments[index] = _raw(originals[index])
    labels = tuple(
        originals[index].label
        for index in sorted(kept)
        if not all(_plain_comment(node) for node in originals[index].nodes)
    )
    return Conversion("\n\n".join(fragments), labels)  # type: ignore[arg-type]


def _plain_comment(node: Node) -> bool:
    """A comment such as <!--more-->, whose Markdown form is the comment itself."""
    return isinstance(node, Comment) and not node.text.lstrip().startswith("wp:")


def _raw(original: _Original) -> str:
    return "\n\n".join(raw_block(node) for node in original.nodes)


def _first_difference(rendered: tuple, expected: list[tuple]) -> int | None:
    """The index of the first original whose nodes the rendering does not match."""
    position = 0
    for index, nodes in enumerate(expected):
        if rendered[position : position + len(nodes)] != nodes:
            return index
        position += len(nodes)
    return None if position == len(rendered) else len(expected) - 1


def _convert(original: _Original, converter: Converter, media: Media) -> str | None:
    try:
        nodes = trim_block_whitespace(original.nodes)
        parts = [converter.block(_for_conversion(node, media)) for node in nodes]
    except Unconvertible:
        return None
    fragment = "\n\n".join(parts)
    return fragment if _displays_same(fragment, original.nodes, media) else None


def _for_conversion(node: Node, media: Media) -> Node:
    """Rewrite WordPress presentation markup into the form the converter reads."""
    if not isinstance(node, Element):
        return node
    classes = node.attrs.get("class", "").split()
    if node.tag == "figure" and "wp-block-table" in classes:
        tables = [c for c in node.children if isinstance(c, Element)]
        if len(classes) == 1 and len(tables) == 1 and tables[0].tag == "table":
            return tables[0]
    if node.tag == "figure" and "wp-block-image" in classes:
        image = _figure_image(node, classes, media)
        if image is not None:
            return Element("p", {}, [image])
    return Element(
        node.tag, node.attrs, [_for_conversion(c, media) for c in node.children]
    )


def _figure_image(figure: Element, classes: list[str], media: Media) -> Element | None:
    if set(figure.attrs) != {"class"}:
        return None
    children = [
        c for c in figure.children if not (isinstance(c, str) and not c.strip())
    ]
    if not children or not isinstance(children[0], Element) or children[0].tag != "img":
        return None
    attrs = dict(children[0].attrs)
    if len(children) == 2:
        caption = children[1]
        if (
            not isinstance(caption, Element)
            or caption.tag != "figcaption"
            or not all(isinstance(c, str) for c in caption.children)
        ):
            return None
        attrs["title"] = "".join(caption.children).strip()  # type: ignore[arg-type]
    elif len(children) != 1:
        return None
    image_classes = attrs.pop("class", "").split()
    sizes = [match[1] for cls in classes if (match := SIZE_CLASS.fullmatch(cls))]
    ids = [
        match[1] for cls in image_classes if (match := WP_IMAGE_CLASS.fullmatch(cls))
    ]
    if (
        len(image_classes) != len(ids)
        or len(ids) > 1
        or len(sizes) > 1
        or len(ids) != len(sizes)
    ):
        return None
    if ids:
        attrs["src"] = media.remember(attrs["src"], ids[0], sizes[0])
    other = [
        cls
        for cls in classes
        if cls != "wp-block-image" and not SIZE_CLASS.fullmatch(cls)
    ]
    if other:
        attrs["class"] = " ".join(other)
    return Element("img", attrs)


def _displays_same(markdown: str, original: list[Node], media: Media) -> bool:
    return _comparable(_render(markdown, media)) == _comparable(original)


def _comparable(nodes: list[Node]) -> tuple:
    return canonical(nodes, EDITOR_CLASSES)


def _separate_adjacent_lists(fragments: list[str]) -> None:
    """Adjacent Markdown lists merge unless their markers differ."""
    for index in range(1, len(fragments)):
        previous, current = fragments[index - 1], fragments[index]
        if previous.startswith("- ") and current.startswith("- "):
            fragments[index] = re.sub(r"^- ", "* ", current, flags=re.M)
        elif re.match(r"\d+\. ", previous) and re.match(r"\d+\. ", current):
            fragments[index] = re.sub(r"^(\d+)\. ", r"\1) ", current, flags=re.M)


def _classic_originals(raw: str) -> list[_Original]:
    nodes = parse_html(autop(raw))
    return [_Original([node], _label(node)) for node in nodes if not _blank(node)]


def _blank(node: Node) -> bool:
    return isinstance(node, str) and not node.strip()


def _label(node: Node) -> str:
    if isinstance(node, Element):
        return f"<{node.tag}>"
    return "comment" if isinstance(node, Comment) else "text"


@dataclass
class _Block:
    name: str
    attrs: dict
    start: int
    inner_start: int
    names: set[str]


def _block_originals(raw: str) -> list[_Original]:
    """Split block content into what each top-level block displays."""
    originals: list[_Original] = []
    stack: list[_Block] = []
    cursor = 0

    def freeform(text: str) -> None:
        for node in parse_html(text):
            if not _blank(node):
                if isinstance(node, str):
                    node = Element("p", {}, [node.strip()])
                originals.append(_Original([node], _label(node)))

    for match in DELIMITER.finditer(raw):
        name = (match["namespace"] or "core/") + match["name"]
        if match["closer"]:
            if not stack or stack[-1].name != name:
                return [_Original(parse_html(raw), "malformed block markup")]
            block = stack.pop()
            if stack:
                stack[-1].names |= block.names
                continue
            originals.extend(
                _top_level(
                    raw[block.start : match.end()],
                    block,
                    raw[block.inner_start : match.start()],
                )
            )
            cursor = match.end()
            continue
        try:
            attrs = json.loads(match["attrs"]) if match["attrs"] else {}
        except json.JSONDecodeError:
            return [_Original(parse_html(raw), "malformed block markup")]
        if not stack:
            freeform(raw[cursor : match.start()])
        if match["void"]:
            if stack:
                stack[-1].names.add(name)
            else:
                originals.append(_Original([Comment(match.group(0)[4:-3])], name))
                cursor = match.end()
            continue
        stack.append(_Block(name, attrs, match.start(), match.end(), {name}))
    if stack:
        return [_Original(parse_html(raw), "malformed block markup")]
    freeform(raw[cursor:])
    return originals


def _top_level(markup: str, block: _Block, inner: str) -> list[_Original]:
    if block.name == "core/embed" or block.name.startswith("core-embed/"):
        url = block.attrs.get("url")
        figures = [n for n in parse_html(inner) if isinstance(n, Element)]
        has_caption = any(
            isinstance(c, Element) and c.tag == "figcaption"
            for figure in figures
            for c in figure.children
        )
        if isinstance(url, str) and not has_caption:
            return [_Original([Element("p", {}, [url])], block.name)]
    if block.name == "core/shortcode":
        return [
            _Original([n], block.name)
            for n in parse_html(autop(inner))
            if not _blank(n)
        ]
    if block.names <= STATIC_BLOCKS:
        stripped = DELIMITER.sub("", inner)
        return [
            _Original([n], block.name) for n in parse_html(stripped) if not _blank(n)
        ]
    return [_Original([n for n in parse_html(markup) if not _blank(n)], block.name)]
