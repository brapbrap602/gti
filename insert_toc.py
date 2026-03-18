"""
Insert a Table of Contents (TOC) navigation into a Calibre HTML file.

This script reads chapter headers previously extracted by extract_chapters.py
and generates a TOC <nav> element, then inserts it into the HTML file at a
specific location (after the main body div).

The TOC is formatted with:
- <nav role="doc-toc"> container
- <h2> heading for "Table of Contents"
- <ol> ordered list of chapter links

Each chapter entry links to its corresponding anchor ID (e.g., #calibre_link-0).

Workflow:
    1. Run extract_chapters.py to generate chapter_headers.txt
    2. Run insert_toc.py to build and insert the TOC

Usage:
    python insert_toc.py <headers_file> <html_file> <output_file>
"""

import argparse
import os

parser = argparse.ArgumentParser(description="Insert TOC into Calibre HTML file.")
parser.add_argument("headers", help="Headers text file with link_id|title format")
parser.add_argument("input", help="Input HTML file")
parser.add_argument("output", help="Output HTML file")

args = parser.parse_args()

headers_file = args.headers
html_file = args.input
output_file = args.output

# Generate TOC HTML
toc_lines = [
    '      <nav type="toc" id="toc_main" role="doc-toc">',
    '        <h2 class="calibre1">Table of Contents</h2>',
    '        <ol class="calibre2">',
]

with open(headers_file, "r", encoding="utf-8") as f:
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
with open(html_file, "r", encoding="utf-8") as f:
    content = f.read()

target = '<body><div class="calibre" id="calibre_link-0">'
if target in content:
    new_content = content.replace(target, f"{target}\n{toc_html}")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Successfully inserted TOC.")
else:
    print("Error: Target div not found in HTML file.")
