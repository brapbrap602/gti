"""Reports as text lines, for the terminal and for job logs."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from novel_audio.legacy import LegacyReport
from novel_core import CheckReport
from novel_sources.importing import ImportReport
from novel_sources.sync import SyncReport
from novel_translate.phase_a import Estimate, GlossaryReport
from novel_translate.phase_b import Estimate as TranslateEstimate
from novel_translate.phase_b import StaleReport, TranslateReport

from novel_app.notation import ranges

if TYPE_CHECKING:  # service imports this module
    from novel_app.service import CompareEstimate

LIST_LIMIT = 10


def import_lines(slug: str, r: ImportReport) -> list[str]:
    lines = [
        f"{'created' if r.created else 'updated'} {slug} ({r.novel_dir}), source {r.source_id}",
        f"  index: {len(r.index.added)} new, {len(r.index.vanished)} vanished, {len(r.index.revived)} revived",
        f"  texts: {r.inserted} stored, {r.unchanged} unchanged, {len(r.unavailable)} unavailable",
        *section("failed", failed_lines(r.failed)),
    ]
    return lines + [f"  note: {note}" for note in r.notes]


def sync_lines(r: SyncReport) -> list[str]:
    return [
        f"  index: {len(r.index.added)} new, {len(r.index.vanished)} vanished; "
        f"fetched {r.wanted}: {r.inserted} stored, {r.unchanged} unchanged, {len(r.unavailable)} locked",
        *section("failed", failed_lines(r.failed)),
    ]


def failed_lines(failed: Sequence[tuple[str, str]]) -> list[str]:
    return [f"{ref}: {reason}" for ref, reason in failed]


def legacy_lines(r: LegacyReport) -> list[str]:
    return [
        f"  registered: {len(r.registered)} ({len(r.unverified)} too short or without sentence files to check)",
        *numbers("partial (no combined mp3)", r.partial),
        *numbers("already built", r.already_built),
        *section("unmapped", [f"folder {n}: {why}" for n, why in r.unmapped]),
        *section("mismatched", [f"folder {m.folder}: not {m.key}; best match is {m.best}" for m in r.mismatched]),
    ]


def check_lines(r: CheckReport) -> list[str]:
    return [
        *numbers("gaps", r.gaps),
        *numbers("raw only", r.raw_only),
        *section("duplicates", [f"source {d.source_id} key {d.key}: {', '.join(d.item_refs)}" for d in r.duplicates]),
        *section("unmapped", [f"source {n.source_id} {n.item_ref} {n.title!r}" for n in r.unmapped]),
        *section("vanished", [f"source {n.source_id} {n.item_ref}" for n in r.vanished]),
        *section("failed", [f"source {n.source_id} {n.item_ref}: {n.detail}" for n in r.failed]),
        *section("title mismatches", [f"{n.title!r} (title says {n.detail})" for n in r.title_mismatches]),
        *numbers("mixed parts", r.mixed_parts),
        *section("pin fallbacks", [f"{p.number}: pinned source {p.pinned_source} has nothing" for p in r.pin_fallbacks]),
        *section("legacy moved", [f"{o.kind} {o.built_key}: {o.item_ref}" for o in r.legacy_moved]),
        *section("legacy unselected", [f"{o.kind} {o.built_key}: {o.item_ref}" for o in r.legacy_unselected]),
    ]


def numbers(name: str, values: Sequence[int]) -> list[str]:
    return [f"  {name}: {len(values)} ({ranges(values)})"] if values else []


def glossary_lines(r: GlossaryReport) -> list[str]:
    decided = ", ".join(f"{n} {status}" for status, n in sorted(r.decided.items())) or "none"
    lines = [
        f"  discovered {r.candidates} new strings; classified {r.classified}; "
        f"official English consulted in {r.hinted} chapters; {r.summarized} chapters summarized",
        f"  decided: {decided}",
        f"  {r.calls} calls, ${r.cost:.4f}",
        *section("failed", r.failed),
    ]
    if r.stopped:
        lines.append(f"  stopped: {r.stopped}; run it again (with a higher --cap) to continue")
    return lines


def estimate_lines(e: Estimate) -> list[str]:
    calls = ", ".join(f"{n} {step}" for step, n in e.calls.items())
    bound = "at most " if e.upper_bound else "about "
    return [f"  {e.chapters} chapters; {e.total_calls} calls ({calls}); {bound}${e.usd:.4f}"]


def translate_lines(r: TranslateReport) -> list[str]:
    flags = ", ".join(f"{n} {flag}" for flag, n in sorted(r.soft_flags.items()))
    lines = [
        f"  translated {len(r.translated)}; {r.skipped} already current; "
        f"{len(r.blocked)} blocked; {len(r.failed)} failed",
        f"  {r.calls} calls, ${r.cost:.4f}" + (f"; stored with flags: {flags}" if flags else ""),
        *section("blocked (review these terms on the glossary page)", r.blocked),
        *section("failed", r.failed),
    ]
    if r.orphans:
        lines.append(f"  orphans (their raw chapter is gone; `nov translate prune` drops them): {', '.join(r.orphans)}")
    if r.stopped:
        lines.append(f"  stopped: {r.stopped}; run it again (with a higher --cap) to continue")
    return lines


def translate_estimate_lines(e: TranslateEstimate) -> list[str]:
    return [
        f"  {e.chapters} chapters to translate ({e.current} already current, {e.blocked} blocked by terms to review); "
        f"at most ${e.usd:.4f}"
    ]


def compare_estimate_lines(e: "CompareEstimate") -> list[str]:
    missing = [ref for ref in e.chapters if ref not in e.references]
    lines = [f"  {len(e.chapters)} chapters ({', '.join(e.chapters)}); reference English for {len(e.references)}"]
    if missing:
        lines.append(f"  no reference for {', '.join(missing)}")
    lines += [f"  {s.label}: at most ${e.usd[s.url]:.4f}" for s in e.setups]
    lines.append(f"  in all at most ${e.total:.4f}")
    return lines


def stale_lines(r: StaleReport) -> list[str]:
    def listed(refs: Sequence[str]) -> str:
        more = " …" if len(refs) > LIST_LIMIT else ""
        return f" ({', '.join(refs[:LIST_LIMIT])}{more})" if refs else ""

    return [f"  stale: {len(r.stale)}{listed(r.stale)}", f"  orphans: {len(r.orphans)}{listed(r.orphans)}"]


def section(name: str, lines: Sequence[str]) -> list[str]:
    if not lines:
        return []
    shown = [f"  {name}: {len(lines)}", *(f"    {line}" for line in lines[:LIST_LIMIT])]
    if len(lines) > LIST_LIMIT:
        shown.append(f"    ... and {len(lines) - LIST_LIMIT} more")
    return shown
