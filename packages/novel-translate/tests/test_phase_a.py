import random
import re
import threading

import pytest
from novel_core import KeyRange, Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec
from novel_translate.budget import Budget
from novel_translate.glossary import AddTerm, Category, Status, UpdateTerm
from novel_translate.models import LLM, Charged, OutOfCredit, Price
from novel_translate.phase_a import GlossaryOptions, build_glossary, estimate_glossary
from novel_translate.tstore import TranslateStore
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

PRICE = Price(0.000001, 0.000002)
FILLER = "山水风云天地日月花草木石金银铜铁春夏秋冬东西南北红黄蓝白黑青紫长短高低远近快慢冷热明暗新旧大小多少"
NAMES = ["韩立", "七玄门", "墨大夫"]
CHAPTERS = 12


def raw_text(number: int, seed: int = 0) -> list[str]:
    """Filler paragraphs with each name three times."""
    rng = random.Random(number * 31 + seed)
    words = ["".join(rng.choice(FILLER) for _ in range(rng.randint(1, 4))) for _ in range(240)]
    for name in NAMES * 3:
        words.insert(rng.randrange(len(words)), name)
    return ["".join(words[i : i + 40]) + "。" for i in range(0, len(words), 40)]


def english(number: int) -> str:
    return f"Chapter {number}. Han Li walked into the Seven Mysteries Sect and bowed to Physician Mo."


class Novel:
    def __init__(self, store: NovelStore):
        self.store = store

    def source(self, name: str, kind: Kind) -> int:
        return self.store.upsert_source(SourceSpec(f"custom:{name}", f"https://{name}.test", "zh" if kind is Kind.RAW_ZH else "en", kind))

    def chapters(self, source: int, numbers, text) -> None:
        self.store.record_index(source, [SourceItem(f"/c/{n}", n, f"Chapter {n}", number=n) for n in numbers])
        for n in numbers:
            paragraphs = text(n)
            if isinstance(paragraphs, str):
                paragraphs = [paragraphs]
            self.store.put_version(source, f"/c/{n}", NewVersion(f"Chapter {n}", tuple(Paragraph.of(p) for p in paragraphs)))


@pytest.fixture
def novel(tmp_path):
    with NovelStore.create(tmp_path / "novel", NovelMeta("Test")) as store:
        n = Novel(store)
        n.chapters(n.source("raw", Kind.RAW_ZH), range(1, CHAPTERS + 1), raw_text)
        n.chapters(n.source("official", Kind.OFFICIAL_EN), range(1, 7), english)
        yield n


@pytest.fixture
def ts(tmp_path):
    with TranslateStore.create(tmp_path / "novel") as store:
        yield store


class Script:
    """A fake model: answers the three Phase A calls from tables, and logs what it was asked."""

    def __init__(self, votes=None, hints=None, on_classify=None, fail=None):
        self.votes = votes or {
            "韩立": (Category.PERSON, ["Han Li"] * 3),
            "七玄门": (Category.SECT, ["Seven Mysteries Sect"] * 3),
            "墨大夫": (Category.TITLE, ["Doctor Mo"] * 3),
        }  # fmt: skip
        self.hints = hints or {"韩立": "Han Li", "七玄门": "Seven Mysteries Sect", "墨大夫": "Doctor Mo"}
        self.on_classify = on_classify
        self.fail = fail
        self.calls: list[tuple[str, object]] = []
        self.lock = threading.Lock()

    def llm(self, cancel: threading.Event) -> LLM:
        return LLM(FunctionModel(self.answer), lambda: PRICE, cancel)

    def answer(self, messages, info) -> ModelResponse:
        prompt = messages[-1].parts[-1].content
        if info.instructions.startswith("Summarize"):
            return self.reply("summarize", None, TextPart("A summary."))
        if info.instructions.startswith("You build"):
            asked = re.findall(r"^### (\S+)", prompt, re.M)
            if self.on_classify:
                self.on_classify(asked)
            terms = []
            for zh in asked:
                category, renderings = self.votes.get(zh, (Category.OTHER, []))
                terms.append({"zh": zh, "is_term": bool(renderings), "category": str(category), "renderings": renderings})
            return self.reply("classify", asked, ToolCallPart(info.output_tools[0].name, {"terms": terms}))
        number = int(re.search(r"Chapter (\d+)\.", prompt).group(1))
        asked = re.findall(r"^- (\S+):", prompt, re.M)
        terms = [{"zh": zh, "en": self.hints.get(zh)} for zh in asked]
        return self.reply("hint", number, ToolCallPart(info.output_tools[0].name, {"terms": terms}))

    def reply(self, kind, detail, part) -> ModelResponse:
        with self.lock:
            self.calls.append((kind, detail))
        if self.fail == kind:
            raise OutOfCredit("no credit", Charged())
        return ModelResponse(parts=[part])

    def count(self, kind: str) -> int:
        return sum(k == kind for k, _ in self.calls)


def build(novel, ts, script, budget=None, **options):
    return build_glossary(
        novel.store, ts, script.llm, PRICE, budget or Budget(100.0),
        GlossaryOptions("vendor/cheap", **options), lambda *_: None,
    )  # fmt: skip


def entry(ts, zh):
    return next(t for t in ts.entries() if t.zh == zh)


def test_unanimous_votes_are_accepted_and_every_chapter_summarized(novel, ts):
    script = Script()
    report = build(novel, ts, script)

    assert entry(ts, "韩立").status is Status.ACCEPTED and entry(ts, "韩立").en == "Han Li"
    assert entry(ts, "韩立").occurrences == 3 * CHAPTERS and entry(ts, "韩立").first_chapter == 1
    assert len(ts.snippets(entry(ts, "韩立").id)) == 3
    assert report.summarized == CHAPTERS and len(ts.summaries()) == CHAPTERS
    assert report.stopped is None and report.cost > 0
    assert {zh for _, asked in script.calls if _ == "classify" for zh in asked} >= set(NAMES)


def test_split_votes_need_review(novel, ts):
    script = Script()
    script.votes["七玄门"] = (Category.SECT, ["Seven Mysteries Sect", "Seven Mysteries Sect", "Qixuan Sect"])
    build(novel, ts, script)
    assert entry(ts, "七玄门").status is Status.NEEDS_REVIEW


def test_official_english_that_disagrees_sends_a_term_to_review(novel, ts):
    script = Script()
    script.hints["墨大夫"] = "Physician Mo"
    build(novel, ts, script)

    mo = entry(ts, "墨大夫")
    assert mo.status is Status.NEEDS_REVIEW
    assert {(c.en, c.origin) for c in ts.candidates(mo.id)} == {("Doctor Mo", "llm"), ("Physician Mo", "official-en")}
    assert {n for k, n in script.calls if k == "hint"} == {1, 2, 3}  # three chapters per term, official ones only


def test_locked_terms_never_change(novel, ts):
    ts.apply([AddTerm("韩立", "Han the Great", Category.PERSON)])
    build(novel, ts, Script())
    han = entry(ts, "韩立")
    assert (han.en, han.status) == ("Han the Great", Status.LOCKED)


def test_an_edit_made_during_the_run_wins(novel, ts):
    ts.propose([("七玄门", "Seven Profound Gate", Category.SECT)])
    term = entry(ts, "七玄门").id

    def edit(asked):
        if "七玄门" in asked:
            ts.apply([UpdateTerm(term, en="Qixuan Sect", status=Status.LOCKED)])

    build(novel, ts, Script(on_classify=edit))
    gate = entry(ts, "七玄门")
    assert (gate.en, gate.status) == ("Qixuan Sect", Status.LOCKED)
    assert ("Seven Mysteries Sect", "llm") in {(c.en, c.origin) for c in ts.candidates(term)}


def test_revoting_leaves_a_users_pick_alone(novel, ts):
    build(novel, ts, Script())
    han = entry(ts, "韩立").id
    ts.apply([UpdateTerm(han, en="Han Li!", status=Status.ACCEPTED)])
    script = Script()
    script.votes["韩立"] = (Category.PERSON, ["Hahn Lee"] * 3)
    build(novel, ts, script, revote=True)
    assert entry(ts, "韩立").en == "Han Li!"


def test_overlapping_raw_sources_count_each_chapter_once(novel, ts):
    novel.chapters(novel.source("raw-b", Kind.RAW_ZH), range(1, CHAPTERS + 1), lambda n: raw_text(n, seed=5))
    script = Script()
    build(novel, ts, script)
    assert entry(ts, "韩立").occurrences == 3 * CHAPTERS
    assert script.count("summarize") == CHAPTERS


class Grants(Budget):
    """A budget that grants the first `n` reservations only."""

    def __init__(self, n: int):
        super().__init__(100.0)
        self.left = n

    def reserve(self, estimate):
        if self.left == 0:
            return None
        self.left -= 1
        return super().reserve(estimate)


def test_the_budget_stops_the_pass_after_the_calls_it_allowed(novel, ts):
    script = Script()
    report = build(novel, ts, script, budget=Grants(1), batch=1, workers=1)
    assert report.stopped == "budget reached"
    assert script.calls[0][0] == "classify" and len(script.calls) == 1
    assert ts.summaries() == {}


def test_a_stopped_pass_resolves_what_it_tallied_and_the_next_run_continues(novel, ts):
    first = Script()
    report = build(novel, ts, first, budget=Grants(first_classify_calls(novel, ts) + 1), workers=1)
    assert report.stopped == "budget reached" and first.count("hint") == 1
    assert entry(ts, "韩立").status in (Status.ACCEPTED, Status.NEEDS_REVIEW)  # decided, not left proposed

    second = Script()
    report = build(novel, ts, second)
    assert second.count("classify") == 0
    assert second.count("hint") == 2 and second.count("summarize") == CHAPTERS
    assert report.stopped is None


def first_classify_calls(novel, ts) -> int:
    return estimate_glossary(novel.store, ts, PRICE, GlossaryOptions("m")).calls["classify"]


def test_out_of_credit_ends_the_pass_with_an_error(novel, ts):
    with pytest.raises(OutOfCredit):
        build(novel, ts, Script(fail="hint"))
    assert entry(ts, "韩立").status is Status.ACCEPTED  # what was tallied is still resolved


def test_a_rerun_with_nothing_new_calls_no_model(novel, ts):
    build(novel, ts, Script())
    again = Script()
    report = build(novel, ts, again)
    assert again.calls == [] and report.calls == 0


def test_hints_come_only_from_chapters_whose_selected_text_is_official(novel, ts):
    mine = novel.source("mtl", Kind.MY_TRANSLATION)
    mislabelled = novel.source("calibre", Kind.OFFICIAL_EN)  # holds machine translation
    novel.chapters(mine, range(1, CHAPTERS + 1), english)
    novel.chapters(mislabelled, range(1, CHAPTERS + 1), english)
    novel.store.set_priority([mine, 2, mislabelled])
    novel.store.set_pin(KeyRange(5, 6), 2)

    script = Script()
    build(novel, ts, script)
    assert {n for k, n in script.calls if k == "hint"} == {5, 6}


def test_the_estimate_is_an_upper_bound_on_what_the_pass_spends(novel, ts):
    estimate = estimate_glossary(novel.store, ts, PRICE, GlossaryOptions("vendor/cheap"))
    report = build(novel, ts, Script())
    assert estimate.upper_bound and estimate.chapters == CHAPTERS
    assert estimate.calls["summarize"] == CHAPTERS and estimate.calls["classify"] >= 1
    assert report.calls <= estimate.total_calls and report.cost <= estimate.usd
