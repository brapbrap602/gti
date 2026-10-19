import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


class TickingClock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def clock():
    return TickingClock()


@pytest.fixture
def host_fixtures(request) -> Path:
    return request.config.rootpath / "tests" / "fixtures" / "hosts"


class WnsFolder:
    """A web-novel-scraper novel folder: data/main.json plus saved pages in data/chapters/."""

    def __init__(self, root: Path, title: str, toc_url: str):
        self.root = root
        self.chapters_dir = root / "data" / "chapters"
        self.chapters_dir.mkdir(parents=True)
        self.main = {"title": title, "host": toc_url.split("/")[2], "toc_main_url": toc_url, "chapters": [],
                     "metadata": {"author": None, "language": "en", "tags": []}}  # fmt: skip

    def chapter(self, url: str, title: str | None, filename: str | None, body: str = "") -> "WnsFolder":
        """Add a chapter; a page is saved under filename unless it is None (never downloaded)."""
        self.main["chapters"].append({"chapter_url": url, "chapter_html_filename": filename, "chapter_title": title})
        if filename:
            self.save(filename, body or f'<div id="chr-content"><p>{title}</p><p>Text of {title}.</p></div>')
        return self

    def save(self, filename: str, html: str) -> None:
        (self.chapters_dir / filename).write_text(html, encoding="utf-8")

    def write(self) -> Path:
        (self.root / "data" / "main.json").write_text(json.dumps(self.main), encoding="utf-8")
        return self.root


@pytest.fixture
def wns(tmp_path):
    def make(title: str, toc_url: str) -> WnsFolder:
        return WnsFolder(tmp_path / "wns" / title, title, toc_url)

    return make
