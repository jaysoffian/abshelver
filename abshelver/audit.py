"""Compare each book folder with its expected layout and list the deviations.

Pure: takes a scanned Library, returns Issues. Nothing here touches disk.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from abshelver import layout
from abshelver.library import BookFolder, Library

Kind = Literal[
    "folder",
    "audio-name",
    "ebook-name",
    "stray",
    "empty-dir",
    "no-metadata",
]

ACTIONABLE: frozenset[str] = frozenset(
    {"folder", "audio-name", "ebook-name", "stray", "empty-dir"}
)
DEFAULT_ON: frozenset[str] = frozenset({"folder", "audio-name", "ebook-name"})


@dataclass(frozen=True, slots=True)
class Issue:
    kind: Kind
    block: PurePosixPath  # the book folder (or container) this belongs to
    src: PurePosixPath | None  # current path, relative to the library root
    dst: PurePosixPath | None  # expected path; None for informational issues
    note: str = ""
    blocked: str | None = None  # why this can't be applied (e.g. target exists)

    @property
    def id(self) -> str:
        return (
            f"{self.kind}:{self.src.as_posix() if self.src else self.block.as_posix()}"
        )

    @property
    def actionable(self) -> bool:
        return self.kind in ACTIONABLE and self.blocked is None

    @property
    def default_on(self) -> bool:
        return self.actionable and self.kind in DEFAULT_ON

    @property
    def op(self) -> str:
        if self.kind == "stray":
            return "delete"
        if self.kind == "empty-dir":
            return "rmdir"
        return "rename"


def _occupied(library: Library) -> set[PurePosixPath]:
    """Every path that exists in the scanned tree, so renames can be checked
    for collisions without touching disk."""
    paths: set[PurePosixPath] = set()
    for bf in library.books:
        paths.add(bf.rel)
        for name in (*bf.audio, *bf.ebooks, *bf.abs_files, *bf.strays):
            paths.add(bf.rel / name)
    paths.update(library.empty_dirs)
    paths.update(library.loose_files)
    for p in list(paths):
        paths.update(p.parents)
    paths.discard(PurePosixPath())
    return paths


def audit_book(bf: BookFolder, occupied: set[PurePosixPath]) -> list[Issue]:
    issues: list[Issue] = []
    for name in bf.strays:
        note = (
            "Has an audio extension; ABS lists it as a library file"
            if layout.AUDIO_EXTENSIONS & {PurePosixPath(name).suffix.lower()}
            else ""
        )
        issues.append(Issue("stray", bf.rel, bf.rel / name, None, note))
    issues.extend(
        Issue(
            "stray",
            bf.rel,
            bf.rel / name,
            None,
            "More than one epub; only the first is kept",
        )
        for name in bf.ebooks[1:]
    )
    if bf.book is None:
        note = bf.metadata_error or "No metadata.json: not scanned by ABS yet"
        issues.append(Issue("no-metadata", bf.rel, None, None, note))
        return issues

    exp = layout.expected(bf.book, len(bf.audio))

    def rename(kind: Kind, src: PurePosixPath, dst: PurePosixPath) -> None:
        if src == dst:
            return
        blocked = None
        if dst in occupied:
            blocked = "Destination already exists"
        elif src == PurePosixPath() or dst.is_relative_to(src):
            blocked = "Destination is inside the source"
        issues.append(Issue(kind, bf.rel, src, dst, blocked=blocked))

    for name, stem in zip(bf.audio, exp.audio_stems, strict=True):
        rename(
            "audio-name",
            bf.rel / name,
            bf.rel / (stem + PurePosixPath(name).suffix.lower()),
        )
    if bf.ebooks:
        rename("ebook-name", bf.rel / bf.ebooks[0], bf.rel / exp.epub_name)
    rename("folder", bf.rel, exp.dir)
    return issues


def audit(library: Library) -> list[Issue]:
    occupied = _occupied(library)
    issues: list[Issue] = []
    for bf in library.books:
        issues.extend(audit_book(bf, occupied))
    issues.extend(
        Issue("stray", rel.parent, rel, None, "File outside a book folder")
        for rel in library.loose_files
    )
    issues.extend(
        Issue("empty-dir", rel.parent, rel, None) for rel in library.empty_dirs
    )
    return issues


def clean_count(library: Library, issues: list[Issue]) -> int:
    dirty = {i.block for i in issues}
    return sum(1 for bf in library.books if bf.rel not in dirty)
