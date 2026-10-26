import json
import re
from pathlib import Path

import pytest

from bpsync.markup.dom import canonical, parse_html
from bpsync.media import MediaImage
from bpsync.wordpress.autop import autop
from bpsync.wordpress.content import (
    EDITOR_CLASSES,
    render_html,
    same_display,
    to_markdown,
)

FIXTURES = Path(__file__).parent / "fixtures"


class MemoryMedia:
    def __init__(self):
        self.images = {}

    def remember(self, url, media_id, size):
        src = "images/" + url.rsplit("/", 1)[-1]
        self.images[src] = MediaImage(media_id, url, size)
        return src

    def lookup(self, src):
        return self.images.get(src)


def displays_same(first, second):
    return canonical(parse_html(first), EDITOR_CLASSES) == canonical(
        parse_html(second), EDITOR_CLASSES
    )


BLOCK_POST = (FIXTURES / "block-post.html").read_text().rstrip("\n")


def test_block_post_becomes_markdown_with_attributes_only_where_styled():
    media = MemoryMedia()

    result = to_markdown(BLOCK_POST, media)

    assert result.kept == ()
    assert result.markdown == (
        'Some [red]{style="color: #c00"} text and '
        "[a link](https://example.com/){target=_blank rel=noopener}.\n"
        "\n"
        "{.has-text-align-right}\n"
        "Right aligned.\n"
        "\n"
        "### Section\n"
        "\n"
        "- One\n"
        "- Two\n"
        "  - Nested\n"
        "\n"
        '![Sunset](images/sunset-1024x768.jpg "Evening"){.aligncenter}\n'
        "\n"
        "https://www.youtube.com/watch?v=abc\n"
        "\n"
        ":::: {.wp-block-columns}\n"
        "::: {.wp-block-column}\n"
        "Left\n"
        ":::\n"
        "::::\n"
        "\n"
        "```\n"
        "if (a < b) {\n"
        "  go();\n"
        "}\n"
        "```"
    )
    assert media.lookup("images/sunset-1024x768.jpg") == MediaImage(
        "42", "https://blog.test/wp-content/uploads/sunset-1024x768.jpg", "large"
    )


def test_pushed_html_displays_like_the_pulled_post_without_stray_line_breaks():
    media = MemoryMedia()
    markdown = to_markdown(BLOCK_POST, media).markdown

    html = render_html(markdown, media)

    # Blocks are separated by blank lines; a newline inside one would become <br>.
    blocks = re.sub(r"<pre.*?</pre>", "", html, flags=re.S).split("\n\n")
    assert all("\n" not in block for block in blocks)
    assert '<figure class="wp-block-image size-large aligncenter">' in html
    assert 'class="wp-image-42"' in html
    assert "<p>https://www.youtube.com/watch?v=abc</p>" in html
    assert same_display(BLOCK_POST, html)


GALLERY = (
    '<!-- wp:gallery {"linkTo":"none"} -->\n'
    '<figure class="wp-block-gallery has-nested-images">'
    '<!-- wp:image {"id":1} -->\n'
    '<figure class="wp-block-image"><img src="a.jpg" alt="" class="wp-image-1"/>'
    "</figure>\n<!-- /wp:image --></figure>\n<!-- /wp:gallery -->"
)


def test_content_without_a_markdown_form_is_kept_as_its_exact_source():
    raw = (
        "<!-- wp:latest-posts /-->\n\n"
        + GALLERY
        + "\n\n<!-- wp:paragraph -->\n<p>After</p>\n<!-- /wp:paragraph -->"
    )
    media = MemoryMedia()

    result = to_markdown(raw, media)

    assert result.kept == ("core/latest-posts", "core/gallery")
    assert result.markdown == (
        "<!-- wp:latest-posts /-->\n\n```{=html}\n" + GALLERY + "\n```\n\nAfter"
    )
    html = render_html(result.markdown, media)
    assert html == "<!-- wp:latest-posts /-->\n\n" + GALLERY + "\n\n<p>After</p>"


def test_classic_content_is_read_with_wordpress_paragraph_rules():
    raw = "First line\nsecond line\n\n<b>Bold</b> start\n\n<ul>\n<li>item</li>\n</ul>"

    result = to_markdown(raw, MemoryMedia())

    assert result.markdown == "First line\\\nsecond line\n\n**Bold** start\n\n- item"


def test_adjacent_lists_stay_separate():
    raw = "<ul>\n<li>a</li>\n</ul>\n<ul>\n<li>b</li>\n</ul>"
    media = MemoryMedia()

    result = to_markdown(raw, media)

    assert result.markdown == "- a\n\n* b"
    assert render_html(result.markdown, media).count("<ul>") == 2


@pytest.mark.parametrize(
    "case",
    json.loads((FIXTURES / "wpautop.json").read_text())["cases"],
    ids=lambda case: case["input"][:30],
)
def test_autop_displays_like_wordpress(case):
    assert displays_same(autop(case["input"]), case["wordpress"])


IMAGE = "https://blog.test/wp-content/uploads/a-1024x768.jpg"
DISPLAY_CASES = {
    "spaces around inline media": (
        '<p>Click the <svg viewBox="0 0 1 1"></svg> icon now</p>',
        "Click the <svg",
    ),
    "first of duplicate attributes": (
        '<p><a href="https://first.test/" href="https://second.test/">x</a></p>',
        'href="https://first.test/"',
    ),
    "query string ampersands": (
        '<p><a href="https://s.test/?page=2&region=us&current=1">n</a></p>',
        "?page=2&amp;region=us&amp;current=1",
    ),
    "bold across a paragraph break": (
        "<strong>Warning.\n\nAlso bold.</strong>",
        "<strong>Also bold.</strong>",
    ),
    "multi-line style": (
        "<!-- wp:html -->\n<style>\n.a { color: red }\n\n.b {}\n</style>\n"
        "<!-- /wp:html -->",
        "<style>\n.a { color: red }\n\n.b {}\n</style>",
    ),
    "multi-line comment": (
        "Intro\n\n<!-- old\nnote -->\n\nOutro",
        "<!-- old\nnote -->",
    ),
    "text in a custom HTML block": (
        '<!-- wp:html -->\nSee <a href="https://x.test">this</a>.\n<!-- /wp:html -->',
        'See <a href="https://x.test">this</a>.',
    ),
    "styled caption": (
        f'<!-- wp:image {{"id":5}} -->\n<figure class="wp-block-image size-large">'
        f'<img src="{IMAGE}" alt="" class="wp-image-5"/><figcaption '
        'class="wp-element-caption" style="font-size:30px">Cap</figcaption>'
        "</figure>\n<!-- /wp:image -->",
        'style="font-size:30px"',
    ),
    "image border classes": (
        f'<!-- wp:image {{"id":5}} -->\n<figure class="wp-block-image size-large">'
        f'<img src="{IMAGE}" alt="" class="has-border-color '
        'has-vivid-red-border-color wp-image-5"/></figure>\n<!-- /wp:image -->',
        "has-vivid-red-border-color",
    ),
    "wide embed": (
        '<!-- wp:embed {"url":"https://youtu.be/x","align":"wide"} -->\n'
        '<figure class="wp-block-embed alignwide"><div class="wp-block-embed__wrapper">'
        "\nhttps://youtu.be/x\n</div></figure>\n<!-- /wp:embed -->",
        "alignwide",
    ),
    "preserved white space": (
        '<!-- wp:paragraph -->\n<p style="white-space:pre">a     b</p>\n'
        "<!-- /wp:paragraph -->",
        "a     b",
    ),
    "non-breaking spacer between blocks": (
        "<!-- wp:paragraph -->\n<p>A</p>\n<!-- /wp:paragraph -->\n&nbsp;\n"
        "<!-- wp:paragraph -->\n<p>B</p>\n<!-- /wp:paragraph -->",
        "&nbsp;",
    ),
}


@pytest.mark.parametrize(
    ("raw", "kept_text"), DISPLAY_CASES.values(), ids=DISPLAY_CASES
)
def test_pull_never_changes_what_a_post_displays(raw, kept_text):
    media = MemoryMedia()

    html = render_html(to_markdown(raw, media).markdown, media)

    assert same_display(raw, html)
    assert kept_text in html
