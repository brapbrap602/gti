"""Where novels live on disk: one folder per novel under the data dir, named by an ASCII slug."""

import os
import re
import unicodedata
from pathlib import Path

from novel_core.store import DB_NAME

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


def site_dir() -> Path:
    """Where `nov build site` writes; not a slug, so it never collides with a novel."""
    return data_dir() / "_site"


def audio_dir(slug: str) -> Path:
    """Where `nov build audio` writes one novel's chapter MP3s, sentence cache and volumes."""
    return data_dir() / "_audio" / slug


def epub_dir(slug: str) -> Path:
    """Where `nov build epub` writes one novel's volumes."""
    return data_dir() / "_epub" / slug


def novel_slugs() -> list[str]:
    """Every novel in the data dir, sorted."""
    root = data_dir()
    return sorted(d.name for d in root.iterdir() if (d / DB_NAME).is_file()) if root.is_dir() else []


def novel_dir(slug: str) -> Path:
    if slug != slugify(slug):
        raise ValueError(f"{slug!r} is not a slug (lowercase ASCII letters, digits and dashes)")
    return data_dir() / slug


def fetch_dir() -> Path:
    """Where fetching keeps what it learns per site: challenge clearances, the Firefox profile."""
    return data_dir() / "_fetch"
