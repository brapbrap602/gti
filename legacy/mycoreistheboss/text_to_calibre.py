import html
import os
import re


def txt_to_calibre_html(input_file, output_file, book_title="My Book"):
    """
    Converts a #
    chapter.js and style.css files.
    """

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = r'(##\sChapter\s\d+)'
    parts = re.split(pattern, content)
    parsed_chapters = []

    for i in range(1, len(parts), 2):
        marker = parts[i]  # e.g., "## Chapter 301"
        content_raw = parts[i + 1]  # e.g., ": Using Connections\n\nText..."

        # Recombine to parse the first line correctly
        full_section = marker + content_raw
        split_section = full_section.split('\n', 1)
        raw_title = split_section[0].strip()  # "## Chapter 301: Using Connections"
        clean_title = raw_title.replace('##', '').strip()
        body_text = split_section[1] if len(split_section) > 1 else ""
        lines = body_text.split('\n')

        # (If the scraper put the title again on the next line)
        if lines and (clean_title in lines[0] or raw_title in lines[0]):
            lines.pop(0)
        if lines and (clean_title in lines[1] or raw_title in lines[1]):
            lines.pop(1)

        html_paragraphs = []
        for line in lines:
            line = line.strip()
            if line:
                html_paragraphs.append(f"<p>{html.escape(line)}</p>")

        parsed_chapters.append({
            'title': clean_title,
            'body': "\n".join(html_paragraphs)
        })

    print(f"Found {len(parsed_chapters)} chapters.")

    html_head = f"""<!DOCTYPE html>
<html>
  <head>
    <meta http-equiv="Content-Type" content="text/html;charset=utf-8" />
    <title>{book_title}</title>
    <link rel="stylesheet" href="../style.css">
    <script src="../chapter.js"></script>
  </head>
  <body>
    <div class="calibre" id="calibre_link-top">
"""

    toc_html = f"""
      <nav type="toc" id="calibre_link-toc" role="doc-toc">
        <h2 class="calibre1">{book_title} - Table of Contents</h2>
        <ol class="calibre2">
"""

    for index, chap in enumerate(parsed_chapters):
        toc_html += f"""          <li class="calibre3">
            <a href="#calibre_link-{index}">{html.escape(chap['title'])}</a>
          </li>\n"""

    toc_html += "        </ol>\n      </nav>\n"

    content_html = ""

    for index, chap in enumerate(parsed_chapters):
        content_html += f'\n      <div class="calibre" id="calibre_link-{index}"></div>'

        content_html += f'\n      <h3 class="calibre1" style="color:#80cbc4;">{html.escape(chap["title"])}</h3>\n'

        content_html += chap['body']

        content_html += '\n      <hr class="calibre1" style="border-color:#333;">\n'

    html_footer = """
    </div>
  </body>
</html>
"""

    full_html = html_head + toc_html + content_html + html_footer

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(full_html)

    print(f"Successfully converted {len(parsed_chapters)} chapters to {output_file}")


INPUT_FILENAME = r"C:\Users\HT\Documents\code\mycoreistheboss\My Longevity Simulation"
OUTPUT_FILENAME = r"C:\Users\HT\Documents\code\mycoreistheboss\index.html"
BOOK_TITLE = "My Longevity Simulation"

if __name__ == "__main__":
    txt_to_calibre_html(INPUT_FILENAME, OUTPUT_FILENAME, BOOK_TITLE)
