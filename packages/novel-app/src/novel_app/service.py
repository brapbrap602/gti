"""Service: every operation the CLI and the web UI offer, over the novels in the data dir.

Long operations (add, sync, builds, imports, deploys) are jobs: `start` queues one on
the runner's threads (web), `run` runs it in the caller's thread (CLI). Both check
their input before taking the job's lock, raising UserError for bad input, so a
mistake is reported at once instead of as a failed job. Each job logs what the CLI
prints. The rest are quick reads and writes that return what they did.

Composition: `sources` (the backends' `open_source`) and `tts` can be passed in; left
out, they are this module's names, looked up when the Service is made.
"""

import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from novel_audio.build import build_audio, retag_audio
from novel_audio.legacy import Positions, TitleNumbers, register_legacy
from novel_audio.media import MediaError
from novel_audio.tts import DEFAULT_VOICE, EdgeTts, TtsEngine
from novel_audio.volumes import VOLUME_SIZE, build_volumes
from novel_core import AlignmentDiff, AlignmentRules, KeyRange, NovelStore, NovelView, SourceInfo, SourceSpec, StoreError
from novel_core.check import CheckReport
from novel_core.selection import Pin
from novel_core.store import DB_NAME
from novel_publish import epub
from novel_publish.site import build_site
from novel_sources.backends import is_web, open_source, spec_for_url
from novel_sources.calibre import CalibreImporter
from novel_sources.decode_guide import Guides
from novel_sources.importing import Importer, import_novel
from novel_sources.mtl import MtlImporter
from novel_sources.scribble import ScribbleImporter
from novel_sources.sync import Source, add_source, sync
from novel_sources.wns import WnsImporter, snapshot_refs

from novel_app import deploy, pages, report
from novel_app.jobs import SITE, JobRow, JobRunner, JobState, Outcome, Work
from novel_app.library import (
    audio_dir,
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


class UserError(Exception):
    """Bad input: an unknown novel or source, a malformed range, a broken guide file."""


@dataclass(frozen=True)
class Ranked:
    rank: int
    source: SourceInfo


def app_db() -> Path:
    return data_dir() / "app.sqlite"


class Service:
    def __init__(
        self,
        runner: JobRunner,
        sources: Callable[..., AbstractContextManager[Source]] | None = None,
        tts: Callable[[str], TtsEngine] | None = None,
    ):
        self.runner = runner
        self._open_source = sources or open_source
        self._tts = tts or EdgeTts
        # Page reads, per novel, until its database files change: (stamp, view, row without job state).
        self._cache: dict[str, tuple[tuple, NovelView, pages.LibraryRow]] = {}
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

    def _sync(self, novel: str, refresh: str | None = None, source: int | None = None):
        keys = _parsed(parse_range, refresh) if refresh else None
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
                        r = sync(store, info.id, live, keys, lambda d, t, item: job.progress(d, t, item.title))
                    for line in report.sync_lines(r):
                        job.log(line)
                    errors += report.failed_lines(r.failed)
            return Outcome(tuple(errors))

        return novel, work

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
            r = import_novel(novel_dir(slug), reader)
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
        return pages.NovelPage(row, pages.chapter_grid(view), view.pins, view.check())

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

    def check(self, novel: str) -> tuple[int, CheckReport]:
        """(chapters selected, report)."""
        with self._store(novel) as store:
            view = store.view()
        return len(view.selection), view.check()

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


def _stamp(folder: Path) -> tuple:
    """Changes with every commit to the novel's database (WAL appends, checkpoints)."""
    return tuple(
        (st.st_mtime_ns, st.st_size) if (st := _stat(folder / name)) else None for name in (DB_NAME, DB_NAME + "-wal")
    )


def _stat(path: Path):
    try:
        return path.stat()
    except FileNotFoundError:
        return None


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

