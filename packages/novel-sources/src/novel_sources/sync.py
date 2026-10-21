"""sync: bring one web source of a novel up to date.

It fetches the source's index, records it (so alignment maps the items to keys),
asks the store which items to fetch (`NovelStore.to_fetch`: by default only the
numbers the book lacks) and stores each fetched chapter in its own transaction.
A failed chapter is marked failed and retried by the next sync.

A raw-zh source syncs with its zh rules (`zh`): they clean and check each chapter,
and a chapter with a finding is held (stored, never translated; another source
fetches its number, and this one fetches it again next time). A decoy site serves
no chapters unless `refresh` asks: only its index is recorded, for numbering.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from novel_core import Finding, IndexDiff, ItemRef, KeyRange, NovelStore, RawChapter, SourceId, SourceItem, SourceSpec
from novel_core.store import Clock

from novel_sources.clean import CleanRules
from novel_sources.importing import NovelIndex, Progress, chapter_version, open_novel, store_chapters
from novel_sources.zh_rules import ZhRules


class Source(Protocol):
    """A live site, as one backend reads it."""

    @property
    def spec(self) -> SourceSpec: ...

    def fetch_index(self) -> NovelIndex: ...

    def fetch_chapter(self, item: SourceItem) -> RawChapter | None:
        """The chapter page; None when the site has it locked. Raises FetchError (an OSError) on failure."""
        ...

    def clean_rules(self, raw: RawChapter) -> CleanRules: ...


@dataclass(frozen=True)
class SyncReport:
    source_id: SourceId
    index: IndexDiff
    wanted: int
    inserted: int
    unchanged: int
    unavailable: tuple[ItemRef, ...]
    failed: tuple[tuple[ItemRef, str], ...]  # (ref, reason)
    held: tuple[tuple[ItemRef, tuple[Finding, ...]], ...] = ()  # fetched now and held, with the findings
    refetched: int = 0  # held before and fetched again
    cleared: int = 0  # held before, fetched again and no longer held
    decoy_site: bool = False  # only the index was recorded (no `refresh`)


def sync(
    store: NovelStore,
    source_id: SourceId,
    source: Source,
    refresh: KeyRange | None = None,
    progress: Progress | None = None,
    only: KeyRange | None = None,
    zh: ZhRules | None = None,
) -> SyncReport:
    """Fetch what the book lacks from this source, plus every item whose key is in `refresh`;
    with `only`, just the items whose key is in it. The whole index is recorded either way.

    `zh` is the source's zh rules (see backends.zh_rules), None for any other kind of source.
    A decoy site fetches only what `refresh` names (within `only`).
    """
    index = source.fetch_index()
    diff = store.record_index(source_id, index.items)
    decoy = zh is not None and zh.decoy_site
    if not decoy:
        wanted = set(store.to_fetch(source_id, refresh, only))
    elif refresh is not None and (window := _overlap(refresh, only)):
        wanted = set(store.to_fetch(source_id, refresh, window))
    else:
        wanted = set()
    items = [i for i in index.items if i.ref in wanted]
    held_before = store.view().held_items(source_id, [i.ref for i in items]) if zh else {}
    provenance = {"backend": source.spec.backend, **index.provenance}
    version = chapter_version(source.clean_rules, provenance, zh)
    stored = store_chapters(store, source_id, items, source.fetch_chapter, version, progress)
    held_after = store.view().held_items(source_id, [i.ref for i in items]) if zh else {}
    return SyncReport(
        source_id, diff, len(items), stored.inserted, stored.unchanged, stored.unavailable, stored.failed,
        held=tuple(held_after.items()),
        refetched=len(held_before),
        cleared=len(held_before.keys() - held_after.keys()),
        decoy_site=decoy and refresh is None,
    )  # fmt: skip


def _overlap(refresh: KeyRange, only: KeyRange | None) -> KeyRange | None:
    """The numbers in both ranges; None when they share none."""
    if only is None:
        return refresh
    start, end = max(refresh.start, only.start), min(refresh.end, only.end)
    return KeyRange(start, end) if start <= end else None


@dataclass(frozen=True)
class AddReport:
    novel_dir: Path
    source_id: SourceId
    created: bool  # the novel did not exist before
    title: str  # the title the site gives
    items: int
    index: IndexDiff


def add_source(novel_dir: Path, spec: SourceSpec, index: NovelIndex, clock: Clock | None = None) -> AddReport:
    """Attach a web source to the novel at novel_dir (creating the novel from the site's
    metadata if it is new) and record the index fetched from it. `sync` fetches the chapters."""
    store, created = open_novel(novel_dir, index.meta, clock)
    with store:
        source_id = store.upsert_source(spec)
        diff = store.record_index(source_id, index.items)
    return AddReport(novel_dir, source_id, created, index.meta.title, len(index.items), diff)
