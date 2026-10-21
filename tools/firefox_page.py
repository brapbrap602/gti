"""Headless Firefox for the `browser` tests: a static file server and one driven tab.

Local only (the `browser` marker is excluded by default). Firefox, never Chromium.
Every page gets a preload script that records uncaught errors in `window.__errors`,
so a test can end with `page.assert_no_errors()`.
"""

import base64
import functools
import http.server
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

PHONE = (390, 844)

_RECORD_ERRORS = """() => {
  window.__errors = [];
  addEventListener('error', e => window.__errors.push(String(e.message)));
  addEventListener('unhandledrejection', e => window.__errors.push(String(e.reason)));
}"""

_THROWING_STORAGE = """() => {
  Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('denied', 'SecurityError'); }});
}"""


@contextmanager
def serve(folder: Path) -> Iterator[str]:
    """Serve folder over http on an ephemeral port; yields the base URL (with a trailing slash)."""
    handler = functools.partial(_QuietHandler, directory=str(folder))
    server = _QuietServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


class _QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        pass  # Firefox resets keep-alive connections when it closes; that is not a failure


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


class Page:
    """One Firefox tab. `js` evaluates an expression and returns its JSON value."""

    def __init__(self, backend) -> None:
        self._b = backend
        self._navigations = 0

    def goto(self, url: str) -> None:
        self._b.navigate(url, timeout=30)
        self.wait_for("document.readyState === 'complete'")

    def js(self, expression: str):
        """The JSON value of expression (awaited if it is a promise); raises if it threw."""
        wrapped = (
            "(async () => { try { return JSON.stringify({ok: await (" + expression + ")}); }"
            " catch (e) { return JSON.stringify({err: String(e)}); } })()"
        )
        raw = self._b.evaluate(wrapped)
        if raw is None:
            raise AssertionError(f"evaluate failed: {expression}")
        result = json.loads(raw)
        if "err" in result:
            raise AssertionError(f"{expression} threw {result['err']}")
        return result.get("ok")

    def wait_for(self, expression: str, timeout: float = 10.0):
        """Poll until expression is truthy; returns its value."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                value = self.js(expression)
            except AssertionError:
                value = None  # mid-navigation the old realm can vanish under us
            if value:
                return value
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {expression}")
            time.sleep(0.05)

    def frame(self) -> None:
        """Wait until the page has painted twice (scroll and rAF handlers have run)."""
        self.js("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def scroll(self, dy: float) -> None:
        """Scroll by dy CSS pixels as a reader would: steps of at most a quarter viewport."""
        step = self.js("innerHeight") / 4
        remaining = dy
        while abs(remaining) > 0.5:
            move = max(-step, min(step, remaining))
            self.js(f"scrollBy(0, {move})")
            self.frame()
            remaining -= move

    def click(self, selector: str) -> None:
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def navigate_by(self, action: str) -> None:
        """Run action (JS) that navigates, and wait for the new document to load."""
        # A token unique to this call: a page back from the bfcache keeps its old one.
        self._navigations += 1
        token = self._navigations
        self.js(f"window.__left = {token}")
        self.js(action)
        self.wait_for(f"window.__left !== {token} && document.readyState === 'complete'")

    def screenshot(self, path: Path, full_page: bool = False) -> None:
        """Save the viewport (or, with full_page, the whole document) as a PNG."""
        params = {"context": self._b._context, **({"origin": "document"} if full_page else {})}
        shot = self._b._rpc.send("browsingContext.captureScreenshot", params)
        path.write_bytes(base64.b64decode(shot["data"]))

    def assert_no_errors(self) -> None:
        assert self.js("window.__errors") == []


@contextmanager
def firefox(profile: Path, *, size: tuple[int, int] = PHONE, prefs: dict | None = None,
            throwing_storage: bool = False) -> Iterator[Page]:
    """A headless Firefox with one tab at size; skips the test when Firefox is missing."""
    from scraper.bidi import FirefoxBackend
    from scraper.browsers import pick_firefox

    executable = pick_firefox()
    if not executable:
        pytest.skip("Firefox is not installed")
    profile.mkdir(parents=True, exist_ok=True)
    # The backend overwrites user.js, so test prefs go in prefs.js (read first).
    lines = [f"user_pref({json.dumps(k)}, {json.dumps(v)});" for k, v in (prefs or {}).items()]
    (profile / "prefs.js").write_text("\n".join(lines) + "\n", encoding="utf-8")
    backend = FirefoxBackend(executable, headless=True, profile_dir=profile, proxy=None, extra=[])
    try:
        backend.attach()
        rpc = backend._rpc  # the backend has no public viewport or preload API
        # --window-size is ignored by headless Firefox on Windows; the BiDi viewport is not.
        viewport = {"width": size[0], "height": size[1]}
        rpc.send("browsingContext.setViewport", {"context": backend._context, "viewport": viewport})
        rpc.send("script.addPreloadScript", {"functionDeclaration": _RECORD_ERRORS})
        if throwing_storage:
            rpc.send("script.addPreloadScript", {"functionDeclaration": _THROWING_STORAGE})
        yield Page(backend)
    finally:
        backend.close()
