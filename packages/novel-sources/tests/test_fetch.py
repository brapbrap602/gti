import json

import pytest
from novel_core import RawChapter, SourceItem
from novel_sources import fetch
from novel_sources.backends import backend_for, spec_for_url
from novel_sources.clean import normalize
from novel_sources.fetch import FetchError, firefox_scraper
from novel_sources.hangulplanet import HangulPlanetSource
from novel_sources.lncrawl import LncrawlSource
from novel_sources.skydemonorder import SkyDemonOrderSource, free_chapters

PROJECT = "https://skydemonorder.com/projects/38-return"
NOVEL = "https://hangulplanet.com/novel/tunnels"


def test_fetch_error_is_an_os_error_so_one_chapter_never_stops_a_sync():
    assert issubclass(FetchError, OSError)


def test_challenges_need_firefox(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "pick_firefox", lambda: None)
    with pytest.raises(FetchError, match="no Firefox is installed"):
        firefox_scraper(PROJECT, tmp_path)


def test_backend_by_host():
    assert backend_for(f"{PROJECT}/") == "custom:skydemonorder"
    assert backend_for("https://novelbuddy.me/some-novel") == "lncrawl"
    assert spec_for_url(f"{PROJECT}/", "en").url == PROJECT
    assert backend_for(f"{NOVEL}#chapters") == "custom:hangulplanet"
    assert spec_for_url(f"{NOVEL}/#chapters", "en").url == NOVEL
    with pytest.raises(ValueError):
        spec_for_url("https://a.test/n", "en", backend="no-such-backend")


def test_lncrawl_body_is_normalized_with_the_common_rules():
    source = LncrawlSource(LncrawlSource.spec_for("https://novelbuddy.me/n"))
    raw = RawChapter('<div id="lncrawl-body"><p>Translate to</p><p>Chapter 3: Fall</p><p>He fell.</p></div>')
    assert [b.text for b in normalize(raw, source.clean_rules(raw), "Chapter 3: Fall")] == ["He fell."]


# -- skydemonorder ------------------------------------------------------------

FREE = [{"episode": 2, "title": "The Second (2)", "slug": "2-the-second-2"},
        {"episode": 1, "title": "Can't Stop", "slug": "1-cant-stop"}]  # fmt: skip


def component_html(chapters) -> str:
    """The chapter-list component as the site renders it: JSON in a JS string, quotes as \\u0022."""
    js = json.dumps(chapters).replace('"', "\\u0022").replace("'", "\\'")
    return f"<div x-data=\"{{ activeTab: 'free', freeChapters: JSON.parse('{js}') }}\"></div>"


PROJECT_PAGE = f"""<html><head><meta name="csrf-token" content="tok">
<script src="/livewire-ab12/livewire.min.js"></script></head>
<body><h1>Return of the Sect</h1>
<div wire:name="project.chapter-list" wire:snapshot="{{&quot;memo&quot;:1}}"></div></body></html>"""


class Response:
    def __init__(self, text="", status=200, data=None):
        self.text, self.status_code, self._data = text, status, data

    def json(self):
        if self._data is None:
            raise ValueError("not JSON")
        return self._data


class FakeScraper:
    def __init__(self, livewire=None, chapter_status=200):
        self.livewire = livewire if livewire is not None else {"components": [{"effects": {"html": component_html(FREE)}}]}
        self.chapter_status = chapter_status
        self.posts = []

    def get(self, url):
        if url == PROJECT:
            return Response(PROJECT_PAGE)
        return Response(f'<div id="chapter-body"><p>Text at {url}.</p></div>', self.chapter_status)

    def post(self, url, json=None, headers=None):
        self.posts.append((url, json, headers))
        return Response(data=self.livewire)


def test_skydemonorder_index_comes_from_the_livewire_chapter_list():
    scraper = FakeScraper()
    index = SkyDemonOrderSource(SkyDemonOrderSource.spec_for(PROJECT), scraper).fetch_index()
    assert index.meta.title == "Return of the Sect"
    assert [(i.ref, i.number, i.title) for i in index.items] == [
        ("/projects/38-return/1-cant-stop", 1, "Can't Stop"),
        ("/projects/38-return/2-the-second-2", 2, "The Second (2)"),
    ]
    url, payload, headers = scraper.posts[0]
    assert url == "https://skydemonorder.com/livewire-ab12/update"
    assert payload == {"_token": "tok", "components": [{"snapshot": '{"memo":1}', "updates": {}, "calls": []}]}
    assert headers["X-CSRF-TOKEN"] == "tok"


def test_skydemonorder_chapter_and_its_failures():
    source = SkyDemonOrderSource(SkyDemonOrderSource.spec_for(PROJECT), FakeScraper())
    raw = source.fetch_chapter(SourceItem("/projects/38-return/1-cant-stop", 1, "Can't Stop"))
    assert [b.text for b in normalize(raw, source.clean_rules(raw))] == [f"Text at {PROJECT}/1-cant-stop."]

    locked = SkyDemonOrderSource(SkyDemonOrderSource.spec_for(PROJECT), FakeScraper(chapter_status=404))
    with pytest.raises(FetchError, match="HTTP 404"):
        locked.fetch_chapter(SourceItem("/projects/38-return/9-x", 9, "X"))
    broken = SkyDemonOrderSource(SkyDemonOrderSource.spec_for(PROJECT), FakeScraper(livewire={"components": []}))
    with pytest.raises(FetchError, match="unexpected Livewire answer"):
        broken.fetch_index()


def test_free_chapters_needs_the_list():
    with pytest.raises(FetchError, match="no free chapter list"):
        free_chapters(PROJECT, "<div x-data=\"{ activeTab: 'free' }\"></div>")


# -- hangulplanet --------------------------------------------------------------

NOVEL_PAGE = """<html><head><meta property="og:title" content="Tunnels "/></head><body>
<a href="/novel/tunnels#chapters">Chapters</a><a href="/novel/tunnels/chapter-1">Start reading</a>
<a href="/novel/tunnels/chapter-4">4</a><a href="/novel/tunnels/chapter-3">3</a>
<a href="/novel/other/chapter-9">elsewhere</a></body></html>"""


def sitemap(*locs):
    return "<urlset>" + "".join(f"<url><loc>{loc}</loc></url>" for loc in locs) + "</urlset>"


class HangulPlanetScraper:
    """The site: a novel page linking its newest chapters, a sitemap index, two chapter sitemaps."""

    def __init__(self, index=None, chapter_status=200):
        self.pages = {
            NOVEL: NOVEL_PAGE,
            "https://hangulplanet.com/content/sitemap.xml": index or sitemap(
                "https://hangulplanet.com/content/sitemap/novels-0.xml",
                "https://hangulplanet.com/content/sitemap/chapters-0.xml",
                "https://hangulplanet.com/content/sitemap/chapters-1.xml"),
            "https://hangulplanet.com/content/sitemap/chapters-0.xml": sitemap(
                f"{NOVEL}/chapter-1", f"{NOVEL}/chapter-2", "https://hangulplanet.com/novel/tunnels-two/chapter-5"),
            "https://hangulplanet.com/content/sitemap/chapters-1.xml": sitemap(f"{NOVEL}/chapter-3"),
        }
        self.chapter_status = chapter_status
        self.gets = []

    def get(self, url):
        self.gets.append(url)
        if url in self.pages:
            return Response(self.pages[url])
        return Response(f'<div class="reader-prose"><p>Text at {url}.</p></div>', self.chapter_status)


def test_hangulplanet_index_joins_the_chapter_sitemaps_and_the_novel_page():
    scraper = HangulPlanetScraper()
    index = HangulPlanetSource(HangulPlanetSource.spec_for(NOVEL), scraper).fetch_index()
    assert index.meta.title == "Tunnels"
    assert [(i.ref, i.position, i.number, i.title) for i in index.items] == [
        (f"/novel/tunnels/chapter-{n}", n, n, f"Chapter {n}") for n in (1, 2, 3, 4)
    ]
    assert "https://hangulplanet.com/content/sitemap/novels-0.xml" not in scraper.gets


def test_hangulplanet_chapter_and_its_failures():
    source = HangulPlanetSource(HangulPlanetSource.spec_for(NOVEL), HangulPlanetScraper())
    raw = source.fetch_chapter(SourceItem("/novel/tunnels/chapter-2", 2, "Chapter 2", number=2))
    assert [b.text for b in normalize(raw, source.clean_rules(raw))] == [f"Text at {NOVEL}/chapter-2."]

    gone = HangulPlanetSource(HangulPlanetSource.spec_for(NOVEL), HangulPlanetScraper(chapter_status=404))
    with pytest.raises(FetchError, match="HTTP 404"):
        gone.fetch_chapter(SourceItem("/novel/tunnels/chapter-9", 9, "Chapter 9", number=9))
    no_sitemap = HangulPlanetSource(HangulPlanetSource.spec_for(NOVEL), HangulPlanetScraper(index=sitemap()))
    with pytest.raises(FetchError, match="no chapter sitemap"):
        no_sitemap.fetch_index()
