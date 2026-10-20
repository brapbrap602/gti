"""Shared fixtures: a fake site behind every backend, in an empty data dir."""

import time
from contextlib import contextmanager

import pytest
from novel_app import service
from novel_app.library import DATA_DIR_ENV
from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec
from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.importing import NovelIndex

URL = "https://novelbuddy.me/test-novel"


class Site:
    """The live site behind every `open_source` call: chapters 1..count; `fail` numbers raise."""

    def __init__(self):
        self.count = 3
        self.fail: set[int] = set()
        self.down = False
        self.delay = 0.0  # seconds per chapter fetch

    def source(self, spec):
        site = self

        class Live:
            def __init__(self):
                self.spec = spec

            def fetch_index(self):
                if site.down:
                    raise FetchError(f"{URL}: HTTP 503 after 3 attempts")
                items = tuple(SourceItem(f"/test-novel/chapter-{n}", n, f"Chapter {n}") for n in range(1, site.count + 1))
                return NovelIndex(NovelMeta("Test Novel"), items)

            def fetch_chapter(self, item):
                n = int(item.ref.rsplit("-", 1)[1])
                time.sleep(site.delay)
                if n in site.fail:
                    raise FetchError(f"{item.ref}: HTTP 500 after 3 attempts")
                return RawChapter(f'<div id="b"><p>Text {n}.</p></div>')

            def clean_rules(self, raw):
                return CleanRules(content=("div#b",))

        return Live()


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    site = Site()

    @contextmanager
    def open_source(spec: SourceSpec, state, guides):
        assert spec.backend == "lncrawl" and spec.kind is Kind.OFFICIAL_EN
        yield site.source(spec)

    monkeypatch.setattr(service, "open_source", open_source)
    return site
