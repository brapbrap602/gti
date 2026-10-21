import re
import threading

import pytest
from fastapi.testclient import TestClient
from novel_app.jobs import JobBoard, JobRunner, JobState
from novel_app.service import Service, app_db
from novel_app.web.app import create_app


@pytest.fixture
def service(openrouter):
    return Service(JobRunner(JobBoard(app_db())))


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as c:
        yield c


def finished(service, job_id):
    gate = threading.Event()
    for _ in range(500):
        row = service.runner.board.job(job_id)
        if not row.state.active:
            return row
        gate.wait(0.02)
    raise AssertionError(f"job {job_id} did not end")


def add_setup(client, **fields) -> int:
    added = client.post("/novels/raw-novel/setups", data={"model": "vendor/cheap", **fields}, follow_redirects=False)
    assert added.status_code == 303, added.text
    return int(re.search(r"source\+(\d+)", added.headers["location"]).group(1))


def test_without_setups_the_add_form_is_open(client):
    page = client.get("/novels/raw-novel").text
    assert '<details class="add-setup" open>' in page and "Add a translator setup to start translating" in page
    assert 'id="translate-form"' not in page
    assert 'id="translate"' not in client.get("/novels/english-only").text


def test_a_new_setup_is_listed_unpublished_with_a_publish_toggle(client, service):
    source = add_setup(client, data_collection="deny")
    page = client.get("/novels/raw-novel").text
    assert f"{source}: vendor/cheap · prompt v1 · parallel, no data collection" in page
    assert f'aria-label="Publish source {source}"' in page

    published = client.post("/novels/raw-novel/publish", data={"source": source, "on": "on"}, follow_redirects=False)
    assert published.status_code == 303
    assert f'aria-label="Unpublish source {source}"' in client.get("/novels/raw-novel").text
    raw = client.post("/novels/raw-novel/publish", data={"source": 1, "on": "on"})
    assert raw.status_code == 200  # raw-zh: the switch exists but the book still never uses it
    bad = client.post("/novels/raw-novel/setups", data={"model": "vendor/cheap", "context": "random"})
    assert bad.status_code == 400 and "context must be one of" in bad.text


def test_start_appears_only_with_an_estimate(client, service, openrouter):
    source = add_setup(client)
    page = client.get("/novels/raw-novel").text
    assert re.search(r'<p class="muted">Enter chapters to see what it would cost.</p>\s*<button type="submit" disabled>Start</button>', page)

    estimate = client.get("/novels/raw-novel/translate/estimate", params={"setup": source, "range": "1-3"}).text
    assert "3 chapters to translate, at most $" in estimate and '<button type="submit">Start</button>' in estimate
    wrong = client.get("/novels/raw-novel/translate/estimate", params={"setup": source, "range": "three"}).text
    assert "not a range" in wrong and "disabled" in wrong

    started = client.post("/jobs", data={"kind": "translate", "novel": "raw-novel", "setup": source, "range": "1-3",
                                         "cap": "0.5", "workers": "2"}, headers={"HX-Request": "true"})  # fmt: skip
    job_id = int(re.search(r"started job (\d+)", started.text).group(1))
    assert finished(service, job_id).state is JobState.DONE
    row = next(r for r in service.setups("raw-novel") if r.source.id == source)
    assert row.chapters == 3 and row.cost > 0
    after = client.get("/novels/raw-novel/translate/estimate", params={"setup": source, "range": "1-3"}).text
    assert "Nothing to translate: 3 already current" in after


def test_stale_chapters_are_linked_from_the_glossary_page(client, service):
    source = add_setup(client)
    state, _ = service.run("translate", lambda _l: None, novel="raw-novel", setup=source, range="1-2")
    assert state is JobState.DONE
    client.post("/novels/raw-novel/glossary", data={"zh": "韩立", "en": "Lord Han", "category": "person"})

    glossary = client.get("/novels/raw-novel/glossary").text
    assert f"source {source}: vendor/cheap · 2 stale" in glossary
    link = f"/novels/raw-novel?setup={source}&range=stale#translate"
    assert link in glossary
    prefilled = client.get(f"/novels/raw-novel?setup={source}&range=stale").text
    assert 'name="range" value="stale"' in prefilled and 'hx-trigger="load,' in prefilled


def test_without_a_key_setups_cannot_be_added(novels, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(create_app(Service(JobRunner(JobBoard(app_db()))))) as c:
        page = c.get("/novels/raw-novel").text
        refused = c.post("/novels/raw-novel/setups", data={"model": "vendor/cheap"})
    assert 'disabled title="set OPENROUTER_API_KEY (and restart nov serve)">Add setup' in page
    assert refused.status_code == 400


def test_the_estimate_shows_unchecked_raws_with_the_reclean_hint(client, openrouter, old_rules):
    source = add_setup(client)
    old_rules([2])
    estimate = client.get("/novels/raw-novel/translate/estimate", params={"setup": source, "range": "1-3"}).text
    assert "2 chapters to translate" in estimate
    assert "1 not checked with current rules" in estimate and "nov reclean raw-novel" in estimate
