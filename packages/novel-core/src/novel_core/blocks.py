"""Typed blocks: the content IR of a chapter version."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Run:
    text: str
    em: bool = False
    strong: bool = False


@dataclass(frozen=True)
class Paragraph:
    runs: tuple[Run, ...]

    @classmethod
    def of(cls, text: str) -> "Paragraph":
        return cls((Run(text),))

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass(frozen=True)
class Heading:
    text: str
    level: int = 2


@dataclass(frozen=True)
class Separator:
    pass


@dataclass(frozen=True)
class Image:
    src: str
    alt: str = ""


@dataclass(frozen=True)
class System:
    """A game-system/status line, from an optional per-novel detection rule."""

    text: str


@dataclass(frozen=True)
class Note:
    """A translator/author note, from an optional per-novel detection rule."""

    text: str


type Block = Paragraph | Heading | Separator | Image | System | Note

_TYPES: dict[str, type] = {
    "paragraph": Paragraph,
    "heading": Heading,
    "separator": Separator,
    "image": Image,
    "system": System,
    "note": Note,
}
_NAMES = {cls: name for name, cls in _TYPES.items()}


def blocks_to_json(blocks: Sequence[Block]) -> str:
    """Canonical JSON: the same blocks always give the same string."""
    return json.dumps(
        [{"type": _NAMES[type(b)], **asdict(b)} for b in blocks],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def blocks_from_json(text: str) -> tuple[Block, ...]:
    out: list[Block] = []
    for raw in json.loads(text):
        cls = _TYPES[raw.pop("type")]
        if cls is Paragraph:
            raw["runs"] = tuple(Run(**r) for r in raw["runs"])
        out.append(cls(**raw))
    return tuple(out)


def content_hash(title: str, blocks: Sequence[Block]) -> str:
    payload = json.dumps(title, ensure_ascii=False) + "\n" + blocks_to_json(blocks)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
