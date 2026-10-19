"""Import all chapter URLs from NovelBuddy into web-novel-scraper."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


DEFAULT_URL = "https://novelbuddy.me/surviving-the-game-as-a-barbarian"
DEFAULT_TITLE = "Surviving the Game as a Barbarian"


def request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_all_chapters(
    novel_url: str, from_chapter: int | None = None
) -> list[dict]:
    """Fetch the complete chapter list from NovelBuddy's current API."""
    print(f"Fetching novel metadata from {novel_url} ...")
    request = Request(novel_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        page_html = response.read().decode("utf-8")

    next_data_match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
        page_html,
        re.DOTALL,
    )
    api_url_match = re.search(r'window\.__API_URL__="([^"]+)"', page_html)
    if not next_data_match or not api_url_match:
        raise SystemExit("Could not find NovelBuddy metadata in the title page.")

    page_data = json.loads(next_data_match.group(1))
    novel = page_data["props"]["pageProps"]["initialManga"]
    api_url = (
        f'{api_url_match.group(1)}/titles/{novel["id"]}/chapters'
        f'?cv={novel["cv"]}'
    )
    print(f"Fetching chapters from {api_url} ...")
    chapters = request_json(api_url)["data"]["chapters"]
    if not chapters:
        raise SystemExit("NovelBuddy returned an empty chapter list; refusing to import it.")
    chapter_urls = [chapter["url"] for chapter in chapters]
    if len(chapter_urls) != len(set(chapter_urls)):
        raise SystemExit("NovelBuddy returned duplicate chapter URLs; refusing to import them.")
    chapters.sort(key=lambda chapter: chapter["number"])

    if from_chapter is not None:
        chapters = [
            chapter
            for chapter in chapters
            if chapter["number"] >= from_chapter
        ]

    base_url = f"{urlsplit(novel_url).scheme}://{urlsplit(novel_url).netloc}/"
    for chapter in chapters:
        chapter["url"] = urljoin(base_url, chapter["url"])
    return chapters


def find_novel_data_path(title: str) -> Path:
    """Find the main.json for the novel."""
    # Default location on Windows
    base = Path.home() / "AppData" / "Local" / "web-novel-scraper" / "web-novel-scraper"
    novel_dir = base / title / "data" / "main.json"
    if novel_dir.exists():
        return novel_dir
    print(f"Could not find novel data at {novel_dir}")
    print(
        f'Make sure you\'ve run: web-novel-scraper create-novel -t "{title}" ...'
    )
    sys.exit(1)


def inject_chapters(
    title: str, chapters: list[dict], allow_removal: bool = False
) -> None:
    """Inject chapter URLs into web-novel-scraper's main.json."""
    data_path = find_novel_data_path(title)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing = {
        chapter["chapter_url"]: chapter for chapter in data.get("chapters", [])
    }
    incoming_urls = {chapter["url"] for chapter in chapters}
    removed_downloads = [
        url
        for url, record in existing.items()
        if url not in incoming_urls and record.get("chapter_html_filename")
    ]
    if removed_downloads and not allow_removal:
        raise SystemExit(
            f"The new list omits {len(removed_downloads)} downloaded chapters; "
            "refusing to replace the existing list."
        )

    ordered = []
    for chapter in chapters:
        chapter_url = chapter["url"]
        record = existing.get(
            chapter_url,
            {
                "chapter_url": chapter_url,
                "chapter_html_filename": None,
                "chapter_title": chapter["name"],
            },
        )
        if not record.get("chapter_title"):
            record["chapter_title"] = chapter["name"]
        ordered.append(record)

    data["chapters"] = ordered
    data["chapters_url_list"] = [chapter["chapter_url"] for chapter in ordered]

    temporary_path = data_path.with_suffix(".json.tmp")
    with open(temporary_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temporary_path, data_path)

    print(f"Imported {len(ordered)} chapters into {data_path}.")


def main():
    parser = argparse.ArgumentParser(description="Import chapters from NovelBuddy.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Novel title-page URL")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Local novel title")
    parser.add_argument(
        "--from-chapter",
        type=int,
        default=None,
        metavar="N",
        help="Only fetch chapters numbered N and above.",
    )
    args = parser.parse_args()

    chapters = fetch_all_chapters(args.url, from_chapter=args.from_chapter)
    if args.from_chapter is not None:
        print(f"Found {len(chapters)} unique chapters (chapter {args.from_chapter}+).")
    else:
        print(f"Found {len(chapters)} unique chapters.")
    inject_chapters(
        args.title,
        chapters,
        allow_removal=args.from_chapter is not None,
    )
    print("\nDone! Now run:")
    print(
        "  uv run web-novel-scraper --decode-guide-file decode_guide.json "
        f'request-all-chapters -t "{args.title}"'
    )


if __name__ == "__main__":
    main()
