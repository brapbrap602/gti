import hashlib
import io
import zipfile

import pytest
from novel_core import SourceItem
from novel_sources import lnreader
from novel_sources.backends import backend_for, spec_for_url
from novel_sources.clean import normalize
from novel_sources.fetch import FetchError
from novel_sources.lnreader import LnreaderSource, plugin_for

PLUGINS = [
    {"file": "plugins/english/novelbuddy.ts", "id": "novelbuddy", "name": "NovelBuddy", "site": "https://novelbuddy.me/", "lang": "english"},
    {"file": "plugins/english/sub.ts", "id": "sub", "name": "Sub", "site": "https://www.sub.test/read/", "lang": "english"},
]  # fmt: skip


class FakeHarness:
    """The harness process, answering from canned results; `fail` ops raise as the plugin would."""

    def __init__(self, chapters=None, fail=()):
        self.chapters = chapters or {}
        self.fail = set(fail)
        self.requests = []
        self.closed = False

    def request(self, op, **fields):
        self.requests.append((op, fields))
        if op in self.fail:
            raise FetchError(f"lnreader {op}: fetch failed (HTTP 503)")
        if op == "novel":
            chapters = [
                {"name": "Chapter 1: Start", "path": "the-novel/chapter-1?id=7&chapterId=1", "chapterNumber": None},
                {"name": "Chapter 2: Next", "path": "the-novel/chapter-2?id=7&chapterId=2", "chapterNumber": None},
                {"name": "Chapter 2: Next", "path": "the-novel/chapter-2?id=7&chapterId=2", "chapterNumber": None},
            ]
            return {"name": "The Novel", "author": "A. Writer", "genres": "action, fantasy", "summary": "", "status": "", "chapters": chapters}
        return {"html": self.chapters.get(fields["path"], "")}

    def close(self):
        self.closed = True


def source(harness, url="https://novelbuddy.me/the-novel") -> LnreaderSource:
    return LnreaderSource(LnreaderSource.spec_for(url), harness, PLUGINS)


def test_a_url_goes_to_the_plugin_for_its_host():
    plugin, path = plugin_for("https://www.novelbuddy.me/the-novel", PLUGINS)
    assert (plugin["id"], path) == ("novelbuddy", "the-novel")
    plugin, path = plugin_for("https://sub.test/read/novel/x/", PLUGINS)  # a site with a path of its own
    assert (plugin["id"], path) == ("sub", "novel/x/")
    with pytest.raises(ValueError, match="no LNReader plugin for other.test"):
        plugin_for("https://other.test/n", PLUGINS)


def test_lnreader_is_only_used_when_asked_for():
    assert backend_for("https://novelbuddy.me/the-novel") == "lncrawl"
    spec = spec_for_url("https://novelbuddy.me/the-novel", "en", backend="lnreader")
    assert (spec.backend, spec.lang) == ("lnreader", "en")


def test_index_refs_are_url_paths_and_chapters_use_the_plugin_paths():
    harness = FakeHarness({"the-novel/chapter-2?id=7&chapterId=2": "<p>Chapter 2: Next</p><p>She ran.</p>"})
    site = source(harness)
    index = site.fetch_index()
    assert harness.requests[0] == ("novel", {"file": "plugins/english/novelbuddy.ts", "path": "the-novel"})
    assert (index.meta.title, index.meta.author, index.meta.tags) == ("The Novel", "A. Writer", ("action", "fantasy"))
    assert [(i.ref, i.position, i.title) for i in index.items] == [
        ("/the-novel/chapter-1", 1, "Chapter 1: Start"),
        ("/the-novel/chapter-2", 2, "Chapter 2: Next"),  # listed twice, kept once
    ]
    assert index.provenance["plugin"] == "novelbuddy"
    item = index.items[1]
    raw = site.fetch_chapter(item)
    assert raw.final_url == "https://novelbuddy.me/the-novel/chapter-2?id=7&chapterId=2"
    assert [b.text for b in normalize(raw, site.clean_rules(raw), item.title)] == ["She ran."]
    site.close()
    assert harness.closed


def test_plugin_failures_are_fetch_errors():
    site = source(FakeHarness())
    with pytest.raises(FetchError, match="not in the index"):
        site.fetch_chapter(SourceItem("/the-novel/chapter-1", 1, "Chapter 1"))
    item = site.fetch_index().items[0]
    with pytest.raises(FetchError, match="empty chapter"):
        site.fetch_chapter(item)
    with pytest.raises(FetchError, match="HTTP 503"):
        source(FakeHarness(fail={"novel"})).fetch_index()


# -- setup: download, check, unpack ---------------------------------------------------


def archive(top: str) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr(f"{top}/README.md", "plugins")
    return data.getvalue()


def test_a_download_that_fails_its_checksum_installs_nothing(tmp_path):
    payload = archive("top")
    write = lambda url, to: to.write_bytes(payload)  # noqa: E731
    with pytest.raises(FetchError, match="SHA-256 .* is not the pinned"):
        lnreader._install(tmp_path, tmp_path / "target", "https://x.test/a.zip", "0" * 64, write, top="top")
    assert not (tmp_path / "target").exists()


def test_install_unpacks_the_top_folder_and_retries_cleanly(tmp_path):
    payload = archive("top")
    sha = hashlib.sha256(payload).hexdigest()
    (tmp_path / ".target.partial" / "junk").mkdir(parents=True)  # left by an interrupted setup
    seen = []
    lnreader._install(tmp_path, tmp_path / "target", "https://x.test/a.zip", sha, lambda url, to: to.write_bytes(payload),
                      top="top", then=lambda folder: seen.append(sorted(p.name for p in folder.iterdir())))  # fmt: skip
    assert seen == [["README.md"]]
    assert (tmp_path / "target" / "README.md").read_text() == "plugins"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["target"]


@pytest.mark.live
def test_g2_novelbuddy_plugin_under_the_pinned_node():
    """Gate G2: the real Node, plugin checkout and harness (set up in the library's own _fetch)."""
    import os
    from pathlib import Path

    from novel_sources.backends import open_source

    data = os.environ.get("NOVELS_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "novels"
    url = "https://novelbuddy.me/surviving-the-game-as-a-barbarian"
    with open_source(spec_for_url(url, "en", backend="lnreader"), Path(data) / "_fetch") as live:
        index = live.fetch_index()
        assert len(index.items) > 800 and index.meta.title
        last = index.items[-1]
        raw = live.fetch_chapter(last)
        assert len(normalize(raw, live.clean_rules(raw), last.title)) > 20
