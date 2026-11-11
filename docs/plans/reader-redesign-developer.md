# Reader redesign: developer plan

Status: approved 2026-11-11. Not built yet. Summary for the requester: [stakeholder plan](reader-redesign-stakeholder.md).
Source: the Firefox UI review of 2026-11-11 (reader items 2-6). Reader item 1 (68ch line length) shipped in `91c22fc`.
Builds on [reader-ui-developer.md](reader-ui-developer.md); where this plan says otherwise, this plan wins (see §1.2).

## 1. Decisions

### 1.1 Approved (user, 2026-11-11)

| # | Decision |
|---|---|
| U1 | **Library = Continue row + compact list.** "Continue reading" lists every novel with a saved place in this browser, most recent first. Each entry shows title, "Ch N", relative time, and × to forget the place. There is no cap. Below it, "All novels (N)" lists every novel as compact rows sorted by title (title, author, chapter count). A row expands without JS to the go-to box and page links. The list always holds every novel, including those in the row. A new visitor sees the list only. |
| U2 | **Novels with nothing to read are left off the site.** This covers raw-only novels and novels with no chapters. Each appears automatically once it has a published chapter. |
| U3 | **Title and author are editable** with `nov meta <novel> --title … --author …` and with a form on the nov serve novel page. Slugs and URLs never change. Placeholder authors (`<unknown>`, `Unknown`, blank) count as no author everywhere. The user fixes titles by hand. |
| U4 | **Sync may refill an empty author** from the source. This is today's rule, so a hand-cleared author can come back, and `<unknown>` is replaced once a source knows the author. |
| U5 | **End of a page:** a full-width "Next: Chs 51–87 →" button, with a smaller "← Chs 1–50" and "Library" under it. The novel's last page says "You're caught up: chapter N is the latest." |
| U5b | **Next/prev labels name the actual chapters and stay fresh.** A page is rebuilt whenever a neighbouring page's chapters change. Each sync that adds chapters to the last page therefore also rewrites the page before it. |
| U6 | **New text settings:** a sepia theme, Sans/Serif (system fonts), line spacing (compact, normal, loose) and line width (narrow, normal, wide; only offered on wide screens). All are saved per browser and applied before first paint. |
| U7 | **Chapters sheet:** a bottom sheet of about 90% height on phones, a taller centred panel on desktop, still opening scrolled to the current chapter. |
| U8 | **Out of scope:** cross-device sync, accounts, covers, search, and changes to page URLs or the 50-chapter grouping. |

### 1.2 Superseded

- **Platform plan decision 18 ("raw-only shown as 'raw only'"), and reader-ui S6's raw-only card:** superseded **for the site only** by U2. The app keeps its raw-only status and badge.
- **reader-ui §3.3 `reader:settings` = `{scale, theme}`:** extended to `{scale, theme, font, spacing, width}`. Older saved objects stay valid (§3.4). `reader:pos:<slug>` is unchanged.
- **Library cards with a Continue link inside them (reader-ui §3.2):** replaced by the Continue row and list rows.

### 1.3 Engineering defaults (decided in planning; not product choices)

- **Forget, then Undo:** × deletes the key immediately. Undo writes it back only if the key is still absent, since another tab may have saved a newer place. Leaving the page during the undo window keeps the place forgotten.
- **`nov meta` edits only the fields named.** An omitted option leaves the field as it is. `--author ""` clears the author. A blank title is refused.
- **Title sort key:** `(title.casefold(), slug)`. CJK titles sort after Latin ones, which is acceptable.
- **"Caught up" uses the last chapter's label as is**, for example "chapter 524 pt 2 is the latest".
- **A second × while an Undo is showing replaces that Undo.** The first place stays forgotten.
- **Relative time:**
  - "just now" under 1 minute
  - then minutes, hours, days, weeks, months
  - no time shown when `t` is missing or more than a year old
- **A Continue entry whose `file` is not among that novel's page links** (the page was removed) is not shown. Its key is left alone and is overwritten the next time the novel is read.
- **Empty library** (every novel left off or private): "No novels yet." The current admin instructions are not shown on the public site.

## 2. Verified baseline (2026-11-11)

- **Library build.** `site.py:47-65` `build_site` loops `sorted(novels.items())` (slug order) and calls `_build_novel` for each novel. `_build_novel` returns a card dict (`:138-147`), and `library.html` renders every card. Raw-only cards are computed at `:138` (no pages, and a raw-zh source). `_build_site` in `novel-app/service.py:376-390` leaves out only `public == False` novels.
- **Page rebuilds.** `_build_novel` (`site.py:97-136`) rewrites a page only when its chapters are stale, the file is new, or a neighbouring page was added or removed. The `fingerprint()` (`:68-77`) covers code, templates and static files, **not novel metadata**. The app's SITE staleness uses the same global fingerprint (`novel-app/pages.py:260`). EPUB fingerprints already include title and author (`novel_publish/epub.py:94`).
- **Cleanup.** The same step deletes old output records, files, and `toc.json` (`site.py:128-136`), so it must run even when a novel ends up with no pages.
- **Metadata.**
  - `NovelMeta(title, author, language, status, cover_path, tags)` lives in novel-core `model.py:24-31`. It is read by `_load_meta` (`store.py:803-805`) and written whole by `set_meta` (`:268-270`).
  - Authors arrive from novel-sources `epub.py:161` (where Calibre's `<unknown>` comes from), `lncrawl.py:90`, `lnreader.py:185`, `wns.py:73`, `noveldl.py:94`, and `open_novel`.
  - `adopt_site_metadata` (`novel-sources/sync.py:99-109`) fills only an empty author.
  - No command edits title or author today.
- **Saved data in the browser.**
  - `reader:pos:<slug>` = `{file, anchor, para, label, t}` (`site.js:10,159`).
  - The library's `fillContinue` (`:200-214`) validates `file`, `anchor` and `para`, never reads `t`, and runs on `pageshow` (`:330`).
  - `reader:settings` = `{scale, theme}` is owned by the head script (`base.html:7-28`). That script validates each field with a fallback, and `change()` saves `current()` (`site.js:313-316`).
- **Chapters sheet.**
  - `.sheet` (`style.css:415-426`) styles both dialogs: `min(32rem, 100vw-2rem)` wide, at most `100dvh-2rem` high.
  - `.sheet-toc ol` is `max-height:40vh` and is the scrolling element (`:609-615`).
  - `initDialogs` scrolls `[aria-current]` into view with `block:'nearest'` (`site.js:218-227`).
- **Tests.**
  - Static assertions are in `test_site.py`.
  - Browser tests are in `test_site_browser.py`. They run in headless Firefox (`tools/firefox_page.py`) at phone size only, against one 3-chapter novel. `firefox(size=…)` already accepts a viewport.
  - Byte-identical forced rebuild is pinned at `test_site.py:233-240`.
  - `test_site.py:147-152` pins that page 1 is *not* rewritten when page 51 grows; U5b reverses this on purpose.
- **Audio.**
  - Audio volumes embed `meta.title` (`novel_audio/volumes.py:71`).
  - `nov audio retag` retags only chapter MP3s (`novel_audio/build.py:139-158`).
  - The retag hint checks for `*.mp3` files on disk (`service.py:299`).
- **Release cost.** Any asset or template change changes the fingerprint, so every page is rebuilt and the whole site is redeployed (last deploy 128 MiB).

## 3. Design

### 3.1 Metadata (owner: novel-core)

- **Placeholder rule.** `model.py` gets `clean_author(value: str | None) -> str | None`: strip, then return None for blank or for a placeholder (`<unknown>` and `unknown`, compared casefolded; the set is a module constant). It is applied in `_load_meta` and `_meta_row`, so every reader (site, EPUB, audio tags, app) and every writer (all importers, `create`, `set_meta`, sync) sees the cleaned value. Existing rows are fixed on read, with no migration. The next sync's `meta.author or site.author` then refills the author when a source knows it (U4).
- **Partial update.** `NovelStore.update_meta(*, title: str | None = None, author: str | None | Unset = UNSET) -> NovelMeta` updates only the named columns in one transaction and returns the new meta.
  - A blank title raises `ValueError`.
  - It does not call `set_meta`, so a sync that read the meta earlier can't revert a title edit. Sync writes only author, status and tags; that read-modify-write keeps its existing small window for the author field, which is accepted.
- **One-time effects of cleaning on read.**
  - Each novel stored with `<unknown>` shows "EPUB stale" and rebuilds its volumes once, because the EPUB fingerprint includes the author.
  - Its MP3s keep the old artist tag until `nov audio retag`.
  - Audio *volumes* keep an old title after a title edit, because retag doesn't touch them. Rebuild the audio volumes if that matters. That rebuild is not automated in this plan.
- **Rejected: cleaning at the site build and the EPUB import only.** EPUBs and MP3s would keep `<unknown>`, and sync would never refill the author (review finding R3).

### 3.2 `nov meta` and the app form (owner: novel-app `Service`)

- `Service.set_meta(slug, title=None, author=UNSET) -> MetaChange` wraps `update_meta`. It maps `ValueError` to `UserError` and returns what changed, plus `audio_built: bool`.
- **CLI.** `nov meta <novel> [--title T] [--author A]`. With no options it prints the current title and author. After a change it prints "site and EPUB rebuild at the next build". If MP3s exist, it adds the existing `nov audio retag` hint (the same text as `service.py:299-300`).
- **Web.**
  - The novel page header gets a `<details>` "Edit title and author" holding a POST form (`/novels/<slug>/meta`, fields `title` and `author`, `back`).
  - The fields are declared `title: str = Form("")` and `author: str = Form("")`. FastAPI treats an empty form string as missing, so a required `Form()` would send an empty author to the 400 handler.
  - An empty author clears the author. A blank title is refused by the service with "A title can't be blank."
  - It follows the existing no-JS POST → 303 pattern, with an `hx-post` into `#notice`.
  - The notice carries the same rebuild and retag text as the CLI.
  - The help text lives in `_help.html`.
- No job lock is needed: the change is one short transaction.

### 3.3 Site build (owner: `site.py`)

- **Per-novel fingerprint.** `novel_fingerprint(meta) = sha256(fingerprint() + title + "\0" + language)`. `_build_novel` uses it for `plan_build` and `record_output`. `assets_v` stays on the global `fingerprint()[:12]`. The function is public, and `novel-app/pages.py:260` calls it, so the app shows "site N stale" after a title edit. Author is not on reading pages; it appears only on `index.html`, which is rewritten on every build.
- **Leaving novels off.** `_build_novel` always runs, so cleanup always happens. When a novel has no pages, its card is dropped from the library and its empty `novels/<slug>/` folder is removed. `NovelBuild.raw_only` becomes `listed: bool`. `_build_site` logs "<slug>: not on the site: no readable chapters".
- **Order.** Cards are sorted by `(title.casefold(), slug)`.
- **Last chapter.** The last page's template context gets `latest = pages[-1].chapters[-1].key.label`. Pages that stop being last are already rebuilt by the neighbour rule (`site.py:106-110`).
- **Fresh neighbour labels (U5b).** The rebuild set also includes page `i` when `pages[i-1].start` or `pages[i+1].start` is in `stale_starts`. `stale_starts` holds page start numbers, not indices. A page whose chapters changed therefore rewrites its neighbours, whose next/prev labels name its range. `test_site.py:147-152` and reader-ui S3b are rewritten to expect this.

### 3.4 Settings (owner: head script in `base.html`)

- **Shape.** `{scale, theme, font, spacing, width}`.

  | Field | Values | Default |
  |---|---|---|
  | `scale` | 5 steps | index 1 |
  | `theme` | system, light, dark, sepia | dark |
  | `font` | sans, serif | sans |
  | `spacing` | compact, normal, loose | normal |
  | `width` | narrow, normal, wide | normal |

  Unknown or missing values fall back per field, so old `{scale, theme}` objects load with defaults for the new fields.
- **`apply(s)`** returns the full validated object. It sets `data-theme` (sepia is literal; system still resolves to light or dark), `data-font`, `--r-scale`, `--r-leading` (1.6, 1.8, 2.0) and `--r-measure` (60ch, 68ch, 80ch). `current()` returns all five fields, so changing one setting never drops another.
- **CSS.**
  - `main[data-slug]` and `main[data-slug] ~ .page-end` use `max-width: var(--r-measure, 68ch)` and `line-height: var(--r-leading, 1.8)`.
  - `:root[data-font="serif"] main[data-slug]` uses a system serif stack (`Georgia, "Iowan Old Style", "Times New Roman", serif`).
  - Leading and font stay off `body`, so the library is unaffected.
  - `:root[data-theme="sepia"]` sets `color-scheme: light` and all 21 `--r-` tokens.
- **Dialog.** Four radio fieldsets (Theme, Font, Spacing, Width) plus the Size row. The Width fieldset is shown only at `min-width: 769px`.
- **`site.js` `initSettings`** generalises to every `fieldset input[type=radio]` keyed by `name`. `show()` must not throw when a radio is missing (guard `querySelector`).

### 3.5 Library (`library.html`, `site.js`, `style.css`)

```html
<section class="continue-row" hidden aria-labelledby="continue-h">
  <h2 id="continue-h">Continue reading</h2>
  <ol class="continue-list"></ol>
</section>
<p class="continue-undo" role="status"></p>   <!-- outside the row, so Undo survives the row emptying -->
<!-- empty library: <p>No novels yet.</p> instead of the list section -->

<section aria-labelledby="all-h">
  <h2 id="all-h" tabindex="-1">All novels (N)</h2>
  <ul class="novel-list">
    <li class="novel-row" data-slug="…" data-toc="…" data-title="…">
      <details>
        <summary><span class="row-title">…</span> <span class="row-author">…</span> <span class="row-count">N chapters</span></summary>
        <form class="goto" hidden>…</form>            <!-- unchanged go-to -->
        <nav class="book-parts">…page links…</nav>
      </details>
    </li>
  </ul>
</section>
```

- **Rendering the row.**
  - `renderContinue()` reads `reader:pos:<slug>` for each `li.novel-row[data-slug]` only, so slugs not on the site are ignored. It skips entries that fail today's validation and sorts by `t` descending, with a missing `t` treated as 0.
  - It skips an entry whose `file` isn't among the row's page links (§1.3).
  - It builds entries with DOM APIs and `textContent` only: a link `novels/<slug>/<file>?p=<para>#<anchor>` containing the title and "Ch <label> · <relative time>", plus a sibling `<button aria-label="Forget your place in <title>">×</button>`.
  - The row is unhidden when it has at least one entry.
  - Relative time uses `Intl.RelativeTimeFormat('en', {numeric: 'auto'})`, following the §1.3 rules.
  - It runs on `DOMContentLoaded` (the script is `defer`) and again on `pageshow` when `persisted`.
- **Forget and Undo.**
  - × removes the key and re-renders. The status line then reads "Forgot your place in <title>. [Undo]" for 6 s, and focus moves to Undo.
  - Undo writes the saved JSON back only if the key is still absent, re-renders, and moves focus to the restored entry.
  - When the window ends, the line clears. If focus was on Undo, it moves to the first Continue link, or to the "All novels" heading if the row is now empty.
  - `pagehide` clears the line.
- **Without JS:** the row stays hidden, and `<details>` works.
- **When storage throws:** the row stays hidden and nothing throws.
- **CSS.** Compact rows and a single column. Continue entries are full-width tap targets of at least 2.75rem. Unused `.book-card`, `.book-link`, `.continue` and `.all-chapters` rules are deleted.

### 3.6 End of a page (`page.html`)

- The end-of-page `page_links()` is replaced by `nav.page-end`:
  - if there is a next page: `<a class="next-page" href="…" rel="next">Next: Chs X →</a>` at full width
  - otherwise: `<p class="caught-up">You're caught up: chapter {{ latest }} is the latest.</p>`
  - then a small line: `← Chs prev` (when there is one) · `Library`
- The sheet keeps `page_links()` as it is. The bar's `data-prev-page`/`data-next-page` and `#last` are unchanged.

### 3.7 Chapters sheet (CSS only)

- `#chapters[open] { display: flex; flex-direction: column; }`. The rule applies only when open, so the browser still hides the closed dialog.
- `.sheet-toc { flex: 1; min-height: 0; overflow: hidden; }`. `.sheet-toc ol` drops `max-height: 40vh` for `height: 100%; overflow-y: auto`. The list stays the only scroller, so `scrollIntoView({block: 'nearest'})` does not push the go-to box away.
- **Up to 768px:** `#chapters` is a bottom sheet: `margin: auto 0 0`, `width: 100%`, `max-width: none`, `height: 90dvh`, top corners rounded.
- **Wider screens:** `#chapters` is `height: min(85dvh, 52rem)` and `width: min(36rem, 100vw - 2rem)`.
- The Text dialog keeps today's size.
- No new animation, so reduced motion needs nothing.

## 4. Tests

### 4.1 Seams and fixtures

- **Python.**
  - `NovelStore` on a tmp DB: novel-core tests.
  - `build_site` on stores made with the `test_site.py` helpers.
  - `Service` and `TestClient(create_app(service))` for `nov meta` and the form.
  - CliRunner for the CLI.
- **Browser** (`test_site_browser.py`, marker `browser`, Firefox only).
  - The module fixture grows to three novels:
    - `n`: "Test Novel", chapters 1-3 and 51-53, as today
    - `z-first`: titled "Alpha Tale", so title order differs from slug order; one page of 50 chapters × 3 paragraphs, ending at chapter 50 pt 2
    - `raw`: a raw-zh source only
  - A new `desktop` fixture uses `firefox(size=(1280, 900))`.
  - Saved places are seeded with `page.js("localStorage.setItem(…)")`.
- **Intentional rewrites:**
  - `test_site.py:212-219` (raw-only badge) becomes L1.
  - `test_site.py:354-371` (cards) becomes L5.
  - `test_site.py:147-152` and reader-ui S3b are rewritten for U5b, so neighbours are rebuilt.
  - The `continue_link` helper (`test_site_browser.py:63`) reads `.continue-list a` and returns `{ch: "Ch N", href}`. The browser tests at `test_site_browser.py:153, 258-259, 282, 292, 304, 317` switch from the "Continue · Ch N" text to that `ch` value, keeping what each one asserts.
  - Every other existing assertion stays.

### 4.2 Case matrix

| ID | Layer | Setup | Action | Expected |
|---|---|---|---|---|
| M1 placeholder | core | create with author `<unknown>`; another with `  Unknown `; another `""` | `meta` | author None for all three |
| M1b stored | core | create, then write `author='<unknown>'` with raw `sqlite3` (as `test_store.py:864-866`); reopen | `meta` | author None (cleaning on read, not only on write) |
| M2 real | core | author "Er Gen" | `meta` | "Er Gen" |
| M3 refill | sources | raw-written `<unknown>` (as M1b), site meta author "Er Gen" | `adopt_site_metadata` | author "Er Gen" |
| M4 partial | core | title A, author X | `update_meta(title="B")` | title B, author X; tags/status unchanged |
| M4b clear | core | author X | `update_meta(author=None)` | author None |
| M4c blank | core | — | `update_meta(title="  ")` | ValueError; row unchanged |
| M5 cli | cli | test novel | `nov meta n --title "Beware of Chicken"`; `nov meta n` | exit 0, "site and EPUB rebuild…"; second prints title and author |
| M5b cli-audio | cli | novel with an `.mp3` file in its audio dir | `nov meta n --author Y` | output contains the `nov audio retag` hint |
| M6 form | web | test novel with an `.mp3` | POST `/novels/n/meta` title, author "" | 303 to `back`; the notice has the rebuild and retag text; GET shows the new title; author gone |
| M6b form-blank | web | — | POST title "" | 400 with "A title can't be blank." (the service's message, not the validation handler's); title unchanged |
| F1 title-rebuild | site | 2 novels built | `update_meta(title=…)` on one; build; build again | first build: that novel's pages all rewritten with the new `<title>`, the other writes 0; second build writes 0 pages (record and plan use the same fingerprint) |
| F1b author-only | site | built | `update_meta(author=…)`; build | 0 reading pages written; `index.html` shows the new author |
| F2 app-stale | web | built site | change title | library row shows site stale until the next build |
| L1 left-off | site | `raw` (raw-zh only) and an empty novel | build | not in `index.html`; no `novels/raw/` folder; `NovelBuild.listed` False |
| L2 emptied | site | novel built with pages, then every chapter removed from the selection | build | old pages and records deleted; folder gone; not listed; app shows no stale site output |
| L3 sort | site | slugs `n` "Test Novel", `z-first` "Alpha Tale", `b` "beta" | build | list order Alpha Tale, beta, Test Novel |
| L4 bytes | site | L3 | forced rebuild | identical bytes (existing test, now with three novels) |
| L5 rows | site | L3 | build | each `li.novel-row` has `data-slug`, `data-toc`, `data-title`, a `<details>` with the go-to form `hidden` and every page link; `section.continue-row` is `hidden`; heading "All novels (3)" |
| L6 no-author | site | author None | build | no empty author span |
| L7 empty | site | only a raw-only novel | build | `index.html` says "No novels yet."; no `nov import` text |
| E1 next | site | 2 pages | build | page 1 has `a.next-page[rel=next]` "Next: Chs 51–53 →" and no `.caught-up` |
| E1b fresh | site | E1 built; add chapter 54 | build | page 1 rewritten and now says "Next: Chs 51–54 →" (replaces `test_site.py:147-152`) |
| E2 caught-up | site | `z-first` ends at 50 pt 2 | build | its only page says "chapter 50 pt 2 is the latest"; no `.next-page` |
| E3 became-last | site | 2 pages built; drop page 2's chapters | build | page 1 rewritten with `.caught-up` |
| B10 continue | browser | seed places: `n` (Test Novel) t=now-1 hour, `z-first` (Alpha Tale) t=now-2 days, `gone` (not on site); plus `n` saved with `file` "9001-9050.html" in a second run | open library | row visible; Test Novel **before** Alpha Tale (time order, not title or DOM order); "1 hour ago"/"2 days ago"; no entry for `gone`; second run: no Test Novel entry |
| B10b times | browser | `n` t=now-20 s; `z-first` with no `t`; `x` t=2 years ago | open | "just now"; no time shown for the other two |
| B11 forget-undo | browser | B10 | × on Test Novel; Undo | key removed and entry gone, Undo focused; after Undo key restored with original JSON and entry back |
| B11b forget-stays | browser | B10 | ×; wait 7 s | key still absent; status line empty; focus on the first Continue link |
| B11c leave | browser | B10 | ×; navigate to a page; back | key absent; no Undo shown |
| B11d newer | browser | B10 | ×; another write to the key (simulated); Undo | the newer value is kept |
| B11e last-one | browser | only one saved place | × | row hidden; the Undo line is visible and focused; Undo restores the key and the row |
| B12 expand | browser | — | click a row's summary; go to chapter 2 | go-to visible inside the row; navigates (B4 behaviour unchanged) |
| B5' resume | browser | existing B5 | via `.continue-list a` | unchanged expectations |
| B8' storage-off | browser | throwing storage | open library | row hidden, `__errors` empty |
| T1 settings | browser | fresh | serif, loose, sepia; open the next page | `data-font=serif`, `--r-leading` 2, `data-theme=sepia` on both pages; saved object has all five fields |
| T2 old-object | browser | seed `{"scale":3,"theme":"light"}` | load; change size | font sans, spacing normal, width normal, theme light kept; saved object now five fields |
| T3 width | browser (desktop + phone) | — | open Aa | desktop: Width visible; narrow → `main` width ≤ 60ch in px. Phone: Width fieldset not displayed |
| T4 bad-values | browser | seed `{"font":"comic","width":9}` | load | defaults, no errors |
| H1 sheet-phone | browser | `z-first` page, scrolled to chapter 40 | open Chapters | dialog height ≥ 85% of the viewport, bottom edge at the viewport bottom; current chapter visible in the list; go-to box visible |
| H2 sheet-desktop | browser (desktop) | same | open | height ≥ 70% of the viewport, centred; current visible |
| H3 text-dialog | browser | — | open Aa | dialog height < 90% of the viewport (it doesn't take the tall size) |

### 4.3 Walkthroughs (agent-run, results shown to the user)

- **W1.** A full rebuild of the real library with `NOVELS_DATA_DIR` pointing at a **copy of the whole data folder** (novel DBs and `_site`). The novel DBs record what was built, so building from the real DBs into a scratch folder would mark the live `_site`'s old pages as current. Screenshots of the library at 390px and 1440px (no saved places, then with three), a page end, the last page of a finished novel, the chapters sheet, and the Aa panel in each theme.
- **W2.** `nov meta` dry run on a **copy** of one novel's DB to fix "Beware Of Chicken". The user runs the real edits.
- **Deploy** (`nov build site --force` + `nov deploy site`, a full push of about 130 MiB) happens only after the user confirms. `--force` guarantees no old page survives, whatever was built before.

## 5. Gates

- **G1 (slice 7):** Firefox applies `90dvh` and `display:flex` on an open modal `<dialog>` as specified, and `scrollIntoView` scrolls only the list. Accepted when H1 and H2 pass in 3 of 3 runs. Fallback: `max-height` on the list computed from the sheet height in CSS without `dvh`.

## 6. Code-design notes

- **The placeholder rule lives where metadata is loaded and saved.** One owner covers every importer and every output. Rejected: per-importer cleanup (five call sites, and existing rows stay dirty).
- **Per-novel fingerprint, not a metadata hash in each page record.** It reuses the existing staleness machinery, and the app reads the same function. Cost: a title edit rebuilds all of that novel's pages, which is correct, because each page shows the title.
- **The Continue row is client-rendered from list rows.** Titles come from `data-title`, so stored shapes don't change, and novels no longer on the site drop out naturally. Rejected: storing titles in `reader:pos` (the stored title goes stale after `nov meta`).
- **No JS framework or JS test runner** (reader-ui §6 stands). site.js grows by about 80 lines.

## 7. Slices (each: failing test → code → green → commit)

0. Fixtures: three novels, the `desktop` fixture, seeding helpers. No behaviour change.
1. novel-core: `clean_author`, `update_meta` (M1, M2, M4-M4c); sync refill (M3).
2. `nov meta`, Service, novel-page form and help text (M5, M5b, M6, M6b).
3. Per-novel fingerprint, and app staleness through it (F1, F2).
4. Site listing: always clean up, leave off empty novels, title sort, `listed`, empty text (L1-L4, L6, L7).
5. Library markup and Continue row with forget/undo (L5, B10-B12, B11e, B5', B8').
6. Page end, caught-up, fresh neighbour labels (E1-E3, E1b).
7. Settings: sepia, font, spacing, width (T1-T4); chapters sheet (H1-H3, G1).
8. W1 and W2 walkthroughs. Update reader-ui-developer.md §3.3 and platform decision 18 with "superseded by" notes. Deploy only on user confirmation.

## 8. Definition of done

- All non-browser tests and `lint-imports` pass in CI. All browser tests pass locally (Firefox).
- W1 screenshots have been reviewed by the user.
- Nothing has been deployed without the user's confirmation.

## 9. Review log

- **R1 (independent review of the baseline and approach, 2026-11-11).** Findings folded in:
  - a title edit didn't reach the pages (§3.3 per-novel fingerprint)
  - leaving novels off skipped cleanup (§3.3 always run)
  - placeholder authors also had to be cleaned in EPUB, audio and sync (§3.1)
  - whole-row `set_meta` raced with sync (§3.1 `update_meta`)
  - settings `current()` had to carry every field
  - the sepia radio guard
  - sheet CSS scoping and `[open]`
  - leading and font scoped to `main`
  - richer fixtures

  Business question resolved as U4.
- **R2 (fresh review of draft v1, 2026-11-11).** Folded in:
  - **High:** W1 on the real DBs would make the live deploy skip old pages, fixed with a data-folder copy and `--force`.
  - **Medium:**
    - FastAPI empty-form handling (`Form("")`)
    - Undo lost when the last entry is forgotten (status line moved outside the row, B11e)
    - the Next label going stale, resolved by the user as U5b
    - B10 not telling time order from title order (reseeded)
    - stored `<unknown>` rows never tested (M1b)
  - **Low:**
    - one-time EPUB and audio effects (§3.1)
    - relative-time edge cases
    - entries pointing at removed pages
    - empty library text
    - browser-test rewrites listed
    - F1 checks the second build; F1b
    - the web notice carries the retag hint
    - M5b uses a real `.mp3`
    - Width shown from 769px
    - line references

  Verdict after the fixes: ready with gate G1.
