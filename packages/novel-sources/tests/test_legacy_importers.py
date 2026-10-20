"""MtlTings, scribblehub and Calibre HTML importers, on small files shaped like the real stores."""

import pytest
from novel_core import ChapterKey, Kind, NovelStore
from novel_sources.calibre import CalibreImporter
from novel_sources.importing import import_novel
from novel_sources.mtl import MtlImporter
from novel_sources.scribble import ScribbleImporter


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))  # the real stores are CRLF
    return path


def keys(novel_dir, source=None):
    with NovelStore.open(novel_dir) as store:
        return [s.key for s in (store.chapters(source) if source else store.selection())]


def version_texts(novel_dir, key):
    with NovelStore.open(novel_dir) as store:
        [chosen] = [s for s in store.selection() if s.key == key]
        version = store.read_version(chosen.version_id)
    return version, [b.text for b in version.blocks]


# -- MtlTings ----------------------------------------------------------------------------


def mtl_hash_names(root):
    """CCG raws: `#N_ Title.txt` with a `Chapter: #N: Title` header; `#_` files have no number.

    3 is split into Part files, and 2 was downloaded twice, once under a cut-off title."""
    folder = root / "data" / "raw" / "Cultivation Chat Group"
    write(folder / "#0_ Today first a chapter.txt", "Chapter: #0: Today first a chapter\n\n今天晚上本来酝酿了大半天的感情。\n")
    write(folder / "#1_ Nine Provinces (1) Group.txt", "Chapter: #1: Nine Provinces (1) Group\n\n2019年5月20日,星期一。\n")
    write(folder / "#2_ Divine.txt", "Chapter: #2: Divine\n\n都说人不中二枉少年。\n\n“算黑卦的又掉线了。”苏氏阿七猜测道。\n")
    write(folder / "#2_ Div.txt", "Chapter: #2: Div\n\n都说人不中二枉少年。\n\n“算黑卦的又掉线了。”苏氏阿七猜测道。\n")
    write(folder / "#3_ Tyrant.txt", "Chapter: #3: Tyrant\n\n太阳高升。\n")
    write(folder / "#3 Part 2_ Tyrant.txt", "Chapter: #3: Tyrant\n\n时值正午。\n")
    write(folder / "#_ Afterword.txt", "Chapter: #: Afterword\n\n我上传了这个故事。\n")
    write(folder / "notes.md", "not a chapter")
    return folder


def test_import_mtl_hash_names(tmp_path, clock):
    report = import_novel(tmp_path / "ccg", MtlImporter(mtl_hash_names(tmp_path)), clock)
    assert report.created and report.inserted == 6 and not report.failed
    assert report.notes == (
        "1 files not named like chapter_N.txt or #N_ Title.txt were not imported",
        "1 files repeat another file's chapter text under a cut-off title; imported once",
    )
    with NovelStore.open(tmp_path / "ccg") as store:
        [source] = store.sources()
        assert (source.spec.backend, source.spec.kind, source.spec.lang) == ("import:mtl", Kind.RAW_ZH, "zh")
        assert store.meta.title == "Cultivation Chat Group"
        # #N is the printed number, with no offset; "(1) Group" is not a part.
        assert [s.key for s in store.chapters(source.id)] == [
            ChapterKey(0), ChapterKey(1), ChapterKey(2), ChapterKey(3), ChapterKey(3, 2)
        ]  # fmt: skip
        check = store.check()
        assert [n.title for n in check.unmapped] == ["Afterword"]
        assert check.raw_only == (0, 1, 2, 3) and check.duplicates == ()
        assert store.selection() == ()  # raw-zh is never published
        [two] = [s for s in store.chapters(source.id) if s.key == ChapterKey(2)]
        version = store.read_version(two.version_id)
    # Short Chinese lines survive: English watermark rules would read them as disguised site names.
    assert version.title == "Divine"
    assert [b.text for b in version.blocks] == ["都说人不中二枉少年。", "“算黑卦的又掉线了。”苏氏阿七猜测道。"]


def test_import_mtl_translations_are_my_translation(tmp_path, clock):
    folder = tmp_path / "data" / "translated" / "my_longevity_simulation"
    for n in (990, 991):
        write(folder / f"chapter_{n}.html", f"Chapter {n}: Name {n}\n\n\n\nText of {n}.\n\nMore of {n}.\n")
    report = import_novel(tmp_path / "longevity", MtlImporter(folder), clock)
    assert report.inserted == 2
    assert keys(tmp_path / "longevity") == [ChapterKey(990), ChapterKey(991)]
    version, texts = version_texts(tmp_path / "longevity", ChapterKey(990))
    assert version.title == "Chapter 990: Name 990" and texts == ["Text of 990.", "More of 990."]
    assert version.provenance["model"] == "unknown (MtlTings)" and version.provenance["glossary"] is None
    with NovelStore.open(tmp_path / "longevity") as store:
        assert store.meta.title == "my longevity simulation"
        assert store.sources()[0].spec.kind is Kind.MY_TRANSLATION


def test_import_mtl_raw_chapter_files_drop_the_repeated_title(tmp_path, clock):
    folder = tmp_path / "data" / "raw" / "my_longevity_simulation"
    write(folder / "chapter_1000.txt", "第1000章 李凡哑无言\n\n\n\n第1000章 李凡哑无言\n百花道人顿了顿。\n")
    import_novel(tmp_path / "longevity", MtlImporter(folder), clock)
    with NovelStore.open(tmp_path / "longevity") as store:
        [chapter] = store.chapters(store.sources()[0].id)
        version = store.read_version(chapter.version_id)
    assert chapter.key == ChapterKey(1000) and [b.text for b in version.blocks] == ["百花道人顿了顿。"]


def test_mtl_folder_must_be_raw_or_translated(tmp_path):
    (tmp_path / "elsewhere" / "novel").mkdir(parents=True)
    with pytest.raises(ValueError, match="data/raw or data/translated"):
        MtlImporter(tmp_path / "elsewhere" / "novel")


# -- scribblehub ---------------------------------------------------------------------------


def scribble_file(root):
    """Markers glued to the previous chapter's last line; 809 is an extra in two halves."""
    text = (
        "## Chapter 439: Millennia of Changes\n\nChapter 439: Millennia of Changes\n\nFirst of 439.\n\nLast of 439."
        "## Chapter 440: The Rain\n\nChapter 440: The Rain\n\nText of 440.\n\nRead extra chapters on >>> patreon.com/SpiritStonetranslation"
        "## Chapter 809: Extra – Longevity (1)\n\nChapter 809: Extra – Longevity (1)\n\nFirst half."
        "## Chapter 809: Extra – Longevity (2)\n\nChapter 809: Extra – Longevity (2)\n\nSecond half.\n"
    )
    return write(root / "mycoreistheboss" / "My Longevity Simulation", text)


def test_import_scribble(tmp_path, clock):
    path = scribble_file(tmp_path)
    report = import_novel(tmp_path / "longevity", ScribbleImporter(path), clock)
    assert report.inserted == 4 and not report.failed
    assert keys(tmp_path / "longevity") == [ChapterKey(439), ChapterKey(440), ChapterKey(809, 1), ChapterKey(809, 2)]
    version, texts = version_texts(tmp_path / "longevity", ChapterKey(439))
    assert version.title == "Chapter 439: Millennia of Changes"
    assert texts == ["First of 439.", "Last of 439."]  # the glued marker is not part of the text
    assert version_texts(tmp_path / "longevity", ChapterKey(440))[1] == ["Text of 440."]  # patreon line dropped
    with NovelStore.open(tmp_path / "longevity") as store:
        assert "My Longevity Simulation#1" in store.item_refs(store.sources()[0].id)


def test_scribble_without_markers_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no '## Chapter N' markers"):
        ScribbleImporter(write(tmp_path / "empty", "just text\n"))


# -- Calibre HTML ----------------------------------------------------------------------------


def calibre_page(chapters, flat=False):
    """A github_pages page: a TOC of calibre_link anchors, then a div (or an <h1>, flat) per chapter."""
    toc = "".join(f'<li><a href="#calibre_link-{i}">{title}</a></li>' for i, title, _ in chapters)
    if flat:
        body = "".join(f'<h1 id="calibre_link-{i}">{title}</h1>' + "".join(f'<p class="calibre2">{p}</p>' for p in ps)
                       for i, title, ps in chapters)  # fmt: skip
    else:
        body = "".join(f'<div class="calibre" id="calibre_link-{i}"><p class="calibre4">{title}</p>'
                       + "".join(f'<p class="calibre4">{p}</p>' for p in ps) + "</div>" for i, title, ps in chapters)  # fmt: skip
    return (f'<html><body><div class="calibre" id="calibre_link-0"><nav role="doc-toc" id="calibre_link-999">'
            f"<ul>{toc}</ul></nav>{body}</div></body></html>")  # fmt: skip


def test_import_calibre_div_pages_with_overlap(tmp_path, clock):
    folder = tmp_path / "novels" / "Who Let Him Cultivate"
    # index_until912 sorts after index_1_50 by name but holds the earlier chapters; 3 is on both pages.
    write(folder / "index_until912.html", calibre_page([
        (1, "Chapter 1: Travel", ["Text 1."]),
        (3, "Chapter 3: Cut", ["Short."]),
    ]))  # fmt: skip
    write(folder / "index_1_50.html", calibre_page([
        (1, "Who Let Him Cultivate?! (WX)-Chapter 3: Cut", ["Longer text of 3.", "More."]),
        (2, "Who Let Him Cultivate?!-Chapter 4 - 3: Nian Beast", ["Text 4."]),
        (7, "Notice", ["Leave."]),
    ]))  # fmt: skip
    write(folder / "index.html", "<html>the old reader's landing page</html>")
    importer = CalibreImporter(folder)
    report = import_novel(tmp_path / "wlhc", importer, clock)
    assert keys(tmp_path / "wlhc") == [ChapterKey(1), ChapterKey(3), ChapterKey(4)]
    assert report.notes == ("1 chapters found on two pages; the longer copy was imported",)
    assert [i.ref for i in importer.read_index().items] == [
        "index_until912.html#calibre_link-1", "index_1_50.html#calibre_link-1",
        "index_1_50.html#calibre_link-2", "index_1_50.html#calibre_link-7",
    ]  # fmt: skip
    assert version_texts(tmp_path / "wlhc", ChapterKey(3))[1] == ["Longer text of 3.", "More."]  # title echo dropped
    with NovelStore.open(tmp_path / "wlhc") as store:
        assert [n.title for n in store.check().unmapped] == ["Notice"]
        assert store.sources()[0].spec.backend == "import:calibre"


def test_calibre_repeat_within_a_page_is_left_for_check(tmp_path, clock):
    # Longevity: the translation of 1555 is titled "Chapter 1554: ...", so the page lists 1554 twice.
    folder = tmp_path / "novels" / "my longevity simulation"
    write(folder / "index_1531_1579.html", calibre_page([
        (1, "Chapter 1554: Morality Has True Immortals", ["Text of 1554, the longer one."]),
        (2, "Chapter 1554: True Immortal of Morality", ["Text of 1555."]),
    ]))  # fmt: skip
    report = import_novel(tmp_path / "longevity", CalibreImporter(folder), clock)
    assert report.inserted == 2 and report.notes == ()
    with NovelStore.open(tmp_path / "longevity") as store:
        [duplicate] = store.check().duplicates
    assert duplicate.key == ChapterKey(1554) and len(duplicate.item_refs) == 2


def test_import_calibre_flat_layout(tmp_path, clock):
    folder = tmp_path / "novels" / "my longevity simulation"
    write(folder / "index_990_991.html", calibre_page([
        (51, "Chapter 990: Secrets", ["Text of 990.", "More."]),
        (52, "Chapter 991: High Wall", ["Text of 991."]),
    ], flat=True))  # fmt: skip
    import_novel(tmp_path / "longevity", CalibreImporter(folder), clock)
    assert keys(tmp_path / "longevity") == [ChapterKey(990), ChapterKey(991)]
    assert version_texts(tmp_path / "longevity", ChapterKey(990))[1] == ["Text of 990.", "More."]
    assert version_texts(tmp_path / "longevity", ChapterKey(991))[1] == ["Text of 991."]
