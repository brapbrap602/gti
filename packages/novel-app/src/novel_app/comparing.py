"""A model comparison's bundle: one folder a reviewer reads to judge the setups.

`comparison.json` holds everything: the raw chapters, the reference English and each
setup's attempts. Written from it are `README.md` (the numbers per setup: chapters done,
cost, time, flags, length against the reference) and `chapters/<ref>.md` (for one chapter,
the Chinese, each setup's English paragraph by paragraph, then the reference). The
reviewer's verdict goes in `judgement.md`, next to what it judged. The web UI reads
bundles back with `read_bundle`; nothing else does.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from novel_translate.models import Charged
from novel_translate.phase_b import Attempt, Comparison, ref_of
from novel_translate.setups import TranslatorSetup

DATA = "comparison.json"
JUDGEMENT = "judgement.md"


@dataclass(frozen=True)
class Reference:
    """The English the setups are judged against, for one chapter."""

    source: int
    title: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class RawChapter:
    title: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class SetupRow:
    """One setup's numbers over a comparison."""

    setup: TranslatorSetup
    done: int
    failed: int
    cost: float
    per_chapter: float | None  # cost over chapters done
    seconds: float | None  # per chapter done (a group request's time split over its chapters)
    length: float | None  # its words over the reference's, on chapters with both
    flags: tuple[str, ...]  # soft-flag kinds seen


@dataclass(frozen=True)
class Bundle:
    name: str  # the folder's name: when it ran and on what
    novel: str
    chapters: tuple[str, ...]  # refs, in order
    raws: Mapping[str, RawChapter]
    references: Mapping[str, Reference]
    setups: tuple[TranslatorSetup, ...]
    attempts: Mapping[str, Mapping[str, Attempt]]  # setup url -> ref -> attempt
    judgement: str | None

    @property
    def cost(self) -> float:
        return sum(a.charged.cost for by_ref in self.attempts.values() for a in by_ref.values())

    def rows(self) -> list[SetupRow]:
        return setup_rows(self.setups, self.attempts, self.references)


def new_bundle(root: Path, span: str, now: datetime) -> Path:
    """A folder for a new bundle, named by when it ran and on what; never one that exists."""
    name = f"{now:%Y-%m-%d_%H%M%S}_{span.replace(' ', '')}"
    folder, n = root / name, 2
    while folder.exists():
        folder, n = root / f"{name}-{n}", n + 1
    return folder


def write_bundle(
    folder: Path,
    novel: str,
    setups: Sequence[TranslatorSetup],
    comparison: Comparison,
    references: Mapping[str, Reference],
    estimates: Mapping[str, float],
) -> Path:
    """Write the bundle into `folder` (created); returns the README's path."""
    (folder / "chapters").mkdir(parents=True, exist_ok=True)
    data = {
        "novel": novel,
        "chapters": [ref_of(r.key) for r in comparison.raws],
        "raws": {ref_of(r.key): {"title": r.title, "paragraphs": list(r.paragraphs)} for r in comparison.raws},
        "references": {ref: {"source": r.source, "title": r.title, "paragraphs": list(r.paragraphs)} for ref, r in references.items()},
        "setups": [
            {
                "url": s.url, "model": s.model, "label": s.label, "estimate": estimates.get(s.url, 0.0),
                "attempts": {ref: _attempt_json(a) for ref, a in comparison.attempts.get(s.url, {}).items()},
            }
            for s in setups
        ],
    }  # fmt: skip
    (folder / DATA).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    bundle = read_bundle(folder)
    for ref in bundle.chapters:
        (folder / "chapters" / f"{ref}.md").write_text(_chapter(bundle, ref), encoding="utf-8")
    readme = folder / "README.md"
    readme.write_text(_summary(bundle), encoding="utf-8")
    return readme


def read_bundle(folder: Path) -> Bundle:
    data = json.loads((folder / DATA).read_text(encoding="utf-8"))
    setups = tuple(TranslatorSetup.from_url(s["url"]) for s in data["setups"])
    judgement = folder / JUDGEMENT
    return Bundle(
        folder.name,
        data["novel"],
        tuple(data["chapters"]),
        {ref: RawChapter(r["title"], tuple(r["paragraphs"])) for ref, r in data.get("raws", {}).items()},
        {ref: Reference(r["source"], r["title"], tuple(r["paragraphs"])) for ref, r in data["references"].items()},
        setups,
        {s["url"]: {ref: _attempt(ref, a) for ref, a in s["attempts"].items()} for s in data["setups"]},
        judgement.read_text(encoding="utf-8") if judgement.exists() else None,
    )


def bundles(root: Path) -> list[Bundle]:
    """Every bundle under `root` (one novel's comparisons), newest first."""
    if not root.is_dir():
        return []
    return [read_bundle(d) for d in sorted(root.iterdir(), reverse=True) if (d / DATA).is_file()]


def setup_rows(
    setups: Sequence[TranslatorSetup], attempts: Mapping[str, Mapping[str, Attempt]], references: Mapping[str, Reference]
) -> list[SetupRow]:
    rows = []
    for s in setups:
        mine = list(attempts.get(s.url, {}).values())
        ok = [a for a in mine if a.failure is None]
        cost = sum(a.charged.cost for a in mine)
        pairs = [(words(a.paragraphs), words(references[a.ref].paragraphs)) for a in ok if a.ref in references]
        reference_words = sum(r for _, r in pairs)
        rows.append(SetupRow(
            s, len(ok), len(mine) - len(ok), cost,
            cost / len(ok) if ok else None,
            sum(a.seconds / a.shared for a in ok) / len(ok) if ok else None,
            sum(w for w, _ in pairs) / reference_words if reference_words else None,
            tuple(sorted({f.split(":")[0] for a in ok for f in a.soft_flags})),
        ))  # fmt: skip
    return rows


def setup_name(setup: TranslatorSetup) -> str:
    """The setup's model, and what sets it apart from the others of a comparison."""
    extras = ([f"reasoning {setup.reasoning}"] if setup.reasoning != "off" else []) + (
        [f"{setup.group} per request"] if setup.group > 1 else []
    )
    return setup.model + (f" ({', '.join(extras)})" if extras else "")


def words(paragraphs: Sequence[str]) -> int:
    return sum(len(p.split()) for p in paragraphs)


def _summary(b: Bundle) -> str:
    lines = [
        f"# {b.novel}: model comparison, chapters {', '.join(b.chapters)}",
        "",
        f"Reference: {_reference_note(b.references, b.chapters)}. Total spend ${b.cost:.4f}.",
        "Each chapter's file in `chapters/` has the Chinese, the reference and every setup's English.",
        "The verdict goes in `judgement.md`.",
        "Setups with several chapters per request: a request's cost and time are split evenly over its chapters.",
        "",
        "| setup | done | failed | cost | $/chapter | s/chapter | words vs reference | soft flags |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in b.rows():
        per = f"${r.per_chapter:.4f}" if r.per_chapter is not None else "–"
        seconds = f"{r.seconds:.0f}" if r.seconds is not None else "–"
        length = f"{r.length:.2f}" if r.length is not None else "–"
        lines.append(
            f"| {r.setup.label} | {r.done} | {r.failed} | ${r.cost:.4f} | {per} | {seconds} | {length} | {', '.join(r.flags) or '–'} |"
        )
    failures = [(s, a) for s in b.setups for a in b.attempts.get(s.url, {}).values() if a.failure]
    if failures:
        lines += ["", "## Failures", "", *(f"- {setup_name(s)} {a.ref}: {a.failure}" for s, a in failures)]
    return "\n".join(lines) + "\n"


def _chapter(b: Bundle, ref: str) -> str:
    raw, reference = b.raws[ref], b.references.get(ref)
    attempts = [(s, b.attempts.get(s.url, {}).get(ref)) for s in b.setups]
    out = [f"# {raw.title}", ""]
    if reference is not None:
        out += [f"Reference: source {reference.source}, {reference.title} (check it is this chapter)", ""]
    for s, a in attempts:
        if a is None or a.failure:
            out.append(f"- {setup_name(s)}: {a.failure if a else 'not run'}")
        else:
            shared = f", in a request of {a.shared} chapters" if a.shared > 1 else ""
            out.append(f"- {setup_name(s)}: {a.title} (${a.charged.cost:.4f}, {a.seconds:.0f} s{shared}, {words(a.paragraphs)} words)")
    out.append("")
    for n, zh in enumerate(raw.paragraphs, 1):
        out += [f"## ¶{n}", "", f"**zh** {zh}", ""]
        for s, a in attempts:
            if a is not None and not a.failure and n <= len(a.paragraphs):
                out += [f"**{setup_name(s)}** {a.paragraphs[n - 1]}", ""]
    if reference is not None:
        # The reference's paragraphs need not line up with the Chinese ones, so it is given whole.
        out += ["## Reference", "", *(p + "\n" for p in reference.paragraphs)]
    return "\n".join(out)


def _attempt_json(a: Attempt) -> dict:
    return {
        "title": a.title, "paragraphs": list(a.paragraphs), "failure": a.failure, "soft_flags": list(a.soft_flags),
        "cost": a.charged.cost, "input_tokens": a.charged.input_tokens, "output_tokens": a.charged.output_tokens,
        "requests": a.charged.requests, "generation_ids": list(a.charged.generation_ids), "seconds": round(a.seconds, 2),
        "shared": a.shared,
    }  # fmt: skip


def _attempt(ref: str, a: dict) -> Attempt:
    charged = Charged(a["cost"], a["input_tokens"], a["output_tokens"], tuple(a["generation_ids"]), a["requests"])
    return Attempt(
        ref, a["title"], tuple(a["paragraphs"]), a["failure"], tuple(a["soft_flags"]), charged, a["seconds"], a.get("shared", 1)
    )


def _reference_note(references: Mapping[str, Reference], refs: Sequence[str]) -> str:
    sources = sorted({r.source for r in references.values()})
    missing = [ref for ref in refs if ref not in references]
    note = f"source {', '.join(map(str, sources))}" if sources else "none"
    return note + (f" (none for {', '.join(missing)})" if missing and sources else "")


# -- the web UI's views over all of a novel's bundles ------------------------------


@dataclass(frozen=True)
class Column:
    """One setup of one comparison run, as a column of the comparison screens."""

    run: str  # the bundle's name
    setup: TranslatorSetup
    attempt: Attempt | None = None  # on a chapter screen: its attempt at that chapter

    @property
    def key(self) -> str:
        return f"{self.run}|{self.setup.url}"

    @property
    def when(self) -> str:
        """The run's date and time, from its name (2026-10-20_222641_...)."""
        day, time = self.run.split("_")[:2]
        return f"{day} {time[:2]}:{time[2:4]}"


@dataclass(frozen=True)
class ChapterScreen:
    ref: str
    raw: RawChapter
    reference: Reference | None
    columns: tuple[Column, ...]  # every run's every setup that has this chapter, newest run first
    chapters: tuple[str, ...]  # every chapter any run compared, in order, for moving between them


def columns(runs: Sequence[Bundle]) -> list[Column]:
    return [Column(b.name, s) for b in runs for s in b.setups]


def all_chapters(runs: Sequence[Bundle]) -> tuple[str, ...]:
    refs = {ref for b in runs for ref in b.chapters}
    return tuple(sorted(refs, key=lambda ref: tuple(int(n) for n in ref[1:].split("p"))))


def chapter_screen(runs: Sequence[Bundle], ref: str) -> ChapterScreen | None:
    """Everything compared on one chapter, from every run; None if no run has it."""
    having = [b for b in runs if ref in b.raws]
    if not having:
        return None
    reference = next((b.references[ref] for b in having if ref in b.references), None)
    cols = tuple(Column(b.name, s, b.attempts.get(s.url, {}).get(ref)) for b in having for s in b.setups)
    return ChapterScreen(ref, having[0].raws[ref], reference, cols, all_chapters(runs))
