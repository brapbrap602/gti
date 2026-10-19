import html5lib
import requests
import time
from bs4 import BeautifulSoup

for x in range(1, 435):
    url = f"https://webnovelpub.co/web-novel-pub/im-really-not-the-demon-gods-lackey/chapter-{x}"
    r = requests.get(url)
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for stuff in soup.find(id="content"):
        best_stuff = stuff.text
        with open("imreallynotthedemongodslackey-434.txt", "a", encoding="utf-8") as f:
            f.write(best_stuff)
