import random

import pytest
from novel_audio.build import build_audio
from novel_audio.legacy import Mismatch, Positions, Shift, TitleNumbers, register_legacy
from novel_core import AlignmentRules, ChapterKey, KeyRange, NewVersion, OutputKind, SourceItem

# Paragraph lengths (characters) of chapter N's text: 40 paragraphs, like a short real chapter.
SHAPES = {n: random.Random(n).choices(range(20, 600), k=40) for n in range(1, 6)}


def body(paragraphs, shape):
    return paragraphs(*("x" * length for length in shape))


@pytest.fixture
def chapters(book, paragraphs):
    """A source listing an unnumbered notice at position 1, then chapters 1-5 at positions 2-6."""
    src = book.source()
    items = [SourceItem("/novel/notice", 1, "Notice")]
    items += [SourceItem(f"/novel/chapter-{n}", n + 1, f"Chapter {n}: Title {n}") for n in SHAPES]
    book.store.record_index(src, items)
    book.store.put_version(src, items[0].ref, NewVersion("Notice", paragraphs("Hiatus.")))
    for n, item in zip(SHAPES, items[1:]):
        book.store.put_version(src, item.ref, NewVersion(item.title, body(paragraphs, SHAPES[n])))
    return src, [i.ref for i in items]


@pytest.fixture
def legacy(tmp_path):
    return tmp_path / "tts_out"


def keys_by_folder(report):
    return {folder: key.label for folder, key in report.registered}


def test_position_maps_through_the_snapshot_and_is_verified(book, chapters, legacy):
    src, refs = chapters
    for folder, chapter in ((2, 1), (3, 2), (6, 5)):
        book.legacy_folder(legacy, folder, SHAPES[chapter])

    report = register_legacy(book.store, legacy, src, Positions(refs))

    assert keys_by_folder(report) == {2: "1", 3: "2", 6: "5"} and report.mismatched == ()
    rows = {r.built_key: r for r in book.store.outputs(OutputKind.AUDIO)}
    assert rows[ChapterKey(1)].legacy and rows[ChapterKey(1)].item_ref == refs[1]
    assert rows[ChapterKey(1)].artifact == str((legacy / "chapter_002" / "chapter_002.mp3").resolve())


def test_title_number_maps_to_the_item_with_that_key(book, chapters, legacy):
    src, _ = chapters
    book.legacy_folder(legacy, 4, SHAPES[4])
    book.legacy_folder(legacy, 9, SHAPES[1])

    report = register_legacy(book.store, legacy, src, TitleNumbers())

    assert keys_by_folder(report) == {4: "4"}
    assert report.unmapped == ((9, "chapter 9 has no item with a key"),)


def test_a_wrong_mapping_is_reported_with_its_best_match_and_fixed_by_a_shift(book, chapters, legacy):
    src, refs = chapters
    book.legacy_folder(legacy, 3, SHAPES[3])  # the old export lacked the notice: folder 3 is position 4

    report = register_legacy(book.store, legacy, src, Positions(refs))
    assert report.registered == () and report.mismatched == (Mismatch(3, ChapterKey(2), 4),)

    shifted = register_legacy(book.store, legacy, src, Positions(refs), shifts=[Shift(KeyRange(3, 10), 1)])
    assert keys_by_folder(shifted) == {3: "3"}


def test_text_cleaned_since_still_matches(book, chapters, legacy):
    """The old text had a credit line first and a stray paragraph mid-chapter that cleanup removed."""
    src, refs = chapters
    book.legacy_folder(legacy, 5, [70, *SHAPES[4][:3], 55, *SHAPES[4][3:]])

    assert keys_by_folder(register_legacy(book.store, legacy, src, Positions(refs))) == {5: "4"}


def test_a_repost_of_the_same_text_is_no_rival(book, paragraphs, legacy):
    src = book.source()
    names = [("chapter-1", 1, SHAPES[1]), ("chapter-2", 2, SHAPES[2]), ("chapter-2-repost", 2, SHAPES[2])]
    items = [SourceItem(f"/novel/{name}", pos, f"Chapter {n}: T") for pos, (name, n, _) in enumerate(names, start=1)]
    book.store.record_index(src, items)
    for item, (_, _, shape) in zip(items, names):
        book.store.put_version(src, item.ref, NewVersion(item.title, body(paragraphs, shape)))
    # Both copies keep a key (the repost via an override), so the repost sits right next to the original.
    book.store.set_alignment(src, AlignmentRules(items={items[2].ref: ChapterKey(7)}))
    book.legacy_folder(legacy, 2, SHAPES[2])

    report = register_legacy(book.store, legacy, src, Positions([i.ref for i in items]))

    assert keys_by_folder(report) == {2: "2"}  # an identical text would tie, never beat, the original


def test_position_of_a_skipped_or_unnumbered_item_is_unmapped(book, chapters, legacy):
    src, refs = chapters
    book.legacy_folder(legacy, 1, SHAPES[1])
    book.legacy_folder(legacy, 40, SHAPES[1])

    report = register_legacy(book.store, legacy, src, Positions(refs))

    assert report.unmapped == ((1, "position 1 has no item with a key"), (40, "position 40 has no item with a key"))


def test_partial_unverified_and_already_built_folders(book, chapters, legacy, tts, tmp_path):
    src, refs = chapters
    book.legacy_folder(legacy, 2, SHAPES[1], combined=False)  # interrupted: no chapter_002.mp3
    book.legacy_folder(legacy, 3, [])  # sentence files deleted
    book.legacy_folder(legacy, 4, SHAPES[3])
    build_audio(book.store, tmp_path / "audio", tts, keys=KeyRange(3, 3))

    report = register_legacy(book.store, legacy, src, Positions(refs))

    assert report.partial == (2,)
    assert report.unverified == (3,) and keys_by_folder(report) == {3: "2"}
    assert report.already_built == (4,)
    rows = {r.built_key: r for r in book.store.outputs(OutputKind.AUDIO)}
    assert not rows[ChapterKey(3)].legacy  # key 3 keeps its built audio


def test_registration_is_idempotent(book, chapters, legacy):
    src, refs = chapters
    book.legacy_folder(legacy, 2, SHAPES[1])
    register_legacy(book.store, legacy, src, Positions(refs))
    again = register_legacy(book.store, legacy, src, Positions(refs))

    assert keys_by_folder(again) == {2: "1"} and len(book.store.outputs(OutputKind.AUDIO)) == 1
