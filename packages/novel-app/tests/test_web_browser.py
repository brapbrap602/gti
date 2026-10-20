"""nov serve in headless Firefox (local only: `pytest -m browser`)."""

import threading
import time

import pytest
import uvicorn
from firefox_page import firefox
from novel_app.jobs import JobBoard, JobRunner, JobState
from novel_app.service import Service, app_db
from novel_app.web.app import create_app

pytestmark = pytest.mark.browser


@pytest.fixture
def service(site):
    return Service(JobRunner(JobBoard(app_db())))


@pytest.fixture
def app_url(service):
    """The app under uvicorn on an ephemeral port, in a thread."""
    server = uvicorn.Server(uvicorn.Config(create_app(service), host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise AssertionError("uvicorn did not start")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


@pytest.fixture
def page(tmp_path):
    with firefox(tmp_path / "profile") as page:
        yield page
        page.assert_no_errors()


def ended(board, target: str, state: JobState = JobState.DONE) -> int:
    job_id = board.claim(target, "sync", {})
    board.finish(job_id, state)
    return job_id


def drawer_open(page) -> bool:
    return page.js("""(() => { const r = document.querySelector('aside.jobs').getBoundingClientRect();
        return getComputedStyle(document.querySelector('aside.jobs')).visibility === 'visible'
            && r.left < innerWidth && r.right > 0; })()""")


RUNNING_DOT = "!['none', 'normal'].includes(getComputedStyle(document.querySelector('.jobs-toggle'), '::after').content)"


def wait_for_swap(page, text: str) -> None:
    page.wait_for(f"document.getElementById('jobs').textContent.includes({text!r})")


def test_jobs_drawer_on_a_phone_survives_live_updates(page, app_url, service):
    board = service.runner.board
    running = board.claim("busy-novel", "sync", {})
    board.start(running)

    page.goto(app_url + "/")
    page.wait_for("document.getElementById('jobs').textContent.includes('running')")
    assert not drawer_open(page)
    assert page.js(RUNNING_DOT)

    page.click(".jobs-toggle")
    page.wait_for("getComputedStyle(document.querySelector('aside.jobs')).visibility === 'visible'")
    assert page.js("document.querySelector('.jobs-toggle').getAttribute('aria-expanded')") == "true"
    board.set_progress(running, 2, 7, "Chapter 2")
    wait_for_swap(page, "2/7")

    assert drawer_open(page)
    board.finish(running, JobState.DONE)
    page.wait_for(f"!({RUNNING_DOT})")


def test_expanded_recent_jobs_stay_expanded_across_live_updates(page, app_url, service):
    board = service.runner.board
    for i in range(12):
        ended(board, f"novel-{i}")

    page.goto(app_url + "/")
    assert not page.js("document.getElementById('recent-jobs').checkVisibility()")
    page.click(".jobs-toggle")
    page.click(".recent-toggle")
    assert page.js("document.getElementById('recent-jobs').checkVisibility()")

    ended(board, "novel-new")
    wait_for_swap(page, "novel-new")

    assert page.js("document.getElementById('recent-jobs').checkVisibility()")
    assert page.js("document.querySelector('.recent-toggle').getAttribute('aria-expanded')") == "true"


def test_compare_jump_stays_in_view_when_the_page_reloads(page, app_url, service, two_texts):
    filler = tuple(f"Same paragraph {i}, long enough to wrap on a phone screen twice over." for i in range(40))
    two_texts("d", {"Chapter 1": (*filler, "He ran fast.", *filler)},
              {"Chapter 1": (*filler, "He ran quickly.", *filler)})
    page.goto(app_url + "/novels/d/compare?number=1")
    in_view = "(() => { const t = document.getElementById('d1-l').getBoundingClientRect().top;" \
              " return t >= 0 && t < innerHeight; })()"

    page.click('.diff-summary a[href="#d1-l"]')
    page.frame()
    assert page.js(in_view)

    page.js("document.getElementById('main').dataset.before = 'reload'")
    board = service.runner.board
    job = board.claim("other", "sync", {})  # a job starting makes the page reload its main region
    page.wait_for("document.getElementById('jobs').textContent.includes('other')")
    board.finish(job, JobState.DONE)
    page.wait_for("!document.getElementById('main').dataset.before")  # main was swapped
    page.js("new Promise(r => setTimeout(r, 1500))")  # past the reload that follows the job's end

    assert page.js(in_view)
