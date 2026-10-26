from datetime import UTC, datetime

import pytest

from wpsync.documents import (
    Document,
    DocumentError,
    parse_document,
    scan_documents,
    serialize_document,
    write_document,
)
from wpsync.posts import Post, PostStatus


def test_synced_fields_survive_a_round_trip_with_yaml_lookalike_values():
    document = Document(
        "42",
        Post(
            title="Yes: no # 123",
            slug="ça-va",
            date=datetime(2026, 10, 1, 7, 30, tzinfo=UTC),
            status=PostStatus.SCHEDULED,
            categories=("News",),
            tags=("2026", "null", "true"),
            body="# Heading\n\nText with `code`.",
        ),
    )

    assert parse_document(serialize_document(document)) == document


def test_unsynced_frontmatter_is_kept_verbatim_while_synced_fields_are_rewritten():
    original = (
        "---\n"
        "layout: post   # theme layout\n"
        "draft: true\n"
        "tags: [b, a, b]\n"
        "title: Hello\n"
        "# kept with the entry below\n"
        "params:\n"
        "  hero: sunset.jpg\n"
        "---\n"
        "\n"
        "Body.\n"
    )

    document = parse_document(original)
    rewritten = serialize_document(document)

    assert document.extra_keys == ("layout", "draft", "params")
    assert document.post.tags == ("a", "b")
    assert rewritten == (
        "---\n"
        "title: Hello\n"
        "status: draft\n"
        "categories: []\n"
        "tags:\n"
        "- a\n"
        "- b\n"
        "layout: post   # theme layout\n"
        "draft: true\n"
        "# kept with the entry below\n"
        "params:\n"
        "  hero: sunset.jpg\n"
        "---\n"
        "\n"
        "Body.\n"
    )
    assert parse_document(rewritten) == document


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# Just Markdown\n", "start the file with a header such as"),
        ("---\ndate: 2026-10-01 09:30\n---\n", "needs a time zone"),
        ("---\ntags: python\n---\n", "'tags' must be a list"),
        ("---\nstatus: publish\n---\n", "must be one of: draft, published"),
    ],
)
def test_invalid_files_are_rejected_with_an_actionable_message(text, message):
    with pytest.raises(DocumentError, match=message):
        parse_document(text)


def test_scan_reads_nested_posts_and_reports_every_problem_at_once(tmp_path):
    posts = tmp_path / "posts"
    write_document(posts / "a.md", Document("7", Post(title="A")))
    write_document(posts / "2026" / "b.md", Document(None, Post(title="B")))
    write_document(posts / "2026" / "copy.md", Document("7", Post(title="Copy")))
    (posts / "broken.md").write_text("no frontmatter\n")
    (posts / ".hidden.md").write_text("ignored\n")
    (posts / "notes.txt").write_text("ignored\n")

    with pytest.raises(DocumentError) as raised:
        scan_documents(tmp_path)

    problems = str(raised.value).splitlines()
    assert problems[0].startswith("posts/broken.md: missing frontmatter")
    assert problems[-1] == (
        "post id 7 is used by more than one file: posts/2026/copy.md, posts/a.md"
    )

    (posts / "broken.md").unlink()
    (posts / "2026" / "copy.md").unlink()
    found = [
        (str(item.path), item.document.post.title) for item in scan_documents(tmp_path)
    ]
    assert found == [("posts/2026/b.md", "B"), ("posts/a.md", "A")]
