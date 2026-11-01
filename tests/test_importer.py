import json
from dataclasses import asdict

import pytest

from abshelver import downloads, importer, library
from abshelver.importer import ImportForm
from tests.conftest import write_book
from tests.test_downloads import make_downloads


@pytest.fixture
def env(tmp_path, fake_ffprobe):
    dl = make_downloads(tmp_path)
    root = tmp_path / "lib"
    root.mkdir()
    write_book(
        root,
        "Anthony Bourdain/Medium Raw {Anthony Bourdain}",
        ["Medium Raw - Anthony Bourdain.mp3"],
        {
            "title": "Medium Raw",
            "authors": ["Anthony Bourdain"],
            "narrators": ["Anthony Bourdain"],
        },
    )
    write_book(
        root,
        "Robert A. Heinlein/All You Zombies {P}",
        ["x.aac"],
        {"title": "All You Zombies", "authors": ["Robert A. Heinlein"]},
    )
    return dl, root


def plan_for(dl, root, name, **form):
    cand = downloads.find(dl, name)
    assert cand
    insp = downloads.inspect(cand)
    if form:
        f = ImportForm(**form)
    else:
        pre = asdict(insp.prefill)
        f = ImportForm(
            authors=", ".join(pre["authors"]),
            narrators=", ".join(pre["narrators"]),
            title=pre["title"],
            series=pre["series"],
            sequence=pre["sequence"],
        )
    return insp, importer.plan(insp, f, library.scan(root))


def test_series_import_plan(env):
    dl, root = env
    insp, p = plan_for(dl, root, "Dungeon Crawler Carl")
    assert (
        p.rel_dir.as_posix()
        == "Matt Dinniman/Dungeon Crawler Carl/1. Dungeon Crawler Carl {Jeff Hays}"
    )
    [(src, dst)] = p.files
    assert (
        dst.name
        == "Dungeon Crawler Carl 1 - Dungeon Crawler Carl {Jeff Hays} - Matt Dinniman.m4b"
    )
    assert not p.blocked
    assert not p.removes_source  # jpg + cue stay behind
    assert [x.suffix for x in p.leftovers] == [".cue", ".jpg"]
    kinds = [op.kind for op in p.ops]
    assert kinds == ["mkdir", "move", "write"]
    seed = json.loads(p.ops[-1].content or "")
    assert seed == {
        "title": "Dungeon Crawler Carl",
        "authors": ["Matt Dinniman"],
        "narrators": ["Jeff Hays"],
        "series": ["Dungeon Crawler Carl #1"],
    }


def test_delete_leftovers(env):
    dl, root = env
    insp, p = plan_for(
        dl,
        root,
        "Dungeon Crawler Carl",
        authors="Matt Dinniman",
        narrators="Jeff Hays",
        title="Dungeon Crawler Carl",
        series="Dungeon Crawler Carl",
        sequence="1",
        delete_leftovers=True,
    )
    assert [op.kind for op in p.ops] == [
        "mkdir",
        "move",
        "write",
        "delete",
        "delete",
        "rmdir",
    ]
    assert [x.suffix for x in p.deletions] == [".cue", ".jpg"]
    assert p.leftovers == () and p.removes_source
    importer.execute(p)
    assert not insp.candidate.path.exists()
    assert (root / p.rel_dir / "metadata.json").exists()
    # an epub that is not imported is never deleted
    _, p = plan_for(
        dl,
        root,
        "Train Dreams - A Novella - Denis Johnson",
        authors="Denis Johnson",
        title="Train Dreams",
        include_epub=False,
        delete_leftovers=True,
    )
    assert (
        p.deletions == ()
        and [x.suffix for x in p.leftovers] == [".epub"]
        and not p.removes_source
    )


def test_seed_omits_empty_keys():
    from abshelver.layout import Book

    seed = json.loads(importer.seed_metadata(Book("Train Dreams", ("Denis Johnson",))))
    assert seed == {"title": "Train Dreams", "authors": ["Denis Johnson"]}
    seed = json.loads(importer.seed_metadata(Book("X", ("A",), series="S")))
    assert seed["series"] == ["S"]


def test_epub_and_rmdir(env):
    dl, root = env
    insp, p = plan_for(
        dl,
        root,
        "Train Dreams - A Novella - Denis Johnson",
        authors="Denis Johnson",
        narrators="Will Patton",
        title="Train Dreams",
    )
    assert p.rel_dir.as_posix() == "Denis Johnson/Train Dreams {Will Patton}"
    names = sorted(dst.name for _, dst in p.files)
    assert names == [
        "Train Dreams {Will Patton} - Denis Johnson.epub",
        "Train Dreams {Will Patton} - Denis Johnson.m4b",
    ]
    assert p.removes_source
    assert p.ops[-1].kind == "rmdir" and p.ops[-1].src == insp.candidate.path
    assert any(w.level == "warn" for w in p.warnings) is False
    # untick the epub: it becomes a leftover and the folder stays
    _, p2 = plan_for(
        dl,
        root,
        "Train Dreams - A Novella - Denis Johnson",
        authors="Denis Johnson",
        narrators="Will Patton",
        title="Train Dreams",
        include_epub=False,
    )
    assert not p2.removes_source
    assert len(p2.files) == 1


def test_bare_file_import(env):
    dl, root = env
    insp, p = plan_for(dl, root, "A Gentleman in Moscow.m4b")
    assert (
        p.rel_dir.as_posix() == "Amor Towles/A Gentleman in Moscow {Nicholas Guy Smith}"
    )
    assert not p.removes_source
    assert [op.kind for op in p.ops] == ["mkdir", "move", "write"]


def test_warnings(env):
    dl, root = env
    _, p = plan_for(dl, root, "Medium Raw")  # title exists; narrators blank
    msgs = {
        w.level: [x.message for x in p.warnings if x.level == w.level]
        for w in p.warnings
    }
    assert any("already exists under this author" in m for m in msgs["info"])
    assert "No narrators" in msgs["warn"]
    assert not p.blocked

    _, p = plan_for(dl, root, "Medium Raw", authors="Robert Heinlein", title="X")
    assert any(
        "different spelling: Robert A. Heinlein" in w.message for w in p.warnings
    )

    _, p = plan_for(
        dl,
        root,
        "Medium Raw",
        authors="Anthony Bourdain",
        narrators="Anthony Bourdain",
        title="Medium Raw",
    )
    assert p.blocked
    assert any(
        "Destination file exists: metadata.json" in w.message for w in p.warnings
    )

    _, p = plan_for(dl, root, "Medium Raw", authors="A", title="T", sequence="1 a")
    assert any("spaces or #" in w.message for w in p.warnings) and p.blocked
    _, p = plan_for(dl, root, "Medium Raw", authors="A", title="T", sequence="2")
    assert any("without a series" in w.message for w in p.warnings)
    _, p = plan_for(dl, root, "Medium Raw", authors="", title="")
    assert p.blocked
    _, p = plan_for(dl, root, "Medium Raw", authors="?", title="T")
    assert any("empty after removing" in w.message for w in p.warnings) and p.blocked


def test_dotfiles_keep_the_source_folder(env):
    dl, root = env
    (dl / "Train Dreams - A Novella - Denis Johnson/.DS_Store").write_bytes(b"x")
    _, p = plan_for(
        dl,
        root,
        "Train Dreams - A Novella - Denis Johnson",
        authors="Denis Johnson",
        title="Train Dreams",
    )
    assert not p.removes_source
    assert [x.name for x in p.leftovers] == [".DS_Store"]


def test_multi_file_execute(env):
    dl, root = env
    insp, p = plan_for(
        dl,
        root,
        "Anthony Bourdain - Kitchen Confidential - mp3",
        authors="Anthony Bourdain",
        narrators="Anthony Bourdain",
        title="Kitchen Confidential",
    )
    assert (
        p.blocked is False
    )  # existing library folder has a different narrator-less title? no: title differs (Medium Raw)
    assert (
        p.files[0][1].name
        == "Kitchen Confidential 01 {Anthony Bourdain} - Anthony Bourdain.mp3"
    )
    assert (
        p.files[27][1].name
        == "Kitchen Confidential 28 {Anthony Bourdain} - Anthony Bourdain.mp3"
    )
    assert p.removes_source
    importer.execute(p)
    dest = root / "Anthony Bourdain/Kitchen Confidential {Anthony Bourdain}"
    assert len(list(dest.glob("*.mp3"))) == 28
    assert json.loads((dest / "metadata.json").read_text())["narrators"] == [
        "Anthony Bourdain"
    ]
    assert not insp.candidate.path.exists()


def test_only_overwrites_block(env):
    dl, root = env
    dest = root / "Amor Towles/A Gentleman in Moscow {Nicholas Guy Smith}"
    dest.mkdir(parents=True)
    (dest / "cover.jpg").write_bytes(b"x")  # unrelated content is fine
    _, p = plan_for(dl, root, "A Gentleman in Moscow.m4b")
    assert not p.blocked
    (dest / "A Gentleman in Moscow {Nicholas Guy Smith} - Amor Towles.m4b").write_bytes(
        b"x"
    )
    _, p = plan_for(dl, root, "A Gentleman in Moscow.m4b")
    assert p.blocked
    assert any(w.message.endswith("- Amor Towles.m4b") for w in p.warnings)


def test_empty_destination_folder_is_reused(env):
    dl, root = env
    (root / "Amor Towles/A Gentleman in Moscow {Nicholas Guy Smith}").mkdir(
        parents=True
    )
    _, p = plan_for(dl, root, "A Gentleman in Moscow.m4b")
    assert not p.blocked
    assert not any("exists" in w.message for w in p.warnings)
    importer.execute(p)
    assert (
        root / "Amor Towles/A Gentleman in Moscow {Nicholas Guy Smith}/metadata.json"
    ).exists()


def test_execute_refuses_blocked(env):
    dl, root = env
    _, p = plan_for(
        dl,
        root,
        "Medium Raw",
        authors="Anthony Bourdain",
        narrators="Anthony Bourdain",
        title="Medium Raw",
    )
    with pytest.raises(importer.ops.OpError):
        importer.execute(p)
    assert (dl / "Medium Raw/Medium Raw.mp3").exists()
