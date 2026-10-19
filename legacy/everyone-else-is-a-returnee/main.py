import requests
from bs4 import BeautifulSoup
import time
import html5lib


for x in range(1, 350):
    r = requests.get(
        f"https://novelonlinefull.com/chapter/everyone_else_is_a_returnee/chapter_{x}"
    )
    soup = BeautifulSoup(r.content, features="lxml")
    # time.sleep(0.5)
    print("On Chapter: {}".format(x))
    for stuff in soup.find_all("div", {"id": "vung_doc"}):
        best_stuff = stuff.text
        with open("Everyone Else is a Returnee.txt", "a", encoding="utf-8") as writer:
            writer.write(best_stuff)
