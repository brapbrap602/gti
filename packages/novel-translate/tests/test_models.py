import json
import threading
import time

import httpx2
import pytest
from novel_translate.budget import Budget
from novel_translate.models import CallFailed, CutOff, ModelFactory, OutOfCredit, Price, PriceUnavailable
from pydantic_ai import models

MODEL = "vendor/cheap"
PRICES = {"data": [{"id": MODEL, "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]}


def completion(content="A summary.", finish="stop", cost=0.0012, gen="gen-1"):
    """A chat completion body shaped like OpenRouter's."""
    usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": gen, "object": "chat.completion", "created": 1, "model": MODEL, "provider": "SomeHost",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": finish, "native_finish_reason": finish}],
        "usage": usage,
    }  # fmt: skip


def error(code, message="nope"):
    return {"error": {"code": code, "message": message}}


class OpenRouter:
    """Serves queued (status, body, headers) replies to chat calls and a fixed model list; records requests."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.chats: list[dict] = []
        self.model_lists = 0

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/models"):
            self.model_lists += 1
            return httpx2.Response(200, json=PRICES)
        self.chats.append({"body": json.loads(request.content), "auth": request.headers["authorization"]})
        status, body, headers = self.replies.pop(0)
        return httpx2.Response(status, json=body, headers=headers)

    def factory(self, clock=time.monotonic) -> ModelFactory:
        return ModelFactory(
            "sk-test",
            base_url="https://openrouter.test/api/v1",
            transport=httpx2.MockTransport(self.handle),
            async_transport=httpx2.MockTransport(self.handle),
            clock=clock,
        )


@pytest.fixture(autouse=True)
def allow_requests(monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)  # every request here hits the fake transport


def ok(**kw):
    return (200, completion(**kw), {})


def test_success_records_openrouters_cost_and_generation_id():
    server = OpenRouter(ok())
    llm = server.factory().llm(MODEL, threading.Event(), data_collection="deny")

    summary = llm.summarize("第一章", max_tokens=300)

    assert summary.text == "A summary."
    c = summary.charged
    assert (c.cost, c.input_tokens, c.output_tokens, c.generation_ids, c.requests) == (0.0012, 100, 50, ("gen-1",), 1)
    sent = server.chats[0]
    assert sent["auth"] == "Bearer sk-test"
    assert sent["body"]["max_tokens"] == 300 and sent["body"]["model"] == MODEL
    assert sent["body"]["provider"] == {"data_collection": "deny"} and sent["body"]["usage"] == {"include": True}
    assert "reasoning" not in sent["body"]


def test_reasoning_effort_is_sent_when_set():
    server = OpenRouter(ok())
    server.factory().llm(MODEL, threading.Event(), reasoning="low").summarize("第一章")
    assert server.chats[0]["body"]["reasoning"] == {"effort": "low"}


def test_without_a_reported_cost_the_tokens_are_priced_from_the_model_list():
    server = OpenRouter(ok(cost=None))
    charged = server.factory().llm(MODEL, threading.Event()).summarize("第一章").charged
    assert charged.cost == pytest.approx(100 * 0.000001 + 50 * 0.000002)


def test_out_of_credit_is_fatal_and_not_retried():
    server = OpenRouter((402, error(402, "Insufficient credits"), {}))
    with pytest.raises(OutOfCredit):
        server.factory().llm(MODEL, threading.Event()).summarize("第一章")
    assert len(server.chats) == 1


def test_a_key_limit_is_out_of_credit_too():
    server = OpenRouter((403, error(403, "Key limit exceeded"), {}))
    with pytest.raises(OutOfCredit):
        server.factory().llm(MODEL, threading.Event()).summarize("第一章")


def test_rate_limits_are_retried_after_the_wait_the_server_asks_for():
    server = OpenRouter((429, error(429), {"Retry-After": "1"}), ok())
    started = time.monotonic()
    summary = server.factory().llm(MODEL, threading.Event()).summarize("第一章")
    assert summary.charged.requests == 1 and len(server.chats) == 2
    assert time.monotonic() - started >= 0.9


def test_server_errors_give_up_after_three_retries():
    server = OpenRouter(*[(500, error(500, "boom"), {"Retry-After": "0"})] * 4)
    with pytest.raises(CallFailed, match="HTTP 500: boom") as failed:
        server.factory().llm(MODEL, threading.Event()).summarize("第一章")
    assert len(server.chats) == 4 and failed.value.charged.cost == 0


def test_an_error_inside_a_200_reply_is_retried():
    server = OpenRouter((200, error(502, "upstream"), {"Retry-After": "0"}), ok())
    assert server.factory().llm(MODEL, threading.Event()).summarize("第一章").text == "A summary."
    assert len(server.chats) == 2


def test_a_bad_request_fails_at_once():
    server = OpenRouter((400, error(400, "bad model"), {}))
    with pytest.raises(CallFailed, match="HTTP 400: bad model"):
        server.factory().llm(MODEL, threading.Event()).summarize("第一章")
    assert len(server.chats) == 1


def test_a_cut_off_reply_is_reported_with_its_cost():
    server = OpenRouter(ok(content="", finish="length", cost=0.003))
    with pytest.raises(CutOff) as cut:
        server.factory().llm(MODEL, threading.Event()).summarize("第一章")
    assert cut.value.charged.cost == 0.003


def test_a_reply_that_finished_with_an_error_fails_with_its_cost():
    server = OpenRouter(ok(finish="error", cost=0.002))
    with pytest.raises(CallFailed, match="finish: error") as failed:
        server.factory().llm(MODEL, threading.Event()).summarize("第一章")
    assert failed.value.charged.cost == 0.002


def test_cancel_ends_a_long_retry_wait_at_once():
    server = OpenRouter((429, error(429), {"Retry-After": "300"}), ok())
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(CallFailed, match="cancelled"):
        server.factory().llm(MODEL, cancel).summarize("第一章")
    assert time.monotonic() - started < 1 and len(server.chats) == 1


def test_prices_are_cached_for_an_hour_and_unknown_models_refused():
    now = [0.0]
    server = OpenRouter()
    factory = server.factory(clock=lambda: now[0])
    assert factory.price(MODEL) == Price(0.000001, 0.000002)
    with pytest.raises(PriceUnavailable, match="does not list"):
        factory.price("vendor/unknown")
    assert server.model_lists == 1
    now[0] = 3601
    factory.price(MODEL)
    assert server.model_lists == 2


def test_an_unreachable_model_list_means_no_price():
    def down(_request):
        raise httpx2.ConnectError("offline")

    factory = ModelFactory("sk-test", transport=httpx2.MockTransport(down))
    with pytest.raises(PriceUnavailable, match="could not read"):
        factory.price(MODEL)


def test_budget_never_grants_more_than_the_cap_across_threads():
    budget = Budget(1.0)
    start = threading.Barrier(4)
    granted = []

    def take():
        start.wait()
        granted.append(budget.reserve(0.3))

    threads = [threading.Thread(target=take) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    held = [r for r in granted if r is not None]
    assert len(held) == 3 and budget.reserved == pytest.approx(0.9)

    budget.settle(held[0], 0.05)
    assert budget.spent == pytest.approx(0.05)
    assert budget.reserve(0.3) is not None and budget.reserve(0.3) is None


def test_each_worker_thread_uses_its_own_llm():
    server = OpenRouter(ok(gen="gen-a"), ok(gen="gen-b"))
    factory = server.factory()
    results = []

    def work():
        results.append(factory.llm(MODEL, threading.Event()).summarize("第一章").charged.generation_ids)

    threads = [threading.Thread(target=work) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [("gen-a",), ("gen-b",)]
