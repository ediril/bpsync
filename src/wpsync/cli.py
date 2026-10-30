from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

import httpx

from wpsync import __version__
from wpsync.config import (
    Configuration,
    ConfigurationError,
    ConfigurationStore,
    Profile,
    canonical_local_root,
    default_password_env,
    validate_environment_name,
    validate_profile_name,
)
from wpsync.documents import DocumentError, LocalDocument, scan_documents
from wpsync.posts import PostSummary, RemoteState
from wpsync.pull import Puller
from wpsync.state import StateError, read_media, read_records
from wpsync.sync import Action, DiffEntry, SelectionError, compare, select
from wpsync.wordpress.client import WordPressClient, WordPressError, discover_api_root
from wpsync.wordpress.remote import WordPressRemote

COMMANDS = (
    "create",
    "map",
    "remove",
    "root",
    "profile",
    "profiles",
    "ls",
    "diff",
    "pull",
)
PROFILE_AWARE_COMMANDS = frozenset(
    {"map", "remove", "root", "profile", "ls", "diff", "pull"}
)
RESET = "\033[0m"
MARKER_COLORS = {
    "+": "\033[38;5;82m",
    "~": "\033[33m",
    "-": "\033[31m",
    "?": "\033[35m",
    "l": "\033[38;5;51m",
    "r": "\033[38;5;30m",
}
LEGEND = (
    ("+ l", "new local post; push creates it, or links it to the post it matches"),
    ("~ l", "changed locally; push updates the post"),
    ("- l", "deleted locally; WordPress keeps the post"),
    ("?  ", "conflict or ambiguous match; push stops and asks"),
    ("=  ", "unchanged (shown with -a)"),
)


class _Session:
    """The process context a command runs in."""

    def __init__(
        self,
        store: ConfigurationStore,
        stdin: TextIO,
        stdout: TextIO,
        environ: Mapping[str, str],
        transport: httpx.BaseTransport | None,
    ) -> None:
        self.store = store
        self.stdin = stdin
        self.stdout = stdout
        self.environ = environ
        self.transport = transport

    def ask(self, prompt: str) -> str:
        print(prompt, end="", file=self.stdout, flush=True)
        return self.stdin.readline().strip()

    def confirm(self, prompt: str, *, default: bool) -> bool:
        """Ask a yes/no question. End of input counts as No."""
        while True:
            print(prompt, end="", file=self.stdout, flush=True)
            answer = self.stdin.readline()
            if answer == "":
                print(file=self.stdout)
                return False
            normalized = answer.strip().lower()
            if normalized in {"y", "yes"}:
                return True
            if normalized in {"n", "no"}:
                return False
            if normalized == "":
                return default
            print("Please answer yes or no.", file=self.stdout)

    def password(self, profile: Profile) -> str:
        password = self.environ.get(profile.password_env)
        if not password:
            raise ConfigurationError(f"{profile.password_env} is not set")
        return password


def _resolve_command(value: str) -> str:
    if value in COMMANDS:
        return value
    matches = [command for command in COMMANDS if command.startswith(value)]
    if not matches:
        raise ConfigurationError(f"unknown command '{value}'")
    if len(matches) > 1:
        raise ConfigurationError(f"ambiguous command '{value}': {', '.join(matches)}")
    return matches[0]


def _could_be_command(value: str) -> bool:
    return any(command.startswith(value) for command in COMMANDS)


def _resolve_invocation(arguments: list[str]) -> tuple[list[str], str | None]:
    """Expand command prefixes and split off a leading profile override."""
    if not arguments or arguments[0].startswith("-"):
        return arguments, None
    first = arguments[0]
    if (
        first not in COMMANDS
        and len(arguments) > 1
        and not arguments[1].startswith("-")
        and _could_be_command(arguments[1])
    ):
        command = _resolve_command(arguments[1])
        if command not in PROFILE_AWARE_COMMANDS:
            raise ConfigurationError(
                f"profile prefix '{first}' cannot be used with '{command}'"
            )
        return [command, *arguments[2:]], validate_profile_name(first)
    return [_resolve_command(first), *arguments[1:]], None


def _profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "profile_name",
        nargs="?",
        metavar="PROFILE",
        help="profile; inferred from the current directory when omitted",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wpsync",
        description=(
            "Manage WordPress posts as local Markdown files. Run commands inside "
            "a mapped profile folder, or prefix a command with a profile name. "
            "Commands may be shortened to any unique prefix."
        ),
    )
    parser.add_argument("-v", "--version", action="version", version=__version__)
    parser.add_argument(
        "--legend", action="store_true", help="show diff symbols and exit"
    )
    subparsers = parser.add_subparsers(dest="command")

    create = subparsers.add_parser(
        "create",
        help="create a profile that maps a local folder to a blog",
        description=(
            "Create a profile for a WordPress site without signing in. Without "
            "--local-root, offer the current directory. Pull next."
        ),
    )
    create.add_argument("profile_name", metavar="PROFILE", help="new profile name")
    create.add_argument(
        "--site", required=True, help="blog address, such as https://example.com"
    )
    create.add_argument(
        "-u", "--username", help="WordPress username; prompted when omitted"
    )
    create.add_argument(
        "--password-env",
        metavar="NAME",
        help="password environment variable (default: PROFILE_WP_PASSWORD)",
    )
    create.add_argument(
        "--local-root", metavar="PATH", help="local folder for this blog"
    )

    map_parser = subparsers.add_parser(
        "map",
        help="move a profile's local folder",
        usage="wpsync map [PROFILE] [--local-root PATH]\n       wpsync PROFILE map",
        description=(
            "Point a profile at a different local folder after a [y/N] "
            "confirmation. A different blog needs its own profile."
        ),
    )
    _profile_argument(map_parser)
    map_parser.add_argument(
        "--local-root",
        metavar="PATH",
        help="new local folder; defaults to the current directory",
    )

    remove = subparsers.add_parser(
        "remove",
        help="remove a profile",
        usage="wpsync remove [PROFILE]\n       wpsync PROFILE remove",
        description="Remove the profile only; local files and the blog stay unchanged.",
    )
    _profile_argument(remove)

    root = subparsers.add_parser(
        "root",
        help="print a profile's local folder",
        usage="wpsync root [PROFILE]\n       wpsync PROFILE root",
        description=(
            'Print only the local folder, suitable for cd "$(wpsync root PROFILE)".'
        ),
    )
    _profile_argument(root)

    profile = subparsers.add_parser(
        "profile",
        help="show the current or named profile",
        usage=(
            "wpsync profile [PROFILE] [--details]\n"
            "       wpsync PROFILE profile [--details]"
        ),
    )
    _profile_argument(profile)
    profile.add_argument(
        "--details",
        action="store_true",
        help="show the site, account, and local folder",
    )

    subparsers.add_parser(
        "profiles",
        help="list profiles",
        description="List profiles; * marks the one containing this directory.",
    )

    subparsers.add_parser(
        "ls",
        help="list local posts with their IDs and slugs",
        usage="wpsync ls\n       wpsync PROFILE ls",
        description="List the post files in this profile without contacting the blog.",
    )

    diff = subparsers.add_parser(
        "diff",
        help="show what push would change",
        usage="wpsync diff [POST] [-a]\n       wpsync PROFILE diff [POST] [-a]",
        description=(
            "Show local changes and anything that would stop a push. Contacts the "
            "blog only for changed or new posts. POST is a post ID, slug, or file."
        ),
    )
    diff.add_argument(
        "post", nargs="?", metavar="POST", help="one post; all when omitted"
    )
    diff.add_argument(
        "-a", "--all", action="store_true", help="also show unchanged posts"
    )

    pull = subparsers.add_parser(
        "pull",
        help="bring posts from the blog into local files",
        usage="wpsync pull [POST] [-y]\n       wpsync PROFILE pull [POST] [-y]",
        description=(
            "Create and update local post files from the blog and download their "
            "images. Local edits are never overwritten without asking. POST is a "
            "post ID, slug, or file."
        ),
    )
    pull.add_argument(
        "post", nargs="?", metavar="POST", help="one post; all when omitted"
    )
    pull.add_argument(
        "-y", "--yes", action="store_true", help="answer yes to every question"
    )
    return parser


def _resolve_profile(
    arguments: argparse.Namespace, configuration: Configuration
) -> tuple[str, Profile]:
    prefix = arguments.profile_prefix
    positional = getattr(arguments, "profile_name", None)
    if prefix is not None and positional is not None:
        raise ConfigurationError(
            "profile was specified both before the command and as an argument"
        )
    name = prefix or positional
    if name is None:
        active = configuration.profile_for_path(Path.cwd().resolve())
        if active is None:
            raise ConfigurationError(
                "current directory is not inside a mapped profile; prefix the "
                "command with a profile (wpsync PROFILE COMMAND)"
            )
        return active
    name = validate_profile_name(name)
    if name not in configuration.profiles:
        raise ConfigurationError(f"profile '{name}' does not exist")
    return name, configuration.profiles[name]


def _normalize_site(site: str) -> str:
    site = site.strip()
    if "://" not in site:
        site = f"https://{site}"
    url = httpx.URL(site)
    if url.scheme not in {"http", "https"} or not url.host:
        raise ConfigurationError(f"'{site}' is not an http or https address")
    return site


def _sign_in(client: WordPressClient, profile: Profile) -> list[str]:
    """Check the account can sync, and describe what limits it."""
    user = client.current_user()
    capabilities = user.get("capabilities", {})
    if not capabilities.get("edit_posts"):
        raise WordPressError(
            f"'{profile.username}' cannot edit posts on {profile.site}"
        )
    roles = ", ".join(user.get("roles", [])) or "no role"
    lines = [f"Signed in to {profile.site} as '{profile.username}' ({roles})."]
    if not capabilities.get("edit_others_posts"):
        lines.append(
            "Note: this account can edit only its own posts, so posts by other "
            "authors are not pulled."
        )
    if not capabilities.get("unfiltered_html"):
        lines.append(
            "Note: this account lacks unfiltered_html, so WordPress removes "
            "markup such as iframes and scripts from saved posts."
        )
    return lines


def _create(arguments: argparse.Namespace, session: _Session) -> str:
    name = validate_profile_name(arguments.profile_name)
    configuration = session.store.load()
    if name in configuration.profiles:
        raise ConfigurationError(f"profile '{name}' already exists")
    site = _normalize_site(arguments.site)
    api_root = discover_api_root(site, session.transport)
    password_env = (
        validate_environment_name(arguments.password_env)
        if arguments.password_env
        else default_password_env(name)
    )
    username = arguments.username or session.ask("WordPress username: ")
    if not username:
        raise ConfigurationError("a WordPress username is required")
    if arguments.local_root is not None:
        local_root = canonical_local_root(arguments.local_root)
    else:
        current = canonical_local_root(Path.cwd())
        if session.confirm(
            f"Map current directory '{current}' to {site}? [Y/n] ", default=True
        ):
            local_root = current
        else:
            supplied = session.ask("What local folder should be mapped instead? ")
            if not supplied:
                raise ConfigurationError("a local folder is required; use --local-root")
            local_root = canonical_local_root(supplied)
    configuration.check_root(name, local_root)
    configuration.add(name, Profile(site, api_root, username, password_env, local_root))
    session.store.save(configuration)
    step = "run wpsync pull"
    if not session.environ.get(password_env):
        step = f"set {password_env} to an Application Password, then {step}"
    return f"Created profile '{name}': '{local_root}' maps to {site}.\nNext: {step}."


def _map(arguments: argparse.Namespace, session: _Session) -> str:
    configuration = session.store.load()
    name, profile = _resolve_profile(arguments, configuration)
    local_root = canonical_local_root(arguments.local_root or Path.cwd())
    if local_root == profile.local_root:
        return f"Profile '{name}' already uses '{local_root}'."
    configuration.remap(name, local_root)
    prompt = (
        f"Change profile '{name}' local folder from '{profile.local_root}' "
        f"to '{local_root}'? [y/N] "
    )
    if not session.confirm(prompt, default=False):
        return f"Profile '{name}' is unchanged."
    session.store.save(configuration)
    return f"Mapped '{local_root}' to {profile.site}."


def _remove(arguments: argparse.Namespace, session: _Session) -> str:
    configuration = session.store.load()
    name, _ = _resolve_profile(arguments, configuration)
    del configuration.profiles[name]
    session.store.save(configuration)
    return f"Removed profile '{name}'. Local files and the blog are unchanged."


def _root(arguments: argparse.Namespace, session: _Session) -> str:
    _, profile = _resolve_profile(arguments, session.store.load())
    return os.fspath(profile.local_root)


def _profile(arguments: argparse.Namespace, session: _Session) -> str:
    configuration = session.store.load()
    if arguments.profile_prefix is None and arguments.profile_name is None:
        active = configuration.profile_for_path(Path.cwd().resolve())
        if active is None:
            return "No active profile. Use wpsync PROFILE COMMAND."
        name, profile = active
    else:
        name, profile = _resolve_profile(arguments, configuration)
    if not arguments.details:
        return name
    return "\n".join(
        (
            f"Profile '{name}':",
            f"  Site: {profile.site}",
            f"  REST API: {profile.api_root}",
            f"  Username: {profile.username}",
            f"  Password env: {profile.password_env}",
            f"  Local root: {profile.local_root}",
        )
    )


def _profiles(arguments: argparse.Namespace, session: _Session) -> str:
    configuration = session.store.load()
    if not configuration.profiles:
        return "No profiles configured."
    active = configuration.profile_for_path(Path.cwd().resolve())
    active_name = active[0] if active else None
    return "\n".join(
        f"{'*' if name == active_name else ' '} {name}"
        for name in sorted(configuration.profiles)
    )


def _use_color(stream: TextIO, environ: Mapping[str, str]) -> bool:
    if "NO_COLOR" in environ:
        return False
    is_terminal = getattr(stream, "isatty", None)
    return bool(is_terminal and is_terminal())


def _paint(text: str, color: bool) -> str:
    if not color:
        return text
    return "".join(
        f"{MARKER_COLORS[char]}{char}{RESET}" if char in MARKER_COLORS else char
        for char in text
    )


def _legend(session: _Session) -> str:
    color = _use_color(session.stdout, session.environ)
    lines = ["Diff legend:"]
    lines.extend(f"  {_paint(marker, color)}  {meaning}" for marker, meaning in LEGEND)
    return "\n".join(lines)


class _LazyRemote:
    """Connects to the blog only if a command turns out to need it."""

    def __init__(self, profile: Profile, session: _Session) -> None:
        self.profile = profile
        self.session = session
        self.client: WordPressClient | None = None

    def _connect(self) -> WordPressClient:
        if self.client is None:
            self.client = WordPressClient(
                self.profile.api_root,
                self.profile.username,
                self.session.password(self.profile),
                self.session.transport,
            )
        return self.client

    def post_states(self, ids: list[str]) -> dict[str, RemoteState]:
        return self._connect().post_states(ids)

    def post_summaries(self) -> list[PostSummary]:
        return self._connect().post_summaries()

    def close(self) -> None:
        if self.client is not None:
            self.client.http.close()


def _profile_root(
    arguments: argparse.Namespace, session: _Session
) -> tuple[Profile, Path]:
    _, profile = _resolve_profile(arguments, session.store.load())
    base = profile.local_root if arguments.profile_prefix else Path.cwd().resolve()
    return profile, base


def _ls(arguments: argparse.Namespace, session: _Session) -> str:
    profile, _ = _profile_root(arguments, session)
    documents = scan_documents(profile.local_root)
    if not documents:
        return "No posts. Run wpsync pull, or add Markdown files under posts/."

    def order(item):  # noqa: ANN001, ANN202
        post_id = item.document.post_id
        return (post_id is None, int(post_id) if post_id else 0, str(item.path))

    rows = [
        (
            item.document.post_id or "-",
            item.document.post.slug or "-",
            item.document.post.title or "(no title)",
            str(item.path),
        )
        for item in sorted(documents, key=order)
    ]
    widths = [
        max(len(row[i]) for row in rows + [("ID", "Slug", "Title", "")])
        for i in range(3)
    ]
    header = f"{'ID':>{widths[0]}}  {'Slug':<{widths[1]}}  {'Title':<{widths[2]}}  File"
    lines = [header]
    lines.extend(
        f"{post_id:>{widths[0]}}  {slug:<{widths[1]}}  {title:<{widths[2]}}  {path}"
        for post_id, slug, title, path in rows
    )
    return "\n".join(lines)


def _diff(arguments: argparse.Namespace, session: _Session) -> str:
    profile, base = _profile_root(arguments, session)
    root = profile.local_root
    selection = select(
        arguments.post,
        scan_documents(root),
        read_records(root, profile.api_root),
        root=root,
        base=base,
    )
    remote = _LazyRemote(profile, session)
    try:
        result = compare(selection, remote)
    finally:
        remote.close()
    color = _use_color(session.stdout, session.environ)
    shown = [
        e for e in result.entries if arguments.all or e.action is not Action.UNCHANGED
    ]
    hidden = len(result.entries) - len(shown)
    width = max((len(e.post_id or "-") for e in shown), default=1)
    lines = [_entry_line(entry, color, width) for entry in shown]
    if not shown:
        lines.append("No local changes.")
    if hidden:
        lines.append(f"Not shown: {hidden} unchanged (-a to show)")
    lines.extend(f"Note: {note}" for note in result.notes)
    return "\n".join(lines)


def _entry_line(entry: DiffEntry, color: bool, width: int = 1) -> str:
    marker = _paint(f"{entry.action} {entry.side or ' '}", color)
    detail = f"  {entry.detail}" if entry.detail else ""
    return f"{marker}  {entry.post_id or '-':>{width}}  {entry.path}{detail}"


def _pull_target(
    selector: str | None, documents: list[LocalDocument], root: Path, base: Path
) -> tuple[list[str] | None, str | None]:
    """The post IDs or slug a pull selector names; a slug may be remote only."""
    if selector is None:
        return None, None
    if selector.isdigit():
        return [selector], None
    if "/" in selector or selector.endswith(".md"):
        chosen = select(selector, documents, {}, root=root, base=base).documents
        post_id = chosen[0].document.post_id
        if post_id is None:
            raise SelectionError(
                f"{selector} is not linked to a post yet; push it first"
            )
        return [post_id], None
    local = [d for d in documents if d.document.post.slug == selector]
    if local and local[0].document.post_id:
        return [local[0].document.post_id], None
    return None, selector


def _pull(arguments: argparse.Namespace, session: _Session) -> str:
    profile, base = _profile_root(arguments, session)
    root = profile.local_root
    yes = arguments.yes
    documents = scan_documents(root)
    ids, slug = _pull_target(arguments.post, documents, root, base)
    records = read_records(root, profile.api_root)
    color = _use_color(session.stdout, session.environ)

    def confirm(question: str) -> bool:
        # Without a terminal nobody can answer, so the question counts as No.
        if yes:
            return True
        interactive = getattr(session.stdin, "isatty", lambda: False)()
        return interactive and session.confirm(f"{question} [y/N] ", default=False)

    def report(entry: DiffEntry) -> None:
        print(_entry_line(entry, color), file=session.stdout, flush=True)

    client = WordPressClient(
        profile.api_root, profile.username, session.password(profile), session.transport
    )
    remote = WordPressRemote(client, session.transport)
    try:
        account = _sign_in(client, profile)
        # Until something is pulled, say who signed in and what limits the account.
        if not records:
            print("\n".join(account), file=session.stdout, flush=True)
        puller = Puller(
            root,
            profile.api_root,
            remote,
            documents,
            records,
            read_media(root, profile.api_root),
            confirm,
            report,
        )
        result = puller.pull(ids=ids, slug=slug)
    finally:
        remote.close()
        client.http.close()
    summary = result.summary()
    if result.skipped and not yes:
        summary += " Rerun with --yes to accept the skipped changes."
    return summary


HANDLERS = {
    "create": _create,
    "map": _map,
    "remove": _remove,
    "root": _root,
    "profile": _profile,
    "profiles": _profiles,
    "ls": _ls,
    "diff": _diff,
    "pull": _pull,
}


def run(
    argv: Sequence[str] | None = None,
    *,
    store: ConfigurationStore | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    environ: Mapping[str, str] = os.environ,
    transport: httpx.BaseTransport | None = None,
) -> int:
    parser = build_parser()
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        raw_arguments, profile_prefix = _resolve_invocation(raw_arguments)
    except ConfigurationError as error:
        parser.error(str(error))
    arguments = parser.parse_args(raw_arguments)
    arguments.profile_prefix = profile_prefix
    session = _Session(store or ConfigurationStore(), stdin, stdout, environ, transport)
    if arguments.legend:
        if arguments.command is not None:
            parser.error("--legend cannot be combined with a command")
        print(_legend(session), file=stdout)
        return 0
    if arguments.command is None:
        parser.error("a command is required")
    try:
        message = HANDLERS[arguments.command](arguments, session)
    except (
        ConfigurationError,
        DocumentError,
        SelectionError,
        StateError,
        WordPressError,
    ) as error:
        print(f"wpsync: error: {error}", file=stderr)
        return 1
    print(message, file=stdout)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)
