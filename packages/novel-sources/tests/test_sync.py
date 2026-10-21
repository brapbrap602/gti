import pytest
from novel_core import KeyRange, Kind, NovelMeta, NovelStore, RawChapter, SourceItem, SourceSpec
from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.importing import NovelIndex
from novel_sources.sync import add_source, sync
from novel_sources.zh_tables import rules

RULES = CleanRules(content=("div#body",))


class FakeSite:
    """A web source whose chapters are `Chapter N`; `fail` and `locked` are numbers it cannot serve."""

    def __init__(self, numbers, fail=(), locked=(), text="Text"):
        self.spec = SourceSpec("custom:fake", "https://fake.test/novel", "en", Kind.OFFICIAL_EN)
        self.numbers = list(numbers)
        self.fail = set(fail)
        self.locked = set(locked)
        self.text = text
        self.fetched: list[int] = []

    def fetch_index(self) -> NovelIndex:
        items = tuple(SourceItem(f"/novel/chapter-{n}", pos, f"Chapter {n}") for pos, n in enumerate(self.numbers, 1))
        return NovelIndex(NovelMeta("Fake Novel", author="A. Writer"), items)

    def fetch_chapter(self, item: SourceItem) -> RawChapter | None:
        n = int(item.ref.rsplit("-", 1)[1])
        self.fetched.append(n)
        if n in self.fail:
            raise FetchError(f"{item.ref}: HTTP 503 after 3 attempts")
        if n in self.locked:
            return None
        return RawChapter(f'<div id="body"><p>{self.text} of chapter {n}.</p></div>', final_url=f"https://fake.test{item.ref}")

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return RULES


@pytest.fixture
def novel(tmp_path, clock):
    site = FakeSite(range(1, 6))
    report = add_source(tmp_path / "fake", site.spec, site.fetch_index(), clock)
    return tmp_path / "fake", report.source_id, site


def test_add_creates_the_novel_and_records_the_index_without_fetching(novel):
    novel_dir, source, site = novel
    assert site.fetched == []
    with NovelStore.open(novel_dir) as store:
        assert store.meta.author == "A. Writer"
        assert store.selection() == ()
        assert len(store.to_fetch(source)) == 5


def test_sync_resume(novel):
    novel_dir, source, site = novel
    site.fail = {3}
    with NovelStore.open(novel_dir) as store:
        first = sync(store, source, site)
        assert (first.inserted, [ref for ref, _ in first.failed]) == (4, ["/novel/chapter-3"])
        assert "HTTP 503" in first.failed[0][1]
        site.fail = set()
        site.fetched.clear()
        second = sync(store, source, site)
        assert site.fetched == [3]
        assert second.inserted == 1 and not second.failed
        assert [s.key.label for s in store.selection()] == ["1", "2", "3", "4", "5"]


def test_sync_new_only(novel):
    novel_dir, source, site = novel
    with NovelStore.open(novel_dir) as store:
        sync(store, source, site)
        site.numbers = list(range(1, 8))
        site.fetched.clear()
        report = sync(store, source, site)
    assert site.fetched == [6, 7]
    assert report.index.added == ("/novel/chapter-6", "/novel/chapter-7")


def test_sync_only_fetches_just_those_numbers_and_the_rest_later(novel):
    novel_dir, source, site = novel
    with NovelStore.open(novel_dir) as store:
        report = sync(store, source, site, only=KeyRange(2, 3))
        assert site.fetched == [2, 3] and report.wanted == 2
        assert len(store.to_fetch(source)) == 3  # the whole index is recorded
        site.fetched.clear()
        sync(store, source, site)
    assert site.fetched == [1, 4, 5]


def test_locked_chapter_is_a_gap_not_a_failure(novel):
    novel_dir, source, site = novel
    site.locked = {2}
    with NovelStore.open(novel_dir) as store:
        report = sync(store, source, site)
        assert report.unavailable == ("/novel/chapter-2",) and not report.failed
        site.fetched.clear()
        sync(store, source, site)
    assert site.fetched == []  # a locked chapter is not asked for again


def test_refresh_stores_a_new_version_only_when_the_text_changed(novel):
    novel_dir, source, site = novel
    with NovelStore.open(novel_dir) as store:
        sync(store, source, site)
        site.text = "Edited text"
        report = sync(store, source, site, refresh=KeyRange(4, 9))
        assert (report.wanted, report.inserted, report.unchanged) == (2, 2, 0)
        site.fetched.clear()
        again = sync(store, source, site, refresh=KeyRange(4, 9))
        assert (again.inserted, again.unchanged) == (0, 2)
        assert [s.title for s in store.selection()][-1] == "Chapter 5"


# -- raw-zh sources: zh rules hold poisoned chapters, decoy sites are index-only --------------

FILLER = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁律吕调阳云腾致雨露结为霜金生丽水玉出昆冈"
CLEAN = "\n".join([FILLER * 3] * 12)
POISONED = "\n".join(FILLER * 3 + marker for marker in ("有没", "是止", "退入") * 4)


class ZhSite:
    """A raw-zh web source serving text chapters; `poisoned` are numbers it serves scrambled."""

    def __init__(self, name, numbers, poisoned=(), content_type="text"):
        self.spec = SourceSpec("custom:zh", f"https://{name}.test/book", "zh", Kind.RAW_ZH)
        self.numbers = list(numbers)
        self.poisoned = set(poisoned)
        self.content_type = content_type
        self.fetched: list[int] = []

    def fetch_index(self) -> NovelIndex:
        items = tuple(SourceItem(f"/book/{n}", pos, f"第{n}章 名字{n}") for pos, n in enumerate(self.numbers, 1))
        return NovelIndex(NovelMeta("书", language="zh"), items)

    def fetch_chapter(self, item: SourceItem) -> RawChapter:
        n = int(item.ref.rsplit("/", 1)[1])
        self.fetched.append(n)
        text = POISONED if n in self.poisoned else CLEAN
        if self.content_type == "html":
            return RawChapter('<div id="c">' + "".join(f"<p>{p}</p>" for p in text.split("\n")) + "</div>")
        return RawChapter(text, "text")

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return CleanRules(content=("div#c",))


@pytest.fixture
def zh_novel(tmp_path, clock):
    """A raw-zh novel with sources A and B (in that priority), both listing 1-3; A serves 2 poisoned."""
    a, b = ZhSite("a", range(1, 4), poisoned={2}), ZhSite("b", range(1, 4))
    novel_dir = tmp_path / "zh"
    ids = [add_source(novel_dir, site.spec, site.fetch_index(), clock).source_id for site in (a, b)]
    with NovelStore.open(novel_dir, clock=clock) as store:
        yield store, dict(zip("ab", ids)), a, b


def test_sync_held_then_other_source(zh_novel):
    store, ids, a, b = zh_novel
    first = sync(store, ids["a"], a, zh=rules("zh", "custom"))
    assert (first.inserted, [ref for ref, _ in first.held]) == (3, ["/book/2"])
    assert first.held[0][1].startswith("poison: 有没×4 是止×4 退入×4")
    second = sync(store, ids["b"], b, zh=rules("zh", "custom"))
    assert b.fetched == [2] and second.held == ()
    chosen = [(s.source_id, s.key.number) for s in store.view().raw_chapters()]
    assert chosen == [(ids["a"], 1), (ids["b"], 2), (ids["a"], 3)]


def test_sync_refetch_clears(zh_novel):
    store, ids, a, _ = zh_novel
    sync(store, ids["a"], a, zh=rules("zh", "custom"))
    a.poisoned.clear()
    a.fetched.clear()
    again = sync(store, ids["a"], a, zh=rules("zh", "custom"))
    assert a.fetched == [2]  # held items are fetched again; clean ones are not
    assert (again.inserted, again.cleared, again.held) == (1, 1, ())
    assert store.view().held(ids["a"], "/book/2") == ()


def test_sync_stamps_rules_rev(zh_novel):
    store, ids, a, _ = zh_novel
    zh = rules("zh", "custom")
    sync(store, ids["a"], a, zh=zh)
    assert {s.rules_rev for s in store.chapters(ids["a"])} == {zh.rev}


def test_sync_decoy_index_only(zh_novel):
    store, ids, a, _ = zh_novel
    decoy = rules("zh", "biquge5")
    a.numbers = list(range(1, 6))
    first = sync(store, ids["a"], a, zh=decoy)
    assert (first.decoy_site, first.wanted, a.fetched, first.index.added) == (True, 0, [], ("/book/4", "/book/5"))
    assert sync(store, ids["a"], a, only=KeyRange(1, 2), zh=decoy).wanted == 0
    assert sync(store, ids["a"], a, refresh=KeyRange(4, 5), only=KeyRange(1, 2), zh=decoy).wanted == 0
    refreshed = sync(store, ids["a"], a, refresh=KeyRange(4, 9), only=KeyRange(1, 4), zh=decoy)
    assert a.fetched == [4] and refreshed.inserted == 1
    assert not sync(store, ids["a"], a, zh=rules("zh", "custom")).decoy_site


def test_html_raw_zh_still_stores(tmp_path, clock):
    site = ZhSite("html", range(1, 3), poisoned={2}, content_type="html")
    report = add_source(tmp_path / "zh", site.spec, site.fetch_index(), clock)
    with NovelStore.open(tmp_path / "zh") as store:
        r = sync(store, report.source_id, site, zh=rules("zh", "lncrawl"))
        assert (r.inserted, r.failed, [ref for ref, _ in r.held]) == (2, (), ["/book/2"])
        assert len(store.read_version(store.chapters(report.source_id)[0].version_id).blocks) == 12


def test_sync_english_unchanged_reports_no_holds(novel):
    novel_dir, source, site = novel
    with NovelStore.open(novel_dir) as store:
        r = sync(store, source, site)
    assert (r.inserted, r.held, r.cleared, r.decoy_site) == (5, (), 0, False)
