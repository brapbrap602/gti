import pytest
from fastapi.testclient import TestClient
from novel_app.jobs import JobBoard, JobRunner, JobState
from novel_app.library import novel_dir
from novel_app.service import Service, app_db
from novel_app.web.app import create_app
from novel_core import Kind, NewVersion, NovelStore, Paragraph, SourceItem, SourceSpec


@pytest.fixture
def service(openrouter):
    return Service(JobRunner(JobBoard(app_db())))


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as c:
        yield c


def compared(service, *per_call):
    with NovelStore.open(novel_dir("raw-novel")) as store:
        en = store.upsert_source(SourceSpec("custom:en", "https://en.test", "en", Kind.OFFICIAL_EN))
        store.record_index(en, [SourceItem("/en1", 1, "Chapter 1: Official", number=1)])
        store.put_version(en, "/en1", NewVersion("Chapter 1: Official", (Paragraph.of("Official words."),)))
    state, _ = service.run(
        "compare", lambda _line: None, novel="raw-novel", models=["vendor/cheap", "vendor/other"], range="1-2",
        per_call=list(per_call or [1]),
    )  # fmt: skip
    assert state is JobState.DONE


def test_without_runs_the_page_says_how_to_make_one(client):
    page = client.get("/novels/raw-novel/comparisons")
    assert page.status_code == 200 and "No comparisons yet" in page.text
    assert "Model comparisons</a> <span class=\"muted\">none yet" in client.get("/novels/raw-novel").text


def test_the_overview_shows_every_run_on_one_screen(service, client):
    compared(service)
    compared(service, 2)
    page = client.get("/novels/raw-novel/comparisons").text
    assert page.count("<th scope=\"row\">vendor/cheap</th>") == 1 and "vendor/cheap (2 per request)" in page
    assert page.count('class="attempt attempt--ok"') == 8  # 2 runs × 2 setups × 2 chapters
    assert page.count('<details class="judgement"') == 2 and "not judged yet" in page
    assert "2 runs" in client.get("/novels/raw-novel").text


def test_a_chapter_screen_has_every_version_from_every_run_and_the_reference(service, client):
    compared(service)
    compared(service, 2)
    page = client.get("/novels/raw-novel/comparisons/n1")
    assert page.status_code == 200
    assert page.text.count('<td data-label="vendor/') == 4  # 2 runs × 2 setups; raw-novel's chapters are one paragraph
    assert 'lang="zh"' in page.text and "Official words." in page.text and "2 →" in page.text

    (first,) = [c.key for c in service.comparison_chapter("raw-novel", "n1").columns if "(2 per request)" not in c.key][:1]
    picked = client.get("/novels/raw-novel/comparisons/n1", params={"show": [first, "ref"]}).text
    assert picked.count('<td data-label="vendor/') == 1 and 'lang="zh"' not in picked and "Official words." in picked

    assert client.get("/novels/raw-novel/comparisons/n9").status_code == 400
