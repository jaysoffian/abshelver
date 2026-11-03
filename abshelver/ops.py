"""The only module that touches disk. Every operation is checked just before
it runs, never overwrites anything, and is logged as `op  src → dst`."""

import errno
import hashlib
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Kind = Literal["mkdir", "rename", "move", "write", "delete", "rmdir"]


class OpError(Exception):
    """`reason` is the short cause without the op line, for showing next to
    the item that failed."""

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or message


@dataclass(frozen=True, slots=True)
class Op:
    kind: Kind
    src: Path | None = None
    dst: Path | None = None
    content: str | None = None  # for `write`

    @property
    def line(self) -> str:
        if self.src is not None and self.dst is not None:
            return f"{self.kind:<6} {self.src} → {self.dst}"
        return f"{self.kind:<6} {self.src or self.dst}"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "op": self.kind,
            "src": str(self.src) if self.src else None,
            "dst": str(self.dst) if self.dst else None,
            "line": self.line,
        }


def nearest_existing(path: Path) -> Path:
    while not path.exists():
        if path.parent == path:
            break
        path = path.parent
    return path


def is_cross_device(src: Path, dst: Path) -> bool:
    try:
        return src.stat().st_dev != nearest_existing(dst).stat().st_dev
    except OSError:
        return False


def _require(path: Path | None, what: str) -> Path:
    if path is None:
        raise OpError(f"{what.capitalize()} missing")
    return path


def _must_exist(path: Path) -> None:
    if not os.path.lexists(path):
        raise OpError(f"Source vanished: {path}")


def _must_not_exist(path: Path, unless_same_as: Path | None = None) -> None:
    if not os.path.lexists(path):
        return
    if unless_same_as is not None and _same_file(path, unless_same_as):
        return  # case-only rename on a case-insensitive filesystem
    raise OpError(f"Target exists: {path}")


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False


def temp_name(dst: Path) -> Path:
    """Where a cross-device copy lands before its final name: a dot-file in
    the destination folder, which Audiobookshelf's watcher ignores, so a scan
    never sees a half-written file under its final name. Named by a hash of
    the final name, so it is short whatever the final name's length and the
    same on every attempt, so a leftover of an interrupted copy is reused."""
    digest = hashlib.md5(dst.name.encode("utf-8")).hexdigest()
    return dst.with_name(f".abshelver-temp-{digest}")


def _move_file(src: Path, dst: Path) -> None:
    """Rename if possible; across filesystems copy to a dot-temp name next to
    the target, verify size, rename into place, then delete the source."""
    try:
        src.rename(dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    # The temp name is ours alone, so a leftover of an interrupted copy is
    # simply overwritten.
    tmp = temp_name(dst)
    try:
        shutil.copy2(src, tmp)
        if tmp.stat().st_size != src.stat().st_size:
            raise OpError(f"Size mismatch after copy: {src}")
        _must_not_exist(dst)
        tmp.rename(dst)
    except OSError, OpError:
        tmp.unlink(missing_ok=True)
        raise
    src.unlink()


def run_one(op: Op) -> None:
    match op.kind:
        case "mkdir":
            dst = _require(op.dst, "mkdir target")
            if dst.exists() and not dst.is_dir():
                raise OpError(f"Not a directory: {dst}")
            dst.mkdir(parents=True, exist_ok=True)
        case "rename":
            src, dst = (
                _require(op.src, "rename source"),
                _require(op.dst, "rename target"),
            )
            _must_exist(src)
            _must_not_exist(dst, unless_same_as=src)
            try:
                src.rename(dst)
            except OSError as exc:
                if exc.errno == errno.EXDEV:
                    raise OpError(f"Cross-device rename refused: {src}") from exc
                raise
        case "move":
            src, dst = _require(op.src, "move source"), _require(op.dst, "move target")
            _must_exist(src)
            _must_not_exist(dst, unless_same_as=src)
            _move_file(src, dst)
        case "write":
            dst = _require(op.dst, "write target")
            _must_not_exist(dst)
            dst.write_text(op.content or "", encoding="utf-8")
        case "delete":
            src = _require(op.src, "delete source")
            _must_exist(src)
            if src.is_dir() and not src.is_symlink():
                raise OpError(f"Refusing to delete a directory: {src}")
            src.unlink()
        case "rmdir":
            src = _require(op.src, "rmdir source")
            _must_exist(src)
            src.rmdir()  # fails if not empty, as it should


def execute(ops: list[Op], progress: Callable[[int], None] | None = None) -> None:
    """Run ops in order. Stops at the first failure; what ran stays run and is
    in the log, which is the undo crib sheet."""
    for index, op in enumerate(ops):
        try:
            run_one(op)
        except OpError as exc:
            reason = str(exc)
        except OSError as exc:
            reason = exc.strerror or str(exc)
        else:
            logger.info("%s", op.line)
            if progress:
                progress(index)
            continue
        logger.error("FAILED %s: %s", op.line, reason)
        raise OpError(f"{op.line}: {reason}", reason)
