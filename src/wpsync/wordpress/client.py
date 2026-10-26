"""WordPress REST API access with Application Password authentication."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from wpsync import __version__
from wpsync.posts import ContentFormat, PostStatus, PostSummary, RemoteState

API_LINK_RELATION = "https://api.w.org/"
TIMEOUT = httpx.Timeout(30.0)
PAGE_SIZE = 100
SYNCED_STATUSES = "publish,future,draft,pending,private"
STATUSES = {
    "publish": PostStatus.PUBLISHED,
    "future": PostStatus.SCHEDULED,
    "draft": PostStatus.DRAFT,
    "pending": PostStatus.PENDING,
    "private": PostStatus.PRIVATE,
}
HEADERS = {"User-Agent": f"wpsync/{__version__}"}


class WordPressError(Exception):
    """Raised when a WordPress site cannot be reached or rejects a request."""


def request(
    http: httpx.Client, method: str, url: str | httpx.URL, **options: Any
) -> httpx.Response:
    try:
        return http.request(method, url, **options)
    except httpx.HTTPError as error:
        raise WordPressError(f"could not reach {url}: {error}") from error


def discover_api_root(site: str, transport: httpx.BaseTransport | None = None) -> str:
    """Find the REST API root that a WordPress site advertises."""
    with httpx.Client(
        headers=HEADERS, timeout=TIMEOUT, follow_redirects=True, transport=transport
    ) as http:
        response = request(http, "GET", site)
    link = response.links.get(API_LINK_RELATION)
    if link is None or not link.get("url"):
        raise WordPressError(
            f"{site} does not advertise a WordPress REST API "
            f"(HTTP {response.status_code}, no '{API_LINK_RELATION}' link)"
        )
    return link["url"]


def route_url(
    api_root: str, route: str, params: dict[str, Any] | None = None
) -> httpx.URL:
    """Build a route URL for both `/wp-json/` and `?rest_route=` API roots."""
    root = httpx.URL(api_root)
    if "rest_route" in root.params:
        url = root.copy_set_param("rest_route", f"/{route}")
    else:
        url = root.copy_with(path=root.path.rstrip("/") + f"/{route}")
    return url.copy_merge_params(params or {})


def _error_message(response: httpx.Response) -> str:
    try:
        document = response.json()
    except ValueError:
        document = None
    if isinstance(document, dict) and "message" in document:
        detail = f"{document['message']} ({document.get('code', 'unknown')})"
    else:
        detail = response.reason_phrase
    message = f"WordPress rejected the request (HTTP {response.status_code}): {detail}"
    if isinstance(document, dict) and document.get("code") == "rest_not_logged_in":
        message += (
            "\nWordPress ignored the credentials. Application Passwords may be "
            "disabled on this site (they require HTTPS), or the host may strip "
            "the Authorization header before WordPress sees it."
        )
    return message


FINGERPRINT_FIELDS = "id,title,content,slug,status,date_gmt,categories,tags"


def fingerprint(post: dict[str, Any]) -> str:
    """A checksum of the stored fields WPSync synchronizes."""
    fields = {
        "title": post["title"]["raw"],
        "content": post["content"]["raw"],
        "slug": post["slug"],
        "status": post["status"],
        "date_gmt": post["date_gmt"],
        "categories": sorted(post["categories"]),
        "tags": sorted(post["tags"]),
    }
    encoded = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def remote_state(post: dict[str, Any]) -> RemoteState:
    blocks = "<!-- wp:" in post["content"]["raw"]
    return RemoteState(
        fingerprint(post), ContentFormat.BLOCKS if blocks else ContentFormat.HTML
    )


def parse_gmt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class WordPressClient:
    def __init__(
        self,
        api_root: str,
        username: str,
        password: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_root = api_root
        self.http = httpx.Client(
            auth=(username, password),
            headers=HEADERS,
            timeout=TIMEOUT,
            transport=transport,
        )

    def __enter__(self) -> WordPressClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.http.close()

    def get(self, route: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = request(self.http, "GET", route_url(self.api_root, route, params))
        if response.is_error:
            raise WordPressError(_error_message(response))
        return response

    def get_all(self, route: str, params: dict[str, Any]) -> Iterator[Any]:
        page = 1
        while True:
            response = self.get(route, {**params, "per_page": PAGE_SIZE, "page": page})
            yield from response.json()
            if page >= int(response.headers.get("X-WP-TotalPages", "1")):
                return
            page += 1

    def current_user(self) -> dict[str, Any]:
        return self.get("wp/v2/users/me", {"context": "edit"}).json()

    def posts(
        self, fields: str, *, ids: list[str] | None = None, slug: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Posts in the synchronized statuses, oldest first, without trashed posts."""
        params: dict[str, Any] = {
            "context": "edit",
            "status": SYNCED_STATUSES,
            "orderby": "id",
            "order": "asc",
            "_fields": fields,
        }
        if slug is not None:
            params["slug"] = slug
        if ids is None:
            yield from self.get_all("wp/v2/posts", params)
            return
        for start in range(0, len(ids), PAGE_SIZE):
            batch = {**params, "include": ",".join(ids[start : start + PAGE_SIZE])}
            yield from self.get_all("wp/v2/posts", batch)

    def post_summaries(self) -> list[PostSummary]:
        return [
            PostSummary(
                id=str(post["id"]),
                title=post["title"]["raw"],
                slug=post["slug"],
                status=STATUSES[post["status"]],
                date=parse_gmt(post["date_gmt"]),
            )
            for post in self.posts("id,title,slug,status,date_gmt")
        ]

    def post_states(self, ids: list[str]) -> dict[str, RemoteState]:
        """The current state of the given posts; missing or trashed posts are absent."""
        return {
            str(post["id"]): remote_state(post)
            for post in self.posts(FINGERPRINT_FIELDS, ids=ids)
        }

    def term_names(self, taxonomy: str) -> dict[int, str]:
        terms = self.get_all(f"wp/v2/{taxonomy}", {"_fields": "id,name"})
        return {term["id"]: term["name"] for term in terms}

    def site_timezone(self) -> tzinfo:
        """The time zone the site displays dates in."""
        index = self.get("", {"_fields": "timezone_string,gmt_offset"}).json()
        # A site set to a manual UTC offset has no time zone name.
        if index.get("timezone_string"):
            return ZoneInfo(index["timezone_string"])
        return timezone(timedelta(hours=float(index.get("gmt_offset") or 0)))
