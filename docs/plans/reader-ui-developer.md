# Reader site and app UI: developer plan

Status: approved by the user 2026-10-20 (r3). Reviewed independently twice (r1 full review, r2 focused review; findings folded in, §9). Implemented and deployed 2026-10-20 (slices 0-8, §10).
Related: [stakeholder plan](reader-ui-stakeholder.md) · [platform v1 developer plan](novel-platform-developer.md) (done).

## 1. Approved decisions (user)

1. Scope: reader site navigation and resume, reader settings, app layout and phone, app compare diff.
2. The site keeps 50-number pages and their URLs (`novels/<slug>/<start>-<start+49>.html`).
3. Mobile reading comes first. The page starts with chapter text. A slim top bar slides in on scroll up and hides on scroll down. The bar shows `‹ Ch 803: First-Class (5) ›` (prev/next chapter, crossing pages) and [Chapters] [Aa] [Library].
4. Chapters sheet: this page's chapters with the current one marked, "Go to chapter #" for any chapter of the novel, and prev/next page links.
5. Aa: text size (5 steps) and theme (system / light / dark), saved per browser. A new visitor gets **dark**, as today.
6. Resume, per browser: a library card shows "Continue · Ch N", which reopens the exact paragraph. **Continue points to the last place actually read.** A quick look at an old range does not overwrite it (§3.3). Opening a range normally starts at its top.
7. Library cards: Continue (if started), "Go to chapter #", and the full range list behind "All chapters" (replaces the 10rem scroll box).
8. App jobs panel: active jobs and unresolved problems stay visible; the rest fold into "Recent (n)", which shows at most 10.
   - A **problem** is a job that ended failed or interrupted, or ended done with item errors.
   - A problem stays visible until a later job of the same kind for the same target ends done with no item errors. Nothing is dismissed by hand.
   - Narrow screens: a "Jobs" toggle opens the panel as a drawer, with a running indicator.
9. App on phones: the sources and library tables stack into cards, and the header and status wrap.
10. App library table: status shows as compact badges. Sources show as host (or folder name for `file://`) plus kind, with the full URL on hover.
11. Compare: a summary line, highlighted differing paragraphs with changed words marked, and links to jump between differences.
12. Tests: Python tests at the existing seams. Browser behaviour is covered by pytest tests marked `browser`, which run **locally only** (excluded by default like `live`) and drive headless Firefox.
13. Out of scope:
    - translation/glossary (paused; see the memory note)
    - one-chapter pages
    - cross-device reading sync
    - audio on the site
    - the Longevity source-7 data issue (1003–1779 publish the MtlTings translation because novelbuddy's official text isn't fetched there)

## 2. Verified baseline

Paths are relative to the repo root. Pub = `packages/novel-publish/src/novel_publish`, App = `packages/novel-app/src/novel_app`.

**Site build**
- `Pub/site.py`:
  - `_paginate` groups chapters by `KeyRange.containing(n, 50)`.
  - `anchor(key)` returns `c{n}` or `c{n}-{part}`.
  - Page context is `novel, page, prev, next, chapters[{anchor, heading, body}]`.
  - The library card dict is `{title, author, chapters, raw_only, pages[{href,label}]}`.
  - `index.html` is rewritten on every build, and `_copy_assets` copies `static/*` to `assets/`.
- Rebuild rules (site.py:102-109): a page is rebuilt when it has stale or pruned chapters, is new, or a neighbour was added or removed.
- `fingerprint()` hashes site.py, render.py, `templates/` and `static/`. Any template or asset change therefore marks every chapter stale, which means one full rebuild of all novels and a ~230 MB redeploy. The app's library staleness counts use the same fingerprint, so after the change they show everything as stale until rebuilt.

**Site templates and assets**
- `base.html` has unversioned asset links and an empty scroll-to-top button.
- `page.html` has a page nav at the top and bottom, a header, `nav.toc`, then the articles.
- `library.html` renders cards with `.book-parts` in a scroll box (`max-height:10rem; overflow-y:auto`).
- `static/site.js` only does scroll-to-top.
- `style.css` is dark only, with hard-coded hex colours and no custom properties.

**App**
- **The app loads the site's `style.css`** (`/site-assets/style.css`, App/web/app.py:64) before `app.css`. `app.css` defines `--bg --surface --border --text --muted --accent…` on `:root`.
- `App/web/templates/base.html`:
  - `main#main` reloads itself on `sse:active` (outerHTML, `hx-disinherit="*"`).
  - `aside.jobs` contains `#jobs`, which the SSE event `jobs` replaces, and only when the HTML changed.
- `job_events` (app.py:209-226) takes `render(list[JobRow])` and derives the active ids from that list. test_web.py:161 pins this behaviour.
- `_jobs.html` renders `Service.jobs(limit=20)`: `JobBoard.jobs`, active first, then newest (jobs.py:217-224).
- Job states: queued, running, done, failed, cancelled, interrupted. `Outcome.errors` on a done job keeps the state DONE (jobs.py:62-66, 319-320).
- `app.css` has one breakpoint (960px, one column). There is no app JS besides vendored htmx 2.0.11 and sse 2.2.4.
- Compare:
  - `pages.comparison` returns `Comparison(number, offers, selected, left, right)`.
  - `Text(source, chapters: tuple[(heading, body: Markup)])` carries HTML that `render.block_html(..., remote_images=False)` has already rendered (App/pages.py:236-261, compare.html:46-49).
  - Layers allow `novel_app` → `novel_publish`/`novel_core` (pages.py:29 already imports `render`).

**Tests**
- `packages/novel-publish/tests/test_site.py` checks HTML by substring and regex. It asserts the exact stylesheet link (:82), the build counts (:128-142) and a byte-identical forced rebuild (:221).
- `packages/novel-app/tests/test_web.py` uses TestClient with a fake-site fixture.
- There are no browser tests and no JS runner.
- `lncrawl-scraper` (`scraper.bidi.FirefoxBackend`, `scraper.browsers.pick_firefox`) is installed through novel-sources.
- Root pytest `addopts` (pyproject.toml:34) includes `-m "not live"` and `--import-mode=importlib`.

## 3. Design

### 3.1 Site build data (owner: `site.py`)

**`novels/<slug>/toc.json`**
- Minimal content: `{"pages": [{"file": "801-850.html", "chapters": [{"n": 801, "a": "c801"}, …]}, …]}`. Everything else (labels, headings) comes from the DOM or saved state.
- Built from the selection only, with no `read_version` calls.
- Written for every novel that has pages, on every build, through a write-if-changed helper. Output is compact, sorted and byte-stable, and `pages_written` keeps counting HTML pages only.
- Raw-only or empty novels get no folder, as today. The file is removed along with the novel folder.

**Cross-page chapter links carry no chapter anchors** (r1 M1).
- At the last chapter of a page, › points to `next.html`, which starts with its first chapter.
- At the first chapter, ‹ points to `prev.html#last`.
- Every page puts `<span id="last"></span>` as the **first child inside its final `<article>`** (r2 R1). These hrefs depend only on which neighbour pages exist, and the current rebuild rules already track that.

**Other build changes**
- Page context adds `slug`. Library cards add `slug` and the `toc` href.
- Site asset links become `assets/style.css?v={fingerprint()[:12]}` (and the same for `site.js`). The app keeps its unversioned `/site-assets/style.css`, which is served live with no CDN.

### 3.2 Site markup

**`base.html`**
- An inline head script runs before first paint. It reads `localStorage` (inside try/catch) and sets `<html data-theme="light|dark" style="--r-scale:…">`.
  - "system" resolves through `matchMedia('(prefers-color-scheme: light)')` and listens for changes.
  - With no saved setting, or without JS, the page is dark (today's look).
- The scroll-to-top button is removed.

**`page.html`**
- `<header class="reader-bar" hidden>` (JS removes `hidden`). It holds the ‹ link, the current heading, the › link, a Chapters button, an Aa button and a Library link.
- `<dialog id="chapters">` holds:
  - an `<ol>` of this page's chapters, with `aria-current="location"` on the current one
  - a go-to form: `<input type=number inputmode=numeric>`, a button and a `role=status` line
  - prev/next page links
- `<dialog id="settings">` holds size −/+ with the current step shown, and a theme radio group (system/light/dark).
- The top page nav and the page header are removed. The bottom page nav stays, so the end of a page leads to the next range. A `<noscript>` block renders the chapter list for no-JS readers.

**`library.html` card**
- `data-slug` and `data-toc` attributes.
- A Continue link and a go-to form, both `hidden` until JS reveals them.
- `<details class="all-chapters"><summary>All chapters (N pages)</summary>` containing the existing `.book-part-link`s, with no max-height box.
- The raw-only card is unchanged.

### 3.3 Site behaviour (`static/site.js`, one IIFE)

**Storage**
- All reads and writes go through a try/catch wrapper. Keys:
  - `reader:settings`: `{scale: 0-4, theme: "system"|"light"|"dark"}`
  - `reader:pos:<slug>`: `{file, anchor, para, label, t}`
- When storage throws, everything still works for the current visit and nothing is saved.

**Current chapter**
- On scroll (throttled with rAF), the current chapter is the last `<article>` whose top is ≤ bar height + 1px.
- **At the scroll bottom (`scrollY + innerHeight ≥ scrollHeight − 2`) the last article is current** (r2 R1).
- Each update changes the bar heading, the ‹/› hrefs and `aria-current` in the sheet.
- ‹ goes to the previous article (or `prev.html#last` from the first one). › goes to the next article (or `next.html` from the last one). At the novel's start or end the arrow is disabled (no href, `aria-disabled`).
- After an in-page jump the link is blurred.

**Reveal bar**
- Shows after ≥ 8px of cumulative upward scroll, or when `scrollY < 64`. Hides after ≥ 8px of downward scroll. Never hides while a dialog is open.
- The bar is fixed and overlays the text. `html { scroll-padding-top: <bar height> }`.
- Transform transition, turned off under `prefers-reduced-motion`.
- No `scroll-behavior: smooth` anywhere.

**Resume, "last place actually read"** (r2 R2)
- Saving is armed once the visit's reading distance reaches 1.5 viewport heights. Reading distance is the sum of |Δ scrollY| over scroll events, **ignoring any single event with |Δ| > 1 viewport**. Such an event is a jump: a hash or anchor link, go-to, ‹/›, browser scroll restoration, or the `?p` restore.
- Arriving through Continue arms it immediately.
- Once armed, the position saved is the current article's anchor plus the index of the first `<p>` in it whose bottom is below the bar. It is saved debounced (1 s) and on `pagehide` or `visibilitychange=hidden`.
- Until armed, nothing is written.

**Continue**
- The library fills each card's Continue link as `novels/<slug>/<file>?p=<para>#<anchor>` with the label "Continue · Ch <label>".
- It refreshes on `pageshow`, including bfcache returns.
- On a page, `?p` plus an existing anchor scrolls to that paragraph (clamped to the paragraph count). `history.replaceState` then removes `?p`. Without `?p`, nothing happens.

**Go to chapter**
- `toc.json` is fetched once, on first use. The target is the first entry with `n == N`.
- If no entry matches: "Chapter N isn't on the site. Nearest: A or B." (nearest lower and higher).
- Invalid input: "Enter a chapter number."
- Fetch failure: "Couldn't load the chapter list."
- The page and the library use the same code.

**Settings**
- Changes apply immediately and are saved.
- Scale steps are ×0.9, 1, 1.1, 1.2 and 1.35 (default index 1).

### 3.4 Site CSS (`static/style.css`)

- Reader colours become custom properties **prefixed `--r-`** (r1 m3). They are defined under `:root` with dark defaults equal to today's exact values, and under `:root[data-theme="light"]`. Only the site script sets `data-theme`, so the app stays dark and unchanged.
- `[hidden]{display:none !important}`.
- New styles: reader bar, dialogs, `.all-chapters`, go-to, Continue. Removed: the `.book-parts` max-height box and the scroll-to-top styles.

### 3.5 App jobs panel

**`JobBoard.panel(recent: int = 10) -> JobPanel(attention, recent)`** and `Service.job_panel()`.
- **attention** (in order):
  - every queued or running job, newest first
  - then, for each (target, kind), its newest **problem** job, if no later job of that (target, kind) ended done with no errors
- A problem is failed, interrupted, or done with a non-empty `errors`. Cancelled jobs, and later failed or partial runs, don't resolve a problem. Only the newest unresolved problem per pair is shown.
- **recent**: the newest `recent` jobs not in attention, newest first.
- "Same job" means same `target` and `kind`; args are ignored. This goes in the docstring. It can be implemented in SQL or in Python over the job rows, whichever reads better.
- `Service.jobs(limit=50)` stays for the per-novel active lookups.

**Plumbing** (r2 m2)
- `page()` puts `job_panel` in the context.
- `job_events` takes `render(JobPanel)` and derives active ids from `attention`. Update test_web.py:161.

**Template and state**
- `_jobs.html` renders attention, then `<h3>Recent (n)</h3>` and the recent items as `li.job.job--recent`.
- Toggle state lives on `aside.jobs`, outside the swapped `#jobs`. The new `static/app.js` toggles the `show-recent` and `open` classes and `aria-expanded`. Both toggle buttons sit in the aside, outside `#jobs`.
- `aside.jobs:not(:has(.job--recent)) .recent-toggle {display:none}`.

**Narrow screens (≤ 960px)**
- The aside becomes a fixed drawer, hidden by default, opened by a "Jobs" button in the app header.
- The running indicator is pure CSS: `.app-header:has(~ .app-layout .job--running)`, so it updates with each SSE swap.

### 3.6 App tables

- `pages.source_label(spec) -> SourceLabel(short, full)`:
  - http(s) URLs give the host without `www.`
  - `file://` URLs give the last path segment, URL-decoded
  - anything else gives the backend name
- In the library, a source shows as `short` plus the kind, with `title=full`. The novel page shows `id: short` with the full URL on a muted line.
- The library's outputs cell becomes badges (`site ✓`, `epub 4 stale`, `audio not built`, `— nothing to build`) built from `Staleness`.
- At ≤ 640px, `table.library` and `table.sources-table` rows become blocks, with each `td` labelled from `data-label`.

### 3.7 App compare diff

**`App/diff.py`** (pure)
- `block_text(block) -> str`:
  - text runs joined for paragraph, heading, system and note blocks
  - `"—"` for a separator
  - the alt text or src for an image
- `diff_blocks(left, right) -> TextDiff`:
  - Uses `difflib.SequenceMatcher(None, L, R, autojunk=False)` on whitespace-normalised block texts (NBSP counts as a space).
  - Each side gets a tuple of `BlockMark(state: same|changed|only, spans: tuple[Span, ...] | None, group: int | None)`.
  - `replace` opcodes pair blocks one-to-one in order; extra blocks on the longer side are `only`.
  - Paired blocks get word spans from a second matcher over `re.findall(r"\w+|\W+")` tokens.
  - Consecutive differing blocks share a group number, starting at 1.
  - `changes` is the number of left blocks not `same` plus right-only blocks. `total` is the number of left blocks.
- If `len(L) × len(R) > 2,000,000`, word spans are skipped. Measured: 0.07 s for 2,200×3,000 blocks, so this is only a safety net.

**`pages.comparison`**
- `Text.chapters` becomes `tuple[Part, ...]`, where `Part(heading, blocks)`. The template renders the bodies.
- The diff runs over each side's concatenated blocks. Part headings are not diffed.
- `Comparison.diff` is None when a side is missing or either source's `spec.kind is Kind.RAW_ZH`. The summary then says "Raw text: no diff".

**Rendering** (simplified per the r2 trim)
- `same` blocks render with `render.block_html` as today.
- Changed blocks render as `<div class="diff diff--changed">` holding the block's plain text with `<mark>` around changed spans. Inline em/strong are not shown in changed blocks (documented).
- `only` blocks render with `block_html` inside `<div class="diff diff--only">`.
- **Ids:** exactly one target per group per side. `id="d{g}-l"` / `id="d{g}-r"` go on the group's first wrapper div on that side. A group with no block on one side gets an empty `<span class="diff-gap" id="d{g}-l">` at the insertion point.
- Summary: "Identical text." or "7 of 52 paragraphs differ · jump: 1 2 3 …" (links to `#d{g}-l`, first 30).
- The page reloads on `sse:active` keep the scroll offset (outerHTML swap). W3 checks this.

## 4. Tests

### 4.1 Seams and harness

**Python seams**
- Site: `build_site` on stores made with the helpers in test_site.py, asserting files, `toc.json` and markup.
- Jobs: `JobBoard` directly, on a tmp `app.sqlite` with an injected clock.
- App: `TestClient(create_app(service))` and direct calls to `pages`/`diff`.

**Browser harness (new, local only)**
- Tests live in `packages/novel-publish/tests/test_site_browser.py` and `packages/novel-app/tests/test_web_browser.py`, marked `browser`.
- Root `pyproject.toml`: `addopts = ["-m", "not live and not browser", "--import-mode=importlib"]` (keeping the existing flag, r2 m3), plus a `browser` entry in `markers`. `lncrawl-scraper~=1.7.0` is added to the root dev dependency group.
- Fixtures:
  - The built tmp site is served by `http.server` on an ephemeral port in a thread.
  - The app runs under uvicorn in a thread with the fake-site service.
  - Driver: `FirefoxBackend(pick_firefox(), headless=True, profile_dir=tmp, extra=["--window-size=390,844"])`, then `attach()`.
  - Prefs go in a pre-written `prefs.js`, because the driver overwrites `user.js`.
  - One helper wraps the private `_rpc.send("script.addPreloadScript", …)`. Its preload script installs `window.__errors` (from `error` and `unhandledrejection`) and, for B8, a throwing `localStorage`.
- Tests read results through `evaluate("JSON.stringify(...)")`, since `evaluate` returns None on exceptions.
- Scrolling is done in steps of ≤ 0.25 viewport, waiting a rAF between steps.
- Tests skip when Firefox is missing. Every browser test ends by asserting that `__errors` is empty.

### 4.2 Case matrix

| ID | Layer | Setup | Action | Expected |
|---|---|---|---|---|
| S1 toc-json | site | chapters 1-3, 51, 52 pt 1, 52 pt 2 | build | toc.json exactly `{"pages":[{"file":"1-50.html","chapters":[{"n":1,"a":"c1"},{"n":2,"a":"c2"},{"n":3,"a":"c3"}]},{"file":"51-100.html","chapters":[{"n":51,"a":"c51"},{"n":52,"a":"c52-1"},{"n":52,"a":"c52-2"}]}]}` (key order as written by the helper); identical bytes after a forced rebuild |
| S2 toc-removed | site | build, then drop the novel | rebuild | folder and toc.json gone |
| S3 cross-links | site | pages 1-50 (1-3) and 51-100 | build | page 1's last article starts with the only `id="last"`; page 1 › at end → `51-100.html`; page 51 ‹ at start → `1-50.html#last`; first page ‹ and last page › disabled |
| S3b gap-fill | site | page 1 = 1-48 and page 51 built; add 49-50 | rebuild | only page 1 rewritten (today's counts); `#last` now inside chapter 50 |
| S4 versioned-assets | site | — | build | `assets/style.css?v=<fp12>` and `assets/site.js?v=<fp12>` (replaces :82) |
| S5 layout | site | — | build | no `nav.toc` outside `<noscript>`; `dialog#chapters` lists the page's chapters; bottom page nav present, top absent |
| S6 library-card | site | 2 novels, one raw-only | build | `data-slug`, `data-toc`, hidden go-to and Continue, `details.all-chapters` with every page link; raw-only card has none |
| S9 hidden | site | — | build | reader bar, Continue and go-to carry `hidden`; CSS has the `[hidden]` rule |
| A1 split | board | running, failed, interrupted, 12 done, 1 cancelled (distinct targets) | `panel()` | attention = running, failed, interrupted; recent = 10 newest of the rest |
| A1b old-problem | board | sync X failed, then 25 done jobs on other targets | `panel()` | sync X failure still in attention |
| A1c resolved | board | sync X failed, later sync X done clean | `panel()` | not in attention |
| A1d not-resolved | board | sync X failed, then sync X cancelled, then epub X done | `panel()` | still in attention |
| A1e newest-only | board | sync X failed twice | `panel()` | only the newer one |
| A1g partial | board | sync X done with 40 errors; then (separately) sync Y failed, then sync Y done with errors | `panel()` | sync X in attention; for Y only the newer partial run in attention (a partial run doesn't resolve) |
| A1f render | web | A1 data | GET / | `#jobs` lists attention, then "Recent (10)"; SSE `job_events` emits `active` from attention ids (updated :161 test) |
| A3 source-label | unit | `https://www.novelbin.com/b/x`; `file:///C:/a/My%20Longevity`; a backend with no URL scheme | `source_label` | `novelbin.com`; `My Longevity`; backend name |
| A4 badges | web | site fresh, epub 4 stale, audio not built, nothing to build | GET / | badge texts and classes |
| A5 labels | web | — | GET / and /novels/x | every `td` in both tables has `data-label` |
| D1 identical | unit | same blocks | diff | 0 changes, all same |
| D2 one-word | unit | "He ran fast." vs "He ran quickly." | diff | one changed pair; spans only `fast`/`quickly` |
| D3 insert | unit | right has an extra paragraph in the middle | diff | that block `only` on the right; group 1; others same |
| D4 uneven | unit | 2 left vs 3 right, all differing | diff | 2 changed pairs + 1 right-only, one group |
| D5 whitespace | unit | differ only by spaces/NBSP | diff | same |
| D6 raw | web | raw-zh vs official-en | GET compare | "Raw text: no diff", no marks |
| D7 bound | unit | 2,200 × 1,000 blocks | diff | completes, no spans |
| D8 render | web | D2 | GET compare | `<mark>` on the changed word; "1 of N"; jump `#d1-l` |
| D8b ids | web | D3 + D4 in one chapter | GET compare | each `href="#dN-l"` matches exactly one id; ids unique; the insert yields a left `diff-gap` span |
| D9 parts | web | 2-part chapter on both sides, differing in part 2 | GET compare | both part headings shown; marks only in part-2 blocks |
| B1 reveal | browser | built page | scroll down 600, up 50; tap ›, scroll down | hidden, then shown, shown at top; hides again after the tap + scroll |
| B2 current | browser | page with 3 chapters | scroll into chapter 2 | bar heading = chapter 2; sheet `aria-current` on chapter 2 |
| B3 cross-next | browser | 2 pages of short chapters | at page 1 bottom tap › | heading names page 1's last chapter before the tap; lands at the top of page 2 |
| B3b cross-prev | browser | same | at page 2's first chapter tap ‹, then ‹ again | heading = page 1's last chapter, then the one before it |
| B4 goto | browser | — | go to existing / missing / "abc" | navigates / "Nearest: …" / "Enter a chapter number." |
| B5 resume | browser | — | step-scroll ≥ 1.5 viewports to ¶7 of chapter 2; open library | "Continue · Ch 2"; following it puts ¶7 just below the bar; `?p` gone |
| B6 normal-open | browser | saved position | open the page from All chapters | starts at the top |
| B6b quick-look | browser | saved Ch 40 ¶7 | open 1-50, step-scroll 0.5 viewport, back to library | still "Ch 40" (pageshow refresh) |
| B6c re-read | browser | saved Ch 40 | open 1-50, step-scroll 3 viewports, back | Continue points into 1-50 |
| B6d jump-only | browser | saved Ch 40 | go to chapter 5, leave | still "Ch 40" |
| B6e restore | browser | saved Ch 40 | open 1-50, step-scroll 1 viewport, reload (scroll restoration), leave | still "Ch 40" |
| B7 settings | browser | fresh profile | load; size +2, theme light; open another page | first `data-theme=dark`, step 1; then light, step 3 |
| B7b system | browser | prefs.js forces a light scheme | choose system | `data-theme=light` |
| B8 storage-off | browser | preload makes `localStorage` throw | use page and library | `__errors` empty, bar works, settings apply for the visit, Continue hidden |
| W1 drawer | browser (app) | running job | load / at 390px | drawer closed, indicator shown; Jobs opens it; stays open across an SSE swap |
| W2 recent | browser (app) | 12 done jobs | expand Recent, wait for an SSE swap | stays expanded |
| W3 compare-jump | browser (app) | D2 | click jump 1, trigger the `sse:active` reload | `#d1-l` in view before and after |

### 4.3 Walkthroughs (agent-run, results shown to the user)

- **W4:** full rebuild of the real library into a scratch copy of `_site`. Screenshots at 390px and 1280px of the library, a CCG page and a Longevity page. Go to 3000 on CCG. Resume flow.
- **W5:** app screenshots before and after (library, novel, compare, add) at 390px and 1280px. The site CSS change must not visibly change the app.
- **Deploy** (`nov build site`, then `nov deploy site`, a full ~230 MB push) happens only after the user confirms.

## 5. Gates

- **G1** (slice 0): `--window-size=390,844` gives `innerWidth == 390`. `evaluate` + `scrollBy` work. The preload script runs before page scripts. Acceptance: the smoke test passes 3 of 3 runs. Fallback: `_rpc.send("browsingContext.setViewport", …)`.
- **G2** (slice 0): the `prefs.js` colour-scheme override (`layout.css.prefers-color-scheme.content-override`) reaches `matchMedia`. Fallback: drop B7b and cover "system" with a static check of the head script.

## 6. Code-design notes

- `site.py` stays the single owner of page grouping. toc.json and the cross-page hrefs are derived from the same `pages` list, so the JS never recomputes page arithmetic.
- **One JS file per surface, no framework.** site.js is about 300 lines in sections (storage, bar, current chapter, resume, go-to, settings). app.js only toggles two classes.
  - Rejected: a JS build step or JS test runner. Browser tests cover behaviour through the real page.
- **Board-level panel rule.** The attention rule is data policy, so it lives in `JobBoard.panel`, where tests can pin it without HTTP.
  - Rejected: filtering in the template (it can't see beyond `LIMIT 20`).
- **Diff as a pure module over blocks.** It sits apart from rendering, so it can be tested without HTML.
  - Rejected: diffing rendered HTML (fragile markup alignment).
  - Rejected: keeping inline formatting in changed blocks. It needed a new render seam (r2 m1) and isn't needed to spot differences.

## 7. Slices (each: failing test → code → green → commit)

0. Browser harness: marker, `addopts`, dev dependency, fixtures, G1/G2 smoke test.
1. Site data: toc.json, slug, anchor-free cross-page hrefs, `#last`, versioned assets (S1, S2, S3, S3b, S4).
2. Site CSS tokens, light theme, settings dialog, head script (S9 CSS part, B7, B7b, B8).
3. Site page layout: reader bar, chapters dialog, noscript list, current chapter, ‹/›, go-to (S5, S9, B1, B2, B3, B3b, B4).
4. Site resume and library cards (S6, B5, B6, B6b–B6e).
5. Jobs: `JobBoard.panel`, then `Service.job_panel` + `job_events`, then template, app.js and drawer (A1–A1g, A1f, W1, W2).
6. App tables: source labels, badges, phone CSS (A3–A5).
7. Compare diff: `diff.py`, `Part`, template (D1–D9, W3).
8. W4 and W5 walkthroughs, plan notes. Deploy only on user confirmation.

## 8. Definition of done

- All non-browser tests and `lint-imports` pass in CI.
- All browser tests pass locally.
- The user has reviewed the W4/W5 screenshots.
- The real site is rebuilt, and deployed after confirmation.

## 9. Review log

- **r1 full independent review.** Folded in:
  - M1: stale cross-page anchors, replaced by anchor-free hrefs and `#last`
  - M2: failures dropping off `LIMIT 20`, fixed by `JobBoard.panel`
  - M3: duplicate or missing jump ids, part mapping, raw detection by kind
  - M4: harness specifics
  - m1: toc.json without `read_version`
  - m2: `[hidden]` rule
  - m3: `--r-` token prefix
  - m4: blur after jumps
  - m5: reload behaviour
  - Optional items adopted: hide an empty Recent toggle; hide the no-JS go-to.
- **User rulings after r1:** resume uses the last place actually read; problems stay until a later clean run; the default theme is dark.
- **r2 focused review.** Folded in:
  - R1: current chapter at the scroll bottom, `#last` inside the final article, new test B3b
  - R2: reading distance ignores single jumps over 1 viewport; step-scrolling tests; B6e; `pageshow` refresh
  - R3 (user ruling): done-with-errors counts as a problem and doesn't resolve one
  - m2: SSE plumbing
  - m3: keep `--import-mode=importlib`
  - m4: slice and matrix sync
  - m5: reload keeps the offset, not the hash
  - Scope trims: toc.json reduced to `{n, a}` per chapter (S8 dropped); changed blocks render as plain marked divs (D10 dropped, no render seam).

## 10. Implementation notes (2026-10-20)

All slices are done on `main` (not pushed): 327 default tests and 21 local `browser` tests pass, and `lint-imports` keeps its contract. A two-axis review (standards, spec) found every §4.2 case covered; its fixes are in the last commit.

**Gates**
- G1: `--window-size` is ignored by headless Firefox on Windows (innerWidth stayed 1366). The fallback `browsingContext.setViewport` works, 3 of 3 runs. The harness lives in `tools/firefox_page.py`.
- G2: the `prefs.js` colour-scheme override reaches `matchMedia` (both values), so B7b stays.

**Deviations from the design**
- Jobs: the Recent toggle is a button in the "Recent (n)" heading inside `#jobs`. Its state is still on `aside.jobs`, and `app.js` restores `aria-expanded` from a MutationObserver after each swap.
- Jobs: the running dot is a class set by `app.js`, not pure CSS. Firefox left the `:has()`-driven `::after` drawn after the job ended (W1 caught it).
- Compare: `Part` is `(heading, body)` with the body rendered in `pages._marked_parts`, so the ids and gaps are built in one tested place rather than in the template.
- Compare, added after W5 on real data: changed words separated only by spaces form one mark, and a paired paragraph with more than half its text changed is highlighted without word marks (two translations otherwise marked nearly every word). `BlockMark.spans` is `()` for such a rewrite. Needs the user's confirmation.
- Go-to input: a visually hidden label and a "Chapter #" placeholder, so it fits one row on library cards.
- The library shows `site — nothing to build` as the badge text; the novel page keeps its longer staleness text.

**Walkthroughs**
- W4: the real library copied into a scratch folder and rebuilt in 70 s; the site is 128 MiB (not the ~230 MB estimated). Phone and desktop screenshots of the library, a CCG page, Longevity in light and dark, go to 3000, and the resume flow.
- W5: `nov serve` from the plan commit and from `main` on the same data copy, phone and desktop. The app's palette and layout are unchanged apart from the intended changes.
- Seen in the data, not caused by this work: CCG chapter 3000's title reads "2998: Multithreaded Fellow Daoists Discussion".

**Shipped** (user confirmed 2026-10-20, including the compare rewrite rule)
- `main` pushed; CI green on 3b68984.
- Real site rebuilt (every page) and deployed: gh-pages b154b477c613, 128 MiB; the live index serves the new versioned assets.
