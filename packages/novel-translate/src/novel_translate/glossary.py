"""Glossary records and the typed edits that change them.

A term's Chinese key (and every alias) is stored in Simplified script, so raws in
either script match the same entry.
"""

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


@cache
def _t2s() -> OpenCC:
    return OpenCC("t2s")


def normalize(text: str) -> str:
    """Simplified script, the form glossary keys are stored and matched in."""
    return _t2s().convert(text)
