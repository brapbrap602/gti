# Backlog

Known gaps to come back to. Newest first; each item says what's wrong, why it matters and where to start.

## Web raws of recent VIP chapters are poisoned (2026-10-20)

Pirate raw sites serve corrupted text for chapters still behind Qidian's paywall, and sync stores it as if it were fine:
- **Decoy text.** biquge5 gives a few real paragraphs, then random sentences from other novels. It did this for every chapter of 以神通之名 that was tried (400, 600, 694–696), so the source is useless. biquge345 did the same on 苟在两界修仙.
- **Antonym and name swaps.** ixdzs8's newest chapters (691–693) read clean at first, then drift: 好→坏, 快→慢, 不→是, 没有→有没, 后→前, and other characters' names put in place of the protagonist's. Its older chapters (300–685) are clean.

A model translates both faithfully, so the damage only shows up as nonsense English. Wanted: a check at sync time that flags such chapters, as a hard warning in `nov check` and in the sync report. Markers that separated clean from poisoned on ixdzs8 were 有没 (0–2 per clean chapter, 14–21 per poisoned one), 是止, 最坏 and 然前. Decoy text needs another signal: names the novel never uses, or the chapter's own names dropping out after a few paragraphs. Start in `novel_sources/sync.py` after `store_chapters`, or in `novel_core/check.py`.

## ixdzs8 raws carry formatting noise (2026-10-20)

On 苟在两界修仙, ixdzs8's text needs normalising before translation:
- every chapter ends with a lone `>` paragraph, and a closing `」` sometimes stands as a paragraph of its own;
- "……" comes through as "————";
- a stray `」` follows item names whose opening `「` is missing (大破障丹」, 琼华枝」).

Each of these is a paragraph or mark the model has to carry through, or one the validator may count as missing. Start in the zh clean rules (`novel_sources/clean.py`): drop paragraphs with no CJK or letters, and map "————" to "……" for zh.

The comparison on chapters 101–103 showed the cost:
- most of DeepSeek's and Qwen's failures on short chapters, and Luna's one id failure, were likely these paragraphs;
- one-at-a-time Luna **invented** sentences for two of them: 「」 became "She fell silent." and `>` became "She eyed him knowingly."

The validator passed both. A soft check would catch it: the source paragraph has no CJK or letters, but the translation is a sentence (`novel_translate` validation).

## Raw sources number the same chapter differently (2026-10-20)

For 以神通之名, ixdzs8's printed numbers run 2 ahead of biquge5's and Qidian's at chapter 300, and 3 ahead near 690. Keys come from printed numbers, so two raw sources put different chapters under one key, and priority silently picks between different texts. `nov align` can shift a source, but only by a fixed offset. The same need as Beyond the Timescape's: match chapters across sources by title or content, not by printed number.

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
