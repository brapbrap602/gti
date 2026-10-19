import html5lib
import requests
import time
from bs4 import BeautifulSoup

bestest = ""
start_time = ""
for x in range(305, 967):
    if x % 5 == 0:
        try:
            print(f"time since last written={time.time() - start_time}")
        except:
            print("some error")
        start_time = ""
        print(f"writing on chapter {x}")
        with open("lordofthemysteries.txt", "a", encoding="utf-8") as writer:
            writer.write(bestest)
            bestest = ""
            print(f"bestest emptied: \n-{bestest}")
            start_time = time.time()

    r = requests.get(f"https://boxnovel.com/novel/lord-of-the-mysteries/chapter-{x}")
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for stuff in soup.find_all("div", {"class": "reading-content"}):
        best_stuff = stuff.text
        bestest += best_stuff
        if x == 966:
            print(f"writing on chapter {x}")
            with open("lordofthemysteries.txt", "a", encoding="utf-8") as writer:
                writer.write(bestest)
                bestest = ""
                print(f"bestest emptied: \n-{bestest}")
