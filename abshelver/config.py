"""Settings from the environment variables. No file, no defaults."""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    import_dir: Path
    library_dir: Path
    abs_url: str | None
    abs_api_key: str | None  # read-only API key, for links on the Library tab

    def check(self) -> None:
        """Fail fast when either directory is missing."""
        for label, path in (
            ("ABSHELVER_IMPORT_DIR", self.import_dir),
            ("ABSHELVER_LIBRARY_DIR", self.library_dir),
        ):
            if not path.is_dir():
                raise ConfigError(f"{label}={path} is not a directory")


def _required(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return Path(value)


@cache
def get_settings() -> Settings:
    url = os.environ.get("AUDIOBOOKSHELF_URL", "").strip().rstrip("/") or None
    return Settings(
        import_dir=_required("ABSHELVER_IMPORT_DIR"),
        library_dir=_required("ABSHELVER_LIBRARY_DIR"),
        abs_url=url,
        abs_api_key=os.environ.get("AUDIOBOOKSHELF_API_KEY", "").strip() or None,
    )
