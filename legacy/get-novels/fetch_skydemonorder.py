"""Import every free Sky Demon Order chapter into web-novel-scraper."""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_URL = (
    "https://skydemonorder.com/projects/"
    "3801994495-return-of-the-mount-hua-sect"
)
DEFAULT_TITLE = "Return of the Mount Hua Sect"
FLARESOLVERR_URL = os.getenv(
    "SCRAPER_FLARESOLVER_URL", "http://localhost:8191/v1"
)


def fetch_project_html(project_url: str) -> str:
    payload = json.dumps(
        {
            "cmd": "request.get",
            "url": project_url,
            "maxTimeout": 60_000,
        }
    ).encode()
    request = Request(
        FLARESOLVERR_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=70) as response:
            result = json.load(response)
    except OSError as error:
        raise SystemExit(
            f"Could not reach FlareSolverr at {FLARESOLVERR_URL}. "
            "Start flaresolverr.exe first."
        ) from error

    html = result.get("solution", {}).get("response")
    if not html:
        raise SystemExit("FlareSolverr did not return the project page.")
    return html


def extract_free_chapters(html: str) -> list[dict]:
    match = re.search(r"freeChapters:\s*JSON\.parse\('(.+?)'\)", html)
    if not match:
        raise SystemExit("Could not find the embedded free chapter list.")

    # Decode the JavaScript string escapes, then parse the resulting JSON.
    encoded_json = match.group(1).replace('"', '\\"')
    chapters = json.loads(json.loads(f'"{encoded_json}"'))
    return sorted(chapters, key=lambda chapter: chapter["episode"])


def novel_data_path(title: str, base_dir: Path | None) -> Path:
    if base_dir is None:
        base_dir = (
            Path(os.environ["LOCALAPPDATA"])
            / "web-novel-scraper"
            / "web-novel-scraper"
        )
    return base_dir / title / "data" / "main.json"


def import_chapters(
    project_url: str,
    title: str,
    base_dir: Path | None = None,
    from_chapter: int | None = None,
    max_chapters: int | None = None,
) -> None:
    data_path = novel_data_path(title, base_dir)
    if not data_path.exists():
        raise SystemExit(
            f'Novel data not found at "{data_path}". Run create-novel first.'
        )

    chapters = extract_free_chapters(fetch_project_html(project_url))
    if from_chapter is not None:
        chapters = [
            chapter
            for chapter in chapters
            if chapter["episode"] >= from_chapter
        ]
    if max_chapters is not None:
        chapters = chapters[:max_chapters]
    with data_path.open(encoding="utf-8") as file:
        data = json.load(file)

    existing = {
        chapter["chapter_url"]: chapter for chapter in data.get("chapters", [])
    }
    project_path = urlsplit(project_url).path.rstrip("/")
    host = f"{urlsplit(project_url).scheme}://{urlsplit(project_url).netloc}"
    ordered = []
    for chapter in chapters:
        chapter_url = f'{host}{project_path}/{chapter["slug"]}'
        ordered.append(
            existing.get(
                chapter_url,
                {
                    "chapter_url": chapter_url,
                    "chapter_html_filename": None,
                    "chapter_title": None,
                },
            )
        )

    data["chapters"] = ordered
    data["chapters_url_list"] = [chapter["chapter_url"] for chapter in ordered]
    with data_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    first_episode = chapters[0]["episode"] if chapters else None
    last_episode = chapters[-1]["episode"] if chapters else None
    print(f'Imported {len(ordered)} free chapters into "{data_path}".')
    if first_episode is not None:
        print(
            f"Source episodes: {first_episode}-{last_episode}. "
            f'Scraper queue item 1 is source episode {first_episode}.'
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import free chapters from a Sky Demon Order project."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Project URL")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Novel title")
    parser.add_argument(
        "--novel-base-dir",
        type=Path,
        help="Base novel directory passed to web-novel-scraper",
    )
    parser.add_argument(
        "--from-chapter",
        type=int,
        help="Start the imported chapter list at episode N",
    )
    parser.add_argument(
        "--max-chapters",
        type=int,
        help="Import only the first N chapters (useful for testing)",
    )
    args = parser.parse_args()
    import_chapters(
        args.url,
        args.title,
        args.novel_base_dir,
        args.from_chapter,
        args.max_chapters,
    )


if __name__ == "__main__":
    main()
