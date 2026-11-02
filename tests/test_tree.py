from pathlib import Path

from abshelver import library, tree
from abshelver.absapi import Links
from tests.conftest import write_book

LINKS = Links(
    web="https://abs.example/audiobookshelf",
    library_id="lib1",
    items={
        "Hugh Howey/Silo/1. Wool {Minnie Goode}": "item-wool",
        "Anthony Bourdain/Kitchen Confidential {Anthony Bourdain}": "item-kc",
    },
    authors={"hugh howey": "au-howey", "anthony bourdain": "au-bourdain"},
    series={"silo": "se-silo"},
)


def make_lib(tmp_path: Path) -> library.Library:
    root = tmp_path / "lib"
    write_book(
        root,
        "Hugh Howey/Silo/1. Wool {Minnie Goode}",
        ["Silo 1 - Wool {Minnie Goode} - Hugh Howey.m4b", "cover.jpg"],
        {"title": "Wool", "authors": ["Hugh Howey"], "series": ["Silo #1"]},
    )
    write_book(
        root,
        "Anthony Bourdain/Kitchen Confidential {Anthony Bourdain}",
        [
            f"Kitchen Confidential {{Anthony Bourdain}} {n:02d} - Anthony Bourdain.mp3"
            for n in range(1, 7)
        ]
        + ["Kitchen Confidential {Anthony Bourdain} - Anthony Bourdain.epub"],
        {"title": "Kitchen Confidential", "authors": ["Anthony Bourdain"]},
    )
    write_book(
        root,
        "Ann Patchett/The Dutch House {Tom Hanks}",
        ["The Dutch House {Tom Hanks} - Ann Patchett.mp3"],
        {"title": "The Dutch House", "authors": ["Ann Patchett"]},
    )
    return library.scan(root)


def by_name(nodes, name):
    return next(n for n in nodes if n.name == name)


def test_tree_structure_and_links(tmp_path, fake_ffprobe):
    t = tree.build(make_lib(tmp_path), LINKS)
    assert t.summary == "3 books, 1 series, 3 authors"
    assert [n.name for n in t.nodes] == [
        "Ann Patchett",
        "Anthony Bourdain",
        "Hugh Howey",
    ]

    howey = by_name(t.nodes, "Hugh Howey")
    assert (
        howey.kind == "dir"
        and howey.url == "https://abs.example/audiobookshelf/author/au-howey"
    )
    silo = howey.children[0]
    assert silo.kind == "dir"
    assert silo.url == "https://abs.example/audiobookshelf/library/lib1/series/se-silo"
    wool = silo.children[0]
    assert (
        wool.kind == "book"
        and wool.url == "https://abs.example/audiobookshelf/item/item-wool"
    )
    assert [c.name for c in wool.children] == [
        "Silo 1 - Wool {Minnie Goode} - Hugh Howey.m4b"
    ]
    assert wool.children[0].url is None
    assert wool.children[0].dl == (
        "/files/Hugh%20Howey/Silo/1.%20Wool%20%7BMinnie%20Goode%7D/"
        "Silo%201%20-%20Wool%20%7BMinnie%20Goode%7D%20-%20Hugh%20Howey.m4b"
    )
    assert wool.children[0].meta == "1 B"  # fixture files hold one byte; no duration

    # several mp3s fold into one line; the epub stays its own line
    kc = by_name(t.nodes, "Anthony Bourdain").children[0]
    assert [c.kind for c in kc.children] == ["fold", "file"]
    fold = kc.children[0]
    assert fold.count == 6 and len(fold.children) == 6
    assert (
        fold.dl
        == "/zip/Anthony%20Bourdain/Kitchen%20Confidential%20%7BAnthony%20Bourdain%7D"
    )
    assert fold.meta == "6 B"
    assert (kc.children[1].dl or "").endswith(".epub")
    assert kc.children[1].meta == "1 B"
    assert (
        fold.name
        == "Kitchen Confidential {Anthony Bourdain} 01…06 - Anthony Bourdain.mp3"
    )

    # unknown to ABS: no link, a note; author matched by metadata fails too
    patchett = by_name(t.nodes, "Ann Patchett")
    assert patchett.url is None
    dutch = patchett.children[0]
    assert dutch.url is None and dutch.note == "not in Audiobookshelf"


def test_tree_without_links(tmp_path, fake_ffprobe):
    t = tree.build(make_lib(tmp_path), None)
    assert not t.linked
    assert all(n.url is None and n.note is None for n in t.nodes)
    assert all(b.note is None for a in t.nodes for b in a.children)


def test_fold_name():
    assert tree.fold_name(("A 01.mp3", "A 28.mp3")) == "A 01…28.mp3"
    assert tree.fold_name(("x.mp3", "x.mp3")) == "2 files"
    assert tree.fold_name(("Part 1 of 3.mp3", "Part 3 of 3.mp3")) == "Part 1…3 of 3.mp3"


def test_fmt_size():
    assert tree.fmt_size(0) == "0 B"
    assert tree.fmt_size(999) == "999 B"
    assert tree.fmt_size(12_345) == "12.3 kB"
    assert tree.fmt_size(456_000_000) == "456 MB"
    assert tree.fmt_size(1_234_000_000) == "1.2 GB"


def test_meta_with_duration(tmp_path, fake_ffprobe, monkeypatch):
    lib = make_lib(tmp_path)
    monkeypatch.setattr(
        tree.probe,
        "probe",
        lambda p: tree.probe.Probe(tags={}, duration=33130, codec="aac"),
    )
    t = tree.build(lib, None)
    wool = by_name(t.nodes, "Hugh Howey").children[0].children[0]
    assert wool.meta == "9h 12m"  # duration sits on the book folder
    assert wool.children[0].meta == "1 B"  # files show size only
    kc = by_name(t.nodes, "Anthony Bourdain").children[0]
    assert kc.meta == "55h 13m"  # six files' durations summed
    assert kc.children[0].meta == "6 B"


def test_fold_at_two(tmp_path, fake_ffprobe):
    """Any multi-file book folds, so two tracks get a zip too; one file does not."""
    root = tmp_path / "lib"
    write_book(
        root,
        "Mary Shelley/Frankenstein {Ada Lockwood}",
        [f"Frankenstein {{Ada Lockwood}} 0{n} - Mary Shelley.mp3" for n in (1, 2)],
        {"title": "Frankenstein", "authors": ["Mary Shelley"]},
    )
    write_book(
        root,
        "Jane Austen/Emma {Rosalind Hale}",
        ["Emma {Rosalind Hale} - Jane Austen.m4b"],
        {"title": "Emma", "authors": ["Jane Austen"]},
    )
    t = tree.build(library.scan(root), None)
    frankenstein = by_name(t.nodes, "Mary Shelley").children[0]
    assert [c.kind for c in frankenstein.children] == ["fold"]
    assert frankenstein.children[0].count == 2
    assert (
        frankenstein.children[0].dl
        == "/zip/Mary%20Shelley/Frankenstein%20%7BAda%20Lockwood%7D"
    )
    emma = by_name(t.nodes, "Jane Austen").children[0]
    assert [c.kind for c in emma.children] == ["file"]
