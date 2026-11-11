# nov serve library, Sync all and compare: plan summary

Status: approved 2026-11-11. Not built yet. Details: [developer plan](app-library-developer.md).

## Goal

The goal is to make the nov serve library something you can scan in one screen. Novels that need you should come first. A single button should bring every novel up to date without hammering the source sites. Comparing two sources for a chapter should be easy to read and easy to step through.

## Library

- **A table by default:** one line per novel showing chapters, gaps, new chapters to fetch, last sync and the state of site, EPUB and audio, with Sync, Build and Open on the right. Running jobs show their progress in the row.
- **Cards are still there:** a Table/Cards switch keeps today's cards, and the app remembers your choice.
- **What needs you comes first:**
  1. running jobs
  2. novels with an unresolved problem in the jobs panel (failed, interrupted or finished with errors); a novel drops back once you dismiss the problem
  3. novels that need a rebuild
  4. novels with new chapters to fetch
  5. novels with gaps
  6. everything else, by title

  Click a column heading to sort by it instead. The app remembers that too.
- **The tiles at the top are clickable:**
  - "New to fetch" shows exactly those novels, through a new tab.
  - "Needs rebuild" shows the novels it counted.
  - "Jobs" opens the jobs panel.
- **The sidebar lists novels by title.**

## Sync all

- **"Sync all"** sits next to "Build site". It queues a sync for every novel that has a web source, and the batch fetches **one novel at a time**.
  - Novels already syncing are skipped.
  - Each novel still has its own line in the jobs panel. Cancelling a queued one takes effect immediately, so you can sync that novel on its own straight away. Re-running one doesn't touch the rest.
  - Queued novels show as "queued", not "running". They don't jump to the top of the library, and the counts read e.g. "1 running · 29 queued".
  - If you stop nov serve mid-batch, the syncs that hadn't started are quietly cancelled, not flagged as problems. Run Sync all again to pick up where it left off; novels already synced have nothing new.
- **A Sync click or Re-run on a single novel still starts at once**, even while a batch runs, so it may fetch alongside the batch.
- **Audio waits for fresh chapters:** an audio build for a novel that is being synced, or is queued to sync, waits until that sync ends.
  - The jobs panel shows "waiting for sync".
  - Other novels' audio builds carry on.
  - This includes `nov build audio` in the terminal, which waits and says so. Ctrl-C stops it.

## Comparing two sources

- The source pickers and ← → stay at the top while you scroll.
- ← → keep the two sources you picked, and → stops at the last chapter.
- When both sources are English, paragraphs line up side by side, with a blank where one source has text the other lacks.
- Chinese against English stays as two separate columns.

## Not included

- phone layouts (the app stays desktop-only)
- changes to what a sync fetches
- per-novel `nov check` counts in the table
- a single "cancel all queued syncs" button (cancel them one by one)

## How it will be checked

- Automated tests cover ordering, filters, the sync queue and audio waiting (including the terminal), and compare alignment.
- Firefox tests check the Build menu, the sticky bar and live progress.
- A speed check confirms the library still loads in under 300 ms during Sync all.
- You'll see screenshots of the app running on a copy of your data. The agent never runs a real Sync all; you do.
