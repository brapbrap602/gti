"""Importer for a MtlTings chapter folder: `data/raw/<novel>/` or `data/translated/<novel>/`.

Raw folders hold Chinese text (raw-zh); translated folders hold MtlTings' own
translations (my-translation). Files are plain text, numbered by file name:

- `chapter_N.txt` / `chapter_N.html` (My Longevity Simulation): the first line is the title.
- `#N_ Title.txt` (CCG, Transcendental Mechanic): the first line is `Chapter: #N: Title`.
  `#N` is the printed chapter number (CCG #2962 is WNS's printed 2962), so no offset
  is needed. `#N Part P_ Title.txt` is part P of N. `#_ Title.txt` files carry no
  number (afterwords, leave notices) and stay unmapped.

Each item's ref is its file name. A chapter downloaded twice, once under a cut-off
title (Transcendental Mechanic), is imported once, from the file with the longer name.
"""

import re
from pathlib import Path

from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec

from novel_sources.clean import CleanRules
from novel_sources.hosts import COMMON
from novel_sources.importing import NovelIndex

BACKEND = "import:mtl"
_KINDS = {"raw": Kind.RAW_ZH, "translated": Kind.MY_TRANSLATION}
_NUMBERED = re.compile(r"^(?:chapter_(\d+)\.(?:txt|html)|#(\d*)(?: Part (\d+))?_ .*\.txt)$")
_HEADER = re.compile(r"^Chapter:\s*#\d*:\s*")  # "Chapter: #1000: Black Iron Divine Armour"
# English junk rules read every CJK letter as a wildcard, so Chinese text gets none of them.
_RAW_RULES = CleanRules(content=())


class MtlImporter:
    def __init__(self, folder: Path):
        """`folder` is `<MtlTings>/data/raw/<novel>` or `<MtlTings>/data/translated/<novel>`."""
        kind = _KINDS.get(folder.parent.name)
        if kind is None:
            raise ValueError(f"{folder}: expected a folder inside MtlTings' data/raw or data/translated")
        self._folder = folder
        self._kind = kind
        self._files: dict[str, tuple[int | None, int, str]] = {}  # file name -> printed number, part, title
        self._unnamed = self._repeats = 0
        seen: set[tuple[int | None, int, str]] = set()  # (number, part, body) of the files kept
        for path in sorted(folder.iterdir(), key=lambda p: (-len(p.name), p.name)):
            m = _NUMBERED.match(path.name)
            if m is None:
                self._unnamed += 1
                continue
            digits = m.group(1) or m.group(2)
            number, part = int(digits) if digits else None, int(m.group(3) or 0)
            title, body = self._split(path.name)
            if (number, part, body) in seen:
                self._repeats += 1
                continue
            seen.add((number, part, body))
            self._files[path.name] = (number, part, title)

    @property
    def spec(self) -> SourceSpec:
        return SourceSpec(BACKEND, self._folder.resolve().as_uri(), self._language, self._kind)

    @property
    def _language(self) -> str:
        return "zh" if self._kind is Kind.RAW_ZH else "en"

    def read_index(self) -> NovelIndex:
        def order(name: str) -> tuple:
            number, part, _ = self._files[name]
            return number is None, number or 0, part, name

        items = []
        for position, name in enumerate(sorted(self._files, key=order), start=1):
            number, part, title = self._files[name]
            # The file name is the number; a title like "... (1) Group" must not make a part.
            items.append(SourceItem(name, position, title, number=number, part=part if number is not None else None,
                                    ref_numbered=False))  # fmt: skip
        notes = []
        if self._unnamed:
            notes.append(f"{self._unnamed} files not named like chapter_N.txt or #N_ Title.txt were not imported")
        if self._repeats:
            notes.append(f"{self._repeats} files repeat another file's chapter text under a cut-off title; imported once")
        provenance = {"model": "unknown (MtlTings)", "glossary": None} if self._kind is Kind.MY_TRANSLATION else {}
        meta = NovelMeta(title=self._folder.name.replace("_", " "), language=self._language)
        return NovelIndex(meta, tuple(items), tuple(notes), provenance=provenance)

    def read_chapter(self, item: SourceItem) -> RawChapter:
        _, body = self._split(item.ref)
        return RawChapter(body, "text")

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return _RAW_RULES if self._kind is Kind.RAW_ZH else COMMON

    def _split(self, name: str) -> tuple[str, str]:
        """(title, body): the first non-blank line is the title."""
        text = (self._folder / name).read_text(encoding="utf-8-sig")
        head, _, body = text.lstrip().partition("\n")
        return _HEADER.sub("", head.strip()), body
