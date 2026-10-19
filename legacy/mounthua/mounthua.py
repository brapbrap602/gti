import requests
from bs4 import BeautifulSoup

with open(r"C:\Users\HT\Documents\code\mounthua\links.txt") as f:
    for link in reversed(f.readlines()):
        link = link.replace("\n", "")
        if link:
            print(f"On Chapter: {link}")
            r = requests.get(link)
            soup = BeautifulSoup(r.content, features="lxml")
            for stuff in soup.find_all("div", {"class": "post-body entry-content"}):
                with open("mounthua_300_after.txt", "a", encoding="utf-8") as f:
                    x = stuff.text.replace(" ", " ")
                    f.write(x)
                    f.write("\n")
