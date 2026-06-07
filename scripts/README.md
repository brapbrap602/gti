# Scripts

## Adding a new novel

### If the HTML file already has a TOC

```
python scripts/split_novel.py "novels/<novel>/index.html" <chapters_per_file>
```

### If the HTML file has no TOC (flat Calibre export)

```
python scripts/extract_chapters.py "novels/<novel>/index.html"
python scripts/insert_toc.py "novels/<novel>/chapter_headers.txt" "novels/<novel>/index.html"
python scripts/split_novel.py "novels/<novel>/index.html" <chapters_per_file>
```

## Scripts

### `split_novel.py`
Splits a Calibre HTML file into multiple files by chapter range and updates `data/library.json`.

```
python scripts/split_novel.py <input_html> <chapters_per_file>
```

### `extract_chapters.py`
Extracts chapter headers from a flat Calibre HTML file into a text file for use by `insert_toc.py`.

```
python scripts/extract_chapters.py <input_html> [output_file]
```

Output defaults to `chapter_headers.txt` in the same directory as the input file.

### `insert_toc.py`
Inserts a TOC `<nav>` element into a Calibre HTML file using headers from `extract_chapters.py`.

```
python scripts/insert_toc.py <headers_file> <input_html> [output_html]
```

Output defaults to overwriting the input file in-place.
