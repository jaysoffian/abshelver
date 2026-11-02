"""The naming schema. Pure functions from a Book to its expected paths.

    {Author}/{Title} {Narrators}/{Title} {Narrators} - {Author}.ext
    {Author}/{Series}/{N}. {Title} {Narrators}/{Series} {N} - {Title} {Narrators} - {Author}.ext

Multi-file books get ` {TT}` after the title, before the narrators. The
epub shares the single-file stem. Everything here depends on one book's metadata alone.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

AUDIO_EXTENSIONS = frozenset({".m4b", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".opus"})
EBOOK_EXTENSIONS = frozenset({".epub"})
# Offered as the book's cover on import; ABS reads any of these as `cover.*`.
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
# Files ABS owns inside a book folder; left alone by organize.
ABS_FILE_RE = re.compile(r"^(cover\.[^.]+|metadata\.json)$")
# `.tmp`/`.part`-style inner extensions mark leftovers of interrupted writes;
# ABS's watcher ignores them, and so do we (they are strays, not audio).
TEMP_STEM_RE = re.compile(r"\.(tmp|part|partial|crdownload)$", re.IGNORECASE)

SEP = " - "


@dataclass(frozen=True, slots=True)
class Book:
    """What a book *is*, independent of where its files happen to live."""

    title: str
    authors: tuple[str, ...]
    narrators: tuple[str, ...] = ()
    series: str | None = None
    sequence: str | None = None

    @property
    def author(self) -> str:
        return join_names(self.authors)

    @property
    def series_string(self) -> str | None:
        """ABS's `"Name #seq"` form, as it appears in metadata.json."""
        if not self.series:
            return None
        return f"{self.series} #{self.sequence}" if self.sequence else self.series


@dataclass(frozen=True, slots=True)
class Expected:
    dir: PurePosixPath  # relative to the library root
    audio_stems: tuple[str, ...]  # one per audio file, in track order
    epub_name: str


def join_names(names: tuple[str, ...] | list[str]) -> str:
    return ", ".join(names)


def sanitize(component: str) -> str:
    """Make one path component safe. `/ \\ :` become ` - `; `? * " < > |`
    and control characters vanish; whitespace and repeated separators are
    collapsed; leading/trailing whitespace and trailing dots are stripped.
    Apostrophes, hyphens, accents and other Unicode are kept."""
    s = re.sub(r"[/\\:]", SEP, component)
    s = re.sub(r'[?*"<>|]', "", s)
    s = re.sub(r"\s+", " ", s)
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")
    s = re.sub(r"( -)+ ", SEP, s)
    return s.strip().rstrip(".").strip()


def narrators_suffix(book: Book) -> str:
    return f" {{{join_names(book.narrators)}}}" if book.narrators else ""


def title_part(book: Book) -> str:
    """`{Title} {Narrators}`, the part shared by the folder and the stem."""
    return sanitize(f"{book.title}{narrators_suffix(book)}")


def author_folder(book: Book) -> str:
    return sanitize(book.author)


def series_folder(book: Book) -> str | None:
    return sanitize(book.series) if book.series else None


def book_folder(book: Book) -> str:
    if book.series and book.sequence:
        return sanitize(f"{book.sequence}. {book.title}{narrators_suffix(book)}")
    return title_part(book)


def expected_dir(book: Book) -> PurePosixPath:
    parts = [author_folder(book)]
    series = series_folder(book)
    if series:
        parts.append(series)
    parts.append(book_folder(book))
    return PurePosixPath(*parts)


def audio_stem(book: Book) -> str:
    """Single-file stem: `{Title} {Narrators} - {Author}` or
    `{Series} {N} - {Title} {Narrators} - {Author}`."""
    head = (
        f"{book.series} {book.sequence}{SEP}" if book.series and book.sequence else ""
    )
    return sanitize(f"{head}{book.title}{narrators_suffix(book)}{SEP}{book.author}")


def track_width(count: int) -> int:
    return 3 if count >= 100 else 2


def track_stem(book: Book, index: int, count: int) -> str:
    """Multi-file stem for the `index`-th (1-based) of `count` files."""
    head = (
        f"{book.series} {book.sequence}{SEP}" if book.series and book.sequence else ""
    )
    tt = f"{index:0{track_width(count)}d}"
    return sanitize(
        f"{head}{book.title} {tt}{narrators_suffix(book)}{SEP}{book.author}"
    )


def audio_stems(book: Book, count: int) -> tuple[str, ...]:
    if count == 0:
        return ()
    if count == 1:
        return (audio_stem(book),)
    return tuple(track_stem(book, i, count) for i in range(1, count + 1))


def expected(book: Book, audio_count: int) -> Expected:
    return Expected(
        dir=expected_dir(book),
        audio_stems=audio_stems(book, audio_count),
        epub_name=audio_stem(book) + ".epub",
    )


def _media(name: str, extensions: frozenset[str]) -> bool:
    # Dot-files (`._foo.m4b` AppleDouble, `.hidden`) are never media.
    p = PurePosixPath(name)
    return (
        not name.startswith(".")
        and p.suffix.lower() in extensions
        and not TEMP_STEM_RE.search(p.stem)
    )


def is_audio(name: str) -> bool:
    return _media(name, AUDIO_EXTENSIONS)


def is_ebook(name: str) -> bool:
    return _media(name, EBOOK_EXTENSIONS)


def is_image(name: str) -> bool:
    return _media(name, IMAGE_EXTENSIONS)


def is_abs_file(name: str) -> bool:
    return ABS_FILE_RE.match(name) is not None


def fold(name: str) -> str:
    """Case- and diacritics-insensitive key for comparing names."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().casefold()


_NATURAL_RE = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple[object, ...]:
    return tuple(
        int(tok) if tok.isdigit() else tok.casefold() for tok in _NATURAL_RE.split(name)
    )
