from pathlib import PurePosixPath

import pytest

from abshelver import layout
from abshelver.layout import Book


def test_standalone():
    b = Book("The Dutch House", ("Ann Patchett",), ("Tom Hanks",))
    e = layout.expected(b, 1)
    assert e.dir == PurePosixPath("Ann Patchett/The Dutch House {Tom Hanks}")
    assert e.audio_stems == ("The Dutch House {Tom Hanks} - Ann Patchett",)
    assert e.epub_name == "The Dutch House {Tom Hanks} - Ann Patchett.epub"


def test_series():
    b = Book("Wool", ("Hugh Howey",), ("Minnie Goode",), "Silo", "1")
    e = layout.expected(b, 1)
    assert e.dir == PurePosixPath("Hugh Howey/Silo/1. Wool {Minnie Goode}")
    assert e.audio_stems == ("Silo 1 - Wool {Minnie Goode} - Hugh Howey",)


def test_fractional_sequence():
    b = Book("Interlude", ("A",), ("N",), "S", "1.5")
    assert layout.expected_dir(b) == PurePosixPath("A/S/1.5. Interlude {N}")
    assert layout.audio_stem(b) == "S 1.5 - Interlude {N} - A"


def test_series_without_sequence():
    b = Book("Interlude", ("A",), ("N",), "S", None)
    assert layout.expected_dir(b) == PurePosixPath("A/S/Interlude {N}")
    assert layout.audio_stem(b) == "Interlude {N} - A"
    assert b.series_string == "S"


def test_no_narrator():
    b = Book("Stoner", ("John Williams",))
    assert layout.expected_dir(b) == PurePosixPath("John Williams/Stoner")
    assert layout.audio_stem(b) == "Stoner - John Williams"


def test_three_narrators_and_two_authors():
    b = Book(
        "Good Omens",
        ("Terry Pratchett", "Neil Gaiman"),
        ("Clare Corbett", "Louise Brealey", "India Fisher"),
    )
    e = layout.expected(b, 1)
    assert e.dir == PurePosixPath(
        "Terry Pratchett, Neil Gaiman/Good Omens {Clare Corbett, Louise Brealey, India Fisher}"
    )
    assert e.audio_stems == (
        "Good Omens {Clare Corbett, Louise Brealey, India Fisher} - Terry Pratchett, Neil Gaiman",
    )


def test_multi_file():
    b = Book("Kitchen Confidential", ("Anthony Bourdain",), ("Anthony Bourdain",))
    stems = layout.audio_stems(b, 28)
    assert len(stems) == 28
    assert stems[0] == "Kitchen Confidential 01 {Anthony Bourdain} - Anthony Bourdain"
    assert stems[-1] == "Kitchen Confidential 28 {Anthony Bourdain} - Anthony Bourdain"
    assert layout.audio_stems(b, 100)[0].startswith("Kitchen Confidential 001 {")
    series = Book("Wool", ("Hugh Howey",), ("Minnie Goode",), "Silo", "1")
    assert (
        layout.audio_stems(series, 3)[1]
        == "Silo 1 - Wool 02 {Minnie Goode} - Hugh Howey"
    )
    # the epub never carries a track number
    assert (
        layout.expected(b, 28).epub_name
        == "Kitchen Confidential {Anthony Bourdain} - Anthony Bourdain.epub"
    )


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Train Dreams: A Novella", "Train Dreams - A Novella"),
        ("A LitRPG/Gamelit Adventure", "A LitRPG - Gamelit Adventure"),
        ("What? Really*", "What Really"),
        ("  Trailing dots...  ", "Trailing dots"),
        ("Tab\tand\x00control", "Tab andcontrol"),
        ("Ends - : - with", "Ends - with"),
        ("L'Étranger — naïve", "L'Étranger — naïve"),
        ("Slaughterhouse-Five", "Slaughterhouse-Five"),
    ],
)
def test_sanitize(raw, clean):
    assert layout.sanitize(raw) == clean


def test_sanitize_applies_to_generated_names():
    b = Book(
        "Dungeon Crawler Carl: A LitRPG/Gamelit Adventure",
        ("Matt Dinniman",),
        ("Jeff Hays",),
    )
    assert (
        layout.book_folder(b)
        == "Dungeon Crawler Carl - A LitRPG - Gamelit Adventure {Jeff Hays}"
    )


def test_file_kinds():
    assert layout.is_audio("x.M4B")
    assert layout.is_audio("All You Zombies - Robert Heinlein.aac")
    assert not layout.is_audio("All You Zombies - Robert Heinlein.tmp.aac")
    assert not layout.is_audio("x.part.mp3")
    assert layout.is_ebook("x.epub")
    assert not layout.is_ebook("x.pdf")
    assert layout.is_abs_file("cover.jpg")
    assert layout.is_abs_file("cover.png")
    assert layout.is_abs_file("metadata.json")
    assert not layout.is_abs_file("metadata.abs")


def test_fold_and_natural_key():
    assert layout.fold("Robert  Heinlein") == layout.fold("robert heinlein")
    assert layout.fold("Émile Zola") == layout.fold("emile zola")
    names = ["t10.mp3", "t2.mp3", "t1.mp3"]
    assert sorted(names, key=layout.natural_key) == ["t1.mp3", "t2.mp3", "t10.mp3"]
