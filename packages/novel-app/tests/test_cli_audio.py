import json
import subprocess

import pytest
from mutagen.id3 import ID3
from novel_app import cli
from novel_app.cli import app
from novel_app.library import DATA_DIR_ENV
from novel_audio.media import ffmpeg
from typer.testing import CliRunner

TOC = "https://novelbin.me/novel-book/test-novel"
SHAPES = {  # paragraph lengths of each chapter's text
    1: (90, 300, 40, 200),
    2: (300, 30, 250, 80),
    4: (200, 60, 60, 400),
}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def frame(tmp_path) -> bytes:
    out = tmp_path / "silence.mp3"
    subprocess.run(
        [ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-frames:a", "1",
         "-c:a", "libmp3lame", "-b:a", "48k", "-write_xing", "0", "-id3v2_version", "0", str(out)],
        check=True,
    )  # fmt: skip
    return out.read_bytes()


@pytest.fixture
def silent_tts(monkeypatch, frame):
    """Replace edge-tts at the CLI's composition point; records the voice it was built with."""
    voices = []

    class SilentTts:
        def __init__(self, voice):
            self.voice = voice
            voices.append(voice)

        async def synthesize(self, text):
            return frame * 3

    monkeypatch.setattr(cli, "EdgeTts", SilentTts)
    return voices


@pytest.fixture
def novel(data_dir, tmp_path):
    """`test-novel` imported from a web-novel-scraper folder: chapters 1, 2 and 4 at positions 1, 2 and 4."""
    root = tmp_path / "wns" / "Test Novel" / "data"
    (root / "chapters").mkdir(parents=True)
    chapters = []
    for n in (1, 2, 3, 4):
        filename = None if n == 3 else f"test_{n}.html"
        chapters.append({"chapter_url": f"{TOC}/chapter-{n}", "chapter_html_filename": filename,
                         "chapter_title": f"Chapter {n}: Name {n}"})  # fmt: skip
        if filename:
            paragraphs = "".join(f"<p>{f'Word{n} ' * (size // 6)}</p>" for size in SHAPES[n])
            (root / "chapters" / filename).write_text(f'<div id="chr-content">{paragraphs}</div>', encoding="utf-8")
    main = {"title": "Test Novel", "toc_main_url": TOC, "chapters": chapters, "metadata": {"author": "Gen, Er"}}
    (root / "main.json").write_text(json.dumps(main), encoding="utf-8")
    assert run("import", "wns", root.parent).exit_code == 0
    return "test-novel"


def run(*args):
    return CliRunner().invoke(app, [str(a) for a in args])


def test_build_audio_and_volumes(novel, data_dir, silent_tts, tmp_path):
    png = tmp_path / "c.png"
    subprocess.run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=8x8", "-frames:v", "1", str(png)], check=True)
    assert run("cover", novel, png).exit_code == 0

    result = run("build", "audio", novel, "--range", "1-2", "--voice", "en-GB-RyanNeural")

    assert result.exit_code == 0, result.output
    assert "[1/2] chapter 1" in result.output and "2 chapters built, 0 pruned" in result.output
    assert silent_tts == ["en-GB-RyanNeural"]
    audio = data_dir / "_audio" / novel
    assert ID3(audio / "chapter_0001.mp3").getall("APIC")
    again = run("build", "audio", novel, "--voice", "en-GB-RyanNeural").output
    assert "1 chapters built, 0 pruned; 4 sentences synthesized, 0 from the cache" in again  # heading + 3 distinct paragraphs

    result = run("build", "volumes", novel)
    assert result.exit_code == 0, result.output
    assert "1 volumes built" in result.output and (audio / "volumes" / "0001-0100.m4b").exists()


def test_register_legacy_by_position(novel, frame, tmp_path):
    legacy = tmp_path / "tts_out"
    for n in (2, 4):
        folder = legacy / f"chapter_{n:03d}"
        folder.mkdir(parents=True)
        for p, size in enumerate(SHAPES[n], start=1):
            (folder / f"ch{n:03d}_p{p:03d}_s001.mp3").write_bytes(bytes(size * 40))
        (folder / f"chapter_{n:03d}.mp3").write_bytes(frame * 4)
    (legacy / "chapter_005").mkdir()

    result = run("audio", "register", novel, legacy, "--key", "position")

    assert result.exit_code == 0, result.output
    assert "registered: 2 (0 too short or without sentence files to check)" in result.output
    assert "partial (no combined mp3): 1 (5)" in result.output

    retag = run("audio", "retag", novel)
    assert "2 chapter MP3s tagged" in retag.output
    assert str(ID3(legacy / "chapter_004" / "chapter_004.mp3")["TIT2"]) == "Chapter 4: Name 4"


def test_bad_shift_is_rejected(novel, tmp_path):
    (tmp_path / "tts_out").mkdir()
    result = run("audio", "register", novel, tmp_path / "tts_out", "--key", "position", "--shift", "736+4")
    assert result.exit_code == 2 and "not a shift like 736-1442:+4" in result.output
