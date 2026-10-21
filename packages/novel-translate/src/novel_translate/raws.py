"""The raw text translation works from, and the official English that can hint at names.

For each chapter number, the raw comes from the first raw-zh source in priority
order that can supply it (a current version, none of its parts held), with all of
that source's parts of the number. Both phases use this rule, so overlapping raw
sources count once.

A raw is sent to a model only when it was checked by today's zh rules for its source
(`RawRules.rev`); the app supplies those per raw source, since translation cannot read
the rules themselves.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from novel_core import ChapterKey, ItemRef, KeyRange, Kind, Note, NovelStore, NovelView, Paragraph, SourceId, System


@dataclass(frozen=True)
class RawRules:
    """What translation needs from a raw source's zh rules: the translator notes for its text, and
    the rules revision a raw must have been checked with to be sent."""

    notes: str
    rev: str


@dataclass(frozen=True)
class RawText:
    key: ChapterKey
    source_id: SourceId
    ref: ItemRef
    content_hash: str
    title: str
    paragraphs: tuple[str, ...]
    rules_rev: str | None  # the zh rules revision that checked it; None if never checked

    def unchecked(self, raw_rules: Mapping[SourceId, RawRules]) -> bool:
        """Not checked with today's rules for its source; a source without rules fails closed."""
        rules = raw_rules.get(self.source_id)
        return rules is None or self.rules_rev != rules.rev

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)


def raw_chapters(novel: NovelStore, keys: KeyRange | None = None, view: NovelView | None = None) -> Iterator[RawText]:
    """One raw per chapter key, in key order (see NovelView.raw_chapters); reads each version as it goes."""
    for s in (view or novel.view()).raw_chapters(keys):
        yield RawText(
            s.key, s.source_id, s.item_ref, s.content_hash, s.title, _paragraphs(novel, s.version_id), s.rules_rev
        )


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
