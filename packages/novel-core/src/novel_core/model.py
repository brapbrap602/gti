"""Records passed into and out of NovelStore."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from novel_core.alignment import AlignmentRules
from novel_core.blocks import Block
from novel_core.finding import Finding
from novel_core.keys import ChapterKey, ItemRef
from novel_core.selection import SourceId


class Kind(StrEnum):
    """What a source's text is. Raw-zh text is stored but never published."""

    OFFICIAL_EN = "official-en"
    RAW_ZH = "raw-zh"
    MY_TRANSLATION = "my-translation"


@dataclass(frozen=True)
class NovelMeta:
    title: str
    author: str | None = None
    language: str = "en"
    status: str | None = None
    cover_path: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceSpec:
    """A source is identified by (backend, url); upserting the same pair updates the rest."""

    backend: str  # lncrawl | lnreader | decode-guide | novel-downloader | custom:<name> | import:<kind>
    url: str
    lang: str
    kind: Kind
    config: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceInfo:
    id: SourceId
    spec: SourceSpec
    alignment: AlignmentRules
    published: bool = True  # off: kept out of the book (site, EPUB, audio); set by the user, never by an upsert


@dataclass(frozen=True)
class SourceItem:
    """One entry of a source's chapter list, identified by `ref` within its source.

    `number` is the backend's printed number. When it is None, the number is parsed
    from the title, then from the ref's slug unless `ref_numbered` is False (hosts that
    number their URLs by position, like freewebnovel). `part` is parsed from the title when None.
    """

    ref: ItemRef
    position: int
    title: str
    number: int | None = None
    part: int | None = None
    ref_numbered: bool = True


class ItemStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"  # locked/premium: a gap, not an error


@dataclass(frozen=True)
class IndexDiff:
    added: tuple[ItemRef, ...]
    vanished: tuple[ItemRef, ...]
    revived: tuple[ItemRef, ...]


@dataclass(frozen=True)
class Moved:
    item_ref: ItemRef
    old: ChapterKey | None
    new: ChapterKey | None


@dataclass(frozen=True)
class AlignmentDiff:
    moved: tuple[Moved, ...]


@dataclass(frozen=True)
class RawChapter:
    """A fetched or imported page before normalization."""

    content: str
    content_type: Literal["html", "text"] = "html"
    final_url: str | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class NewVersion:
    """A chapter text to store. Findings and rules_rev come from the checks that judged it (raw-zh only);
    rules_rev None means no checks ran, so a stored text keeps the findings it has."""

    title: str
    blocks: Sequence[Block]
    raw: RawChapter | None = None
    provenance: Mapping[str, object] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    rules_rev: str | None = None


@dataclass(frozen=True)
class Inserted:
    version_id: int
    content_hash: str


@dataclass(frozen=True)
class Unchanged:
    """The same text was already stored; its last_seen_at was bumped, making it current.

    It also took the put's raw (when given), and its findings and rules_rev (when rules_rev is given).
    """

    version_id: int
    content_hash: str


type PutResult = Inserted | Unchanged


@dataclass(frozen=True)
class Version:
    id: int
    source_id: SourceId
    item_ref: ItemRef
    title: str
    blocks: tuple[Block, ...]
    content_hash: str
    provenance: Mapping[str, object]
