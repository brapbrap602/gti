---
name: investigate
description: Find out why the library looks wrong and fix what is data rather than code. Use when the user pastes `nov check` output (gaps, unmapped, duplicates, held, failed), says a novel is missing chapters, a sync is slow or stuck, or asks "why does X show Y" about a novel in the library. Covers reading the novel and app databases safely while nov serve runs, telling unfetched chapters from misnumbered ones, reading job logs, timing fetches to find where a slowdown lives, and which fixes are a `nov` command versus a plan.
---

# Investigate a library problem

The goal is a cause backed by evidence, then the smallest fix. A report full of numbers is usually one cause seen many times. Find that one cause before touching anything.

## Ground rules

- Run the CLI as `uv run --no-sync nov …`. The user's `nov serve` holds the venv's `nov.exe` open.
- In Git Bash, `export MSYS_NO_PATHCONV=1` before passing item refs. Refs start with `/`, and without it Git Bash rewrites `/fiction/...` to `C:/Program Files/Git/fiction/...`.
- Assume `nov serve` is running, with jobs writing. Check before changing anything (see Jobs below).
- Read databases **read-only through sqlite3**, never through `NovelStore.open`:
  `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. `NovelStore.open` hung for minutes while a sync was writing.
- Set `PYTHONIOENCODING=utf-8`. Titles contain characters cp1252 cannot print, and the script dies halfway through.
- No paid runs: never translate or build glossaries to "test" something.
- Fetching a handful of public pages to time them is fine. Never hammer a site that is already throttling us.

## Where things live

- Novel: `%LOCALAPPDATA%\novels\<slug>\novel.sqlite`. Tables `source` (with `alignment_json`: offset, ranges, explicit `items` keys, `skip`), `source_item` (index rows: `printed_number`, `part`, `status` ok/pending/failed, `vanished`) and `version` (stored text; a ref with no version has not been fetched).
- Jobs: `%LOCALAPPDATA%\novels\app.sqlite`. Table `job` holds target, kind, state, done/total and errors; table `lock` holds target, job_id, pid and heartbeat. Logs are in `%LOCALAPPDATA%\novels\_jobs\<id>.log`, one timestamped line per chapter as it starts.
- Scraper memory comes in **two places**. Our own fetchers use `%LOCALAPPDATA%\novels\_fetch\origins.json`. The lncrawl backend uses lncrawl's process-wide scraper, `%APPDATA%\LNCrawl\scraper\origins.json`. Each holds a per-origin profile: `interval` (learned mean seconds between requests), `failures`, `binding_layer` (8 = behavioural, i.e. rate limited) and `clearance`.
- Meaning of each check field: `packages/novel-core/src/novel_core/check.py`. A gap is "a number inside the book's range with nothing publishable". It does **not** say that nothing maps there.

## Method

1. **Re-run the check yourself.** `uv run --no-sync nov check <slug>`. Pasted output may be old; a running sync changes it minute to minute.
2. **Classify before explaining.** For every reported number, ask which source items map to it and whether they have text. Build the key map from `alignment_json.items` plus printed numbers, join it with `version`, and count the patterns, e.g. `[(source 2, not fetched)]: 312`. A single dominant pattern is the cause. Typical outcomes:
   - mapped but not fetched → a sync problem (not run, interrupted, slow, failing), not alignment;
   - nothing maps there → numbering or alignment (see the `load-novel` skill, `nov align range|item`), or the sources really lack it;
   - mapped twice → duplicates (`nov align skip` the repost).
3. **Look at the jobs.** Find the novel's jobs in `app.sqlite` and read their logs. `interrupted` means nov serve restarted mid-sync. `running` with a fresh lock heartbeat and a live pid (`tasklist //FI "PID eq <pid>"`) means it is still going. Also check which *other* jobs hit the same host at the same time.
4. **If it is slow, find where the time goes.** The log timestamps give seconds per chapter. Compare with:
   - a plain `curl -w "%{http_code} %{time_total}s"` of one chapter URL (is the site itself slow or refusing?);
   - the backend in-process, one or two chapters, with `logging.basicConfig(level=DEBUG)`. `scraper.session GET … proceed` is logged as the request goes out, so a long pause *before* that line is our pacing, not the network.
   Then read the origin's profile `interval`. A profile learns from throttles, persists across runs, and its pacer is shared by every job on that origin in the process.
5. **Fix what is data, with nov commands.** Notices or announcements unmapped → `nov align skip <slug> --source N <refs…>`. Numbering off → `nov align range/item`. Re-run the check to show the effect.
6. **Stop and ask before** killing or restarting `nov serve`, cancelling jobs, or editing a file a live process holds in memory (it will overwrite your edit on its next save). Use AskUserQuestion. A cause in code (fetch pacing, a parser) goes to a plan, not a quick patch.

## Report

Lead with the cause in one sentence. Then give the evidence (the counts, the timings, the profile values), what you changed and its effect on `nov check`, and what is left with the options. Name files with full paths.

## Seen before

- **beware-of-chicken, 2026-11-10.** 387 gaps and 8 unmapped. The gaps were freewebnovel chapters mapped by explicit item keys but not fetched yet. A sync was running at ~30 s per chapter: lncrawl's freewebnovel.com profile had learned a 27 s interval from 5 old throttles. The site answered 1 req/s fine, and three freewebnovel syncs shared that one pacer. The unmapped were Royal Road author notices (preorders, merch, Christmas) → `nov align skip`. The throttling design went to a plan.
