import sqlite3

import pytest
from novel_core import (
    AlignmentRules,
    ChapterKey,
    Duplicate,
    Inserted,
    ItemStatus,
    KeyRange,
    Kind,
    NewVersion,
    NovelMeta,
    NovelStore,
    OutputKind,
    Paragraph,
    PinFallback,
    RangeOverride,
    RawChapter,
    SourceItem,
    SourceSpec,
    StoreError,
    Unchanged,
    VolumeRow,
    url_ref,
)
from novel_core.selection import Pin


def titles(*numbers) -> list[str]:
    return [f"Chapter {n}" for n in numbers]


def build_all(store, kind=OutputKind.SITE, fingerprint="f1"):
    for s in store.selection():
        store.record_output(kind, s, fingerprint, f"{kind}/{s.key.label}")


def keys(selected) -> list[str]:
    return [s.key.label for s in selected]


# -- lifecycle ----------------------------------------------------------------


def test_reopen_keeps_data_and_refuses_double_create(tmp_path, book):
    a = book.source("a")
    book.chapters(a, titles(1, 2))
    book.store.close()
    with pytest.raises(FileExistsError):
        NovelStore.create(tmp_path / "novel", NovelMeta("again"))
    with NovelStore.open(tmp_path / "novel") as reopened:
        assert keys(reopened.selection()) == ["1", "2"]
        assert reopened.meta.title == "Test Novel"
    with pytest.raises(FileNotFoundError):
        NovelStore.open(tmp_path / "missing")


# -- selection ----------------------------------------------------------------


def test_select_priority(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, titles(5))
    book.chapters(b, titles(5))
    book.store.set_priority([b, a])
    assert book.picked() == {"5": b}


def test_priority_lists_unranked_sources_after_the_ranked_ones(book):
    a, b, c = book.source("a"), book.source("b"), book.source("c")
    assert book.store.priority() == (a, b, c)
    book.store.set_priority([c])
    assert book.store.priority() == (c, a, b)


def test_select_pin_range(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, titles(*range(8, 23)))
    book.chapters(b, titles(*range(8, 23)))
    book.store.set_priority([a, b])
    book.store.set_pin(KeyRange(10, 20), b)
    picked = book.picked()
    assert [picked[n] for n in ("9", "10", "20", "21")] == [a, b, b, a]


def test_select_never_raw(book):
    raw = book.source("raw", Kind.RAW_ZH)
    book.chapters(raw, ["第7章"])
    assert book.store.selection() == ()
    assert book.store.check().raw_only == (7,)


def test_select_fallback(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, titles(1, 2, 4))
    book.chapters(b, titles(1, 2, 3, 4))
    book.store.set_priority([a, b])
    assert book.picked() == {"1": a, "2": a, "3": b, "4": a}


def test_select_mixed_parts(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, ["Chapter 524 (1)", "Chapter 524 (2)"])
    book.chapters(b, titles(524))
    book.store.set_priority([b, a])
    assert book.picked() == {"524": b}
    assert book.store.check().mixed_parts == (524,)


def test_select_mixed_parts_a_first(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, ["Chapter 524 (1)", "Chapter 524 (2)"])
    book.chapters(b, titles(524))
    book.store.set_priority([a, b])
    assert book.picked() == {"524 pt 1": a, "524 pt 2": a}


def test_lone_part_suffix_is_not_a_split(book):
    # Barbarian / Mount Hua: "(2)" numbers an arc, and every chapter has its own number.
    a = book.source("a")
    book.chapters(a, ["Chapter 55 The Forest (2)", "Chapter 56 The Forest (3)", "Chapter 57 Rules (1)"])
    assert keys(book.store.selection()) == ["55", "56", "57"]


def test_parts_split_only_numbers_they_share(book):
    a = book.source("a")
    book.chapters(a, ["Chapter 183 (part 3)", "Chapter 184 (part 1)", "Chapter 184 (part 2)", "Chapter 185"])
    assert keys(book.store.selection()) == ["183", "184 pt 1", "184 pt 2", "185"]


def test_part_zero_dropped_when_same_source_has_parts(book):
    a = book.source("a")
    book.chapters(a, ["Chapter 524", "Chapter 524 (1)", "Chapter 524 (2)"])
    assert keys(book.store.selection()) == ["524 pt 1", "524 pt 2"]


def test_placed_part_is_an_extra_beside_the_whole_chapter(book):
    # BTS: an unnumbered side story posted after 852, placed there with `nov align item`.
    a, b = book.source("a"), book.source("b")
    refs = book.chapters(a, ["Chapter 852", "Side Story (Part One)", "Chapter 853"])
    book.chapters(b, titles(852, 853))
    book.store.set_alignment(a, AlignmentRules(items={refs[1]: ChapterKey(852, 1)}))
    book.store.set_priority([a, b])
    assert book.picked() == {"852": a, "852 pt 1": a, "853": a}
    report = book.store.check()
    assert report.mixed_parts == () and report.unmapped == ()


def test_placed_part_on_a_split_number_still_drops_part_zero(book):
    a = book.source("a")
    refs = book.chapters(a, ["Chapter 524", "Chapter 524 (1)", "Chapter 524 part two"])
    book.store.set_alignment(a, AlignmentRules(items={refs[2]: ChapterKey(524, 2)}))
    assert keys(book.store.selection()) == ["524 pt 1", "524 pt 2"]


def test_pin_part0_vs_parts(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, ["Chapter 524 (1)", "Chapter 524 (2)"])
    book.chapters(b, titles(524))
    book.store.set_priority([a, b])
    book.store.set_pin(KeyRange(524, 524), b)
    assert book.picked() == {"524": b}


def test_pin_missing_source(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, titles(*range(10, 21)))
    book.chapters(b, titles(*(n for n in range(10, 21) if n != 15)))
    book.store.set_priority([a, b])
    book.store.set_pin(KeyRange(10, 20), b)
    picked = book.picked()
    assert picked["15"] == a and picked["14"] == b
    assert book.store.check().pin_fallbacks == (PinFallback(15, b),)


def test_pin_raw_rejected(book):
    a, raw = book.source("a"), book.source("raw", Kind.RAW_ZH)
    book.chapters(a, titles(1))
    book.chapters(raw, ["第1章"])
    with pytest.raises(StoreError, match="raw-zh"):
        book.store.set_pin(KeyRange(1, 1), raw)
    assert book.picked() == {"1": a}
    assert book.store.check().pin_fallbacks == ()


def test_later_pin_wins_where_pins_overlap(book):
    a, b, c = book.source("a"), book.source("b"), book.source("c")
    for s in (a, b, c):
        book.chapters(s, titles(1, 2, 3))
    book.store.set_pin(KeyRange(1, 3), b)
    book.store.set_pin(KeyRange(2, 2), c)
    assert book.picked() == {"1": b, "2": c, "3": b}


def test_unpin_returns_numbers_to_priority_and_keeps_the_rest(book):
    a, b, c = book.source("a"), book.source("b"), book.source("c")
    for s in (a, b, c):
        book.chapters(s, titles(1, 2, 3, 4, 5))
    book.store.set_pin(KeyRange(1, 5), b)
    book.store.set_pin(KeyRange(4, 4), c)
    left = book.store.unpin(KeyRange(2, 3))
    assert left == (Pin(KeyRange(1, 1), b), Pin(KeyRange(4, 5), b), Pin(KeyRange(4, 4), c))
    assert book.picked() == {"1": b, "2": a, "3": a, "4": c, "5": b}  # the later pin still wins on 4
    assert book.store.view().pins == left


def test_unpin_where_nothing_is_pinned_is_refused(book):
    a, b = book.source("a"), book.source("b")
    book.store.set_pin(KeyRange(10, 20), b)
    with pytest.raises(StoreError, match="nothing in 1-9 is pinned"):
        book.store.unpin(KeyRange(1, 9))
    assert book.store.unpin(KeyRange(1, 30)) == ()


# -- versions -----------------------------------------------------------------


def test_put_idempotent(book):
    a = book.source("a")
    [r] = book.chapters(a, titles(1), text="same")
    again = book.store.put_version(a, r, book.version("same Chapter 1"))
    assert isinstance(again, Unchanged)
    assert again.version_id == book.store.selection()[0].version_id


def test_put_changed(book):
    a = book.source("a")
    [r] = book.chapters(a, titles(1))
    first = book.store.selection()[0].version_id
    result = book.store.put_version(a, r, book.version("edited"))
    assert isinstance(result, Inserted) and result.version_id != first
    assert book.store.selection()[0].version_id == result.version_id
    assert book.store.read_version(first).blocks == (Paragraph.of("text Chapter 1"),)  # old text kept


def test_put_revert(book):
    a = book.source("a")
    [r] = book.store.record_index(a, [SourceItem("/c/1", 1, "Chapter 1")]).added
    text_a = book.store.put_version(a, r, book.version("A"))
    text_b = book.store.put_version(a, r, book.version("B"))
    back = book.store.put_version(a, r, book.version("A"))
    assert isinstance(text_b, Inserted) and isinstance(back, Unchanged)
    assert back.version_id == text_a.version_id
    assert book.store.selection()[0].version_id == text_a.version_id


def test_put_requires_indexed_item(book):
    a = book.source("a")
    with pytest.raises(StoreError, match="record_index first"):
        book.store.put_version(a, "/nope", book.version("x"))


def test_raw_stored_once_per_distinct_raw(tmp_path, book):
    a = book.source("a")
    [r] = book.store.record_index(a, [SourceItem("/c/1", 1, "Chapter 1")]).added
    page = RawChapter("<p>one</p>")
    book.store.put_version(a, r, NewVersion("T", (Paragraph.of("one"),), raw=page))
    book.store.put_version(a, r, NewVersion("T", (Paragraph.of("one!"),), raw=page))
    book.store.put_version(a, r, NewVersion("T", (Paragraph.of("two"),), raw=RawChapter("<p>two</p>")))
    files = list((tmp_path / "novel" / "raw" / str(a)).iterdir())
    assert len(files) == 2 and all(f.name.endswith(".html.zst") for f in files)


# -- alignment ----------------------------------------------------------------


def test_align_offset(book):
    a = book.source("a")
    items = [SourceItem(f"/c/x{i}", i, f"Notice {i}") for i in range(1, 7)]
    items.append(SourceItem("/c/x7", 7, "Chapter 5"))
    book.store.record_index(a, items)
    book.store.put_version(a, "/c/x7", book.version("t"))
    book.store.set_alignment(a, AlignmentRules(offset=1))
    assert keys(book.store.selection()) == ["6"]


def test_align_override_precedence(book):
    a = book.source("a")
    r1000, r1899, r3165 = book.chapters(a, titles(1000, 1899, 3165))
    diff = book.store.set_alignment(
        a,
        AlignmentRules(offset=1, ranges=(RangeOverride(1897, 3166, -2),), items={r3165: ChapterKey(3200)}),
    )
    got = {s.item_ref: s.key.number for s in book.store.selection()}
    assert got == {r1000: 1001, r1899: 1897, r3165: 3200}
    assert {m.item_ref: (m.old, m.new) for m in diff.moved} == {
        r1000: (ChapterKey(1000), ChapterKey(1001)),
        r1899: (ChapterKey(1899), ChapterKey(1897)),
        r3165: (ChapterKey(3165), ChapterKey(3200)),
    }


def test_align_unnumbered(book):
    a = book.source("a")
    prologue, side, _ = book.chapters(a, ["Prologue", "Side story: X", "Chapter 1"])
    assert {n.item_ref for n in book.store.check().unmapped} == {prologue, side}
    book.store.set_alignment(a, AlignmentRules(items={prologue: ChapterKey(0)}))
    assert keys(book.store.selection()) == ["0", "1"]
    assert {n.item_ref for n in book.store.check().unmapped} == {side}


def test_positional_slug_is_not_a_chapter_number(book):
    # freewebnovel numbers pages by position: /chapter-1370 is a translator post titled "2025.10.29".
    a = book.source("a")
    items = [SourceItem("/n/chapter-1369", 1, "Chapter 1353: Xu", ref_numbered=False),
             SourceItem("/n/chapter-1370", 2, "2025.10.29", ref_numbered=False)]  # fmt: skip
    book.store.record_index(a, items)
    for item in items:
        book.store.put_version(a, item.ref, book.version(item.title))
    assert keys(book.store.selection()) == ["1353"]
    assert [n.title for n in book.store.check().unmapped] == ["2025.10.29"]


def test_align_dup(book):
    a = book.source("a")
    book.store.record_index(a, [SourceItem("/c/a", 1, "Chapter 3165"), SourceItem("/c/b", 2, "Chapter 3165")])
    for r in ("/c/a", "/c/b"):
        book.store.put_version(a, r, book.version(r))
    assert book.store.selection() == ()
    assert book.store.check().duplicates == (Duplicate(a, ChapterKey(3165), ("/c/a", "/c/b")),)


def test_skipped_repost_resolves_a_duplicate_and_keeps_parts(book):
    # freewebnovel lists BTS 651 pt 1, 651 pt 2 and 652 twice; skip the second copies.
    a = book.source("a")
    titles_ = ["Chapter 651 (part 1)", "Chapter 651 (part 2)", "Chapter 652"] * 2
    items = [SourceItem(f"/c/{i}", i, t) for i, t in enumerate(titles_, start=1)]
    book.store.record_index(a, items)
    for item in items:
        book.store.put_version(a, item.ref, book.version(item.ref))
    diff = book.store.set_alignment(a, AlignmentRules(skip=frozenset({"/c/4", "/c/5", "/c/6"})))
    assert [(s.key.label, s.item_ref) for s in book.store.selection()] == [
        ("651 pt 1", "/c/1"), ("651 pt 2", "/c/2"), ("652", "/c/3")
    ]  # fmt: skip
    report = book.store.check()
    assert report.duplicates == () and report.unmapped == ()
    assert {m.item_ref for m in diff.moved} == {"/c/1", "/c/2", "/c/3"}
    assert book.store.rebase_refs(a, "/c/", "/d/") == 6
    assert book.store.sources()[0].alignment.skip == {"/d/4", "/d/5", "/d/6"}


def test_title_mismatch_reported(book):
    a = book.source("a")
    book.store.record_index(a, [SourceItem("/c/1", 1, "Chapter 7: Oops", number=8)])
    [note] = book.store.check().title_mismatches
    assert (note.item_ref, note.detail) == ("/c/1", "7")


# -- index changes ------------------------------------------------------------


def test_index_domain_move(book):
    a = book.source("a")
    urls = [f"https://novelbin.me/b/x/chapter-{n}" for n in (1, 2)]
    items = [SourceItem(url_ref(u), i, f"Chapter {i}") for i, u in enumerate(urls, start=1)]
    book.store.record_index(a, items)
    for item in items:
        book.store.put_version(a, item.ref, book.version(item.ref))
    before = book.store.selection()
    moved = [SourceItem(url_ref(u.replace(".me/", ".com/")), i, f"Chapter {i}") for i, u in enumerate(urls, 1)]
    diff = book.store.record_index(a, moved)
    assert (diff.added, diff.vanished) == ((), ())
    assert book.store.selection() == before


def test_index_path_change_then_rebase(book):
    a = book.source("a")
    book.store.record_index(a, [SourceItem(f"/b/x/chapter-{n}", n, f"Chapter {n}") for n in (1, 2, 3)])
    for n in (1, 2, 3):
        book.store.put_version(a, f"/b/x/chapter-{n}", book.version(str(n)))
    before = {s.key: s.version_id for s in book.store.selection()}

    diff = book.store.record_index(a, [SourceItem(f"/book/x/chapter-{n}", n, f"Chapter {n}") for n in (1, 2, 3)])
    assert len(diff.vanished) == 3 and len(diff.added) == 3
    report = book.store.check()
    assert len(report.vanished) == 3 and report.duplicates == ()
    assert book.store.selection() == ()  # new items have no versions yet; old ones are excluded

    assert book.store.rebase_refs(a, "/b/x/", "/book/x/") == 3
    assert {s.key: s.version_id for s in book.store.selection()} == before
    assert {s.item_ref for s in book.store.selection()} == {f"/book/x/chapter-{n}" for n in (1, 2, 3)}
    assert book.store.check().vanished == ()


def test_index_insert_middle(book):
    a = book.source("a")
    book.chapters(a, titles(*range(1, 13)))
    before = {s.item_ref: s.version_id for s in book.store.selection()}
    items = [SourceItem(book.ref(t), p, t) for p, t in enumerate(titles(*range(1, 10)), start=1)]
    items.append(SourceItem("/novel/notice", 10, "Author notice"))
    items += [SourceItem(book.ref(t), p, t) for p, t in enumerate(titles(10, 11, 12), start=11)]
    diff = book.store.record_index(a, items)
    assert (diff.added, diff.vanished) == (("/novel/notice",), ())
    assert {s.item_ref: s.version_id for s in book.store.selection()} == before


def test_index_shrink(book):
    a = book.source("a")
    refs = book.chapters(a, titles(*range(48, 53)))
    gone = refs[2]  # chapter 50
    version_id = next(s.version_id for s in book.store.selection() if s.item_ref == gone)
    diff = book.store.record_index(a, [SourceItem(r, i, t) for i, (r, t) in enumerate(
        zip(refs, titles(*range(48, 53)), strict=True)) if r != gone])  # fmt: skip
    assert diff.vanished == (gone,)
    assert book.store.read_version(version_id).item_ref == gone  # versions are kept
    assert [n.item_ref for n in book.store.check().vanished] == [gone]
    assert book.store.check().gaps == (50,)

    revived = book.store.record_index(a, [SourceItem(r, i, t) for i, (r, t) in enumerate(
        zip(refs, titles(*range(48, 53)), strict=True))])  # fmt: skip
    assert revived.revived == (gone,)
    assert "50" in book.picked()


# -- build planning -----------------------------------------------------------


def test_fingerprint_stale(book):
    a = book.source("a")
    book.chapters(a, titles(1, 2, 3))
    build_all(book.store, fingerprint="f1")
    assert book.store.plan_build(OutputKind.SITE, "f1").to_build == ()
    assert keys(book.store.plan_build(OutputKind.SITE, "f2").to_build) == ["1", "2", "3"]


def test_stale_on_pin(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, titles(*range(1, 6)))
    book.chapters(b, titles(*range(1, 6)))
    book.store.set_priority([a, b])
    build_all(book.store)
    book.store.set_pin(KeyRange(2, 3), b)
    plan = book.store.plan_build(OutputKind.SITE, "f1")
    assert keys(plan.to_build) == ["2", "3"] and plan.to_prune == ()


def test_switch_source_keeps_one_row_per_key(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, titles(5))
    book.chapters(b, titles(5))
    book.store.set_priority([a, b])
    build_all(book.store)
    book.store.set_priority([b, a])
    [s] = book.store.plan_build(OutputKind.SITE, "f1").to_build
    book.store.record_output(OutputKind.SITE, s, "f1", "site/5")
    [row] = book.store.outputs(OutputKind.SITE)
    assert (row.built_key, row.source_id) == (ChapterKey(5), b)


def test_override_edit_remaps(book):
    w = book.source("wns")
    _, x = book.chapters(w, titles(1898, 1899))
    build_all(book.store, OutputKind.SITE)
    selected_x = next(s for s in book.store.selection() if s.item_ref == x)
    book.store.record_output(OutputKind.AUDIO, selected_x, "legacy", "chapter_1899.mp3", legacy=True)

    diff = book.store.set_alignment(w, AlignmentRules(items={x: ChapterKey(1897)}))

    assert [(m.old, m.new) for m in diff.moved] == [(ChapterKey(1899), ChapterKey(1897))]
    assert next(s.key for s in book.store.selection() if s.item_ref == x) == ChapterKey(1897)
    site = book.store.plan_build(OutputKind.SITE, "f1")
    assert keys(site.to_build) == ["1897"]
    assert [r.built_key for r in site.to_prune] == [ChapterKey(1899)]
    audio = book.store.plan_build(OutputKind.AUDIO, "a1")
    assert x not in {s.item_ref for s in audio.to_build} and audio.to_prune == ()
    [moved] = book.store.check().legacy_moved
    assert (moved.item_ref, moved.built_key) == (x, ChapterKey(1899))


def test_legacy_row_survives_source_switch_unless_forced(book):
    w, l = book.source("wns"), book.source("lncrawl")
    book.chapters(w, titles(7))
    selected = book.store.selection()[0]
    book.store.record_output(OutputKind.AUDIO, selected, "legacy", "chapter_007.mp3", legacy=True)
    book.chapters(l, titles(7))
    book.store.set_priority([l, w])

    assert book.store.plan_build(OutputKind.AUDIO, "a1").to_build == ()
    assert [r.built_key for r in book.store.check().legacy_unselected] == [ChapterKey(7)]
    forced = book.store.plan_build(OutputKind.AUDIO, "a1", force=KeyRange(7, 7))
    assert [s.source_id for s in forced.to_build] == [l]


def test_chapters_lists_a_sources_items_even_when_not_selected(book):
    w, l = book.source("wns"), book.source("lncrawl")
    book.chapters(w, titles(1, 2))
    book.chapters(l, titles(2))
    book.store.set_priority([l, w])

    assert [(s.key.label, s.source_id) for s in book.store.chapters(w)] == [("1", w), ("2", w)]
    assert [s.source_id for s in book.store.selection() if s.key == ChapterKey(2)] == [l]


# -- what a sync fetches ------------------------------------------------------


def index(book, source, *chapter_titles) -> list[str]:
    items = [SourceItem(book.ref(t), pos, t) for pos, t in enumerate(chapter_titles, start=1)]
    book.store.record_index(source, items)
    return [i.ref for i in items]


def test_sync_new_only(book):
    a = book.source("a")
    book.chapters(a, titles(*range(1, 11)))
    refs = index(book, a, *titles(*range(1, 13)))
    assert book.store.to_fetch(a) == tuple(refs[10:])


def test_to_fetch_skips_numbers_another_source_already_has(book):
    imported, web = book.source("import"), book.source("web")
    book.chapters(imported, titles(1, 2, 3))
    refs = index(book, web, *titles(1, 2, 3, 4), "Notice: hiatus")
    assert book.store.to_fetch(web) == (refs[3], refs[4])  # 4, and the unmapped notice


def test_to_fetch_raw_counts_only_raw_coverage(book):
    en, raw = book.source("en"), book.source("raw", Kind.RAW_ZH)
    book.chapters(en, titles(1, 2))
    refs = index(book, raw, "第1章", "第2章")
    assert book.store.to_fetch(raw) == tuple(refs)
    assert book.store.to_fetch(en) == ()


def test_to_fetch_leaves_out_unavailable_vanished_and_skipped(book):
    a = book.source("a")
    refs = index(book, a, *titles(1, 2, 3, 4))
    book.store.mark_item(a, refs[0], ItemStatus.UNAVAILABLE)
    book.store.mark_item(a, refs[1], ItemStatus.FAILED, "timeout")
    book.store.set_alignment(a, AlignmentRules(skip={refs[2]}))
    index(book, a, *titles(1, 2, 3))  # 4 vanished
    assert book.store.to_fetch(a) == (refs[1],)  # a failed item is retried


def test_to_fetch_refresh_range_refetches_stored_and_unavailable(book):
    a = book.source("a")
    refs = book.chapters(a, titles(1, 2, 3, 4))
    book.store.mark_item(a, refs[2], ItemStatus.UNAVAILABLE)
    assert book.store.to_fetch(a) == ()
    assert book.store.to_fetch(a, refresh=KeyRange(2, 3)) == (refs[1], refs[2])


def test_to_fetch_only_keeps_items_keyed_in_the_range(book):
    a = book.source("a")
    refs = book.chapters(a, titles(1, 2))
    more = index(book, a, *titles(1, 2, 3, 4, 5), "Notice")
    assert book.store.to_fetch(a) == (more[2], more[3], more[4], more[5])  # unmapped is fetched too
    assert book.store.to_fetch(a, only=KeyRange(2, 4)) == (more[2], more[3])
    assert book.store.to_fetch(a, refresh=KeyRange(1, 2), only=KeyRange(2, 4)) == (refs[1], more[2], more[3])


def test_volumes_are_recorded_per_range(store):
    store.record_volume(VolumeRow(KeyRange(1, 100), "h1", "v1.m4b"))
    store.record_volume(VolumeRow(KeyRange(101, 200), "h2", "v2.m4b"))
    store.record_volume(VolumeRow(KeyRange(1, 100), "h3", "v1.m4b"))
    assert store.volumes() == (VolumeRow(KeyRange(1, 100), "h3", "v1.m4b"), VolumeRow(KeyRange(101, 200), "h2", "v2.m4b"))

    store.prune_volume(KeyRange(1, 100))
    assert [v.range for v in store.volumes()] == [KeyRange(101, 200)]


def test_open_migrates_a_version_1_store(tmp_path):
    folder = tmp_path / "old"
    NovelStore.create(folder, NovelMeta("Old")).close()
    with sqlite3.connect(folder / "novel.sqlite") as conn:
        conn.execute("DROP TABLE volume")
        conn.execute("ALTER TABLE source DROP COLUMN published")
        conn.execute("PRAGMA user_version=1")
    conn.close()

    with NovelStore.open(folder) as store:
        store.record_volume(VolumeRow(KeyRange(1, 100), "h", "v.m4b"))
        assert len(store.volumes()) == 1
    with NovelStore.open(folder) as store:
        assert len(store.volumes()) == 1
    NovelStore.create(tmp_path / "new", NovelMeta("New")).close()
    assert source_columns(folder) == source_columns(tmp_path / "new")


def source_columns(folder):
    with sqlite3.connect(folder / "novel.sqlite") as conn:
        columns = conn.execute("PRAGMA table_info(source)").fetchall()
    conn.close()
    return columns


def test_open_migrates_a_version_2_store_keeping_every_source_published(tmp_path):
    folder = tmp_path / "old"
    with NovelStore.create(folder, NovelMeta("Old")) as store:
        store.upsert_source(SourceSpec("custom:a", "https://a.test", "en", Kind.OFFICIAL_EN))
        store.upsert_source(SourceSpec("custom:raw", "https://raw.test", "zh", Kind.RAW_ZH))
    with sqlite3.connect(folder / "novel.sqlite") as conn:
        conn.execute("ALTER TABLE source DROP COLUMN published")
        conn.execute("PRAGMA user_version=2")
    conn.close()

    with NovelStore.open(folder) as store:
        assert [s.published for s in store.sources()] == [True, True]
    with sqlite3.connect(folder / "novel.sqlite") as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (3,)
    conn.close()


# -- publish switch -----------------------------------------------------------


def test_a_repeat_upsert_never_changes_the_publish_switch(book):
    mine = book.source("mine", Kind.MY_TRANSLATION, published=False)
    assert book.source("mine", Kind.MY_TRANSLATION, published=True) == mine
    assert {s.id: s.published for s in book.store.sources()} == {mine: False}


def test_an_unpublished_source_is_left_out_of_the_book_until_switched_on(book):
    a = book.source("a")
    mine = book.source("mine", Kind.MY_TRANSLATION, published=False)
    book.chapters(a, titles(1, 2))
    book.chapters(mine, titles(5, 6, 7, 8, 9))

    assert book.picked() == {"1": a, "2": a}
    assert keys(book.store.chapters(mine)) == ["5", "6", "7", "8", "9"]
    book.store.set_published(mine, True)
    assert book.picked() == {"1": a, "2": a} | {str(n): mine for n in range(5, 10)}
    book.store.set_published(mine, False)
    assert book.picked() == {"1": a, "2": a}


def test_check_ignores_unpublished_sources_but_lists_their_failures(book):
    a = book.source("a")
    raw = book.source("raw", Kind.RAW_ZH)
    mine = book.source("mine", Kind.MY_TRANSLATION, published=False)
    book.chapters(a, titles(1, 2))
    book.chapters(raw, ["第1章", "第2章", "第9章"])
    index = titles("2 (1)", "2 (2)", 3, 4)
    book.store.record_index(mine, [SourceItem(book.ref(t), i, t) for i, t in enumerate(index, 1)])
    for t in index[:3]:
        book.store.put_version(mine, book.ref(t), book.version(t))
    book.store.mark_item(mine, book.ref("Chapter 4"), ItemStatus.FAILED, "blocked: 天元")

    report = book.store.check()
    assert report.gaps == () and report.mixed_parts == ()
    assert report.raw_only == (9,)
    assert [(f.source_id, f.detail) for f in report.failed] == [(mine, "blocked: 天元")]


def test_pins_and_unpublishing_refuse_each_other(book):
    a = book.source("a")
    mine = book.source("mine", Kind.MY_TRANSLATION, published=False)
    book.chapters(a, titles(1, 2))
    book.chapters(mine, titles(1, 2))
    with pytest.raises(StoreError, match="unpublished"):
        book.store.set_pin(KeyRange(1, 2), mine)

    book.store.set_published(mine, True)
    book.store.set_pin(KeyRange(1, 2), mine)
    book.store.set_pin(KeyRange(7, 9), mine)
    with pytest.raises(StoreError, match="1-2, 7-9"):
        book.store.set_published(mine, False)
    assert book.picked() == {"1": mine, "2": mine}


def test_official_sources_still_fetch_numbers_only_my_translation_has(book):
    official = book.source("official")
    mine = book.source("mine", Kind.MY_TRANSLATION)
    other = book.source("other")
    refs = book.store.record_index(official, [SourceItem(book.ref(t), i, t) for i, t in enumerate(titles(9, 10, 11), 1)]).added
    book.chapters(mine, titles(10))
    book.chapters(other, titles(11))

    assert book.picked()["10"] == mine
    assert book.store.to_fetch(official) == (refs[0], refs[1])  # 11 is official text already


def test_raw_fetching_is_unchanged_by_my_translation(book):
    official = book.source("official")
    mine = book.source("mine", Kind.MY_TRANSLATION, published=False)
    raw_a, raw_b = book.source("raw-a", Kind.RAW_ZH), book.source("raw-b", Kind.RAW_ZH)
    official_refs = book.store.record_index(official, [SourceItem(book.ref(t), 1, t) for t in titles(10)]).added
    raw_refs = book.store.record_index(raw_a, [SourceItem("/raw/10", 1, "第10章")]).added
    book.chapters(mine, titles(10))
    book.store.record_index(raw_b, [SourceItem("/b/10", 1, "第10章")])
    book.store.put_version(raw_b, "/b/10", book.version("十"))

    assert book.store.to_fetch(official) == official_refs
    assert book.store.to_fetch(raw_a) == ()
    assert raw_refs  # indexed, but raw-b already has the text


# -- views ----------------------------------------------------------------------


def test_a_view_is_one_read_that_later_writes_do_not_change(book):
    a, b = book.source("a"), book.source("b")
    book.chapters(a, titles(1, 2))
    view = book.store.view()
    book.chapters(b, titles(3))
    book.store.set_pin(KeyRange(1, 1), b)

    assert keys(view.selection) == ["1", "2"]
    assert view.pins == () and view.priority == (a, b)
    assert view.to_fetch(b) == ()
    assert keys(book.store.view().selection) == ["1", "2", "3"]


def test_view_items_show_each_entry_as_the_book_sees_it(book):
    a = book.source("a")
    index = ["Chapter 1", "Notice", "Chapter 2", "Chapter 3"]
    book.store.record_index(a, [SourceItem(book.ref(t), i, t) for i, t in enumerate(index, start=1)])
    book.store.put_version(a, "/novel/chapter-1", book.version("one"))
    book.store.mark_item(a, "/novel/chapter-2", ItemStatus.FAILED, "HTTP 500")
    book.store.set_alignment(a, AlignmentRules(skip={"/novel/chapter-3"}))

    items = {i.ref: i for i in book.store.view().items(a)}
    assert (items["/novel/chapter-1"].key, items["/novel/chapter-1"].has_text) == (ChapterKey(1), True)
    assert items["/novel/notice"].key is None
    assert (items["/novel/chapter-2"].status, items["/novel/chapter-2"].reason) == (ItemStatus.FAILED, "HTTP 500")
    assert items["/novel/chapter-3"].skipped and items["/novel/chapter-3"].key is None
    with pytest.raises(StoreError, match="unknown source"):
        book.store.view().items(99)
