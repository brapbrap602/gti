"""`nov check`, `nov release` and `nov reclean` over raw-zh sources: held chapters and rule revisions."""

import sqlite3
from dataclasses import replace

from novel_app.cli import app
from novel_app.library import data_dir, novel_dir
from novel_core import Finding, Kind, NewVersion, NovelMeta, NovelStore, Paragraph, RawChapter, SourceItem, SourceSpec
from novel_sources.backends import zh_rules
from novel_sources.clean import CleanRules
from typer.testing import CliRunner

IXDZS = SourceSpec("novel-downloader", "https://ixdzs8.com/read/38804/", "zh", Kind.RAW_ZH)
PROSE = "他笑了笑，转身走出山门，沿着石阶一路向下，风吹过松林，远处传来钟声。" * 2
MORE = "夜色渐深，山中寂静无声，只有溪水潺潺流过，月光洒在青石板上。" * 2
POISONED = "\n".join("天地玄黄宇宙洪荒日月盈昃" * 12 + m for m in ("有没", "是止", "退入") * 4)


def run(*args, input=None):
    return CliRunner().invoke(app, [str(a) for a in args], input=input)


def hold(slug: str, source: int, ref: str, check: str = "poison", detail: str = "有没×9") -> None:
    """Give the current text of `ref` a finding from today's rules, as a sync would have."""
    with NovelStore.open(novel_dir(slug)) as store:
        spec = next(s.spec for s in store.sources() if s.id == source)
        current = next(s for s in store.view().chapters(source) if s.item_ref == ref)
        v = store.read_version(current.version_id)
        rev = zh_rules(slug, spec).rev
        store.put_version(source, ref, NewVersion(v.title, v.blocks, findings=(Finding(check, detail),), rules_rev=rev))


def test_check_lists_held_chapters_and_counts_unchecked_ones(novels):
    hold("raw-novel", 1, "/3")
    result = run("check", "raw-novel")
    assert result.exit_code == 0, result.output
    assert "  held: 1\n    source 1 /3: poison: 有没×9\n" in result.output
    assert result.output.endswith("  4 chapters not checked with current rules: run nov reclean raw-novel\n")


def test_release_lets_a_held_chapter_through(novels):
    hold("raw-novel", 1, "/3")
    result = run("release", "raw-novel", "2-3")
    assert result.exit_code == 0, result.output
    assert result.output == "raw-novel: released source 1 /3 (poison)\n"
    assert "held" not in run("check", "raw-novel").output

    assert run("release", "raw-novel", "3").output == "raw-novel: nothing held in 3\n"
    assert run("release", "raw-novel", "3", "--source", 9).exit_code == 2
    assert run("release", "english-only", "3").exit_code == 2  # no raw-zh source


def ixdzs_novel() -> int:
    """zh-novel: three ixdzs8 chapters stored before its cleaners and the poison check existed."""
    before = replace(zh_rules("zh-novel", IXDZS), cleaners=(), markers=None)
    texts = {1: f"{PROSE}\n>", 2: f"{MORE}————", 3: POISONED}
    with NovelStore.create(novel_dir("zh-novel"), NovelMeta("书", language="zh")) as store:
        source = store.upsert_source(IXDZS)
        store.record_index(source, [SourceItem(f"/read/38804/p{n}.html", n, f"第{n}章") for n in texts])
        for n, text in texts.items():
            v = before.version(RawChapter(text, "text"), f"第{n}章", CleanRules(content=()), {"backend": IXDZS.backend})
            store.put_version(source, f"/read/38804/p{n}.html", v)
    return source


def test_reclean_reports_what_the_current_rules_change(openrouter):
    source = ixdzs_novel()
    setup = run("translate", "setup", "add", "zh-novel", "--model", "vendor/cheap")
    setup_id = int(setup.output.split(" is source ")[1].split()[0])
    assert "translated 1;" in run("translate", "run", "zh-novel", setup_id, "2", "--yes").output

    result = run("reclean", "zh-novel")
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        f"zh-novel: source {source} (novel-downloader) {IXDZS.url}\n"
        "  rechecked 3: 2 rewritten, 1 unchanged\n"
        "  cleaner hits: lone-noise 1, dash-run 1\n"
        "  held: 1 newly, 0 no longer\n"
        "    /read/38804/p3.html: poison: 有没×4 是止×4 退入×4"
    )
    assert f"  setup {setup_id} vendor/cheap · prompt v1 · parallel: 1 translation now stale (n2)\n" in result.output
    with NovelStore.open(novel_dir("zh-novel")) as store:
        view = store.view()
        (p1, p2, p3) = view.chapters(source)
        assert store.read_version(p2.version_id).blocks == (Paragraph.of(MORE + "……"),)
        assert {s.rules_rev for s in (p1, p2, p3)} == {zh_rules("zh-novel", IXDZS).rev}

    again = run("reclean", "zh-novel").output
    assert "  rechecked 3: 0 rewritten, 3 unchanged\n  cleaner hits: lone-noise 1, dash-run 1\n" in again
    assert "  held: 0 newly, 0 no longer\n" in again and ": 0 translations now stale\n" in again


def test_reclean_of_html_raws_rechecks_the_stored_text(novels):
    spec = SourceSpec("lncrawl", "https://zh.test/book", "zh", Kind.RAW_ZH)
    blocks = tuple(Paragraph.of(p) for p in POISONED.split("\n"))
    with NovelStore.create(novel_dir("zh-novel"), NovelMeta("书", language="zh")) as store:
        source = store.upsert_source(spec)
        store.record_index(source, [SourceItem("/book/1", 1, "第1章")])
        html = RawChapter('<div id="c">' + "".join(f"<p>{b.text}</p>" for b in blocks) + "</div>")
        stored = store.put_version(source, "/book/1", NewVersion("第1章", blocks, html))

    result = run("reclean", "zh-novel")
    assert result.exit_code == 0, result.output
    assert "  rechecked 1: 0 rewritten, 1 unchanged\n  cleaner hits: none\n  held: 1 newly, 0 no longer\n" in result.output
    with NovelStore.open(novel_dir("zh-novel")) as store:
        (chapter,) = store.view().chapters(source)
        assert (chapter.version_id, chapter.content_hash) == (stored.version_id, stored.content_hash)
        assert [f.check for f in chapter.findings] == ["poison"]
        assert chapter.rules_rev == zh_rules("zh-novel", spec).rev


def test_reclean_all_skips_backups_and_novels_without_raws(novels):
    hold("raw-novel", 1, "/3")
    backup = data_dir() / "_backup-x"
    NovelStore.create(backup, NovelMeta("Backup")).close()
    with sqlite3.connect(backup / "novel.sqlite") as conn:
        conn.execute("DROP TABLE finding")
        conn.execute("DROP TABLE release")
        conn.execute("ALTER TABLE version DROP COLUMN rules_rev")
        conn.execute("ALTER TABLE version DROP COLUMN raw_hash")
        conn.execute("PRAGMA user_version=3")
    conn.close()

    result = run("reclean", "--all")
    assert result.exit_code == 0, result.output
    assert "raw-novel: source 1 (custom:raw) https://raw.test\n  rechecked 5: 0 rewritten, 5 unchanged\n" in result.output
    assert "  held: 0 newly, 1 no longer\n" in result.output  # today's rules find nothing in /3
    assert "english-only" not in result.output and "_backup" not in result.output
    with sqlite3.connect(backup / "novel.sqlite") as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (3,)
    conn.close()
    assert "not checked" not in run("check", "raw-novel").output


def test_reclean_needs_a_novel_with_raws(novels):
    assert run("reclean").exit_code == 2
    assert run("reclean", "raw-novel", "--all").exit_code == 2
    assert run("reclean", "english-only").exit_code == 2
    assert run("reclean", "raw-novel", "--source", 9).exit_code == 2
