import pytest
from novel_app.jobs import JobRow, JobState
from novel_app.pages import (
    LIBRARY_FILTERS,
    Cell,
    CellState,
    GridBlock,
    LibraryRow,
    NavRow,
    NovelCheck,
    NovelStatus,
    SourceLabel,
    SourceRow,
    Staleness,
    attention,
    sort_rows,
    source_label,
    state_counts,
)
from novel_core import ChapterKey, CheckReport, HeldNote, KeyRange, Kind, NumberingRun, OutputKind, SourceInfo, SourceSpec
from novel_core.alignment import AlignmentRules


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


def row(outputs=(), numbers=None, selected=10, jobs=(), slug="n", title="N", gaps=0, new=0, last_sync=None,
        web=True) -> LibraryRow:
    info = SourceInfo(1, spec("noveldl", "https://x.test"), AlignmentRules())
    sources = (SourceRow(info, 1, 0, 0, new if web else None),)
    return LibraryRow(slug, title, sources, numbers or {Kind.OFFICIAL_EN: selected}, selected, gaps, new, last_sync,
                      tuple(outputs), tuple(jobs), 100)  # fmt: skip


def job(state: JobState, kind: str = "sync") -> JobRow:
    return JobRow(1, "n", kind, {}, state, 0.0, None, 0, 0, "", ())


STALE = Staleness(OutputKind.SITE, 40, 2)


def titles(rows) -> list[str]:
    return [r.title for r in rows]


def test_attention_ranks_running_then_problems_rebuilds_new_gaps_then_the_rest():
    rows = [
        row(slug="bee", title="Bee"),
        row(slug="vee", title="Vee", gaps=2),
        row(slug="wo", title="Wo", new=5),
        row(slug="xu", title="Xu", outputs=[STALE]),
        row(slug="yak", title="Yak"),
        row(slug="zed", title="Zed", jobs=[job(JobState.RUNNING)]),
        row(slug="ant", title="Ant"),
    ]
    assert titles(sort_rows(rows, "attention", frozenset({"yak"}))) == ["Zed", "Yak", "Xu", "Wo", "Vee", "Ant", "Bee"]


def test_a_running_row_that_needs_a_rebuild_ranks_as_running():
    both = row(title="Both", outputs=[STALE], jobs=[job(JobState.RUNNING)])
    assert attention(both, frozenset()) == 0


def test_a_queued_job_is_not_running():
    abe = row(slug="abe", title="Abe", outputs=[STALE], jobs=[job(JobState.QUEUED)])
    cat = row(slug="cat", title="Cat")
    assert attention(abe, frozenset()) == 2
    assert abe.queued and not cat.queued
    assert abe.status is NovelStatus.REBUILD
    assert not LIBRARY_FILTERS["running"].test(abe)
    assert abe.job_of("sync") is not None  # still what keeps another sync from starting


@pytest.mark.parametrize(("sort", "order"), [
    ("title", ["Ant", "Bee", "Cat"]),
    ("chapters", ["Cat", "Ant", "Bee"]),
    ("gaps", ["Bee", "Ant", "Cat"]),  # Ant and Cat tie at 0: by title
    ("new", ["Ant", "Cat", "Bee"]),
    ("sync", ["Cat", "Bee", "Ant"]),  # never synced last
    ("outputs", ["Bee", "Ant", "Cat"]),
])  # fmt: skip
def test_each_column_sorts_one_way_then_by_title(sort, order):
    rows = [
        row(slug="c", title="Cat", selected=30, gaps=0, new=4, last_sync=200.0),
        row(slug="b", title="Bee", selected=10, gaps=5, new=0, last_sync=100.0,
            outputs=[Staleness(OutputKind.SITE, 40, 9)]),
        row(slug="a", title="Ant", selected=20, gaps=0, new=7, last_sync=None, outputs=[STALE]),
    ]  # fmt: skip
    assert titles(sort_rows(rows, sort, frozenset())) == order


def test_an_unknown_sort_is_attention():
    rows = [row(slug="a", title="Ant"), row(slug="z", title="Zed", new=3)]
    assert titles(sort_rows(rows, "bogus", frozenset())) == titles(sort_rows(rows, "attention", frozenset())) == ["Zed", "Ant"]


def test_library_filters_may_overlap():
    both = row(slug="both", outputs=[STALE], new=3)
    rebuild = row(slug="rebuild", outputs=[STALE], jobs=[job(JobState.RUNNING, "build-epub")])
    new = row(slug="new", new=2)
    offline = row(slug="offline", new=0, web=False)
    raw = row(slug="raw", numbers={Kind.RAW_ZH: 5}, selected=0)
    plain = row(slug="plain")
    rows = [both, rebuild, new, offline, raw, plain]

    def shown(name: str) -> list[str]:
        return [r.slug for r in rows if LIBRARY_FILTERS[name].test(r)]

    assert shown("running") == ["rebuild"]
    assert shown("rebuild") == ["both", "rebuild"]
    assert shown("new") == ["both", "new"]
    assert shown("raw-only") == ["raw"]
    assert shown("ok") == ["new", "offline", "plain"]
    assert list(LIBRARY_FILTERS) == ["running", "rebuild", "new", "raw-only", "ok"]


@pytest.mark.parametrize(("r", "status"), [
    (row(), NovelStatus.OK),
    (row([Staleness(OutputKind.SITE, 0, 40)]), NovelStatus.OK),  # never built: not a rebuild
    (row([Staleness(OutputKind.SITE, 40, 2)]), NovelStatus.REBUILD),
    (row(numbers={Kind.RAW_ZH: 5}, selected=0), NovelStatus.RAW_ONLY),
])  # fmt: skip
def test_novel_status(r, status):
    assert r.status is status
    assert NavRow.of(r) == NavRow("n", "N", status)
