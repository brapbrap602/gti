import requests
from bs4 import BeautifulSoup

for x in range(599, 1247):
    r = requests.get(f"https://lightnovel.site/novel/overgeared/chapter-{x}/")
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for content in soup.find_all(attrs={"class": "text-left"}):
        for stuff in content.find_all("p"):
            with open("overgeared_2.txt", "a", encoding="utf-8") as f:
                f.write(stuff.text)
                f.write("\n\n")
