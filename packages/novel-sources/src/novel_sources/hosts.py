"""Cleanup rules per host, keyed by site name so novelbin.me and novelbin.com share one entry.

Aggregators copy each other's text, watermarks included, so the watermark rules
apply to every host. Watermarks disguise the site name: look-alike letters
("freeweɓnovel.cѳm"), symbols between letters ("novel※fire.net", "novel{f}ire"),
a dropped letter ("reewebnovel.com"), or no domain at all ("free(w)ebnovel").
A short line naming a site is dropped whole. In a longer paragraph only the
watermark sentence is cut, back to where the previous sentence ended.
"""

import re
from urllib.parse import urlsplit

from novel_sources.clean import CleanError, CleanRules

_SHORT = 160  # a watermark, credit or navigation line is never longer than this

# Long names are matched within a few edits; a look-alike letter costs nothing.
_FUZZY_SITES = ("freewebnovel", "freenovelkiss", "lightnovelpub")
_FUZZY_EDITS = 2
# Names close to ordinary words ("a novel fire") only count when followed by a domain.
_DOMAIN_SITES = re.compile(
    "(?:{})".format("|".join("".join(f"[{c}?]" for c in name) for name in ("novelfire", "novelbin", "novelbuddy", "novelhi")))
    + r"(?:\.?(?:net|com)|\.[a-z?]{2,3})"
)
_HINT = re.compile(r"nov|ovel|web|kiss|pub|\?")


def is_watermark(text: str) -> bool:
    """A short line naming an aggregator site, however disguised."""
    if len(text) > _SHORT:
        return False
    s = _skeleton(text)
    if not _HINT.search(s):
        return False
    return bool(_DOMAIN_SITES.search(s)) or any(_within(s, site, _FUZZY_EDITS) for site in _FUZZY_SITES)


def _skeleton(text: str) -> str:
    """Lowercase ASCII letters, digits and dots only; every non-ASCII letter becomes '?'."""
    out = []
    for c in text.lower():
        if c.isalpha() and not c.isascii():
            out.append("?")
        elif c.isascii() and (c.isalnum() or c == "."):
            out.append(c)
    return "".join(out)


def _within(text: str, word: str, edits: int) -> bool:
    """Whether some substring of text is within `edits` edits of word ('?' in text matches any letter)."""
    # Sellers' approximate substring match: cur[j] = cheapest match of word[:j] ending at this char.
    prev = list(range(len(word) + 1))
    for c in text:
        cur = [0]
        for j, w in enumerate(word, start=1):
            same = c == w or c == "?"
            cur.append(min(prev[j - 1] + (not same), prev[j] + 1, cur[j - 1] + 1))
        if cur[-1] <= edits:
            return True
        prev = cur
    return False


_JUNK = r"(?:[^\w\s]|_){0,3}"  # symbols a watermark puts between letters


def _disguised(word: str) -> str:
    return _JUNK.join(rf"(?:{re.escape(c)}|[^\x00-\x7f])" for c in word)


# A site name in running text, with its domain when it has one.
_SITE_IN_TEXT = re.compile(
    rf"(?:(?:{_disguised('f')})?{_disguised('reewebnovel')}|{_disguised('novelfire')}|{_disguised('freenovelkiss')})"
    rf"(?:(?:[^\w\s]|_){{1,3}}\s?[^\s.,!?;:\"'“”]{{2,3}}(?!\w))?",
    re.IGNORECASE,
)
_SENTENCE_END = '.!?…"”'
_WATERMARK_SENTENCE = 80  # how far back a watermark sentence starts from the site name


def cut_glued_watermarks(text: str) -> str:
    """'...retreated. Thɪs chapter is updatᴇd by novel(ꜰ)ire.net' -> '...retreated.'"""
    for m in reversed(list(_SITE_IN_TEXT.finditer(text))):
        start = m.start()
        end_of_sentence = max(text.rfind(c, 0, start) for c in _SENTENCE_END)
        if end_of_sentence >= 0 and start - end_of_sentence <= _WATERMARK_SENTENCE:
            start = end_of_sentence + 1
        text = text[:start] + text[m.end() :]
    return text


_CREDIT = re.compile(rf"^(?=.{{0,{_SHORT}}}$)\s*(?:translator|editor|proofreader|tl|ed)\s*:", re.IGNORECASE)
_NAVIGATION = re.compile(
    rf"^(?=.{{0,{_SHORT}}}$).*(?:\bprevious chapter\b|\bnext chapter\b|\bko-fi\b|\bproject page\b|discord\.gg/)",
    re.IGNORECASE,
)
_STRAY_MARKUP = re.compile(r"^[^\w]*`[^\w]*$")  # '“`': a markdown fence left in the text

COMMON = CleanRules(
    content=(),
    drop=(is_watermark, _CREDIT.search, _NAVIGATION.search, _STRAY_MARKUP.search),
    strip=(cut_glued_watermarks,),
)

HOSTS: dict[str, CleanRules] = {
    "freewebnovel": CleanRules(content=("div#article",)),
    "novelbin": CleanRules(content=("div#chr-content", "div#chapter-content"), remove=("div.PUBFUTURE",)),
    # novelbuddy.me (current layout) and novelbuddy.com (older layout).
    "novelbuddy": CleanRules(content=("div.novel-tts-content", "div.content-inner")),
    "skydemonorder": CleanRules(content=("div#chapter-body",)),
}


def site_name(url: str) -> str:
    """'novelbin' for https://www.novelbin.me/... ."""
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else host


def rules_for(url: str) -> CleanRules:
    try:
        return COMMON | HOSTS[site_name(url)]
    except KeyError:
        raise CleanError(f"no cleanup rules for host of {url!r}") from None
