import json

import pytest
from wordpress_fake import PASSWORD, SITE, FakeWordPress, add_profile, invoke


def test_create_saves_a_profile_without_signing_in(tmp_path, store, monkeypatch):
    blog = tmp_path / "blog"
    blog.mkdir()
    monkeypatch.chdir(blog)
    wordpress = FakeWordPress()

    status, output, errors = invoke(
        ["create", "myblog", "--site", "blog.test"],
        store,
        stdin="emrah\n\n",
        wordpress=wordpress,
        password=None,
    )

    assert (status, errors) == (0, "")
    assert output.endswith(
        f"Created profile 'myblog': '{blog.resolve()}' maps to {SITE}.\n"
        "Next: set MYBLOG_WP_PASSWORD to an Application Password, then run "
        "wpsync pull.\n"
    )
    saved = json.loads(store.path.read_text())["profiles"]["myblog"]
    assert saved == {
        "site": SITE,
        "api_root": f"{SITE}/wp-json/",
        "username": "emrah",
        "password_env": "MYBLOG_WP_PASSWORD",
        "local_root": str(blog.resolve()),
    }
    assert [r.headers.get("Authorization") for r in wordpress.requests] == [None]


def test_create_refuses_a_site_that_is_not_wordpress(tmp_path, store):
    status, _, errors = invoke(
        ["create", "myblog", "--site", SITE, "--local-root", str(tmp_path)],
        store,
        wordpress=FakeWordPress(advertises_api=False),
    )

    assert (status, errors) == (
        1,
        f"wpsync: error: {SITE} is not a WordPress site (no REST API link)\n",
    )
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
    assert invoke(["profile"], store)[:2] == (0, "myblog\n")

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


def test_first_pull_signs_in_through_a_rest_route_api_root(tmp_path, store):
    wordpress = FakeWordPress(post_count=120, rest_route=True, can_edit_others=False)
    profile = ["--username", "emrah", "--local-root", str(tmp_path)]
    invoke(["create", "myblog", "--site", SITE, *profile], store, wordpress=wordpress)

    status, output, errors = invoke(["myblog", "pull"], store, wordpress=wordpress)

    assert (status, errors) == (0, "")
    assert store.load().profiles["myblog"].api_root == f"{SITE}/?rest_route=/"
    lines = output.splitlines()
    assert lines[:2] == [
        f"Signed in to {SITE} as 'emrah' (administrator).",
        "Note: this account can edit only its own posts, so posts by other "
        "authors are not pulled.",
    ]
    assert lines[-1] == "Pulled 120 posts (120 new)."


@pytest.mark.parametrize(
    ("wordpress", "password", "message"),
    [
        (FakeWordPress(), None, "MYBLOG_WP_PASSWORD is not set"),
        (FakeWordPress(), "wrong", "invalid application password"),
        (FakeWordPress(can_edit=False), PASSWORD, "'emrah' cannot edit posts"),
    ],
)
def test_pull_records_nothing_until_sign_in_works(
    tmp_path, store, wordpress, password, message
):
    add_profile(store, "myblog", tmp_path)

    status, _, errors = invoke(
        ["myblog", "pull"], store, wordpress=wordpress, password=password
    )

    assert status == 1
    assert message in errors
    assert not (tmp_path / ".wpsync").exists()
