"""sync: bring one web source of a novel up to date.

It fetches the source's index, records it (so alignment maps the items to keys),
asks the store which items to fetch (`NovelStore.to_fetch`: by default only the
numbers the book lacks) and stores each fetched chapter in its own transaction.
A failed chapter is marked failed and retried by the next sync.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from novel_core import IndexDiff, ItemRef, KeyRange, NovelStore, RawChapter, SourceId, SourceItem, SourceSpec
from novel_core.store import Clock

from novel_sources.clean import CleanRules
from novel_sources.importing import NovelIndex, Progress, open_novel, store_chapters


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


def sync(
    store: NovelStore,
    source_id: SourceId,
    source: Source,
    refresh: KeyRange | None = None,
    progress: Progress | None = None,
    only: KeyRange | None = None,
) -> SyncReport:
    """Fetch what the book lacks from this source, plus every item whose key is in `refresh`;
    with `only`, just the items whose key is in it. The whole index is recorded either way."""
    index = source.fetch_index()
    diff = store.record_index(source_id, index.items)
    wanted = set(store.to_fetch(source_id, refresh, only))
    items = [i for i in index.items if i.ref in wanted]
    provenance = {"backend": source.spec.backend, **index.provenance}
    stored = store_chapters(store, source_id, items, source.fetch_chapter, source.clean_rules, provenance, progress)
    return SyncReport(
        source_id, diff, len(items), stored.inserted, stored.unchanged, stored.unavailable, stored.failed
    )


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
