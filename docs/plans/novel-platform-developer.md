# Novel platform consolidation: developer plan

Status: **APPROVED r3 (2026-10-18)**. Reviewed three times: baseline, final, and a focused follow-up on r2. All P1 findings are resolved (§15). Implementation is not authorized.
Companion: [stakeholder-plan.md](novel-platform-stakeholder.md)
Source: planning session of 2026-10-18 (requester: repo owner, single user).

## 1. Goal

Put all novel tooling in one repo, **gti** (`github.com/brapbrap602/gti`, public; local clone `github_pages`), organized as a **uv workspace**. The center of the design is a **canonical IR store**: source backends write into it, and site, EPUB and audio are projections built from it. A CLI and a local web UI both run over one core service. Use third-party code wherever something close exists.

## 2. Terminology

| Term | Meaning |
|---|---|
| Novel | One work, e.g. "Cultivation Chat Group". It owns metadata, sources, the priority policy and alignment rules. |
| Source | One place a novel comes from: a backend kind, a URL and a language. A novel can have many sources. |
| Backend | The code that talks to a site: `lncrawl`, `lnreader` (Node), `decode-guide`, `novel-downloader`, or `custom:<name>`. |
| Importer | One-shot reader of a **legacy** local store: web-novel-scraper, MtlTings, scribblehub text, Calibre HTML. Every importer creates a normal Source row (`backend=import:<kind>`) and goes through the same `record_index` alignment, so import output can be pinned and prioritized like any source. |
| SourceItem | One entry in a source's chapter list. Its **identity is `(source_id, item_ref)`**. Position, printed number, part and title are mutable attributes. Raw HTML files and Versions refer to the item_ref, never to the position. **item_ref per backend:**<br>- *Web backends* (lncrawl, lnreader, decode-guide, custom, novel-downloader): the canonical URL **path**, i.e. the URL with scheme, host, query, fragment and trailing slash removed. If G1 shows lncrawl gives no URL, use its chapter id instead.<br>- `import:wns`: the canonical path of `chapter_url`.<br>- `import:mtl`: the file name.<br>- `import:scribble`: `<file>#<header-ordinal>`.<br>- `import:calibre`: `<file>#<calibre_link id>`.<br>If a host changes path layout, `nov source rebase-urls <source> <old-prefix> <new-prefix>` rewrites the refs. Items marked `vanished` are left out of key derivation and duplicate detection. |
| ChapterKey | Canonical chapter identity `(number:int, part:int=0)`, ordered lexicographically. Label: `"524"` or `"524 pt 1"`. |
| Version | One text of one chapter from one source or importer. `kind` is one of `official-en`, `raw-zh` or `my-translation`. Holds title, blocks, content hash and provenance. |
| Selection | Decided **per chapter number N**, never per individual key:<br>1. Choose one source for N. A pin covering N comes first; otherwise the first source in the priority list that has *any* non-`raw-zh` version for N. Pin ranges are inclusive and cover every part of each number.<br>2. Emit **only that source's** keys for N. If that source has parts above 0 for N, its part 0 is dropped; parts from other sources are never mixed in.<br>3. If the pinned source has nothing for N, fall back to priority and `check` warns. A pin to a `raw-zh` source is rejected.<br>4. Within the chosen source, each item's **current** version is the one with the greatest `last_seen_at`, with ties broken by the higher version id. A refresh that returns to an older text makes that text current again.<br>`check` warns when sources disagree on whether N is split. |
| Block | IR content unit: `paragraph` (inline runs: text/em/strong), `heading`, `separator`, `image`, `system`, `note`. |
| Build | Producing site, EPUB or audio output from the selections. It is incremental, tracked per chapter by selected-version hash. |
| Legacy audio | Existing `tts_out/<novel>/chapter_NNN/chapter_NNN.mp3` registered as done. It is never regenerated unless forced. |

## 3. Approved decisions

1. One repo, gti, as a uv workspace. **Code only in git.** Novel content lives in a local data dir outside git (`NOVELS_DATA_DIR`, default `%LOCALAPPDATA%\novels`).
2. A novel can mix sources. **All versions are kept.** Selection uses the per-novel **source priority list** plus **pins for chapter ranges**.
3. Chinese raws are a normal source (`raw-zh`). They are stored, never published, and wait for the translation project.
4. Translation and glossary are **out of scope** and get their own later project. MtlTings is archived. The IR keeps a `my-translation` kind.
5. Acquisition backends v1: lncrawl (primary), LNReader plugins via Node harness, web-novel-scraper decode guides, ported custom importers (novelbuddy API, skydemonorder free list). EN and ZH sources. *Added from third-party scouting:* novel-downloader as the ZH raw backend.
6. lncrawl is used **headless as an engine only**. Its server/UI is not used.
7. **Prefer third-party** wherever close (§7).
8. Outputs: static site (GitHub Pages), EPUB with correct metadata, audio as **per-chapter MP3 plus M4B volumes** with chapter markers.
9. Typed blocks IR. **Superseded scope:** v1 *guarantees* only paragraph, heading, separator and image. `system` and `note` come from optional per-novel detection rules (review finding 6).
10. One SQLite file per novel, plus raw fetched HTML stored alongside, compressed.
11. Alignment: source printed number plus per-source offset plus explicit range overrides. A `check` reports gaps, duplicates and title mismatches. Range overrides are needed in v1 (CCG drift). **Key derivation, the one rule all backends and importers share** (owned by `record_index`):
    - The printed number comes from the backend's number field, or else the title/slug (`Chapter N`, `第N章` via cn2an, slug `chapter-N` or `^N-`).
    - The part comes from a trailing `(N)`, `part N` or `pt N`; otherwise it is 0.
    - Precedence: an explicit item override, then a range override, then the per-source offset added to the printed number.
    - An item with no number (prologue, side story, notice) is **`unmapped`**. It is listed by `check` and gets a key only through an explicit override.
    - Keys are **never stored on Versions or output rows**. They are derived on read from `(source_id, item_ref)`, so editing an override moves every Version and every output row with it in one step.
12. **Split parts are separate canonical entries** (BTS "part 1/2", Mount Hua "(1)/(2)/(3)"). **Superseded:** "Chapter = canonical integer number" is replaced by `ChapterKey(number, part)`.
13. Imports v1: web-novel-scraper store, MtlTings raws and translations, scribblehub Longevity 439–836, github_pages Calibre HTML (lowest priority).
14. Legacy audio is kept and registered. **Superseded:** "map by NNN". It is now mapped by a per-novel key type (§9.4).
15. CLI plus local web UI over the same service. Web UI v1: dashboard, sync/build with live progress, add novel by URL, side-by-side version compare plus pin.
16. Proposed and baseline-confirmed: `sync` (fetch and normalize) is separate from `build site|epub|audio`.
17. Site is deployed by force-pushing an **orphan `gh-pages`** branch. main has no site HTML. **Old URLs break** (no redirects).
18. Chinese-only novels (Transcendental Mechanic) are imported and shown as "raw only". Builds skip them.
19. Legacy per-novel scraper `.py` files are copied to `gti/legacy/<name>/` with keys scrubbed. Original folders are untouched.
20. gti is licensed GPL-3.0. Secrets are read only from env. The user rotates the OpenRouter and Google keys.
21. Test fixtures keep real structure with **scrubbed text**. No novel prose goes in git.

**Out of scope:** translation and glossary, scheduled sync, editing chapter text in the UI, moving off public hosting, rewriting gti git history, rebuilding the 4.2 GB `book.mp3`.

## 4. Verified baseline (evidence)

- Site: `index.html` loads `data/library.json`. Pages are `novels/<Novel>/index_A_B.html` (Calibre HTML). `assets/chapter.js` labels chapters as `id+1`. There is no localStorage. Pages serves `main` `/` (legacy build, no `.nojekyll`) at `brapbrap602.github.io/gti/`. `novels/` is 231 MB.
- Calibre HTML parsing is reimplemented in `scripts/split_novel.py`, `extract_chapters.py`, `insert_toc.py`, `tts_reader.py` (`parse_chapters*`, `NOVEL_CONFIGS` lines 53–91) and `assets/chapter.js`. The chapter-number regex is duplicated in 4 places.
- Audio: `tts_reader.py` writes `<out>/chapter_NNN/chNNN_pPPP_sSSS.mp3` plus `chapter_NNN.mp3`, with sentence-level skip-if-exists. NNN = `calibre_link id - id_offset` unless `chapter_num_from_title` is set (lines 312–318). The book/CHAP code is commented out (683–691). `tag_audiobook.py` sets TRCK=NNN.
- web-novel-scraper store: `%LOCALAPPDATA%\web-novel-scraper\web-novel-scraper\<Title>\data\{main.json, chapters/, toc/}`. `chapters/` holds full raw site pages. It contains 7 novels plus 1 empty one. Longevity has 170/1005 files; Mount Hua 1–229 is missing; CCG has 72 extra NovelHi files; Golden Core has hash filenames; titles contain U+FFFD; only BTS has an author.
- MtlTings: raws in `data/raw/<novel>/` as `chapter_N.txt` (Longevity, 369–1781 with a gap 497–911) or `#N_ Title.txt` (CCG 3177, Transcendental Mechanic 1472). Translations are `data/translated/my_longevity_simulation/chapter_N.html` (plain text, 990–1781). All data is tracked in git. Its remote is gti, with 43 unpushed commits containing a key.
- Scribblehub file `mycoreistheboss/My Longevity Simulation`: CRLF, the first header is `## Chapter N`, later ones are `Chapter N: Title`, and 439 appears twice.
- There are no automated tests (`test_parse.py` only prints).
- **gti remote state** (`git ls-remote`, final review): only `refs/heads/main` at d50b366, with no gh-pages. MtlTings' `origin` is gti, but its history is **unrelated** to gti main (different root commits), and its tracking ref f10ba0de is no longer in gti. A plain push would be rejected. `push -f` would replace the live site's main with MtlTings history, including a key.
- **The working tree is dirty.** The Barbarian novel files, `data/library.json` and the `tts_reader.py` Barbarian config are uncommitted. The live site therefore has no Barbarian yet.
- Python is pinned to 3.12 (`.python-version`). Stdlib zstd is only available in 3.14. ffmpeg is installed via WinGet but not declared. Windows LongPathsEnabled=1.

## 5. Flows

### 5.1 Normal
1. `nov add <url> [--novel <id>] [--lang en|zh] [--backend auto|…]`: the backend is auto-picked by host (lncrawl if it supports the host, then custom, then decode-guide, then lnreader). It creates or attaches a Source and fetches metadata and the index.
2. `nov sync <novel>|--all [--refresh <range>]`: for each source, fetch the index, map items to ChapterKeys, then fetch and normalize items that have no version. With `--refresh`, re-fetch and store a new Version only if the content hash differs.
3. `nov check <novel>`: gaps, duplicate keys, title-number mismatches, and items unmapped by the alignment rules.
4. `nov pin <novel> <range> <source>` / `nov priority <novel> <src1,src2,…>`.
5. `nov build site|epub|audio <novel>|--all [--force <range>]`: rebuilds chapters whose selected-version hash changed since the last build.
6. `nov deploy site`: assembles the whole site, runs a size check, force-pushes orphan `gh-pages`, then smoke-fetches the live URL.
7. `nov import <kind> <path> --novel <id>`: one-shot legacy imports.
8. `nov serve`: the web UI on `127.0.0.1`.

### 5.2 Exceptional
| Case | Behavior |
|---|---|
| Fetch fails (network, 5xx, Cloudflare) | Per item: retry with backoff through the fetch ladder (§7). If it still fails, record `item_status=failed(reason)`, continue with other items, and exit non-zero with a summary. Re-running retries the failed items. |
| Interrupted sync or build (Ctrl-C, crash, server stop) | Every write is per-item and idempotent (one transaction per Version). A re-run continues. Job rows are marked `interrupted` at startup. |
| Source index shrinks or reorders | Items are matched by `item_ref` (URL), not position, so an insertion in the middle only updates positions. Existing Versions are never deleted. Items missing from the new index are flagged `vanished` in `check`. |
| Override edited after import or build | Keys are derived on read, so Versions move with the override. Output rows are keyed by `built_key`. On the next build, a key whose selected item now differs from its row is rebuilt, and rows and artifacts for keys that are no longer selected are **pruned** (site pages and EPUB chapters deleted). Legacy audio rows are never pruned or rebuilt automatically. `check` lists them as "legacy row's item moved" for you to resolve. |
| Template, CSS or normalizer rules change | Output rows store `builder_fingerprint`. A new fingerprint makes those outputs stale. Changed cleaner rules apply only after `nov renormalize <novel> [--source]`, which writes new Versions from the stored raw HTML (no refetch). |
| Two sources map to the same key with different content | Both are kept as Versions. Selection decides which is used. |
| Duplicate key within one source | `check` reports it. The later item's number is not guessed; the user adds an override. |
| Chapter locked or premium (Mount Hua 1–229) | Stored as a gap (`item_status=unavailable`). It is not an error. |
| Glossary/translation | n/a (out of scope) |
| Second job for the same novel | Rejected with "job already running". This is enforced **across processes**: a lock row in `app.sqlite` is taken with `BEGIN IMMEDIATE`, held with a heartbeat, and both the CLI and `nov serve` check it. A lock whose heartbeat is older than 60 s is treated as stale and can be taken over. Jobs for different novels may run in parallel (cap: 2). |
| Missing secret/env | Commands that need it fail at startup with the env var name. Secrets are never logged. |
| Site exceeds size budget (default 900 MB) | Deploy aborts before pushing. |

## 6. Architecture

### 6.1 Workspace layout (proposed paths)

```
gti/
  pyproject.toml            # [tool.uv.workspace] members = ["packages/*"]
  packages/
    novel-core/             # IR types, ChapterKey, NovelStore (SQLite), selection, alignment, check
    novel-sources/          # Source seam, fetch ladder, normalizer, backends, legacy importers
    novel-publish/          # site (Jinja2) + EPUB (ebooklib) builders
    novel-audio/            # TTS (edge-tts), sentence cache, legacy registration, MP3 tags, M4B volumes
    novel-app/              # Service, job runner, CLI (Typer), web UI (FastAPI + Jinja2 + htmx + SSE)
  tools/lnreader-harness/   # Node 22 project: bundles and runs LNReader plugins, prints JSON
  legacy/<name>/            # frozen old scraper .py files (scrubbed)
  tests/fixtures/           # scrubbed real-structure fixtures + scrub script
  LICENSE (GPL-3.0)
```

Dependencies point inward: `novel-app → {sources, publish, audio} → novel-core`. novel-core has no network, HTML or TTS dependencies. An import-linter contract enforces this in CI.

**lncrawl is not a workspace dependency.** Its dependency set (fastapi, sqlmodel, psycopg, alembic, …) would be forced into the single workspace lock. It runs as a subprocess from an isolated tool env (`uv tool install lightnovel-crawler==<pinned>`), called with the JSON output format, and the ZIP is imported. Gate G1 checks whether it can live in-workspace instead.

### 6.2 Deep modules and interfaces (illustrative Python, proposals)

**NovelStore** (novel-core): the single owner of novel facts.
```python
class NovelStore:                      # one per novel.sqlite; context manager owns the connection
    @classmethod
    def open(cls, path: Path) -> "NovelStore": ...
    novel: NovelMeta
    def upsert_source(self, spec: SourceSpec) -> SourceId: ...
    def record_index(self, source: SourceId, items: Sequence[SourceItem]) -> IndexDiff: ...
    def put_version(self, source: SourceId, item_ref: ItemRef, v: NewVersion) -> PutResult: ...   # Inserted | Unchanged(hash); Unchanged bumps last_seen_at via injected Clock
    def mark_item(self, source: SourceId, item: ItemRef, status: ItemStatus) -> None: ...
    def set_priority(self, sources: Sequence[SourceId]) -> None: ...
    def set_pin(self, keys: KeyRange, source: SourceId) -> None: ...      # rejects raw-zh
    def set_alignment(self, source: SourceId, rules: AlignmentRules) -> AlignmentDiff: ...  # offsets/overrides; returns moved items
    def renormalize(self, source: SourceId, normalize: Callable[[RawChapter], Blocks]) -> int: ...
    def selection(self) -> Sequence[Selected]: ...         # pins + priority + current-per-source + part-0 suppression, never raw-zh
    def plan_build(self, output: OutputKind, fingerprint: str) -> BuildPlan: ...   # per key: to_build[Selected], to_prune[OutputRow]; legacy rows excluded
    def record_output(self, output: OutputKind, selected: Selected, fingerprint: str, artifact: str) -> None: ...  # upsert by (kind, built_key)
    def prune_output(self, output: OutputKind, key: ChapterKey) -> None: ...
    def check(self) -> CheckReport: ...
```
It hides the schema, transactions (one per call), the alignment rules (`record_index` maps items to keys through offsets and overrides), and the selection policy. Callers never write SQL and never compute selection.

**Source** (novel-sources): the external seam with several real adapters.
```python
class Source(Protocol):
    def fetch_index(self) -> NovelIndex: ...            # meta + ordered SourceItems
    def fetch_chapter(self, item: SourceItem) -> RawChapter: ...   # html|text, fetched_at, final_url
```
`normalize(raw: RawChapter, rules: CleanRules) -> Blocks` is a single function. Per-host junk rules are data (selectors, bad-text regex in the style of lncrawl's TextCleaner), and per-novel rules add `system` and `note` detection. Importers implement the same two-step shape against a frozen local store: `Importer.read_index() -> NovelIndex` (SourceItems with item_refs per §2) and `Importer.read_chapter(item) -> RawChapter`. The sync orchestrator runs both through `record_index` and `put_version`, so alignment has exactly one owner.

**sync(store, sources, fetcher)** (novel-sources): the only orchestrator of fetch, normalize and put. It takes injected `Fetcher` and `Clock` for tests.

**Builders** (publish/audio): `build_site(stores, out_dir)`, `build_epub(store, out_dir, volume_size)`, `build_audio(store, out_dir, tts: TtsEngine)`. Each one calls `plan_build`, writes the artifacts in `to_build` and calls `record_output`, then deletes the artifacts in `to_prune` and calls `prune_output`. Staleness is computed **per key**: the selected `(source, item_ref, version_hash, fingerprint)` differs from the row, or the row's item no longer derives to `built_key`. `TtsEngine` is a seam (edge-tts in production, a fake that writes silent MP3s in tests).

**Service** (novel-app): the only API that the CLI and web routes call (`add`, `sync`, `build`, `check`, `pin`, `status`, `compare`). It runs long operations as jobs in an in-process `ThreadPoolExecutor`, with job rows and progress in `app.sqlite` streamed over SSE. It enforces one job per novel.

**SQLite concurrency contract:**
- Every DB file uses WAL with `busy_timeout=5000`.
- There is one SQLAlchemy engine per file, and each thread uses its own connection; connections are never shared across threads.
- A job writes one short transaction per item.
- Progress is held in memory, pushed over SSE, and persisted to `app.sqlite` at most once per second plus at job end.
- Web reads use their own connections and see committed state only.

### 6.3 Material design choices

| Choice | Alternatives rejected | Why / consequence |
|---|---|---|
| SQLite per novel, owned by NovelStore | JSON files; one global DB | Atomic writes and gap queries. A per-novel file keeps blast radius small. Cross-novel views iterate stores (fine at ~10 novels). |
| ChapterKey `(number, part)` | Plain int; source position | Supports split parts and stays stable across sources. Position-numbered legacy data maps through the source item list at import. |
| Content-hash Versions, never deleted | Overwrite in place | Re-scrapes can't silently replace text. Storage grows only when content actually changes. |
| Build tracking by selected-version hash | mtime; full rebuild | Pins and priority changes automatically mark the affected outputs stale. |
| Audio sentence cache keyed by `hash(voice, sentence_text)` | Positional `pPPP_sSSS` names | Re-splitting or editing a paragraph regenerates only the changed sentences. Legacy positional files are not reused at sentence level, only at chapter level. |
| lncrawl via subprocess + JSON | In-process `Crawler` classes | No stable public API (verified). Internals changed heavily in 2026. |
| In-process job runner | huey/SqliteHuey (thread workers) | Single user. Simpler: no separate worker process. Interrupted jobs resume because steps are idempotent, so durable queues aren't needed. |
| FastAPI + Jinja2 + htmx **2.x** + `htmx-ext-sse` | NiceGUI, Streamlit; htmx 4 | Server-rendered pages reuse the site's Jinja/CSS. The compare view is custom. htmx 4 is a fresh major version, so stay on the stable 2.x line (G4). |
| Keys derived on read from `(source_id, item_ref)` | Keys stored on Versions | Editing an override can never strand Versions or audio on old keys. Costs a join, which is trivial at this scale. |
| Jinja2 static site | Hugo/MkDocs | Data is in SQLite. SSGs struggle with 1000+ chapter navigation. |

## 7. Third-party components (each pinned; gates in §11)

| Concern | Component |
|---|---|
| EN scraping | lightnovel-crawler **pinned `==4.14.0`** (subprocess, JSON ZIP; G1 re-verifies the CLI flags), LNReader plugins via `tools/lnreader-harness` (adapted from upstream `scripts/live-check-plugin.js`; MIT license and script existence re-verified in G2), web-novel-scraper decode-guide JSON (our own engine reads the guide format) |
| ZH raws | novel-downloader (Python API), OpenCC `t2s`, cn2an (Chinese numerals → int) |
| Fetch ladder | curl_cffi impersonation → FlareSolverr/Byparr sidecar (cookie harvest) → per-host rate limit |
| Cleanup | per-host selectors + TextCleaner-style rules (vendored from lncrawl, GPL). *Optional:* trafilatura fallback for unknown hosts. |
| Store | SQLAlchemy Core (SQLite), Alembic-free schema versioning via `PRAGMA user_version`; `zstandard` for raw HTML compression (no stdlib zstd before 3.14) |
| Prerequisites | ffmpeg on PATH (declared in README; `nov doctor` checks it), Node 22 only for the LNReader harness |
| CLI / UI / jobs | Typer; FastAPI, Jinja2, htmx, sse-starlette; stdlib ThreadPoolExecutor |
| EPUB | ebooklib (AGPL-3.0; compatible with GPL-3.0, local use) |
| Audio | edge-tts (unofficial Microsoft endpoint; accepted risk, with the `TtsEngine` seam allowing a swap later), pySBD (+ length cap / short-fragment merge), ffmpeg (concat, AAC, FFMETADATA chapters → M4B), mutagen (MP3 ID3) |
| Tests | pytest, pytest-httpserver or recorded responses, Typer CliRunner, FastAPI TestClient, import-linter |

## 8. Data model (SQLite, novel.sqlite)

`novel(id, title, author, cover_path, status, language, tags_json, priority_json)`
`source(id, backend, url, lang, kind, offset, overrides_json, backend_config_json)`: importers are sources too (`backend=import:<kind>`)
`source_item(source_id, item_ref, position, printed_number, part, title, status, last_seen_at)`: unique `(source_id, item_ref)`; the key is derived (view `item_key`)
`version(id, source_id, item_ref, kind, title, blocks_json, content_hash, first_seen_at, last_seen_at, provenance_json, raw_path)`: unique `(source_id, item_ref, content_hash)`. "Current" = max `last_seen_at`. `put_version` on Unchanged updates `last_seen_at`.
`pin(range_start, range_end, source_id)`
`output(kind, built_key, source_id, item_ref, version_hash, builder_fingerprint, artifact, built_at, legacy:bool)`: **one row per `(kind, built_key)`**. A key switching sources replaces the row, so no key is ever claimed twice. Legacy rows are exempt from staleness and pruning unless `--force`.
`volume(kind='m4b', range_start, range_end, membership_hash, artifact, built_at)`: membership_hash = hash of the ordered `(key, version_hash)` of its chapters. A different hash means stale.

Raw HTML: `<data>/<novel-slug>/raw/<source_id>/<sha1(item_ref)>-<sha1(raw)[:12]>.html.zst`. One file per distinct raw, so every Version's `raw_path` stays valid and `renormalize` can rebuild any version. Data-dir names are ASCII slugs, never titles.
Invariants: a Version is immutable apart from its `last_seen_at`; `selection()` never returns `raw-zh` and never returns both part 0 and part >0 for one number; keys are never persisted outside `built_key`.

## 9. Imports and migration

### 9.1 web-novel-scraper store
- Order and URL come from `main.json.chapters` (`chapter_url`, `chapter_html_filename`, `chapter_title`).
- The number comes from the **URL slug** (`chapter-(\d+)`, skydemonorder `^(\d+)-`), and the part from a `(N)` or `part N` suffix.
- A null filename becomes item `unavailable`.
- HTML is normalized with per-host rules for freewebnovel, novelbin.me/.com, novelbuddy.me/.com and skydemonorder.
- `item_ref` = `chapter_url`. The import is an `import:wns` Source, and the store snapshot is frozen as provenance (main.json is copied into the data dir).
- CCG: the 72 NovelHi files are **not imported** (they aren't referenced by main.json; this is recorded in the import report). The importer seeds the CCG range override for the drift from position 1897 via `set_alignment`.
- Titles are repaired with `ftfy`. U+FFFD is kept but flagged. Title-mismatch checks ignore the U+FFFD position.

### 9.2 MtlTings
- `chapter_N.txt` gives N from the filename.
- `#N_ Title.txt` gives N from the prefix, with an offset seeded per novel (CCG raws start at `#0_`).
- Translations become `my-translation` Versions, with provenance `{model:"unknown (MtlTings)", glossary:null}`.

### 9.3 Scribblehub / Calibre HTML
- Scribblehub: split on `^(##\s)?Chapter (\d+):`. The duplicate 439 keeps the longer body and is flagged.
- Calibre HTML: a parser per the current `NOVEL_CONFIGS` semantics (ported once, then frozen) at the lowest priority. Numbers come from TOC titles, not ids.

### 9.4 Legacy audio registration
- Per-novel config `legacy_audio: {dir, key: position|title-number, source: <source_id>}`.
- `position` (BTS, CCG): `NNN` is resolved against the **frozen WNS import snapshot** (the position in the copied main.json, never a live index) to an `item_ref`. The output row stores `(source_id, item_ref)`, so its key follows later override edits.
- `title-number` (Barbarian, WLHC): `NNN` becomes `ChapterKey(NNN, 0)`, which is resolved at registration to the item in the configured source that derives to that key. If no item maps to it, the folder is listed as "unregistered legacy audio" in the import report and left untouched.
- Legacy rows are keyed by `(kind='audio', built_key)`. A later switch to a higher-priority source for that key does **not** regenerate the MP3 (only `--force` does). `check` lists keys whose legacy audio came from a non-selected source.
- A chapter is registered only if `chapter_NNN.mp3` exists and is non-empty. Partial dirs are ignored (they get rebuilt).
- `test_bts/` and `book.mp3` are skipped.
- `output.legacy = true`, and `version_hash` = the hash of the version selected at registration time.
- Legacy rows are not considered stale when the selection changes, unless `--force`. Retagging is opt-in (`nov audio retag`).

### 9.5 Cutover (order matters)
0. **Preconditions (before slice 0, needs user confirmation):**
   - **Detach MtlTings from gti now** (`git -C MtlTings remote remove origin`) to prevent an accidental `push -f` that would replace the live site with MtlTings history and its key.
   - **Commit or snapshot the dirty github_pages tree** (Barbarian files, library.json, tts_reader.py) as the comparison baseline.
   - Copy the current `tts_reader.py`, `tag_audiobook.py`, `scripts/`, `test_parse.py` and `main.py` into `legacy/github_pages/` as reference. `tag_test/` covers go to the data dir.
1. Build the new site to a local dir and compare it against the current site for the same novels (chapter count per novel, first and last chapter text).
2. Push orphan `gh-pages` with `.nojekyll`. Switch the Pages source to `gh-pages` / root (manual or `gh api`, user-confirmed). Smoke-fetch `https://brapbrap602.github.io/gti/`.
3. Only then remove `novels/`, `data/library.json`, `index.html` and `assets/` from main (they are now built from templates).
4. MtlTings: the user rotates the key (the remote was already removed in step 0). The folder stays on disk as the archive.
5. Copy legacy `.py` files, scrubbed by a secret scan that fails on any key pattern.

## 10. UI (applies: substantial, new local app)

Journey: open `nov serve`, see the library, spot novels with new chapters or gaps, sync, inspect, pin, build.
- **Library page.** A row per novel: sources (lang, backend), counts per kind, gaps, last sync, new items available (from the last index fetch), site/EPUB/audio staleness, and a "raw only" badge. Actions: Sync, Build ▾, Open.
- **Novel page.** A chapter grid in ranges of 100: a cell per ChapterKey colored by state (selected kind, missing, failed, pinned). It has a source priority editor (drag order) and a check report.
- **Compare view.** Pick a chapter, then see two versions side by side (rendered blocks), with "Pin this source for [range]".
- **Jobs drawer.** Running and recent jobs with SSE progress (items done/total, current item, errors), Cancel (cooperative, between items), and a link to the log.
- **Add novel.** Paste a URL; the detected backend and metadata preview appear; confirm.
- States: empty library, a job already running (buttons disabled with a reason), fetch errors listed per item, server restart (jobs shown `interrupted` with Re-run).
- Accessibility: semantic tables and buttons, keyboard-reachable actions, and color plus text labels in the grid.
- Visual: reuses the site CSS tokens from `assets/style.css`.

## 11. Validation gates (resolve in the slice that first depends on them)

| Gate | Check | Accept when |
|---|---|---|
| G1 lncrawl headless | Pinned lncrawl CLI, non-interactive, JSON output for a URL plus a chapter range on 2 known hosts | The ZIP is produced and parsed into SourceItems/RawChapters. Also decide in- or out-of-workspace. |
| G2 LNReader harness | Bundle + run `novelbuddy.ts` under Node 22 from the harness | JSON novel + chapter output for 1 chapter |
| G3 novel-downloader | Covers the user's ZH raw hosts (e.g. biquge mirrors) | index + 1 chapter fetched |
| G4 htmx 2.x + SSE | `htmx-ext-sse` works with sse-starlette | Live progress updates in the browser |
| G5 OpenCC wheel | Windows cp312 wheel installs under uv | `t2s` converts a sample |
| G6 M4B chapters | ffmpeg FFMETADATA M4B opens with chapters in Audiobookshelf or another player | Chapter list is visible and seeking works |
| G7 Pages switch | Source switched to gh-pages | Live URL serves the new index |
| G8 Fetch ladder | curl_cffi vs FlareSolverr on skydemonorder | Index fetched |

## 12. Tests

Seams (agreed): `NovelStore` public methods; `Source`/`Importer` contracts; `normalize`; `sync` with an injected Fetcher; builders with a fake TtsEngine; `Service`; CLI via CliRunner; web via TestClient. Live-site tests are marked `@pytest.mark.live` and never run by default. Fixtures come from a scrub script that keeps tags, attributes, numbering and filenames and replaces prose with deterministic placeholder words of equal length.

### Case matrix (named pytest params)

| id | Setup | Action | Expected | Layer |
|---|---|---|---|---|
| key-order-parts | keys 524, (524,1), (524,2), 525 | sort | 524 < 524pt1 < 524pt2 < 525 | core |
| select-priority | versions from A(en) and B(en) for ch 5; priority [B,A] | selection | B | core |
| select-pin-range | priority [A,B], pin 10–20 → B | selection 9, 10, 20, 21 | A, B, B, A | core |
| select-never-raw | only raw-zh for ch 7 | selection | ch 7 absent; check lists it as raw-only | core |
| select-fallback | priority [A,B], A lacks ch 3 | selection | B for ch 3 | core |
| put-idempotent | same content twice | put_version ×2 | Inserted then Unchanged; 1 row | core |
| put-changed | refresh with different text | put_version | 2 versions; current = the new one | core |
| put-revert | source text A, then B, then A again | put_version ×3 | 2 rows; current = A (the 3rd call returns Unchanged but updates last_seen_at) | core |
| align-offset | global offset +1, item position 7 printed "Chapter 5" | record_index | key 6 (not 7 or 8: proves printed number + offset, not position) | core |
| align-override-precedence | offset +1, range override 1897–3166 → −2, item override 3165 → 3163 | record_index | 1000→1001, 1899→1897, 3165→3163 | core |
| align-unnumbered | item "Prologue" / "Side story: X" | record_index | `unmapped`, listed by check; mapped after an item override | core |
| select-mixed-parts | A has (524,1),(524,2); B has 524; **priority [B,A]** | selection | only B's 524 (part 0); no A parts; check warns about mixed parts | core |
| select-mixed-parts-a-first | same, priority [A,B] | selection | only A's (524,1),(524,2) | core |
| pin-part0-vs-parts | priority [A,B]; pin 524 → B; B has only 524 part 0 | selection | B's 524; A's parts not emitted | core |
| pin-missing-source | pin 10–20 → B, B lacks 15 | selection | 15 from priority; check warns | core |
| select-switch-source-single-row | site built from A for key 5; priority changes to [B,A] | build site | one output row for key 5 (source B); A's artifact replaced | publish |
| site-prune-moved-key | site built at key 1899; override moves the item to 1897 | build site | page/row for 1899 deleted; 1897 built; deploy dir has no 1899 | publish |
| index-domain-move | items stored for novelbin.me; index now on novelbin.com with the same paths | record_index | same item_refs (paths); no vanished items; no duplicates | core |
| index-path-change | paths change layout; then rebase-urls | record_index, rebase | before: old items vanished and excluded from duplicates; after rebase: matched | core |
| pin-raw-rejected | pin → raw-zh source | set_pin | error; nothing stored | core |
| override-edit-remaps | versions + site output + legacy audio for item X at key 1899; override edited → 1897 | set_alignment, plan_build, check | the version appears at 1897; plan has build 1897 and prune 1899 for the site; the legacy audio row is in neither list and check reports it as moved | core |
| index-insert-middle | index 1–12 stored; new index inserts an item at position 10 | record_index | items 10–12 keep their versions and raw files (matched by URL); only positions change | core |
| fingerprint-stale | site built; template changes the fingerprint | plan_build(site) | every site key in to_build | core |
| renormalize | cleaner rule changes | renormalize | new Versions from stored raw HTML, no Fetcher call | sources |
| m4b-volume-stale | volume 1–100 built; ch 50's selection changes | build audio | ch 50 MP3 and volume 1–100 rebuilt; volume 101–200 untouched | audio |
| two-jobs | sync on novel A and build on novel B concurrently (real SQLite files) | Service | both complete; no `database is locked`; progress rows for both | app |
| job-lock-cross-process | server job running for N (lock row held) | CLI `nov sync N` in a subprocess | CLI exits with "job already running"; after heartbeat expiry the lock can be taken | app |
| renormalize-old-version | two versions with different raws | renormalize | both rebuilt from their own raw files | sources |
| align-dup | two items both printed 3165 | check | duplicate reported, both kept unmapped | core |
| align-unavailable | null filenames 1–229 | import | gaps reported, not errors | sources |
| index-shrink | 2nd index lacks item 50 | record_index | versions kept; item `vanished` | core |
| stale-on-pin | built site at hash h1; add pin → other version | plan_build(site) | that range in to_build | core |
| legacy-position | BTS fixture: `chapter_501/chapter_501.mp3`; frozen snapshot position 501 = URL of printed 492 | register legacy | output row (source, that URL), key 492 | audio |
| legacy-title | WLHC fixture `chapter_992` title-number | register | key 992 | audio |
| legacy-partial | `chapter_037/` without combined mp3 | register | not registered; build generates it | audio |
| legacy-not-stale | legacy row from import:wns; (a) the version changes within the source; (b) a higher-priority lncrawl source gains the key | plan_build(audio) | in both cases: not in to_build or to_prune; with `--force`: rebuilt | audio |
| legacy-title-unmapped | WLHC folder `chapter_1500`, no item derives to 1500 | register | listed as unregistered; no row | audio |
| sentence-cache | paragraph edited in one sentence | build audio | only that sentence re-synthesized (fake TTS call log by text) | audio |
| m4b-volume | 3 fake chapter MP3s | build m4b | FFMETADATA has 3 chapters, correct start ms | audio |
| norm-host-{freewebnovel,novelbin,novelbuddy,skydemon} | scrubbed real page | normalize | ads/gtag removed; paragraph count equals fixture's known count | sources |
| norm-system-rule | Barbarian page with `[…]` status lines + rule | normalize | system blocks; without rule → paragraphs | sources |
| import-wns-numbers | main.json slice (golden core hash names, skydemon slugs) | import | keys from slugs | sources |
| import-ccg-novelhi | 72 unreferenced files | import | not imported; listed in the import report | sources |
| import-mtl-hash-names | `#0_ x.txt` with offset +1 | import | key 1 | sources |
| import-scribble | CRLF, mixed `##`, duplicate 439 | import | 398 keys, 439 flagged | sources |
| sync-resume | Fetcher fails at item 3 of 5 | sync, then sync | 1st: 2 ok, 3 failed, 4–5 ok, exit≠0; 2nd: only 3 fetched | sources |
| sync-new-only | store has 1–10; index 1–12 | sync | fetches 11–12 only | sources |
| epub-metadata | novel author "Gen, Er" | build epub | dc:creator set; filename has no " - " pattern that Calibre misreads | publish |
| site-labels | BTS parts | build site | page titles show real labels; library.json ranges are labels | publish |
| site-budget | out dir > budget | deploy | aborts before push | app |
| job-one-per-novel | job running for N | start another for N | 409 / CLI error; different novel OK | app |
| job-interrupted | job row running at startup | start server | marked interrupted; re-run resumes | app |
| cli-sync-exit | sync with failures | CliRunner | exit 1, summary lists failed items | app |
| secrets-scan-{google,openrouter} | legacy copy containing an `AIza…` / `sk-or-…` shaped string | copy script | aborts, names file | app |
| import-boundary *(optional)* | core imports bs4 | import-linter | contract fails | CI |

**Acceptance walkthroughs** (agent-executed, on the real machine, opt-in):
1. Import the web-novel-scraper store for Barbarian, build the site, and diff it against the current site (chapter count 815, first and last chapter text).
2. Register legacy audio for BTS. Spot-check 5 mappings by listening to the first sentence against the chapter title.
3. Run `nov sync` on Barbarian with no new chapters (no fetches beyond the index), then on an ongoing novel.
4. In `nov serve`, compare one Longevity chapter (scribblehub vs translation in the 834–836 overlap), pin it, rebuild, and check that the site page changed.
5. Run the cutover steps in §9.5 with a live URL check.

CI: GitHub Actions on push runs `uv sync`, `pytest -m "not live"` on a **Windows runner** (matches the user's machine), with no services and ffmpeg installed in a setup step. *Optional:* import-linter; an Ubuntu runner; a separate Node harness job.

## 13. Implementation slices (vertical, test-first per slice)

0. **Repo base** (after the §9.5 step-0 preconditions). Workspace skeleton, GPL LICENSE, `.gitignore`, env-only secrets, scrub script + fixtures, CI. Copy legacy with the secrets scan.
1. **Core.** ChapterKey, NovelStore, selection, alignment, check (core cases).
2. **WNS importer + normalizers** for 4 hosts, then `nov import wns`, `nov check`.
3. **Site builder.** Jinja templates reuse the CSS. Then walkthrough 1, then the **cutover** (§9.5 steps 1–3, G7). *The cutover is deferred until after slice 8 (user decision, 2026-10-19).*
4. **Audio.** Sentence cache, fake TTS, legacy registration (G6 for M4B), MP3 tags, M4B volumes.
5. **EPUB builder.**
6. **Other importers.** MtlTings, scribblehub, Calibre HTML, then the MtlTings archive step.
7. **Sync + lncrawl backend** (G1, G8). Then custom importers ported as backends, the decode-guide engine, novel-downloader (G3, G5), and the LNReader harness (G2).
8. **Service + jobs + web UI** (G4). The CLI has grown slice by slice; here it is moved onto the Service.

Definition of done: all non-live tests are green on CI; walkthroughs 1–5 are executed and recorded; the live site is served from gh-pages; no novel text in main; no secrets in the repo (scan clean).

## 14. Deferred and open

- Translation/glossary project. The IR slot is `my-translation` with provenance.
- Scheduled sync, text editing in the UI, private hosting, git history rewrite, `book.mp3`.
- Open technical contracts: lncrawl JSON ZIP field mapping (resolved in G1); LNReader harness I/O schema (G2); novel-downloader API surface (G3).
- Optional, not in v1 unless trivial: trafilatura fallback, FlareSolverr/Byparr sidecar (only if G8 shows curl_cffi is insufficient), `nov audio retag`, import-linter, Ubuntu CI.

## 15. Review log

- **Baseline review (r0):** legacy audio position keys, split parts, Pages-from-main cutover order, import data facts, CCG drift, system/note blocks, raw-only novels. All resolved in r1.
- **Final review (r1 → r2), P1:**
  1. Keys are derived from `(source_id, item_ref)`, not stored.
  2. Items are identified by URL.
  3. Part-0 suppression.
  4. "Current" is defined by `last_seen_at`.
  5. A single key-derivation rule, and importers are Sources.
  6. MtlTings is detached from gti before anything else.
  7. Dirty tree is snapshotted first.
  All are resolved above.
- **Final review (r1 → r2), P2 adopted:** builder fingerprint plus `renormalize`; M4B `volume` rows; store setters; SQLite concurrency contract; zstandard, ffmpeg, ASCII slugs; pin edge cases; stronger alignment and secret tests; htmx 2.x; lncrawl pin.
- **Final review, scope trims accepted:** NovelHi not imported; CI on Windows only; import-linter, trafilatura and the sidecar are optional.
- **Follow-up review of r2 (r2 → r3), P1:**
  1. Selection is decided per number, and pins beat part-0 suppression.
  2. Output rows are keyed by `(kind, built_key)`, with per-key staleness, pruning, and legacy exemption across source switches.
  3. item_ref is defined per backend and canonicalized, with `rebase-urls` and vanished items excluded.
- **Follow-up review of r2 (r2 → r3), P2:**
  - raw file per distinct raw
  - title-number legacy resolved to an item
  - cross-process job lock
  - importers emit indexes
  - ties broken by version id with an injected Clock
  - strengthened tests
- **r3 edits:** reviewed only by self-check. The changes are confined to the remedies proposed by the reviewer.
- **Slice 0–1 implementation notes (2026-10-19):**
  - `kind` lives on the Source, not on each Version. A source's texts all share one kind, so a pin's raw-zh check reads it from one place.
  - Range overrides apply to **printed numbers**, and the range's offset replaces the source offset. The precedence test uses an item override whose target differs from the range result (3165 → 3200), since 3165 → 3163 cannot tell the two apart.
  - Items of one source that derive to the same key are all left without a key and reported as duplicates.
  - In `plan_build`, an item that already has a legacy row at another key is not rebuilt. `check` reports it as `legacy_moved`.
  - When pins overlap, the most recent pin wins.
  - NovelStore owns a novel directory (`novel.sqlite` plus `raw/`).
  - Repo tools live in `tools/`. The per-host fixtures move to slice 2, where the junk-text keep patterns are defined.
- **Slice 2 implementation notes (2026-10-19):**
  - A printed part only splits a chapter when another item of the same source has the same printed number. In Barbarian and Mount Hua, "(2)" numbers a story arc and every chapter has its own number, so a lone suffix becomes part 0. `(part N)` is parsed as a part too (BTS).
  - The CCG range override is **not** seeded. In the WNS titles the inner number ("Chapter 3161: 3159: …") is 2 lower from printed 2962 onwards, and agrees at 2740. Where the drift starts between those two can't be read from the titles, and nothing supports 1897. The user sets the override once the start is known.
  - Watermark rules apply to every host, since aggregators copy each other's text:
    - A short line naming a site is dropped, even when disguised by look-alike letters, symbols between letters, a missing letter, or no domain at all.
    - A watermark sentence glued onto a real paragraph is cut back to where the previous sentence ended.
    - Translator credits, chapter navigation and Discord links are dropped.
  - `CleanRules.drop` and `strip` take functions as well as regexes.
  - `normalize(raw, rules, title)` also drops the copy of the title at the top of the body. This covers "Chapter N …" lines, an exact copy of the title, and the title without its "Chapter N" prefix.
  - Importers return a `NovelIndex` that carries report notes and snapshot files. `import_novel(novel_dir, importer)` is the shared import step.
  - The first snapshot of `main.json` keeps its plain name. Later, different copies are kept beside it under their hash.
  - Titles are repaired with ftfy using `uncurl_quotes=False`, so curly quotes stay as they are.
  - Found in the data: freewebnovel lists BTS 651–655 twice, and some BTS side stories carry a title number, so `check` reports those as duplicates. Longevity has a 606 duplicate and 4 unnumbered notices. Golden Core has 2 unnumbered extras.
  - freewebnovel numbers its chapter URLs by position (BTS `/chapter-1446` is "Chapter 1353"). `SourceItem.ref_numbered=False` stops the slug fallback there, so untitled posts like "2025.10.29" are listed as unmapped instead of becoming chapter 1370.
- **Slice 3 implementation notes (2026-10-19):**
  - Reading pages hold 50 chapter **numbers** each, named by their range (`novels/<slug>/1-50.html`; a number-0 override joins page 1). Anchors are `#c524` and `#c524-1`. Headings come from the key label plus the source title with everything through "Chapter N" removed, so a novel name in front of the title is dropped too.
  - The library page is rendered statically. There is no `data/library.json` and no `chapter.js`. The scroll-to-top button moved into `assets/site.js`.
  - `build_site(novels_by_slug, out_dir, force)` owns the whole site directory. A page is rebuilt when a chapter on it is in `to_build` or `to_prune`, when its file is missing, or when a neighbouring page appeared or disappeared (its prev/next links changed). Pages left empty and folders of novels that no longer exist are deleted. The fingerprint hashes the templates, the static files, the page size and the renderer source.
  - `nov deploy site` commits `_site` in a throwaway git dir whose work tree is `_site` (so the site is never copied), then force-pushes `gh-pages`. Before pushing it writes `deploy.txt` with a deploy id. The live check polls `deploy.txt` with a cache-busting query until it matches. Tested against a local bare repo only; nothing was pushed to GitHub.
  - `AlignmentRules.skip`: reposts and other non-chapters are left out of derivation (no key, not unmapped, not a duplicate). `nov align item|skip` edit the rules, and refs are checked against `NovelStore.item_refs`. In Git Bash, set `MSYS_NO_PATHCONV=1`, or refs starting with `/` get rewritten into Windows paths.
  - normalize: a `<br>` followed by a lowercase word joins the lines (skydemonorder hard-wraps sentences). Reader-site UI lines ("A new text-to-speech function…", "Please visit to enjoy reading") are dropped.
  - Walkthrough 1 (all 7 WNS novels, against the live site):
    - Same chapter set for Barbarian (815), Mount Hua (230–1343) and WLHC (1339). BTS (1438) and CCG (3165) are supersets of the old site.
    - Text differences are junk removed (watermarks, credits, `❄️❄️❄️` lines now shown as `<hr>`) or old Calibre losses repaired.
    - Data fixes applied with `nov align`: BTS date-titled posts 1370/1398/1400/1406 → 1277/1305/1307/1313; BTS reposts 734–739 and the second CCG 3165 copy skipped (the first copy of each pair kept).
    - Longevity has only WNS 834–1002, while the live site shows MtlTings 990–1781. The user plans a better translation later, so this is left as is.
- **Slice 4 implementation notes (2026-10-19):**
  - `chapter_heading` moved from novel-publish into novel-core (`keys.py`), since audio needs it too and publish/audio are independent layers. The site fingerprint changes once because `site.py` changed, so the next `nov build site` rewrites every page.
  - Store schema 2 adds the `volume` table. `NovelStore.open` migrates version-1 stores in place. `NovelStore.chapters(source)` lists a source's mapped items with their current versions, selected or not (needed for legacy registration).
  - Audio lives in `<data>/_audio/<slug>/`: `chapter_0524.mp3` (`chapter_0524-1.mp3` for parts), `_sentences/<voice>/` (the sentence cache, keyed by sha256 of voice + text) and `volumes/0001-0100.m4b`. Built rows store paths relative to that folder; legacy rows store the old MP3's absolute path (the files stay in `tts_out/`).
  - Fingerprint = voice + the source of `script.py` (how blocks become sentences). Changing `--voice` rebuilds every non-legacy chapter.
  - Sentences: pySBD, cut at clause breaks above 500 chars, fragments under 15 chars merged into the next sentence of their paragraph. A missing file is rebuilt even when the row is current.
  - Volumes: one per 100 chapter numbers, holding every selected key with audio (built or legacy). The membership hash covers key, version hash, fingerprint and artifact. AAC 64k mono, FFMETADATA chapters, cover as attached picture. G6 machine side verified with ffprobe (chapter list and starts); the player check is the user's.
  - **Legacy positions do not always equal snapshot positions.** BTS folders 1–733 are snapshot positions, 734–735 are repost audio (skipped items), and from 736 on the old Calibre export is 4 positions behind main.json. Registration therefore takes `--shift 736-1442:+4`, and every mapping is verified. tts_reader kept `chNNN_pPPP_sSSS.mp3` per sentence, and a paragraph's summed MP3 size follows its length, so each folder records its text's paragraph-length shape. A mapping is accepted when its version beats every other version within ±30 on a lag-tolerant correlation of log lengths or on a diff of half-octave length buckets (reposts with identical text are not rivals); otherwise the best match is reported. Sentence counts per paragraph were tried first and are too weak for dialogue-heavy novels. On a 150-folder sample per novel the rule accepted 600/600 true mappings and 1/593 mappings shifted by 7. CCG, Barbarian and WLHC map at shift 0.
  - edge-tts 7.2.8 now gets 403 from the endpoint; 7.3.1 (2026-10-13) works. The legacy `tts_reader.py` needs the same upgrade.
  - CI installs ffmpeg with choco. `nov cover` copies a cover into the novel folder (`tag_test/` covers moved for WLHC, BTS and CCG).
- **Slice 5 implementation notes (2026-10-19):**
  - `build_epub(store, out_dir, slug, size=100, cover, force)` writes one EPUB per 100 chapter numbers to `<data>/_epub/<slug>/<slug>_0001-0100.epub`, so the file name has no "Title - Author" pattern. Like the site, the folder is owned by the builder: a volume is rebuilt when a chapter in it is in `to_build` or `to_prune` or when its file is missing, and `.epub` files no longer called for are deleted. Output rows are per chapter (`kind=epub`), and their artifact is the volume file.
  - The fingerprint covers the builder, the shared renderer, the volume size, the novel's title, author, language and tags, and the cover's hash, so new metadata or a new cover rebuilds every volume.
  - Metadata: the title is `<novel> <first label>–<last label>`, plus `dc:creator`, `dc:language`, `dc:subject` per tag, and a series both as `calibre:series`/`series_index` and as EPUB 3 `belongs-to-collection`/`group-position`. The identifier is a uuid5 of slug plus range, so a rebuilt volume replaces the old one in a reader. Calibre `ebook-meta` reads all of it. epubcheck was not run (no Java).
  - Block HTML moved from `site.py` to `novel_publish/render.py`, which is shared by both builders. The site fingerprint now hashes `render.py` too. This lands in the same one-time full site rebuild that slice 4 already caused, since the site has not been rebuilt since then. Image blocks in the real data are only WordPress emoji and one ad GIF (CCG, Golden Core, BTS), so the EPUB shows an image's alt text and never a remote `<img>`.
  - `KeyRange.containing(number, size)` replaces the range arithmetic that site pages, M4B volumes and EPUB volumes each had a copy of.
  - Built for all 7 novels (91 volumes, 69 MB).
- **Slice 6 implementation notes (2026-10-19):**
  - `nov import mtl|scribble|calibre` plus `nov priority <novel> [ids]`. Each importer chooses its cleanup rules (`Importer.clean_rules`), and `NovelIndex.provenance` is added to every version (MtlTings translations: `{model: "unknown (MtlTings)", glossary: null}`). Later imports rank after earlier ones, so Calibre is imported last.
  - MtlTings: the kind comes from the folder (`data/raw` → raw-zh, `data/translated` → my-translation). **CCG raws need no offset**: `#N` is the printed number (#2962 is WNS "2962: 2960…"). `#N Part P_` is part P; `#_` files (afterword, leave notice) stay unmapped. Raw-zh text gets no watermark rules, because the fuzzy site-name match reads every CJK letter as a wildcard. Transcendental Mechanic has 7 chapters downloaded twice (one under a cut-off title); identical bodies are imported once. Its #4411 ("…0 Edition Update") is a misread number, left as raw only.
  - Scribblehub: the r0 baseline misread the file. Each `## Chapter N: Title` marker is glued to the end of the previous chapter's last line, and 439 is **not** duplicated. 809 is an extra in two halves, so it becomes 809 pt 1 / pt 2 (399 items, 439–836).
  - Calibre: items come from each page's TOC, the body is the anchored div or (flat layout) the siblings after the anchored `<h1>`. Numbers come from TOC titles, which equal the WNS titles. Overlapping pages (WLHC `index_until912` vs `index_1_50`, 902–914) keep the page with the longer copy; repeats within one page go to `check`. CCG's second 3165 copy is skipped, as in WNS.
  - Cleanup for every host now removes pubfuture/pubadx ad images and their wrappers, "(End of this chapter)", patreon lines and the "Spirit.Stone.translation" sign-off. Re-running `nov import wns` re-normalizes the stored pages, which is how the 7 WNS novels picked this up.
  - Data found: the MtlTings translation of Longevity 1303 repeats one passage about 94 times (2200 paragraphs; the old site has the same text). Several translations carry the wrong number in their title (`chapter_1555.html` is "Chapter 1554: …"); `check` lists them. The Longevity WNS item `chapter-6061-extra-story-…` is skipped (its slug made `check` report gaps up to 6061).
  - MtlTings archive: its 6 scripts are in `legacy/mtltings/`. `translate.py` and `summarize.py` held an OpenRouter key; the copies read `OPENROUTER_API_KEY` instead. The key is still in MtlTings itself and must be rotated. The folder stays on disk as the archive.
- **Slice 7 implementation notes, part 1 (2026-10-19): sync, lncrawl, skydemonorder (G1, G8):**
  - **The user changed two constraints mid-slice.** First, the app must be self-contained: every third-party library is a declared workspace dependency, used in-process, and a tool with no Python package gets a thin Python shim around its pinned binary. Second, any browser must be Firefox; Chromium is never launched.
  - **G1:** lncrawl is an ordinary workspace dependency (`lightnovel-crawler==4.14.0`, resolved with the rest of the lock; the earlier §6.1 "isolated tool env" is dropped). Its CLI can only select first/last/all/missing chapters and re-crawls the index on every call (12 minutes on freewebnovel), so the plan's "CLI + JSON ZIP" contract is replaced by its crawler classes, called in-process: `read_novel`/`format_novel` for the index, `download_chapter`/`format_chapter` per item. lncrawl's database, binder and server are not used. lncrawl refreshes its crawlers from its online index at startup, so the pin does not freeze the crawlers. Challenges are solved only in Firefox (`browser_driver=firefox`, saved in lncrawl's config). The ZIP field mapping in §14 is therefore moot.
  - **G8:** skydemonorder serves a Cloudflare challenge that curl_cffi alone cannot pass, in any impersonation. FlareSolverr passed it, but launches Chromium and was rejected. lncrawl-scraper's Firefox solver (WebDriver BiDi) earns the clearance, and its ladder (browser fingerprint, clearance reuse, pacing, retries) replaces the planned curl_cffi→FlareSolverr ladder. The clearance and the Firefox profile live in `<data>/_fetch`. Firefox did not earn the clearance on every try (2 of 4 during testing); a failed sync is simply re-run.
  - `custom:skydemonorder` reads the free list from the chapter-list Livewire component (POST of the page's snapshot with its CSRF token). lncrawl's own crawler for this host fails because its POST lacks the token. Free chapters now include 1–229 (missing from the WNS store).
  - The novelbuddy custom port is not needed: lncrawl's crawler reads both novelbuddy.me and .com. Its bodies start with a "Translate to" line, now a common junk rule.
  - `nov add <url>` attaches a web source (the backend is picked by host: custom if one exists, else lncrawl) and records its index. `nov sync <novel>|--all [--refresh range] [--source]` fetches. **Default scope deviation:** sync fetches the items that have no version *and whose number the book lacks*, not every item without a version. Otherwise a web source attached to an imported novel would refetch the whole book. `NovelStore.to_fetch` owns this rule. For a raw-zh source, "lacks" counts only raw texts. Unmapped items are fetched once; unavailable, vanished and skipped ones are not; `--refresh` refetches its range whatever is stored.
  - `store_chapters` is the one read→normalize→put loop, shared by imports and sync. `FetchError` is an `OSError`, so one bad chapter is marked failed, the run continues, and the command exits 1.
  - Key rule fixes found by the live syncs: "Chapters 486" counts as chapter 486, and a dated slug (`2025-11-18`) gives no number (it had made WLHC report gaps up to 2024). freewebnovel's positional URL numbers are a host fact in `hosts.numbered_urls`, used by both the WNS importer and lncrawl.
  - `nov align copy <novel> <from> <to>` gives a new web source the fixes made on the import from the same site (refs are the same URL paths). It was used for BTS (1 → 3).
  - Live results: Barbarian (novelbuddy) is current, with only the index fetched (walkthrough 3, first half). WLHC: 26 chapters fetched, now 1–1364 except 675. BTS (freewebnovel): 19 chapters, through 1354 (the finale). Mount Hua (skydemonorder): see below. novelbin.com/.me answer every request with an empty 503, so Golden Core, Longevity and CCG cannot sync until it returns or another site is added.
  - Still open after part 1: decode-guide engine, novel-downloader for ZH raws (G3, G5), LNReader harness (G2). See part 2.
- **Slice 7 implementation notes, part 2 (2026-10-19): novel-downloader, decode guides (G3, G5):**
  - **G5:** `opencc` 1.4.2 and `cn2an` install as Windows cp312 wheels under uv; `t2s` converts a sample. cn2an was already a novel-core dependency (titles like 第一千零六十章).
  - **G3:** novel-downloader (`~=3.1.1`, MIT) is a declared dependency, used in-process like lncrawl. Its API is async: each site has a fetcher (raw pages) and a parser (`BookInfoDict` / `ChapterDict`), and `resolve_book_url` maps a URL to a site key and book id. `NovelDownloaderSource` runs them on an `asyncio.Runner` it owns, so it is a blocking Source like the others. Chapter text is stored as `text` (the parser already cuts it out) after OpenCC `t2s`, a no-op on Simplified text. Refs are URL paths. Sites number URLs by position, so `ref_numbered=False` and numbers come from titles.
  - novel-downloader has ~80 site plugins but **not biquges123**, so `noveldl_sites.py` registers one through its own registry (`register_fetcher`/`register_parser`/`register_extractor`). Its chapter page is the layout the shared `Biquge1Parser` reads; only the book page (`div.list`) needed a parser. Live: index of 1825 items and chapters fetched (also a `-m live` case).
  - Backend pick by host is now: custom → novel-downloader (a plugin resolves the URL) → lncrawl if it has a crawler that it does not list as rejected → decode guide → lncrawl's generic crawler. A novel-downloader source is always `zh` / raw-zh, whatever `--lang` says.
  - **Longevity raws:** biquges123 is source 6 of my-longevity-simulation. Sync fetched 844 items: every English gap (1–438, 934–942) now has a raw. The site lists 34 chapters twice (e.g. positions 741/743 are both 第738章): 8 copies have identical text, 26 differ by one to three paragraphs (an early upload and its revision). They are reported as duplicates and left for the user to choose; 10 author notes (请假条 etc.) are unmapped.
  - **Decode guides:** web-novel-scraper (`~=2.2.1`) is a declared dependency for its packaged `decode_guide.json` (read with `importlib.resources`) and its custom processors (novelbin's TOC address, genesistudio's chapter list), which run in-process. The rules are interpreted by our own engine (`decode_guide.py`) with WNS's semantics: `selector` with `XOR` alternatives, or element/id/class/attributes; `extract` attr/text; `array`; `has_pagination` + `next_page`; `index.inverted`; `clean`. Unlike WNS, the index keeps each link's text as the item title. Pages are fetched with the fetch.py ladder (Firefox only on a challenge).
  - **Finding:** lncrawl covers most guide hosts. Of the ones it lacks, novelbin.com/.me are down (empty 503; lncrawl's index lists them as "Site is down"), and the shipped guide entries for novelingua (links now `p > strong > a`) and genesistudio (now a Next.js app) no longer match the sites. The engine is tested on fixtures built from the real guide entries, but no guide-only host works live today. Its value is user-written guide entries (the user has some in `get-novels/decode_guide.json`); where they live is open (see below).
  - `nov` now writes UTF-8 to stdout/stderr: on Windows a piped stdout used cp1252, and `nov check` crashed printing Chinese titles.
  - Still open in slice 7: where user-written decode guides live; LNReader harness (G2; needs Node, so a pinned Node binary behind a thin Python shim, to be confirmed with the user before building).
