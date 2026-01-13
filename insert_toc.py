import os

headers_file = 'chapter_headers.txt'
html_file = 'latest_lon_sim/index.html'
output_file = 'latest_lon_sim/index_newest.html' # Overwrite

# Generate TOC HTML
toc_lines = [
    '      <nav type="toc" id="toc_main" role="doc-toc">',
    '        <h2 class="calibre1">Table of Contents</h2>',
    '        <ol class="calibre2">'
]

with open(headers_file, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        link_id, title = line.split('|', 1)
        toc_lines.append(f'          <li class="calibre3">')
        toc_lines.append(f'            <a href="#{link_id}">{title}</a>')
        toc_lines.append(f'          </li>')

toc_lines.append('        </ol>')
toc_lines.append('      </nav>')

toc_html = '\n'.join(toc_lines)

# Insert into HTML file
with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

target = '<body><div class="calibre" id="calibre_link-0">'
if target in content:
    new_content = content.replace(target, f'{target}\n{toc_html}')
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Successfully inserted TOC.")
else:
    print("Error: Target div not found in HTML file.")
