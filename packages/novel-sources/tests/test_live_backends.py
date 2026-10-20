"""Gates G1 (lncrawl in-process), G3 (novel-downloader) and G8 (fetch ladder) against the real sites: `pytest -m live`."""

import os
from pathlib import Path

import pytest
from novel_sources.backends import open_source, spec_for_url
from novel_sources.clean import normalize

pytestmark = pytest.mark.live


@pytest.mark.parametrize(
    "url",
    ["https://novelbuddy.me/surviving-the-game-as-a-barbarian", "https://skydemonorder.com/projects/3801994495-return-of-the-mount-hua-sect",
     "https://www.biquges123.com/50537/"],
    ids=["lncrawl-novelbuddy", "skydemonorder-firefox", "noveldl-biquges123"],
)  # fmt: skip
def test_index_and_last_chapter(url):
    data = os.environ.get("NOVELS_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "novels"
    state = Path(data) / "_fetch"  # the library's own, so a clearance earned there is reused
    with open_source(spec_for_url(url, "en"), state) as source:
        index = source.fetch_index()
        assert len(index.items) > 800 and index.meta.title
        last = index.items[-1]
        raw = source.fetch_chapter(last)
        blocks = normalize(raw, source.clean_rules(raw), last.title)
    assert len(blocks) > 20  # real prose, not a challenge page
    assert not any("Just a moment" in getattr(b, "text", "") for b in blocks)
