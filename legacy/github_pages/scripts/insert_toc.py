"""
Insert a Table of Contents (TOC) navigation into a Calibre HTML file.

Reads chapter headers extracted by extract_chapters.py and generates a TOC
<nav> element, inserting it into the HTML file after the opening body div.

Workflow:
    1. python scripts/extract_chapters.py <input_html>
    2. python scripts/insert_toc.py <headers_file> <input_html>
    3. python scripts/split_novel.py <input_html> <chapters_per_file>

Usage:
    python scripts/insert_toc.py <headers_file> <input_html> [output_html]

    If output_html is omitted, the input file is updated in-place.

Example:
    python scripts/insert_toc.py "novels/my longevity simulation/chapter_headers.txt" "novels/my longevity simulation/index.html"
"""

import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description="Insert TOC into Calibre HTML file.")
parser.add_argument("headers", help="Headers text file with link_id|title format")
parser.add_argument("input", help="Input HTML file")
parser.add_argument("output", nargs="?", help="Output HTML file (default: overwrite input)")

args = parser.parse_args()

input_path = Path(args.input)
output_path = Path(args.output) if args.output else input_path

# Generate TOC HTML
toc_lines = [
    '      <nav type="toc" id="toc_main" role="doc-toc">',
    '        <h2 class="calibre1">Table of Contents</h2>',
    '        <ol class="calibre2">',
]

with open(args.headers, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        link_id, title = line.split("|", 1)
        toc_lines.append(f'          <li class="calibre3">')
        toc_lines.append(f'            <a href="#{link_id}">{title}</a>')
        toc_lines.append(f"          </li>")

toc_lines.append("        </ol>")
toc_lines.append("      </nav>")

toc_html = "\n".join(toc_lines)

# Insert into HTML file
try:
    content = input_path.read_text(encoding="utf-8")
except UnicodeDecodeError:
    content = input_path.read_text(encoding="latin-1")

target = '<body><div class="calibre" id="calibre_link-0">'
if target in content:
    new_content = content.replace(target, f"{target}\n{toc_html}")
    output_path.write_text(new_content, encoding="utf-8")
    print(f"Successfully inserted TOC into {output_path}")
else:
    print("Error: Target div not found in HTML file.")
