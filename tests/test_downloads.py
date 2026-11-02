"""Prefill from the captured tags of the six real downloads."""

from pathlib import Path

import pytest

from abshelver import downloads


def make_downloads(tmp_path: Path) -> Path:
    d = tmp_path / "downloads"
    d.mkdir()
    (d / "A Gentleman in Moscow.m4b").write_bytes(b"x")
    kc = d / "Anthony Bourdain - Kitchen Confidential - mp3"
    kc.mkdir()
    for n in range(1, 29):
        (kc / f"Kitchen Confidential - {n:03d}.mp3").write_bytes(b"x")
    dcc = d / "Dungeon Crawler Carl"
    dcc.mkdir()
    for ext in ("m4b", "jpg", "cue"):
        (dcc / f"Dungeon Crawler Carl꞉ A LitRPG∕Gamelit Adventure.{ext}").write_bytes(
            b"x"
        )
    (d / "Dungeon Crawler Carl - Season 1 - Audio Immersion Tunnel.m4b").write_bytes(
        b"x"
    )
    mr = d / "Medium Raw"
    mr.mkdir()
    (mr / "Medium Raw.mp3").write_bytes(b"x")
    (mr / "Medium Raw.jpg").write_bytes(b"x")
    td = d / "Train Dreams - A Novella - Denis Johnson"
    td.mkdir()
    (td / "Train Dreams - A Novella - Denis Johnson.m4b").write_bytes(b"x")
    (td / "Train Dreams - A Novella - Denis Johnson (2002).epub").write_bytes(b"x")
    (d / ".DS_Store").write_bytes(b"x")
    (d / "notes.txt").write_text("not an audiobook")
    return d


@pytest.fixture
def dl(tmp_path, fake_ffprobe):
    return make_downloads(tmp_path)


def inspect(dl: Path, name: str) -> downloads.Inspection:
    cand = downloads.find(dl, name)
    assert cand is not None
    return downloads.inspect(cand)


def test_scan_lists_entries(dl):
    cands = downloads.scan(dl)
    names = [c.name for c in cands]
    assert ".DS_Store" not in names
    assert "notes.txt" in names
    by = {c.name: c for c in cands}
    assert by["A Gentleman in Moscow.m4b"].summary == "1 × m4b"
    assert by["Anthony Bourdain - Kitchen Confidential - mp3"].summary == "28 × mp3"
    assert by["Train Dreams - A Novella - Denis Johnson"].summary == "1 × m4b + epub"
    assert by["notes.txt"].summary == "no audio"
    dcc = by["Dungeon Crawler Carl"]
    assert [x.suffix for x in dcc.images] == [".jpg"]
    assert [x.suffix for x in dcc.leftovers] == [".cue"]
    assert all(
        c.name != ".DS_Store" for c in cands
    )  # top-level dot-entries are skipped


def test_gentleman(dl):
    p = inspect(dl, "A Gentleman in Moscow.m4b").prefill
    assert p.authors == ("Amor Towles",)
    assert p.narrators == ("Nicholas Guy Smith",)
    assert p.title == "A Gentleman in Moscow"  # album, not the "- A Novel" title tag
    assert p.series == "" and p.sequence == ""


def test_dungeon_crawler_carl(dl):
    insp = inspect(dl, "Dungeon Crawler Carl")
    p = insp.prefill
    assert p.authors == ("Matt Dinniman",)
    assert p.narrators == ("Jeff Hays",)
    assert p.title == "Dungeon Crawler Carl"  # "(Unabridged)" stripped
    assert p.series == "Dungeon Crawler Carl"
    assert p.sequence == "1"
    assert insp.duration > 48000


def test_audio_immersion_tunnel(dl):
    p = inspect(
        dl, "Dungeon Crawler Carl - Season 1 - Audio Immersion Tunnel.m4b"
    ).prefill
    assert p.title == "Dungeon Crawler Carl Audio Immersion Tunnel"
    assert p.narrators == ("Jeff Hays",)


def test_train_dreams(dl):
    insp = inspect(dl, "Train Dreams - A Novella - Denis Johnson")
    p = insp.prefill
    assert p.authors == ("Denis Johnson",)
    assert p.narrators == ()
    assert p.title == "Train Dreams: A Novella"
    assert len(insp.candidate.ebooks) == 1


def test_medium_raw(dl):
    p = inspect(dl, "Medium Raw").prefill
    assert p.authors == ("Anthony Bourdain",)  # trailing space stripped
    assert p.title == "Medium Raw"


def test_kitchen_confidential(dl):
    insp = inspect(dl, "Anthony Bourdain - Kitchen Confidential - mp3")
    p = insp.prefill
    assert p.authors == (
        "Anthony Bourdain",
    )  # "Anthony Bourdain/Anthony Bourdain" deduped
    assert p.narrators == ()
    assert p.title == "Kitchen Confidential - Adventures in the Culinary Underbelly"
    assert len(insp.order) == 28
    assert [f.name for f in insp.order][:2] == [
        "Kitchen Confidential - 001.mp3",
        "Kitchen Confidential - 002.mp3",
    ]
    assert insp.notes == ()


def test_split_names():
    assert downloads.split_names("Anthony Bourdain/Anthony Bourdain") == (
        "Anthony Bourdain",
    )
    assert downloads.split_names("A; B , c") == ("A", "B", "c")
    assert downloads.split_names("") == ()
    assert downloads.split_names(None) == ()


def test_find_rejects_traversal(dl):
    assert downloads.find(dl, "../etc") is None
    assert downloads.find(dl, ".hidden") is None
    assert downloads.find(dl, "missing") is None


def test_track_order_falls_back_to_natural_sort(dl, fake_ffprobe):
    d = dl / "Set"
    d.mkdir()
    for n in ("10", "2", "1"):
        (d / f"part {n}.mp3").write_bytes(b"x")
    insp = inspect(dl, "Set")
    assert [f.name for f in insp.order] == ["part 1.mp3", "part 2.mp3", "part 10.mp3"]
    assert any("no track tag" in n for n in insp.notes)
    assert (
        insp.prefill.title == ""
    )  # multi-file with no album: never the per-track title


def test_cover_default(dl, tmp_path):
    # the m4b has embedded art: offer the jpg, but unticked
    insp = inspect(dl, "Dungeon Crawler Carl")
    assert insp.first is not None and insp.first.cover
    assert [x.suffix for x in insp.candidate.images] == [".jpg"]
    assert not insp.cover_default
    # no audio art at all: ticked; `cover.*`/`folder.*` sort first
    kc = dl / "Anthony Bourdain - Kitchen Confidential - mp3"
    (kc / "back.png").write_bytes(b"x")
    (kc / "folder.jpg").write_bytes(b"x")
    insp = inspect(dl, "Anthony Bourdain - Kitchen Confidential - mp3")
    assert insp.first is not None and not insp.first.cover
    assert [x.name for x in insp.candidate.images] == ["folder.jpg", "back.png"]
    assert insp.cover_default
