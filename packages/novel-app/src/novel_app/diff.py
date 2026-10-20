"""Where two texts of a chapter differ: paragraph by paragraph, with the changed words marked.

Pure: it works on blocks and knows nothing of HTML. Blocks are compared by their
whitespace-normalised text, so formatting (italics, bold) and spacing never count as
a difference. Consecutive differing blocks form one numbered group, the unit a reader
jumps between.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from novel_core import Block, Heading, Image, Note, Paragraph, Separator, System

WORD_DIFF_LIMIT = 2_000_000  # len(left) * len(right) above which changed words are not marked
MARKED_SHARE = 0.5  # a paired block with more of its text changed than this is shown without word marks
_TOKENS = re.compile(r"\w+|\W+")


class Mark(StrEnum):
    SAME = "same"
    CHANGED = "changed"  # paired with a differing block on the other side
    ONLY = "only"  # no counterpart on the other side


@dataclass(frozen=True)
class Span:
    """Characters start:end of the block's normalised text."""

    start: int
    end: int


@dataclass(frozen=True)
class BlockMark:
    state: Mark
    spans: tuple[Span, ...] | None = None  # changed words when CHANGED: () for a rewrite, None if not computed
    group: int | None = None  # None for SAME


@dataclass(frozen=True)
class TextDiff:
    left: tuple[BlockMark, ...]  # one per left block
    right: tuple[BlockMark, ...]
    left_gaps: tuple[tuple[int, int], ...]  # (index, group): a group with no left block sits before left[index]
    right_gaps: tuple[tuple[int, int], ...]
    changes: int  # left blocks that differ, plus right-only blocks
    total: int  # left blocks
    groups: int


def block_text(block: Block) -> str:
    match block:
        case Paragraph():
            return block.text
        case Heading(text) | System(text) | Note(text):
            return text
        case Separator():
            return "—"
        case Image(src, alt):
            return alt or src
    raise TypeError(f"unknown block {block!r}")


def normalised(block: Block) -> str:
    """The text compared and shown for a changed block: runs of whitespace (NBSP too) as one space."""
    return " ".join(block_text(block).split())


def diff_blocks(left: Sequence[Block], right: Sequence[Block]) -> TextDiff:
    lt = [normalised(b) for b in left]
    rt = [normalised(b) for b in right]
    words = len(lt) * len(rt) <= WORD_DIFF_LIMIT
    lm = [BlockMark(Mark.SAME)] * len(lt)
    rm = [BlockMark(Mark.SAME)] * len(rt)
    left_gaps, right_gaps = [], []
    group = 0
    # Between two matching runs difflib yields exactly one opcode, so each non-equal one is a group.
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, lt, rt, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        group += 1
        paired = min(i2 - i1, j2 - j1)
        for k in range(paired):
            ls, rs = _changed_words(lt[i1 + k], rt[j1 + k]) if words else (None, None)
            lm[i1 + k] = BlockMark(Mark.CHANGED, ls, group)
            rm[j1 + k] = BlockMark(Mark.CHANGED, rs, group)
        for i in range(i1 + paired, i2):
            lm[i] = BlockMark(Mark.ONLY, None, group)
        for j in range(j1 + paired, j2):
            rm[j] = BlockMark(Mark.ONLY, None, group)
        if i1 == i2:
            left_gaps.append((i1, group))
        if j1 == j2:
            right_gaps.append((j1, group))
    changes = sum(m.state is not Mark.SAME for m in lm) + sum(m.state is Mark.ONLY for m in rm)
    return TextDiff(tuple(lm), tuple(rm), tuple(left_gaps), tuple(right_gaps), changes, len(lt), group)


def _changed_words(a: str, b: str) -> tuple[tuple[Span, ...], tuple[Span, ...]]:
    ta, tb = _TOKENS.findall(a), _TOKENS.findall(b)
    oa, ob = _offsets(ta), _offsets(tb)
    sa, sb = [], []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if i1 < i2:
            sa.append(Span(oa[i1], oa[i2]))
        if j1 < j2:
            sb.append(Span(ob[j1], ob[j2]))
    sa, sb = _joined(a, sa), _joined(b, sb)
    if _share(a, sa) > MARKED_SHARE or _share(b, sb) > MARKED_SHARE:
        return (), ()  # a rewrite, not an edit: marking nearly every word only adds noise
    return sa, sb


def _joined(text: str, spans: list[Span]) -> tuple[Span, ...]:
    """Spans with only whitespace between them become one, so a changed phrase reads as one mark."""
    out: list[Span] = []
    for span in spans:
        if out and not text[out[-1].end:span.start].strip():
            out[-1] = Span(out[-1].start, span.end)
        else:
            out.append(span)
    return tuple(out)


def _share(text: str, spans: tuple[Span, ...]) -> float:
    return sum(s.end - s.start for s in spans) / len(text) if text else 0.0


def _offsets(tokens: Sequence[str]) -> list[int]:
    """Start offset of each token, plus the end of the text."""
    out = [0]
    for t in tokens:
        out.append(out[-1] + len(t))
    return out
