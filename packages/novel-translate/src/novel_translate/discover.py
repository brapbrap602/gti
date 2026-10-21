"""New-word discovery: strings in the raws that behave like names.

A candidate is a run of 2-8 Chinese characters that occurs often, whose parts
stick together more than chance would make them (PMI), and that turns up next
to many different characters on both sides (boundary entropy). The counting
passes are bounded: a string is only counted when both its shorter parts
survived the frequency cut, so memory follows the frequent strings, not the text.
Everyday words are left out: a short hand list (`common_words.txt`) also rules out
strings that start or end with one of its words, and a long list from a general
dictionary (`everyday_words.txt`) rules out only strings that are exactly one of its
words, so names built from everyday words stay. So are strings of numerals alone.
Recall matters more than precision here: the glossary pass's model rejects non-terms.
"""

import itertools
import math
import re
from importlib import resources
from collections import Counter, defaultdict
from collections.abc import Iterable, Set
from dataclasses import dataclass

MIN_LEN, MAX_LEN = 2, 8
MIN_COUNT = 10  # over the whole novel; rarer names come in through manual adds and translations
MIN_PMI = 3.0  # nats, the weakest split of the string
MIN_ENTROPY = 1.0  # nats, of the characters seen on the poorer side
DOMINANCE = 0.9  # a part seen almost only inside a longer candidate is that candidate
# Particles that never occur inside a name: a string holding one is a phrase.
INNER_STOPS = frozenset("的了着")
# Grammatical characters that do not start or end a name.
EDGE_STOPS = frozenset("的了是在和与及或也都就还又而着过把被让给对向从到于以为之其这那此彼他她它我你您们个一不没很太更最吗呢吧啊呀哦嗯说道")

NUMERALS = frozenset("一二三四五六七八九十百千万亿几两零半数")


def _words(name: str) -> frozenset[str]:
    text = resources.files(__package__).joinpath(name).read_text(encoding="utf-8")
    return frozenset(w for line in text.splitlines() if not line.startswith("#") for w in line.split())


_COMMON = _words("common_words.txt")
_EVERYDAY = _words("everyday_words.txt")

_CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")


@dataclass(frozen=True)
class Candidate:
    zh: str
    count: int


def candidates(chapters: Iterable[str], known: Set[str]) -> list[Candidate]:
    """Likely names in the chapters (Simplified script expected), most frequent first, minus `known`."""
    runs = [run for text in chapters for run in _CJK_RUN.findall(text)]
    chars = Counter(c for run in runs for c in run)
    total = sum(chars.values())
    if not total:
        return []

    counts: dict[str, int] = {}
    frequent: Set[str] = {c for c, n in chars.items() if n >= MIN_COUNT}
    for length in range(MIN_LEN, MAX_LEN + 1):
        grams = Counter(
            run[i : i + length]
            for run in runs
            for i in range(len(run) - length + 1)
            if run[i : i + length - 1] in frequent and run[i + 1 : i + length] in frequent
        )
        frequent = {g for g, n in grams.items() if n >= MIN_COUNT}
        if not frequent:
            break
        counts.update((g, grams[g]) for g in frequent)

    def part(s: str) -> int:
        return chars[s] if len(s) == 1 else counts[s]

    def pmi(w: str) -> float:
        n = counts[w]
        return min(math.log(n * total / (part(w[:k]) * part(w[k:]))) for k in range(1, len(w)))

    cohesive = {
        w for w in counts
        if w not in known and not _ordinary(w) and pmi(w) >= MIN_PMI
    }  # fmt: skip
    sides = _neighbours(runs, cohesive)
    kept = {w for w in cohesive if min(_entropy(sides[w][0]), _entropy(sides[w][1])) >= MIN_ENTROPY}
    kept = _without_dominated_parts(kept, counts)
    return sorted((Candidate(w, counts[w]) for w in kept), key=lambda c: (-c.count, c.zh))


def _ordinary(w: str) -> bool:
    """An everyday word or a number; or starts or ends with a grammatical character or a common word, or holds a particle."""
    if w in _EVERYDAY or NUMERALS.issuperset(w):
        return True
    if w[0] in EDGE_STOPS or w[-1] in EDGE_STOPS or not INNER_STOPS.isdisjoint(w):
        return True
    return any(w[:n] in _COMMON or w[-n:] in _COMMON for n in range(MIN_LEN, len(w) + 1))


def _neighbours(runs: list[str], wanted: Set[str]) -> dict[str, tuple[Counter, Counter]]:
    """For each wanted string, the characters seen just before and after it. A run's edge counts
    as a fresh neighbour each time (punctuation around a name is a sign of a boundary)."""
    sides: dict[str, tuple[Counter, Counter]] = defaultdict(lambda: (Counter(), Counter()))
    edges = itertools.count()
    lengths = sorted({len(w) for w in wanted})
    for run in runs:
        for length in lengths:
            for i in range(len(run) - length + 1):
                w = run[i : i + length]
                if w in wanted:
                    left, right = sides[w]
                    left[run[i - 1] if i else next(edges)] += 1
                    right[run[i + length] if i + length < len(run) else next(edges)] += 1
    return sides


def _entropy(counts: Counter) -> float:
    n = sum(counts.values())
    return -sum(c / n * math.log(c / n) for c in counts.values()) if n else 0.0


def _without_dominated_parts(words: Set[str], counts: dict[str, int]) -> set[str]:
    dominated = set()
    for w in words:
        for length in range(MIN_LEN, len(w)):
            for i in range(len(w) - length + 1):
                part = w[i : i + length]
                if part in words and counts[w] >= DOMINANCE * counts[part]:
                    dominated.add(part)
    return set(words) - dominated
