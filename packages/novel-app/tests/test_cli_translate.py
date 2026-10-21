from novel_app.cli import app
from novel_app.jobs import JobBoard
from novel_app.service import app_db
from typer.testing import CliRunner


def run(*args, input=None):
    return CliRunner().invoke(app, [str(a) for a in args], input=input)


def added_setup(*options) -> int:
    result = run("translate", "setup", "add", "raw-novel", "--model", "vendor/cheap", *options)
    assert result.exit_code == 0, result.output
    return int(result.output.split(" is source ")[1].split()[0])


def test_a_setup_is_added_unpublished_and_translates_after_confirmation(openrouter):
    source = added_setup("--data-collection", "deny")
    assert "unpublished" in run("translate", "setup", "list", "raw-novel").output

    refused = run("translate", "run", "raw-novel", source, "1-3", input="n\n")
    assert refused.exit_code == 1 and "3 chapters to translate" in refused.output and "at most $" in refused.output
    assert "translate" not in openrouter.calls

    done = run("translate", "run", "raw-novel", source, "1-3", "--yes")
    assert done.exit_code == 0, done.output
    assert "translated 3; 0 already current" in done.output
    assert openrouter.models[-1] == ("vendor/cheap", {"data_collection": "deny", "reasoning": None})
    listed = run("translate", "setup", "list", "raw-novel").output
    assert f"source {source}: vendor/cheap · prompt v1 · parallel, no data collection [unpublished]: 3 chapters" in listed

    again = run("translate", "run", "raw-novel", source, "1-3", "--yes")
    assert "nothing to translate" in again.output


def test_publish_switches_a_setup_into_the_book(openrouter):
    source = added_setup()
    run("translate", "run", "raw-novel", source, "1-2", "--yes")
    assert "0 chapters selected" in run("check", "raw-novel").output
    assert run("publish", "raw-novel", source, "on").exit_code == 0
    assert "2 chapters selected" in run("check", "raw-novel").output
    assert run("publish", "raw-novel", source, "maybe").exit_code == 2


def test_stale_and_prune_report_per_setup(openrouter):
    source = added_setup()
    run("translate", "run", "raw-novel", source, "1-2", "--yes")
    assert "stale: 0" in run("translate", "stale", "raw-novel", source).output
    assert run("glossary", "add", "raw-novel", "韩立", "Lord Han", "--category", "person").exit_code == 0
    assert "stale: 2 (n1, n2)" in run("translate", "stale", "raw-novel", source).output
    assert "translated 2" in run("translate", "run", "raw-novel", source, "--stale", "--yes").output
    assert "0 orphans dropped" in run("translate", "prune", "raw-novel", source).output


def test_without_a_key_no_job_is_made(novels, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = run("translate", "setup", "add", "raw-novel", "--model", "vendor/cheap")
    assert result.exit_code == 2 and "set OPENROUTER_API_KEY" in result.output
    assert JobBoard(app_db()).jobs() == []


def test_bad_setups_and_sources_are_refused(openrouter):
    assert run("translate", "setup", "add", "raw-novel", "--model", "m", "--context", "random").exit_code == 2
    assert "not a translator setup" in run("translate", "stale", "raw-novel", 1).output
    assert run("translate", "run", "raw-novel", 1).exit_code == 2  # neither numbers nor --stale


def test_unchecked_raws_are_left_out_with_the_reclean_hint(openrouter, old_rules):
    source = added_setup()
    old_rules([2])
    refused = run("translate", "run", "raw-novel", source, "1-3", input="n\n")
    assert "2 chapters to translate" in refused.output and "1 not checked with current rules" in refused.output
    done = run("translate", "run", "raw-novel", source, "1-3", "--yes")
    assert "translated 2" in done.output
    assert "1 chapters not checked with current rules: run nov reclean raw-novel" in done.output
