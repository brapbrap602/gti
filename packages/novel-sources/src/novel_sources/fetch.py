"""Fetching from sites that challenge plain clients, with lncrawl-scraper's ladder.

lncrawl-scraper sends requests with a browser's TLS fingerprint. When a site
answers with a challenge (Cloudflare), it solves it once in a real browser and
reuses the clearance for later requests, pacing and retrying along the way.
The browser is always Firefox, driven over WebDriver BiDi; Chromium is never
launched. What it learns per site is kept under the data dir it is given.
"""

from pathlib import Path

from scraper import BidiSolver, Scraper, ScraperConfig
from scraper.browsers import pick_firefox


class FetchError(OSError):
    """A page could not be fetched: network failure, an HTTP error, or a challenge left unsolved."""


def firefox_scraper(origin: str, data_dir: Path) -> Scraper:
    """A scraper for one site that solves challenges in the installed Firefox. Close it when done."""
    firefox = pick_firefox()
    if firefox is None:
        raise FetchError(f"{origin} needs Firefox to pass its challenge, and no Firefox is installed")
    config = ScraperConfig(browser=BidiSolver(executable=firefox), impersonate="firefox", data_dir=data_dir)
    return Scraper(origin=origin, config=config)
