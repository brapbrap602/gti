import json
import shutil
import subprocess

import pytest
from novel_audio.build import build_audio
from novel_audio.media import duration_ms
from novel_audio.volumes import build_volumes
from novel_core import AlignmentRules, KeyRange, NewVersion, OutputKind


@pytest.fixture
def out(tmp_path):
    return tmp_path / "audio"


def probe(path) -> dict:
    result = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-show_chapters", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, encoding="utf-8",
    )  # fmt: skip
    return json.loads(result.stdout)


def test_m4b_volume_has_a_chapter_mark_per_chapter(book, tts, out):
    book.chapters(book.source(), [1, 2, 3])
    build_audio(book.store, out, tts)

    report = build_volumes(book.store, out, cover=None)

    assert report.built == (KeyRange(1, 100),)
    info = probe(out / "volumes" / "0001-0100.m4b")
    marks = [(c["tags"]["title"], round(float(c["start_time"]) * 1000)) for c in info["chapters"]]
    lengths = [duration_ms(out / f"chapter_000{n}.mp3") for n in (1, 2)]
    assert marks == [
        ("Chapter 1: Title 1", 0),
        ("Chapter 2: Title 2", lengths[0]),
        ("Chapter 3: Title 3", lengths[0] + lengths[1]),
    ]
    assert info["format"]["tags"]["title"] == "Test Novel 1–3"
    assert info["format"]["tags"]["artist"] == "Gen, Er"
    assert [s["codec_name"] for s in info["streams"] if s["codec_type"] != "data"] == ["aac"]  # data: the chapter track


def test_volume_embeds_the_cover(book, tts, out, silent_frame, tmp_path):
    book.chapters(book.source(), [1])
    build_audio(book.store, out, tts)
    png = tmp_path / "cover.png"
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=8x8", "-frames:v", "1", str(png)], check=True)

    build_volumes(book.store, out, cover=png.read_bytes())

    streams = probe(out / "volumes" / "0001-0100.m4b")["streams"]
    media = [(s["codec_type"], s["disposition"]["attached_pic"]) for s in streams if s["codec_type"] != "data"]
    assert media == [("audio", 0), ("video", 1)]


def test_only_the_volume_of_a_changed_chapter_is_rebuilt(book, tts, out, paragraphs):
    src = book.source()
    refs = book.chapters(src, [50, 150])
    build_audio(book.store, out, tts)
    build_volumes(book.store, out)

    book.store.put_version(src, refs[0], NewVersion("Chapter 50: Title 50", paragraphs("A new text for fifty.")))
    build_audio(book.store, out, tts)
    report = build_volumes(book.store, out)

    assert report.built == (KeyRange(1, 100),)
    assert build_volumes(book.store, out).built == ()


def test_volume_without_chapters_is_deleted(book, tts, out):
    src = book.source()
    refs = book.chapters(src, [5, 150])
    build_audio(book.store, out, tts)
    build_volumes(book.store, out)
    book.store.set_alignment(src, AlignmentRules(skip={refs[1]}))
    build_audio(book.store, out, tts)

    report = build_volumes(book.store, out)

    assert report.pruned == (KeyRange(101, 200),)
    assert [p.name for p in (out / "volumes").iterdir()] == ["0001-0100.m4b"]
    assert [v.range for v in book.store.volumes()] == [KeyRange(1, 100)]


def test_volume_reports_chapters_without_audio(book, tts, out):
    book.chapters(book.source(), [1, 2, 3])
    build_audio(book.store, out, tts, keys=KeyRange(1, 2))

    report = build_volumes(book.store, out)

    assert report.incomplete == ((KeyRange(1, 100), 1),)
    assert len(book.store.outputs(OutputKind.AUDIO)) == 2
