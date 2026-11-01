"""FastAPI app: logging, lifespan, templates, static files, the two pages."""

import hashlib
import logging
import os
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import Scope

from abshelver import absapi, api, download, downloads, layout, library, organizer, tree
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
    threading.Thread(
        target=tree.warm, args=(settings.library_dir,), name="warm", daemon=True
    ).start()
    yield
    logger.info("abshelver shutdown")


class CachedStaticFiles(StaticFiles):
    """Static files with explicit caching: a URL carrying ?v= (see static_url)
    changes whenever the content does, so it may be cached forever; any other
    URL must be revalidated on every use. Browsers otherwise cache favicons,
    fonts and stylesheets on a heuristic and keep showing stale ones."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        versioned = b"v=" in scope.get("query_string", b"")
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if versioned else "no-cache"
        )
        return response


app = FastAPI(title="abshelver", lifespan=lifespan)
app.include_router(api.router)
app.mount("/static", CachedStaticFiles(directory=here / "static"), name="static")
templates = Jinja2Templates(directory=here / "templates")


@cache
def static_version(filename: str) -> str | None:
    """Short content hash of a /static file, computed once per process."""
    try:
        data = (here / "static" / filename).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()[:12]


def static_url(filename: str) -> str:
    """Cache-busting URL for a /static asset: ?v= is a hash of its content."""
    v = static_version(filename)
    return f"/static/{filename}?v={v}" if v else f"/static/{filename}"


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
    response = templates.TemplateResponse(
        request, name, {"abs_url": settings.abs_url, **context}
    )
    response.headers["Cache-Control"] = "no-cache"  # every load rescans
    return response


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
    _, issues = organizer.rescan(settings.library_dir)
    blocks: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        blocks.setdefault(issue.block.as_posix(), []).append(api.issue_view(issue))
    return render(
        request,
        "organize.html",
        page="organize",
        blocks=blocks,
        actionable=any(i.actionable for i in issues),
        counts={
            k: sum(1 for i in issues if i.kind == k and i.actionable)
            for k in ("folder", "audio-name", "ebook-name", "stray", "empty-dir")
        },
        library_dir=str(settings.library_dir),
    )


@app.get("/library", response_class=HTMLResponse)
def page_library(request: Request) -> HTMLResponse:
    settings = get_settings()
    lib = library.scan(settings.library_dir)
    links, abs_error = absapi.links(settings)
    return render(
        request,
        "library.html",
        page="library",
        tree=tree.build(lib, links),
        abs_error=abs_error,
    )


@app.get("/files/{rel:path}")
def file_download(rel: str) -> FileResponse:
    """Download one audio or ebook file from the library (the Library tab's
    file links). Anything else under the library, or outside it, is a 404."""
    root = get_settings().library_dir.resolve()
    name = PurePosixPath(rel).name
    if not (layout.is_audio(name) or layout.is_ebook(name)):
        raise HTTPException(404)
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=name)


@app.get("/zip/{rel:path}")
def zip_download(rel: str) -> StreamingResponse:
    """Download a book folder's audio and ebook files as one uncompressed zip."""
    root = get_settings().library_dir.resolve()
    folder = (root / rel).resolve()
    if not folder.is_relative_to(root) or folder == root or not folder.is_dir():
        raise HTTPException(404)
    files = download.book_files(folder)
    if not files:
        raise HTTPException(404)
    return StreamingResponse(
        download.zip_stream(files),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(folder.name)}.zip"
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}
