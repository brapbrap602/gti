import requests
from bs4 import BeautifulSoup
import time

start = 1
stop = 1000
for x in range(start, stop):
    r = requests.get(
        "https://boxnovel.com/novel/the-experimental-log-of-the-crazy-lich/chapter-{}/".format(
            x
        )
    )
    soup = BeautifulSoup(r.content, features="lxml")
    time.sleep(0.5)
    print("On Chapter: {}".format(x))
    for stuff in soup.find_all("p", limit=150):
        best_stuff = stuff.text
        with open(
            "TheExperimentalLogoftheCrazyLich.txt", "a", encoding="utf-8"
        ) as writer:
            writer.write(best_stuff)
