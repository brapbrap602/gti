"""Reader site behaviour in headless Firefox (local only: `pytest -m browser`)."""

import pytest
from firefox_page import firefox, serve
from novel_core import Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec
from novel_publish.site import build_site

pytestmark = pytest.mark.browser

COLOR_SCHEME = "layout.css.prefers-color-scheme.content-override"  # 0 dark, 1 light
PARAGRAPHS = 12  # per chapter, each several lines on a phone


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """Base URL of a built site: novel "n" with chapters 1-3 (page 1-50) and 51-53 (page 51-100)."""
    root = tmp_path_factory.mktemp("built")
    store = NovelStore.create(root / "data" / "n", NovelMeta("Test Novel"))
    source = store.upsert_source(SourceSpec("custom:a", "https://a.test/novel", "en", Kind.OFFICIAL_EN))
    numbers = [1, 2, 3, 51, 52, 53]
    items = [SourceItem(f"/c{n}", i, f"Chapter {n}: Title {n}") for i, n in enumerate(numbers, start=1)]
    store.record_index(source, items)
    for n, item in zip(numbers, items):
        body = tuple(Paragraph.of(f"Ch{n} p{i}. " + "Words to fill a line on a phone. " * 6) for i in range(PARAGRAPHS))
        store.put_version(source, item.ref, NewVersion(item.title, body))
    build_site({"n": store}, root / "site")
    store.close()
    with serve(root / "site") as base:
        yield base


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    with firefox(tmp_path_factory.mktemp("profile")) as page:
        yield page


@pytest.fixture
def page(browser, site):
    """The shared tab, with storage cleared (a fresh visitor); asserts no page errors at the end."""
    browser.goto(site + "index.html")
    browser.js("localStorage.clear()")
    yield browser
    browser.assert_no_errors()


def settings(page) -> dict:
    return page.js("({theme: document.documentElement.dataset.theme,"
                   " scale: document.documentElement.style.getPropertyValue('--r-scale')})")


def test_harness_phone_window_scroll_and_preload(tmp_path):
    """G1: a phone-sized viewport, evaluate + scrollBy, and the preload runs before page scripts."""
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "index.html").write_text(
        "<!doctype html><meta name=viewport content='width=device-width'>"
        "<script>window.preloaded = Array.isArray(window.__errors)</script>"
        "<div style='height:5000px'></div>",
        encoding="utf-8",
    )
    with serve(tmp_path / "www") as base, firefox(tmp_path / "profile") as page:
        page.goto(base)
        assert page.js("innerWidth") == 390
        assert page.js("window.preloaded") is True
        page.scroll(600)
        assert page.js("scrollY") == 600
        page.assert_no_errors()


@pytest.mark.parametrize(("override", "light"), [(0, False), (1, True)])
def test_harness_forces_color_scheme(tmp_path, override, light):
    """G2: the prefs.js colour-scheme override reaches matchMedia."""
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "index.html").write_text("<!doctype html><p>x", encoding="utf-8")
    with serve(tmp_path / "www") as base, firefox(tmp_path / "profile", prefs={COLOR_SCHEME: override}) as page:
        page.goto(base)
        assert page.js("matchMedia('(prefers-color-scheme: light)').matches") is light


def test_settings_apply_at_once_and_follow_to_the_next_page(page, site):
    page.goto(site + "novels/n/1-50.html")
    assert settings(page) == {"theme": "dark", "scale": "1"}

    page.click('#settings [data-size="1"]')
    page.click('#settings [data-size="1"]')
    page.click('#settings input[value="light"]')
    assert settings(page) == {"theme": "light", "scale": "1.2"}
    assert page.js("document.querySelector('#settings output').textContent") == "120%"

    page.goto(site + "novels/n/51-100.html")
    assert settings(page) == {"theme": "light", "scale": "1.2"}
    page.goto(site + "index.html")
    assert settings(page)["theme"] == "light"


def test_system_theme_follows_the_browser(tmp_path, site):
    with firefox(tmp_path / "profile", prefs={COLOR_SCHEME: 1}) as page:
        page.goto(site + "novels/n/1-50.html")
        assert settings(page)["theme"] == "dark"  # a new visitor gets dark, whatever the browser says

        page.click('#settings input[value="system"]')

        assert settings(page)["theme"] == "light"
        page.goto(site + "novels/n/51-100.html")
        assert settings(page)["theme"] == "light"
        page.assert_no_errors()


def test_settings_work_for_the_visit_when_storage_throws(tmp_path, site):
    with firefox(tmp_path / "profile", throwing_storage=True) as page:
        page.goto(site + "novels/n/1-50.html")
        assert settings(page)["theme"] == "dark"

        page.click('#settings input[value="light"]')
        page.click('#settings [data-size="-1"]')

        assert settings(page) == {"theme": "light", "scale": "0.9"}
        page.assert_no_errors()
