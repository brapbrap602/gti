import re

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


def built(service):
    state, _ = service.run("glossary-build", lambda _line: None, novel="raw-novel", model="vendor/cheap")
    assert state is JobState.DONE


def term_id(service, zh):
    return next(t.id for t in service.glossary("raw-novel") if t.zh == zh)


def test_an_empty_glossary_offers_a_build_and_the_add_form(client):
    page = client.get("/novels/raw-novel/glossary").text
    assert "No entries yet" in page
    assert re.search(r'<button type="submit"\s*>Build glossary</button>', page)  # enabled
    assert 'name="zh" required' in page
    assert "Glossary</a>" in client.get("/novels/raw-novel").text and "no entries yet" in client.get("/novels/raw-novel").text


def test_build_starts_from_the_page_and_its_terms_show_up(client, service, openrouter):
    started = client.post("/jobs", data={"kind": "glossary-build", "novel": "raw-novel", "model": "vendor/cheap", "cap": "0.5"},
                          headers={"HX-Request": "true"})  # fmt: skip
    assert started.status_code == 200 and "started job" in started.text
    service.runner.shutdown()  # waits for the job
    page = client.get("/novels/raw-novel/glossary", params={"tab": "all"}).text
    assert "韩立" in page and 'value="Han Li"' in page and "accepted" in page
    assert "<mark>韩立</mark>" in page  # the snippets mark the term
    assert "1 accepted" in client.get("/novels/raw-novel").text


def test_a_row_action_swaps_only_that_row_and_bumps_the_revision(client, service):
    built(service)
    term = term_id(service, "韩立")
    before = service.glossary_page("raw-novel").revision

    swapped = client.post(f"/novels/raw-novel/glossary/{term}", data={"action": "save", "en": "Han Li the Elder"},
                          headers={"HX-Request": "true"})  # fmt: skip
    assert swapped.text.lstrip().startswith(f'<tbody id="term-{term}"')
    assert 'value="Han Li the Elder"' in swapped.text and "✎" in swapped.text
    assert service.glossary_page("raw-novel").revision == before + 1

    locked = client.post(f"/novels/raw-novel/glossary/{term}", data={"action": "lock"}, follow_redirects=False)
    assert locked.status_code == 303
    assert "locked" in client.get("/novels/raw-novel/glossary", params={"tab": "locked"}).text


def test_picking_a_candidate_accepts_it(client, service):
    built(service)
    term = term_id(service, "韩立")
    client.post(f"/novels/raw-novel/glossary/{term}", data={"action": "reject"})
    client.post(f"/novels/raw-novel/glossary/{term}", data={"action": "pick", "en": "Han Li"})
    han = next(t for t in service.glossary("raw-novel") if t.id == term)
    assert (han.en, han.status.value, han.edited) == ("Han Li", "accepted", True)


def test_add_term_bulk_actions_and_details(client, service):
    added = client.post("/novels/raw-novel/glossary", data={"zh": "七玄门", "en": "Seven Mysteries Sect", "category": "sect",
                                                            "aliases": "七玄，玄门"}, follow_redirects=False)  # fmt: skip
    assert added.status_code == 303
    sect = term_id(service, "七玄门")
    assert next(t for t in service.glossary("raw-novel") if t.id == sect).aliases == ("七玄", "玄门")

    client.post(f"/novels/raw-novel/glossary/{sect}", data={"action": "details", "category": "place", "gender": "",
                                                            "notes": "the hero's first sect", "alias": "七玄宗"})  # fmt: skip
    entry = next(t for t in service.glossary("raw-novel") if t.id == sect)
    assert entry.category.value == "place" and entry.notes == "the hero's first sect" and "七玄宗" in entry.aliases

    refused = client.post("/novels/raw-novel/glossary/bulk", data={"action": "lock"})
    assert refused.status_code == 400 and "tick some terms" in refused.text
    client.post("/novels/raw-novel/glossary/bulk", data={"ids": [str(sect)], "action": "reject"})
    assert next(t for t in service.glossary("raw-novel") if t.id == sect).status.value == "rejected"

    duplicate = client.post("/novels/raw-novel/glossary", data={"zh": "七玄门", "en": "x"})
    assert duplicate.status_code == 400 and "already in the glossary" in duplicate.text


def test_search_and_tabs_filter_the_list(client, service):
    built(service)
    client.post("/novels/raw-novel/glossary", data={"zh": "墨大夫", "en": "Doctor Mo", "category": "title"})
    assert "墨大夫" in client.get("/novels/raw-novel/glossary", params={"tab": "locked"}).text
    assert "墨大夫" not in client.get("/novels/raw-novel/glossary", params={"tab": "all", "q": "Han"}).text
    review = client.get("/novels/raw-novel/glossary").text
    assert 'aria-current="page">Needs review' in review and "No terms here." in review


def test_a_novel_without_raws_cannot_build(client):
    page = client.get("/novels/english-only/glossary")
    assert page.status_code == 200 and "has no Chinese raws" in page.text and "disabled" in page.text
    assert 'href="/novels/english-only/glossary"' not in client.get("/novels/english-only").text


def test_without_a_key_build_says_what_to_do(novels, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(create_app(Service(JobRunner(JobBoard(app_db()))))) as c:
        page = c.get("/novels/raw-novel/glossary").text
    assert "set OPENROUTER_API_KEY (and restart nov serve)" in page and "disabled" in page


def test_a_busy_novel_disables_build(client, service):
    service.runner.board.claim("raw-novel", "sync", {"novel": "raw-novel"})
    page = client.get("/novels/raw-novel/glossary").text
    assert re.search(r'<button type="submit" disabled\s+title="novel busy: Sync \(job \d+\)">Build glossary', page)
