"""Reports as text lines, for the terminal and for job logs."""

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from novel_audio.legacy import LegacyReport
from novel_sources.importing import ImportReport
from novel_sources.reclean import RecleanReport
from novel_sources.sync import SyncReport
from novel_sources.zh_inspect import Inspection, Reference
from novel_translate.phase_a import Estimate, GlossaryReport
from novel_translate.phase_b import Estimate as TranslateEstimate
from novel_translate.phase_b import StaleReport, TranslateReport

from novel_app.notation import ranges
from novel_app.pages import NovelCheck, align_range_command

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


def sync_lines(r: SyncReport, other_raws: bool = False) -> list[str]:
    """`other_raws`: the novel has another raw-zh source, which can supply the numbers held here."""
    lines = [
        f"  index: {len(r.index.added)} new, {len(r.index.vanished)} vanished; "
        f"fetched {r.wanted}: {r.inserted} stored, {r.unchanged} unchanged, {len(r.unavailable)} locked",
        *section("failed", failed_lines(r.failed)),
    ]
    if r.held or r.refetched:
        checks = Counter(check for _, detail in r.held for check in _checks(detail))
        line = f"  held: {len(r.held)}" + (f" ({', '.join(f'{c} {n}' for c, n in checks.items())})" if checks else "")
        if r.refetched:
            line += f"; refetched held: {r.refetched}, now clean {r.cleared}"
        lines += [line, *listed(failed_lines(r.held))]
        if r.held and other_raws:
            lines.append("  another source picks up held numbers on its next sync")
    if r.decoy_site:
        lines.append("  decoy site: index only")
    return lines


def reclean_lines(r: RecleanReport) -> list[str]:
    hits = ", ".join(f"{rule} {n}" for rule, n in r.hits.items()) or "none"
    return [
        f"  rechecked {r.chapters}: {r.rewritten} rewritten, {r.unchanged} unchanged",
        f"  cleaner hits: {hits}",
        f"  held: {len(r.held)} newly, {len(r.cleared)} no longer",
        *listed(failed_lines(r.held)),
    ]


_SHOWN = 60  # chars of a paragraph shown in inspect lines


def inspect_lines(slug: str, found: Sequence[Inspection]) -> list[str]:
    lines = []
    for i in found:
        c = i.chapter
        state = "checked" if i.checked else "not checked with current rules"
        lines.append(f"{slug}: source {c.source_id} {c.item_ref}, chapter {c.key} {c.title}: {state}")
        lines += [f"  finding {f.check}: {f.detail} ({'held' if f in i.held else 'released'})" for f in c.findings]
        if (p := i.poison) is not None and (m := i.markers) is not None:
            if p.counts:
                lines.append(
                    f"  poison: {_counts(p.counts)} = {p.hits} hits, {p.density:.1f} per 1000 of {p.cjk} CJK chars"
                    f" (flags at {m.density}, {m.distinct} markers, {m.hits} hits)"
                )
            else:
                lines.append(f"  poison: no markers in {p.cjk} CJK chars")
        if (n := i.names) is not None:
            lines.append(f"  names: {_counts(n.opening)} in the opening, {_counts(n.rest)} in the {n.rest_cjk} CJK chars after it")
        hits = [f"{h.rule} ×{k}: {_short(h.before)} → {'(dropped)' if h.after is None else _short(h.after)}" for h, k in i.hits]
        lines += _listing("cleaner hits", hits)
        lines += _listing("suspicious", [f"{s.label}: {_short(s.text)}" for s in i.suspects])
        if (r := i.reference) is not None:
            lines += _reference_lines(r)
    return lines


def _reference_lines(r: Reference) -> list[str]:
    if r.chapter is None:
        return [f"  against source {r.source_id}: no single chapter named {r.name or '(no name)'}"]
    head = f"  against source {r.source_id} {r.chapter.item_ref}, chapter {r.chapter.key} {r.chapter.title}:"
    if not r.spans:
        return [f"{head} same text"]
    return [head, *listed([f"{_short(s.ours) or '(nothing)'} ↔ {_short(s.theirs) or '(nothing)'} ×{s.count}" for s in r.spans])]


def _listing(name: str, lines: Sequence[str]) -> list[str]:
    return [f"  {name}:", *listed(lines)] if lines else [f"  {name}: none"]


def _counts(counts: Sequence[tuple[str, int]]) -> str:
    return " ".join(f"{word}×{n}" for word, n in counts) or "none"


def _short(text: str) -> str:
    return text if len(text) <= _SHOWN else text[: _SHOWN - 1] + "…"


def now_stale_line(setup: int, label: str, refs: Sequence[str]) -> str:
    shown = f" ({', '.join(refs[:LIST_LIMIT])}{' …' if len(refs) > LIST_LIMIT else ''})" if refs else ""
    return f"  setup {setup} {label}: {len(refs)} translation{'' if len(refs) == 1 else 's'} now stale{shown}"


def unchecked_lines(count: int, slug: str) -> list[str]:
    return [f"  {count} chapters not checked with current rules: run nov reclean {slug}"] if count else []


def _checks(detail: str) -> list[str]:
    """The check names in a held item's detail ("check: detail; check: detail")."""
    return [part.split(":", 1)[0] for part in detail.split("; ")]


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


def check_lines(slug: str, c: NovelCheck) -> list[str]:
    r = c.report
    return [
        *numbers("gaps", r.gaps),
        *numbers("raw only", r.raw_only),
        *section("duplicates", [f"source {d.source_id} key {d.key}: {', '.join(d.item_refs)}" for d in r.duplicates]),
        *section("unmapped", [f"source {n.source_id} {n.item_ref} {n.title!r}" for n in r.unmapped]),
        *section("vanished", [f"source {n.source_id} {n.item_ref}" for n in r.vanished]),
        *section("failed", [f"source {n.source_id} {n.item_ref}: {n.detail}" for n in r.failed]),
        *section("held", [f"source {n.source_id} {n.item_ref}: {n.detail}" for n in r.held]),
        *numbering_lines(slug, c),
        *section("title mismatches", [f"{n.title!r} (title says {n.detail})" for n in r.title_mismatches]),
        *numbers("mixed parts", r.mixed_parts),
        *section("pin fallbacks", [f"{p.number}: pinned source {p.pinned_source} has nothing" for p in r.pin_fallbacks]),
        *section("legacy moved", [f"{o.kind} {o.built_key}: {o.item_ref}" for o in r.legacy_moved]),
        *section("legacy unselected", [f"{o.kind} {o.built_key}: {o.item_ref}" for o in r.legacy_unselected]),
        *unchecked_lines(c.unchecked, slug),
    ]


def numbering_lines(slug: str, c: NovelCheck) -> list[str]:
    if not c.numbering:
        return []
    return [
        f"  numbering: {len(c.numbering)} (against source {c.anchor})",
        *listed([
            f"source {n.source_id} printed {n.printed_start}-{n.printed_end} are chapters "
            f"{n.printed_start + n.offset}-{n.printed_end + n.offset} (offset {n.offset:+d}, {n.matched} titles match): "
            f"{align_range_command(slug, n)}"
            for n in c.numbering
        ]),
    ]  # fmt: skip


def numbers(name: str, values: Sequence[int]) -> list[str]:
    return [f"  {name}: {len(values)} ({ranges(values)})"] if values else []


def glossary_lines(r: GlossaryReport, slug: str) -> list[str]:
    decided = ", ".join(f"{n} {status}" for status, n in sorted(r.decided.items())) or "none"
    lines = [
        f"  discovered {r.candidates} new strings; classified {r.classified}; "
        f"official English consulted in {r.hinted} chapters; {r.summarized} chapters summarized",
        f"  decided: {decided}",
        f"  {r.calls} calls, ${r.cost:.4f}",
        *section("failed", r.failed),
        *unchecked_lines(r.unchecked, slug),
    ]
    if r.stopped:
        lines.append(f"  stopped: {r.stopped}; run it again (with a higher --cap) to continue")
    return lines


def estimate_lines(e: Estimate, slug: str) -> list[str]:
    calls = ", ".join(f"{n} {step}" for step, n in e.calls.items())
    bound = "at most " if e.upper_bound else "about "
    return [
        f"  {e.chapters} chapters; {e.total_calls} calls ({calls}); {bound}${e.usd:.4f}",
        *unchecked_lines(e.unchecked, slug),
    ]


def translate_lines(r: TranslateReport, slug: str) -> list[str]:
    flags = ", ".join(f"{n} {flag}" for flag, n in sorted(r.soft_flags.items()))
    lines = [
        f"  translated {len(r.translated)}; {r.skipped} already current; "
        f"{len(r.blocked)} blocked; {len(r.failed)} failed",
        f"  {r.calls} calls, ${r.cost:.4f}" + (f"; stored with flags: {flags}" if flags else ""),
        *section("blocked (review these terms on the glossary page)", r.blocked),
        *section("failed", r.failed),
        *unchecked_lines(len(r.unchecked), slug),
        *section("waiting (sequential: the chapter before is not checked)", r.waiting),
    ]
    if r.orphans:
        lines.append(f"  orphans (their raw chapter is gone; `nov translate prune` drops them): {', '.join(r.orphans)}")
    if r.stopped:
        lines.append(f"  stopped: {r.stopped}; run it again (with a higher --cap) to continue")
    return lines


def translate_estimate_lines(e: TranslateEstimate, slug: str) -> list[str]:
    unchecked = f", {e.unchecked} not checked with current rules: run nov reclean {slug}" if e.unchecked else ""
    return [
        f"  {e.chapters} chapters to translate ({e.current} already current, {e.blocked} blocked by terms to review"
        f"{unchecked}); at most ${e.usd:.4f}"
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

    lines = [f"  stale: {len(r.stale)}{listed(r.stale)}", f"  orphans: {len(r.orphans)}{listed(r.orphans)}"]
    if r.held:
        lines.append(f"  held (every raw copy is held; kept, not published): {len(r.held)}{listed(r.held)}")
    return lines


def section(name: str, lines: Sequence[str]) -> list[str]:
    if not lines:
        return []
    return [f"  {name}: {len(lines)}", *listed(lines)]


def listed(lines: Sequence[str]) -> list[str]:
    """The lines indented under a heading, the first LIST_LIMIT of them."""
    shown = [f"    {line}" for line in lines[:LIST_LIMIT]]
    if len(lines) > LIST_LIMIT:
        shown.append(f"    ... and {len(lines) - LIST_LIMIT} more")
    return shown
