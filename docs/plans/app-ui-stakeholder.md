# App UI overhaul (`nov serve`): plan summary

Status: approved 2026-10-21. Not built yet. Details: [developer plan](app-ui-developer.md).

## Goal

The goal is a better-looking `nov serve` app that tells you more at a glance. It takes the clean, dark "shadcn" style: neutral greys, cards, clear buttons and badges, and one consistent font and icon set. Everything you can do today still works the same way. The public reader site is not touched, so no site rebuild or redeploy is needed.

## What changes

- **Layout**
  - A sidebar lists the Library, Add novel and every novel, each novel with a small status dot (job running, needs a rebuild, raw only).
  - A slim top bar shows where you are (Library › Longevity › Glossary).
  - A **Jobs** button in the top bar shows "2 running" or "1 problem" with a live progress line. It opens the jobs panel from the right, on any screen size.
  - On a phone, the sidebar slides in from a menu button.
- **Library**
  - Summary cards across the top: number of novels, chapters, new chapters waiting to be fetched, novels that need a rebuild, and running jobs.
  - Each novel is its own card: sources, chapter counts, last sync, output badges (site, EPUB, audio), Sync / Build / Open, and a live progress bar while a job runs.
- **Novel page**
  - A header with the actions, summary cards, then tabs: **Sources**, **Chapters**, **Translate**, **Check**. Each tab shows a count, for example the number of problems on Check.
  - The page opens on Chapters. Links like "blocked → Check" still jump to the right tab.
  - Chapters get a coloured bar showing how much is official, your translation, raw only, failed, locked or missing, for the whole book and for each block of 100.
- **Messages:** "started job…" appears as a small toast in the corner and fades on its own. Errors stay until you close them.
- **Other pages:** the glossary, compare, model comparisons and add-novel pages get the same look (cards, tabs, badges) with the same buttons and fields.

## What stays the same

- Every button, form, page address and job works as it does now. All of it still works with JavaScript turned off; the page just shows every section at once.
- Dark only.

## What you'll need to do

- Review screenshots (phone and desktop) of every page before it's called done, and ask for any colour or layout changes.
- Say OK before your running `nov serve` is restarted on the new code. One quick timing check runs against it while a sync is going.

## Not included

- A light theme.
- Covers, authors or other new information that the app doesn't already have.
- History charts (syncs, spend).
- Any change to the public reader site.

## Verification

- Automated tests cover the new layout, the summary numbers, the jobs button, the tabs and the messages.
- Local Firefox tests check:
  - live progress updates
  - tabs staying put during live reloads
  - jumps not hiding under the top bar
  - no sideways scrolling on a phone
  - the no-JavaScript fallback
- They also take the screenshots for your review.
