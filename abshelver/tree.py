"""The Library tab: the scanned library as a `tree`-style listing of the
files the schema governs (audio and ebooks), with Audiobookshelf links."""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from abshelver import layout, probe
from abshelver.absapi import Links
from abshelver.api import fmt_duration
from abshelver.library import BookFolder, Library, scan

logger = logging.getLogger(__name__)

FOLD_AT = 2  # a book with this many audio files is shown folded: one line, one zip


@dataclass(slots=True)
class Node:
    name: str
    kind: str  # dir | book | fold | file
    url: str | None = None  # dir/book: the Audiobookshelf page
    dl: str | None = None  # file: the download; fold: the zip
    meta: str | None = None  # file/fold: `456 MB`; book: `9h 12m`
    size: int = 0  # file: bytes
    note: str | None = None
    count: int = 0  # fold: number of files inside
    children: list[Node] = field(default_factory=list)


@dataclass(slots=True)
class Tree:
    root: str
    nodes: list[Node]
    summary: str  # `42 books, 4 series, 28 authors`
    linked: bool


@dataclass(slots=True)
class _Dir:
    children: dict[str, _Dir] = field(default_factory=dict)
    book: BookFolder | None = None


def fold_name(names: tuple[str, ...]) -> str:
    """`Kitchen Confidential 01 - Bourdain.mp3` … `… 28 - Bourdain.mp3` as
    `Kitchen Confidential 01…28 - Bourdain.mp3`."""
    first, last = names[0], names[-1]
    i = 0
    while i < min(len(first), len(last)) and first[i] == last[i]:
        i += 1
    # keep a digit run whole: `01` vs `06` differ in the `1`, but show both digits
    while 0 < i < len(first) and first[i - 1].isdigit() and first[i].isdigit():
        i -= 1
    j = 0
    while j < min(len(first), len(last)) - i and first[-1 - j] == last[-1 - j]:
        j += 1
    while (
        j > 0 and j < len(first) - i and first[-j].isdigit() and first[-j - 1].isdigit()
    ):
        j -= 1
    mid_a, mid_b = first[i : len(first) - j], last[i : len(last) - j]
    if not mid_a or not mid_b:
        return f"{len(names)} files"
    return f"{first[:i]}{mid_a}…{mid_b}{first[len(first) - j :]}"


def file_url(book: BookFolder, name: str) -> str:
    return "/files/" + quote((book.rel / name).as_posix())


def zip_url(book: BookFolder) -> str:
    return "/zip/" + quote(book.rel.as_posix())


def fmt_size(n: int) -> str:
    size = float(n)
    unit = "B"
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            break
        size /= 1000
    if unit == "B":
        return f"{int(size)} B"
    return f"{size:.0f} {unit}" if size >= 100 else f"{size:.1f} {unit}"


def _file(root: Path, book: BookFolder, name: str, audio: bool) -> tuple[Node, float]:
    path = root / book.rel / name
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    duration = probe.probe(path).duration if audio and size else 0.0
    node = Node(name=name, kind="file", dl=file_url(book, name), meta=fmt_size(size))
    node.size = size
    return node, duration


def _files(root: Path, book: BookFolder) -> tuple[list[Node], float]:
    """The book folder's file nodes and its total audio duration."""
    audio = [_file(root, book, n, True) for n in book.audio]
    nodes = [n for n, _ in audio]
    duration = sum(d for _, d in audio)
    if len(nodes) >= FOLD_AT:
        nodes = [
            Node(
                name=fold_name(book.audio),
                kind="fold",
                dl=zip_url(book),
                meta=fmt_size(sum(n.size for n in nodes)),
                count=len(nodes),
                children=nodes,
            )
        ]
    return nodes + [_file(root, book, n, False)[0] for n in book.ebooks], duration


def _insert(root: _Dir, book: BookFolder) -> None:
    node = root
    for part in book.rel.parts:
        node = node.children.setdefault(part, _Dir())
    node.book = book


def _first_book(d: _Dir) -> BookFolder | None:
    if d.book:
        return d.book
    for child in d.children.values():
        found = _first_book(child)
        if found:
            return found
    return None


def _convert(
    d: _Dir, depth: int, links: Links | None, path: PurePosixPath, root: Path
) -> list[Node]:
    out: list[Node] = []
    for name in sorted(d.children, key=layout.natural_key):
        child = d.children[name]
        rel = path / name
        if child.book:
            url = links.item_url(rel.as_posix()) if links else None
            files, duration = _files(root, child.book)
            out.append(
                Node(
                    name=name,
                    kind="book",
                    url=url,
                    meta=fmt_duration(duration) if duration else None,
                    note="not in Audiobookshelf" if links and not url else None,
                    children=files,
                )
            )
            continue
        url = None
        if links:
            if depth == 0:
                url = links.author_url(name)
                if not url:
                    book = _first_book(child)
                    if book and book.book and book.book.authors:
                        url = links.author_url(book.book.authors[0])
            elif depth == 1:
                url = links.series_url(name)
                if not url:
                    book = _first_book(child)
                    if book and book.book and book.book.series:
                        url = links.series_url(book.book.series)
        out.append(
            Node(
                name=name,
                kind="dir",
                url=url,
                children=_convert(child, depth + 1, links, rel, root),
            )
        )
    return out


def _root(lib: Library) -> _Dir:
    root = _Dir()
    for book in lib.books:
        _insert(root, book)
    return root


def summary(lib: Library) -> str:
    """`42 books, 4 series, 28 authors`, the line under the library path."""
    root = _root(lib)
    series = sum(
        1
        for author in root.children.values()
        for child in author.children.values()
        if not child.book
    )
    return f"{len(lib.books)} books, {series} series, {len(root.children)} authors"


def build(lib: Library, links: Links | None) -> Tree:
    root = _root(lib)
    return Tree(
        root=str(lib.root),
        nodes=_convert(root, 0, links, PurePosixPath(), lib.root),
        summary=summary(lib),
        linked=links is not None,
    )


def warm(root: Path) -> None:
    """Probe every audio file once so the first Library page is quick. Run in
    a background thread at startup; `probe` memoizes by (path, size, mtime),
    so only new or changed files cost anything later."""
    started = time.monotonic()
    lib = scan(root)
    n = 0
    for book in lib.books:
        for name in book.audio:
            probe.probe(root / book.rel / name)
            n += 1
    logger.info("probed %d audio files in %.1fs", n, time.monotonic() - started)
