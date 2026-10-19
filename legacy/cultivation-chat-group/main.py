import requests
from bs4 import BeautifulSoup
import time
import html5lib


for x in range(665, 1148):
    r = requests.get(
        "https://boxnovel.com/novel/cultivation-chat-group/chapter-{}".format(x)
    )
    soup = BeautifulSoup(r.content, features="lxml")
    print("On Chapter: {}".format(x))
    for stuff in soup.find_all("div", {"class": "reading-content"}):
        best_stuff = stuff.text
        with open("ccg_from_until_1148.txt", "a", encoding="utf-8") as f:
            f.write(best_stuff)
