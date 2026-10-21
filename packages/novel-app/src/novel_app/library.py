"""Where novels live on disk: one folder per novel under the data dir, named by an ASCII slug."""

import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import date
from pathlib import Path

from novel_core.store import DB_NAME, SCHEMA_VERSION, stored_schema

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


def compare_dir(slug: str) -> Path:
    """Where `nov translate compare` writes one novel's comparison bundles."""
    return data_dir() / "_compare" / slug


def novel_slugs() -> list[str]:
    """Every novel in the data dir, sorted. Folders starting with `_` (outputs, backups) are never novels."""
    root = data_dir()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if not d.name.startswith("_") and (d / DB_NAME).is_file())


def back_up_old_stores(today: date) -> list[Path]:
    """Copy each novel database that opening would migrate to _backup-schema<N>-<today>/<slug>/, once.

    Run before anything opens a store, so the schema-N file survives the upgrade. Returns the copies made.
    """
    made = []
    for slug in novel_slugs():
        version = stored_schema(data_dir() / slug)
        backup = data_dir() / f"_backup-schema{version}-{today.isoformat()}" / slug / DB_NAME
        if version >= SCHEMA_VERSION or backup.exists():
            continue
        backup.parent.mkdir(parents=True, exist_ok=True)
        # The backup API copies what the WAL holds too, which a file copy would miss.
        with closing(sqlite3.connect(data_dir() / slug / DB_NAME)) as src, closing(sqlite3.connect(backup)) as dst:
            src.backup(dst)
        made.append(backup)
    return made


def novel_dir(slug: str) -> Path:
    if slug != slugify(slug):
        raise ValueError(f"{slug!r} is not a slug (lowercase ASCII letters, digits and dashes)")
    return data_dir() / slug


def guide_file() -> Path:
    """The user's own decode guide entries (web-novel-scraper's format), overriding the shipped ones by host."""
    return data_dir() / "decode_guide.json"


def fetch_dir() -> Path:
    """Where fetching keeps what it learns per site: challenge clearances, the Firefox profile."""
    return data_dir() / "_fetch"
