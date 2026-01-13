import re

input_file = 'latest_lon_sim/index.html'
output_file = 'chapter_headers.txt'

pattern = re.compile(r'<h1 id="(calibre_link-\d+)" class="calibre1">(.*?)</h1>')

with open(input_file, 'r', encoding='utf-8') as f:
    content = f.read()

matches = pattern.findall(content)

with open(output_file, 'w', encoding='utf-8') as f:
    for link_id, title in matches:
        f.write(f'{link_id}|{title}\n')

print(f'Extracted {len(matches)} chapters.')
