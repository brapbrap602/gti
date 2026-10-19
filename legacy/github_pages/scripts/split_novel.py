"""
Split a Calibre HTML ebook into multiple files by chapter range.

This script takes an input HTML file (typically from Calibre conversion) and
splits it into multiple files, each containing a specified number of chapters.

It handles:
1. Creating split files (index_1_100.html, index_101_200.html, etc.)
2. Updating TOC to show only chapters in each file
3. Adding generic head elements (viewport, style.css, chapter.js)
4. Updating library.json with all split files

Usage:
    python scripts/split_novel.py <input_html> <chapters_per_file>

Example:
    python scripts/split_novel.py "Who Let Him Cultivate/index_all.html" 100

    Splits the novel into files with 100 chapters each.
"""

import argparse
import json
import re
from pathlib import Path


def extract_chapter_ids(content):
    """Return chapter IDs in TOC order, deduplicated (handles duplicate nav elements)."""
    pattern = re.compile(r'href="#calibre_link-(\d+)"')
    seen = set()
    result = []
    for cid in pattern.findall(content):
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


def extract_all_chapters(content, chapter_ids):
    """Single-pass extraction: find all chapter anchors and slice between boundaries.

    Supports two Calibre export structures:
      - div-based:  <div class="calibre" id="calibre_link-N">
      - h1-based:   <h1 id="calibre_link-N" ...>  (preceded by <div class="calibreN"></div>)

    Returns a dict mapping chapter_id (str) -> html string for that chapter.
    Each chapter runs from its opening tag up to (but not including) the next
    chapter boundary, or </body>.
    """
    id_set = set(chapter_ids)

    # Find end of body
    body_end = re.search(r"</body", content, re.IGNORECASE)
    doc_end = body_end.start() if body_end else len(content)

    # Try div-based structure first
    div_pattern = re.compile(
        r'<div\s[^>]*class="calibre"[^>]*id="calibre_link-(\d+)"[^>]*>', re.DOTALL
    )
    all_anchors = [(m.group(1), m.start()) for m in div_pattern.finditer(content)]

    # If only the wrapper div (calibre_link-0) was found, fall back to h1-based
    chapter_anchors = [(cid, pos) for cid, pos in all_anchors if cid in id_set]
    if not chapter_anchors:
        # h1-based: each chapter starts at the <div class="calibreN"></div> separator
        # that immediately precedes the <h1 id="calibre_link-N">, or at the h1 itself
        # for the very first chapter (which has no preceding separator).
        h1_pattern = re.compile(r'<h1[^>]*\bid="calibre_link-(\d+)"[^>]*>', re.DOTALL)
        h1_matches = [(m.group(1), m.start()) for m in h1_pattern.finditer(content)]

        # Build a lookup of h1 start positions so we can find the preceding separator
        sep_pattern = re.compile(r'<div\s[^>]*class="calibre\d+"[^>]*>\s*</div>')
        sep_positions = [m.start() for m in sep_pattern.finditer(content)]

        all_anchors = []
        for cid, h1_pos in h1_matches:
            # Find the closest separator that comes just before this h1
            preceding = [s for s in sep_positions if s < h1_pos]
            start_pos = preceding[-1] if preceding else h1_pos
            all_anchors.append((cid, start_pos))

        chapter_anchors = [(cid, pos) for cid, pos in all_anchors if cid in id_set]

    chapters = {}
    for i, (cid, start_pos) in enumerate(all_anchors):
        if cid not in id_set:
            continue
        end_pos = all_anchors[i + 1][1] if i + 1 < len(all_anchors) else doc_end
        chapters[cid] = content[start_pos:end_pos]

    return chapters


def get_novel_title(content):
    title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
    return title_match.group(1) if title_match else "Unknown"


def build_clean_head(content):
    """Build a clean <head> with only the required elements."""
    title = get_novel_title(content)
    return (
        "<head>\n"
        '    <meta charset="utf-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"    <title>{title}</title>\n"
        '    <link rel="stylesheet" href="../../assets/style.css">\n'
        '    <script src="../../assets/chapter.js"></script>\n'
        "</head>"
    )


def extract_chapter_number(li_html):
    """Pull the first integer after 'Chapter ' from a TOC <li> string, or None."""
    m = re.search(r"Chapter\s+(\d+)", li_html)
    return int(m.group(1)) if m else None


def build_toc_content(toc_match, start, end, chapter_ids):
    """Build a filtered TOC nav element for the slice chapter_ids[start-1:end].

    Returns (html, first_ch_num, last_ch_num) where the chapter numbers are the
    actual chapter numbers extracted from the titles (or None if not found).
    """
    if not toc_match:
        return "", None, None

    toc_start_tag = toc_match.group(1)
    toc_inner = toc_match.group(2)
    toc_end_tag = toc_match.group(3)

    li_pattern = re.compile(r"(<li[^>]*>.*?</li>)", re.DOTALL)
    lis = li_pattern.findall(toc_inner)
    filtered_lis = lis[start - 1 : end]

    # Derive human-readable chapter numbers from the actual titles
    first_num = extract_chapter_number(filtered_lis[0]) if filtered_lis else None
    last_num = extract_chapter_number(filtered_lis[-1]) if filtered_lis else None
    if first_num is not None and last_num is not None:
        label = f"Chapters {first_num} - {last_num}"
    else:
        label = f"Chapters {start} - {end}"

    h2_match = re.search(r"(<h2[^>]*>)(.*?)(</h2>)", toc_inner, re.DOTALL)
    if h2_match:
        h2 = f"{h2_match.group(1)}{label}{h2_match.group(3)}"
    else:
        h2 = f"<h2>{label}</h2>"
    ol_start = '<ul style="list-style: none; padding: 0;">'

    new_toc_inner = (
        f"\n      {h2}\n      {ol_start}\n        "
        + "\n        ".join(filtered_lis)
        + "\n      </ul>\n    "
    )
    return toc_start_tag + new_toc_inner + toc_end_tag, first_num, last_num


def process_chunks(input_path: Path, chapters_per_file: int):
    if not input_path.exists():
        print(f"Error: {input_path} does not exist")
        return

    input_path = input_path.resolve()
    folder = input_path.parent
    novel_name = folder.name

    print(f"Reading {input_path}...")
    try:
        content = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = input_path.read_text(encoding="latin-1")

    novel_title = get_novel_title(content)
    print(f"Novel: {novel_title}")

    chapter_ids = extract_chapter_ids(content)
    if not chapter_ids:
        print("Error: No chapters found in TOC.")
        return

    total_chapters = len(chapter_ids)
    print(f"Found {total_chapters} chapters")

    # Build a clean <head> (strips original Calibre head cruft and bad relative paths)
    clean_head = build_clean_head(content)

    # Find the TOC nav in the source so we can rebuild it per chunk
    toc_pattern = re.compile(
        r"(<nav[^>]*?role=\"doc-toc\"[^>]*>)(.*?)(</nav>)", re.DOTALL
    )
    toc_match = toc_pattern.search(content)
    if not toc_match:
        print("Warning: TOC not found in source file.")

    # Extract the wrapper div that holds the TOC: <div class="calibre" id="calibre_link-0">
    # We keep this as the body opener so anchors/IDs are preserved.
    toc_wrapper_open = '<div class="calibre" id="calibre_link-0">'

    footer_match = re.search(r"(</body>\s*</html>)", content, re.IGNORECASE)
    file_footer = footer_match.group(1) if footer_match else "</body></html>"

    # Single-pass extraction of all chapter content (O(n) over the file)
    print("Extracting chapter content...")
    chapter_map = extract_all_chapters(content, chapter_ids)
    print(f"Extracted {len(chapter_map)} chapters")

    split_files = []
    split_ranges = []

    for start in range(1, total_chapters + 1, chapters_per_file):
        end = min(start + chapters_per_file - 1, total_chapters)
        print(f"Creating positional slice {start} - {end}...")

        toc_content, first_ch, last_ch = build_toc_content(toc_match, start, end, chapter_ids)

        valid_segments = [
            chapter_map[ch_id]
            for ch_id in chapter_ids[start - 1 : end]
            if ch_id in chapter_map
        ]

        # Use real chapter numbers in file name when available
        file_start = first_ch if first_ch is not None else start
        file_end = last_ch if last_ch is not None else end

        output_file = folder / f"index_{file_start}_{file_end}.html"
        split_files.append(f"novels/{novel_name}/{output_file.name}")
        split_ranges.append((file_start, file_end))

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("<html>")
            f.write(clean_head)
            f.write("\n<body>")
            if toc_content:
                f.write(f"\n{toc_wrapper_open}\n{toc_content}\n</div>\n")
            f.write("\n")
            f.write("".join(valid_segments))
            f.write("\n" + file_footer)

        print(f"Created {output_file.name} with {len(valid_segments)} chapters")

    print(f"\nUpdating library.json...")
    library_path = Path("data/library.json")
    if library_path.exists():
        library_data = json.loads(library_path.read_text(encoding="utf-8"))
    else:
        library_data = []

    # Remove all existing entries for this novel (match by folder name, novel field, or title)
    library_data = [
        item
        for item in library_data
        if item.get("path", "").split("/")[0] != novel_name
        and item.get("novel", item.get("title")) != novel_title
    ]

    for file_path, (file_start, file_end) in zip(split_files, split_ranges):
        library_data.append(
            {
                "novel": novel_title,
                "title": f"{novel_title} Chs {file_start}-{file_end}",
                "chapters": {"start": file_start, "end": file_end},
                "path": file_path,
            }
        )

    library_data.sort(
        key=lambda x: (x["novel"], x["chapters"]["start"] if "chapters" in x else 0)
    )
    library_path.write_text(json.dumps(library_data, indent=2), encoding="utf-8")
    print(f"Updated library.json with {len(split_files)} entries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split HTML novel into chunks.")
    parser.add_argument("input", help="Input HTML file")
    parser.add_argument("chunks", type=int, help="Number of chapters per file")

    args = parser.parse_args()
    process_chunks(Path(args.input), args.chunks)
