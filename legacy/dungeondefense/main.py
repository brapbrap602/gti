import html5lib
import requests
import time
from bs4 import BeautifulSoup

bestest = ""
start_time = ""
for x in range(1, 43):
    if x % 5 == 0:
        try:
            print(f"time since last written={time.time() - start_time}")
        except:
            print("some error")
        start_time = ""
        print(f"writing on chapter {x}")
        with open("dungeondefense.txt", "a", encoding="utf-8") as writer:
            writer.write(bestest)
            bestest = ""
            print(f"bestest emptied: \n-{bestest}")
            start_time = time.time()

    r = requests.get(
        f"https://kisslightnovels.info/novel/dungeon-defense/dungeon-defense-chapter-{x}"
    )
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for stuff in soup.find_all("div", {"class": "reading-content"}):
        best_stuff = stuff.text
        bestest += best_stuff
        if x == 42:
            print(f"writing on chapter {x}")
            with open("dungeondefense.txt", "a", encoding="utf-8") as writer:
                writer.write(bestest)
                bestest = ""
                print(f"bestest emptied: \n-{bestest}")
