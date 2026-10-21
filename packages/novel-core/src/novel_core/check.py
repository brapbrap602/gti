"""The consistency report produced by NovelStore.check()."""

from dataclasses import dataclass

from novel_core.build import OutputRow
from novel_core.finding import Finding
from novel_core.keys import ChapterKey, ItemRef
from novel_core.selection import PinFallback, SourceId


@dataclass(frozen=True)
class ItemNote:
    source_id: SourceId
    item_ref: ItemRef
    title: str
    detail: str = ""


@dataclass(frozen=True)
class HeldNote:
    """An item never translated: the findings on its current version not yet released."""

    source_id: SourceId
    item_ref: ItemRef
    title: str
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class Duplicate:
    source_id: SourceId
    key: ChapterKey
    item_refs: tuple[ItemRef, ...]


@dataclass(frozen=True)
class NumberingRun:
    """A numbering suggestion: printed start..end of a raw source match the anchor's chapters at
    printed number + offset (by title name), which the source's alignment does not give them yet.
    The offset is what a RangeOverride(printed_start, printed_end, offset) takes."""

    source_id: SourceId
    printed_start: int
    printed_end: int
    offset: int
    matched: int  # title-name matches in the run


@dataclass(frozen=True)
class CheckReport:
    gaps: tuple[int, ...]  # numbers inside the book's range with nothing publishable
    raw_only: tuple[int, ...]  # numbers that only a raw-zh source has, and not only as held text
    duplicates: tuple[Duplicate, ...]
    unmapped: tuple[ItemNote, ...]
    vanished: tuple[ItemNote, ...]
    failed: tuple[ItemNote, ...]  # detail = failure reason
    held: tuple[HeldNote, ...]
    title_mismatches: tuple[ItemNote, ...]  # detail = number found in the title
    mixed_parts: tuple[int, ...]  # sources disagree on whether the number is split
    pin_fallbacks: tuple[PinFallback, ...]
    legacy_moved: tuple[OutputRow, ...]  # legacy row whose item now derives to another key
    legacy_unselected: tuple[OutputRow, ...]  # legacy row whose item is not the selected one for its key
