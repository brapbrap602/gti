"""Importers read a frozen local store; import_novel puts what they read into a NovelStore.

Every importer becomes an ordinary Source (`backend=import:<kind>`), so its
chapters go through the same alignment, selection, pins and priority as a web
source. Re-running an import is safe: unchanged texts are stored once.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from novel_core import (
    IndexDiff,
    Inserted,
    ItemRef,
    ItemStatus,
    NewVersion,
    NovelMeta,
    NovelStore,
    RawChapter,
    SourceItem,
    SourceSpec,
)
from novel_core.store import DB_NAME, Clock

from novel_sources.clean import CleanError, normalize
from novel_sources.hosts import COMMON, rules_for


@dataclass(frozen=True)
class NovelIndex:
    meta: NovelMeta
    items: tuple[SourceItem, ...]
    notes: tuple[str, ...] = ()  # what the reader skipped or doubted, for the import report
    snapshot: Mapping[str, bytes] = field(default_factory=dict)  # files kept as provenance, by name


class Importer(Protocol):
    @property
    def spec(self) -> SourceSpec: ...

    def read_index(self) -> NovelIndex: ...

    def read_chapter(self, item: SourceItem) -> RawChapter | None:
        """The stored page or text; None when the store never had this chapter (locked, skipped)."""
        ...


@dataclass(frozen=True)
class ImportReport:
    novel_dir: Path
    source_id: int
    created: bool  # the novel did not exist before this import
    index: IndexDiff
    inserted: int
    unchanged: int
    unavailable: tuple[ItemRef, ...]
    failed: tuple[tuple[ItemRef, str], ...]  # (ref, reason)
    notes: tuple[str, ...]


def import_novel(novel_dir: Path, importer: Importer, clock: Clock | None = None) -> ImportReport:
    """Import into the novel at novel_dir, creating it from the index's metadata if it is new.

    One bad chapter never stops the import: it is marked failed with the reason.
    """
    index = importer.read_index()
    created = not (novel_dir / DB_NAME).exists()
    clock_arg = {} if clock is None else {"clock": clock}
    store = NovelStore.create(novel_dir, index.meta, **clock_arg) if created else NovelStore.open(novel_dir, **clock_arg)
    with store:
        source = store.upsert_source(importer.spec)
        _write_snapshot(novel_dir / "imports" / str(source), index.snapshot)
        diff = store.record_index(source, index.items)
        inserted = unchanged = 0
        unavailable: list[ItemRef] = []
        failed: list[tuple[ItemRef, str]] = []
        for item in index.items:
            try:
                raw = importer.read_chapter(item)
                if raw is None:
                    store.mark_item(source, item.ref, ItemStatus.UNAVAILABLE)
                    unavailable.append(item.ref)
                    continue
                rules = COMMON if raw.content_type == "text" else rules_for(raw.final_url or importer.spec.url)
                blocks = normalize(raw, rules, item.title)
            except (OSError, CleanError) as e:
                store.mark_item(source, item.ref, ItemStatus.FAILED, str(e))
                failed.append((item.ref, str(e)))
                continue
            result = store.put_version(source, item.ref, NewVersion(item.title, blocks, raw, {"importer": importer.spec.backend}))
            if isinstance(result, Inserted):
                inserted += 1
            else:
                unchanged += 1
    return ImportReport(
        novel_dir, source, created, diff, inserted, unchanged, tuple(unavailable), tuple(failed), index.notes
    )


def _write_snapshot(folder: Path, files: Mapping[str, bytes]) -> None:
    """Keep each snapshot file. The first one keeps the plain name (legacy audio positions
    resolve against it); a later, different copy is kept next to it under its hash."""
    for name, data in files.items():
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        if path.exists() and path.read_bytes() != data:
            path = path.with_stem(f"{path.stem}.{hashlib.sha1(data).hexdigest()[:12]}")
        if not path.exists():
            path.write_bytes(data)
