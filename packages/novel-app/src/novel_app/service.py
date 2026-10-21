"""Service: every operation the CLI and the web UI offer, over the novels in the data dir.

Long operations (add, sync, builds, imports, deploys) are jobs: `start` queues one on
the runner's threads (web), `run` runs it in the caller's thread (CLI). Both check
their input before taking the job's lock, raising UserError for bad input, so a
mistake is reported at once instead of as a failed job. Each job logs what the CLI
prints. The rest are quick reads and writes that return what they did.

Composition: `sources` (the backends' `open_source`), `tts` and `translator` (what
makes OpenRouter models) can be passed in; left out, they are this module's names,
looked up when the Service is made.
"""

import os
import shutil
from datetime import datetime
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from novel_audio.build import build_audio, retag_audio
from novel_audio.legacy import Positions, TitleNumbers, register_legacy
from novel_audio.media import MediaError
from novel_audio.tts import DEFAULT_VOICE, EdgeTts, TtsEngine
from novel_audio.volumes import VOLUME_SIZE, build_volumes
from novel_core import AlignmentDiff, AlignmentRules, KeyRange, Kind, NovelStore, NovelView, SourceInfo, SourceSpec, StoreError
from novel_core.selection import Pin
from novel_core.store import DB_NAME
from novel_publish import epub
from novel_publish.site import build_site
from novel_sources import zh_inspect
from novel_sources.backends import is_web, open_source, spec_for_url, zh_rules
from novel_sources.calibre import CalibreImporter
from novel_sources.decode_guide import Guides
from novel_sources.importing import Importer, import_novel
from novel_sources.mtl import MtlImporter
from novel_sources.reclean import reclean
from novel_sources.scribble import ScribbleImporter
from novel_sources.sync import Source, add_source, sync
from novel_sources.wns import WnsImporter, snapshot_refs
from novel_translate.budget import Budget
from novel_translate.glossary import Category, Edit, GlossaryError, Status, Term
from novel_translate.models import ModelFactory, OutOfCredit, Price, PriceUnavailable
from novel_translate.phase_a import Estimate, GlossaryOptions, build_glossary, estimate_glossary
from novel_translate.phase_b import Estimate as TranslateEstimate
from novel_translate.phase_b import (
    Comparison,
    StaleReport,
    TranslateReport,
    compare,
    estimate_compare,
    estimate_translate,
    prune,
    ref_of,
    stale,
    translate,
)
from novel_translate.raws import official_english, raw_chapters, version_text
from novel_translate.setups import SetupError, TranslatorSetup, prompt_versions, register, setups
from novel_translate.tstore import DB_NAME as TRANSLATE_DB
from novel_translate.tstore import TranslateStore

from novel_app import deploy, pages, report
from novel_app.comparing import Bundle, ChapterScreen, Reference, bundles, chapter_screen, new_bundle, write_bundle
from novel_app.glossary_page import GlossaryPage, TermRow, glossary_page, term_row
from novel_app.jobs import SITE, JobPanel, JobRow, JobRunner, JobState, Outcome, Work
from novel_app.library import (
    audio_dir,
    compare_dir,
    data_dir,
    epub_dir,
    fetch_dir,
    guide_file,
    novel_dir,
    novel_slugs,
    site_dir,
    slugify,
)
from novel_app.notation import parse_key, parse_range, parse_shift

IMPORTERS: Mapping[str, Callable[[Path], Importer]] = {
    "wns": WnsImporter,
    "mtl": MtlImporter,
    "scribble": ScribbleImporter,
    "calibre": CalibreImporter,
}
LEGACY_KEYS = ("position", "title-number")
KEY_ENV = "OPENROUTER_API_KEY"
DEFAULT_CAP = 1.0  # dollars per job unless the run says otherwise


class UserError(Exception):
    """Bad input: an unknown novel or source, a malformed range, a broken guide file."""


@dataclass(frozen=True)
class SetupRow:
    source: SourceInfo
    setup: TranslatorSetup
    chapters: int  # translated and current in the ledger
    flagged: int  # of those, stored with soft flags
    failed: int
    cost: float  # every attempt, failed ones included
    stale: int
    orphans: int


@dataclass(frozen=True)
class TranslatePanel:
    setups: list[SetupRow]
    blocked: str | None  # why nothing can be translated now (no key)
    prompts: tuple[str, ...]


@dataclass(frozen=True)
class CompareEstimate:
    setups: tuple[TranslatorSetup, ...]
    usd: dict[str, float]  # setup url -> upper bound
    chapters: tuple[str, ...]  # refs of the raw chapters compared
    references: tuple[str, ...]  # of those, the ones with reference English

    @property
    def total(self) -> float:
        return sum(self.usd.values())


@dataclass(frozen=True)
class Ranked:
    rank: int
    source: SourceInfo


def app_db() -> Path:
    return data_dir() / "app.sqlite"


def openrouter() -> ModelFactory:
    """OpenRouter, with the key from the environment it was started in."""
    key = os.environ.get(KEY_ENV)
    if not key:
        raise UserError(f"set {KEY_ENV} (and restart nov serve)")
    return ModelFactory(key)


class Service:
    def __init__(
        self,
        runner: JobRunner,
        sources: Callable[..., AbstractContextManager[Source]] | None = None,
        tts: Callable[[str], TtsEngine] | None = None,
        translator: Callable[[], ModelFactory] | None = None,
    ):
        self.runner = runner
        self._open_source = sources or open_source
        self._tts = tts or EdgeTts
        self._translator = translator or openrouter
        # Page reads, per novel, until its database files change: (stamp, view, row without job state).
        self._cache: dict[str, tuple[tuple, NovelView, pages.LibraryRow]] = {}
        # Staleness per (novel, setup url), until either of the novel's databases changes.
        self._stale: dict[tuple[str, str], tuple[tuple, StaleReport]] = {}
        self._ops: Mapping[str, Callable[..., tuple[str, Work]]] = {
            "add": self._add,
            "sync": self._sync,
            "build-site": self._build_site,
            "build-epub": self._build_epub,
            "build-audio": self._build_audio,
            "build-volumes": self._build_volumes,
            "import": self._import,
            "audio-register": self._audio_register,
            "audio-retag": self._audio_retag,
            "deploy-site": self._deploy_site,
            "glossary-build": self._glossary_build,
            "translate": self._translate,
            "compare": self._compare,
            "reclean": self._reclean,
        }

    # -- jobs ----------------------------------------------------------------

    def start(self, kind: str, **args) -> int:
        """Queue a job; raises UserError for bad input and JobRunning if its target is busy."""
        target, work = self._prepare(kind, args)
        return self.runner.submit(target, kind, args, work)

    def run(self, kind: str, echo: Callable[[str], None], **args) -> tuple[JobState, Outcome]:
        """Run a job in this thread, echoing its log; the work's own exceptions propagate."""
        target, work = self._prepare(kind, args)
        return self.runner.run(target, kind, args, work, echo)

    def rerun(self, job_id: int) -> int:
        """Start a job again with the same arguments (after it was interrupted or failed)."""
        row = self.runner.board.job(job_id)
        if row is None:
            raise UserError(f"no job {job_id}")
        return self.start(row.kind, **row.args)

    def _prepare(self, kind: str, args: Mapping[str, object]) -> tuple[str, Work]:
        op = self._ops.get(kind)
        if op is None:
            raise UserError(f"no job kind {kind!r}")
        return op(**args)

    # -- web sources ---------------------------------------------------------

    def _add(self, url: str, novel: str | None = None, lang: str = "en", backend: str | None = None):
        guides = self.guides()
        try:
            spec = spec_for_url(url, lang, backend, guides)
        except ValueError as e:
            raise UserError(str(e)) from e
        if novel is not None:
            _slug(novel)

        def work(job) -> Outcome:
            with self._open_source(spec, fetch_dir(), guides) as source:
                index = source.fetch_index()
            slug = novel or slugify(index.meta.title)
            r = add_source(novel_dir(slug), spec, index)
            job.log(f"{'created' if r.created else 'updated'} {slug}: source {r.source_id} ({spec.backend}), {r.items} chapters listed")
            with NovelStore.open(novel_dir(slug)) as store:
                job.log(f"  to fetch: {len(store.to_fetch(r.source_id))}; run `nov sync {slug}`")
            return Outcome()

        return novel or url, work

    def web_sources(self, novel: str, source: int | None = None) -> list[SourceInfo]:
        with self._store(novel) as store:
            return [s for s in store.sources() if is_web(s.spec) and source in (None, s.id)]

    def _sync(self, novel: str, refresh: str | None = None, source: int | None = None, numbers: str | None = None):
        keys = _parsed(parse_range, refresh) if refresh else None
        only = _parsed(parse_range, numbers) if numbers else None
        web = self.web_sources(novel, source)
        if not web:
            raise UserError(f"{novel} has no web source{'' if source is None else f' {source}'}; add one with `nov add`")
        guides = self.guides()

        def work(job) -> Outcome:
            errors: list[str] = []
            with self._store(novel) as store:
                for info in web:
                    job.log(f"{novel}: source {info.id} ({info.spec.backend}) {info.spec.url}")
                    with self._open_source(info.spec, fetch_dir(), guides) as live:
                        r = sync(
                            store, info.id, live, keys, lambda d, t, item: job.progress(d, t, item.title), only,
                            zh=zh_rules(novel, info.spec),
                        )  # fmt: skip
                    others = [s for s in store.sources() if s.spec.kind is Kind.RAW_ZH and s.id != info.id]
                    for line in report.sync_lines(r, other_raws=bool(others)):
                        job.log(line)
                    errors += report.failed_lines(r.failed)
                for line in report.unchecked_lines(pages.unchecked(novel, store.view()), novel):
                    job.log(line)
            return Outcome(tuple(errors))

        return novel, work

    def raw_sources(self, novel: str, source: int | None = None) -> list[SourceInfo]:
        """The novel's raw-zh sources (or just `source`, which must be one); UserError if none."""
        with self._store(novel) as store:
            raws = [s for s in store.sources() if s.spec.kind is Kind.RAW_ZH]
        if not raws:
            raise UserError(f"{novel} has no Chinese raws")
        chosen = [s for s in raws if source in (None, s.id)]
        if not chosen:
            raise UserError(f"source {source} is not one of {novel}'s raw sources {[s.id for s in raws]}")
        return chosen

    def _reclean(self, novel: str, source: int | None = None):
        """Clean and check the stored raws again with today's zh rules; never fetches."""
        raws = self.raw_sources(novel, source)

        def work(job) -> Outcome:
            with self._store(novel) as store, ExitStack() as stack:
                translators = setups(store.sources())
                ts = stack.enter_context(self._tstore(novel)) if translators else None
                # Staleness includes neighbours whose context changed, so compare whole reports.
                before = {info.id: set(stale(store, ts, setup).stale) for info, setup in translators}
                for info in raws:
                    job.log(f"{novel}: source {info.id} ({info.spec.backend}) {info.spec.url}")
                    for line in report.reclean_lines(reclean(store, info.id, zh_rules(novel, info.spec))):
                        job.log(line)
                for info, setup in translators:
                    now = [ref for ref in stale(store, ts, setup).stale if ref not in before[info.id]]
                    job.log(report.now_stale_line(info.id, setup.label, now))
            return Outcome()

        return novel, work

    def release(self, novel: str, numbers: str, source: int | None = None) -> list[tuple[int, str, tuple[str, ...]]]:
        """Release every held chapter at these numbers: its findings now are false positives.
        Returns (source, ref, checks released) per chapter."""
        keys = _parsed(parse_range, numbers)
        raws = self.raw_sources(novel, source)
        released = []
        with self._store(novel) as store:
            view = store.view()
            for info in raws:
                held = [s.item_ref for s in view.chapters(info.id) if s.key.number in keys and view.held(info.id, s.item_ref)]
                released += [(info.id, ref, checks) for ref, checks in store.release(info.id, held).items()]
        return released

    def inspect(
        self, novel: str, numbers: str, source: int | None = None, against: int | None = None
    ) -> list[zh_inspect.Inspection]:
        """What today's zh rules make of the raw chapters at these numbers (every raw source but `against`,
        or just `source`), each diffed with the chapter of the same title name in `against` when given."""
        keys = _parsed(parse_range, numbers)
        raws = self.raw_sources(novel, source)
        reference = self.raw_sources(novel, against)[0] if against is not None else None
        found = []
        with self._store(novel) as store:
            pair = (reference.id, zh_rules(novel, reference.spec)) if reference else None
            for info in raws:
                if info != reference:
                    found += zh_inspect.inspect(store, info.id, zh_rules(novel, info.spec), keys, pair)
        return found

    def guides(self) -> Guides:
        """The decode guides: shipped ones, with the user's own file applied."""
        try:
            return Guides.load(guide_file())
        except ValueError as e:
            raise UserError(str(e)) from e

    # -- builds --------------------------------------------------------------

    def _build_site(self, out: str | None = None, force: bool = False):
        folder = Path(out) if out else site_dir()

        def work(job) -> Outcome:
            with ExitStack() as stack:
                stores = {slug: stack.enter_context(NovelStore.open(novel_dir(slug))) for slug in novel_slugs()}
                r = build_site(stores, folder, force=force)
            for n in r.novels:
                state = "raw only" if n.raw_only else f"{n.chapters} chapters"
                job.log(f"{n.slug}: {state}, {n.pages_written} pages written, {n.pages_deleted} deleted")
            job.log(f"site: {folder} ({deploy.site_size(folder) / 2**20:.0f} MiB)")
            return Outcome()

        return SITE, work

    def _build_epub(self, novel: str, size: int = epub.VOLUME_SIZE, force: bool = False, out: str | None = None):
        self._require(novel)
        folder = Path(out) if out else epub_dir(novel)

        def work(job) -> Outcome:
            with self._store(novel) as store:
                r = epub.build_epub(
                    store, folder, novel, size=size, cover=self._cover(novel, store), force=force,
                    progress=lambda v, i, n: job.progress(i, n, f"volume {v.start}-{v.end}"),
                )  # fmt: skip
            job.log(f"{novel}: {len(r.built)} of {r.volumes} volumes built, {len(r.deleted)} deleted ({folder})")
            return Outcome()

        return novel, work

    def _build_audio(
        self,
        novel: str,
        range: str | None = None,
        force: bool = False,
        voice: str = DEFAULT_VOICE,
        concurrency: int = 2,
        out: str | None = None,
    ):
        self._require(novel)
        keys = _parsed(parse_range, range) if range else None
        folder = Path(out) if out else audio_dir(novel)
        tts = self._tts(voice)

        def work(job) -> Outcome:
            with self._store(novel) as store:
                try:
                    r = build_audio(
                        store, folder, tts, keys=keys, force=force, cover=self._cover(novel, store),
                        concurrency=concurrency, progress=lambda s, i, n: job.progress(i, n, f"chapter {s.key.label}"),
                    )  # fmt: skip
                except MediaError as e:
                    job.log(f"audio build stopped: {e}")
                    return Outcome((f"audio build stopped: {e}",))
            job.log(
                f"{novel}: {len(r.built)} chapters built, {len(r.pruned)} pruned; "
                f"{r.synthesized} sentences synthesized, {r.reused} from the cache ({folder})"
            )
            return Outcome()

        return novel, work

    def _build_volumes(self, novel: str, size: int = VOLUME_SIZE, out: str | None = None):
        self._require(novel)
        folder = Path(out) if out else audio_dir(novel)

        def work(job) -> Outcome:
            with self._store(novel) as store:
                try:
                    r = build_volumes(
                        store, folder, size=size, cover=self._cover(novel, store),
                        progress=lambda v, i, n: job.progress(i, n, f"volume {v.start}-{v.end}"),
                    )  # fmt: skip
                except MediaError as e:
                    job.log(f"volume build stopped: {e}")
                    return Outcome((f"volume build stopped: {e}",))
            job.log(f"{novel}: {len(r.built)} volumes built, {len(r.pruned)} deleted ({folder / 'volumes'})")
            for v, missing in r.incomplete:
                job.log(f"  volume {v.start}-{v.end} lacks audio for {missing} selected chapters")
            return Outcome()

        return novel, work

    # -- legacy stores -------------------------------------------------------

    def _import(self, importer: str, path: str, novel: str | None = None):
        make = IMPORTERS.get(importer)
        if make is None:
            raise UserError(f"no importer {importer!r}; one of {', '.join(IMPORTERS)}")
        reader = _parsed(make, Path(path))
        slug = _slug(novel) if novel else slugify(reader.read_index().meta.title)

        def work(job) -> Outcome:
            r = import_novel(novel_dir(slug), reader, zh=zh_rules(slug, reader.spec))
            for line in report.import_lines(slug, r):
                job.log(line)
            return Outcome(tuple(report.failed_lines(r.failed)))

        return slug, work

    def _audio_register(
        self, novel: str, folder: str, key: str, source: int | None = None, shift: Sequence[str] = ()
    ):
        if key not in LEGACY_KEYS:
            raise UserError(f"key must be one of {', '.join(LEGACY_KEYS)}")
        shifts = [_parsed(parse_shift, s) for s in shift]
        with self._store(novel) as store:
            source = self._pick_source(store, source)

        def work(job) -> Outcome:
            with self._store(novel) as store:
                keys = Positions(snapshot_refs(novel_dir(novel), source)) if key == "position" else TitleNumbers()
                r = register_legacy(store, Path(folder), source, keys, shifts)
            for line in report.legacy_lines(r):
                job.log(line)
            return Outcome()

        return novel, work

    def _audio_retag(self, novel: str, out: str | None = None):
        self._require(novel)

        def work(job) -> Outcome:
            with self._store(novel) as store:
                done = retag_audio(store, Path(out) if out else audio_dir(novel), self._cover(novel, store))
            job.log(f"{novel}: {done} chapter MP3s tagged")
            return Outcome()

        return novel, work

    def _deploy_site(self, remote: str, site: str | None = None, budget: int = deploy.DEFAULT_BUDGET, wait: bool = True):
        folder = Path(site) if site else site_dir()

        def work(job) -> Outcome:
            try:
                done = deploy.deploy_site(folder, remote, budget)
            except deploy.DeployError as e:
                job.log(f"deploy aborted: {e}")
                return Outcome((f"deploy aborted: {e}",))
            job.log(f"pushed {deploy.BRANCH} {done.commit[:12]} ({done.size / 2**20:.0f} MiB) to {remote}")
            url = deploy.pages_url(remote)
            if not wait or url is None:
                return Outcome()
            job.log(f"waiting for {url} to serve deploy {done.deploy_id} ...")
            if not deploy.wait_live(url, done.deploy_id):
                msg = f"{url} is not serving this deploy yet; is Pages set to the {deploy.BRANCH} branch?"
                job.log(msg)
                return Outcome((msg,))
            job.log(f"live: {url}")
            return Outcome()

        return SITE, work

    def jobs(self, limit: int = 20) -> list[JobRow]:
        """Active jobs first, then the most recent."""
        return self.runner.board.jobs(limit)

    def job_panel(self) -> JobPanel:
        """The jobs drawer: active jobs and unresolved problems, then recent jobs (see JobBoard.panel)."""
        return self.runner.board.panel()

    def job_log(self, job_id: int) -> str:
        path = self.runner.board.log_path(job_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def cancel(self, job_id: int) -> bool:
        """Ask a job of this process to stop after its current item."""
        return self.runner.cancel(job_id)

    # -- pages ---------------------------------------------------------------

    def library(self) -> list[pages.LibraryRow]:
        jobs = self.jobs(limit=50)
        return [self._row(slug, jobs) for slug in novel_slugs()]

    def novel(self, novel: str) -> pages.NovelPage:
        row = self._row(novel, self.jobs(limit=50))
        view = self._read(novel)[0]
        return pages.NovelPage(row, pages.chapter_grid(view), view.pins, pages.novel_check(novel, view))

    def compare(self, novel: str, number: int, left: int | None = None, right: int | None = None) -> pages.Comparison:
        with self._store(novel) as store:
            return pages.comparison(store, store.view(), number, left, right)

    def preview_add(self, url: str, lang: str = "en", backend: str | None = None) -> SourceSpec:
        """The source `add` would create for this URL (the backend picked by host), without fetching."""
        try:
            return spec_for_url(url, lang, backend, self.guides())
        except ValueError as e:
            raise UserError(str(e)) from e

    def _read(self, novel: str) -> tuple[NovelView, pages.LibraryRow]:
        """The novel's view and library row, read again only after its database changed."""
        folder = self._require(novel)
        stamp = _stamp(folder)
        cached = self._cache.get(novel)
        if cached is None or cached[0] != stamp:
            with NovelStore.open(folder) as store:
                view = store.view()
            cached = (stamp, view, pages.library_row(novel, view, (), None))
            self._cache[novel] = cached
        return cached[1], cached[2]

    def _row(self, novel: str, jobs: Sequence[JobRow]) -> pages.LibraryRow:
        last = self.runner.board.last_ended(novel, "sync")
        job = next((j for j in jobs if j.target == novel and j.state.active), None)
        return replace(self._read(novel)[1], job=job, last_sync=last.ended_at if last else None)

    # -- quick reads and writes ------------------------------------------------

    def novels(self) -> list[str]:
        return novel_slugs()

    def check(self, novel: str) -> tuple[int, pages.NovelCheck]:
        """(chapters selected, what the check found)."""
        with self._store(novel) as store:
            view = store.view()
        return len(view.selection), pages.novel_check(novel, view)

    def priority(self, novel: str, order: Sequence[int] | None = None) -> list[Ranked]:
        """The sources best first, after setting the order if given (unlisted sources rank after, by id)."""
        with self._store(novel) as store:
            known = {s.id: s for s in store.sources()}
            if order is not None:
                if unknown := [s for s in order if s not in known]:
                    raise UserError(f"no source {unknown[0]}; the novel has {sorted(known)}")
                store.set_priority(order)
            return [Ranked(rank, known[s]) for rank, s in enumerate(store.priority(), start=1)]

    def pin(self, novel: str, keys: KeyRange, source: int) -> None:
        """Use this source for these chapter numbers whatever the priority says."""
        with self._store(novel) as store:
            try:
                store.set_pin(keys, source)
            except StoreError as e:
                raise UserError(str(e)) from e

    def unpin(self, novel: str, keys: KeyRange) -> tuple[Pin, ...]:
        """Let the priority decide these chapter numbers again; returns the pins left."""
        with self._store(novel) as store:
            try:
                return store.unpin(keys)
            except StoreError as e:
                raise UserError(str(e)) from e

    def align_item(self, novel: str, ref: str, key: str, source: int | None = None) -> AlignmentDiff:
        chapter = _parsed(parse_key, key)
        return self._edit_alignment(novel, source, [ref], lambda r: replace(r, items={**r.items, ref: chapter}))

    def align_skip(self, novel: str, refs: Sequence[str], source: int | None = None) -> AlignmentDiff:
        return self._edit_alignment(novel, source, refs, lambda r: replace(r, skip=r.skip | set(refs)))

    def align_copy(self, novel: str, from_source: int, to_source: int) -> AlignmentDiff:
        """Give a source another's offsets, ranges, item keys and skips (for items it also lists)."""
        with self._store(novel) as store:
            sources = {s.id: s for s in store.sources()}
            if unknown := [s for s in (from_source, to_source) if s not in sources]:
                raise UserError(f"no source {unknown[0]}; the novel has {sorted(sources)}")
            rules = sources[from_source].alignment
            known = store.item_refs(to_source)
            copied = replace(
                rules,
                items={**sources[to_source].alignment.items, **{r: k for r, k in rules.items.items() if r in known}},
                skip=sources[to_source].alignment.skip | (rules.skip & known),
            )
            return store.set_alignment(to_source, copied)

    def _edit_alignment(
        self, novel: str, source: int | None, refs: Sequence[str], edit: Callable[[AlignmentRules], AlignmentRules]
    ) -> AlignmentDiff:
        with self._store(novel) as store:
            sources = {s.id: s for s in store.sources()}
            source = self._pick_source(store, source)
            known = store.item_refs(source)
            if unknown := [r for r in refs if r not in known]:
                raise UserError(f"source {source} has no item {unknown[0]!r}")
            return store.set_alignment(source, edit(sources[source].alignment))

    def set_cover(self, novel: str, image: Path) -> None:
        suffix = ".jpg" if image.suffix.lower() == ".jpeg" else image.suffix.lower()
        if suffix not in {".jpg", ".png"}:
            raise UserError(f"{image.name}: expected a .jpg or .png")
        with self._store(novel) as store:
            folder = novel_dir(novel)
            for old in folder.glob("cover.*"):
                old.unlink()
            shutil.copyfile(image, folder / f"cover{suffix}")
            store.set_meta(replace(store.meta, cover_path=f"cover{suffix}"))

    # -- glossary ------------------------------------------------------------

    def _glossary_build(
        self, novel: str, model: str, cap: float | str = DEFAULT_CAP, revote: bool = False, workers: int | str = 4
    ):
        options = self._glossary_options(novel, model, cap, workers, revote)
        model, cap = options.model, float(cap)
        factory = self._translator()
        price = _price(factory, model)

        def work(job) -> Outcome:
            with self._store(novel) as store, self._tstore(novel) as ts:
                job.log(f"{novel}: glossary pass with {model}, cap ${cap:.2f}")
                try:
                    r = build_glossary(
                        store, ts, lambda cancel: factory.llm(model, cancel), price, Budget(cap), options,
                        lambda done, total, step: job.progress(done, total, step),
                    )  # fmt: skip
                except OutOfCredit as e:
                    job.log(f"stopped: out of OpenRouter credit ({e})")
                    return Outcome((f"out of OpenRouter credit: {e}",))
            for line in report.glossary_lines(r):
                job.log(line)
            return Outcome(tuple(r.failed))

        return novel, work

    def glossary_estimate(self, novel: str, model: str) -> Estimate:
        options = self._glossary_options(novel, model)
        price = _price(self._translator(), model)
        with self._store(novel) as store, self._tstore(novel) as ts:
            return estimate_glossary(store, ts, price, options)

    def glossary(
        self, novel: str, status: Status | None = None, category: Category | None = None, search: str | None = None
    ) -> tuple[Term, ...]:
        with self._tstore(novel) as ts:
            return ts.entries(status, category, search)

    def glossary_page(
        self, novel: str, tab: str = "review", search: str = "", category: Category | None = None
    ) -> GlossaryPage:
        row = self._row(novel, self.jobs(limit=50))
        try:
            self._require_raws(novel)
            self._translator()
            blocked = None
        except UserError as e:
            blocked = str(e)
        with self._tstore(novel) as ts:
            return glossary_page(novel, row.title, ts, tab, search, category, blocked, row.job)

    def glossary_counts(self, novel: str) -> dict[Status, int] | None:
        """Terms per status, for the novel page; None when the novel has no raws to translate."""
        row = self._read(novel)[1]
        if not row.numbers.get(Kind.RAW_ZH):
            return None
        folder = self._require(novel)
        if not (folder / TRANSLATE_DB).exists():
            return {}
        with TranslateStore.open(folder) as ts:
            return ts.counts()

    def glossary_row(self, novel: str, term_id: int) -> TermRow:
        with self._tstore(novel) as ts:
            row = term_row(ts, term_id)
        if row is None:
            raise UserError(f"no term {term_id}")
        return row

    def glossary_edit(self, novel: str, edits: Sequence[Edit]) -> int:
        """Apply the user's glossary edits together; returns the glossary's new revision."""
        with self._tstore(novel) as ts:
            try:
                return ts.apply(edits)
            except GlossaryError as e:
                raise UserError(str(e)) from e

    def _glossary_options(
        self, novel: str, model: str, cap: float | str = DEFAULT_CAP, workers: int | str = 4, revote: bool = False
    ) -> GlossaryOptions:
        """Checks a glossary pass's arguments (web forms pass numbers as text)."""
        self._require_raws(novel)
        if not model.strip():
            raise UserError("name an OpenRouter model, like google/gemini-2.5-flash-lite")
        if _number(float, cap, "the cap") <= 0:
            raise UserError("the cap must be more than $0")
        if (workers := _number(int, workers, "workers")) < 1:
            raise UserError("workers must be at least 1")
        return GlossaryOptions(model.strip(), workers, revote)

    # -- translation -----------------------------------------------------------

    def add_setup(self, novel: str, setup: TranslatorSetup) -> int:
        """Add a translator setup as an unpublished source; its model must be one OpenRouter lists."""
        self._require_raws(novel)
        _price(self._translator(), setup.model)
        with self._store(novel) as store:
            try:
                return register(store, setup)
            except SetupError as e:
                raise UserError(str(e)) from e

    def setups(self, novel: str) -> list[SetupRow]:
        with self._store(novel) as store, self._tstore(novel) as ts:
            rows = []
            for info, setup in setups(store.sources()):
                ledger = ts.latest(setup.url).values()
                ok = [r for r in ledger if r.outcome == "ok"]
                behind = self._stale_report(novel, store, ts, setup)
                rows.append(SetupRow(
                    info, setup, len(ok), sum(1 for r in ok if r.soft_flags),
                    sum(1 for r in ledger if r.outcome == "failed"), ts.spend(setup.url).cost,
                    len(behind.stale), len(behind.orphans),
                ))  # fmt: skip
            return rows

    def translate_panel(self, novel: str) -> TranslatePanel | None:
        """The novel page's translation section; None for a novel without raws."""
        if self.glossary_counts(novel) is None:
            return None
        try:
            self._translator()
            blocked = None
        except UserError as e:
            blocked = str(e)
        return TranslatePanel(self.setups(novel), blocked, prompt_versions())

    def _stale_report(self, novel: str, store: NovelStore, ts: TranslateStore, setup: TranslatorSetup) -> StaleReport:
        folder = self._require(novel)
        stamp = _stamp(folder) + _stamp(folder, TRANSLATE_DB)
        cached = self._stale.get((novel, setup.url))
        if cached is None or cached[0] != stamp:
            cached = (stamp, stale(store, ts, setup))
            self._stale[(novel, setup.url)] = cached
        return cached[1]

    def _translate(
        self, novel: str, setup: int, range: str = "", cap: float | str = DEFAULT_CAP, workers: int | str = 4
    ):
        keys, chosen, workers = self._translate_args(novel, setup, range, workers)
        cap = _number(float, cap, "the cap")
        if cap <= 0:
            raise UserError("the cap must be more than $0")
        factory = self._translator()
        price = _price(factory, chosen.model)

        def new_llm(cancel):
            return factory.llm(chosen.model, cancel, data_collection=chosen.data_collection, reasoning=_effort(chosen))

        def work(job) -> Outcome:
            progress_report = TranslateReport()
            job.log(f"{novel}: translating {range or 'stale chapters'} with source {setup} ({chosen.label}), cap ${cap:.2f}")
            with self._store(novel) as store, self._tstore(novel) as ts:
                try:
                    translate(
                        store, ts, chosen, keys, new_llm, price, Budget(cap), workers,
                        lambda done, total, step: job.progress(done, total, step), progress_report,
                    )  # fmt: skip
                except OutOfCredit as e:
                    job.log(f"stopped: out of OpenRouter credit ({e})")
                    for line in report.translate_lines(progress_report):
                        job.log(line)
                    return Outcome((f"out of OpenRouter credit: {e}",))
                except BaseException:
                    job.log("stopped before the end; what was paid for is kept:")
                    for line in report.translate_lines(progress_report):
                        job.log(line)
                    raise
            for line in report.translate_lines(progress_report):
                job.log(line)
            return Outcome(tuple(progress_report.failed + progress_report.blocked))

        return novel, work

    def translate_estimate(self, novel: str, setup: int, range: str = "") -> TranslateEstimate:
        keys, chosen, _ = self._translate_args(novel, setup, range, 1)
        price = _price(self._translator(), chosen.model)
        with self._store(novel) as store, self._tstore(novel) as ts:
            return estimate_translate(store, ts, chosen, keys, price)

    # -- comparing models --------------------------------------------------------

    def compare_estimate(
        self,
        novel: str,
        models: Sequence[str],
        range: str,
        reference: int | str | None = None,
        reference_shift: int | str = 0,
        per_call: Sequence[int | str] = (1,),
    ) -> CompareEstimate:
        """What comparing these models on these chapters would cost at most, and which have reference English."""
        chosen, keys = self._compare_args(novel, models, range, per_call)
        factory = self._translator()
        prices = {s.url: _price(factory, s.model) for s in chosen}
        with self._store(novel) as store, self._tstore(novel) as ts:
            usd = _setup_errors(lambda: estimate_compare(store, ts, chosen, keys, prices))
            refs = tuple(ref_of(r.key) for r in raw_chapters(store, keys))
            found = _references(store, keys, _reference_source(store, reference), _number(int, reference_shift, "the shift"))
        if not refs:
            raise UserError(f"{novel} has no raw chapters in {range}")
        return CompareEstimate(chosen, usd, refs, tuple(r for r in refs if r in found))

    def _compare(
        self,
        novel: str,
        models: Sequence[str],
        range: str,
        cap: float | str | None = None,
        workers: int | str = 4,
        reference: int | str | None = None,
        reference_shift: int | str = 0,
        per_call: Sequence[int | str] = (1,),
    ):
        estimate = self.compare_estimate(novel, models, range, reference, reference_shift, per_call)
        cap = estimate.total if cap in (None, "") else _number(float, cap, "the cap")
        if cap < estimate.total:
            raise UserError(
                f"the cap ${cap:.4f} is below the estimate ${estimate.total:.4f}: a comparison cut short "
                "gives the models different chapters"
            )
        if (workers := _number(int, workers, "workers")) < 1:
            raise UserError("workers must be at least 1")
        chosen, keys = self._compare_args(novel, models, range, per_call)
        factory = self._translator()
        prices = {s.url: _price(factory, s.model) for s in chosen}

        def new_llm(setup, cancel):
            return factory.llm(setup.model, cancel, data_collection=setup.data_collection, reasoning=_effort(setup))

        def work(job) -> Outcome:
            folder = new_bundle(compare_dir(novel), range, datetime.now())
            job.log(f"{novel}: comparing {len(chosen)} setups on {range}, cap ${cap:.4f}")
            comparison = Comparison()
            with self._store(novel) as store, self._tstore(novel) as ts:
                references = _references(store, keys, _reference_source(store, reference), int(reference_shift))
                try:
                    compare(
                        store, ts, chosen, keys, new_llm, prices, Budget(cap), workers,
                        lambda done, total, step: job.progress(done, total, step), comparison,
                    )  # fmt: skip
                except OutOfCredit as e:
                    job.log(f"stopped: out of OpenRouter credit ({e})")
                finally:
                    readme = write_bundle(folder, novel, chosen, comparison, references, estimate.usd)
                    job.log(f"  ${comparison.cost:.4f} spent; bundle: {readme}")
            failed = [
                f"{s.model} {a.ref}: {a.failure}" for s in chosen for a in comparison.attempts.get(s.url, {}).values() if a.failure
            ]
            return Outcome(tuple(failed))

        return novel, work

    def comparisons(self, novel: str) -> list[Bundle]:
        """The novel's comparison runs, newest first."""
        self._require(novel)
        return bundles(compare_dir(novel))

    def comparison_chapter(self, novel: str, ref: str) -> ChapterScreen:
        screen = chapter_screen(self.comparisons(novel), ref)
        if screen is None:
            raise UserError(f"no comparison of {novel} has chapter {ref}")
        return screen

    def _compare_args(
        self, novel: str, models: Sequence[str], range: str, per_call: Sequence[int | str] = (1,)
    ) -> tuple[tuple[TranslatorSetup, ...], KeyRange]:
        """Models as `id` or `id@effort` (reasoning low, medium or high), each sent `per_call` chapters
        per request for every value given: parallel setups on prompt v1."""
        self._require_raws(novel)
        if not models:
            raise UserError("name at least one model")
        groups = [_number(int, n, "chapters per request") for n in per_call] or [1]
        chosen = []
        for text in models:
            model, _, effort = text.strip().partition("@")
            for group in groups:
                try:
                    chosen.append(TranslatorSetup(model, reasoning=effort or "off", group=group))
                except SetupError as e:
                    raise UserError(f"{text}: {e}") from e
        if len({s.url for s in chosen}) < len(chosen):
            raise UserError("a model or a number of chapters per request is named twice")
        return tuple(chosen), _parsed(parse_range, range)

    def stale(self, novel: str, setup: int) -> StaleReport:
        chosen = self._setup(novel, setup)
        with self._store(novel) as store, self._tstore(novel) as ts:
            return self._stale_report(novel, store, ts, chosen)

    def prune_orphans(self, novel: str, setup: int) -> tuple[str, ...]:
        chosen = self._setup(novel, setup)
        with self._store(novel) as store, self._tstore(novel) as ts:
            return prune(store, ts, chosen)

    def set_published(self, novel: str, source: int, on: bool) -> None:
        with self._store(novel) as store:
            try:
                store.set_published(source, on)
            except StoreError as e:
                raise UserError(str(e)) from e

    def _setup(self, novel: str, source: int) -> TranslatorSetup:
        with self._store(novel) as store:
            for info, setup in setups(store.sources()):
                if info.id == source:
                    return setup
        raise UserError(f"source {source} of {novel} is not a translator setup; see `nov translate setup list {novel}`")

    def _translate_args(self, novel: str, setup: int | str, range: str, workers: int | str):
        self._require_raws(novel)
        chosen = self._setup(novel, _number(int, setup, "the setup"))
        keys = "stale" if range.strip().lower() in ("", "stale") else _parsed(parse_range, range)
        if (workers := _number(int, workers, "workers")) < 1:
            raise UserError("workers must be at least 1")
        return keys, chosen, workers

    def _require_raws(self, novel: str) -> None:
        with self._store(novel) as store:
            if not any(s.spec.kind is Kind.RAW_ZH for s in store.sources()):
                raise UserError(f"{novel} has no Chinese raws")

    @contextmanager
    def _tstore(self, novel: str) -> Iterator[TranslateStore]:
        with TranslateStore.open_or_create(self._require(novel)) as ts:
            yield ts

    # -- helpers ---------------------------------------------------------------

    def _require(self, novel: str) -> Path:
        folder = novel_dir(_slug(novel))
        if not folder.exists():
            raise UserError(f"no novel {novel!r} in {folder.parent}")
        return folder

    @contextmanager
    def _store(self, novel: str) -> Iterator[NovelStore]:
        with NovelStore.open(self._require(novel)) as store:
            yield store

    def _cover(self, novel: str, store: NovelStore) -> bytes | None:
        path = store.meta.cover_path
        return (novel_dir(novel) / path).read_bytes() if path else None

    @staticmethod
    def _pick_source(store: NovelStore, source: int | None) -> int:
        """The given source, or the novel's only one."""
        ids = sorted(s.id for s in store.sources())
        if source is None and len(ids) == 1:
            return ids[0]
        if source not in ids:
            raise UserError(f"pass --source, one of {ids}")
        return source


def _stamp(folder: Path, db: str = DB_NAME) -> tuple:
    """Changes with every commit to one of the novel's databases (WAL appends, checkpoints)."""
    return tuple((st.st_mtime_ns, st.st_size) if (st := _stat(folder / name)) else None for name in (db, db + "-wal"))


def _stat(path: Path):
    try:
        return path.stat()
    except FileNotFoundError:
        return None


def _reference_source(store: NovelStore, reference: int | str | None) -> int | None:
    """The source given as the reference (English), or None for the book's own selection."""
    if reference in (None, ""):
        return None
    source = _number(int, reference, "the reference")
    info = next((i for i in store.sources() if i.id == source), None)
    if info is None or info.spec.lang != "en":
        raise UserError(f"source {source} is not one of the novel's English sources")
    return source


def _references(store: NovelStore, keys: KeyRange, source: int | None, shift: int = 0) -> dict[str, Reference]:
    """Reference English per raw chapter ref: the given source's text, else the book's selection where
    it is official English, for chapter number + `shift` (where the raws are numbered differently)."""
    view = store.view()
    if source is None:
        by_number = official_english(view)
    else:
        by_number = {}
        for s in view.chapters(source):
            by_number.setdefault(s.key.number, []).append(s)
    references = {}
    for raw in raw_chapters(store, keys, view=view):
        parts = sorted(by_number.get(raw.key.number + shift, []), key=lambda s: s.key.part)
        if parts:
            paragraphs = tuple(p for s in parts for p in version_text(store, s.version_id).split("\n") if p)
            references[ref_of(raw.key)] = Reference(parts[0].source_id, parts[0].title, paragraphs)
    return references


def _setup_errors[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except SetupError as e:
        raise UserError(str(e)) from e


def _effort(setup: TranslatorSetup) -> str | None:
    return None if setup.reasoning == "off" else setup.reasoning


def _number[N](kind: type[N], text: N | str, name: str) -> N:
    try:
        return kind(text)
    except ValueError as e:
        raise UserError(f"{name}: {text!r} is not a number") from e


def _price(factory: ModelFactory, model: str) -> Price:
    try:
        return factory.price(model)
    except PriceUnavailable as e:
        raise UserError(str(e)) from e


def _slug(novel: str) -> str:
    try:
        novel_dir(novel)
    except ValueError as e:
        raise UserError(str(e)) from e
    return novel


def _parsed[T, A](parse: Callable[[A], T], text: A) -> T:
    try:
        return parse(text)
    except ValueError as e:
        raise UserError(str(e)) from e

