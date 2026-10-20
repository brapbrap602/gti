import threading

import pytest
from novel_app.jobs import Cancelled, JobBoard, JobRunner, JobRunning, JobState, Outcome


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


def test_job_one_per_novel(board, runner):
    release = threading.Event()
    held = runner.submit("a", "sync", {"novel": "a"}, lambda job: release.wait(5) and Outcome())
    with pytest.raises(JobRunning, match="job already running for a"):
        runner.submit("a", "build-epub", {"novel": "a"}, lambda job: Outcome())
    other = runner.submit("b", "sync", {"novel": "b"}, lambda job: Outcome())
    assert wait_for(board, other).state is JobState.DONE
    release.set()
    assert wait_for(board, held).state is JobState.DONE
    assert wait_for(board, runner.submit("a", "sync", {}, lambda job: Outcome())).state is JobState.DONE


def test_a_lock_whose_heartbeat_expired_can_be_taken(board, clock):
    dead = board.claim("a", "sync", {})  # a process that died while holding the lock
    clock.now += 30
    with pytest.raises(JobRunning):
        board.claim("a", "sync", {})
    clock.now += 31
    board.claim("a", "sync", {})
    assert board.job(dead).state is JobState.INTERRUPTED


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
