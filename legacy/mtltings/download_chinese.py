import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = r"https://www.biquges123.com/50537"
NOVEL_NAME = "my_longevity_simulation"
BASE_STORE = Path("data") / "raw" / NOVEL_NAME
BASE_STORE.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    for ch_num in range(1060, 1826):
        url = f"{BASE_URL}/{ch_num}"
        print(f"getting {url}")
        r = requests.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, features="html.parser")
        content = soup.find("article")
        title_el = soup.select_one("div.text > h1")
        title = title_el.text.strip()
        actual_ch_num = re.search(r"\d+", title)
        if not actual_ch_num:
            print(f"Skipping {url} - chapter number not found in title '{title}'")
            continue

        try:
            f_name = BASE_STORE / f"chapter_{actual_ch_num.group()}.txt"
        except Exception as e:
            print(e)
            continue

        with f_name.open("w", encoding="utf-8") as f:
            f.write(title + "\n\n")
            for c in content:
                f.write(c.text)
                f.write("\n")
