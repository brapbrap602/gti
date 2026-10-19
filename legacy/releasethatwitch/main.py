import requests
from bs4 import BeautifulSoup

for x in range(252, 1499):
    r = requests.get(f"https://boxnovel.com/novel/release-that-witch/chapter-{x}")
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for parag in soup.find_all("div", {"class": "reading-content"}):
        best_stuff = parag.text
        with open("rtw.txt", "a", encoding="utf-8") as f:
            f.write(best_stuff)
