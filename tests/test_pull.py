import io

import pytest
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
        "+  1  posts/post-1.md  1 image",
        "+  2  posts/post-2.md",
        "Pulled 2 posts (2 new), 1 image.",
    ]
    assert (tmp_path / "posts/post-1.md").read_text() == (
        "---\n"
        "id: 1\n"
        "title: Post 1\n"
        "slug: post-1\n"
        "date: 2026-01-02T13:00:00+03:00\n"
        "status: public\n"
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
        "~  1  posts/post-1.md",
        "?  2  posts/post-2.md  changed on both sides; your file is unchanged",
        "Pulled 1 post (1 updated); 1 skipped. "
        "Rerun with --yes to accept the skipped changes.",
    ]
    assert "title: Renamed on WordPress" in first.read_text()
    assert "layout: post" in first.read_text()
    assert "My edit" in second.read_text()

    status, output, _ = pull(store, wordpress, "2", "--yes")

    assert output.splitlines() == [
        "~  2  posts/post-2.md",
        "Pulled 1 post (1 updated).",
    ]
    assert "My edit" not in second.read_text()


def test_only_a_shared_slug_links_an_unlinked_file_to_a_remote_post(tmp_path, store):
    wordpress = blog()
    add_profile(store, "myblog", tmp_path)
    write_document(tmp_path / "posts/draft.md", Document(None, Post(slug="post-2")))
    write_document(tmp_path / "posts/idea.md", Document(None, Post(title="Post 1")))

    status, output, _ = pull(store, wordpress)

    assert "?  2  posts/draft.md  same slug as this file; not linked" in output
    names = sorted(p.name for p in (tmp_path / "posts").iterdir())
    assert names == ["draft.md", "idea.md", "post-1.md"]

    status, output, _ = pull(store, wordpress, "2", stdin=Terminal("y\n"))

    assert output.splitlines()[-2].endswith("+  2  posts/draft.md")
    assert (tmp_path / "posts/draft.md").read_text().startswith("---\nid: 2\n")


def test_pull_never_deletes_or_restores_files(tmp_path, store):
    wordpress = blog()
    add_profile(store, "myblog", tmp_path)
    pull(store, wordpress)
    (tmp_path / "posts/post-1.md").unlink()
    wordpress.posts.remove(wordpress.post(2))

    status, output, _ = pull(store, wordpress)

    assert output.splitlines() == [
        "-  1  posts/post-1.md  deleted locally; not restored",
        "-  2  posts/post-2.md  deleted on WordPress; local file kept",
        "Nothing to pull.",
    ]
    assert not (tmp_path / "posts/post-1.md").exists()
    assert (tmp_path / "posts/post-2.md").exists()


def two_image_blog():
    """A blog whose first post shows two library images."""
    wordpress = blog()
    gone = IMAGE_URL.replace("sunset", "gone")
    block = (
        '<!-- wp:image {"id":43,"sizeSlug":"large"} -->\n'
        f'<figure class="wp-block-image size-large"><img src="{gone}" alt="" '
        'class="wp-image-43"/></figure>\n<!-- /wp:image -->'
    )
    wordpress.post(1)["content"]["raw"] += "\n\n" + block
    return wordpress, gone, block


@pytest.mark.parametrize("response", [404, 200], ids=["not-found", "web-page"])
def test_a_missing_image_is_reported_and_the_post_still_converts(
    tmp_path, store, response
):
    wordpress, gone, _ = two_image_blog()
    wordpress.broken_uploads["/wp-content/uploads/2026/01/gone-1024x768.jpg"] = response
    add_profile(store, "myblog", tmp_path)

    status, output, errors = pull(store, wordpress)

    assert (status, errors) == (0, "")
    assert output.splitlines()[1:] == [
        f"+  1  posts/post-1.md  1 image; image missing: {gone}",
        "+  2  posts/post-2.md",
        "Pulled 2 posts (2 new), 1 image; 1 image missing.",
    ]
    body = (tmp_path / "posts/post-1.md").read_text()
    assert (
        "![Sunset](images/sunset-1024x768.jpg)\n\n![](images/gone-1024x768.jpg)" in body
    )
    assert sorted(p.name for p in (tmp_path / "images").iterdir()) == [
        "sunset-1024x768.jpg"
    ]

    status, output, _ = invoke(["myblog", "diff"], store, wordpress=wordpress)
    assert output.startswith("No local changes.")


def test_a_missing_image_stays_flagged_until_a_pull_restores_it_under_your_edits(
    tmp_path, store
):
    wordpress, _, _ = two_image_blog()
    path = "/wp-content/uploads/2026/01/gone-1024x768.jpg"
    wordpress.broken_uploads[path] = 404
    add_profile(store, "myblog", tmp_path)
    pull(store, wordpress)

    def issues():
        output = invoke(["myblog", "ls"], store, wordpress=wordpress, password=None)[1]
        return output.splitlines()[1].split()[-1]

    assert issues() == "b"
    _, output, _ = pull(store, wordpress)
    assert output == "Nothing to pull; 1 image missing.\n"
    assert issues() == "b"

    post = tmp_path / "posts/post-1.md"
    post.write_text(post.read_text() + "\nMy edit.\n")
    edited = post.read_text()
    del wordpress.broken_uploads[path]
    _, output, _ = pull(store, wordpress)

    assert output.splitlines() == [
        "~  1  posts/post-1.md  1 image restored",
        "Restored 1 image; 1 post with local changes.",
    ]
    assert post.read_text() == edited
    assert (tmp_path / "images/gone-1024x768.jpg").exists()
    assert issues() == "-"


def test_a_failed_download_stops_the_pull_without_leaving_part_of_a_post(
    tmp_path, store
):
    wordpress, _, _ = two_image_blog()
    path = "/wp-content/uploads/2026/01/gone-1024x768.jpg"
    wordpress.broken_uploads[path] = 500
    add_profile(store, "myblog", tmp_path)

    status, _, errors = pull(store, wordpress)

    assert status != 0
    assert "HTTP 500" in errors
    assert not (tmp_path / "posts/post-1.md").exists()
    assert not (tmp_path / "images").exists()

    del wordpress.broken_uploads[path]
    status, output, _ = pull(store, wordpress)
    assert status == 0
    assert "Pulled 2 posts (2 new), 2 images." in output
    assert sorted(p.name for p in (tmp_path / "images").iterdir()) == [
        "gone-1024x768.jpg",
        "sunset-1024x768.jpg",
    ]


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

    assert "+  2  posts/post-2.md  kept as HTML: core/image" in output
    assert sorted(p.name for p in (tmp_path / "images").iterdir()) == [
        "sunset-1024x768.jpg"
    ]
    assert not any("kept" in r.url.path for r in wordpress.requests)
