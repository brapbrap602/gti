"""custom:skydemonorder backend: the free chapters of a Sky Demon Order project.

The site sits behind a Cloudflare challenge, which the scraper passes in Firefox
(see fetch.py). The chapter list is a lazily loaded Livewire component: the
project page holds its snapshot, and posting that snapshot to the Livewire
update endpoint returns the component's HTML, whose Alpine `x-data` carries the
`freeChapters` JSON. Locked chapters are not in it. lncrawl has a crawler for
this site, but its update request lacks the token the site checks, so it fails.
The episode number is the chapter number (titles only number story arcs).
"""

import json
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec, url_ref

from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.hosts import rules_for
from novel_sources.importing import NovelIndex

BACKEND = "custom:skydemonorder"
_FREE_CHAPTERS = re.compile(r"freeChapters:\s*JSON\.parse\('(.+?)'\)")
_LIVEWIRE = re.compile(r"(livewire-[a-f0-9]+)")


class SkyDemonOrderSource:
    def __init__(self, spec: SourceSpec, scraper):
        """`scraper` is a lncrawl-scraper Scraper for the site (fetch.firefox_scraper)."""
        self._spec = spec
        self._scraper = scraper

    @staticmethod
    def spec_for(url: str) -> SourceSpec:
        return SourceSpec(BACKEND, url.rstrip("/"), "en", Kind.OFFICIAL_EN)

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def fetch_index(self) -> NovelIndex:
        url = self._spec.url
        page = BeautifulSoup(self._get(url), "lxml")
        token = page.select_one('meta[name="csrf-token"]')
        script = page.select_one('script[src*="livewire"]')
        component = page.find("div", attrs={"wire:name": "project.chapter-list"})
        livewire = _LIVEWIRE.search(script["src"]) if script else None
        if token is None or livewire is None or component is None:
            raise FetchError(f"{url}: the project page has no Livewire chapter list")
        update = f"{_origin(url)}/{livewire.group(1)}/update"
        snapshot = {"snapshot": component["wire:snapshot"], "updates": {}, "calls": []}
        payload = {"_token": token["content"], "components": [snapshot]}
        headers = {"X-CSRF-TOKEN": token["content"], "X-Livewire": "", "Referer": url}
        try:
            answer = self._scraper.post(update, json=payload, headers=headers).json()
            html = answer["components"][0]["effects"]["html"]
        except (ValueError, KeyError, IndexError) as e:
            raise FetchError(f"{update}: unexpected Livewire answer ({type(e).__name__}: {e})") from e
        except Exception as e:  # lncrawl-scraper's Blocked/Exhausted, or its HTTP stack's errors
            raise FetchError(f"{update}: {type(e).__name__}: {e}") from e
        heading = page.select_one("h1")
        title = heading.get_text(" ", strip=True) if heading else url.rsplit("/", 1)[-1]
        return NovelIndex(meta=NovelMeta(title=title), items=free_chapters(url, html))

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


def free_chapters(project_url: str, component_html: str) -> tuple[SourceItem, ...]:
    """The free chapters in the chapter-list component's HTML, in episode order."""
    holder = BeautifulSoup(component_html, "lxml").select_one("div[x-data*=freeChapters]")
    m = _FREE_CHAPTERS.search(holder["x-data"]) if holder else None
    if m is None:
        raise FetchError(f"{project_url}: no free chapter list in the chapter-list component")
    # A JSON text inside a single-quoted JS string: undo the JS escapes (", \'), then parse.
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda u: chr(int(u.group(1), 16)), m.group(1)).replace("\\'", "'")
    chapters = sorted(json.loads(text), key=lambda c: c["episode"])
    base = url_ref(project_url)
    return tuple(
        SourceItem(f"{base}/{c['slug']}", position, c["title"].strip(), number=int(c["episode"]))
        for position, c in enumerate(chapters, start=1)
    )


def _origin(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"
