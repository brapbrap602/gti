import pytest
from bs4 import BeautifulSoup
from novel_core import SourceItem
from novel_sources import backends, decode_guide
from novel_sources.backends import backend_for, spec_for_url
from novel_sources.clean import normalize
from novel_sources.decode_guide import DecodeGuideSource, select
from novel_sources.fetch import FetchError


class Response:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status


class FakeScraper:
    """A site of canned pages by URL; any other URL is a 404."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.gets: list[str] = []

    def get(self, url):
        self.gets.append(url)
        return Response(self.pages[url]) if url in self.pages else Response("", 404)


def test_rules_select_by_selector_alternatives_or_by_parts():
    soup = BeautifulSoup('<div class="a"><p id="x" data-k="1">One</p><p>Two</p><a href="/c/1">C1</a></div>', "lxml")
    assert [p.text for p in select(soup, {"selector": "div.missing p XOR div.a p", "array": True})] == ["One", "Two"]
    assert [p.text for p in select(soup, {"element": "p", "id": "x", "attributes": {"data-k": "1"}})] == ["One"]
    assert select(soup, {"element": "p", "array": False})[0].text == "One"
    assert select(soup, {"element": "a", "array": True, "extract": {"type": "attr", "key": "href"}}) == ["/c/1"]
    assert select(soup, {"element": "div", "class": "a", "extract": {"type": "text", "key": "text"}}) == ["One Two C1"]
    assert select(soup, {"element": "table", "array": True}) == []


# -- novellive.net: a paginated table of contents -------------------------------

NOVEL = "https://novellive.net/book/long-road"


def toc_page(chapters, next_href=None) -> str:
    links = "".join(f'<li><a href="/book/long-road/chapter-{n}">Chapter {n}: Step {n}</a></li>' for n in chapters)
    pager = f'<a class="index-container-btn" href="{next_href}">next</a><a class="index-container-btn" href="#">last</a>' if next_href else ""
    return f'<h1>The Long Road</h1><div class="m-newest2"><ul>{links}</ul></div><div class="page">{pager}</div>'


def test_paginated_index_follows_next_page_and_titles_items_by_link_text():
    second = "https://novellive.net/book/long-road/2"
    scraper = FakeScraper({NOVEL: toc_page([1, 2], next_href=second), second: toc_page([2, 3])})
    index = DecodeGuideSource(spec_for_url(NOVEL, "en", backend="decode-guide"), scraper).fetch_index()
    assert index.meta.title == "The Long Road"
    assert [(i.ref, i.position, i.title) for i in index.items] == [
        ("/book/long-road/chapter-1", 1, "Chapter 1: Step 1"),
        ("/book/long-road/chapter-2", 2, "Chapter 2: Step 2"),  # listed on both pages, kept once
        ("/book/long-road/chapter-3", 3, "Chapter 3: Step 3"),
    ]
    assert scraper.gets == [NOVEL, second]


def test_chapter_body_comes_from_the_content_rule_and_is_cleaned():
    url = f"{NOVEL}/chapter-1"
    page = "<h4>Chapter 1: Step 1</h4><p>Chapter 1: Step 1</p><p>He walked.</p><p>Read at novellive.net</p>"
    source = DecodeGuideSource(spec_for_url(NOVEL, "en", backend="decode-guide"), FakeScraper({url: page}))
    item = SourceItem("/book/long-road/chapter-1", 1, "Chapter 1: Step 1")
    raw = source.fetch_chapter(item)
    assert raw.final_url == url
    assert [b.text for b in normalize(raw, source.clean_rules(raw), item.title)][:1] == ["He walked."]


def test_failures_are_fetch_errors():
    source = DecodeGuideSource(spec_for_url(NOVEL, "en", backend="decode-guide"), FakeScraper({NOVEL: "<p>no list</p>"}))
    with pytest.raises(FetchError, match="matched no chapter links"):
        source.fetch_index()
    with pytest.raises(FetchError, match="HTTP 404"):
        source.fetch_chapter(SourceItem("/book/long-road/chapter-9", 9, "Chapter 9"))


# -- novelbin: a custom processor for the TOC address, links extracted by attribute ----


def test_novelbin_index_uses_its_toc_processor_and_keeps_link_titles():
    archive = "https://novelbin.me/ajax/chapter-archive?novelId=golden-core"
    links = '<ul class="list-chapter"><li><a href="https://novelbin.me/b/golden-core/chapter-1" title="Chapter 1 Start"></a></li></ul>'
    scraper = FakeScraper({archive: links})
    spec = spec_for_url("https://novelbin.me/novel-book/golden-core", "en", backend="decode-guide")
    index = DecodeGuideSource(spec, scraper).fetch_index()
    assert scraper.gets == [archive]
    assert [(i.ref, i.title) for i in index.items] == [("/b/golden-core/chapter-1", "Chapter 1 Start")]


def test_backend_choice_for_guide_hosts(monkeypatch):
    monkeypatch.setattr(backends.lncrawl, "supports", lambda url: "novelbin" not in url)  # lncrawl lists novelbin as down
    assert backend_for("https://novelbin.me/novel-book/golden-core") == "decode-guide"
    assert backend_for("https://www.royalroad.com/fiction/1") == "lncrawl"  # in the guide, but lncrawl reads it
    assert backend_for("https://unknown.test/novel") == "lncrawl"  # no guide: lncrawl's generic crawler
    with pytest.raises(ValueError, match="no decode guide"):
        spec_for_url("https://unknown.test/novel", "en", backend="decode-guide")


def test_the_guide_comes_from_the_installed_web_novel_scraper():
    assert {"novelbin.me", "novellive.net", "genesistudio.com"} <= set(decode_guide.guides())
    assert decode_guide.guide_for("https://www.novelbin.me/b/x")["host"] == "novelbin.me"
