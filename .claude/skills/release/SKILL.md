---
name: release
description: Deploy the public reading site to GitHub Pages and push main. Use when the user says "release", "deploy", "deploy to my pages", "publish the site", or "push it live". Covers what gets deployed (the reader site, never the nov serve admin app), the build and deploy commands, why the deploy force-pushes gh-pages, size limits, and which GitHub account to use.
---

# Release

Deploys the **reading site** (static reader pages) to GitHub Pages. The admin app (`nov serve`) runs only locally and is never deployed.

## Steps

Run these from the repo root. Both commands are free: they don't translate or call any paid API.

1. **Check git state:** `git status -sb` and `git log origin/main..main --oneline`. Tell the user if any commits are unpushed, and push them only if they agree (step 4).
2. **Build:** `uv run nov build site`
   - Incremental: it rewrites only stale pages. Add `--force` only when the renderer changed.
   - Output goes to `%LOCALAPPDATA%\novels\_site`. The last line prints the site's total size.
3. **Deploy:** `uv run nov deploy site`, run in the background with a long timeout, because it waits until the Pages URL is live.
   - Success is a line like `pushed gh-pages <sha> (<size>) to https://brapbrap602@github.com/brapbrap602/gti.git` followed by exit 0.
   - It doesn't print a "live" line: `--wait` is the default, so exit 0 means the live check passed.
4. **Push main** (if the user agrees): `git push origin main`. CI (`.github/workflows/ci.yml`) runs on the push.
   - You can't check CI with `gh`, because it's logged in as the wrong account (see below). Ask the user to look at the Actions tab instead.

## Facts users ask about

- **Why force-push?** `nov deploy site` pushes the site as a single orphan commit that replaces `gh-pages` each time. Keeping history would store a full copy of the site on every deploy and grow the repo toward GitHub's limits. Only `gh-pages` is overwritten; `main` is never force-pushed.
- **Size limits:**
  - Pages: the published site can be at most 1 GB, with a soft bandwidth limit of 100 GB/month. The deploy aborts above `--budget-mb 900` by default.
  - Repo: GitHub recommends under 1 GB and strongly recommends under 5 GB. Files over 50 MB get a warning, files over 100 MB are rejected, and one push can be at most 2 GB.
- **Per-novel size:** run `du -sh "$LOCALAPPDATA/novels/_site/novels"/*` in Git Bash.
  - On 2026-11-03 the whole site was 131 MiB; the largest novel, cultivation-chat-group, was 36 MB.
  - Raw-only novels add nothing. Audio MP3s are what would fill the 1 GB limit.
  - Removing a novel shrinks both the site and the repo, because old orphan commits become unreachable.
  - There's no command that leaves a whole novel out of the site. `nov publish` switches individual sources in or out.

## Account rule

- Only use the **brapbrap602** account. Git pushes already use `https://brapbrap602@github.com/...` credentials.
- Never run `gh` against this repo, not even reads: it's logged in as xeare.
- Ask the user to make GitHub settings changes (such as Pages settings) in their browser.
