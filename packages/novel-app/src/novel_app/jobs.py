"""Jobs: long operations (sync, builds), one at a time per novel and kind, across processes.

`JobBoard` owns app.sqlite: a row per job (state, progress, errors) and a lock row
per (target, kind), the target being a novel slug or SITE for library-wide builds.
Different kinds of job on one novel run side by side (retag MP3s while audio builds);
two of the same kind would fight over the same files, so the second is refused. A lock
is taken with BEGIN IMMEDIATE and kept alive by a heartbeat; one whose heartbeat is
older than `stale_after` seconds belongs to a dead process and can be taken over. The
CLI and `nov serve` share the board, so either refuses a second job of a kind for a target.

`JobRunner` runs work on a thread of its own per job (web) or in the calling thread (CLI);
a job given a lane takes its turn there instead, one at a time (Sync all's syncs; audio
builds, which call a rate-limited TTS service), and may wait while its novel has a job of
another kind. Which kind goes where is the service's policy; the runner knows no kinds.
Work receives a `Job` to log lines and report progress; a cancel request is raised
as `Cancelled` from `Job.progress`, so cancelling a started job is cooperative, between
items. A job still waiting its turn is ended at once.
"""

import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)
SITE = "_site"  # the lock target of library-wide jobs; slugs never start with "_"
STALE_AFTER = 60.0
HEARTBEAT_EVERY = 10.0
PERSIST_EVERY = 1.0

type Clock = Callable[[], float]


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"  # the work raised
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # its process stopped before it ended

    @property
    def active(self) -> bool:
        return self in (JobState.QUEUED, JobState.RUNNING)


@dataclass(frozen=True)
class JobRow:
    id: int
    target: str
    kind: str
    args: Mapping[str, object]
    state: JobState
    created_at: float
    ended_at: float | None
    done: int
    total: int
    current: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class JobPanel:
    """The jobs drawer: what needs attention, then the rest of the recent jobs."""

    attention: tuple[JobRow, ...]  # active jobs, then unresolved problems; each newest first
    recent: tuple[JobRow, ...]  # newest first, none of them in attention

    @property
    def active(self) -> tuple[JobRow, ...]:
        return tuple(j for j in self.attention if j.state.active)

    @property
    def problem_jobs(self) -> tuple[JobRow, ...]:
        """Unresolved problems: what needs attention and is not active (app.js counts the same)."""
        return tuple(j for j in self.attention if not j.state.active)

    @property
    def problems(self) -> int:
        return len(self.problem_jobs)


@dataclass(frozen=True)
class Outcome:
    """What finished work reports: per-item errors (failed chapters) that did not stop it."""

    errors: tuple[str, ...] = ()


class JobRunning(Exception):
    def __init__(self, target: str, kind: str, job_id: int):
        super().__init__(f"{kind} already running for {target} (job {job_id})")
        self.target = target
        self.kind = kind
        self.job_id = job_id


class Cancelled(Exception):
    """Raised inside work at its next progress report after a cancel request."""


class Job:
    """What work sees of its job."""

    def __init__(self, board: "JobBoard", job_id: int, echo: Callable[[str], None] | None, clock: Clock):
        self.id = job_id
        self._board = board
        self._echo = echo
        self._clock = clock
        self._cancel = threading.Event()
        self._last_persist = 0.0
        self._last_echo = 0.0
        self._logged_done = 0
        self.last_progress: tuple[int, int, str] | None = None

    def log(self, line: str) -> None:
        self._board.append_log(self.id, line)
        if self._echo:
            self._echo(line)

    def progress(self, done: int, total: int, current: str = "") -> None:
        """Report progress; raises Cancelled when a cancel was requested."""
        now = self._clock()
        self.last_progress = (done, total, current)
        if done == total or now - self._last_persist >= PERSIST_EVERY:
            self._board.set_progress(self.id, done, total, current)
            self._last_persist = now
        if done != self._logged_done:  # one log line per item, as it starts, so a running job's log grows
            stamp = time.strftime("%H:%M:%S", time.localtime(now))
            self._board.append_log(self.id, f"{stamp} [{done}/{total}] {current}")
            self._logged_done = done
        if self._echo and (done in (1, total) or now - self._last_echo >= 2.0):
            self._echo(f"  [{done}/{total}] {current}")
            self._last_echo = now
        if self._cancel.is_set():
            raise Cancelled()


type Work = Callable[[Job], Outcome]


class JobBoard:
    def __init__(self, path: Path, clock: Clock = time.time, stale_after: float = STALE_AFTER):
        self._path = path
        self._logs = path.parent / "_jobs"
        self._clock = clock
        self._stale_after = stale_after
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS job (
                    id INTEGER PRIMARY KEY, target TEXT NOT NULL, kind TEXT NOT NULL, args TEXT NOT NULL,
                    state TEXT NOT NULL, created_at REAL NOT NULL, ended_at REAL,
                    done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                    current TEXT NOT NULL DEFAULT '', errors TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS lock (
                    target TEXT PRIMARY KEY, job_id INTEGER NOT NULL, pid INTEGER NOT NULL, heartbeat REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS job_by_pair ON job (target, kind, id);
                """
            )
        finally:
            db.close()
        with self._connect(immediate=True) as db:  # one process adds the column; another waits, then sees it
            if "dismissed" not in {c[1] for c in db.execute("PRAGMA table_info(job)")}:
                db.execute("ALTER TABLE job ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def _connect(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def claim(self, target: str, kind: str, args: Mapping[str, object]) -> int:
        """A new queued job holding the (target, kind) lock; raises JobRunning if a live job holds it."""
        now = self._clock()
        key = _lock_key(target, kind)
        with self._connect(immediate=True) as db:
            held = db.execute("SELECT job_id, heartbeat FROM lock WHERE target = ?", (key,)).fetchone()
            if held is not None:
                if now - held[1] <= self._stale_after:
                    raise JobRunning(target, kind, held[0])
                self._interrupt(db, held[0], now)
            job_id = db.execute(
                "INSERT INTO job (target, kind, args, state, created_at) VALUES (?, ?, ?, ?, ?)",
                (target, kind, json.dumps(dict(args), sort_keys=True), JobState.QUEUED, now),
            ).lastrowid
            db.execute("INSERT INTO lock VALUES (?, ?, ?, ?)", (key, job_id, os.getpid(), now))
        return job_id

    def heartbeat(self, job_ids: Sequence[int]) -> None:
        if job_ids:
            with self._connect() as db:
                db.executemany("UPDATE lock SET heartbeat = ? WHERE job_id = ?", [(self._clock(), j) for j in job_ids])

    def held(self, target: str, kind: str) -> bool:
        """Whether a live job (queued or running, in any process) holds the (target, kind) lock."""
        with self._connect() as db:
            row = db.execute("SELECT heartbeat FROM lock WHERE target = ?", (_lock_key(target, kind),)).fetchone()
        return row is not None and self._clock() - row[0] <= self._stale_after

    def start(self, job_id: int) -> None:
        """The job runs; a note it had while queued ("waiting for sync") goes."""
        with self._connect() as db:
            db.execute("UPDATE job SET state = ?, current = '' WHERE id = ?", (JobState.RUNNING, job_id))

    def set_progress(self, job_id: int, done: int, total: int, current: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE job SET done = ?, total = ?, current = ? WHERE id = ?", (done, total, current, job_id))

    def finish(self, job_id: int, state: JobState, errors: Sequence[str] = ()) -> None:
        """End the job and release its lock."""
        with self._connect() as db:
            db.execute(
                "UPDATE job SET state = ?, ended_at = ?, errors = ? WHERE id = ?",
                (state, self._clock(), json.dumps(list(errors)), job_id),
            )
            db.execute("DELETE FROM lock WHERE job_id = ?", (job_id,))

    def dismiss(self, job_ids: Sequence[int]) -> int:
        """Take ended jobs out of the problems (they stay in the recent jobs); returns how many ended jobs
        were found. Unknown and active jobs are left alone."""
        if not job_ids:
            return 0
        with self._connect() as db:
            return db.executemany(
                "UPDATE job SET dismissed = 1 WHERE id = ? AND state NOT IN (?, ?)",
                [(j, JobState.QUEUED, JobState.RUNNING) for j in job_ids],
            ).rowcount

    def reconcile(self) -> int:
        """End active jobs whose lock is gone or stale (their process stopped), as `_interrupt` says; returns how many."""
        now = self._clock()
        with self._connect(immediate=True) as db:
            orphans = [
                job_id
                for job_id, heartbeat in db.execute(
                    "SELECT job.id, lock.heartbeat FROM job LEFT JOIN lock ON lock.job_id = job.id"
                    " WHERE job.state IN (?, ?)",
                    (JobState.QUEUED, JobState.RUNNING),
                )
                if heartbeat is None or now - heartbeat > self._stale_after
            ]
            for job_id in orphans:
                self._interrupt(db, job_id, now)
        return len(orphans)

    def _interrupt(self, db: sqlite3.Connection, job_id: int, now: float) -> None:
        """End a job whose process stopped: interrupted if it had started (a problem), else cancelled
        (it never ran, so nothing is half done; Sync all can simply be run again)."""
        db.execute(
            "UPDATE job SET state = CASE state WHEN ? THEN ? ELSE ? END, ended_at = ? WHERE id = ? AND state IN (?, ?)",
            (JobState.QUEUED, JobState.CANCELLED, JobState.INTERRUPTED, now, job_id, JobState.QUEUED, JobState.RUNNING),
        )
        db.execute("DELETE FROM lock WHERE job_id = ?", (job_id,))

    def jobs(self, limit: int = 20) -> list[JobRow]:
        """Active jobs first, then the most recent."""
        with self._connect() as db:
            rows = db.execute(
                f"SELECT {_COLUMNS} FROM job ORDER BY state IN (?, ?) DESC, id DESC LIMIT ?",
                (JobState.QUEUED, JobState.RUNNING, limit),
            ).fetchall()
        return [_row(r) for r in rows]

    def panel(self, recent: int = 10) -> JobPanel:
        """Active jobs and unresolved problems, then the `recent` newest other jobs.

        A problem is a job that failed, was interrupted, or ended done with item errors.
        It stays until it is dismissed, or a later job of the same kind for the same target (args are
        ignored) ends: a clean run resolves it, and a later problem replaces it, so only
        the newest problem of a (target, kind) shows. Cancelled and active jobs neither
        resolve nor replace one.
        """
        ended = (JobState.DONE, JobState.FAILED, JobState.INTERRUPTED)
        with self._connect() as db:
            active = db.execute(
                f"SELECT {_COLUMNS} FROM job WHERE state IN (?, ?) ORDER BY id DESC", (JobState.QUEUED, JobState.RUNNING)
            ).fetchall()
            problems = db.execute(
                f"SELECT {_COLUMNS} FROM job AS j WHERE NOT j.dismissed"
                " AND (j.state IN (?, ?) OR (j.state = ? AND j.errors != '[]'))"
                " AND NOT EXISTS (SELECT 1 FROM job AS k WHERE k.target = j.target AND k.kind = j.kind"
                " AND k.id > j.id AND k.state IN (?, ?, ?)) ORDER BY j.id DESC",
                (JobState.FAILED, JobState.INTERRUPTED, JobState.DONE, *ended),
            ).fetchall()
            attention = [_row(r) for r in active + problems]
            shown = {j.id for j in attention}
            newest = db.execute(f"SELECT {_COLUMNS} FROM job ORDER BY id DESC LIMIT ?", (recent + len(shown),)).fetchall()
        rest = [row for row in map(_row, newest) if row.id not in shown]
        return JobPanel(tuple(attention), tuple(rest[:recent]))

    def job(self, job_id: int) -> JobRow | None:
        with self._connect() as db:
            r = db.execute(f"SELECT {_COLUMNS} FROM job WHERE id = ?", (job_id,)).fetchone()
        return _row(r) if r else None

    def last_ended(self, target: str, kind: str) -> JobRow | None:
        """The target's most recent job of this kind that ran to the end (done)."""
        with self._connect() as db:
            r = db.execute(
                f"SELECT {_COLUMNS} FROM job WHERE target = ? AND kind = ? AND state = ? ORDER BY id DESC LIMIT 1",
                (target, kind, JobState.DONE),
            ).fetchone()
        return _row(r) if r else None

    def append_log(self, job_id: int, line: str) -> None:
        self._logs.mkdir(exist_ok=True)
        with self.log_path(job_id).open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def log_path(self, job_id: int) -> Path:
        return self._logs / f"{job_id}.log"


def _lock_key(target: str, kind: str) -> str:
    """The lock table's `target` column holds this key; a space never occurs in a slug or a kind."""
    return f"{target} {kind}"


_COLUMNS = "id, target, kind, args, state, created_at, ended_at, done, total, current, errors"


def _row(r: tuple) -> JobRow:
    job_id, target, kind, args, state, created_at, ended_at, done, total, current, errors = r
    return JobRow(
        job_id, target, kind, json.loads(args), JobState(state), created_at, ended_at, done, total, current,
        tuple(json.loads(errors)),
    )  # fmt: skip


class CancelResult(StrEnum):
    REMOVED = "removed"  # it was waiting in a lane: ended cancelled at once
    SIGNALLED = "signalled"  # it had started (or was just starting): it stops at its next item


@dataclass
class _Queued:
    job: Job
    target: str
    work: Work
    waits_for: str | None
    marked: bool = False  # its waiting note is on the board


class _Lane:
    """Jobs that take turns: a FIFO with one worker thread. The first job that is ready runs; one whose
    target holds a `waits_for` lock (in any process, so the board is polled) is passed over meanwhile."""

    def __init__(self, name: str, runner: "JobRunner", poll: float):
        self._runner = runner
        self._poll = poll
        self._queue: list[_Queued] = []
        self._cond = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._work, name=f"job-lane-{name}", daemon=True)
        self._thread.start()

    def put(self, entry: _Queued) -> bool:
        """Queue a job; False once the lane is closed (the caller ends the job)."""
        with self._cond:
            if self._closed:
                return False
            self._queue.append(entry)
            self._cond.notify()
        return True

    def take(self, job_id: int) -> Job | None:
        """Remove a job that has not started; None if it is not queued here (any more)."""
        with self._cond:
            entry = next((e for e in self._queue if e.job.id == job_id), None)
            if entry is not None:
                self._queue.remove(entry)
                self._cond.notify()
        return entry.job if entry else None

    def close(self) -> list[Job]:
        """Stop taking jobs; returns those still queued, now out of the lane."""
        with self._cond:
            self._closed = True
            left, self._queue = [e.job for e in self._queue], []
            self._cond.notify_all()
        return left

    def join(self) -> None:
        """Wait for the worker to finish the job it is running (after `close`)."""
        self._thread.join()

    def _work(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                waiting = list(self._queue)
            try:
                ready = self._first_ready(waiting)
            except sqlite3.Error:
                log.exception("job lane: reading the board")  # the next look retries; the lane carries on
                ready = None
            if ready is None:
                with self._cond:
                    if not self._closed:
                        self._cond.wait(self._poll)
                continue
            with self._cond:
                if ready not in self._queue:  # cancelled meanwhile
                    continue
                self._queue.remove(ready)
            try:
                self._runner._execute(ready.job, ready.work)
            except Exception:
                log.exception("job lane: job %s", ready.job.id)  # its work's errors end the job; this is the board's

    def _first_ready(self, waiting: Sequence[_Queued]) -> _Queued | None:
        """The first job free to start. Each held job before it gets its waiting note, once. A database read:
        done outside the condition, so submit and cancel never wait on it."""
        for e in waiting:
            if e.waits_for is None or not self._runner.board.held(e.target, e.waits_for):
                return e
            if not e.marked:
                self._runner.board.set_progress(e.job.id, 0, 0, f"waiting for {e.waits_for}")
                e.marked = True
        return None


class JobRunner:
    """Runs work under the board's locks: `submit` on worker threads, `run` in the caller's thread.

    A job submitted to a named lane takes its turn there, one at a time, instead of starting at once; with
    `waits_for`, it waits while its target has a job of that kind (queued or running, in any process).
    `poll` is how often a waiting job looks again; `sleep` is the CLI's wait between looks."""

    def __init__(
        self, board: JobBoard, clock: Clock = time.time, poll: float = 2.0, sleep: Callable[[float], None] = time.sleep
    ):
        self.board = board
        self._clock = clock
        self._poll = poll
        self._sleep = sleep
        self._lanes: dict[str, _Lane] = {}
        self._closed = False  # shutting down: no new lanes
        self._threads: list[threading.Thread] = []
        self._active: dict[int, Job] = {}
        self._mutex = threading.Lock()
        self._stop = threading.Event()
        self._beat = threading.Thread(target=self._heartbeats, name="job-heartbeat", daemon=True)
        self._beat.start()

    def submit(
        self, target: str, kind: str, args: Mapping[str, object], work: Work,
        lane: str | None = None, waits_for: str | None = None,
    ) -> int:  # fmt: skip
        """Start work now on its own thread, or queue it in the named lane (created on first use).
        Raises JobRunning if the target already has a job of this kind (in any process)."""
        if waits_for is not None and lane is None:
            raise ValueError("only a lane job can wait for another kind")
        job = self._claim(target, kind, args, echo=None)
        if lane is not None:
            with self._mutex:
                if lane not in self._lanes and not self._closed:
                    self._lanes[lane] = _Lane(lane, self, self._poll)
                turns = self._lanes.get(lane)
            if turns is None or not turns.put(_Queued(job, target, work, waits_for)):
                self._drop(job)  # shutting down: it would never run
            return job.id
        thread = threading.Thread(target=self._execute, args=(job, work), name=f"job-{job.id}")
        with self._mutex:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
        thread.start()
        return job.id

    def run(
        self, target: str, kind: str, args: Mapping[str, object], work: Work, echo: Callable[[str], None],
        waits_for: str | None = None,
    ) -> tuple[JobState, Outcome]:  # fmt: skip
        """Run work now in this thread; with `waits_for`, first wait while the target has a job of that kind.
        Ctrl-C (waiting or running) ends the job as interrupted and is re-raised."""
        job = self._claim(target, kind, args, echo)
        return self._execute(job, work, reraise=True, wait=(target, waits_for) if waits_for else None)

    def cancel(self, job_id: int) -> CancelResult | None:
        """End a queued job of this process at once, or ask a started one to stop at its next item;
        None if the job is not this process's."""
        with self._mutex:
            lanes = list(self._lanes.values())
        for lane in lanes:
            if (job := lane.take(job_id)) is not None:
                self._drop(job)
                return CancelResult.REMOVED
        with self._mutex:
            job = self._active.get(job_id)
        if job is None:
            return None
        job._cancel.set()  # if a lane has just taken it, _execute ends it before it starts
        return CancelResult.SIGNALLED

    def owns(self, job_id: int) -> bool:
        """Whether the job is queued or running in this process, so `cancel` can reach it."""
        with self._mutex:
            return job_id in self._active

    def shutdown(self) -> None:
        """End the queued jobs as cancelled, ask the running ones to stop, and wait for them."""
        with self._mutex:
            self._closed = True
            lanes = list(self._lanes.values())
        for lane in lanes:
            for job in lane.close():
                self._drop(job)
        with self._mutex:
            jobs = list(self._active.values())
        for job in jobs:
            job._cancel.set()
        for lane in lanes:
            lane.join()
        with self._mutex:
            threads = list(self._threads)
        for thread in threads:
            thread.join()
        self._stop.set()

    def _claim(self, target: str, kind: str, args: Mapping[str, object], echo) -> Job:
        job = Job(self.board, self.board.claim(target, kind, args), echo, self._clock)
        with self._mutex:
            self._active[job.id] = job
        return job

    def _drop(self, job: Job) -> None:
        """End a job that never started as cancelled, releasing its lock."""
        with self._mutex:
            self._active.pop(job.id, None)
        job.log("cancelled")
        self.board.finish(job.id, JobState.CANCELLED)

    def _execute(
        self, job: Job, work: Work, reraise: bool = False, wait: tuple[str, str] | None = None
    ) -> tuple[JobState, Outcome]:
        state, outcome = JobState.FAILED, Outcome()
        try:
            if wait is not None:
                self._wait_turn(job, *wait)
            if job._cancel.is_set():
                state = JobState.CANCELLED
                return state, outcome
            self.board.start(job.id)
            outcome = work(job)
            state = JobState.DONE
        except Cancelled:
            state = JobState.CANCELLED
            job.log("cancelled")
        except KeyboardInterrupt:
            state = JobState.INTERRUPTED
            raise
        except Exception as e:
            outcome = Outcome((f"{type(e).__name__}: {e}",))
            job.log(f"failed: {e}")
            if reraise:
                raise
        finally:
            if job.last_progress:  # progress is saved at most once a second; keep where it stopped
                self.board.set_progress(job.id, *job.last_progress)
            self.board.finish(job.id, state, outcome.errors)
            with self._mutex:
                del self._active[job.id]
        return state, outcome

    def _wait_turn(self, job: Job, target: str, kind: str) -> None:
        """The CLI's wait, before the job starts: polled with `sleep`, which Ctrl-C interrupts
        (an untimed lock or condition wait would not, on Windows)."""
        if not self.board.held(target, kind):
            return
        job.log(f"waiting for {kind} of {target}…")
        self.board.set_progress(job.id, 0, 0, f"waiting for {kind}")
        while self.board.held(target, kind) and not job._cancel.is_set():
            self._sleep(self._poll)

    def _heartbeats(self) -> None:
        while not self._stop.wait(HEARTBEAT_EVERY):
            with self._mutex:
                ids = list(self._active)
            try:
                self.board.heartbeat(ids)
                # Also end jobs a stopped process left behind: one that stopped just before this
                # process started still had a fresh heartbeat when startup reconciled.
                self.board.reconcile()
            except sqlite3.Error:
                pass  # the next beat retries; a lock only goes stale after several missed beats
