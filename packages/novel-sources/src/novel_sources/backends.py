"""Which backend reads a URL, and opening a stored source spec as a live Source.

A host with a custom backend uses it: those exist because lncrawl's crawler for
the host fails (skydemonorder). A host the user wrote a decode guide for uses it.
A Chinese raw site novel-downloader has a plugin for goes to it. Then lncrawl, when
it has a crawler for the host (asking it loads lncrawl's crawler index); failing
that, web-novel-scraper's shipped decode guide for the host (novelbin, which lncrawl
lists as down); lncrawl's generic crawler is last.

`guides` is the decode guides in force (decode_guide.Guides.load with the user's
file); left out, only the shipped ones.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from novel_core import SourceSpec

from novel_sources import decode_guide, lncrawl, noveldl, skydemonorder
from novel_sources.decode_guide import Guides
from novel_sources.fetch import firefox_scraper
from novel_sources.hosts import site_name
from novel_sources.sync import Source

CUSTOM = {"skydemonorder": skydemonorder.BACKEND}
BACKENDS = (lncrawl.BACKEND, noveldl.BACKEND, decode_guide.BACKEND, *CUSTOM.values())


def backend_for(url: str, guides: Guides = Guides()) -> str:
    if custom := CUSTOM.get(site_name(url)):
        return custom
    if guides.is_own(url):
        return decode_guide.BACKEND
    if noveldl.site_book(url):
        return noveldl.BACKEND
    if guides.for_url(url) and not lncrawl.supports(url):
        return decode_guide.BACKEND
    return lncrawl.BACKEND


def is_web(spec: SourceSpec) -> bool:
    """Whether sync can read this source (imports are frozen local stores)."""
    return spec.backend in BACKENDS


@contextmanager
def open_source(spec: SourceSpec, state: Path, guides: Guides = Guides()) -> Iterator[Source]:
    """The live source for a spec, closed (its browser included) on exit.

    `state` is where fetching keeps what it learns per site (challenge clearances, the Firefox profile).
    """
    with ExitStack() as stack:
        if spec.backend == lncrawl.BACKEND:
            source = lncrawl.LncrawlSource(spec)
            stack.callback(source.close)
        elif spec.backend == noveldl.BACKEND:
            source = noveldl.connect(spec, state)
            stack.callback(source.close)
        elif spec.backend == skydemonorder.BACKEND:
            scraper = stack.enter_context(firefox_scraper(spec.url, state))
            source = skydemonorder.SkyDemonOrderSource(spec, scraper)
        elif spec.backend == decode_guide.BACKEND:
            scraper = stack.enter_context(firefox_scraper(spec.url, state))
            source = decode_guide.DecodeGuideSource(spec, guides, scraper)
        else:
            raise ValueError(f"backend {spec.backend!r} is not a web backend; sync reads only {list(BACKENDS)}")
        yield source


def spec_for_url(url: str, lang: str, backend: str | None = None, guides: Guides = Guides()) -> SourceSpec:
    backend = backend or backend_for(url, guides)
    if backend == skydemonorder.BACKEND:
        return skydemonorder.SkyDemonOrderSource.spec_for(url)
    if backend == noveldl.BACKEND:
        return noveldl.NovelDownloaderSource.spec_for(url)
    if backend == decode_guide.BACKEND:
        return decode_guide.DecodeGuideSource.spec_for(url, lang, guides)
    if backend == lncrawl.BACKEND:
        return lncrawl.LncrawlSource.spec_for(url, lang)
    raise ValueError(f"unknown backend {backend!r}; choose from {list(BACKENDS)}")

