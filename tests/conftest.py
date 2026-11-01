import json
from pathlib import Path

import pytest

from abshelver import probe

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake_ffprobe(monkeypatch):
    """Serve captured ffprobe JSON by file basename. Files not in any fixture
    get empty tags, so tests can build trees without real audio."""
    table: dict[str, dict] = {}
    for fx in FIXTURES.glob("*.json"):
        for rel, data in json.loads(fx.read_text()).items():
            table[Path(rel).name] = data

    def run(path: Path) -> dict:
        return table.get(
            path.name, {"format": {"duration": "0", "tags": {}}, "streams": []}
        )

    monkeypatch.setattr(probe, "run_ffprobe", run)
    probe.clear_memo()
    return table


def write_book(
    root: Path, rel: str, files: list[str], meta: dict | None = None
) -> Path:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    for name in files:
        (d / name).write_bytes(b"x")
    if meta is not None:
        (d / "metadata.json").write_text(json.dumps(meta))
    return d
