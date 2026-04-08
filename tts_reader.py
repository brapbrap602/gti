"""
TTS Reader - sentence-by-sentence generation with resume support and ID3 chapter markers.

Pipeline:
  Parse HTML -> chapters -> paragraphs -> sentences
  Generate   -> one mp3 per sentence (skips existing = resumable)
  Combine    -> sentences -> chapter mp3 -> book mp3 with ID3 CHAP markers

Structure:
  tts_out/
    chapter_010/
      ch010_p001_s001.mp3
      ch010_p001_s002.mp3
      ...
      chapter_010.mp3       <- combined chapter
    book.mp3                <- combined book with chapter markers

Usage:
  python tts_reader.py                          # all chapters
  python tts_reader.py --chapter 10             # single chapter
  python tts_reader.py --range 1-10             # chapter range
  python tts_reader.py --chapters 5,10,27       # specific chapters
"""

import argparse
import asyncio
import re
import shutil
import subprocess
from pathlib import Path

import edge_tts
from edge_tts.exceptions import NoAudioReceived
import nltk
from bs4 import BeautifulSoup, NavigableString
from mutagen.id3 import ID3, CHAP, TIT2, CTOC, CTOCFlags, ID3NoHeaderError
from mutagen.mp3 import MP3

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HTML_FILE = r"novels\Who Let Him Cultivate\index_1_50.html"
OUT_DIR = Path("tts_out")
VOICE = "en-US-BrianMultilingualNeural"
CONCURRENCY = 2  # simultaneous TTS requests
RETRY_ATTEMPTS = 5
RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry

# Per-novel HTML parsing config.
# title_selector : CSS selector for the chapter title element (scoped to the chapter div)
# para_class     : class of <p> tags that contain body text
# id_offset      : calibre_link-N minus this = chapter number (0 means IDs match chapter nums)
NOVEL_CONFIGS: dict[str, dict] = {
    "who let him cultivate": {
        "title_selector": "div.content-inner div.content-inner",
        "para_class": "calibre4",
        "id_offset": 0,
        # TOC titles in some exports are prefixed with the novel name; strip it.
        "title_strip_prefix": "Who Let Him Cultivate",
        # When calibre_link IDs don't match chapter numbers, extract from title.
        "chapter_num_from_title": True,
    },
    "beyond the timescape": {
        "title_selector": "p.calibre5",
        "para_class": "calibre5",
        "id_offset": 1,  # calibre_link-2 = Chapter 1, etc.
    },
    "cultivation chat group": {
        "title_selector": None,  # title comes from TOC; in-div <p> is unreliable
        "para_class": "calibre4",
        "id_offset": 0,  # calibre_link-1 = Chapter 1
    },
}
DEFAULT_NOVEL = "who let him cultivate"


def detect_novel(html_file: str) -> str | None:
    """Return the novel key whose name appears in the html_file path, or None."""
    path_lower = html_file.replace("\\", "/").lower()
    for key in NOVEL_CONFIGS:
        if key in path_lower:
            return key
    return None


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def fix_encoding(raw: str) -> str:
    """Replace Windows-1252 bytes that leaked into the UTF-8 file."""
    table = {
        "\x93": "\u201c",
        "\x94": "\u201d",
        "\x91": "\u2018",
        "\x92": "\u2019",
        "\x96": "\u2013",
        "\x97": "\u2014",
        "\x85": "\u2026",
    }
    for bad, good in table.items():
        raw = raw.replace(bad, good)
    return raw


def load_html(html_file: str) -> BeautifulSoup:
    with open(html_file, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    return BeautifulSoup(fix_encoding(raw), "html.parser")


def toc_chapter_range(soup: BeautifulSoup) -> tuple[int, int]:
    """Return (first, last) chapter numbers found in the TOC nav."""
    ids = [
        int(m.group(1))
        for a in soup.select("nav[role='doc-toc'] a[href]")
        if (m := re.search(r"calibre_link-(\d+)", a["href"]))
    ]
    if not ids:
        return (0, 0)
    return (min(ids), max(ids))


def _toc_title_map(
    soup: BeautifulSoup, title_strip_prefix: str | None = None
) -> dict[str, str]:
    """Build a map of calibre_link-ID -> title text from the TOC nav.

    If title_strip_prefix is given, any title starting with that string
    (followed by optional punctuation/spaces up to 'Chapter') is stripped
    down to the 'Chapter ...' portion.
    """
    mapping = {}
    for a in soup.select("nav[role='doc-toc'] a[href]"):
        m = re.search(r"calibre_link-(\d+)", a.get("href", ""))
        if m:
            title = a.get_text(strip=True)
            if title_strip_prefix:
                # Strip everything up to and including the last '-' or ':' before 'Chapter'
                clean = re.sub(
                    r"^.*?(?:Chapter\s)", "Chapter ", title, flags=re.IGNORECASE
                )
                if clean != title:
                    title = clean
            mapping[f"calibre_link-{m.group(1)}"] = title
    return mapping


def parse_chapters(soup: BeautifulSoup, novel_cfg: dict) -> list[dict]:
    """
    Return list of:
      { "id": "calibre_link-10", "title": "Chapter 10: ...", "paragraphs": [...] }

    novel_cfg keys:
      title_selector  - CSS selector for the title element inside the chapter div.
                        Use None to fall back to the TOC title map for all chapters.
      para_class      - p class name for body paragraphs
      id_offset       - subtract from calibre_link-N to get chapter number (default 0)
    """
    title_selector = novel_cfg.get("title_selector")
    para_class = novel_cfg["para_class"]
    id_offset = novel_cfg.get("id_offset", 0)
    title_strip_prefix = novel_cfg.get("title_strip_prefix")

    toc_titles = _toc_title_map(soup, title_strip_prefix=title_strip_prefix)

    chapters = []
    for chapter_div in soup.find_all("div", class_="calibre"):
        cid = chapter_div.get("id", "")
        if not cid.startswith("calibre_link-") or cid == "calibre_link-0":
            continue

        # Resolve title: try in-div selector first, fall back to TOC map
        title_tag = chapter_div.select_one(title_selector) if title_selector else None
        if title_tag:
            # Extract only the direct text nodes (not text from child <p> or other tags)
            direct_text = "".join(
                str(node)
                for node in title_tag.children
                if isinstance(node, NavigableString)
            ).strip()
            inline_title = (
                direct_text if direct_text else title_tag.get_text(strip=True)
            )
            # Only trust it if it looks like a chapter heading
            title = (
                inline_title
                if re.search(r"(?i)\bchapter\b.*\d", inline_title)
                else toc_titles.get(cid, "")
            )
        else:
            title = toc_titles.get(cid, "")

        if not title:
            continue

        paragraphs = []
        title_skipped = (
            title_tag is not None
        )  # Layout A skips by identity; others skip by text match
        for p in chapter_div.find_all("p", class_=para_class):
            if p is title_tag:
                continue  # Layout A: skip the title <p> by identity
            text = p.get_text(" ", strip=True)
            if not title_skipped and text == title:
                title_skipped = True
                continue  # Layout B/CCG: skip first <p> whose text matches the TOC title
            if (
                text
                and not re.match(r"^[~\-*=`\s]+$", text)
                and not re.match(r"^\d+\.\s", text)
            ):
                paragraphs.append(text)

        if paragraphs:
            chapters.append(
                {
                    "id": cid,
                    "title": title,
                    "paragraphs": paragraphs,
                    "id_offset": id_offset,
                    "chapter_num_from_title": novel_cfg.get(
                        "chapter_num_from_title", False
                    ),
                }
            )

    return chapters


def chapter_index(chapter: dict) -> int:
    if chapter.get("chapter_num_from_title"):
        m = re.search(r"Chapter\s+(\d+)", chapter["title"], re.IGNORECASE)
        if m:
            return int(m.group(1))
    m = re.search(r"calibre_link-(\d+)", chapter["id"])
    return int(m.group(1)) - chapter.get("id_offset", 0) if m else 0


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in nltk.sent_tokenize(text) if s.strip()]


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe"
    if winget.exists():
        return str(winget)
    raise FileNotFoundError("ffmpeg not found. Install it or add it to PATH.")


def ffmpeg_concat(chunks: list[Path], output: Path, ffmpeg: str) -> None:
    """Concatenate mp3 files using ffmpeg concat demuxer."""
    if not chunks:
        return
    list_file = output.parent / f"_concat_{output.stem}.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(f"file '{c.resolve().as_posix()}'\n")
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {output}:\n{result.stderr}")


def get_mp3_duration_ms(path: Path) -> int:
    """Return duration of an mp3 file in milliseconds."""
    audio = MP3(str(path))
    return int(audio.info.length * 1000)


# ---------------------------------------------------------------------------
# ID3 chapter markers
# ---------------------------------------------------------------------------


def embed_chapter_markers(
    book_mp3: Path, chapter_mp3s: list[Path], titles: list[str]
) -> None:
    """
    Embed ID3 CHAP frames and a CTOC table of contents into book_mp3.
    Each chapter_mp3 duration is measured to calculate start/end times.
    """
    print(
        f"\n[ID3] Embedding {len(chapter_mp3s)} chapter markers into {book_mp3.name} ..."
    )

    # Calculate start/end times for each chapter
    start_ms = 0
    chapters_info = []
    for mp3_path, title in zip(chapter_mp3s, titles):
        dur = get_mp3_duration_ms(mp3_path)
        chapters_info.append(
            {
                "title": title,
                "start_ms": start_ms,
                "end_ms": start_ms + dur,
            }
        )
        start_ms += dur

    # Load or create ID3 tag
    try:
        tags = ID3(str(book_mp3))
    except ID3NoHeaderError:
        tags = ID3()

    # Remove any existing chapter/TOC frames
    for key in list(tags.keys()):
        if key.startswith("CHAP") or key.startswith("CTOC"):
            del tags[key]

    # Add CHAP frames
    chap_ids = []
    for i, ch in enumerate(chapters_info):
        element_id = f"ch{i:03d}"
        chap_ids.append(element_id)
        tags.add(
            CHAP(
                element_id=element_id,
                start_time=ch["start_ms"],
                end_time=ch["end_ms"],
                start_offset=0xFFFFFFFF,
                end_offset=0xFFFFFFFF,
                sub_frames=[TIT2(encoding=3, text=ch["title"])],
            )
        )
        print(f"  {element_id}: {ch['title']} ({ch['start_ms']}ms - {ch['end_ms']}ms)")

    # Add CTOC (table of contents) pointing to all chapters
    tags.add(
        CTOC(
            element_id="toc",
            flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids=chap_ids,
            sub_frames=[TIT2(encoding=3, text="Table of Contents")],
        )
    )

    tags.save(str(book_mp3), v2_version=3)
    print(f"[ID3] Done.")


# ---------------------------------------------------------------------------
# TTS with retry + semaphore
# ---------------------------------------------------------------------------


async def tts_save(text: str, path: Path, semaphore: asyncio.Semaphore) -> None:
    """Generate TTS for text, save to path. Skips if file already exists."""
    if path.exists() and path.stat().st_size > 0:
        return  # resume: already done

    async with semaphore:
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                communicate = edge_tts.Communicate(text, VOICE)
                await communicate.save(str(path))
                return
            except NoAudioReceived:
                if attempt == RETRY_ATTEMPTS:
                    print(
                        f"  [SKIP] No audio received after {RETRY_ATTEMPTS} attempts: {path.name} — skipping sentence."
                    )
                    return
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(
                    f"  [RETRY {attempt}] {path.name} — No audio received — waiting {delay:.1f}s"
                )
                await asyncio.sleep(delay)
            except Exception as e:
                if attempt == RETRY_ATTEMPTS:
                    print(
                        f"  [ERROR] Failed after {RETRY_ATTEMPTS} attempts: {path.name} — {e}"
                    )
                    raise
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  [RETRY {attempt}] {path.name} — {e} — waiting {delay:.1f}s")
                await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Chapter pipeline
# ---------------------------------------------------------------------------


async def process_chapter(
    chapter: dict,
    ch_idx: int,
    ffmpeg: str,
    semaphore: asyncio.Semaphore,
    out_dir: Path,
) -> Path:
    ch_dir = out_dir / f"chapter_{ch_idx:03d}"
    ch_dir.mkdir(parents=True, exist_ok=True)

    chapter_mp3 = ch_dir / f"chapter_{ch_idx:03d}.mp3"
    print(f"\n[Chapter {ch_idx:03d}] {chapter['title']}")

    all_sentence_files: list[Path] = []

    # Title as first audio chunk
    title_path = ch_dir / f"ch{ch_idx:03d}_p000_s000.mp3"
    await tts_save(chapter["title"], title_path, semaphore)
    if title_path.exists() and title_path.stat().st_size > 0:
        all_sentence_files.append(title_path)

    for p_idx, para in enumerate(chapter["paragraphs"], 1):
        sentences = split_sentences(para)
        tasks, s_paths = [], []
        for s_idx, sentence in enumerate(sentences, 1):
            s_path = ch_dir / f"ch{ch_idx:03d}_p{p_idx:03d}_s{s_idx:03d}.mp3"
            s_paths.append(s_path)
            tasks.append(tts_save(sentence, s_path, semaphore))
            try:
                print(
                    f"  p{p_idx:03d} s{s_idx:03d}: {sentence[:80]}{'...' if len(sentence) > 80 else ''}"
                )
            except UnicodeEncodeError:
                print(f"  p{p_idx:03d} s{s_idx:03d}: [non-printable characters]")

        await asyncio.gather(*tasks)
        all_sentence_files.extend(
            p for p in s_paths if p.exists() and p.stat().st_size > 0
        )

    print(
        f"  [ffmpeg] Combining {len(all_sentence_files)} sentences -> {chapter_mp3.name}"
    )
    ffmpeg_concat(all_sentence_files, chapter_mp3, ffmpeg)
    return chapter_mp3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate TTS audiobook from novel HTML with ID3 chapter markers."
    )
    parser.add_argument(
        "html_file",
        nargs="?",
        default=HTML_FILE,
        help="Path to the HTML file (default: %(default)s)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--chapter",
        "-c",
        type=int,
        metavar="N",
        help="Single chapter number, e.g. --chapter 10",
    )
    group.add_argument(
        "--range",
        "-r",
        type=str,
        metavar="START-END",
        help="Chapter range, e.g. --range 1-10",
    )
    group.add_argument(
        "--chapters",
        "-C",
        type=str,
        metavar="N,N,N",
        help="Specific chapters, e.g. --chapters 5,10,27",
    )
    parser.add_argument(
        "--out",
        "-o",
        type=Path,
        default=OUT_DIR,
        help="Output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--novel",
        "-n",
        type=str,
        default=None,
        choices=list(NOVEL_CONFIGS.keys()),
        help="Novel name for HTML parsing config (auto-detected from path if omitted)",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    args = parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(exist_ok=True)
    ffmpeg = find_ffmpeg()

    novel_name = args.novel or detect_novel(args.html_file) or DEFAULT_NOVEL
    novel_cfg = NOVEL_CONFIGS[novel_name]
    print(f"Novel config: {novel_name}")

    print(f"Loading {args.html_file} ...")
    soup = load_html(args.html_file)
    chapters = parse_chapters(soup, novel_cfg)
    available_indices = sorted(chapter_index(c) for c in chapters)
    file_first = available_indices[0] if available_indices else 0
    file_last = available_indices[-1] if available_indices else 0
    print(f"Found {len(chapters)} chapters (range: {file_first}–{file_last})")

    # Filter by CLI args, with clear messaging when chapters aren't in this file
    available = {chapter_index(c) for c in chapters}

    if args.chapter is not None:
        requested = {args.chapter}
        missing = requested - available
        if missing:
            print(f"Error: Chapter {args.chapter} is not in this file.")
            print(f"  This file contains chapters {file_first}–{file_last}.")
            return
        chapters = [c for c in chapters if chapter_index(c) in requested]

    elif args.range is not None:
        start, end = (int(x) for x in args.range.split("-"))
        requested = set(range(start, end + 1))
        found = requested & available
        missing = requested - available
        if not found:
            print(f"Error: None of chapters {start}–{end} are in this file.")
            print(f"  This file contains chapters {file_first}–{file_last}.")
            return
        if missing:
            print(
                f"Warning: Chapters {sorted(missing)} are not in this file and will be skipped."
            )
        chapters = [c for c in chapters if chapter_index(c) in found]

    elif args.chapters is not None:
        requested = {int(x) for x in args.chapters.split(",")}
        found = requested & available
        missing = requested - available
        if not found:
            print(
                f"Error: None of the requested chapters {sorted(requested)} are in this file."
            )
            print(f"  This file contains chapters {file_first}–{file_last}.")
            return
        if missing:
            print(
                f"Warning: Chapters {sorted(missing)} are not in this file and will be skipped."
            )
        chapters = [c for c in chapters if chapter_index(c) in found]

    if not chapters:
        print("No chapters matched.")
        return

    print(
        f"Processing {len(chapters)} chapter(s): "
        f"{', '.join(str(chapter_index(c)) for c in chapters)}"
    )

    semaphore = asyncio.Semaphore(CONCURRENCY)
    chapter_mp3s: list[Path] = []

    for chapter in chapters:
        ch_idx = chapter_index(chapter)
        ch_mp3 = await process_chapter(
            chapter,
            ch_idx,
            ffmpeg,
            semaphore,
            out_dir=out_dir,
        )
        chapter_mp3s.append(ch_mp3)

    if len(chapter_mp3s) == 1:
        print(f"\nDone! Chapter saved to {chapter_mp3s[0]}")
    else:
        # book_mp3 = out_dir / "book.mp3"
        # print(f"\n[ffmpeg] Combining {len(chapter_mp3s)} chapters -> {book_mp3}")
        # ffmpeg_concat(chapter_mp3s, book_mp3, ffmpeg)

        # Embed ID3 chapter markers
        # titles = [c["title"] for c in chapters]
        # embed_chapter_markers(book_mp3, chapter_mp3s, titles)
        #
        # print(f"\nDone! Book with chapter markers saved to {book_mp3}")
        print("done")


if __name__ == "__main__":
    asyncio.run(main())
