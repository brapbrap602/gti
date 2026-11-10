"""Importer for an EPUB file: its chapters, as the book's table of contents lists them.

Chapters come from the TOC (toc.ncx, else the EPUB 3 nav document), in reading order.
An entry runs from its anchor to the next entry's anchor, so a document holding several
chapters is cut at their anchors, and a volume heading above a chapter's own entry is a
divider of its own. A spine document the TOC doesn't list is a chapter of its own when it
has a heading, else the rest of the chapter before it (calibre splits long chapters into
headless files). A book with no TOC has a chapter per spine document.

An item's ref is the document's path inside the EPUB, plus `#anchor` when the entry
starts at one. Its title is the TOC label (else the chapter's heading, else <title>); its
number comes from "Chapter N", then a "chapter-N" slug, then a leading bare number
("502 Our Secret Weapon"), never from a file name, which counts from 0 or not at all.

Left out, by title in the report: dividers (a volume or arc heading with no text under
it), the cover and contents pages, and the front and back matter outside the numbered
chapters (synopsis, credits, ...) unless its title names a part of the story: a prologue,
epilogue, afterword, side story, extra or the like. Unnumbered chapters between numbered
ones (author notes, interludes) are kept; `nov check` lists them for keying.
"""

import posixpath
import re
import warnings
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag, UnicodeDammit, XMLParsedAsHTMLWarning
from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec
from novel_core.keys import parse_printed

from novel_sources.clean import CleanRules
from novel_sources.hosts import COMMON
from novel_sources.importing import NovelIndex

BACKEND = "import:epub"
_RULES = COMMON | CleanRules(content=("body",))
_HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
_SLUG_NUMBER = re.compile(r"chapter[\s_-]*(\d+)", re.IGNORECASE)
_BARE_NUMBER = re.compile(r"^\s*#?\s*(\d+)\b(?![.,:]?\d)")
_STORY_PART = re.compile(
    r"\b(?:prologue|prolog|epilogue|afterword|interlude|intermission|side ?stor(?:y|ies)|extras?|bonus|specials?"
    r"|author'?s? ?notes?|translator'?s? ?notes?)\b|序章|序幕|楔子|尾声|后记|番外|感言",
    re.IGNORECASE,
)
_DIVIDER_TEXT = 3  # characters under the headings: fewer, and the entry only marks a volume or arc
_BODY_OPEN = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
_BODY_CLOSE = re.compile(r"</body\s*>", re.IGNORECASE)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_NOT_CHAPTERS = {"cover", "toc", "title-page", "copyright-page"}  # OPF guide reference types

type _Entry = tuple[str, str | None, str]  # (document, anchor or None, label)


@dataclass
class _Chapter:
    ref: str
    title: str
    parts: list[str]  # body HTML: the chapter's own, then any headless continuations
    whole: str | None  # the document's full HTML when the chapter is exactly one document
    numbered_headings: int
    text_under_headings: int
    number: int | None = field(init=False)

    def __post_init__(self) -> None:
        self.number = chapter_number(self.title)

    @property
    def is_divider(self) -> bool:
        """A volume or arc heading with (almost) no text under it."""
        return self.number is None and len(self.parts) == 1 and self.text_under_headings < _DIVIDER_TEXT

    def html(self) -> str:
        if self.whole is not None and len(self.parts) == 1:
            return self.whole
        return "<html><body>" + "".join(self.parts) + "</body></html>"


class EpubImporter:
    def __init__(self, path: Path):
        self._path = path
        try:
            with zipfile.ZipFile(path) as z:
                book = _Book(z)
                chapters = list(book.chapters())
                self._meta = book.meta()
        except (zipfile.BadZipFile, KeyError) as e:
            raise ValueError(f"{path}: not an EPUB ({e})") from e
        self._notes = list(book.notes)
        self._chapters = {c.ref: c for c in self._keep(chapters)}
        if not any(c.number is not None for c in self._chapters.values()):
            raise ValueError(f"{path}: no numbered chapters among {len(chapters)} TOC entries and documents")

    def _keep(self, chapters: list[_Chapter]) -> list[_Chapter]:
        """Drop dividers, and the front and back matter outside the numbered chapters that isn't story."""
        dividers = [c for c in chapters if c.is_divider]
        chapters = [c for c in chapters if not c.is_divider]
        numbered = [i for i, c in enumerate(chapters) if c.number is not None]
        first, last = (numbered[0], numbered[-1]) if numbered else (len(chapters), -1)
        kept, matter = [], []
        for i, c in enumerate(chapters):
            (kept if first <= i <= last or _STORY_PART.search(c.title) else matter).append(c)
        if dividers:
            self._notes.append(f"left out {len(dividers)} dividers: {_titles(dividers)}")
        if matter:
            self._notes.append(f"left out {len(matter)} front/back matter entries: {_titles(matter)}")
        if multi := [c for c in kept if c.numbered_headings > 1]:
            self._notes.append(f"{len(multi)} items hold several numbered headings, imported as one each: {_titles(multi)}")
        return kept

    @property
    def spec(self) -> SourceSpec:
        zh = self._meta.language.lower().startswith("zh")
        kind = Kind.RAW_ZH if zh else Kind.OFFICIAL_EN
        return SourceSpec(BACKEND, self._path.resolve().as_uri(), "zh" if zh else "en", kind)

    def read_index(self) -> NovelIndex:
        items = tuple(
            SourceItem(c.ref, position, c.title, number=c.number, ref_numbered=False)
            for position, c in enumerate(self._chapters.values(), start=1)
        )
        return NovelIndex(self._meta, items, tuple(self._notes))

    def read_chapter(self, item: SourceItem) -> RawChapter:
        return RawChapter(self._chapters[item.ref].html(), "html")

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return _RULES


def chapter_number(title: str) -> int | None:
    """'Chapter N' / 第N章, else a 'chapter-N' slug, else a leading bare number ('502 Our Secret Weapon')."""
    number = parse_printed(title)[0]
    if number is None and (m := _SLUG_NUMBER.search(title) or _BARE_NUMBER.match(title)):
        number = int(m.group(1))
    return number


class _Book:
    """An open EPUB: its package, spine and TOC, and the chapters they make."""

    def __init__(self, z: zipfile.ZipFile):
        self._z = z
        container = BeautifulSoup(z.read("META-INF/container.xml"), "xml")
        rootfile = container.find("rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            raise KeyError("container.xml names no rootfile")
        self._opf_path = str(rootfile["full-path"])
        self._opf = BeautifulSoup(z.read(self._opf_path), "xml")
        self._manifest = {str(i["id"]): i for i in self._opf.select("manifest > item[id][href]")}
        self.notes: list[str] = []

    def meta(self) -> NovelMeta:
        def text(tag: str) -> str | None:
            element = self._opf.find(tag)
            return (element.get_text(strip=True) or None) if element else None

        return NovelMeta(title=text("title") or "Untitled", author=text("creator"), language=text("language") or "en")

    def chapters(self) -> Iterator[_Chapter]:
        """Every TOC entry and unlisted headed document as a chapter, in reading order."""
        spine = self._spine()
        toc = [e for e in self._toc() if e[0] in spine]
        by_doc: dict[str, dict[str | None, str]] = {}
        for ref, anchor, label in toc:  # a volume and its first chapter at one place: the later (chapter) wins
            by_doc.setdefault(ref, {})[anchor] = label
        skip = self._not_chapters()
        missing = []
        current: _Chapter | None = None
        for ref in spine:
            try:
                html = _decode(self._z.read(ref))
            except KeyError:
                missing.append(ref)
                continue
            start, end = _body_bounds(html)
            entries = by_doc.get(ref)
            if entries is None:
                if ref in skip:
                    continue
                body = html[start:end]
                chapter = _chapter(ref, "", body, html)
                if chapter.title == "" and toc and current is not None:  # a headless continuation
                    current.parts.append(body)
                    continue
                if not chapter.title:
                    chapter.title = _doc_title(html) or posixpath.basename(ref)
                    chapter.number = chapter_number(chapter.title) if chapter.title != posixpath.basename(ref) else None
                current = chapter
                yield current
                continue
            cuts = sorted((_anchor_at(html, anchor, start, end), anchor or "", label) for anchor, label in entries.items())
            if cuts[0][0] > start and current is not None:  # text before the first anchor ends the last chapter
                current.parts.append(html[start : cuts[0][0]])
            for i, (at, anchor, label) in enumerate(cuts):
                upto = cuts[i + 1][0] if i + 1 < len(cuts) else end
                whole = html if len(cuts) == 1 and at <= start else None
                current = _chapter(f"{ref}#{anchor}" if anchor else ref, label, html[at:upto], whole)
                yield current
        if missing:
            self.notes.append(f"{len(missing)} spine documents missing from the EPUB: {', '.join(missing[:10])}")

    def _spine(self) -> list[str]:
        refs = []
        for itemref in self._opf.select("spine > itemref[idref]"):
            item = self._manifest.get(str(itemref["idref"]))
            if item is not None and (ref := _resolve(self._opf_path, str(item["href"]))[0]) not in refs:
                refs.append(ref)
        return refs

    def _nav_path(self) -> str | None:
        nav = next((i for i in self._manifest.values() if "nav" in str(i.get("properties", "")).split()), None)
        return _resolve(self._opf_path, str(nav["href"]))[0] if nav is not None else None

    def _not_chapters(self) -> set[str]:
        """The nav document and the guide's cover, title and contents pages."""
        refs = {nav} if (nav := self._nav_path()) else set()
        for reference in self._opf.select("guide > reference[type][href]"):
            if str(reference["type"]).lower() in _NOT_CHAPTERS:
                refs.add(_resolve(self._opf_path, str(reference["href"]))[0])
        return refs

    def _toc(self) -> list[_Entry]:
        """The TOC entries, in order: toc.ncx, else the nav document."""
        spine = self._opf.select_one("spine")
        ncx = self._manifest.get(str(spine.get("toc"))) if spine is not None else None
        ncx = ncx or next((i for i in self._manifest.values() if i.get("media-type") == "application/x-dtbncx+xml"), None)
        if ncx is not None and (entries := self._ncx_entries(_resolve(self._opf_path, str(ncx["href"]))[0])):
            return entries
        nav = self._nav_path()
        return self._nav_entries(nav) if nav else []

    def _ncx_entries(self, path: str) -> list[_Entry]:
        try:
            ncx = BeautifulSoup(self._z.read(path), "xml")
        except KeyError:
            return []
        entries = []
        for point in ncx.find_all("navPoint"):
            content = point.find("content", recursive=False)
            label = point.find("navLabel", recursive=False)
            if content is not None and content.get("src"):
                text = label.get_text(" ", strip=True) if label else ""
                entries.append((*_resolve(path, str(content["src"])), text))
        return entries

    def _nav_entries(self, path: str) -> list[_Entry]:
        try:
            soup = _soup(_decode(self._z.read(path)))
        except KeyError:
            return []
        nav = soup.find("nav", attrs={"epub:type": "toc"}) or soup.find("nav")
        if not isinstance(nav, Tag):
            return []
        return [(*_resolve(path, str(a["href"])), a.get_text(" ", strip=True)) for a in nav.select("a[href]")]


def _resolve(base_file: str, href: str) -> tuple[str, str | None]:
    """(zip path, anchor) of an href relative to the file that holds it."""
    path, _, anchor = href.partition("#")
    ref = posixpath.normpath(posixpath.join(posixpath.dirname(base_file), unquote(path)))
    return ref, unquote(anchor) or None


def _chapter(ref: str, label: str, body: str, whole: str | None) -> _Chapter:
    """A chapter from its body HTML, titled by its TOC label, else its numbered heading, else its first heading."""
    soup = _soup(body)
    headings = [t for h in soup.find_all(_HEADINGS) if (t := h.get_text(" ", strip=True))]
    numbered = [h for h in headings if chapter_number(h) is not None]
    title = label.strip()
    if chapter_number(title) is None and numbered:
        title = numbered[0]
    title = title or (headings[0] if headings else "")
    under = len(soup.get_text(" ", strip=True)) - sum(len(h) for h in headings)
    return _Chapter(ref, title, [body], whole, len({chapter_number(h) for h in numbered}), under)


def _decode(data: bytes) -> str:
    """The document's text: UTF-8 when it decodes as such (nearly every book, and fast), else the encoding
    its BOM or declaration names (UTF-16 and GBK books exist), else a guess."""
    if not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    return UnicodeDammit(data, is_html=True).unicode_markup or data.decode("utf-8", errors="replace")


def _soup(html: str) -> BeautifulSoup:
    with warnings.catch_warnings():  # XHTML read as HTML, as normalize reads it
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(html, "lxml")


def _body_bounds(html: str) -> tuple[int, int]:
    opened = _BODY_OPEN.search(html)
    start = opened.end() if opened else 0
    closes = list(_BODY_CLOSE.finditer(html, start))
    return start, closes[-1].start() if closes else len(html)


def _anchor_at(html: str, anchor: str | None, start: int, end: int) -> int:
    """Where the element with this id (or name) opens; the body's start for no anchor or one not found."""
    if anchor is None:
        return start
    m = re.compile(rf"""<[^<>]*\s(?:id|name)\s*=\s*["']{re.escape(anchor)}["']""").search(html, start, end)
    return m.start() if m else start


def _doc_title(html: str) -> str | None:
    m = _TITLE.search(html)
    return (re.sub(r"\s+", " ", m.group(1)).strip() or None) if m else None


def _titles(chapters: list[_Chapter], limit: int = 12) -> str:
    names = [c.title for c in chapters[:limit]]
    return ", ".join(names) + (f", ... ({len(chapters) - limit} more)" if len(chapters) > limit else "")
