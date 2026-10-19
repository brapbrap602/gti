"""Create EPUBs with unique internal filenames for duplicate chapter titles."""

import argparse
import itertools
import re
from pathlib import Path

from web_novel_scraper import utils
from web_novel_scraper.config_manager import ScraperConfig
from web_novel_scraper.novel_scraper import Novel


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save a novel to EPUB without duplicate manifest entries."
    )
    parser.add_argument("-t", "--title", required=True)
    parser.add_argument("--config-file", type=Path, default=Path("scraper-config.json"))
    parser.add_argument(
        "--start-chapter",
        type=int,
        help="First TOC position (defaults to the first downloaded chapter)",
    )
    parser.add_argument("--end-chapter", type=int)
    parser.add_argument("--chapters-by-book", type=int, default=1000)
    parser.add_argument("--base-novels-dir", type=Path)
    args = parser.parse_args()

    config_parameters = {"config_file": str(args.config_file)}
    if args.base_novels_dir:
        config_parameters["base_novels_dir"] = str(args.base_novels_dir)
    config = ScraperConfig(parameters=config_parameters)
    novel = Novel.load(args.title, config)

    downloaded = []
    for position, chapter in enumerate(novel.chapters, 1):
        filename = chapter.chapter_html_filename
        if filename and novel.file_manager.chapter_file_exists(filename):
            downloaded.append(position)
    if not downloaded:
        raise SystemExit("No downloaded chapters were found.")

    start_chapter = args.start_chapter or downloaded[0]
    end_chapter = args.end_chapter or len(novel.chapters)
    if start_chapter < 1 or end_chapter > len(novel.chapters):
        raise SystemExit(
            f"Requested range must be within 1-{len(novel.chapters)}."
        )
    if end_chapter < start_chapter:
        raise SystemExit("--end-chapter must not be less than --start-chapter.")

    downloaded_set = set(downloaded)
    missing = [
        position
        for position in range(start_chapter, end_chapter + 1)
        if position not in downloaded_set
    ]
    if missing:
        preview = ", ".join(str(position) for position in missing[:10])
        suffix = "..." if len(missing) > 10 else ""
        raise SystemExit(
            f"Cannot build EPUB: {len(missing)} selected chapters are not "
            f"downloaded ({preview}{suffix}). Run request-all-chapters first."
        )

    if args.start_chapter is None:
        print(f"Using first downloaded chapter: {start_chapter}")

    original_filename = utils.generate_epub_file_name_from_title
    original_scrap_chapter = novel.scrap_chapter
    sequence = itertools.count(1)
    decoded_titles = {}

    def unique_filename(title: str) -> str:
        return f"chapter_{next(sequence):06d}_{original_filename(title)}"

    def scrap_numbered_chapter(chapter, *args, **kwargs):
        chapter = original_scrap_chapter(chapter, *args, **kwargs)
        if chapter is None:
            return None
        slug = chapter.chapter_url.rsplit("/", 1)[-1]
        match = re.match(r"(?:chapter-)?(\d+)(?:-|$)", slug)
        if match is None:
            raise SystemExit(
                f"Could not determine source episode from {chapter.chapter_url}"
            )
        source_episode = match.group(1)
        decoded_titles[chapter.chapter_url] = chapter.chapter_title
        if not re.match(
            rf"Chapter\s+{re.escape(source_episode)}(?:\b|:)",
            chapter.chapter_title,
            re.IGNORECASE,
        ):
            chapter.chapter_title = (
                f"Chapter {source_episode}: {chapter.chapter_title}"
            )
        return chapter

    utils.generate_epub_file_name_from_title = unique_filename
    novel.scrap_chapter = scrap_numbered_chapter
    try:
        novel.save_novel_to_epub(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            chapters_by_book=args.chapters_by_book,
        )
    finally:
        for chapter in novel.chapters:
            decoded_title = decoded_titles.get(chapter.chapter_url)
            if decoded_title is not None:
                chapter.chapter_title = decoded_title
        novel.save_novel()
    print("All books saved.")


if __name__ == "__main__":
    main()
