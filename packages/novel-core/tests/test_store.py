import pytest
from novel_core import (
    AlignmentRules,
    ChapterKey,
    Duplicate,
    Inserted,
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
    StoreError,
    Unchanged,
    url_ref,
)


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


def test_part_zero_dropped_when_same_source_has_parts(book):
    a = book.source("a")
    book.chapters(a, ["Chapter 524", "Chapter 524 (1)", "Chapter 524 (2)"])
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


def test_align_dup(book):
    a = book.source("a")
    book.store.record_index(a, [SourceItem("/c/a", 1, "Chapter 3165"), SourceItem("/c/b", 2, "Chapter 3165")])
    for r in ("/c/a", "/c/b"):
        book.store.put_version(a, r, book.version(r))
    assert book.store.selection() == ()
    assert book.store.check().duplicates == (Duplicate(a, ChapterKey(3165), ("/c/a", "/c/b")),)


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
