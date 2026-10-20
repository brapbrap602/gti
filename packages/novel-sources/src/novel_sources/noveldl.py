"""novel-downloader backend: Chinese raw sites, through novel-downloader's site plugins in-process.

Each site has a fetcher (async; returns the raw pages) and a parser (pages -> book
info or chapter text). The backend runs them on an event loop it owns, so it reads
like every other blocking Source. Sites novel-downloader lacks are added as plugins
in noveldl_sites. Chapter text is converted to Simplified Chinese (OpenCC t2s), so
raws from Traditional mirrors compare and translate like the rest; on Simplified
text it is a no-op. Item refs are chapter URL paths, like every web backend; sites
number their URLs by position, so chapter numbers come from titles (cn2an reads
第一千零六十章).
"""

import asyncio
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from urllib.parse import urljoin

from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec, url_ref
from novel_downloader.infra.book_url_resolver import resolve_book_url
from novel_downloader.plugins.registry import registrar
from novel_downloader.schemas import FetcherConfig, ParserConfig
from opencc import OpenCC

from novel_sources import noveldl_sites  # noqa: F401  (registers the extra site plugins)
from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.importing import NovelIndex

BACKEND = "novel-downloader"
# English junk rules read every CJK letter as a wildcard, so Chinese text gets none of them.
_RAW_RULES = CleanRules(content=())


def site_book(url: str) -> tuple[str, str] | None:
    """(site key, book id) when a novel-downloader plugin reads this URL, else None."""
    info = resolve_book_url(url)
    if info is None or not info["book_id"]:
        return None
    return info["site_key"], info["book_id"]


def connect(spec: SourceSpec, state: Path) -> "NovelDownloaderSource":
    """The source for a spec, with the site's fetcher and parser. Close it when done.

    `state` is where fetching keeps what it learns per site (novel-downloader's cache).
    """
    site, _ = _site_book(spec.url)
    cache_dir = str(state / "novel-downloader")
    fetcher = registrar.get_fetcher(site, FetcherConfig(cache_dir=cache_dir, request_interval=1.0))
    parser = registrar.get_parser(site, ParserConfig(cache_dir=cache_dir))
    return NovelDownloaderSource(spec, fetcher, parser)


class NovelDownloaderSource:
    def __init__(self, spec: SourceSpec, fetcher, parser):
        """`fetcher` and `parser` are novel-downloader's for the site (see `connect`); the source closes the fetcher."""
        self._spec = spec
        self._book_id = _site_book(spec.url)[1]
        self._fetcher = fetcher
        self._parser = parser
        self._loop = asyncio.Runner()
        self._started = False
        self._ids: dict[str, str] = {}  # item ref -> chapter id, from the last index

    @staticmethod
    def spec_for(url: str) -> SourceSpec:
        _site_book(url)
        return SourceSpec(BACKEND, url, "zh", Kind.RAW_ZH)

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def fetch_index(self) -> NovelIndex:
        url = self._spec.url
        pages = self._run(url, self._fetcher.fetch_book_info(self._book_id))
        info = self._parser.parse_book_info(pages) if pages else None
        if info is None:
            raise FetchError(f"{url}: novel-downloader found no chapter list")
        items = []
        chapters = (c for volume in info["volumes"] for c in volume["chapters"])
        for position, chapter in enumerate(chapters, start=1):
            ref = url_ref(urljoin(url, chapter["url"])) if chapter.get("url") else f"#{chapter['chapterId']}"
            self._ids[ref] = chapter["chapterId"]
            items.append(SourceItem(ref, position, _simplified(chapter["title"].strip()), ref_numbered=False))
        meta = NovelMeta(
            title=_simplified(info["book_name"]),
            author=_simplified(info["author"]) or None,
            language="zh",
            tags=tuple(info.get("tags") or ()),
        )
        return NovelIndex(meta, tuple(items))

    def fetch_chapter(self, item: SourceItem) -> RawChapter:
        chapter_id = self._ids.get(item.ref)
        if chapter_id is None:
            raise FetchError(f"{item.ref}: not in the index fetched this run")
        where = f"{self._spec.url} chapter {chapter_id}"
        pages = self._run(where, self._fetcher.fetch_chapter_content(self._book_id, chapter_id))
        chapter = self._parser.parse_chapter_content(pages, chapter_id) if pages else None
        if chapter is None or not chapter["content"].strip():
            raise FetchError(f"{where}: novel-downloader returned an empty chapter")
        final_url = urljoin(self._spec.url, item.ref) if item.ref.startswith("/") else None
        return RawChapter(_simplified(chapter["content"]), "text", final_url=final_url, fetched_at=datetime.now(UTC))

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return _RAW_RULES

    def close(self) -> None:
        if self._started:
            self._loop.run(self._fetcher.close())
            self._started = False
        self._loop.close()

    def _run(self, where: str, request):
        """Run one fetcher coroutine on the source's loop; FetchError on failure."""
        try:
            if not self._started:
                self._loop.run(self._fetcher.init())
                self._started = True
            return self._loop.run(request)
        except Exception as e:  # novel-downloader raises whatever its HTTP session raised
            raise FetchError(f"{where}: novel-downloader: {type(e).__name__}: {e}") from e


def _site_book(url: str) -> tuple[str, str]:
    found = site_book(url)
    if found is None:
        raise ValueError(f"{url}: novel-downloader has no plugin for this site, or the URL names no book")
    return found


@cache
def _t2s() -> OpenCC:
    return OpenCC("t2s")


def _simplified(text: str) -> str:
    return _t2s().convert(text)
