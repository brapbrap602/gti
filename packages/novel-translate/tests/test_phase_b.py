import random
import re
import threading

import pytest
from novel_core import AlignmentRules, ChapterKey, KeyRange, Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec
from novel_translate.budget import Budget
from novel_translate.glossary import AddTerm, Category, Status, UpdateTerm
from novel_translate.models import LLM, Price
from novel_translate.phase_b import TranslateReport, estimate_translate, prune, stale, translate
from novel_translate.setups import SetupError, TranslatorSetup, register
from novel_translate.tstore import TranslateStore
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

PRICE = Price(0.000001, 0.000002)
SETUP = TranslatorSetup("vendor/cheap")
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
    def __init__(self, store: NovelStore, raw: int):
        self.store, self.raw = store, raw
        self.numbers: set[int] = set()

    def raws(self, numbers, text=raw_paragraphs) -> None:
        """Store raw texts for these numbers; the index keeps every number stored before."""
        self.numbers |= set(numbers)
        self.store.record_index(self.raw, [SourceItem(f"/{n}", n, f"第{n}章", number=n) for n in sorted(self.numbers)])
        for n in numbers:
            self.store.put_version(self.raw, f"/{n}", NewVersion(f"第{n}章", tuple(Paragraph.of(p) for p in text(n))))

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
    return translate(novel.store, ts, setup, keys, translator.llm, PRICE, budget or Budget(100.0), workers, progress, report)


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
    assert stale(novel.store, ts, SETUP).stale == ()

    mo = next(t.id for t in ts.entries() if t.zh == "墨大夫")
    ts.apply([UpdateTerm(mo, en="Physician Mo")])
    assert stale(novel.store, ts, SETUP).stale == ("n2",)
    report = run(novel, ts, Translator(), "stale")  # the fake gives the same text again: put_version says Unchanged
    assert report.translated == ["n2"]
    assert stale(novel.store, ts, SETUP).stale == ()


def test_a_changed_raw_stales_its_chapter_and_the_next_ones(novel, ts):
    run(novel, ts, Translator(), KeyRange(1, 12))
    for n in range(1, 13):
        ts.put_summary((n, 0), novel.store.view().chapters(novel.raw)[n - 1].content_hash, "m", f"summary {n}")
    run(novel, ts, Translator(), KeyRange(1, 12))  # summaries are now part of every input
    novel.raws([2], lambda n: raw_paragraphs(n) + ["新的一段。"])
    ts.put_summary((2, 0), novel.store.view().chapters(novel.raw)[1].content_hash, "m", "a new summary 2")
    assert stale(novel.store, ts, SETUP).stale == tuple(f"n{n}" for n in range(2, 13))


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
    assert stale(novel.store, ts, sequential).stale == ("n3",)


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
    assert stale(novel.store, ts, SETUP).orphans == ("n4411",)
    assert prune(novel.store, ts, SETUP) == ("n4411",)
    assert stale(novel.store, ts, SETUP).orphans == ()


def test_the_cap_holds_with_retries_in_flight(novel, ts):
    one = estimate_translate(novel.store, ts, SETUP, KeyRange(1, 1), PRICE).usd
    budget = Budget(one * 2.5)
    report = run(novel, ts, Translator({1: ["loop"], 2: ["cut"]}), KeyRange(1, 8), budget=budget, workers=4)
    assert report.stopped == "budget reached"
    assert budget.spent <= budget.cap
    assert len(report.translated) + len(report.failed) <= 3


def test_the_estimate_counts_what_would_be_sent(novel, ts):
    run(novel, ts, Translator(), KeyRange(1, 2))
    estimate = estimate_translate(novel.store, ts, SETUP, KeyRange(1, 5), PRICE)
    assert (estimate.chapters, estimate.current, estimate.blocked) == (3, 2, 0) and estimate.usd > 0
