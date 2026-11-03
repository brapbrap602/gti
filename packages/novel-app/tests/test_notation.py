import pytest
from novel_app.notation import OPEN_END, parse_range
from novel_core import KeyRange


@pytest.mark.parametrize(
    ("text", "keys"),
    [("7", KeyRange(7, 7)), ("1-100", KeyRange(1, 100)), (" 50- ", KeyRange(50, OPEN_END)), ("-80", KeyRange(0, 80))],
)
def test_ranges(text, keys):
    assert parse_range(text) == keys


@pytest.mark.parametrize("text", ["", "-", "5 7", "a", "9-3", "5--6"])
def test_not_ranges(text):
    with pytest.raises(ValueError):
        parse_range(text)
