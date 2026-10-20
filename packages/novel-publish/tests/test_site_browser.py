"""Reader site behaviour in headless Firefox (local only: `pytest -m browser`)."""

import pytest
from firefox_page import firefox, serve

pytestmark = pytest.mark.browser

COLOR_SCHEME = "layout.css.prefers-color-scheme.content-override"  # 0 dark, 1 light


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
