# Development notes

Context for working on abshelver that is not obvious from the code.

## Tooling

```
uv sync                 # venv with dev tools (pytest, ruff, ty)
make serve              # http://127.0.0.1:8556 with reload; needs the env vars
make test               # prek hooks (ruff, ty, pyright, hadolint) + pytest
make build              # podman image for linux/amd64
```

`ffprobe` (ffmpeg) must be on the PATH. Put the env vars in `mise.local.toml`
(gitignored), pointing at the SMB/NFS mounts, so `make serve` and the CLI dry
run work against the real library. `prek install` adds the git hook.

## Layout

```
abshelver/
  layout.py       PURE: Book -> expected dir and file stems; sanitize; file-kind tests
  audit.py        PURE: scanned Library -> list[Issue]
  library.py      walk the library; read metadata.json into Book
  downloads.py    walk the import dir into Candidates; prefill from tags; track order
  probe.py        ffprobe wrapper, memoized by (path, size, mtime)
  importer.py     ImportForm + plan() -> Plan(ops, warnings); execute()
  organizer.py    plan_indexed() -> ops + issue-id -> op-index; apply() rescans first
  ops.py          THE ONLY MODULE THAT TOUCHES DISK
  api.py          JSON API, the one-at-a-time job runner, view-model dicts
  app.py          FastAPI app, logging, the three HTML pages
  cli.py          `abshelver organize [--doit]`
  templates/      base, imports (list), import (one candidate), organize
  static/         abshelver.css, abshelver.js (no build step, no dependencies)
tests/
  fixtures/*.json captured ffprobe output (tags only) of real downloads
```

## Rules that the code depends on

- `metadata.json` is the only source of truth for organize. Paths are never
  parsed for meaning; a book folder is any directory that directly contains
  an audio file. A book without `metadata.json` is listed as not scanned and
  otherwise skipped.
- Every expected name depends on one book's metadata alone, so narrators are
  always in the file stem even when there is only one narration.
- `ops.py`: each op checks its source exists and its target does not,
  immediately before running. Nothing is overwritten. A batch stops at the
  first failure; what ran stays run and is in the log (one line per op, the
  same `op  src → dst` form everywhere). `OpError.reason` is the short cause
  the UI shows on the failed row.
- Organize's apply re-scans and re-plans from the submitted issue ids before
  the first write; an id that no longer exists aborts the batch.
- The importer writes the audio first and the seed `metadata.json` last.
  Empty keys are omitted, because Audiobookshelf treats `"narrators": []` as
  "clear" rather than "unset". Series is written as `"Name #seq"`; the
  sequence may not contain spaces or `#`.
- Leftovers in a source folder (jpg, cue, nfo, dot-files) stay unless the
  import form's "Delete leftovers" box is ticked, in which case they are
  deleted after the moves and the folder is removed. An epub that was not
  imported is never deleted. Otherwise the folder is removed only when the
  moves leave it empty.
- Import file moves are always the `move` op: rename first, and on EXDEV
  copy, verify size, delete. EXDEV also happens between two bind mounts of
  the same filesystem (st_dev is equal, so it can't be predicted); mounting
  one parent directory for both avoids the copy.
- Organize runs file renames, then deletes, then rmdirs, then folder renames
  (deepest first), because deletes and rmdirs are planned with pre-rename
  paths. Two renames sharing a destination, or a folder renamed into its own
  subtree, are refused at plan time. A case-only rename is allowed through
  the "target exists" check when source and target are the same file.
- Dot-files are never audio or ebooks (AppleDouble `._x.m4b`); in the library
  they are strays, in a source folder they are leftovers that keep the folder
  from being removed. Audiobookshelf's own files (`metadata.json`, `cover.*`)
  are never strays, even outside a book folder.
- One job at a time (`asyncio.Lock` in `api.Jobs`); a second submit gets 409.
  The browser polls `/api/status` once a second while a job runs.

## How Audiobookshelf behaves (verified against v2.37.2)

- The library's metadata precedence is folder structure, then audio tags,
  then ... then the item's `metadata.json`, later sources winning. So the
  seed file beats the tags, and after the first scan Audiobookshelf rewrites
  it in full and owns it from then on.
- The folder watcher batches events and scans about 10 s after the last one.
  Dot-files and `.tmp`/`.part` names are ignored by the watcher; `.json` is
  not, so the seed is written directly under its final name.
- Items are tracked by inode, so same-filesystem renames keep listening
  progress. Organize only ever uses `os.rename` inside the library.
- A file like `Foo.tmp.aac` still shows up in Audiobookshelf as a library
  file, which is why strays with audio extensions are flagged loudly.

## Tests

`tests/fixtures/*.json` hold the ffprobe output (format tags, duration,
stream codecs) of the real downloads the app was built against; `conftest.py`
serves them by file basename in place of running ffprobe, so the downloads
and importer tests build fake trees with empty files. `test_audit.py` builds
a fixture tree reproducing every issue kind. `test_api.py` drives both flows
through `TestClient`.

## UI shape

Server-rendered pages, stateless; every page load rescans. The import page
recomputes the plan on every keystroke via `POST /api/imports/{name}/plan`
and renders the destination tree client-side. The plan endpoints return the
op index of each file / issue so the page can mark lines or rows done as the
job runs and follow the current one.

The look follows the Audiobookshelf web client: its colours, its fonts
(Source Sans Pro and Ubuntu Mono, bundled as woff2 in `abshelver/static/fonts/`
with their licences). The logo (`abshelver/static/icon.svg`) is our own. Dark
only, like ABS.
