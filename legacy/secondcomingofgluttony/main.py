import html5lib
import requests
import time
from bs4 import BeautifulSoup


for x in range(147, 226):
    url = f"https://readnovelfull.com/the-second-coming-of-gluttony/chapter-{x}.html"
    url = f"https://listnovel.com/novel/the-second-coming-of-gluttony/chapter-{x}/"

    r = requests.get(url)

    if not r:
        print("not r: {url}")
        with open("secondcomingofgluttony.txt", "a", encoding="utf-8") as f:
            f.write(f"CHAPTER: {x} encountered server error read online pls thx")
    elif r:
        soup = BeautifulSoup(r.content, features="lxml")
        print("On Chapter: {}".format(x))
        for stuff in soup.find_all("div", {"class": "reading-content"}):
            best_stuff = stuff.text
            with open("2ndgluttony.txt", "a", encoding="utf-8") as f:
                f.write(best_stuff)
