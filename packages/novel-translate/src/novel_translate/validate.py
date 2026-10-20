"""Deterministic checks of one translated chapter against its source.

A hard finding fails the attempt (it is retried once, and never stored if it fails
again); a soft one is stored with the text as a flag. Cut-off output is the caller's
to handle, not a finding. The limits that vary by novel (`Norms`) are kept per novel.
"""

import re
import zlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from pypinyin import lazy_pinyin

from novel_translate.chapter import Translated
from novel_translate.glossary import Category
from novel_translate.matching import Match

LOOP_MIN_CHARS = 40  # a paragraph this long seen more than LOOP_REPEATS times is a loop
LOOP_REPEATS = 2
LOOP_MIN_TEXT = 2000  # compression ratio says nothing about short texts

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿　-〿！-／：-＠［-｀｛-･]")
_HANZI = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_HEADING = re.compile(r"^\s*chapter\s+\d+", re.IGNORECASE)
_SOURCE_HEADING = re.compile(r"第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章节回]")
_GENERIC_TITLE = re.compile(r"^\s*(chapter\s*\d*)?\s*[:.\-–—]?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Norms:
    length_range: tuple[float, float] = (0.35, 1.10)  # English words per Chinese character
    loop_ratio: float = 3.2  # zlib compression ratio above which the text repeats itself


@dataclass(frozen=True)
class Findings:
    hard: tuple[str, ...]  # check ids: cjk, ids, empty, loop, length, heading
    soft: tuple[str, ...]  # flags: term:<zh>, pinyin:<zh>, title

    @property
    def ok(self) -> bool:
        return not self.hard


def check(source: Sequence[str], out: Translated, match: Match, norms: Norms = Norms()) -> Findings:
    """`source` is the raw chapter's paragraphs; paragraph ids are their 1-based positions."""
    hard: list[str] = []
    texts = [p.text for p in out.paragraphs]
    english = "\n".join(texts)

    if _CJK.search(out.title) or any(_CJK.search(t) for t in texts):
        hard.append("cjk")
    if sorted(p.id for p in out.paragraphs) != list(range(1, len(source) + 1)):
        hard.append("ids")
    by_id = {p.id: p.text for p in out.paragraphs}
    if any(not by_id.get(i, "x").strip() for i, s in enumerate(source, 1) if s.strip()):
        hard.append("empty")
    if _loops(texts, english, norms):
        hard.append("loop")
    hanzi = sum(len(_HANZI.findall(s)) for s in source)
    if hanzi:
        ratio = len(_WORD.findall(english)) / hanzi
        if not norms.length_range[0] <= ratio <= norms.length_range[1]:
            hard.append("length")
    if any(_HEADING.match(by_id[i]) and not _SOURCE_HEADING.search(s) for i, s in enumerate(source, 1) if i in by_id):
        hard.append("heading")

    soft: list[str] = []
    folded = english.casefold()
    for term in match.terms:
        if term.en.casefold() not in folded:
            soft.append(f"term:{term.zh}")
        if term.category is Category.PERSON and _pinyin_used(term.zh, term.en, english):
            soft.append(f"pinyin:{term.zh}")
    if _GENERIC_TITLE.match(out.title):
        soft.append("title")
    return Findings(tuple(hard), tuple(soft))


def _loops(texts: Sequence[str], english: str, norms: Norms) -> bool:
    repeats = Counter(" ".join(t.split()).casefold() for t in texts if len(t.strip()) >= LOOP_MIN_CHARS)
    if any(n > LOOP_REPEATS for n in repeats.values()):
        return True
    data = english.encode()
    return len(data) >= LOOP_MIN_TEXT and len(data) / len(zlib.compress(data)) > norms.loop_ratio


def _pinyin_used(zh: str, en: str, english: str) -> bool:
    """The name's bare pinyin shows up although the glossary renders it otherwise."""
    syllables = [s for s in lazy_pinyin(zh) if s.isalpha()]
    if not syllables or "".join(syllables) == re.sub(r"[^a-z]", "", en.casefold()):
        return False
    return re.search(r"\b" + r"[\s-]*".join(syllables) + r"\b", english, re.IGNORECASE) is not None
