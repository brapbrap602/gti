"""`nov`: the command line. Each command parses its arguments, calls the Service and prints."""

import sys
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from novel_audio.tts import DEFAULT_VOICE
from novel_audio.volumes import VOLUME_SIZE
from novel_core import AlignmentDiff
from novel_publish import epub
from novel_sources.backends import BACKENDS
from novel_sources.fetch import FetchError
from novel_translate.glossary import AddTerm, Category, Status, UpdateTerm
from novel_translate.setups import SetupError, TranslatorSetup

from novel_app import deploy, report
from novel_app.jobs import JobBoard, JobRunner, JobRunning, Outcome
from novel_app.notation import parse_range
from novel_app.service import DEFAULT_CAP, Service, UserError, app_db

app = typer.Typer(no_args_is_help=True, help="Novel library: import, sync, check, build.")
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
glossary_app = typer.Typer(no_args_is_help=True, help="A novel's glossary: the names its translations keep.")
app.add_typer(glossary_app, name="glossary")
translate_app = typer.Typer(no_args_is_help=True, help="LLM translations of the raws, one source per translator setup.")
app.add_typer(translate_app, name="translate")
setup_app = typer.Typer(no_args_is_help=True, help="Translator setups: model, prompt, context, reasoning.")
translate_app.add_typer(setup_app, name="setup")


@app.callback()
def _utf8_output() -> None:
    # Titles can be Chinese; on Windows a piped stdout defaults to the ANSI code page, which cannot print them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _service() -> Service:
    return Service(JobRunner(JobBoard(app_db())))


def _job(kind: str, **args) -> Outcome:
    """Run a job here, printing its log; exit 1 if any item failed."""
    try:
        _, outcome = _calling(lambda: _service().run(kind, typer.echo, **args))
    except FetchError as e:
        typer.echo(f"fetch failed: {e}", err=True)
        raise typer.Exit(1) from e
    if outcome.errors:
        raise typer.Exit(1)
    return outcome


def _calling[T](call: Callable[[], T]) -> T:
    """Run a Service call, turning refusals into an error line and an exit code."""
    try:
        return call()
    except UserError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    except JobRunning as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e


Novel = Annotated[str, typer.Argument(help="novel slug")]
NovelOpt = Annotated[str | None, typer.Option(help="novel slug; defaults to the slug of the folder or file name")]
Refs = Annotated[list[str], typer.Argument(help="item refs, as `nov check` prints them")]
SourceOpt = Annotated[int | None, typer.Option(help="source id; needed when the novel has several")]


@import_app.command("wns")
def import_wns(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="web-novel-scraper novel folder")],
    novel: Annotated[str | None, typer.Option(help="novel slug; defaults to the slug of the stored title")] = None,
) -> None:
    """Import a web-novel-scraper novel folder (main.json + saved pages)."""
    _import("wns", folder, novel)


@import_app.command("mtl")
def import_mtl(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="MtlTings data/raw/<novel> or data/translated/<novel>")],
    novel: NovelOpt = None,
) -> None:
    """Import MtlTings chapter files: raws as raw-zh, translations as my-translation."""
    _import("mtl", folder, novel)


@import_app.command("scribble")
def import_scribble(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="scribblehub text dump")],
    novel: NovelOpt = None,
) -> None:
    """Import a scribblehub text dump ('## Chapter N: Title' markers)."""
    _import("scribble", file, novel)


@import_app.command("calibre")
def import_calibre(
    folder: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="github_pages novels/<Novel> folder")],
    novel: NovelOpt = None,
) -> None:
    """Import an old site's Calibre HTML pages; later imports rank lower, so import this last."""
    _import("calibre", folder, novel)


def _import(importer: str, path: Path, novel: str | None) -> None:
    _job("import", importer=importer, path=str(path), novel=novel)


@app.command()
def add(
    url: Annotated[str, typer.Argument(help="the novel's page on the site")],
    novel: Annotated[str | None, typer.Option(help="novel slug to attach to; defaults to the slug of the site's title")] = None,
    lang: Annotated[str, typer.Option(help="en, or zh for Chinese raws")] = "en",
    backend: Annotated[str | None, typer.Option(help=f"one of {', '.join(BACKENDS)}; picked by host when left out")] = None,
) -> None:
    """Add a web source to a novel (creating the novel if it is new) and read its chapter list."""
    _job("add", url=url, novel=novel, lang=lang, backend=backend)


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
    if refresh:
        _parsed(parse_range, refresh)
    service = _service()
    _calling(service.guides)
    slugs = [s for s in service.novels() if service.web_sources(s, source)] if all_novels else [novel]
    failed = False
    for slug in slugs:
        try:
            _job("sync", novel=slug, refresh=refresh, source=source)
        except typer.Exit as e:
            if e.exit_code != 1 or not all_novels:
                raise
            failed = True
    if failed:
        raise typer.Exit(1)


@app.command()
def check(novel: Novel) -> None:
    """Report gaps, duplicates, unmapped chapters and other problems."""
    selected, r = _calling(lambda: _service().check(novel))
    typer.echo(f"{novel}: {selected} chapters selected")
    _echo(report.check_lines(r))


@app.command()
def priority(
    novel: Novel,
    sources: Annotated[str | None, typer.Argument(help="source ids, best first, e.g. 3,1,2")] = None,
) -> None:
    """Show the novel's sources in priority order, or set the order (unlisted sources rank after, by id)."""
    order = None
    if sources is not None:
        try:
            order = [int(x) for x in sources.split(",")]
        except ValueError:
            raise typer.BadParameter(f"{sources!r} is not a list of source ids like 3,1,2") from None
    for r in _calling(lambda: _service().priority(novel, order)):
        spec = r.source.spec
        typer.echo(f"  {r.rank}. source {r.source.id}: {spec.backend} {spec.kind} {spec.url}")


@app.command()
def pin(
    novel: Novel,
    numbers: Annotated[str, typer.Argument(help="chapter numbers, e.g. 834-836 or 7")],
    source: Annotated[int, typer.Argument(help="source id to use for them")],
) -> None:
    """Use one source's text for these chapter numbers, whatever the priority says (a later pin wins)."""
    keys = _parsed(parse_range, numbers)
    _calling(lambda: _service().pin(novel, keys, source))
    typer.echo(f"{novel}: {keys.start}-{keys.end} pinned to source {source}")


@app.command()
def unpin(
    novel: Novel,
    numbers: Annotated[str, typer.Argument(help="chapter numbers, e.g. 834-836 or 7")],
) -> None:
    """Let the priority choose these chapter numbers again (pins on other numbers stay)."""
    keys = _parsed(parse_range, numbers)
    left = _calling(lambda: _service().unpin(novel, keys))
    typer.echo(f"{novel}: {keys.start}-{keys.end} unpinned")
    for p in left:
        typer.echo(f"  still pinned: {p.range.start}-{p.range.end} to source {p.source_id}")


@align_app.command("item")
def align_item(
    novel: Novel,
    ref: Annotated[str, typer.Argument(help="item ref, as `nov check` prints it")],
    key: Annotated[str, typer.Argument(help="chapter key: 1277, or 524pt1 for a part")],
    source: SourceOpt = None,
) -> None:
    """Give one item an explicit chapter key (overrides offsets and ranges)."""
    _echo_moved(_calling(lambda: _service().align_item(novel, ref, key, source)))


@align_app.command("skip")
def align_skip(novel: Novel, refs: Refs, source: SourceOpt = None) -> None:
    """Leave items out of the book (reposts, notices): no key, not unmapped, not a duplicate."""
    _echo_moved(_calling(lambda: _service().align_skip(novel, refs, source)))


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
    diff = _calling(lambda: _service().align_copy(novel, from_source, to_source))
    typer.echo(f"{len(diff.moved)} items moved")


def _echo_moved(diff: AlignmentDiff) -> None:
    for m in diff.moved:
        typer.echo(f"  {m.item_ref}: {m.old or 'none'} -> {m.new or 'none'}")
    typer.echo(f"{len(diff.moved)} items moved")


@build_app.command("site")
def build_site_cmd(
    out: Annotated[Path | None, typer.Option(help="site folder; defaults to <data dir>/_site")] = None,
    force: Annotated[bool, typer.Option(help="rebuild every page, not only stale ones")] = False,
) -> None:
    """Build the static site for every novel in the data dir (incremental)."""
    _job("build-site", out=_str(out), force=force)


@build_app.command("epub")
def build_epub_cmd(
    novel: Novel,
    size: Annotated[int, typer.Option(help="chapter numbers per volume")] = epub.VOLUME_SIZE,
    force: Annotated[bool, typer.Option(help="rebuild every volume, not only stale ones")] = False,
    out: Annotated[Path | None, typer.Option(help="EPUB folder; defaults to <data dir>/_epub/<novel>")] = None,
) -> None:
    """EPUB volumes of the selected chapters, with title, author, series and cover (incremental)."""
    _job("build-epub", novel=novel, size=size, force=force, out=_str(out))


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
    _job("build-audio", novel=novel, range=chapters, force=force, voice=voice, concurrency=concurrency, out=_str(out))


@build_app.command("volumes")
def build_volumes_cmd(
    novel: Novel,
    size: Annotated[int, typer.Option(help="chapter numbers per volume")] = VOLUME_SIZE,
    out: AudioOut = None,
) -> None:
    """M4B audiobook volumes with chapter marks, from the chapter audio already built or registered."""
    _job("build-volumes", novel=novel, size=size, out=_str(out))


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
    _job("audio-register", novel=novel, folder=str(folder), key=str(key), source=source, shift=shift or [])


@audio_app.command("retag")
def audio_retag(novel: Novel, out: AudioOut = None) -> None:
    """Rewrite title, album, artist, track and cover tags of every chapter MP3, legacy ones included."""
    _job("audio-retag", novel=novel, out=_str(out))


@app.command()
def cover(
    novel: Novel,
    image: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="a .jpg or .png")],
) -> None:
    """Set the novel's cover (copied into its folder); used for audio tags, M4B and EPUB volumes."""
    _calling(lambda: _service().set_cover(novel, image))
    typer.echo(f"{novel}: cover set to {image.name}")


@deploy_app.command("site")
def deploy_site_cmd(
    remote: Annotated[str | None, typer.Option(help="git remote URL; defaults to this repo's origin")] = None,
    site: Annotated[Path | None, typer.Option(help="built site folder; defaults to <data dir>/_site")] = None,
    budget_mb: Annotated[int, typer.Option(help="abort when the site is larger than this")] = deploy.DEFAULT_BUDGET // 2**20,
    wait: Annotated[bool, typer.Option(help="poll the Pages URL until this deploy is live")] = True,
) -> None:
    """Force-push the built site as an orphan gh-pages branch, then check the live URL."""
    remote = remote or deploy.origin_url(Path.cwd())
    _job("deploy-site", remote=remote, site=_str(site), budget=budget_mb * 2**20, wait=wait)


Model = Annotated[str, typer.Option(help="OpenRouter model id, e.g. google/gemini-2.5-flash-lite")]
Cap = Annotated[float, typer.Option(help="stop once this many US dollars are spent")]
TermIds = Annotated[list[int], typer.Argument(help="term ids, as `nov glossary list` prints them")]


@glossary_app.command("build")
def glossary_build(
    novel: Novel,
    model: Model,
    cap: Cap = DEFAULT_CAP,
    revote: Annotated[bool, typer.Option(help="re-decide accepted terms you never edited")] = False,
    workers: Annotated[int, typer.Option(help="calls at once")] = 4,
    yes: Annotated[bool, typer.Option("--yes", help="start without asking")] = False,
) -> None:
    """Find the novel's names, ask the model about them and summarize changed chapters (resumable)."""
    estimate = _calling(lambda: _service().glossary_estimate(novel, model))
    typer.echo(f"{novel}: glossary pass with {model}, cap ${cap:.2f}")
    _echo(report.estimate_lines(estimate))
    if not yes and not typer.confirm("start?"):
        raise typer.Exit(1)
    _job("glossary-build", novel=novel, model=model, cap=cap, revote=revote, workers=workers)


@glossary_app.command("list")
def glossary_list(
    novel: Novel,
    status: Annotated[Status | None, typer.Option(help="only terms with this status")] = None,
    category: Annotated[Category | None, typer.Option(help="only terms of this category")] = None,
    search: Annotated[str | None, typer.Option(help="text in the Chinese, an alias or the English")] = None,
) -> None:
    """Show glossary terms: id, Chinese, English, category, status."""
    terms = _calling(lambda: _service().glossary(novel, status, category, search))
    for t in terms:
        aliases = f" (also {', '.join(t.aliases)})" if t.aliases else ""
        edited = " *" if t.edited else ""
        typer.echo(f"  {t.id:>5}  {t.zh}{aliases} → {t.en}  [{t.category}, {t.status}{edited}]")
    typer.echo(f"{len(terms)} terms (* edited by you)")


@glossary_app.command("add")
def glossary_add(
    novel: Novel,
    zh: Annotated[str, typer.Argument(help="the Chinese name")],
    en: Annotated[str, typer.Argument(help="its English rendering")],
    category: Annotated[Category, typer.Option(help="what it names")] = Category.OTHER,
    status: Annotated[Status, typer.Option(help="locked terms are never changed by a glossary pass")] = Status.LOCKED,
    alias: Annotated[list[str] | None, typer.Option(help="another Chinese form (repeatable)")] = None,
    gender: Annotated[str | None, typer.Option(help="for persons: male or female")] = None,
    notes: Annotated[str, typer.Option(help="a note the translator is given")] = "",
) -> None:
    """Add a term (locked unless --status says otherwise)."""
    edit = AddTerm(zh, en, category, status, gender, notes, tuple(alias or ()))
    revision = _calling(lambda: _service().glossary_edit(novel, [edit]))
    typer.echo(f"{novel}: added {zh} → {en} (glossary revision {revision})")


@glossary_app.command("set")
def glossary_set(
    novel: Novel,
    term: Annotated[int, typer.Argument(help="term id")],
    en: Annotated[str | None, typer.Option(help="new English rendering")] = None,
    category: Annotated[Category | None, typer.Option()] = None,
    status: Annotated[Status | None, typer.Option()] = None,
    gender: Annotated[str | None, typer.Option(help='male, female, or "" to clear')] = None,
    notes: Annotated[str | None, typer.Option(help='a note for the translator, or "" to clear')] = None,
) -> None:
    """Change a term; what you leave out stays. Any change marks it edited, so passes leave it alone."""
    revision = _calling(lambda: _service().glossary_edit(novel, [UpdateTerm(term, en, category, status, gender, notes)]))
    typer.echo(f"{novel}: term {term} updated (glossary revision {revision})")


@glossary_app.command("lock")
def glossary_lock(novel: Novel, terms: TermIds) -> None:
    """Lock terms: injected as they are, never changed by a glossary pass."""
    _glossary_status(novel, terms, Status.LOCKED)


@glossary_app.command("reject")
def glossary_reject(novel: Novel, terms: TermIds) -> None:
    """Mark strings as not terms: never injected, never proposed again."""
    _glossary_status(novel, terms, Status.REJECTED)


def _glossary_status(novel: str, terms: Sequence[int], status: Status) -> None:
    revision = _calling(lambda: _service().glossary_edit(novel, [UpdateTerm(t, status=status) for t in terms]))
    typer.echo(f"{novel}: {len(terms)} terms {status} (glossary revision {revision})")


SetupArg = Annotated[int, typer.Argument(help="the setup's source id, as `nov translate setup list` prints it")]


@setup_app.command("add")
def setup_add(
    novel: Novel,
    model: Model,
    prompt: Annotated[str, typer.Option(help="prompt version")] = "v1",
    context: Annotated[str, typer.Option(help="parallel, or sequential (also gives the previous translation)")] = "parallel",
    reasoning: Annotated[str, typer.Option(help="off, low, medium or high")] = "off",
    data_collection: Annotated[str, typer.Option(help="allow, or deny (only hosts that do not keep prompts)")] = "allow",
) -> None:
    """Add a translator setup: its own source, unpublished until you switch it on."""
    try:
        setup = TranslatorSetup(model, prompt, context, reasoning, data_collection)
    except SetupError as e:
        raise typer.BadParameter(str(e)) from e
    source = _calling(lambda: _service().add_setup(novel, setup))
    typer.echo(f"{novel}: setup {setup.label} is source {source} (unpublished)")


@setup_app.command("list")
def setup_list(novel: Novel) -> None:
    """The novel's translator setups, with chapters done and spend so far."""
    for r in _calling(lambda: _service().setups(novel)):
        state = "published" if r.source.published else "unpublished"
        typer.echo(
            f"  source {r.source.id}: {r.setup.label} [{state}]: {r.chapters} chapters "
            f"({r.flagged} flagged, {r.failed} failed), ${r.cost:.4f}"
        )


@translate_app.command("run")
def translate_run(
    novel: Novel,
    setup: SetupArg,
    numbers: Annotated[str | None, typer.Argument(help="chapter numbers, e.g. 1495-1504")] = None,
    stale: Annotated[bool, typer.Option("--stale", help="the chapters whose inputs changed instead")] = False,
    cap: Cap = DEFAULT_CAP,
    workers: Annotated[int, typer.Option(help="chapters at once (sequential setups use 1)")] = 4,
    yes: Annotated[bool, typer.Option("--yes", help="start without asking")] = False,
) -> None:
    """Translate chapters with one setup (prints the cost estimate and asks first)."""
    if (numbers is None) == (not stale):
        raise typer.BadParameter("give chapter numbers or --stale")
    span = numbers or ""
    estimate = _calling(lambda: _service().translate_estimate(novel, setup, span))
    _echo(report.translate_estimate_lines(estimate))
    if not estimate.chapters:
        typer.echo("nothing to translate")
        return
    if not yes and not typer.confirm(f"start, with a cap of ${cap:.2f}?"):
        raise typer.Exit(1)
    _job("translate", novel=novel, setup=setup, range=span, cap=cap, workers=workers)


@translate_app.command("compare")
def translate_compare(
    novel: Novel,
    numbers: Annotated[str, typer.Argument(help="chapter numbers, e.g. 1354-1358")],
    model: Annotated[list[str], typer.Option(help="an OpenRouter model id, or id@low|medium|high for reasoning (repeat)")],
    reference: Annotated[int | None, typer.Option(help="English source to judge against; default the book's official EN")] = None,
    cap: Annotated[float | None, typer.Option(help="US dollars; default the estimate, and never below it")] = None,
    workers: Annotated[int, typer.Option(help="chapters at once, per model")] = 4,
    yes: Annotated[bool, typer.Option("--yes", help="start without asking")] = False,
) -> None:
    """Translate the same chapters with several models, store nothing, and write a bundle to judge them by."""
    estimate = _calling(lambda: _service().compare_estimate(novel, model, numbers, reference))
    _echo(report.compare_estimate_lines(estimate))
    if not yes and not typer.confirm(f"start, with a cap of ${cap if cap is not None else estimate.total:.4f}?"):
        raise typer.Exit(1)
    _job("compare", novel=novel, models=list(model), range=numbers, cap=cap, workers=workers, reference=reference)


@translate_app.command("stale")
def translate_stale(novel: Novel, setup: SetupArg) -> None:
    """Chapters whose inputs (raw, glossary lines, context) changed since they were translated."""
    _echo(report.stale_lines(_calling(lambda: _service().stale(novel, setup))))


@translate_app.command("prune")
def translate_prune(novel: Novel, setup: SetupArg) -> None:
    """Drop translations of raw chapters that no longer exist (orphans) from the setup."""
    dropped = _calling(lambda: _service().prune_orphans(novel, setup))
    typer.echo(f"{novel}: {len(dropped)} orphans dropped" + (f" ({', '.join(dropped)})" if dropped else ""))


@app.command()
def publish(
    novel: Novel,
    source: Annotated[int, typer.Argument(help="source id")],
    switch: Annotated[str, typer.Argument(help="on or off")],
) -> None:
    """Switch a source in or out of the book (site, EPUB, audio). New translator setups start off."""
    if switch not in ("on", "off"):
        raise typer.BadParameter("on or off")
    _calling(lambda: _service().set_published(novel, source, switch == "on"))
    typer.echo(f"{novel}: source {source} {'published' if switch == 'on' else 'unpublished'}; rank it with `nov priority`")


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="port on 127.0.0.1")] = 8765,
    workers: Annotated[int, typer.Option(help="jobs that may run at once (one per novel)")] = 2,
) -> None:
    """The web UI on http://127.0.0.1:<port>: library, chapter grids, compare and pin, jobs."""
    # Imported here: the web stack is not needed by the other commands.
    import uvicorn

    from novel_app.web.app import create_app

    service = Service(JobRunner(JobBoard(app_db()), workers=workers))
    typer.echo(f"serving the library on http://127.0.0.1:{port} (Ctrl-C stops; running jobs end as cancelled)")
    uvicorn.run(create_app(service), host="127.0.0.1", port=port, log_level="warning")


def _parsed[T](parse: Callable[[str], T], text: str) -> T:
    try:
        return parse(text)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


def _str(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _echo(lines: Sequence[str]) -> None:
    for line in lines:
        typer.echo(line)
