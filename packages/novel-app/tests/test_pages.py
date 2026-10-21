import pytest
from novel_app.pages import (
    Cell,
    CellState,
    GridBlock,
    LibraryRow,
    NavRow,
    NovelCheck,
    NovelStatus,
    SourceLabel,
    Staleness,
    source_label,
    state_counts,
)
from novel_core import ChapterKey, CheckReport, HeldNote, KeyRange, Kind, NumberingRun, OutputKind, SourceSpec


def spec(backend: str, url: str) -> SourceSpec:
    return SourceSpec(backend, url, "en", Kind.OFFICIAL_EN)


@pytest.mark.parametrize(("backend", "url", "short"), [
    ("lncrawl", "https://www.novelbin.com/b/x", "novelbin.com"),
    ("noveldl", "http://novelbuddy.me/novel/test", "novelbuddy.me"),
    ("calibre", "file:///C:/a/My%20Longevity", "My Longevity"),
    ("calibre", "file:///C:/a/My%20Longevity/", "My Longevity"),
    ("custom:mine", "mine", "custom:mine"),
])  # fmt: skip
def test_source_label_names_the_site_or_folder(backend, url, short):
    assert source_label(spec(backend, url)) == SourceLabel(short, url)


@pytest.mark.parametrize(("built", "stale", "badge"), [
    (40, 0, ("site ✓", "fresh")),
    (40, 4, ("site 4 stale", "stale")),
    (0, 40, ("site not built", "missing")),
    (0, 0, ("site — nothing to build", "none")),
])  # fmt: skip
def test_output_badges(built, stale, badge):
    assert Staleness(OutputKind.SITE, built, stale).badge == badge


def test_a_translator_setup_is_labelled_by_its_model():
    from novel_translate.setups import TranslatorSetup

    label = source_label(TranslatorSetup("google/gemini-2.5-flash", data_collection="deny").spec())
    assert label == SourceLabel("google/gemini-2.5-flash", "google/gemini-2.5-flash · prompt v1 · parallel, no data collection")


def report(**found) -> CheckReport:
    empty = {f: () for f in CheckReport.__dataclass_fields__}
    return CheckReport(**{**empty, **found})


def test_check_problems_count_every_finding_but_gaps():
    held = HeldNote(1, "/3", "第3章", ())
    check = NovelCheck(report(held=(held,), gaps=(7, 8)), numbering=(NumberingRun(2, 2, 6, -1, 5),), unchecked=4)
    assert check.problems == 6


def test_state_counts_add_up_the_blocks():
    def cell(n: int, state: CellState) -> Cell:
        return Cell(ChapterKey(n), state, None, False)

    blocks = (
        GridBlock(KeyRange(1, 100), (cell(1, CellState.OFFICIAL), cell(2, CellState.MISSING), cell(3, CellState.OFFICIAL))),
        GridBlock(KeyRange(101, 200), (cell(101, CellState.FAILED), cell(102, CellState.OFFICIAL))),
    )
    assert state_counts(blocks) == {CellState.OFFICIAL: 3, CellState.MISSING: 1, CellState.FAILED: 1}


def row(outputs=(), numbers=None, selected=10, job=None) -> LibraryRow:
    return LibraryRow("n", "N", (), numbers or {Kind.OFFICIAL_EN: selected}, selected, 0, 0, None, tuple(outputs), job)


@pytest.mark.parametrize(("r", "status"), [
    (row(), NovelStatus.OK),
    (row([Staleness(OutputKind.SITE, 0, 40)]), NovelStatus.OK),  # never built: not a rebuild
    (row([Staleness(OutputKind.SITE, 40, 2)]), NovelStatus.REBUILD),
    (row(numbers={Kind.RAW_ZH: 5}, selected=0), NovelStatus.RAW_ONLY),
])  # fmt: skip
def test_novel_status(r, status):
    assert r.status is status
    assert NavRow.of(r) == NavRow("n", "N", status)
