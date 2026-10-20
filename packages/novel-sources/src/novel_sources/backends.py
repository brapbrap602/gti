"""Which backend reads a URL, and opening a stored source spec as a live Source.

A host with a custom backend uses it: those exist because lncrawl's crawler for
the host fails (skydemonorder). Every other host goes to lncrawl.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from novel_core import SourceSpec

from novel_sources import lncrawl, skydemonorder
from novel_sources.fetch import firefox_scraper
from novel_sources.hosts import site_name
from novel_sources.sync import Source

CUSTOM = {"skydemonorder": skydemonorder.BACKEND}
BACKENDS = (lncrawl.BACKEND, *CUSTOM.values())


def backend_for(url: str) -> str:
    return CUSTOM.get(site_name(url), lncrawl.BACKEND)


def is_web(spec: SourceSpec) -> bool:
    """Whether sync can read this source (imports are frozen local stores)."""
    return spec.backend in BACKENDS


@contextmanager
def open_source(spec: SourceSpec, state: Path) -> Iterator[Source]:
    """The live source for a spec, closed (its browser included) on exit.

    `state` is where fetching keeps what it learns per site (challenge clearances, the Firefox profile).
    """
    with ExitStack() as stack:
        if spec.backend == lncrawl.BACKEND:
            source = lncrawl.LncrawlSource(spec)
            stack.callback(source.close)
        elif spec.backend == skydemonorder.BACKEND:
            scraper = stack.enter_context(firefox_scraper(spec.url, state))
            source = skydemonorder.SkyDemonOrderSource(spec, scraper)
        else:
            raise ValueError(f"backend {spec.backend!r} is not a web backend; sync reads only {list(BACKENDS)}")
        yield source


def spec_for_url(url: str, lang: str, backend: str | None = None) -> SourceSpec:
    backend = backend or backend_for(url)
    if backend == skydemonorder.BACKEND:
        return skydemonorder.SkyDemonOrderSource.spec_for(url)
    if backend == lncrawl.BACKEND:
        return lncrawl.LncrawlSource.spec_for(url, lang)
    raise ValueError(f"unknown backend {backend!r}; choose from {list(BACKENDS)}")

