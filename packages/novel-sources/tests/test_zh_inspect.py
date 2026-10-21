import pytest
from novel_sources.zh_inspect import Span, Suspect, diff, suspects

KEEPS = ("……", "“……”", "5555")
NO_CJK = "no CJK"
UNBALANCED = "unbalanced quotes"
LETTERS = "Latin/Cyrillic in a CJK line"


@pytest.mark.parametrize(
    ("paragraph", "labels"),
    [
        (">>", [NO_CJK]),
        ("OK", [NO_CJK]),
        ("……", []),
        ("“……”", []),
        ("5555", []),
        ("「他说", [UNBALANCED]),
        ("他说」", [UNBALANCED]),
        ("“好”他说。「走」", []),
        ("“好", [UNBALANCED]),
        ("wωw▪▪C〇赵二宝闻言大喜", [LETTERS]),
        ("为我做事？”шшш¤¤￠O", [UNBALANCED, LETTERS]),
        ("赵二宝闻言大喜。", []),
    ],
    ids=["symbols", "latin-only", "keep-dots", "keep-quoted-dots", "keep-crying", "open-corner", "close-corner",
         "balanced", "open-curly", "latin-run", "cyrillic-run-and-quote", "clean"],
)  # fmt: skip
def test_suspects_label_each_heuristic_that_fires(paragraph, labels):
    assert suspects([paragraph], KEEPS) == tuple(Suspect(label, paragraph) for label in labels)


def test_diff_pairs_paragraphs_then_characters_and_groups_spans():
    ours = ["他转身走出————山门", "风吹过松林", "远处传来————钟声", "广告", "月光洒在————石板上"]
    theirs = ["他转身走出……山门", "风吹过松林", "远处传来……钟声", "月光洒在……石板上", "辛"]
    assert diff(ours, theirs) == (Span("————", "……", 3), Span("广告", "", 1), Span("", "辛", 1))


def test_diff_of_equal_texts_is_empty():
    assert diff(["甲", "乙"], ["甲", "乙"]) == ()
