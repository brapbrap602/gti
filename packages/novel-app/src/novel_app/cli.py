"""`nov`: the command line. Each command is a thin wrapper over the packages below it."""

import re
import shutil
import sys
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from novel_audio.build import build_audio, retag_audio
from novel_audio.legacy import LegacyReport, Positions, Shift, TitleNumbers, register_legacy
from novel_audio.media import MediaError
from novel_audio.tts import DEFAULT_VOICE, EdgeTts
from novel_audio.volumes import VOLUME_SIZE, build_volumes
from novel_core import AlignmentRules, ChapterKey, CheckReport, KeyRange, NovelStore, SourceItem
from novel_publish import epub
from novel_publish.site import build_site
from novel_sources.backends import BACKENDS, is_web, open_source, spec_for_url
from novel_sources.calibre import CalibreImporter
from novel_sources.fetch import FetchError
from novel_sources.importing import Importer, ImportReport, import_novel
from novel_sources.mtl import MtlImporter
from novel_sources.scribble import ScribbleImporter
from novel_sources.sync import add_source, sync
from novel_sources.wns import WnsImporter, snapshot_refs

from novel_app import deploy
from novel_app.library import audio_dir, epub_dir, novel_dir, novel_slugs, site_dir, slugify, fetch_dir

app = typer.Typer(no_args_is_help=True, help="Novel library: import, sync, check, build.")
import_app = typer.Typer(no_args_is_help=True, help="One-shot imports of legacy local stores.")
app.add_typer(import_app, name="import")
build_app = typer.Typer(no_args_is_help=True, help="Build outputs from the selected chapters.")
app.add_typer(build_app, name="build")
deploy_app = typer.Typer(no_args_is_help=True, help="Publish built outputs.")
app.add_typer(deploy_app, name="deploy")
align_app = typer.Typer(no_args_is_help=True, help="Fix how a source's items map to chapter keys.")
app.add_typer(align_app, name="align")


@app.callback()
def _utf8_output() -> None:
    # Titles can be Chinese; on Windows a piped stdout defaults to the ANSI code page, which cannot print them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
audio_app = typer.Typer(no_args_is_help=True, help="Chapter audio: legacy registration and tags.")
app.add_typer(audio_app, name="audio")

LIST_LIMIT = 10


@import_app.command("wns")
def import_wns(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="web-novel-scraper novel folder")],
    novel: Annotated[str | None, typer.Option(help="novel slug; defaults to the slug of the stored title")] = None,
) -> None:
    """Import a web-novel-scraper novel folder (main.json + saved pages)."""
    _import(WnsImporter(folder), novel)


NovelOpt = Annotated[str | None, typer.Option(help="novel slug; defaults to the slug of the folder or file name")]


@import_app.command("mtl")
def import_mtl(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="MtlTings data/raw/<novel> or data/translated/<novel>")],
    novel: NovelOpt = None,
) -> None:
    """Import MtlTings chapter files: raws as raw-zh, translations as my-translation."""
    _import(_checked(MtlImporter, folder), novel)


@import_app.command("scribble")
def import_scribble(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="scribblehub text dump")],
    novel: NovelOpt = None,
) -> None:
    """Import a scribblehub text dump ('## Chapter N: Title' markers)."""
    _import(_checked(ScribbleImporter, file), novel)


@import_app.command("calibre")
def import_calibre(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="github_pages novels/<Novel> folder")],
    novel: NovelOpt = None,
) -> None:
    """Import an old site's Calibre HTML pages; later imports rank lower, so import this last."""
    _import(CalibreImporter(folder), novel)


def _checked[T](make: Callable[[Path], T], path: Path) -> T:
    try:
        return make(path)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


def _import(importer: Importer, novel: str | None) -> None:
    slug = novel or slugify(importer.read_index().meta.title)
    report = import_novel(novel_dir(slug), importer)
    _print_import(slug, report)
    if report.failed:
        raise typer.Exit(1)


Novel = Annotated[str, typer.Argument(help="novel slug")]
Refs = Annotated[list[str], typer.Argument(help="item refs, as `nov check` prints them")]
SourceOpt = Annotated[int | None, typer.Option(help="source id; needed when the novel has several")]


@app.command()
def add(
    url: Annotated[str, typer.Argument(help="the novel's page on the site")],
    novel: Annotated[str | None, typer.Option(help="novel slug to attach to; defaults to the slug of the site's title")] = None,
    lang: Annotated[str, typer.Option(help="en, or zh for Chinese raws")] = "en",
    backend: Annotated[str | None, typer.Option(help=f"one of {', '.join(BACKENDS)}; picked by host when left out")] = None,
) -> None:
    """Add a web source to a novel (creating the novel if it is new) and read its chapter list."""
    try:
        spec = spec_for_url(url, lang, backend)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    with open_source(spec, fetch_dir()) as source:
        index = _fetching(source.fetch_index)
    slug = novel or slugify(index.meta.title)
    r = add_source(novel_dir(slug), spec, index)
    typer.echo(f"{'created' if r.created else 'updated'} {slug}: source {r.source_id} ({spec.backend}), {r.items} chapters listed")
    with _open(slug) as store:
        typer.echo(f"  to fetch: {len(store.to_fetch(r.source_id))}; run `nov sync {slug}`")


@app.command("sync")
def sync_cmd(
    novel: Annotated[str | None, typer.Argument(help="novel slug; leave out with --all")] = None,
    all_novels: Annotated[bool, typer.Option("--all", help="sync every novel with a web source")] = False,
    refresh: Annotated[str | None, typer.Option(help="also fetch these chapter numbers again, e.g. 1400-1414")] = None,
    source: SourceOpt = None,
) -> None:
    """Fetch the chapters the book lacks from each web source; exit 1 if any chapter failed."""
    if all_novels == (novel is not None):
        raise typer.BadParameter("give a novel slug or --all")
    keys = _parse_range(refresh) if refresh else None
    failed = 0
    for slug in novel_slugs() if all_novels else [novel]:
        with _open(slug) as store:
            web = [s for s in store.sources() if is_web(s.spec) and source in (None, s.id)]
            if not web and not all_novels:
                typer.echo(f"{slug} has no web source{'' if source is None else f' {source}'}; add one with `nov add`", err=True)
                raise typer.Exit(2)
            for info in web:
                typer.echo(f"{slug}: source {info.id} ({info.spec.backend}) {info.spec.url}")
                with open_source(info.spec, fetch_dir()) as live:
                    r = _fetching(lambda: sync(store, info.id, live, keys, _progress))
                typer.echo(
                    f"  index: {len(r.index.added)} new, {len(r.index.vanished)} vanished; "
                    f"fetched {r.wanted}: {r.inserted} stored, {r.unchanged} unchanged, {len(r.unavailable)} locked"
                )
                _section("failed", [f"{ref}: {reason}" for ref, reason in r.failed])
                failed += len(r.failed)
    if failed:
        raise typer.Exit(1)


def _fetching[T](call: Callable[[], T]) -> T:
    """Run a fetch whose failure (no index at all) ends the command with the reason."""
    try:
        return call()
    except FetchError as e:
        typer.echo(f"fetch failed: {e}", err=True)
        raise typer.Exit(1) from e


def _progress(done: int, total: int, item: SourceItem) -> None:
    if done == total or done % 25 == 0:
        typer.echo(f"  {done}/{total} {item.title}")


@app.command()
def check(novel: Annotated[str, typer.Argument(help="novel slug")]) -> None:
    """Report gaps, duplicates, unmapped chapters and other problems."""
    with _open(novel) as store:
        report = store.check()
        selected = len(store.selection())
    typer.echo(f"{novel}: {selected} chapters selected")
    _print_check(report)


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


@align_app.command("copy")
def align_copy(
    novel: Novel,
    from_source: Annotated[int, typer.Argument(help="source whose rules to copy")],
    to_source: Annotated[int, typer.Argument(help="source to give them to")],
) -> None:
    """Give a source another's offsets, ranges, item keys and skips (for items it also lists).

    For a web source attached to a novel imported from the same site: refs are URL
    paths, so the fixes made on the import apply to the same chapters.
    """
    with _open(novel) as store:
        sources = {s.id: s for s in store.sources()}
        if unknown := [s for s in (from_source, to_source) if s not in sources]:
            typer.echo(f"no source {unknown[0]}; the novel has {sorted(sources)}", err=True)
            raise typer.Exit(2)
        rules = sources[from_source].alignment
        known = store.item_refs(to_source)
        copied = replace(
            rules,
            items={**sources[to_source].alignment.items, **{r: k for r, k in rules.items.items() if r in known}},
            skip=sources[to_source].alignment.skip | (rules.skip & known),
        )
        diff = store.set_alignment(to_source, copied)
    typer.echo(f"{len(diff.moved)} items moved")


def _edit_alignment(
    novel: str, source: int | None, refs: Sequence[str], edit: Callable[[AlignmentRules], AlignmentRules]
) -> None:
    with _open(novel) as store:
        sources = {s.id: s for s in store.sources()}
        source = _pick_source(store, source)
        known = store.item_refs(source)
        if unknown := [r for r in refs if r not in known]:
            typer.echo(f"source {source} has no item {unknown[0]!r}", err=True)
            raise typer.Exit(2)
        diff = store.set_alignment(source, edit(sources[source].alignment))
    for m in diff.moved:
        typer.echo(f"  {m.item_ref}: {m.old or 'none'} -> {m.new or 'none'}")
    typer.echo(f"{len(diff.moved)} items moved")


@app.command()
def priority(
    novel: Novel,
    sources: Annotated[str | None, typer.Argument(help="source ids, best first, e.g. 3,1,2")] = None,
) -> None:
    """Show the novel's sources in priority order, or set the order (unlisted sources rank after, by id)."""
    with _open(novel) as store:
        known = {s.id: s for s in store.sources()}
        if sources is not None:
            try:
                order = [int(x) for x in sources.split(",")]
            except ValueError:
                raise typer.BadParameter(f"{sources!r} is not a list of source ids like 3,1,2") from None
            if unknown := [s for s in order if s not in known]:
                raise typer.BadParameter(f"no source {unknown[0]}; the novel has {sorted(known)}")
            store.set_priority(order)
        ranked = store.priority()
    for rank, source in enumerate(ranked, start=1):
        spec = known[source].spec
        typer.echo(f"  {rank}. source {source}: {spec.backend} {spec.kind} {spec.url}")


def _pick_source(store: NovelStore, source: int | None) -> int:
    """The given source, or the novel's only one."""
    ids = sorted(s.id for s in store.sources())
    if source is None and len(ids) == 1:
        return ids[0]
    if source not in ids:
        typer.echo(f"pass --source, one of {ids}", err=True)
        raise typer.Exit(2)
    return source


def _parse_range(text: str) -> KeyRange:
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", text)
    if m is None:
        raise typer.BadParameter(f"{text!r} is not a range of chapter numbers like 1-100 or 7")
    start = int(m.group(1))
    return KeyRange(start, int(m.group(2) or start))


def _parse_shift(text: str) -> Shift:
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*:\s*([+-]?\d+)\s*", text)
    if m is None:
        raise typer.BadParameter(f"{text!r} is not a shift like 736-1442:+4")
    return Shift(KeyRange(int(m.group(1)), int(m.group(2))), int(m.group(3)))


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


@build_app.command("epub")
def build_epub_cmd(
    novel: Novel,
    size: Annotated[int, typer.Option(help="chapter numbers per volume")] = epub.VOLUME_SIZE,
    force: Annotated[bool, typer.Option(help="rebuild every volume, not only stale ones")] = False,
    out: Annotated[Path | None, typer.Option(help="EPUB folder; defaults to <data dir>/_epub/<novel>")] = None,
) -> None:
    """EPUB volumes of the selected chapters, with title, author, series and cover (incremental)."""
    out = out or epub_dir(novel)
    with _open(novel) as store:
        report = epub.build_epub(
            store, out, novel, size=size, cover=_cover(novel, store), force=force,
            progress=lambda r, i, n: typer.echo(f"  [{i}/{n}] volume {r.start}-{r.end}"),
        )  # fmt: skip
    typer.echo(f"{novel}: {len(report.built)} of {report.volumes} volumes built, {len(report.deleted)} deleted ({out})")


AudioOut = Annotated[Path | None, typer.Option(help="audio folder; defaults to <data dir>/_audio/<novel>")]


@build_app.command("audio")
def build_audio_cmd(
    novel: Novel,
    chapters: Annotated[str | None, typer.Option("--range", help="only chapter numbers in this range, e.g. 1-100")] = None,
    force: Annotated[bool, typer.Option(help="rebuild every chapter in --range, legacy ones too")] = False,
    voice: Annotated[str, typer.Option(help="edge-tts voice; a different voice rebuilds every built chapter")] = DEFAULT_VOICE,
    concurrency: Annotated[int, typer.Option(help="TTS requests in flight")] = 2,
    out: AudioOut = None,
) -> None:
    """Text-to-speech MP3 per selected chapter (incremental; sentences are cached)."""
    out = out or audio_dir(novel)
    keys = _parse_range(chapters) if chapters else None
    with _open(novel) as store:
        try:
            report = build_audio(
                store, out, EdgeTts(voice), keys=keys, force=force, cover=_cover(novel, store),
                concurrency=concurrency, progress=lambda s, i, n: typer.echo(f"  [{i}/{n}] chapter {s.key.label}"),
            )  # fmt: skip
        except MediaError as e:
            typer.echo(f"audio build stopped: {e}", err=True)
            raise typer.Exit(1) from e
    typer.echo(
        f"{novel}: {len(report.built)} chapters built, {len(report.pruned)} pruned; "
        f"{report.synthesized} sentences synthesized, {report.reused} from the cache ({out})"
    )


@build_app.command("volumes")
def build_volumes_cmd(
    novel: Novel,
    size: Annotated[int, typer.Option(help="chapter numbers per volume")] = VOLUME_SIZE,
    out: AudioOut = None,
) -> None:
    """M4B audiobook volumes with chapter marks, from the chapter audio already built or registered."""
    out = out or audio_dir(novel)
    with _open(novel) as store:
        try:
            report = build_volumes(
                store, out, size=size, cover=_cover(novel, store),
                progress=lambda r, i, n: typer.echo(f"  [{i}/{n}] volume {r.start}-{r.end}"),
            )  # fmt: skip
        except MediaError as e:
            typer.echo(f"volume build stopped: {e}", err=True)
            raise typer.Exit(1) from e
    typer.echo(f"{novel}: {len(report.built)} volumes built, {len(report.pruned)} deleted ({out / 'volumes'})")
    for r, missing in report.incomplete:
        typer.echo(f"  volume {r.start}-{r.end} lacks audio for {missing} selected chapters")


class LegacyKey(StrEnum):
    POSITION = "position"
    TITLE_NUMBER = "title-number"


@audio_app.command("register")
def audio_register(
    novel: Novel,
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="old tts_out/<novel> folder")],
    key: Annotated[LegacyKey, typer.Option(help="what chapter_NNN counts: main.json positions or chapter numbers")],
    source: SourceOpt = None,
    shift: Annotated[list[str] | None, typer.Option(help="move folders: 736-1442:+4 maps folder 736 to 740")] = None,
) -> None:
    """Register old tts_reader chapter MP3s as built audio, after checking each against its text."""
    shifts = [_parse_shift(s) for s in shift or []]
    with _open(novel) as store:
        source = _pick_source(store, source)
        keys = Positions(snapshot_refs(novel_dir(novel), source)) if key is LegacyKey.POSITION else TitleNumbers()
        report = register_legacy(store, folder, source, keys, shifts)
    _print_legacy(report)


@audio_app.command("retag")
def audio_retag(novel: Novel, out: AudioOut = None) -> None:
    """Rewrite title, album, artist, track and cover tags of every chapter MP3, legacy ones included."""
    with _open(novel) as store:
        done = retag_audio(store, out or audio_dir(novel), _cover(novel, store))
    typer.echo(f"{novel}: {done} chapter MP3s tagged")


@app.command()
def cover(
    novel: Novel,
    image: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="a .jpg or .png")],
) -> None:
    """Set the novel's cover (copied into its folder); used for audio tags, M4B and EPUB volumes."""
    suffix = ".jpg" if image.suffix.lower() == ".jpeg" else image.suffix.lower()
    if suffix not in {".jpg", ".png"}:
        raise typer.BadParameter(f"{image.name}: expected a .jpg or .png")
    with _open(novel) as store:
        folder = novel_dir(novel)
        for old in folder.glob("cover.*"):
            old.unlink()
        shutil.copyfile(image, folder / f"cover{suffix}")
        store.set_meta(replace(store.meta, cover_path=f"cover{suffix}"))
    typer.echo(f"{novel}: cover set to {image.name}")


def _cover(novel: str, store: NovelStore) -> bytes | None:
    path = store.meta.cover_path
    return (novel_dir(novel) / path).read_bytes() if path else None


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


def _print_legacy(r: LegacyReport) -> None:
    typer.echo(f"  registered: {len(r.registered)} ({len(r.unverified)} too short or without sentence files to check)")
    _numbers("partial (no combined mp3)", r.partial)
    _numbers("already built", r.already_built)
    _section("unmapped", [f"folder {n}: {why}" for n, why in r.unmapped])
    _section("mismatched", [f"folder {m.folder}: not {m.key}; best match is {m.best}" for m in r.mismatched])


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
