import pytest
from novel_core import Kind, SourceItem
from novel_downloader.schemas import ParserConfig
from novel_sources.backends import backend_for, spec_for_url
from novel_sources.clean import normalize
from novel_sources.fetch import FetchError
from novel_sources.noveldl import NovelDownloaderSource
from novel_sources.noveldl_sites import Biquges123Parser

BOOK = "https://www.biquges123.com/50537/"

NOVEL_PAGE = """<html><body><div class="info">
<div class="info_lt"><img src="https://cdn.test/50537.jpg"></div>
<h1 class="info_title">我的模擬長生路</h1>
<div class="info_ct"><div>状态：完结</div><div>作者：愤怒的乌贼</div><div>最后更新：<time>2025-09-11</time></div></div>
<div class="des"><span>简介：</span>仙道何其难</div></div>
<div class="list"><h2>章节列表</h2><ul>
<li><a href="/50537/1" title="第1章 仙从何处来">第1章 仙从何处来</a></li>
<li><a href="/50537/2" title="第一千零六十章 長生">第一千零六十章 長生</a></li>
<li><a href="/50537/3" title="完本感言">完本感言</a></li>
</ul></div></body></html>"""


def chapter_page(text: str) -> str:
    return f'<html><body><div class="text"><h1>第1章 仙从何处来</h1></div><article class="article">{text}</article></body></html>'


class FakeFetcher:
    """novel-downloader's async fetcher for a site, serving canned pages."""

    def __init__(self, chapters: dict[str, str], fail: str | None = None):
        self.chapters = chapters
        self.fail = fail
        self.calls: list[str] = []

    async def init(self):
        self.calls.append("init")

    async def close(self):
        self.calls.append("close")

    async def fetch_book_info(self, book_id):
        assert book_id == "50537"
        return [NOVEL_PAGE]

    async def fetch_chapter_content(self, book_id, chapter_id):
        if chapter_id == self.fail:
            raise TimeoutError("read timed out")
        return [chapter_page(self.chapters.get(chapter_id, ""))]


def source(fetcher) -> NovelDownloaderSource:
    parser = Biquges123Parser(ParserConfig())
    return NovelDownloaderSource(NovelDownloaderSource.spec_for(BOOK), fetcher, parser)


def test_chinese_raw_sites_go_to_novel_downloader():
    assert backend_for(BOOK) == "novel-downloader"
    assert backend_for("https://www.biquge5.com/12_345/") == "novel-downloader"  # one of its own plugins
    assert backend_for("https://novelbuddy.me/some-novel") == "lncrawl"
    spec = spec_for_url(BOOK, "en")  # a raw site's text is Chinese whatever --lang says
    assert (spec.backend, spec.lang, spec.kind) == ("novel-downloader", "zh", Kind.RAW_ZH)
    with pytest.raises(ValueError, match="no plugin"):
        spec_for_url("https://a.test/n", "zh", backend="novel-downloader")


def test_index_lists_url_paths_with_simplified_titles_numbered_by_title():
    index = source(FakeFetcher({})).fetch_index()
    assert index.meta.title == "我的模拟长生路"
    assert (index.meta.author, index.meta.language) == ("愤怒的乌贼", "zh")
    assert [(i.ref, i.title, i.ref_numbered) for i in index.items] == [
        ("/50537/1", "第1章 仙从何处来", False),
        ("/50537/2", "第一千零六十章 长生", False),
        ("/50537/3", "完本感言", False),
    ]


def test_chapter_text_is_simplified_and_closes_the_fetcher():
    fetcher = FakeFetcher({"1": "<p>第1章 仙从何处来</p><p>萬古長青。</p><p>仙人一劍！</p>"})
    site = source(fetcher)
    item = site.fetch_index().items[0]
    raw = site.fetch_chapter(item)
    assert (raw.content_type, raw.final_url) == ("text", "https://www.biquges123.com/50537/1")
    assert [b.text for b in normalize(raw, site.clean_rules(raw), item.title)] == ["万古长青。", "仙人一剑！"]
    site.close()
    assert fetcher.calls == ["init", "close"]


def test_chapter_failures_are_fetch_errors():
    site = source(FakeFetcher({}, fail="2"))
    with pytest.raises(FetchError, match="not in the index"):
        site.fetch_chapter(SourceItem("/50537/1", 1, "第1章"))
    items = site.fetch_index().items
    with pytest.raises(FetchError, match="TimeoutError"):
        site.fetch_chapter(items[1])
    with pytest.raises(FetchError, match="empty chapter"):
        site.fetch_chapter(items[2])
    site.close()
