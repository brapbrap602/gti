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
    pattern = re.compile(r'href="#calibre_link-(\d+)"')
    return pattern.findall(content)


def extract_all_chapters(content, chapter_ids):
    """Single-pass extraction: find all chapter divs and slice between boundaries.

    Returns a dict mapping chapter_id (str) -> html string for that chapter.
    Each chapter runs from its opening div tag up to (but not including) the
    next sibling calibre div, or the </body> tag.
    """
    id_set = set(chapter_ids)

    # Find every <div class="calibre" id="calibre_link-N"> in document order
    div_pattern = re.compile(
        r'<div\s[^>]*class="calibre"[^>]*id="calibre_link-(\d+)"[^>]*>', re.DOTALL
    )
    all_divs = [(m.group(1), m.start()) for m in div_pattern.finditer(content)]

    # Find end of body
    body_end = re.search(r"</body", content, re.IGNORECASE)
    doc_end = body_end.start() if body_end else len(content)

    chapters = {}
    for i, (div_id, start_pos) in enumerate(all_divs):
        if div_id not in id_set:
            continue
        # Slice ends at the start of the next calibre div, or </body>
        end_pos = all_divs[i + 1][1] if i + 1 < len(all_divs) else doc_end
        chapters[div_id] = content[start_pos:end_pos]

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


def build_toc_content(toc_match, start, end, chapter_ids):
    """Build a filtered TOC nav element for chapters start..end (1-indexed)."""
    if not toc_match:
        return ""

    toc_start_tag = toc_match.group(1)
    toc_inner = toc_match.group(2)
    toc_end_tag = toc_match.group(3)

    li_pattern = re.compile(r"(<li[^>]*>.*?</li>)", re.DOTALL)
    lis = li_pattern.findall(toc_inner)
    filtered_lis = lis[start - 1 : end]

    h2_match = re.search(r"(<h2[^>]*>)(.*?)(</h2>)", toc_inner, re.DOTALL)
    ol_start_match = re.search(r"(<ol[^>]*>)", toc_inner)

    if h2_match:
        h2 = f"{h2_match.group(1)}Chapters {start} - {end}{h2_match.group(3)}"
    else:
        h2 = f"<h2>Chapters {start} - {end}</h2>"
    ol_start = '<ul style="list-style: none; padding: 0;">'

    new_toc_inner = (
        f"\n      {h2}\n      {ol_start}\n        "
        + "\n        ".join(filtered_lis)
        + "\n      </ul>\n    "
    )
    return toc_start_tag + new_toc_inner + toc_end_tag


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
        print(f"Creating chapters {start} - {end}...")

        toc_content = build_toc_content(toc_match, start, end, chapter_ids)

        valid_segments = [
            chapter_map[ch_id]
            for ch_id in chapter_ids[start - 1 : end]
            if ch_id in chapter_map
        ]

        output_file = folder / f"index_{start}_{end}.html"
        split_files.append(f"novels/{novel_name}/{output_file.name}")
        split_ranges.append((start, end))

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

    for file_path, (start, end) in zip(split_files, split_ranges):
        library_data.append(
            {
                "novel": novel_title,
                "title": f"{novel_title} Chs {start}-{end}",
                "chapters": {"start": start, "end": end},
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
