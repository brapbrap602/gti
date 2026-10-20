import pytest
from novel_translate.glossary import AddAlias, AddTerm, Category, GlossaryError, RemoveAlias, Status, Term, UpdateTerm
from novel_translate.matching import Matcher
from novel_translate.tstore import TranslateStore


def term(zh, en, status=Status.ACCEPTED, category=Category.SECT, aliases=(), notes="", gender=None, id=None) -> Term:
    return Term(id or hash(zh), zh, en, category, status, gender=gender, notes=notes, aliases=tuple(aliases))


# -- matching -------------------------------------------------------------------


def test_the_longest_name_wins_and_aliases_match_like_keys():
    matcher = Matcher([
        term("天元", "Tianyuan", category=Category.PLACE),
        term("天元宗", "Heavenly Origin Sect"),
        term("林凡", "Lin Fan", category=Category.PERSON, aliases=["天元老祖"]),
    ])  # fmt: skip
    match = matcher.match("天元宗弟子拜见天元老祖。")
    assert [t.zh for t in match.terms] == ["天元宗", "林凡"]
    assert match.blocking == ()


def test_terms_needing_review_block_and_are_not_injected():
    matcher = Matcher([
        term("韩立", "Han Li", category=Category.PERSON),
        term("七玄门", "Seven Mysteries Sect", status=Status.NEEDS_REVIEW),
        term("墨大夫", "Doctor Mo", status=Status.PROPOSED),
        term("长春功", "Eternal Spring Art", status=Status.REJECTED),
    ])  # fmt: skip
    match = matcher.match("韩立走进七玄门，拜墨大夫为师，修炼长春功。")
    assert [t.zh for t in match.terms] == ["韩立"]
    assert [t.zh for t in match.blocking] == ["七玄门"]


def test_the_subset_hash_is_independent_of_order_and_follows_the_prompt_lines():
    a = term("韩立", "Han Li", category=Category.PERSON, gender="male", id=1)
    b = term("七玄门", "Seven Mysteries Sect", id=2)
    text = "七玄门的韩立"
    first, second = Matcher([a, b]).match(text), Matcher([b, a]).match(text)
    assert first.subset_hash == second.subset_hash
    assert first.prompt_lines == ("七玄门 → Seven Mysteries Sect (sect)", "韩立 → Han Li (person, male)")

    noted = Matcher([term("韩立", "Han Li", category=Category.PERSON, gender="male", notes="the hero", id=1), b])
    assert noted.match(text).subset_hash != first.subset_hash
    unrelated = Matcher([a, b, term("墨大夫", "Doctor Mo", notes="changed")])
    assert unrelated.match(text).subset_hash == first.subset_hash


def test_traditional_script_raws_match_simplified_entries():
    assert [t.en for t in Matcher([term("万剑宗", "Myriad Swords Sect")]).match("他入了萬劍宗").terms] == ["Myriad Swords Sect"]


# -- store ----------------------------------------------------------------------


@pytest.fixture
def ts(tmp_path):
    with TranslateStore.create(tmp_path) as store:
        yield store


def test_manual_terms_are_locked_normalized_and_marked_edited(ts):
    revision = ts.apply([AddTerm("萬劍宗", "Myriad Swords Sect", Category.SECT, aliases=("劍宗",))])
    (entry,) = ts.entries()
    assert (entry.zh, entry.status, entry.origin, entry.aliases, entry.edited) == (
        "万剑宗", Status.LOCKED, "manual", ("剑宗",), True,
    )  # fmt: skip
    assert revision == ts.revision == 1


def test_one_apply_is_all_or_nothing(ts):
    ts.apply([AddTerm("韩立", "Han Li", Category.PERSON)])
    with pytest.raises(GlossaryError, match="already in the glossary"):
        ts.apply([AddTerm("七玄门", "Seven Mysteries Sect", Category.SECT), AddTerm("韓立", "Han Li", Category.PERSON)])
    assert [t.zh for t in ts.entries()] == ["韩立"] and ts.revision == 1


def test_aliases_never_collide_with_names(ts):
    ts.apply([AddTerm("韩立", "Han Li", Category.PERSON), AddTerm("七玄门", "Seven Mysteries Sect", Category.SECT)])
    han = ts.entries(search="Han")[0].id
    with pytest.raises(GlossaryError, match="already in the glossary"):
        ts.apply([AddAlias(han, "七玄门")])
    ts.apply([AddAlias(han, "韩跑跑")])
    with pytest.raises(GlossaryError, match="already in the glossary"):
        ts.apply([AddTerm("韩跑跑", "Runner Han", Category.PERSON)])
    ts.apply([RemoveAlias("韩跑跑")])
    assert ts.entries(search="韩立")[0].aliases == ()


def test_updates_change_only_what_they_name(ts):
    ts.apply([AddTerm("韩立", "Han Li", Category.PERSON, notes="hero", gender="male")])
    han = ts.entries()[0].id
    ts.apply([UpdateTerm(han, en="Han Li (韩)", status=Status.ACCEPTED)])
    entry = ts.entries()[0]
    assert (entry.en, entry.status, entry.notes, entry.gender) == ("Han Li (韩)", Status.ACCEPTED, "hero", "male")
    ts.apply([UpdateTerm(han, notes="", gender="")])
    entry = ts.entries()[0]
    assert (entry.notes, entry.gender) == ("", None)
    with pytest.raises(GlossaryError, match="no term 999"):
        ts.apply([UpdateTerm(999, en="x")])


def test_entries_filter_by_status_and_search_either_language(ts):
    ts.apply([
        AddTerm("韩立", "Han Li", Category.PERSON, status=Status.ACCEPTED),
        AddTerm("七玄门", "Seven Mysteries Sect", Category.SECT),
        AddTerm("墨大夫", "Doctor Mo", Category.PERSON, status=Status.REJECTED),
    ])  # fmt: skip
    assert [t.zh for t in ts.entries(status=Status.LOCKED)] == ["七玄门"]
    assert [t.zh for t in ts.entries(search="mo")] == ["墨大夫"]
    assert [t.zh for t in ts.entries(search="七玄")] == ["七玄门"]
    assert [t.zh for t in ts.entries(category=Category.PERSON)] == ["韩立", "墨大夫"]


def test_the_matcher_reflects_the_stored_glossary_and_survives_reopening(tmp_path):
    with TranslateStore.create(tmp_path) as ts:
        ts.apply([AddTerm("韩立", "Han Li", Category.PERSON, aliases=("韩老魔",))])
    with TranslateStore.open(tmp_path) as ts:
        assert [t.en for t in ts.matcher().match("韩老魔笑了").terms] == ["Han Li"]
        assert ts.revision == 1
    with pytest.raises(FileExistsError):
        TranslateStore.create(tmp_path)
