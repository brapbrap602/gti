from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import time
import html5lib
from selenium import webdriver
from selenium.webdriver.firefox.options import Options


def write_to(text):
    with open("reformation_of_the_dead_beat_novel.txt", "a", encoding="utf-8") as f:
        f.write(text)

#
# for x in range(2100, 2421):
#     r = requests.get(
#         rf"https://novelnext.com/novelnext/a-record-of-a-mortals-journey-to-immortality-novel/chapter-{x}"
#     )
#     soup = BeautifulSoup(r.content, features="html5lib")
#     print(f"On Chapter: {x}")
#
#     for stuff in soup.find(id="chr-content"):
#         write_to(stuff.text)


firefox_profile = webdriver.FirefoxProfile()

# Set custom User-Agent
firefox_profile.set_preference("general.useragent.override", "Mozilla/5.0")

# Create Firefox Options object
firefox_options = Options()

# Set the custom Firefox profile
firefox_options.profile = firefox_profile

# Initialize the Firefox driver with the custom profile
driver = webdriver.Firefox(options=firefox_options)

links = reversed(Path("links").read_text(encoding="utf-8").split('\n'))
for link in links:
    print(link)
    driver.get(link)
    soup = BeautifulSoup(driver.page_source, features="html5lib")
    p_elements = soup.find_all('p')
    for p in p_elements:
        write_to(p.text)
        write_to('\n')

    driver.quit()

