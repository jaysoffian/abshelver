"""A fixture tree reproducing every row of the issue table, plus the ops."""

from pathlib import PurePosixPath

import pytest

from abshelver import audit, library, ops, organizer
from tests.conftest import write_book


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    # clean single-file book
    write_book(
        root,
        "Kurt Vonnegut/Slaughterhouse-Five {Ethan Hawke}",
        ["Slaughterhouse-Five {Ethan Hawke} - Kurt Vonnegut.m4b", "cover.png"],
        {
            "title": "Slaughterhouse-Five",
            "authors": ["Kurt Vonnegut"],
            "narrators": ["Ethan Hawke"],
            "series": [],
        },
    )
    # audio-name: narrator missing from the stem
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
    # audio-name + stray with an audio extension
    write_book(
        root,
        "Robert A. Heinlein/All You Zombies {Paul Lawley-Jones}",
        [
            "All You Zombies - Robert Heinlein.aac",
            "All You Zombies - Robert Heinlein.tmp.aac",
            "cover.jpg",
        ],
        {
            "title": "All You Zombies",
            "authors": ["Robert A. Heinlein"],
            "narrators": ["Paul Lawley-Jones"],
        },
    )
    # ebook-name
    write_book(
        root,
        "Ottessa Moshfegh/Eileen {Alyssa Bresnahan}",
        [
            "Eileen {Alyssa Bresnahan} - Ottessa Moshfegh.m4b",
            "Eileen - Ottessa Moshfegh.epub",
        ],
        {
            "title": "Eileen",
            "authors": ["Ottessa Moshfegh"],
            "narrators": ["Alyssa Bresnahan"],
        },
    )
    # folder: title in metadata differs from the folder
    write_book(
        root,
        "Martha Wells/Murderbot Diaries/4. Exit Strategy {Kevin R. Free}",
        ["Murderbot Diaries 4 - All Systems Red {Kevin R. Free} - Martha Wells.m4b"],
        {
            "title": "All Systems Red",
            "authors": ["Martha Wells"],
            "narrators": ["Kevin R. Free"],
            "series": ["Murderbot Diaries #4"],
        },
    )
    # folder: author spelled differently, series folder missing -> needs mkdir
    write_book(
        root,
        "Robert Heinlein/Starship Troopers {Lloyd James}",
        ["Starship Troopers {Lloyd James} - Robert Anson Heinlein.m4b"],
        {
            "title": "Starship Troopers",
            "authors": ["Robert Anson Heinlein"],
            "narrators": ["Lloyd James"],
        },
    )
    # multi-file: three tracks, wrong names
    write_book(
        root,
        "Anthony Bourdain/Kitchen Confidential {Anthony Bourdain}",
        [
            "Kitchen Confidential - 001.mp3",
            "Kitchen Confidential - 002.mp3",
            "Kitchen Confidential - 003.mp3",
        ],
        {
            "title": "Kitchen Confidential",
            "authors": ["Anthony Bourdain"],
            "narrators": ["Anthony Bourdain"],
        },
    )
    # no-metadata
    write_book(root, "Nobody/Unscanned {X}", ["Unscanned.m4b"])
    # empty dir and loose files
    (root / "Kurt Vonnegut/Slaughterhouse-Five {Ethan Hawk}").mkdir()
    (root / ".abook-org.log").write_text("")
    return root


def by_kind(issues):
    out = {}
    for i in issues:
        out.setdefault(i.kind, []).append(i)
    return out


def test_issue_table(tree):
    lib = library.scan(tree)
    issues = audit.audit(lib)
    kinds = by_kind(issues)
    assert len(lib.books) == 8

    audio = {i.src.name: i.dst.name for i in kinds["audio-name"]}
    assert (
        audio["The Dutch House - Ann Patchett.mp3"]
        == "The Dutch House {Tom Hanks} - Ann Patchett.mp3"
    )
    assert (
        audio["All You Zombies - Robert Heinlein.aac"]
        == "All You Zombies {Paul Lawley-Jones} - Robert A. Heinlein.aac"
    )
    assert (
        audio["Kitchen Confidential - 001.mp3"]
        == "Kitchen Confidential 01 {Anthony Bourdain} - Anthony Bourdain.mp3"
    )
    assert (
        audio["Kitchen Confidential - 003.mp3"]
        == "Kitchen Confidential 03 {Anthony Bourdain} - Anthony Bourdain.mp3"
    )
    assert "Slaughterhouse-Five {Ethan Hawke} - Kurt Vonnegut.m4b" not in audio

    [ebook] = kinds["ebook-name"]
    assert ebook.dst.name == "Eileen {Alyssa Bresnahan} - Ottessa Moshfegh.epub"

    folders = {i.src.as_posix(): i.dst.as_posix() for i in kinds["folder"]}
    assert (
        folders["Martha Wells/Murderbot Diaries/4. Exit Strategy {Kevin R. Free}"]
        == "Martha Wells/Murderbot Diaries/4. All Systems Red {Kevin R. Free}"
    )
    assert (
        folders["Robert Heinlein/Starship Troopers {Lloyd James}"]
        == "Robert Anson Heinlein/Starship Troopers {Lloyd James}"
    )

    strays = {i.src.as_posix(): i for i in kinds["stray"]}
    assert (
        "audio extension"
        in strays[
            "Robert A. Heinlein/All You Zombies {Paul Lawley-Jones}/All You Zombies - Robert Heinlein.tmp.aac"
        ].note
    )
    assert ".abook-org.log" in strays
    assert all(not i.default_on for i in kinds["stray"])

    [empty] = kinds["empty-dir"]
    assert empty.src == PurePosixPath("Kurt Vonnegut/Slaughterhouse-Five {Ethan Hawk}")
    assert not empty.default_on

    assert "multi-file" not in kinds  # several tracks is normal, not a finding

    [nometa] = kinds["no-metadata"]
    assert nometa.block == PurePosixPath("Nobody/Unscanned {X}")
    assert not nometa.actionable

    assert audit.clean_count(lib, issues) == 1  # Slaughterhouse-Five


def test_ordered_ops(tree):
    lib = library.scan(tree)
    issues = audit.audit(lib)
    ops = organizer.plan(lib, issues, [i.id for i in issues if i.actionable])
    kinds = [op.kind for op in ops]
    # file renames, then deletes, then rmdirs, then (mkdir +) folder renames
    first_delete = kinds.index("delete")
    assert all(k == "rename" for k in kinds[:first_delete])
    assert kinds.count("delete") == 2
    assert kinds.index("rmdir") > first_delete
    assert kinds.index("mkdir") > kinds.index("rmdir")
    mk = next(op for op in ops if op.kind == "mkdir")
    assert mk.dst == tree / "Robert Anson Heinlein"
    folder_op = next(
        op
        for op in ops
        if op.kind == "rename"
        and op.src == tree / "Robert Heinlein/Starship Troopers {Lloyd James}"
    )
    assert ops.index(folder_op) > ops.index(mk)


def test_stray_inside_renamed_folder(tmp_path):
    write_book(
        tmp_path,
        "A/T",
        ["T {N} - A.m4b", "notes.txt"],
        {"title": "T", "authors": ["A"], "narrators": ["N"]},
    )
    (tmp_path / "A/T/old").mkdir()
    lib = library.scan(tmp_path)
    issues = audit.audit(lib)
    assert sorted(i.kind for i in issues) == ["empty-dir", "folder", "stray"]
    organizer.apply(tmp_path, [i.id for i in issues if i.actionable])
    assert (tmp_path / "A/T {N}/T {N} - A.m4b").exists()
    assert not (tmp_path / "A/T {N}/notes.txt").exists()
    assert not (tmp_path / "A/T {N}/old").exists()


def test_duplicate_destination_is_refused(tmp_path):
    meta = {"title": "T", "authors": ["A"], "narrators": ["N"]}
    write_book(tmp_path, "A/T v1", ["T {N} - A.m4b"], meta)
    write_book(tmp_path, "A/T v2", ["T {N} - A.m4b"], meta)
    lib = library.scan(tmp_path)
    issues = audit.audit(lib)
    with pytest.raises(organizer.PlanError, match="share a destination"):
        organizer.plan(lib, issues, [i.id for i in issues if i.actionable])


def test_folder_rename_into_own_subtree_is_blocked(tmp_path):
    write_book(
        tmp_path,
        "A",
        ["T {N} - A.m4b"],
        {"title": "T", "authors": ["A"], "narrators": ["N"]},
    )
    issues = audit.audit(library.scan(tmp_path))
    folder = next(i for i in issues if i.kind == "folder")
    assert folder.blocked == "Destination is inside the source"


def test_abs_files_and_dotfiles(tmp_path):
    write_book(
        tmp_path,
        "A/T {N}",
        ["._T {N} - A.m4b", "T {N} - A.m4b", ".DS_Store"],
        {"title": "T", "authors": ["A"], "narrators": ["N"]},
    )
    (tmp_path / "A/T {N}/CD1").mkdir()
    (tmp_path / "A/T {N}/CD1/01.mp3").write_bytes(b"x")
    (tmp_path / "A/Other").mkdir()
    (tmp_path / "A/Other/metadata.json").write_text("{}")
    (tmp_path / "A/Other/cover.jpg").write_bytes(b"x")
    (tmp_path / "A/Other/notes.txt").write_bytes(b"x")
    lib = library.scan(tmp_path)
    book = next(b for b in lib.books if b.rel.as_posix() == "A/T {N}")
    assert book.audio == ("T {N} - A.m4b",)  # the AppleDouble file is not audio
    assert set(book.strays) == {"._T {N} - A.m4b", ".DS_Store"}
    assert [p.as_posix() for p in lib.loose_files] == ["A/Other/notes.txt"]


def test_plan_rejects_unknown_and_informational(tree):
    lib = library.scan(tree)
    issues = audit.audit(lib)
    with pytest.raises(organizer.PlanError):
        organizer.plan(lib, issues, ["audio-name:nope"])
    nometa = next(i for i in issues if i.kind == "no-metadata")
    with pytest.raises(organizer.PlanError):
        organizer.plan(lib, issues, [nometa.id])


def test_blocked_when_destination_exists(tmp_path):
    root = tmp_path
    write_book(
        root,
        "A/T {N}",
        ["T - A.m4b", "T {N} - A.m4b"],
        {"title": "T", "authors": ["A"], "narrators": ["N"]},
    )
    issues = audit.audit(library.scan(root))
    # two audio files -> multi-file naming; the first wants "T {N} 01 - A.m4b" (free), fine.
    # Make a real collision: folder rename onto an existing dir.
    write_book(
        root,
        "B/X {N}",
        ["X {N} - B.m4b"],
        {"title": "X", "authors": ["B"], "narrators": ["N"]},
    )
    write_book(
        root,
        "B/X",
        ["X {N} - B.m4b"],
        {"title": "X", "authors": ["B"], "narrators": ["N"]},
    )
    issues = audit.audit(library.scan(root))
    folder = next(
        i for i in issues if i.kind == "folder" and i.src and i.src.as_posix() == "B/X"
    )
    assert folder.blocked == "Destination already exists"
    assert not folder.actionable


def test_apply_against_tmp(tree):
    lib = library.scan(tree)
    issues = audit.audit(lib)
    selected = [i.id for i in issues if i.actionable]
    organizer.apply(tree, selected)
    lib2, issues2 = organizer.rescan(tree)
    # everything actionable is gone; only the informational rows remain, plus
    # the author dir left empty by moving Starship Troopers
    kinds = sorted(i.kind for i in issues2)
    assert kinds == ["empty-dir", "no-metadata"]
    assert (tree / "Robert Anson Heinlein/Starship Troopers {Lloyd James}").is_dir()
    assert (
        tree
        / "Ann Patchett/The Dutch House {Tom Hanks}/The Dutch House {Tom Hanks} - Ann Patchett.mp3"
    ).exists()
    assert not (tree / ".abook-org.log").exists()


def test_parse_metadata():
    b = library.parse_metadata(
        {
            "title": " Wool ",
            "authors": ["Hugh Howey"],
            "narrators": ["Minnie Goode"],
            "series": ["Silo #1"],
        }
    )
    assert (b.title, b.series, b.sequence) == ("Wool", "Silo", "1")
    b = library.parse_metadata(
        {"title": "X", "authors": ["A"], "series": ["Just a Name"]}
    )
    assert (b.series, b.sequence) == ("Just a Name", None)
    b = library.parse_metadata(
        {"title": "X", "authors": ["A"], "narrators": None, "series": []}
    )
    assert b.narrators == () and b.series is None
    with pytest.raises(ValueError, match="authors"):
        library.parse_metadata({"title": "X", "authors": []})
    with pytest.raises(ValueError, match="title"):
        library.parse_metadata({"authors": ["A"]})


def test_execute_stops_at_first_failure_with_reason(tmp_path):
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "b").write_bytes(b"x")
    (tmp_path / "c").write_bytes(b"x")
    todo = [
        ops.Op("rename", tmp_path / "a", tmp_path / "a2"),
        ops.Op("rename", tmp_path / "b", tmp_path / "c"),  # target exists
        ops.Op("rename", tmp_path / "c", tmp_path / "c2"),
    ]
    done: list[int] = []
    with pytest.raises(ops.OpError) as info:
        ops.execute(todo, done.append)
    assert done == [0]
    assert info.value.reason == f"Target exists: {tmp_path / 'c'}"
    assert str(info.value).startswith("rename ")
    assert (
        (tmp_path / "a2").exists()
        and (tmp_path / "b").exists()
        and (tmp_path / "c").exists()
    )


def test_case_only_rename_is_allowed(tmp_path):
    (tmp_path / "x.M4B").write_bytes(b"x")
    ops.execute([ops.Op("rename", tmp_path / "x.M4B", tmp_path / "x.m4b")])
    assert [p.name for p in tmp_path.iterdir()] == ["x.m4b"]
