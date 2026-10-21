import json

from novel_app.cli import app
from novel_app.library import compare_dir, novel_dir
from novel_core import Kind, NewVersion, NovelStore, Paragraph, SourceItem, SourceSpec
from typer.testing import CliRunner


def run(*args, input=None):
    return CliRunner().invoke(app, [str(a) for a in args], input=input)


def with_official_english(numbers) -> int:
    with NovelStore.open(novel_dir("raw-novel")) as store:
        en = store.upsert_source(SourceSpec("custom:en", "https://en.test", "en", Kind.OFFICIAL_EN))
        store.record_index(en, [SourceItem(f"/en{n}", n, f"Chapter {n}: Official", number=n) for n in numbers])
        for n in numbers:
            store.put_version(en, f"/en{n}", NewVersion(f"Chapter {n}: Official", (Paragraph.of(f"Official words of {n}."),)))
        return en


def test_a_comparison_asks_first_stores_nothing_and_writes_a_bundle(openrouter):
    with_official_english([1, 2])
    models = ("--model", "vendor/cheap", "--model", "vendor/other@low")

    refused = run("translate", "compare", "raw-novel", "1-3", *models, input="n\n")
    assert refused.exit_code == 1, refused.output
    assert "3 chapters (n1, n2, n3); reference English for 2" in refused.output and "no reference for n3" in refused.output
    assert "vendor/other · prompt v1 · parallel, reasoning low: at most $" in refused.output
    assert openrouter.calls == []

    done = run("translate", "compare", "raw-novel", "1-3", *models, "--yes")
    assert done.exit_code == 0, done.output
    assert openrouter.calls == ["translate"] * 6
    assert ("vendor/other", {"data_collection": "allow", "reasoning": "low"}) in openrouter.models
    with NovelStore.open(novel_dir("raw-novel")) as store:
        assert not any(s.spec.kind is Kind.MY_TRANSLATION for s in store.sources())

    (bundle,) = compare_dir("raw-novel").iterdir()
    readme = (bundle / "README.md").read_text(encoding="utf-8")
    assert "| vendor/cheap · prompt v1 · parallel | 3 | 0 | $" in readme
    chapter = (bundle / "chapters" / "n1.md").read_text(encoding="utf-8")
    assert "**zh** " in chapter and "**vendor/cheap** " in chapter and "**vendor/other** " in chapter
    assert "## Reference" in chapter and "Official words of 1." in chapter
    data = json.loads((bundle / "comparison.json").read_text(encoding="utf-8"))
    assert data["chapters"] == ["n1", "n2", "n3"] and set(data["references"]) == {"n1", "n2"}
    assert all(a["cost"] > 0 and a["paragraphs"] for s in data["setups"] for a in s["attempts"].values())


def test_a_comparison_refuses_a_cap_below_the_estimate_and_bad_models(openrouter):
    low = run("translate", "compare", "raw-novel", "1-2", "--model", "vendor/cheap", "--cap", "0.0000001", "--yes")
    assert low.exit_code == 2 and "below the estimate" in low.output
    twice = run("translate", "compare", "raw-novel", "1-2", "--model", "vendor/cheap", "--model", "vendor/cheap", "--yes")
    assert twice.exit_code == 2 and "named twice" in twice.output
    effort = run("translate", "compare", "raw-novel", "1-2", "--model", "vendor/cheap@huge", "--yes")
    assert effort.exit_code == 2 and "reasoning must be one of" in effort.output
    reference = run("translate", "compare", "raw-novel", "1-2", "--model", "vendor/cheap", "--reference", "1", "--yes")
    assert reference.exit_code == 2 and "not one of the novel's English sources" in reference.output
    assert openrouter.calls == []
