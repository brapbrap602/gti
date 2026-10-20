import os
import subprocess
import sys
import threading

import pytest
from novel_app.jobs import JobBoard, JobRunner, JobRunning, JobState
from novel_app.library import novel_dir
from novel_app.service import Service, UserError, app_db
from novel_core import KeyRange, Kind, NovelStore, SourceSpec

URL = "https://novelbuddy.me/test-novel"


@pytest.fixture
def service(site):
    s = Service(JobRunner(JobBoard(app_db())))
    yield s
    s.runner.shutdown()


def finished(service, job_id, timeout=20.0):
    gate = threading.Event()
    for _ in range(int(timeout / 0.02)):
        row = service.runner.board.job(job_id)
        if not row.state.active:
            return row
        gate.wait(0.02)
    raise AssertionError(f"job {job_id} did not end")


def added(service, novel):
    state, _ = service.run("add", lambda _l: None, url=URL, novel=novel)
    assert state is JobState.DONE


def test_two_jobs(service, site):
    """A sync of one novel and an EPUB build of another run at once on real SQLite files."""
    added(service, "a")
    added(service, "b")
    service.run("sync", lambda _l: None, novel="b")
    site.count, site.delay = 40, 0.01

    sync = service.start("sync", novel="a")
    build = service.start("build-epub", novel="b")
    rows = [finished(service, sync), finished(service, build)]
    assert [r.state for r in rows] == [JobState.DONE, JobState.DONE], [r.errors for r in rows]
    assert (rows[0].done, rows[0].total) == (40, 40)
    assert "fetched 40: 40 stored" in service.runner.board.log_path(sync).read_text(encoding="utf-8")


def test_job_lock_cross_process(service, site, tmp_path):
    added(service, "a")
    service.runner.board.claim("a", "sync", {"novel": "a"})  # this process holds the lock (fresh heartbeat)
    cli = subprocess.run(
        [sys.executable, "-c", "from novel_app.cli import app; app()", "sync", "a"],
        capture_output=True, text=True, env={**os.environ}, timeout=120,
    )  # fmt: skip
    assert cli.returncode == 1 and "job already running for a" in cli.stderr, cli.stdout + cli.stderr

    later = JobBoard(app_db(), clock=lambda: 10**12)  # long after the heartbeat
    later.claim("a", "sync", {})


def test_bad_input_is_refused_before_a_job_starts(service, site):
    with pytest.raises(UserError, match="no novel"):
        service.start("sync", novel="nope")
    added(service, "a")
    with pytest.raises(UserError, match="not a range"):
        service.start("sync", novel="a", refresh="x-y")
    with NovelStore.open(novel_dir("a")) as store:
        raw = store.upsert_source(SourceSpec("import:mtl", "file:///raw", "zh", Kind.RAW_ZH))
    with pytest.raises(UserError, match="raw-zh"):
        service.pin("a", KeyRange(1, 2), raw)
    assert service.runner.board.jobs()[0].kind == "add"  # nothing else was queued


def test_rerun_repeats_a_job_with_its_arguments(service, site):
    added(service, "a")
    site.fail = {2}
    first = finished(service, service.start("sync", novel="a"))
    assert first.state is JobState.DONE
    assert first.errors == ("/test-novel/chapter-2: /test-novel/chapter-2: HTTP 500 after 3 attempts",)
    site.fail = set()
    again = finished(service, service.rerun(first.id))
    assert (again.kind, again.args, again.errors) == ("sync", {"novel": "a"}, ())
    service.runner.board.claim("a", "sync", {})  # say, a CLI sync
    with pytest.raises(JobRunning):
        service.rerun(first.id)
