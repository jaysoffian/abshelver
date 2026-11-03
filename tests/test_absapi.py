from pathlib import Path

import pytest

from abshelver import absapi
from abshelver.config import Settings

LIBRARIES = {
    "libraries": [
        {"id": "pod", "mediaType": "podcast"},
        {"id": "lib1", "mediaType": "book"},
    ]
}
ITEMS = {
    "results": [
        {"id": "item-wool", "relPath": "Hugh Howey/Silo/1. Wool {Minnie Goode}"}
    ]
}
AUTHORS = {"authors": [{"id": "au-howey", "name": "Hugh  Howey"}]}
SERIES = {"results": [{"id": "se-silo", "name": "Silo"}]}
INDEX = '<html><head><base href="/audiobookshelf/"><title>Audiobookshelf</title>'


@pytest.fixture
def fake_abs(monkeypatch):
    calls = []

    def get(url, token):
        calls.append(url)
        assert token == "key"
        if url.endswith("/api/libraries"):
            return LIBRARIES
        if "/items?" in url:
            return ITEMS
        if url.endswith("/authors"):
            return AUTHORS
        if "/series?" in url:
            return SERIES
        raise AssertionError(url)

    monkeypatch.setattr(absapi, "_get", get)
    monkeypatch.setattr(absapi, "_get_text", lambda url: INDEX)
    absapi.forget()
    yield calls
    absapi.forget()


def settings(url: str | None = "https://abs.example", token: str | None = "key"):
    return Settings(
        import_dir=Path(), library_dir=Path(), abs_url=url, abs_api_key=token
    )


def test_cache_is_stale_right_after_boot(fake_abs, monkeypatch):
    # monotonic counts from boot; a cache stamped 0.0 looked fresh for TTL
    # seconds after the host came up
    monkeypatch.setattr(absapi.time, "monotonic", lambda: 30.0)
    links, error = absapi.links(settings())
    assert error is None
    assert links is not None
    assert fake_abs


def test_fetch_builds_maps(fake_abs):
    links = absapi.fetch("https://abs.example", "key")
    assert links.library_id == "lib1"
    assert links.web == "https://abs.example/audiobookshelf"
    assert (
        links.item_url("Hugh Howey/Silo/1. Wool {Minnie Goode}")
        == "https://abs.example/audiobookshelf/item/item-wool"
    )
    assert (
        links.author_url("hugh howey")
        == "https://abs.example/audiobookshelf/author/au-howey"
    )
    assert (
        links.series_url("SILO")
        == "https://abs.example/audiobookshelf/library/lib1/series/se-silo"
    )
    assert links.item_url("nope") is None
    assert all("/lib1/" in u for u in fake_abs[1:])


def test_web_base():
    assert (
        absapi.web_base("https://abs.example", INDEX)
        == "https://abs.example/audiobookshelf"
    )
    assert (
        absapi.web_base("https://abs.example/audiobookshelf", INDEX)
        == "https://abs.example/audiobookshelf"
    )
    assert absapi.web_base("https://abs.example", "<html>") == "https://abs.example"
    assert (
        absapi.web_base("https://abs.example", '<base href="/">')
        == "https://abs.example"
    )


def test_links_cached_and_optional(fake_abs):
    assert absapi.links(settings(token=None)) == (None, None)
    assert absapi.links(settings(url=None)) == (None, None)
    found, err = absapi.links(settings())
    assert found is not None and err is None
    n = len(fake_abs)
    assert absapi.links(settings())[0] is found
    assert len(fake_abs) == n  # served from the cache


def test_links_failure_is_reported_and_cached(fake_abs, monkeypatch):
    def boom(url, token):
        raise OSError("connection refused")

    monkeypatch.setattr(absapi, "_get", boom)
    found, err = absapi.links(settings())
    assert found is None and err == "OSError: connection refused"
    monkeypatch.setattr(
        absapi,
        "_get",
        lambda url, token: (_ for _ in ()).throw(AssertionError("called")),
    )
    assert absapi.links(settings()) == (None, err)
