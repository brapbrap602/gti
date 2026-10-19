import requests
from bs4 import BeautifulSoup

for x in range(31, 265):
    r = requests.get(
        f"https://webnovelonline.com/chapter/the_beginning_after_the_end/chapter-{x}"
    )
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for stuff in soup.find_all("p"):
        with open("the_beginning_after_the_end.txt", "a", encoding="utf-8") as f:
            f.write(stuff.text)
            f.write("\n")
