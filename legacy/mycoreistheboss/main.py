import requests
import json
from bs4 import BeautifulSoup
import time
import os

FLARESOLVERR_URL = "http://localhost:8191/v1"
LINKS_FILE = "links.txt"
OUTPUT_FILE = "My Longevity Simulation"


def scrape_chapter(url):
    print(f"Requesting: {url}")
    payload = {'cmd': 'request.get', 'url': url, 'maxTimeout': 60000}

    try:
        response = requests.post(FLARESOLVERR_URL, headers={'Content-Type': 'application/json'},
                                 data=json.dumps(payload))
        response.raise_for_status()

        flaresolverr_data = response.json()
        if flaresolverr_data.get('status') != 'ok':
            print(f"  [!] FlareSolverr error: {flaresolverr_data.get('message')}")
            return None, None

        html_content = flaresolverr_data['solution']['response']
        soup = BeautifulSoup(html_content, 'html.parser')

        chapter_title = soup.find(class_="chapter-title").get_text(strip=True)

        # Extract chapter content
        content_div = soup.find("div", class_="chp_raw")
        if not content_div:
            print("  [!] Could not find chapter content div.")
            return chapter_title, None

        # Gather text content (skipping empty <p> tags)
        paragraphs = [
            p.get_text(strip=True)
            for p in content_div.find_all("p")
            if p.get_text(strip=True)
        ]

        chapter_content = "\n\n".join(paragraphs) if paragraphs else None

        return chapter_title, chapter_content
    except Exception as e:
        print(e)
        raise e

def main():
    if not os.path.exists(LINKS_FILE):
        print(f"Error: '{LINKS_FILE}' not found.")
        return

    with open(LINKS_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    print(f"Found {len(urls)} URLs. Starting scrape...")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for url in reversed(urls):
            title, content = scrape_chapter(url)
            if title and content:
                f.write(f"## {title}\n\n")
                f.write(content)
            else:
                f.write(f"## FAILED TO SCRAPE: {url}\n\n")
            time.sleep(1)

    print(f"\n✅ Done! Saved to '{OUTPUT_FILE}'.")


if __name__ == "__main__":
    main()
