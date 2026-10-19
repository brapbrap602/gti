"""Audio files: joining MP3s, ID3 tags, durations and M4B volumes. ffmpeg must be on PATH.

Every writer goes through a temporary file and an atomic replace, so an
interrupted build never leaves a truncated MP3 or M4B behind.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TIT2, TPE1, TRCK, ID3NoHeaderError
from mutagen.mp3 import MP3

GENRE = "Audiobook"


class MediaError(Exception):
    """ffmpeg is missing or failed."""


@dataclass(frozen=True)
class Tags:
    title: str
    album: str
    artist: str | None = None
    track: int | None = None
    comment: str | None = None
    cover: bytes | None = None


@dataclass(frozen=True)
class Marker:
    """A chapter mark in a volume, in milliseconds from its start."""

    title: str
    start_ms: int
    end_ms: int


def ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise MediaError("ffmpeg not found on PATH (install it, e.g. `winget install ffmpeg`)")
    return path


def join_mp3(parts: Sequence[Path], out: Path) -> None:
    """Concatenate MP3s of one encoding into `out` without re-encoding."""
    if not parts:
        raise MediaError(f"nothing to join into {out.name}")
    with _temp_beside(out) as tmp, _concat_list(parts) as listing:
        _run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
              "-map", "0:a", "-c", "copy", "-f", "mp3", str(tmp)])  # fmt: skip
        os.replace(tmp, out)


def duration_ms(path: Path) -> int:
    return round(MP3(path).info.length * 1000)


def tag_mp3(path: Path, tags: Tags) -> None:
    try:
        id3 = ID3(path)
    except ID3NoHeaderError:
        id3 = ID3()
    for frame in ("TIT2", "TALB", "TPE1", "TRCK", "TCON", "COMM", "APIC"):
        id3.delall(frame)
    id3.add(TIT2(encoding=3, text=tags.title))
    id3.add(TALB(encoding=3, text=tags.album))
    id3.add(TCON(encoding=3, text=GENRE))
    if tags.artist:
        id3.add(TPE1(encoding=3, text=tags.artist))
    if tags.track is not None:
        id3.add(TRCK(encoding=3, text=str(tags.track)))
    if tags.comment:
        id3.add(COMM(encoding=3, lang="eng", desc="", text=tags.comment))
    if tags.cover:
        id3.add(APIC(encoding=0, mime=_image_mime(tags.cover), type=3, desc="Cover", data=tags.cover))
    id3.save(path, v2_version=3)


def encode_m4b(parts: Sequence[Path], markers: Sequence[Marker], out: Path, tags: Tags) -> None:
    """Encode chapter MP3s into one AAC M4B with a chapter list (FFMETADATA) and cover."""
    with tempfile.TemporaryDirectory() as tmpdir, _temp_beside(out) as tmp, _concat_list(parts) as listing:
        meta = Path(tmpdir) / "chapters.txt"
        meta.write_text(_ffmetadata(markers, tags), encoding="utf-8")
        cmd = [ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
               "-f", "ffmetadata", "-i", str(meta)]  # fmt: skip
        cover_args = []
        if tags.cover:
            cover = Path(tmpdir) / ("cover.png" if _image_mime(tags.cover) == "image/png" else "cover.jpg")
            cover.write_bytes(tags.cover)
            cmd += ["-i", str(cover)]
            cover_args = ["-map", "2:v", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        cmd += ["-map", "0:a", *cover_args, "-map_metadata", "1", "-map_chapters", "1",
                "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", "-f", "mp4", str(tmp)]  # fmt: skip
        _run(cmd)
        os.replace(tmp, out)


def _ffmetadata(markers: Sequence[Marker], tags: Tags) -> str:
    def esc(text: str) -> str:
        return "".join("\\" + c if c in "=;#\\\n" else c for c in text)

    lines = [";FFMETADATA1", f"title={esc(tags.title)}", f"album={esc(tags.album)}", f"genre={GENRE}"]
    if tags.artist:
        lines.append(f"artist={esc(tags.artist)}")
    for m in markers:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={m.start_ms}", f"END={m.end_ms}", f"title={esc(m.title)}"]
    return "\n".join(lines) + "\n"


def _image_mime(data: bytes) -> str:
    return "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise MediaError(f"ffmpeg failed ({result.returncode}): {result.stderr.strip()[-2000:]}")


@contextmanager
def _temp_beside(out: Path) -> Iterator[Path]:
    """A temporary path next to `out` (same volume, so the final replace is atomic), removed on failure."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.tmp{out.suffix}")
    try:
        yield tmp
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def _concat_list(parts: Sequence[Path]) -> Iterator[Path]:
    """An ffmpeg concat-demuxer list file naming `parts`."""
    fd, name = tempfile.mkstemp(suffix=".txt", prefix="concat-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for part in parts:
                escaped = part.resolve().as_posix().replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
        yield Path(name)
    finally:
        Path(name).unlink(missing_ok=True)
