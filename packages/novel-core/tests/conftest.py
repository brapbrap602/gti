from datetime import UTC, datetime, timedelta

import pytest
from novel_core import (
    Kind,
    NewVersion,
    NovelMeta,
    NovelStore,
    Paragraph,
    SourceItem,
    SourceSpec,
)


class TickingClock:
    """Each call is one second later, so last_seen_at ordering is deterministic."""

    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class Book:
    """Test-side helper for setting up a store: sources, indexes and chapter texts."""

    def __init__(self, store: NovelStore):
        self.store = store

    def source(self, name: str, kind: Kind = Kind.OFFICIAL_EN, published: bool = True) -> int:
        lang = "zh" if kind is Kind.RAW_ZH else "en"
        spec = SourceSpec(f"custom:{name}", f"https://{name}.test/novel", lang, kind)
        return self.store.upsert_source(spec, published=published)

    def chapters(self, source: int, titles: list[str], text: str = "text") -> list[str]:
        """Index items titled `titles` (refs derive from the titles) and store one version each."""
        items = [SourceItem(self.ref(t), pos, t) for pos, t in enumerate(titles, start=1)]
        self.store.record_index(source, items)
        for item in items:
            self.store.put_version(source, item.ref, self.version(f"{text} {item.title}"))
        return [i.ref for i in items]

    def picked(self) -> dict[str, int]:
        """Selection as {key label: source id}."""
        return {s.key.label: s.source_id for s in self.store.selection()}

    @staticmethod
    def ref(title: str) -> str:
        return "/novel/" + "-".join(title.lower().replace("(", "").replace(")", "").replace(":", "").split())

    @staticmethod
    def version(text: str, title: str = "T") -> NewVersion:
        return NewVersion(title=title, blocks=(Paragraph.of(text),))


@pytest.fixture
def clock():
    return TickingClock()


@pytest.fixture
def store(tmp_path, clock):
    with NovelStore.create(tmp_path / "novel", NovelMeta("Test Novel"), clock=clock) as s:
        yield s


@pytest.fixture
def book(store):
    return Book(store)
