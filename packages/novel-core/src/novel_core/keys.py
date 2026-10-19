"""Chapter identity: ChapterKey, key ranges, item refs and printed-number parsing."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import cn2an

type ItemRef = str


@dataclass(frozen=True, order=True)
class ChapterKey:
    """Canonical chapter identity. Ordered by number, then part (524 < 524 pt 1 < 525)."""

    number: int
    part: int = 0

    @property
    def label(self) -> str:
        return f"{self.number} pt {self.part}" if self.part else str(self.number)

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class KeyRange:
    """Inclusive range of chapter numbers; covers every part of each number."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"empty range {self.start}-{self.end}")

    def __contains__(self, number: object) -> bool:
        return isinstance(number, int) and self.start <= number <= self.end


def url_ref(url: str) -> ItemRef:
    """Item ref of a web chapter: the URL path without scheme, host, query, fragment or trailing slash.

    A host move (novelbin.me -> novelbin.com) therefore keeps every ref.
    """
    path = urlsplit(url).path.rstrip("/")
    return path or "/"


_TITLE_NUMBER = re.compile(r"\bchapter\s*(\d+)", re.IGNORECASE)
_CJK_NUMBER = re.compile(r"第\s*([0-9零〇一二三四五六七八九十百千万两]+)\s*[章节回]")
_SLUG_NUMBER = re.compile(r"chapter-(\d+)", re.IGNORECASE)
_LEADING_NUMBER = re.compile(r"^(\d+)(?:-|$)")
_PART = re.compile(r"(?:\((?:(?:part|pt)\.?\s*)?(\d+)\)|\b(?:part|pt)\.?\s*(\d+))\s*$", re.IGNORECASE)


def parse_printed(title: str, ref: ItemRef = "") -> tuple[int | None, int]:
    """Printed (number, part) from a title, else from the ref's last path segment.

    The number is None for items without one (prologue, side story, notice).
    The part is 0 unless the title ends with "(N)", "(part N)", "part N" or "pt N".
    Whether a part really splits a chapter is decided at key derivation.
    """
    number = title_number(title)
    if number is None:
        slug = ref.rsplit("/", 1)[-1]
        m = _SLUG_NUMBER.search(slug) or _LEADING_NUMBER.match(slug)
        number = int(m.group(1)) if m else None
    title_head = re.split(r"[:：\-–—]", title, maxsplit=1)[0]
    part = _PART.search(title_head.strip()) or _PART.search(title.strip())
    return number, int(part.group(1) or part.group(2)) if part else 0


def title_number(title: str) -> int | None:
    """The chapter number written in a title ("Chapter 12", "第十二章"), if any."""
    if m := _TITLE_NUMBER.search(title):
        return int(m.group(1))
    if m := _CJK_NUMBER.search(title):
        return int(cn2an.cn2an(m.group(1), "smart"))
    return None


# Up to and through "Chapter N", wherever it starts: some sources put the novel's name first
# ("Who Let Him Cultivate?! (WX)-Chapter 1: Today Is ...").
_CHAPTER_PREFIX = re.compile(
    r"^.{0,80}?\bchapter\s*\d+\s*(?:\((?:(?:part|pt)\.?\s*)?\d+\)|(?:part|pt)\.?\s*\d+)?\s*[:：\-–—.]*\s*", re.IGNORECASE
)


def chapter_heading(key: ChapterKey, title: str) -> str:
    """'Chapter 524 pt 1: The Gate' from key (524, 1) and a source title like 'Chapter 524 (1) - The Gate'."""
    rest = _CHAPTER_PREFIX.sub("", title, count=1).strip()
    return f"Chapter {key.label}: {rest}" if rest else f"Chapter {key.label}"
