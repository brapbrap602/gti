import requests
from bs4 import BeautifulSoup
import time
import html5lib


for x in range(1, 10):
    r = requests.get(
        "https://novelonlinefull.com/chapter/everyone_else_is_a_returnee/chapter_{}".format(
            x
        )
    )
    soup = BeautifulSoup(r.content, features="html5lib")
    # time.sleep(0.5)
    print("On Chapter: {}".format(x))
    # for stuff in soup.find_all('p', limit=100):
    for stuff in soup.find_all("div", {"id": "vung_doc"}):
        best_stuff = stuff.text
        print(best_stuff)
