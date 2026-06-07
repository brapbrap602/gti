"""
Extract chapter headers from a Calibre HTML file.

Scans for <h1 id="calibre_link-N"> tags and writes them to a text file
in the format used by insert_toc.py.

Usage:
    python scripts/extract_chapters.py <input_html> [output_file]

    If output_file is omitted, writes to chapter_headers.txt in the same
    directory as the input HTML file.

Example:
    python scripts/extract_chapters.py "novels/my longevity simulation/index.html"
"""

import argparse
import re
from pathlib import Path

parser = argparse.ArgumentParser(description="Extract chapter headers from Calibre HTML.")
parser.add_argument("input", help="Input HTML file")
parser.add_argument("output", nargs="?", help="Output text file (default: <input_dir>/chapter_headers.txt)")

args = parser.parse_args()

input_path = Path(args.input)
output_path = Path(args.output) if args.output else input_path.parent / "chapter_headers.txt"

pattern = re.compile(r'<h1 id="(calibre_link-\d+)" class="calibre1">(.*?)</h1>')

try:
    content = input_path.read_text(encoding="utf-8")
except UnicodeDecodeError:
    content = input_path.read_text(encoding="latin-1")

matches = pattern.findall(content)

with open(output_path, "w", encoding="utf-8") as f:
    for link_id, title in matches:
        f.write(f"{link_id}|{title}\n")

print(f"Extracted {len(matches)} chapters to {output_path}")
