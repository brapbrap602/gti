"""Where novels live on disk: one folder per novel under the data dir, named by an ASCII slug."""

import os
import re
import unicodedata
from pathlib import Path

DATA_DIR_ENV = "NOVELS_DATA_DIR"


def data_dir() -> Path:
    """$NOVELS_DATA_DIR, else %LOCALAPPDATA%\\novels (~/.local/share/novels elsewhere)."""
    if configured := os.environ.get(DATA_DIR_ENV):
        return Path(configured)
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "novels" if base else Path.home() / ".local" / "share" / "novels"


def slugify(title: str) -> str:
    """'Return of the Mount Hua Sect' -> 'return-of-the-mount-hua-sect'."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    if not slug:
        raise ValueError(f"title {title!r} has no ASCII letters; pass a slug explicitly")
    return slug


def novel_dir(slug: str) -> Path:
    if slug != slugify(slug):
        raise ValueError(f"{slug!r} is not a slug (lowercase ASCII letters, digits and dashes)")
    return data_dir() / slug
