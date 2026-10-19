import requests
from bs4 import BeautifulSoup
import time
import html5lib

for x in range(1485, 2256 + 1):
    r = requests.get(f"https://novels247.com/martial-world/chapter-{x}")
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for stuff in soup.find_all("div", {"class": "text-content"}):
        for stuff in stuff.find_all("p"):
            best_stuff = stuff.text
            with open("mw1485-2257.txt", "a", encoding="utf-8") as f:
                f.write("\n\n")
                f.write(best_stuff)
                f.write("\n\n")
