"""EPUB importer, on small books shaped like the real ones in the user's Calibre folders."""

import zipfile
from urllib.parse import unquote

import pytest
from novel_core import ChapterKey, Kind, NovelStore
from novel_sources.epub import EpubImporter, chapter_number
from novel_sources.importing import import_novel

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def page(title, body):
    return (
        '<?xml version="1.0" encoding="UTF-8" ?>\n<html xmlns="http://www.w3.org/1999/xhtml">'
        f"<head><title>{title}</title></head><body>{body}</body></html>"
    )


def chapter(title, paragraphs, tag="h2"):
    ps = "".join(f"<p>{p}</p>" for p in paragraphs)
    return page(title, f'<div class="chapter"><{tag} class="chapter-title">{title}</{tag}><div class="ugc">{ps}</div></div>')


def make_epub(path, docs, spine=None, language="en", toc=None, missing=()):
    """`docs` is [(href relative to the OPF, html str or bytes)], in spine order unless `spine` gives one.
    `toc` is [(href[#anchor], label)] for a toc.ncx; None leaves the book without a TOC.
    `missing` hrefs are listed in the manifest and spine but not stored."""
    manifest = "".join(
        f'<item id="d{i}" href="{href}" media-type="application/xhtml+xml"/>' for i, (href, _) in enumerate(docs)
    )
    order = spine if spine is not None else range(len(docs))
    itemrefs = "".join(f'<itemref idref="d{i}"/>' for i in order)
    manifest += "".join(f'<item id="m{i}" href="{href}" media-type="application/xhtml+xml"/>' for i, href in enumerate(missing))
    itemrefs += "".join(f'<itemref idref="m{i}"/>' for i in range(len(missing)))
    if toc is not None:
        manifest += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    opf = (
        '<?xml version="1.0"?><package version="2.0" xmlns="http://www.idpf.org/2007/opf">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>Lord of the Mysteries (Web Novel)</dc:title><dc:creator>Cuttlefish That Loves Diving</dc:creator>"
        f"<dc:language>{language}</dc:language></metadata>"
        f'<manifest>{manifest}</manifest><spine{" toc=\"ncx\"" if toc is not None else ""}>{itemrefs}</spine></package>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        for href, html in docs:
            z.writestr(f"OEBPS/{unquote(href)}", html)  # hrefs are URL-escaped, zip names are not
        if toc is not None:
            points = "".join(
                f'<navPoint id="n{i}"><navLabel><text>{label}</text></navLabel><content src="{src}"/></navPoint>'
                for i, (src, label) in enumerate(toc)
            )
            z.writestr("OEBPS/toc.ncx", f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{points}</navMap></ncx>')
    return path


def items(path):
    return [(i.ref, i.title, i.number) for i in EpubImporter(path).read_index().items]


def notes(path):
    return " | ".join(EpubImporter(path).read_index().notes)


def book(tmp_path):
    return make_epub(tmp_path / "lotm.epub", [
        ("front-cover.html", page("Cover", '<img src="cover.jpg"/>')),
        ("title-page.html", page("Information", "<h1>Lord of the Mysteries</h1><p>In the waves of steam and machinery…</p>")),
        ("text/page-0.html", chapter("Chapter 1: Crimson", ["Painful!", "How painful!"])),
        ("text/page-1.html", page("Notice", "<p>The author is on leave today.</p>")),
        ("text/page%202.html", chapter("Chapter 2: Situation", ["Tap! Tap! Tap!"])),
        ("notes.html", page("Notes", "<p>Made with an EPUB tool.</p>")),
    ])  # fmt: skip


def test_import_epub(tmp_path, clock):
    report = import_novel(tmp_path / "lotm", EpubImporter(book(tmp_path)), clock)
    assert report.inserted == 3 and not report.failed
    with NovelStore.open(tmp_path / "lotm") as store:
        [source] = store.sources()
        assert source.spec.backend == "import:epub" and source.spec.kind == Kind.OFFICIAL_EN
        assert store.item_refs(source.id) == {"OEBPS/text/page-0.html", "OEBPS/text/page-1.html", "OEBPS/text/page 2.html"}
        assert [c.key for c in store.chapters(source.id)] == [ChapterKey(1), ChapterKey(2)]  # the notice has no number
        assert store.meta.title == "Lord of the Mysteries (Web Novel)"
        assert store.meta.author == "Cuttlefish That Loves Diving"
        [first] = [c for c in store.selection() if c.key == ChapterKey(1)]
        version = store.read_version(first.version_id)
    assert version.title == "Chapter 1: Crimson"
    assert [b.text for b in version.blocks] == ["Painful!", "How painful!"]  # the heading echo is dropped
    left_out = " | ".join(report.notes)
    assert "Cover" in left_out and "Lord of the Mysteries" in left_out and "Notes" in left_out  # by title


def test_epub_spine_order_wins_over_file_names(tmp_path):
    path = make_epub(tmp_path / "b.epub", [
        ("b.html", chapter("Chapter 2: Second", ["Two."])),
        ("a.html", chapter("Chapter 1: First", ["One."])),
    ], spine=[1, 0])  # fmt: skip
    assert [title for _, title, _ in items(path)] == ["Chapter 1: First", "Chapter 2: Second"]


def test_toc_cuts_a_volume_heading_off_its_first_chapter(tmp_path):
    """Nine Star Hegemon: Volume 1's document opens with the volume <h1>, then Chapter 1's anchored <h2>."""
    volume = page("Section0001", '<h1>Volume 1: Dragon Soars</h1><h2 id="toc_1">Chapter 1 Memories of a Pill God</h2><p>Who am I?</p>')
    path = make_epub(tmp_path / "v.epub", [
        ("Text/Section0001.xhtml", volume),
        ("Text/Section0002.xhtml", chapter("Chapter 2 Despicable Scum", ["The liquid entered."])),
    ], toc=[
        ("Text/Section0001.xhtml", "Volume 1: Dragon Soars"),
        ("Text/Section0001.xhtml#toc_1", "Chapter 1 Memories of a Pill God"),
        ("Text/Section0002.xhtml", "Chapter 2 Despicable Scum"),
    ])  # fmt: skip
    assert items(path) == [
        ("OEBPS/Text/Section0001.xhtml#toc_1", "Chapter 1 Memories of a Pill God", 1),
        ("OEBPS/Text/Section0002.xhtml", "Chapter 2 Despicable Scum", 2),
    ]
    assert "dividers: Volume 1: Dragon Soars" in notes(path)


def test_toc_splits_a_document_holding_several_chapters(tmp_path, clock):
    both = page("x", '<h2 id="c1">Chapter 1: One</h2><p>First text.</p><h2 id="c2">Chapter 2: Two</h2><p>Second text.</p>')
    path = make_epub(tmp_path / "s.epub", [("both.html", both)], toc=[("both.html#c1", "Chapter 1: One"), ("both.html#c2", "Chapter 2: Two")])
    import_novel(tmp_path / "n", EpubImporter(path), clock)
    with NovelStore.open(tmp_path / "n") as store:
        texts = {s.key: [b.text for b in store.read_version(s.version_id).blocks] for s in store.selection()}
    assert texts == {ChapterKey(1): ["First text."], ChapterKey(2): ["Second text."]}


def test_headless_files_continue_the_chapter_before_them(tmp_path, clock):
    """Calibre splits long chapters into index_split_NNN files with no heading of their own."""
    path = make_epub(tmp_path / "c.epub", [
        ("split_000.html", chapter("Chapter 1: Long", ["Start of one."])),
        ("split_001.html", page("Book", "<p>Rest of one.</p>")),
        ("split_002.html", chapter("Chapter 2: Short", ["Two."])),
    ], toc=[("split_000.html", "Chapter 1: Long"), ("split_002.html", "Chapter 2: Short")])  # fmt: skip
    import_novel(tmp_path / "n", EpubImporter(path), clock)
    with NovelStore.open(tmp_path / "n") as store:
        [one, _] = store.selection()
        assert [b.text for b in store.read_version(one.version_id).blocks] == ["Start of one.", "Rest of one."]


def test_unlisted_headed_document_is_its_own_item(tmp_path):
    path = make_epub(tmp_path / "u.epub", [
        ("1.html", chapter("Chapter 1: A", ["One."])),
        ("note.html", chapter("Author's Note", ["Leave today."])),
        ("2.html", chapter("Chapter 2: B", ["Two."])),
    ], toc=[("1.html", "Chapter 1: A"), ("2.html", "Chapter 2: B")])  # fmt: skip
    assert [title for _, title, _ in items(path)] == ["Chapter 1: A", "Author's Note", "Chapter 2: B"]


def test_story_parts_outside_the_numbered_chapters_are_kept(tmp_path):
    path = make_epub(tmp_path / "p.epub", [
        ("syn.html", page("Synopsis", "<h1>Synopsis</h1><p>A long description of the novel.</p>")),
        ("pro.html", chapter("Prologue: About Religions", ["This is a continent filled with religions."])),
        ("1.html", chapter("Chapter 1: Start", ["One."])),
        ("aft.html", chapter("Afterword", ["Thanks for reading this far."])),
        ("credits.html", page("Credits", "<h1>Credits</h1><p>ePub conversion by someone.</p>")),
    ])  # fmt: skip
    assert [title for _, title, _ in items(path)] == ["Prologue: About Religions", "Chapter 1: Start", "Afterword"]
    assert "front/back matter entries: Synopsis, Credits" in notes(path)


def test_toc_labels_title_headless_documents(tmp_path):
    """The Grandmaster Strategist: no headings, the title is a <p>; the TOC names each chapter."""
    path = make_epub(tmp_path / "g.epub", [
        ("00001-Prologue.html", page("Unknown", "<p>Prologue</p><p>It really is a good painting.</p>")),
        ("00002.html", page("Unknown", "<p>Volume 1, Chapter 1: A Destitute Scholar</p><p>Text.</p>")),
    ], toc=[("00001-Prologue.html", "Prologue"), ("00002.html", "Volume 1, Chapter 1: A Destitute Scholar")])  # fmt: skip
    assert [(title, n) for _, title, n in items(path)] == [("Prologue", None), ("Volume 1, Chapter 1: A Destitute Scholar", 1)]


@pytest.mark.parametrize(
    ("title", "number"),
    [
        ("Chapter 12: Twelve", 12),
        ("第3章 开始", 3),
        ("502 Our Secret Weapon", 502),  # Superstars of Tomorrow
        ("1 Crimson", 1),
        ("#147 Chapter 147", 147),
        ("0000 awe-chapter-1", 1),  # A Will Eternal: the leading number counts from 0, the slug is the chapter
        ("Volume 2: Faceless", None),
        ("Prologue", None),
        ("3.5 Interlude", None),
    ],
)
def test_chapter_number(title, number):
    assert chapter_number(title) == number


def test_file_names_never_number_a_chapter(tmp_path):
    """Lord of the Mysteries 1-1429: 1427.xhtml is an empty watermark page with no title."""
    path = make_epub(tmp_path / "f.epub", [
        ("1426.xhtml", page("1426 In Modern Day 24", "<h1>1426 In Modern Day 24</h1><p>Text.</p>")),
        ("1427.xhtml", page("", "<h1></h1><p>Please go to to read the latest chapters for free</p>")),
        ("1428.xhtml", page("1428 In Modern Day 26", "<h1>1428 In Modern Day 26</h1><p>Text.</p>")),
    ])  # fmt: skip
    assert [n for _, _, n in items(path)] == [1426, None, 1428]


def test_utf16_and_gbk_documents_are_decoded(tmp_path):
    utf16 = chapter("Chapter 1: Wide", ["Text."]).replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
    gbk = chapter("第2章 中文", ["正文。"]).replace('encoding="UTF-8"', 'encoding="GBK"').encode("gbk")
    path = make_epub(tmp_path / "e.epub", [("a.html", utf16), ("b.html", gbk)])
    assert [n for _, _, n in items(path)] == [1, 2]


def test_a_missing_document_is_noted_not_fatal(tmp_path):
    path = make_epub(tmp_path / "m.epub", [("1.html", chapter("Chapter 1: A", ["One."]))], missing=["gone.html"])
    assert [n for _, _, n in items(path)] == [1]
    assert "1 spine documents missing from the EPUB: OEBPS/gone.html" in notes(path)


def test_chinese_epub_is_raw_zh(tmp_path):
    path = make_epub(tmp_path / "zh.epub", [("c.html", chapter("第1章 开始", ["正文。"]))], language="zh-CN")
    spec = EpubImporter(path).spec
    assert spec.kind == Kind.RAW_ZH and spec.lang == "zh"


def test_not_an_epub_is_an_error(tmp_path):
    (tmp_path / "x.epub").write_text("not a zip")
    with pytest.raises(ValueError, match="not an EPUB"):
        EpubImporter(tmp_path / "x.epub")


def test_epub_without_numbered_chapters_is_an_error(tmp_path):
    path = make_epub(tmp_path / "n.epub", [("a.html", page("Cover", "<p>Nothing here.</p>"))])
    with pytest.raises(ValueError, match="no numbered chapters"):
        EpubImporter(path)
