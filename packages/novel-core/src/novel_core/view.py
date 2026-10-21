"""NovelView: one read of a novel, from which every derived fact is answered.

Keys, selection, fetch lists, build plans and checks all derive from the same
rows, so a page that shows several of them reads the store once and they agree.
The view holds no connection; later writes to the store do not change it.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property

from novel_core.alignment import Derivation, Printed, derive_keys
from novel_core.build import BuildPlan, OutputKind, OutputRow, plan_build
from novel_core.check import CheckReport, Duplicate, ItemNote
from novel_core.finding import Finding
from novel_core.keys import ChapterKey, ItemRef, KeyRange, title_number
from novel_core.model import ItemStatus, Kind, NovelMeta, SourceInfo
from novel_core.selection import Pin, PinFallback, Selected, Selection, SourceId, rank, select


class StoreError(Exception):
    """A request the store refuses (unknown source or item, pin to a raw source, ...)."""


@dataclass(frozen=True)
class StoredItem:
    """A source_item row as stored: what the source's index said, before alignment."""

    source_id: SourceId
    ref: ItemRef
    title: str
    printed_number: int | None
    part: int
    status: ItemStatus
    reason: str | None
    vanished: bool


@dataclass(frozen=True)
class ItemState:
    """One entry of a source's index as the book sees it now."""

    ref: ItemRef
    title: str
    key: ChapterKey | None  # None when unmapped, skipped or vanished
    status: ItemStatus
    reason: str | None
    vanished: bool
    skipped: bool
    has_text: bool  # some version is stored


@dataclass(frozen=True)
class CurrentVersion:
    """The current (most recently seen) version of one item."""

    source_id: SourceId
    ref: ItemRef
    version_id: int
    content_hash: str
    title: str
    rules_rev: str | None = None
    findings: tuple[Finding, ...] = ()
    raw_hash: str | None = None


# A release: the checks the user cleared for one kept raw of one item.
type ReleaseKey = tuple[SourceId, ItemRef, str]  # raw hash, "" for a version without a raw


def derive(items: Iterable[StoredItem], info: SourceInfo) -> Derivation:
    # Vanished items take no part in key derivation or duplicate detection.
    return derive_keys((Printed(i.ref, i.printed_number, i.part) for i in items if not i.vanished), info.alignment)


class NovelView:
    def __init__(
        self,
        meta: NovelMeta,
        sources: Mapping[SourceId, SourceInfo],
        items: Mapping[SourceId, Sequence[StoredItem]],  # each in index order
        current: Iterable[CurrentVersion],
        priority: Sequence[SourceId],
        pins: Sequence[Pin],
        outputs: Mapping[OutputKind, Sequence[OutputRow]],
        releases: Mapping[ReleaseKey, frozenset[str]] | None = None,
    ):
        self.meta = meta
        self._sources = dict(sources)
        self._items = {sid: list(items.get(sid, [])) for sid in self._sources}
        self._derivations = {sid: derive(self._items[sid], info) for sid, info in self._sources.items()}
        current = list(current)
        self._stored = {(v.source_id, v.ref) for v in current}
        releases = releases or {}
        # Held: the current version has a finding the user has not released for its raw.
        self._held = {
            (v.source_id, v.ref): held
            for v in current
            if (held := tuple(
                f for f in v.findings if f.check not in releases.get((v.source_id, v.ref, v.raw_hash or ""), ())
            ))
        }  # fmt: skip
        self._current: dict[SourceId, list[Selected]] = defaultdict(list)
        for v in current:
            key = self._derivations[v.source_id].keys.get(v.ref)
            if key is not None:
                self._current[v.source_id].append(
                    Selected(
                        key, v.source_id, v.ref, v.version_id, v.content_hash, v.title, v.rules_rev, v.findings, v.raw_hash
                    )
                )
        self._priority = list(priority)
        self.pins = tuple(pins)
        self._outputs = {kind: tuple(outputs.get(kind, ())) for kind in OutputKind}

    # -- sources ---------------------------------------------------------------

    @property
    def sources(self) -> tuple[SourceInfo, ...]:
        """In id order."""
        return tuple(self._sources[sid] for sid in sorted(self._sources))

    def source(self, source: SourceId) -> SourceInfo:
        info = self._sources.get(source)
        if info is None:
            raise StoreError(f"unknown source {source}")
        return info

    @property
    def priority(self) -> tuple[SourceId, ...]:
        """Every source, best first; sources missing from the stored list rank after it, by id."""
        return tuple(rank(self._priority, self._sources))

    def items(self, source: SourceId) -> tuple[ItemState, ...]:
        """The source's index in order, vanished items included."""
        skip = self.source(source).alignment.skip
        keys = self._derivations[source].keys
        return tuple(
            ItemState(
                i.ref, i.title, keys.get(i.ref), i.status, i.reason, i.vanished, i.ref in skip,
                (source, i.ref) in self._stored,
            )
            for i in self._items[source]
        )  # fmt: skip

    def item_refs(self, source: SourceId) -> frozenset[ItemRef]:
        """Every item the source's index has listed, vanished ones included."""
        return frozenset(i.ref for i in self._items[self.source(source).id])

    # -- selection ---------------------------------------------------------

    @cached_property
    def _selection(self) -> Selection:
        publishable = {sid: c for sid, c in self._current.items() if sid not in self._unpublishable}
        extras = {sid: self._derivations[sid].extras for sid in publishable}
        return select(publishable, self._priority, self.pins, extras)

    @cached_property
    def _unpublishable(self) -> frozenset[SourceId]:
        """Raw-zh sources and the ones switched off: neither takes part in the book."""
        return frozenset(
            sid for sid, info in self._sources.items() if info.spec.kind is Kind.RAW_ZH or not info.published
        )

    @property
    def selection(self) -> tuple[Selected, ...]:
        """The publishable book: one source per number (pins, then priority), never raw-zh or unpublished."""
        return self._selection.chapters

    @property
    def pin_fallbacks(self) -> tuple[PinFallback, ...]:
        return self._selection.pin_fallbacks

    def chapters(self, source: SourceId) -> tuple[Selected, ...]:
        """Every mapped item of one source with its current version, selected or not, in key order."""
        self.source(source)
        return tuple(sorted(self._current.get(source, []), key=lambda s: s.key))

    def held(self, source: SourceId, ref: ItemRef) -> tuple[Finding, ...]:
        """The findings that hold an item back from translation: those on its current version that
        the user has not released for that version's raw. Empty when it is not held."""
        return self._held.get((source, ref), ())

    def raw_chapters(self, keys: KeyRange | None = None) -> tuple[Selected, ...]:
        """The raw text translation works from, in key order.

        Per number, every part from the first raw-zh source in priority that can supply it:
        one with a current version at the number and none of its parts there held.
        """
        return tuple(s for n in sorted(self._usable_raws) if keys is None or n in keys for s in self._usable_raws[n])

    @cached_property
    def _usable_raws(self) -> dict[int, tuple[Selected, ...]]:
        chosen: dict[int, tuple[Selected, ...]] = {}
        for sid in self.priority:
            if self._sources[sid].spec.kind is not Kind.RAW_ZH:
                continue
            parts: dict[int, list[Selected]] = defaultdict(list)
            for s in self._current.get(sid, []):
                parts[s.key.number].append(s)
            for number, mine in parts.items():
                if number not in chosen and not any((sid, s.item_ref) in self._held for s in mine):
                    chosen[number] = tuple(sorted(mine, key=lambda s: s.key))
        return chosen

    def to_fetch(
        self, source: SourceId, refresh: KeyRange | None = None, only: KeyRange | None = None
    ) -> tuple[ItemRef, ...]:
        """The items a sync of this source should fetch, in index order.

        An item is fetched when it has no version yet and the book lacks its number:
        no other source has a text for it (for a raw-zh source, no raw source can supply
        it, see raw_chapters; for an official-en source, no other official text, so
        official English keeps syncing where only my-translation text is published).
        Unmapped items without a version are fetched too, so their text can show what
        they are. Held items are fetched again, in case the source has fixed them.
        Unavailable (locked), vanished and skipped items are left alone.
        Items whose key falls in `refresh` are fetched again whatever they hold.
        With `only`, items whose key falls outside it (or that have no key) are left alone.
        """
        info = self.source(source)
        if info.spec.kind is Kind.RAW_ZH:
            covered = set(self._usable_raws)
        elif info.spec.kind is Kind.OFFICIAL_EN:
            mine = {sid for sid, info in self._sources.items() if info.spec.kind is Kind.MY_TRANSLATION}
            covered = {s.key.number for s in self.selection if s.source_id not in mine}
        else:
            covered = {s.key.number for s in self.selection}
        keys = self._derivations[source].keys
        wanted = []
        for item in self._items[source]:
            if item.vanished or item.ref in info.alignment.skip:
                continue
            key = keys.get(item.ref)
            if only is not None and (key is None or key.number not in only):
                continue
            if refresh is not None and key is not None and key.number in refresh:
                wanted.append(item.ref)
            elif (source, item.ref) in self._held:
                wanted.append(item.ref)
            elif (source, item.ref) not in self._stored and item.status is not ItemStatus.UNAVAILABLE:
                if key is None or key.number not in covered:
                    wanted.append(item.ref)
        return tuple(wanted)

    # -- builds ------------------------------------------------------------

    def outputs(self, kind: OutputKind) -> tuple[OutputRow, ...]:
        """In key order."""
        return self._outputs[kind]

    def plan_build(self, kind: OutputKind, fingerprint: str, force: KeyRange | None = None) -> BuildPlan:
        return plan_build(self.selection, self._outputs[kind], fingerprint, force)

    # -- checks ------------------------------------------------------------

    def check(self) -> CheckReport:
        hidden = self._unpublishable
        selection = self.selection
        selected_numbers = {s.key.number for s in selection}
        selected_by_key = {s.key: s for s in selection}

        expected = {
            key.number for sid, d in self._derivations.items() if sid not in hidden for key in d.keys.values()
        } | selected_numbers
        gaps = sorted(set(range(min(expected), max(expected) + 1)) - selected_numbers) if expected else []
        raw_only = sorted(set(self._usable_raws) - selected_numbers)

        split_by_number: dict[int, set[bool]] = defaultdict(set)
        for sid, chapters in self._current.items():
            if sid in hidden:
                continue
            per_number: dict[int, bool] = defaultdict(bool)
            extras = self._derivations[sid].extras
            for c in chapters:
                per_number[c.key.number] |= c.key.part > 0 and c.key not in extras
            for number, split in per_number.items():
                split_by_number[number].add(split)

        def notes(pred, detail=lambda _i: "") -> tuple[ItemNote, ...]:
            return tuple(
                ItemNote(i.source_id, i.ref, i.title, detail(i))
                for sid in sorted(self._items)
                for i in self._items[sid]
                if pred(i)
            )

        legacy = [r for kind in OutputKind for r in self._outputs[kind] if r.legacy]
        unmapped = {(sid, ref) for sid, d in self._derivations.items() for ref in d.unmapped}
        moved = tuple(r for r in legacy if self._derivations[r.source_id].keys.get(r.item_ref) != r.built_key)
        unselected = tuple(
            r
            for r in legacy
            if r not in moved
            and (
                (s := selected_by_key.get(r.built_key)) is None
                or (s.source_id, s.item_ref) != (r.source_id, r.item_ref)
            )
        )
        return CheckReport(
            gaps=tuple(gaps),
            raw_only=tuple(raw_only),
            duplicates=tuple(
                Duplicate(sid, key, refs)
                for sid, d in sorted(self._derivations.items())
                for key, refs in sorted(d.duplicates.items())
            ),
            unmapped=notes(lambda i: (i.source_id, i.ref) in unmapped),
            vanished=notes(lambda i: i.vanished),
            failed=notes(lambda i: i.status is ItemStatus.FAILED, lambda i: i.reason or ""),
            held=notes(
                lambda i: not i.vanished and (i.source_id, i.ref) in self._held,
                lambda i: "; ".join(f"{f.check}: {f.detail}" for f in self._held[i.source_id, i.ref]),
            ),
            title_mismatches=notes(
                lambda i: not i.vanished
                and i.printed_number is not None
                and (n := title_number(i.title)) is not None
                and n != i.printed_number,
                lambda i: str(title_number(i.title)),
            ),
            mixed_parts=tuple(sorted(n for n, splits in split_by_number.items() if len(splits) > 1)),
            pin_fallbacks=self.pin_fallbacks,
            legacy_moved=moved,
            legacy_unselected=unselected,
        )
