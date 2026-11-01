"""Walk the library and read each book folder's metadata.json."""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from abshelver import layout
from abshelver.layout import Book

logger = logging.getLogger(__name__)

SERIES_RE = re.compile(r"^(.*?)\s*#([^#\s]+)$")


@dataclass(frozen=True, slots=True)
class BookFolder:
    """A directory under the library that directly contains audio."""

    rel: PurePosixPath  # relative to the library root
    book: Book | None  # None when metadata.json is missing or unreadable
    metadata_error: str | None
    audio: tuple[str, ...]  # file names, natural order
    ebooks: tuple[str, ...]
    abs_files: tuple[str, ...]
    strays: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.rel.name


@dataclass(frozen=True, slots=True)
class Library:
    root: Path
    books: tuple[BookFolder, ...]
    empty_dirs: tuple[PurePosixPath, ...]
    loose_files: tuple[PurePosixPath, ...]  # files outside any book folder
    author_dirs: tuple[str, ...] = field(default=())


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(s.strip() for s in value if isinstance(s, str) and s.strip())


def parse_metadata(data: object) -> Book:
    """Build a Book from ABS's metadata.json object."""
    if not isinstance(data, dict):
        raise ValueError("metadata.json is not an object")
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("metadata.json has no title")
    authors = _strings(data.get("authors"))
    if not authors:
        raise ValueError("metadata.json has no authors")
    series_name = sequence = None
    series = _strings(data.get("series"))
    if series:
        m = SERIES_RE.match(series[0])
        if m:
            series_name, sequence = m.group(1).strip(), m.group(2)
        else:
            series_name = series[0]
        series_name = series_name or None
    return Book(
        title=title.strip(),
        authors=authors,
        narrators=_strings(data.get("narrators")),
        series=series_name,
        sequence=sequence,
    )


def read_metadata(path: Path) -> tuple[Book | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"Unreadable metadata.json: {exc}"
    try:
        return parse_metadata(data), None
    except ValueError as exc:
        return None, str(exc)


def classify(
    names: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    audio, ebooks, abs_files, strays = [], [], [], []
    for name in sorted(names, key=layout.natural_key):
        if layout.is_audio(name):
            audio.append(name)
        elif layout.is_ebook(name):
            ebooks.append(name)
        elif layout.is_abs_file(name):
            abs_files.append(name)
        else:
            strays.append(name)
    return tuple(audio), tuple(ebooks), tuple(abs_files), tuple(strays)


def scan(root: Path) -> Library:
    books: list[BookFolder] = []
    empty_dirs: list[PurePosixPath] = []
    loose: list[PurePosixPath] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort(key=layout.natural_key)
        here = Path(dirpath)
        rel = (
            PurePosixPath(here.relative_to(root).as_posix())
            if here != root
            else PurePosixPath()
        )
        if not filenames and not dirnames and here != root:
            empty_dirs.append(rel)
            continue
        audio, ebooks, abs_files, strays = classify(filenames)
        if audio:
            book, error = read_metadata(here / "metadata.json")
            books.append(
                BookFolder(
                    rel=rel,
                    book=book,
                    metadata_error=error,
                    audio=audio,
                    ebooks=ebooks,
                    abs_files=abs_files,
                    strays=strays,
                )
            )
        else:
            loose.extend(
                rel / name
                for name in sorted(filenames, key=layout.natural_key)
                if not layout.is_abs_file(name)
            )
    author_dirs = tuple(sorted(p.name for p in root.iterdir() if p.is_dir()))
    return Library(
        root=root,
        books=tuple(books),
        empty_dirs=tuple(empty_dirs),
        loose_files=tuple(loose),
        author_dirs=author_dirs,
    )
