import time

from novel_app.diff import Mark, block_text, diff_blocks
from novel_core import Image, Paragraph, Run, Separator, System


def paras(*texts: str) -> tuple[Paragraph, ...]:
    return tuple(Paragraph.of(t) for t in texts)


def marked(text: str, spans) -> list[str]:
    return [text[s.start:s.end] for s in spans]


def test_identical_texts_have_no_changes():
    d = diff_blocks(paras("One.", "Two."), paras("One.", "Two."))

    assert (d.changes, d.total, d.groups) == (0, 2, 0)
    assert {m.state for m in d.left + d.right} == {Mark.SAME}


def test_one_changed_word_is_marked_on_both_sides():
    d = diff_blocks(paras("Start.", "He ran fast.", "End."), paras("Start.", "He ran quickly.", "End."))

    assert (d.changes, d.groups) == (1, 1)
    assert [m.state for m in d.left] == [Mark.SAME, Mark.CHANGED, Mark.SAME]
    assert d.left[1].group == d.right[1].group == 1
    assert marked("He ran fast.", d.left[1].spans) == ["fast"]
    assert marked("He ran quickly.", d.right[1].spans) == ["quickly"]


def test_an_inserted_paragraph_is_only_on_its_side():
    d = diff_blocks(paras("A.", "B.", "C."), paras("A.", "B.", "New.", "C."))

    assert [m.state for m in d.right] == [Mark.SAME, Mark.SAME, Mark.ONLY, Mark.SAME]
    assert d.right[2].group == 1 and d.right[2].spans is None
    assert [m.state for m in d.left] == [Mark.SAME] * 3
    assert d.left_gaps == ((2, 1),) and d.right_gaps == ()
    assert d.changes == 1


def test_uneven_replacements_pair_in_order_and_leave_the_rest_alone():
    d = diff_blocks(paras("x", "a1", "a2", "y"), paras("x", "b1", "b2", "b3", "y"))

    assert [m.state for m in d.left] == [Mark.SAME, Mark.CHANGED, Mark.CHANGED, Mark.SAME]
    assert [m.state for m in d.right] == [Mark.SAME, Mark.CHANGED, Mark.CHANGED, Mark.ONLY, Mark.SAME]
    assert {m.group for m in d.left[1:3] + d.right[1:4]} == {1}
    assert d.changes == 3 and d.groups == 1


def test_whitespace_and_no_break_spaces_are_not_differences():
    d = diff_blocks(paras("He  ran fast. "), paras("He ran fast."))

    assert d.changes == 0


def test_block_text_of_each_kind():
    assert block_text(Paragraph((Run("a "), Run("b", em=True)))) == "a b"
    assert block_text(Separator()) == "—"
    assert block_text(Image("https://x/y.png", "a smile")) == "a smile"
    assert block_text(Image("https://x/y.png")) == "https://x/y.png"
    assert block_text(System("[Level up]")) == "[Level up]"


def test_huge_texts_skip_word_marks():
    left = paras(*(f"Left paragraph {i}." for i in range(2200)))
    right = paras(*(f"Right paragraph {i}." for i in range(1000)))

    started = time.monotonic()
    d = diff_blocks(left, right)

    assert time.monotonic() - started < 10
    assert any(m.state is Mark.CHANGED for m in d.left)
    assert all(m.spans is None for m in d.left + d.right)


def test_changed_words_next_to_each_other_form_one_mark():
    left = "Then he ran very fast towards the old gate of the city."
    d = diff_blocks(paras(left), paras("Then he walked quite slowly towards the old gate of the city."))

    assert marked(left, d.left[0].spans) == ["ran very fast"]


def test_a_rewritten_paragraph_is_highlighted_without_word_marks():
    d = diff_blocks(paras("Li Fan narrowed his eyes and looked down."), paras("Squinting, the cultivator surveyed the mortals."))

    assert d.left[0].state is Mark.CHANGED and d.left[0].spans == () and d.right[0].spans == ()
