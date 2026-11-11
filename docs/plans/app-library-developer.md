# nov serve library, Sync all and compare: developer plan

Status: approved 2026-11-11. Built 2026-11-11, slices 1-7 (local, not pushed). G1 and G2' passed; the W5 screenshots await the user's review (§10). Summary for the requester: [stakeholder plan](app-library-stakeholder.md).
Source: the Firefox UI review of 2026-11-11 (app items 2-4).
- App item 1 ("done with errors") shipped in `79f9188`.
- The small items (page titles, error page for a bad query, inline code size) shipped in `f7a50a4`.

Builds on [app-ui-developer.md](app-ui-developer.md). Its constraints stand: desktop only, dark only, hand-written CSS in `ui.css`/`app.css`, explanations owned by `_help.html`, every form working without JS, the HTMX/SSE patterns, and the kept contracts of §7.1 except where §4.1 here lists a deliberate change.

## 1. Decisions

### 1.1 Approved (user, 2026-11-11)

| # | Decision |
|---|---|
| A1 | **Library table by default.** One row per novel with: title (raw-only and off-site badges), chapters, gaps, new to fetch, last sync, outputs (site, EPUB and audio badges), actions Sync / Build▾ / Open, and live job progress. A remembered Table/Cards switch keeps today's cards. |
| A2 | **Attention-first order:** running → has an unresolved problem → needs rebuild → new to fetch > 0 → gaps > 0 → the rest; ties by title. Clicking a column header sorts by that column instead. The choice is kept in `?sort=`, remembered, and works without JS. |
| A3 | **Sidebar order:** by title instead of slug. |
| A4 | **Stat tiles are links:** Novels → All; New to fetch → a new "New to fetch" tab; Needs rebuild → its tab; Jobs → opens the jobs panel; Chapters stays plain. Tabs may overlap. |
| A5 | **Sync all** next to Build site queues a sync for every novel with a web source, skipping novels already syncing. The batch runs **one sync at a time**, and each novel keeps its own job row, cancel and re-run. |
| A6 | **A single Sync click or a Re-run starts at once, as today.** It runs alongside a batch if one is running. |
| A7 | **Every audio build of novel X waits while X has a sync queued or running**, then runs. Other novels' audio builds are not held. This applies to builds started from the terminal too (`nov build audio X` waits and says so; Ctrl-C ends it as interrupted). |
| A8 | **"Has an unresolved problem"** means a job of any kind for that novel is listed as a problem in the jobs panel: failed, interrupted, or done with errors. It clears on Dismiss, on "Clear N problems", or when the same job later succeeds. |
| A9 | **Compare page:** a compact sticky bar holds the source pickers and prev/next. Prev/next keep the requested left/right sources, and next hides after the last chapter. When both sides are English, paragraphs line up in rows, with blank cells where one side has extra paragraphs. English against Chinese keeps two columns. |
| A11 | **A queued job is not "running".** Only a job in state RUNNING puts a novel in rank 0, the Running tab and the running counts. A novel whose job is only queued ranks by its other state, and its row says "queued". The Jobs tile and the pill read "1 running · 29 queued". |
| A12 | **Queued jobs that never started end CANCELLED when nov serve stops**, whether it stops cleanly or is killed hard. They are not problems. The job that was running ends INTERRUPTED, as today. Sync all can simply be run again. |
| A10 | **Out of scope:** phone layouts, changes to what a sync does, per-novel `nov check` problem counts in the table, and a "Cancel all queued syncs" button. |

### 1.2 Engineering defaults (decided in planning)

- **Sort and view are remembered in cookies** (`lib_sort`, `lib_view`). A cookie is written whenever `?sort=`/`?view=` is present and read when it is absent. This survives the SSE reload of `#main` and the no-JS POST → 303 back to `/`, with no flash and no JS needed.
  - Rejected: localStorage plus a redirect. It needs JS and flashes the default order first.
- **One natural direction per column, no direction toggle:**

  | Column | Order |
  |---|---|
  | title | A→Z |
  | chapters | most first |
  | gaps | most first |
  | new | most first |
  | last sync | most recent first, never-synced last |
  | outputs | most stale items first |

  `sort=attention` returns to the default.
- **Only the chosen view is rendered on the server.** Rendering both would duplicate every form and progress mirror.
- **Tabs keep the `?status=` parameter.** Existing values keep their meaning, and `new` is added. Unknown values still show all.

## 2. Verified baseline (2026-11-11)

- **Route and rows.**
  - `GET /` (`web/app.py:161-168`) calls `service.library()`. That returns one `LibraryRow` per slug, in `novel_slugs()` order, which is slug order (`library.py:54-59`, `service.py:552-554`).
  - The rows are cached per DB stamp (`service.py:588-604`).
  - Each row costs `last_ended(build-epub)` and `last_ended(sync)`.
  - `page()` adds `jobs()` (limit 20) and `job_panel()` (`app.py:119-126`).
- **`LibraryRow`** (`pages.py:104-142`) has slug, title, sources, numbers, selected, gaps, new_items, last_sync, outputs, jobs, epub_size and public.
  - Derived: `raw_only`, `can_sync`, `needs_rebuild`, and `status` (RUNNING > REBUILD > RAW_ONLY > OK, `pages.py:136-152`).
  - `LIBRARY_STATUSES` drives both the library tabs and the sidebar chips (`library.html:31-36`, `base.html:47`).
- **The "Needs rebuild" tile and tab disagree.** The tile counts `needs_rebuild` (`library.html:28`). The tab filters `status == REBUILD`, which RUNNING overrides.
- **Stat tiles** come from the `stat` macro (`_ui.html:12-20`), a `div` with no link.
- **The Build site busy check** uses `jobs` (limit 20, `library.html:12`).
- **Job queue.**
  - `JobRunner` has one serial queue, `ThreadPoolExecutor(max_workers=1)` (`jobs.py:344,356-357`). Only `build-audio` uses it (`service.py:173`).
  - A queued job claims its lock at submit and is heartbeated while queued (`jobs.py:355,400-404,434-442`). Cancel is checked only before start (`jobs.py:409-411`).
  - No board query asks "is (target, kind) held". `last_ended` returns DONE jobs only (`jobs.py:304-311`).
  - Dead locks are reclaimed after `STALE_AFTER` = 60 s (`jobs.py:30,239-254`).
- **CLI sync.** `nov sync --all` selects novels with web sources (`cli.py:169`) and runs them in sequence.
- **Compare.**
  - `/novels/{novel}/compare` (`app.py:175-178`) → `pages.comparison()` (`pages.py:431-466`).
    - When a requested side has no text for that number, it silently falls back to a default (`:441-444`).
    - `Part.body` is one pre-joined `Markup` per part (`:405-410,495`).
  - `TextDiff` (`diff.py:43-51`) has per-side marks and gaps. The block pairing (opcodes, `:81-97`) is discarded.
  - Prev/next (`compare.html:15-18`) drop left/right, and next is unbounded.
  - Jump targets' `scroll-margin-top` allows for the topbar only (`app.css:473`).
- **Menus.** `.table-wrap` has `overflow-x: auto` (`ui.css:252-257`), which clips the absolutely positioned `.menu-items` (`ui.css:312-331`).

## 3. Design

### 3.1 Library model (owner: `pages.py`)

- **Filters.** `LIBRARY_FILTERS: dict[str, Filter]` maps a name to `(label, predicate over LibraryRow)`:

  | Name | Predicate |
  |---|---|
  | `running` | has a job in state RUNNING (A11) |
  | `rebuild` | `needs_rebuild` |
  | `new` | `can_sync and new_items > 0` |
  | `raw-only` | `raw_only` |
  | `ok` | `status is OK` |

  The names are the existing tab values (`running`, `rebuild`, `raw-only`, `ok`, `pages.py:150`), plus `new`.
- **What counts as running.** `LibraryRow.status` becomes RUNNING only for a RUNNING job (A11). A row has `queued: bool` for "only queued jobs".
  - The sidebar dots follow `status`. A novel that is only queued therefore shows its other status (for example "up to date", green), and only its table row says "queued". This is accepted.
  - `row.jobs`, `job_of`, the buttons, mirrors and the Build site busy check keep using all active jobs (QUEUED + RUNNING).
- **Running and queued counts.** One label rule, used by the server's first paint (`base.html:73,76`), `app.js` (`:53-65`) and the Jobs tile (`library.html:22`): a zero part is left out.
  - Examples: "1 running", "3 queued", "1 running · 29 queued".
  - `jobs-toggle--running` stays on for any active job.
  - `app.js` counts with separate `li.job--running` and `li.job--queued` selectors. Its `active` array, which feeds the mirrors and the pill progress, stays as it is.
  - The kept `"1 running"` assertions (`test_web.py:481`, `test_web_browser.py:108`) still hold.
- **Live reload when a job starts.** The SSE `active` event (`web/app.py:423-426`) is keyed on `(id, state)` instead of id alone, so `#main` also reloads when a queued job starts. Otherwise a started job would stay out of rank 0 and the Running tab until it ended. This doubles reloads during Sync all (one at start, one at end), and G2' measures it. Tiles and tabs count with the same predicates. `NovelStatus` and `LIBRARY_STATUSES` stay for the sidebar dots and chips only.
- **Attention rank.** `attention(row, problem_targets: frozenset[str]) -> int`:
  - 0 a RUNNING job (queued doesn't count, A11)
  - 1 `row.slug in problem_targets`
  - 2 needs rebuild
  - 3 new > 0
  - 4 gaps > 0
  - 5 the rest
- **Ordering.** `LIBRARY_SORTS: dict[str, key]` holds `attention`, `title`, `chapters`, `gaps`, `new`, `sync` and `outputs`. Every key ends in `title.casefold()`, then slug, for a total, stable order. `sort_rows(rows, sort, problem_targets) -> list[LibraryRow]` is pure, and an unknown name means attention.

### 3.2 Library route and templates

- **Route.**
  1. `GET /` resolves `sort` and `view` from the query, then the cookie, then the default. It computes `panel = service.job_panel()` **once**, with `problem_targets = {j.target for j in panel.problem_jobs}`.
  2. It sorts the rows, filters them with `?status=`, and passes `job_panel=panel` to `page()`, so the panel isn't queried twice.
  3. It sets cookies only when the query carried the parameter.
- **Build site busy state.** Both views and the Build site button read active jobs from `panel.active`, which has no limit, instead of `jobs` (limit 20).
- **Table** (`_library_table.html`):
  - `<table class="library-table">`, **not** inside `.table-wrap`. The app is desktop-only at 1280px or wider.
  - `<th>` cells are sort links (`/?sort=x`, keeping `status`) with `aria-sort` on the active one.
  - Rows are `<tr class="novel-row" data-novel="slug">`. The cells are:
    - the title link (`title` attribute = full title), then the badges, then `job_progress(r.jobs)` (the existing macro, so `app.js` mirroring keeps working)
    - chapters ("N" plus the per-kind counts in a `title` tooltip)
    - gaps (`.stale` when > 0)
    - new, or "—" with the no-web-source tooltip
    - last sync, through `ago`
    - `output_badge` × 3
    - actions: the `job_button` Sync, `build_menu` with `menu--end`, and Open
  - Every term's explanation comes from `_help.html`.
- **Cards.** Today's markup is moved unchanged into `_library_cards.html`.
- **Header controls.** A segmented Table/Cards link pair (`?view=`) sits in the page header beside Build site, Sync all and Add novel.
- **Tiles.** The `stat` macro gains an optional `href`. With one, it renders `<a class="stat stat--link" href=… title=…>` with the same inner markup.
  - The Jobs tile links to `#jobs` and carries `data-open-jobs`. `app.js` opens the sheet and returns focus to the tile on close. It does not use the `jobs-toggle` class, because `sync()` rewrites that class.
- **Sidebar.** `nav_rows` sorts `NavRow`s by `title.casefold()` itself, so it doesn't depend on the route's order.

### 3.3 Job lanes and waiting (owner: `jobs.py` mechanism, `service.py` policy)

- **Interface change.** `JobRunner.submit(target, kind, args, work, lane: str | None = None, waits_for: str | None = None)` replaces `serial: bool`.
  - `lane=None` means a thread of its own, as today.
  - A named lane is a FIFO with one worker thread. Lanes are created on first use, and there are two: `"sync"` and `"audio"`.
  - `waits_for="sync"` means the lane skips over this job while `board.held(target, "sync")`.
- **Policy, in one table** in `service.py`, replacing `SERIAL_KINDS`:

  | Kind | Lane | Waits for |
  |---|---|---|
  | `build-audio` | `audio` | `sync` |
  | `sync` from Sync all | `sync` | — |
  | `sync` from a click or Re-run | none (own thread, A6) | — |

  No kind waits for audio, so waiting cannot form a cycle.
- **Lane worker.** The worker loops:
  1. Under the lane's `Condition`, take the **first ready job**.
  2. If none is ready, mark each waiting job once with `set_progress(id, 0, 0, "waiting for sync")`, then `wait(timeout=2.0)`. Readiness can change in another process, so the board is polled.
  3. `submit` and `cancel` call `notify()`.
- **Cancelling a queued job takes effect at once.**
  - One helper serves both `cancel()` and `shutdown()`. Under the lane's `Condition` it removes the job from the lane, then removes it from `_active`. **Outside** the Condition it appends "cancelled" to the job's log and calls `board.finish(id, CANCELLED)`, which releases the lock. `owns()` is then False, and a second `cancel()` returns False.
  - A cancelled queued sync can be started again by a click straight away, and its novel's audio build stops waiting. This works even while the lane's worker is busy with another job.
  - **Race:** if the worker popped the job first, cancel falls back to setting `_cancel`, and `_execute` ends the job CANCELLED before it starts (`jobs.py:409-411`). A running job is cancelled cooperatively, as today.
  - `cancel()` returns which case happened (`removed` or `signalled`). The cancel route says "job N cancelled" or "job N will stop after its current item" (`app.py:367`).
- **Readiness checks don't hold the lane's lock.** The worker copies the queue under the Condition, checks `held()` (a database read) outside it, then pops under the Condition only if the job is still there. A slow SQLite read therefore never blocks `submit`/`cancel`.
- **`board.start` clears `current`**, so "waiting for sync" doesn't outlive the wait.
- **`JobBoard.held(target, kind) -> bool`.** A lock row exists and its heartbeat is newer than `stale_after`.
  - A sync queued in the app's sync lane already holds its lock (claimed at submit), so audio X waits for **queued** syncs too.
  - A CLI `nov sync X` holds the same lock, so it counts as well.
- **CLI.** `JobRunner.run(..., waits_for=…)` claims the job (QUEUED; duplicates are refused). The wait runs **inside `_execute`'s `try`, before `board.start`**, so the existing `except KeyboardInterrupt`/`finally` (`jobs.py:418-431`) ends it INTERRUPTED and releases the lock on Ctrl-C.
  - While waiting, it echoes "waiting for sync of X…" once and calls `set_progress(…, "waiting for sync")`, so the app's panel shows it too.
  - It polls with an injectable `sleep` (default `time.sleep(2)`). An untimed lock or `Condition` wait would not respond to Ctrl-C on Windows.
  - `nov build audio` passes the kind's `waits_for` from the same policy table.
- **Shutdown.** `shutdown()` finishes every queued lane job as CANCELLED at once (A12), cancels running jobs cooperatively, notifies each lane's condition, and joins the lane workers. This replaces `self._serial.shutdown`.
- **Hard kill (A12).** The rule lives in `JobBoard._interrupt` (`jobs.py:256-261`): `state = CASE state WHEN 'queued' THEN 'cancelled' ELSE 'interrupted' END`. Both callers therefore apply it: `reconcile` (`:253`) and a stale-lock takeover in `claim` (`:196-198`).
  - It covers queued jobs in both lanes and a CLI build killed hard while waiting.
  - Ctrl-C on a waiting CLI build still ends it INTERRUPTED (a problem), because it is handled in `_execute`. That is deliberate: you stopped it.
  - After a hard kill mid-batch, the cancelled syncs fill "Recent". They are not problems.
- **Lane by kind, and Re-run.** `start(kind, …)` puts only `build-audio` in a lane. `sync_all` calls `_prepare` and then `runner.submit(..., lane="sync")` itself, with args unchanged. A Re-run of a Sync-all job therefore replays `start("sync", …)` and starts at once (A6).
- **Waiting jobs and `owns`.** A waiting job is in `_active` from its claim, so `owns` is True and Cancel shows. A CLI-waiting job shows "running in another process" (`_jobs.html:22-28`), as for any CLI job.
- **Known race (accepted).** A sync of X that starts after audio X has started does not pause the audio. This is today's behaviour.
- **Jobs panel.** `_jobs.html` shows `current` for queued jobs even when `total` is 0, so "waiting for sync" is visible there. The library row and card mirrors (`app.js:80-86`) show "Build audio queued". They copy `.job-progress` only when there is a `<progress>`, and that is unchanged.

### 3.4 Sync all

- **`Service.syncable_novels(source: str | None = None) -> list[str]`** is the selection `cli.py:169` uses today, including its `--source` filter. The CLI switches to it.
- **`Service.sync_all() -> SyncAll(queued: tuple[int, ...], skipped: tuple[tuple[str, str], ...])`.** For each syncable novel it submits `sync` on lane `"sync"`. A `JobRunning` is recorded as (slug, "already syncing"), and a `UserError` as (slug, its message).
- **Route.** `POST /jobs/sync-all` (fields: `back`) uses the same no-JS and HTMX handling as `POST /jobs`. The notice reads "Queued 7 syncs (one at a time); skipped 2 already syncing", or "Nothing to sync" when nothing was queued.
- **Button.** "Sync all" (refresh icon) sits beside Build site. Its tooltip comes from `_help.html`.

### 3.5 Compare (owners: `diff.py`, `pages.py`, `compare.html`)

- **Pairing.** `TextDiff.pairs: tuple[tuple[int | None, int | None], ...]` is built in `diff_blocks` from the opcodes:
  - `equal` pairs 1:1
  - `replace` pairs the first `min(len)` blocks 1:1, then the rest against `None`
  - `insert`/`delete` pair against `None`
- **Rows.** `Comparison` gains `rows: tuple[Row, ...] | None`, present only when `diff` is not None (both sides non-raw).
  - `Row(left: Cell | None, right: Cell | None)` holds either a block cell (`html`, `block index`) or a heading cell.
  - A heading row is emitted wherever either side starts a part; the other side's cell is blank unless it also starts a part.
  - A `diff-gap` span (`id="dN-l"`/`dN-r`) goes in the **first** blank cell of a group, but only for groups listed in `left_gaps`/`right_gaps`. The blank cells of an unequal replace (2 against 3) get no id, so ids stay unique (kept test `test_web.py:355-364`).
  - The two-column `Part` rendering stays for the raw case.
- **Bounds and requested sources.**
  - `Comparison` gains `last: int` (the highest number any source has text for; computed during the existing walk, `pages.py:434-437`).
  - The route passes the **requested** `left`/`right` to the template. Prev/next, the pin form's `back`, and the bar build their links from those, not from the resolved sides.
  - Next is shown only if `number < last`.
  - Prev goes to `min(number - 1, last)` when `number > last`.
- **Sticky bar.** The window scrolls, not `#main` (`app.css:22-34,97-103`; `.glossary-bulk` at `app.css:418-427` is a working sticky precedent).
  - `div.compare-bar` is a **direct child of `main#main`**, with `position: sticky; top: var(--topbar-h)`, a solid background, and a z-index below the topbar (20) and menus (30).
  - It has a fixed, non-wrapping height, declared as a static `--compare-bar-h` token in `app.css`.
  - It holds the two selects, Show, and ← N−1 / N+1 →.
  - In the empty state ("No source has a text for chapter N") there are no offers, so it shows prev/next only.
  - Jump targets get `scroll-margin-top: calc(var(--topbar-h) + var(--compare-bar-h) + 1rem)`.
- **Aligned layout.**
  - A header row holds the two source headers (name, kind badge, pin form or "Used by the book").
  - It is followed by `div.compare-rows`, a CSS grid with two equal columns. Each row is `div.compare-row` with two `div.compare-cell` children, inside the existing `.compare-text` class so the mark styles still apply.
  - Blank cells are styled as gaps.

## 4. Tests

### 4.1 Seams, fixtures and deliberate contract changes

- **Pure functions:** `pages.sort_rows`, `attention`, and `LIBRARY_FILTERS` over hand-made `LibraryRow`s. `diff.diff_blocks(...).pairs`.
- **Board and runner:** `JobBoard` on a tmp `app.sqlite`, with a second `JobBoard` on the same file standing in for the CLI, and `JobRunner`. Synchronise with `threading.Event`s, never sleeps; the lane poll interval is injectable for tests.
- **Web:** `TestClient(create_app(service))`, where cookies persist within a test. Existing helpers: `added`, `two_texts`, `novels`.
- **Browser:** `test_web_browser.py` `desktop` (1280×900), Firefox only.
- **Deliberate contract changes**, recorded here as required by app-ui §7.1:
  - `test_web.py:305-319`: the card contract becomes a table-row contract: `<tr class="novel-row" data-novel=`, a title link, and the Sync form. The old assertions are kept under `?view=cards`.
  - `test_web.py:76`: the stat markup becomes `<a class="stat stat--link"` for linked tiles. Chapters keeps `<div class="stat"`.
  - `test_web.py:483`: the job mirror is asserted inside the table row.
  - `test_web.py:318-335` (`card_slugs` in `test_library_filters_novels_by_status`) switches to a row-slug helper. Its tab hrefs at :330 (`/?status=…`) are unchanged, because sort travels by cookie.
  - `test_web_browser.py:139-159` (app-ui W3, jump in view): its topbar check is tightened to the compare bar (W2 here). Its "still in view after an `sse:active` reload" half is kept.
- More deliberate contract changes:
  - `test_jobs.py:77-84` (a stale **never-started** job taken over → INTERRUPTED) now expects CANCELLED (A12). A started variant keeps INTERRUPTED.
  - `test_web.py:213-219` (startup reconcile + Re-run) gains `dead.start(job_id)`, so it still tests INTERRUPTED and Re-run.
  - `test_jobs.py:57-74` changes `serial=True` to `lane="audio"`.
- **Accepted limit.** Row job mirrors come from `jobs(limit=50)` (`service.py:553`), so a novel's job could be missing from its row only with more than 50 active jobs.

### 4.2 Case matrix

| ID | Layer | Setup | Action | Expected |
|---|---|---|---|---|
| L1 rank | unit | rows: running "Zed"; problem "Yak"; rebuild "Xu"; new "Wo"; gaps "Vee"; plain "Ant", "Bee" | `sort_rows(…, "attention", {"yak"})` | Zed, Yak, Xu, Wo, Vee, Ant, Bee |
| L1b rank-overlap | unit | running + rebuild on one row | same | ranked running |
| L1c queued | unit | "Abe" whose only job is QUEUED and needs rebuild; "Cat" plain | attention | Abe at rank 2 (rebuild), not 0; the `running` filter excludes Abe; `Abe.queued` True |
| L2 columns | unit | 3 rows with distinct chapters/gaps/new/last_sync (one None) | each sort | the stated direction; None last for `sync`; ties by title |
| L2b unknown | unit | — | `sort_rows(…, "bogus")` | same as attention |
| L3 filters | unit | rows covering each predicate; one both rebuild and new | each filter | rebuild and new both include the overlap row; `running` excludes non-running rebuild rows |
| L4 tile=tab | web | 2 rows need rebuild, one of them running | GET / | the Needs rebuild tile says 2; `/?status=rebuild` lists 2 rows |
| L5 table | web | `added` novel | GET / | `<tr class="novel-row" data-novel="test-novel">` with title link, "3", Sync form, 3 output badges; no `novel-card` |
| L6 cards | web | — | GET `/?view=cards`; then GET / | cards on both (cookie); `Set-Cookie: lib_view=cards` on the first only |
| L7 sort-cookie | web | 2 novels whose attention order differs from title order ("Ant" with no new chapters; "Zed" with new chapters) | GET `/?sort=title`; GET `/?status=ok` | second response is title-sorted (Ant first); tab hrefs still `/?status=…` |
| L7b counts | web | one RUNNING sync, two QUEUED | GET / | pill and Jobs tile read "1 running · 2 queued"; the Running tab lists 1 row |
| L8 problem-rank | web | novel B's sync FAILED (board); A plain | GET / | B first; after POST dismiss, A first (title order) |
| L9 tiles | web | — | GET / | New to fetch tile `href="/?status=new"`, Needs rebuild `href="/?status=rebuild"`, Novels `href="/"`, Jobs `href="#jobs"`; Chapters is a `div` |
| L10 sidebar | web | slugs `a-zed` "Zed" (5 new), `b-ant` "Ant" (0 new) | GET / with `?sort=new` | table Zed, Ant; sidebar Ant, Zed |
| L11 busy | web | an active build-site job, then 21 newer active jobs (queued syncs claimed on the board) | GET / | Build site shows running (read from `panel.active`, not `jobs()` limit 20) |
| J1 lane-fifo | runner | sync lane; submit S1, S2 (blocking work) | release S1 | S2 starts only after S1 ends |
| J2 overtake | runner | sync X claimed (held); audio X then audio Y queued | — | Y runs while X waits; X's `current` = "waiting for sync" |
| J3 release | runner | J2 | end sync X | audio X starts |
| J4 cli-held | runner | lock `(x, sync)` claimed via a second `JobBoard` on the same file | submit audio X | waits; after that board finishes the job, X runs |
| J5 cancel-waiting | runner | J2 | `cancel(audio X)` | X ends CANCELLED promptly; sync X unaffected |
| J5b cancel-queued-busy | runner + web | sync lane running S1 (blocked on an Event); S2 for novel B queued | `cancel(S2)`; then POST /jobs sync B | S2 CANCELLED at once and B's lock released while S1 still runs; the new sync of B starts RUNNING |
| J6 shutdown | runner | sync lane: S1 running, S2 and S3 queued; audio X waiting | `shutdown()` | returns; S2, S3 and X CANCELLED; S1 ends INTERRUPTED or CANCELLED as today; lane threads gone; none of S2, S3, X in `panel().problem_jobs` |
| J6b hard-kill | board | QUEUED job and RUNNING job with stale heartbeats (injected clock) | `reconcile()`; separately, `claim` over each stale lock | QUEUED → CANCELLED; RUNNING → INTERRUPTED, on both paths |
| J5c cancel-owns | runner | J5b after the cancel | `owns(S2)`; `cancel(S2)` again; GET the cancel route's notice | False; False; "job S2 cancelled"; S2's log ends with "cancelled" |
| J10 sse-start | web | claim a job; start it; finish it | read `job_events` | an `active` event after each of the three steps |
| J7 stale-lock | runner | sync lock with a heartbeat older than `stale_after` | submit audio X | runs (not held) |
| J8 cli-wait | cli | sync X held via the board | `nov build audio X` in a thread; then end the sync | prints "waiting for sync of X" once; the board row's `current` is "waiting for sync"; then builds |
| J8b cli-ctrl-c | runner | sync X held; injected `sleep` raises KeyboardInterrupt | `run(build-audio X, waits_for="sync")` | KeyboardInterrupt re-raised; job INTERRUPTED; X's audio lock released (a new claim succeeds) |
| J9 click-sync | web | Sync all batch running (lane busy) | POST /jobs sync for another novel; Re-run an ended Sync-all job of a third novel | both RUNNING at once while the lane's next job is QUEUED |
| S1 sync-all | web | 3 novels: 2 web, 1 epub-only; one web novel already syncing | POST /jobs/sync-all | 1 queued; notice "Queued 1 sync…; skipped 1 already syncing"; epub-only not mentioned as an error |
| S2 sync-all-nojs | web | — | POST without HX | 303 to `back` with the notice |
| S3 waiting-shown | web | J2 state | GET / | jobs panel shows audio X "queued · waiting for sync" |
| C1 pairs | unit | equal; insert in the middle; delete; 2-vs-3 replace | `diff_blocks().pairs` | exact tuples, e.g. replace → (0,0),(1,1),(None,2) |
| C2 rows | web | two English texts with an inserted paragraph | GET compare | one `compare-row` per pair; the insert row has a blank left cell holding `id="d1-l"`; ids unique; existing mark/summary regexes pass |
| C3 parts | web | left in 2 parts, right in 1 | GET compare | heading rows for left's parts with right blank; "Chapter 1 pt N" twice per side where present |
| C4 raw | web | raw vs English | GET compare | two `compare-side` columns, "Raw text: no diff", no `compare-row` |
| C5 keep-sources | web | a new fixture with five sources (`two_texts` makes only 1 and 2); sources 3 and 5 requested; chapter 120 lacks 3 | GET `?number=120&left=3&right=5` | page falls back to show something; next/prev hrefs carry `left=3&right=5`; pin `back` too |
| C6 last | web | chapters 1-3 | GET `?number=3` | no next link; `?number=2` has next |
| C7 empty-bar | web | number with no text | GET | bar with prev/next present |
| W1 menu | browser | 6 novels | open Build▾ on the last table row | `elementFromPoint` at the Audio "to" field's centre returns that field |
| W2 sticky-jump | browser | C2 with a long text | click jump 1; trigger `sse:active` | `#d1-l` top ≥ `.compare-bar` bottom, before and after the reload; bar still on screen after scrolling 3 viewports (tightens app-ui W3) |
| W3 tile-jobs | browser | — | click the Jobs tile; Esc | sheet opens; focus returns to the tile |
| W4 row-progress | browser | sync running | — | the row's progress updates without a reload (`test_web_browser.py:267` adapted to the row) |
| G2' perf | walkthrough | Sync all running over the real library copy | 20 × GET / | median < 300 ms |

### 4.3 Walkthroughs (agent-run, results shown to the user)

- **W5.** `nov serve` against a **copy** of the data folder, so nothing is fetched from the real sites. Sync work is faked with the test site fixture. Screenshots at 1280 and 1440 of:
  - the library table, sorted by attention and by title
  - the cards view
  - a filter tab
  - the jobs panel with a waiting audio build
  - compare (English pair aligned; raw pair; empty chapter)
- **Real Sync all.** Never run by the agent; the user starts it (the no-paid-runs rule covers fetch load too).

## 5. Gates

- **G1 (slice 4):** the lane and CLI polls are reliable. Accepted when J1-J8b pass in 3 of 3 runs. Their effect on `GET /` latency is measured by G2' in slice 7.
- **G2' (slice 7):** `GET /` median < 300 ms with a Sync-all batch running (the app-ui G2 threshold). Every sync that ends fires an `active` event, which reloads `/`.

## 6. Code-design notes

- **Ranking, sorting and filters are pure functions in `pages.py`**, testable without HTTP. The route only resolves parameters. Rejected: sorting in the template (no seam for tests).
- **Mechanism versus policy for jobs.** `JobRunner` knows lanes and `waits_for` but no kinds. `service.py` owns which kind uses which lane and what it waits for, in one table. Rejected:
  - one shared queue for sync and audio (it deadlocks, review F1)
  - waiting inside `_build_audio` (the job would show "running" and block the lane)
- **Locks as the cross-process truth for "syncing".** `held()` reads what the CLI and the app already write. No new state.
- **The diff owns the pairing.** pages.py arranges the pairs into rows and the template only lays them out. Rejected: re-pairing blocks in the template.

## 7. Slices (each: failing test → code → green → commit)

1. `pages`: filters, the queued/running split, attention, sorts (L1-L3, L1c). Sidebar by title (L10).
2. Route and table/cards templates, cookies, tiles, counts, busy check (L4-L9, L7b, L11; contract changes in §4.1).
3. `JobBoard.held`, `_interrupt` for never-started jobs, lanes, `waits_for`, immediate cancel of queued jobs, shutdown, panel "waiting" text, SSE keyed on state (J1-J7, J5b, J5c, J6b, J10, S3).
4. CLI waiting and Ctrl-C (J8, J8b). Gate G1.
5. Sync all: `syncable_novels`, `sync_all`, route, button, help (S1, S2, J9).
6. Compare: `pairs`, rows, `last`, requested sources, sticky bar (C1-C7).
7. Browser: W1-W4. G2'. W5 screenshots. Update app-ui-developer.md §7.1 with the changed contracts.

## 8. Definition of done

- All non-browser tests and `lint-imports` pass in CI. Browser tests pass locally (Firefox).
- G1 and G2' have passed. W5 screenshots have been reviewed by the user.

## 9. Review log

- **R1 (independent review of the baseline and approach, 2026-11-11).** Folded in:
  - **F1:** the single serial queue deadlocks or holds other novels; fixed with lanes and readiness (§3.3).
  - **F2:** the tile and tab disagree; fixed with library-only filters (§3.1).
  - **F3:** Build▾ clipped; fixed by not using a `table-wrap` and using `menu--end` (W1).
  - **F4:** jump targets under the sticky bar; fixed with the scroll margin and the tightened W2.
  - **F5:** requested sources lost at gaps, and `last` (§3.5).
  - **F6:** `pairs` and the heading-row rule (§3.5).
  - **F7:** rank from the panel's problems, panel computed once (§3.2).
  - **F8:** contract changes listed (§4.1).
  - Plus: cookies, a dedicated Sync all route, the sidebar sorted in `nav_rows`, Jobs tile focus, and the limit-20 busy check.

  Business questions resolved as A6, A7 (terminal waits) and A8.
- **R2 (fresh review of draft v1, 2026-11-11).** Folded in:
  - **High:**
    - queued counted as running, resolved by the user as A11 (L1c, L7b)
    - cancelling a queued lane job did nothing until the lane reached it (immediate removal, J5b)
  - **Medium:**
    - CLI Ctrl-C while waiting: the wait moved inside `_execute`, plus an injectable sleep (J8b)
    - missed contract `test_web.py:318-335` and the `raw-only` filter name
    - L11 couldn't fail (reseeded)
    - queued jobs on stop or kill, resolved by the user as A12 (J6, J6b)
    - the lane for a Re-run of a Sync-all job (J9)
  - **Low:**
    - `syncable_novels(source)`
    - L7 and L10 reseeded
    - sticky-bar placement and static height
    - gap ids only for `left_gaps`/`right_gaps` groups
    - prev past `last`
    - C5 fixture
    - gate order
    - mirror wording
    - `board.start` clears `current`
    - stakeholder wording on site load

  Verdict after the fixes: ready with gates G1 and G2'.
- **R3 (focused review of the sections changed by A11/A12, 2026-11-11).** Folded in:
  - **High:** SSE didn't reload when a queued job started (keyed on `(id, state)`, J10).
  - **Medium:**
    - A12 placed in `_interrupt` so the takeover path applies it too, with the kept tests adjusted
    - one pill/tile label rule across server, JS and the tile
  - **Low:**
    - immediate cancel also leaves `_active`, logs "cancelled", and reports which case happened (J5c)
    - readiness checked outside the Condition
    - `serial=` test updated
    - A11/A12 consequences stated (a queued novel's sidebar dot; Ctrl-C versus hard kill)

  Verdict: the changed sections are ready.

## 10. Build notes (2026-11-11)

- **Gates.**
  - **G1 passed.** The lane, waiting and CLI tests (25 of them, including J1-J8b) passed in 3 of 3 runs.
  - **G2' passed.** The setup:
    - a copy of the real library (25 novels, databases only) with every source faked, so a sync's index fetch blocks and nothing is fetched
    - Sync all queued 21 syncs: 1 running, 20 queued
    - 20 calls of `GET /` over uvicorn

    The result: median 104 ms (max 151 ms), against 97 ms idle.
- **W5.** Screenshots at 1280 and 1440 were taken on the same copy, with an audio build waiting for its novel's queued sync. They cover:
  - the table sorted by attention and by title
  - the cards view
  - the New to fetch tab
  - the jobs panel showing "queued · waiting for sync"
  - compare: an English pair, a raw pair, and a chapter past the end
- **Deviations and details.**
  - **Short output badges.** The table shows `site 3` (the kind, plus a stale count). The tooltip and colour carry the rest, so rows stay one line. On the real library at 1280px, long counts made the table about 90px too wide; the badges now wrap there.
  - **Filter counts.** The route computes the filter counts (`filter_counts`), so a tab and its tile share one predicate. Jinja's `select` cannot take a callable.
  - **Returning to attention order.** A "Needs a look first" link sits in the actions header. It shows only when another order is active. Sorted headers show an arrow.
  - **The `stat` macro** takes `href` and `attrs`. `attrs` is used for `data-open-jobs`.
  - **The policy table in `service.py`** is `TURNS: {kind: Turn(lane, waits_for)}`, plus `SYNC_ALL = Turn("sync")`. `JobRunner.submit` refuses `waits_for` without a lane.
  - **Cancel** returns `CancelResult.REMOVED` or `CancelResult.SIGNALLED`, or None.
  - **Compare.** The aligned rows are `AlignedRow(left, right)` of `AlignedCell(kind, html)`, where kind is block, heading or blank. ← 0 still shows on chapter 1, as before: chapter 0 can exist.
  - **Test fixture.** `conftest.Site` gained `hold`, an Event that chapter fetches wait on. J9 uses it to keep a Sync-all sync running.
