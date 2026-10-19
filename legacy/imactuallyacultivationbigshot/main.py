import requests
from bs4 import BeautifulSoup
import re

with open(r"C:\Users\HT\Documents\code\imactuallyacultivationbigshot\links.txt") as f:
    for link in reversed(f.readlines()):
        link = link.replace("\n", "")
        if link:
            print(f"On Chapter: {link}")
            r = requests.get(link)
            soup = BeautifulSoup(r.content, features="lxml")

            for stuff in soup.find_all("div", {"id": "chr-content"}):
                with open("imacultivationbigshot.txt", "a", encoding="utf-8") as f:
                    f.write(stuff.text)
