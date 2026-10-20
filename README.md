# github_pages

This repo (gti) is being consolidated into a uv workspace for novel tooling; see
`docs/plans/novel-platform-stakeholder.md`. Until the cutover, the root scripts
below still build the live site.

## Development

```
uv sync                                  # installs the workspace packages and dev tools
uv run pytest                            # live-site tests are skipped unless you pass -m live
uv run lint-imports                      # novel_core must not import the outer packages
uv run python tools/secret_scan.py       # fails on API-key-shaped strings in tracked files
```

The new tooling is the `nov` command. Novels live in `$NOVELS_DATA_DIR` (default `%LOCALAPPDATA%/novels`), one folder per novel:

```
uv run nov import wns "%LOCALAPPDATA%\web-novel-scraper\web-novel-scraper\<Title>"   # [--novel <slug>]
uv run nov import mtl "<MtlTings>\data\raw\<novel>"         # raws as raw-zh; data\translated\<novel> as my-translation
uv run nov import scribble "<file>" --novel <slug>          # scribblehub text dump ('## Chapter N: Title' markers)
uv run nov import calibre "novels\<Novel>" --novel <slug>   # old site's Calibre HTML pages; import last (ranks lowest)
uv run nov priority <slug> [3,1,2]       # show the sources best first, or set the order
uv run nov check <slug>                  # gaps, duplicates, unmapped chapters, failed pages, ...
uv run nov align item <slug> <ref> 1277   # give an item an explicit key (524pt1 for a part); --source when several
uv run nov align skip <slug> <ref>...    # leave reposts/notices out of the book
uv run nov build site                    # every novel -> <data dir>/_site (incremental; --force rebuilds all)
uv run nov deploy site                   # force-push _site as orphan gh-pages, then wait until it is live
uv run nov cover <slug> <image.jpg|png>  # cover for audio tags, M4B and EPUB (copied into the novel folder)
uv run nov build epub <slug>             # EPUB per 100 chapter numbers -> <data dir>/_epub/<slug> (--size, --force)
uv run nov build audio <slug>            # edge-tts MP3 per chapter -> <data dir>/_audio/<slug> (--range 1-100, --voice, --force)
uv run nov build volumes <slug>          # M4B per 100 chapter numbers, with chapter marks and cover
uv run nov audio register <slug> "tts_out/<novel>" --key position|title-number   # [--shift 736-1442:+4]
uv run nov audio retag <slug>            # rewrite tags of every chapter MP3, legacy ones included
```

Audio needs ffmpeg on PATH. Built chapters are recorded per chapter, so an interrupted
`nov build audio` resumes where it stopped; sentences are cached under `_audio/<slug>/_sentences`,
so an edited chapter re-synthesizes only the sentences that changed. Changing `--voice` rebuilds
every built (non-legacy) chapter. `nov audio register` checks each old `chapter_NNN` folder against
its text using the per-sentence file names and reports mappings that don't fit instead of registering them.

Reading pages hold 50 chapter numbers each (`novels/<slug>/1-50.html`, anchors `#c524`, `#c524-1` for parts).
In Git Bash, `export MSYS_NO_PATHCONV=1` first, or refs starting with `/` are rewritten into Windows paths.
`nov deploy site` aborts before pushing if the site is over 900 MiB (`--budget-mb`).

- `packages/`: the workspace packages (`novel-core` ← `novel-sources`, `novel-publish`, `novel-audio` ← `novel-app`).
- `tools/scrub_fixture.py`: turns a real chapter page into a test fixture without novel prose.
  The host fixtures in `tests/fixtures/hosts/` were made with
  `--keep '\S*(?:nov|ovel|web|kiss)\S*' --keep 'Translator:|Editor:' --keep 'Previous Chapter|Next Chapter|Project Page|Support Us on Ko-fi'`
  so the junk lines the cleanup rules must remove survive the scrub.
- `tools/copy_legacy.py`: freezes old scraper scripts into `legacy/`, aborting if any contains a key.
- Secrets are read only from environment variables. Never commit keys or a `.env` file.

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
