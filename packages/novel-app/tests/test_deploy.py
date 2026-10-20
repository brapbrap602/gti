import subprocess

import pytest
from novel_app.deploy import STAMP, DeployError, deploy_site, pages_url, wait_live


def git(*args) -> str:
    return subprocess.run(["git", *map(str, args)], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "data" / "_site"
    (root / "novels" / "n").mkdir(parents=True)
    (root / "index.html").write_text("<h1>Library</h1>", encoding="utf-8")
    (root / ".nojekyll").touch()
    (root / "novels" / "n" / "1-50.html").write_text("page", encoding="utf-8")
    return root


@pytest.fixture
def remote(tmp_path):
    path = tmp_path / "remote.git"
    git("init", "--bare", "--quiet", path)
    return path


def test_deploy_pushes_one_orphan_commit(site, remote):
    first = deploy_site(site, str(remote))
    second = deploy_site(site, str(remote))

    log = git("--git-dir", remote, "log", "--format=%H", "gh-pages").split()
    assert log == [second.commit] and first.commit != second.commit  # force-pushed, no history kept
    files = git("--git-dir", remote, "ls-tree", "-r", "--name-only", "gh-pages").split()
    assert sorted(files) == [".nojekyll", STAMP, "index.html", "novels/n/1-50.html"]
    assert git("--git-dir", remote, "show", f"gh-pages:{STAMP}").strip() == second.deploy_id
    assert not (site / ".git").exists() and not (site.parent / ".deploy-git").exists()


def test_deploy_without_a_git_identity(site, remote, tmp_path, monkeypatch):
    # CI runners have no user.name/user.email; useConfigOnly stops git guessing one from the host.
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    deployed = deploy_site(site, str(remote))
    assert git("--git-dir", remote, "rev-parse", "gh-pages").strip() == deployed.commit


def test_deploy_keeps_the_users_git_identity(site, remote, tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Someone\n\temail = someone@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    deploy_site(site, str(remote))
    assert git("--git-dir", remote, "log", "-1", "--format=%an <%ae>", "gh-pages").strip() == "Someone <someone@example.com>"


def test_site_over_budget_aborts_before_push(site, remote):
    with pytest.raises(DeployError, match="over the"):
        deploy_site(site, str(remote), budget=10)
    assert git("--git-dir", remote, "branch", "--list").strip() == ""


def test_site_without_index_is_not_pushed(tmp_path, remote):
    (tmp_path / "empty").mkdir()
    with pytest.raises(DeployError, match="no index.html"):
        deploy_site(tmp_path / "empty", str(remote))


def test_wait_live_until_the_stamp_matches():
    served = iter(["old", "old", "new"])

    def fetch(url):
        return next(served) if url.endswith(STAMP) else "<html>"

    assert wait_live("https://x.github.io/gti", "new", interval=0, fetch=fetch)
    assert not wait_live("https://x.github.io/gti", "new", timeout=0, interval=0, fetch=lambda _u: "old")


@pytest.mark.parametrize(
    ("remote", "url"),
    [
        ("https://github.com/brapbrap602/gti.git", "https://brapbrap602.github.io/gti/"),
        ("git@github.com:BrapBrap602/gti.git", "https://brapbrap602.github.io/gti/"),
        ("C:/repos/site.git", None),
    ],
)
def test_pages_url(remote, url):
    assert pages_url(remote) == url
