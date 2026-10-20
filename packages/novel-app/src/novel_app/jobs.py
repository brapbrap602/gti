"""Jobs: long operations (sync, builds) run one at a time per novel, across processes.

`JobBoard` owns app.sqlite: a row per job (state, progress, errors) and a lock row
per target (a novel slug, or SITE for library-wide builds). A lock is taken with
BEGIN IMMEDIATE and kept alive by a heartbeat; one whose heartbeat is older than
`stale_after` seconds belongs to a dead process and can be taken over. The CLI and
`nov serve` share the board, so either refuses a second job for the same target.

`JobRunner` runs work on a small thread pool (web) or in the calling thread (CLI).
Work receives a `Job` to log lines and report progress; a cancel request is raised
as `Cancelled` from `Job.progress`, so cancelling is cooperative, between items.
"""

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

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


@dataclass(frozen=True)
class Outcome:
    """What finished work reports: per-item errors (failed chapters) that did not stop it."""

    errors: tuple[str, ...] = ()


class JobRunning(Exception):
    def __init__(self, target: str, job_id: int):
        super().__init__(f"job already running for {target} (job {job_id})")
        self.target = target
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
        """A new queued job holding target's lock; raises JobRunning if a live job holds it."""
        now = self._clock()
        with self._connect(immediate=True) as db:
            held = db.execute("SELECT job_id, heartbeat FROM lock WHERE target = ?", (target,)).fetchone()
            if held is not None:
                if now - held[1] <= self._stale_after:
                    raise JobRunning(target, held[0])
                self._interrupt(db, held[0], now)
            job_id = db.execute(
                "INSERT INTO job (target, kind, args, state, created_at) VALUES (?, ?, ?, ?, ?)",
                (target, kind, json.dumps(dict(args), sort_keys=True), JobState.QUEUED, now),
            ).lastrowid
            db.execute("INSERT INTO lock VALUES (?, ?, ?, ?)", (target, job_id, os.getpid(), now))
        return job_id

    def heartbeat(self, job_ids: Sequence[int]) -> None:
        if job_ids:
            with self._connect() as db:
                db.executemany("UPDATE lock SET heartbeat = ? WHERE job_id = ?", [(self._clock(), j) for j in job_ids])

    def start(self, job_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE job SET state = ? WHERE id = ?", (JobState.RUNNING, job_id))

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

    def reconcile(self) -> int:
        """Mark active jobs whose lock is gone or stale interrupted (their process stopped); returns how many."""
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
        db.execute(
            "UPDATE job SET state = ?, ended_at = ? WHERE id = ? AND state IN (?, ?)",
            (JobState.INTERRUPTED, now, job_id, JobState.QUEUED, JobState.RUNNING),
        )
        db.execute("DELETE FROM lock WHERE job_id = ?", (job_id,))

    def jobs(self, limit: int = 20) -> list[JobRow]:
        """Active jobs first, then the most recent."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM job ORDER BY state IN (?, ?) DESC, id DESC LIMIT ?",
                (JobState.QUEUED, JobState.RUNNING, limit),
            ).fetchall()
        return [_row(r) for r in rows]

    def panel(self, recent: int = 10) -> JobPanel:
        """Active jobs and unresolved problems, then the `recent` newest other jobs.

        A problem is a job that failed, was interrupted, or ended done with item errors.
        It stays until a later job of the same kind for the same target (args are
        ignored) ends: a clean run resolves it, and a later problem replaces it, so only
        the newest problem of a (target, kind) shows. Cancelled and active jobs neither
        resolve nor replace one.
        """
        ended = (JobState.DONE, JobState.FAILED, JobState.INTERRUPTED)
        with self._connect() as db:
            active = db.execute(
                "SELECT * FROM job WHERE state IN (?, ?) ORDER BY id DESC", (JobState.QUEUED, JobState.RUNNING)
            ).fetchall()
            problems = db.execute(
                "SELECT * FROM job AS j WHERE (j.state IN (?, ?) OR (j.state = ? AND j.errors != '[]'))"
                " AND NOT EXISTS (SELECT 1 FROM job AS k WHERE k.target = j.target AND k.kind = j.kind"
                " AND k.id > j.id AND k.state IN (?, ?, ?)) ORDER BY j.id DESC",
                (JobState.FAILED, JobState.INTERRUPTED, JobState.DONE, *ended),
            ).fetchall()
            attention = [_row(r) for r in active + problems]
            shown = {j.id for j in attention}
            newest = db.execute("SELECT * FROM job ORDER BY id DESC LIMIT ?", (recent + len(shown),)).fetchall()
        rest = [row for row in map(_row, newest) if row.id not in shown]
        return JobPanel(tuple(attention), tuple(rest[:recent]))

    def job(self, job_id: int) -> JobRow | None:
        with self._connect() as db:
            r = db.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
        return _row(r) if r else None

    def last_ended(self, target: str, kind: str) -> JobRow | None:
        """The target's most recent job of this kind that ran to the end (done)."""
        with self._connect() as db:
            r = db.execute(
                "SELECT * FROM job WHERE target = ? AND kind = ? AND state = ? ORDER BY id DESC LIMIT 1",
                (target, kind, JobState.DONE),
            ).fetchone()
        return _row(r) if r else None

    def append_log(self, job_id: int, line: str) -> None:
        self._logs.mkdir(exist_ok=True)
        with self.log_path(job_id).open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def log_path(self, job_id: int) -> Path:
        return self._logs / f"{job_id}.log"


def _row(r: tuple) -> JobRow:
    job_id, target, kind, args, state, created_at, ended_at, done, total, current, errors = r
    return JobRow(
        job_id, target, kind, json.loads(args), JobState(state), created_at, ended_at, done, total, current,
        tuple(json.loads(errors)),
    )  # fmt: skip


class JobRunner:
    """Runs work under the board's locks: `submit` on worker threads, `run` in the caller's thread."""

    def __init__(self, board: JobBoard, workers: int = 2, clock: Clock = time.time):
        self.board = board
        self._clock = clock
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._active: dict[int, Job] = {}
        self._mutex = threading.Lock()
        self._stop = threading.Event()
        self._beat = threading.Thread(target=self._heartbeats, name="job-heartbeat", daemon=True)
        self._beat.start()

    def submit(self, target: str, kind: str, args: Mapping[str, object], work: Work) -> int:
        """Queue work; raises JobRunning if the target already has a job (in any process)."""
        job = self._claim(target, kind, args, echo=None)
        self._pool.submit(self._execute, job, work)
        return job.id

    def run(
        self, target: str, kind: str, args: Mapping[str, object], work: Work, echo: Callable[[str], None]
    ) -> tuple[JobState, Outcome]:
        """Run work now in this thread. Ctrl-C ends the job as interrupted and is re-raised."""
        job = self._claim(target, kind, args, echo)
        return self._execute(job, work, reraise=True)

    def cancel(self, job_id: int) -> bool:
        """Ask a job of this process to stop at its next item; False if it is not running here."""
        with self._mutex:
            job = self._active.get(job_id)
        if job is None:
            return False
        job._cancel.set()
        return True

    def owns(self, job_id: int) -> bool:
        """Whether the job is queued or running in this process, so `cancel` can reach it."""
        with self._mutex:
            return job_id in self._active

    def shutdown(self) -> None:
        """Cancel this process's jobs and wait for them to stop."""
        with self._mutex:
            jobs = list(self._active.values())
        for job in jobs:
            job._cancel.set()
        self._pool.shutdown(wait=True)
        self._stop.set()

    def _claim(self, target: str, kind: str, args: Mapping[str, object], echo) -> Job:
        job = Job(self.board, self.board.claim(target, kind, args), echo, self._clock)
        with self._mutex:
            self._active[job.id] = job
        return job

    def _execute(self, job: Job, work: Work, reraise: bool = False) -> tuple[JobState, Outcome]:
        state, outcome = JobState.FAILED, Outcome()
        try:
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

    def _heartbeats(self) -> None:
        while not self._stop.wait(HEARTBEAT_EVERY):
            with self._mutex:
                ids = list(self._active)
            try:
                self.board.heartbeat(ids)
            except sqlite3.Error:
                pass  # the next beat retries; a lock only goes stale after several missed beats
