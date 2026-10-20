"""lnreader backend: LNReader's site plugins, run by a pinned Node behind this thin shim.

LNReader plugins are TypeScript and have no Python port, so the app keeps its own
Node: the shim downloads a pinned Node build and a pinned lnreader-plugins commit,
checks both against their SHA-256, installs the harness's npm packages from its
lockfile (`npm ci`, scripts off) and starts one harness process (lnreader_harness/
harness.mjs). The harness bundles a plugin with esbuild on first use and answers one
JSON request per line. Everything lives under `<state>/lnreader`; each piece is set up
in a temporary folder renamed into place when complete, so an interrupted setup is
simply redone.

A URL is read by the plugin whose `site` has the same host. Nothing picks this backend
by itself (asking would mean setting up Node): `nov add --backend lnreader`.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from novel_core import Kind, NovelMeta, RawChapter, SourceItem, SourceSpec, url_ref

from novel_sources.clean import CleanRules
from novel_sources.fetch import FetchError
from novel_sources.hosts import COMMON, numbered_urls
from novel_sources.importing import NovelIndex

BACKEND = "lnreader"
_BODY = "lnreader-body"  # id of the div a fetched body is stored in, so normalize can find it

NODE_VERSION = "v22.23.3"
_NODE_SHA256 = {  # from https://nodejs.org/dist/v22.23.3/SHASUMS256.txt
    "win-x64.zip": "2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71",
    "linux-x64.tar.gz": "1084aa36196bba4c3a5e69a1ee388a6e4ff729dad09445fbcd434b28fe3c24af",
    "darwin-arm64.tar.gz": "23b25245dcfb9af7262f8ff142e9e2e0af025368117329e7a7458a51e5922f53",
    "darwin-x64.tar.gz": "8a677b0219178efd6eb0e475457c4afb452b521a92f6e67845a73bd85727f2a8",
}
PLUGINS_COMMIT = "b66c2a40948dcaab61a6e36fc285383d8c2bfb06"  # LNReader/lnreader-plugins, 2026-10-19
_PLUGINS_SHA256 = "c565e1f40de9f8fdf858570eea274b34164f80e0c4c3ec01b3f2182a6c56686a"
_PLUGINS_URL = f"https://codeload.github.com/LNReader/lnreader-plugins/zip/{PLUGINS_COMMIT}"
_HARNESS_FILES = ("harness.mjs", "package.json", "package-lock.json")

Download = Callable[[str, Path], None]  # (url, destination file)


@dataclass(frozen=True)
class Runtime:
    """A set-up Node, plugin checkout and harness, ready to start."""

    node: Path
    plugins: Path  # the lnreader-plugins checkout, multisrc plugins generated
    harness: Path  # the harness folder, its node_modules installed

    @classmethod
    def ensure(cls, root: Path, download: Download | None = None) -> "Runtime":
        """Set up whatever under `root` is missing. FetchError on a failed download, checksum or install."""
        download = download or _download
        root.mkdir(parents=True, exist_ok=True)
        node_dir = _node(root, download)
        node, npm = _node_paths(node_dir)
        plugins = _plugins(root, node, download)
        harness = _harness(root, node, npm)
        return cls(node, plugins, harness)


class Harness:
    """One running harness process; requests are answered in order. Close it when done."""

    def __init__(self, runtime: Runtime, log: Path):
        self._log = log.open("ab")
        try:
            self._process = subprocess.Popen(
                [str(runtime.node), str(runtime.harness / "harness.mjs"), str(runtime.plugins)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._log,
                cwd=runtime.harness,
            )
        except OSError:
            self._log.close()
            raise

    def request(self, op: str, **fields) -> object:
        """The harness's result. FetchError when the plugin failed or the harness is gone."""
        line = json.dumps({"op": op, **fields}) + "\n"
        try:
            self._process.stdin.write(line.encode())
            self._process.stdin.flush()
            reply = self._process.stdout.readline()
        except OSError as e:
            raise FetchError(f"lnreader harness: {e}") from e
        if not reply:
            raise FetchError(f"lnreader harness exited (code {self._process.poll()}); see {self._log.name}")
        answer = json.loads(reply)
        if not answer["ok"]:
            raise FetchError(f"lnreader {op}: {answer['error']}")
        return answer["result"]

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.stdin.close()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._log.close()


def connect(spec: SourceSpec, state: Path) -> "LnreaderSource":
    """The source for a spec: the runtime set up under `state`, a harness started. Close it when done."""
    root = state / "lnreader"
    harness = Harness(Runtime.ensure(root), root / "harness.log")
    try:
        return LnreaderSource(spec, harness, catalog(harness, root))
    except Exception:
        harness.close()
        raise


def catalog(harness: Harness, root: Path) -> list[dict]:
    """Every plugin's {file, id, name, site, lang}; listed once per plugins commit (bundling all of them takes a while)."""
    cached = root / f"catalog-{PLUGINS_COMMIT[:12]}.json"
    if cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    plugins = [p for p in harness.request("plugins") if "site" in p and p["site"]]
    cached.write_text(json.dumps(plugins, indent=1), encoding="utf-8")
    return plugins


def plugin_for(url: str, plugins: list[dict]) -> tuple[dict, str]:
    """(the plugin whose site has this URL's host, the novel path relative to its site)."""
    host = _host(url)
    for plugin in plugins:
        if _host(plugin["site"]) == host:
            path = urlsplit(url).path.lstrip("/")
            site_path = urlsplit(plugin["site"]).path.strip("/")
            if site_path and path.startswith(site_path + "/"):
                path = path[len(site_path) + 1 :]
            return plugin, path
    raise ValueError(f"{url}: no LNReader plugin for {host}")


class LnreaderSource:
    def __init__(self, spec: SourceSpec, harness: Harness, plugins: list[dict]):
        """`harness` is a started Harness, owned (closed) by the source; `plugins` is the catalog."""
        self._spec = spec
        self._harness = harness
        self._plugin, self._novel_path = plugin_for(spec.url, plugins)
        self._paths: dict[str, str] = {}  # item ref -> plugin chapter path, from the last index

    @staticmethod
    def spec_for(url: str, lang: str = "en") -> SourceSpec:
        return SourceSpec(BACKEND, url, lang, Kind.RAW_ZH if lang == "zh" else Kind.OFFICIAL_EN)

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    def fetch_index(self) -> NovelIndex:
        novel = self._harness.request("novel", file=self._plugin["file"], path=self._novel_path)
        site = self._plugin["site"]
        items = []
        for chapter in novel["chapters"]:
            url = urljoin(site, chapter["path"])
            ref = url_ref(url)
            if ref in self._paths:  # listed twice
                continue
            self._paths[ref] = chapter["path"]
            items.append(SourceItem(ref, len(items) + 1, chapter["name"].strip(), ref_numbered=numbered_urls(url)))
        if not items:
            raise FetchError(f"{self._spec.url}: the {self._plugin['id']} plugin listed no chapters")
        meta = NovelMeta(
            title=novel["name"],
            author=novel["author"] or None,
            language=self._spec.lang,
            tags=tuple(g.strip() for g in novel["genres"].split(",") if g.strip()),
        )
        return NovelIndex(meta, tuple(items), provenance={"plugin": self._plugin["id"], "plugins_commit": PLUGINS_COMMIT})

    def fetch_chapter(self, item: SourceItem) -> RawChapter:
        path = self._paths.get(item.ref)
        if path is None:
            raise FetchError(f"{item.ref}: not in the index fetched this run")
        html = self._harness.request("chapter", file=self._plugin["file"], path=path)["html"]
        if not html or not html.strip():
            raise FetchError(f"{item.ref}: the {self._plugin['id']} plugin returned an empty chapter")
        url = urljoin(self._plugin["site"], path)
        return RawChapter(f'<div id="{_BODY}">{html}</div>', "html", final_url=url, fetched_at=datetime.now(UTC))

    def clean_rules(self, raw: RawChapter) -> CleanRules:
        return COMMON | CleanRules(content=(f"div#{_BODY}",))

    def close(self) -> None:
        self._harness.close()


# -- setup -------------------------------------------------------------------------


def _node(root: Path, download: Download) -> Path:
    archive = _node_archive()
    name = f"node-{NODE_VERSION}-{archive.split('.', 1)[0]}"
    target = root / name
    if not target.is_dir():
        url = f"https://nodejs.org/dist/{NODE_VERSION}/{name}.{archive.split('.', 1)[1]}"
        _install(root, target, url, _NODE_SHA256[archive], download, top=name)
    return target


def _plugins(root: Path, node: Path, download: Download) -> Path:
    target = root / f"lnreader-plugins-{PLUGINS_COMMIT[:12]}"
    if not target.is_dir():

        def generate(checkout: Path) -> None:  # the multisrc plugins (madara, novelfire, ...) are generated files
            _run([str(node), "plugins/multisrc/generate-multisrc-plugins.js"], checkout, "generating multisrc plugins")

        _install(root, target, _PLUGINS_URL, _PLUGINS_SHA256, download, top=f"lnreader-plugins-{PLUGINS_COMMIT}", then=generate)
    return target


def _harness(root: Path, node: Path, npm: Path) -> Path:
    files = resources.files("novel_sources").joinpath("lnreader_harness")
    lock = files.joinpath("package-lock.json").read_bytes()
    target = root / f"lnreader-harness-{hashlib.sha256(lock).hexdigest()[:12]}"
    if target.is_dir():
        return target
    staging = _staging(root, target)
    for name in _HARNESS_FILES:
        (staging / name).write_bytes(files.joinpath(name).read_bytes())
    _run([str(node), str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund"], staging, "installing the harness's npm packages")
    staging.rename(target)
    return target


def _install(root: Path, target: Path, url: str, sha256: str, download: Download, top: str, then=None) -> None:
    """Download `url`, check it, unpack its `top` folder as `target` (after `then(folder)`)."""
    staging = _staging(root, target)
    archive = staging.with_suffix(".download")
    try:
        download(url, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != sha256:
            raise FetchError(f"{url}: SHA-256 {digest} is not the pinned {sha256}")
        _unpack(archive, staging)
    finally:
        archive.unlink(missing_ok=True)
    unpacked = staging / top
    if not unpacked.is_dir():
        raise FetchError(f"{url}: the archive has no {top}/ folder")
    if then is not None:
        then(unpacked)
    unpacked.rename(target)
    shutil.rmtree(staging)


def _staging(root: Path, target: Path) -> Path:
    staging = root / f".{target.name}.partial"
    shutil.rmtree(staging, ignore_errors=True)  # a setup interrupted earlier
    staging.mkdir(parents=True)
    return staging


def _unpack(archive: Path, into: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into, filter="data")


def _node_archive() -> str:
    machine = "arm64" if _machine() in ("arm64", "aarch64") else "x64"
    key = {"win32": "win-x64.zip", "linux": "linux-x64.tar.gz", "darwin": f"darwin-{machine}.tar.gz"}.get(sys.platform)
    if key is None or key not in _NODE_SHA256 or (sys.platform != "darwin" and machine != "x64"):
        raise FetchError(f"no pinned Node build for {sys.platform}/{_machine()}")
    return key


def _machine() -> str:
    import platform

    return platform.machine().lower()


def _node_paths(node_dir: Path) -> tuple[Path, Path]:
    """(node executable, npm-cli.js) inside an unpacked Node build."""
    if sys.platform == "win32":
        return node_dir / "node.exe", node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js"
    return node_dir / "bin" / "node", node_dir / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"


def _run(command: list[str], cwd: Path, what: str) -> None:
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip()[-1500:]
        raise FetchError(f"{what} failed (exit {done.returncode}): {tail}")


def _download(url: str, to: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=120) as response, to.open("wb") as out:
            shutil.copyfileobj(response, out)
    except OSError as e:
        raise FetchError(f"{url}: download failed: {e}") from e


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")
