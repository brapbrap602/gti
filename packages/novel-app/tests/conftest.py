"""Shared fixtures: a fake site behind every backend, in an empty data dir."""

import random
import re
import threading
import time
from contextlib import contextmanager

import pytest
from novel_app import service
from novel_app.library import DATA_DIR_ENV, novel_dir
from novel_core import Block, Kind, NewVersion, NovelMeta, NovelStore, Paragraph, RawChapter, SourceItem, SourceSpec
from novel_sources.backends import zh_rules
from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.importing import NovelIndex
from novel_translate.models import LLM, Price
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

URL = "https://novelbuddy.me/test-novel"


class Site:
    """The live site behind every `open_source` call: chapters 1..count; `fail` numbers raise."""

    def __init__(self):
        self.count = 3
        self.fail: set[int] = set()
        self.down = False
        self.delay = 0.0  # seconds per chapter fetch

    def source(self, spec):
        site = self

        class Live:
            def __init__(self):
                self.spec = spec

            def fetch_index(self):
                if site.down:
                    raise FetchError(f"{URL}: HTTP 503 after 3 attempts")
                items = tuple(SourceItem(f"/test-novel/chapter-{n}", n, f"Chapter {n}") for n in range(1, site.count + 1))
                return NovelIndex(NovelMeta("Test Novel"), items)

            def fetch_chapter(self, item):
                n = int(item.ref.rsplit("-", 1)[1])
                time.sleep(site.delay)
                if n in site.fail:
                    raise FetchError(f"{item.ref}: HTTP 500 after 3 attempts")
                return RawChapter(f'<div id="b"><p>Text {n}.</p></div>')

            def clean_rules(self, raw):
                return CleanRules(content=("div#b",))

        return Live()


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    site = Site()

    @contextmanager
    def open_source(spec: SourceSpec, state, guides):
        assert spec.backend == "lncrawl" and spec.kind is Kind.OFFICIAL_EN
        yield site.source(spec)

    monkeypatch.setattr(service, "open_source", open_source)
    return site


@pytest.fixture
def two_texts(site):
    """Makes a novel whose sources 1 and 2 hold the given chapters (title -> paragraphs, as text or blocks)."""

    def make(slug: str, left: dict[str, tuple[str | Block, ...]], right: dict[str, tuple[str | Block, ...]],
             right_kind: Kind = Kind.OFFICIAL_EN) -> None:
        store = NovelStore.create(novel_dir(slug), NovelMeta("Diff Novel"))
        try:
            for name, chapters, kind in (("a", left, Kind.OFFICIAL_EN), ("b", right, right_kind)):
                source = store.upsert_source(SourceSpec(f"custom:{name}", f"https://{name}.test/n", "en", kind))
                items = [SourceItem(f"/{title}", i, title) for i, title in enumerate(chapters, start=1)]
                store.record_index(source, items)
                for item in items:
                    body = tuple(Paragraph.of(t) if isinstance(t, str) else t for t in chapters[item.title])
                    store.put_version(source, item.ref, NewVersion(item.title, body))
        finally:
            store.close()

    return make


# -- translation -------------------------------------------------------------------

FILLER = "山水风云天地日月花草木石金银铜铁春夏秋冬东西南北红黄蓝白黑青紫长短高低远近快慢冷热明暗新旧大小多少"


class FakeOpenRouter:
    """Stands in for ModelFactory: only 韩立 is a term ('Han Li'), every chapter is summarized, and
    every translation is made-up English of the right length; `models` lists what it was asked for."""

    def __init__(self):
        self.calls: list[str] = []
        self.models: list[tuple[str, dict]] = []

    def price(self, model: str) -> Price:
        return Price(0.000001, 0.000002)

    def llm(self, model: str, cancel: threading.Event, **settings) -> LLM:
        self.models.append((model, settings))
        return LLM(FunctionModel(self.answer), lambda: self.price(model), cancel)

    def answer(self, messages, info) -> ModelResponse:
        prompt = messages[-1].parts[-1].content
        if "several consecutive chapters" in info.instructions:
            self.calls.append("translate-group")
            chapters = []
            for number, body in re.findall(r"^### Chapter (\d+) \(title: [^)]*\)\n((?:\[\d+\] .+\n?)+)", prompt, re.M):
                source = re.findall(r"^\[(\d+)\] (.+)$", body, re.M)
                paragraphs = [{"id": int(i), "text": _english(len(text), f"{i}{text[:4]}")} for i, text in source]
                chapters.append({"number": int(number), "title": "A Title", "paragraphs": paragraphs, "new_terms": []})
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"chapters": chapters})])
        if info.instructions.startswith("You translate"):
            self.calls.append("translate")
            source = re.findall(r"^\[(\d+)\] (.+)$", prompt.split("## Chapter to translate")[1], re.M)
            paragraphs = [{"id": int(i), "text": _english(len(text), f"{i}{text[:4]}")} for i, text in source]
            result = {"title": "A Title", "paragraphs": paragraphs, "new_terms": []}
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, result)])
        if info.instructions.startswith("Summarize"):
            self.calls.append("summarize")
            return ModelResponse(parts=[TextPart("A summary.")])
        self.calls.append("classify")
        asked = re.findall(r"^### (\S+)", prompt, re.M)
        terms = [{"zh": zh, "is_term": zh == "韩立", "category": "person", "renderings": ["Han Li"] * 3} for zh in asked]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"terms": terms})])


@pytest.fixture
def novels(tmp_path, monkeypatch):
    """raw-novel: five raw chapters naming 韩立 nine times each, checked with today's zh rules;
    english-only: no raws."""
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    with NovelStore.create(novel_dir("raw-novel"), NovelMeta("Raw Novel")) as store:
        spec = SourceSpec("custom:raw", "https://raw.test", "zh", Kind.RAW_ZH)
        raw, rev = store.upsert_source(spec), zh_rules("raw-novel", spec).rev
        store.record_index(raw, [SourceItem(f"/{n}", n, f"第{n}章", number=n) for n in range(1, 6)])
        for n in range(1, 6):
            words = [FILLER[(n * 7 + i * 13) % len(FILLER)] * (1 + i % 3) for i in range(600)]
            text = "韩立".join("".join(words[i : i + 60]) for i in range(0, 600, 60))  # 韩立 nine times a chapter
            store.put_version(raw, f"/{n}", NewVersion(f"第{n}章", (Paragraph.of(text),), rules_rev=rev))
    with NovelStore.create(novel_dir("english-only"), NovelMeta("English Only")) as store:
        store.upsert_source(SourceSpec("custom:en", "https://en.test", "en", Kind.OFFICIAL_EN))


@pytest.fixture
def old_rules(novels):
    """Mark raw-novel's raws at these numbers as checked by older zh rules (unchecked today)."""

    def mark(numbers) -> None:
        with NovelStore.open(novel_dir("raw-novel")) as store:
            for s in store.view().chapters(1):
                if s.key.number in numbers:
                    v = store.read_version(s.version_id)
                    store.put_version(1, s.item_ref, NewVersion(v.title, v.blocks, rules_rev="rules-0"))

    return mark


NAMES = ("山门", "钟声", "松林", "溪水", "月光")


@pytest.fixture
def misnumbered(novels):
    """raw-novel's chapters get names, and a second raw source lists them one number later
    (printed 2-6 for chapters 1-5): numbering suggests `nov align range raw-novel 2-6 -1 --source 2`."""
    with NovelStore.open(novel_dir("raw-novel")) as store:
        store.record_index(1, [SourceItem(f"/{n}", n, f"第{n}章 {NAMES[n - 1]}", number=n) for n in range(1, 6)])
        later = store.upsert_source(SourceSpec("custom:later", "https://later.test", "zh", Kind.RAW_ZH))
        store.record_index(later, [SourceItem(f"/b/{n + 1}", n, f"第{n + 1}章 {NAMES[n - 1]}") for n in range(1, 6)])
    return later


@pytest.fixture
def openrouter(novels, monkeypatch):
    fake = FakeOpenRouter()
    monkeypatch.setattr(service, "openrouter", lambda: fake)
    return fake


def _english(n_chars: int, seed: str) -> str:
    """Varied made-up English, about 0.6 words per Chinese character (passes the length check)."""
    rng = random.Random(seed)
    return " ".join("".join(rng.choice("aeioubcdfghklmnprstvw") for _ in range(rng.randint(3, 8))) for _ in range(int(n_chars * 0.6)))
