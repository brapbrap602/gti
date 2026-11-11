import asyncio
import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from novel_app.jobs import JobBoard, JobRunner, JobState
from novel_app.service import Service, app_db
from novel_app.web.app import create_app, job_events
from novel_app.library import audio_dir, novel_dir
from novel_core import Finding, Kind, NewVersion, NovelMeta, NovelStore, Paragraph, SourceItem, SourceSpec
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
    page = client.get("/", params={"view": "cards"}).text
    assert 'href="/novels/test-novel">Test Novel</a>' in page
    assert "3 selected" in page
    assert re.search(r'name="kind" value="sync"', page)
    assert re.search(r'class="[^"]*out--missing[^"]*" title="site: not built">site not built<', page)
    assert re.search(r'<li title="https://novelbuddy\.me/test-novel">.*?novelbuddy\.me.*?official-en.*?</li>', page)

    novel = client.get("/novels/test-novel").text
    assert 'title="3, official, source 1: Chapter 3"' in novel
    assert "No problems found." in novel


def test_terms_explain_themselves(client, service):
    """Every page's jargon carries its meaning: a source kind, a job button, a stat, a table column, a legend."""
    added(service)
    page = client.get("/").text
    assert re.search(r'name="kind" value="sync">.*?<button type="submit" class="[^"]*" title="Fetch the chapters', page, re.S)
    assert '<a class="stat stat--link" href="/?status=new" title="Chapters a web source lists that no source has a text for yet' in page
    assert '<div class="stat" title="Chapter numbers the books take a text for' in page
    assert re.search(r'<th scope="col"[^>]* title="Numbers inside the book&#39;s range with nothing publishable', page)
    cards = client.get("/", params={"view": "cards"}).text
    assert 'title="official-en: a published English translation; the book can use it">official-en<' in cards

    novel = client.get("/novels/test-novel").text
    assert '<th scope="col" class="num" title="Listed chapters no source has a text for yet; Sync fetches them">To fetch</th>' in novel
    assert '<li title="Fetching failed; the next Sync tries again">' in novel


def test_library_counts_leave_out_unpublished_sources(client, service):
    added(service)
    with NovelStore.open(novel_dir("test-novel")) as store:
        mine = store.upsert_source(SourceSpec("translate:test", "test:setup", "en", Kind.MY_TRANSLATION), published=False)
        store.record_index(mine, [SourceItem("n1", 1, "Chapter 1")])
        store.put_version(mine, "n1", NewVersion("Chapter 1", (Paragraph.of("one"),)))
    page = client.get("/", params={"view": "cards"}).text  # remembered for the next look
    assert "<li>3 official-en</li>" in page and "<li>1 my-translation</li>" not in page

    with NovelStore.open(novel_dir("test-novel")) as store:
        store.set_published(mine, True)
    assert "<li>1 my-translation</li>" in client.get("/").text


def test_compare_then_pin(client, service, site):
    added(service)
    added(service, url=URL + "/")  # a second source with the same chapters
    page = client.get("/novels/test-novel/compare", params={"number": 2}).text
    assert "The book uses source 1" in page
    assert "Source 2: novelbuddy.me" in page and 'name="numbers" value="2"' in page
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


def test_the_public_switch_takes_a_novel_off_the_site_and_back(client, service):
    added(service)
    assert "Take off site" in client.get("/novels/test-novel").text
    assert "off site</span>" not in client.get("/").text

    off = client.post("/novels/test-novel/public", data={"on": "off"}, follow_redirects=False)

    assert off.status_code == 303 and off.headers["location"].startswith("/novels/test-novel?notice=")
    page = client.get("/novels/test-novel").text
    assert "Put on site" in page and "off site</span>" in page
    assert "off site</span>" in client.get("/").text
    with NovelStore.open(novel_dir("test-novel")) as store:
        assert not store.public

    client.post("/novels/test-novel/public", data={"on": "on"})
    assert "Take off site" in client.get("/novels/test-novel").text


def test_the_meta_form_edits_title_and_clears_author(client, service):
    added(service)
    with NovelStore.open(novel_dir("test-novel")) as store:
        store.update_meta(author="Someone")
    audio = audio_dir("test-novel")
    audio.mkdir(parents=True)
    (audio / "0001.mp3").write_bytes(b"")
    assert 'action="/novels/test-novel/meta"' in client.get("/novels/test-novel").text

    edited = client.post("/novels/test-novel/meta", data={"title": "New Title", "author": "", "back": "/novels/test-novel"},
                         follow_redirects=False)

    assert edited.status_code == 303 and edited.headers["location"].startswith("/novels/test-novel?notice=")
    notice = client.get(edited.headers["location"]).text
    assert "site and EPUB rebuild at the next build" in notice and "nov audio retag test-novel" in notice
    assert "<h1>New Title" in notice
    with NovelStore.open(novel_dir("test-novel")) as store:
        assert (store.meta.title, store.meta.author) == ("New Title", None)
    in_place = client.post("/novels/test-novel/meta", data={"title": "New Title", "author": "A"}, headers={"HX-Request": "true"})
    assert in_place.status_code == 200 and "site and EPUB rebuild" in in_place.text


def test_a_title_edit_marks_the_built_site_stale(client, service):
    added(service)
    assert service.run("build-site", quiet)[0] is JobState.DONE
    assert 'title="site: 3 stale"' not in client.get("/").text

    client.post("/novels/test-novel/meta", data={"title": "Renamed", "author": ""})

    assert 'title="site: 3 stale"' in client.get("/").text
    assert service.run("build-site", quiet)[0] is JobState.DONE
    assert 'title="site: 3 stale"' not in client.get("/").text


def test_the_meta_form_refuses_a_blank_title(client, service):
    added(service)
    with NovelStore.open(novel_dir("test-novel")) as store:
        before = store.meta

    refused = client.post("/novels/test-novel/meta", data={"title": "", "author": "X", "back": "/novels/test-novel"})

    assert refused.status_code == 400 and "A title can&#39;t be blank." in refused.text
    with NovelStore.open(novel_dir("test-novel")) as store:
        assert store.meta == before


def test_one_job_per_novel_and_kind(client, service):
    added(service)
    service.runner.board.claim("test-novel", "sync", {"novel": "test-novel"})  # say, a CLI sync
    refused = client.post("/jobs", data={"kind": "sync", "novel": "test-novel", "back": "/"})
    assert refused.status_code == 409 and "sync already running for test-novel" in refused.text
    page = client.get("/").text
    assert re.search(r'<button type="submit"(?: class="[^"]*")? disabled title="Sync is queued \(job \d+\)"(?: class="[^"]*")?>.*?Sync</button>', page)
    assert "running in another process" in page
    assert re.search(r'<button type="submit" title="[^"]*">.*?EPUB</button>', page)  # other kinds can start

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

class SilentTts:
    voice = "silent"

    def __init__(self, voice):
        pass

    async def synthesize(self, text):
        return b""


@pytest.mark.parametrize(
    ("first", "last", "range_"),
    [("2", "3", "2-3"), ("2", "", "2-"), ("", "3", "-3"), ("", "", None)],
    ids=["both", "from-only", "to-only", "all"],
)
def test_audio_from_the_build_menu_takes_an_optional_chapter_span(site, first, last, range_):
    service = Service(JobRunner(JobBoard(app_db())), tts=SilentTts)
    added(service)
    with TestClient(create_app(service)) as client:
        page = client.get("/novels/test-novel").text
        assert 'name="from"' in page and 'name="to"' in page
        form = {"kind": "build-audio", "novel": "test-novel", "from": first, "to": last}
        ok = client.post("/jobs", data=form, headers={"HX-Request": "true"})
        job_id = int(re.search(r"started job (\d+)", ok.text).group(1))
        row = finished(service, job_id)
    assert row.args.get("range") == range_


def test_job_interrupted_at_startup(site, service):
    dead = JobBoard(app_db(), clock=lambda: 0.0)  # its heartbeat is decades old
    job_id = dead.claim("test-novel", "sync", {"novel": "test-novel"})
    dead.start(job_id)  # it was running (one only queued would end cancelled)
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


def test_an_audio_build_waits_for_its_novels_sync_and_can_be_cancelled_at_once(client, service):
    added(service)
    board = service.runner.board
    sync = board.claim("test-novel", "sync", {"novel": "test-novel"})  # say, a CLI sync
    audio = service.start("build-audio", novel="test-novel")
    gate = threading.Event()
    while board.job(audio).current != "waiting for sync":
        gate.wait(0.02)

    panel = re.search(rf'data-job="{audio}".*?</li>', client.get("/").text, re.S).group(0)
    assert '<span class="job-state">queued</span>' in panel and "waiting for sync" in panel

    cancelled = client.post(f"/jobs/{audio}/cancel", data={"back": "/"}, headers={"HX-Request": "true"})
    assert f"job {audio} cancelled" in cancelled.text
    assert board.job(audio).state is JobState.CANCELLED
    again = client.post(f"/jobs/{audio}/cancel", data={"back": "/"}, headers={"HX-Request": "true"})
    assert f"job {audio} is not running in this server" in again.text
    board.finish(sync, JobState.DONE)


def test_sync_all_queues_every_web_novel_but_those_already_syncing(client, service, novels):
    titled(service, "a", "Ant", fetched=True)
    titled(service, "b", "Bee", fetched=True)
    board = service.runner.board
    busy = board.claim("b", "sync", {"novel": "b"})  # say, a CLI sync

    r = client.post("/jobs/sync-all", data={"back": "/"}, headers={"HX-Request": "true"})

    assert r.status_code == 200 and "Queued 1 sync (one at a time); skipped 1 already syncing" in r.text
    assert "raw-novel" not in r.text and "english-only" not in r.text  # no web source: not an error
    (queued,) = (j for j in board.jobs(limit=50) if j.kind == "sync" and j.id > busy)
    assert queued.target == "a" and finished(service, queued.id).state is JobState.DONE
    board.finish(busy, JobState.DONE)
    assert 'action="/jobs/sync-all"' in client.get("/").text


def test_sync_all_without_javascript_goes_back_with_a_notice(client, service):
    r = client.post("/jobs/sync-all", data={"back": "/?status=new"}, follow_redirects=False)

    assert r.status_code == 303 and r.headers["location"] == "/?status=new&notice=Nothing+to+sync"


def test_a_sync_click_or_a_rerun_starts_at_once_beside_a_sync_all_batch(client, service, site):
    for slug, title in (("a", "Ant"), ("b", "Bee"), ("f", "Fox")):
        titled(service, slug, title, fetched=True)
    board = service.runner.board
    site.count, site.hold = 4, threading.Event()  # one new chapter each, whose fetch waits
    client.post("/jobs/sync-all", data={"back": "/"})
    batch = {j.target: j.id for j in board.jobs(limit=50) if j.kind == "sync" and j.state.active}
    gate = threading.Event()
    while board.job(batch["a"]).state is not JobState.RUNNING:
        gate.wait(0.02)
    client.post(f"/jobs/{batch['f']}/cancel", data={"back": "/"})  # an ended Sync-all job
    titled(service, "e", "Eel", fetched=False)

    clicked = client.post("/jobs", data={"kind": "sync", "novel": "e"}, headers={"HX-Request": "true"})
    rerun = client.post(f"/jobs/{batch['f']}/rerun", data={"back": "/"}, headers={"HX-Request": "true"})

    started = [int(re.search(r"started job (\d+)", r.text).group(1)) for r in (clicked, rerun)]
    for job_id in started:
        while board.job(job_id).state is JobState.QUEUED:
            gate.wait(0.02)
    assert [board.job(j).state for j in started] == [JobState.RUNNING] * 2
    assert board.job(batch["b"]).state is JobState.QUEUED  # the batch's next sync still waits its turn
    site.hold.set()
    for job_id in (*started, batch["a"], batch["b"]):
        assert finished(service, job_id).state is JobState.DONE


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


def test_main_reloads_when_a_queued_job_starts_too(service):
    board, polls, claimed = service.runner.board, [], []

    async def disconnected():
        polls.append(len(polls) + 1)
        if len(polls) == 2:
            claimed.append(board.claim("other", "sync", {}))
        if len(polls) == 3:
            board.start(claimed[0])
        if len(polls) == 4:
            board.finish(claimed[0], JobState.DONE)
        return len(polls) > 5

    async def collect():
        return [e async for e in job_events(service, lambda panel: "", disconnected, every=0.0)]

    events = asyncio.run(collect())
    assert [e.splitlines()[0] for e in events].count("event: active") == 3  # claimed, started, ended


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


def test_sources_table_cells_carry_labels_for_phones(client, service):
    added(service)

    html = re.search(r'<table class="sources-table">.*?</table>', client.get("/novels/test-novel").text, re.S).group(0)
    body = html.split("<tbody>", 1)[1]
    cells = re.findall(r"<td(?: [^>]*)?>", body)
    assert cells and all("data-label=" in c for c in cells), cells


def test_library_cards_name_link_and_sync_each_novel(client, service, novels):
    added(service)

    page = client.get("/", params={"view": "cards"}).text
    listed = page.split("</main>")[0].split('<li class="card novel-card" data-novel="')[1:]
    cards = {card.split('"', 1)[0]: card for card in listed}
    assert sorted(cards) == ["english-only", "raw-novel", "test-novel"]
    for slug, card in cards.items():
        assert f'href="/novels/{slug}">' in card
    syncable = cards["test-novel"]
    assert 'name="kind" value="sync"' in syncable and 'name="novel" value="test-novel"' in syncable


def table_rows(page: str) -> dict[str, str]:
    listed = page.split("</main>")[0].split('<tr class="novel-row" data-novel="')[1:]
    return {r.split('"', 1)[0]: r.split("</tr>", 1)[0] for r in listed}


def row_slugs(page: str) -> list[str]:
    return re.findall(r'<tr class="novel-row" data-novel="([^"]+)"', page)


def test_the_library_is_a_table_by_default(client, service):
    added(service)

    page = client.get("/").text

    rows = table_rows(page)
    assert list(rows) == ["test-novel"] and "novel-card" not in page
    row = rows["test-novel"]
    assert 'title="Test Novel" href="/novels/test-novel">Test Novel</a>' in row
    assert re.search(r'<td class="num"[^>]*>3</td>', row)
    assert 'name="kind" value="sync"' in row and 'name="novel" value="test-novel"' in row
    assert len(re.findall(r'class="badge [^"]* out out--', row)) == 3
    assert 'class="menu menu--end"' in row and '<table class="library-table">' in page


def test_the_cards_view_is_remembered(client, service):
    added(service)

    first = client.get("/", params={"view": "cards"})
    again = client.get("/")

    assert "lib_view=cards" in first.headers["set-cookie"] and "set-cookie" not in again.headers
    for page in (first.text, again.text):
        assert '<li class="card novel-card" data-novel="test-novel"' in page and "novel-row" not in page
    assert 'href="/?view=table"' in again.text


def test_the_sort_is_remembered_and_tabs_keep_it(client, service):
    titled(service, "a", "Ant", fetched=True)
    titled(service, "z", "Zed", fetched=False)  # new chapters: first by attention
    assert row_slugs(client.get("/").text) == ["z", "a"]

    assert "lib_sort=title" in client.get("/", params={"sort": "title"}).headers["set-cookie"]
    page = client.get("/", params={"status": "ok"}).text
    assert row_slugs(page) == ["a", "z"]
    assert '<a class="tab" href="/?status=ok"' in page and '<a class="tab" href="/?status=new"' in page
    assert re.search(r'<th scope="col"[^>]* aria-sort="ascending"><a href="/\?sort=title&amp;status=ok"', page)


def test_queued_jobs_are_counted_apart_from_running_ones(client, service, novels):
    added(service)
    board = service.runner.board
    running = board.claim("raw-novel", "sync", {})
    board.start(running)
    queued = [board.claim(slug, "build-epub", {}) for slug in ("english-only", "test-novel")]

    page = client.get("/").text

    assert '<span class="pill-label">1 running · 2 queued</span>' in page
    assert stat(page, "Jobs")[0] == "1 running · 2 queued"
    assert row_slugs(client.get("/", params={"status": "running"}).text) == ["raw-novel"]
    for job_id in (running, *queued):
        board.finish(job_id, JobState.DONE)


def test_a_novel_with_a_job_problem_comes_first_until_dismissed(client, service):
    titled(service, "a", "Ant", fetched=True)
    titled(service, "b", "Bee", fetched=True)
    board = service.runner.board
    failed = board.claim("b", "sync", {})
    board.finish(failed, JobState.FAILED)

    assert row_slugs(client.get("/").text) == ["b", "a"]
    client.post(f"/jobs/{failed}/dismiss", data={"back": "/"})
    assert row_slugs(client.get("/").text) == ["a", "b"]


def test_the_stat_tiles_link_to_their_tabs(client, service):
    added(service)

    page = client.get("/").text

    def tile(label: str) -> str:
        return re.search(rf'<(a|div) class="stat[^"]*"([^>]*)>\s*<span class="stat-label">{label}<', page).group(0)

    assert 'href="/"' in tile("Novels")
    assert 'href="/?status=new"' in tile("New to fetch")
    assert 'href="/?status=rebuild"' in tile("Needs rebuild")
    assert 'href="#jobs"' in tile("Jobs") and "data-open-jobs" in tile("Jobs")
    assert tile("Chapters").startswith('<div class="stat"')


def test_the_rebuild_tile_and_tab_count_the_same_novels(client, service):
    titled(service, "a", "Ant", fetched=True)
    titled(service, "b", "Bee", fetched=True)
    assert service.run("build-site", quiet)[0] is JobState.DONE
    service.set_meta("a", "Ant 2")
    service.set_meta("b", "Bee 2")  # both sites stale
    board = service.runner.board
    running = board.claim("a", "build-epub", {})
    board.start(running)

    assert stat(client.get("/").text, "Needs rebuild")[0] == "2"
    assert sorted(row_slugs(client.get("/", params={"status": "rebuild"}).text)) == ["a", "b"]
    board.finish(running, JobState.DONE)


def test_build_site_shows_busy_however_many_jobs_are_active(client, service):
    added(service)
    board = service.runner.board
    site = board.claim("_site", "build-site", {})
    board.start(site)
    others = [board.claim(f"n{i}", "sync", {}) for i in range(21)]  # newer, so jobs(limit=20) misses the build

    page = client.get("/").text

    assert re.search(rf'disabled title="Build site is running \(job {site}\)"', page)
    for job_id in (site, *others):
        board.finish(job_id, JobState.DONE)


def test_library_filters_novels_by_status(client, service, novels):
    added(service)
    by_status = {r.slug: r.status for r in service.library()}
    assert "raw-only" in by_status.values() and "ok" in by_status.values()

    for status in ("raw-only", "ok"):
        page = client.get("/", params={"status": status}).text
        assert sorted(row_slugs(page)) == sorted(s for s, st in by_status.items() if st == status)
        assert re.findall(r'<a class="tab" href="([^"]*)"[^>]*aria-current="page"', page) == [f"/?status={status}"]

    running = client.get("/", params={"status": "running"}).text
    assert row_slugs(running) == [] and "Show all novels" in running
    everything = client.get("/", params={"status": "bogus"}).text  # an unknown status shows every novel
    assert sorted(row_slugs(everything)) == sorted(by_status)


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


def compare_rows(page: str, heading: bool = False) -> list[str]:
    """The compare page's aligned rows, in order: paragraph rows, or with `heading` the part-heading rows."""
    body = page.split('<div class="compare-rows', 1)[1].split("</main>", 1)[0]
    rows = body.split('<div class="compare-row')[1:]
    return [r for r in rows if r.startswith(' compare-row--heading">' if heading else '">')]


def cells(row: str) -> list[tuple[str, str]]:
    """A row's two cells: (class modifier, e.g. "--blank" or "", and the HTML after the cell's tag)."""
    return [tuple(c.split('">', 1)) for c in row.split('<div class="compare-cell')[1:]]


def test_english_texts_line_up_paragraph_by_paragraph(client, two_texts):
    two_texts("d", {"Chapter 1": ("A.", "B.", "C.")}, {"Chapter 1": ("A.", "B.", "New.", "C.")})

    page = compare_page(client, "d")

    rows = compare_rows(page)
    assert len(rows) == 4
    blank, new = cells(rows[2])
    assert "--blank" in blank[0] and blank[1].startswith('<span class="diff-gap" id="d1-l"></span>')
    assert "New." in new[1] and 'id="d1-r"' in new[1]
    assert all("--blank" not in c[0] for r in (rows[0], rows[1], rows[3]) for c in cells(r))
    ids = re.findall(r'id="(d\d+-[lr])"', page)
    assert len(ids) == len(set(ids))


def test_a_part_heading_on_one_side_faces_a_blank(client, two_texts):
    two_texts("d", {"Chapter 1 (part 1)": ("Same one.",), "Chapter 1 (part 2)": ("Left two.",)},
              {"Chapter 1": ("Same one.", "Right two.")})

    page = compare_page(client, "d")

    first, second = (cells(r) for r in compare_rows(page, heading=True))
    assert "Chapter 1 pt 1" in first[0][1] and "Chapter 1" in first[1][1]
    assert "Chapter 1 pt 2" in second[0][1] and "--blank" in second[1][0]
    assert len(compare_rows(page)) == 2


def test_raw_text_keeps_two_columns(client, two_texts):
    two_texts("d", {"Chapter 1": ("English text.",)}, {"Chapter 1": ("中文。",)}, right_kind=Kind.RAW_ZH)

    page = compare_page(client, "d")

    assert page.count('class="card compare-side"') == 2 and "compare-row" not in page


def five_sources(slug: str, numbers: dict[int, tuple[int, ...]]) -> None:
    """Sources 1-5 of a novel, each with English chapters at the given numbers."""
    with NovelStore.create(novel_dir(slug), NovelMeta("Five")) as store:
        for s in range(1, 6):
            source = store.upsert_source(SourceSpec(f"custom:s{s}", f"https://s{s}.test/n", "en", Kind.OFFICIAL_EN))
            items = [SourceItem(f"/{n}", i, f"Chapter {n}", number=n) for i, n in enumerate(numbers[s], start=1)]
            store.record_index(source, items)
            for item in items:
                store.put_version(source, item.ref, NewVersion(item.title, (Paragraph.of(f"Source {s}, {item.title}."),)))


def test_prev_and_next_keep_the_sources_asked_for(client, site):
    five_sources("five", {s: (119, 121) if s == 3 else (119, 120, 121) for s in range(1, 6)})

    page = client.get("/novels/five/compare", params={"number": 120, "left": 3, "right": 5}).text

    assert "Source 1: s1.test" in page and "Source 5: s5.test" in page  # source 3 lacks 120: the book's shows
    assert 'href="/novels/five/compare?number=119&amp;left=3&amp;right=5"' in page
    assert 'href="/novels/five/compare?number=121&amp;left=3&amp;right=5"' in page
    assert 'name="back" value="/novels/five/compare?number=120&amp;left=3&amp;right=5"' in page


def test_next_stops_at_the_last_chapter_any_source_has(client, two_texts):
    two_texts("d", {f"Chapter {n}": (f"L{n}.",) for n in (1, 2, 3)}, {f"Chapter {n}": (f"R{n}.",) for n in (1, 2, 3)})

    assert "compare?number=3" in compare_page(client, "d", 2)
    last = compare_page(client, "d", 3)
    assert "compare?number=4" not in last and "compare?number=2" in last


def test_a_chapter_no_source_has_still_gets_the_bar(client, two_texts):
    two_texts("d", {"Chapter 1": ("A.",)}, {"Chapter 1": ("B.",)})

    page = compare_page(client, "d", 50)

    bar = re.search(r'<div class="compare-bar">.*?</nav>', page, re.S).group(0)
    assert 'href="/novels/d/compare?number=1"' in bar  # back to the last chapter there is
    assert "number=51" not in bar and "<select" not in bar
    assert "No source has a text for chapter 50" in page


def test_compare_says_when_texts_are_identical(client, two_texts):
    two_texts("d", {"Chapter 1": ("Same.",)}, {"Chapter 1": ("Same.",)})

    assert "Identical text." in compare_page(client, "d")


def test_check_section_lists_held_chapters_numbering_and_unchecked_ones(client, novels, old_rules, misnumbered):
    old_rules([1, 2, 4, 5])
    with NovelStore.open(novel_dir("raw-novel")) as store:
        current = next(s for s in store.view().chapters(1) if s.item_ref == "/3")
        v = store.read_version(current.version_id)
        rev = zh_rules("raw-novel", store.sources()[0].spec).rev
        store.put_version(1, "/3", NewVersion(v.title, v.blocks, findings=(Finding("poison", "有没×9"),), rules_rev=rev))

    check = client.get("/novels/raw-novel").text.split('id="check-heading"')[1]
    assert "<summary>Held: 1</summary>" in check
    assert "<li>source 1 <code>/3</code> 第3章 松林 — poison: 有没×9</li>" in check
    assert "Not checked with current rules: 4 — run <code>nov reclean raw-novel</code>" in check
    assert "<summary>Numbering: 1 (against source 1)</summary>" in check
    assert (
        "<li>source 2 printed 2–6 are chapters 1–5 (offset -1, 5 titles match):"
        " <code>nov align range raw-novel 2-6 -1 --source 2</code></li>"
    ) in check
    assert "No problems found." not in check


def test_vendored_fonts_and_icons_are_served(client):
    for path in ("/static/vendor/lucide.svg", "/static/vendor/fonts/OFL.txt", "/static/vendor/LICENSE-lucide.txt"):
        assert client.get(path).status_code == 200, path
    for name in ("Geist-Variable", "GeistMono-Variable"):
        font = client.get(f"/static/vendor/fonts/{name}.woff2")
        assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"


def test_every_icon_a_template_uses_is_in_the_sprite():
    web = Path(create_app.__code__.co_filename).parent
    named = r"""(?:\bicon\(|\bempty\(|icon_name=)["']([\w-]+)["']"""
    used = {name for t in (web / "templates").glob("*.html") for name in re.findall(named, t.read_text(encoding="utf-8"))}
    symbols = set(re.findall(r'<symbol id="([\w-]+)"', (web / "static/vendor/lucide.svg").read_text(encoding="utf-8")))
    assert used - symbols == set()


def stat(page: str, label: str) -> tuple[str, str | None]:
    """A stat card's value and hint, by its label."""
    found = re.search(rf'<span class="stat-label">{label}</span>.*?<span class="stat-value[^"]*">([^<]*)</span>\s*'
                      r'(?:<span class="stat-hint">([^<]*)</span>)?', page, re.S)
    assert found, label
    return found.group(1), found.group(2)


def test_the_shell_has_the_sidebar_and_its_own_styles(client, novels):
    page = client.get("/").text
    assert 'id="nav-novels"' in page and 'data-novel="raw-novel"' in page and 'id="nav-raw-novel"' in page
    assert "/site-assets/" not in page
    assert page.index("/static/ui.css") < page.index("/static/app.css")
    main = re.search(r"<main [^>]*>", page).group(0)
    assert 'id="main"' in main and 'hx-select-oob="#nav-novels"' in main
    assert page.index('id="notice"') < page.index("<main")


def titled(service, slug: str, title: str, fetched: bool) -> None:
    """A novel on the test site under its own title; unfetched, it has 3 new chapters."""
    assert service.run("add", quiet, url=f"{URL}/{slug}", novel=slug)[0] is JobState.DONE
    if fetched:
        assert service.run("sync", quiet, novel=slug)[0] is JobState.DONE
    service.set_meta(slug, title)


def nav_titles(page: str) -> list[str]:
    return re.findall(r'<span class="nav-text">([^<]*)</span>', page)


def test_the_sidebar_lists_novels_by_title_whatever_the_library_order(client, service):
    titled(service, "a-zed", "Zed", fetched=False)
    titled(service, "b-ant", "Ant", fetched=True)

    page = client.get("/", params={"sort": "new"}).text

    assert row_slugs(page) == ["a-zed", "b-ant"]
    assert nav_titles(page) == ["Ant", "Zed"]


def test_the_sidebar_falls_back_to_slugs_when_the_library_cannot_be_read(client, service, novels, monkeypatch):
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("store locked")

    monkeypatch.setattr(service, "library", broken)
    page = client.get("/add")
    assert page.status_code == 200 and calls
    assert 'data-novel="raw-novel"' in page.text and ">raw-novel</span>" in page.text


def test_library_stats_sum_the_rows(client, service, novels):
    added(service)
    rows = service.library()
    page = client.get("/").text

    raw_only = sum(r.raw_only for r in rows)
    assert stat(page, "Novels") == ("3", f"{raw_only} raw only" if raw_only else None)
    assert stat(page, "Chapters")[0] == f"{sum(r.selected for r in rows):,}"
    assert stat(page, "New to fetch")[0] == f"{sum(r.new_items for r in rows if r.can_sync):,}"
    assert stat(page, "Needs rebuild")[0] == "0"


def test_the_jobs_pill_shows_a_running_job_and_its_progress(client, novels, service):
    board = service.runner.board
    running = board.claim("raw-novel", "sync", {})
    board.start(running)
    board.set_progress(running, 2, 7, "")

    page = client.get("/").text
    pill = re.search(r'<button type="button" class="jobs-toggle.*?</button>', page, re.S).group(0)
    assert "jobs-toggle--running" in pill and '<span class="pill-label">1 running</span>' in pill
    assert re.search(r'class="pill-progress"[^>]*max="7" value="2"', pill)
    row = table_rows(page)["raw-novel"]
    assert f'<div class="job-mirror" data-job-progress="{running}">' in row and "Sync 2/7" in row
    beside = board.claim("raw-novel", "build-epub", {})  # a second kind on the same novel gets its own bar
    assert f'data-job-progress="{beside}"' in client.get("/").text
    board.finish(beside, JobState.DONE)
    board.finish(running, JobState.DONE)


def test_the_jobs_pill_counts_unresolved_problems_only(client, service):
    board = service.runner.board
    with_errors = board.claim("a", "sync", {})
    board.finish(with_errors, JobState.DONE, ["chapter 3: HTTP 500"])
    failed = board.claim("b", "sync", {})
    board.finish(failed, JobState.FAILED)
    board.finish(board.claim("b", "sync", {}), JobState.DONE)  # resolves b's failure, which moves to Recent

    page = client.get("/").text
    assert '<span class="pill-label">1 problem</span>' in page and "jobs-toggle--problem" in page


def test_the_novel_page_has_five_tabs_and_their_panels(openrouter, client, service):
    from novel_translate.setups import TranslatorSetup

    service.add_setup("raw-novel", TranslatorSetup("vendor/cheap"))
    page = client.get("/novels/raw-novel").text

    panels = re.findall(r'<section id="(\w+)"[^>]* data-panel="(\w+)"', page)
    assert panels == [(p, p) for p in ("sources", "chapters", "translate", "check", "files")]
    links = re.findall(r'<a class="tab" href="#(\w+)" data-tab-link="(\w+)">', page)
    assert links == [(p, p) for p in ("sources", "chapters", "translate", "check", "files")]
    assert 'role="tablist"' not in page
    problems = service.novel("raw-novel").check.problems
    check_tab = re.search(r'data-tab-link="check">.*?</a>', page, re.S).group(0)
    assert (f">{problems}</span>" if problems else "✓") in check_tab


def test_a_novel_without_raws_has_no_translate_tab(client, novels):
    page = client.get("/novels/english-only").text
    assert 'data-panel="translate"' not in page and 'data-tab-link="translate"' not in page
    assert 'data-panel="chapters"' in page


def test_unpin_goes_back_to_the_sources_tab(client, service):
    added(service)
    added(service, url=URL + "/")
    client.post("/novels/test-novel/pin", data={"numbers": "2", "source": "2"})
    unpinned = client.post("/novels/test-novel/unpin", data={"numbers": "2"}, follow_redirects=False)
    location = unpinned.headers["location"]
    assert unpinned.status_code == 303 and location.startswith("/novels/test-novel?notice=") and location.endswith("#sources")


def test_a_refused_htmx_job_is_an_error_toast(client, service):
    added(service)
    service.runner.board.claim("test-novel", "sync", {"novel": "test-novel"})
    refused = client.post("/jobs", data={"kind": "sync", "novel": "test-novel"}, headers={"HX-Request": "true"})
    assert refused.status_code == 409
    assert "toast--destructive" in refused.text and "sync already running for test-novel" in refused.text
    assert 'class="toast-close"' in refused.text and "<html" not in refused.text


def test_files_tab_shows_where_the_novel_lives_and_opens_its_folders(site):
    shown = []
    service = Service(JobRunner(JobBoard(app_db())), show=shown.append)
    added(service)
    with TestClient(create_app(service)) as client:
        page = client.get("/novels/test-novel").text
        assert f'<td data-label="Path" class="path">{novel_dir("test-novel")}</td>' in page
        assert 'action="/novels/test-novel/folders/novel"' in page
        assert 'action="/novels/test-novel/folders/epub"' not in page  # nothing built yet

        opened = client.post("/novels/test-novel/folders/novel", follow_redirects=False)
        assert opened.status_code == 303 and shown == [novel_dir("test-novel")]

        assert client.post("/novels/test-novel/folders/epub").status_code == 400  # not built
        assert client.post("/novels/test-novel/folders/raw").status_code == 400  # only the listed folders
        assert client.post("/novels/nobody/folders/novel").status_code == 400
    assert shown == [novel_dir("test-novel")]


def test_epub_volume_size_is_chosen_in_the_build_menu_and_remembered(client, service):
    added(service)
    menu = client.get("/novels/test-novel").text
    assert re.search(r'<input name="size" type="number" min="1" inputmode="numeric" value="100"', menu)

    ok = client.post("/jobs", data={"kind": "build-epub", "novel": "test-novel", "size": "2"}, headers={"HX-Request": "true"})
    job_id = int(re.search(r"started job (\d+)", ok.text).group(1))
    assert finished(service, job_id).state is JobState.DONE
    assert "2 of 2 volumes built" in client.get(f"/jobs/{job_id}/log").text  # chapters 1-3 in volumes of 2

    page = client.get("/novels/test-novel").text
    assert re.search(r'<input name="size" type="number" min="1" inputmode="numeric" value="2"', page)
    assert re.search(r'<span class="kind">epub</span>\s*<span class="fresh">up to date</span>', page)  # not stale at size 2

    bad = client.post("/jobs", data={"kind": "build-epub", "novel": "test-novel", "size": "0"})
    assert bad.status_code == 400 and "at least 1 chapter" in bad.text


def test_problems_are_cleared_one_at_a_time_or_all_at_once(client, service):
    board = service.runner.board
    jobs = []
    for target in ("a", "b", "c"):
        jobs.append(board.claim(target, "sync", {}))
        board.finish(jobs[-1], JobState.FAILED)

    page = client.get("/").text
    assert f'action="/jobs/{jobs[0]}/dismiss"' in page and "Clear 3 problems" in page
    one = client.post(f"/jobs/{jobs[0]}/dismiss", data={"back": "/"}, headers={"HX-Request": "true"})
    assert f"cleared job {jobs[0]}" in one.text
    page = client.get("/").text
    assert '<span class="pill-label">2 problems</span>' in page
    shown = re.findall(r'name="job" value="(\d+)"', page)
    assert shown == [str(jobs[2]), str(jobs[1])]
    later = board.claim("d", "sync", {})  # fails after the drawer was drawn
    board.finish(later, JobState.FAILED)

    rest = client.post("/jobs/dismiss", data={"back": "/", "job": shown}, follow_redirects=False)
    assert rest.status_code == 303 and "cleared+2+problems" in rest.headers["location"]
    assert [j.id for j in service.job_panel().attention] == [later]


def test_a_hand_edited_url_gets_the_error_page_not_json(client, service):
    added(service)
    for url in ("/novels/test-novel/compare", "/novels/test-novel/compare?number=x"):
        r = client.get(url)
        assert r.status_code == 400 and r.headers["content-type"].startswith("text/html"), url
        assert "This page needs a valid number." in r.text and "<title>Refused · Novel library</title>" in r.text


def test_page_titles_name_the_novel_by_its_title_then_the_page(client, service):
    added(service)
    for url, title in (
        ("/novels/test-novel", "Test Novel · Novel library"),
        ("/novels/test-novel/compare?number=1", "Test Novel · Chapter 1 · Novel library"),
        ("/novels/test-novel/comparisons", "Test Novel · Model comparisons · Novel library"),
        ("/novels/test-novel/glossary", "Test Novel · Glossary · Novel library"),
    ):
        assert f"<title>{title}</title>" in client.get(url).text, url


def test_a_job_that_ended_with_errors_is_not_shown_as_done(client, service):
    board = service.runner.board
    flawed = board.claim("a", "sync", {})
    board.finish(flawed, JobState.DONE, ["ch 1: 404"])
    clean = board.claim("b", "sync", {})
    board.finish(clean, JobState.DONE)

    page = client.get("/").text
    assert re.search(rf'data-job="{flawed}"[^>]*>\s*<div class="job-head">.*?<span class="job-state">done with errors</span>', page, re.S)
    assert f'class="job job--done job--with-errors' in page
    assert re.search(rf'data-job="{clean}"[^>]*>\s*<div class="job-head">.*?<span class="job-state">done</span>', page, re.S)


def test_dismissing_a_running_or_unknown_job_says_so(client, service):
    running = service.runner.board.claim("a", "sync", {})
    for job_id in (running, 999):
        r = client.post(f"/jobs/{job_id}/dismiss", data={"back": "/"}, headers={"HX-Request": "true"})
        assert f"no ended job {job_id}" in r.text
    service.runner.board.finish(running, JobState.DONE)
