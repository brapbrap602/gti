# App UI overhaul (`nov serve`): developer plan

Status: approved by the user 2026-10-21 (r2). Not implemented; building it needs the user's go-ahead. Three independent reviews are folded in: r1 reviewed the baseline (§9.1), r2 reviewed draft r1 (§9.2), and a focused follow-up checked the r2 changes (§9.3).
Related: [stakeholder plan](app-ui-stakeholder.md) · [reader UI plan](reader-ui-developer.md) (it built today's jobs drawer, compare diff and phone tables) · [platform plan](novel-platform-developer.md).

Paths are relative to the repo root. App = `packages/novel-app/src/novel_app`, Web = `App/web`, Tests = `packages/novel-app/tests`.

## 1. Decisions

**User decisions (2026-10-21)**
1. Scope: only the local `nov serve` app. The reader site (`novel-publish`) is not touched.
2. Depth: a reskin and a restructure of the pages, using only data the Service already exposes. Routes, forms, job behaviour and the no-JS fallbacks stay as they are. Rejected: a reskin only, and new backend data (covers, author, sync history).
3. Dark theme only. Rejected: light + dark.
4. Style: "shadcn UI inspired, pretty, informative".
5. The user left layout and aesthetic details to the agent: "be sensible and aesthetically pleasing and very functional". Anything in §3–§5 that is not listed here is the agent's call under that delegation.
6. Baseline approved: the design system, a sidebar plus a jobs sheet, library cards, novel tabs, the other pages restyled, no Service data changes, no reader-site changes.

**Agent decisions under the delegation.** Each one can be revised at the screenshot gate, G3.
- **D1.** Hand-written CSS with shadcn's zinc-dark tokens and component vocabulary. No Tailwind and no build step: the app has no JS/CSS tooling, and the repo stays self-contained.
- **D2.** Vendor Geist Sans/Mono (OFL-1.1) and a Lucide icon sprite subset (ISC). No CDN.
- **D3.** Shell: a left sidebar with Library, Add novel, then every novel with a status dot; a top bar with breadcrumbs and a Jobs pill.
  - With JS: jobs open as a right sheet at every width. The sidebar is a sheet below 1024px and on `wide` pages.
  - Without JS: both render inline.
- **D4.** Library: stat cards plus one card per novel, replacing the table.
- **D5.** Novel page: a header, stat cards, then the tabs Sources / Chapters / Translate / Check. The hash selects the tab; **Chapters is the default**.
- **D6.** An output that is not built gets a neutral badge. Only a built output with stale chapters counts as "needs rebuild" (amber).
- **D7.** The Jobs pill shows a running dot, the text "N running" or "N problems", and a thin progress bar for the first running job. The server renders it, and `app.js` keeps it live.
- **D8.** `unpin` redirects to `#sources`. With no hash it would now land on the default tab, Chapters.

## 2. Verified baseline

**Templates and assets**
- Templates in Web/templates: `base, library, novel, compare, comparisons, comparison_chapter, glossary, add, error`.
- Partials: `_jobs, _term, _estimate, _notice, _macros`.
- `Web/static/app.css` (418 lines) and `app.js` (50 lines: the drawer, the Recent toggle and the running dot).
- Vendored htmx 2.0.11 and sse 2.2.4, with hashes in `vendor/README.md`. That README says "Both are 0BSD".
- **CSS coupling:** `base.html:9` loads the reader site's `style.css` from the `/site-assets` mount (`app.py:78`; nothing else uses the mount).
  - The app gets these from it: body background, colour and font, `overflow-x:hidden`, `* {box-sizing}`, `[hidden]`, link colours, `p` margins, `.chapter`, `.badge`, `.status-msg`, `.separator`, `.system`, `.note`, `blockquote` and `img {max-width}`.
  - That file is part of the site `fingerprint()` (`packages/novel-publish/src/novel_publish/site.py:68-77`). Any edit to it, even a comment, makes every built page stale.
- Compare text is `render.block_html` output (`App/pages.py:423-426`): `<p>`, headings, `<hr class="separator">`, `<img>`, `p.system` and `aside.note`.

**Live updates** (`base.html`, `app.py:340-358`)
- The SSE `jobs` event swaps `#jobs` (inside `aside.jobs`) when its HTML changes. `job_stream` renders `_jobs.html` with only `job_panel` and `owns`.
- The SSE `active` event fires when the set of active job ids changes. `main#main` then re-GETs path + query (no hash) and swaps itself with `hx-select="#main"` and `hx-disinherit="*"`. Nothing else on the page is re-rendered.
- **htmx 2.0.11 facts** (checked in r2 against the vendored file):
  - `hx-select-oob` on `#main` is read from the requesting element, including on the `sse:active` `hx-get`, and takes its ids from the full response before `hx-select` narrows it.
  - `hx-disinherit="*"` keeps it off the forms inside `#main`.
  - `htmx:afterSwap` fires for the new `#main`.
  - The `<head>` of the response is ignored apart from the title.
- htmx restores focus only by element id.

**Data, rendering and redirects**
- `page()` (`app.py:90-95`) is synchronous. It adds `jobs` (20 rows) and `job_panel` to every page, and every page that extends `base.html` goes through it.
- `refused()` renders `error.html` through `page()`, or `_notice.html` with only `error` for htmx. `done()` renders `_notice.html` with only `notice`.
- `Service.library()`:
  - It builds one row per novel, with one `board.last_ended()` query per row.
  - `_read()` caches each view by DB stamp (`service.py:513-547`). The stamp changes with every commit, so during a sync the syncing novel's view is read again on every call (`service.py:1001`).
  - The library route calls it via `run_in_threadpool` (`app.py:126`).
  - The library page takes ~80 ms warm on the real library; this was not measured during a sync.
- **Job problems:** `JobBoard.panel` (`jobs.py:235-259`) puts active jobs first in `attention`, followed by unresolved problems (failed, interrupted, or done with item errors). Recent jobs, failed ones included, go to `recent`.
- **Hash redirects:**
  - `priority` (`app.py:171`) and `publish` (`:197`) redirect to `#sources`.
  - `add_setup` (`:214`) and the Translate form's `back` (`novel.html:130`) go to `#translate`.
  - `unpin` (`:189`) redirects with no hash.
- **Hash links:**
  - `#check`: `_estimate.html:7,11` and `novel.html:117`.
  - `?setup=N&range=stale#translate`: `novel.html:118` and `glossary.html:43`.
  - The `#translate` back link: `comparisons.html:4`.
- The Chapters section has no id. The Translate section is absent when `translate_panel` is None.
- Python 3.12 on this machine guesses no MIME type for `.woff2`, so StaticFiles would serve the fonts as `text/plain`.

**Tests**
- About 45 TestClient tests in `Tests/test_web*.py` match on HTML substrings and regexes; see §7.1.
- Browser tests (`test_web_browser.py`, marker `browser`, local only) use `tools/firefox_page.py`:
  - `firefox(profile, size=PHONE, prefs=None)`.
  - `Page.screenshot(path)` captures the viewport only.
  - `Page.js` runs BiDi `script.evaluate`. A preload script records errors in `window.__errors`.
  - The fixture novels are `raw-novel` and `english-only` (from `novels`), plus `test-novel` through `added()`.
- CI (`.github/workflows/ci.yml`) runs `uv run pytest`, without the browser tests.

## 3. Design system

### 3.1 Files (proposed)
| File | Owns |
|---|---|
| `Web/static/ui.css` | Tokens, base/reset, typography, the prose scope and the components in §3.3. Knows nothing about novels. |
| `Web/static/app.css` (rewritten) | The shell (sidebar, top bar, sheets, toast) and per-page layout: library cards, novel tabs, chapter grid, glossary, compare, comparisons, add. |
| `Web/templates/_ui.html` | Generic macros: `icon(name, label=None)`, `badge(text, variant)`, `stat(label, value, hint=None, icon=None)`, `empty(icon, text)`. |
| `Web/templates/_macros.html` | The domain macros stay here and use `_ui`: `job_button`, `build_menu`, the outputs badge, `staleness`, `busy_reason`. |
| `Web/static/vendor/fonts/` | `Geist[wght].woff2`, `GeistMono[wght].woff2`, `OFL.txt` |
| `Web/static/vendor/lucide.svg`, `LICENSE-lucide.txt` | A `<symbol>` sprite of the icons in §3.4 |

- Why two CSS files: the component layer serves every page and changes for different reasons than page layouts. A third file would add a request and gain nothing.
- Load order is `ui.css` then `app.css`. No `@layer`; flat, single-class specificity.
- `app.py` registers `mimetypes.add_type("font/woff2", ".woff2")` before mounting static. The font preload carries `crossorigin`.

### 3.2 Tokens (`:root` in ui.css)
```css
--background:#09090b; --foreground:#fafafa;
--card:#0c0c0e; --card-foreground:#fafafa;
--popover:#0c0c0e; --muted:#27272a; --muted-foreground:#a1a1aa;
--secondary:#27272a; --accent:#27272a; --border:#27272a; --input:#27272a; --ring:#d4d4d8;
--primary:#fafafa; --primary-foreground:#18181b;
--destructive:#ef4444; --ok:#22c55e; --warn:#f59e0b; --info:#38bdf8;
--mine:#a78bfa; --raw:#a16207; --official:#2dd4bf; --missing:#3f3f46;
--radius:0.5rem; --sidebar-w:15rem; --topbar-h:3.25rem;
--font-sans:"Geist", ui-sans-serif, system-ui, "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
--font-mono:"Geist Mono", ui-monospace, "Cascadia Code", Consolas, monospace;
```
- The values are illustrative and get tuned at G3.
- The CJK fallbacks sit in the base stack because a lot of zh text has no `lang` attribute (the raw compare side, Check titles). `:lang(zh)` also gets a CJK-first stack and a larger line-height.
- The chapter-grid colours map one to one from the old palette onto the new tokens. Each state also keeps its text (title, aria-label, legend).

### 3.3 Components (classes in ui.css)
- **Button** `.btn`:
  - Variants `--primary` (the default), `--secondary`, `--outline`, `--ghost` and `--destructive`. Sizes `--sm` and `--icon`.
  - States: hover, a `:focus-visible` ring, and `:disabled` (opacity 0.5, not-allowed cursor).
  - Bare `<button>`, `<input>` and `<select>` get the outline look as their base style, so markup that hasn't been migrated still looks right.
- **Badge** `.badge`: `--secondary`, `--outline`, `--ok`, `--warn`, `--destructive`, `--info`.
- **Card** `.card`, `.card-header`, `.card-title`, `.card-description`, `.card-content`, `.card-footer`. Cards never set `overflow:hidden`, so `details.menu` dropdowns aren't clipped.
- **Form controls:**
  - Inputs and selects are 2.25rem high with `--input` borders.
  - `.field` holds a label, a control and a `.field-hint`. `.field-row` is a flex row that wraps.
- **Tables:**
  - `.table-wrap` scrolls sideways.
  - Tables inside it are styled through `.table-wrap > table`: a muted header, row hover, and numbers right-aligned (`.num`).
  - No class goes on the `<table>` itself, because `<table class="sources-table">` must stay exactly as it is (test_web.py:238).
- **Tabs** `.tabs` + `.tab`: a segmented pill look, with a `.tab .count` badge. The glossary's server tabs (`aria-current="page"`) and the novel page's hash tabs (`data-tab-link`, with `aria-current="true"` set by JS) share it.
- **Dropdown** `details.menu`: the existing markup, restyled as a popover with `--popover` and a shadow. `app.js` closes it on an outside click or Escape.
- **Sheet** `.sheet`: a fixed side panel with a header and a close button. It is not a `<dialog>`, so the toast can sit above it (§4.4).
- **Progress:** `progress` is restyled. `.meter` is a stacked bar of chapter states, made of `<span style="flex-grow:N">` segments.
- **Stat** `.stat`: a label, a big number, an optional muted hint and an optional icon.
- **Alert** `.alert`, with `--destructive` and `--warn` variants. Used by error.html, `busy_reason` and the blocked notes.
- **Toast:** see §4.4.
- **Empty state** `.empty`: an icon, text and an action.
- **Prose** `.prose`: the reader typography for `block_html` output, now owned by the app.
  - It covers `p` margins, headings, `.chapter`, `hr.separator`, `p.system`, `aside.note`, `blockquote`, `img {max-width:100%}` and `mark`.
  - It is used on `.compare-text`, `.reference-text` and `.judgement-text`.
- **Base:** `*{box-sizing:border-box}`, `[hidden]{display:none!important}`, links (foreground colour, underline on hover), `code` (mono on `--muted`), `.visually-hidden` and `::selection`.

### 3.4 Vendoring (G1)
- **Geist:** variable woff2 files from the official `vercel/geist-font` release.
  - Record the version, URL and SHA-256 in `vendor/README.md`, and ship `OFL.txt`.
  - Preload only Sans; Mono loads when needed. Both use `font-display: swap`.
  - Accept a combined size of about 150 KB or less. If they're bigger, use static 400/500/600 subsets instead.
- **Lucide:** pin one `lucide-static` release.
  - Copy these SVGs into a sprite by hand: `library, plus, book-open, refresh-cw, hammer, chevron-down, chevron-right, x, check, circle-alert, triangle-alert, loader, list, git-compare, languages, file-text, panel-left, activity, rotate-ccw, square, pin, pin-off, arrow-up, arrow-down, external-link, search`.
  - Record the release, each source file's hash, the sprite's hash and the steps to regenerate it. Ship Lucide's LICENSE.
- Replace the README's "Both are 0BSD" with one licence line per file.
- `icon()` renders `<svg class="icon" aria-hidden="true"><use href="/static/vendor/lucide.svg#NAME"/></svg>`.

## 4. Shell

### 4.1 Layout (`base.html`)
```
┌ sidebar ───────────┬ top bar: [≡] Library › Longevity › Glossary      [● 2 running ▬▬▬] ┐
│ ◆ Novel library    │                                                                   │
│ ▸ Library          │  #notice (toast)                                                  │
│ ＋ Add novel       │  main#main (max-width 80rem, centred; wide pages take full width)│
│ NOVELS             │                                                                   │
│ ● Beyond The Ti…   │                                                                   │
│ ○ 苟在两界修仙      │                                                                   │
│ ● My Longevity…    │                                                                   │
└────────────────────┴───────────────────────────────────────────────────────────────────┘
                                                             aside.jobs = right sheet (JS)
```
- **`<head>`:**
  - A tiny inline script runs before paint. It adds `js` to `<html>` and sets `data-tab` from the hash (§5.2).
  - Then the font preload, `ui.css` and `app.css`, followed by htmx, sse and app.js (deferred).
  - The `/site-assets` link and mount are removed.
- **Sidebar** `nav#sidebar` (`aria-label="Main"`):
  - It holds the Library and Add novel links, then `ul#nav-novels`: one `li[data-novel=slug]` per row. Each row has a link with `id="nav-<slug>"`, so htmx keeps focus across the OOB swap, and a status dot.
  - The dot states:
    - **running:** `row.job` is set.
    - **needs rebuild:** some output has `built > 0` and `stale > 0`.
    - **raw only:** the novel has only raws.
    - **ok:** otherwise.
  - Each dot gets its text through `title` and visually-hidden text.
  - Under `html.js`, below 1024px and on `body.wide`, the sidebar is a sheet opened by `.nav-toggle`. The `.open` state sits on `nav#sidebar`, never on the swapped `#nav-novels`.
  - Without JS it is always inline. Below 1024px it stacks above the content as a compact link list, and `.nav-toggle` is hidden (`html:not(.js)`).
- **Top bar** `header.topbar`, sticky and `--topbar-h` high:
  - the nav toggle
  - breadcrumbs (`nav aria-label="Breadcrumb"`, from a `crumbs` block each template fills)
  - the Jobs pill `button.jobs-toggle`
    - It contains `.pill-label` and `.pill-progress` (a 3px `<progress>`).
    - It keeps the `jobs-toggle--running` class and its `::after` dot, which is a browser-test contract.
- **`#notice`** sits in the DOM right before `main`, so the toast can sit in normal flow without JS (§4.4).
- **`aside.jobs#jobs-panel`** stays after `main`.
  - Under `html.js` it is a right sheet at every width, hidden until `.open`. It keeps the `aria-expanded` sync, and Escape closes it and returns focus to `.jobs-toggle`.
  - Without JS it renders inline as a card after `main`, and its Cancel and Re-run POST forms work as they do today.
  - Opening one sheet closes the other.
- **`wide` page class:** the sidebar is a sheet (under `html.js`) and main takes the full width.
  - On desktop the comparison chapter's `.reading-wrap` is its own scroller. Its `max-height` becomes `calc(100dvh - var(--topbar-h) - 1rem)`; its inner sticky `thead` and reference offsets stay relative to the wrap and get no top-bar offset.
  - On phones the wrap has `overflow: visible`, so there the sticky offsets add `--topbar-h`.

### 4.2 Sidebar data (`app.py`)
- `page()` and `refused()` become `async` (call sites change to `return await page(...)`).
  - `page()` adds `nav_rows = await run_in_threadpool(service.library)`. It never calls `library()` on the event loop.
  - If `library()` raises, `page()` logs the error and falls back to rows `NavRow(slug, title=slug)` built from `service.novels()`, with a neutral dot, so `refused()` and other pages still render. Plain strings won't do: Jinja would render `row.slug` on a string as empty.
  - The library route passes its own `rows` as `nav_rows`, so `/` doesn't call `library()` twice.
  - `job_panel` and `jobs` are computed as before.
- `main#main` gains `hx-select-oob="#nav-novels"`. The `sse:active` reload response is already a full page, so the sidebar list is refreshed with no extra request. That covers a novel just created by `add`, stale states after a build, and running dots.
- Cost: one cached `library()` per page, in the threadpool. G2 times it on the real library while a sync is running.

### 4.3 Jobs pill and the progress mirror (`app.js`)
**One rule for "problems", used by both sides:**
- Server (`base.html`): `job_panel.attention | rejectattr("state.active") | list | length`.
- JS: `#jobs li.job:not(.job--recent):not(.job--running):not(.job--queued)`.

Both count the unresolved problems in `attention`: failed, interrupted, and done with item errors. Neither counts Recent.

**Server first frame (`base.html`):**
- The pill label is "N running" if any job is active, else "N problem(s)" if there are problems, else "Jobs".
- `.pill-progress` shows `done/total` of the first active job that has a total; otherwise it is hidden.

**One `sync()`** extends today's function and runs from the existing MutationObserver on `aside.jobs`, and also after the `htmx:afterSwap` of `#main`. It:
1. counts the active jobs (`li.job--running, li.job--queued`) and the problems (the rule above), toggles `.jobs-toggle--running`, and updates `.pill-label` and `.pill-progress` from the first active item's `progress[value][max]`.
2. for each active `#jobs li.job[data-target=T]` that has a `<progress>`, updates `[data-job-progress=T]` in `#main` (library card, novel header) with "Label done/total" and the progress value, and shows it. A `[data-job-progress]` with no active job is hidden.
3. restores `aria-expanded` on `.jobs-toggle` and `.recent-toggle`, as today.

`_jobs.html` is unchanged; it already renders `<progress max value>` (`_jobs.html:8`). The sidebar's running dots need no mirror: the running set only changes on `active`, which already refreshes `#nav-novels` out of band.

### 4.4 Notices as toasts
- **`#notice`:**
  - `role="status"` and `aria-live="polite"` stay.
  - It is still the `hx-target` of every job form and the target of 4xx swaps.
  - Placed right before `main`, it is `position: fixed` (bottom right, `z-index` above both sheets) only under `html.js`. Without JS it shows in flow at the top of the content, and the close button is hidden.
- `_notice.html` renders `.toast` (with `--destructive` for `error`), the message, and `button.toast-close` with `aria-label="Dismiss"`. It needs only `notice`/`error` in its context, as today.
- **Dismissal (`app.js`):**
  - Close removes the toast's content.
  - A success toast clears itself after 6 s. The timer starts on a swap into `#notice` and also at DOMContentLoaded when a success toast is already rendered (the `?notice=` redirect from plain POST forms: publish, priority, pin, unpin, add setup, add term).
  - Every swap into `#notice` cancels the pending timer first, so a timer can't wipe a newer error.
  - An error stays until it is closed or replaced.

## 5. Pages

**Shared across pages:** a page header (h1, a muted description, actions on the right) and a card per section. Wording pinned by tests (§7.1) stays unless §7.1 says otherwise.

### 5.1 Library (`library.html`)
- **Header:** "Library", a muted description, and the actions *Build site* (`job_button`) and *Add novel* (a link styled `.btn--outline`).
- **Stat row** (computed in the template from `rows` and `job_panel`):
  - **Novels:** the count, with "k raw only" as a hint.
  - **Chapters:** the sum of `selected`.
  - **New to fetch:** the sum of `new_items` over rows that can sync, with "in n novels" as a hint.
  - **Needs rebuild:** the number of novels with a stale built output (D6).
  - **Jobs:** how many are running, plus problems (§4.3 rule).
- **Novel cards** `ul.novel-cards > li.card.novel-card[data-novel=slug]`: a grid of `repeat(auto-fill, minmax(22rem, 1fr))`, one column on phones. Each card has:
  - **Title:** links to the novel page, with the "raw only" badge and a muted slug.
  - **`dl.metrics`:** Chapters (`selected`, plus a per-kind line such as "1354 official-en · 159 raw-zh"), Gaps, New (or "no web source"), Last sync.
  - **Sources:** an ordered list of host label and kind badge, with the full URL in `title`.
  - **Outputs:** badges for site, epub and audio. Fresh is ok, stale is warn, missing is a neutral outline, none is muted.
  - **Footer:** Sync (`job_button`), Build (`build_menu`), Open, and `[data-job-progress=slug]`. That last one is server-rendered from `row.job` and hidden when the novel has no active job.
- **Empty library:** `.empty` with the existing text "The library is empty…".

### 5.2 Novel (`novel.html`)
- **Breadcrumb:** Library › Title.
- **Header:**
  - The h1 title with the raw-only badge, and "slug · last sync X" muted below it.
  - **Actions:**
    - Sync and Build ▾.
    - The Glossary link: "Glossary", followed by its status text (today's wording: the counts, or "no entries yet").
    - The Comparisons link: "Model comparisons", followed by `<span class="muted">` with the run count (today's "N runs" or "none yet" wording).
  - `busy_reason` as an `.alert`, and `[data-job-progress=slug]`.
- **Stat row:**
  - **Chapters selected**, with the per-kind hint.
  - **Gaps**.
  - **New to fetch** (`new_items`).
  - **Outputs:** three badges with their staleness text.
- **Tabs** `nav.tabs[aria-label="Novel sections"][data-tabs]`, with links `a.tab[data-tab-link=X][href="#X"]`:
  - **Sources:** shows the source count.
  - **Chapters:** shows failed + missing when that is non-zero.
  - **Translate:** shown only when `translate` exists; shows the total of stale chapters.
  - **Check:** shows `novel.check.problems`, or a ✓.
  - `app.js` sets `aria-current="true"` on the active link. There is no `role=tablist`.
- **Panels** `section[data-panel=X]` with ids `sources`, `chapters` (new), `translate` and `check`. Their inner content stays and is restyled:
  - **Sources:** `<table class="sources-table">` (exact class kept, `data-label` cells) inside `.table-wrap`; up/down icon buttons; Publish/Unpublish; the pins list with Unpin.
  - **Chapters:** the legend, a whole-novel `.meter`, then one `<details>` per block. Each block's summary shows the range, a small `.meter` and the counts. The cells are restyled.
  - **Translate:** the setups table; the Translate form as a card with fields; the estimate; and "Add a translator setup" in `<details>`.
  - **Check:** the same `<details>` lists, each summary with a count badge. "No problems found." becomes an ok alert.

**Tab behaviour.** The selection lives on `<html data-tab>`, outside `#main`, so a `#main` reload neither flashes nor resets it.
- **Before paint:** the head script sets `data-tab` to the hash if it names `sources|chapters|translate|check`, else to `chapters`.
- **CSS:** under `html.js`, `[data-panel]` is hidden unless it matches `html[data-tab]` (four explicit rules), and the matching `.tab` is styled active.
  - If `data-tab` names a panel the page lacks (`#translate` on an English-only novel), `app.js` resets it to `chapters` on DOMContentLoaded.
  - Without JS, every panel shows, stacked.
- **Clicks:** `app.js` delegates clicks on any `a[href^="#"]` whose target is a `[data-panel]`: tab links, `#check` in the estimate, `#check` on the failed cells. On a click it:
  1. sets `data-tab` and `aria-current`
  2. calls `history.replaceState` with the hash
  3. scrolls the tab bar to the top, under the top bar

  This works on a second click of the same link, because nothing relies on `hashchange`. Back/forward still go through `hashchange`.
- **Scope:** all of this runs only when `[data-tabs]` exists. It ignores the glossary's tabs (no `data-tab-link`) and compare's `#dN-l` jumps.
- **Loading at `#check`:** the panels are hidden before paint, so the browser's own anchor scroll lands on the Check panel. Panels have `scroll-margin-top: calc(var(--topbar-h) + tab bar height)`.
- **Redirects:** `#sources` and `#translate` land on those tabs. `unpin` now redirects to `/novels/x#sources` (D8). Translate's `back` keeps `#translate`.

**Pages helper** (`App/pages.py`), both pure:
- a `NovelCheck.problems` property, moving today's template sum (`novel.html:160`) into Python
- `state_counts(blocks) -> dict[CellState, int]`, for the whole-novel meter

### 5.3 Glossary (`glossary.html`, `_term.html`)
- **Breadcrumb:** Library › Title › Glossary.
- **Two cards:**
  - "Build glossary": model, cap, the button and the blocked note.
  - "Add a term": fields with labels and a hint.
- The stale-translations panel becomes an `.alert--warn`, keeping its list and the "Translate stale" links.
- The tabs restyle onto `.tabs`, with `aria-current` and the counts as before. The filter row becomes a toolbar.
- The bulk bar is sticky under the top bar while the table is in view.
- **Term rows:**
  - Status is a badge: needs review = warn, accepted = ok, locked = info, proposed = secondary, rejected = muted.
  - The actions are small buttons.
  - Every `id` in `_term.html` stays as it is (the focus contract), and the htmx response still starts with `<tbody id="term-N"`.

### 5.4 Compare (`compare.html`)
- **Breadcrumb:** Library › Title › Chapter N. The title comes from `nav_rows`, falling back to the slug.
- **Toolbar card:** prev/next buttons, the Left/Right selects and Show. "The book uses source N" stays as text with a badge.
- **Diff summary:** an alert with "k of n paragraphs differ" and the jump links as small chips. The `<a href="#d1-l">1</a>` markup stays.
- **Each side:** a card. Its header shows the source title and a kind badge, then "Used by the book" (an ok badge) or the pin form. The text is `.prose`.
- Diff colours move onto tokens; `mark` stays.
- `[id^="d"]` gets `scroll-margin-top: calc(var(--topbar-h) + 1rem)`.

### 5.5 Model comparisons (`comparisons.html`, `comparison_chapter.html`)
- Tables restyle through `.table-wrap`. The attempt ✓/✗ marks keep their classes and text, and the judgement `<details>` become cards.
- The chapter screen stays `wide`: a column-picker card, then the reading table with sticky offsets as in §4.1. Reference and judgement text use `.prose`.

### 5.6 Add (`add.html`), error, log
- **Add:** a card form.
  - Fields: URL (full width), Language and Backend with hints, and a Preview button.
  - The preview card shows a definition list (backend, kind, URL), then "Attach to" and "Add and read the chapter list". The long-job note becomes the footer text.
- **error.html:** an `.alert--destructive` with the message. The h1 stays "Refused", plus a back-link button.
- **Job log:** stays plain text; out of scope.

## 6. Failure and edge behaviour
| Situation | Behaviour |
|---|---|
| JS disabled, any width, `wide` pages too | Sidebar inline (nav toggle hidden), every panel shown, jobs panel inline, toast in flow, every form posts and redirects. Same capabilities as today. |
| `library()` raises while rendering any page | Sidebar falls back to slugs; the page renders. The library page itself still surfaces its error as today. |
| Hash names a missing panel | Falls back to Chapters. |
| `sse:active` reload | Tab kept (state on `<html>`); sidebar refreshed out of band; focus in the sidebar kept by id; job progress mirrored again after the swap. |
| Job progress changes without `active` | Pill and card progress update from `#jobs` within one SSE tick. |
| Success toast, then a 4xx within 6 s | The error replaces it and stays; the old timer was cancelled. |
| Long title, long URL, CJK title | Ellipsis in the sidebar and cards (full text in `title`); URLs wrap (`overflow-wrap:anywhere`); no sideways scroll at 390px. |
| Thousands of chapters | Grid blocks stay collapsed unless missing or failed, as today; the meters add one element per state. |

## 7. Tests

### 7.1 Existing contracts, kept or deliberately changed
**Kept verbatim**
- `#jobs` stays inside `aside.jobs`.
- Job items keep the exact pattern `<li class="job job--(\w+)( job--recent)?" data-job="(\d+)"` (test_web.py:226).
- The Recent heading regex `<h3[^>]*><button[^>]*>Recent \(10\)</button></h3>` still matches.
- `aria-expanded` on `.jobs-toggle`, the `::after` dot under `.jobs-toggle--running` (`RUNNING_DOT`), and `#recent-jobs` stay.
- **Compare:**
  - the `mark` count
  - `<span class="diff-gap" id="d1-l"></span>`
  - the summary regex `1 of 3 paragraphs differ\s*·\s*jump:\s*<a href="#d1-l">1</a>`
- **Glossary:**
  - all ids and `term--STATUS` classes
  - the `<tbody id="term-N"` response
  - `aria-current="page">Needs review`
  - the disabled Build glossary regexes
- **Translate:**
  - the `#estimate` and `#translate-form` contracts
  - `<details class="add-setup" open>`
  - the publish aria-labels
  - the stale link and its prefill
- **Check section:** every string (test_web.py:309-318), i.e. `<summary>Held: 1</summary>`, the poison line, the reclean and align commands, and "No problems found."
- `<table class="sources-table">` with `data-label` on every body `td`.
- **Comparisons:**
  - `class="attempt attempt--ok"`
  - `<details class="judgement"`
  - `<th scope="row">vendor/cheap</th>`
  - `<td data-label="vendor/`
- `Model comparisons</a> <span class="muted">none yet` (test_web_comparisons.py:36) and "2 runs" (:46). The header link keeps that exact form.
- On the novel page: "Glossary</a>" and "no entries yet" (test_web_glossary.py:14), and "1 accepted" (:26). The header link is `…>Glossary</a> <span class="muted">…</span>`.

**Changed deliberately** (each edit goes in the same commit as its markup change)
- `test_web.py:235-242`: the half that checks the `library` table becomes a card contract. Every `li.novel-card` has `data-novel`, the title link, and, for a novel that can sync, the Sync form. The `sources-table` half stays.
- `test_web.py:61`: the exact badge span becomes a regex that tolerates the badge classes, `class="[^"]*out--missing[^"]*" title="site: not built">site not built<`.
- `test_web.py:62`: the exact sources `li` becomes a regex. It keeps `title="https://novelbuddy.me/test-novel"` and the visible `novelbuddy.me` and `official-en`.
- `test_web.py:126`: the `disabled title="Sync is queued (job N)"` regex is loosened to allow `class` on either side of `disabled`. It still requires the title and "Sync".
- `test_web_glossary.py:107`: `"Glossary</a>" not in page` becomes `'href="/novels/english-only/glossary"' not in page`. The old form would pass even if the link wrongly appeared.
- Any other exact string that breaks is loosened only to tolerate added attributes, never to drop the fact it asserts.

### 7.2 New cases
TestClient (`test_web.py` unless named otherwise; fixture novels: `raw-novel`, `english-only` and `test-novel` via `added()`):

| Id | Setup | Action | Expected |
|---|---|---|---|
| T1 shell | `novels` | GET `/` | `id="nav-novels"` with `data-novel="raw-novel"` and `id="nav-raw-novel"`; no `/site-assets/` link; `ui.css` then `app.css`; `hx-select-oob="#nav-novels"` on `#main`; `#notice` comes before `<main` |
| T2 sidebar-fallback | `service.library` monkeypatched to raise, with a counter proving it was called | GET `/add` | 200, and the sidebar lists `raw-novel` |
| T3 stats | `novels` + `added()` (3 novels; expected values computed from each row's own fields in the test, worked out by hand for the fixture) | GET `/` | the Novels stat is 3 with the raw-only hint count; Chapters = sum of `selected`; New = sum of `new_items` over rows that can sync |
| T4 pill-running | a running job on `raw-novel`, `set_progress(id, 2, 7, "")` | GET `/` | pill label "1 running"; `.pill-progress` has `value="2" max="7"`; the card's `[data-job-progress=raw-novel]` is not hidden |
| T5 pill-problem | 1 done-with-errors job in attention + 1 failed job in Recent (the failed one superseded by a later clean run of the same kind and target) | GET `/` | pill label "1 problem" |
| T6 tabs-markup | `raw-novel` with a setup | GET the novel | 4 `[data-panel]` sections, ids `sources chapters translate check`; tab links `href="#…"` with `data-tab-link`; no `role="tablist"`; the Check tab count equals `NovelCheck.problems` |
| T7 tabs-english | `english-only` | GET the novel | no `data-panel="translate"` and no Translate tab |
| T8 unpin-redirect | pinned novel | POST unpin without htmx | 303 to `/novels/x?notice=…#sources` |
| T9 toast | a running job on the novel, then htmx POST `/jobs` sync → 409 | | the response has `.toast--destructive`, the message and `toast-close` |
| T10 problems | pages-level | `NovelCheck.problems` on a report with 1 held + 1 numbering run + 4 unchecked | 6 |
| T11 state_counts | blocks with hand-made cells | `state_counts` | the exact dict |
| T12 vendor | | GET `lucide.svg`, both woff2 files and `OFL.txt` | 200; the woff2 files come back as `font/woff2` |
| T13 icons-exist | | read every template, collect the `icon("…")` names | each one has a `<symbol id="…">` in `lucide.svg` |

Browser (`test_web_browser.py`, marker `browser`; desktop cases use `firefox(size=(1280, 900))`):

| Id | Slice | Setup | Action | Expected |
|---|---|---|---|---|
| W1 drawer (updated) | 2 | running job, phone | as today | as today, plus the pill label "1 running" |
| W2 recent | 2 | unchanged | | |
| W3 compare-jump (tightened) | 2 | D2 | jump; reload through `sse:active` | the top of `#d1-l` is ≥ the top bar's bottom and < innerHeight, before and after |
| W4 desktop-sheet | 2 | 1280; a done-with-errors job | load `/` | `aside.jobs` hidden; the pill reads "1 problem" and still reads it after the first `jobs` swap (parity); clicking the pill opens the sheet; Escape closes it and focus is on `.jobs-toggle` |
| W5 card-progress | 4 | job claimed and started on `raw-novel` before load, 1280 | `set_progress(id, 2, 7, "")` (no `active` event) | the `[data-job-progress=raw-novel]` text includes "2/7" without a reload; the pill's progress value is 2 |
| W6 tab-load | 5 | `raw-novel` with problems | goto `/novels/raw-novel#check` | only `#check` visible; the Check link has `aria-current="true"`; the tab bar is in the viewport |
| W7 tab-reload | 5 | `raw-novel` | goto `#check`, set `#main.dataset.before`, start a job on another novel | once `dataset.before` is gone, Check is still the only visible panel and has `aria-current` |
| W8 tab-link-twice | 5 | estimate showing a "blocked" `#check` link | click the Check tab, then Chapters, then the `#check` link, then Chapters, then the `#check` link again | Check is active after each `#check` click |
| W9 no-sideways | 4–6 | phone | library, novel (each tab), compare, glossary, add, comparison chapter | `scrollWidth <= innerWidth` on each |
| W10 toast | 3 | phone; `english-only` claimed through the board **before** load (its Sync button is disabled, so the form can't trigger the 409) | start a job on another novel through its form; within 6 s, `page.js("htmx.ajax('POST','/jobs',{target:'#notice',values:{kind:'sync',novel:'english-only'}})")` | the success toast appears; the 409 error replaces it and is still there after 8 s (the old timer was cancelled); a separate success toast is gone after 7 s |
| W11 nojs | 2 and 5 | spike first: `javascript.enabled=false` via `prefs` | load `/novels/raw-novel` at 1280 and at phone width, and a `wide` page at 1280 | sidebar links visible; all four panels visible; jobs panel inline |
| W12 assets | 1 | 1280 | load `/`, await `document.fonts.ready` | a FontFace with family `Geist` has `status === 'loaded'`; `svg.icon use` has `getBBox().width > 0` |
| W13 shots | 7 | phone + 1280 | library, novel (each tab), glossary with terms, compare with a note/system block, comparisons, comparison chapter, add, error | full-page PNGs saved for G3 |

- Every browser test ends with `assert_no_errors()` except W11.
- **W11 spike (start of slice 2):** check that BiDi `script.evaluate` and the preload still run with `javascript.enabled=false`.
  - If they do, W11 runs as written, using a fixture without `assert_no_errors`.
  - If not, W11 loads the pages normally, removes `js` from `<html>`, closes any open sheet, and asserts the same visibility. That proves the CSS gating, which is the real risk. Record which variant was used in §10.
- **W13:** add `origin: "document"` to the BiDi `captureScreenshot` call in `tools/firefox_page.py` (a `full_page` flag on `Page.screenshot`).

### 7.3 Commands
- Default suite: `uv run --no-sync pytest packages/novel-app`. CI runs `uv run pytest`.
- Browser suite: `uv run --no-sync pytest -m browser packages/novel-app`.
- Use `--no-sync` while the user's `nov serve` holds `nov.exe`.

## 8. Implementation slices
Each slice is test-first at the seams above. It is committed when the default suite and the browser suite are green.

0. **Vendor (G1):** fonts, sprite and licences; per-file licences in the README; the woff2 MIME type; T12 and T13.
1. **Design system and base:**
   - `ui.css`, `_ui.html`, the prose scope; `base.html` drops `/site-assets`, and the mount is removed.
   - Pages restyle through the base element styles; every existing test still passes.
   - The compare fixture gains a note block and a system block.
   - W12.
2. **Shell:**
   - async `page()`/`refused()` with `nav_rows` and its fallback (T1, T2)
   - top bar and breadcrumbs
   - sidebar with inline/sheet behaviour, and jobs sheet under `html.js`
   - pill server text and `sync()` (T4 pill part, T5, W1, W4)
   - `hx-select-oob`
   - W3 tightened
   - W11 spike + sidebar/jobs part
3. **Toast:** `_notice.html`, `#notice` placement and dismissal (T9, W10).
4. **Library:** stats and cards (T3, T4 card part, card contract, W5, W9 part).
5. **Novel:**
   - header, stats, tabs plus the head script, panels, meters
   - `NovelCheck.problems` and `state_counts`
   - tests: T6, T7, T8, T10, T11, W6, W7, W8, W11 panel part, the header contracts of §7.1
6. **Glossary, compare, comparisons, add and error restyle:** the existing tests, W9 rest, and the `test_web_glossary.py:107` change.
7. **Gates:**
   - W13 screenshots, with the `tools/firefox_page.py` full-page flag.
   - G2 timing and G3 user review.
   - Token tuning.
   - Notes in §10.

## 9. Review findings and resolutions

### 9.1 r1 (baseline review)
1. **Card progress would freeze**, because `#main` only reloads on `active`. Fixed with the `app.js` mirror (§4.3); tested by W5.
2. **Hash tabs had four broken transitions:** the scroll jump on load, a flash on reload, the same link clicked twice, and scope/fallbacks.
   - Fixed: state on `<html>` set before paint, delegated link clicks, scoping and fallback, and `id="chapters"` (§5.2).
   - Tested by W6–W8.
3. **A jobs sheet at every width would hide jobs without JS.** Fixed: the sheet is gated on `html.js` (§4.1); tested by W11.
4. **Toast vs `#notice`.** Fixed: a non-dialog sheet with the toast above it, and dismissal rules (§4.4); tested by T9 and W10.
5. **Dropping the site `style.css` would unstyle compare text, and editing that file costs a full site rebuild.**
   - The app now owns `.prose`.
   - `novel_publish/static/style.css` is not edited, not even its stale comment, and the mount is removed.
   - Tested by W13 with the note/system fixture.
6. **The sticky top bar would hide jump targets and fight the wide reading table.** Fixed with `scroll-margin` and `dvh` sizing (§4.1, §5.4); tested by W3 tightened.
7. **The sidebar would go stale, the error page could crash, and the cost was unmeasured.** Fixed with `hx-select-oob`, the slug fallback and G2; tested by T1 and T2.

The review's business questions were decided under the delegation as D5 and D8 (default tab), D6 (stale counting) and D7 (pill instead of a docked panel). The server-rendered pill and closing menus on an outside click or Escape were adopted. Keeping typed Translate inputs and open chapter `<details>` across a reload was deferred; that is existing behaviour.

### 9.2 r2 (review of draft r1)
The review confirmed: htmx `hx-select-oob` semantics, the head script not re-running on a reload, the partial contexts, and the cited lines. Necessary findings and how each was handled:

| # | Finding | Resolution |
|---|---|---|
| N1 | Without JS, the sidebar couldn't be opened on phones or wide pages | Sheet only under `html.js`; inline otherwise (§4.1). W11 covers phone and wide. |
| N2 | W11 relies on evaluate/preload running with JS off, which is untested | Spike at the start of slice 2, with a defined fallback variant (§7.2). |
| N3 | W5 targeted a non-novel, sat in the wrong slice, and its sidebar half proved nothing | Uses `raw-novel`, moved to slice 4. The sidebar mirror was dropped, since OOB already refreshes it (§4.3). |
| N4 | W7 tested the default tab | Now on `#check`. |
| N5 | The server and JS counted problems differently | One rule (§4.3); parity checked in W4, and T5 includes a failed job in Recent. |
| N6 | §7.1 missed the Glossary/Comparisons header contracts; glossary :107 could pass vacuously | Listed and kept; :107 rewritten. |
| N7 | `library()` ran on the event loop | Async `page()` with `run_in_threadpool` (§4.2). |
| N8 | `role=tablist` without tab semantics | Dropped; `aria-current` on the active link instead. |
| N9 | W12 passed even with broken fonts and icons | FontFace status, `getBBox`, and T13 symbol existence. |
| N10 | Toast: no-JS placement, toasts from plain-POST forms never faded, timer race | `#notice` placed before `main`; timer also started at load; timer cancelled on each swap; W10 covers the race. |

Optional findings adopted:
- **O1:** slice order fixed (W3 in slice 2, W12 in slice 1).
- **O2:** dropped `data-done`/`data-total`, the `.nav-toggle` `aria-expanded` restore, and the sidebar mirror.
- **O3:** sticky offsets on the reading table.
- **O4:** T3 setup made explicit.
- **O5:** `.table-wrap > table` instead of a class on the table.
- **O6:** woff2 MIME type and `crossorigin`.
- **O7:** full-page screenshots.
- **O8:** sidebar link ids, with sheet state on `nav#sidebar`.
- **O9:** G2's fallback specified below.
- **O11:** stakeholder wording.

### 9.3 Focused follow-up (r2 changes)
- **Confirmed:** async `page()` at every call site, including both exception handlers; the server and JS rules for "problems" select the same set; `afterSwap` targets the new `#main`; T5, T9 and W11 can be built from the existing fixtures; every slice can be green on its own.
- **Fixed:**
  - W10 could not provoke a 409 through the disabled form. It now claims `english-only` before load and fires the 409 with `htmx.ajax`.
  - The fallback rows are typed `NavRow(slug, title)`, not plain strings.
  - `set_progress` gets its `current` argument.
  - `/` reuses its own rows for `nav_rows`.
- **Verdict:** ready to proceed under gates G1–G3.

## 10. Gates
- **G1, vendoring:**
  - Fonts and sprite come from the official releases, with hashes and licences recorded.
  - The fonts total about 150 KB or less, or a subset is chosen.
  - T12, T13 and W12 pass.
- **G2, cost:**
  - On the real library, with a sync running on one novel, time `GET /` and `GET /novels/<syncing novel>`.
  - These are read-only curl calls against the user's server. It must first be restarted on the new code, which needs the user's OK.
  - Pass: median under 300 ms, and the SSE stream keeps ticking (`jobs` events about 1 s apart) during the timing.
  - Fallback if it fails: the sidebar reads each novel's title from its store metadata once per process, cached by slug (a small new Service read), and drops the stale dot; the library page keeps it.
- **G3, look:** the user reviews the W13 screenshots (phone and desktop) and either approves or asks for token or layout changes before the work counts as done.

## 11. Not included
- A light theme or theme toggle.
- Covers, author, tags or any other new Service data.
- Sync history or spend charts.
- Changes to the job log page.
- Keeping form input across live reloads.
- Any change to the reader site or its `style.css`, including its now-stale comment that the app loads it. Fix that comment the next time the site changes for another reason.

## 12. Definition of done
- Slices 0–6 merged, with the default suite and `-m browser` green locally and CI green.
- G1–G3 passed, with notes recorded here.
- `docs/plans/app-ui-*.md` marked as implemented.
