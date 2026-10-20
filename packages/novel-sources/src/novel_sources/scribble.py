"""Importer for a scribblehub text dump: one file holding every chapter (My Longevity Simulation 439-836).

Each chapter starts with a `## Chapter N: Title` marker, glued to the end of the
previous chapter's last line rather than on a line of its own, then repeats the
title on its own line (dropped by normalize). An item's ref is `<file name>#<ordinal>`,
the marker's 1-based position in the file; numbers come from the titles, so the
two halves of the extra "Chapter 809: ... (1)" and "(2)" become parts.
"""

import re
from pathlib import Path

from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec

from novel_sources.clean import CleanRules
from novel_sources.hosts import COMMON
from novel_sources.importing import NovelIndex

BACKEND = "import:scribble"
_MARKER = re.compile(r"## (Chapter \d+[^\r\n]*)")


class ScribbleImporter:
    def __init__(self, path: Path):
        self._path = path
        text = path.read_text(encoding="utf-8-sig")
        marks = list(_MARKER.finditer(text))
        if not marks:
            raise ValueError(f"{path}: no '## Chapter N' markers")
        ends = [m.start() for m in marks[1:]] + [len(text)]
        self._chapters = {
            self._ref(i): (m.group(1).strip(), text[m.end() : end]) for i, (m, end) in enumerate(zip(marks, ends), start=1)
        }

    def _ref(self, ordinal: int) -> str:
        return f"{self._path.name}#{ordinal}"

    @property
    def spec(self) -> SourceSpec:
        return SourceSpec(BACKEND, self._path.resolve().as_uri(), "en", Kind.OFFICIAL_EN)

    def read_index(self) -> NovelIndex:
        items = tuple(
            SourceItem(ref, position, title, ref_numbered=False)
            for position, (ref, (title, _)) in enumerate(self._chapters.items(), start=1)
        )
        return NovelIndex(NovelMeta(title=self._path.name), items)

    def read_chapter(self, item: SourceItem) -> RawChapter:
        return RawChapter(self._chapters[item.ref][1], "text")

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return COMMON
