import json
import re
from pathlib import Path

import pytest

from bpsync.markup.dom import canonical, parse_html
from bpsync.wordpress.autop import autop
from bpsync.wordpress.content import (
    EDITOR_CLASSES,
    MediaImage,
    render_html,
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


def test_pushed_html_displays_like_the_pulled_post_and_has_no_stray_line_breaks():
    media = MemoryMedia()
    markdown = to_markdown(BLOCK_POST, media).markdown

    html = render_html(markdown, media)

    assert "\n" not in re.sub(r"<pre.*?</pre>", "", html, flags=re.S)
    assert '<figure class="wp-block-image size-large aligncenter">' in html
    assert 'class="wp-image-42"' in html
    assert "<p>https://www.youtube.com/watch?v=abc</p>" in html
    without_embed = (
        BLOCK_POST.split("<!-- wp:embed")[0] + BLOCK_POST.split("<!-- /wp:embed -->")[1]
    )
    html_without_embed = html.replace("<p>https://www.youtube.com/watch?v=abc</p>", "")
    stripped = re.sub(r"<!--\s+/?wp:.*?-->", "", without_embed)
    assert displays_same(html_without_embed, stripped)


def test_content_without_a_markdown_form_is_kept_as_html_that_survives_push():
    raw = (
        "<!-- wp:latest-posts /-->\n\n"
        '<!-- wp:gallery {"linkTo":"none"} -->\n'
        '<figure class="wp-block-gallery has-nested-images">'
        '<!-- wp:image {"id":1} -->\n'
        '<figure class="wp-block-image"><img src="a.jpg" alt="" class="wp-image-1"/>'
        "</figure>\n<!-- /wp:image --></figure>\n<!-- /wp:gallery -->\n\n"
        "<!-- wp:paragraph -->\n<p>After</p>\n<!-- /wp:paragraph -->"
    )
    media = MemoryMedia()

    result = to_markdown(raw, media)

    assert result.kept == ("core/latest-posts", "core/gallery")
    assert result.markdown.startswith("<!-- wp:latest-posts /-->\n\n<figure")
    assert result.markdown.endswith("\n\nAfter")
    html = render_html(result.markdown, media)
    assert "<!-- wp:latest-posts /-->" in html
    assert 'class="wp-block-gallery has-nested-images"' in html


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
