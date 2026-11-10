"""Fetching from sites that challenge plain clients, with lncrawl-scraper's ladder.

lncrawl-scraper sends requests with a browser's TLS fingerprint. When a site
answers with a challenge (Cloudflare), it solves it once in a real browser and
reuses the clearance for later requests, pacing and retrying along the way.
The browser is always Firefox, driven over WebDriver BiDi; Chromium is never
launched. What it learns per site is kept under the data dir it is given.
"""

from pathlib import Path
from urllib.parse import urlsplit

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


def cover_suffix(data: bytes) -> str | None:
    """The file suffix of a JPEG or PNG, judged by its bytes; None for anything else, since those are
    the only formats MP3 tags, M4B and EPUB volumes are built to carry."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    return None


def fetch_cover(url: str, data_dir: Path) -> tuple[bytes, str]:
    """The image at `url` and its file suffix. Raises FetchError unless it is a JPEG or PNG."""
    u = urlsplit(url)
    scraper = firefox_scraper(f"{u.scheme}://{u.netloc}", data_dir)
    try:
        response = scraper.get(url)
    except Exception as e:  # lncrawl-scraper's Blocked/Exhausted, or its HTTP stack's errors
        raise FetchError(f"{url}: {type(e).__name__}: {e}") from e
    finally:
        scraper.close()
    if response.status_code >= 400:
        raise FetchError(f"{url}: HTTP {response.status_code}")
    suffix = cover_suffix(response.content)
    if suffix is None:
        raise FetchError(f"{url}: not a JPEG or PNG")
    return response.content, suffix
