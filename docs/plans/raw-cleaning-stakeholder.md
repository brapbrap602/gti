# Raw cleaning and checks: plan summary

Status: approved 2026-10-21. Not built. Details: [developer plan](raw-cleaning-developer.md).

## Goal

Chinese raws from pirate sites are stored clean. Chapters that are poisoned or decoys never reach a paid translation.

The rules start small and grow with each novel and site you add, and every rule comes with tested examples.

## What goes wrong today
- **Decoy text.** biquge5 and biquge345 serve a few real paragraphs, then sentences from other novels.
- **Poisoned text.** Some sites swap words in their newest chapters (有没 for 没有, 是止 for 不止, other names for the protagonist's). This happens on ixdzs8, and the plan's library scan found it on biquges123 too (Longevity 第651章).
- **Formatting noise.** ixdzs8 adds junk lines (`>`, lone `」`, digits) and writes `————` for `……`. biquges123 inserts disguised website watermarks, sometimes glued to a sentence. The junk lines made translators invent sentences and fail their paragraph checks.
- **Numbering.** Sites number the same chapters 0–3 apart, and the gap jumps back and forth through the book.
- Sync stores all of it without a warning.

## How it will work
1. **Cleaning happens when a chapter is stored.**
   - Rules come in three layers: rules for all Chinese raws, rules per site, and rules per novel.
   - They fix formatting only, and assume the words themselves are genuine.
   - Lone `……` and `——` lines are real prose and are kept.
2. **Checks hold bad chapters.**
   - A chapter is **held** when it is dense in poison markers, or when the novel's main names appear in its opening and then vanish.
   - A held chapter is kept for inspection, but it is never translated.
   - The book uses another raw source's copy of that chapter, and the next sync of another source fetches it.
   - The held site refetches it on every sync, so a chapter the site later cleans up comes back by itself.
3. **Known decoy sites** (biquge5, biquge345) are synced for their chapter list only, never for chapter text.
4. **False alarms.** `nov release <novel> <numbers>` clears a chapter you judge to be fine.
5. **Unchecked chapters are not translated or read by the glossary pass.**
   - Translation, comparisons and the glossary build skip any raw chapter that hasn't been checked with the current rules, and tell you to run `nov reclean`.
   - Your existing chapters therefore can't be translated until the first reclean has run.
   - After any rule change, reclean again. It's free and local.
6. **Notes for the translator.** A site or novel can carry short notes added to the translation instructions, such as "a 」 after an item name is a formatting artifact". Changing them marks the affected translations stale, the same as a glossary change does.
7. **Numbering.**
   - `nov check` compares chapter titles across sources and suggests fixes per range, e.g. "ixdzs8 printed 300–420: −2 to match qidian", with a ready-to-run `nov align range` command.
   - The anchor is Qidian's numbering when the novel has a Qidian source, otherwise your top-priority raw source that isn't a decoy site.
   - Nothing is re-numbered automatically.
8. **When rules change.**
   - `nov check` and the sync report say how many chapters weren't checked with the current rules.
   - `nov reclean <novel>` (or `--all`) re-cleans them from the copies already on disk and reports what changed: rewritten chapters, newly held ones, released ones, and translations now stale.
   - Nothing changes until you run it.
9. **Adding a novel.** The load-novel skill becomes the method:
   1. Fetch a few spread-out chapters, including the newest.
   2. Run `nov inspect` to see junk lines and check scores.
   3. Where possible, compare against a clean copy with `nov inspect --against`, e.g. Qidian's free chapters, to learn what each junk pattern really stands for.
   4. Add a rule with its examples and run the tests. Claude commits only when you ask.
10. **The web app** shows held chapters, numbering suggestions and the unchecked count on the novel page's Check section, and the unchecked count beside each translate estimate. The actions stay in the CLI.

## Your existing data
- No translations exist yet, so the first reclean makes nothing stale.
- It will hold ixdzs8 691–693, Longevity 第651章 and the biquge5 chapters that lose their names (600, 694–696).
- Before the upgrade, every novel's database is backed up.
- The first full reclean is tried on a copy of the library before it is run on the real one.

## Not included
- Automatic re-numbering.
- Keeping the full web pages; only the extracted text is kept.
- A Release button in the web app.
- Repairing poisoned text.
- A translation check for punctuation-only lines.
- A rules file you edit outside the repo.

## Verification
- **Tests** cover:
  - every rule's examples;
  - lines that must not change (`……`, `——`, `××××`);
  - holds, fallbacks and release;
  - reclean;
  - refusing unchecked chapters;
  - translator notes.
- **A local-only test** over your library checks the poison and names thresholds: the known bad chapters are flagged, and no other chapter is.
- **A Qidian trial** checks that the reference comparison works. It is a free fetch.
- **Prompt caching for notes** can only be measured with a paid call, so you would run that. Nothing depends on it.
