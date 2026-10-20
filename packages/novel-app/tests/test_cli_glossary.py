import re
import threading

import pytest
from novel_app import service
from novel_app.cli import app
from novel_app.library import DATA_DIR_ENV, novel_dir
from novel_core import Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec
from novel_translate.models import LLM, Price
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from typer.testing import CliRunner

FILLER = "山水风云天地日月花草木石金银铜铁春夏秋冬东西南北红黄蓝白黑青紫长短高低远近快慢冷热明暗新旧大小多少"


class FakeOpenRouter:
    """Stands in for ModelFactory: every string is a term rendered 'Name', every chapter summarized."""

    def __init__(self):
        self.calls: list[str] = []

    def price(self, model: str) -> Price:
        return Price(0.000001, 0.000002)

    def llm(self, model: str, cancel: threading.Event, **_settings) -> LLM:
        return LLM(FunctionModel(self.answer), lambda: self.price(model), cancel)

    def answer(self, messages, info) -> ModelResponse:
        prompt = messages[-1].parts[-1].content
        if info.instructions.startswith("Summarize"):
            self.calls.append("summarize")
            return ModelResponse(parts=[TextPart("A summary.")])
        self.calls.append("classify")
        asked = re.findall(r"^### (\S+)", prompt, re.M)
        terms = [{"zh": zh, "is_term": zh == "韩立", "category": "person", "renderings": ["Han Li"] * 3} for zh in asked]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"terms": terms})])


@pytest.fixture
def novels(tmp_path, monkeypatch):
    """raw-novel: five raw chapters naming 韩立 nine times each; english-only: no raws."""
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    with NovelStore.create(novel_dir("raw-novel"), NovelMeta("Raw Novel")) as store:
        raw = store.upsert_source(SourceSpec("custom:raw", "https://raw.test", "zh", Kind.RAW_ZH))
        store.record_index(raw, [SourceItem(f"/{n}", n, f"第{n}章", number=n) for n in range(1, 6)])
        for n in range(1, 6):
            words = [FILLER[(n * 7 + i * 13) % len(FILLER)] * (1 + i % 3) for i in range(600)]
            text = "韩立".join("".join(words[i : i + 60]) for i in range(0, 600, 60))  # 韩立 nine times a chapter
            store.put_version(raw, f"/{n}", NewVersion(f"第{n}章", (Paragraph.of(text),)))
    with NovelStore.create(novel_dir("english-only"), NovelMeta("English Only")) as store:
        store.upsert_source(SourceSpec("custom:en", "https://en.test", "en", Kind.OFFICIAL_EN))


@pytest.fixture
def openrouter(novels, monkeypatch):
    fake = FakeOpenRouter()
    monkeypatch.setattr(service, "openrouter", lambda: fake)
    return fake


def run(*args, input=None):
    return CliRunner().invoke(app, [str(a) for a in args], input=input)


def test_build_shows_the_estimate_and_asks_first(openrouter):
    refused = run("glossary", "build", "raw-novel", "--model", "vendor/cheap", input="n\n")
    assert refused.exit_code == 1
    assert "at most $" in refused.output and "5 summarize" in refused.output
    assert openrouter.calls == []

    done = run("glossary", "build", "raw-novel", "--model", "vendor/cheap", "--yes")
    assert done.exit_code == 0, done.output
    assert "5 chapters summarized" in done.output and "decided: 1 accepted" in done.output
    listed = run("glossary", "list", "raw-novel", "--status", "accepted")
    assert "韩立 → Han Li  [person, accepted]" in listed.output


def test_without_a_key_nothing_starts(novels, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = run("glossary", "build", "raw-novel", "--model", "vendor/cheap", "--yes")
    assert result.exit_code == 2 and "set OPENROUTER_API_KEY" in result.output


def test_a_novel_without_raws_has_no_glossary_pass(openrouter):
    result = run("glossary", "build", "english-only", "--model", "vendor/cheap", "--yes")
    assert result.exit_code == 2 and "has no Chinese raws" in result.output


def test_manual_terms_are_added_changed_locked_and_rejected(openrouter):
    added = run("glossary", "add", "raw-novel", "韓立", "Han Li", "--category", "person", "--alias", "韩老魔")
    assert added.exit_code == 0 and "added 韓立 → Han Li" in added.output
    assert "韩立 (also 韩老魔) → Han Li  [person, locked *]" in run("glossary", "list", "raw-novel").output

    assert run("glossary", "add", "raw-novel", "韩立", "Han Li").exit_code == 2  # already there
    assert run("glossary", "set", "raw-novel", "1", "--en", "Han Li the Elder").exit_code == 0
    assert run("glossary", "reject", "raw-novel", "1").exit_code == 0
    assert "Han Li the Elder  [person, rejected *]" in run("glossary", "list", "raw-novel").output
    assert run("glossary", "lock", "raw-novel", "99").exit_code == 2
