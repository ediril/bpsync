"""Comparing local post files with their last synchronized state."""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Generic, Protocol, TypeVar

from wpsync.documents import (
    FIELDS,
    POSTS_DIR,
    LocalDocument,
    body_checksum,
    fields_checksum,
)
from wpsync.posts import ContentFormat, Post, PostStatus, PostSummary, RemoteState
from wpsync.state import PostRecord

C = TypeVar("C", bound="Candidate")


class SelectionError(ValueError):
    """Raised when a post selector matches no post or several."""


class Remote(Protocol):
    def post_states(self, ids: list[str]) -> dict[str, RemoteState]: ...

    def post_summaries(self) -> list[PostSummary]: ...


@dataclass(frozen=True)
class Selection:
    documents: list[LocalDocument]
    records: dict[str, PostRecord]


def select(
    selector: str | None,
    documents: list[LocalDocument],
    records: dict[str, PostRecord],
    *,
    root: Path,
    base: Path,
) -> Selection:
    """Narrow to one post chosen by post ID, file path, or slug."""
    if selector is None:
        return Selection(documents, records)
    if selector.isdigit():
        chosen = [item for item in documents if item.document.post_id == selector]
        if chosen or selector in records:
            record = {selector: records[selector]} if selector in records else {}
            return Selection(chosen, record)
        raise SelectionError(f"no local post has id {selector}")
    if "/" in selector or selector.endswith(".md"):
        path = (base / selector).resolve()
        try:
            relative = PurePosixPath(path.relative_to(root).as_posix())
        except ValueError as error:
            raise SelectionError(f"{selector} is outside the profile folder") from error
        chosen = [item for item in documents if PurePosixPath(item.path) == relative]
        if not chosen:
            raise SelectionError(f"{selector} is not a post file under {POSTS_DIR}/")
    else:
        chosen = [item for item in documents if item.document.post.slug == selector]
        if not chosen:
            raise SelectionError(f"no local post has slug '{selector}'")
        if len(chosen) > 1:
            paths = ", ".join(str(item.path) for item in chosen)
            raise SelectionError(f"slug '{selector}' is used by {paths}")
    post_id = chosen[0].document.post_id
    record = {post_id: records[post_id]} if post_id in records else {}
    return Selection(chosen, record)


class Candidate(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def slug(self) -> str: ...


@dataclass(frozen=True)
class Match(Generic[C]):
    """How a post relates to the posts on the other side.

    Only a shared slug identifies the same post. A shared title is reported so
    the user can avoid a duplicate, but titles need not be unique.
    """

    post: C | None
    """The one post with the same slug."""
    candidates: tuple[C, ...] = ()
    """Several posts with the same slug; none is chosen."""
    same_title: tuple[C, ...] = ()
    """Other posts with the same title."""


def match_post(post: Post, candidates: Sequence[C]) -> Match[C]:
    by_slug = tuple(c for c in candidates if post.slug and c.slug == post.slug)
    title = post.title.strip()
    same_title = tuple(
        c for c in candidates if title and c.title.strip() == title and c not in by_slug
    )
    if len(by_slug) > 1:
        return Match(None, by_slug, same_title)
    return Match(by_slug[0] if by_slug else None, (), same_title)


class Action(StrEnum):
    NEW = "+"
    CHANGED = "~"
    DELETED = "-"
    CONFLICT = "?"
    UNCHANGED = "="
    PRIVATE = "x"


@dataclass(frozen=True)
class DiffEntry:
    action: Action
    side: str
    """'l' when the difference is local, 'r' when remote, blank for both."""
    post_id: str | None
    path: PurePosixPath
    detail: str = ""


@dataclass(frozen=True)
class Diff:
    entries: list[DiffEntry]
    notes: list[str]


def _local_changes(document: LocalDocument, record: PostRecord) -> list[str]:
    post = document.document.post
    changes = []
    if body_checksum(post) != record.body_checksum:
        changes.append("content")
    if fields_checksum(post) != record.fields_checksum:
        changes.append("details")
    return changes


def _typo_notes(document: LocalDocument) -> list[str]:
    notes = []
    for key in document.document.extra_keys:
        close = difflib.get_close_matches(key, FIELDS, n=1, cutoff=0.75)
        if close:
            notes.append(
                f"{document.path}: '{key}' is not synced; did you mean '{close[0]}'?"
            )
    return notes


def compare(selection: Selection, remote: Remote) -> Diff:
    """Classify the selected posts, contacting the remote only when needed."""
    entries: list[DiffEntry] = []
    changed: dict[str, tuple[LocalDocument, list[str]]] = {}
    unlinked: list[LocalDocument] = []
    new: list[LocalDocument] = []
    notes: list[str] = []
    present = set()
    for document in selection.documents:
        notes.extend(_typo_notes(document))
        post_id = document.document.post_id
        path = PurePosixPath(document.path)
        private = document.document.post.status is PostStatus.PRIVATE
        if post_id is not None:
            present.add(post_id)
        record = selection.records.get(post_id) if post_id else None
        if private and record is None:
            entries.append(DiffEntry(Action.PRIVATE, "l", post_id, path, "private"))
            continue
        if post_id is None:
            new.append(document)
            continue
        if record is None:
            unlinked.append(document)
            continue
        changes = _local_changes(document, record)
        if changes:
            changed[post_id] = (document, changes)
        else:
            entries.append(DiffEntry(Action.UNCHANGED, "", post_id, path))
    for post_id, record in selection.records.items():
        if post_id not in present:
            entries.append(
                DiffEntry(
                    Action.DELETED,
                    "l",
                    post_id,
                    record.path,
                    "deleted locally; WordPress keeps the post",
                )
            )

    ids = sorted({*changed, *(d.document.post_id for d in unlinked)}, key=int)
    states = remote.post_states(ids) if ids else {}  # type: ignore[arg-type]
    for post_id, (document, changes) in changed.items():
        record = selection.records[post_id]
        state = states.get(post_id)
        path = PurePosixPath(document.path)
        detail = ", ".join(changes)
        unpublish = document.document.post.status is PostStatus.PRIVATE
        if unpublish:
            # Push sends nothing for a private post except unpublishing it.
            if state is None or not state.published:
                entries.append(
                    DiffEntry(Action.PRIVATE, "l", post_id, path, f"{detail}; private")
                )
                continue
            detail = "unpublish; becomes a draft on WordPress"
        if state is None:
            entries.append(
                DiffEntry(
                    Action.CONFLICT,
                    "",
                    post_id,
                    path,
                    f"{detail}; deleted on WordPress",
                )
            )
        elif state.fingerprint != record.remote_fingerprint:
            entries.append(
                DiffEntry(
                    Action.CONFLICT,
                    "",
                    post_id,
                    path,
                    f"{detail}; also changed on WordPress since the last sync",
                )
            )
        else:
            if (
                "content" in changes
                and not unpublish
                and state.format is ContentFormat.BLOCKS
            ):
                detail += "; block post becomes plain HTML on push"
            entries.append(DiffEntry(Action.CHANGED, "l", post_id, path, detail))
    for document in unlinked:
        post_id = document.document.post_id
        exists = post_id in states
        detail = (
            "linked to a post that was never synced here"
            if exists
            else "linked to a post that is not on WordPress"
        )
        entries.append(
            DiffEntry(
                Action.CONFLICT, "", post_id, PurePosixPath(document.path), detail
            )
        )
    if new:
        summaries = remote.post_summaries()
        for document in new:
            entries.append(_new_entry(document, summaries))
    entries.sort(key=lambda entry: str(entry.path))
    return Diff(entries, notes)


def _new_entry(document: LocalDocument, summaries: Sequence[PostSummary]) -> DiffEntry:
    path = PurePosixPath(document.path)
    match = match_post(document.document.post, summaries)
    if match.candidates:
        listed = ", ".join(f"#{post.id} {post.title!r}" for post in match.candidates)
        return DiffEntry(
            Action.CONFLICT, "l", None, path, f"same slug as several posts: {listed}"
        )
    if match.post is not None:
        detail = f"same slug as #{match.post.id} {match.post.title!r}"
        return DiffEntry(Action.CONFLICT, "l", None, path, detail)
    detail = "new post"
    if match.same_title:
        detail += "; same title as " + ", ".join(f"#{p.id}" for p in match.same_title)
    return DiffEntry(Action.NEW, "l", None, path, detail)
