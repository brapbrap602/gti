"""Fix chapter order in main.json by sorting by chapter number."""

import json
import re
from pathlib import Path

NOVEL_TITLE = "Who Let Him Cultivate"


def extract_chapter_num(url: str) -> int:
    """Extract chapter number from URL like .../chapter-62-location-of-the-base."""
    match = re.search(r"chapter-(\d+)-", url)
    return int(match.group(1)) if match else 0


def main():
    p = (
        Path.home()
        / "AppData"
        / "Local"
        / "web-novel-scraper"
        / "web-novel-scraper"
        / NOVEL_TITLE
        / "data"
        / "main.json"
    )

    with open(p) as f:
        data = json.load(f)

    chapters = data["chapters"]
    print(f"Total chapters: {len(chapters)}")

    # Sort by chapter number (ascending: 1, 2, 3, ...)
    chapters.sort(key=lambda c: extract_chapter_num(c["chapter_url"]))

    data["chapters"] = chapters

    with open(p, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"First: {chapters[0]['chapter_url'].split('/')[-1]}")
    print(f"Last:  {chapters[-1]['chapter_url'].split('/')[-1]}")
    print("Done!")


if __name__ == "__main__":
    main()
