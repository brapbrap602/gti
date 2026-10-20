# Reader site and app UI: plan summary

Status: approved 2026-10-20. Not built yet. Details: [developer plan](reader-ui-developer.md).

## Goal

The goal is to make the public reader site comfortable to read on a phone, and to make the local `nov serve` app easier to use, including on a narrow screen.

## Reading on the site

- **Opening a range:** the page starts straight with the chapter text. The chapter list no longer sits above it.
- **Scrolling down:** you see only the text.
- **Scrolling up:** a slim bar slides in. It shows the current chapter with ‹ and › to step between chapters, crossing into the previous or next 50-chapter page when needed, plus **Chapters**, **Aa** and **Library**.
- **Chapters:** lists this page's chapters. It also offers "Go to chapter #" for any chapter, and links to the previous and next pages.
- **Aa:** text size (5 steps) and theme (dark, light or follow the phone). Dark stays the default.
- **Library:** each novel card has
  - **Continue · Ch N**, which reopens the exact paragraph you last read
  - a "Go to chapter" box
  - the full chapter range list behind "All chapters"

Your place and settings are saved in each browser and phone separately; nothing is sent anywhere. "Continue" follows where you actually read. Glancing at an old chapter or jumping somewhere doesn't overwrite it, but reading there for a while does.

## Using the app (`nov serve`)

- **Jobs panel:**
  - Running jobs and problems stay visible. A problem is a job that failed, was interrupted, or finished with some failed items.
  - A problem clears itself once the same job runs again cleanly.
  - Everything else folds into "Recent".
  - On a phone the panel is a "Jobs" drawer with a running indicator.
- **Tables on phones:** the library and source tables stack into readable cards. Statuses show as short badges, and sources show as a site name instead of a long file path.
- **Compare:** shows whether two versions are identical or how many paragraphs differ. Changed words are highlighted, and you can jump from one difference to the next.

## What you'll need to do

- Review screenshots of the finished site and app (phone and desktop) before anything goes live.
- Confirm the deploy. Because the page design changes, every page is rebuilt and the whole site (about 230 MB) is pushed once.
- Optionally run the browser tests before a deploy. They run on your machine, not in CI.

## Not included

- Translation and glossary work, which is paused.
- One-chapter-per-page layout.
- Syncing your reading position between devices.
- Audio on the site.
- Fixing which Longevity text is published for 1003–1779. Today it's the old machine translation, because the official chapters there were never fetched; that's a separate data task.

## Verification

- Automated tests cover the site's pages, chapter map and links, the jobs panel rules, the source labels and the compare highlighting.
- Firefox browser tests cover scrolling, the bar, resume, settings, the drawer and compare jumps.
- After a rebuild of the real library, screenshots are checked at phone and desktop width.
