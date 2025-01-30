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


def main():
    for chapter in CHAPTERS.iterdir():
        # Detect the file encoding
        detected_encoding = get_encoding(chapter)
        # Read using the detected encoding
        with open(chapter, encoding=detected_encoding, errors="replace") as f:
            data = f.read()

        data = data.split("\n")
        title = data[1]
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
