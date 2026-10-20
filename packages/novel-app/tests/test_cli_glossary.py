from novel_app.cli import app
from typer.testing import CliRunner


def run(*args, input=None):
    return CliRunner().invoke(app, [str(a) for a in args], input=input)


def test_build_shows_the_estimate_and_asks_first(openrouter):
    refused = run("glossary", "build", "raw-novel", "--model", "vendor/cheap", input="n\n")
    assert refused.exit_code == 1
    assert "at most $" in refused.output and "5 summarize" in refused.output
    assert openrouter.calls == []

    done = run("glossary", "build", "raw-novel", "--model", "vendor/cheap", "--yes")
    assert done.exit_code == 0, done.output
    assert "5 chapters summarized" in done.output and "decided: 1 accepted" in done.output
    listed = run("glossary", "list", "raw-novel", "--status", "accepted")
    assert "韩立 → Han Li  [person, accepted]" in listed.output


def test_without_a_key_nothing_starts(novels, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = run("glossary", "build", "raw-novel", "--model", "vendor/cheap", "--yes")
    assert result.exit_code == 2 and "set OPENROUTER_API_KEY" in result.output


def test_a_novel_without_raws_has_no_glossary_pass(openrouter):
    result = run("glossary", "build", "english-only", "--model", "vendor/cheap", "--yes")
    assert result.exit_code == 2 and "has no Chinese raws" in result.output


def test_manual_terms_are_added_changed_locked_and_rejected(openrouter):
    added = run("glossary", "add", "raw-novel", "韓立", "Han Li", "--category", "person", "--alias", "韩老魔")
    assert added.exit_code == 0 and "added 韓立 → Han Li" in added.output
    assert "韩立 (also 韩老魔) → Han Li  [person, locked *]" in run("glossary", "list", "raw-novel").output

    assert run("glossary", "add", "raw-novel", "韩立", "Han Li").exit_code == 2  # already there
    assert run("glossary", "set", "raw-novel", "1", "--en", "Han Li the Elder").exit_code == 0
    assert run("glossary", "reject", "raw-novel", "1").exit_code == 0
    assert "Han Li the Elder  [person, rejected *]" in run("glossary", "list", "raw-novel").output
    assert run("glossary", "lock", "raw-novel", "99").exit_code == 2
