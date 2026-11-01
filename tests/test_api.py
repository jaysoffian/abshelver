import time

import pytest
from fastapi.testclient import TestClient

from abshelver import config
from tests.conftest import write_book
from tests.test_downloads import make_downloads


@pytest.fixture
def client(tmp_path, monkeypatch, fake_ffprobe):
    dl = make_downloads(tmp_path)
    root = tmp_path / "lib"
    write_book(
        root,
        "Ann Patchett/The Dutch House {Tom Hanks}",
        ["The Dutch House - Ann Patchett.mp3"],
        {
            "title": "The Dutch House",
            "authors": ["Ann Patchett"],
            "narrators": ["Tom Hanks"],
        },
    )
    (root / "Empty").mkdir()
    monkeypatch.setenv("ABSHELVER_IMPORT_DIR", str(dl))
    monkeypatch.setenv("ABSHELVER_LIBRARY_DIR", str(root))
    monkeypatch.setenv("AUDIOBOOKSHELF_URL", "https://abs.example/")
    config.get_settings.cache_clear()
    from abshelver.app import app

    with TestClient(app) as c:
        yield c, dl, root
    config.get_settings.cache_clear()


def wait_idle(c):
    for _ in range(100):
        s = c.get("/api/status").json()
        if s["state"] == "idle":
            return s
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_pages(client):
    c, dl, root = client
    assert c.get("/health").json()["status"] == "ok"
    r = c.get("/")
    assert r.status_code == 200
    assert "Dungeon Crawler Carl" in r.text
    assert "Audiobookshelf ↗" in r.text
    r = c.get("/import/Train%20Dreams%20-%20A%20Novella%20-%20Denis%20Johnson")
    assert r.status_code == 200
    assert 'value="Denis Johnson"' in r.text
    assert c.get("/import/nope").status_code == 404
    r = c.get("/organize")
    assert r.status_code == 200
    assert "The Dutch House <mark>{Tom Hanks} </mark>- Ann Patchett.mp3" in r.text
    assert "1 books, 0 clean" in r.text


def test_import_flow(client):
    c, dl, root = client
    rows = c.get("/api/imports").json()
    assert any(
        r["name"] == "A Gentleman in Moscow.m4b" and r["summary"] == "1 × m4b"
        for r in rows
    )
    detail = c.get("/api/imports/Dungeon%20Crawler%20Carl").json()
    assert detail["prefill"]["series"] == "Dungeon Crawler Carl"
    form = {
        "authors": "Matt Dinniman",
        "narrators": "Jeff Hays",
        "title": "Dungeon Crawler Carl",
        "series": "Dungeon Crawler Carl",
        "sequence": "1",
    }
    plan = c.post("/api/imports/Dungeon%20Crawler%20Carl/plan", json=form).json()
    assert (
        plan["dest_dir"]
        == "Matt Dinniman/Dungeon Crawler Carl/1. Dungeon Crawler Carl {Jeff Hays}"
    )
    assert not plan["blocked"]
    r = c.post("/api/imports/Dungeon%20Crawler%20Carl/run", json=form)
    assert r.status_code == 202
    s = wait_idle(c)
    assert s["last"]["ok"], s
    assert (root / plan["dest_dir"] / "metadata.json").exists()
    # the folder stays because of the jpg + cue
    assert (dl / "Dungeon Crawler Carl").is_dir()
    # a second run is blocked: destination exists
    assert (
        c.post("/api/imports/Dungeon%20Crawler%20Carl/run", json=form).status_code
        == 422
    )


def test_organize_flow(client):
    c, dl, root = client
    lib = c.get("/api/library").json()
    ids = {i["kind"]: i["id"] for i in lib["issues"]}
    assert set(ids) == {"audio-name", "empty-dir"}
    plan = c.post("/api/library/plan", json={"ids": [ids["audio-name"]]}).json()
    assert len(plan["ops"]) == 1 and plan["ops"][0]["op"] == "rename"
    assert c.post("/api/library/plan", json={"ids": ["bogus:x"]}).status_code == 409
    assert c.post("/api/library/apply", json={"ids": []}).status_code == 422
    r = c.post("/api/library/apply", json={"ids": list(ids.values())})
    assert r.status_code == 202
    s = wait_idle(c)
    assert s["last"]["ok"], s
    assert c.get("/api/library").json()["issues"] == []
    assert not (root / "Empty").exists()


def test_static_cache_busting(client):
    c, _, _ = client
    html = c.get("/").text
    assert 'href="/static/icon.svg?v=' in html
    assert "/static/fonts/SourceSansPro-Regular.woff2?v=" in html
    assert c.get("/").headers["cache-control"] == "no-cache"
    r = c.get("/static/abshelver.css")
    assert r.headers["cache-control"] == "no-cache"
    r = c.get("/static/abshelver.css?v=abc")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    r = c.get(
        "/static/abshelver.css?v=abc", headers={"If-None-Match": r.headers["etag"]}
    )
    assert r.status_code == 304
