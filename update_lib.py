import json
from pathlib import Path

IGNORE = {".git", ".github", "css", "js", "venv", "__pycache__", ".idea"}


def main():
    library = []
    for folder in sorted(Path(".").iterdir()):
        if folder.is_dir() and folder.name not in IGNORE:
            if (folder / "index.html").exists():
                library.append(
                    {"title": folder.name, "path": f"{folder.name}/index.html"}
                )
                print(f"Added: {folder.name}")
    with open("library.json", "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2)


if __name__ == "__main__":
    main()
