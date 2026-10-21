"""Importers read a frozen local store; import_novel puts what they read into a NovelStore.

Every importer becomes an ordinary Source (`backend=import:<kind>`), so its
chapters go through the same alignment, selection, pins and priority as a web
source. Re-running an import is safe: unchanged texts are stored once.
"""

import hashlib
from collections.abc import Callable, Mapping, Sequence
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
    SourceId,
    SourceItem,
    SourceSpec,
)
from novel_core.store import DB_NAME, Clock

from novel_sources.clean import CleanError, CleanRules, normalize
from novel_sources.zh_rules import ZhRules


@dataclass(frozen=True)
class NovelIndex:
    meta: NovelMeta
    items: tuple[SourceItem, ...]
    notes: tuple[str, ...] = ()  # what the reader skipped or doubted, for the import report
    snapshot: Mapping[str, bytes] = field(default_factory=dict)  # files kept as provenance, by name
    provenance: Mapping[str, object] = field(default_factory=dict)  # added to every version's provenance


class Importer(Protocol):
    @property
    def spec(self) -> SourceSpec: ...

    def read_index(self) -> NovelIndex: ...

    def read_chapter(self, item: SourceItem) -> RawChapter | None:
        """The stored page or text; None when the store never had this chapter (locked, skipped)."""
        ...

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        """How to normalize a chapter this importer read."""
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


def import_novel(
    novel_dir: Path, importer: Importer, clock: Clock | None = None, zh: ZhRules | None = None
) -> ImportReport:
    """Import every chapter into the novel at novel_dir, creating it from the index's metadata if it is new.

    `zh` is the zh rules for a raw-zh importer (see backends.zh_rules); they clean and check each chapter.
    """
    index = importer.read_index()
    store, created = open_novel(novel_dir, index.meta, clock)
    with store:
        source = store.upsert_source(importer.spec)
        _write_snapshot(novel_dir / "imports" / str(source), index.snapshot)
        diff = store.record_index(source, index.items)
        provenance = {"importer": importer.spec.backend, **index.provenance}
        version = chapter_version(importer.clean_rules, provenance, zh)
        stored = store_chapters(store, source, index.items, importer.read_chapter, version)
    return ImportReport(
        novel_dir, source, created, diff, stored.inserted, stored.unchanged, stored.unavailable, stored.failed,
        index.notes,
    )  # fmt: skip


def open_novel(novel_dir: Path, meta: NovelMeta, clock: Clock | None = None) -> tuple[NovelStore, bool]:
    """The novel's store, created from `meta` when the novel is new; and whether it was created."""
    clock_arg = {} if clock is None else {"clock": clock}
    if (novel_dir / DB_NAME).exists():
        return NovelStore.open(novel_dir, **clock_arg), False
    return NovelStore.create(novel_dir, meta, **clock_arg), True


@dataclass(frozen=True)
class Stored:
    inserted: int
    unchanged: int
    unavailable: tuple[ItemRef, ...]
    failed: tuple[tuple[ItemRef, str], ...]  # (ref, reason)


type Progress = Callable[[int, int, SourceItem], None]  # (done, total, item just stored)
type MakeVersion = Callable[[SourceItem, RawChapter], NewVersion]


def chapter_version(
    rules: Callable[[RawChapter], CleanRules], provenance: Mapping[str, object], zh: ZhRules | None
) -> MakeVersion:
    """How a source's chapters become versions: through its zh rules when it has them, else normalized
    with its own clean rules."""
    if zh is not None:
        return lambda item, raw: zh.version(raw, item.title, rules(raw), provenance)
    return lambda item, raw: NewVersion(item.title, normalize(raw, rules(raw), item.title), raw, provenance)


def store_chapters(
    store: NovelStore,
    source: SourceId,
    items: Sequence[SourceItem],
    read: Callable[[SourceItem], RawChapter | None],
    version: MakeVersion,
    progress: Progress | None = None,
) -> Stored:
    """Read, make a version of (see chapter_version) and store each item; one transaction per item,
    so an interrupted run resumes.

    `read` returning None marks the item unavailable (locked, never downloaded). One bad
    chapter never stops the run: an OSError (network failures included) or a CleanError
    marks it failed with the reason.
    """
    inserted = unchanged = 0
    unavailable: list[ItemRef] = []
    failed: list[tuple[ItemRef, str]] = []
    for done, item in enumerate(items, start=1):
        try:
            raw = read(item)
            if raw is None:
                store.mark_item(source, item.ref, ItemStatus.UNAVAILABLE)
                unavailable.append(item.ref)
            else:
                result = store.put_version(source, item.ref, version(item, raw))
                if isinstance(result, Inserted):
                    inserted += 1
                else:
                    unchanged += 1
        except (OSError, CleanError) as e:
            store.mark_item(source, item.ref, ItemStatus.FAILED, str(e))
            failed.append((item.ref, str(e)))
        if progress:
            progress(done, len(items), item)
    return Stored(inserted, unchanged, tuple(unavailable), tuple(failed))


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
