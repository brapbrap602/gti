import random
import re
import threading

import pytest
from novel_core import AlignmentRules, ChapterKey, Finding, KeyRange, Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec
from novel_translate.budget import Budget
from novel_translate.glossary import AddTerm, Category, Status, UpdateTerm
from novel_translate.models import LLM, Price
from novel_translate.phase_b import (
    COMPARE_SPEND,
    GROUP_ADDENDUM,
    TranslateReport,
    compare,
    estimate_compare,
    estimate_translate,
    prune,
    stale,
    translate,
)
from novel_translate.raws import RawRules
from novel_translate.setups import SetupError, TranslatorSetup, prompt, register
from novel_translate.tstore import TranslateStore
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

PRICE = Price(0.000001, 0.000002)
SETUP = TranslatorSetup("vendor/cheap")
REV = "rules-1"  # the zh rules revision the raws were checked with
FILLER = "山水风云天地日月花草木石金银铜铁春夏秋冬东西南北红黄蓝白黑青紫长短高低远近快慢冷热明暗新旧大小多少"


def raw_paragraphs(number: int) -> list[str]:
    rng = random.Random(number)
    paragraphs = ["".join(rng.choice(FILLER) for _ in range(rng.randint(40, 60))) for _ in range(4)]
    paragraphs[1] = "韩立" + paragraphs[1]
    return paragraphs


def english(n_chars: int, seed: str) -> str:
    """Varied made-up English, about 0.6 words per Chinese character."""
    rng = random.Random(seed)
    words = ["".join(rng.choice("aeioubcdfghklmnprstvw") for _ in range(rng.randint(3, 8))) for _ in range(int(n_chars * 0.6))]
    return " ".join(words) + "."


class Translator:
    """A fake model: translates each [id] paragraph; `plan[number]` lists what its next calls do."""

    def __init__(self, plan=None, gate: threading.Event | None = None):
        self.plan: dict[int, list[str]] = {k: list(v) for k, v in (plan or {}).items()}
        self.prompts: dict[int, list[str]] = {}
        self.instructions: dict[int, list[str]] = {}
        self.max_tokens: dict[int, list[int]] = {}
        self.gate = gate
        self.lock = threading.Lock()

    def llm(self, cancel: threading.Event) -> LLM:
        return LLM(FunctionModel(self.answer), lambda: PRICE, cancel)

    def answer(self, messages, info) -> ModelResponse:
        prompt = next(p.content for p in messages[0].parts if isinstance(p, UserPromptPart))
        number = int(re.search(r"\(title: 第(\d+)章\)", prompt).group(1))
        with self.lock:
            self.prompts.setdefault(number, []).append(prompt)
            self.instructions.setdefault(number, []).append(info.instructions)
            self.max_tokens.setdefault(number, []).append(info.model_settings["max_tokens"])
            behaviour = self.plan.get(number, []).pop(0) if self.plan.get(number) else "clean"
        if self.gate is not None:
            self.gate.wait(5)
        source = re.findall(r"^\[(\d+)\] (.+)$", prompt.split("## Chapter to translate")[1], re.M)
        paragraphs = [{"id": int(i), "text": ("Han Li " if "韩立" in text else "") + english(len(text), f"{number}-{i}")}
                      for i, text in source]  # fmt: skip
        result = {"title": f"The Title of {number}", "paragraphs": paragraphs, "new_terms": []}
        if behaviour == "loop":
            result["paragraphs"] = [{"id": p["id"], "text": "the same words again and again here " * 3} for p in paragraphs]
        elif behaviour == "terms":
            result["new_terms"] = [{"zh": "七玄门", "en": "Seven Mysteries Sect", "category": "sect"}]
        elif behaviour == "cut":
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, '{"title": "The Ti')], finish_reason="length")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, result)])


class Novel:
    """Raw sources and their zh rules: `rules` is what the app would pass as raw_rules."""

    def __init__(self, store: NovelStore, raw: int):
        self.store, self.raw = store, raw
        self.numbers: dict[int, set[int]] = {raw: set()}
        self.rules: dict[int, RawRules] = {raw: RawRules("", REV)}

    def raw_source(self, name: str, notes: str = "") -> int:
        source = self.store.upsert_source(SourceSpec("custom:raw", f"https://{name}.test", "zh", Kind.RAW_ZH))
        self.numbers[source] = set()
        self.rules[source] = RawRules(notes, REV)
        return source

    def raws(self, numbers, text=raw_paragraphs, source=None, rev=REV, findings=()) -> None:
        """Store raw texts for these numbers, checked by `rev` with these findings; the index keeps
        every number stored before."""
        source = source or self.raw
        self.numbers[source] |= set(numbers)
        self.store.record_index(source, [SourceItem(f"/{n}", n, f"第{n}章", number=n) for n in sorted(self.numbers[source])])
        for n in numbers:
            paragraphs = tuple(Paragraph.of(p) for p in text(n))
            self.store.put_version(source, f"/{n}", NewVersion(f"第{n}章", paragraphs, findings=findings, rules_rev=rev))

    def hold(self, number: int, source=None) -> None:
        """Poison the raw of this number (same text, now with a finding)."""
        self.raws([number], source=source, findings=(Finding("poison", "有没×9"),))

    def setup_source(self, setup=SETUP) -> int:
        return next(i.id for i in self.store.sources() if i.spec.url == setup.url)

    def texts(self, setup=SETUP) -> dict[str, str]:
        source = self.setup_source(setup)
        return {s.item_ref: s.title for s in self.store.chapters(source)}


@pytest.fixture
def novel(tmp_path):
    with NovelStore.create(tmp_path / "novel", NovelMeta("Test")) as store:
        n = Novel(store, store.upsert_source(SourceSpec("custom:raw", "https://raw.test", "zh", Kind.RAW_ZH)))
        n.raws(range(1, 13))
        yield n


@pytest.fixture
def ts(tmp_path):
    with TranslateStore.create(tmp_path / "novel") as store:
        store.apply([AddTerm("韩立", "Han Li", Category.PERSON)])
        yield store


def run(novel, ts, translator, keys, setup=SETUP, budget=None, workers=4, progress=lambda *_: None, report=None):
    return translate(novel.store, ts, novel.rules, setup, keys, translator.llm, PRICE, budget or Budget(100.0), workers, progress, report)


def test_chapters_are_stored_unpublished_with_a_ledger_row_each(novel, ts):
    report = run(novel, ts, Translator(), KeyRange(1, 3))
    assert sorted(report.translated) == ["n1", "n2", "n3"] and report.failed == [] and report.cost > 0
    source = novel.setup_source()
    info = next(i for i in novel.store.sources() if i.id == source)
    assert info.published is False and info.spec.kind is Kind.MY_TRANSLATION
    assert novel.texts() == {"n1": "Chapter 1: The Title of 1", "n2": "Chapter 2: The Title of 2", "n3": "Chapter 3: The Title of 3"}
    assert novel.store.selection() == ()  # unpublished: not in the book
    ledger = ts.latest(SETUP.url)
    assert {r.outcome for r in ledger.values()} == {"ok"} and all(r.cost > 0 for r in ledger.values())
    assert ts.spend(SETUP.url).cost == pytest.approx(report.cost)


def test_the_index_grows_and_a_rerun_is_free(novel, ts):
    run(novel, ts, Translator(), KeyRange(1, 2))
    run(novel, ts, Translator(), KeyRange(3, 4))
    assert set(novel.texts()) == {"n1", "n2", "n3", "n4"}
    again = Translator()
    report = run(novel, ts, again, KeyRange(1, 4))
    assert again.prompts == {} and report.skipped == 4


def test_a_glossary_edit_makes_its_chapters_stale_and_the_ledger_follows_unchanged_text(novel, ts):
    def text(n):
        paragraphs = raw_paragraphs(n)
        if n == 2:
            paragraphs[0] = "墨大夫" + paragraphs[0]
        return paragraphs

    novel.raws(range(1, 13), text)
    ts.apply([AddTerm("墨大夫", "Doctor Mo", Category.TITLE)])
    run(novel, ts, Translator(), KeyRange(1, 3))
    assert stale(novel.store, ts, novel.rules, SETUP).stale == ()

    mo = next(t.id for t in ts.entries() if t.zh == "墨大夫")
    ts.apply([UpdateTerm(mo, en="Physician Mo")])
    assert stale(novel.store, ts, novel.rules, SETUP).stale == ("n2",)
    report = run(novel, ts, Translator(), "stale")  # the fake gives the same text again: put_version says Unchanged
    assert report.translated == ["n2"]
    assert stale(novel.store, ts, novel.rules, SETUP).stale == ()


def test_a_changed_raw_stales_its_chapter_and_the_next_ones(novel, ts):
    run(novel, ts, Translator(), KeyRange(1, 12))
    for n in range(1, 13):
        ts.put_summary((n, 0), novel.store.view().chapters(novel.raw)[n - 1].content_hash, "m", f"summary {n}")
    run(novel, ts, Translator(), KeyRange(1, 12))  # summaries are now part of every input
    novel.raws([2], lambda n: raw_paragraphs(n) + ["新的一段。"])
    ts.put_summary((2, 0), novel.store.view().chapters(novel.raw)[1].content_hash, "m", "a new summary 2")
    assert stale(novel.store, ts, novel.rules, SETUP).stale == tuple(f"n{n}" for n in range(2, 13))


def test_a_term_needing_review_blocks_its_chapters_and_the_block_persists(novel, ts):
    novel.raws([2], lambda n: ["七玄门" + p for p in raw_paragraphs(n)])
    ts.record_verdicts([], {})
    ts.propose([("七玄门", "Seven Mysteries Sect", Category.SECT)])
    gate = next(t.id for t in ts.entries() if t.zh == "七玄门")
    ts.apply([UpdateTerm(gate, status=Status.NEEDS_REVIEW)])

    report = run(novel, ts, Translator(), KeyRange(1, 3))
    assert sorted(report.translated) == ["n1", "n3"]
    assert report.blocked == ["n2: blocked: 七玄门 (Seven Mysteries Sect)"]
    failed = [(f.item_ref, f.detail) for f in novel.store.check().failed]
    assert failed == [("n2", "blocked: 七玄门 (Seven Mysteries Sect)")]

    other = TranslatorSetup("vendor/other")
    run(novel, ts, Translator(), KeyRange(1, 1), setup=other)
    assert ("n2", "blocked: 七玄门 (Seven Mysteries Sect)") in [(f.item_ref, f.detail) for f in novel.store.check().failed]


def test_invalid_output_gets_one_retry_inside_the_call(novel, ts):
    translator = Translator({1: ["loop"]})
    report = run(novel, ts, translator, KeyRange(1, 1))
    assert report.translated == ["n1"]
    row = ts.latest(SETUP.url)["n1"]
    assert row.attempts == 2 and len(translator.prompts[1]) == 2
    assert row.cost == pytest.approx(ts.spend(SETUP.url).cost)


def test_output_invalid_twice_is_not_stored_but_its_cost_is(novel, ts):
    budget = Budget(100.0)
    report = run(novel, ts, Translator({1: ["loop", "loop"]}), KeyRange(1, 1), budget=budget)
    assert report.translated == [] and report.failed == ["n1: invalid: loop"]
    assert "n1" not in novel.texts()
    row = ts.latest(SETUP.url)["n1"]
    assert (row.outcome, row.attempts) == ("failed", 2) and row.cost > 0
    assert budget.spent == pytest.approx(row.cost)
    assert [(f.item_ref, f.detail) for f in novel.store.check().failed] == [("n1", "invalid: loop")]


def test_cut_off_output_is_retried_with_more_room_after_its_own_reservation(novel, ts):
    holds = []

    class Watching(Budget):
        def reserve(self, estimate):
            holds.append(estimate)
            return super().reserve(estimate)

    # The first cut-off uses the call's one retry; the second ends the call, and the chapter is sent again.
    translator = Translator({1: ["cut", "cut"]})
    report = run(novel, ts, translator, KeyRange(1, 1), budget=Watching(100.0))
    assert report.translated == ["n1"]
    first, again, roomier = translator.max_tokens[1]
    assert again == first and roomier == int(first * 1.5)
    assert len(holds) == 2
    row = ts.latest(SETUP.url)["n1"]
    assert row.attempts == 3 and row.cost == pytest.approx(ts.spend(SETUP.url).cost)


def test_cut_off_twice_more_fails_the_chapter(novel, ts):
    report = run(novel, ts, Translator({1: ["cut", "cut", "cut"]}), KeyRange(1, 1))
    assert report.failed == ["n1: cut-off"] and "n1" not in novel.texts()


def test_a_missing_glossary_rendering_is_stored_with_a_flag(novel, ts):
    han = next(t.id for t in ts.entries() if t.zh == "韩立")
    ts.apply([UpdateTerm(han, en="Lord Han")])
    report = run(novel, ts, Translator(), KeyRange(1, 1))
    assert report.translated == ["n1"] and report.soft_flags["term"] == 1
    assert ts.latest(SETUP.url)["n1"].soft_flags == ("term:韩立", "pinyin:韩立")  # the fake writes "Han Li"


def test_new_terms_from_a_translation_are_proposed_and_never_injected(novel, ts):
    run(novel, ts, Translator({1: ["terms"]}), KeyRange(1, 1))
    gate = next(t for t in ts.entries() if t.zh == "七玄门")
    assert (gate.status, gate.origin) == (Status.PROPOSED, "side-channel")
    later = Translator()
    novel.raws([2], lambda n: ["七玄门" + p for p in raw_paragraphs(n)])
    run(novel, ts, later, KeyRange(2, 2))
    assert "七玄门" not in later.prompts[2][0].split("## Glossary")[1].split("##")[0]


def test_cancel_keeps_the_paid_results_of_calls_in_flight(novel, ts):
    gate = threading.Event()

    class Cancelled(Exception):
        pass

    def progress(done, total, step):
        raise Cancelled()

    report = TranslateReport()
    threading.Timer(0.3, gate.set).start()
    with pytest.raises(Cancelled):
        run(novel, ts, Translator(gate=gate), KeyRange(1, 12), workers=4, progress=progress, report=report)
    stored = set(novel.texts())
    assert len(stored) == 4  # the four in flight when the first result came back
    assert ts.spend(SETUP.url).cost > 0 and set(ts.latest(SETUP.url)) == stored


def test_sequential_mode_gives_the_previous_translation_and_chains_staleness(novel, ts):
    sequential = TranslatorSetup("vendor/cheap", context="sequential")
    translator = Translator()
    run(novel, ts, translator, KeyRange(1, 3), setup=sequential)
    assert "## End of the previous chapter in English" in translator.prompts[2][0]
    assert "## End of the previous chapter in English" not in translator.prompts[1][0]

    novel.raws([2], lambda n: raw_paragraphs(n) + ["新的一段。"])
    run(novel, ts, Translator(), KeyRange(2, 2), setup=sequential)
    assert stale(novel.store, ts, novel.rules, sequential).stale == ("n3",)


def test_a_setup_is_immutable(novel, ts):
    novel.store.upsert_source(SourceSpec("translate:openrouter", SETUP.url, "en", Kind.MY_TRANSLATION, {"model": "x"}))
    with pytest.raises(SetupError, match="another configuration"):
        register(novel.store, SETUP)
    with pytest.raises(SetupError, match="no prompt"):
        TranslatorSetup("vendor/cheap", prompt_version="v99")


def test_an_orphan_is_never_published_and_prune_drops_it(novel, ts):
    novel.raws([4411], raw_paragraphs)
    run(novel, ts, Translator(), KeyRange(4411, 4411))
    source = novel.setup_source()
    novel.store.set_published(source, True)
    assert "n4411" in {s.item_ref for s in novel.store.selection()}

    novel.store.set_alignment(novel.raw, AlignmentRules(items={"/4411": ChapterKey(13)}))  # TM's misnumbered chapter
    report = run(novel, ts, Translator(), KeyRange(13, 13))
    assert report.orphans == ["n4411"]
    assert "n13" in novel.texts() and "n4411" not in {s.item_ref for s in novel.store.selection()}
    assert novel.store.check().gaps == ()
    assert stale(novel.store, ts, novel.rules, SETUP).orphans == ("n4411",)
    assert prune(novel.store, ts, novel.rules, SETUP) == ("n4411",)
    assert stale(novel.store, ts, novel.rules, SETUP).orphans == ()


def test_the_cap_holds_with_retries_in_flight(novel, ts):
    one = estimate_translate(novel.store, ts, novel.rules, SETUP, KeyRange(1, 1), PRICE).usd
    budget = Budget(one * 2.5)
    report = run(novel, ts, Translator({1: ["loop"], 2: ["cut"]}), KeyRange(1, 8), budget=budget, workers=4)
    assert report.stopped == "budget reached"
    assert budget.spent <= budget.cap
    assert len(report.translated) + len(report.failed) <= 3


def test_the_estimate_counts_what_would_be_sent(novel, ts):
    run(novel, ts, Translator(), KeyRange(1, 2))
    estimate = estimate_translate(novel.store, ts, novel.rules, SETUP, KeyRange(1, 5), PRICE)
    assert (estimate.chapters, estimate.current, estimate.blocked) == (3, 2, 0) and estimate.usd > 0


# -- comparing setups ----------------------------------------------------------------

OTHER = TranslatorSetup("vendor/other")
PRICES = {SETUP.url: PRICE, OTHER.url: PRICE}


def compare_with(novel, ts, translators, keys, budget=None, setups=(SETUP, OTHER)):
    return compare(
        novel.store, ts, novel.rules, setups, keys, lambda setup, cancel: translators[setup.model].llm(cancel), PRICES,
        budget or Budget(100.0), 2, lambda *_: None,
    )  # fmt: skip


def test_a_comparison_sends_what_translate_sends_and_stores_nothing(novel, ts):
    ts.put_summary((1, 0), novel.store.view().chapters(novel.raw)[0].content_hash, "m", "summary 1")
    fakes = {"vendor/cheap": Translator(), "vendor/other": Translator({3: ["loop", "loop"]})}
    sources_before, versions_before = novel.store.sources(), novel.store.view().selection

    result = compare_with(novel, ts, fakes, KeyRange(2, 3))

    assert [r.key.number for r in result.raws] == [2, 3]
    cheap, other = result.attempts[SETUP.url], result.attempts[OTHER.url]
    assert cheap["n2"].title == "The Title of 2" and len(cheap["n2"].paragraphs) == 4 and cheap["n2"].failure is None
    assert cheap["n2"].charged.cost > 0 and cheap["n2"].seconds >= 0
    assert other["n3"].failure == "invalid: loop" and other["n3"].paragraphs == ()
    assert novel.store.sources() == sources_before and novel.store.view().selection == versions_before
    assert ts.latest(SETUP.url) == {} and ts.spend(SETUP.url).cost == 0
    assert ts.spend(COMPARE_SPEND + SETUP.url).cost == pytest.approx(cheap["n2"].charged.cost + cheap["n3"].charged.cost)
    assert result.cost == pytest.approx(sum(ts.spend(COMPARE_SPEND + s.url).cost for s in (SETUP, OTHER)))

    production = Translator()
    run(novel, ts, production, KeyRange(2, 2))
    assert fakes["vendor/cheap"].prompts[2] == production.prompts[2]  # the very prompt production sends


def test_a_comparison_estimate_is_per_setup_and_bounds_the_spend(novel, ts):
    estimates = estimate_compare(novel.store, ts, novel.rules, (SETUP, OTHER), KeyRange(1, 3), PRICES)
    assert set(estimates) == {SETUP.url, OTHER.url} and estimates[SETUP.url].usd == estimates[OTHER.url].usd > 0
    result = compare_with(novel, ts, {"vendor/cheap": Translator(), "vendor/other": Translator()}, KeyRange(1, 3))
    assert result.cost <= sum(e.usd for e in estimates.values())


def test_the_budget_stops_a_comparison_and_the_rest_is_marked_not_sent(novel, ts):
    one_chapter = estimate_compare(novel.store, ts, novel.rules, (SETUP,), KeyRange(1, 1), PRICES)[SETUP.url].usd
    result = compare_with(
        novel, ts, {"vendor/cheap": Translator(), "vendor/other": Translator()}, KeyRange(1, 3), Budget(one_chapter * 1.5)
    )
    outcomes = {url: sorted(a.failure or "ok" for a in by_ref.values()) for url, by_ref in result.attempts.items()}
    assert outcomes[SETUP.url] == ["not sent", "not sent", "ok"]  # the first chapter's hold leaves no room for a second
    assert len(outcomes[OTHER.url]) == 3 and "not sent" in outcomes[OTHER.url]  # what the first left unspent
    assert result.cost <= one_chapter * 1.5


def test_a_comparison_reports_blocked_chapters_and_refuses_sequential_setups(novel, ts):
    novel.raws([2], lambda n: ["七玄门" + p for p in raw_paragraphs(n)])
    ts.propose([("七玄门", "Seven Mysteries Sect", Category.SECT)])
    gate = next(t.id for t in ts.entries() if t.zh == "七玄门")
    ts.apply([UpdateTerm(gate, status=Status.NEEDS_REVIEW)])
    fake = Translator()
    result = compare_with(novel, ts, {"vendor/cheap": fake}, KeyRange(1, 2), setups=(SETUP,))
    assert result.attempts[SETUP.url]["n2"].failure == "blocked: 七玄门 (Seven Mysteries Sect)"
    assert set(fake.prompts) == {1}
    with pytest.raises(SetupError, match="parallel"):
        compare_with(novel, ts, {}, KeyRange(1, 1), setups=(TranslatorSetup("vendor/x", context="sequential"),))


class GroupTranslator:
    """A fake model for group requests: translates every '### Chapter N' section; `drop_first` leaves
    the last chapter out of its first answer."""

    def __init__(self, drop_first: bool = False):
        self.prompts: list[str] = []
        self.instructions: list[str] = []
        self.drop = drop_first

    def llm(self, cancel: threading.Event) -> LLM:
        return LLM(FunctionModel(self.answer), lambda: PRICE, cancel)

    def answer(self, messages, info) -> ModelResponse:
        prompt = next(p.content for p in messages[0].parts if isinstance(p, UserPromptPart))
        self.prompts.append(prompt)
        self.instructions.append(info.instructions)
        chapters = []
        for number, body in re.findall(r"^### Chapter (\d+) \(title: [^)]*\)\n((?:\[\d+\] .+\n?)+)", prompt, re.M):
            source = re.findall(r"^\[(\d+)\] (.+)$", body, re.M)
            paragraphs = [{"id": int(i), "text": ("Han Li " if "韩立" in t else "") + english(len(t), f"{number}-{i}")} for i, t in source]
            chapters.append({"number": int(number), "title": f"The Title of {number}", "paragraphs": paragraphs, "new_terms": []})
        if self.drop:
            self.drop, chapters = False, chapters[:-1]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"chapters": chapters})])


def test_a_group_setup_sends_several_chapters_in_one_request_and_splits_the_answer(novel, ts):
    grouped = TranslatorSetup("vendor/cheap", group=3)
    fake = GroupTranslator(drop_first=True)
    result = compare(
        novel.store, ts, novel.rules, (grouped,), KeyRange(2, 4), lambda setup, cancel: fake.llm(cancel), {grouped.url: PRICE},
        Budget(100.0), 2, lambda *_: None,
    )  # fmt: skip

    (prompt,) = set(fake.prompts)  # one request, sent again once after the missing chapter
    assert len(fake.prompts) == 2 and "several consecutive chapters" in fake.instructions[0]
    assert prompt.count("## End of the previous chapter") == 1 and prompt.index("## End of the previous") < prompt.index("### Chapter 2")
    assert [n for n in re.findall(r"^### Chapter (\d+)", prompt, re.M)] == ["2", "3", "4"]
    attempts = result.attempts[grouped.url]
    assert [a.title for a in attempts.values()] == ["The Title of 2", "The Title of 3", "The Title of 4"]
    assert all(a.shared == 3 and len(a.paragraphs) == 4 for a in attempts.values())
    assert sum(a.charged.cost for a in attempts.values()) == pytest.approx(ts.spend(COMPARE_SPEND + grouped.url).cost)


def test_a_group_setup_is_its_own_setup_and_not_for_production_yet(novel, ts):
    assert SETUP.url == "openrouter:vendor/cheap?prompt=v1&context=parallel&reasoning=off&dc=allow"
    grouped = TranslatorSetup("vendor/cheap", group=5)
    assert grouped.url == SETUP.url + "&group=5" and "5 chapters per request" in grouped.label
    assert TranslatorSetup.from_spec(grouped.spec()) == grouped and TranslatorSetup.from_spec(SETUP.spec()) == SETUP
    with pytest.raises(SetupError, match="comparisons only"):
        run(novel, ts, Translator(), KeyRange(1, 2), setup=grouped)
    with pytest.raises(SetupError, match="one chapter per request"):
        TranslatorSetup("vendor/cheap", context="sequential", group=2)


# -- held and unchecked raws, translator notes ------------------------------------------

UNCHECKED = "unchecked (not checked with current rules)"


def grouped_compare(novel, ts, fake, keys, group=3):
    grouped = TranslatorSetup("vendor/cheap", group=group)
    return compare(
        novel.store, ts, novel.rules, (grouped,), keys, lambda setup, cancel: fake.llm(cancel), {grouped.url: PRICE},
        Budget(100.0), 2, lambda *_: None,
    ).attempts[grouped.url]  # fmt: skip


def requested(fake: GroupTranslator) -> list[list[int]]:
    return [[int(n) for n in re.findall(r"^### Chapter (\d+)", p, re.M)] for p in fake.prompts]


def test_a_held_chapter_is_never_sent_and_is_held_not_orphaned(novel, ts):
    novel.hold(3)
    translator = Translator()
    report = run(novel, ts, translator, KeyRange(1, 4))
    assert sorted(translator.prompts) == [1, 2, 4] and report.orphans == []
    behind = stale(novel.store, ts, novel.rules, SETUP)
    assert (behind.held, behind.orphans) == (("n3",), ())


def test_a_held_chapter_falls_back_to_the_next_raw_source(novel, ts):
    other = novel.raw_source("other")
    novel.raws([3], lambda n: ["别处" + p for p in raw_paragraphs(n)], source=other)
    novel.hold(3)
    translator = Translator()
    run(novel, ts, translator, KeyRange(3, 3))
    assert "别处" in translator.prompts[3][0]


def test_unchecked_raws_are_refused_on_every_send_path(novel, ts):
    novel.raws([2], rev="rules-0")  # checked by older rules
    estimate = estimate_translate(novel.store, ts, novel.rules, SETUP, KeyRange(1, 3), PRICE)
    assert (estimate.chapters, estimate.unchecked, estimate.blocked) == (2, 1, 0)

    translator = Translator()
    report = run(novel, ts, translator, KeyRange(1, 3))
    assert sorted(translator.prompts) == [1, 3] and report.unchecked == ["n2"] and report.failed == []
    assert novel.store.check().failed == ()  # not marked failed: a reclean is all it needs
    assert "n2" not in {i.ref for i in novel.store.view().items(novel.setup_source())}  # nor indexed

    compared = estimate_compare(novel.store, ts, novel.rules, (OTHER,), KeyRange(1, 3), PRICES)[OTHER.url]
    assert (compared.chapters, compared.unchecked) == (2, 1)
    fake = Translator()
    attempts = compare_with(novel, ts, {"vendor/other": fake}, KeyRange(1, 3), setups=(OTHER,)).attempts[OTHER.url]
    assert attempts["n2"].failure == UNCHECKED and sorted(fake.prompts) == [1, 3]


def test_a_raw_source_without_rules_counts_as_unchecked(novel, ts):
    estimate = estimate_translate(novel.store, ts, {}, SETUP, KeyRange(1, 3), PRICE)
    assert (estimate.chapters, estimate.unchecked) == (0, 3)


def test_unchecked_is_reported_before_blocked(novel, ts):
    novel.raws([2], lambda n: ["七玄门" + p for p in raw_paragraphs(n)], rev=None)
    ts.propose([("七玄门", "Seven Mysteries Sect", Category.SECT)])
    gate = next(t.id for t in ts.entries() if t.zh == "七玄门")
    ts.apply([UpdateTerm(gate, status=Status.NEEDS_REVIEW)])
    estimate = estimate_translate(novel.store, ts, novel.rules, SETUP, KeyRange(1, 3), PRICE)
    assert (estimate.unchecked, estimate.blocked) == (1, 0)


def test_a_sequential_run_stops_at_the_first_unchecked_chapter(novel, ts):
    novel.raws([3], rev="rules-0")
    translator = Translator()
    report = run(novel, ts, translator, KeyRange(2, 5), setup=TranslatorSetup("vendor/cheap", context="sequential"))
    assert sorted(translator.prompts) == [2] and report.translated == ["n2"]
    assert report.unchecked == ["n3"] and report.waiting == ["n4: waits for n3", "n5: waits for n3"]


def test_a_group_is_split_where_a_chapter_between_is_not_sent(novel, ts):
    novel.raws([3], rev="rules-0")
    fake = GroupTranslator()
    attempts = grouped_compare(novel, ts, fake, KeyRange(2, 4))
    assert sorted(requested(fake)) == [[2], [4]]
    assert attempts["n3"].failure == UNCHECKED


def test_a_group_is_split_where_the_raw_source_changes(novel, ts):
    other = novel.raw_source("other")
    novel.raws([13], source=other)
    fake = GroupTranslator()
    grouped_compare(novel, ts, fake, KeyRange(12, 13))
    assert sorted(requested(fake)) == [[12], [13]]


def test_notes_are_in_the_system_prompt_on_every_path(novel, ts):
    novel.rules[novel.raw] = RawRules("A 」 after a name is noise.", REV)
    section = "\n\n## About this source text\nA 」 after a name is noise."
    single = Translator()
    run(novel, ts, single, KeyRange(1, 1))
    assert single.instructions[1][0] == prompt("v1") + section
    compared = Translator()
    compare_with(novel, ts, {"vendor/other": compared}, KeyRange(1, 1), setups=(OTHER,))
    assert compared.instructions[1][0] == prompt("v1") + section
    group = GroupTranslator()
    grouped_compare(novel, ts, group, KeyRange(1, 2))
    assert group.instructions[0] == prompt("v1") + section + GROUP_ADDENDUM


def test_without_notes_the_instructions_are_the_prompt(novel, ts):
    single = Translator()
    run(novel, ts, single, KeyRange(1, 1))
    assert single.instructions[1][0] == prompt("v1").strip()  # pydantic-ai trims the ends
    group = GroupTranslator()
    grouped_compare(novel, ts, group, KeyRange(1, 2))
    assert group.instructions[0] == prompt("v1") + GROUP_ADDENDUM


# input_keys recorded with the code from before translator notes: without notes they must not change.
GOLDEN_KEYS = {
    "parallel": [
        "abde21d0b4ed569da9d67ffe066171455f03cc99053a3774ce9a3ec05b5825da",
        "02d467d22cc374b4506bd115bfd73d126c82647ad170158924c03ee24324106c",
        "2a8741c8eeb40e2c617453f749a816a0d440b79484e5a240592aff913889fa2b",
    ],
    "sequential": "7bee125c91455cbb36535e1d7a8c40d2523709f9a7f234277df5ffebc956a3c8",
}


def test_without_notes_the_input_keys_are_unchanged(novel, ts):
    run(novel, ts, Translator(), KeyRange(1, 3))
    assert [ts.latest(SETUP.url)[f"n{n}"].input_key for n in (1, 2, 3)] == GOLDEN_KEYS["parallel"]
    sequential = TranslatorSetup("vendor/cheap", context="sequential")
    run(novel, ts, Translator(), KeyRange(1, 1), setup=sequential)
    assert ts.latest(sequential.url)["n1"].input_key == GOLDEN_KEYS["sequential"]


def test_changed_notes_stale_only_that_sources_chapters(novel, ts):
    other = novel.raw_source("other")
    novel.raws([13, 14], source=other)
    run(novel, ts, Translator(), KeyRange(1, 14))
    novel.rules[novel.raw] = RawRules("New notes.", REV)
    assert stale(novel.store, ts, novel.rules, SETUP).stale == tuple(f"n{n}" for n in range(1, 13))


def test_prune_keeps_held_translations(novel, ts):
    run(novel, ts, Translator(), KeyRange(3, 3))
    novel.hold(3)
    assert prune(novel.store, ts, novel.rules, SETUP) == ()
    assert "n3" in novel.texts() and stale(novel.store, ts, novel.rules, SETUP).held == ("n3",)


def test_a_released_chapter_is_published_again_without_a_call(novel, ts):
    run(novel, ts, Translator(), KeyRange(1, 3))
    novel.store.set_published(novel.setup_source(), True)
    novel.hold(3)
    run(novel, ts, Translator(), KeyRange(1, 3))
    assert "n3" not in {s.item_ref for s in novel.store.selection()}

    novel.store.release(novel.raw, ["/3"])
    again = Translator()
    run(novel, ts, again, KeyRange(1, 3))
    assert again.prompts == {} and "n3" in {s.item_ref for s in novel.store.selection()}
