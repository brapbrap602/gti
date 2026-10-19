import pytest
from mutagen.id3 import ID3
from novel_audio.build import build_audio, chapter_file, retag_audio
from novel_audio.legacy import LEGACY_FINGERPRINT
from novel_audio.media import duration_ms
from novel_core import AlignmentRules, ChapterKey, KeyRange, NewVersion, OutputKind


@pytest.fixture
def out(tmp_path):
    return tmp_path / "audio"


def rows(store):
    return {r.built_key.label: r for r in store.outputs(OutputKind.AUDIO)}


def test_builds_tagged_chapter_mp3s_from_heading_and_sentences(book, tts, out):
    book.chapters(book.source(), [1, 2])

    report = build_audio(book.store, out, tts, cover=b"\x89PNG\r\n\x1a\nfake")

    assert report.built == (ChapterKey(1), ChapterKey(2)) and report.synthesized == 6
    assert tts.calls[:3] == ["Chapter 1: Title 1", "First paragraph of chapter 1.", "Second paragraph of chapter 1."]
    assert sorted(p.name for p in out.glob("*.mp3")) == ["chapter_0001.mp3", "chapter_0002.mp3"]
    tags = ID3(out / "chapter_0001.mp3")
    assert str(tags["TIT2"]) == "Chapter 1: Title 1" and str(tags["TALB"]) == "Test Novel"
    assert str(tags["TPE1"]) == "Gen, Er" and str(tags["TRCK"]) == "1"
    assert tags.getall("APIC")[0].mime == "image/png"
    assert duration_ms(out / "chapter_0001.mp3") > 0
    assert {k: r.artifact for k, r in rows(book.store).items()} == {"1": "chapter_0001.mp3", "2": "chapter_0002.mp3"}


def test_second_build_does_nothing(book, tts, out):
    book.chapters(book.source(), [1, 2])
    build_audio(book.store, out, tts)
    tts.calls.clear()

    report = build_audio(book.store, out, tts)

    assert report.built == () and tts.calls == []


def test_sentence_cache_resynthesizes_only_the_edited_sentence(book, tts, out, paragraphs):
    src = book.source()
    [ref] = book.chapters(src, [7], body=lambda n: paragraphs("The sun rose over the hills. Birds sang loudly."))
    build_audio(book.store, out, tts)
    tts.calls.clear()

    edited = paragraphs("The sun rose over the hills. Birds sang very quietly.")
    book.store.put_version(src, ref, NewVersion("Chapter 7: Title 7", edited))
    report = build_audio(book.store, out, tts)

    assert report.built == (ChapterKey(7),)
    assert tts.calls == ["Birds sang very quietly."]
    assert report.reused == 2  # the heading and the first sentence


def test_a_new_voice_rebuilds_every_chapter(book, tts, out):
    book.chapters(book.source(), [1, 2])
    build_audio(book.store, out, tts)
    tts.voice = "other-voice"

    assert build_audio(book.store, out, tts).built == (ChapterKey(1), ChapterKey(2))


def test_missing_file_is_rebuilt(book, tts, out):
    book.chapters(book.source(), [1, 2])
    build_audio(book.store, out, tts)
    (out / "chapter_0002.mp3").unlink()

    assert build_audio(book.store, out, tts).built == (ChapterKey(2),)


def test_keys_limit_what_is_built(book, tts, out):
    book.chapters(book.source(), [1, 2, 3])

    assert build_audio(book.store, out, tts, keys=KeyRange(2, 3)).built == (ChapterKey(2), ChapterKey(3))
    assert sorted(rows(book.store)) == ["2", "3"]


def test_unselected_chapter_is_pruned_and_its_file_deleted(book, tts, out):
    src = book.source()
    _, second = book.chapters(src, [1, 2])
    build_audio(book.store, out, tts)
    book.store.set_alignment(src, AlignmentRules(skip={second}))

    report = build_audio(book.store, out, tts)

    assert report.pruned == (ChapterKey(2),) and report.built == ()
    assert not (out / "chapter_0002.mp3").exists() and sorted(rows(book.store)) == ["1"]


def test_empty_sentence_audio_is_left_out(book, tts, out, paragraphs):
    book.chapters(book.source(), [1], body=lambda n: paragraphs("(silent)", "Something is said here."))
    build_audio(book.store, out, tts)
    assert tts.calls == ["Chapter 1: Title 1", "(silent)", "Something is said here."]
    assert (out / chapter_file(ChapterKey(1))).stat().st_size > 0


def test_legacy_chapters_are_kept_unless_forced(book, tts, out, tmp_path):
    book.chapters(book.source(), [1, 2])
    legacy_mp3 = tmp_path / "tts_out" / "chapter_001.mp3"
    legacy_mp3.parent.mkdir()
    legacy_mp3.write_bytes(book.frame * 5)
    [first] = [s for s in book.store.selection() if s.key == ChapterKey(1)]
    book.store.record_output(OutputKind.AUDIO, first, LEGACY_FINGERPRINT, str(legacy_mp3), legacy=True)

    assert build_audio(book.store, out, tts).built == (ChapterKey(2),)
    forced = build_audio(book.store, out, tts, keys=KeyRange(1, 1), force=True)

    assert forced.built == (ChapterKey(1),)
    assert rows(book.store)["1"].legacy is False and rows(book.store)["1"].artifact == "chapter_0001.mp3"
    assert legacy_mp3.exists()


def test_retag_rewrites_legacy_and_built_tags(book, tts, out, tmp_path):
    book.chapters(book.source(), [1, 2])
    build_audio(book.store, out, tts, keys=KeyRange(2, 2))
    legacy_mp3 = tmp_path / "chapter_001.mp3"
    legacy_mp3.write_bytes(book.frame * 5)
    [first] = [s for s in book.store.selection() if s.key == ChapterKey(1)]
    book.store.record_output(OutputKind.AUDIO, first, LEGACY_FINGERPRINT, str(legacy_mp3), legacy=True)

    assert retag_audio(book.store, out, cover=b"\xff\xd8jpeg") == 2
    tags = ID3(legacy_mp3)
    assert str(tags["TIT2"]) == "Chapter 1: Title 1" and str(tags["TRCK"]) == "1"
    assert tags.getall("APIC")[0].mime == "image/jpeg"
