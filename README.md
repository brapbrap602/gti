# github_pages

## Adding a new novel

### If the HTML file already has a TOC

```
uv run scripts/split_novel.py "novels/<novel>/index.html" <chapters_per_file>
```

### If the HTML file has no TOC (flat Calibre export)

```
uv run scripts/extract_chapters.py "novels/<novel>/index.html"
uv run scripts/insert_toc.py "novels/<novel>/chapter_headers.txt" "novels/<novel>/index.html"
uv run scripts/split_novel.py "novels/<novel>/index.html" <chapters_per_file>
```

## Generating audio

Before generating audio, add the novel config to `NOVEL_CONFIGS` in `tts_reader.py`.

```
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>"
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>" --range 10-20
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>" --chapter 15
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>" --chapters 5,10,27
```
