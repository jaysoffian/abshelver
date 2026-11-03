import errno
import json
from pathlib import Path

import pytest

from abshelver import ops, probe
from abshelver.ops import Op


@pytest.fixture
def exdev(monkeypatch):
    """Make every `Path.rename` from the source directory fail with EXDEV, as a
    rename across filesystems (or bind mounts) does."""
    real = Path.rename

    def rename(self, target):
        if "src" in self.parts:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", rename)


def test_cross_device_move_lands_via_dot_temp(tmp_path, exdev, monkeypatch):
    src = tmp_path / "src/book.m4b"
    src.parent.mkdir()
    src.write_bytes(b"audio" * 100)
    dst = tmp_path / "lib/book.m4b"
    dst.parent.mkdir()
    seen: list[str] = []
    real_copy = ops.shutil.copy2

    def copy2(s, d):
        seen.append(Path(d).name)
        return real_copy(s, d)

    monkeypatch.setattr(ops.shutil, "copy2", copy2)
    ops.run_one(Op("move", src, dst))
    # the copy was written under a dot-name, which the ABS watcher ignores,
    # and only renamed to its final name once complete
    assert seen == [ops.temp_name(dst).name]
    assert seen[0].startswith(".abshelver-temp-")
    assert dst.read_bytes() == b"audio" * 100
    assert not src.exists()
    assert list(dst.parent.iterdir()) == [dst]


def test_cross_device_move_cleans_up_a_short_copy(tmp_path, exdev, monkeypatch):
    src = tmp_path / "src/book.m4b"
    src.parent.mkdir()
    src.write_bytes(b"audio" * 100)
    dst = tmp_path / "lib/book.m4b"
    dst.parent.mkdir()

    def short_copy(s, d):
        Path(d).write_bytes(b"audio")

    monkeypatch.setattr(ops.shutil, "copy2", short_copy)
    with pytest.raises(ops.OpError, match="Size mismatch"):
        ops.run_one(Op("move", src, dst))
    assert src.exists()  # the source is never deleted on failure
    assert list(dst.parent.iterdir()) == []


def test_temp_name_is_short_and_stable():
    long = Path("lib") / ("é" * 127 + ".m4b")  # 258 bytes, over NAME_MAX
    assert len(ops.temp_name(long).name.encode()) == 48
    assert ops.temp_name(long) == ops.temp_name(long)
    assert ops.temp_name(long) != ops.temp_name(long.with_suffix(".mp3"))


def test_cross_device_move_overwrites_a_stale_temp(tmp_path, exdev):
    src = tmp_path / "src/book.m4b"
    src.parent.mkdir()
    src.write_bytes(b"whole")
    dst = tmp_path / "lib/book.m4b"
    dst.parent.mkdir()
    ops.temp_name(dst).write_bytes(b"half")  # an earlier copy was interrupted
    ops.run_one(Op("move", src, dst))
    assert dst.read_bytes() == b"whole"
    assert list(dst.parent.iterdir()) == [dst]


def test_probe_failures_are_remembered_until_ttl(tmp_path, monkeypatch):
    path = tmp_path / "x.m4b"
    path.write_bytes(b"x")
    calls = 0

    def run(p: Path) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise probe.ProbeError("ffprobe timed out")
        return json.loads('{"format": {"duration": "7", "tags": {}}, "streams": []}')

    monkeypatch.setattr(probe, "run_ffprobe", run)
    probe.clear_memo()
    now = 1000.0
    monkeypatch.setattr(probe.time, "monotonic", lambda: now)
    first = probe.probe(path)
    assert first.error and first.duration == 0
    assert probe.probe(path).error  # still within the TTL: not retried
    assert calls == 1
    now += probe.FAILURE_TTL
    second = probe.probe(path)
    assert second.error is None and second.duration == 7
    assert probe.probe(path).duration == 7
    assert calls == 2  # the failure was retried after the TTL, success cached


def test_probe_missing_ffprobe_is_not_remembered(tmp_path, monkeypatch):
    path = tmp_path / "x.m4b"
    path.write_bytes(b"x")
    calls = 0

    def run(p: Path) -> dict:
        nonlocal calls
        calls += 1
        raise probe.FFprobeMissingError("ffprobe is not installed")

    monkeypatch.setattr(probe, "run_ffprobe", run)
    probe.clear_memo()
    assert probe.probe(path).error
    assert probe.probe(path).error
    assert calls == 2


def test_probe_stat_error_is_reported(tmp_path):
    probe.clear_memo()
    assert probe.probe(tmp_path / "gone.m4b").error
