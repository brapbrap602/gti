"""Reader site behaviour in headless Firefox (local only: `pytest -m browser`)."""

import json
import time

import pytest
from firefox_page import firefox, serve
from novel_core import Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec
from novel_publish.site import build_site

pytestmark = pytest.mark.browser

COLOR_SCHEME = "layout.css.prefers-color-scheme.content-override"  # 0 dark, 1 light
PARAGRAPHS = 12  # per chapter, each several lines on a phone


def _novel(root, slug: str, title: str, titles: list[str], paragraphs: int, kind: Kind = Kind.OFFICIAL_EN) -> NovelStore:
    store = NovelStore.create(root / "data" / slug, NovelMeta(title))
    source = store.upsert_source(SourceSpec("custom:a", "https://a.test/novel", "en", kind))
    items = [SourceItem(f"/c{i}", i, t) for i, t in enumerate(titles, start=1)]
    store.record_index(source, items)
    for item in items:
        n = item.title.split()[1].rstrip(":") if " " in item.title else item.number
        body = tuple(Paragraph.of(f"Ch{n} p{i}. " + "Words to fill a line on a phone. " * 6) for i in range(paragraphs))
        store.put_version(source, item.ref, NewVersion(item.title, body))
    return store


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """Base URL of a built site with three novels:
    "n" (Test Novel): chapters 1-3 (page 1-50) and 51-53 (page 51-100);
    "z-first" (Alpha Tale, so title order differs from slug order): one page, chapters 1-49, 50 pt 1, 50 pt 2;
    "raw": a raw-zh source only."""
    root = tmp_path_factory.mktemp("built")
    stores = {
        "n": _novel(root, "n", "Test Novel", [f"Chapter {n}: Title {n}" for n in (1, 2, 3, 51, 52, 53)], PARAGRAPHS),
        "z-first": _novel(root, "z-first", "Alpha Tale",
                          [f"Chapter {n}" for n in range(1, 50)] + ["Chapter 50 (part 1)", "Chapter 50 (part 2)"], 3),
        "raw": _novel(root, "raw", "修真聊天群", ["第1章"], 3, Kind.RAW_ZH),
    }
    build_site(stores, root / "site")
    for store in stores.values():
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


@pytest.fixture(scope="module")
def desktop_browser(tmp_path_factory):
    with firefox(tmp_path_factory.mktemp("desktop-profile"), size=(1280, 900)) as page:
        yield page


@pytest.fixture
def desktop(desktop_browser, site):
    """A desktop-sized tab (1280x900), storage cleared; asserts no page errors at the end."""
    desktop_browser.goto(site + "index.html")
    desktop_browser.js("localStorage.clear()")
    yield desktop_browser
    desktop_browser.assert_no_errors()


def seed(page, key: str, value) -> None:
    """Store value (JSON-encoded) under key in the open page's localStorage."""
    page.js(f"localStorage.setItem({json.dumps(key)}, {json.dumps(json.dumps(value))})")


def bar(page) -> dict:
    return page.js("""(() => { const b = document.querySelector('.reader-bar');
        return {shown: !b.hidden && b.classList.contains('reader-bar--shown'),
                title: b.querySelector('.bar-title').textContent,
                prev: b.querySelector('.bar-prev').getAttribute('href'),
                next: b.querySelector('.bar-next').getAttribute('href')}; })()""")


def scroll_into(page, anchor: str, extra: float = 0) -> None:
    """Step-scroll until the article's top is just under the bar, plus extra pixels."""
    page.scroll(page.js(f"document.getElementById('{anchor}').getBoundingClientRect().top"
                        " - document.querySelector('.reader-bar').offsetHeight") + extra)


def continue_link(page, slug: str = "n") -> dict | None:
    """Test Novel's entry in the Continue row: {ch: "Ch N", href}, or None when it has none or the row is hidden."""
    return page.js(f"""(() => {{ const row = document.querySelector('.continue-row');
        const a = document.querySelector('.continue-list li[data-slug="{slug}"] a');
        return row.hidden || !a ? null : {{ch: a.querySelector('.continue-ch').textContent, href: a.getAttribute('href')}}; }})()""")


def continue_entries(page) -> list[dict]:
    """The Continue row's entries in order: {title, ch, time}; [] when the row is hidden."""
    return page.js("""document.querySelector('.continue-row').hidden ? [] :
        [...document.querySelectorAll('.continue-list li')].map(li => ({
            title: li.querySelector('.continue-title').textContent,
            ch: li.querySelector('.continue-ch').textContent,
            time: li.querySelector('.continue-time') ? li.querySelector('.continue-time').textContent : null}))""")


def place(file: str = "1-50.html", anchor: str = "c2", para: int = 3, label: str = "2", age: float | None = None) -> dict:
    """A saved place, `age` seconds old (the browser shares this machine's clock); no `t` when age is None."""
    t = {} if age is None else {"t": int((time.time() - age) * 1000)}
    return {"file": file, "anchor": anchor, "para": para, "label": label, **t}


def seed_places(page, site, places: dict) -> None:
    """Open the library with these saved places (slug -> place()) and nothing else saved."""
    page.goto(site + "index.html")
    page.js("localStorage.clear()")
    for slug, pos in places.items():
        seed(page, f"reader:pos:{slug}", pos)
    page.goto(site + "index.html")


def focused(page) -> str:
    return page.js("(() => { const e = document.activeElement; return e.id || e.className || e.tagName; })()")


HOUR, DAY = 3600, 86400


def save_position(page, site, file: str, anchor: str, para: int, label: str) -> None:
    page.goto(site + "index.html")
    seed(page, "reader:pos:n", {"file": file, "anchor": anchor, "para": para, "label": label, "t": 1})


def open_first_page(page) -> None:
    """From the library, follow Test Novel's link to its first page (Chs 1-3)."""
    page.navigate_by("""document.querySelector('.novel-row[data-slug="n"] .book-parts a').click()""")


def back_to_library(page) -> None:
    page.navigate_by("history.back()")
    page.frame()


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
        scroll_into(page, "c2", 50)
        assert bar(page)["title"] == "Ch 2: Title 2"
        page.goto(site + "index.html")
        assert continue_link(page) is None
        page.assert_no_errors()


def test_bar_reveals_on_scroll_up_and_hides_on_scroll_down(page, site):
    page.goto(site + "novels/n/1-50.html")
    assert bar(page)["shown"]  # at the top

    page.scroll(600)
    assert not bar(page)["shown"]
    page.scroll(-50)
    assert bar(page)["shown"]
    page.scroll(-page.js("scrollY"))
    assert bar(page)["shown"]

    page.click(".bar-next")
    page.frame()
    assert bar(page)["shown"]  # a jump from the bar leaves it up
    page.scroll(300)
    assert not bar(page)["shown"]


def test_bar_follows_the_current_chapter(page, site):
    page.goto(site + "novels/n/1-50.html")
    assert bar(page) | {"shown": True} == {"shown": True, "title": "Ch 1: Title 1", "prev": None, "next": "#c2"}

    scroll_into(page, "c2", 100)

    assert bar(page)["title"] == "Ch 2: Title 2"
    assert bar(page)["prev"] == "#c1" and bar(page)["next"] == "#c3"
    assert page.js("[...document.querySelectorAll('#chapters [aria-current]')].map(a => a.getAttribute('href'))") == ["#c2"]


def test_next_from_a_pages_last_chapter_opens_the_next_page(page, site):
    page.goto(site + "novels/n/1-50.html")
    page.js("scrollTo(0, document.documentElement.scrollHeight)")
    page.frame()
    assert bar(page)["title"] == "Ch 3: Title 3" and bar(page)["next"] == "51-100.html"

    page.navigate_by("document.querySelector('.bar-next').click()")

    assert page.js("location.pathname").endswith("/51-100.html")
    assert page.js("scrollY") == 0 and bar(page)["title"] == "Ch 51: Title 51"


def test_prev_from_a_pages_first_chapter_opens_the_previous_pages_last(page, site):
    page.goto(site + "novels/n/51-100.html")
    assert bar(page)["prev"] == "1-50.html#last"

    page.navigate_by("document.querySelector('.bar-prev').click()")
    page.frame()
    assert bar(page)["title"] == "Ch 3: Title 3"

    page.click(".bar-prev")
    page.frame()
    assert bar(page)["title"] == "Ch 2: Title 2"


def test_novel_ends_disable_the_arrows(page, site):
    page.goto(site + "novels/n/51-100.html")
    page.js("scrollTo(0, document.documentElement.scrollHeight)")
    page.frame()

    assert bar(page)["next"] is None
    assert page.js("document.querySelector('.bar-next').getAttribute('aria-disabled')") == "true"


def goto(page, text: str) -> None:
    """Submit the chapters sheet's go-to form; goto_status then waits for the new answer."""
    page.js("document.querySelector('#chapters .goto [role=status]').textContent = ''")
    page.js(f"document.querySelector('#chapters .goto input').value = {text!r}")
    page.js("document.querySelector('#chapters .goto').requestSubmit()")


def goto_status(page) -> str:
    return page.wait_for("document.querySelector('#chapters .goto [role=status]').textContent")


def test_go_to_chapter(page, site):
    page.goto(site + "novels/n/1-50.html")
    page.click('[data-open="chapters"]')

    goto(page, "abc")
    assert goto_status(page) == "Enter a chapter number."
    goto(page, "40")
    assert goto_status(page) == "Chapter 40 isn't on the site. Nearest: 3 or 51."
    goto(page, "60")
    assert goto_status(page) == "Chapter 60 isn't on the site. Nearest: 53."

    page.navigate_by("(document.querySelector('#chapters .goto input').value = '52',"
                     " document.querySelector('#chapters .goto').requestSubmit())")
    assert page.js("location.pathname + location.hash").endswith("/51-100.html#c52")
    page.frame()
    assert bar(page)["title"] == "Ch 52: Title 52"


def test_continue_reopens_the_paragraph_last_read(page, site):
    page.goto(site + "novels/n/1-50.html")
    assert page.js("innerHeight") * 1.5 < page.js("document.getElementById('c2').getBoundingClientRect().top")

    scroll_into(page, "c2")
    page.scroll(page.js("document.querySelectorAll('#c2 p')[7].getBoundingClientRect().top")
                - page.js("document.querySelector('.reader-bar').offsetHeight") + 5)
    page.goto(site + "index.html")

    assert continue_link(page) == {"ch": "Ch 2", "href": "novels/n/1-50.html?p=7#c2"}
    page.navigate_by("""document.querySelector('.continue-list li[data-slug="n"] a').click()""")
    page.frame()
    top = page.js("document.querySelectorAll('#c2 p')[7].getBoundingClientRect().top")
    assert abs(top - page.js("document.querySelector('.reader-bar').offsetHeight")) <= 2
    assert page.js("location.search") == "" and page.js("location.hash") == "#c2"


def test_opening_a_range_starts_at_its_top(page, site):
    save_position(page, site, "1-50.html", "c2", 7, "2")
    page.goto(site + "index.html")

    open_first_page(page)

    assert page.js("scrollY") == 0


def test_a_quick_look_keeps_the_saved_place(page, site):
    save_position(page, site, "51-100.html", "c52", 7, "52")
    open_first_page(page)

    page.scroll(page.js("innerHeight") * 0.5)
    back_to_library(page)

    assert continue_link(page)["ch"] == "Ch 52"


def test_reading_on_in_another_range_moves_the_saved_place(page, site):
    save_position(page, site, "51-100.html", "c52", 7, "52")
    open_first_page(page)

    page.scroll(page.js("innerHeight") * 3)
    back_to_library(page)

    assert continue_link(page)["href"].startswith("novels/n/1-50.html?p=")


def test_jumps_alone_keep_the_saved_place(page, site):
    save_position(page, site, "51-100.html", "c52", 7, "52")
    open_first_page(page)

    page.click('[data-open="chapters"]')
    goto(page, "3")
    page.wait_for("location.hash === '#c3'")
    page.goto(site + "index.html")

    assert continue_link(page)["ch"] == "Ch 52"


def test_scroll_restored_on_reload_is_not_reading(page, site):
    save_position(page, site, "51-100.html", "c52", 7, "52")
    open_first_page(page)

    page.scroll(page.js("innerHeight"))
    page.navigate_by("location.reload()")
    page.frame()
    assert page.js("scrollY") > 0  # the browser put us back
    page.goto(site + "index.html")

    assert continue_link(page)["ch"] == "Ch 52"


# -- library: Continue row ------------------------------------------------------


def test_a_new_visitor_sees_only_the_list(page, site):
    page.goto(site + "index.html")  # the fixture cleared storage after this page had rendered
    assert page.js("document.querySelector('.continue-row').hidden") is True
    assert page.js("[...document.querySelectorAll('.row-title')].map(e => e.textContent)") == ["Alpha Tale", "Test Novel"]


def test_continue_lists_saved_places_most_recent_first(page, site):
    seed_places(page, site, {
        "z-first": place("1-50.html", "c40", 1, "40", age=2 * DAY),
        "n": place("51-100.html", "c52", 3, "52", age=HOUR),
        "gone": place(age=60),  # not on the site
    })

    assert continue_entries(page) == [
        {"title": "Test Novel", "ch": "Ch 52", "time": "1 hour ago"},
        {"title": "Alpha Tale", "ch": "Ch 40", "time": "2 days ago"},
    ]
    assert continue_link(page)["href"] == "novels/n/51-100.html?p=3#c52"

    seed_places(page, site, {"n": place("9001-9050.html", "c9001", 0, "9001", age=60),
                             "z-first": place(age=HOUR)})  # n's page is gone from the site
    assert [e["title"] for e in continue_entries(page)] == ["Alpha Tale"]


def test_continue_times(page, site):
    seed_places(page, site, {"n": place(age=20), "z-first": place()})
    assert [e["time"] for e in continue_entries(page)] == ["just now", None]

    seed_places(page, site, {"n": place(age=2 * 365 * DAY)})
    assert [e["time"] for e in continue_entries(page)] == [None]


def forget(page, slug: str = "n") -> None:
    page.click(f'.continue-list li[data-slug="{slug}"] button')


def undo_text(page) -> str:
    return page.js("document.querySelector('.continue-undo').textContent")


def saved(page, slug: str = "n"):
    return page.js(f"localStorage.getItem('reader:pos:{slug}')")


def two_places(page, site) -> str:
    seed_places(page, site, {"n": place(age=HOUR), "z-first": place(age=2 * DAY)})
    return saved(page)


def test_forget_then_undo(page, site):
    before = two_places(page, site)

    forget(page)

    assert saved(page) is None and [e["title"] for e in continue_entries(page)] == ["Alpha Tale"]
    assert undo_text(page) == "Forgot your place in Test Novel. Undo"
    assert focused(page) == "continue-undo-button"

    page.click(".continue-undo button")

    assert saved(page) == before
    assert [e["title"] for e in continue_entries(page)] == ["Test Novel", "Alpha Tale"]
    assert undo_text(page) == ""
    assert page.js("document.activeElement === document.querySelector('.continue-list li[data-slug=\"n\"] a')")


def test_a_forgotten_place_stays_forgotten(page, site):
    two_places(page, site)
    forget(page)

    page.wait_for("document.querySelector('.continue-undo').textContent === ''", timeout=10)

    assert saved(page) is None
    assert page.js("document.activeElement === document.querySelector('.continue-list a')")


def test_leaving_the_page_ends_the_undo(page, site):
    two_places(page, site)
    forget(page)

    open_first_page(page)
    back_to_library(page)

    assert saved(page) is None and undo_text(page) == ""
    assert [e["title"] for e in continue_entries(page)] == ["Alpha Tale"]


def test_undo_keeps_a_newer_place(page, site):
    two_places(page, site)
    forget(page)
    newer = json.dumps(place("51-100.html", "c53", 0, "53", age=0))
    page.js(f"localStorage.setItem('reader:pos:n', {json.dumps(newer)})")  # another tab read on

    page.click(".continue-undo button")

    assert saved(page) == newer


def test_forgetting_the_last_place_keeps_undo(page, site):
    seed_places(page, site, {"n": place(age=HOUR)})

    forget(page)

    assert page.js("document.querySelector('.continue-row').hidden") is True
    assert undo_text(page).startswith("Forgot your place in Test Novel.")
    assert focused(page) == "continue-undo-button"
    page.click(".continue-undo button")
    assert saved(page) is not None and [e["title"] for e in continue_entries(page)] == ["Test Novel"]


def test_a_row_opens_to_go_to_and_its_pages(page, site):
    page.click('.novel-row[data-slug="n"] summary')
    assert page.js("""document.querySelector('.novel-row[data-slug="n"] .goto').getBoundingClientRect().height""") > 0

    page.js("""document.querySelector('.novel-row[data-slug="n"] .goto input').value = '2'""")
    page.navigate_by("""document.querySelector('.novel-row[data-slug="n"] .goto').requestSubmit()""")

    assert page.js("location.pathname + location.hash").endswith("/novels/n/1-50.html#c2")


def test_storage_off_hides_the_continue_row(tmp_path, site):
    with firefox(tmp_path / "profile", throwing_storage=True) as page:
        page.goto(site + "index.html")
        assert page.js("document.querySelector('.continue-row').hidden") is True
        page.assert_no_errors()
