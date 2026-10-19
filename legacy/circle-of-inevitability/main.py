from pathlib import Path

import requests
from bs4 import BeautifulSoup
import time
import html5lib


for line in Path("coe.txt").read_text(encoding="utf-8").split():
    r = requests.get(line.strip())
    soup = BeautifulSoup(r.content, features="lxml")
    print("On Chapter: {}".format(r.url))

    for stuff in soup.find(id="chr-content"):
        best_stuff = stuff.text
        with open("Circle of Inevitability.txt", "a", encoding="utf-8") as f:
            f.write(best_stuff.replace("\n", ""))
            f.write("\n")
            if "chapter" in best_stuff.lower():
                f.write("\n\n")
