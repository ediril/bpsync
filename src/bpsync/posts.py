"""Platform-neutral post types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ContentFormat(StrEnum):
    BLOCKS = "blocks"
    HTML = "html"


class PostStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    PENDING = "pending"
    PRIVATE = "private"


@dataclass(frozen=True)
class Post:
    """The synchronized fields of a post. Terms are sorted and unique."""

    title: str = ""
    slug: str = ""
    date: datetime | None = None
    status: PostStatus = PostStatus.DRAFT
    categories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    body: str = ""


@dataclass(frozen=True)
class PostSummary:
    id: str
    title: str
    slug: str
    status: PostStatus
    date: datetime


@dataclass(frozen=True)
class RemoteState:
    """What a post looks like on the platform, reduced to what sync compares."""

    fingerprint: str
    format: ContentFormat


@dataclass(frozen=True)
class FetchedPost:
    """A post as the platform stores it, before its content is converted."""

    id: str
    post: Post
    """Every field except the body, which conversion produces."""
    content: str
    state: RemoteState
    name: str
    """The file name stem the post prefers, usually its slug."""


@dataclass(frozen=True)
class Conversion:
    """A post body converted to Markdown."""

    markdown: str
    kept: tuple[str, ...]
    """Descriptions of elements kept as the platform's markup."""


class UnrepresentableContent(ValueError):
    """Content whose display cannot be reproduced, even keeping it as source."""
