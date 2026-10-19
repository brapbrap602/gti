"""Turn a real chapter page into a test fixture with no novel prose in it.

Tags, attributes, digits, punctuation and whitespace stay as they are. Every
letter run becomes placeholder text of the same length and letter case, drawn
from a fixed filler stream, so the output depends only on word lengths and order
and the original prose cannot be recovered. Kept verbatim:

- chapter-numbering words (Chapter, part, pt, 第…章, Chinese numerals), so key
  derivation still works on fixtures;
- text matching any ``keep`` regex (e.g. a host's ad line that a cleaner rule
  must still match);
- comments, CSS and non-JSON scripts (ads and gtag stay detectable).

Prose-bearing attributes (alt, title, aria-label, meta descriptions/titles) and
string values in JSON scripts are scrubbed too.

    uv run python tools/scrub_fixture.py page.html tests/fixtures/x.html --keep "novelbin\\.me"
"""

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Declaration, Doctype
from bs4.element import Script, Stylesheet

KEEP_WORDS = frozenset(
    {"chapter", "chap", "ch", "part", "pt", "vol", "volume", "book", "prologue", "epilogue", "side",
     "story", "extra", "interlude", "afterword"}
)
KEEP_CJK = frozenset("第章节回卷零〇一二三四五六七八九十百千万两")
LATIN_FILLER = "loremipsumdolorsitametconsecteturadipiscingelitseddoeiusmodtemporincididuntutlaboreetdoloremagnaaliqua"
CJK_FILLER = "甲乙丙丁戊己庚辛壬癸"
PROSE_ATTRS = ("alt", "title", "aria-label")
PROSE_META = re.compile(r"description|title", re.I)
JSON_SCRIPT_TYPES = {"application/json", "application/ld+json"}
WORD = re.compile(r"[^\W\d_]+")


class _Scrubber:
    """Holds the filler positions, so one document always scrubs the same way."""

    def __init__(self, keep: Sequence[str]):
        self.keep = re.compile("|".join(f"(?:{k})" for k in keep)) if keep else None
        self.latin = 0
        self.cjk = 0

    def text(self, text: str) -> str:
        if self.keep is None:
            return self._words(text)
        out, pos = [], 0
        for m in self.keep.finditer(text):
            out += [self._words(text[pos:m.start()]), m.group()]
            pos = m.end()
        out.append(self._words(text[pos:]))
        return "".join(out)

    def _words(self, text: str) -> str:
        return WORD.sub(lambda m: m.group() if m.group().lower() in KEEP_WORDS else self._word(m.group()), text)

    def _word(self, word: str) -> str:
        out = []
        for ch in word:
            if ch.lower() != ch.upper():  # cased letter
                filler = LATIN_FILLER[self.latin % len(LATIN_FILLER)]
                self.latin += 1
                out.append(filler.upper() if ch.isupper() else filler)
            elif ch in KEEP_CJK:
                out.append(ch)
            else:
                out.append(CJK_FILLER[self.cjk % len(CJK_FILLER)])
                self.cjk += 1
        return "".join(out)

    def json(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json(v) for v in value]
        if isinstance(value, dict):
            # JSON-LD "@type"/"@context" values are schema markers, not prose.
            return {k: v if k.startswith("@") else self.json(v) for k, v in value.items()}
        return value


def scrub_html(html: str | bytes, keep: Sequence[str] = ()) -> str:
    soup = BeautifulSoup(html, "html.parser")
    scrub = _Scrubber(keep)

    for tag in soup.find_all(True):
        for attr in PROSE_ATTRS:
            if isinstance(tag.get(attr), str):
                tag[attr] = scrub.text(tag[attr])
        if tag.name == "meta" and PROSE_META.search(tag.get("name", "") + tag.get("property", "")):
            if isinstance(tag.get("content"), str):
                tag["content"] = scrub.text(tag["content"])

    for node in soup.find_all(string=True):
        if isinstance(node, (Comment, Declaration, Doctype, Stylesheet)):
            continue
        if isinstance(node, Script):
            if node.parent.get("type", "").lower() not in JSON_SCRIPT_TYPES:
                continue
            try:
                new = json.dumps(scrub.json(json.loads(node)), ensure_ascii=False)
            except json.JSONDecodeError:
                new = scrub.text(node)
        else:
            new = scrub.text(node)
        node.replace_with(type(node)(new))

    return str(soup)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--keep", action="append", default=[], help="regex for text to keep verbatim (repeatable)")
    args = parser.parse_args()
    args.dest.write_text(scrub_html(args.source.read_bytes(), args.keep), encoding="utf-8")


if __name__ == "__main__":
    main()
