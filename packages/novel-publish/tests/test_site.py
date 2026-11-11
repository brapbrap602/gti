import json
import re
from importlib import resources

import pytest
from novel_core import (
    AlignmentRules,
    ChapterKey,
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
from novel_publish.site import build_site, fingerprint, novel_fingerprint


@pytest.fixture
def stores(tmp_path):
    """Opens novels by slug under tmp_path/data; all are closed at teardown."""
    opened: dict[str, NovelStore] = {}

    def make(slug: str, title: str = "Test Novel", **meta) -> NovelStore:
        opened[slug] = NovelStore.create(tmp_path / "data" / slug, NovelMeta(title, **meta))
        return opened[slug]

    yield make
    for store in opened.values():
        store.close()


@pytest.fixture
def site(tmp_path):
    return tmp_path / "site"


def add_source(store: NovelStore, name: str, kind: Kind = Kind.OFFICIAL_EN) -> int:
    return store.upsert_source(SourceSpec(f"custom:{name}", f"https://{name}.test/novel", "en", kind))


def add_chapters(store: NovelStore, source: int, titles: list[str], text: str = "text", blocks=None) -> list[str]:
    items = [SourceItem(f"/novel/{n}", n, t) for n, t in enumerate(titles, start=1)]
    store.record_index(source, items)
    for item in items:
        body = blocks or (Paragraph.of(f"{text} {item.title}"),)
        store.put_version(source, item.ref, NewVersion(item.title, body))
    return [i.ref for i in items]


def add_numbered(store: NovelStore, source: int, numbers) -> None:
    """Index chapters by number with refs that stay put as the index grows (add_chapters' refs are positional)."""
    items = [SourceItem(f"/novel/c{n}", i, f"Chapter {n}") for i, n in enumerate(numbers, start=1)]
    store.record_index(source, items)
    for item in items:
        store.put_version(source, item.ref, NewVersion(item.title, (Paragraph.of(f"text {item.title}"),)))


def chapters(n: int, first: int = 1) -> list[str]:
    return [f"Chapter {i}" for i in range(first, first + n)]


def page_files(site, slug: str) -> list[str]:
    return sorted(p.name for p in (site / "novels" / slug).glob("*.html"))


def read(site, slug: str, page: str) -> str:
    return (site / "novels" / slug / page).read_text(encoding="utf-8")


def anchors(html: str) -> list[str]:
    return re.findall(r'<article id="([^"]+)"', html)


def test_pages_of_50_numbers_with_library_cards(stores, site):
    store = stores("novel-a", "Novel A", author="Gen, Er")
    add_chapters(store, add_source(store, "a"), chapters(120))

    report = build_site({"novel-a": store}, site)

    assert page_files(site, "novel-a") == ["1-50.html", "101-150.html", "51-100.html"]
    assert report.novels[0].chapters == 120 and report.novels[0].pages_written == 3
    first = read(site, "novel-a", "1-50.html")
    assert anchors(first) == [f"c{i}" for i in range(1, 51)]
    assert "<title>Novel A Chs 1–50</title>" in first
    assert 'href="51-100.html" rel="next"' in first and 'rel="prev"' not in first
    fp = fingerprint()[:12]
    assert f'<link rel="stylesheet" href="../../assets/style.css?v={fp}">' in first
    assert f'<script src="../../assets/site.js?v={fp}" defer></script>' in first
    library = (site / "index.html").read_text(encoding="utf-8")
    assert "Novel A" in library and "Gen, Er" in library and "120 chapters" in library
    assert '<a class="book-part-link" href="novels/novel-a/101-150.html">Chs 101–120</a>' in library
    assert (site / "assets" / "style.css").exists() and (site / ".nojekyll").exists()


def test_site_labels_show_split_parts(stores, site):
    store = stores("bts")
    add_chapters(store, add_source(store, "a"), ["Chapter 523", "Chapter 524 (part 1)", "Chapter 524 (part 2): Gate"])

    build_site({"bts": store}, site)

    html = read(site, "bts", "501-550.html")
    assert anchors(html) == ["c523", "c524-1", "c524-2"]
    assert '<h2 class="chapter">Chapter 524 pt 2: Gate</h2>' in html
    assert "<title>Test Novel Chs 523–524 pt 2</title>" in html
    assert "Chs 523–524 pt 2" in (site / "index.html").read_text(encoding="utf-8")


def test_blocks_render_escaped(stores, site):
    store = stores("n")
    blocks = (
        Paragraph((Run("a <b> & "), Run("lean", em=True), Run("bold", strong=True))),
        Separator(),
        System("[Level up]"),
    )
    add_chapters(store, add_source(store, "a"), ["Chapter 1"], blocks=blocks)

    build_site({"n": store}, site)

    html = read(site, "n", "1-50.html")
    assert "<p>a &lt;b&gt; &amp; <em>lean</em><strong>bold</strong></p>" in html
    assert '<hr class="separator">' in html and '<p class="system">[Level up]</p>' in html


def test_second_build_writes_nothing(stores, site):
    store = stores("n")
    add_chapters(store, add_source(store, "a"), chapters(60))
    build_site({"n": store}, site)

    report = build_site({"n": store}, site)

    assert report.novels[0].pages_written == 0


def test_new_chapters_rebuild_their_page_and_its_neighbours(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    add_chapters(store, a, chapters(60))
    build_site({"n": store}, site)

    add_chapters(store, a, chapters(110))  # 61-110: page 51 grows, page 101 is new
    report = build_site({"n": store}, site)

    assert page_files(site, "n") == ["1-50.html", "101-150.html", "51-100.html"]
    # page 51 (new chapters, new next link), page 101, and page 1, whose Next label names page 51's range
    assert report.novels[0].pages_written == 3
    assert next_page(read(site, "n", "1-50.html")) == ("51-100.html", "Next: Chs 51–100 →")
    assert next_page(read(site, "n", "51-100.html")) == ("101-150.html", "Next: Chs 101–110 →")


def test_select_switch_source_single_row(stores, site):
    store = stores("n")
    a, b = add_source(store, "a"), add_source(store, "b")
    add_chapters(store, a, chapters(5), text="from A")
    build_site({"n": store}, site)
    add_chapters(store, b, chapters(5), text="from B")

    store.set_priority([b, a])
    build_site({"n": store}, site)

    rows = [r for r in store.outputs(OutputKind.SITE) if r.built_key == ChapterKey(5)]
    assert [(r.source_id, r.artifact) for r in rows] == [(b, "novels/n/1-50.html")]
    html = read(site, "n", "1-50.html")
    assert "from B Chapter 5" in html and "from A" not in html


def test_site_prune_moved_key(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    refs = add_chapters(store, a, ["Chapter 1898", "Chapter 1899"])
    build_site({"n": store}, site)

    store.set_alignment(a, AlignmentRules(items={refs[1]: ChapterKey(1897)}))
    build_site({"n": store}, site)

    assert anchors(read(site, "n", "1851-1900.html")) == ["c1897", "c1898"]
    assert sorted(r.built_key.number for r in store.outputs(OutputKind.SITE)) == [1897, 1898]


def test_page_left_empty_is_deleted_and_neighbour_relinked(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    refs = add_chapters(store, a, chapters(51))
    build_site({"n": store}, site)

    store.set_alignment(a, AlignmentRules(items={refs[50]: ChapterKey(50, 1)}))  # 51 joins page 1 as 50 pt 1
    report = build_site({"n": store}, site)

    assert page_files(site, "n") == ["1-50.html"]
    assert report.novels[0].pages_deleted == 1
    html = read(site, "n", "1-50.html")
    assert "c50-1" in html and 'rel="next"' not in html
    assert [r.built_key for r in store.outputs(OutputKind.SITE)][-1] == ChapterKey(50, 1)


def test_missing_page_file_is_rebuilt(stores, site):
    store = stores("n")
    add_chapters(store, add_source(store, "a"), chapters(60))
    build_site({"n": store}, site)
    (site / "novels" / "n" / "51-100.html").unlink()

    build_site({"n": store}, site)

    assert anchors(read(site, "n", "51-100.html")) == [f"c{i}" for i in range(51, 61)]


def library_titles(site) -> list[str]:
    return re.findall(r'<span class="row-title">([^<]+)</span>', (site / "index.html").read_text(encoding="utf-8"))


def test_novels_with_nothing_to_read_are_left_off(stores, site):
    zh, empty, n = stores("raw", "修真聊天群"), stores("empty", "Empty Novel"), stores("n")
    add_chapters(zh, add_source(zh, "zh", Kind.RAW_ZH), ["第1章"])
    add_chapters(n, add_source(n, "a"), chapters(1))

    report = build_site({"raw": zh, "empty": empty, "n": n}, site)

    assert {b.slug: b.listed for b in report.novels} == {"empty": False, "n": True, "raw": False}
    library = (site / "index.html").read_text(encoding="utf-8")
    assert "修真聊天群" not in library and "Empty Novel" not in library and "raw only" not in library
    assert library_titles(site) == ["Test Novel"]
    assert not (site / "novels" / "raw").exists() and not (site / "novels" / "empty").exists()


def test_a_novel_emptied_of_chapters_leaves_the_site_and_its_records(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    refs = add_chapters(store, a, chapters(60))
    build_site({"n": store}, site)

    store.set_alignment(a, AlignmentRules(skip=frozenset(refs)))
    report = build_site({"n": store}, site)

    assert not report.novels[0].listed and report.novels[0].pages_deleted == 2
    assert not (site / "novels" / "n").exists() and library_titles(site) == []
    assert not store.outputs(OutputKind.SITE)
    plan = store.plan_build(OutputKind.SITE, novel_fingerprint(store.meta))
    assert not plan.to_build and not plan.to_prune


def test_the_library_lists_novels_by_title(stores, site):
    novels = {slug: stores(slug, title) for slug, title in (("n", "Test Novel"), ("z-first", "Alpha Tale"), ("b", "beta"))}
    for store in novels.values():
        add_chapters(store, add_source(store, "a"), chapters(1))

    build_site(novels, site)

    assert library_titles(site) == ["Alpha Tale", "beta", "Test Novel"]


def test_a_novel_without_an_author_shows_no_author(stores, site):
    store = stores("n", author="<unknown>")
    add_chapters(store, add_source(store, "a"), chapters(1))

    build_site({"n": store}, site)

    library = (site / "index.html").read_text(encoding="utf-8")
    assert 'class="row-author"' not in library and "&lt;unknown&gt;" not in library


def test_an_empty_library_says_so_without_admin_instructions(stores, site):
    zh = stores("raw", "修真聊天群")
    add_chapters(zh, add_source(zh, "zh", Kind.RAW_ZH), ["第1章"])

    build_site({"raw": zh}, site)

    library = (site / "index.html").read_text(encoding="utf-8")
    assert "No novels yet." in library and "nov import" not in library and "All novels" not in library


def test_removed_novel_folder_is_deleted(stores, site):
    a, b = stores("a"), stores("b")
    for store in (a, b):
        add_chapters(store, add_source(store, "x"), chapters(1))
    build_site({"a": a, "b": b}, site)

    build_site({"a": a}, site)

    assert not (site / "novels" / "b").exists() and (site / "novels" / "a").exists()


def test_output_is_deterministic(stores, tmp_path):
    novels = {slug: stores(slug, title) for slug, title in (("n", "Test Novel"), ("z-first", "Alpha Tale"), ("b", "beta"))}
    for store in novels.values():
        add_chapters(store, add_source(store, "a"), chapters(3))
    build_site(novels, tmp_path / "one")
    build_site(novels, tmp_path / "two", force=True)

    for name in ("index.html", "novels/n/1-50.html"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()


def toc(site, slug: str) -> dict:
    return json.loads((site / "novels" / slug / "toc.json").read_text(encoding="utf-8"))


def test_toc_json_lists_every_page_and_chapter(stores, tmp_path):
    store = stores("n")
    add_chapters(store, add_source(store, "a"),
                 ["Chapter 1", "Chapter 2", "Chapter 3", "Chapter 51", "Chapter 52 (part 1)", "Chapter 52 (part 2)"])

    build_site({"n": store}, tmp_path / "one")
    build_site({"n": store}, tmp_path / "two", force=True)

    assert toc(tmp_path / "one", "n") == {"pages": [
        {"file": "1-50.html", "chapters": [{"n": 1, "a": "c1"}, {"n": 2, "a": "c2"}, {"n": 3, "a": "c3"}]},
        {"file": "51-100.html", "chapters": [{"n": 51, "a": "c51"}, {"n": 52, "a": "c52-1"}, {"n": 52, "a": "c52-2"}]},
    ]}
    one, two = (d / "novels" / "n" / "toc.json" for d in (tmp_path / "one", tmp_path / "two"))
    assert one.read_bytes() == two.read_bytes()


def test_toc_json_goes_when_a_novel_has_no_pages_left(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    refs = add_chapters(store, a, chapters(2))
    build_site({"n": store}, site)

    store.set_alignment(a, AlignmentRules(skip=frozenset(refs)))
    build_site({"n": store}, site)

    assert page_files(site, "n") == [] and not (site / "novels" / "n" / "toc.json").exists()


def test_toc_json_goes_with_a_removed_novel(stores, site):
    a, b = stores("a"), stores("b")
    for store in (a, b):
        add_chapters(store, add_source(store, "x"), chapters(1))
    build_site({"a": a, "b": b}, site)
    assert (site / "novels" / "b" / "toc.json").exists()

    build_site({"a": a}, site)

    assert not (site / "novels" / "b").exists()


def last_marker_chapter(html: str) -> str:
    """The id of the article that holds the page's only `id="last"` marker, which must be its first child."""
    assert html.count('id="last"') == 1
    return re.search(r'<article id="([^"]+)"[^>]*>\s*<span id="last"></span>', html).group(1)


def test_cross_page_links_carry_no_chapter_anchors(stores, site):
    store = stores("n")
    add_chapters(store, add_source(store, "a"), chapters(3) + ["Chapter 51", "Chapter 101"])

    build_site({"n": store}, site)

    first, middle, last = (read(site, "n", p) for p in ("1-50.html", "51-100.html", "101-150.html"))
    assert last_marker_chapter(first) == "c3"
    assert 'data-next-page="51-100.html"' in first and "data-prev-page" not in first
    assert 'data-prev-page="1-50.html#last"' in middle and 'data-next-page="101-150.html"' in middle
    assert 'data-prev-page="51-100.html#last"' in last and "data-next-page" not in last


def test_filling_a_page_gap_rewrites_that_page_and_the_labels_naming_it(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    add_numbered(store, a, [*range(1, 49), 51, 101])
    build_site({"n": store}, site)
    third = read(site, "n", "101-150.html")

    add_numbered(store, a, [*range(1, 52), 101])  # 49 and 50 arrive; 51 and 101 are unchanged
    report = build_site({"n": store}, site)

    assert report.novels[0].pages_written == 2  # page 1, and page 51, whose back link names page 1's range
    assert last_marker_chapter(read(site, "n", "1-50.html")) == "c50"
    assert 'rel="prev">&larr; Chs 1–50</a>' in read(site, "n", "51-100.html")
    assert read(site, "n", "101-150.html") == third  # two pages away: untouched


def test_hidden_attribute_always_hides():
    """Reader controls are rendered `hidden` until site.js shows them; author CSS must not override that."""
    css = resources.files("novel_publish").joinpath("static/style.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", css)


def test_page_opens_on_chapter_text_with_chapters_in_a_dialog(stores, site):
    store = stores("n")
    add_chapters(store, add_source(store, "a"), chapters(3) + ["Chapter 51"])

    build_site({"n": store}, site)

    html = read(site, "n", "1-50.html")
    outside_noscript = re.sub(r"<noscript>.*?</noscript>", "", html, flags=re.S)
    assert '<nav class="toc"' not in outside_noscript and '<nav class="toc"' in html
    assert 'class="library-header"' not in html
    dialog = re.search(r'<dialog id="chapters".*?</dialog>', html, re.S).group(0)
    assert re.findall(r'<li><a href="#(c\d+)">', dialog) == ["c1", "c2", "c3"]
    assert html.count('rel="next"') == 2  # the dialog's page links and the one page nav, after the text
    assert html.index('class="page-nav"') > html.index("</main>")


def test_reader_controls_start_hidden(stores, site):
    store = stores("n")
    add_chapters(store, add_source(store, "a"), chapters(2))

    build_site({"n": store}, site)

    html = read(site, "n", "1-50.html")
    assert re.search(r'<header class="reader-bar" hidden', html)
    assert re.search(r'<form class="goto" hidden', html)


def test_library_rows_hold_go_to_and_every_page_under_a_hidden_continue_row(stores, site):
    novels = {slug: stores(slug, title) for slug, title in (("n", "Test Novel"), ("z-first", "Alpha Tale"), ("b", "beta"))}
    for store in novels.values():
        add_chapters(store, add_source(store, "a"), chapters(60))

    build_site(novels, site)

    library = (site / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<section class="continue-row" hidden', library)
    assert re.search(r'<h2 id="all-h"[^>]*>All novels \(3\)</h2>', library)
    rows = re.findall(r'(<li class="novel-row"[^>]*>)(.*?)</li>', library, re.S)
    assert len(rows) == 3
    tag, body = next((t, b) for t, b in rows if 'data-slug="n"' in t)
    assert 'data-toc="novels/n/toc.json"' in tag and 'data-title="Test Novel"' in tag
    details = re.search(r"<details>\s*<summary>(.*?)</summary>(.*?)</details>", body, re.S)
    assert '<span class="row-title">Test Novel</span>' in details.group(1) and "60 chapters" in details.group(1)
    assert re.search(r'<form class="goto" hidden', details.group(2))
    assert re.findall(r'href="([^"]+)"', details.group(2)) == ["novels/n/1-50.html", "novels/n/51-100.html"]


def test_a_title_edit_rewrites_that_novels_pages_once(stores, site):
    a, b = stores("a", "Old Title"), stores("b", "Other")
    for store in (a, b):
        add_chapters(store, add_source(store, "x"), chapters(60))
    build_site({"a": a, "b": b}, site)

    a.update_meta(title="New Title")
    first = build_site({"a": a, "b": b}, site)
    second = build_site({"a": a, "b": b}, site)

    assert [n.pages_written for n in first.novels] == [2, 0]
    assert "<title>New Title Chs 1–50</title>" in read(site, "a", "1-50.html")
    assert "<title>New Title Chs 51–60</title>" in read(site, "a", "51-100.html")
    assert [n.pages_written for n in second.novels] == [0, 0]


def test_an_author_edit_rewrites_only_the_library(stores, site):
    store = stores("a", "A", author="Old Author")
    add_chapters(store, add_source(store, "x"), chapters(3))
    build_site({"a": store}, site)

    store.update_meta(author="New Author")
    report = build_site({"a": store}, site)

    assert report.novels[0].pages_written == 0
    library = (site / "index.html").read_text(encoding="utf-8")
    assert "New Author" in library and "Old Author" not in library


def next_page(html: str) -> tuple[str, str] | None:
    """The page end's Next button: (href, text), or None."""
    end = re.search(r'<nav class="page-end".*?</nav>', html, re.S).group(0)
    m = re.search(r'<a class="next-page" href="([^"]+)" rel="next">([^<]+)</a>', end)
    return (m.group(1), m.group(2).replace("&rarr;", "→")) if m else None


def caught_up(html: str) -> str | None:
    m = re.search(r'<p class="caught-up">([^<]+)</p>', html)
    return m.group(1).replace("&#39;", "'") if m else None


def test_a_page_ends_with_a_next_button_naming_the_chapters(stores, site):
    store = stores("n")
    add_chapters(store, add_source(store, "a"), chapters(3) + ["Chapter 51", "Chapter 52", "Chapter 53"])

    build_site({"n": store}, site)

    first, second = read(site, "n", "1-50.html"), read(site, "n", "51-100.html")
    assert next_page(first) == ("51-100.html", "Next: Chs 51–53 →") and caught_up(first) is None
    end = re.search(r'<nav class="page-end".*?</nav>', second, re.S).group(0)
    assert 'href="1-50.html" rel="prev">&larr; Chs 1–3</a>' in end and 'href="../../index.html">Library</a>' in end
    assert next_page(second) is None


def test_more_chapters_on_the_next_page_refresh_the_next_label(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    add_numbered(store, a, [1, 2, 3, 51, 52, 53])
    build_site({"n": store}, site)

    add_numbered(store, a, [1, 2, 3, 51, 52, 53, 54])
    build_site({"n": store}, site)

    assert next_page(read(site, "n", "1-50.html")) == ("51-100.html", "Next: Chs 51–54 →")


def test_the_last_page_says_you_are_caught_up(stores, site):
    store = stores("n")
    add_chapters(store, add_source(store, "a"), [*chapters(49), "Chapter 50 (part 1)", "Chapter 50 (part 2)"])

    build_site({"n": store}, site)

    html = read(site, "n", "1-50.html")
    assert caught_up(html) == "You're caught up: chapter 50 pt 2 is the latest."
    assert next_page(html) is None


def test_a_page_that_becomes_last_says_caught_up(stores, site):
    store = stores("n")
    a = add_source(store, "a")
    refs = add_chapters(store, a, chapters(3) + ["Chapter 51"])
    build_site({"n": store}, site)
    assert caught_up(read(site, "n", "1-50.html")) is None

    store.set_alignment(a, AlignmentRules(skip=frozenset(refs[3:])))
    build_site({"n": store}, site)

    assert caught_up(read(site, "n", "1-50.html")) == "You're caught up: chapter 3 is the latest."
