"""Inspect: what the zh rules make of a raw-zh source's chapters, for writing new rules (`nov inspect`).

Read-only. Each chapter is cleaned again from its kept text raw with today's rules
(stored blocks for HTML raws), so a rule being written shows its effect before any
reclean. For each it gives the cleaner hits, what the checks measured, and the
paragraphs that survived cleaning but look like noise, by three labelled heuristics.
Against a clean reference source, chapters pair by title name (keys may disagree),
and the cleaned paragraphs are diffed; the differing spans are grouped, so a
pattern a rule should fix shows as one line with its count.

Not part of the rules revision: nothing here changes what is stored.
"""

import re
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from novel_core import Block, Finding, KeyRange, NovelStore, Paragraph, SourceId
from novel_core.keys import title_name
from novel_core.selection import Selected

from novel_sources.clean import CleanRules
from novel_sources.zh_rules import Hit, Markers, NameCount, PoisonCount, ZhRules

_CJK = re.compile(r"[㐀-䶿一-鿿]")
_LETTERS = re.compile(r"[A-Za-zＡ-Ｚａ-ｚͰ-ϿЀ-ӿ]+")  # Latin, Greek (ω) and Cyrillic look-alikes


@dataclass(frozen=True)
class Suspect:
    label: str  # the heuristic that fired
    text: str  # the paragraph


_HEURISTICS: tuple[tuple[str, Callable[[str, Collection[str]], bool]], ...] = (
    ("no CJK", lambda p, keeps: not _CJK.search(p) and p not in keeps),
    ("unbalanced quotes", lambda p, keeps: p.count("「") != p.count("」") or p.count("“") != p.count("”")),
    ("Latin/Cyrillic in a CJK line", lambda p, keeps: bool(_CJK.search(p) and _LETTERS.search(p))),
)


def suspects(paragraphs: Sequence[str], keeps: Collection[str]) -> tuple[Suspect, ...]:
    """Paragraphs that look like noise, once per heuristic that fires; `keeps` are known prose."""
    return tuple(Suspect(label, p) for p in paragraphs for label, fires in _HEURISTICS if fires(p, keeps))


@dataclass(frozen=True)
class Span:
    """Text that differs between two cleaned chapters: ours where theirs has something else."""

    ours: str  # "" when only theirs has it
    theirs: str  # "" when only ours has it
    count: int


_SAME_PARAGRAPH = 0.5  # similarity at which two differing paragraphs count as one paragraph changed


def diff(ours: Sequence[str], theirs: Sequence[str]) -> tuple[Span, ...]:
    """The spans in which two paragraph lists differ, grouped and most frequent first.

    Paragraphs are matched first; within a changed run, similar paragraphs pair up and
    are compared character by character, and the rest count whole.
    """
    found: Counter[tuple[str, str]] = Counter()
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ours, theirs, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for a, b in _pairs(ours[i1:i2], theirs[j1:j2]):
            if a and b:
                found.update(_char_spans(a, b))
            else:
                found[(a, b)] += 1
    ranked = sorted(found.items(), key=lambda kv: -kv[1])  # stable: ties keep the order first seen
    return tuple(Span(a, b, n) for (a, b), n in ranked)


def _pairs(ours: Sequence[str], theirs: Sequence[str]) -> Iterator[tuple[str, str]]:
    """In order: each paragraph of ours with the next similar one of theirs, else alone ("" beside it)."""
    j = 0
    for a in ours:
        k = next((k for k in range(j, len(theirs)) if _similar(a, theirs[k])), None)
        if k is None:
            yield a, ""
            continue
        yield from (("", b) for b in theirs[j:k])
        yield a, theirs[k]
        j = k + 1
    yield from (("", b) for b in theirs[j:])


def _similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= _SAME_PARAGRAPH


def _char_spans(a: str, b: str) -> Iterator[tuple[str, str]]:
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            yield a[i1:i2], b[j1:j2]


@dataclass(frozen=True)
class Reference:
    """The reference source's chapter of the same title name, and how its cleaned text differs."""

    source_id: SourceId
    name: str  # the title name looked for
    chapter: Selected | None  # None when the reference has no chapter, or several, of that name
    spans: tuple[Span, ...] = ()


@dataclass(frozen=True)
class Inspection:
    chapter: Selected  # key, ref, title and the stored findings (released ones included)
    checked: bool  # stored with today's rules
    held: tuple[Finding, ...]  # the stored findings not released: they hold the chapter back
    poison: PoisonCount | None  # measured on today's cleaning; None when the rules have no markers
    markers: Markers | None  # the poison thresholds it is judged by
    names: NameCount | None  # None when the novel lists no names
    hits: tuple[tuple[Hit, int], ...]  # each distinct cleaner change and how many lines it made
    suspects: tuple[Suspect, ...]
    reference: Reference | None = None


def inspect(
    store: NovelStore,
    source_id: SourceId,
    zh: ZhRules,
    numbers: KeyRange,
    against: tuple[SourceId, ZhRules] | None = None,
) -> tuple[Inspection, ...]:
    """Every current chapter of the source at these numbers, inspected; `against` is a reference source and its rules."""
    view = store.view()
    named: dict[str, list[Selected]] = {}
    if against is not None:
        for s in view.chapters(against[0]):
            named.setdefault(title_name(s.title), []).append(s)
    found = []
    for s in view.chapters(source_id):
        if s.key.number not in numbers:
            continue
        blocks, hits = _cleaned(store, s, zh)
        paragraphs = _paragraphs(blocks)
        reference = None
        if against is not None:
            name = title_name(s.title)
            match = named.get(name, []) if name else []
            if len(match) == 1:
                theirs = _paragraphs(_cleaned(store, match[0], against[1])[0])
                reference = Reference(against[0], name, match[0], diff(paragraphs, theirs))
            else:
                reference = Reference(against[0], name, None)
        found.append(Inspection(
            s, s.rules_rev == zh.rev, view.held(source_id, s.item_ref),
            zh.poison_count(blocks), zh.markers, zh.name_count(blocks),
            tuple(Counter(hits).items()), suspects(paragraphs, zh.keeps), reference,
        ))  # fmt: skip
    return tuple(found)


def _cleaned(store: NovelStore, chapter: Selected, zh: ZhRules) -> tuple[tuple[Block, ...], tuple[Hit, ...]]:
    """Today's cleaning of a chapter, from its kept text raw (stored blocks for any other), and the cleaner hits."""
    version = store.read_version(chapter.version_id)
    raw = store.read_raw(chapter.version_id)
    if raw is None or raw.content_type != "text":
        return version.blocks, ()
    return zh.version(raw, version.title, CleanRules(content=()), {}).blocks, zh.trace(raw.content)


def _paragraphs(blocks: Sequence[Block]) -> list[str]:
    return [b.text for b in blocks if isinstance(b, Paragraph)]
