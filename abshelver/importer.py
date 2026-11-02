"""Plan and execute an import: mkdir, move audio (+ epub), seed metadata.json,
rmdir the source if it is now empty."""

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel

from abshelver import layout, ops
from abshelver.downloads import Inspection, split_names
from abshelver.layout import Book, fold
from abshelver.library import Library
from abshelver.ops import Op

logger = logging.getLogger(__name__)

Level = Literal["block", "warn", "info"]


class ImportForm(BaseModel):
    authors: str = ""
    narrators: str = ""
    title: str = ""
    series: str = ""
    sequence: str = ""
    include_epub: bool = True
    include_cover: bool = False
    delete_leftovers: bool = False

    def book(self) -> Book:
        return Book(
            title=re.sub(r"\s+", " ", self.title).strip(),
            authors=split_names(self.authors),
            narrators=split_names(self.narrators),
            series=re.sub(r"\s+", " ", self.series).strip() or None,
            sequence=self.sequence.strip() or None,
        )


@dataclass(frozen=True, slots=True)
class Warning:  # noqa: A001 - the builtin is a warning category; this is a UI message
    level: Level
    message: str


@dataclass(frozen=True, slots=True)
class Plan:
    book: Book
    rel_dir: PurePosixPath
    dest_dir: Path
    files: tuple[tuple[Path, Path], ...]  # (source, destination)
    ops: tuple[Op, ...]
    warnings: tuple[Warning, ...]
    leftovers: tuple[Path, ...]  # stay behind
    deletions: tuple[Path, ...]  # removed because the user asked
    removes_source: bool
    cross_device: bool

    @property
    def blocked(self) -> bool:
        return any(w.level == "block" for w in self.warnings)


def seed_metadata(book: Book) -> str:
    """The minimal metadata.json ABS adopts on first scan. Empty keys are
    omitted: `"narrators": []` would clear what the tags provide."""
    data: dict[str, object] = {"title": book.title, "authors": list(book.authors)}
    if book.narrators:
        data["narrators"] = list(book.narrators)
    if book.series_string:
        data["series"] = [book.series_string]
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def similar_name(a: str, b: str) -> bool:
    """Case- and diacritics-insensitive, and tolerant of a middle name or
    initial: `Robert Heinlein` ~ `Robert A. Heinlein`."""
    fa, fb = fold(a), fold(b)
    if fa == fb:
        return True
    wa, wb = fa.split(), fb.split()
    return len(wa) > 1 and len(wb) > 1 and (wa[0], wa[-1]) == (wb[0], wb[-1])


def plan(insp: Inspection, form: ImportForm, lib: Library) -> Plan:
    cand = insp.candidate
    book = form.book()
    warnings: list[Warning] = []
    if not insp.order:
        warnings.append(Warning("block", "No audio files"))
    if not book.title:
        warnings.append(Warning("block", "Title is required"))
    if not book.authors:
        warnings.append(Warning("block", "At least one author is required"))
    if book.sequence and re.search(r"[\s#]", book.sequence):
        warnings.append(Warning("block", "Sequence may not contain spaces or #"))
    if book.sequence and not book.series:
        warnings.append(
            Warning("warn", "Sequence given without a series; it will be ignored")
        )
    if not book.narrators:
        warnings.append(Warning("warn", "No narrators"))

    exp = layout.expected(book, len(insp.order))
    depth = 3 if book.series else 2
    if len(exp.dir.parts) != depth or any(part in ("", ".") for part in exp.dir.parts):
        warnings.append(
            Warning("block", "A name is empty after removing unsafe characters")
        )
    root = lib.root
    dest_dir = root / exp.dir

    author_dir = layout.author_folder(book)
    if author_dir not in lib.author_dirs:
        for existing in lib.author_dirs:
            if similar_name(existing, author_dir):
                warnings.append(
                    Warning(
                        "warn",
                        f"Author folder exists with a different spelling: {existing}",
                    )
                )
                break
    for bf in lib.books:
        if (
            bf.book
            and fold(bf.book.author) == fold(book.author)
            and fold(bf.book.title) == fold(book.title)
        ):
            warnings.append(
                Warning("info", f"Title already exists under this author: {bf.rel}")
            )
            break
    if dest_dir.exists() and not dest_dir.is_dir():
        warnings.append(Warning("block", f"Destination is not a folder: {exp.dir}"))

    files: list[tuple[Path, Path]] = []
    for src, stem in zip(insp.order, exp.audio_stems, strict=True):
        files.append((src, dest_dir / (stem + src.suffix.lower())))
    leftovers = list(cand.leftovers)
    epub = cand.ebooks[0] if cand.ebooks else None
    if epub and form.include_epub:
        files.append((epub, dest_dir / exp.epub_name))
        leftovers.extend(cand.ebooks[1:])
    else:
        leftovers.extend(cand.ebooks)
    # The first image becomes `cover.<ext>`, which ABS adopts as the cover.
    # Images not imported are leftovers like any other, so they may be deleted.
    if cand.images and form.include_cover:
        cover = cand.images[0]
        files.append((cover, dest_dir / ("cover" + cover.suffix.lower())))
        spare_images = cand.images[1:]
    else:
        spare_images = cand.images
    leftovers.extend(spare_images)
    deletable = [*cand.leftovers, *spare_images]
    # Only an actual overwrite blocks. An existing book folder has a
    # metadata.json, so that is the collision that catches duplicates.
    warnings.extend(
        Warning("block", f"Destination file exists: {dst.name}")
        for dst in [*(d for _, d in files), dest_dir / "metadata.json"]
        if os.path.lexists(dst)
    )

    cross = bool(insp.order) and ops.is_cross_device(insp.order[0], dest_dir)
    if cross:
        warnings.append(
            Warning(
                "info",
                "Import and library directories are on different filesystems: files will be copied, verified, then deleted",
            )
        )

    # Leftovers (cue, nfo, dot-files, images not used as the cover) stay
    # unless asked; an epub that was not imported is never deleted.
    deletions = deletable if form.delete_leftovers else []
    leftovers = [x for x in leftovers if x not in deletions]
    removes_source = cand.is_dir and not leftovers and not cand.truncated
    plan_ops: list[Op] = [Op("mkdir", dst=dest_dir)]
    # `move` renames when it can and falls back to copy+verify+delete on EXDEV,
    # which also happens between two bind mounts of one filesystem.
    plan_ops.extend(Op("move", src, dst) for src, dst in files)
    plan_ops.append(
        Op("write", dst=dest_dir / "metadata.json", content=seed_metadata(book))
    )
    plan_ops.extend(Op("delete", x) for x in deletions)
    if removes_source:
        plan_ops.extend(Op("rmdir", d) for d in cand.dirs)
        plan_ops.append(Op("rmdir", cand.path))

    return Plan(
        book=book,
        rel_dir=exp.dir,
        dest_dir=dest_dir,
        files=tuple(files),
        ops=tuple(plan_ops),
        warnings=tuple(warnings),
        leftovers=tuple(sorted(leftovers, key=lambda p: layout.natural_key(str(p)))),
        deletions=tuple(sorted(deletions, key=lambda p: layout.natural_key(str(p)))),
        removes_source=removes_source,
        cross_device=cross,
    )


def execute(p: Plan, progress: Callable[[int], None] | None = None) -> None:
    if p.blocked:
        raise ops.OpError(
            "Plan is blocked: "
            + "; ".join(w.message for w in p.warnings if w.level == "block")
        )
    logger.info(
        "import: %s → %s (%d ops)",
        p.files[0][0].parent if p.files else "?",
        p.rel_dir,
        len(p.ops),
    )
    ops.execute(list(p.ops), progress)
    logger.info("import: done %s", p.rel_dir)
