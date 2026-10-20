import json

import pytest
from novel_app.cli import app
from novel_app.library import DATA_DIR_ENV, novel_dir, slugify
from typer.testing import CliRunner

TOC = "https://novelbin.me/novel-book/test-novel"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def wns_folder(tmp_path):
    """A web-novel-scraper folder: 1, 2 and 4 saved, 3 never downloaded, plus an unnumbered notice."""
    root = tmp_path / "wns" / "Test Novel"
    (root / "data" / "chapters").mkdir(parents=True)
    chapters = []
    for n in (1, 2, 3, 4):
        filename = None if n == 3 else f"test_{n}.html"
        chapters.append({"chapter_url": f"{TOC}/chapter-{n}", "chapter_html_filename": filename,
                         "chapter_title": f"Chapter {n}"})  # fmt: skip
        if filename:
            page = f'<div id="chr-content"><p>Chapter {n}</p><p>Text {n}.</p></div>'
            (root / "data" / "chapters" / filename).write_text(page, encoding="utf-8")
    chapters.append({"chapter_url": f"{TOC}/notice", "chapter_html_filename": None, "chapter_title": "Notice"})
    main = {"title": "Test Novel", "toc_main_url": TOC, "chapters": chapters, "metadata": {"language": "en"}}
    (root / "data" / "main.json").write_text(json.dumps(main), encoding="utf-8")
    return root


def run(*args):
    return CliRunner().invoke(app, [str(a) for a in args])


def test_import_wns_then_check(data_dir, wns_folder):
    result = run("import", "wns", wns_folder)
    assert result.exit_code == 0, result.output
    assert "created test-novel" in result.output
    assert "texts: 3 stored, 0 unchanged, 2 unavailable" in result.output
    assert (data_dir / "test-novel" / "novel.sqlite").exists()

    result = run("check", "test-novel")
    assert result.exit_code == 0, result.output
    assert "test-novel: 3 chapters selected" in result.output
    assert "gaps: 1 (3)" in result.output
    assert "unmapped: 1" in result.output and "'Notice'" in result.output

    again = run("import", "wns", wns_folder, "--novel", "test-novel")
    assert "updated test-novel" in again.output and "texts: 0 stored, 3 unchanged" in again.output


def test_import_exits_1_and_lists_failed_chapters(data_dir, wns_folder):
    (wns_folder / "data" / "chapters" / "test_2.html").unlink()
    result = run("import", "wns", wns_folder)
    assert result.exit_code == 1
    assert "failed: 1" in result.output and "/novel-book/test-novel/chapter-2" in result.output


def test_align_skip_and_item(data_dir, wns_folder):
    run("import", "wns", wns_folder)
    notice = "/novel-book/test-novel/notice"
    chapter_4 = "/novel-book/test-novel/chapter-4"

    result = run("align", "item", "test-novel", chapter_4, "3pt1")
    assert result.exit_code == 0, result.output
    assert f"{chapter_4}: 4 -> 3 pt 1" in result.output

    result = run("align", "skip", "test-novel", notice)
    assert result.exit_code == 0 and "0 items moved" in result.output
    check = run("check", "test-novel").output
    assert check == "test-novel: 3 chapters selected\n"  # 3 pt 1 fills the gap at 3; the notice is skipped

    bad = run("align", "skip", "test-novel", "/typo")
    assert bad.exit_code == 2 and "no item '/typo'" in bad.output
    assert run("align", "item", "test-novel", chapter_4, "x").exit_code == 2


def test_build_site_for_every_novel(data_dir, wns_folder):
    run("import", "wns", wns_folder)

    result = run("build", "site")

    assert result.exit_code == 0, result.output
    assert "test-novel: 3 chapters, 1 pages written, 0 deleted" in result.output
    page = (data_dir / "_site" / "novels" / "test-novel" / "1-50.html").read_text(encoding="utf-8")
    assert "Text 4." in page
    assert "test-novel: 3 chapters, 0 pages written" in run("build", "site").output


def test_build_epub(data_dir, wns_folder):
    run("import", "wns", wns_folder)

    result = run("build", "epub", "test-novel")

    assert result.exit_code == 0, result.output
    assert "test-novel: 1 of 1 volumes built, 0 deleted" in result.output
    assert (data_dir / "_epub" / "test-novel" / "test-novel_0001-0100.epub").exists()
    assert "test-novel: 0 of 1 volumes built" in run("build", "epub", "test-novel").output


def test_deploy_site_over_budget(data_dir, wns_folder, tmp_path):
    run("import", "wns", wns_folder)
    run("build", "site")

    result = run("deploy", "site", "--remote", tmp_path / "nowhere.git", "--budget-mb", 0)

    assert result.exit_code == 1 and "over the 0 MiB budget; nothing pushed" in result.output


def test_import_legacy_stores_into_one_novel_then_rank_them(data_dir, tmp_path):
    translated = tmp_path / "MtlTings" / "data" / "translated" / "test_novel"
    translated.mkdir(parents=True)
    for n in (2, 3):
        (translated / f"chapter_{n}.html").write_text(f"Chapter {n}: T{n}\n\nMine {n}.\n", encoding="utf-8")
    dump = tmp_path / "Test Novel"
    dump.write_text("## Chapter 1: T1\n\nChapter 1: T1\n\nTheirs 1.## Chapter 2: T2\n\nTheirs 2.\n", encoding="utf-8")

    result = run("import", "mtl", translated)  # the slug comes from the folder name
    assert result.exit_code == 0, result.output
    assert "created test-novel" in result.output and "texts: 2 stored" in result.output
    result = run("import", "scribble", dump, "--novel", "test-novel")
    assert result.exit_code == 0, result.output
    assert "updated test-novel" in result.output

    result = run("priority", "test-novel")
    assert result.exit_code == 0, result.output
    assert "1. source 1: import:mtl my-translation" in result.output
    assert "2. source 2: import:scribble official-en" in result.output
    result = run("priority", "test-novel", "2")
    assert "1. source 2: import:scribble" in result.output and "2. source 1: import:mtl" in result.output
    assert run("priority", "test-novel", "5").exit_code == 2


def test_import_mtl_rejects_other_folders(data_dir, tmp_path):
    result = run("import", "mtl", tmp_path)
    assert result.exit_code == 2 and "data/raw or data/translated" in result.output


def test_check_unknown_novel(data_dir):
    result = run("check", "nope")
    assert result.exit_code == 2 and "no novel 'nope'" in result.output


def test_slugs():
    assert slugify("Return of the Mount Hua Sect") == "return-of-the-mount-hua-sect"
    assert slugify("Who Let Him Cultivate?! (WX)") == "who-let-him-cultivate-wx"
    with pytest.raises(ValueError):
        slugify("修真聊天群")
    with pytest.raises(ValueError):
        novel_dir("../escape")
