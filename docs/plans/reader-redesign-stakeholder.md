# Reader redesign: plan summary

Status: approved 2026-11-11. Built 2026-11-11 (not pushed or deployed yet). Details: [developer plan](reader-redesign-developer.md).

## Goal

The goal is to make the public reading site quicker to get back into and more comfortable to read. The library should open on what you're reading. The site should show only novels you can actually read. Titles and authors should look right, and the text should be adjustable to taste.

## What changes for a reader

- **Library**
  - **Continue reading** sits at the top, listing every novel you've started in this browser, most recent first, with the chapter and when you read it. One tap resumes. **×** forgets a novel's place, and **Undo** brings it back for a few seconds afterwards.
  - Below it, **All novels** is a compact list sorted by title. Tap a novel to open its "Go to chapter" box and chapter ranges.
  - A first-time visitor just sees the list.
- **End of a page:** a big "Next: Chs 51–87 →" button, naming the chapters actually there, with "← previous" and "Library" under it. On a novel's last page it says you're caught up and names the latest chapter.
- **Aa (text settings):**
  - a sepia theme next to light and dark
  - a Sans or Serif font
  - three line-spacing steps
  - three line widths, offered on screens wider than a phone
  - Everything is still saved in each browser separately, and nothing is sent anywhere.
- **Chapters:** on a phone it slides up from the bottom and fills most of the screen, so you see many chapters at once. On a computer it's a taller panel.

## What changes for you (the site owner)

- **Novels with nothing to read are left off the site.** That means Chinese-only novels and novels with no chapters yet. Each appears by itself at the next build after its first chapter is published. `nov public <novel> off` still hides any novel by hand.
- **Fixing titles and authors:** `nov meta <novel> --title "…" --author "…"`, or "Edit title and author" on the novel's page in nov serve. Web addresses never change.
  - Change a title and that novel's pages and EPUB rebuild at the next build. If it has audio, you'll be reminded to run `nov audio retag`.
  - Placeholder authors such as Calibre's `<unknown>` are treated as "no author". A later sync fills in the real author when the source knows it.
    - Novels that had `<unknown>` will show their EPUB as stale once, and it rebuilds at the next EPUB build.
    - Their MP3 tags update with `nov audio retag`.
    - Audio *volumes* keep an old title until you rebuild them.
  - **Each sync that adds chapters now also rewrites the page before the newest one**, so its "Next" button stays accurate.
  - Titles such as "Beware Of Chicken" are fixed by hand, once.
- **The first deploy after this work republishes the whole site** (about 130 MiB). It goes live only when you say so.

## Not included

- syncing your place between devices
- accounts
- cover images
- search
- any change to page addresses or the 50-chapter pages

## How it will be checked

- Automated tests cover the build, the new command, and the library, settings and chapters panel in Firefox at phone and desktop sizes.
- You'll see screenshots of a full rebuild of your real library (made in a scratch copy) before anything is deployed.
