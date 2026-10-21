"""What the web UI shows of a novel, each derived from one NovelView.

`library_row` is the library page's summary, `chapter_grid` the novel page's cells
(one per chapter key, in blocks of 100 numbers) and `comparison` two sources' texts
of one chapter number side by side, with their differences marked.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from markupsafe import Markup, escape
from novel_audio.build import fingerprint as audio_fingerprint
from novel_audio.tts import DEFAULT_VOICE
from novel_core import (
    Block,
    ChapterKey,
    CheckReport,
    ItemStatus,
    KeyRange,
    Kind,
    NovelStore,
    NovelView,
    OutputKind,
    SourceInfo,
    SourceSpec,
)
from novel_core.keys import chapter_heading
from novel_core.selection import Pin
from novel_publish import epub, render
from novel_publish import site as site_builder
from novel_sources.backends import is_web
from novel_translate.setups import BACKEND as SETUP_BACKEND
from novel_translate.setups import TranslatorSetup

from novel_app.diff import BlockMark, Mark, TextDiff, diff_blocks, normalised
from novel_app.jobs import JobRow
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
    job: JobRow | None  # the novel's active job

    @property
    def raw_only(self) -> bool:
        return self.selected == 0 and self.numbers.get(Kind.RAW_ZH, 0) > 0

    @property
    def can_sync(self) -> bool:
        return any(s.to_fetch is not None for s in self.sources)


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


def library_row(slug: str, view: NovelView, jobs: Sequence[JobRow], last_sync: float | None) -> LibraryRow:
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
        OutputKind.SITE: site_builder.fingerprint(),
        OutputKind.EPUB: epub.fingerprint(view.meta, (novel_dir(slug) / cover).read_bytes() if cover else None, epub.VOLUME_SIZE),
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
        job=next((j for j in jobs if j.target == slug and j.state.active), None),
    )


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
class NovelPage:
    row: LibraryRow
    grid: tuple[GridBlock, ...]
    pins: tuple[Pin, ...]  # oldest first; a later pin wins
    check: CheckReport


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
class Comparison:
    number: int
    offers: tuple[SourceInfo, ...]  # sources with a text for the number, best first
    selected: int | None  # the source the book uses
    left: Text | None
    right: Text | None
    diff: TextDiff | None  # None when a side is missing or either side is raw text


def comparison(store: NovelStore, view: NovelView, number: int, left: int | None, right: int | None) -> Comparison:
    """The number's texts from `left` and `right`; left defaults to the selected source, right to the next offer."""
    by_source: dict[int, list] = defaultdict(list)
    for info in view.sources:
        for c in view.chapters(info.id):
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

    return Comparison(number, offers, selected, text(left, "l"), text(right, "r"), diff)


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
