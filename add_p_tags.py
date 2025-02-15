from pathlib import Path

import chardet

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


def main():
    sorted_files = sorted(
        CHAPTERS.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True
    )
    for chapter in sorted_files:
        data, detected_encoding = get_data(chapter)

        data = data.split("\n")
        try:
            title = data[1]
        except Exception:
            print("err", chapter)
            continue
        new_data = [f"<h1>{title}</h1>"]
        for d in data[1:]:
            if d.strip() and d.strip().lower() != title.strip().lower():
                new_data.append(f"<p>{d}</p>")

        # Write back using the original encoding
        with open(chapter, "w", encoding=detected_encoding, errors="replace") as f:
            print(f"writing to {chapter.stem} with encoding {detected_encoding}")
            f.write("".join(new_data))


if __name__ == "__main__":
    main()
