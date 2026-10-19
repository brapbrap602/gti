# Novel platform: one repo, one library

Status: **APPROVED r3 (2026-10-18)**. Details are in [developer-plan.md](novel-platform-developer.md).

## What you get
All your novel tooling lives in one place, the **gti** repo. Every novel is kept in one local library, whether it came from an English site, a Chinese raw site, or your old downloads. The reading site, EPUBs and audiobooks are all generated from that library. You no longer go through Calibre, hand-split HTML, or tune per-novel parsing settings.

## How you'll use it
1. **Add a novel** by pasting its URL, in the web UI or with `nov add`. You can attach several sources to one novel, for example an English site plus a Chinese raw site.
2. **Sync** whenever new chapters come out. Only new chapters are downloaded. Every version of a chapter is kept.
3. **Choose versions.** Each novel has a source order, for example "official English first, then my translation". You can pin a different source for a range of chapters. Chinese raws are never published.
4. **Build** the site, EPUB or audio. Only the parts that changed are rebuilt.
5. **Deploy** the site to GitHub Pages with one command.
6. The **web UI** shows every novel's chapters and gaps, runs syncs and builds with live progress, and lets you compare two versions of a chapter side by side.

## Your existing data
- Imported once: the web-novel-scraper downloads, MtlTings raws and translations, the scribblehub Longevity chapters, and the current site's HTML (as a last-resort fallback).
- Your finished chapter MP3s are kept and never regenerated. For Beyond the Timescape and Cultivation Chat Group, the old folder numbers are list positions, so they are mapped to the real chapter numbers.
- Split chapters such as "524 part 1/part 2" stay as separate entries.
- Old site links stop working, and chapter labels become correct.

## Things you must do yourself
- **Before anything else:**
  - Detach MtlTings from the gti remote. Its history is unrelated to gti, so a force-push from it would replace your live site and publish a key.
  - Commit (or let us snapshot) the uncommitted Barbarian work in github_pages.
- **Rotate the OpenRouter and Google API keys.** After that, keys only come from environment variables.
- Confirm the GitHub Pages switch to the `gh-pages` branch when asked.
- MtlTings stays on disk as an archive.
- If you later fix a chapter-number mapping, the chapter text moves with it, and the next build rebuilds affected pages and removes outdated ones. Old audio is never regenerated automatically, even if a better source appears later. It is flagged for you to check, and you can force a regeneration.

## Not included
AI translation and glossaries (a separate later project), scheduled automatic syncing, editing chapter text in the UI, private hosting, and cleaning old git history.

## How we'll know it works
Automated tests use real page structures with the text scrubbed. Before the switchover, the new site is compared against the current one. Legacy audio mappings are spot-checked by ear. The live site URL is checked after the deploy.
