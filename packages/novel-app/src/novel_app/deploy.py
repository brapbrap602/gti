"""Publishing the built site: force-push it as a one-commit orphan `gh-pages` branch, then check it is live."""

import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BRANCH = "gh-pages"
DEFAULT_BUDGET = 900 * 1024 * 1024
STAMP = "deploy.txt"  # holds the deploy id, so the live check can tell this deploy from the previous one


class DeployError(Exception):
    pass


@dataclass(frozen=True)
class Deployed:
    deploy_id: str
    size: int
    commit: str


def site_size(site_dir: Path) -> int:
    return sum(f.stat().st_size for f in site_dir.rglob("*") if f.is_file())


def deploy_site(site_dir: Path, remote: str, budget: int = DEFAULT_BUDGET, git_dir: Path | None = None) -> Deployed:
    """Commit site_dir as the only commit of an orphan gh-pages branch and force-push it to `remote`.

    Aborts before anything is pushed when the site is over `budget` bytes or has no index.html.
    The commit is made in a throwaway git dir (`git_dir`, default site_dir/../.deploy-git) with
    site_dir as its work tree, so no copy of the site is made and the source repo is untouched.
    """
    if not (site_dir / "index.html").is_file():
        raise DeployError(f"{site_dir} has no index.html; run `nov build site` first")
    size = site_size(site_dir)
    if size > budget:
        raise DeployError(f"site is {size / 2**20:.0f} MiB, over the {budget / 2**20:.0f} MiB budget; nothing pushed")

    deploy_id = uuid.uuid4().hex
    (site_dir / STAMP).write_text(deploy_id + "\n", encoding="utf-8")
    git_dir = git_dir or site_dir.parent / ".deploy-git"
    if git_dir.exists():
        _rmtree(git_dir)

    def git(*args: str) -> str:
        return _run("git", f"--git-dir={git_dir}", f"--work-tree={site_dir}", *args)

    try:
        git("init", "--quiet", f"--initial-branch={BRANCH}")
        git("config", "core.autocrlf", "false")
        if not _has_identity(git_dir):  # e.g. a CI runner: commit as `nov deploy` rather than fail
            git("config", "user.name", "nov deploy")
            git("config", "user.email", "nov-deploy@localhost")
        git("add", "--all", "--force")  # --force: a global excludes file must not drop site files
        git("commit", "--quiet", "--message", f"Site deploy {deploy_id}")
        commit = git("rev-parse", "HEAD").strip()
        git("push", "--force", "--quiet", remote, f"{BRANCH}:{BRANCH}")
    finally:
        _rmtree(git_dir)
    return Deployed(deploy_id, size, commit)


def wait_live(
    base_url: str,
    deploy_id: str,
    timeout: float = 600,
    interval: float = 15,
    fetch: Callable[[str], str] | None = None,
) -> bool:
    """Poll base_url until it serves this deploy's stamp and its index page. False on timeout."""
    fetch = fetch or _fetch
    base = base_url.rstrip("/") + "/"
    deadline = time.monotonic() + timeout
    while True:
        try:
            if fetch(base + STAMP).strip() == deploy_id and fetch(base + "index.html"):
                return True
        except (urllib.error.URLError, TimeoutError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def pages_url(remote: str) -> str | None:
    """https://<owner>.github.io/<repo>/ for a GitHub remote, else None."""
    for prefix in ("https://github.com/", "git@github.com:"):
        if remote.startswith(prefix):
            owner, _, repo = remote.removeprefix(prefix).removesuffix(".git").partition("/")
            return f"https://{owner.lower()}.github.io/{repo}/" if owner and repo else None
    return None


def origin_url(repo: Path) -> str:
    return _run("git", "-C", str(repo), "remote", "get-url", "origin").strip()


def _fetch(url: str) -> str:
    # The query defeats Pages' CDN cache, which otherwise serves the previous stamp for minutes.
    with urllib.request.urlopen(f"{url}?t={time.time_ns()}", timeout=30) as response:
        return response.read().decode("utf-8")


def _run(*cmd: str) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise DeployError(f"{' '.join(cmd[:4])} ... failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def _has_identity(git_dir: Path) -> bool:
    """Whether git has user.name and user.email from its config (it may still guess them otherwise)."""
    return all(
        subprocess.run(["git", f"--git-dir={git_dir}", "config", key], capture_output=True).returncode == 0
        for key in ("user.name", "user.email")
    )


def _rmtree(path: Path) -> None:
    def writable(func, p, _exc):  # git object files are read-only on Windows
        Path(p).chmod(stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onexc=writable)
