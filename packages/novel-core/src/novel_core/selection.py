"""Selection policy: which source's version is used for each chapter number.

Decided per number N, never per key:
1. A pin covering N wins (the most recent pin, if several), provided the pinned
   source has something for N. Otherwise the first source in priority order
   that has something for N. Raw-zh sources are never candidates.
2. Only the chosen source's keys for N are emitted. If it has parts above 0 for
   N, its part 0 is dropped, unless those parts are all extras (alignment.py).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass

from novel_core.keys import ChapterKey, ItemRef, KeyRange

type SourceId = int


@dataclass(frozen=True)
class Selected:
    """One chapter of the publishable book: a key and the version chosen for it."""

    key: ChapterKey
    source_id: SourceId
    item_ref: ItemRef
    version_id: int
    content_hash: str
    title: str


@dataclass(frozen=True)
class Pin:
    range: KeyRange
    source_id: SourceId


@dataclass(frozen=True)
class PinFallback:
    """A pin whose source has nothing for this number; priority was used instead."""

    number: int
    pinned_source: SourceId


@dataclass(frozen=True)
class Selection:
    chapters: tuple[Selected, ...]
    pin_fallbacks: tuple[PinFallback, ...]


def rank(priority: Sequence[SourceId], sources: Iterable[SourceId]) -> list[SourceId]:
    """Every source, best first: the priority list, then sources missing from it in id order."""
    return list(priority) + sorted(s for s in sources if s not in priority)


def select(
    current: Mapping[SourceId, Sequence[Selected]],
    priority: Sequence[SourceId],
    pins: Sequence[Pin],
    extras: Mapping[SourceId, Set[ChapterKey]] | None = None,
) -> Selection:
    """`current` holds each publishable (non-raw) source's current version per mapped item.

    Sources missing from `priority` rank after it, in id order.
    """
    order = rank(priority, current)
    by_number: dict[int, dict[SourceId, list[Selected]]] = defaultdict(lambda: defaultdict(list))
    for source_id, chapters in current.items():
        for c in chapters:
            by_number[c.key.number][source_id].append(c)

    chosen: list[Selected] = []
    fallbacks: list[PinFallback] = []
    for number in sorted(by_number):
        offers = by_number[number]
        pin = next((p for p in reversed(pins) if number in p.range), None)
        if pin is not None and pin.source_id in offers:
            source = pin.source_id
        else:
            if pin is not None:
                fallbacks.append(PinFallback(number, pin.source_id))
            source = next(s for s in order if s in offers)
        keys = sorted(offers[source], key=lambda c: c.key)
        source_extras = (extras or {}).get(source, frozenset())
        if any(c.key.part and c.key not in source_extras for c in keys):
            keys = [c for c in keys if c.key.part]
        chosen.extend(keys)
    return Selection(tuple(chosen), tuple(fallbacks))


def unpinned(pins: Sequence[Pin], keys: KeyRange) -> list[Pin]:
    """The pins with every number in keys taken out; what remains keeps its order (and so its precedence)."""
    kept: list[Pin] = []
    for p in pins:
        r = p.range
        if r.end < keys.start or keys.end < r.start:
            kept.append(p)
            continue
        if r.start < keys.start:
            kept.append(Pin(KeyRange(r.start, keys.start - 1), p.source_id))
        if keys.end < r.end:
            kept.append(Pin(KeyRange(keys.end + 1, r.end), p.source_id))
    return kept
