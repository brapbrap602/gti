"""What gets spoken: a chapter's blocks as a list of sentences, one TTS request each.

Sentences come from pySBD. A sentence over MAX_CHARS is cut at a clause break
(or a space) so no request is huge, and a fragment under MIN_CHARS ("Hm.") is
merged into the next sentence of its paragraph so it doesn't cost a request of
its own. Images and separators are silent. This module's source is part of the
audio fingerprint: changing how text is split re-renders every built chapter.
"""

import re
from collections.abc import Sequence
from functools import cache

import pysbd
from novel_core import Block, ChapterKey, Heading, Note, Paragraph, System, chapter_heading

MAX_CHARS = 500
MIN_CHARS = 15

_SPEAKABLE = re.compile(r"\w")
_CLAUSE_BREAK = re.compile(r"[,;:—–]\s+|\s+[—–]\s*")


def chapter_script(key: ChapterKey, title: str, blocks: Sequence[Block]) -> tuple[str, ...]:
    """The heading, then every spoken block's sentences, in reading order."""
    lines = [chapter_heading(key, title)]
    for text in spoken_texts(blocks):
        lines.extend(_merge_short(_cap(s) for s in split_sentences(text)))
    return tuple(line for line in lines if _SPEAKABLE.search(line))


def spoken_texts(blocks: Sequence[Block]) -> list[str]:
    """The text of each block that is read aloud (paragraphs, headings, system lines, notes)."""
    out = []
    for b in blocks:
        match b:
            case Paragraph():
                out.append(b.text)
            case Heading(text) | System(text) | Note(text):
                out.append(text)
    return [t for t in (t.strip() for t in out) if t]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _segmenter().segment(text) if s.strip()]


def _cap(sentence: str) -> list[str]:
    pieces = []
    while len(sentence) > MAX_CHARS:
        window = sentence[:MAX_CHARS]
        breaks = [m.end() for m in _CLAUSE_BREAK.finditer(window)]
        cut = breaks[-1] if breaks else window.rfind(" ") + 1 or MAX_CHARS
        pieces.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    return [*pieces, sentence]


def _merge_short(groups) -> list[str]:
    sentences = [s for group in groups for s in group if s]
    out: list[str] = []
    pending = ""
    for s in sentences:
        s = f"{pending} {s}" if pending else s
        if len(s) < MIN_CHARS:
            pending = s
        else:
            out.append(s)
            pending = ""
    if pending:
        if out:
            out[-1] = f"{out[-1]} {pending}"
        else:
            out.append(pending)
    return out


@cache
def _segmenter() -> pysbd.Segmenter:
    return pysbd.Segmenter(language="en", clean=False)
