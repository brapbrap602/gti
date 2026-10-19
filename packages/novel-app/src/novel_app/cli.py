"""`nov`: the command line. Each command is a thin wrapper over the packages below it."""

import re
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer
from novel_core import AlignmentRules, ChapterKey, CheckReport, NovelStore
from novel_publish.site import build_site
from novel_sources.importing import ImportReport, import_novel
from novel_sources.wns import WnsImporter

from novel_app import deploy
from novel_app.library import novel_dir, novel_slugs, site_dir, slugify

app = typer.Typer(no_args_is_help=True, help="Novel library: import, check, build.")
import_app = typer.Typer(no_args_is_help=True, help="One-shot imports of legacy local stores.")
app.add_typer(import_app, name="import")
build_app = typer.Typer(no_args_is_help=True, help="Build outputs from the selected chapters.")
app.add_typer(build_app, name="build")
deploy_app = typer.Typer(no_args_is_help=True, help="Publish built outputs.")
app.add_typer(deploy_app, name="deploy")
align_app = typer.Typer(no_args_is_help=True, help="Fix how a source's items map to chapter keys.")
app.add_typer(align_app, name="align")

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
    with _open(novel) as store:
        report = store.check()
        selected = len(store.selection())
    typer.echo(f"{novel}: {selected} chapters selected")
    _print_check(report)


Novel = Annotated[str, typer.Argument(help="novel slug")]
Refs = Annotated[list[str], typer.Argument(help="item refs, as `nov check` prints them")]
SourceOpt = Annotated[int | None, typer.Option(help="source id; needed when the novel has several")]


@align_app.command("item")
def align_item(
    novel: Novel,
    ref: Annotated[str, typer.Argument(help="item ref, as `nov check` prints it")],
    key: Annotated[str, typer.Argument(help="chapter key: 1277, or 524pt1 for a part")],
    source: SourceOpt = None,
) -> None:
    """Give one item an explicit chapter key (overrides offsets and ranges)."""
    chapter = _parse_key(key)
    _edit_alignment(novel, source, [ref], lambda r: replace(r, items={**r.items, ref: chapter}))


@align_app.command("skip")
def align_skip(novel: Novel, refs: Refs, source: SourceOpt = None) -> None:
    """Leave items out of the book (reposts, notices): no key, not unmapped, not a duplicate."""
    _edit_alignment(novel, source, refs, lambda r: replace(r, skip=r.skip | set(refs)))


def _edit_alignment(
    novel: str, source: int | None, refs: Sequence[str], edit: Callable[[AlignmentRules], AlignmentRules]
) -> None:
    with _open(novel) as store:
        sources = {s.id: s for s in store.sources()}
        if source is None and len(sources) == 1:
            source = next(iter(sources))
        if source not in sources:
            typer.echo(f"pass --source, one of {sorted(sources)}", err=True)
            raise typer.Exit(2)
        known = store.item_refs(source)
        if unknown := [r for r in refs if r not in known]:
            typer.echo(f"source {source} has no item {unknown[0]!r}", err=True)
            raise typer.Exit(2)
        diff = store.set_alignment(source, edit(sources[source].alignment))
    for m in diff.moved:
        typer.echo(f"  {m.item_ref}: {m.old or 'none'} -> {m.new or 'none'}")
    typer.echo(f"{len(diff.moved)} items moved")


def _parse_key(text: str) -> ChapterKey:
    m = re.fullmatch(r"\s*(\d+)\s*(?:pt\s*(\d+))?\s*", text, re.IGNORECASE)
    if m is None:
        raise typer.BadParameter(f"{text!r} is not a chapter key like 1277 or 524pt1")
    return ChapterKey(int(m.group(1)), int(m.group(2) or 0))


def _open(novel: str) -> NovelStore:
    folder = novel_dir(novel)
    if not folder.exists():
        typer.echo(f"no novel {novel!r} in {folder.parent}", err=True)
        raise typer.Exit(2)
    return NovelStore.open(folder)


@build_app.command("site")
def build_site_cmd(
    out: Annotated[Path | None, typer.Option(help="site folder; defaults to <data dir>/_site")] = None,
    force: Annotated[bool, typer.Option(help="rebuild every page, not only stale ones")] = False,
) -> None:
    """Build the static site for every novel in the data dir (incremental)."""
    out = out or site_dir()
    with ExitStack() as stack:
        stores = {slug: stack.enter_context(NovelStore.open(novel_dir(slug))) for slug in novel_slugs()}
        report = build_site(stores, out, force=force)
    for n in report.novels:
        state = "raw only" if n.raw_only else f"{n.chapters} chapters"
        typer.echo(f"{n.slug}: {state}, {n.pages_written} pages written, {n.pages_deleted} deleted")
    typer.echo(f"site: {out} ({deploy.site_size(out) / 2**20:.0f} MiB)")


@deploy_app.command("site")
def deploy_site_cmd(
    remote: Annotated[str | None, typer.Option(help="git remote URL; defaults to this repo's origin")] = None,
    site: Annotated[Path | None, typer.Option(help="built site folder; defaults to <data dir>/_site")] = None,
    budget_mb: Annotated[int, typer.Option(help="abort when the site is larger than this")] = deploy.DEFAULT_BUDGET // 2**20,
    wait: Annotated[bool, typer.Option(help="poll the Pages URL until this deploy is live")] = True,
) -> None:
    """Force-push the built site as an orphan gh-pages branch, then check the live URL."""
    remote = remote or deploy.origin_url(Path.cwd())
    try:
        done = deploy.deploy_site(site or site_dir(), remote, budget_mb * 2**20)
    except deploy.DeployError as e:
        typer.echo(f"deploy aborted: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"pushed {deploy.BRANCH} {done.commit[:12]} ({done.size / 2**20:.0f} MiB) to {remote}")
    url = deploy.pages_url(remote)
    if not wait or url is None:
        return
    typer.echo(f"waiting for {url} to serve deploy {done.deploy_id} ...")
    if not deploy.wait_live(url, done.deploy_id):
        typer.echo(f"{url} is not serving this deploy yet; is Pages set to the {deploy.BRANCH} branch?", err=True)
        raise typer.Exit(1)
    typer.echo(f"live: {url}")


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
