import re
import zipfile
from dataclasses import replace

import pytest
from novel_core import (
    AlignmentRules,
    Image,
    Kind,
    NewVersion,
    NovelMeta,
    NovelStore,
    OutputKind,
    Paragraph,
    Run,
    Separator,
    SourceItem,
    SourceSpec,
    System,
)
from novel_publish.epub import build_epub

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


@pytest.fixture
def store(tmp_path):
    with NovelStore.create(tmp_path / "data" / "novel-a", NovelMeta("Novel A", author="Gen, Er")) as s:
        yield s


@pytest.fixture
def out(tmp_path):
    return tmp_path / "epub"


def add_source(store: NovelStore, name: str = "a") -> int:
    return store.upsert_source(SourceSpec(f"custom:{name}", f"https://{name}.test/novel", "en", Kind.OFFICIAL_EN))


def add_chapters(store: NovelStore, source: int, titles: list[str], text: str = "text", blocks=None) -> list[str]:
    items = [SourceItem(f"/novel/{n}", n, t) for n, t in enumerate(titles, start=1)]
    store.record_index(source, items)
    for item in items:
        body = blocks or (Paragraph.of(f"{text} {item.title}"),)
        store.put_version(source, item.ref, NewVersion(item.title, body))
    return [i.ref for i in items]


def chapters(n: int, first: int = 1) -> list[str]:
    return [f"Chapter {i}" for i in range(first, first + n)]


def files(out) -> list[str]:
    return sorted(p.name for p in out.glob("*.epub"))


def opf(path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("EPUB/content.opf").decode()


def chapter(path, name: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(f"EPUB/{name}").decode()


def spine(path) -> list[str]:
    return re.findall(r'<itemref idref="([^"]+)"', opf(path))


def test_epub_metadata(store, out):
    add_chapters(store, add_source(store), chapters(120))

    report = build_epub(store, out, "novel-a", cover=PNG)

    assert files(out) == ["novel-a_0001-0100.epub", "novel-a_0101-0200.epub"]  # no "Title - Author" name
    assert report.volumes == 2 and len(report.built) == 2
    meta = opf(out / "novel-a_0101-0200.epub")
    assert "<dc:title>Novel A 101–120</dc:title>" in meta
    assert '<dc:creator id="creator">Gen, Er</dc:creator>' in meta
    assert "<dc:language>en</dc:language>" in meta
    assert '<meta name="calibre:series" content="Novel A">' in meta
    assert '<meta name="calibre:series_index" content="2">' in meta
    assert '<meta refines="#series" property="group-position">2</meta>' in meta
    assert 'href="cover.png"' in meta and spine(out / "novel-a_0101-0200.epub")[:2] == ["cover", "nav"]


def test_identifier_is_stable_per_volume(store, tmp_path):
    add_chapters(store, add_source(store), chapters(3))
    build_epub(store, tmp_path / "one", "novel-a")
    build_epub(store, tmp_path / "two", "novel-a", force=True)

    ident = re.compile(r"<dc:identifier[^>]*>([^<]+)<")
    first = ident.search(opf(tmp_path / "one" / "novel-a_0001-0100.epub")).group(1)
    assert first.startswith("urn:uuid:")
    assert first == ident.search(opf(tmp_path / "two" / "novel-a_0001-0100.epub")).group(1)


def test_chapters_in_key_order_with_part_labels(store, out):
    add_chapters(store, add_source(store), ["Chapter 523", "Chapter 524 (part 1)", "Chapter 524 (part 2): Gate"])

    build_epub(store, out, "novel-a")

    book = out / "novel-a_0501-0600.epub"
    assert spine(book) == ["nav", "chapter_0", "chapter_1", "chapter_2"]
    assert '<h2 class="chapter">Chapter 524 pt 2: Gate</h2>' in chapter(book, "c524-2.xhtml")
    assert "<dc:title>Novel A 523–524 pt 2</dc:title>" in opf(book)
    nav = chapter(book, "nav.xhtml")
    assert nav.index("Chapter 523") < nav.index("Chapter 524 pt 1") < nav.index("Chapter 524 pt 2: Gate")


def test_blocks_render_without_remote_images(store, out):
    blocks = (
        Paragraph((Run("a <b> & "), Run("lean", em=True))),
        Separator(),
        System("[Level up]"),
        Image("https://s.w.org/images/core/emoji/13.1.0/svg/2744.svg", "❄"),
        Image("https://ads.test/banner.gif"),
    )
    add_chapters(store, add_source(store), ["Chapter 1"], blocks=blocks)

    build_epub(store, out, "novel-a")

    html = chapter(out / "novel-a_0001-0100.epub", "c1.xhtml")
    assert "<p>a &lt;b&gt; &amp; <em>lean</em></p>" in html
    assert '<hr class="separator"/>' in html and '<p class="system">[Level up]</p>' in html
    assert "<p>❄</p>" in html and "<img" not in html and "ads.test" not in html


def test_second_build_writes_nothing(store, out):
    add_chapters(store, add_source(store), chapters(150))
    build_epub(store, out, "novel-a")

    assert build_epub(store, out, "novel-a").built == ()


def test_changed_chapter_rebuilds_only_its_volume(store, out):
    a = add_source(store)
    add_chapters(store, a, chapters(150))
    build_epub(store, out, "novel-a")
    second = (out / "novel-a_0101-0200.epub").read_bytes()

    store.put_version(a, "/novel/42", NewVersion("Chapter 42", (Paragraph.of("revised"),)))
    report = build_epub(store, out, "novel-a")

    assert [(r.start, r.end) for r in report.built] == [(1, 100)]
    assert "revised" in chapter(out / "novel-a_0001-0100.epub", "c42.xhtml")
    assert (out / "novel-a_0101-0200.epub").read_bytes() == second


def test_missing_file_is_rebuilt(store, out):
    add_chapters(store, add_source(store), chapters(150))
    build_epub(store, out, "novel-a")
    (out / "novel-a_0101-0200.epub").unlink()

    report = build_epub(store, out, "novel-a")

    assert [r.start for r in report.built] == [101] and len(files(out)) == 2


def test_new_metadata_or_cover_rebuilds_every_volume(store, out):
    add_chapters(store, add_source(store), chapters(150))
    build_epub(store, out, "novel-a")

    store.set_meta(replace(store.meta, author="Er Gen"))
    assert len(build_epub(store, out, "novel-a").built) == 2
    assert len(build_epub(store, out, "novel-a", cover=PNG).built) == 2
    assert build_epub(store, out, "novel-a", cover=PNG).built == ()


def test_unselected_volume_is_deleted_and_rows_pruned(store, out):
    a = add_source(store)
    refs = add_chapters(store, a, chapters(150))
    build_epub(store, out, "novel-a")

    store.set_alignment(a, AlignmentRules(skip=frozenset(refs[100:])))
    report = build_epub(store, out, "novel-a")

    assert files(out) == ["novel-a_0001-0100.epub"]
    assert report.deleted == ("novel-a_0101-0200.epub",) and report.volumes == 1
    assert max(r.built_key.number for r in store.outputs(OutputKind.EPUB)) == 100


def test_new_volume_size_replaces_the_files(store, out):
    add_chapters(store, add_source(store), chapters(150))
    build_epub(store, out, "novel-a")

    report = build_epub(store, out, "novel-a", size=500)

    assert files(out) == ["novel-a_0001-0500.epub"]
    assert set(report.deleted) == {"novel-a_0001-0100.epub", "novel-a_0101-0200.epub"}
