"""decode-guide backend: web-novel-scraper's per-host decode guides, read by our own engine.

web-novel-scraper ships a JSON guide: one entry per host, with a rule for each part
of a site (`index`: chapter links on the table of contents, `next_page`: the next
TOC page when `has_pagination`, `content`: the chapter body). A rule names elements
by `selector` (alternatives split by "XOR", first match wins) or by element / id /
class / attributes, optionally `extract`s an attribute or the text, and keeps every
match (`array`) or the first. A host may also register a custom processor for a part
(novelbin's TOC address, genesistudio's chapter list); those run in-process from the
web-novel-scraper package, which is a declared dependency. Pages are fetched with the
same ladder as every custom backend (fetch.py: Firefox only when a site challenges).

Where web-novel-scraper keeps only chapter URLs, the index here keeps the link text
as the item title, so chapters are numbered from titles like on every other source.
"""

import json
from datetime import UTC, datetime
from functools import cache
from importlib import resources
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec, url_ref

from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.hosts import COMMON, numbered_urls
from novel_sources.importing import NovelIndex

BACKEND = "decode-guide"
_BODY = "decode-guide-body"  # id of the div a fetched body is stored in, so normalize can find it
_XOR = "XOR"
_MAX_TOC_PAGES = 500  # a next-page rule that loops is cut off here


@cache
def guides() -> dict[str, dict]:
    """web-novel-scraper's guide entries by host."""
    text = resources.files("web_novel_scraper").joinpath("decode_guide/decode_guide.json").read_text(encoding="utf-8")
    return {entry["host"]: entry for entry in json.loads(text) if entry["host"] != "default"}


def guide_for(url: str) -> dict | None:
    host = (urlsplit(url).hostname or "").lower()
    bare = host.removeprefix("www.")
    return guides().get(host) or guides().get(bare) or guides().get(f"www.{bare}")


class DecodeGuideSource:
    def __init__(self, spec: SourceSpec, scraper):
        """`scraper` is a lncrawl-scraper Scraper for the site (fetch.firefox_scraper)."""
        guide = guide_for(spec.url)
        if guide is None:
            raise ValueError(f"{spec.url}: web-novel-scraper has no decode guide for this host")
        self._spec = spec
        self._guide = guide
        self._scraper = scraper

    @staticmethod
    def spec_for(url: str, lang: str = "en") -> SourceSpec:
        if guide_for(url) is None:
            raise ValueError(f"{url}: web-novel-scraper has no decode guide for this host")
        return SourceSpec(BACKEND, url, lang, Kind.RAW_ZH if lang == "zh" else Kind.OFFICIAL_EN)

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def fetch_index(self) -> NovelIndex:
        toc_url = self._processed("toc_main_url", self._spec.url) or self._spec.url
        links: list[tuple[str, str]] = []  # (absolute chapter URL, link text)
        seen_pages: set[str] = set()
        title = ""
        while toc_url and toc_url not in seen_pages and len(seen_pages) < _MAX_TOC_PAGES:
            seen_pages.add(toc_url)
            html = self._get(toc_url)
            title = title or _page_title(html)
            found = self._chapter_links(html)
            if not found:
                raise FetchError(f"{toc_url}: the decode guide's index rule matched no chapter links")
            links += [(urljoin(toc_url, href), text) for href, text in found]
            toc_url = self._next_page(html, toc_url) if self._guide.get("has_pagination") else None
        if self._guide["index"].get("inverted"):
            links.reverse()
        items, refs = [], set()
        for url, text in links:
            ref = url_ref(url)
            if ref in refs:  # a chapter linked twice (a "latest" box above the full list)
                continue
            refs.add(ref)
            items.append(SourceItem(ref, len(items) + 1, text, ref_numbered=numbered_urls(url)))
        meta = NovelMeta(title=title or self._spec.url.rstrip("/").rsplit("/", 1)[-1], language=self._spec.lang)
        return NovelIndex(meta, tuple(items))

    def fetch_chapter(self, item: SourceItem) -> RawChapter:
        url = urljoin(self._spec.url, item.ref)
        found = self._decode(self._get(url), "content")
        if not found:
            raise FetchError(f"{url}: the decode guide's content rule matched nothing")
        body = "\n".join(str(part) for part in found)
        return RawChapter(f'<div id="{_BODY}">{body}</div>', "html", final_url=url, fetched_at=datetime.now(UTC))

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return COMMON | CleanRules(content=(f"div#{_BODY}",), remove=tuple(self._guide.get("clean", ())))

    def _chapter_links(self, html: str) -> list[tuple[str, str]]:
        """(href, link text) of each chapter link on a TOC page. The rule's elements are kept
        whole (not reduced to the extracted href), so the link text can title the item."""
        processed = self._processed("index", html)
        if processed is not None:  # a processor gives URLs only
            return [(str(url), "") for url in (processed if isinstance(processed, list) else [processed])]
        rule = self._guide["index"]
        extract = rule.get("extract") or {}
        key = extract["key"] if extract.get("type") == "attr" else "href"
        links = []
        for a in select(BeautifulSoup(html, "lxml"), {**rule, "extract": None}):
            if href := a.get(key):
                links.append((href, a.get_text(" ", strip=True) or a.get("title", "")))
        return links

    def _next_page(self, html: str, page_url: str) -> str | None:
        found = self._decode(html, "next_page")
        first = found[0] if found else None
        href = first.get("href") if isinstance(first, Tag) else first
        return urljoin(page_url, href) if href else None

    def _decode(self, html: str, part: str) -> list:
        """What the guide's rule for `part` finds in the page: strings or elements, [] when nothing."""
        processed = self._processed(part, html)
        if processed is not None:
            return processed if isinstance(processed, list) else [processed]
        rule = self._guide.get(part)
        if not rule:
            return []
        return select(BeautifulSoup(html, "lxml"), rule)

    def _processed(self, part: str, value: str):
        """The host's custom processor's result for `part`, or None when it has none."""
        processor = _processors().get_processor(self._guide["host"], part)
        if processor is None:
            return None
        try:
            return processor.process(value)
        except Exception as e:  # web-novel-scraper's DecodeError family, or whatever the processor hit
            raise FetchError(f"{self._spec.url}: decode-guide {part} processor: {type(e).__name__}: {e}") from e

    def _get(self, url: str) -> str:
        try:
            response = self._scraper.get(url)
        except Exception as e:  # lncrawl-scraper's Blocked/Exhausted, or its HTTP stack's errors
            raise FetchError(f"{url}: {type(e).__name__}: {e}") from e
        if response.status_code >= 400:
            raise FetchError(f"{url}: HTTP {response.status_code}")
        return response.text


def select(soup: BeautifulSoup, rule: dict) -> list:
    """Apply one guide rule: the matching elements (or extracted strings), all of them or the first."""
    selector = rule.get("selector")
    alternatives = selector.split(_XOR) if selector else [_compose(rule)]
    elements: list = []
    for alternative in alternatives:
        if alternative.strip() and (elements := soup.select(alternative.strip())):
            break
    extract = rule.get("extract")
    if extract and extract["type"] == "attr":
        elements = [value for e in elements if (value := e.get(extract["key"]))]
    elif extract and extract["type"] == "text":
        elements = [e.get_text(" ", strip=True) for e in elements]
    return elements if rule.get("array") else elements[:1]


def _compose(rule: dict) -> str:
    selector = rule.get("element") or ""
    if rule.get("id"):
        selector += f"#{rule['id']}"
    if rule.get("class"):
        selector += f".{rule['class']}"
    for attr, value in (rule.get("attributes") or {}).items():
        selector += f'[{attr}="{value}"]' if value is not None else f"[{attr}]"
    return selector


def _page_title(html: str) -> str:
    heading = BeautifulSoup(html, "lxml").select_one("h1")
    return heading.get_text(" ", strip=True) if heading else ""


@cache
def _processors():
    from web_novel_scraper.custom_processor import ProcessorRegistry  # importing it registers the site processors

    return ProcessorRegistry
