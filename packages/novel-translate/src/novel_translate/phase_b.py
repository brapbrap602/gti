"""Phase B: translate raw chapters with one translator setup, against the glossary as it stands.

Each chapter key is translated once per `input_key`: a hash of everything its request
depends on (setup, raw text, the glossary lines it gets, the summaries and raw tail it
is given as context, and in sequential mode the previous chapter's translation). A
chapter whose latest good translation has the same input_key is current and skipped,
so a stopped run resumes where it ended and `stale` lists exactly what changed.

A chapter containing a term that needs review is not sent: it is marked failed as
blocked. Output failing a hard check is retried once in the same call; output cut off
at max_tokens is retried once with more room, after its own budget reservation.
Nothing that fails is stored. Every paid attempt is in the spend log; the ledger has
each chapter's outcome (its truth even when put_version finds the text unchanged).
"""

import hashlib
import json
import re
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import Literal

from novel_core import (
    ChapterKey,
    ItemStatus,
    KeyRange,
    NewVersion,
    NovelStore,
    NovelView,
    Paragraph,
    SourceId,
    SourceItem,
    chapter_heading,
)

from novel_translate.budget import Budget
from novel_translate.chapter import Translated
from novel_translate.matching import Match, Matcher
from novel_translate.models import LLM, Attempted, CallFailed, Charged, CutOff, Price
from novel_translate.pool import run_paid
from novel_translate.raws import RawText, raw_chapters, version_text
from novel_translate.setups import TranslatorSetup, prompt, register
from novel_translate.tstore import LedgerRow, StoredSummary, TranslateStore
from novel_translate.validate import Norms, check

CONTEXT_SUMMARIES = 10  # the story so far: this many preceding chapters' summaries
TAIL_PARAGRAPHS = 3
ZH_TOKENS_PER_CHAR = 1.0  # upper-bound estimates
EN_TOKENS_PER_CHAR = 0.35
OUTPUT_PER_SOURCE_TOKEN = 1.6
MIN_OUTPUT_TOKENS = 512
CUTOFF_GROWTH = 1.5
VALIDATOR_RETRY = 2  # a first attempt may cost twice: the in-call retry after a failed check

type Keys = KeyRange | Literal["stale"]
type Progress = Callable[[int, int, str], None]

_REF = re.compile(r"^n(\d+)(?:p(\d+))?$")


def ref_of(key: ChapterKey) -> str:
    return f"n{key.number}" + (f"p{key.part}" if key.part else "")


def key_of(ref: str) -> ChapterKey | None:
    m = _REF.match(ref)
    return ChapterKey(int(m.group(1)), int(m.group(2) or 0)) if m else None


@dataclass(frozen=True)
class Estimate:
    chapters: int  # to send
    current: int  # already translated with the same inputs
    blocked: int
    usd: float
    upper_bound: bool = True


@dataclass
class TranslateReport:
    translated: list[str] = field(default_factory=list)
    skipped: int = 0  # current already
    blocked: list[str] = field(default_factory=list)  # "<ref>: <reason>"
    failed: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    soft_flags: Counter = field(default_factory=Counter)
    calls: int = 0
    cost: float = 0.0
    stopped: str | None = None


@dataclass(frozen=True)
class StaleReport:
    stale: tuple[str, ...]  # refs whose inputs changed since their translation
    orphans: tuple[str, ...]  # refs whose raw chapter no longer exists


def estimate_translate(
    novel: NovelStore, ts: TranslateStore, setup: TranslatorSetup, keys: Keys, price: Price
) -> Estimate:
    run = _Run(novel, ts, setup)
    send = blocked = current = 0
    usd = 0.0
    for raw in run.selected(keys):
        state = run.state(raw)
        if state == "current":
            current += 1
        elif state == "blocked":
            blocked += 1
        else:
            send += 1
            usd += run.reservation(run.request(raw), price)
    return Estimate(send, current, blocked, usd)


def stale(novel: NovelStore, ts: TranslateStore, setup: TranslatorSetup) -> StaleReport:
    run = _Run(novel, ts, setup)
    ledger = ts.latest(setup.url)
    stale_refs = []
    for raw in run.raws:
        row = ledger.get(ref_of(raw.key))
        if row is not None and row.outcome == "ok" and row.input_key != run.input_key(raw):
            stale_refs.append(ref_of(raw.key))
    return StaleReport(tuple(stale_refs), tuple(run.orphans()))


def translate(
    novel: NovelStore,
    ts: TranslateStore,
    setup: TranslatorSetup,
    keys: Keys,
    new_llm: Callable[[threading.Event], LLM],
    price: Price,
    budget: Budget,
    workers: int,
    progress: Progress,
    report: TranslateReport | None = None,
) -> TranslateReport:
    """Translate the keys (a range, or "stale"); `report` is filled in as it goes, so a caller
    holding it still has the spend after a cancel. Raises OutOfCredit, or whatever `progress`
    raises, once the calls in flight have ended and their results are kept."""
    report = report if report is not None else TranslateReport()
    run = _Run(novel, ts, setup)
    source = register(novel, setup)
    run.source = source
    report.orphans = run.index(source, keys)
    if setup.context == "sequential":
        workers = 1
    selected = list(run.selected(keys))

    def requests() -> Iterator[_Request]:
        for raw in selected:
            state = run.state(raw)  # lazily: in sequential mode it depends on the previous chapter
            if state == "current":
                report.skipped += 1
            elif state == "blocked":
                reason = run.blocked_reason(raw)
                novel.mark_item(source, ref_of(raw.key), ItemStatus.FAILED, reason)
                report.blocked.append(f"{ref_of(raw.key)}: {reason}")
            else:
                yield run.request(raw)

    def call(llm: LLM, r: _Request) -> Attempted:
        try:
            return llm.translate(run.instructions, r.prompt, r.hard_checks, r.max_tokens)
        except CutOff as cut:
            # Once more with room to finish, after its own hold on the budget (the pool's hold
            # settles the chapter's whole cost, so this one is released with nothing spent).
            roomier = replace(r, max_tokens=int(r.max_tokens * CUTOFF_GROWTH))
            hold = budget.reserve(run.reservation(roomier, price, retry=False))
            if hold is None:
                raise CallFailed("budget", cut.charged) from cut
            try:
                second = llm.translate(run.instructions, r.prompt, r.hard_checks, roomier.max_tokens, retry_invalid=False)
            except CallFailed as e:
                raise CallFailed(e.reason, cut.charged + e.charged) from e
            finally:
                budget.settle(hold, 0.0)
            return Attempted(second.out, cut.charged + second.charged)

    def done(r: _Request, outcome: Attempted | CallFailed) -> None:
        ts.record_spend(setup.url, r.ref, outcome.charged)  # first, always: it was paid for
        if isinstance(outcome, CallFailed):
            run.failed(r, outcome.reason, outcome.charged)
            report.failed.append(f"{r.ref}: {outcome.reason}")
            return
        flags = run.stored(r, outcome.out, outcome.charged)
        report.translated.append(r.ref)
        report.soft_flags.update(f.split(":")[0] for f in flags)

    def tick(calls: int) -> None:
        progress(calls, max(calls, len(selected)), "translate")

    result = run_paid(
        requests(), lambda r: run.reservation(r, price), call, done,
        new_llm=new_llm, budget=budget, workers=workers, progress=tick,
    )  # fmt: skip
    report.calls, report.cost = result.calls, result.cost
    if not result.finished:
        report.stopped = "budget reached"
    return report


def prune(novel: NovelStore, ts: TranslateStore, setup: TranslatorSetup) -> tuple[str, ...]:
    """Drop the setup's orphans (translations of raw chapters that no longer exist) from its index."""
    run = _Run(novel, ts, setup)
    source = run.source
    if source is None:
        return ()
    orphans = run.orphans()
    if orphans:
        view = novel.view()
        info = view.source(source)
        keep = [i for i in view.items(source) if i.ref not in orphans and not i.vanished]
        novel.set_alignment(source, replace(info.alignment, skip=info.alignment.skip - set(orphans)))
        novel.record_index(source, [_item(i.ref, pos, i.title) for pos, i in enumerate(keep, 1)])
    return tuple(orphans)


# -- one run's view of the novel ---------------------------------------------------


@dataclass(frozen=True)
class _Request:
    raw: RawText
    match: Match
    input_key: str
    prompt: str
    max_tokens: int
    hard_checks: Callable[[Translated], tuple[str, ...]]

    @property
    def ref(self) -> str:
        return ref_of(self.raw.key)


class _Run:
    def __init__(self, novel: NovelStore, ts: TranslateStore, setup: TranslatorSetup):
        self.novel, self.ts, self.setup = novel, ts, setup
        self.view: NovelView = novel.view()
        self.raws: list[RawText] = list(raw_chapters(novel, view=self.view))
        self.position = {r.key: i for i, r in enumerate(self.raws)}
        self.summaries: dict[tuple[int, int], StoredSummary] = ts.summaries()
        self.matcher: Matcher = ts.matcher()
        self.norms: Norms = ts.norms()
        self.ledger: dict[str, LedgerRow] = ts.latest(setup.url)
        self.instructions = prompt(setup.prompt_version)
        self.source: SourceId | None = next(
            (i.id for i in self.view.sources if (i.spec.backend, i.spec.url) == (setup.spec().backend, setup.url)), None
        )
        self.translated: dict[ChapterKey, str] = {}  # key -> current content hash of this setup's text
        self.translated_version: dict[ChapterKey, int] = {}
        if self.source is not None:
            for s in self.view.chapters(self.source):
                self.translated[s.key] = s.content_hash
                self.translated_version[s.key] = s.version_id
        self._matches: dict[ChapterKey, Match] = {}

    # -- which chapters, and in what state --------------------------------

    def selected(self, keys: Keys) -> Iterator[RawText]:
        if keys == "stale":
            wanted = set(stale(self.novel, self.ts, self.setup).stale)
            return (r for r in self.raws if ref_of(r.key) in wanted)
        return (r for r in self.raws if r.key.number in keys)

    def match(self, raw: RawText) -> Match:
        if raw.key not in self._matches:
            self._matches[raw.key] = self.matcher.match(raw.text)
        return self._matches[raw.key]

    def state(self, raw: RawText) -> str:
        if self.match(raw).blocking:
            return "blocked"
        row = self.ledger.get(ref_of(raw.key))
        if row is not None and row.outcome == "ok" and row.input_key == self.input_key(raw):
            return "current"
        return "send"

    def blocked_reason(self, raw: RawText) -> str:
        terms = []
        for t in self.match(raw).blocking:
            renderings = " / ".join(dict.fromkeys(c.en for c in self.ts.candidates(t.id)))
            terms.append(f"{t.zh} ({renderings})" if renderings else t.zh)
        return "blocked: " + "; ".join(terms)

    def input_key(self, raw: RawText) -> str:
        i = self.position[raw.key]
        before = self.raws[max(0, i - CONTEXT_SUMMARIES) : i]
        previous = self.raws[i - 1] if i else None
        parts = {
            "setup": self.setup.url,
            "raw": raw.content_hash,
            "glossary": self.match(raw).subset_hash,
            "summaries": [_hash(s.text) if (s := self._summary(r)) else None for r in before],
            "previous_raw": previous.content_hash if previous else None,
        }
        if self.setup.context == "sequential":
            parts["previous_translation"] = self.translated.get(previous.key) if previous else None
        return _hash(json.dumps(parts, sort_keys=True))

    # -- requests -----------------------------------------------------------

    def request(self, raw: RawText) -> _Request:
        i = self.position[raw.key]
        match = self.match(raw)
        sections = []
        story = [
            f"Chapter {r.key.label}: {s.text}"
            for r in self.raws[max(0, i - CONTEXT_SUMMARIES) : i]
            if (s := self._summary(r))
        ]
        if story:
            sections.append("## Story so far\n" + "\n".join(story))
        if i:
            previous = self.raws[i - 1]
            sections.append("## End of the previous chapter (context only)\n" + "\n".join(previous.paragraphs[-TAIL_PARAGRAPHS:]))
            if self.setup.context == "sequential" and previous.key in self.translated_version:
                english = version_text(self.novel, self.translated_version[previous.key]).split("\n")
                sections.append("## End of the previous chapter in English (context only)\n" + "\n".join(english[-TAIL_PARAGRAPHS:]))
        if match.prompt_lines:
            sections.append("## Glossary\n" + "\n".join(match.prompt_lines))
        body = "\n".join(f"[{n}] {p}" for n, p in enumerate(raw.paragraphs, 1))
        sections.append(f"## Chapter to translate (title: {raw.title})\n{body}")
        source_tokens = sum(len(p) for p in raw.paragraphs) * ZH_TOKENS_PER_CHAR
        allowance = max(MIN_OUTPUT_TOKENS, int(source_tokens * OUTPUT_PER_SOURCE_TOKEN))
        if self.setup.reasoning != "off":
            allowance *= 2
        norms, paragraphs = self.norms, raw.paragraphs
        return _Request(
            raw, match, self.input_key(raw), "\n\n".join(sections), allowance,
            lambda out: check(paragraphs, out, match, norms).hard,
        )  # fmt: skip

    def reservation(self, r: _Request, price: Price, retry: bool = True) -> float:
        """An upper bound on a request's cost; `retry` covers the call's one retry after a failed check."""
        chinese = sum(1 for ch in r.prompt if "㐀" <= ch <= "鿿")
        tokens_in = chinese * ZH_TOKENS_PER_CHAR + (len(r.prompt) - chinese + len(self.instructions)) * EN_TOKENS_PER_CHAR
        cost = price.cost(int(tokens_in), r.max_tokens)
        return cost * VALIDATOR_RETRY if retry else cost

    # -- writes (the coordinating thread only) ------------------------------

    def stored(self, r: _Request, out: Translated, spent: Charged) -> tuple[str, ...]:
        findings = check(r.raw.paragraphs, out, r.match, self.norms)
        by_id = sorted(out.paragraphs, key=lambda p: p.id)
        version = NewVersion(
            chapter_heading(r.raw.key, out.title),
            tuple(Paragraph.of(p.text.strip()) for p in by_id),
            provenance={
                "setup": self.setup.url, "model": self.setup.model, "prompt": self.setup.prompt_version,
                "raw_source": r.raw.source_id, "raw_hash": r.raw.content_hash, "glossary_revision": self.ts.revision,
            },
        )  # fmt: skip
        put = self.novel.put_version(self.source, r.ref, version)
        self.translated[r.raw.key] = put.content_hash
        self.translated_version[r.raw.key] = put.version_id
        self.ts.record_outcome(
            self.setup.url,
            LedgerRow(r.ref, r.input_key, put.content_hash, "ok", None, spent.cost, spent.requests, findings.soft),
        )
        if out.new_terms:
            self.ts.propose([(t.zh, t.en, t.category) for t in out.new_terms])
        return findings.soft

    def failed(self, r: _Request, reason: str, spent: Charged) -> None:
        self.ts.record_outcome(
            self.setup.url, LedgerRow(r.ref, r.input_key, None, "failed", reason, spent.cost, spent.requests, ())
        )
        self.novel.mark_item(self.source, r.ref, ItemStatus.FAILED, reason)

    def index(self, source: SourceId, keys: Keys) -> list[str]:
        """Record the setup's index cumulatively: what it already lists whose raw chapter still
        exists, plus these keys. Orphans with text are skipped (kept, never published); orphans
        without text are dropped. Returns the orphans."""
        view = self.novel.view()
        info = view.source(source)
        listed = {i.ref: i for i in view.items(source) if not i.vanished}
        raw_refs = {ref_of(r.key) for r in self.raws}
        wanted = {ref_of(r.key) for r in self.selected(keys)} if keys != "stale" else set()
        orphans = sorted(ref for ref in listed if ref not in raw_refs)
        with_text = {ref for ref in orphans if listed[ref].has_text}
        keep = [ref_of(r.key) for r in self.raws if ref_of(r.key) in listed or ref_of(r.key) in wanted]
        items = [_item(ref, pos, listed[ref].title if ref in listed else None) for pos, ref in enumerate(keep, 1)]
        items += [_item(ref, len(items) + n, listed[ref].title) for n, ref in enumerate(sorted(with_text), 1)]
        if with_text - info.alignment.skip:
            self.novel.set_alignment(source, replace(info.alignment, skip=info.alignment.skip | with_text))
        self.novel.record_index(source, items)
        return sorted(with_text)

    def orphans(self) -> list[str]:
        if self.source is None:
            return []
        raw_refs = {ref_of(r.key) for r in self.raws}
        return sorted(i.ref for i in self.view.items(self.source) if not i.vanished and i.ref not in raw_refs and i.has_text)

    def _summary(self, raw: RawText) -> StoredSummary | None:
        s = self.summaries.get((raw.key.number, raw.key.part))
        return s if s is not None and s.raw_hash == raw.content_hash else None


def _item(ref: str, position: int, title: str | None) -> SourceItem:
    key = key_of(ref)
    return SourceItem(ref, position, title or f"Chapter {key.label}", number=key.number, part=key.part, ref_numbered=False)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

