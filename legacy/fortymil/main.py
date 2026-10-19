import html5lib
import requests
import time
from bs4 import BeautifulSoup

for x in range(1449, 1840):
    r = requests.get(
        f"https://boxnovel.com/novel/forty-millenniums-of-cultivation/chapter-{x}"
    )
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for stuff in soup.find_all("div", {"class": "reading-content"}):
        best_stuff = stuff.text
        with open("fortymil_1449_1839.txt", "a", encoding="utf-8") as f:
            f.write(best_stuff)
