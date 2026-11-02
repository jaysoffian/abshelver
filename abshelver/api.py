"""JSON API, the one-at-a-time job runner, and the view-model helpers the
HTML pages share with it."""

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from abshelver import audit, downloads, importer, library, organizer
from abshelver.audit import Issue
from abshelver.config import get_settings
from abshelver.layout import fold
from abshelver.ops import Op, OpError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# --- jobs -------------------------------------------------------------------


class Jobs:
    """One job at a time. Status is a plain dict the poller returns verbatim."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self.status: dict[str, Any] = {"state": "idle", "last": None}

    @property
    def running(self) -> bool:
        return self._lock.locked()

    async def start(
        self,
        kind: str,
        ops: list[Op],
        run: Callable[[Callable[[int], None]], object],
        result: dict[str, Any],
    ) -> None:
        if self._lock.locked():
            raise HTTPException(409, "A job is already running")
        await self._lock.acquire()
        lines = [op.line for op in ops]
        self.status = {
            "state": "running",
            "kind": kind,
            "ops": lines,
            "done": 0,
            "current": lines[0] if lines else None,
            "last": self.status.get("last"),
        }

        def progress(index: int) -> None:
            self.status["done"] = index + 1
            self.status["current"] = (
                lines[index + 1] if index + 1 < len(lines) else None
            )

        async def runner() -> None:
            error: str | None = None
            reason: str | None = None
            failed: int | None = None  # index of the op that failed, if one did
            try:
                await asyncio.to_thread(run, progress)
            except OpError as exc:
                error, reason = str(exc), exc.reason
                failed = self.status.get("done", 0)
            except organizer.PlanError as exc:
                error = reason = str(exc)
            except Exception as exc:
                logger.exception("%s job crashed", kind)
                error = reason = f"{type(exc).__name__}: {exc}"
            finally:
                self.status = {
                    "state": "idle",
                    "last": {
                        "kind": kind,
                        "ok": error is None,
                        "error": error,
                        "reason": reason,
                        "failed": failed,
                        "ops": lines,
                        "done": self.status.get("done", 0),
                        "result": result,
                        "ended": time.time(),
                    },
                }
                self._lock.release()

        logger.info("%s job started: %d ops", kind, len(ops))
        self._task = asyncio.create_task(runner())


jobs = Jobs()


# --- view models ------------------------------------------------------------


def fmt_duration(seconds: float) -> str:
    total = round(seconds)
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m" if m else f"{total}s"


def library_titles(lib: library.Library) -> set[tuple[str, str]]:
    return {(fold(bf.book.author), fold(bf.book.title)) for bf in lib.books if bf.book}


def candidate_row(
    cand: downloads.Candidate, titles: set[tuple[str, str]]
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": cand.name,
        "id": quote(cand.name, safe=""),
        "is_dir": cand.is_dir,
        "summary": cand.summary,
        "audio_count": len(cand.audio),
        "has_epub": bool(cand.ebooks),
        "duration": None,
        "duration_text": "",
        "authors": "",
        "title": "",
        "in_library": False,
    }
    if not cand.audio:
        return row
    insp = downloads.inspect(cand)
    pre = insp.prefill
    row.update(
        duration=insp.duration,
        duration_text=fmt_duration(insp.duration),
        authors=", ".join(pre.authors),
        title=pre.title,
        in_library=(fold(", ".join(pre.authors)), fold(pre.title)) in titles
        if pre.title
        else False,
    )
    return row


def candidate_rows(downloads_dir: Path, lib: library.Library) -> list[dict[str, Any]]:
    titles = library_titles(lib)
    return [candidate_row(c, titles) for c in downloads.scan(downloads_dir)]


def inspection_view(insp: downloads.Inspection) -> dict[str, Any]:
    cand = insp.candidate
    base = cand.path if cand.is_dir else cand.path.parent
    first = insp.first
    return {
        "name": cand.name,
        "id": quote(cand.name, safe=""),
        "is_dir": cand.is_dir,
        "summary": cand.summary,
        "duration_text": fmt_duration(insp.duration),
        "prefill": {
            "authors": ", ".join(insp.prefill.authors),
            "narrators": ", ".join(insp.prefill.narrators),
            "title": insp.prefill.title,
            "series": insp.prefill.series,
            "sequence": insp.prefill.sequence,
        },
        "files": [
            {
                "name": f.relative_to(base).as_posix(),
                "duration_text": fmt_duration(insp.probes[f].duration),
                "track": insp.probes[f].track_number,
                "codec": insp.probes[f].codec,
            }
            for f in insp.order
        ],
        "ebooks": [e.relative_to(base).as_posix() for e in cand.ebooks],
        "images": [i.relative_to(base).as_posix() for i in cand.images],
        "cover": cand.images[0].relative_to(base).as_posix()
        if insp.cover_default
        else "",
        "leftovers": [x.relative_to(base).as_posix() for x in cand.leftovers],
        "tags": dict(sorted(first.tags.items(), key=lambda kv: kv[0].lower()))
        if first
        else {},
        "notes": list(insp.notes),
    }


def plan_view(p: importer.Plan, source_dir: Path, root: Path) -> dict[str, Any]:
    def rel(path: Path, base: Path) -> str:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            return str(path)

    return {
        "dest_dir": p.rel_dir.as_posix(),
        "source_dir": str(source_dir),
        "metadata": next((op.content for op in p.ops if op.kind == "write"), ""),
        "metadata_op": next(
            (i for i, op in enumerate(p.ops) if op.kind == "write"), None
        ),
        "rmdir_op": next(
            (
                i
                for i, op in enumerate(p.ops)
                if op.kind == "rmdir" and op.src == source_dir
            ),
            None,
        ),
        "files": [
            {
                "src": rel(src, source_dir),
                "dst": rel(dst, root),
                "op": next((i for i, op in enumerate(p.ops) if op.dst == dst), None),
            }
            for src, dst in p.files
        ],
        "warnings": [{"level": w.level, "message": w.message} for w in p.warnings],
        "ops": [op.as_dict() for op in p.ops],
        "leftovers": [rel(x, source_dir) for x in p.leftovers],
        "deletions": [
            {
                "name": rel(x, source_dir),
                "op": next(
                    (
                        i
                        for i, op in enumerate(p.ops)
                        if op.kind == "delete" and op.src == x
                    ),
                    None,
                ),
            }
            for x in p.deletions
        ],
        "removes_source": p.removes_source,
        "cross_device": p.cross_device,
        "blocked": p.blocked,
    }


ACTION_LABEL = {
    "folder": "Rename",
    "audio-name": "Rename",
    "ebook-name": "Rename",
    "stray": "Remove",
    "empty-dir": "Remove",
}


def issue_view(issue: Issue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "kind": issue.kind,
        "block": issue.block.as_posix(),
        "src": issue.src.as_posix() if issue.src else None,
        "dst": issue.dst.as_posix() if issue.dst else None,
        "note": issue.note,
        "blocked": issue.blocked,
        "actionable": issue.actionable,
        "default_on": issue.default_on,
        "op": issue.op,
        "action": ACTION_LABEL.get(issue.kind, "Note"),
    }


def library_view(lib: library.Library, issues: list[Issue]) -> dict[str, Any]:
    return {
        "books": len(lib.books),
        "clean": audit.clean_count(lib, issues),
        "issues": [issue_view(i) for i in issues],
    }


# --- routes -----------------------------------------------------------------


def _candidate(name: str) -> downloads.Candidate:
    cand = downloads.find(get_settings().import_dir, name)
    if cand is None:
        raise HTTPException(404, f"No such download: {name}")
    return cand


@router.get("/imports")
def api_imports() -> list[dict[str, Any]]:
    s = get_settings()
    return candidate_rows(s.import_dir, library.scan(s.library_dir))


@router.get("/imports/{name}")
def api_import(name: str) -> dict[str, Any]:
    return inspection_view(downloads.inspect(_candidate(name)))


@router.post("/imports/{name}/plan")
def api_import_plan(name: str, form: importer.ImportForm) -> dict[str, Any]:
    s = get_settings()
    insp = downloads.inspect(_candidate(name))
    p = importer.plan(insp, form, library.scan(s.library_dir))
    cand = insp.candidate
    return plan_view(p, cand.path if cand.is_dir else cand.path.parent, s.library_dir)


@router.post("/imports/{name}/run", status_code=202)
async def api_import_run(name: str, form: importer.ImportForm) -> dict[str, Any]:
    s = get_settings()
    cand = _candidate(name)

    def prepare() -> importer.Plan:
        return importer.plan(downloads.inspect(cand), form, library.scan(s.library_dir))

    p = await asyncio.to_thread(prepare)
    if p.blocked:
        raise HTTPException(
            422, "; ".join(w.message for w in p.warnings if w.level == "block")
        )
    result = {
        "dest_dir": p.rel_dir.as_posix(),
        "leftovers": [str(x) for x in p.leftovers],
    }
    await jobs.start(
        "import", list(p.ops), lambda progress: importer.execute(p, progress), result
    )
    return jobs.status


class IssueIds(BaseModel):
    ids: list[str]


@router.get("/library")
def api_library() -> dict[str, Any]:
    lib, issues = organizer.rescan(get_settings().library_dir)
    return library_view(lib, issues)


@router.post("/library/plan")
def api_library_plan(body: IssueIds) -> dict[str, Any]:
    lib, issues = organizer.rescan(get_settings().library_dir)
    try:
        ops, index = organizer.plan_indexed(lib, issues, body.ids)
    except organizer.PlanError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ops": [op.as_dict() for op in ops], "index": index}


@router.post("/library/apply", status_code=202)
async def api_library_apply(body: IssueIds) -> dict[str, Any]:
    root = get_settings().library_dir
    lib, issues = await asyncio.to_thread(organizer.rescan, root)
    try:
        ops = organizer.plan(lib, issues, body.ids)
    except organizer.PlanError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not ops:
        raise HTTPException(422, "Nothing selected")
    ids = list(body.ids)
    await jobs.start(
        "organize",
        ops,
        lambda progress: organizer.apply(root, ids, progress),
        {"count": len(ops)},
    )
    return jobs.status


@router.get("/status")
def api_status() -> dict[str, Any]:
    return jobs.status
