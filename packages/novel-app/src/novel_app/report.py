"""Reports as text lines, for the terminal and for job logs."""

from collections.abc import Sequence

from novel_audio.legacy import LegacyReport
from novel_core import CheckReport
from novel_sources.importing import ImportReport
from novel_sources.sync import SyncReport
from novel_translate.phase_a import Estimate, GlossaryReport

from novel_app.notation import ranges

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


def section(name: str, lines: Sequence[str]) -> list[str]:
    if not lines:
        return []
    shown = [f"  {name}: {len(lines)}", *(f"    {line}" for line in lines[:LIST_LIMIT])]
    if len(lines) > LIST_LIMIT:
        shown.append(f"    ... and {len(lines) - LIST_LIMIT} more")
    return shown
