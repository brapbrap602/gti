import requests
import bs4
import re

FILE_TITLE = "martial_world-2035-end.txt"
URL = "https://mnovelfree.com/martial-world-241220/chapter-{chapter}"


def get_content():
    for chapter in range(2035, 2280):
        r = requests.get(URL.format(chapter=chapter))
        wrap_in_bs4(r.text)


def wrap_in_bs4(content):
    soup = bs4.BeautifulSoup(content, "html.parser")
    for item in soup.find_all("p"):
        if "chapter" in item.text.lower():
            _ch = f"\n* {item.text} *\n"
            matches = bool(re.match(r"\n\*\s+Chapter\s+.*\*", string=_ch))
            print(f"On {item.text}. {' ' * 20}{matches=}")
            write_content(_ch)
        elif item.text:
            write_content(item.text)


def write_content(cleaned_content):
    if cleaned_content:
        with open(FILE_TITLE, "a") as f:
            f.write(f"\n{cleaned_content}")


get_content()
