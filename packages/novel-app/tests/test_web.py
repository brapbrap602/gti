import asyncio
import re
import threading

import pytest
from fastapi.testclient import TestClient
from novel_app.jobs import JobBoard, JobRunner, JobState
from novel_app.service import Service, app_db
from novel_app.web.app import create_app, job_events

URL = "https://novelbuddy.me/test-novel"


@pytest.fixture
def service(site):
    return Service(JobRunner(JobBoard(app_db())))


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as c:  # runs the lifespan: reconcile at start, shutdown at end
        yield c


def quiet(_line):
    pass


def added(service, novel="test-novel", url=URL):
    """Add a source and fetch all its chapters, even those another source already has."""
    assert service.run("add", quiet, url=url, novel=novel)[0] is JobState.DONE
    source = service.web_sources(novel)[-1].id
    assert service.run("sync", quiet, novel=novel, source=source, refresh="1-1000")[0] is JobState.DONE


def finished(service, job_id):
    gate = threading.Event()
    for _ in range(1000):
        row = service.runner.board.job(job_id)
        if not row.state.active:
            return row
        gate.wait(0.02)
    raise AssertionError(f"job {job_id} did not end")


def test_empty_library(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "The library is empty" in page.text and "No jobs yet" in page.text


def test_library_row_and_novel_grid(client, service):
    added(service)
    page = client.get("/").text
    assert 'href="/novels/test-novel">Test Novel</a>' in page
    assert "3 selected" in page and "lncrawl" in page
    assert re.search(r'name="kind" value="sync"', page)
    assert re.search(r'site:\s*<span class="stale">not built</span>', page)

    novel = client.get("/novels/test-novel").text
    assert 'title="3, official, source 1: Chapter 3"' in novel
    assert "No problems found." in novel


def test_compare_then_pin(client, service, site):
    added(service)
    added(service, url=URL + "/")  # a second source with the same chapters
    page = client.get("/novels/test-novel/compare", params={"number": 2}).text
    assert "The book uses source 1" in page
    assert "Source 2: lncrawl" in page and 'name="numbers" value="2"' in page
    assert 'title="2, official, source 1: Chapter 2"' in client.get("/novels/test-novel").text  # now cached

    pinned = client.post(
        "/novels/test-novel/pin",
        data={"numbers": "2", "source": "2", "back": "/novels/test-novel/compare?number=2"},
        follow_redirects=False,
    )
    assert pinned.status_code == 303 and pinned.headers["location"].startswith("/novels/test-novel/compare?number=2&notice=")
    assert "The book uses source 2" in client.get(pinned.headers["location"]).text
    assert 'title="2, official, source 2, pinned: Chapter 2"' in client.get("/novels/test-novel").text

    bad = client.post("/novels/test-novel/pin", data={"numbers": "two", "source": "2"})
    assert bad.status_code == 400 and "not a range" in bad.text


def test_priority_buttons_reorder_sources(client, service):
    added(service)
    added(service, url=URL + "/")
    moved = client.post("/novels/test-novel/priority", data={"source": "2", "move": "up"}, follow_redirects=False)
    assert moved.status_code == 303
    assert [r.source.id for r in service.priority("test-novel")] == [2, 1]


def test_job_one_per_novel(client, service):
    added(service)
    service.runner.board.claim("test-novel", "sync", {"novel": "test-novel"})  # say, a CLI sync
    refused = client.post("/jobs", data={"kind": "sync", "novel": "test-novel", "back": "/"})
    assert refused.status_code == 409 and "job already running for test-novel" in refused.text
    page = client.get("/").text
    assert re.search(r'<button type="submit" disabled title="Sync is queued \(job \d+\)">Sync</button>', page)
    assert "running in another process" in page

    started = client.post("/jobs", data={"kind": "build-site", "back": "/"}, follow_redirects=False)
    assert started.status_code == 303 and "started+job" in started.headers["location"]


def test_htmx_posts_get_the_notice_in_place(client, service):
    added(service)
    ok = client.post("/jobs", data={"kind": "build-epub", "novel": "test-novel"}, headers={"HX-Request": "true"})
    assert ok.status_code == 200 and "started job" in ok.text and "<html" not in ok.text
    job_id = int(re.search(r"started job (\d+)", ok.text).group(1))
    assert finished(service, job_id).state is JobState.DONE
    assert "volumes built" in client.get(f"/jobs/{job_id}/log").text


def test_job_interrupted_at_startup(site, service):
    dead = JobBoard(app_db(), clock=lambda: 0.0)  # its heartbeat is decades old
    job_id = dead.claim("test-novel", "sync", {"novel": "test-novel"})
    added(service)  # the stale lock does not block new jobs
    with TestClient(create_app(service)) as client:
        assert service.runner.board.job(job_id).state is JobState.INTERRUPTED
        assert f'action="/jobs/{job_id}/rerun"' in client.get("/").text
        again = client.post(f"/jobs/{job_id}/rerun", data={"back": "/"}, follow_redirects=False)
        assert again.status_code == 303
        new = int(re.search(r"started\+job\+(\d+)", again.headers["location"]).group(1))
        assert finished(service, new).args == {"novel": "test-novel"}


def test_cancel_from_the_drawer(client, service, site):
    added(service)
    site.count, site.delay = 300, 0.02
    job_id = service.start("sync", novel="test-novel")
    gate = threading.Event()
    while service.runner.board.job(job_id).done == 0:
        gate.wait(0.02)
    assert f'action="/jobs/{job_id}/cancel"' in client.get("/").text
    assert client.post(f"/jobs/{job_id}/cancel", data={"back": "/"}, follow_redirects=False).status_code == 303
    row = finished(service, job_id)
    assert row.state is JobState.CANCELLED and row.done < 297


def test_unknown_novel_and_job_kind(client):
    assert client.get("/novels/nope").status_code == 400
    assert client.post("/jobs", data={"kind": "deploy-site"}).status_code == 400


def test_cross_site_posts_are_refused(client):
    r = client.post("/jobs", data={"kind": "build-site"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.post("/jobs", data={"kind": "build-site"}, headers={"Origin": "http://testserver"}).status_code == 200


def test_job_events_push_changes_and_starts_and_ends(service):
    board, polls, claimed = service.runner.board, [], []

    async def disconnected():  # called before each poll; drives the board between polls
        polls.append(len(polls) + 1)
        if len(polls) == 2:
            claimed.append(board.claim("other", "sync", {}))
        if len(polls) == 3:
            board.finish(claimed[0], JobState.DONE)
        return len(polls) > 4

    async def collect():
        render = lambda jobs: "|".join(f"{j.id}:{j.state}" for j in jobs)  # noqa: E731
        return [e async for e in job_events(service, render, disconnected, every=0.0)]

    events = asyncio.run(collect())
    assert [e.splitlines()[0] for e in events] == ["event: jobs", "event: jobs", "event: active", "event: jobs", "event: active"]
    assert events[1].split("\n") == ["event: jobs", f"data: {claimed[0]}:queued", "", ""]
