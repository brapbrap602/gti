"""custom:hangulplanet backend: a HangulPlanet novel's chapters.

The novel page is a Next.js page whose chapter list renders only its first page
(the newest ~50 chapters); later pages load client-side through /api, which
robots.txt disallows. The site's chapter sitemaps (listed in its content sitemap
index) carry every chapter URL, so the index is their entries under the novel's
path, plus the novel page's own links in case a sitemap lags behind a new
chapter. Chapter URLs end in `chapter-<number>`, the chapter number; the site
titles chapters only "Chapter <number>".
"""

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec, url_ref

from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.hosts import rules_for
from novel_sources.importing import NovelIndex

BACKEND = "custom:hangulplanet"
SITEMAP_INDEX = "/content/sitemap.xml"
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


class HangulPlanetSource:
    def __init__(self, spec: SourceSpec, scraper):
        """`scraper` is a lncrawl-scraper Scraper for the site (fetch.firefox_scraper)."""
        self._spec = spec
        self._scraper = scraper

    @staticmethod
    def spec_for(url: str) -> SourceSpec:
        u = urlsplit(url)
        return SourceSpec(BACKEND, f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}", "en", Kind.OFFICIAL_EN)

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def fetch_index(self) -> NovelIndex:
        url = self._spec.url
        page = BeautifulSoup(self._get(url), "lxml")
        links = [a["href"] for a in page.select("a[href]")]
        sitemaps = [loc for loc in _LOC.findall(self._get(_origin(url) + SITEMAP_INDEX)) if "chapters" in loc]
        if not sitemaps:
            raise FetchError(f"{_origin(url)}{SITEMAP_INDEX}: no chapter sitemap listed")
        for sitemap in sitemaps:
            links += _LOC.findall(self._get(sitemap))
        items = novel_chapters(url, links)
        if not items:
            raise FetchError(f"{url}: no chapter links in the novel page or the chapter sitemaps")
        og = page.select_one('meta[property="og:title"]')
        title = og["content"].strip() if og else url.rsplit("/", 1)[-1]
        cover = page.select_one('meta[property="og:image"]')
        return NovelIndex(meta=NovelMeta(title=title), items=items, cover_url=cover["content"] if cover else None)

    def fetch_chapter(self, item: SourceItem) -> RawChapter:
        url = _origin(self._spec.url) + item.ref
        return RawChapter(self._get(url), "html", final_url=url, fetched_at=datetime.now(UTC))

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return rules_for(raw.final_url or self._spec.url)

    def _get(self, url: str) -> str:
        try:
            response = self._scraper.get(url)
        except Exception as e:  # lncrawl-scraper's Blocked/Exhausted, or its HTTP stack's errors
            raise FetchError(f"{url}: {type(e).__name__}: {e}") from e
        if response.status_code >= 400:
            raise FetchError(f"{url}: HTTP {response.status_code}")
        return response.text


def novel_chapters(novel_url: str, links: list[str]) -> tuple[SourceItem, ...]:
    """The novel's chapters among `links` (absolute or site-relative URLs), once each, by number."""
    base = url_ref(novel_url)
    chapter = re.compile(rf"^{re.escape(base)}/chapter-(\d+)$")
    numbers = {int(m.group(1)) for link in links if (m := chapter.match(url_ref(link)))}
    return tuple(
        SourceItem(f"{base}/chapter-{n}", position, f"Chapter {n}", number=n)
        for position, n in enumerate(sorted(numbers), start=1)
    )


def _origin(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"
