"""A fake WordPress REST API and CLI helpers shared by the tests."""

import base64
import io

import httpx

from bpsync.cli import run
from bpsync.config import Profile

SITE = "https://blog.test"
PASSWORD = "abcd efgh ijkl mnop"


class FakeWordPress:
    """Serves the REST API responses bpsync reads, as WordPress shapes them."""

    def __init__(self, post_count=3, rest_route=False, can_edit=True):
        self.rest_route = rest_route
        self.can_edit = can_edit
        self.requests = []
        self.posts = [
            {
                "id": number,
                "title": {"raw": f"Post {number}"},
                "content": {"raw": f"<p>Body {number}</p>"},
                "slug": f"post-{number}",
                "status": "publish" if number % 2 else "draft",
                "date_gmt": f"2026-01-{number % 28 + 1:02d}T10:00:00",
                "categories": [1],
                "tags": [],
            }
            for number in range(1, post_count + 1)
        ]

    categories = {1: "News", 2: "Travel"}
    tags = {5: "python"}

    def post(self, post_id):
        return next(post for post in self.posts if post["id"] == int(post_id))

    @property
    def api_root(self):
        return f"{SITE}/?rest_route=/" if self.rest_route else f"{SITE}/wp-json/"

    def route(self, request):
        if self.rest_route:
            return request.url.params.get("rest_route")
        prefix = "/wp-json"
        path = request.url.path
        return path[len(prefix) :] if path.startswith(prefix + "/") else None

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path.startswith("/wp-content/uploads/"):
            return httpx.Response(200, content=b"image:" + request.url.path.encode())
        route = self.route(request)
        if route is None:
            link = f'<{self.api_root}>; rel="https://api.w.org/"'
            return httpx.Response(200, headers={"Link": link}, text="<html></html>")
        expected = "Basic " + base64.b64encode(f"emrah:{PASSWORD}".encode()).decode()
        if request.headers.get("Authorization") != expected:
            return httpx.Response(
                401,
                json={
                    "code": "incorrect_password",
                    "message": (
                        "The provided password is an invalid application password."
                    ),
                },
            )
        if route == "/wp/v2/users/me":
            return httpx.Response(
                200,
                json={
                    "roles": ["administrator"],
                    "capabilities": {
                        "edit_posts": self.can_edit,
                        "unfiltered_html": True,
                    },
                },
            )
        if route == "/":
            return httpx.Response(
                200, json={"timezone_string": "Europe/Istanbul", "gmt_offset": 3}
            )
        if route in ("/wp/v2/categories", "/wp/v2/tags"):
            terms = self.categories if route.endswith("categories") else self.tags
            return httpx.Response(
                200,
                json=[{"id": i, "name": n} for i, n in terms.items()],
                headers={"X-WP-TotalPages": "1"},
            )
        if route == "/wp/v2/posts":
            per_page = int(request.url.params["per_page"])
            page = int(request.url.params["page"])
            posts = self.posts
            if "include" in request.url.params:
                wanted = {int(i) for i in request.url.params["include"].split(",")}
                posts = [post for post in posts if post["id"] in wanted]
            if "slug" in request.url.params:
                posts = [p for p in posts if p["slug"] == request.url.params["slug"]]
            pages = max(1, -(-len(posts) // per_page))
            chunk = posts[(page - 1) * per_page : page * per_page]
            return httpx.Response(
                200, json=chunk, headers={"X-WP-TotalPages": str(pages)}
            )
        return httpx.Response(
            404, json={"code": "rest_no_route", "message": "No route"}
        )


def invoke(arguments, store, *, stdin="", wordpress=None, password=PASSWORD):
    stdout, stderr = io.StringIO(), io.StringIO()
    status = run(
        arguments,
        store=store,
        stdin=stdin if hasattr(stdin, "readline") else io.StringIO(stdin),
        stdout=stdout,
        stderr=stderr,
        environ={"MYBLOG_WP_PASSWORD": password} if password else {},
        transport=httpx.MockTransport(wordpress or FakeWordPress()),
    )
    return status, stdout.getvalue(), stderr.getvalue()


def add_profile(store, name, root):
    configuration = store.load()
    configuration.add(
        name,
        Profile(
            SITE, f"{SITE}/wp-json/", "emrah", "MYBLOG_WP_PASSWORD", root.resolve()
        ),
    )
    store.save(configuration)
