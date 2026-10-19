"""The consistency report produced by NovelStore.check()."""

from dataclasses import dataclass

from novel_core.build import OutputRow
from novel_core.keys import ChapterKey, ItemRef
from novel_core.selection import PinFallback, SourceId


@dataclass(frozen=True)
class ItemNote:
    source_id: SourceId
    item_ref: ItemRef
    title: str
    detail: str = ""


@dataclass(frozen=True)
class Duplicate:
    source_id: SourceId
    key: ChapterKey
    item_refs: tuple[ItemRef, ...]


@dataclass(frozen=True)
class CheckReport:
    gaps: tuple[int, ...]  # numbers inside the book's range with nothing publishable
    raw_only: tuple[int, ...]  # numbers that only a raw-zh source has
    duplicates: tuple[Duplicate, ...]
    unmapped: tuple[ItemNote, ...]
    vanished: tuple[ItemNote, ...]
    failed: tuple[ItemNote, ...]  # detail = failure reason
    title_mismatches: tuple[ItemNote, ...]  # detail = number found in the title
    mixed_parts: tuple[int, ...]  # sources disagree on whether the number is split
    pin_fallbacks: tuple[PinFallback, ...]
    legacy_moved: tuple[OutputRow, ...]  # legacy row whose item now derives to another key
    legacy_unselected: tuple[OutputRow, ...]  # legacy row whose item is not the selected one for its key
