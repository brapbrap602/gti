from pathlib import Path

import requests
from bs4 import BeautifulSoup
import time
import html5lib

# Assuming 'chapters.txt' contains URLs of chapters
for line in Path("chapters.txt").read_text(encoding="utf-8").split():
    r = requests.get(line.strip())
    soup = BeautifulSoup(r.content, features="lxml")

    # chapter_item = soup.find(id="chapter_item")
    chapter_item = soup.find(class_="content")
    # p_tags = chr_content.find_all('p')
    # title = chr_content.find('h4')
    _title = soup.find(class_="chapter_name").text
    title = f'<h2>{_title}</h2><p></p>'
    print(_title)
    with open("beyond_the_timescape.html", "a", encoding="utf-8") as f:
        f.write(title)
        f.write(str(chapter_item))
