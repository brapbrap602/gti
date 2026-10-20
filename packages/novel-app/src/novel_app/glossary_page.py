"""What the glossary page shows: one novel's terms under a tab, with their evidence."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from markupsafe import Markup, escape
from novel_translate.glossary import Candidate, Category, Status, Term, normalize
from novel_translate.tstore import TranslateStore

from novel_app.jobs import JobRow

# (tab, label, statuses it lists); the first is the default.
TABS: tuple[tuple[str, str, tuple[Status, ...]], ...] = (
    ("review", "Needs review", (Status.NEEDS_REVIEW,)),
    ("all", "All", tuple(Status)),
    ("proposed", "Proposed", (Status.PROPOSED,)),
    ("locked", "Locked", (Status.LOCKED,)),
    ("rejected", "Rejected", (Status.REJECTED,)),
)
ROW_LIMIT = 200  # a long novel has thousands of rejected strings; search narrows the list


@dataclass(frozen=True)
class TermRow:
    term: Term
    candidates: tuple[Candidate, ...]  # most voted first
    snippets: tuple[Markup, ...]  # with the term marked

    @property
    def top_llm(self) -> str | None:
        return next((c.en for c in self.candidates if c.origin == "llm"), None)


@dataclass(frozen=True)
class GlossaryPage:
    slug: str
    title: str
    tab: str
    search: str
    category: Category | None
    counts: Mapping[Status, int]
    rows: tuple[TermRow, ...]
    matching: int  # terms under this tab and filter; rows holds at most ROW_LIMIT of them
    revision: int
    build_blocked: str | None  # why Build cannot start (no raws, no key)
    job: JobRow | None  # the novel's active job

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def tab_count(self, tab: str) -> int:
        return sum(self.counts.get(s, 0) for t, _label, statuses in TABS if t == tab for s in statuses)

    @property
    def building(self) -> bool:
        return self.job is not None and self.job.kind == "glossary-build"


def glossary_page(
    slug: str,
    title: str,
    ts: TranslateStore,
    tab: str,
    search: str,
    category: Category | None,
    build_blocked: str | None,
    job: JobRow | None,
) -> GlossaryPage:
    statuses = next((s for t, _label, s in TABS if t == tab), None)
    if statuses is None:
        tab, statuses = TABS[0][0], TABS[0][2]
    terms = [t for t in ts.entries(category=category, search=search or None) if t.status in statuses]
    shown = terms[:ROW_LIMIT]
    evidence = ts.evidence([t.id for t in shown])
    rows = tuple(
        TermRow(t, evidence[t.id][0], tuple(_marked(s, (t.zh, *t.aliases)) for s in evidence[t.id][1])) for t in shown
    )
    return GlossaryPage(
        slug, title, tab, search, category, ts.counts(), rows, len(terms), ts.revision, build_blocked, job
    )  # fmt: skip


def term_row(ts: TranslateStore, term_id: int) -> TermRow | None:
    term = next((t for t in ts.entries() if t.id == term_id), None)
    if term is None:
        return None
    candidates, snippets = ts.evidence([term_id])[term_id]
    return TermRow(term, candidates, tuple(_marked(s, (term.zh, *term.aliases)) for s in snippets))


def _marked(snippet: str, keys: Sequence[str]) -> Markup:
    """The snippet, escaped, with every key in <mark>."""
    keys = sorted({normalize(k) for k in keys if k}, key=len, reverse=True)
    if not keys:
        return escape(snippet)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    out, last = Markup(), 0
    for m in pattern.finditer(snippet):
        out += escape(snippet[last : m.start()]) + Markup("<mark>") + escape(m.group()) + Markup("</mark>")
        last = m.end()
    return out + escape(snippet[last:])
