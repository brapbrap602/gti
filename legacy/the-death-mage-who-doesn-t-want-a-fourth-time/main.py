import requests
from bs4 import BeautifulSoup
import time
import html5lib


for x in range(1, 198):
    r = requests.get(
        "https://novelonlinefull.com/chapter/the_death_mage_who_doesnt_want_a_fourth_time/chapter_{}".format(
            x
        )
    )
    soup = BeautifulSoup(r.content, features="lxml")
    # time.sleep(0.5)
    print("On Chapter: {}".format(x))
    for stuff in soup.find_all("div", {"id": "vung_doc"}):
        best_stuff = stuff.text
        with open(
            "The Death Mage Who Doesn't Want A Fourth Time.txt", "a", encoding="utf-8"
        ) as writer:
            writer.write(best_stuff)
