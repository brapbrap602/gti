from contextlib import contextmanager

import pytest

from novel_app import cli, service
from novel_app.cli import app
from novel_app.library import novel_dir
from novel_core import Kind, NewVersion, NovelMeta, NovelStore, Paragraph, RawChapter, SourceItem, SourceSpec
from novel_sources.backends import zh_rules
from novel_sources.clean import CleanRules
from novel_sources.importing import NovelIndex
from typer.testing import CliRunner

URL = "https://novelbuddy.me/test-novel"


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


def test_a_malformed_guide_file_ends_add_and_sync(site, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "decode_guide.json").write_text("[{", encoding="utf-8")
    for args in (["add", URL], ["sync", "--all"]):
        result = CliRunner().invoke(cli.app, args)
        assert result.exit_code == 2 and "not a decode guide" in result.output


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


ZH = SourceSpec("lncrawl", "https://zh.test/book", "zh", Kind.RAW_ZH)
POISONED = "\n".join("天地玄黄宇宙洪荒日月盈昃" * 12 + m for m in ("有没", "是止", "退入") * 4)


@pytest.fixture
def zh_site(site, monkeypatch):
    """Every source is a raw-zh site serving `texts` (ref -> text; "他笑了。" for any other ref) for 1 and 2."""
    texts: dict[str, str] = {}

    class Live:
        def __init__(self, spec):
            self.spec = spec

        def fetch_index(self):
            return NovelIndex(NovelMeta("书"), tuple(SourceItem(f"/book/{n}", n, f"第{n}章") for n in (1, 2)))

        def fetch_chapter(self, item):
            return RawChapter(texts.get(item.ref, "他笑了。"), "text")

        def clean_rules(self, raw):
            return CleanRules(content=())

    @contextmanager
    def open_source(spec, state, guides):
        yield Live(spec)

    monkeypatch.setattr(service, "open_source", open_source)
    return texts


def zh_novel(*specs: SourceSpec) -> list[int]:
    with NovelStore.create(novel_dir("zh-novel"), NovelMeta("书", language="zh")) as store:
        return [store.upsert_source(spec) for spec in specs]


def test_sync_of_a_raw_zh_source_uses_its_zh_rules(zh_site):
    """The Service passes each raw-zh source its rules: chapters are stamped and poison is held."""
    (source,) = zh_novel(ZH)
    zh_site["/book/2"] = POISONED
    result = run("sync", "zh-novel")
    assert result.exit_code == 0, result.output
    with NovelStore.open(novel_dir("zh-novel")) as store:
        view = store.view()
        assert {s.rules_rev for s in view.chapters(source)} == {zh_rules("zh-novel", ZH).rev}
        assert [f.check for f in view.held(source, "/book/2")] == ["poison"]


def test_sync_report_counts_held_chapters_and_the_held_ones_fetched_again(zh_site):
    zh_novel(ZH, SourceSpec("import:mtl", "file:///raws", "zh", Kind.RAW_ZH))
    zh_site["/book/2"] = POISONED

    first = run("sync", "zh-novel").output
    assert "  held: 1 (poison 1)\n    /book/2: poison: 有没×4 是止×4 退入×4" in first
    assert "another source picks up held numbers on its next sync" in first

    assert "  held: 1 (poison 1); refetched held: 1, now clean 0\n" in run("sync", "zh-novel").output

    zh_site["/book/2"] = "他哭了。"
    third = run("sync", "zh-novel").output
    assert "  held: 0; refetched held: 1, now clean 1\n" in third
    assert "another source" not in third


def test_sync_report_says_when_no_other_source_can_pick_up_held_numbers(zh_site):
    zh_novel(ZH)
    zh_site["/book/2"] = POISONED
    output = run("sync", "zh-novel").output
    assert "  held: 1 (poison 1)" in output and "another source" not in output


def test_sync_counts_chapters_not_checked_with_the_current_rules(zh_site):
    (source,) = zh_novel(ZH)
    with NovelStore.open(novel_dir("zh-novel")) as store:  # stored before the novel had zh rules
        store.record_index(source, [SourceItem("/book/1", 1, "第1章")])
        store.put_version(source, "/book/1", NewVersion("第1章", (Paragraph.of("他笑了。"),)))

    output = run("sync", "zh-novel").output
    assert output.endswith("1 chapters not checked with current rules: run nov reclean zh-novel\n"), output

    assert run("reclean", "zh-novel").exit_code == 0
    assert "not checked" not in run("sync", "zh-novel").output


def test_sync_of_a_decoy_site_records_its_index_only(zh_site):
    zh_novel(SourceSpec("novel-downloader", "https://www.biquge5.com/9_9194/", "zh", Kind.RAW_ZH))
    output = run("sync", "zh-novel").output
    assert "fetched 0: 0 stored" in output and "  decoy site: index only" in output
