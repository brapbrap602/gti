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
