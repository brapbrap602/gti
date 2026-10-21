# Backlog

Known gaps to come back to. Newest first; each item says what's wrong, why it matters and where to start.

## nov sync can't fetch only some chapters (2026-10-20)

`nov sync <novel>` fetches every chapter the book lacks from every web source; there is no chapter range and no per-source choice. A new raw source means fetching the whole novel even when a few chapters are wanted, e.g. 5 chapters for a model comparison on Beyond the Timescape meant fetching all 1,363.

Wanted: `nov sync <novel> [numbers] [--source N]` (and the same on the web job), fetching only those chapter numbers from that source. Start in `novel_sources/sync.py` (`sync`, `to_fetch`) and the `sync` op in `novel_app/service.py`.

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
