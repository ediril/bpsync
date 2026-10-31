"""WordPress posts in WPSync's platform-neutral form."""

from __future__ import annotations

import re
from datetime import tzinfo
from typing import Any
from urllib.parse import unquote

import httpx

from wpsync.media import Media, MissingImage
from wpsync.posts import Conversion, FetchedPost, Post
from wpsync.wordpress.client import (
    FINGERPRINT_FIELDS,
    HEADERS,
    TIMEOUT,
    WordPressClient,
    WordPressError,
    local_status,
    parse_gmt,
    remote_state,
    request,
)
from wpsync.wordpress.content import to_markdown

PULL_FIELDS = FINGERPRINT_FIELDS + ",generated_slug,link"


class WordPressRemote:
    """Reads posts and media from one WordPress site."""

    def __init__(
        self, client: WordPressClient, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.client = client
        # Images are often served from another host, so this client never
        # carries the site's credentials.
        self.downloads = httpx.Client(
            headers=HEADERS, timeout=TIMEOUT, follow_redirects=True, transport=transport
        )
        self._timezone: tzinfo | None = None
        self._terms: dict[str, dict[int, str]] = {}

    def close(self) -> None:
        self.downloads.close()

    def fetch_posts(
        self, ids: list[str] | None = None, slug: str | None = None
    ) -> list[FetchedPost]:
        return [
            self._fetched(post)
            for post in self.client.posts(PULL_FIELDS, ids=ids, slug=slug)
        ]

    def convert(self, post: FetchedPost, media: Media) -> Conversion:
        return to_markdown(post.content, media)

    def download(self, url: str) -> bytes:
        response = request(self.downloads, "GET", url)
        if response.status_code in (404, 410):
            raise MissingImage(url)
        if response.is_error:
            raise WordPressError(
                f"could not download {url} (HTTP {response.status_code})"
            )
        # Some servers answer a missing file with a web page and a 200.
        if not response.headers.get("content-type", "").startswith("image/"):
            raise MissingImage(url)
        return response.content

    def _fetched(self, post: dict[str, Any]) -> FetchedPost:
        if self._timezone is None:
            self._timezone = self.client.site_timezone()
        names = {
            taxonomy: self._term_names(taxonomy) for taxonomy in ("categories", "tags")
        }
        fields = Post(
            title=post["title"]["raw"],
            slug=unquote(post["slug"]),
            date=parse_gmt(post["date_gmt"]).astimezone(self._timezone),
            status=local_status(post["status"]),
            categories=tuple(
                sorted({names["categories"][i] for i in post["categories"]})
            ),
            tags=tuple(sorted({names["tags"][i] for i in post["tags"]})),
        )
        return FetchedPost(
            str(post["id"]),
            fields,
            post["content"]["raw"],
            remote_state(post),
            _file_stem(post),
            post["link"],
        )

    def _term_names(self, taxonomy: str) -> dict[int, str]:
        if taxonomy not in self._terms:
            self._terms[taxonomy] = self.client.term_names(taxonomy)
        return self._terms[taxonomy]


def _file_stem(post: dict[str, Any]) -> str:
    slug = unquote(post["slug"] or post.get("generated_slug") or "")
    slug = re.sub(r"[/\\:\x00]", "-", slug).strip(".-")
    return slug or f"post-{post['id']}"
