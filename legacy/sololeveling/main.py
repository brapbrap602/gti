import requests
from bs4 import BeautifulSoup
import time
import html5lib


for x in range(136, 271):
    r = requests.get(
        "https://boxnovel.com/novel/i-alone-level-up/chapter-{}/".format(x)
    )
    soup = BeautifulSoup(r.content, features="lxml")
    print("On Chapter: {}".format(x))
    for stuff in soup.find_all("div", {"class": "reading-content"}):
        best_stuff = stuff.text
        with open("sololevling.txt", "a", encoding="utf-8") as f:
            f.write(best_stuff)
