import io

from wordpress_fake import FakeWordPress, add_profile, invoke

from wpsync.documents import Document, Post, write_document


class Terminal(io.StringIO):
    def isatty(self):
        return True


IMAGE_URL = "https://blog.test/wp-content/uploads/2026/01/sunset-1024x768.jpg"


def blog():
    wordpress = FakeWordPress(post_count=2)
    first = wordpress.post(1)
    first["categories"], first["tags"] = [1, 2], [5]
    first["content"]["raw"] = (
        "<!-- wp:paragraph -->\n<p>Hello <strong>world</strong>.</p>\n"
        "<!-- /wp:paragraph -->\n\n"
        '<!-- wp:image {"id":42,"sizeSlug":"large"} -->\n'
        f'<figure class="wp-block-image size-large"><img src="{IMAGE_URL}" '
        'alt="Sunset" class="wp-image-42"/></figure>\n<!-- /wp:image -->'
    )
    return wordpress


def pull(store, wordpress, *arguments, stdin=""):
    return invoke(
        ["myblog", "pull", *arguments], store, wordpress=wordpress, stdin=stdin
    )


def test_first_pull_writes_posts_and_images_that_diff_then_sees_as_synced(
    tmp_path, store
):
    wordpress = blog()
    add_profile(store, "myblog", tmp_path)

    status, output, errors = pull(store, wordpress)

    assert (status, errors) == (0, "")
    assert output.splitlines() == [
        "Signed in to https://blog.test as 'emrah' (administrator).",
        "+ r  1  posts/post-1.md  1 image",
        "+ r  2  posts/post-2.md",
        "Pulled 2 posts (2 new), 1 image.",
    ]
    assert (tmp_path / "posts/post-1.md").read_text() == (
        "---\n"
        "id: 1\n"
        "title: Post 1\n"
        "slug: post-1\n"
        "date: 2026-01-02T13:00:00+03:00\n"
        "status: published\n"
        "categories:\n"
        "- News\n"
        "- Travel\n"
        "tags:\n"
        "- python\n"
        "---\n"
        "\n"
        "Hello **world**.\n"
        "\n"
        "![Sunset](images/sunset-1024x768.jpg)\n"
    )
    image = tmp_path / "images/sunset-1024x768.jpg"
    assert (
        image.read_bytes() == b"image:/wp-content/uploads/2026/01/sunset-1024x768.jpg"
    )
    downloads = [r for r in wordpress.requests if "/wp-content/" in r.url.path]
    assert [r.headers.get("Authorization") for r in downloads] == [None]

    wordpress.requests.clear()
    status, output, _ = invoke(["myblog", "diff"], store, wordpress=wordpress)
    assert (status, output) == (
        0,
        "No local changes.\nNot shown: 2 unchanged (-a to show)\n",
    )
    assert wordpress.requests == []


def test_later_pulls_update_unedited_files_and_ask_before_replacing_edits(
    tmp_path, store
):
    wordpress = blog()
    add_profile(store, "myblog", tmp_path)
    pull(store, wordpress)
    first, second = tmp_path / "posts/post-1.md", tmp_path / "posts/post-2.md"
    first.write_text(first.read_text().replace("---\n\n", "layout: post\n---\n\n"))
    second.write_text(second.read_text().replace("Body 2", "My edit"))
    wordpress.post(1)["title"]["raw"] = "Renamed on WordPress"
    wordpress.post(2)["title"]["raw"] = "Also renamed"

    status, output, _ = pull(store, wordpress)

    assert status == 0
    assert output.splitlines() == [
        "~ r  1  posts/post-1.md",
        "?    2  posts/post-2.md  changed on both sides; your file is unchanged",
        "Pulled 1 post (1 updated); 1 skipped. "
        "Rerun with --yes to accept the skipped changes.",
    ]
    assert "title: Renamed on WordPress" in first.read_text()
    assert "layout: post" in first.read_text()
    assert "My edit" in second.read_text()

    status, output, _ = pull(store, wordpress, "2", "--yes")

    assert output.splitlines() == [
        "~ r  2  posts/post-2.md",
        "Pulled 1 post (1 updated).",
    ]
    assert "My edit" not in second.read_text()


def test_a_remote_post_matching_an_unlinked_file_is_linked_not_duplicated(
    tmp_path, store
):
    wordpress = blog()
    add_profile(store, "myblog", tmp_path)
    write_document(tmp_path / "posts/draft.md", Document(None, Post(title="Post 2")))

    status, output, _ = pull(store, wordpress)

    assert (
        "?    2  posts/draft.md  matches this file (same title); not linked"
        in output.splitlines()
    )
    names = sorted(p.name for p in (tmp_path / "posts").iterdir())
    assert names == ["draft.md", "post-1.md"]

    status, output, _ = pull(store, wordpress, "2", stdin=Terminal("y\n"))

    assert output.splitlines()[-2].endswith("+ r  2  posts/draft.md")
    assert (tmp_path / "posts/draft.md").read_text().startswith("---\nid: 2\n")


def test_pull_never_deletes_or_restores_files(tmp_path, store):
    wordpress = blog()
    add_profile(store, "myblog", tmp_path)
    pull(store, wordpress)
    (tmp_path / "posts/post-1.md").unlink()
    wordpress.posts.remove(wordpress.post(2))

    status, output, _ = pull(store, wordpress)

    assert output.splitlines() == [
        "- l  1  posts/post-1.md  deleted locally; not restored",
        "- r  2  posts/post-2.md  deleted on WordPress; local file kept",
        "Nothing to pull.",
    ]
    assert not (tmp_path / "posts/post-1.md").exists()
    assert (tmp_path / "posts/post-2.md").exists()


def test_images_kept_inside_html_are_not_downloaded(tmp_path, store):
    wordpress = blog()
    wordpress.post(2)["content"]["raw"] = (
        '<!-- wp:image {"id":7} -->\n<figure class="wp-block-image size-large">'
        f'<img src="{IMAGE_URL.replace("sunset", "kept")}" alt=""'
        ' class="wp-image-7" title="Tip"/>'
        '<figcaption class="wp-element-caption">Cap</figcaption>'
        "</figure>\n<!-- /wp:image -->"
    )
    add_profile(store, "myblog", tmp_path)

    status, output, _ = pull(store, wordpress)

    assert "+ r  2  posts/post-2.md  kept as HTML: core/image" in output
    assert sorted(p.name for p in (tmp_path / "images").iterdir()) == [
        "sunset-1024x768.jpg"
    ]
    assert not any("kept" in r.url.path for r in wordpress.requests)
