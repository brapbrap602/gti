from novel_audio.script import MAX_CHARS, chapter_script
from novel_core import ChapterKey, Heading, Image, Note, Paragraph, Separator, System


def test_heading_then_sentences_in_reading_order():
    blocks = (
        Paragraph.of("He drew the sword from its sheath. Mr. Li watched him closely."),
        Separator(),
        Image("a.png"),
        System("[Level up: strength increased by one]"),
        Heading("Part Two of the Story"),
        Note("The translator would like to thank you."),
    )
    assert chapter_script(ChapterKey(524, 1), "Chapter 524 (1) - The Gate", blocks) == (
        "Chapter 524 pt 1: The Gate",
        "He drew the sword from its sheath.",
        "Mr. Li watched him closely.",
        "[Level up: strength increased by one]",
        "Part Two of the Story",
        "The translator would like to thank you.",
    )


def test_short_fragments_merge_into_the_next_sentence_of_their_paragraph():
    blocks = (Paragraph.of('"Hm." He looked up at the sky. "Yes."'), Paragraph.of("Okay."))
    assert chapter_script(ChapterKey(1), "Chapter 1", blocks)[1:] == (
        '"Hm." He looked up at the sky. "Yes."',
        "Okay.",
    )


def test_long_sentences_are_cut_at_clause_breaks():
    clause = "the river ran on and on past the hills"
    sentence = ", ".join([clause] * 40) + "."
    lines = chapter_script(ChapterKey(1), "Chapter 1", (Paragraph.of(sentence),))[1:]
    assert len(lines) > 1 and all(len(line) <= MAX_CHARS for line in lines)
    assert " ".join(lines) == sentence


def test_lines_with_nothing_to_say_are_dropped():
    blocks = (Paragraph.of("***"), Paragraph.of("……"), Paragraph.of("He nodded once, slowly."))
    assert chapter_script(ChapterKey(1), "Chapter 1", blocks)[1:] == ("He nodded once, slowly.",)
