import pytest
from novel_core import KeyRange, Kind, NovelMeta, NovelStore, RawChapter, SourceItem, SourceSpec
from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.importing import NovelIndex
from novel_sources.sync import add_source, sync

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
