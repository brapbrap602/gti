import pytest
from novel_app.pages import SourceLabel, Staleness, source_label
from novel_core import Kind, OutputKind, SourceSpec


def spec(backend: str, url: str) -> SourceSpec:
    return SourceSpec(backend, url, "en", Kind.OFFICIAL_EN)


@pytest.mark.parametrize(("backend", "url", "short"), [
    ("lncrawl", "https://www.novelbin.com/b/x", "novelbin.com"),
    ("noveldl", "http://novelbuddy.me/novel/test", "novelbuddy.me"),
    ("calibre", "file:///C:/a/My%20Longevity", "My Longevity"),
    ("calibre", "file:///C:/a/My%20Longevity/", "My Longevity"),
    ("custom:mine", "mine", "custom:mine"),
])  # fmt: skip
def test_source_label_names_the_site_or_folder(backend, url, short):
    assert source_label(spec(backend, url)) == SourceLabel(short, url)


@pytest.mark.parametrize(("built", "stale", "badge"), [
    (40, 0, ("site ✓", "fresh")),
    (40, 4, ("site 4 stale", "stale")),
    (0, 40, ("site not built", "missing")),
    (0, 0, ("site — nothing to build", "none")),
])  # fmt: skip
def test_output_badges(built, stale, badge):
    assert Staleness(OutputKind.SITE, built, stale).badge == badge
