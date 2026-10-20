"""The model seam: every LLM call of the pipeline goes through `LLM`.

pydantic-ai, the OpenRouter settings, the HTTP retry policy, cost extraction,
price lookup and error classification all stay in here. Callers pass domain
requests and get the result together with what it cost (`Charged`); a failed
call raises with the cost it ran up, so paid failures are always recorded.

Threads: an httpx client is bound to the event loop of the thread that first
uses it and `run_sync` makes one loop per thread, so each worker thread gets
its own `LLM` (its own provider, client and model) from the shared factory.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx2
from openai import AsyncOpenAI
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import IncompleteToolCall, ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

OPENROUTER_URL = "https://openrouter.ai/api/v1"
TIMEOUT_S = 180.0
HTTP_RETRIES = 3  # after the first try, for 408/429/5xx and connection errors
MAX_WAIT_S = 60.0  # longest Retry-After we honour; the SDK's own retries (up to 120 s) are off
PRICE_TTL_S = 3600.0
SUMMARY_WORDS = 120

type Clock = Callable[[], float]


@dataclass(frozen=True)
class Price:
    """US dollars per token."""

    prompt: float
    completion: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return input_tokens * self.prompt + output_tokens * self.completion


@dataclass(frozen=True)
class Charged:
    """What one call cost, over every request it made (HTTP retries and validator retries included)."""

    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    generation_ids: tuple[str, ...] = ()
    requests: int = 0

    def __add__(self, other: "Charged") -> "Charged":
        return Charged(
            self.cost + other.cost,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.generation_ids + other.generation_ids,
            self.requests + other.requests,
        )


class OutOfCredit(Exception):
    """The account or key has no credit left (402, or a key limit). Fatal for the whole job."""

    def __init__(self, message: str, charged: Charged):
        super().__init__(message)
        self.charged = charged


class CallFailed(Exception):
    """This call failed; the job may go on with other chapters."""

    def __init__(self, reason: str, charged: Charged):
        super().__init__(reason)
        self.reason = reason
        self.charged = charged


class CutOff(CallFailed):
    """The output hit `max_tokens` before it was complete."""

    def __init__(self, charged: Charged):
        super().__init__("cut-off", charged)


class PriceUnavailable(Exception):
    """OpenRouter's model list could not be read, or does not list the model."""


@dataclass(frozen=True)
class Summary:
    text: str
    charged: Charged


class LLM:
    """One thread's handle on one model. Build it with `ModelFactory.llm`, or directly around a test model."""

    def __init__(
        self,
        model: Model,
        price: Callable[[], Price],
        cancel: threading.Event,
        settings: dict[str, Any] | None = None,
        wait: Callable[[threading.Event, float], bool] = threading.Event.wait,
    ):
        self._model = model
        self._price = price
        self._cancel = cancel
        self._settings = settings or {}
        self._wait = wait  # returns True when cancelled during the wait

    def price(self) -> Price:
        return self._price()

    def summarize(self, raw: str, max_tokens: int = 400) -> Summary:
        """At most SUMMARY_WORDS English words on what happens in one raw chapter."""
        agent = Agent(
            self._model,
            output_type=str,
            instructions=(
                f"Summarize this Chinese web-novel chapter in English, in at most {SUMMARY_WORDS} words. "
                "Name who does what; keep names as they appear in the source. Plain prose, no preamble."
            ),
        )
        text, charged = self._run(agent, raw, max_tokens=max_tokens, output_retries=0)
        return Summary(text.strip(), charged)

    def _run(self, agent: Agent, prompt: str, *, max_tokens: int, output_retries: int) -> tuple[Any, Charged]:
        """Run the agent once, retrying transient HTTP failures. Raises OutOfCredit or CallFailed."""
        charged = Charged()
        settings = self._settings | {"max_tokens": max_tokens}
        for attempt in range(HTTP_RETRIES + 1):
            if self._cancel.is_set():
                raise CallFailed("cancelled", charged)
            with capture_run_messages() as messages:
                try:
                    result = agent.run_sync(prompt, model_settings=settings, retries={"output": output_retries})
                    error = None
                except (ModelAPIError, UnexpectedModelBehavior) as e:  # IncompleteToolCall is one of these
                    error = e
            charged += self._charged(messages)
            if error is None:
                if (finish := _last_response(messages)) is not None and finish.finish_reason in ("error", "content_filter"):
                    raise CallFailed(f"finish: {finish.finish_reason}", charged)
                return result.output, charged
            match _classify(error, messages):
                case "credit":
                    raise OutOfCredit(str(error), charged) from error
                case "cut-off":
                    raise CutOff(charged) from error
                case "retry" if attempt < HTTP_RETRIES:
                    if self._wait(self._cancel, _retry_wait(error, attempt)):
                        raise CallFailed("cancelled", charged) from error
                case _:
                    raise CallFailed(_reason(error), charged) from error
        raise AssertionError("unreachable")

    def _charged(self, messages: list[ModelMessage]) -> Charged:
        total = Charged()
        for m in messages:
            if not isinstance(m, ModelResponse):
                continue
            tokens_in, tokens_out = m.usage.input_tokens, m.usage.output_tokens
            cost = (m.provider_details or {}).get("cost")
            if cost is None:  # OpenRouter left it out: price the tokens ourselves
                try:
                    cost = self._price().cost(tokens_in, tokens_out)
                except PriceUnavailable:
                    cost = 0.0
            ids = (m.provider_response_id,) if m.provider_response_id else ()
            total += Charged(float(cost), tokens_in, tokens_out, ids, 1)
        return total


class ModelFactory:
    """Makes per-thread `LLM`s for OpenRouter models and owns the shared, cached price list."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = OPENROUTER_URL,
        transport: httpx2.BaseTransport | None = None,  # tests: a MockTransport serving recorded bodies
        async_transport: httpx2.AsyncBaseTransport | None = None,
        clock: Clock = time.monotonic,
    ):
        self._key = api_key
        self._base_url = base_url
        self._transport = transport
        self._async_transport = async_transport
        self._clock = clock
        self._prices: dict[str, Price] = {}
        self._prices_at: float | None = None
        self._lock = threading.Lock()

    def llm(
        self,
        model: str,
        cancel: threading.Event,
        *,
        data_collection: str = "allow",
        reasoning: str | None = None,  # an OpenRouter effort ("low", "high", ...); None leaves the model's default
    ) -> LLM:
        http_client = httpx2.AsyncClient(transport=self._async_transport) if self._async_transport else None
        client = AsyncOpenAI(
            base_url=self._base_url, api_key=self._key, max_retries=0, timeout=TIMEOUT_S, http_client=http_client
        )
        settings: dict[str, Any] = {
            "openrouter_provider": {"data_collection": data_collection},
            "openrouter_usage": {"include": True},
        }
        if reasoning is not None:
            settings["openrouter_reasoning"] = {"effort": reasoning}
        return LLM(
            OpenRouterModel(model, provider=OpenRouterProvider(openai_client=client)),
            lambda: self.price(model),
            cancel,
            settings,
        )

    def price(self, model: str) -> Price:
        with self._lock:
            now = self._clock()
            if self._prices_at is None or now - self._prices_at > PRICE_TTL_S:
                self._prices = self._fetch_prices()
                self._prices_at = now
            if model not in self._prices:
                raise PriceUnavailable(f"OpenRouter does not list the model {model!r}")
            return self._prices[model]

    def _fetch_prices(self) -> dict[str, Price]:
        try:
            with httpx2.Client(transport=self._transport, timeout=30) as http:
                response = http.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._key}"})
                response.raise_for_status()
                rows = response.json()["data"]
            return {r["id"]: Price(float(r["pricing"]["prompt"]), float(r["pricing"]["completion"])) for r in rows}
        except (httpx2.HTTPError, KeyError, TypeError, ValueError) as e:
            raise PriceUnavailable(f"could not read OpenRouter's model list: {e}") from e


def _last_response(messages: list[ModelMessage]) -> ModelResponse | None:
    return next((m for m in reversed(messages) if isinstance(m, ModelResponse)), None)


def _classify(error: Exception, messages: list[ModelMessage]) -> str:
    if isinstance(error, IncompleteToolCall):
        return "cut-off"
    if isinstance(error, UnexpectedModelBehavior):
        last = _last_response(messages)
        return "cut-off" if last is not None and last.finish_reason == "length" else "fail"
    if isinstance(error, ModelHTTPError):
        if error.status_code == 402 or (error.status_code == 403 and "limit" in str(error.body).lower()):
            return "credit"
        return "retry" if error.status_code in (408, 429) or error.status_code >= 500 else "fail"
    return "retry"  # connection errors and timeouts


def _retry_wait(error: Exception, attempt: int) -> float:
    backoff = 2.0**attempt
    headers = getattr(error, "headers", None) or {}
    value = headers.get("retry-after")
    if value is None:
        return min(backoff, MAX_WAIT_S)
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            seconds = backoff
    return min(max(seconds, 0.0), MAX_WAIT_S)


def _reason(error: Exception) -> str:
    if isinstance(error, ModelHTTPError):
        body = error.body.get("message", error.body) if isinstance(error.body, dict) else error.body
        return f"HTTP {error.status_code}: {body}"
    return f"{type(error).__name__}: {error}"
