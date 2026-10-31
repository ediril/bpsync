"""Local post files: Markdown with YAML frontmatter.

WPSync owns the synchronized fields and rewrites them canonically. Any other
frontmatter entry is kept byte for byte, including its comments, and is never
sent to the blog.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from wpsync.posts import Post, PostStatus
from wpsync.storage import write_text_atomic

POSTS_DIR = "posts"
FENCE = "---"
FIELDS = ("id", "title", "slug", "date", "status", "categories", "tags")
EXAMPLE_HEADER = "---\ntitle: My post\nstatus: public\n---"


class DocumentError(ValueError):
    """Raised when a post file cannot be read as a WPSync document."""


@dataclass(frozen=True)
class Document:
    post_id: str | None
    post: Post
    extra: tuple[tuple[str, str], ...] = ()
    """Unsynchronized frontmatter entries as (key, original text)."""

    @property
    def extra_keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.extra)


@dataclass(frozen=True)
class LocalDocument:
    path: Path
    """Relative to the profile's local root."""
    document: Document


def _scalar(node: Node, key: str) -> str:
    if not isinstance(node, ScalarNode):
        raise DocumentError(f"'{key}' must be a single value")
    return node.value


def _terms(node: Node, key: str) -> tuple[str, ...]:
    if isinstance(node, ScalarNode) and node.value == "":
        return ()
    if not isinstance(node, SequenceNode):
        raise DocumentError(f"'{key}' must be a list, such as {key}: [One, Two]")
    names = [_scalar(item, key).strip() for item in node.value]
    if not all(names):
        raise DocumentError(f"'{key}' cannot contain empty names")
    return tuple(sorted(set(names)))


def _date(value: str) -> datetime | None:
    if value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise DocumentError(
            f"date '{value}' is not an ISO date, such as 2026-10-01T09:30:00+02:00"
        ) from error
    if parsed.tzinfo is None:
        raise DocumentError(
            f"date '{value}' needs a time zone, such as 2026-10-01T09:30:00+02:00"
        )
    return parsed


def _status(value: str) -> PostStatus:
    if value == "":
        return PostStatus.PRIVATE
    try:
        return PostStatus(value)
    except ValueError as error:
        choices = ", ".join(status.value for status in PostStatus)
        raise DocumentError(f"status '{value}' must be one of: {choices}") from error


def _line_end(text: str, index: int) -> int:
    if index > 0 and text[index - 1] == "\n":
        return index
    newline = text.find("\n", index)
    return len(text) if newline == -1 else newline + 1


def _split(text: str) -> tuple[str, str]:
    lines = text.split("\n")
    if lines[0] != FENCE:
        raise DocumentError(
            f"missing frontmatter; start the file with a header such as:\n"
            f"{EXAMPLE_HEADER}"
        )
    for index, line in enumerate(lines[1:], start=1):
        if line in (FENCE, "..."):
            return "\n".join(lines[1:index]) + "\n", "\n".join(lines[index + 1 :])
    raise DocumentError("frontmatter is not closed with a '---' line")


def parse_document(text: str) -> Document:
    text = text.removeprefix("﻿").replace("\r\n", "\n")
    header, body = _split(text)
    try:
        root = yaml.compose(header, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise DocumentError(f"frontmatter is not valid YAML: {error}") from error
    if root is None:
        entries = []
    elif isinstance(root, MappingNode):
        entries = root.value
    else:
        raise DocumentError("frontmatter must be a set of 'key: value' lines")
    values: dict[str, Node] = {}
    extra: list[tuple[str, str]] = []
    seen: set[str] = set()
    start = 0
    for index, (key_node, value_node) in enumerate(entries):
        key = _scalar(key_node, "frontmatter key")
        last = index == len(entries) - 1
        end = len(header) if last else _line_end(header, value_node.end_mark.index)
        if key in seen:
            raise DocumentError(f"'{key}' appears more than once")
        seen.add(key)
        if key in FIELDS:
            values[key] = value_node
        else:
            extra.append((key, header[start:end]))
        start = end
    post_id = _scalar(values["id"], "id").strip() if "id" in values else ""
    post = Post(
        title=_scalar(values["title"], "title") if "title" in values else "",
        slug=_scalar(values["slug"], "slug").strip() if "slug" in values else "",
        date=_date(_scalar(values["date"], "date").strip())
        if "date" in values
        else None,
        status=_status(_scalar(values["status"], "status").strip())
        if "status" in values
        else PostStatus.PRIVATE,
        categories=_terms(values["categories"], "categories")
        if "categories" in values
        else (),
        tags=_terms(values["tags"], "tags") if "tags" in values else (),
        body=body.strip("\n"),
    )
    return Document(post_id or None, post, tuple(extra))


def _yaml_value(key: str, value: object) -> str:
    return yaml.safe_dump(
        {key: value}, allow_unicode=True, sort_keys=False, width=1_000_000
    )


def serialize_document(document: Document) -> str:
    post = document.post
    lines = []
    if document.post_id is not None:
        if document.post_id.isdigit():
            lines.append(f"id: {document.post_id}\n")
        else:
            lines.append(_yaml_value("id", document.post_id))
    lines.append(_yaml_value("title", post.title))
    if post.slug:
        lines.append(_yaml_value("slug", post.slug))
    if post.date is not None:
        lines.append(f"date: {post.date.isoformat()}\n")
    lines.append(f"status: {post.status}\n")
    lines.append(_yaml_value("categories", list(post.categories)))
    lines.append(_yaml_value("tags", list(post.tags)))
    for _, text in document.extra:
        lines.append(text if text.endswith("\n") else text + "\n")
    header = "".join(lines)
    body = f"\n{post.body}\n" if post.body else ""
    return f"{FENCE}\n{header}{FENCE}\n{body}"


def _load(path: Path) -> Document:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DocumentError(f"cannot read: {error}") from error
    return parse_document(text)


def write_document(path: Path, document: Document) -> None:
    write_text_atomic(path, serialize_document(document), mode=0o644)


def _post_files(posts_dir: Path) -> list[Path]:
    files = []
    for directory, subdirectories, names in os.walk(posts_dir):
        subdirectories[:] = [
            name for name in subdirectories if not name.startswith(".")
        ]
        files.extend(
            Path(directory, name)
            for name in names
            if name.endswith(".md") and not name.startswith(".")
        )
    return sorted(files)


def scan_documents(root: Path) -> list[LocalDocument]:
    """Read every post file under the root, reporting all problems together."""
    documents: list[LocalDocument] = []
    problems: list[str] = []
    for path in _post_files(root / POSTS_DIR):
        relative = path.relative_to(root)
        try:
            documents.append(LocalDocument(relative, _load(path)))
        except DocumentError as error:
            problems.append(f"{relative}: {error}")
    users: dict[str, list[Path]] = {}
    for item in documents:
        if item.document.post_id is not None:
            users.setdefault(item.document.post_id, []).append(item.path)
    for post_id, paths in sorted(users.items()):
        if len(paths) > 1:
            listed = ", ".join(str(path) for path in paths)
            problems.append(
                f"post id {post_id} is used by more than one file: {listed}"
            )
    if problems:
        raise DocumentError("\n".join(problems))
    return documents


def body_checksum(post: Post) -> str:
    return hashlib.sha256(post.body.encode()).hexdigest()


def fields_checksum(post: Post) -> str:
    """One checksum over every synchronized header field."""
    fields = {
        "title": post.title,
        "slug": post.slug,
        "date": post.date.astimezone(UTC).isoformat() if post.date else None,
        "status": post.status.value,
        "categories": list(post.categories),
        "tags": list(post.tags),
    }
    encoded = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()
