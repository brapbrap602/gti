"""What the web UI shows of a novel, each derived from one NovelView.

`library_row` is the library page's summary, `chapter_grid` the novel page's cells
(one per chapter key, in blocks of 100 numbers) and `comparison` two sources' texts
of one chapter number side by side, with their differences marked. `novel_check` is
what `nov check` and the Check section show; `unchecked` counts raw-zh chapters
not checked with the current zh rules, and `anchor` picks the raw source the others'
numbering is compared with.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import zip_longest
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit

from markupsafe import Markup, escape
from novel_audio.build import fingerprint as audio_fingerprint
from novel_audio.tts import DEFAULT_VOICE
from novel_core import (
    Block,
    ChapterKey,
    CheckReport,
    Finding,
    ItemStatus,
    KeyRange,
    Kind,
    NovelStore,
    NovelView,
    NumberingRun,
    OutputKind,
    SourceId,
    SourceInfo,
    SourceSpec,
)
from novel_core.keys import chapter_heading
from novel_core.selection import Pin
from novel_publish import epub, render
from novel_publish import site as site_builder
from novel_sources.backends import is_reference, is_web, zh_rules
from novel_translate.raws import RawRules, unchecked_raw
from novel_translate.setups import BACKEND as SETUP_BACKEND
from novel_translate.setups import TranslatorSetup

from novel_app.diff import BlockMark, Mark, TextDiff, diff_blocks, normalised
from novel_app.jobs import JobRow, JobState
from novel_app.library import novel_dir

GRID_BLOCK = 100


@dataclass(frozen=True)
class SourceRow:
    info: SourceInfo
    rank: int
    listed: int  # items in its index, vanished ones excluded
    texts: int  # mapped items with a stored text
    to_fetch: int | None  # None for imports, which are never synced

    @property
    def id(self) -> int:
        return self.info.id


@dataclass(frozen=True)
class SourceLabel:
    short: str  # what a table shows: a site's host, an imported folder's name, a setup's model, else the backend
    full: str  # the source's URL, for a tooltip or a second line


def source_label(spec: SourceSpec) -> SourceLabel:
    if spec.backend == SETUP_BACKEND:  # a translator setup: its model, and the rest of its identity
        setup = TranslatorSetup.from_spec(spec)
        return SourceLabel(setup.model, setup.label)
    parts = urlsplit(spec.url)
    if parts.scheme in ("http", "https") and parts.hostname:
        short = parts.hostname.removeprefix("www.")
    elif parts.scheme == "file":
        short = PurePosixPath(unquote(parts.path).rstrip("/")).name or spec.backend
    else:
        short = spec.backend
    return SourceLabel(short, spec.url)


@dataclass(frozen=True)
class Staleness:
    kind: OutputKind
    built: int  # chapters with an output row
    stale: int  # chapters to build or prune

    @property
    def badge(self) -> tuple[str, str]:
        """Short text and its state (fresh, stale, missing, none) for the library's outputs cell."""
        if self.built == 0 and self.stale == 0:
            return f"{self.kind} — nothing to build", "none"
        if self.built == 0:
            return f"{self.kind} not built", "missing"
        if self.stale:
            return f"{self.kind} {self.stale} stale", "stale"
        return f"{self.kind} ✓", "fresh"


@dataclass(frozen=True)
class LibraryRow:
    slug: str
    title: str
    sources: tuple[SourceRow, ...]  # best first
    numbers: Mapping[Kind, int]  # chapter numbers that each kind of source has a text for
    selected: int
    gaps: int
    new_items: int  # items the web sources list that the book lacks
    last_sync: float | None
    outputs: tuple[Staleness, ...]
    jobs: tuple[JobRow, ...]  # the novel's active jobs, newest first; at most one of each kind
    epub_size: int  # chapter numbers per EPUB volume, as the last EPUB build had it
    public: bool = True  # on the public reading site

    def job_of(self, kind: str) -> JobRow | None:
        """The novel's active job of this kind: what keeps another of that kind from starting."""
        return next((j for j in self.jobs if j.kind == kind), None)

    @property
    def raw_only(self) -> bool:
        return self.selected == 0 and self.numbers.get(Kind.RAW_ZH, 0) > 0

    @property
    def can_sync(self) -> bool:
        return any(s.to_fetch is not None for s in self.sources)

    @property
    def needs_rebuild(self) -> bool:
        """Some output was built and has stale chapters; one never built is not a rebuild."""
        return any(o.built and o.stale for o in self.outputs)

    @property
    def running(self) -> bool:
        """A job of the novel has started; one only queued does not count."""
        return any(j.state is JobState.RUNNING for j in self.jobs)

    @property
    def queued(self) -> bool:
        """The novel's jobs are all waiting their turn."""
        return bool(self.jobs) and not self.running

    @property
    def status(self) -> "NovelStatus":
        if self.running:
            return NovelStatus.RUNNING
        if self.needs_rebuild:
            return NovelStatus.REBUILD
        return NovelStatus.RAW_ONLY if self.raw_only else NovelStatus.OK


class NovelStatus(StrEnum):
    """A novel's dot in the app's sidebar."""

    RUNNING = "running"
    REBUILD = "rebuild"
    RAW_ONLY = "raw-only"
    OK = "ok"
    UNKNOWN = "unknown"  # its library row could not be read


STATUS_LABELS = {
    NovelStatus.RUNNING: "a job is running",
    NovelStatus.REBUILD: "an output needs a rebuild",
    NovelStatus.RAW_ONLY: "raw chapters only",
    NovelStatus.OK: "up to date",
    NovelStatus.UNKNOWN: "status unknown",
}

# The sidebar's status chips, in order: each status a library row can have, and its label.
LIBRARY_STATUSES = {
    NovelStatus.RUNNING: "Running",
    NovelStatus.REBUILD: "Needs rebuild",
    NovelStatus.RAW_ONLY: "Raw only",
    NovelStatus.OK: "Up to date",
}


@dataclass(frozen=True)
class Filter:
    label: str
    test: Callable[[LibraryRow], bool]


# The library's filter tabs (`?status=`), in order. Unlike the sidebar's statuses they may overlap,
# so a stat tile and the tab it links to count the same rows.
LIBRARY_FILTERS: dict[str, Filter] = {
    "running": Filter("Running", lambda r: r.running),
    "rebuild": Filter("Needs rebuild", lambda r: r.needs_rebuild),
    "new": Filter("New to fetch", lambda r: r.can_sync and r.new_items > 0),
    "raw-only": Filter("Raw only", lambda r: r.raw_only),
    "ok": Filter("Up to date", lambda r: r.status is NovelStatus.OK),
}


def attention(row: LibraryRow, problem_targets: frozenset[str]) -> int:
    """How soon the novel wants a look, 0 first: a job running, an unresolved job problem,
    a stale output, chapters to fetch, gaps, else nothing."""
    if row.running:
        return 0
    if row.slug in problem_targets:
        return 1
    if row.needs_rebuild:
        return 2
    if row.new_items > 0:
        return 3
    return 4 if row.gaps > 0 else 5


type SortKey = Callable[[LibraryRow, frozenset[str]], tuple]

# The library's orders (`?sort=`): one natural direction per column; ties go by title.
LIBRARY_SORTS: dict[str, SortKey] = {
    "attention": lambda r, p: (attention(r, p),),
    "title": lambda r, p: (),
    "chapters": lambda r, p: (-r.selected,),
    "gaps": lambda r, p: (-r.gaps,),
    "new": lambda r, p: (-r.new_items,),
    "sync": lambda r, p: (r.last_sync is None, -(r.last_sync or 0.0)),  # most recent first, never synced last
    "outputs": lambda r, p: (-sum(o.stale for o in r.outputs),),
}


def sort_rows(rows: Iterable[LibraryRow], sort: str, problem_targets: frozenset[str]) -> list[LibraryRow]:
    """The rows in the named order (an unknown name is attention), a total order: then title, then slug."""
    key = LIBRARY_SORTS.get(sort, LIBRARY_SORTS["attention"])
    return sorted(rows, key=lambda r: (*key(r, problem_targets), r.title.casefold(), r.slug))


@dataclass(frozen=True)
class NavRow:
    """A novel in the app's sidebar."""

    slug: str
    title: str
    status: NovelStatus = NovelStatus.UNKNOWN

    @classmethod
    def of(cls, row: LibraryRow) -> "NavRow":
        return cls(row.slug, row.title, row.status)


class CellState(StrEnum):
    OFFICIAL = "official"  # selected from an official-en source
    MINE = "mine"  # selected from a my-translation source
    RAW_ONLY = "raw-only"
    FAILED = "failed"
    LOCKED = "locked"
    MISSING = "missing"


CELL_LABELS = {
    CellState.OFFICIAL: "official",
    CellState.MINE: "my translation",
    CellState.RAW_ONLY: "raw only",
    CellState.FAILED: "fetch failed",
    CellState.LOCKED: "locked",
    CellState.MISSING: "missing",
}


@dataclass(frozen=True)
class Cell:
    key: ChapterKey
    state: CellState
    source_id: int | None  # the selected source
    pinned: bool
    title: str = ""

    @property
    def label(self) -> str:
        """Text for screen readers and tooltips: the color is never the only signal."""
        parts = [self.key.label, CELL_LABELS[self.state]]
        if self.source_id is not None:
            parts.append(f"source {self.source_id}")
        if self.pinned:
            parts.append("pinned")
        return ", ".join(parts) + (f": {self.title}" if self.title else "")


@dataclass(frozen=True)
class GridBlock:
    range: KeyRange
    cells: tuple[Cell, ...]

    def count(self, state: CellState) -> int:
        return sum(c.state is state for c in self.cells)


def state_counts(blocks: Iterable[GridBlock]) -> dict[CellState, int]:
    """How many cells of the whole grid are in each state (states with none left out)."""
    counts: dict[CellState, int] = defaultdict(int)
    for block in blocks:
        for cell in block.cells:
            counts[cell.state] += 1
    return dict(counts)


def library_row(
    slug: str, view: NovelView, jobs: Sequence[JobRow], last_sync: float | None, epub_size: int = epub.VOLUME_SIZE
) -> LibraryRow:
    """The novel's row; EPUB staleness is judged against volumes of `epub_size` chapter numbers."""
    counts: dict[Kind, set[int]] = defaultdict(set)
    rows = []
    to_fetch_total = 0
    rank = {sid: i for i, sid in enumerate(view.priority, start=1)}
    for info in view.sources:
        items = view.items(info.id)
        texts = view.chapters(info.id)
        if info.published:
            counts[info.spec.kind] |= {c.key.number for c in texts}
        to_fetch = len(view.to_fetch(info.id)) if is_web(info.spec) else None
        to_fetch_total += to_fetch or 0
        rows.append(SourceRow(info, rank[info.id], sum(not i.vanished for i in items), len(texts), to_fetch))
    rows.sort(key=lambda r: r.rank)
    cover = view.meta.cover_path
    fingerprints = {
        OutputKind.SITE: site_builder.novel_fingerprint(view.meta),
        OutputKind.EPUB: epub.fingerprint(view.meta, (novel_dir(slug) / cover).read_bytes() if cover else None, epub_size),
        OutputKind.AUDIO: audio_fingerprint(DEFAULT_VOICE),
    }
    outputs = []
    for kind, fp in fingerprints.items():
        plan = view.plan_build(kind, fp)
        outputs.append(Staleness(kind, len(view.outputs(kind)), len(plan.to_build) + len(plan.to_prune)))
    return LibraryRow(
        slug=slug,
        title=view.meta.title,
        sources=tuple(rows),
        numbers={k: len(v) for k, v in counts.items()},
        selected=len(view.selection),
        gaps=len(view.check().gaps),
        new_items=to_fetch_total,
        last_sync=last_sync,
        outputs=tuple(outputs),
        jobs=active_jobs(jobs, slug),
        epub_size=epub_size,
        public=view.public,
    )


def active_label(jobs: Iterable[JobRow]) -> str:
    """Active jobs as "1 running · 29 queued", a zero part left out; "" for none (app.js says the same)."""
    states = [j.state for j in jobs]
    parts = [(states.count(s), s) for s in (JobState.RUNNING, JobState.QUEUED)]
    return " · ".join(f"{n} {s}" for n, s in parts if n)


def active_jobs(jobs: Sequence[JobRow], target: str) -> tuple[JobRow, ...]:
    return tuple(j for j in jobs if j.target == target and j.state.active)


def chapter_grid(view: NovelView) -> tuple[GridBlock, ...]:
    """A cell per selected key; a number with nothing selected gets one cell saying why."""
    selected: dict[int, list] = defaultdict(list)
    for s in view.selection:
        selected[s.key.number].append(s)
    raw, failed, locked = set(), set(), set()
    numbers = set(selected)
    for info in view.sources:
        for item in view.items(info.id):
            if item.key is None:
                continue
            numbers.add(item.key.number)
            if info.spec.kind is Kind.RAW_ZH:
                if item.has_text:
                    raw.add(item.key.number)
            elif item.status is ItemStatus.FAILED:
                failed.add(item.key.number)
            elif item.status is ItemStatus.UNAVAILABLE:
                locked.add(item.key.number)
    if not numbers:
        return ()
    kinds = {info.id: info.spec.kind for info in view.sources}

    def pinned(n: int) -> bool:
        return any(n in p.range for p in view.pins)

    blocks: dict[KeyRange, list[Cell]] = defaultdict(list)
    for n in range(min(numbers), max(numbers) + 1):
        block = KeyRange.containing(n, GRID_BLOCK)
        if n in selected:
            for s in selected[n]:
                state = CellState.MINE if kinds[s.source_id] is Kind.MY_TRANSLATION else CellState.OFFICIAL
                blocks[block].append(Cell(s.key, state, s.source_id, pinned(n), s.title))
            continue
        if n in raw:
            state = CellState.RAW_ONLY
        elif n in failed:
            state = CellState.FAILED
        elif n in locked:
            state = CellState.LOCKED
        else:
            state = CellState.MISSING
        blocks[block].append(Cell(ChapterKey(n), state, None, pinned(n)))
    return tuple(GridBlock(r, tuple(cells)) for r, cells in sorted(blocks.items(), key=lambda kv: kv[0].start))


@dataclass(frozen=True)
class NovelCheck:
    """What `nov check` and the novel page's Check section show."""

    report: CheckReport
    numbering: tuple[NumberingRun, ...] = ()  # raw sources numbered unlike the anchor
    unchecked: int = 0  # raw-zh chapters not checked with the current zh rules
    anchor: SourceId | None = None  # the raw source numbering compares against

    @property
    def problems(self) -> int:
        """Every finding to act on; gaps and raw-only numbers are facts about the book, not problems."""
        k = self.report
        listed = (k.duplicates, k.unmapped, k.vanished, k.failed, k.held, k.title_mismatches, k.mixed_parts,
                  k.pin_fallbacks, k.legacy_moved, k.legacy_unselected, self.numbering)  # fmt: skip
        return sum(len(found) for found in listed) + self.unchecked


def novel_check(slug: str, view: NovelView) -> NovelCheck:
    numbering = view.numbering(found) if (found := anchor(slug, view)) is not None else ()
    return NovelCheck(view.check(), numbering, unchecked(slug, view), found)


def anchor(slug: str, view: NovelView) -> SourceId | None:
    """The raw source whose numbering counts as right: Qidian's, else the first raw source in
    priority that is not a decoy site (whose printed numbers repeat); None without one."""
    raws = [view.source(sid) for sid in view.priority if view.source(sid).spec.kind is Kind.RAW_ZH]
    if reference := next((info for info in raws if is_reference(info.spec)), None):
        return reference.id
    return next((info.id for info in raws if not zh_rules(slug, info.spec).decoy_site), None)


def align_range_command(slug: str, run: NumberingRun) -> str:
    """The command that applies a numbering suggestion."""
    return f"nov align range {slug} {run.printed_start}-{run.printed_end} {run.offset} --source {run.source_id}"


def reclean_command(slug: str) -> str:
    """The command that checks a novel's raws with the current zh rules."""
    return f"nov reclean {slug}"


def findings_text(found: Sequence[Finding]) -> str:
    """A held chapter's findings, as `nov check` and the Check section show them."""
    return "; ".join(f"{f.check}: {f.detail}" for f in found)


def unchecked(slug: str, view: NovelView) -> int:
    """Current raw-zh chapters not checked with today's zh rules (never checked, or by older rules),
    by the rule translation refuses them by."""
    rules = raw_rules(slug, view.sources)
    return sum(
        unchecked_raw(info.id, s.rules_rev, rules)
        for info in view.sources if info.spec.kind is Kind.RAW_ZH
        for s in view.chapters(info.id)
    )  # fmt: skip


def raw_rules(slug: str, sources: Iterable[SourceInfo]) -> dict[SourceId, RawRules]:
    """What translation needs of each raw-zh source's zh rules: its translator notes and revision."""
    return {info.id: RawRules(zh.notes, zh.rev) for info in sources if (zh := zh_rules(slug, info.spec))}


@dataclass(frozen=True)
class NovelPage:
    row: LibraryRow
    grid: tuple[GridBlock, ...]
    pins: tuple[Pin, ...]  # oldest first; a later pin wins
    check: NovelCheck


@dataclass(frozen=True)
class Part:
    """One key (part) of a chapter number: its heading and its body rendered, differences marked."""

    heading: str
    body: Markup


@dataclass(frozen=True)
class Text:
    """One source's text for a chapter number."""

    source: SourceInfo
    chapters: tuple[Part, ...]


@dataclass(frozen=True)
class AlignedCell:
    kind: Literal["block", "heading", "blank"]
    html: Markup = Markup("")  # a blank holds the jump target of a group its side has no block of


@dataclass(frozen=True)
class AlignedRow:
    """A row of two English texts side by side: a block and its counterpart, or a part's heading."""

    left: AlignedCell
    right: AlignedCell

    @property
    def heading(self) -> bool:
        return "heading" in (self.left.kind, self.right.kind)


@dataclass(frozen=True)
class Comparison:
    number: int
    offers: tuple[SourceInfo, ...]  # sources with a text for the number, best first
    selected: int | None  # the source the book uses
    left: Text | None
    right: Text | None
    diff: TextDiff | None  # None when a side is missing or either side is raw text
    rows: tuple[AlignedRow, ...] | None  # the texts lined up, when there is a diff
    last: int  # the highest chapter number any source has a text for; 0 if none


def comparison(store: NovelStore, view: NovelView, number: int, left: int | None, right: int | None) -> Comparison:
    """The number's texts from `left` and `right`; left defaults to the selected source, right to the next offer."""
    by_source: dict[int, list] = defaultdict(list)
    last = 0
    for info in view.sources:
        for c in view.chapters(info.id):
            last = max(last, c.key.number)
            if c.key.number == number:
                by_source[info.id].append(c)
    offers = tuple(view.source(sid) for sid in view.priority if sid in by_source)
    selected = next((s.source_id for s in view.selection if s.key.number == number), None)
    ids = [o.id for o in offers]
    if left not in by_source:
        left = selected if selected is not None else (ids[0] if ids else None)
    if right not in by_source:
        right = next((i for i in ids if i != left), None)

    def parts(sid: int) -> list[tuple[str, tuple[Block, ...]]]:
        out = []
        for c in sorted(by_source[sid], key=lambda c: c.key):
            version = store.read_version(c.version_id)
            out.append((chapter_heading(c.key, version.title), version.blocks))
        return out

    sides = {sid: parts(sid) for sid in (left, right) if sid is not None}
    diff = None
    if left is not None and right is not None and Kind.RAW_ZH not in (view.source(left).spec.kind, view.source(right).spec.kind):
        diff = diff_blocks(*([b for _, blocks in sides[sid] for b in blocks] for sid in (left, right)))

    def text(sid: int | None, side: str) -> Text | None:
        if sid is None:
            return None
        marks, gaps = None, ()
        if diff:
            marks, gaps = (diff.left, diff.left_gaps) if side == "l" else (diff.right, diff.right_gaps)
        return Text(view.source(sid), _marked_parts(sides[sid], marks, gaps, side))

    rows = _aligned_rows(sides[left], sides[right], diff) if diff else None
    return Comparison(number, offers, selected, text(left, "l"), text(right, "r"), diff, rows, last)


def _aligned_rows(
    left: Sequence[tuple[str, Sequence[Block]]], right: Sequence[tuple[str, Sequence[Block]]], diff: TextDiff
) -> tuple[AlignedRow, ...]:
    """Both sides' blocks in the diff's pairs, a blank facing an extra block. A heading row comes wherever
    either side starts a part. Ids as in `_marked_parts`: a group's first block on a side, else (when that
    side has none of the group) the first blank facing it."""
    sides = {"l": _flat(left), "r": _flat(right)}
    marks = {"l": diff.left, "r": diff.right}
    gapped = {"l": {g for _, g in diff.left_gaps}, "r": {g for _, g in diff.right_gaps}}
    targeted: dict[str, set[int | None]] = {"l": set(), "r": set()}
    rows: list[AlignedRow] = []

    def headings(at: dict[str, int | None]) -> None:
        found = {side: sides[side][1].pop(i, []) if i is not None else [] for side, i in at.items()}
        for a, b in zip_longest(found["l"], found["r"]):
            rows.append(AlignedRow(*(AlignedCell("heading", Markup('<h3 class="chapter">{}</h3>').format(h))
                                     if h is not None else AlignedCell("blank") for h in (a, b))))  # fmt: skip

    def cell(side: str, index: int | None, facing: BlockMark) -> AlignedCell:
        if index is None:
            if facing.group in gapped[side]:
                gapped[side].discard(facing.group)
                return AlignedCell("blank", _gap(facing.group, side))
            return AlignedCell("blank")
        mark = marks[side][index]
        html = _marked_block(sides[side][0][index], mark, side, mark.group not in targeted[side])
        targeted[side].add(mark.group)
        return AlignedCell("block", html)

    for i, j in diff.pairs:
        headings({"l": i, "r": j})
        rows.append(AlignedRow(cell("l", i, diff.right[j] if j is not None else BlockMark(Mark.SAME)),
                               cell("r", j, diff.left[i] if i is not None else BlockMark(Mark.SAME))))  # fmt: skip
    headings({"l": len(sides["l"][0]), "r": len(sides["r"][0])})  # parts with no blocks, at the end
    return tuple(rows)


def _flat(parts: Sequence[tuple[str, Sequence[Block]]]) -> tuple[list[Block], dict[int, list[str]]]:
    """A side's blocks in order, and the headings of the parts starting at each block index."""
    blocks: list[Block] = []
    starts: dict[int, list[str]] = defaultdict(list)
    for heading, part in parts:
        starts[len(blocks)].append(heading)
        blocks.extend(part)
    return blocks, starts


def _marked_parts(
    parts: Sequence[tuple[str, Sequence[Block]]],
    marks: Sequence[BlockMark] | None,
    gaps: Sequence[tuple[int, int]],
    side: str,
) -> tuple[Part, ...]:
    """Render one side's parts. A differing group's first block (or its gap, when it has
    none on this side) carries the jump target id `d<group>-<side>`; changed blocks show
    their normalised text with the changed words in <mark>, so inline formatting is dropped there."""
    gaps_at: dict[int, list[int]] = defaultdict(list)
    for index, group in gaps:
        gaps_at[index].append(group)
    targeted: set[int] = set()
    index = 0
    out = []
    for heading, blocks in parts:
        html = []
        for block in blocks:
            html.extend(_gap(g, side) for g in gaps_at.pop(index, ()))
            mark = marks[index] if marks else BlockMark(Mark.SAME)
            html.append(_marked_block(block, mark, side, mark.group not in targeted))
            targeted.add(mark.group)
            index += 1
        out.append([heading, html])
    for groups in gaps_at.values():  # groups after the last block
        out[-1][1].extend(_gap(g, side) for g in groups)
    return tuple(Part(heading, Markup("\n").join(html)) for heading, html in out)


def _target_id(group: int, side: str) -> str:
    return f"d{group}-{side}"


def _gap(group: int, side: str) -> Markup:
    return Markup('<span class="diff-gap" id="{}"></span>').format(_target_id(group, side))


def _marked_block(block: Block, mark: BlockMark, side: str, target: bool) -> Markup:
    if mark.state is Mark.SAME:
        return render.block_html(block, remote_images=False)
    id_attr = Markup(' id="{}"').format(_target_id(mark.group, side)) if target else Markup("")
    if mark.state is Mark.ONLY:
        return Markup('<div class="diff diff--only"{}>{}</div>').format(id_attr, render.block_html(block, remote_images=False))
    text = normalised(block)
    inner, at = [], 0
    for span in mark.spans or ():
        inner.append(escape(text[at:span.start]))
        inner.append(Markup("<mark>{}</mark>").format(text[span.start:span.end]))
        at = span.end
    inner.append(escape(text[at:]))
    return Markup('<div class="diff diff--changed"{}><p>{}</p></div>').format(id_attr, Markup("").join(inner))
