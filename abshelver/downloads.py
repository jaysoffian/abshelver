"""Walk the downloads directory into import candidates and prefill the form
from embedded tags. Filenames are never parsed for meaning."""

import re
from dataclasses import dataclass
from pathlib import Path

from abshelver import layout, probe
from abshelver.layout import fold, natural_key
from abshelver.probe import Probe

MAX_DEPTH = 3
UNABRIDGED_RE = re.compile(r"\s*[(\[]unabridged[)\]]\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One top-level entry of the downloads directory."""

    name: str
    path: Path
    is_dir: bool
    audio: tuple[Path, ...]  # natural-sorted; see Inspection.order for track order
    ebooks: tuple[Path, ...]
    images: tuple[Path, ...]  # cover candidates; `cover.*`/`folder.*` first
    leftovers: tuple[Path, ...]
    dirs: tuple[Path, ...]  # subdirectories, deepest first
    truncated: bool = False  # the walk stopped at MAX_DEPTH with content below

    @property
    def summary(self) -> str:
        parts: list[str] = []
        exts: dict[str, int] = {}
        for p in self.audio:
            ext = p.suffix.lower().lstrip(".")
            exts[ext] = exts.get(ext, 0) + 1
        parts.extend(
            f"{n} × {ext}"  # noqa: RUF001
            for ext, n in sorted(exts.items(), key=lambda kv: -kv[1])
        )
        if self.ebooks:
            parts.append("+ epub")
        return " ".join(parts) if parts else "no audio"


def _walk(top: Path) -> tuple[list[Path], list[Path], bool]:
    files: list[Path] = []
    dirs: list[Path] = []
    truncated = False
    stack = [(top, 0)]
    while stack:
        here, depth = stack.pop()
        for child in sorted(here.iterdir(), key=lambda p: natural_key(p.name)):
            if child.is_dir():
                if depth + 1 >= MAX_DEPTH:
                    truncated = True
                    continue
                dirs.append(child)
                stack.append((child, depth + 1))
            elif child.is_file():
                files.append(child)
    dirs.sort(key=lambda p: (-len(p.parts), str(p)))
    return files, dirs, truncated


def candidate(entry: Path) -> Candidate:
    if entry.is_dir():
        files, dirs, truncated = _walk(entry)
    else:
        files, dirs, truncated = [entry], [], False
    audio = sorted(
        (f for f in files if layout.is_audio(f.name)), key=lambda p: natural_key(str(p))
    )
    ebooks = sorted(
        (f for f in files if layout.is_ebook(f.name)), key=lambda p: natural_key(str(p))
    )
    images = sorted(
        (f for f in files if layout.is_image(f.name)),
        key=lambda p: (p.stem.lower() not in ("cover", "folder"), natural_key(str(p))),
    )
    leftovers = sorted(
        set(files) - set(audio) - set(ebooks) - set(images),
        key=lambda p: natural_key(str(p)),
    )
    return Candidate(
        name=entry.name,
        path=entry,
        is_dir=entry.is_dir(),
        audio=tuple(audio),
        ebooks=tuple(ebooks),
        images=tuple(images),
        leftovers=tuple(leftovers),
        dirs=tuple(dirs),
        truncated=truncated,
    )


def scan(downloads: Path) -> list[Candidate]:
    entries = [p for p in downloads.iterdir() if not p.name.startswith(".")]
    entries.sort(key=lambda p: natural_key(p.name))
    return [candidate(p) for p in entries]


def find(downloads: Path, name: str) -> Candidate | None:
    if not name or name.startswith(".") or "/" in name or name in (".", ".."):
        return None
    entry = downloads / name
    if not entry.exists():
        return None
    return candidate(entry)


def split_names(raw: str | None) -> tuple[str, ...]:
    """Split a tag or form value on `/`, `;` and `,`; strip; dedupe."""
    if not raw:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[/;,]", raw):
        name = re.sub(r"\s+", " ", part).strip()
        key = fold(name)
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Prefill:
    authors: tuple[str, ...]
    narrators: tuple[str, ...]
    title: str
    series: str
    sequence: str


def prefill(first: Probe, multi: bool) -> Prefill:
    album = first.tag("album")
    if album:
        title = UNABRIDGED_RE.sub("", album)
    elif multi:
        title = ""  # never the per-track title
    else:
        title = first.tag("title") or ""
    return Prefill(
        authors=split_names(first.tag("artist", "album_artist")),
        narrators=split_names(first.tag("composer")),
        title=title,
        series=first.tag("series", "mvnm") or "",
        sequence=first.tag("part", "mvin") or "",
    )


def order_tracks(
    files: tuple[Path, ...], probes: dict[Path, Probe]
) -> tuple[Path, ...]:
    """By the `track` tag when every file has a distinct one, else natural
    sort of the file paths."""
    numbers = [probes[f].track_number for f in files]
    if (
        len(files) > 1
        and all(n is not None for n in numbers)
        and len(set(numbers)) == len(numbers)
    ):
        return tuple(
            f
            for _, f in sorted(
                zip(numbers, files, strict=True), key=lambda t: t[0] or 0
            )
        )
    return tuple(sorted(files, key=lambda p: natural_key(str(p))))


@dataclass(frozen=True, slots=True)
class Inspection:
    candidate: Candidate
    order: tuple[Path, ...]  # audio files in track order
    probes: dict[Path, Probe]
    prefill: Prefill
    duration: float
    notes: tuple[str, ...]  # things to check before importing

    @property
    def first(self) -> Probe | None:
        return self.probes[self.order[0]] if self.order else None

    @property
    def cover_default(self) -> bool:
        """Tick "include cover" when there is an image and the audio has no
        embedded art."""
        return (
            bool(self.candidate.images)
            and self.first is not None
            and not self.first.cover
        )


def inspect(cand: Candidate) -> Inspection:
    probes = {f: probe.probe(f) for f in cand.audio}
    order = order_tracks(cand.audio, probes)
    first = probes[order[0]] if order else Probe(tags={}, duration=0.0, codec=None)
    notes: list[str] = []
    if len(order) > 1 and any(probes[f].track_number is None for f in order):
        notes.append("Some files have no track tag; order is by filename")
    notes.extend(f"{f.name}: {probes[f].error}" for f in order if probes[f].error)
    if cand.truncated:
        notes.append(f"Folders deeper than {MAX_DEPTH} levels were not scanned")
    return Inspection(
        candidate=cand,
        order=order,
        probes=probes,
        prefill=prefill(first, len(order) > 1),
        duration=sum(p.duration for p in probes.values()),
        notes=tuple(notes),
    )
