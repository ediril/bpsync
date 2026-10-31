"""Post content: WordPress HTML to the post Markdown dialect and back.

Conversion is checked against a model of what WordPress displays. Content
with block markup is displayed block by block; content without it goes
through WordPress's `wpautop` filter. The stored post and the post a push
would send are both put through that model, and any part of the post whose
Markdown would not display the same is kept as its exact original source.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass

from markdown_it.token import Token

from wpsync.markup.dom import (
    HTML_SPACE,
    Comment,
    Element,
    Node,
    canonical,
    parse_html,
    to_html,
    trim_block_whitespace,
)
from wpsync.markup.markdown import (
    Converter,
    Unconvertible,
    join_blocks,
    kept_markdown,
    pieces,
    render_inline,
    render_tokens,
)
from wpsync.media import Media
from wpsync.posts import Conversion, UnrepresentableContent
from wpsync.wordpress.autop import BLOCK_NAMES, autop

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

EDITOR_LINK_ATTRS = frozenset({"data-type", "data-id"})
"""Attributes the editor adds to links for its own use; browsers ignore them."""

UPLOADS_PATH = "/wp-content/uploads/"

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
PLACEMENT_CLASS = re.compile(r"align(?:left|right|center|wide|full|none)")
CAPTION_CLASS = "wp-element-caption"
RESIZED_CLASS = "is-resized"
"""The class WordPress puts on the figure of an image given its own width."""
EMBED_ATTRS = frozenset({"url", "type", "providerNameSlug", "responsive", "className"})
EMBED_CLASS = re.compile(
    r"wp-block-embed(?:-[\w-]+)?|is-type-[\w-]+|is-provider-[\w-]+"
    r"|wp-embed-aspect-[\w-]+|wp-has-aspect-ratio"
)
EMBED_URL = re.compile(r"https?://[^\s<>\"]+")
CLASSIC_MARKUP = re.compile(
    r"<!--.*?-->|<(script|style|pre|textarea)\b.*?</\1\s*>"
    r"|<(/?)([a-zA-Z][\w:-]*)\b[^>]*?(/?)>|(\n[ \t]*\n)",
    re.DOTALL | re.IGNORECASE,
)
VOID_NAMES = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)


def is_block_content(raw: str) -> bool:
    return "<!-- wp:" in raw


# Push ----------------------------------------------------------------------


def render_html(markdown: str, media: Media) -> str:
    """The HTML a push sends; raw HTML from the Markdown is sent exactly."""
    html = []
    for piece in pieces(markdown):
        if piece.raw is not None:
            html.append(piece.raw)
        else:
            html.append(to_html(render_tokens(_present(piece.tokens, media))))
    return "\n\n".join(html)


def _present(tokens: list[Token], media: Media) -> list[Token]:
    """Use WordPress's presentation for Markdown images and tables."""
    presented: list[Token] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        window = tokens[index : index + 3]
        if [t.type for t in window] == ["paragraph_open", "inline", "paragraph_close"]:
            children = [
                c
                for c in window[1].children or []
                if not (c.type == "text" and not c.content.strip(HTML_SPACE))
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
    """WordPress's image figure: placement on the figure, the rest on the image."""
    attrs = dict(image.attrs)
    title = attrs.pop("title", None)
    classes = attrs.pop("class", "").split()
    figure_classes = ["wp-block-image"]
    image_classes = [c for c in classes if not PLACEMENT_CLASS.fullmatch(c)]
    library = media.lookup(attrs["src"])
    if library is not None:
        attrs["src"] = library.url
        figure_classes.append(f"size-{library.size}")
        image_classes.append(f"wp-image-{library.id}")
    figure_classes.extend(c for c in classes if PLACEMENT_CLASS.fullmatch(c))
    if "width" in attrs or "width" in attrs.get("style", ""):
        figure_classes.append(RESIZED_CLASS)
    if image_classes:
        attrs["class"] = " ".join(image_classes)
    children: list[Node] = [Element("img", attrs)]
    if title:
        children.append(Element("figcaption", {"class": CAPTION_CLASS}, [title]))
    return Element("figure", {"class": " ".join(figure_classes)}, children)


# What WordPress displays ---------------------------------------------------


@dataclass(frozen=True)
class _Unit:
    """A part of the stored content that converts, or is kept, as a whole."""

    source: str
    """The exact original text."""
    nodes: list[Node]
    """What WordPress displays for it."""
    label: str
    convertible: bool
    separator: str = ""
    """The whitespace before it in the original."""


def display(content: str) -> list[Node]:
    """What WordPress displays for stored or pushed post content."""
    if not is_block_content(content):
        return parse_html(autop(content))
    nodes: list[Node] = []
    for unit in _block_units(content):
        if unit.separator and nodes:
            nodes.append(" ")
        nodes.extend(unit.nodes)
    return nodes


def same_display(stored: str, pushed: str) -> bool:
    """Whether WordPress displays two post contents the same."""
    return _comparable(display(stored)) == _comparable(display(pushed))


def _comparable(nodes: list[Node]) -> tuple:
    return canonical(_canonical_media(nodes), EDITOR_CLASSES)


def _displays_same(first: list[Node], second: list[Node]) -> bool:
    return _comparable(first) == _comparable(second)


def _blank(node: Node) -> bool:
    return isinstance(node, str) and not node.strip(HTML_SPACE)


def _block_units(raw: str) -> list[_Unit]:
    try:
        return list(_scan_blocks(raw))
    except ValueError:
        return [_Unit(raw, parse_html(raw), "malformed block markup", False)]


def _scan_blocks(raw: str) -> Iterator[_Unit]:
    depth = 0
    start = cursor = 0
    name = ""
    attrs: dict = {}
    names: set[str] = set()
    inner_start = 0
    for match in DELIMITER.finditer(raw):
        block = (match["namespace"] or "core/") + match["name"]
        if match["closer"]:
            depth -= 1
            if depth < 0:
                raise ValueError(f"unexpected closing delimiter for {block}")
            if depth == 0:
                if block != name:
                    raise ValueError(f"{block} closes {name}")
                yield from _freeform(raw[cursor:start])
                yield _block_unit(
                    raw[start : match.end()],
                    name,
                    attrs,
                    names,
                    raw[inner_start : match.start()],
                    raw[cursor:start],
                )
                cursor = match.end()
            continue
        if depth == 0:
            name, start, inner_start, names = block, match.start(), match.end(), set()
            try:
                attrs = json.loads(match["attrs"]) if match["attrs"] else {}
            except json.JSONDecodeError as error:
                raise ValueError("invalid block attributes") from error
        names.add(block)
        if match["void"]:
            if depth == 0:
                yield from _freeform(raw[cursor:start])
                yield _Unit(match.group(0), parse_html(match.group(0)), block, False)
                cursor = match.end()
            continue
        depth += 1
    if depth:
        raise ValueError(f"unclosed block {name}")
    yield from _freeform(raw[cursor:])


def _freeform(text: str) -> Iterator[_Unit]:
    source = text.strip(HTML_SPACE)
    if source:
        separator = text[: len(text) - len(text.lstrip(HTML_SPACE))]
        yield _Unit(source, parse_html(source), "classic content", True, separator)


def _block_unit(
    markup: str, name: str, attrs: dict, names: set[str], inner: str, before: str
) -> _Unit:
    separator = before[len(before.rstrip(HTML_SPACE)) :]
    if name == "core/embed" or name.startswith("core-embed/"):
        url = _plain_embed_url(attrs, inner)
        if url is not None:
            embed = Element("p", {"data-wpsync-embed": url})
            return _Unit(markup, [embed], name, True, separator)
    if name == "core/shortcode":
        return _Unit(markup, parse_html(autop(inner)), name, True, separator)
    if names <= STATIC_BLOCKS:
        nodes = parse_html(DELIMITER.sub("", inner))
        return _Unit(markup, nodes, name, True, separator)
    return _Unit(markup, parse_html(markup), name, False, separator)


def _plain_embed_url(attrs: dict, inner: str) -> str | None:
    """The URL of an embed WordPress displays from its address alone."""
    url = attrs.get("url")
    classes = attrs.get("className", "").split()
    if (
        not isinstance(url, str)
        or set(attrs) - EMBED_ATTRS
        or not all(EMBED_CLASS.fullmatch(c) for c in classes)
    ):
        return None
    figures = [n for n in parse_html(inner) if not _blank(n)]
    if len(figures) != 1 or not isinstance(figures[0], Element):
        return None
    figure = figures[0]
    if figure.tag != "figure" or set(figure.attrs) != {"class"}:
        return None
    if not all(EMBED_CLASS.fullmatch(c) for c in figure.attrs["class"].split()):
        return None
    wrappers = [n for n in figure.children if not _blank(n)]
    if len(wrappers) != 1 or not isinstance(wrappers[0], Element):
        return None
    text = wrappers[0].children
    if len(text) != 1 or not isinstance(text[0], str) or text[0].strip() != url:
        return None
    return url


def _classic_units(raw: str) -> list[_Unit]:
    """Split classic content where `wpautop` starts a new paragraph or block.

    Boundaries are blank lines and the edges of block elements, counted only
    outside every other element.
    """
    cuts = [0]
    depth = 0
    for match in CLASSIC_MARKUP.finditer(raw):
        if match[5] is not None:
            if depth == 0:
                cuts.append(match.start())
            continue
        name = (match[1] or match[3] or "").lower()
        block = name in BLOCK_NAMES
        if match[1] or (match[3] and not match[2] and not match[4]):
            if depth == 0 and block:
                cuts.append(match.start())
            if match[3] and name not in VOID_NAMES:
                depth += 1
        if match[1] or (match[3] and match[2]):
            if match[3]:
                depth = max(0, depth - 1)
            if depth == 0 and block:
                cuts.append(match.end())
    cuts.append(len(raw))
    chunks = (raw[start:end] for start, end in zip(cuts, cuts[1:]))
    units = []
    for chunk in chunks:
        source = chunk.strip(HTML_SPACE)
        if source:
            nodes = parse_html(autop(source))
            units.append(_Unit(source, nodes, _classic_label(nodes), True))
    return units


def _classic_label(nodes: list[Node]) -> str:
    elements = [n for n in nodes if isinstance(n, Element)]
    if len(elements) == 1 and elements[0].tag == "p":
        elements = [
            c for c in elements[0].children if isinstance(c, Element)
        ] or elements
    return f"<{elements[0].tag}>" if elements else "classic text"


# Comparable forms of WordPress presentation --------------------------------


@dataclass(frozen=True)
class _Image:
    """An image as either editor presents it."""

    src: str
    alt: str | None
    caption: str | None
    media_id: str | None
    size: str | None
    placement: tuple[str, ...]
    """Alignment classes, which may sit on the image or its figure."""
    figure_classes: tuple[str, ...]
    image_classes: tuple[str, ...]
    attrs: tuple[tuple[str, str], ...]


def _parse_image(node: Node) -> _Image | None:
    """Read a block-editor image figure or a classic paragraph holding one image."""
    if not isinstance(node, Element):
        return None
    children = [c for c in node.children if not _blank(c)]
    caption = None
    figure_classes: list[str] = []
    if node.tag == "figure" and "wp-block-image" in node.attrs.get("class", "").split():
        if set(node.attrs) != {"class"} or not children:
            return None
        if len(children) == 2:
            caption = _caption_text(children[1])
            if caption is None:
                return None
        elif len(children) != 1:
            return None
        figure_classes = [
            c for c in node.attrs["class"].split() if c != "wp-block-image"
        ]
    elif not (node.tag == "p" and not node.attrs and len(children) == 1):
        return None
    image = children[0]
    if not isinstance(image, Element) or image.tag != "img" or "src" not in image.attrs:
        return None
    attrs = dict(image.attrs)
    src, alt = attrs.pop("src"), attrs.pop("alt", None)
    image_classes = attrs.pop("class", "").split()
    pooled = figure_classes + image_classes
    ids = [m[1] for c in image_classes if (m := WP_IMAGE_CLASS.fullmatch(c))]
    sizes = [m[1] for c in pooled if (m := SIZE_CLASS.fullmatch(c))]
    if len(ids) > 1 or len(sizes) > 1 or len(ids) != len(sizes):
        return None

    def own(classes: list[str]) -> tuple[str, ...]:
        return tuple(
            c
            for c in classes
            if not (
                WP_IMAGE_CLASS.fullmatch(c)
                or SIZE_CLASS.fullmatch(c)
                or PLACEMENT_CLASS.fullmatch(c)
                or c == RESIZED_CLASS
            )
        )

    return _Image(
        src,
        alt,
        caption,
        ids[0] if ids else None,
        sizes[0] if sizes else None,
        tuple(sorted({c for c in pooled if PLACEMENT_CLASS.fullmatch(c)})),
        own(figure_classes),
        own(image_classes),
        tuple(attrs.items()),
    )


def _caption_text(node: Node) -> str | None:
    """A plain figure caption's text; styled or attributed captions return None."""
    if not isinstance(node, Element) or node.tag != "figcaption":
        return None
    if node.attrs and node.attrs != {"class": CAPTION_CLASS}:
        return None
    if not all(isinstance(child, str) for child in node.children):
        return None
    return "".join(node.children).strip(HTML_SPACE)  # type: ignore[arg-type]


def _canonical_media(nodes: list[Node]) -> list[Node]:
    """Give each displayed image, embed, and comment paragraph one comparable form.

    The forms are block elements, like the figures and paragraphs they stand for.
    """
    result: list[Node] = []
    for node in nodes:
        image = _parse_image(node)
        if image is not None:
            node = Element(
                "figure",
                {
                    "data-wpsync-image": "",
                    "src": image.src,
                    "alt": "" if image.alt is None else image.alt,
                    "has-alt": str(image.alt is not None),
                    "caption": image.caption or "",
                    "media": f"{image.media_id}:{image.size}",
                    "placement": " ".join(image.placement),
                    "figure-class": " ".join(sorted(image.figure_classes)),
                    "image-class": " ".join(sorted(image.image_classes)),
                    **dict(image.attrs),
                },
            )
        elif isinstance(node, Element) and node.tag == "p" and not node.attrs:
            content = [c for c in node.children if not _blank(c)]
            if len(content) == 1 and isinstance(content[0], str):
                url = content[0].strip(HTML_SPACE)
                if EMBED_URL.fullmatch(url):
                    node = Element("p", {"data-wpsync-embed": url})
            elif content and all(isinstance(c, Comment) for c in content):
                # WordPress wraps a lone <!--more--> in an empty paragraph.
                result.extend(content)
                continue
        if isinstance(node, Element) and not _is_media_form(node):
            node = Element(
                node.tag, _displayed_attrs(node), _canonical_media(node.children)
            )
        result.append(node)
    return result


def _displayed_attrs(node: Element) -> dict[str, str]:
    if node.tag != "a":
        return node.attrs
    return {k: v for k, v in node.attrs.items() if k not in EDITOR_LINK_ATTRS}


def _is_media_form(node: Element) -> bool:
    return "data-wpsync-image" in node.attrs or "data-wpsync-embed" in node.attrs


# Pull ----------------------------------------------------------------------


def to_markdown(raw: str, media: Media) -> Conversion:
    """Convert stored content, keeping as exact source what would not display alike."""
    units = _block_units(raw) if is_block_content(raw) else _classic_units(raw)
    converter = Converter(EDITOR_CLASSES)
    fragments = [_convert(unit, converter, media) for unit in units]
    converted = [
        index for index, fragment in enumerate(fragments) if fragment is not None
    ]
    expected = _comparable(display(raw))

    def document(chosen: list[int]) -> str:
        parts = [
            fragments[index] if index in chosen else kept_markdown(unit.source)
            for index, unit in enumerate(units)
        ]
        return join_blocks([part for part in parts if part])  # type: ignore[misc]

    def displays_alike(chosen: list[int]) -> bool:
        pushed = render_html(document(chosen), media)
        return _comparable(display(pushed)) == expected

    if not displays_alike(converted):
        if not displays_alike([]):
            raise UnrepresentableContent(
                "the post displays differently even when kept entirely as HTML"
            )
        while not displays_alike(converted):
            # Find the first conversion that breaks the document and keep it.
            good, bad = 0, len(converted)
            while bad - good > 1:
                middle = (good + bad) // 2
                if displays_alike(converted[:middle]):
                    good = middle
                else:
                    bad = middle
            converted.pop(bad - 1)
    kept = tuple(
        unit.label for index, unit in enumerate(units) if index not in converted
    )
    pages = tuple(dict.fromkeys(_uploaded_pages(display(raw))))
    return Conversion(document(converted), kept, pages)


def _convert(unit: _Unit, converter: Converter, media: Media) -> str | None:
    if not unit.convertible:
        return None
    try:
        nodes = trim_block_whitespace(unit.nodes)
        parts = [converter.block(_for_conversion(node, media)) for node in nodes]
    except Unconvertible:
        return None
    fragment = join_blocks(parts)
    if not _displays_same(display(render_html(fragment, media)), unit.nodes):
        return None
    return fragment


def _for_conversion(node: Node, media: Media) -> Node:
    """Rewrite WordPress presentation markup into the form the converter reads."""
    if not isinstance(node, Element):
        return node
    if "data-wpsync-embed" in node.attrs:
        return Element("p", {}, [node.attrs["data-wpsync-embed"]])
    classes = node.attrs.get("class", "").split()
    if node.tag == "figure" and "wp-block-table" in classes:
        tables = [c for c in node.children if isinstance(c, Element)]
        if len(classes) == 1 and len(tables) == 1 and tables[0].tag == "table":
            return tables[0]
    image = _parse_image(node)
    if image is not None and not image.figure_classes:
        attrs = {"src": image.src, **dict(image.attrs)}
        if image.alt is not None:
            attrs["alt"] = image.alt
        if image.media_id is not None:
            attrs["src"] = media.remember(image.src, image.media_id, image.size)  # type: ignore[arg-type]
        if image.caption:
            attrs["title"] = image.caption
        classes = list(image.placement) + list(image.image_classes)
        if classes:
            attrs["class"] = " ".join(classes)
        return Element("p", {}, [Element("img", attrs)])
    return Element(
        node.tag,
        _displayed_attrs(node),
        [_for_conversion(c, media) for c in node.children],
    )


def _uploaded_pages(nodes: list[Node]) -> Iterator[str]:
    """The sources of iframes showing files uploaded to a WordPress site."""
    for node in nodes:
        if isinstance(node, Element):
            if node.tag == "iframe" and UPLOADS_PATH in node.attrs.get("src", ""):
                yield node.attrs["src"]
            yield from _uploaded_pages(node.children)
