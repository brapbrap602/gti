import requests
from bs4 import BeautifulSoup

for x in range(1, 405):
    r = requests.get(f"https://novelbookonline.com/94027-bone_painting_coroner/{x}")
    soup = BeautifulSoup(r.content, features="lxml")
    print(f"On Chapter: {x}")
    for stuff in soup.find_all("div", {"class": "d2"}):
        with open("bone_painting_coroner.txt", "a", encoding="utf-8") as f:
            f.write(stuff.text)
            f.write("\n")
