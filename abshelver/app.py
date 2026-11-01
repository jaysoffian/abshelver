"""FastAPI app: logging, lifespan, templates, static files, the two pages."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from abshelver import api, downloads, library, organizer
from abshelver.config import get_settings


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s %(levelname)s] %(message)s")
    )
    for name, level in (
        ("abshelver", logging.INFO),
        ("uvicorn", logging.INFO),
        ("uvicorn.access", logging.INFO),
        ("uvicorn.error", logging.INFO),
    ):
        log = logging.getLogger(name)
        log.setLevel(level)
        log.handlers = [handler]
        log.propagate = False


configure_logging()
logger = logging.getLogger(__name__)

here = Path(__file__).parent
VERSION = (
    (here.parent / "VERSION").read_text().strip()
    if (here.parent / "VERSION").exists()
    else "dev"
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    settings.check()  # raises ConfigError: fail fast, uvicorn exits
    logger.info(
        "abshelver %s started; downloads=%s library=%s abs=%s",
        VERSION,
        settings.import_dir,
        settings.library_dir,
        settings.abs_url or "-",
    )
    yield
    logger.info("abshelver shutdown")


app = FastAPI(title="abshelver", lifespan=lifespan)
app.include_router(api.router)
app.mount("/static", StaticFiles(directory=here / "static"), name="static")
templates = Jinja2Templates(directory=here / "templates")


def static_url(filename: str) -> str:
    """Cache-busting URL for a /static asset: the file's mtime as ?v=."""
    p = here / "static" / filename
    try:
        return f"/static/{filename}?v={int(p.stat().st_mtime)}"
    except OSError:
        return f"/static/{filename}"


def highlight(a: str, b: str) -> tuple[str, str, str, str]:
    """Split two strings into (common prefix, a's middle, b's middle, common suffix)."""
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    suffix = a[len(a) - j :] if j else ""
    return a[:i], a[i : len(a) - j], b[i : len(b) - j], suffix


jinja_globals: dict[str, Any] = templates.env.globals
jinja_globals["static_url"] = static_url
jinja_globals["highlight"] = highlight
jinja_globals["urlquote"] = lambda s: quote(s, safe="")
jinja_globals["version"] = VERSION


def render(request: Request, name: str, **context: Any) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request, name, {"abs_url": settings.abs_url, **context}
    )


@app.get("/", response_class=HTMLResponse)
def page_imports(request: Request) -> HTMLResponse:
    settings = get_settings()
    rows = api.candidate_rows(settings.import_dir, library.scan(settings.library_dir))
    return render(
        request,
        "imports.html",
        page="imports",
        candidates=[r for r in rows if r["audio_count"]],
        others=[r for r in rows if not r["audio_count"]],
        downloads_dir=str(settings.import_dir),
    )


@app.get("/import/{name}", response_class=HTMLResponse)
def page_import(request: Request, name: str) -> HTMLResponse:
    settings = get_settings()
    cand = downloads.find(settings.import_dir, name)
    if cand is None:
        raise HTTPException(404, f"No such download: {name}")
    return render(
        request,
        "import.html",
        page="imports",
        selected=api.inspection_view(downloads.inspect(cand)),
        downloads_dir=str(settings.import_dir),
        library_dir=str(settings.library_dir),
    )


@app.get("/organize", response_class=HTMLResponse)
def page_organize(request: Request) -> HTMLResponse:
    settings = get_settings()
    lib, issues = organizer.rescan(settings.library_dir)
    blocks: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        blocks.setdefault(issue.block.as_posix(), []).append(api.issue_view(issue))
    view = api.library_view(lib, issues)
    return render(
        request,
        "organize.html",
        page="organize",
        blocks=blocks,
        books=view["books"],
        clean=view["clean"],
        counts={
            k: sum(1 for i in issues if i.kind == k and i.actionable)
            for k in ("folder", "audio-name", "ebook-name", "stray", "empty-dir")
        },
        library_dir=str(settings.library_dir),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}
