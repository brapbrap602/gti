"""Gate G1: one cheap real OpenRouter call per data-collection setting. Run with `pytest -m live`."""

import os
import threading

import pytest
from novel_translate.models import ModelFactory
from pydantic_ai import models

# A cheap model whose hosts accept data_collection "deny"; override with NOV_LIVE_MODEL.
LIVE_MODEL = os.environ.get("NOV_LIVE_MODEL", "google/gemini-2.5-flash-lite")


@pytest.mark.live
@pytest.mark.parametrize("data_collection", ["allow", "deny"])
def test_one_real_call_records_cost_and_generation_id(monkeypatch, data_collection):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        pytest.skip("set OPENROUTER_API_KEY")
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    factory = ModelFactory(key)

    summary = factory.llm(LIVE_MODEL, threading.Event(), data_collection=data_collection).summarize(
        "韩立走进七玄门，拜墨大夫为师，开始修炼长春功。", max_tokens=200
    )

    print(f"\n{data_collection}: ${summary.charged.cost:.6f} {summary.charged.generation_ids} {summary.text!r}")
    assert summary.text
    assert summary.charged.cost > 0
    assert summary.charged.generation_ids and summary.charged.generation_ids[0].startswith("gen-")
    assert factory.price(LIVE_MODEL).completion > 0
