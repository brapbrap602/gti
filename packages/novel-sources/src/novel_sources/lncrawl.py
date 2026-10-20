"""lncrawl backend: lightnovel-crawler's per-site crawlers, used in-process as a library.

Only its crawler classes are used: `read_novel` lists the chapters, `download_chapter`
fetches one body, already cut out of the page. lncrawl's own database, binder and
server are never touched. Its crawlers are refreshed from lncrawl's online index at
startup, so a fixed site layout reaches us without a new release. Item refs are the
chapter URL paths, like every web backend.
"""

import threading
from datetime import UTC, datetime

from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec, url_ref

from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.hosts import COMMON, numbered_urls
from novel_sources.importing import NovelIndex

BACKEND = "lncrawl"
_BODY = "lncrawl-body"  # id of the div a fetched body is stored in, so normalize can find it
_setup_lock = threading.Lock()
_ready = False


def _context():
    """lncrawl's process-wide context, set up once: logging, config and the crawler index.

    Challenges are solved in Firefox only (lncrawl would fall back to Chromium); this is
    saved in lncrawl's own config file.
    """
    global _ready
    from lncrawl.context import ctx

    with _setup_lock:
        if not _ready:
            ctx.logger.setup(None)
            ctx.config.load(None)
            if ctx.config.crawler.browser_driver != "firefox":
                ctx.config.crawler.browser_driver = "firefox"
            ctx.sources.load(True)
            _ready = True
    return ctx


def supports(url: str) -> bool:
    """Whether lncrawl has a crawler for this host that it does not list as rejected (site down)."""
    sources = _context().sources
    try:
        sources.find_crawler(url)
    except Exception:  # lncrawl's ServerError: no crawler, or the host is rejected
        return False
    return True


class LncrawlSource:
    def __init__(self, spec: SourceSpec):
        self._spec = spec
        self._crawler = None
        self._urls: dict[str, str] = {}  # item ref -> chapter URL, from the last index

    @staticmethod
    def spec_for(url: str, lang: str = "en") -> SourceSpec:
        return SourceSpec(BACKEND, url, lang, Kind.RAW_ZH if lang == "zh" else Kind.OFFICIAL_EN)

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def fetch_index(self) -> NovelIndex:
        from lncrawl.core import Novel

        novel = Novel(url=self._spec.url)
        try:
            crawler = self._open()
            crawler.read_novel(novel)
            crawler.format_novel(novel)
        except FetchError:
            raise
        except Exception as e:  # lncrawl raises whatever its crawler or HTTP stack raised
            raise FetchError(f"{self._spec.url}: lncrawl index failed: {type(e).__name__}: {e}") from e
        items = []
        for chapter in novel.chapters:
            ref = url_ref(chapter.url)
            self._urls[ref] = chapter.url
            items.append(SourceItem(ref, chapter.id, chapter.title, ref_numbered=numbered_urls(chapter.url)))
        return NovelIndex(
            meta=NovelMeta(
                title=novel.title,
                author=novel.author or None,
                language=novel.language or self._spec.lang,
                tags=tuple(novel.tags or ()),
            ),
            items=tuple(items),
        )

    def fetch_chapter(self, item: SourceItem) -> RawChapter:
        from lncrawl.core import Chapter

        url = self._urls.get(item.ref)
        if url is None:
            raise FetchError(f"{item.ref}: not in the index fetched this run")
        chapter = Chapter(id=item.position, url=url, title=item.title)
        try:
            crawler = self._open()
            crawler.download_chapter(chapter)
            crawler.format_chapter(chapter)
        except Exception as e:
            raise FetchError(f"{url}: lncrawl: {type(e).__name__}: {e}") from e
        if not chapter.success:
            raise FetchError(f"{url}: lncrawl returned an empty chapter body")
        html = f'<div id="{_BODY}">{chapter.body}</div>'
        return RawChapter(html, "html", final_url=url, fetched_at=datetime.now(UTC))

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return COMMON | CleanRules(content=(f"div#{_BODY}",))

    def close(self) -> None:
        if self._crawler is not None:
            self._crawler.close()
            self._crawler = None

    def _open(self):
        if self._crawler is None:
            self._crawler = _context().sources.init_crawler(self._spec.url)
        return self._crawler
