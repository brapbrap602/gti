"""A model comparison's bundle: one folder a reviewer reads to judge the setups.

`README.md` has the numbers per setup (chapters done, cost, time, flags, length
against the reference); `chapters/<ref>.md` has, for one chapter, the Chinese, the
reference English and each setup's English, paragraph by paragraph; `comparison.json`
has the same data for tools. The reviewer's verdict goes in `judgement.md`, next to
what it judged. Bundles are never read back by the app.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from novel_translate.phase_b import Attempt, Comparison, ref_of
from novel_translate.setups import TranslatorSetup


@dataclass(frozen=True)
class Reference:
    """The English the setups are judged against, for one chapter."""

    source: int
    title: str
    paragraphs: tuple[str, ...]


def bundle_name(span: str, now: datetime) -> str:
    return f"{now:%Y-%m-%d_%H%M%S}_{span.replace(' ', '')}"


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
    refs = [ref_of(r.key) for r in comparison.raws]
    for raw in comparison.raws:
        ref = ref_of(raw.key)
        attempts = [(s, comparison.attempts.get(s.url, {}).get(ref)) for s in setups]
        (folder / "chapters" / f"{ref}.md").write_text(_chapter(raw.title, raw.paragraphs, references.get(ref), attempts), encoding="utf-8")
    data = {
        "novel": novel,
        "chapters": refs,
        "references": {ref: {"source": r.source, "title": r.title, "paragraphs": list(r.paragraphs)} for ref, r in references.items()},
        "setups": [
            {
                "url": s.url, "model": s.model, "label": s.label, "estimate": estimates.get(s.url, 0.0),
                "attempts": {ref: _attempt_json(a) for ref, a in comparison.attempts.get(s.url, {}).items()},
            }
            for s in setups
        ],
    }  # fmt: skip
    (folder / "comparison.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    readme = folder / "README.md"
    readme.write_text(_summary(novel, refs, setups, comparison, references), encoding="utf-8")
    return readme


def _summary(
    novel: str, refs: Sequence[str], setups: Sequence[TranslatorSetup], comparison: Comparison, references: Mapping[str, Reference]
) -> str:
    lines = [
        f"# {novel}: model comparison, chapters {', '.join(refs)}",
        "",
        f"Reference: {_reference_note(references, refs)}. Total spend ${comparison.cost:.4f}.",
        "Each chapter's file in `chapters/` has the Chinese, the reference and every setup's English.",
        "The verdict goes in `judgement.md`.",
        "Setups with several chapters per request: a request's cost and time are split evenly over its chapters.",
        "",
        "| setup | done | failed | cost | $/chapter | s/chapter | words vs reference | soft flags |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in setups:
        attempts = list(comparison.attempts.get(s.url, {}).values())
        ok = [a for a in attempts if a.failure is None]
        cost = sum(a.charged.cost for a in attempts)
        per = f"${cost / len(ok):.4f}" if ok else "–"
        seconds = f"{sum(a.seconds / a.shared for a in ok) / len(ok):.0f}" if ok else "–"
        flags = sorted({f.split(":")[0] for a in ok for f in a.soft_flags})
        lines.append(
            f"| {s.label} | {len(ok)} | {len(attempts) - len(ok)} | ${cost:.4f} | {per} | {seconds} | "
            f"{_length_ratio(ok, references)} | {', '.join(flags) or '–'} |"
        )
    failures = [(s, a) for s in setups for a in comparison.attempts.get(s.url, {}).values() if a.failure]
    if failures:
        lines += ["", "## Failures", "", *(f"- {_name(s)} {a.ref}: {a.failure}" for s, a in failures)]
    return "\n".join(lines) + "\n"


def _chapter(
    title: str,
    raw: Sequence[str],
    reference: Reference | None,
    attempts: Sequence[tuple[TranslatorSetup, Attempt | None]],
) -> str:
    out = [f"# {title}", ""]
    if reference is not None:
        out += [f"Reference: source {reference.source}, {reference.title} (check it is this chapter)", ""]
    for s, a in attempts:
        if a is None or a.failure:
            out.append(f"- {_name(s)}: {a.failure if a else 'not run'}")
        else:
            shared = f", in a request of {a.shared} chapters" if a.shared > 1 else ""
            out.append(f"- {_name(s)}: {a.title} (${a.charged.cost:.4f}, {a.seconds:.0f} s{shared}, {_words(a.paragraphs)} words)")
    out.append("")
    for n, zh in enumerate(raw, 1):
        out += [f"## ¶{n}", "", f"**zh** {zh}", ""]
        for s, a in attempts:
            if a is not None and not a.failure and n <= len(a.paragraphs):
                out += [f"**{_name(s)}** {a.paragraphs[n - 1]}", ""]
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


def _length_ratio(ok: Sequence[Attempt], references: Mapping[str, Reference]) -> str:
    pairs = [(_words(a.paragraphs), _words(references[a.ref].paragraphs)) for a in ok if a.ref in references]
    reference_words = sum(r for _, r in pairs)
    return f"{sum(w for w, _ in pairs) / reference_words:.2f}" if reference_words else "–"


def _reference_note(references: Mapping[str, Reference], refs: Sequence[str]) -> str:
    sources = sorted({r.source for r in references.values()})
    missing = [ref for ref in refs if ref not in references]
    note = f"source {', '.join(map(str, sources))}" if sources else "none"
    return note + (f" (none for {', '.join(missing)})" if missing and sources else "")


def _name(setup: TranslatorSetup) -> str:
    """The setup's model, and what sets it apart from the others of a comparison."""
    extras = ([f"reasoning {setup.reasoning}"] if setup.reasoning != "off" else []) + (
        [f"{setup.group} per request"] if setup.group > 1 else []
    )
    return setup.model + (f" ({', '.join(extras)})" if extras else "")


def _words(paragraphs: Sequence[str]) -> int:
    return sum(len(p.split()) for p in paragraphs)
