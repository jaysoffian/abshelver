"""Downloads from the Library tab: one file, or a book folder's files as a
streamed, uncompressed zip. Read-only."""

import zipfile
from collections.abc import Iterator
from pathlib import Path

from abshelver import library

CHUNK = 1 << 20


def book_files(folder: Path) -> list[Path]:
    """The audio and ebook files of one book folder, in natural order."""
    names = [p.name for p in folder.iterdir() if p.is_file()]
    audio, ebooks, _, _ = library.classify(names)
    return [folder / n for n in audio + ebooks]


class _Sink:
    """A write-only, unseekable file for zipfile, drained chunk by chunk."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.pos = 0

    def write(self, data: bytes) -> int:
        self.buf += data
        self.pos += len(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def tell(self) -> int:
        return self.pos

    def take(self) -> bytes:
        out = bytes(self.buf)
        self.buf.clear()
        return out


def zip_stream(files: list[Path]) -> Iterator[bytes]:
    """Yield a ZIP_STORED archive of `files` (flat, by name) as it is built,
    so a multi-gigabyte book never sits in memory or on disk."""
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as zf:
        for path in files:
            info = zipfile.ZipInfo.from_file(path, arcname=path.name)
            with path.open("rb") as src, zf.open(info, "w", force_zip64=True) as dst:
                while chunk := src.read(CHUNK):
                    dst.write(chunk)
                    yield sink.take()
            yield sink.take()
    yield sink.take()
