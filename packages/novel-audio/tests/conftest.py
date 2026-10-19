import subprocess
from pathlib import Path

import pytest
from novel_audio.media import ffmpeg
from novel_core import Block, Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec

FRAME_MS = 48  # one 24 kHz MPEG-2 layer III frame is 1152 samples


@pytest.fixture(scope="session")
def silent_frame(tmp_path_factory) -> bytes:
    """One frame of silent CBR MP3 in edge-tts's format (24 kHz mono, 48 kbps), with no Xing header."""
    out = tmp_path_factory.mktemp("mp3") / "silence.mp3"
    subprocess.run(
        [ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-frames:a", "1",
         "-c:a", "libmp3lame", "-b:a", "48k", "-write_xing", "0", "-id3v2_version", "0", str(out)],
        check=True,
    )  # fmt: skip
    return out.read_bytes()


class FakeTts:
    """Silent MP3 whose length is one frame per 10 characters; logs every text it was asked for."""

    def __init__(self, frame: bytes, voice: str = "fake-voice"):
        self.voice = voice
        self.frame = frame
        self.calls: list[str] = []

    async def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        if text == "(silent)":
            return b""
        return self.frame * (len(text) // 10 + 1)


@pytest.fixture
def tts(silent_frame):
    return FakeTts(silent_frame)


@pytest.fixture
def store(tmp_path):
    with NovelStore.create(tmp_path / "novel", NovelMeta("Test Novel", author="Gen, Er")) as s:
        yield s


class Book:
    """Test-side helper for filling a store and making legacy tts_reader folders."""

    def __init__(self, store: NovelStore, frame: bytes):
        self.store = store
        self.frame = frame

    def source(self, name: str = "a") -> int:
        return self.store.upsert_source(SourceSpec(f"custom:{name}", f"https://{name}.test/novel", "en", Kind.OFFICIAL_EN))

    def chapters(self, source: int, numbers, body=None) -> list[str]:
        """Chapters titled 'Chapter N: Title N' at refs /novel/chapter-N; two short paragraphs unless `body(n)`."""
        items = [SourceItem(f"/novel/chapter-{n}", pos, f"Chapter {n}: Title {n}") for pos, n in enumerate(numbers, 1)]
        self.store.record_index(source, items)
        for n, item in zip(numbers, items):
            blocks = body(n) if body else text(f"First paragraph of chapter {n}.", f"Second paragraph of chapter {n}.")
            self.store.put_version(source, item.ref, NewVersion(item.title, blocks))
        return [i.ref for i in items]

    def legacy_folder(self, root: Path, number: int, paragraph_lengths: list[int], combined: bool = True) -> Path:
        """A tts_reader chapter folder: one sentence file per paragraph, sized like its text, and the combined MP3."""
        folder = root / f"chapter_{number:03d}"
        folder.mkdir(parents=True)
        (folder / f"ch{number:03d}_p000_s000.mp3").write_bytes(self.frame)
        for p, length in enumerate(paragraph_lengths, start=1):
            (folder / f"ch{number:03d}_p{p:03d}_s001.mp3").write_bytes(bytes(length * 37))
        if combined:
            (folder / f"{folder.name}.mp3").write_bytes(self.frame * 20)
        return folder


def text(*paragraphs: str) -> tuple[Block, ...]:
    return tuple(Paragraph.of(p) for p in paragraphs)


@pytest.fixture
def book(store, silent_frame):
    return Book(store, silent_frame)


@pytest.fixture
def paragraphs():
    return text
