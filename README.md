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

## Tagging audio

```
python tag_audiobook.py --dir "tts_out/<novel>" --recursive --album "<Title>" --artist "<Author>" --comment "<description>" --cover "<path/to/cover.jpg>"
```

Cover images are stored in `novels/<novel>/cover.jpg`.

## Generating audio

Before generating audio, add the novel config to `NOVEL_CONFIGS` in `tts_reader.py`.

```
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>"
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>" --range 10-20
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>" --chapter 15
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>" --chapters 5,10,27
```

Novels split into multiple files (e.g. 50 chapters each) are passed one file at a
time; use the same `--out` dir so all chapters land in one place:

```
uv run tts_reader.py "novels/<novel>/index.html" --out "tts_out/<novel>"
```

For the whole novel at once (e.g. Return of the Mount Hua Sect, config already in
`NOVEL_CONFIGS`), run against the full `index.html`:

```
uv run tts_reader.py "novels/Return of the Mount Hua Sect/index.html" --out "tts_out/Return of the Mount Hua Sect"
```

Generation is resumable — already-generated sentences are skipped, so you can stop
(`Ctrl+C`) and run the same command again to continue.

Then tag the finished chapters:

```
uv run tag_audiobook.py --dir "tts_out/Return of the Mount Hua Sect" --recursive --album "Return of the Mount Hua Sect" --artist "Biga" --comment "Wuxia audiobook by Biga | Korean web novel" --cover "novels/Return of the Mount Hua Sect/cover.jpg"
```
