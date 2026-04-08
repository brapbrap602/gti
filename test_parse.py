import sys

sys.stdout.reconfigure(encoding="utf-8")
import tts_reader as t

for path in [
    r"novels\Who Let Him Cultivate\index.html",
    r"novels\Who Let Him Cultivate\index_until912.html",
    r"novels\Who Let Him Cultivate\index_1_50.html",
]:
    soup = t.load_html(path)
    cfg = t.NOVEL_CONFIGS["who let him cultivate"]
    chapters = t.parse_chapters(soup, cfg)
    first, last = t.toc_chapter_range(soup)
    print(f"\n{path.split(chr(92))[-1]}")
    print(f"  Chapters found: {len(chapters)}, TOC range: {first}-{last}")
    if chapters:
        c0, cx = chapters[0], chapters[-1]
        print(f"  First: [{t.chapter_index(c0)}] {c0['title'][:70]}")
        print(f"         para[0]: {c0['paragraphs'][0][:80]}")
        print(f"  Last:  [{t.chapter_index(cx)}] {cx['title'][:70]}")
