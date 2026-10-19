"""`nov`: the command line. Each command is a thin wrapper over the packages below it."""

import re
import shutil
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
from novel_core import AlignmentRules, ChapterKey, CheckReport, KeyRange, NovelStore
from novel_publish import epub
from novel_publish.site import build_site
from novel_sources.importing import ImportReport, import_novel
from novel_sources.wns import WnsImporter, snapshot_refs

from novel_app import deploy
from novel_app.library import audio_dir, epub_dir, novel_dir, novel_slugs, site_dir, slugify

app = typer.Typer(no_args_is_help=True, help="Novel library: import, check, build.")
import_app = typer.Typer(no_args_is_help=True, help="One-shot imports of legacy local stores.")
app.add_typer(import_app, name="import")
build_app = typer.Typer(no_args_is_help=True, help="Build outputs from the selected chapters.")
app.add_typer(build_app, name="build")
deploy_app = typer.Typer(no_args_is_help=True, help="Publish built outputs.")
app.add_typer(deploy_app, name="deploy")
align_app = typer.Typer(no_args_is_help=True, help="Fix how a source's items map to chapter keys.")
app.add_typer(align_app, name="align")
audio_app = typer.Typer(no_args_is_help=True, help="Chapter audio: legacy registration and tags.")
app.add_typer(audio_app, name="audio")

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
        source = _pick_source(store, source)
        known = store.item_refs(source)
        if unknown := [r for r in refs if r not in known]:
            typer.echo(f"source {source} has no item {unknown[0]!r}", err=True)
            raise typer.Exit(2)
        diff = store.set_alignment(source, edit(sources[source].alignment))
    for m in diff.moved:
        typer.echo(f"  {m.item_ref}: {m.old or 'none'} -> {m.new or 'none'}")
    typer.echo(f"{len(diff.moved)} items moved")


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
