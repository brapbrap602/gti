"""zh rules: how a raw-zh chapter is cleaned and checked before it is stored.

Rules come in layers (common zh → site → novel, see zh_tables). Cleaners rewrite
one line of kept raw text before `normalize`; they fix formatting only and assume
the text is genuine. Checks judge the cleaned chapter and return Findings that
hold it back from translation; they never change the text. HTML raws (lncrawl and
the like) are normalized by their backend's own rules and only checked.

`rev` names the rule code: a hash of this file, zh_tables.py and clean.py, read
once at import, plus the slug and site key. A stored version whose rules_rev is
not the current one is unchecked. Rule logic must therefore live in those three
files only, which is why they import nothing else from novel_sources (a test
guards it). Notes (zh_notes) are not in the hash: translation keys on them directly.
"""

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from novel_core import Block, Finding, NewVersion, Paragraph, RawChapter, Version

from novel_sources import clean
from novel_sources.clean import CleanRules, normalize


@dataclass(frozen=True)
class Example:
    before: str  # one kept-raw line
    after: str | None  # the cleaned line, or None when it is dropped


@dataclass(frozen=True)
class Cleaner:
    name: str
    apply: Callable[[str], str | None]  # a stripped line -> the new line, or None to drop it
    examples: tuple[Example, ...]

    def __post_init__(self) -> None:
        if not any(ex.after != ex.before for ex in self.examples):
            raise ValueError(f"cleaner {self.name!r} needs an example it changes")


@dataclass(frozen=True)
class Hit:
    """One cleaner changing one line."""

    rule: str  # the cleaner's name
    before: str
    after: str | None  # None when the line was dropped


@dataclass(frozen=True)
class Markers:
    """Poison: words a scrambling site swaps in. A chapter is poisoned when, per 1000 CJK chars,
    at least `density` hits are found, from at least `distinct` markers and `hits` in all."""

    words: tuple[str, ...]
    density: float = 2.0
    distinct: int = 3
    hits: int = 6


@dataclass(frozen=True)
class Layer:
    cleaners: tuple[Cleaner, ...] = ()
    keeps: tuple[str, ...] = ()  # lines that must come through this layer (and the ones above) unchanged
    markers: Markers | None = None  # poison markers and thresholds
    decoy_site: bool = False  # the site serves decoy text: sync records its index only
    names: tuple[str, ...] = ()  # novel layer: recurring names, for the decoy-names check


def drop(name: str, pattern: str, examples: tuple[Example, ...]) -> Cleaner:
    """A cleaner that drops every line `pattern` matches whole."""
    regex = re.compile(pattern)
    return Cleaner(name, lambda line: None if regex.fullmatch(line) else line, examples)


def rewrite(name: str, pattern: str, repl: str, examples: tuple[Example, ...]) -> Cleaner:
    """A cleaner that replaces `pattern` wherever it is in a line; a line left empty is dropped."""
    regex = re.compile(pattern)
    return Cleaner(name, lambda line: regex.sub(repl, line).strip() or None, examples)


_OPENING = 6  # paragraphs a decoy chapter keeps from the real one before it drifts off
_DECOY_REST = 600  # CJK chars the rest needs before a missing name means anything
_CJK = re.compile(r"[㐀-䶿一-鿿]")


@dataclass(frozen=True)
class ZhRules:
    """The composed rules for one raw-zh source of one novel (see `compose`)."""

    rev: str
    notes: str
    decoy_site: bool
    cleaners: tuple[Cleaner, ...] = ()
    markers: Markers | None = None
    names: tuple[str, ...] = ()

    def version(
        self, raw: RawChapter, title: str, base: CleanRules, provenance: Mapping[str, object]
    ) -> NewVersion:
        """The chapter to store, with its findings and this rev.

        Text raws: each line is cleaned, then normalized with no other rules (`base` is
        ignored, so sync and reclean cannot diverge). HTML raws: normalized with `base`.
        Raises CleanError as normalize does.
        """
        if raw.content_type == "text":
            cleaned = (self._clean_line(line)[0] for line in raw.content.splitlines())
            text = "\n".join(line for line in cleaned if line is not None)
            blocks = normalize(RawChapter(text, "text", raw.final_url, raw.fetched_at), CleanRules(content=()), title)
        else:
            blocks = normalize(raw, base, title)
        return NewVersion(title, blocks, raw, provenance, self.check(blocks), self.rev)

    def recheck(self, version: Version) -> NewVersion:
        """The stored text again, with the findings of today's checks and this rev."""
        return NewVersion(
            version.title, version.blocks, None, version.provenance, self.check(version.blocks), self.rev
        )

    def check(self, blocks: Sequence[Block]) -> tuple[Finding, ...]:
        paragraphs = [b.text for b in blocks if isinstance(b, Paragraph)]
        found = (_poison(paragraphs, self.markers), _decoy_names(paragraphs, self.names))
        return tuple(f for f in found if f is not None)

    def trace(self, text: str) -> tuple[Hit, ...]:
        """What the cleaners do to a kept raw text: each rule that changed a line, in order."""
        return tuple(hit for line in text.splitlines() for hit in self._clean_line(line)[1])

    def _clean_line(self, line: str) -> tuple[str | None, list[Hit]]:
        out: str | None = line.strip()
        hits: list[Hit] = []
        for cleaner in self.cleaners:
            if out is None:
                break
            before, out = out, cleaner.apply(out)
            if out != before:
                hits.append(Hit(cleaner.name, before, out))
        return out, hits


def compose(layers: Sequence[Layer | None], slug: str, site: str, notes: str = "") -> ZhRules:
    """Rules from layers given outermost first: cleaners run in that order, later markers win."""
    present = [layer for layer in layers if layer is not None]
    markers = next((layer.markers for layer in reversed(present) if layer.markers), None)
    return ZhRules(
        rev=hashlib.sha256(b"\0".join([_CODE, slug.encode(), site.encode()])).hexdigest()[:16],
        notes=notes,
        decoy_site=any(layer.decoy_site for layer in present),
        cleaners=tuple(c for layer in present for c in layer.cleaners),
        markers=markers,
        names=tuple(n for layer in present for n in layer.names),
    )


def _poison(paragraphs: Sequence[str], markers: Markers | None) -> Finding | None:
    if markers is None:
        return None
    text = "\n".join(paragraphs)
    counts = {w: n for w in markers.words if (n := text.count(w))}
    hits = sum(counts.values())
    cjk = len(_CJK.findall(text))
    density = hits * 1000 / cjk if cjk else 0.0
    if density < markers.density or len(counts) < markers.distinct or hits < markers.hits:
        return None
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])  # stable: ties keep the markers' order
    return Finding("poison", " ".join(f"{w}×{n}" for w, n in ranked) + f" ({density:.1f}/1000)")


def _decoy_names(paragraphs: Sequence[str], names: Sequence[str]) -> Finding | None:
    """A decoy keeps the real chapter's opening, then drifts into text without its people."""
    if not names:
        return None
    opening = "\n".join(paragraphs[:_OPENING])
    rest = "\n".join(paragraphs[_OPENING:])
    seen = {n: k for n in names if (k := opening.count(n))}
    rest_cjk = len(_CJK.findall(rest))
    if not seen or any(n in rest for n in names) or rest_cjk < _DECOY_REST:
        return None
    named = " ".join(f"{n}×{k}" for n, k in seen.items())
    return Finding("decoy-names", f"{named} in the opening, no name in the {rest_cjk} CJK chars after it")


def _code_digest(paths: Sequence[Path]) -> bytes:
    h = hashlib.sha256()
    for path in paths:
        data = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(len(data).to_bytes(8, "big") + data)
    return h.digest()


# Read once: a process running old rule code keeps stamping the old rev, so what it stores shows as unchecked.
_CODE = _code_digest([Path(__file__), Path(__file__).with_name("zh_tables.py"), Path(clean.__file__)])
