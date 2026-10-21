# Backlog

Known gaps to come back to. Newest first; each item says what's wrong, why it matters and where to start.

## ixdzs8 raws: 「」 forms wait for a reference; invented sentences unguarded (2026-10-20)

Raw cleaning (`novel_sources/zh_tables.py`) now drops ixdzs8's lone `>`, `」`, `。` and digit lines and maps "————" to "……", and a translator note covers the stray `」` after item names. Two things are left:
- **`「」`, `「————”`, `「...—..」` and `「7`-style openings** are left as they are. Which form they stand for waits for a clean reference to diff with (`nov inspect --against`). Qidian's free chapters (G2) don't help: ixdzs8 only uses `「」` in later chapters, which are locked on Qidian.
- **Invented sentences.** In the comparison on 苟在两界修仙 chapters 101–103, one-at-a-time Luna turned 「」 into "She fell silent." and `>` into "She eyed him knowingly.", and the validator passed both. The `>` lines are gone now; a `「」` line can still do it. A soft check would catch it: the source paragraph has no CJK or letters, but the translation is a sentence (`novel_translate` validation). The raw cleaning plan left it out.

## Qwen's provider rate-limits parallel requests (2026-10-20)

In the 以神通之名 comparison, `qwen/qwen3.8-flash` got HTTP 429 on 2 of 3 chapters at the default 4 workers. `models.py` retries 429 three times (HTTP_RETRIES) and honours Retry-After up to 60 s, and both chapters still failed. A failure from rate-limiting costs nothing but loses the chapter. Options: fewer workers per model when a 429 comes back (back off the pool, not only the request), or more retries for 429 than for 5xx.

## Range sync: not on the web job yet (2026-10-20)

`nov sync <novel> [numbers] [--source N]` now fetches only those chapter numbers (`only` in `NovelView.to_fetch` and `sync`). The web Sync button still fetches everything; it needs a numbers field (`WEB_JOBS["sync"]` in `web/app.py`, and the form).

## Beyond the Timescape: raws and English numbered differently (2026-10-20)

The raw source (biquges123, source 4) and the official English disagree on chapter numbers. At the end, EN = raw − 4 (EN 1354 is the finale, raw 1358). The raw site also skips 698 and 822, and the titles already differ at 300. A comparison works around this with `--reference-shift`. Anything that pairs raws with English by key would pair the wrong chapters: Phase A hints and comparisons without a shift. A full alignment needs a way to match Chinese and English chapters by content, not titles.

## Models with mandatory reasoning get no extra output room (2026-10-20)

Reasoning "off" can't switch reasoning off for models that make it mandatory (e.g. `anthropic/claude-sonnet-5.5`, `openai/gpt-6.1-sol`). Their reasoning tokens still count against `max_tokens`, and the output allowance is only doubled when the setup asks for reasoning. The cut-off retry with 1.5× room covers it for now. Better: double the allowance when the model list says reasoning is mandatory (`phase_b._Run.request`, with the flag from `ModelFactory`).

## Discovery: "name + verb" phrases still become candidates (2026-10-20)

Strings like 李凡沉吟 and 韩萧无奈 (a name plus an everyday verb) pass discovery, and the model has to reject them. A filter for them was tried, but it also dropped organisation names (无限财团, 萌芽组织). It needs a better signal than jieba's part-of-speech tags.

## Several chapters per request: comparisons only (2026-10-20)

A translator setup can send several consecutive chapters in one request (`group`, `nov translate compare --per-call N`). Only comparisons use it so far: `nov translate run` refuses such setups. If a comparison shows grouping translates better, production needs the following:
- an input_key per group;
- the ledger and stored versions per chapter from one shared call;
- staleness for a group whose chapters change separately;
- what a re-run sends when only some chapters of a group are stale.

## Groups pass or fail whole; failed answers aren't kept (2026-10-20)

In a five-chapter request, DeepSeek skipped paragraphs in 4 chapters, so its good chapter was thrown away too. The fix is to keep the chapters that pass the hard checks and resend only the failed ones, alone (`phase_b._Run.group_request` hard checks, and `compare`'s `done`).

Separately, a failed attempt's raw answer is not kept anywhere. "Exceeded maximum output retries" (DeepSeek and Qwen on long chapters and on groups) can't be diagnosed after the fact. Keep the last raw response, or its first and last few kB, with the failure in the comparison bundle.
