"""Key derivation: the one rule that maps a source's items to ChapterKeys.

Precedence: an explicit item override, then the last range override covering the
printed number, then the source's offset added to the printed number. A printed
part only splits a chapter when another item of the source has the same printed
number; a lone "(2)" numbers a story arc (Barbarian, Mount Hua) and becomes part 0.
Items with no printed number and no override are unmapped. Items of one source that derive
to the same key are all left unmapped and reported as duplicates; the user
resolves them with item overrides, or by skipping a repost. Skipped items take no
part in derivation at all: no key, not unmapped, not a duplicate.
An item override onto a part of a number the source does not itself split (e.g. an
unnumbered side story placed at 852 pt 1) is an extra: it sits beside the whole chapter
instead of replacing it.
"""

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from novel_core.keys import ChapterKey, ItemRef


@dataclass(frozen=True)
class RangeOverride:
    """Offset for printed numbers start..end (inclusive), replacing the source offset."""

    start: int
    end: int
    offset: int


@dataclass(frozen=True)
class AlignmentRules:
    offset: int = 0
    ranges: tuple[RangeOverride, ...] = ()
    items: Mapping[ItemRef, ChapterKey] = field(default_factory=dict)
    skip: frozenset[ItemRef] = frozenset()  # reposts and other items that are not chapters of the book

    def to_json(self) -> str:
        return json.dumps(
            {
                "offset": self.offset,
                "ranges": [[r.start, r.end, r.offset] for r in self.ranges],
                "items": {ref: [k.number, k.part] for ref, k in sorted(self.items.items())},
                "skip": sorted(self.skip),
            }
        )

    @classmethod
    def from_json(cls, text: str) -> "AlignmentRules":
        raw = json.loads(text)
        return cls(
            offset=raw["offset"],
            ranges=tuple(RangeOverride(*r) for r in raw["ranges"]),
            items={ref: ChapterKey(*k) for ref, k in raw["items"].items()},
            skip=frozenset(raw.get("skip", ())),
        )

    def rebased(self, old_prefix: str, new_prefix: str) -> "AlignmentRules":
        def rebase(ref: ItemRef) -> ItemRef:
            return new_prefix + ref[len(old_prefix) :] if ref.startswith(old_prefix) else ref

        items = {rebase(ref): key for ref, key in self.items.items()}
        return AlignmentRules(self.offset, self.ranges, items, frozenset(map(rebase, self.skip)))


@dataclass(frozen=True)
class Printed:
    """What derivation needs to know about one item."""

    ref: ItemRef
    number: int | None
    part: int


@dataclass(frozen=True)
class Derivation:
    keys: dict[ItemRef, ChapterKey]
    unmapped: tuple[ItemRef, ...]
    duplicates: dict[ChapterKey, tuple[ItemRef, ...]]
    extras: frozenset[ChapterKey] = frozenset()  # placed parts that do not split their number


def derive_keys(items: Iterable[Printed], rules: AlignmentRules) -> Derivation:
    items = [i for i in items if i.ref not in rules.skip]
    shared = {n for n, count in Counter(i.number for i in items).items() if n is not None and count > 1}
    candidates: dict[ItemRef, ChapterKey] = {}
    unmapped: list[ItemRef] = []
    for item in items:
        key = _key(item if item.number in shared else replace(item, part=0), rules)
        if key is None:
            unmapped.append(item.ref)
        else:
            candidates[item.ref] = key

    by_key: dict[ChapterKey, list[ItemRef]] = defaultdict(list)
    for ref, key in candidates.items():
        by_key[key].append(ref)
    duplicates = {key: tuple(refs) for key, refs in by_key.items() if len(refs) > 1}
    keys = {ref: key for ref, key in candidates.items() if key not in duplicates}
    split = {key.number for ref, key in keys.items() if key.part and ref not in rules.items}
    extras = frozenset(key for ref, key in keys.items() if key.part and ref in rules.items and key.number not in split)
    return Derivation(keys, tuple(unmapped), duplicates, extras)


def _key(item: Printed, rules: AlignmentRules) -> ChapterKey | None:
    if item.ref in rules.items:
        return rules.items[item.ref]
    if item.number is None:
        return None
    offset = rules.offset
    for r in rules.ranges:
        if r.start <= item.number <= r.end:
            offset = r.offset
    return ChapterKey(item.number + offset, item.part)
