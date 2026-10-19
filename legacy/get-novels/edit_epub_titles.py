"""Edit EPUB chapter titles to 'Chapter N: Title' format."""

import re
import zipfile
import tempfile
import shutil
from pathlib import Path
from bs4 import BeautifulSoup

EPUB_PATH = Path("novels/Who-Let-Him-Cultivate.epub")


def extract_chapter_num(filename: str) -> int | None:
    """Extract chapter number from filename like 'chapter_001.xhtml'."""
    match = re.search(r"chapter_(\d+)", filename)
    return int(match.group(1)) if match else None


def clean_title(raw_title: str, chapter_num: int) -> str:
    """Convert title like 'Who Let Him Cultivate?! (WX)-Chapter 62: Location...' to 'Chapter 62: Location...'"""
    # Strip novel name prefix
    title = re.sub(r"^Who Let Him Cultivate[!?]*\s*\(WX\)\s*[-–]?\s*", "", raw_title)
    # Ensure 'Chapter N:' prefix
    if not re.match(r"^Chapter\s+\d+", title, re.IGNORECASE):
        # Try to extract just the subtitle after 'Chapter N: '
        match = re.match(r"^Chapter\s*\d+\s*[:：]\s*(.*)", title, re.IGNORECASE)
        if match:
            title = f"Chapter {chapter_num}: {match.group(1).strip()}"
        else:
            title = f"Chapter {chapter_num}: {title.strip()}"
    else:
        # Normalize existing 'Chapter N' format
        match = re.match(r"^Chapter\s*\d+\s*[:：]?\s*(.*)", title, re.IGNORECASE)
        if match:
            subtitle = match.group(1).strip()
            title = (
                f"Chapter {chapter_num}: {subtitle}"
                if subtitle
                else f"Chapter {chapter_num}"
            )
    return title


def main():
    tmpdir = Path(tempfile.mkdtemp())
    print(f"Extracting to {tmpdir}")

    # Extract EPUB
    with zipfile.ZipFile(EPUB_PATH, "r") as z:
        z.extractall(tmpdir)

    # Find all chapter HTML/XHTML files (inside EPUB/ subdirectory)
    chapter_files = sorted(tmpdir.rglob("*chapter_*.xhtml"))
    if not chapter_files:
        chapter_files = sorted(tmpdir.rglob("*chapter_*.html"))
    print(f"Found {len(chapter_files)} chapter files")

    # Update each chapter file
    for cf in chapter_files:
        ch_num = extract_chapter_num(cf.name)
        if not ch_num:
            continue

        soup = BeautifulSoup(cf.read_text(encoding="utf-8"), "html.parser")

        # Update <title> tag
        if soup.title:
            raw = soup.title.string or ""
            soup.title.string = clean_title(raw, ch_num)

        # Update <h1> or first heading in body
        for tag_name in ["h1", "h2", "h3"]:
            heading = soup.find(tag_name)
            if heading:
                raw = heading.get_text()
                heading.string = clean_title(raw, ch_num)
                break

        cf.write_text(str(soup), encoding="utf-8")

    # Update nav.xhtml (EPUB3 navigation)
    nav_file = tmpdir / "EPUB" / "nav.xhtml"
    if not nav_file.exists():
        nav_file = tmpdir / "nav.xhtml"
    if not nav_file.exists():
        nav_file = tmpdir / "OPS" / "nav.xhtml"
    if nav_file.exists():
        soup = BeautifulSoup(nav_file.read_text(encoding="utf-8"), "html.parser")
        for li in soup.find_all("li"):
            a = li.find("a")
            if a and "chapter_" in a.get("href", ""):
                ch_num = extract_chapter_num(a["href"])
                if ch_num:
                    raw = a.get_text()
                    a.string = clean_title(raw, ch_num)
        nav_file.write_text(str(soup), encoding="utf-8")
        print("Updated nav.xhtml")

    # Update toc.ncx (EPUB2 navigation)
    ncx_file = tmpdir / "EPUB" / "toc.ncx"
    if not ncx_file.exists():
        ncx_file = tmpdir / "toc.ncx"
    if not ncx_file.exists():
        ncx_file = tmpdir / "OPS" / "toc.ncx"
    if ncx_file.exists():
        soup = BeautifulSoup(ncx_file.read_text(encoding="utf-8"), "html.parser")
        for navpoint in soup.find_all("navpoint"):
            content = navpoint.find("content")
            if content and "chapter_" in content.get("src", ""):
                ch_num = extract_chapter_num(content["src"])
                if ch_num:
                    label = navpoint.find("text")
                    if label:
                        raw = label.get_text()
                        label.string = clean_title(raw, ch_num)
        ncx_file.write_text(str(soup), encoding="utf-8")
        print("Updated toc.ncx")

    # Repack EPUB
    backup = EPUB_PATH.with_suffix(".epub.bak")
    shutil.copy2(EPUB_PATH, backup)
    print(f"Backup saved to {backup}")

    with zipfile.ZipFile(EPUB_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype must be first, uncompressed
        mimetype_path = tmpdir / "mimetype"
        if mimetype_path.exists():
            z.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        for f in tmpdir.rglob("*"):
            if f.is_file() and f.name != "mimetype":
                z.write(f, f.relative_to(tmpdir))

    shutil.rmtree(tmpdir)
    print(f"Done! Updated {EPUB_PATH}")


if __name__ == "__main__":
    main()
