#!/usr/bin/env python3
"""
Tag audiobook chapter MP3s with ID3 metadata.

Usage:
    # Tag files in the test directory (uses default WLHCI metadata):
    python tag_audiobook.py --dir tag_test

    # Tag all chapters in a tts_out-style folder (chapter_NNN subdirs):
    python tag_audiobook.py --dir tts_out --recursive

    # Tag a different book with custom metadata:
    python tag_audiobook.py --dir "tts_out/beyond the timescape" --recursive \\
        --album "Beyond the Timescape" --artist "Er Gen" \\
        --comment "Xianxia audiobook by Er Gen | Translator: Deathblade | Publisher: Wuxiaworld" \\
        --cover tag_test/cover_bts.jpg

    # Dry run (print what would be done without writing):
    python tag_audiobook.py --dir tag_test --dry-run
"""

import argparse
import os
import re
import sys
from pathlib import Path

from mutagen.id3 import (
    ID3,
    APIC,  # Cover art
    TIT2,  # Title
    TALB,  # Album
    TPE1,  # Artist
    TRCK,  # Track number
    TCON,  # Genre
    COMM,  # Comment
    ID3NoHeaderError,
)
from mutagen.mp3 import MP3

# ── Book metadata ─────────────────────────────────────────────────────────────
METADATA = {
    "album": "Who Let Him Cultivate Immortality",
    "artist": "The Whitest Crow (最白的乌鸦)",
    "genre": "Audiobook",
    "comment": (
        "Xianxia comedy audiobook. "
        "Original title: 谁让他修仙的！ | Publisher: Wuxiaworld | Year: 2023"
    ),
    # Cover image path – relative to this script or absolute
    "cover": Path(__file__).parent / "tag_test" / "cover.png",
}
# ─────────────────────────────────────────────────────────────────────────────


def load_cover(cover_path: Path) -> bytes | None:
    """Return raw PNG/JPEG bytes for the cover, or None if not found."""
    cover_path = Path(cover_path)
    if not cover_path.exists():
        print(f"  [WARN] Cover not found at {cover_path}; skipping cover art.")
        return None
    with open(cover_path, "rb") as f:
        return f.read()


def chapter_number_from_filename(filename: str) -> int | None:
    """
    Extract chapter number from filenames like:
      chapter_151.mp3  ->  151
      ch151_p000.mp3   ->  151
    """
    m = re.search(r"chapter[_\-]?(\d+)", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"ch(\d+)", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def tag_mp3(
    mp3_path: Path, cover_data: bytes | None, meta: dict, dry_run: bool = False
):
    """Apply ID3 tags to a single MP3 file."""
    ch_num = chapter_number_from_filename(mp3_path.name)
    if ch_num is None:
        print(f"  [SKIP] Cannot determine chapter number: {mp3_path.name}")
        return

    title = f"Chapter {ch_num}"
    track = str(ch_num)

    print(f"  {'[DRY] ' if dry_run else ''}Tagging {mp3_path.name}  ->  {title}")

    if dry_run:
        return

    # Load or create ID3 header
    try:
        tags = ID3(str(mp3_path))
    except ID3NoHeaderError:
        tags = ID3()

    tags.delall("TIT2")
    tags.delall("TALB")
    tags.delall("TPE1")
    tags.delall("TRCK")
    tags.delall("TCON")
    tags.delall("COMM")
    tags.delall("APIC")

    tags["TIT2"] = TIT2(encoding=3, text=title)
    tags["TALB"] = TALB(encoding=3, text=meta["album"])
    tags["TPE1"] = TPE1(encoding=3, text=meta["artist"])
    tags["TRCK"] = TRCK(encoding=3, text=track)
    tags["TCON"] = TCON(encoding=3, text=meta["genre"])
    tags["COMM"] = COMM(encoding=3, lang="eng", desc="", text=meta["comment"])

    if cover_data:
        mime = "image/png" if cover_data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        tags["APIC"] = APIC(
            encoding=0,
            mime=mime,
            type=3,  # Front cover
            desc="Cover",
            data=cover_data,
        )

    tags.save(str(mp3_path), v2_version=3)


def collect_mp3s(root: Path, recursive: bool) -> list[Path]:
    """
    Collect target MP3s.

    Non-recursive: every *.mp3 directly in `root`.
    Recursive:     chapter_NNN.mp3 inside chapter_NNN/ subdirectories of `root`.
    """
    if not recursive:
        return sorted(root.glob("*.mp3"))

    # tts_out layout: tts_out/chapter_NNN/chapter_NNN.mp3
    mp3s = []
    for chapter_dir in sorted(root.iterdir()):
        if not chapter_dir.is_dir():
            continue
        m = re.match(r"chapter_(\d+)$", chapter_dir.name, re.IGNORECASE)
        if not m:
            continue
        ch_mp3 = chapter_dir / f"{chapter_dir.name}.mp3"
        if ch_mp3.exists():
            mp3s.append(ch_mp3)
        else:
            # Fallback: pick any mp3 whose name contains the chapter number
            candidates = list(chapter_dir.glob(f"*chapter_{m.group(1)}*.mp3"))
            mp3s.extend(sorted(candidates))
    return mp3s


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Tag audiobook chapter MP3s with ID3 metadata.\n\n"
            "Example:\n"
            '  python tag_audiobook.py --dir "tts_out/<book folder>" --recursive \\\n'
            '    --album "Book Title" --artist "Author Name" \\\n'
            '    --comment "your comment" --cover "path/to/cover.jpg"'
        ),
    )
    parser.add_argument("--dir", required=True, help="Directory to process")
    parser.add_argument(
        "--cover", default=None, help="Path to cover image (overrides default)"
    )
    parser.add_argument(
        "--album", default=None, help="Album / book title (overrides default)"
    )
    parser.add_argument(
        "--artist", default=None, help="Artist / author name (overrides default)"
    )
    parser.add_argument(
        "--comment", default=None, help="Comment tag (overrides default)"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse into chapter_NNN subdirectories (for tts_out layout)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without modifying files",
    )
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.exists():
        print(f"Error: directory not found: {root}")
        sys.exit(1)

    # Build effective metadata (CLI args override defaults)
    meta = {
        "album": args.album or METADATA["album"],
        "artist": args.artist or METADATA["artist"],
        "genre": METADATA["genre"],
        "comment": args.comment or METADATA["comment"],
    }

    cover_path = Path(args.cover) if args.cover else METADATA["cover"]
    cover_data = load_cover(cover_path)

    mp3s = collect_mp3s(root, args.recursive)
    if not mp3s:
        print(f"No MP3s found in {root}")
        sys.exit(0)

    print(f"Found {len(mp3s)} MP3(s) in {root}")
    print(f"  Album  : {meta['album']}")
    print(f"  Artist : {meta['artist']}")
    print(f"  Cover  : {cover_path}\n")
    for mp3_path in mp3s:
        tag_mp3(mp3_path, cover_data, meta, dry_run=args.dry_run)

    print(f"\nDone. {'(dry run - no files modified)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
