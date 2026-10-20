"""Glossary records and the typed edits that change them.

A term's Chinese key (and every alias) is stored in Simplified script, so raws in
either script match the same entry.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

from opencc import OpenCC


class Status(StrEnum):
    PROPOSED = "proposed"  # reported by a translation, not yet scored by a glossary pass
    NEEDS_REVIEW = "needs_review"  # low confidence: blocks every chapter it occurs in
    ACCEPTED = "accepted"
    LOCKED = "locked"  # never changed by a glossary pass
    REJECTED = "rejected"  # not a term

    @property
    def injected(self) -> bool:
        """Given to the translator as a fixed rendering."""
        return self in (Status.ACCEPTED, Status.LOCKED)


class Category(StrEnum):
    PERSON = "person"
    PLACE = "place"
    SECT = "sect"
    TECHNIQUE = "technique"
    REALM = "realm"
    ITEM = "item"
    TITLE = "title"
    OTHER = "other"


class GlossaryError(Exception):
    """An edit the glossary refuses (duplicate name, unknown term, ...)."""


@dataclass(frozen=True)
class Term:
    id: int
    zh: str
    en: str
    category: Category
    status: Status
    gender: str | None = None
    notes: str = ""
    aliases: tuple[str, ...] = ()
    origin: str = "manual"  # manual | discovered | side-channel | hint-import
    edited: bool = False  # the user has changed it: a glossary pass never overwrites it
    first_chapter: int | None = None
    occurrences: int = 0

    @property
    def prompt_line(self) -> str:
        """How the translator is told about this term: `zh → en (category, gender, notes)`."""
        details = ", ".join(d for d in (str(self.category), self.gender, self.notes) if d)
        return f"{self.zh} → {self.en} ({details})"


# -- user edits (each one marks the term edited) ---------------------------------


@dataclass(frozen=True)
class AddTerm:
    zh: str
    en: str
    category: Category
    status: Status = Status.LOCKED
    gender: str | None = None
    notes: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdateTerm:
    """Fields left as None stay as they are; gender "" clears it."""

    term_id: int
    en: str | None = None
    category: Category | None = None
    status: Status | None = None
    gender: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class AddAlias:
    term_id: int
    zh: str


@dataclass(frozen=True)
class RemoveAlias:
    zh: str


type Edit = AddTerm | UpdateTerm | AddAlias | RemoveAlias


# -- evidence and how a glossary pass decides -------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The model's answer about one possible term: what it is and its renderings, one per snippet."""

    zh: str
    is_term: bool
    category: Category
    renderings: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    gender: str | None = None


@dataclass(frozen=True)
class Seen:
    """Where a term occurs in the raws."""

    first_chapter: int
    occurrences: int
    snippets: tuple[str, ...]


AGREEMENT = 0.7  # the top rendering's least share of the model's votes for a confident pick


@dataclass(frozen=True)
class Candidate:
    """One proposed English rendering of a term and how many times a source gave it."""

    en: str
    votes: int
    origin: str  # llm | official-en | mtl-glossary | side-channel


@dataclass(frozen=True)
class Resolution:
    status: Status  # accepted or needs_review
    en: str
    confidence: float  # the top rendering's share of the model's votes


def resolve(candidates: Sequence[Candidate]) -> Resolution | None:
    """Pick a rendering from the model's votes; None when the model has not voted.

    Low confidence (needs review): the top rendering has under AGREEMENT of the votes,
    or the official English renders it otherwise most of the time. Renderings that
    differ only in case or a leading article count as the same.
    """
    llm = _tally(c for c in candidates if c.origin == "llm")
    if not llm:
        return None
    top, (votes, spelling) = max(llm.items(), key=lambda kv: (kv[1][0], kv[0]))
    confidence = votes / sum(v for v, _ in llm.values())
    official = _tally(c for c in candidates if c.origin == "official-en")
    disputed = bool(official) and max(official.items(), key=lambda kv: (kv[1][0], kv[0]))[0] != top
    status = Status.NEEDS_REVIEW if confidence < AGREEMENT or disputed else Status.ACCEPTED
    return Resolution(status, spelling, confidence)


def _tally(candidates: Iterable[Candidate]) -> dict[str, tuple[int, str]]:
    """Votes per rendering, compared loosely; keeps the most voted spelling of each."""
    totals: dict[str, int] = defaultdict(int)
    spellings: dict[str, Counter] = defaultdict(Counter)
    for c in candidates:
        key = _ARTICLE.sub("", c.en.strip()).casefold()
        totals[key] += c.votes
        spellings[key][c.en.strip()] += c.votes
    return {k: (n, spellings[k].most_common(1)[0][0]) for k, n in totals.items()}


_ARTICLE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


@cache
def _t2s() -> OpenCC:
    return OpenCC("t2s")


def normalize(text: str) -> str:
    """Simplified script, the form glossary keys are stored and matched in."""
    return _t2s().convert(text)
