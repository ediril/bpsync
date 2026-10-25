import json

import pytest
from wordpress_fake import PASSWORD, SITE, FakeWordPress, add_profile, invoke


def test_create_maps_current_directory_and_lists_every_page_of_posts(
    tmp_path, store, monkeypatch
):
    blog = tmp_path / "blog"
    blog.mkdir()
    monkeypatch.chdir(blog)

    status, output, errors = invoke(
        ["create", "myblog", "--site", "blog.test"],
        store,
        stdin="emrah\n\n",
        wordpress=FakeWordPress(post_count=150),
    )

    assert (status, errors) == (0, "")
    assert f"Mapped '{blog.resolve()}' to {SITE}." in output
    assert "150 posts: 75 draft, 75 published" in output
    saved = json.loads(store.path.read_text())["profiles"]["myblog"]
    assert saved == {
        "site": SITE,
        "api_root": f"{SITE}/wp-json/",
        "username": "emrah",
        "password_env": "MYBLOG_WP_PASSWORD",
        "local_root": str(blog.resolve()),
    }
    assert PASSWORD not in store.path.read_text()


@pytest.mark.parametrize(
    ("password", "message"),
    [
        (None, "set MYBLOG_WP_PASSWORD to an Application Password"),
        ("wrong", "invalid application password"),
    ],
)
def test_create_saves_nothing_until_credentials_work(
    tmp_path, store, password, message
):
    status, _, errors = invoke(
        [
            "create",
            "myblog",
            "--site",
            SITE,
            "--username",
            "emrah",
            "--local-root",
            str(tmp_path),
        ],
        store,
        password=password,
    )

    assert status == 1
    assert message in errors
    assert not store.path.exists()


def test_create_rejects_a_folder_inside_another_profile(tmp_path, store):
    add_profile(store, "first", tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()

    status, _, errors = invoke(
        [
            "create",
            "myblog",
            "--site",
            SITE,
            "--username",
            "emrah",
            "--local-root",
            str(nested),
        ],
        store,
    )

    assert status == 1
    assert "overlaps profile 'first'" in errors


def test_commands_infer_the_profile_or_take_a_prefix(tmp_path, store, monkeypatch):
    blog = tmp_path / "blog"
    (blog / "posts").mkdir(parents=True)
    add_profile(store, "myblog", blog)

    monkeypatch.chdir(blog / "posts")
    assert invoke(["ro"], store)[:2] == (0, f"{blog.resolve()}\n")
    assert invoke(["connect"], store)[0] == 0

    monkeypatch.chdir(tmp_path)
    status, _, errors = invoke(["root"], store)
    assert status == 1 and "not inside a mapped profile" in errors
    assert invoke(["myblog", "root"], store)[:2] == (0, f"{blog.resolve()}\n")


def test_map_moves_the_local_folder_only_after_confirmation(tmp_path, store):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    add_profile(store, "myblog", old)
    arguments = ["myblog", "map", "--local-root", str(new)]

    assert "unchanged" in invoke(arguments, store, stdin="\n")[1]
    assert store.load().profiles["myblog"].local_root == old.resolve()

    assert invoke(arguments, store, stdin="y\n")[0] == 0
    assert store.load().profiles["myblog"].local_root == new.resolve()


def test_connect_works_with_a_rest_route_api_root(tmp_path, store):
    wordpress = FakeWordPress(post_count=120, rest_route=True)
    status, output, errors = invoke(
        [
            "create",
            "myblog",
            "--site",
            SITE,
            "--username",
            "emrah",
            "--local-root",
            str(tmp_path),
        ],
        store,
        wordpress=wordpress,
    )

    assert (status, errors) == (0, "")
    assert store.load().profiles["myblog"].api_root == f"{SITE}/?rest_route=/"
    assert "120 posts" in output


def test_connect_refuses_an_account_that_cannot_edit_posts(tmp_path, store):
    add_profile(store, "myblog", tmp_path)

    status, _, errors = invoke(
        ["myblog", "connect"], store, wordpress=FakeWordPress(can_edit=False)
    )

    assert status == 1
    assert "cannot edit posts" in errors
