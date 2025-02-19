import time
from pathlib import Path
import chardet
from concurrent.futures import ThreadPoolExecutor

CHAPTERS = Path(r"chapters")


def get_encoding(chapter):
    detected_encoding = "utf-8"
    try:
        with open(chapter, "rb") as f:
            raw_data = f.read()
            detected_encoding = chardet.detect(raw_data)["encoding"]
    except Exception as e:
        print(e)
    return detected_encoding


def get_data(chapter):
    detected_encoding = get_encoding(chapter)
    with open(chapter, encoding=detected_encoding, errors="replace") as f:
        data = f.read()
    return data, detected_encoding


def process_chapter(chapter):
    data, detected_encoding = get_data(chapter)
    data = data.split("\n")
    title = None
    try:
        for d in (data[1], data[0]):
            if d.strip() and 'chapter' in d.lower():
                title = d
    except Exception:
        print("err", chapter)
        return  # Skip processing this chapter
    if not title:
        raise SystemExit
    new_data = [f"<h1>{title}</h1>"]
    for d in data[1:]:
        if d.strip() and d.strip().lower() != title.strip().lower():
            new_data.append(f"<p>{d}</p>")

    with open(chapter, "w", encoding=detected_encoding, errors="replace") as f:
        print(f"writing to {chapter.stem}")
        f.write("".join(new_data).replace("Qin桑", "Qin Sang").replace("Qin桑", "Qin Sang"))


def main():
    five_minutes_ago = time.time() - 300000  # 5 minutes in seconds
    recent_files = [
        f for f in CHAPTERS.iterdir() if f.stat().st_mtime >= five_minutes_ago
    ]
    print(f"Found {len(recent_files)}")
    with ThreadPoolExecutor() as executor:
        executor.map(process_chapter, recent_files)
    # process_chapter(Path(r'C:\Users\HT\Documents\code\github_pages\chapters\chapter_1501.html'))

if __name__ == "__main__":
    main()