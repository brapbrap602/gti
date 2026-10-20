import re
from pathlib import Path

if __name__ == "__main__":
    durr = Path(
        r"C:\Users\HT\Documents\code\MtlTings\data\translated\my_longevity_simulation"
    )
    all_content = []
    for file in sorted(durr.iterdir(), key=lambda x: int(x.stem.split("_")[1])):
        c = file.read_text(encoding="utf-8")
        lines = c.splitlines()
        
        # Check if the title is at the beginning (first 5 lines)
        has_title = False
        for line in lines[:5]:
            if re.search(r"Chapter\s\d+", line):
                has_title = True
                break
        
        if not has_title:
            # Insert title from filename
            # chapter_1765 -> Chapter 1765
            stem_parts = file.stem.split("_")
            new_title = f"{stem_parts[0].capitalize()} {stem_parts[1]}"
            all_content.append(f"<h1>{new_title}</h1>")

        for line in lines:
            if re.search(r"Chapter\s\d+", line):
                all_content.append(f"<h1>{line}</h1>")
            else:
                all_content.append(f"<p>{line}</p>")

    with (durr.parent.parent.parent / "my_longevity_simulation.index.html").open(
        "w", encoding="utf-8"
    ) as f:
        f.write("\n".join(all_content))
