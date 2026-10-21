"""nov serve in headless Firefox (local only: `pytest -m browser`)."""

import os
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from firefox_page import PHONE, firefox
from novel_app.jobs import JobBoard, JobRunner, JobState
from novel_app.library import novel_dir
from novel_app.service import Service, app_db
from novel_app.web.app import create_app
from novel_core import Kind, NewVersion, Paragraph, SourceItem, SourceSpec

pytestmark = pytest.mark.browser
DESKTOP = (1280, 900)


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


def test_glossary_review_keeps_focus_on_the_row(openrouter, page, app_url, service, tmp_path):
    from novel_translate.glossary import Status, UpdateTerm

    assert service.run("glossary-build", lambda _l: None, novel="raw-novel", model="vendor/cheap")[0] is JobState.DONE
    han = next(t.id for t in service.glossary("raw-novel") if t.zh == "韩立")
    service.glossary_edit("raw-novel", [UpdateTerm(han, status=Status.NEEDS_REVIEW)])

    page.goto(app_url + "/novels/raw-novel/glossary")
    assert page.js(f"!!document.getElementById('term-{han}')")
    assert page.js("document.documentElement.scrollWidth <= innerWidth")  # a phone never scrolls sideways
    assert page.js(f"document.querySelector('#term-{han} details').open")  # evidence shown for review
    page.js(f"document.getElementById('term-{han}-en').value = 'Han Li the Elder'")
    page.js(f"document.getElementById('term-{han}-save').focus()")
    page.click(f"#term-{han}-save")
    page.wait_for(f"document.querySelector('#term-{han} th').textContent.includes('✎')")
    assert page.js("document.activeElement.id") == f"term-{han}-save"

    settled = "!document.querySelector('.htmx-request, .htmx-swapping, .htmx-settling')"
    page.wait_for(settled)  # a person never clicks within htmx's settle delay
    page.js(f"document.getElementById('term-{han}-lock').focus()")
    page.click(f"#term-{han}-lock")
    page.wait_for(f"document.querySelector('#term-{han}').classList.contains('term--locked')")
    assert page.js(f"document.getElementById('term-{han}-en').value") == "Han Li the Elder"
    page.screenshot(tmp_path / "glossary.png")
    assert (tmp_path / "glossary.png").stat().st_size > 1000


def test_translate_form_enables_start_once_an_estimate_shows(openrouter, page, app_url, service):
    from novel_translate.setups import TranslatorSetup

    source = service.add_setup("raw-novel", TranslatorSetup("vendor/cheap"))
    page.goto(app_url + "/novels/raw-novel")
    start = "document.querySelector('#estimate button[type=submit]')"
    assert page.js(f"{start}.disabled")
    assert page.js("document.documentElement.scrollWidth <= innerWidth")
    page.js("""(() => { const i = document.querySelector('#translate-form input[name=range]');
        i.value = '1-3'; i.dispatchEvent(new Event('change', {bubbles: true})); })()""")
    page.wait_for(f"!{start}.disabled")
    assert "3 chapters to translate" in page.js("document.getElementById('estimate').textContent")
    assert page.js(f"document.querySelector('#translate-form select[name=setup]').value") == str(source)


SHOTS_ENV = "APP_UI_SHOTS"  # a folder to keep the screenshots in, for review


@pytest.mark.parametrize("size", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_screenshots_of_every_page(openrouter, two_texts, app_url, service, tmp_path, size):
    from novel_core import NovelStore, Note, System
    from novel_translate.glossary import Status, UpdateTerm
    from novel_translate.setups import TranslatorSetup

    assert service.run("glossary-build", lambda _l: None, novel="raw-novel", model="vendor/cheap")[0] is JobState.DONE
    setup = service.add_setup("raw-novel", TranslatorSetup("vendor/cheap"))
    assert service.run("translate", lambda _l: None, novel="raw-novel", setup=setup, range="1-2")[0] is JobState.DONE
    with NovelStore.open(novel_dir("raw-novel")) as store:
        en = store.upsert_source(SourceSpec("custom:en", "https://en.test", "en", Kind.OFFICIAL_EN))
        store.record_index(en, [SourceItem("/en1", 1, "Chapter 1: Official", number=1)])
        store.put_version(en, "/en1", NewVersion("Chapter 1: Official", (Paragraph.of("Official words."),)))
    assert service.run("compare", lambda _l: None, novel="raw-novel", models=["vendor/cheap", "vendor/other"],
                       range="1-2", per_call=[1])[0] is JobState.DONE  # fmt: skip
    han = next(t.id for t in service.glossary("raw-novel") if t.zh == "韩立")
    service.glossary_edit("raw-novel", [UpdateTerm(han, status=Status.NEEDS_REVIEW)])  # holds back chapters 3-5
    filler = tuple(f"Paragraph {i} of the chapter, the same on both sides." for i in range(6))
    two_texts("d", {"Chapter 1": (*filler, "He ran fast.", System("[Strength +1]"), Note("TL note: a pun."))},
              {"Chapter 1": (*filler, "He ran quickly.", System("[Strength +1]"))})
    running = service.runner.board.claim("d", "sync", {})
    service.runner.board.start(running)
    service.runner.board.set_progress(running, 2, 7, "Chapter 2")

    out = Path(os.environ.get(SHOTS_ENV) or tmp_path / "shots")
    out.mkdir(parents=True, exist_ok=True)
    pages = {
        "library": "/",
        "novel-sources": "/novels/raw-novel?s=1#sources",
        "novel-chapters": "/novels/raw-novel?s=2#chapters",
        "novel-translate": "/novels/raw-novel?s=3#translate",
        "novel-check": "/novels/raw-novel?s=4#check",
        "glossary": "/novels/raw-novel/glossary?tab=all",
        "compare": "/novels/d/compare?number=1",
        "comparisons": "/novels/raw-novel/comparisons",
        "comparison-chapter": "/novels/raw-novel/comparisons/n1",
        "add": "/add",
        "error": "/novels/nope",
    }
    name = "phone" if size == PHONE else "desktop"
    with firefox(tmp_path / "profile", size=size) as page:
        for shot, path in pages.items():
            page.goto(app_url + path)
            page.js("document.fonts.ready.then(() => true)")
            page.js("scrollTo(0, 0)")  # a full-page shot of a scrolled page draws the sticky top bar mid-page
            page.frame()
            assert page.js("document.documentElement.scrollWidth <= innerWidth"), shot  # never sideways
            page.screenshot(out / f"{name}-{shot}.png", full_page=True)
        page.assert_no_errors()
    service.runner.board.finish(running, JobState.DONE)
