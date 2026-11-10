import re
import subprocess

from novel_audio.media import MP3_COVER_BYTES, MP3_COVER_PX, ffmpeg, mp3_cover


def _noise_png(path, w, h) -> bytes:
    """A PNG of random noise: large on disk, like a real high-resolution cover."""
    subprocess.run(
        [ffmpeg(), "-v", "error", "-f", "lavfi", "-i", f"nullsrc=s={w}x{h},geq=random(1)*255:128:128",
         "-frames:v", "1", str(path)],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


def _size(data: bytes, tmp_path) -> tuple[int, int]:
    """Width and height, read from the video stream line `ffmpeg -i` prints."""
    probe = tmp_path / "probe.jpg"
    probe.write_bytes(data)
    info = subprocess.run([ffmpeg(), "-i", str(probe)], capture_output=True, text=True).stderr
    w, h = re.search(r"Video: .*?, (\d+)x(\d+)", info).groups()
    return int(w), int(h)


def test_large_cover_is_shrunk_to_a_small_jpeg(tmp_path):
    cover = _noise_png(tmp_path / "cover.png", 1200, 1600)
    assert len(cover) > MP3_COVER_BYTES

    small = mp3_cover(cover)

    assert small.startswith(b"\xff\xd8") and len(small) < len(cover) // 4
    w, h = _size(small, tmp_path)
    assert max(w, h) == MP3_COVER_PX and abs(w / h - 1200 / 1600) < 0.01


def test_small_cover_is_kept_as_is():
    cover = b"\x89PNG\r\n\x1a\nfake"
    assert mp3_cover(cover) is cover
