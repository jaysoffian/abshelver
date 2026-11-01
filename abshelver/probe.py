"""ffprobe wrapper. Results are memoized in-process by (path, size, mtime)."""

import json
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class ProbeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Probe:
    tags: dict[str, str]  # as ffprobe reports them, original key case
    duration: float
    codec: str | None
    error: str | None = None
    _lower: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def tag(self, *names: str) -> str | None:
        """First non-blank tag among `names`, matched case-insensitively."""
        for name in names:
            value = self._lower.get(name.lower())
            if value and value.strip():
                return value.strip()
        return None

    @property
    def track_number(self) -> int | None:
        raw = self.tag("track")
        if not raw:
            return None
        head = raw.split("/", 1)[0].strip()
        return int(head) if head.isdigit() else None


_memo: dict[tuple[str, int, int], Probe] = {}
_lock = threading.Lock()


def run_ffprobe(path: Path) -> dict:
    """Run ffprobe and return its JSON. Separate so tests can replace it."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=120
        )
    except FileNotFoundError as exc:
        raise ProbeError("ffprobe is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe timed out") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise ProbeError(f"ffprobe failed (exit {result.returncode})")
    return json.loads(result.stdout)


def parse(data: dict) -> Probe:
    fmt = data.get("format") or {}
    tags = {str(k): str(v) for k, v in (fmt.get("tags") or {}).items()}
    try:
        duration = float(fmt.get("duration") or 0)
    except ValueError:
        duration = 0.0
    codec = next(
        (
            s.get("codec_name")
            for s in data.get("streams") or []
            if s.get("codec_type") == "audio"
        ),
        None,
    )
    return Probe(
        tags=tags,
        duration=duration,
        codec=codec,
        _lower={k.lower(): v for k, v in tags.items()},
    )


def probe(path: Path) -> Probe:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _memo.get(key)
    if hit is not None:
        return hit
    try:
        result = parse(run_ffprobe(path))
    except (ProbeError, json.JSONDecodeError) as exc:
        logger.warning("probe failed for %s: %s", path, exc)
        result = Probe(tags={}, duration=0.0, codec=None, error=str(exc))
    with _lock:
        _memo[key] = result
    return result


def clear_memo() -> None:
    with _lock:
        _memo.clear()
