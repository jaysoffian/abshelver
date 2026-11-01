"""Turn ticked organize issues into an ordered op list, and apply it."""

import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from abshelver import audit, library, ops
from abshelver.audit import Issue
from abshelver.ops import Op

logger = logging.getLogger(__name__)


class PlanError(Exception):
    pass


def plan_indexed(
    lib: library.Library, issues: list[Issue], selected: Iterable[str]
) -> tuple[list[Op], dict[str, int]]:
    """Ops for the selected issue ids: file renames, then deletes, then
    rmdirs deepest-first, then folder renames deepest-first. Also returns the
    index of each issue's op, so a UI can tick rows as they complete."""
    wanted = set(selected)
    by_id = {i.id: i for i in issues}
    missing = sorted(wanted - by_id.keys())
    if missing:
        raise PlanError(
            f"No such issue (the library changed since the scan?): {', '.join(missing)}"
        )
    chosen = [by_id[i] for i in sorted(wanted)]
    for issue in chosen:
        if not issue.actionable:
            raise PlanError(
                f"Not applicable: {issue.id} ({issue.blocked or issue.kind})"
            )

    root = lib.root
    result: list[Op] = []
    index: dict[str, int] = {}

    def add(issue: Issue, op: Op) -> None:
        index[issue.id] = len(result)
        result.append(op)

    files = [i for i in chosen if i.kind in ("audio-name", "ebook-name")]
    for issue in sorted(files, key=lambda i: str(i.src)):
        assert issue.src and issue.dst
        add(issue, Op("rename", root / issue.src, root / issue.dst))

    # Deletes and rmdirs use pre-rename paths, so they must run before any
    # folder rename moves the directory they live in.
    for issue in sorted(
        (i for i in chosen if i.kind == "stray"), key=lambda i: str(i.src)
    ):
        assert issue.src
        add(issue, Op("delete", root / issue.src))

    empties = [i for i in chosen if i.kind == "empty-dir"]
    for issue in sorted(
        empties, key=lambda i: (-len(i.src.parts) if i.src else 0, str(i.src))
    ):
        assert issue.src
        add(issue, Op("rmdir", root / issue.src))

    folders = [i for i in chosen if i.kind == "folder"]
    made: set[Path] = set()
    for issue in sorted(
        folders, key=lambda i: (-len(i.src.parts) if i.src else 0, str(i.src))
    ):
        assert issue.src and issue.dst
        parent = root / issue.dst.parent
        if not parent.exists() and parent not in made:
            result.append(Op("mkdir", dst=parent))
            made.add(parent)
        add(issue, Op("rename", root / issue.src, root / issue.dst))

    targets = [op.dst for op in result if op.kind == "rename"]
    dupes = sorted({str(t) for t in targets if targets.count(t) > 1})
    if dupes:
        raise PlanError(f"Two renames share a destination: {', '.join(dupes)}")
    return result, index


def plan(
    lib: library.Library, issues: list[Issue], selected: Iterable[str]
) -> list[Op]:
    return plan_indexed(lib, issues, selected)[0]


def rescan(root: Path) -> tuple[library.Library, list[Issue]]:
    lib = library.scan(root)
    return lib, audit.audit(lib)


def apply(
    root: Path, selected: Iterable[str], progress: Callable[[int], None] | None = None
) -> list[Op]:
    """Re-validate against the live filesystem, then execute. Any selected
    issue that no longer exists aborts before the first write."""
    lib, issues = rescan(root)
    todo = plan(lib, issues, selected)
    logger.info("organize: applying %d ops", len(todo))
    ops.execute(todo, progress)
    logger.info("organize: done")
    return todo
