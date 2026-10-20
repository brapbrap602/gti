"""Importer for a github_pages Calibre HTML novel folder (`novels/<Novel>/index_*.html`).

Each page's TOC (`nav[role=doc-toc]`) links `#calibre_link-N` anchors; those are
the items, and an item's ref is `<page>#calibre_link-N`. Numbers come from the
TOC titles, never from the ids, which are offset differently in every export.
A chapter is either the div carrying the anchor id or, in the flat layout (My
Longevity Simulation), everything after the anchored <h1> up to the next anchor.
Pages overlap (WLHC's index_until912 holds 1-914, index_1_50 902-951), so when
pages share a printed number and part only the page with the longest copy keeps it;
the report counts the rest. Repeats within one page are left for `check` to report.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec
from novel_core.keys import parse_printed

from novel_sources.clean import CleanRules
from novel_sources.hosts import COMMON
from novel_sources.importing import NovelIndex

BACKEND = "import:calibre"
_BODY_ID = "calibre-chapter"
_RULES = COMMON | CleanRules(content=(f"div#{_BODY_ID}",))
_ANCHOR = re.compile(r"^#(calibre_link-\d+)$")


@dataclass(frozen=True)
class _Chapter:
    ref: str
    title: str
    html: str
    length: int  # characters of text, to choose between overlapping pages


class CalibreImporter:
    def __init__(self, folder: Path):
        self._folder = folder
        self._missing = 0
        pages = [self._read_page(p) for p in folder.glob("index_*.html")]
        # Order pages by their first chapter number: names like index_until912 don't sort.
        pages.sort(key=lambda chapters: _first_number(chapters))
        best: dict[tuple[int, int], tuple[int, int]] = {}  # printed (number, part) -> (length, page)
        for page_no, page in enumerate(pages):
            for c in page:
                number, part = parse_printed(c.title)
                if number is not None and c.length > best.get((number, part), (-1, 0))[0]:
                    best[number, part] = (c.length, page_no)
        chapters = [c for page in pages for c in page]
        kept = [
            c for page_no, page in enumerate(pages) for c in page
            if (printed := parse_printed(c.title))[0] is None or best[printed][1] == page_no
        ]  # fmt: skip
        self._overlaps = len(chapters) - len(kept)
        self._chapters = {c.ref: c for c in kept}

    @property
    def spec(self) -> SourceSpec:
        return SourceSpec(BACKEND, self._folder.resolve().as_uri(), "en", Kind.OFFICIAL_EN)

    def read_index(self) -> NovelIndex:
        items = tuple(
            SourceItem(c.ref, position, c.title, ref_numbered=False)
            for position, c in enumerate(self._chapters.values(), start=1)
        )
        notes = []
        if self._overlaps:
            notes.append(f"{self._overlaps} chapters found on two pages; the longer copy was imported")
        if self._missing:
            notes.append(f"{self._missing} TOC entries point at no chapter on their page")
        return NovelIndex(NovelMeta(title=self._folder.name), items, tuple(notes))

    def read_chapter(self, item: SourceItem) -> RawChapter:
        return RawChapter(self._chapters[item.ref].html, "html")

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return _RULES

    def _read_page(self, path: Path) -> list[_Chapter]:
        soup = BeautifulSoup(path.read_bytes().decode("utf-8", errors="replace"), "lxml")
        toc = []
        for a in soup.select("nav[role=doc-toc] a[href]"):
            if m := _ANCHOR.match(str(a["href"])):
                toc.append((m.group(1), a.get_text(" ", strip=True)))
        anchors = {anchor for anchor, _ in toc}
        chapters = []
        for anchor, title in toc:
            element = soup.find(id=anchor)
            if not isinstance(element, Tag):
                self._missing += 1
                continue
            parts = _flat_body(element, anchors) if element.name == "h1" else [element]
            inner = "".join(str(p) for p in parts)
            length = sum(len(p.get_text()) for p in parts if isinstance(p, Tag))
            chapters.append(_Chapter(f"{path.name}#{anchor}", title, f'<div id="{_BODY_ID}">{inner}</div>', length))
        return chapters


def _flat_body(heading: Tag, anchors: set[str]) -> list:
    """The siblings after an anchored <h1>, up to the next anchored element."""
    body = []
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag) and sibling.get("id") in anchors:
            break
        body.append(sibling)
    return body


def _first_number(chapters: list[_Chapter]) -> int:
    numbers = [n for c in chapters if (n := parse_printed(c.title)[0]) is not None]
    return min(numbers, default=0)
