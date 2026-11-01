"""Read-only lookups against the Audiobookshelf API: the ids behind the links
on the Library tab. Nothing here writes to ABS. Needs AUDIOBOOKSHELF_URL and
AUDIOBOOKSHELF_API_KEY (an API key); without them the tab renders unlinked."""

import http.client
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from abshelver.config import Settings
from abshelver.layout import fold

logger = logging.getLogger(__name__)

TIMEOUT = 5.0
TTL = 60.0  # seconds a fetched Links is reused
BASE_HREF_RE = re.compile(r'<base\s+href="([^"]*)"', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Links:
    web: str  # web UI base, e.g. https://abs.example/audiobookshelf
    library_id: str
    items: dict[str, str]  # relPath under the library folder -> item id
    authors: dict[str, str]  # fold(name) -> author id
    series: dict[str, str]  # fold(name) -> series id

    def item_url(self, rel_path: str) -> str | None:
        item_id = self.items.get(rel_path)
        return f"{self.web}/item/{item_id}" if item_id else None

    def author_url(self, name: str) -> str | None:
        author_id = self.authors.get(fold(name))
        return f"{self.web}/author/{author_id}" if author_id else None

    def series_url(self, name: str) -> str | None:
        series_id = self.series.get(fold(name))
        if not series_id:
            return None
        return f"{self.web}/library/{self.library_id}/series/{series_id}"


ATTEMPTS = 3  # a home reverse proxy now and then cuts a response short


def _get(url: str, token: str) -> Any:
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except http.client.HTTPException, OSError:
            if attempt == ATTEMPTS:
                raise
            logger.info("retrying %s (attempt %d)", url, attempt + 1)
    raise AssertionError("unreachable")


def _get_text(url: str) -> str:
    with urlopen(url, timeout=TIMEOUT) as resp:
        return resp.read(65536).decode("utf-8", "replace")


def web_base(abs_url: str, html: str) -> str:
    """ABS behind a ROUTER_BASE_PATH serves its pages under that path, which
    its index page announces as <base href>. Append it unless the configured
    URL already ends with it."""
    m = BASE_HREF_RE.search(html)
    base = (m.group(1) if m else "/").strip("/")
    if not base:
        return abs_url
    if urlsplit(abs_url).path.rstrip("/").endswith("/" + base):
        return abs_url
    return f"{abs_url}/{base}"


def fetch(abs_url: str, token: str) -> Links:
    """Four requests: the libraries (to pick the book library), its items,
    authors and series. Raises on any failure."""
    libraries = _get(f"{abs_url}/api/libraries", token)["libraries"]
    books = [lib for lib in libraries if lib.get("mediaType") == "book"]
    if not books:
        raise LookupError("Audiobookshelf has no book library")
    library_id = books[0]["id"]
    items = _get(
        f"{abs_url}/api/libraries/{library_id}/items?limit=0&minified=1", token
    )
    authors = _get(f"{abs_url}/api/libraries/{library_id}/authors", token)
    series = _get(
        f"{abs_url}/api/libraries/{library_id}/series?limit=1000&minified=1", token
    )
    return Links(
        web=web_base(abs_url, _get_text(abs_url + "/")),
        library_id=library_id,
        items={i["relPath"]: i["id"] for i in items["results"]},
        authors={fold(a["name"]): a["id"] for a in authors["authors"]},
        series={fold(s["name"]): s["id"] for s in series["results"]},
    )


class _Cache:
    lock = threading.Lock()
    at = 0.0  # time.monotonic() of the last fetch attempt
    links: Links | None = None
    error: str | None = None


def links(settings: Settings) -> tuple[Links | None, str | None]:
    """(Links, None) when ABS is configured and answered within the last TTL
    seconds; (None, None) when not configured; (None, reason) on failure.
    Failures are cached for TTL too, so a down ABS costs one request a minute."""
    if not settings.abs_url or not settings.abs_api_key:
        return None, None
    with _Cache.lock:
        if time.monotonic() - _Cache.at < TTL:
            return _Cache.links, _Cache.error
        try:
            _Cache.links, _Cache.error = (
                fetch(settings.abs_url, settings.abs_api_key),
                None,
            )
        except (
            URLError,
            OSError,
            http.client.HTTPException,
            LookupError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            _Cache.links, _Cache.error = None, f"{type(exc).__name__}: {exc}"
            logger.warning("Audiobookshelf lookup failed: %s", _Cache.error)
        _Cache.at = time.monotonic()
        return _Cache.links, _Cache.error


def forget() -> None:
    """Drop the cache (tests)."""
    with _Cache.lock:
        _Cache.at = 0.0
        _Cache.links = _Cache.error = None
