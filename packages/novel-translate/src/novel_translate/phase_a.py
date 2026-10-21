"""Phase A, the glossary pass: find a novel's names, ask a model about them, decide.

Steps, each resumable, so a run stopped by its budget or a cancel is continued by
the next one:
1. discover candidates in the raws (cached per set of raws);
2. classify the new ones, and every `proposed` term, in batches: is it a term,
   what category, one rendering per snippet (its votes);
3. hint: ask how the official English renders each term not yet hinted, in up to
   HINT_CHAPTERS chapters where the selected text is official English;
4. resolve every unedited open term from its votes (also after a stop);
5. summarize each chapter whose raw changed or has no summary yet.
Raws not checked with today's zh rules are left out of every step, as translation leaves them out.
A user's edit always wins: the store's writes skip edited terms.
"""

import hashlib
import threading
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import ahocorasick
from novel_core import NovelStore, SourceId

from novel_translate.budget import Budget
from novel_translate.discover import candidates
from novel_translate.glossary import Seen, Status, normalize
from novel_translate.models import LLM, CallFailed, Price, Sample
from novel_translate.pool import run_paid
from novel_translate.raws import RawRules, RawText, official_english, raw_chapters, version_text
from novel_translate.tstore import TranslateStore

BATCH = 30  # candidates per classification call
SNIPPETS = 3  # per candidate: its votes
CONTEXT = 80  # characters each side of an occurrence
HINT_CHAPTERS = 3
# Token estimates: an upper bound, not a forecast.
ZH_TOKENS_PER_CHAR = 1.0
EN_TOKENS_PER_CHAR = 0.35
INSTRUCTIONS = 300
SUMMARY_MAX_TOKENS = 400
CLASSIFY_TOKENS_PER_TERM = 80
HINT_TOKENS_PER_TERM = 40


@dataclass(frozen=True)
class GlossaryOptions:
    model: str
    workers: int = 4
    revote: bool = False  # re-decide unedited accepted terms too
    batch: int = BATCH


@dataclass(frozen=True)
class Estimate:
    """An upper bound: classification assumes every candidate is a term, hints assume three chapters each."""

    chapters: int
    calls: dict[str, int]  # per step: classify, hint, summarize
    usd: float
    unchecked: int  # raws left out: not checked with today's zh rules
    upper_bound: bool = True

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())


@dataclass
class GlossaryReport:
    candidates: int = 0  # new strings discovery found
    classified: int = 0
    hinted: int = 0  # chapters whose official English was consulted
    summarized: int = 0
    decided: dict[Status, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    calls: int = 0
    cost: float = 0.0
    stopped: str | None = None  # "budget reached" when the cap stopped it
    unchecked: int = 0  # raws left out: not checked with today's zh rules


type Progress = Callable[[int, int, str], None]


def estimate_glossary(
    novel: NovelStore, ts: TranslateStore, raw_rules: Mapping[SourceId, RawRules], price: Price, options: GlossaryOptions
) -> Estimate:
    plan = _plan(novel, ts, raw_rules)
    official_chars = sum(len(t) for t in plan.official_sample_texts(novel))
    classify_calls = -(-len(plan.to_classify) // options.batch)
    hint_terms = len(plan.unhinted_keys) + len(plan.to_classify)
    hint_calls = min(HINT_CHAPTERS * hint_terms, len(plan.official))
    avg_en = official_chars / max(1, min(len(plan.official), 20))
    usd = (
        sum(_summary_cost(price, r) for r in plan.to_summarize)
        + classify_calls * _classify_cost(price, options.batch)
        + hint_calls * _hint_cost(price, avg_en, max(1, hint_terms // max(1, hint_calls)))
    )  # fmt: skip
    calls = {"classify": classify_calls, "hint": hint_calls, "summarize": len(plan.to_summarize)}
    return Estimate(len(plan.raws), calls, usd, plan.unchecked)


def build_glossary(
    novel: NovelStore,
    ts: TranslateStore,
    raw_rules: Mapping[SourceId, RawRules],
    new_llm: Callable[[threading.Event], LLM],
    price: Price,
    budget: Budget,
    options: GlossaryOptions,
    progress: Progress,
) -> GlossaryReport:
    """Run the glossary pass; raises OutOfCredit, or whatever `progress` raises to cancel, after
    keeping the paid results of calls already sent."""
    report = GlossaryReport()
    plan = _plan(novel, ts, raw_rules)
    report.candidates, report.unchecked = len(plan.to_classify), plan.unchecked
    seen = _scan(plan.raws, [*plan.to_classify, *plan.unhinted_keys], set(plan.official))
    total = len(plan.to_summarize) + -(-len(plan.to_classify) // options.batch)  # hint calls are added once known
    done = 0

    def paid(items, reserve, call, on_result, step: str) -> bool:
        nonlocal done, total

        def tick(calls: int) -> None:
            progress(done + calls, max(total, done + calls), step)

        result = run_paid(
            items, reserve, call, on_result,
            new_llm=new_llm, budget=budget, workers=options.workers, progress=tick,
        )  # fmt: skip
        done += result.calls
        report.calls += result.calls
        report.cost += result.cost
        if not result.finished:
            report.stopped = "budget reached"
        return result.finished

    try:
        # 2. classify
        batches = [plan.to_classify[i : i + options.batch] for i in range(0, len(plan.to_classify), options.batch)]

        def classified(batch: Sequence[str], outcome) -> None:
            if isinstance(outcome, CallFailed):
                report.failed.append(f"classify {batch[0]}…: {outcome.reason}")
                return
            ts.record_verdicts(outcome.verdicts, {zh: seen[zh].seen for zh in batch if zh in seen})
            report.classified += len(outcome.verdicts)

        if not paid(
            batches,
            lambda batch: _classify_cost(price, len(batch)),
            lambda llm, batch: llm.classify(
                [Sample(zh, seen[zh].seen.snippets if zh in seen else ()) for zh in batch],
                max_tokens=INSTRUCTIONS + CLASSIFY_TOKENS_PER_TERM * len(batch),
            ),
            classified,
            "classify",
        ):
            return report

        # 3. hints from official English
        official = plan.official
        consulted = ts.consulted()
        pending: dict[int, set[int]] = {}
        by_chapter: dict[int, list] = defaultdict(list)
        nothing_left = []
        for term in ts.unhinted():
            chapters = sorted({n for key in (term.zh, *term.aliases) if key in seen for n in seen[key].official})
            left = set(chapters[:HINT_CHAPTERS]) - consulted.get(term.id, set())
            if not left:
                nothing_left.append(term.id)
                continue
            pending[term.id] = left
            for n in left:
                by_chapter[n].append(term)
        if nothing_left:
            ts.record_hints({}, {}, nothing_left)
        def english(number: int) -> str:
            return "\n".join(version_text(novel, s.version_id) for s in official[number])

        def hint_samples(number: int) -> list[Sample]:
            return [Sample(t.zh, seen[t.zh].in_chapter.get(number, ()) if t.zh in seen else ()) for t in by_chapter[number]]

        def hinted(number: int, outcome) -> None:
            if isinstance(outcome, CallFailed):
                report.failed.append(f"hint chapter {number}: {outcome.reason}")
                return
            renderings = {t.id: [outcome.renderings[t.zh]] for t in by_chapter[number] if t.zh in outcome.renderings}
            finished = []
            for t in by_chapter[number]:
                pending[t.id].discard(number)
                if not pending[t.id]:
                    finished.append(t.id)
            ts.record_hints(renderings, {t.id: number for t in by_chapter[number]}, finished)
            report.hinted += 1

        chapters = sorted(by_chapter)
        total += len(chapters)
        if not paid(
            [(n, english(n), hint_samples(n)) for n in chapters],
            lambda item: _hint_cost(price, len(item[1]), len(item[2])),
            lambda llm, item: llm.hint(item[2], item[1], max_tokens=INSTRUCTIONS + HINT_TOKENS_PER_TERM * len(item[2])),
            lambda item, outcome: hinted(item[0], outcome),
            "hint",
        ):
            return report

        # 5. summaries (4, resolve, runs in `finally`)
        def summarized(raw: RawText, outcome) -> None:
            if isinstance(outcome, CallFailed):
                report.failed.append(f"summary {raw.key.label}: {outcome.reason}")
                return
            ts.put_summary((raw.key.number, raw.key.part), raw.content_hash, options.model, outcome.text)
            report.summarized += 1

        paid(
            plan.to_summarize,
            lambda raw: _summary_cost(price, raw),
            lambda llm, raw: llm.summarize(raw.text, max_tokens=SUMMARY_MAX_TOKENS),
            summarized,
            "summarize",
        )
        return report
    finally:
        report.decided = ts.resolve(options.revote)


# -- planning ----------------------------------------------------------------------


@dataclass
class _Plan:
    raws: list[RawText]  # checked with today's zh rules
    unchecked: int  # raws left out
    to_classify: list[str]  # new candidates, most frequent first, then proposed terms without votes
    unhinted_keys: list[str]
    to_summarize: list[RawText]
    official: dict[int, list]

    def official_sample_texts(self, novel: NovelStore) -> list[str]:
        """A few official chapters, to size hint calls."""
        return [version_text(novel, s.version_id) for n in sorted(self.official)[:20] for s in self.official[n]]


def _plan(novel: NovelStore, ts: TranslateStore, raw_rules: Mapping[SourceId, RawRules]) -> _Plan:
    view = novel.view()
    every = list(raw_chapters(novel, view=view))
    raws = [r for r in every if not r.unchecked(raw_rules)]
    raws_hash = hashlib.sha256("\n".join(f"{r.key.label} {r.content_hash}" for r in raws).encode()).hexdigest()
    found = ts.discovery(raws_hash)
    if found is None:
        found = [(c.zh, c.count) for c in candidates((normalize(r.text) for r in raws), known=frozenset())]
        ts.set_discovery(raws_hash, found)
    known = ts.known_keys()
    proposed = [t.zh for t in ts.entries(status=Status.PROPOSED) if not any(c.origin == "llm" for c in ts.candidates(t.id))]
    to_classify = [zh for zh, _count in found if zh not in known] + proposed
    unhinted_keys = [key for t in ts.unhinted() for key in (t.zh, *t.aliases)]
    summaries = ts.summaries()
    to_summarize = [
        r for r in raws if (s := summaries.get((r.key.number, r.key.part))) is None or s.raw_hash != r.content_hash
    ]
    return _Plan(raws, len(every) - len(raws), to_classify, unhinted_keys, to_summarize, official_english(view))


@dataclass
class _Found:
    seen: Seen
    official: list[int]  # chapter numbers with official English where it occurs, up to HINT_CHAPTERS
    in_chapter: dict[int, tuple[str, ...]]  # a snippet in each of those chapters


def _scan(raws: Sequence[RawText], keys: Sequence[str], official: set[int]) -> dict[str, _Found]:
    """One pass over the raws for every key: count, first chapter, snippets in distinct chapters."""
    if not keys:
        return {}
    automaton = ahocorasick.Automaton()
    for key in keys:
        automaton.add_word(key, key)
    automaton.make_automaton()
    counts: dict[str, int] = defaultdict(int)
    first: dict[str, int] = {}
    snippets: dict[str, list[str]] = defaultdict(list)
    sampled: dict[str, set[int]] = defaultdict(set)
    hints: dict[str, dict[int, tuple[str, ...]]] = defaultdict(dict)
    for raw in raws:
        text = normalize(raw.text)
        number = raw.key.number
        for end, key in automaton.iter(text):
            counts[key] += 1
            first.setdefault(key, number)
            start = end - len(key) + 1
            snippet = None
            if len(snippets[key]) < SNIPPETS and number not in sampled[key]:
                snippet = _snippet(text, start, end)
                snippets[key].append(snippet)
                sampled[key].add(number)
            if number in official and len(hints[key]) < HINT_CHAPTERS and number not in hints[key]:
                hints[key][number] = (snippet or _snippet(text, start, end),)
    return {
        key: _Found(Seen(first[key], counts[key], tuple(snippets[key])), sorted(hints[key]), hints[key])
        for key in counts
    }


def _snippet(text: str, start: int, end: int) -> str:
    return text[max(0, start - CONTEXT) : end + 1 + CONTEXT].replace("\n", " ")


# -- cost bounds -------------------------------------------------------------------


def _summary_cost(price: Price, raw: RawText) -> float:
    return price.cost(int(len(raw.text) * ZH_TOKENS_PER_CHAR) + INSTRUCTIONS, SUMMARY_MAX_TOKENS)


def _classify_cost(price: Price, terms: int) -> float:
    prompt = terms * SNIPPETS * (2 * CONTEXT + 8) * ZH_TOKENS_PER_CHAR + INSTRUCTIONS
    return price.cost(int(prompt), INSTRUCTIONS + CLASSIFY_TOKENS_PER_TERM * terms)


def _hint_cost(price: Price, en_chars: float, terms: int) -> float:
    prompt = en_chars * EN_TOKENS_PER_CHAR + terms * (2 * CONTEXT + 8) * ZH_TOKENS_PER_CHAR + INSTRUCTIONS
    return price.cost(int(prompt), INSTRUCTIONS + HINT_TOKENS_PER_TERM * terms)
