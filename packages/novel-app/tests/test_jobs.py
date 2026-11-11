import re
import sqlite3
import threading

import pytest
from novel_app.jobs import CancelResult, Cancelled, JobBoard, JobPanel, JobRunner, JobRunning, JobState, Outcome


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def board(tmp_path, clock):
    return JobBoard(tmp_path / "app.sqlite", clock=clock)


@pytest.fixture
def runner(board):
    r = JobRunner(board)
    yield r
    r.shutdown()


def wait_for(board, job_id, timeout=10.0):
    gate = threading.Event()
    for _ in range(int(timeout / 0.02)):
        if not board.job(job_id).state.active:
            return board.job(job_id)
        gate.wait(0.02)
    raise AssertionError(f"job {job_id} still {board.job(job_id).state}")


def test_one_job_per_novel_and_kind(board, runner):
    release = threading.Event()
    held = runner.submit("a", "sync", {"novel": "a"}, lambda job: release.wait(5) and Outcome())
    with pytest.raises(JobRunning, match="sync already running for a"):
        runner.submit("a", "sync", {"novel": "a"}, lambda job: Outcome())
    beside = runner.submit("a", "build-epub", {"novel": "a"}, lambda job: Outcome())  # another kind runs alongside
    assert wait_for(board, beside).state is JobState.DONE
    other = runner.submit("b", "sync", {"novel": "b"}, lambda job: Outcome())
    assert wait_for(board, other).state is JobState.DONE
    release.set()
    assert wait_for(board, held).state is JobState.DONE
    assert wait_for(board, runner.submit("a", "sync", {}, lambda job: Outcome())).state is JobState.DONE


def test_jobs_run_at_once_but_lane_jobs_queue(board, runner):
    release, started = threading.Event(), threading.Semaphore(0)

    def blocking(job):
        started.release()
        release.wait(5)
        return Outcome()

    plain = [runner.submit(f"n{i}", "sync", {}, blocking) for i in range(5)]
    for _ in plain:  # all five are running together; a fixed pool would stall here
        assert started.acquire(timeout=5)
    first = runner.submit("a", "build-audio", {}, blocking, lane="audio")
    assert started.acquire(timeout=5)
    second = runner.submit("b", "build-audio", {}, blocking, lane="audio")
    assert not started.acquire(timeout=0.3)  # waits behind the first audio job
    assert board.job(second).state is JobState.QUEUED
    release.set()
    assert all(wait_for(board, j).state is JobState.DONE for j in [*plain, first, second])


def test_a_lock_whose_heartbeat_expired_can_be_taken(board, clock):
    queued = board.claim("a", "sync", {})  # a process that died while its job waited its turn
    clock.now += 30
    with pytest.raises(JobRunning):
        board.claim("a", "sync", {})
    clock.now += 31
    started = board.claim("a", "sync", {})
    board.start(started)  # this one died while running
    clock.now += 61
    board.claim("a", "sync", {})
    assert board.job(queued).state is JobState.CANCELLED  # it never started: not a problem
    assert board.job(started).state is JobState.INTERRUPTED


def test_reconcile_cancels_jobs_that_never_started_and_interrupts_running_ones(board, clock):
    queued = board.claim("a", "sync", {})
    running = board.claim("b", "sync", {})
    board.start(running)
    clock.now += 61

    assert board.reconcile() == 2

    assert board.job(queued).state is JobState.CANCELLED and board.job(running).state is JobState.INTERRUPTED
    assert ids(board.panel().attention) == [running]


def test_job_interrupted_at_startup(board, clock):
    dead = board.claim("a", "sync", {})
    board.start(dead)
    live = board.claim("b", "sync", {})  # another process, still beating
    clock.now += 61
    board.heartbeat([live])
    assert board.reconcile() == 1
    assert board.job(dead).state is JobState.INTERRUPTED
    assert board.job(live).state is JobState.QUEUED
    board.claim("a", "sync", {})  # the dead job's lock is gone


def test_a_running_process_ends_jobs_left_by_one_that_stopped(board, clock, monkeypatch):
    """A restart within STALE_AFTER: startup's reconcile still saw the dead job's heartbeat as fresh."""
    monkeypatch.setattr("novel_app.jobs.HEARTBEAT_EVERY", 0.02)
    dead = board.claim("a", "sync", {})
    board.start(dead)
    runner = JobRunner(board, clock=clock)
    try:
        assert board.reconcile() == 0
        clock.now += 61
        gate = threading.Event()
        for _ in range(250):
            if board.job(dead).state is JobState.INTERRUPTED:
                break
            gate.wait(0.02)
        assert board.job(dead).state is JobState.INTERRUPTED
    finally:
        runner.shutdown()


def test_cancel_stops_work_at_its_next_item(board, runner):
    started, seen = threading.Event(), []

    def work(job):
        for i in range(1, 1000):
            seen.append(i)
            started.set()
            job.progress(i, 999, f"item {i}")
            threading.Event().wait(0.01)
        return Outcome()

    job_id = runner.submit("a", "sync", {}, work)
    started.wait(5)
    assert runner.cancel(job_id)
    row = wait_for(board, job_id)
    assert row.state is JobState.CANCELLED and len(seen) < 999
    assert (row.done, row.current) == (seen[-1], f"item {seen[-1]}")  # where it stopped, not the last 1 s save
    assert "cancelled" in board.log_path(job_id).read_text(encoding="utf-8")


def test_failures_end_the_job_and_release_the_lock(board, runner):
    def boom(job):
        raise RuntimeError("disk full")

    row = wait_for(board, runner.submit("a", "sync", {}, boom))
    assert row.state is JobState.FAILED and row.errors == ("RuntimeError: disk full",)
    row = wait_for(board, runner.submit("a", "sync", {}, lambda job: Outcome(("ch 2: HTTP 500",))))
    assert row.state is JobState.DONE and row.errors == ("ch 2: HTTP 500",)


def test_run_in_the_callers_thread_echoes_and_keeps_progress(board, runner):
    lines = []

    def work(job):
        job.log("index: 3 new")
        for i in (1, 2, 3):
            job.progress(i, 3, f"Chapter {i}")
        return Outcome()

    state, outcome = runner.run("a", "sync", {"novel": "a"}, work, lines.append)
    assert state is JobState.DONE and outcome == Outcome()
    assert lines == ["index: 3 new", "  [1/3] Chapter 1", "  [3/3] Chapter 3"]
    (row,) = board.jobs()
    assert (row.kind, row.args, row.done, row.total, row.current) == ("sync", {"novel": "a"}, 3, 3, "Chapter 3")
    with pytest.raises(KeyboardInterrupt):
        runner.run("a", "sync", {}, lambda job: (_ for _ in ()).throw(KeyboardInterrupt), lines.append)
    assert board.jobs()[0].state is JobState.INTERRUPTED


def test_the_log_gets_a_line_as_each_item_starts(board, runner):
    def work(job):
        for i in (1, 2):
            for sentence in (0, 1, 2):  # progress within an item, like an audio chapter's sentences
                job.progress(i, 2, f"chapter {i} · sentence {sentence}/2")
        return Outcome()

    runner.run("a", "build-audio", {}, work, lambda line: None)
    lines = board.log_path(board.jobs()[0].id).read_text(encoding="utf-8").splitlines()
    assert [line.split(" ", 1)[1] for line in lines] == ["[1/2] chapter 1 · sentence 0/2", "[2/2] chapter 2 · sentence 0/2"]
    assert all(re.fullmatch(r"\d\d:\d\d:\d\d", line.split(" ", 1)[0]) for line in lines)


def test_jobs_list_active_first(board, runner):
    done = wait_for(board, runner.submit("a", "sync", {}, lambda job: Outcome()))
    queued = board.claim("b", "sync", {})
    assert [j.id for j in board.jobs()] == [queued, done.id]
    assert board.last_ended("a", "sync").id == done.id and board.last_ended("b", "sync") is None


def test_cancelled_raises_from_progress_only(board):
    runner = JobRunner(board)
    try:
        def work(job):
            runner.cancel(job.id)
            job.log("still running")
            with pytest.raises(Cancelled):
                job.progress(1, 2)
            return Outcome()

        assert runner.run("a", "sync", {}, work, lambda _l: None)[0] is JobState.DONE
    finally:
        runner.shutdown()


def ended(board, target: str, state: JobState, kind: str = "sync", errors: tuple[str, ...] = ()) -> int:
    job_id = board.claim(target, kind, {})
    board.start(job_id)
    board.finish(job_id, state, errors)
    return job_id


def ids(rows) -> list[int]:
    return [r.id for r in rows]


def test_panel_keeps_active_jobs_and_problems_and_folds_the_rest(board):
    running = board.claim("run", "sync", {})
    board.start(running)
    failed = ended(board, "f", JobState.FAILED)
    interrupted = ended(board, "i", JobState.INTERRUPTED)
    done = [ended(board, f"d{i}", JobState.DONE) for i in range(12)]
    cancelled = ended(board, "c", JobState.CANCELLED)

    panel = board.panel()

    assert isinstance(panel, JobPanel)
    assert ids(panel.attention) == [running, interrupted, failed]
    assert ids(panel.recent) == [cancelled, *reversed(done[3:])]


def test_panel_keeps_an_old_problem_however_many_jobs_follow(board):
    failed = ended(board, "x", JobState.FAILED)
    for i in range(25):
        ended(board, f"other{i}", JobState.DONE)

    assert ids(board.panel().attention) == [failed]


def test_a_later_clean_run_resolves_a_problem(board):
    failed = ended(board, "x", JobState.FAILED)
    clean = ended(board, "x", JobState.DONE)

    panel = board.panel()

    assert panel.attention == ()
    assert ids(panel.recent) == [clean, failed]


def test_cancelling_or_another_kind_does_not_resolve_a_problem(board):
    failed = ended(board, "x", JobState.FAILED)
    ended(board, "x", JobState.CANCELLED)
    ended(board, "x", JobState.DONE, kind="build-epub")

    assert ids(board.panel().attention) == [failed]


def test_only_the_newest_problem_of_a_job_shows(board):
    ended(board, "x", JobState.FAILED)
    newer = ended(board, "x", JobState.FAILED)

    assert ids(board.panel().attention) == [newer]


def test_a_run_with_item_errors_is_a_problem_that_replaces_but_does_not_resolve(board):
    partial = ended(board, "x", JobState.DONE, errors=("ch 5: HTTP 500",) * 40)
    ended(board, "y", JobState.FAILED)
    partial_y = ended(board, "y", JobState.DONE, errors=("ch 9: HTTP 500",))

    assert ids(board.panel().attention) == [partial_y, partial]


def test_a_dismissed_problem_leaves_attention_for_recent(board):
    running = board.claim("run", "sync", {})
    board.start(running)
    failed = ended(board, "x", JobState.FAILED)
    kept = ended(board, "y", JobState.INTERRUPTED)

    board.dismiss([failed, running])  # an active job cannot be dismissed

    panel = board.panel()
    assert ids(panel.attention) == [running, kept]
    assert ids(panel.recent) == [failed]


def test_a_new_problem_shows_after_an_older_one_was_dismissed(board):
    board.dismiss([ended(board, "x", JobState.FAILED)])
    again = ended(board, "x", JobState.FAILED)

    assert ids(board.panel().attention) == [again]


def test_dismiss_counts_only_ended_jobs(board):
    running = board.claim("run", "sync", {})
    failed = ended(board, "x", JobState.FAILED)

    assert board.dismiss([running, failed, 999]) == 1
    assert board.dismiss([]) == 0


def test_a_board_from_before_dismissing_gains_it_and_keeps_its_jobs(tmp_path, clock):
    path = tmp_path / "app.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE job (id INTEGER PRIMARY KEY, target TEXT NOT NULL, kind TEXT NOT NULL, args TEXT NOT NULL,"
            " state TEXT NOT NULL, created_at REAL NOT NULL, ended_at REAL,"
            " done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,"
            " current TEXT NOT NULL DEFAULT '', errors TEXT NOT NULL DEFAULT '[]')"
        )
        db.execute("INSERT INTO job (target, kind, args, state, created_at) VALUES ('x', 'sync', '{}', 'failed', 1)")
    db.close()

    board = JobBoard(path, clock=clock)
    (old,) = board.panel().attention
    board.dismiss([old.id])

    assert JobBoard(path, clock=clock).panel().attention == ()


# -- lanes: one job at a time each, a job waiting while its novel syncs ------------------------

POLL = 0.02  # the lanes' and the CLI's poll of locks held by other processes


@pytest.fixture
def lanes(board):
    r = JobRunner(board, poll=POLL)
    yield r
    r.shutdown()


class Gate:
    """Work that reports it started, then blocks until released."""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, job):
        self.started.set()
        assert self.release.wait(10)
        return Outcome()


def started(board, job_id, timeout=10.0) -> bool:
    gate = threading.Event()
    for _ in range(int(timeout / 0.02)):
        if board.job(job_id).state is not JobState.QUEUED:
            return True
        gate.wait(0.02)
    return False


def test_a_lane_runs_its_jobs_one_at_a_time_in_order(board, lanes):
    first, second = Gate(), Gate()
    s1 = lanes.submit("a", "sync", {}, first, lane="sync")
    s2 = lanes.submit("b", "sync", {}, second, lane="sync")
    assert first.started.wait(5)
    assert not second.started.wait(0.2) and board.job(s2).state is JobState.QUEUED

    first.release.set()

    assert second.started.wait(5)
    assert wait_for(board, s1).state is JobState.DONE
    second.release.set()
    assert wait_for(board, s2).state is JobState.DONE


def test_an_audio_build_waits_while_its_novel_syncs_and_others_overtake_it(board, lanes):
    sync_x = board.claim("x", "sync", {})  # queued or running, here or in another process: the lock is held
    x, y = Gate(), Gate()
    audio_x = lanes.submit("x", "build-audio", {}, x, lane="audio", waits_for="sync")
    audio_y = lanes.submit("y", "build-audio", {}, y, lane="audio", waits_for="sync")

    assert y.started.wait(5)  # Y overtakes X, which waits
    assert board.job(audio_x).state is JobState.QUEUED and board.job(audio_x).current == "waiting for sync"
    y.release.set()
    assert wait_for(board, audio_y).state is JobState.DONE
    assert not x.started.wait(0.2)

    board.finish(sync_x, JobState.DONE)

    assert x.started.wait(5)
    assert board.job(audio_x).current == ""  # starting clears the waiting note
    x.release.set()
    assert wait_for(board, audio_x).state is JobState.DONE


def test_a_sync_in_another_process_holds_an_audio_build_too(board, lanes, tmp_path, clock):
    cli = JobBoard(tmp_path / "app.sqlite", clock=clock)
    sync_x = cli.claim("x", "sync", {})
    cli.start(sync_x)
    x = Gate()
    audio_x = lanes.submit("x", "build-audio", {}, x, lane="audio", waits_for="sync")
    assert not x.started.wait(0.2)

    cli.finish(sync_x, JobState.DONE)

    assert x.started.wait(5)
    x.release.set()
    assert wait_for(board, audio_x).state is JobState.DONE


def test_a_stale_sync_lock_does_not_hold_an_audio_build(board, lanes, clock):
    board.claim("x", "sync", {})  # its process died a while ago
    clock.now += 61
    assert wait_for(board, lanes.submit("x", "build-audio", {}, lambda job: Outcome(), lane="audio",
                                        waits_for="sync")).state is JobState.DONE  # fmt: skip


def test_cancelling_a_waiting_job_ends_it_at_once(board, lanes):
    sync_x = board.claim("x", "sync", {})
    audio_x = lanes.submit("x", "build-audio", {}, lambda job: Outcome(), lane="audio", waits_for="sync")

    assert lanes.cancel(audio_x) is CancelResult.REMOVED

    assert board.job(audio_x).state is JobState.CANCELLED
    assert board.job(sync_x).state is JobState.QUEUED


def test_cancelling_a_queued_job_frees_its_novel_while_the_lane_is_busy(board, lanes):
    busy = Gate()
    s1 = lanes.submit("a", "sync", {}, busy, lane="sync")
    assert busy.started.wait(5)
    s2 = lanes.submit("b", "sync", {}, lambda job: Outcome(), lane="sync")

    assert lanes.cancel(s2) is CancelResult.REMOVED

    assert board.job(s2).state is JobState.CANCELLED and board.job(s1).state is JobState.RUNNING
    assert not lanes.owns(s2) and lanes.cancel(s2) is None
    assert board.log_path(s2).read_text(encoding="utf-8").splitlines()[-1] == "cancelled"
    again = Gate()  # a click on Sync starts B straight away, beside the lane
    b = lanes.submit("b", "sync", {}, again)
    assert again.started.wait(5) and board.job(b).state is JobState.RUNNING
    again.release.set()
    busy.release.set()
    assert wait_for(board, s1).state is JobState.DONE and wait_for(board, b).state is JobState.DONE


def test_cancelling_a_started_job_asks_it_to_stop(board, lanes):
    def work(job):
        while True:
            job.progress(1, 2)
            threading.Event().wait(0.01)

    job_id = lanes.submit("a", "sync", {}, work, lane="sync")
    assert started(board, job_id)

    assert lanes.cancel(job_id) is CancelResult.SIGNALLED
    assert wait_for(board, job_id).state is JobState.CANCELLED


def test_shutdown_cancels_queued_and_waiting_jobs_which_are_not_problems(board, clock):
    runner = JobRunner(board, poll=POLL)

    def work(job):
        while True:
            job.progress(1, 2)
            threading.Event().wait(0.01)

    s1 = runner.submit("a", "sync", {}, work, lane="sync")
    assert started(board, s1)
    s2, s3 = (runner.submit(n, "sync", {}, lambda job: Outcome(), lane="sync") for n in ("b", "c"))
    board.claim("x", "sync", {})
    audio_x = runner.submit("x", "build-audio", {}, lambda job: Outcome(), lane="audio", waits_for="sync")

    runner.shutdown()

    assert board.job(s1).state is JobState.CANCELLED
    assert [board.job(j).state for j in (s2, s3, audio_x)] == [JobState.CANCELLED] * 3
    assert not {s2, s3, audio_x} & set(ids(board.panel().problem_jobs))
    assert not [t for t in threading.enumerate() if t.name.startswith("job-lane-")]  # the lane workers are gone


def test_the_cli_waits_for_a_sync_then_builds(board, lanes):
    sync_x = board.claim("x", "sync", {})
    lines, built = [], threading.Event()

    def build(job):
        built.set()
        return Outcome()

    cli = threading.Thread(target=lambda: lanes.run("x", "build-audio", {}, build, lines.append, waits_for="sync"))
    cli.start()
    gate = threading.Event()
    for _ in range(250):
        if board.jobs()[0].kind == "build-audio" and board.jobs()[0].current == "waiting for sync":
            break
        gate.wait(0.02)
    assert board.jobs()[0].current == "waiting for sync" and not built.is_set()

    board.finish(sync_x, JobState.DONE)

    cli.join(5)
    assert built.is_set() and lines.count("waiting for sync of x…") == 1


def test_ctrl_c_while_the_cli_waits_ends_the_job_interrupted(board):
    board.claim("x", "sync", {})

    def interrupted(_seconds):
        raise KeyboardInterrupt

    runner = JobRunner(board, sleep=interrupted)
    try:
        with pytest.raises(KeyboardInterrupt):
            runner.run("x", "build-audio", {}, lambda job: Outcome(), lambda _l: None, waits_for="sync")
    finally:
        runner.shutdown()
    (audio,) = (j for j in board.jobs() if j.kind == "build-audio")
    assert audio.state is JobState.INTERRUPTED
    board.claim("x", "build-audio", {})  # its lock was released
