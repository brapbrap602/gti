"""`nov`: the command line. Each command is a thin wrapper over the packages below it."""

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated

import typer
from novel_core import CheckReport, NovelStore
from novel_sources.importing import ImportReport, import_novel
from novel_sources.wns import WnsImporter

from novel_app.library import novel_dir, slugify

app = typer.Typer(no_args_is_help=True, help="Novel library: import, check, build.")
import_app = typer.Typer(no_args_is_help=True, help="One-shot imports of legacy local stores.")
app.add_typer(import_app, name="import")

LIST_LIMIT = 10


@import_app.command("wns")
def import_wns(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="web-novel-scraper novel folder")],
    novel: Annotated[str | None, typer.Option(help="novel slug; defaults to the slug of the stored title")] = None,
) -> None:
    """Import a web-novel-scraper novel folder (main.json + saved pages)."""
    importer = WnsImporter(folder)
    slug = novel or slugify(importer.read_index().meta.title)
    report = import_novel(novel_dir(slug), importer)
    _print_import(slug, report)
    if report.failed:
        raise typer.Exit(1)


@app.command()
def check(novel: Annotated[str, typer.Argument(help="novel slug")]) -> None:
    """Report gaps, duplicates, unmapped chapters and other problems."""
    folder = novel_dir(novel)
    if not folder.exists():
        typer.echo(f"no novel {novel!r} in {folder.parent}", err=True)
        raise typer.Exit(2)
    with NovelStore.open(folder) as store:
        report = store.check()
        selected = len(store.selection())
    typer.echo(f"{novel}: {selected} chapters selected")
    _print_check(report)


def _print_import(slug: str, r: ImportReport) -> None:
    typer.echo(f"{'created' if r.created else 'updated'} {slug} ({r.novel_dir}), source {r.source_id}")
    typer.echo(
        f"  index: {len(r.index.added)} new, {len(r.index.vanished)} vanished, {len(r.index.revived)} revived"
    )
    typer.echo(f"  texts: {r.inserted} stored, {r.unchanged} unchanged, {len(r.unavailable)} unavailable")
    _section("failed", [f"{ref}: {reason}" for ref, reason in r.failed])
    for note in r.notes:
        typer.echo(f"  note: {note}")


def _print_check(r: CheckReport) -> None:
    _numbers("gaps", r.gaps)
    _numbers("raw only", r.raw_only)
    _section("duplicates", [f"source {d.source_id} key {d.key}: {', '.join(d.item_refs)}" for d in r.duplicates])
    _section("unmapped", [f"source {n.source_id} {n.item_ref} {n.title!r}" for n in r.unmapped])
    _section("vanished", [f"source {n.source_id} {n.item_ref}" for n in r.vanished])
    _section("failed", [f"source {n.source_id} {n.item_ref}: {n.detail}" for n in r.failed])
    _section("title mismatches", [f"{n.title!r} (title says {n.detail})" for n in r.title_mismatches])
    _numbers("mixed parts", r.mixed_parts)
    _section("pin fallbacks", [f"{p.number}: pinned source {p.pinned_source} has nothing" for p in r.pin_fallbacks])
    _section("legacy moved", [f"{o.kind} {o.built_key}: {o.item_ref}" for o in r.legacy_moved])
    _section("legacy unselected", [f"{o.kind} {o.built_key}: {o.item_ref}" for o in r.legacy_unselected])


def _numbers(name: str, numbers: Sequence[int]) -> None:
    if numbers:
        typer.echo(f"  {name}: {len(numbers)} ({_ranges(numbers)})")


def _section(name: str, lines: Sequence[str]) -> None:
    if not lines:
        return
    typer.echo(f"  {name}: {len(lines)}")
    for line in lines[:LIST_LIMIT]:
        typer.echo(f"    {line}")
    if len(lines) > LIST_LIMIT:
        typer.echo(f"    ... and {len(lines) - LIST_LIMIT} more")


def _ranges(numbers: Iterable[int]) -> str:
    """[1, 2, 3, 7, 9, 10] -> '1-3, 7, 9-10'."""
    spans: list[list[int]] = []
    for n in sorted(numbers):
        if spans and n == spans[-1][1] + 1:
            spans[-1][1] = n
        else:
            spans.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)
