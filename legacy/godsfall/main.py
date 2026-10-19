import requests
from bs4 import BeautifulSoup

for x in range(462, 902):
    r = requests.get(
        f"https://noveltrench.com/manga/the-godsfall-chronicles/chapter-{x}"
    )
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    try:
        for stuff in soup.find(id="chapter-heading"):
            with open("godsfall.txt", "a", encoding="utf-8") as f:
                f.write(stuff)
    except Exception as e:
        print(e)
    for stuff in soup.find_all("div", {"class": "reading-content"}):
        with open("godsfall.txt", "a", encoding="utf-8") as f:
            f.write(stuff.text)
