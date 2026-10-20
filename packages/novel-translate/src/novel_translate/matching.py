"""Which glossary terms a chapter contains: the subset the translator is given."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

import ahocorasick

from novel_translate.glossary import Status, Term, normalize


@dataclass(frozen=True)
class Match:
    terms: tuple[Term, ...]  # injected (accepted or locked), in order of first occurrence
    blocking: tuple[Term, ...]  # needing review: the chapter must wait for them
    subset_hash: str  # of the prompt lines; changes exactly when what the translator is told changes

    @property
    def prompt_lines(self) -> tuple[str, ...]:
        return tuple(sorted(t.prompt_line for t in self.terms))


class Matcher:
    """Aho-Corasick over every term's key and aliases; the longest match wins and matches never overlap."""

    def __init__(self, terms: Iterable[Term]):
        self._automaton = ahocorasick.Automaton()
        for t in terms:
            if t.status.injected or t.status is Status.NEEDS_REVIEW:
                for key in (t.zh, *t.aliases):
                    self._automaton.add_word(key, t)
        self._empty = len(self._automaton) == 0
        if not self._empty:
            self._automaton.make_automaton()

    def match(self, text: str) -> Match:
        found: dict[int, Term] = {}
        if not self._empty:
            for _end, t in self._automaton.iter_long(normalize(text)):
                found.setdefault(t.id, t)
        terms = tuple(t for t in found.values() if t.status.injected)
        blocking = tuple(t for t in found.values() if t.status is Status.NEEDS_REVIEW)
        lines = "\n".join(sorted(t.prompt_line for t in terms))
        return Match(terms, blocking, hashlib.sha256(lines.encode()).hexdigest())
