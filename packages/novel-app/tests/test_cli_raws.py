"""`nov check`, `nov release` and `nov reclean` over raw-zh sources: held chapters and rule revisions."""

import sqlite3
from dataclasses import replace

import pytest

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


def test_check_lists_held_chapters_numbering_and_counts_unchecked_ones(novels, old_rules, misnumbered):
    old_rules([1, 2, 4, 5])
    hold("raw-novel", 1, "/3")
    result = run("check", "raw-novel")
    assert result.exit_code == 0, result.output
    assert "  held: 1\n    source 1 /3: poison: 有没×9\n" in result.output
    assert (
        "  numbering: 1 (against source 1)\n"
        "    source 2 printed 2-6 are chapters 1-5 (offset -1, 5 titles match):"
        " nov align range raw-novel 2-6 -1 --source 2\n"
    ) in result.output
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


def store_raws(slug: str, spec: SourceSpec, chapters: dict[str, str], today: bool = True) -> int:
    """A raw-zh source of `slug` whose chapters (title -> kept text) are cleaned and checked by today's
    rules, or by older rules without cleaners and checks; keys come from the titles."""
    zh = zh_rules(slug, spec) if today else replace(zh_rules(slug, spec), rev="old", cleaners=(), markers=None)
    path = novel_dir(slug)
    with (NovelStore.open(path) if path.exists() else NovelStore.create(path, NovelMeta("书", language="zh"))) as store:
        source = store.upsert_source(spec)
        items = [SourceItem(f"/{source}/{n}", n, title) for n, title in enumerate(chapters, start=1)]
        store.record_index(source, items)
        for item in items:
            raw = RawChapter(chapters[item.title], "text")
            store.put_version(source, item.ref, zh.version(raw, item.title, CleanRules(content=()), {}))
    return source


def test_inspect_shows_findings_cleaner_hits_and_suspicious_paragraphs(novels):
    store_raws("zh-novel", IXDZS, {"第3章 毒": POISONED})
    noisy = f"{PROSE}\n>\n他说————走了。\n「他说\nOK\n……\nwωw赵二宝闻言大喜"
    store_raws("zh-novel", replace(IXDZS, url="https://ixdzs8.com/read/38805/"), {"第4章 山门": noisy}, today=False)

    result = run("inspect", "zh-novel", "3-4")
    assert result.exit_code == 0, result.output
    assert result.output == (
        "zh-novel: source 1 /1/1, chapter 3 第3章 毒: checked\n"
        "  finding poison: 有没×4 是止×4 退入×4 (6.8/1000) (held)\n"
        "  poison: 有没×4 是止×4 退入×4 = 12 hits, 6.8 per 1000 of 1752 CJK chars"
        " (flags at 2.0, 3 markers, 6 hits)\n"
        "  cleaner hits: none\n"
        "  suspicious: none\n"
        "zh-novel: source 2 /2/1, chapter 4 第4章 山门: not checked with current rules\n"
        "  poison: no markers in 71 CJK chars\n"
        "  cleaner hits:\n"
        "    lone-noise ×1: > → (dropped)\n"
        "    dash-run ×1: 他说————走了。 → 他说……走了。\n"
        "  suspicious:\n"
        "    unbalanced quotes: 「他说\n"
        "    no CJK: OK\n"
        "    Latin/Cyrillic in a CJK line: wωw赵二宝闻言大喜\n"
    )
    assert run("inspect", "zh-novel", "4", "--source", 1).output == ""  # source 1 has no chapter 4


def test_inspect_against_a_reference_pairs_chapters_by_title_name(novels):
    raw = SourceSpec("custom:raw", "https://raw.test", "zh", Kind.RAW_ZH)
    qidian = SourceSpec("novel-downloader", "https://www.qidian.com/book/1035420986/", "zh", Kind.RAW_ZH)
    ours = {"第5章 山门": f"{PROSE}\n他转身————走了。\n山风————吹过。\n广告", "第6章 钟声": f"{MORE}————", "第7章 求票": MORE}
    theirs = {
        "第6章 山门（求月票）": f"{PROSE}\n他转身……走了。\n山风……吹过。",
        "第7章 钟声": f"{MORE}……",
        "第8章 求票": MORE, "第9章 求票": MORE,
    }  # fmt: skip
    store_raws("zh-novel", raw, ours)
    store_raws("zh-novel", qidian, theirs)

    result = run("inspect", "zh-novel", "5-7", "--against", 2)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    first = lines.index("zh-novel: source 1 /1/1, chapter 5 第5章 山门: checked")
    assert lines[first + 4 :][:3] == [
        "  against source 2 /2/1, chapter 6 第6章 山门（求月票）:",
        "    ———— ↔ …… ×2",
        "    广告 ↔ (nothing) ×1",
    ]
    assert "  against source 2 /2/2, chapter 7 第7章 钟声:" in lines
    assert "  against source 2: no single chapter named 求票" in lines
    assert not any(line.startswith("zh-novel: source 2") for line in lines)  # the reference itself is not inspected


def test_inspect_needs_raw_sources(novels):
    assert run("inspect", "english-only", "1").exit_code == 2
    assert run("inspect", "raw-novel", "1", "--against", 9).exit_code == 2
    assert run("inspect", "raw-novel", "x").exit_code == 2


def test_reclean_needs_a_novel_with_raws(novels):
    assert run("reclean").exit_code == 2
    assert run("reclean", "raw-novel", "--all").exit_code == 2
    assert run("reclean", "english-only").exit_code == 2
    assert run("reclean", "raw-novel", "--source", 9).exit_code == 2


def test_align_range_moves_a_printed_range_and_settles_the_numbering(novels, misnumbered):
    result = run("align", "range", "raw-novel", "2-6", "-1", "--source", misnumbered)
    assert result.exit_code == 0, result.output
    assert result.output == "".join(f"  /b/{n}: {n} -> {n - 1}\n" for n in range(2, 7)) + "5 items moved\n"
    assert "numbering" not in run("check", "raw-novel").output

    assert run("align", "range", "raw-novel", "4-6", "+2", "--source", misnumbered).output.endswith("3 items moved\n")
    assert run("align", "range", "raw-novel", "6-2", "0", "--source", misnumbered).exit_code == 2
    assert run("align", "range", "raw-novel", "2-6", "x", "--source", misnumbered).exit_code == 2
    assert run("align", "range", "raw-novel", "2-6", "0").exit_code == 2  # two sources: --source needed


BIQUGE5 = SourceSpec("novel-downloader", "https://www.biquge5.com/9_9194/", "zh", Kind.RAW_ZH)
QIDIAN = SourceSpec("novel-downloader", "https://www.qidian.com/book/1035420986/", "zh", Kind.RAW_ZH)


@pytest.mark.parametrize(
    "specs, anchor",
    [
        pytest.param((BIQUGE5, IXDZS), 2, id="anchor-skips-decoy"),
        pytest.param((IXDZS, BIQUGE5, QIDIAN), 3, id="anchor-is-qidian"),
    ],
)
def test_numbering_is_against_qidian_else_the_first_raw_source_not_a_decoy_site(novels, specs, anchor):
    names = ("山门", "钟声", "松林", "溪水")
    with NovelStore.create(novel_dir("zh-novel"), NovelMeta("书", language="zh")) as store:
        for i, spec in enumerate(specs):
            source = store.upsert_source(spec)
            shift = 0 if source == anchor else 10 * (i + 1)
            items = [SourceItem(f"/{source}/{n}", n, f"第{n + shift}章 {t}") for n, t in enumerate(names, start=1)]
            store.record_index(source, items)
    lines = run("check", "zh-novel").output.splitlines()
    numbering = lines.index(f"  numbering: {len(specs) - 1} (against source {anchor})")
    assert sorted(line.split(" printed")[0].strip() for line in lines[numbering + 1 : numbering + len(specs)]) == [
        f"source {s}" for s in range(1, len(specs) + 1) if s != anchor
    ]
