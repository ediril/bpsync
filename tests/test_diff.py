from pathlib import Path, PurePosixPath

from wordpress_fake import SITE, FakeWordPress, add_profile, invoke

from bpsync.documents import Document, body_checksum, fields_checksum, write_document
from bpsync.posts import ContentFormat, Post
from bpsync.state import PostRecord, write_state
from bpsync.wordpress.client import fingerprint

API_ROOT = f"{SITE}/wp-json/"


def synced(root, wordpress, post_id, name):
    """Write a post file and record it as synchronized with the fake blog."""
    remote = wordpress.post(post_id)
    post = Post(title=remote["title"]["raw"], slug=remote["slug"], body="Body")
    path = Path("posts") / name
    write_document(root / path, Document(str(post_id), post))
    with write_state(root, API_ROOT) as state:
        state.save(
            PostRecord(
                str(post_id),
                PurePosixPath(path),
                body_checksum(post),
                fields_checksum(post),
                fingerprint(remote),
                ContentFormat.HTML,
            )
        )
    return root / path


def edit(path, old, new):
    path.write_text(path.read_text().replace(old, new))


def new_post(root, name, **fields):
    write_document(root / "posts" / name, Document(None, Post(**fields)))


def test_diff_without_local_changes_never_contacts_the_blog(tmp_path, store):
    wordpress = FakeWordPress()
    add_profile(store, "myblog", tmp_path)
    synced(tmp_path, wordpress, 1, "one.md")
    synced(tmp_path, wordpress, 2, "two.md")

    status, output, errors = invoke(
        ["myblog", "diff"], store, wordpress=wordpress, password=None
    )

    assert (status, errors) == (0, "")
    assert output == "No local changes.\nNot shown: 2 unchanged (-a to show)\n"
    assert wordpress.requests == []


def test_diff_shows_local_changes_and_fetches_only_those_posts(tmp_path, store):
    wordpress = FakeWordPress(post_count=6)
    wordpress.post(3)["content"]["raw"] = (
        "<!-- wp:paragraph --><p>x</p><!-- /wp:paragraph -->"
    )
    add_profile(store, "myblog", tmp_path)
    edit(synced(tmp_path, wordpress, 1, "content.md"), "Body", "New body")
    edit(
        synced(tmp_path, wordpress, 2, "details.md"), "title: Post 2", "title: Renamed"
    )
    edit(synced(tmp_path, wordpress, 3, "blocks.md"), "Body", "New body")
    edit(synced(tmp_path, wordpress, 4, "both.md"), "Body", "New body")
    wordpress.post(4)["title"]["raw"] = "Edited on WordPress"
    synced(tmp_path, wordpress, 5, "deleted.md").unlink()
    synced(tmp_path, wordpress, 6, "unchanged.md")

    status, output, _ = invoke(["myblog", "diff"], store, wordpress=wordpress)

    assert status == 0
    assert output.splitlines() == [
        "~ l  3  posts/blocks.md  content; block post becomes plain HTML on push",
        "?    4  posts/both.md  content; also changed on WordPress since the last sync",
        "~ l  1  posts/content.md  content",
        "- l  5  posts/deleted.md  deleted locally; WordPress keeps the post",
        "~ l  2  posts/details.md  details",
        "Not shown: 1 unchanged (-a to show)",
    ]
    fetched = [r.url.params.get("include") for r in wordpress.requests]
    assert fetched == ["1,2,3,4"]


def test_diff_matches_new_files_to_existing_posts_by_title_and_slug(tmp_path, store):
    wordpress = FakeWordPress(post_count=3)
    wordpress.posts.append({**wordpress.post(2), "id": 9, "slug": "post-2-copy"})
    add_profile(store, "myblog", tmp_path)
    new_post(tmp_path, "a.md", title="Different", slug="post-1")
    new_post(tmp_path, "b.md", title="Post 3")
    new_post(tmp_path, "c.md", title="Post 2")
    new_post(tmp_path, "d.md", title="Fresh")

    status, output, _ = invoke(["myblog", "diff"], store, wordpress=wordpress)

    assert status == 0
    assert output.splitlines() == [
        "+ l  -  posts/a.md  matches #1 'Post 1' (same slug)",
        "+ l  -  posts/b.md  matches #3 'Post 3' (same title)",
        "? l  -  posts/c.md  matches several posts: #2 'Post 2', #9 'Post 2'",
        "+ l  -  posts/d.md  new post",
    ]


def test_one_post_is_selected_by_id_slug_or_path(tmp_path, store, monkeypatch):
    wordpress = FakeWordPress(post_count=2)
    add_profile(store, "myblog", tmp_path)
    edit(synced(tmp_path, wordpress, 1, "one.md"), "Body", "New body")
    edit(synced(tmp_path, wordpress, 2, "two.md"), "Body", "New body")
    monkeypatch.chdir(tmp_path / "posts")

    for selector in ("2", "post-2", "two.md"):
        status, output, _ = invoke(["diff", selector], store, wordpress=wordpress)
        assert (status, output) == (0, "~ l  2  posts/two.md  content\n"), selector

    status, _, errors = invoke(["diff", "post-9"], store, wordpress=wordpress)
    assert status == 1
    assert "no local post has slug 'post-9'" in errors


def test_ls_lists_local_posts_without_contacting_the_blog(tmp_path, store):
    wordpress = FakeWordPress(post_count=12)
    add_profile(store, "myblog", tmp_path)
    synced(tmp_path, wordpress, 12, "twelve.md")
    synced(tmp_path, wordpress, 3, "three.md")
    new_post(tmp_path, "idea.md", title="Idea")

    status, output, _ = invoke(
        ["myblog", "ls"], store, wordpress=wordpress, password=None
    )

    assert status == 0
    assert output.splitlines() == [
        "ID  Slug     Title    File",
        " 3  post-3   Post 3   posts/three.md",
        "12  post-12  Post 12  posts/twelve.md",
        " -  -        Idea     posts/idea.md",
    ]
    assert wordpress.requests == []


def test_state_from_another_blog_is_refused(tmp_path, store):
    add_profile(store, "myblog", tmp_path)
    with write_state(tmp_path, "https://other.test/wp-json/"):
        pass

    status, _, errors = invoke(["myblog", "diff"], store)

    assert status == 1
    assert "synchronized with a different blog" in errors
