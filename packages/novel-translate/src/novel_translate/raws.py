"""The raw text translation works from, and the official English that can hint at names.

For each chapter number, the raw comes from the first raw-zh source in priority
order that has a current version of it, with all of that source's parts of the
number. Both phases use this rule, so overlapping raw sources count once.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from novel_core import ChapterKey, ItemRef, KeyRange, Kind, Note, NovelStore, NovelView, Paragraph, SourceId, System


@dataclass(frozen=True)
class RawText:
    key: ChapterKey
    source_id: SourceId
    ref: ItemRef
    content_hash: str
    title: str
    paragraphs: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)


def raw_chapters(novel: NovelStore, keys: KeyRange | None = None, view: NovelView | None = None) -> Iterator[RawText]:
    """One raw per chapter key, in key order; reads each version as it goes."""
    view = view or novel.view()
    chosen: dict[int, list] = {}
    for sid in view.priority:
        if view.source(sid).spec.kind is not Kind.RAW_ZH:
            continue
        mine: dict[int, list] = {}
        for s in view.chapters(sid):
            if s.key.number not in chosen and (keys is None or s.key.number in keys):
                mine.setdefault(s.key.number, []).append(s)
        chosen.update(mine)
    for number in sorted(chosen):
        for s in chosen[number]:
            yield RawText(s.key, s.source_id, s.item_ref, s.content_hash, s.title, _paragraphs(novel, s.version_id))


def official_english(view: NovelView) -> dict[int, list]:
    """The book's selected versions per number, where the selected source is official-en."""
    official = {info.id for info in view.sources if info.spec.kind is Kind.OFFICIAL_EN}
    by_number: dict[int, list] = {}
    for s in view.selection:
        if s.source_id in official:
            by_number.setdefault(s.key.number, []).append(s)
    return by_number


def version_text(novel: NovelStore, version_id: int) -> str:
    return "\n".join(_paragraphs(novel, version_id))


def _paragraphs(novel: NovelStore, version_id: int) -> tuple[str, ...]:
    blocks = novel.read_version(version_id).blocks
    return tuple(t for b in blocks if isinstance(b, (Paragraph, System, Note)) and (t := b.text.strip()))
