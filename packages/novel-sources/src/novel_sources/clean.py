"""normalize: turn a fetched chapter page (or text file) into typed blocks.

Per-host differences are data (`CleanRules`): where the chapter body is, which
elements to delete, and which text is junk. The walk itself is shared: block
elements and <br> end paragraphs, inline <i>/<em> and <b>/<strong> become run
styles, <hr> and symbol-only lines ("***", "❄️❄️❄️") become separators.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from bs4.element import Script, Stylesheet
from novel_core import Block, Heading, Image, Paragraph, RawChapter, Run, Separator


class CleanError(Exception):
    """The page has no chapter body where the rules say it should be."""


@dataclass(frozen=True)
class CleanRules:
    content: Sequence[str]  # CSS selectors tried in order; the first match is the chapter body
    remove: Sequence[str] = ()  # CSS selectors deleted from the body before reading it
    drop: Sequence[Callable[[str], object]] = ()  # a paragraph any of these is truthy for is dropped
    strip: Sequence[Callable[[str], str]] = ()  # each rewrites a paragraph's text (cutting junk out)

    def __or__(self, other: "CleanRules") -> "CleanRules":
        """Combine two rule sets; `other`'s body selectors win."""
        return CleanRules(
            content=tuple(other.content) or tuple(self.content),
            remove=(*self.remove, *other.remove),
            drop=(*self.drop, *other.drop),
            strip=(*self.strip, *other.strip),
        )


_ALWAYS_REMOVE = "script, style, noscript, iframe, ins, button, form, svg, template"
_BLOCK = frozenset(
    ["p", "div", "section", "article", "blockquote", "li", "ul", "ol", "dl", "dd", "dt", "table", "tbody",
     "tr", "td", "th", "center", "figure", "figcaption"]
)
_HEADING = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])
_EM = frozenset(["i", "em", "cite"])
_STRONG = frozenset(["b", "strong"])
_SEPARATOR = re.compile(r"[\s*~_=#\u2022\u00b7\-\u2013\u2014`\u2744\ufe0f\u200b]{3,}")  # *** ~~~ ___ ❄❄❄ and the like
_CHAPTER_ECHO = re.compile(r"^\s*(?:chapter|ch\.?)\s*\d+|^\s*第\s*\S+?\s*[章节回]", re.IGNORECASE)
_CHAPTER_PREFIX = re.compile(r"^\s*(?:(?:chapter|ch\.?)\s*)?\d+\s*[:.\-–—]?\s*", re.IGNORECASE)
_ECHO_WINDOW = 3  # a title echo is only looked for among the first blocks
_SPACE = re.compile(r"\s+")


def normalize(raw: RawChapter, rules: CleanRules, title: str = "") -> tuple[Block, ...]:
    """The chapter's blocks, with junk, ads and the in-body copy of the title removed."""
    if raw.content_type == "text":
        blocks = [_paragraph_or_separator([Run(line)]) for line in raw.content.splitlines()]
    else:
        blocks = list(_html_blocks(raw.content, rules))
    blocks = [b for b in (_clean(b, rules) for b in blocks) if b is not None]
    return tuple(_drop_title_echo(_collapse_separators(blocks), title))


def _html_blocks(html: str, rules: CleanRules) -> Iterator[Block]:
    soup = BeautifulSoup(html, "lxml")
    body = next((found for sel in rules.content if (found := soup.select_one(sel)) is not None), None)
    if body is None:
        raise CleanError(f"no chapter body matches {list(rules.content)}")
    for junk in body.select(", ".join([_ALWAYS_REMOVE, *rules.remove])):
        junk.decompose()
    walker = _Walker()
    walker.walk(body, em=False, strong=False)
    walker.flush()
    return iter(walker.blocks)


class _Walker:
    """Collects inline runs until a block boundary, then emits a paragraph."""

    def __init__(self):
        self.blocks: list[Block] = []
        self.runs: list[Run] = []

    def flush(self) -> None:
        if self.runs:
            self.blocks.append(_paragraph_or_separator(self.runs))
            self.runs = []

    def walk(self, node: Tag, em: bool, strong: bool) -> None:
        for child in node.children:
            if isinstance(child, Comment | Script | Stylesheet):
                continue
            if isinstance(child, NavigableString):
                if text := str(child):
                    self.runs.append(Run(text, em, strong))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            if name == "br":
                self.flush()
            elif name == "hr":
                self.flush()
                self.blocks.append(Separator())
            elif name == "img":
                self.flush()
                if src := child.get("src"):
                    self.blocks.append(Image(str(src), str(child.get("alt", ""))))
            elif name in _HEADING:
                self.flush()
                self.blocks.append(Heading(_squash(child.get_text(" ")), int(name[1])))
            elif name in _BLOCK:
                self.flush()
                self.walk(child, em, strong)
                self.flush()
            else:
                self.walk(child, em or name in _EM, strong or name in _STRONG)


def _paragraph_or_separator(runs: Sequence[Run]) -> Block:
    paragraph = Paragraph(_merge_runs(runs))
    return Separator() if _SEPARATOR.fullmatch(paragraph.text) else paragraph


def _merge_runs(runs: Sequence[Run]) -> tuple[Run, ...]:
    """Collapse whitespace, trim the ends and join neighbouring runs of the same style."""
    merged: list[Run] = []
    for run in runs:
        text = _SPACE.sub(" ", run.text)
        if merged and (merged[-1].em, merged[-1].strong) == (run.em, run.strong):
            merged[-1] = Run(merged[-1].text + text, run.em, run.strong)
        elif text:
            merged.append(Run(text, run.em, run.strong))
    if merged:
        merged[0] = Run(merged[0].text.lstrip(), merged[0].em, merged[0].strong)
        merged[-1] = Run(merged[-1].text.rstrip(), merged[-1].em, merged[-1].strong)
    return tuple(r for r in merged if r.text)


def _clean(block: Block, rules: CleanRules) -> Block | None:
    if isinstance(block, Heading):
        text = _strip(block.text, rules)
        return Heading(text, block.level) if text and not _dropped(text, rules) else None
    if not isinstance(block, Paragraph):
        return block
    if _dropped(block.text, rules):
        return None
    runs = tuple(Run(_strip(r.text, rules), r.em, r.strong) for r in block.runs)
    paragraph = Paragraph(_merge_runs(runs))
    return paragraph if paragraph.runs else None


def _strip(text: str, rules: CleanRules) -> str:
    for cut in rules.strip:
        text = cut(text)
    return text


def _dropped(text: str, rules: CleanRules) -> bool:
    return any(junk(text) for junk in rules.drop)


def _collapse_separators(blocks: Sequence[Block]) -> list[Block]:
    """No separator at either end, and never two in a row."""
    out: list[Block] = []
    for b in blocks:
        if isinstance(b, Separator) and (not out or isinstance(out[-1], Separator)):
            continue
        out.append(b)
    while out and isinstance(out[-1], Separator):
        out.pop()
    return out


def _drop_title_echo(blocks: list[Block], title: str) -> list[Block]:
    """Remove the copies of the chapter title most pages print at the top of the body."""
    # Bodies vary the number part: "Chapter 55 The Forest (2)" may appear as "The Forest (2)"
    # or "55 The Forest (2)", so names are compared without it.
    wanted = _name(title)

    def is_echo(b: Block) -> bool:
        text = b.text if isinstance(b, Paragraph | Heading) else ""
        if not text:
            return False
        return bool(wanted and _name(text) == wanted) or bool(_CHAPTER_ECHO.match(text) and len(text) <= 200)

    head = [b for b in blocks[:_ECHO_WINDOW] if not is_echo(b)]
    return head + blocks[_ECHO_WINDOW:]


def _name(title: str) -> str:
    """A chapter title without its number prefix, for comparing ('Chapter 5: Fall' -> 'fall')."""
    return _squash(_CHAPTER_PREFIX.sub("", title)).casefold()


def _squash(text: str) -> str:
    return _SPACE.sub(" ", text).strip()
