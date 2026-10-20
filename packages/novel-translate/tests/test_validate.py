import pytest
from novel_translate.chapter import Para, Translated
from novel_translate.glossary import Category, Status, Term
from novel_translate.matching import Matcher
from novel_translate.validate import Norms, check

SOURCE = [
    "韩立走进七玄门的山门，抬头看见一座高大的石牌坊，上面刻着几个苍劲有力的大字。",
    "他深吸了一口气，跟着前面的人一步一步走了进去，心中既紧张又期待。",
    "墨大夫坐在堂上，神情淡然，似乎对眼前的一切都不太在意。",
]
CLEAN = [
    "Han Li walked through the mountain gate of the Seven Mysteries Sect and looked up at a tall stone archway "
    "carved with a few bold characters.",
    "He took a deep breath and followed the people ahead of him step by step, nervous and expectant at once.",
    "Doctor Mo sat in the hall, his expression calm, as if nothing before him mattered much.",
]
TERMS = [
    Term(1, "韩立", "Han Li", Category.PERSON, Status.LOCKED),
    Term(2, "七玄门", "Seven Mysteries Sect", Category.SECT, Status.ACCEPTED),
    Term(3, "墨大夫", "Doctor Mo", Category.TITLE, Status.ACCEPTED),
]
MATCH = Matcher(TERMS).match("".join(SOURCE))


def out(paragraphs=None, ids=None, title="Entering the Sect") -> Translated:
    texts = CLEAN if paragraphs is None else paragraphs
    return Translated(title=title, paragraphs=[Para(id=i, text=t) for i, t in zip(ids or range(1, len(texts) + 1), texts)])


def with_para(i: int, text: str) -> list[str]:
    texts = list(CLEAN)
    texts[i] = text
    return texts


LONG_SOURCE = SOURCE * 20


@pytest.mark.parametrize(("source", "translated", "hard", "soft"), [
    pytest.param(SOURCE, out(), (), (), id="V1-clean"),
    pytest.param(SOURCE, out(with_para(1, CLEAN[1] + " 他")), ("cjk",), (), id="V2-one-cjk-char"),
    pytest.param(SOURCE, out(CLEAN[:2]), ("ids",), ("term:墨大夫",), id="V3-id-missing"),
    pytest.param(SOURCE, out([CLEAN[0] + " " + CLEAN[1], CLEAN[2]], ids=[1, 3]), ("ids",), (), id="V4-ids-merged"),
    pytest.param(SOURCE, out(with_para(1, "   ")), ("empty",), (), id="V5-empty-paragraph"),
    pytest.param(SOURCE * 2, out(CLEAN * 2), (), (), id="V6-paragraph-twice-is-fine"),
    pytest.param(SOURCE * 3 + SOURCE[:1], out(CLEAN * 3 + CLEAN[:1]), ("loop",), (), id="V6-paragraph-x3"),
    pytest.param(LONG_SOURCE, out([CLEAN[1] + " " + "and again" * 94] + [f"Line {i} of the story goes on." for i in range(2, 61)]),
                 ("loop", "length"), ("term:韩立", "term:七玄门", "term:墨大夫"), id="V7-94x-loop"),
    pytest.param(SOURCE, out(["Han Li went in.", "He breathed.", "Doctor Mo sat. Seven Mysteries Sect."]), ("length",), (), id="V8-ratio-low"),
    pytest.param(SOURCE, out([t + " " + t + " " + t for t in CLEAN]), ("length",), (), id="V9-ratio-high"),
    pytest.param(SOURCE, out(with_para(0, "Chapter 12: " + CLEAN[0])), ("heading",), (), id="V10-chapter-heading-in-body"),
    pytest.param(SOURCE, out(with_para(2, "Physician Mo sat in the hall, his expression calm, as if nothing before him mattered much.")),
                 (), ("term:墨大夫",), id="V11-term-missing"),
    pytest.param(SOURCE, out(with_para(0, CLEAN[0].replace("Han Li", "Hanli")), title="Chapter 3"),
                 (), ("term:韩立", "title"), id="V12-generic-title"),
])  # fmt: skip
def test_checks(source, translated, hard, soft):
    findings = check(source, translated, Matcher(TERMS).match("".join(source)))
    assert (findings.hard, findings.soft) == (hard, soft)


def test_a_heading_the_source_also_has_is_not_a_merged_chapter():
    source = ["第十二章 入门", *SOURCE[1:]]
    findings = check(source, out(with_para(0, "Chapter 12: Entering the Sect")), MATCH)
    assert "heading" not in findings.hard


def test_bare_pinyin_for_a_person_with_another_rendering_is_flagged():
    terms = [Term(1, "韩立", "Hann Lee", Category.PERSON, Status.LOCKED)]
    texts = with_para(0, CLEAN[0].replace("Han Li", "Hann Lee"))
    texts[1] = "Han Li took a deep breath and followed the people ahead of him step by step, nervous at once."
    findings = check(SOURCE, out(texts), Matcher(terms).match("".join(SOURCE)))
    assert findings.soft == ("pinyin:韩立",)
    assert check(SOURCE, out(), MATCH).soft == ()  # "Han Li" is the rendering, so its pinyin is expected


def test_norms_are_per_novel():
    assert "length" in check(SOURCE, out(), MATCH, Norms(length_range=(1.5, 3.0))).hard
