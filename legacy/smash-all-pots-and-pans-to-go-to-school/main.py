from pathlib import Path

import requests
from bs4 import BeautifulSoup
import time
import html5lib


for line in Path("boba.txt").read_text(encoding="utf-8").split():
    r = requests.get(line.strip())
    chapter = ' '.join(line.strip().split("-")[-2:]).capitalize()
    soup = BeautifulSoup(r.content, features="lxml")
    print("On Chapter: {}".format(r.url))
    with open("Smash All Pots and Pans To Go to School.txt", "a", encoding="utf-8") as f:
        f.write(f"{chapter}\n")

    for stuff in soup.find(class_="content-holder"):
        best_stuff = stuff.text
        with open("Smash All Pots and Pans To Go to School.txt", "a", encoding="utf-8") as f:
            f.write(best_stuff.replace("\n", ""))
            f.write("\n")
            if "chapter" in best_stuff.lower():
                f.write("\n\n")
