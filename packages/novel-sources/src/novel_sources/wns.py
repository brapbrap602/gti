"""Importer for a web-novel-scraper novel folder (`<Title>/data/{main.json, chapters/}`).

`main.json.chapters` gives the order, URL, saved page and title of each chapter.
Each item's ref is the canonical path of its URL. The chapter number is read
from the title, else from the URL slug, by the core's one key-derivation rule;
freewebnovel slugs count pages by position, so there only the title counts.
A chapter with no saved page was never downloaded (locked or skipped) and
becomes unavailable. Saved pages that main.json does not list (CCG's NovelHi
pages) are not imported; the report lists how many there are.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import ftfy
from novel_core import ItemRef, Kind, NovelMeta, RawChapter, SourceItem, SourceSpec, url_ref

from novel_sources.clean import CleanRules
from novel_sources.hosts import numbered_urls, rules_for
from novel_sources.importing import NovelIndex

BACKEND = "import:wns"
SNAPSHOT_NAME = "wns-main.json"


@dataclass(frozen=True)
class _Entry:
    url: str
    filename: str | None


class WnsImporter:
    def __init__(self, folder: Path):
        """`folder` is the novel's folder or its `data` subfolder."""
        data = folder / "data" if (folder / "data" / "main.json").exists() else folder
        self._data = data
        self._main_bytes = (data / "main.json").read_bytes()
        self._main = json.loads(self._main_bytes)
        self._entries = {
            url_ref(ch["chapter_url"]): _Entry(ch["chapter_url"], ch.get("chapter_html_filename"))
            for ch in self._main["chapters"]
        }

    @property
    def spec(self) -> SourceSpec:
        language = (self._main.get("metadata") or {}).get("language") or "en"
        return SourceSpec(BACKEND, self._main["toc_main_url"], language, Kind.OFFICIAL_EN)

    def read_index(self) -> NovelIndex:
        chapters = self._main["chapters"]
        items: list[SourceItem] = []
        replacement_titles = 0
        for position, ch in enumerate(chapters, start=1):
            ref = url_ref(ch["chapter_url"])
            title = ftfy.fix_text(ch.get("chapter_title") or "", uncurl_quotes=False).strip()
            replacement_titles += "\ufffd" in title
            items.append(SourceItem(ref, position, title, ref_numbered=numbered_urls(ch["chapter_url"])))

        notes = []
        listed = {e.filename for e in self._entries.values() if e.filename}
        chapters_dir = self._data / "chapters"
        saved = {p.name for p in chapters_dir.iterdir()} if chapters_dir.exists() else set()
        if unlisted := sorted(saved - listed):
            notes.append(f"{len(unlisted)} saved pages not listed in main.json were not imported (e.g. {unlisted[0]})")
        if replacement_titles:
            notes.append(f"{replacement_titles} titles contain U+FFFD (a character lost before download)")

        meta = self._main.get("metadata") or {}
        return NovelIndex(
            meta=NovelMeta(
                title=self._main["title"],
                author=meta.get("author"),
                language=meta.get("language") or "en",
                tags=tuple(meta.get("tags") or ()),
            ),
            items=tuple(items),
            notes=tuple(notes),
            snapshot={SNAPSHOT_NAME: self._main_bytes},
        )

    def read_chapter(self, item: SourceItem) -> RawChapter | None:
        entry = self._entries[item.ref]
        if not entry.filename:
            return None
        html = (self._data / "chapters" / entry.filename).read_bytes().decode("utf-8", errors="replace")
        return RawChapter(html, "html", final_url=entry.url)

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return rules_for(raw.final_url or self.spec.url)


def snapshot_refs(novel_dir: Path, source_id: int) -> list[ItemRef]:
    """Item refs in the order of the first main.json imported for this source (position 1 first).

    Legacy audio folders are numbered by position in that frozen list, never in a live index.
    """
    path = novel_dir / "imports" / str(source_id) / SNAPSHOT_NAME
    if not path.exists():
        raise FileNotFoundError(f"{path}: source {source_id} was not imported from web-novel-scraper")
    return [url_ref(ch["chapter_url"]) for ch in json.loads(path.read_bytes())["chapters"]]
