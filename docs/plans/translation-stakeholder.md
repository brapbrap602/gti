# Translation pipeline: plan summary

Status: approved 2026-10-20. Not built yet. Details: [developer plan](translation-developer.md).

## Goal

Translate Chinese raw chapters into English yourself, using OpenRouter models, for any novel and any chapter range:
- Longevity 1495–1781, replacing the old MtlTings text.
- CCG past the official translation.
- All of Transcendental Mechanic.

Later, the same tool can re-translate chapters that already have English.

Names stay consistent because every novel has a **glossary** that you control.

## How it works

1. **Build the glossary.** Run "Build glossary" on a novel.
   - It scans every raw chapter for names, places, sects, techniques, realms and items.
   - A cheap model proposes an English name for each one. Where official English exists, it also notes how that text rendered the name, as a hint only.
   - Each chapter also gets a short summary, which later gives the translator the story so far.
2. **Review the names.** The new **Glossary** page in the app shows:
   - the entries that need your decision, because the model disagreed with itself or with the existing English;
   - the suggestions and example sentences for each one.

   You pick, edit, lock or reject entries. You can also add names yourself at any time, before the first build too. Names you add or edit are never overwritten.
3. **Set up a translator.** A translator setup is a model plus a prompt version and a context mode. "Parallel" is fast. "Sequential" also shows the model the end of its previous translated chapter, so it runs one chapter at a time. Each setup appears as its own source, so you can try several and compare them chapter by chapter on the Compare page.
4. **Translate a range.**
   - You see an estimated cost first, and the job stops at a dollar cap. The cap defaults to **$1**; raise it for big runs.
   - Each chapter is sent with only the glossary names it contains, plus recent context.
   - A chapter is **skipped as blocked** if it contains a name still waiting for your review. It's listed, with the name, in the novel page's check section until you resolve it.
   - Every chapter is checked automatically for:
     - Chinese left in the text;
     - looping or repeated passages;
     - missing paragraphs;
     - a chapter cut off midway;
     - a wrong length.

     A failing chapter is retried once. If it still fails, it isn't saved, and it's listed as a problem. Smaller issues, such as a glossary name not used, are saved but flagged.
5. **Publish when you're happy.** A new translator is **never published by itself**, even for novels with no English at all. Turn on **Publish** for a setup, rank or pin it, then build and deploy as today.

## Ongoing

- Glossary editing is expected to continue throughout.
- After you change a name, the app shows which translated chapters used the old name, and you can re-translate just those.
- New names the translator notices go into the glossary as suggestions for the next glossary build. They never hold up a run.
- Every chapter records what it cost, including failed attempts, and the app shows the total per translator.
- Official English keeps syncing. If official chapters appear for a range you've translated, they're downloaded so you can compare them. Whichever source you rank higher is the one published. A new translator ranks last, so newly fetched official text would take over unless you've ranked your translator above it.
- If a raw chapter is renumbered, a translation stored under its old number is flagged as an orphan rather than quietly published. You remove it with one command.
- Prompts may go to any OpenRouter provider, including ones that log data; it's public novel text. Each setup can switch this to "deny".

## What you'll need to do

- Set `OPENROUTER_API_KEY` in the environment you run `nov` / `nov serve` from.
- Review the names that need a decision, and add any you already know.
- Approve the spend for a trial of 20–50 Longevity chapters with 2–3 models. Its results set the default models and the automatic-check thresholds.
- Decide when a translator gets published.
- Big runs are best started from the command line. While a novel is being translated, syncing and building *that* novel wait until the run ends.

## Costs (current list prices, estimates)

- Cheap Chinese-trained models (e.g. DeepSeek V4.1 Flash): well under a cent per chapter, so a few dollars for all of TM.
- Gemini Flash-class models: about $0.02 per chapter.
- The glossary build costs a fraction of a translation run.

## Not included

- Multi-step "critique and rewrite" translation.
- Automatic quality scoring models.
- Automatic re-translation after glossary edits (you start it).
- Scheduled runs.
- Labelling machine-translated chapters on the site.
- OpenRouter's half-price batch mode (possible later for big backfills).
