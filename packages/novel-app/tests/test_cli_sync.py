from contextlib import contextmanager

import pytest
from novel_app import cli
from novel_app.cli import app
from novel_app.library import DATA_DIR_ENV
from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec
from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.importing import NovelIndex
from typer.testing import CliRunner

URL = "https://novelbuddy.me/test-novel"


class Site:
    """The live site behind every `open_source` call: chapters 1..count; `fail` numbers raise."""

    def __init__(self):
        self.count = 3
        self.fail: set[int] = set()
        self.down = False

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
    def open_source(spec: SourceSpec, state):
        assert spec.backend == "lncrawl" and spec.kind is Kind.OFFICIAL_EN
        yield site.source(spec)

    monkeypatch.setattr(cli, "open_source", open_source)
    return site


def run(*args):
    return CliRunner().invoke(app, [str(a) for a in args])


def test_add_then_sync(site):
    result = run("add", URL)
    assert result.exit_code == 0, result.output
    assert "created test-novel: source 1 (lncrawl), 3 chapters listed" in result.output
    assert "to fetch: 3" in result.output

    result = run("sync", "test-novel")
    assert result.exit_code == 0, result.output
    assert "fetched 3: 3 stored, 0 unchanged, 0 locked" in result.output

    site.count = 4
    result = run("sync", "--all")
    assert "index: 1 new, 0 vanished; fetched 1: 1 stored" in result.output


def test_cli_sync_exit(site):
    run("add", URL)
    site.fail = {2}
    result = run("sync", "test-novel")
    assert result.exit_code == 1
    assert "failed: 1" in result.output
    assert "/test-novel/chapter-2: /test-novel/chapter-2: HTTP 500" in result.output


def test_unreachable_index_ends_the_command(site):
    site.down = True
    result = run("add", URL)
    assert result.exit_code == 1
    assert "fetch failed" in result.output


def test_sync_needs_a_web_source(site, tmp_path):
    run("add", URL)
    assert run("sync").exit_code != 0
    assert run("sync", "test-novel", "--source", 9).exit_code == 2


def test_align_copy_gives_a_web_source_the_fixes_made_on_another(site):
    run("add", URL)
    site.count = 4
    run("add", URL + "/", "--novel", "test-novel", "--backend", "lncrawl")  # a second source, same paths
    assert run("align", "skip", "test-novel", "/test-novel/chapter-2", "--source", 1).exit_code == 0
    assert run("align", "item", "test-novel", "/test-novel/chapter-3", "30", "--source", 1).exit_code == 0

    result = run("align", "copy", "test-novel", 1, 2)
    assert result.exit_code == 0, result.output
    assert "2 items moved" in result.output
    assert run("align", "copy", "test-novel", 1, 9).exit_code == 2
