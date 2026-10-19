from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Tuple, Union

from flask import Flask, redirect, render_template, url_for
from loguru import logger

app = Flask(__name__)


def extract_chapter_number(chapter_str: Path | str) -> int:
    """Extracts the chapter number from a string."""
    return int(Path(chapter_str).stem.split("-")[1])


@lru_cache
def get_sorted_chapter_titles() -> Tuple[Path]:
    """Returns sorted chapter titles."""
    chapter_folder = Path(app.template_folder)
    all_chapters = chapter_folder.glob("Chapter-*.html")
    return tuple(sorted(all_chapters, key=lambda x: extract_chapter_number(str(x))))


@dataclass
class Context:
    curr_chapter_title: Union[str, Path]
    all_chapters: Tuple[Path] = field(default_factory=tuple)
    curr_chapter_num: int = field(init=False)
    next_chapter: str = field(init=False)
    prev_chapter: str = field(init=False)

    def __post_init__(self):
        self.curr_chapter_num = extract_chapter_number(self.curr_chapter_title)
        all_chapter_nums = [extract_chapter_number(str(x)) for x in self.all_chapters]

        if self.curr_chapter_num + 1 in all_chapter_nums:
            self.next_chapter = url_for(
                "serve_chapter", chapter_number=self.curr_chapter_num + 1
            )
        if self.curr_chapter_num - 1 in all_chapter_nums:
            self.prev_chapter = url_for(
                "serve_chapter", chapter_number=self.curr_chapter_num - 1
            )

        self.curr_chapter_title = Path(self.curr_chapter_title).stem.replace("-", " ")


@app.route("/<int:chapter_number>")
def serve_chapter(chapter_number: int):
    all_chapters = get_sorted_chapter_titles()
    min_chapter, max_chapter = all_chapters[0], all_chapters[-1]

    if chapter_number < extract_chapter_number(min_chapter):
        filename = min_chapter
    elif chapter_number > extract_chapter_number(max_chapter):
        filename = max_chapter
    else:
        filename = Path(f"Chapter-{chapter_number}.html")

    chapter_context = Context(curr_chapter_title=filename, all_chapters=all_chapters)
    logger.info(f"Rendering {filename}")
    return render_template(filename.name, context=chapter_context)


@app.route("/")
def index():
    return redirect(
        url_for(
            "serve_chapter",
            chapter_number=extract_chapter_number(get_sorted_chapter_titles()[0]),
        )
    )


if __name__ == "__main__":
    app.run()
