import html5lib
import requests
import time
from bs4 import BeautifulSoup

for x in range(1, 767):
    url = f"https://novelnb.net/mediterranean-hegemon-of-ancient-greece/chapter-{x}"
    r = requests.get(url)
    soup = BeautifulSoup(r.content, features="lxml")

    title = soup.find(class_="chapter-title")
    print(f"On Chapter: {title.text.strip()}")

    with open("mediterranean-hegemon-of-ancient-greece.txt", "a", encoding="utf-8") as f:
        f.write(f"\n{title.text}\n")

    for stuff in soup.find(class_="chapter-content"):
        with open("mediterranean-hegemon-of-ancient-greece.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{stuff.text}\n")

