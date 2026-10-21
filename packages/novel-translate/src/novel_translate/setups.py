"""Translator setups: each one is its own `my-translation` source of the novel.

A setup is model + prompt version + context mode + reasoning + data collection, and
how many consecutive chapters go in one request (`group`, 1 unless set).
Its source URL spells all of them out, so a setup never changes: a different
choice is a different setup (and source), which is what makes them comparable.
New setups start unpublished; publishing one is the user's call.
"""

from dataclasses import asdict, dataclass
from importlib import resources
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from novel_core import Kind, NovelStore, SourceId, SourceInfo, SourceSpec

BACKEND = "translate:openrouter"
CONTEXTS = ("parallel", "sequential")
REASONING = ("off", "low", "medium", "high")
DATA_COLLECTION = ("allow", "deny")
MAX_GROUP = 10

type Context = Literal["parallel", "sequential"]


class SetupError(Exception):
    """A setup the novel refuses: unknown prompt version, or a source that disagrees with its URL."""


@dataclass(frozen=True)
class TranslatorSetup:
    model: str
    prompt_version: str = "v1"
    context: Context = "parallel"
    reasoning: str = "off"
    data_collection: str = "allow"
    group: int = 1  # chapters per request

    def __post_init__(self):
        if not self.model.strip() or "?" in self.model:
            raise SetupError(f"not an OpenRouter model id: {self.model!r}")
        if self.prompt_version not in prompt_versions():
            raise SetupError(f"no prompt {self.prompt_version!r}; there are {', '.join(prompt_versions())}")
        for value, allowed, name in (
            (self.context, CONTEXTS, "context"),
            (self.reasoning, REASONING, "reasoning"),
            (self.data_collection, DATA_COLLECTION, "data collection"),
        ):
            if value not in allowed:
                raise SetupError(f"{name} must be one of {', '.join(allowed)}, not {value!r}")
        if not 1 <= self.group <= MAX_GROUP:
            raise SetupError(f"chapters per request must be 1 to {MAX_GROUP}, not {self.group}")
        if self.group > 1 and self.context == "sequential":
            raise SetupError("a sequential setup sends one chapter per request")

    @property
    def url(self) -> str:
        return (
            f"openrouter:{self.model}?prompt={self.prompt_version}&context={self.context}"
            f"&reasoning={self.reasoning}&dc={self.data_collection}"
        ) + (f"&group={self.group}" if self.group > 1 else "")

    @property
    def label(self) -> str:
        extras = [self.context] + ([f"reasoning {self.reasoning}"] if self.reasoning != "off" else [])
        extras += ["no data collection"] if self.data_collection == "deny" else []
        extras += [f"{self.group} chapters per request"] if self.group > 1 else []
        return f"{self.model} · prompt {self.prompt_version} · {', '.join(extras)}"

    def spec(self) -> SourceSpec:
        return SourceSpec(BACKEND, self.url, "en", Kind.MY_TRANSLATION, asdict(self))

    @classmethod
    def from_spec(cls, spec: SourceSpec) -> "TranslatorSetup":
        if spec.backend != BACKEND:
            raise SetupError(f"{spec.url} is not a translator setup")
        return cls.from_url(spec.url)

    @classmethod
    def from_url(cls, text: str) -> "TranslatorSetup":
        url = urlsplit(text)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        return cls(url.path, query["prompt"], query["context"], query["reasoning"], query["dc"], int(query.get("group", 1)))


def register(store: NovelStore, setup: TranslatorSetup) -> SourceId:
    """The setup's source: added unpublished if it is new; refused if one with its URL disagrees."""
    for info in store.sources():
        if (info.spec.backend, info.spec.url) == (BACKEND, setup.url) and {"group": 1, **info.spec.config} != asdict(setup):
            raise SetupError(f"source {info.id} has this setup's URL but another configuration")
    return store.upsert_source(setup.spec(), published=False)


def setups(sources: tuple[SourceInfo, ...] | list[SourceInfo]) -> list[tuple[SourceInfo, TranslatorSetup]]:
    return [(info, TranslatorSetup.from_spec(info.spec)) for info in sources if info.spec.backend == BACKEND]


def prompt_versions() -> tuple[str, ...]:
    files = resources.files(__package__).joinpath("prompts").iterdir()
    return tuple(sorted(f.name.removesuffix(".md") for f in files if f.name.endswith(".md")))


def prompt(version: str) -> str:
    """A prompt file's text; a version is never edited once used (edit a copy as the next version)."""
    return resources.files(__package__).joinpath("prompts", f"{version}.md").read_text(encoding="utf-8")
