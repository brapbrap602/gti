"""How people write chapter numbers, in the CLI and in web forms. Each parser raises ValueError."""

import re
from collections.abc import Iterable

from novel_audio.legacy import Shift
from novel_core import ChapterKey, KeyRange


def parse_range(text: str) -> KeyRange:
    """'1-100' or '7'."""
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", text)
    if m is None:
        raise ValueError(f"{text!r} is not a range of chapter numbers like 1-100 or 7")
    start = int(m.group(1))
    return KeyRange(start, int(m.group(2) or start))


def parse_key(text: str) -> ChapterKey:
    """'1277', or '524pt1' for a part."""
    m = re.fullmatch(r"\s*(\d+)\s*(?:pt\s*(\d+))?\s*", text, re.IGNORECASE)
    if m is None:
        raise ValueError(f"{text!r} is not a chapter key like 1277 or 524pt1")
    return ChapterKey(int(m.group(1)), int(m.group(2) or 0))


def parse_shift(text: str) -> Shift:
    """'736-1442:+4' maps legacy folder 736 to chapter 740."""
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*:\s*([+-]?\d+)\s*", text)
    if m is None:
        raise ValueError(f"{text!r} is not a shift like 736-1442:+4")
    return Shift(KeyRange(int(m.group(1)), int(m.group(2))), int(m.group(3)))


def ranges(numbers: Iterable[int]) -> str:
    """[1, 2, 3, 7, 9, 10] -> '1-3, 7, 9-10'."""
    spans: list[list[int]] = []
    for n in sorted(numbers):
        if spans and n == spans[-1][1] + 1:
            spans[-1][1] = n
        else:
            spans.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)
