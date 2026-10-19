from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import time
import html5lib


def write_to(text):
    with open("rmj_immortal-realm_to_903.txt", "a", encoding="utf-8") as f:
        f.write(text)


for link in Path(r"C:\Users\HT\Documents\code\rmji\ch_regex.txt").read_text().splitlines():
    r = requests.get(link)
    soup = BeautifulSoup(r.content, features="html5lib")
    print(f"On Chapter: {link}")

    ch_content = soup.find(id="chr-content")

    skip_oth = False
    ch_title = f'<h4>{link.split("/")[-1].replace("-", " ").capitalize()}</h4>'
    if h4_title := ch_content.find('h4'):
        ch_title = str(h4_title)
    all_p_tags = ch_content.find_all("p")
    if "Chapter" in str(all_p_tags[0]) and ":" in str(all_p_tags[0]):
        skip_oth = True
        ch_title = f"<h4>{str(all_p_tags[0].text)}</h4>"

    content = ch_title
    if skip_oth:
        all_p_tags = all_p_tags[1:]

    content += ''.join([str(para) for para in all_p_tags])
    content += "\n"

    write_to(content.replace(" ", ""))
