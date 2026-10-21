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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx2
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, capture_run_messages
from pydantic_ai.exceptions import IncompleteToolCall, ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from novel_translate.chapter import Translated
from novel_translate.glossary import Category, Verdict

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


@dataclass(frozen=True)
class Sample:
    """A possible term with where it was seen: a few raw snippets around it."""

    zh: str
    snippets: tuple[str, ...]


class _TermVerdict(BaseModel):
    zh: str
    is_term: bool = Field(description="a proper name or fixed term (person, place, sect, technique, ...), not an ordinary word")
    category: Category
    renderings: list[str] = Field(description="one English rendering per snippet, in snippet order")
    aliases: list[str] = Field(default=[], description="other Chinese forms of the same name seen in the snippets")
    gender: Literal["male", "female"] | None = Field(default=None, description="persons only, when the snippets show it")


class _Verdicts(BaseModel):
    terms: list[_TermVerdict]


@dataclass(frozen=True)
class Classified:
    verdicts: tuple[Verdict, ...]  # those for zh that were asked about; others are dropped
    charged: Charged


class _Usage(BaseModel):
    zh: str
    en: str | None = Field(description="the English the text uses for it, exactly as written; null if it does not appear")


class _Usages(BaseModel):
    terms: list[_Usage]


@dataclass(frozen=True)
class Hinted:
    renderings: Mapping[str, str]  # zh -> how the English text renders it, for the terms it renders
    charged: Charged


@dataclass(frozen=True)
class Attempted:
    out: Translated
    charged: Charged


# What the translator is told when a hard check fails (validate.py's check ids).
_FIXES = {
    "cjk": "- Some Chinese characters or Chinese punctuation are left in the title or text: write English only.",
    "ids": "- The paragraph ids must be exactly the source ids, each once: one English paragraph per source paragraph.",
    "empty": "- A paragraph is empty although its source paragraph is not: translate every paragraph.",
    "loop": "- The text repeats itself: translate each source paragraph once.",
    "length": "- The translation is far too short or too long for the source: translate fully, without padding.",
    "heading": "- A paragraph starts with 'Chapter N' although the source paragraph does not: drop it.",
}


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

    def classify(self, samples: Sequence[Sample], max_tokens: int) -> Classified:
        """Is each string a term, and how would one render it in each snippet (those are its votes)?"""
        agent = Agent(
            self._model,
            output_type=_Verdicts,
            instructions=(
                "You build the glossary for an English translation of a Chinese web novel. For each string, "
                "decide from its snippets whether it is a proper name or fixed term (person, place, sect, "
                "technique, cultivation realm, item, title) rather than an ordinary word or phrase. Give one "
                "English rendering per snippet, as a careful translator would write it in English prose: "
                "personal names in pinyin (surname first), other names translated for meaning. "
                "Answer for every string, in order."
            ),
        )
        asked = {s.zh for s in samples}
        prompt = "\n\n".join(
            f"### {s.zh}\n" + "\n".join(f"{i}. {snippet}" for i, snippet in enumerate(s.snippets, 1)) for s in samples
        )
        out, charged = self._run(agent, prompt, max_tokens=max_tokens, output_retries=1)
        verdicts = (
            Verdict(v.zh, v.is_term, v.category, tuple(v.renderings), tuple(v.aliases), v.gender)
            for v in out.terms
            if v.zh in asked
        )
        return Classified(tuple(verdicts), charged)

    def hint(self, samples: Sequence[Sample], en_text: str, max_tokens: int) -> Hinted:
        """How an existing English translation of one chapter renders each term."""
        agent = Agent(
            self._model,
            output_type=_Usages,
            instructions=(
                "Below is an English translation of one chapter of a Chinese novel, then Chinese terms from that "
                "chapter with snippets of the original. For each term, quote the English the translation uses "
                "for it, exactly as written, or null if you cannot find it."
            ),
        )
        asked = {s.zh for s in samples}
        terms = "\n".join(f"- {s.zh}: {' / '.join(s.snippets)}" for s in samples)
        out, charged = self._run(
            agent, f"## English translation\n{en_text}\n\n## Terms\n{terms}", max_tokens=max_tokens, output_retries=1
        )
        return Hinted({u.zh: u.en.strip() for u in out.terms if u.zh in asked and u.en and u.en.strip()}, charged)

    def translate(
        self,
        instructions: str,
        prompt: str,
        hard_checks: Callable[[Translated], Sequence[str]],
        max_tokens: int,
        retry_invalid: bool = True,
    ) -> Attempted:
        """One chapter. Output failing `hard_checks` is sent back once with what to fix (`retry_invalid`);
        raises CallFailed("invalid: <checks>") if it still fails, CutOff if it hit `max_tokens`."""
        agent = Agent(self._model, output_type=Translated, instructions=instructions)
        failed: list[Sequence[str]] = []

        @agent.output_validator
        def _valid(out: Translated) -> Translated:
            if problems := hard_checks(out):
                failed.append(problems)
                raise ModelRetry("Fix these problems and answer again in full:\n" + "\n".join(_FIXES[p] for p in problems))
            return out

        try:
            out, charged = self._run(agent, prompt, max_tokens=max_tokens, output_retries=1 if retry_invalid else 0)
        except CutOff:
            raise
        except CallFailed as e:
            if failed:
                raise CallFailed(f"invalid: {', '.join(failed[-1])}", e.charged) from e
            raise
        return Attempted(out, charged)

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
        self._reasons_by_default: set[str] = set()  # models that reason unless told not to, and may be told
        self._prices_at: float | None = None
        self._lock = threading.Lock()

    def llm(
        self,
        model: str,
        cancel: threading.Event,
        *,
        data_collection: str = "allow",
        reasoning: str | None = None,  # an OpenRouter effort ("low", "high", ...); None turns it off where the model allows
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
        elif self._reasons_unless_told(model):  # else it reasons anyway: billed, and eating max_tokens
            settings["openrouter_reasoning"] = {"effort": "none"}
        return LLM(
            OpenRouterModel(model, provider=OpenRouterProvider(openai_client=client)),
            lambda: self.price(model),
            cancel,
            settings,
        )

    def price(self, model: str) -> Price:
        with self._lock:
            self._refresh()
            if model not in self._prices:
                raise PriceUnavailable(f"OpenRouter does not list the model {model!r}")
            return self._prices[model]

    def _reasons_unless_told(self, model: str) -> bool:
        """Whether the model reasons unless told not to and accepts being told; False when the list is unreadable."""
        with self._lock:
            try:
                self._refresh()
            except PriceUnavailable:
                return False
            return model in self._reasons_by_default

    def _refresh(self) -> None:
        now = self._clock()
        if self._prices_at is None or now - self._prices_at > PRICE_TTL_S:
            self._prices, self._reasons_by_default = self._fetch_models()
            self._prices_at = now

    def _fetch_models(self) -> tuple[dict[str, Price], set[str]]:
        try:
            with httpx2.Client(transport=self._transport, timeout=30) as http:
                response = http.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._key}"})
                response.raise_for_status()
                rows = response.json()["data"]
            prices = {r["id"]: Price(float(r["pricing"]["prompt"]), float(r["pricing"]["completion"])) for r in rows}
        except (httpx2.HTTPError, KeyError, TypeError, ValueError) as e:
            raise PriceUnavailable(f"could not read OpenRouter's model list: {e}") from e
        reasoning = {r["id"]: r["reasoning"] if isinstance(r.get("reasoning"), dict) else {} for r in rows}
        return prices, {m for m, r in reasoning.items() if r.get("default_enabled") and not r.get("mandatory")}


def _last_response(messages: list[ModelMessage]) -> ModelResponse | None:
    return next((m for m in reversed(messages) if isinstance(m, ModelResponse)), None)


def _classify(error: Exception, messages: list[ModelMessage]) -> str:
    if isinstance(error, IncompleteToolCall):
        return "cut-off"
    if isinstance(error, UnexpectedModelBehavior):
        last = _last_response(messages)
        return "cut-off" if last is not None and last.finish_reason == "length" else "fail"
    if isinstance(error, ModelHTTPError):
        if error.status_code == 402 or (error.status_code == 403 and _budget_spent(error.body)):
            return "credit"
        return "retry" if error.status_code in (408, 429) or error.status_code >= 500 else "fail"
    return "retry"  # connection errors and timeouts


def _budget_spent(body: object) -> bool:
    """A 403 for a spent key, workspace or guardrail budget (OpenRouter names it in `metadata.limit_source`),
    as opposed to a moderation or guardrail block of this one request."""
    if not isinstance(body, dict):
        return False
    metadata = body.get("metadata")
    return isinstance(metadata, dict) and bool(metadata.get("limit_source"))


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
