import pytest
from novel_core import ChapterKey, KeyRange, parse_printed, url_ref


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
    ],
    ids=["title", "paren-part", "part-word", "trailing-part", "paren-part-word", "cn-numerals", "cn-digits", "slug", "skydemon-slug",
         "prologue", "side-story"],
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
