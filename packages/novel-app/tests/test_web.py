import asyncio
import re
import threading

import pytest
from fastapi.testclient import TestClient
from novel_app.jobs import JobBoard, JobRunner, JobState
from novel_app.service import Service, app_db
from novel_app.web.app import create_app, job_events
from novel_app.library import novel_dir
from novel_core import Finding, Kind, NewVersion, NovelStore, Paragraph, SourceItem, SourceSpec
from novel_sources.backends import zh_rules

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
    assert "3 selected" in page
    assert re.search(r'name="kind" value="sync"', page)
    assert '<span class="out out--missing" title="site: not built">site not built</span>' in page
    assert '<li title="https://novelbuddy.me/test-novel">novelbuddy.me <span class="muted">official-en</span></li>' in page

    novel = client.get("/novels/test-novel").text
    assert 'title="3, official, source 1: Chapter 3"' in novel
    assert "No problems found." in novel


def test_library_counts_leave_out_unpublished_sources(client, service):
    added(service)
    with NovelStore.open(novel_dir("test-novel")) as store:
        mine = store.upsert_source(SourceSpec("translate:test", "test:setup", "en", Kind.MY_TRANSLATION), published=False)
        store.record_index(mine, [SourceItem("n1", 1, "Chapter 1")])
        store.put_version(mine, "n1", NewVersion("Chapter 1", (Paragraph.of("one"),)))
    page = client.get("/").text
    assert "<li>3 official-en</li>" in page and "<li>1 my-translation</li>" not in page

    with NovelStore.open(novel_dir("test-novel")) as store:
        store.set_published(mine, True)
    assert "<li>1 my-translation</li>" in client.get("/").text


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

    assert 'aria-label="Unpin 2–2"' in client.get("/novels/test-novel").text
    unpinned = client.post("/novels/test-novel/unpin", data={"numbers": "2-2"}, follow_redirects=False)
    assert unpinned.status_code == 303
    novel = client.get(unpinned.headers["location"]).text
    assert 'title="2, official, source 1: Chapter 2"' in novel and "Unpin" not in novel
    again = client.post("/novels/test-novel/unpin", data={"numbers": "2"})
    assert again.status_code == 400 and "nothing in 2-2 is pinned" in again.text


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



def test_retag_from_the_build_menu(client, service):
    added(service)
    assert 'name="kind" value="audio-retag"' in client.get("/novels/test-novel").text
    ok = client.post("/jobs", data={"kind": "audio-retag", "novel": "test-novel"}, headers={"HX-Request": "true"})
    assert "started job" in ok.text and "Retag MP3s test-novel" in ok.text
    job_id = int(re.search(r"started job (\d+)", ok.text).group(1))
    assert finished(service, job_id).state is JobState.DONE
    assert "test-novel: 0 chapter MP3s tagged" in client.get(f"/jobs/{job_id}/log").text

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
        render = lambda panel: "|".join(f"{j.id}:{j.state}" for j in panel.attention + panel.recent)  # noqa: E731
        return [e async for e in job_events(service, render, disconnected, every=0.0)]

    events = asyncio.run(collect())
    assert [e.splitlines()[0] for e in events] == ["event: jobs", "event: jobs", "event: active", "event: jobs", "event: active"]
    assert events[1].split("\n") == ["event: jobs", f"data: {claimed[0]}:queued", "", ""]


def test_jobs_panel_shows_attention_then_recent(client, service):
    board = service.runner.board

    def ended(target, state):
        job_id = board.claim(target, "sync", {})
        board.finish(job_id, state)
        return job_id

    running = board.claim("run", "sync", {})
    board.start(running)
    failed, interrupted = ended("f", JobState.FAILED), ended("i", JobState.INTERRUPTED)
    done = [ended(f"d{i}", JobState.DONE) for i in range(12)]
    cancelled = ended("c", JobState.CANCELLED)

    page = client.get("/").text

    panel = re.search(r'<div id="jobs".*?</aside>', page, re.S).group(0)
    jobs = re.findall(r'<li class="job job--(\w+)( job--recent)?" data-job="(\d+)"', panel)
    assert [(int(i), bool(r)) for _, r, i in jobs] == [
        (running, False), (interrupted, False), (failed, False),
        (cancelled, True), *((d, True) for d in reversed(done[3:])),
    ]  # fmt: skip
    assert re.search(r"<h3[^>]*><button[^>]*>Recent \(10\)</button></h3>", panel)
    board.finish(running, JobState.DONE)


def test_table_cells_carry_labels_for_phones(client, service):
    added(service)

    for path, table in (("/", "library"), ("/novels/test-novel", "sources-table")):
        html = re.search(rf'<table class="{table}">.*?</table>', client.get(path).text, re.S).group(0)
        body = html.split("<tbody>", 1)[1]
        cells = re.findall(r"<td(?: [^>]*)?>", body)
        assert cells and all("data-label=" in c for c in cells), (path, cells)


def compare_page(client, slug: str, number: int = 1) -> str:
    page = client.get(f"/novels/{slug}/compare", params={"number": number})
    assert page.status_code == 200
    return page.text


def test_compare_marks_a_changed_word_and_links_to_it(client, two_texts):
    two_texts("d", {"Chapter 1": ("Start.", "He ran fast.", "End.")},
              {"Chapter 1": ("Start.", "He ran quickly.", "End.")})

    page = compare_page(client, "d")

    assert "He ran <mark>fast</mark>." in page and "He ran <mark>quickly</mark>." in page
    assert page.count("<mark>") == 2
    assert re.search(r"1 of 3 paragraphs differ\s*·\s*jump:\s*<a href=\"#d1-l\">1</a>", page)


def test_compare_jump_targets_are_unique_and_never_missing(client, two_texts):
    two_texts("d", {"Chapter 1": ("A.", "B.", "C.", "x", "a1", "a2", "y")},
              {"Chapter 1": ("A.", "B.", "New.", "C.", "x", "b1", "b2", "b3", "y")})

    page = compare_page(client, "d")

    ids = re.findall(r'id="(d\d+-[lr])"', page)
    assert len(ids) == len(set(ids))
    hrefs = re.findall(r'href="#(d\d+-l)"', page)
    assert hrefs == ["d1-l", "d2-l"] and all(ids.count(h) == 1 for h in hrefs)
    assert '<span class="diff-gap" id="d1-l"></span>' in page


def test_compare_diffs_parts_without_diffing_their_headings(client, two_texts):
    two_texts("d", {"Chapter 1 (part 1)": ("Same one.",), "Chapter 1 (part 2)": ("Left two.",)},
              {"Chapter 1 (part 1)": ("Same one.",), "Chapter 1 (part 2)": ("Right two.",)})

    page = compare_page(client, "d")

    assert page.count("Chapter 1 pt 1") >= 2 and page.count("Chapter 1 pt 2") >= 2
    assert "<p>Same one.</p>" in page
    assert "<mark>Left</mark> two." in page and "<mark>Right</mark> two." in page
    assert "1 of 2 paragraphs differ" in page


def test_compare_does_not_diff_raw_text(client, two_texts):
    two_texts("d", {"Chapter 1": ("English text.",)}, {"Chapter 1": ("中文。",)}, right_kind=Kind.RAW_ZH)

    page = compare_page(client, "d")

    assert "Raw text: no diff" in page and "<mark>" not in page and "diff--" not in page


def test_compare_says_when_texts_are_identical(client, two_texts):
    two_texts("d", {"Chapter 1": ("Same.",)}, {"Chapter 1": ("Same.",)})

    assert "Identical text." in compare_page(client, "d")


def test_check_section_lists_held_chapters_and_counts_unchecked_ones(client, novels):
    with NovelStore.open(novel_dir("raw-novel")) as store:
        current = next(s for s in store.view().chapters(1) if s.item_ref == "/3")
        v = store.read_version(current.version_id)
        rev = zh_rules("raw-novel", store.sources()[0].spec).rev
        store.put_version(1, "/3", NewVersion(v.title, v.blocks, findings=(Finding("poison", "有没×9"),), rules_rev=rev))

    check = client.get("/novels/raw-novel").text.split('id="check-heading"')[1]
    assert "<summary>Held: 1</summary>" in check
    assert "<li>source 1 <code>/3</code> 第3章 — poison: 有没×9</li>" in check
    assert "Not checked with current rules: 4 — run <code>nov reclean raw-novel</code>" in check
    assert "No problems found." not in check
