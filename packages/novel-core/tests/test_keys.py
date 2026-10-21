import pytest
from novel_core import ChapterKey, KeyRange, chapter_heading, parse_printed, url_ref
from novel_core.keys import title_name


def test_key_order_parts():
    keys = [ChapterKey(525), ChapterKey(524, 2), ChapterKey(524), ChapterKey(524, 1)]
    assert sorted(keys) == [ChapterKey(524), ChapterKey(524, 1), ChapterKey(524, 2), ChapterKey(525)]
    assert [k.label for k in sorted(keys)] == ["524", "524 pt 1", "524 pt 2", "525"]


@pytest.mark.parametrize(
    ("title", "ref", "expected"),
    [
        ("Chapter 12: The Fall", "", (12, 0)),
        ("Chapter 524 (1): Title", "", (524, 1)),
        ("Chapter 524 part 2", "", (524, 2)),
        ("Chapter 88 - The Gate (3)", "", (88, 3)),
        ("Chapter 184: Strange Developments (part 2)", "", (184, 2)),
        ("第一千八百九十七章 天下", "", (1897, 0)),
        ("第12章", "", (12, 0)),
        ("The Fall", "/novel/x/chapter-301", (301, 0)),
        ("Untitled", "/novels/foo/1205-a-new-dawn", (1205, 0)),
        ("Prologue", "/novel/x/prologue", (None, 0)),
        ("Side story: X", "/novel/x/side-story-x", (None, 0)),
        ("Chapters 486: The Finals Begin", "", (486, 0)),
        ("2025.11.18", "/novel/x/2025-11-18", (None, 0)),
    ],
    ids=["title", "paren-part", "part-word", "trailing-part", "paren-part-word", "cn-numerals", "cn-digits", "slug", "skydemon-slug",
         "prologue", "side-story", "plural-typo", "date-post"],
)  # fmt: skip
def test_parse_printed(title, ref, expected):
    assert parse_printed(title, ref) == expected


def test_url_ref_drops_host_query_fragment_and_trailing_slash():
    assert url_ref("https://novelbin.me/b/x/chapter-5/?utm=1#top") == "/b/x/chapter-5"
    assert url_ref("https://novelbin.com/b/x/chapter-5") == "/b/x/chapter-5"


def test_key_range_is_inclusive_and_rejects_empty():
    r = KeyRange(10, 20)
    assert 10 in r and 20 in r and 9 not in r and 21 not in r
    with pytest.raises(ValueError):
        KeyRange(5, 4)


@pytest.mark.parametrize(("number", "start"), [(0, 1), (1, 1), (100, 1), (101, 101), (250, 201)])
def test_range_containing(number, start):
    assert KeyRange.containing(number, 100) == KeyRange(start, start + 99)


@pytest.mark.parametrize(
    ("key", "title", "heading"),
    [
        (ChapterKey(5), "Chapter 5: The Gate", "Chapter 5: The Gate"),
        (ChapterKey(5), "Chapter 5 - The Gate", "Chapter 5: The Gate"),
        (ChapterKey(5), "Chapter 5", "Chapter 5"),
        (ChapterKey(6), "Chapter 5: Drifted", "Chapter 6: Drifted"),
        (ChapterKey(524, 1), "Chapter 524 (1) - Gate", "Chapter 524 pt 1: Gate"),
        (ChapterKey(0), "Prologue", "Chapter 0: Prologue"),
        (ChapterKey(1), "Who Let Him Cultivate?! (WX)-Chapter 1: Today", "Chapter 1: Today"),
        (ChapterKey(9), "The Chapter Nine Riddle", "Chapter 9: The Chapter Nine Riddle"),
    ],
)
def test_chapter_heading(key, title, heading):
    assert chapter_heading(key, title) == heading


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("第12章 名字", "名字"),
        ("第一千零六十章 长生", "长生"),
        ("第12章 名字（九千求月票）", "名字"),
        ("第12章 名字(求订阅)", "名字"),
        ("第12章  名字 （二）", "名字"),
        ("12. 名字", "名字"),
        ("第十二节 山  门", "山 门"),
        ("上架感言", "上架感言"),
        ("第12章", ""),
    ],
    ids=["digits", "cn-numerals", "suffix-ignored", "ascii-suffix", "spaces", "bare-digits", "squashed", "no-number",
         "number-only"],
)  # fmt: skip
def test_title_name(title, name):
    """What two sources' titles of one chapter share: no printed number, no （…） note after it."""
    assert title_name(title) == name
