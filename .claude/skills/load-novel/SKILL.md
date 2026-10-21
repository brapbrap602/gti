---
name: load-novel
description: Find a good web source for a novel and load it into the user's library (nov add / nov sync), given a link, a title (Chinese or English) or a vague description such as "a top Qidian xianxia with no English". Use when the user wants a novel added, raws found, an English translation checked, or a source replaced. Covers checking what English exists, finding raw sites, spotting poisoned or decoy text, chapter numbering offsets, and fetching only some chapters.
---

# Load a novel into the library

The library is this repo's `nov` CLI. Each novel is a folder in `%LOCALAPPDATA%\novels\<slug>\`. Its `novel.sqlite` holds sources, index items and stored versions. Run the CLI with `uv run --no-sync nov …`, because the user's `nov serve` holds the venv's `nov.exe` open.

Everything here is free: no LLM calls. Never run `nov translate …` or `nov glossary build` as part of loading; those spend money and are the user's call.

## 1. Pin down the novel

- **A link:**
  - a raw site (Chinese) → go to step 3;
  - an English site (novelbin, freewebnovel, novelbuddy, Wuxiaworld, …) → it may be an `official-en` source, so `nov add <url>` with the default `--lang en`;
  - Qidian / NovelUpdates → use it to get the Chinese title and author.
- **A title or description:** find the Chinese title and author first. Qidian rankings (月票榜, 畅销榜, 新书榜) are rarely fetchable directly. WebSearch for dated third-party snapshots ("起点 月票榜 2026"), and cross-check with novelbrief.com and sina/sohu round-ups.
- **The library already has it?** Check the novel folders and each `novel.sqlite`'s `source` table before adding anything.

## 2. Check what English exists (when it matters)

The user often wants novels with no English, or needs to know which English to trust.
- NovelUpdates returns 403 to WebFetch. Use WebSearch with the Chinese title + "novelupdates", the pinyin, and likely English titles. A NovelUpdates page exists for most popular titles even when it only lists an MTL or a small fan translation.
- Also check Webnovel (official Qidian English), Wuxiaworld (licensed), WTR-LAB (machine translation) and MangaUpdates (shows license status).
- Report it as: **official / licensed**, **fan (partial)**, **MTL only**, or **nothing found**. A fully untranslated top-100 Qidian novel is rare; MTL sites cover them all.
- Many library novels go by MTL English names (Transcendental Mechanic = 超神机械师 = *The Legendary Mechanic*). Identify the Chinese original before claiming "no English".

## 3. Find a raw (Chinese) source

The library fetches through **novel-downloader**, which supports ~100 sites, plus the custom `biquges123` plugin (`novel_sources/noveldl_sites.py`). Search all of them at once:

```bash
uv run --no-sync python -X utf8 -c "
import asyncio
from novel_downloader.plugins.search import search
for x in asyncio.run(search('以神通之名', timeout=20, per_site_limit=3)):
    if '神通' in x.get('title',''):
        print(x['site'], x['book_id'], x['title'], x.get('author'), x.get('latest_chapter'))"
```

- Many sites fail to answer the search; that's normal noise.
- Prefer sites whose `latest_chapter` matches Qidian's newest.
- Build the book URL from the site's pattern in `.venv/Lib/site-packages/novel_downloader/infra/book_url_resolver.py` (`register_extractor`); e.g. biquge5 is `https://www.biquge5.com/<id>/` and ixdzs8 is `https://ixdzs8.com/read/<id>/`.
- biquges123 has its own search (`/search?keyword=`), but it often returns unrelated lists.

What sites have done so far (update this list as you learn more, and put what can be fixed into rules, step 5):

| site | verdict |
|---|---|
| ixdzs8 | **good** for finished novels and older chapters; newest VIP chapters are poisoned (held by the poison check); formatting noise is cleaned by its cleaners |
| biquges123 | good (Longevity, Beyond the Timescape raws) but carries few current titles; its obfuscated `www…C O` watermarks are cut by a cleaner |
| biquge5 | **decoy text**: a few real paragraphs, then random sentences from other novels. `decoy_site`: index only |
| biquge345 | **decoy text**, same as biquge5. `decoy_site`: index only |
| 69shuba, ttkan | 403 to our fetcher |
| czbooks | traditional characters. Avoid unless nothing else exists |
| qidian (plugin) | official text, but only the free chapters; locked chapters are unavailable (no request made). The clean reference for `--against` |

## 4. Add the source and sample it

```bash
uv run --no-sync nov add "<book url>" --lang zh --novel <slug>    # reads the index, fetches nothing
uv run --no-sync nov sync <slug> 300 --source <id>                # one number or one range (300-302)
uv run --no-sync nov sync <slug> --source <id>                    # everything the book lacks
```

- Pick an English slug for a new novel (`--novel in-the-name-of-divine-powers`). Without it, the slug comes from the site's title.
- **Sample before a full sync.** Fetch 3–5 spread-out chapters, including the newest (e.g. 100, 300, 600, newest−1, newest), one `nov sync` each, and check them (step 5). The newest is where VIP poisoning shows.
- **Decoy sites are index-only.** Sync records their index (numbering uses it) and fetches nothing, so `nov sync <slug> 400` fetches nothing from one. To sample one anyway, use `--refresh`: `nov sync <slug> --source <id> --refresh 400`. Those chapters are checked like any other.
- `--refresh 300-302` fetches again chapters that are already stored. Held chapters (step 5) are refetched on every sync.
- With two raw sources, one source's chapters count as "covered" for the other; held numbers don't. Use `--source N --refresh a-b` to fetch them from the second source anyway.
- `nov priority <slug> 2,1` picks which source's text the book uses.

## 5. Check the text is real

Sync cleans and checks every raw-zh chapter with the zh rules (`packages/novel-sources/src/novel_sources/zh_tables.py`, layers common → site → novel). A chapter with a finding is **held**: stored, never translated; another raw source supplies the number if it can.

```bash
uv run --no-sync nov inspect <slug> 600 --source <id>                   # findings, cleaner hits, suspicious lines
uv run --no-sync nov inspect <slug> 1-5 --source <id> --against <ref>   # diff with a clean copy, paired by title
```

- `nov inspect` changes nothing. Per chapter it shows checked or not, findings with their numbers, each cleaner's before → after hits, and surviving lines that look like noise (no CJK and not a keep, unbalanced `「」`/`“”`, Latin or Cyrillic inside a CJK line). Read past paragraph 6 too; decoys start there.
- The checks:
  - **poison**: anti-piracy swaps on VIP chapters. The text reads fine, then drifts: 好→坏, 快→慢, 不→是, 没有→有没, 后→前, other names in the protagonist's place. Markers 有没 是止 最坏 坏是 然前 退入 (有没 inside 有没有 doesn't count); flagged at ≥ 2.0 per 1000 CJK chars, ≥ 3 distinct, ≥ 6 hits.
  - **decoy-names**: only for novels with `names` in their layer. Flagged when a listed name is in the first 6 paragraphs and none is in the rest. For a novel with a doubtful source, add 2–3 recurring names (protagonist, close companions).
- **Reference copy.** `--against` diffs with a clean raw source of the same novel: Qidian's free chapters (`nov add "https://www.qidian.com/book/<id>/" --lang zh --novel <slug>`, then sync the free range; not yet tried without cookies), or any source you trust. Chapters pair by title, so offsets don't matter. Differing spans are grouped by pattern (`————` ↔ `……` ×14); each group is a candidate rule.
- **Write each new pattern as a rule** in `zh_tables.py`, on the site's layer:
  - formatting noise → a `cleaners` entry: `drop(name, pattern, examples)` drops a line the pattern matches whole; `rewrite(name, pattern, repl, examples)` replaces it anywhere in a line. Cleaners fix formatting only. Poison is never repaired; that chapter stays held.
  - every cleaner carries real single-line `Example(before, after)` pairs from the raws (`after=None` for a dropped line), at least one that changes;
  - real prose that looks like noise → `keeps`;
  - a site that serves decoy text → `decoy_site=True`; recurring names → the novel layer's `names`;
  - a pattern moves from a site to `COMMON` only after it shows on two sites.

  What a translator should know but no cleaner can fix (ixdzs8's stray `」` after item names) is a note in `zh_notes.py`, per site key or slug. Run the example tests: `uv run --no-sync pytest packages/novel-sources/tests/test_zh_rules.py`.
- **After a rule change, reclean.** Any edit to `zh_tables.py` leaves every zh chapter unchecked, and translation and the glossary pass skip unchecked chapters ("not checked with current rules: run nov reclean <slug>"). `uv run --no-sync nov reclean <slug>` (or `--all`) is free and fetches nothing; it reports rewritten chapters, cleaner hits, newly held and cleared. Then `nov check <slug>`.
- **Held chapters.** The sync report and `nov check` list them with their findings. If one is a false positive (read it with `nov inspect`), `nov release <slug> <numbers> --source <id>` lets it through until its raw changes. Real poison is never released; find another source.
- **Author notes:** 上架感言, 请假, 抽奖, 月票 and 总结 items appear in the index, mostly without a chapter number. Pick chapters with none in between.

## 6. Check numbering

Sites number chapters differently: ixdzs8 ran 2 ahead of Qidian at chapter 300 and 3 ahead near 690.

- `nov check <slug>` compares title names across raw sources against the anchor (Qidian if the novel has it, else the first raw source in `nov priority` that is not a decoy site). Each run of chapters at another offset is a suggestion with a ready command, e.g. `nov align range <slug> 300-420 -2 --source <id>`.
- Nothing re-keys by itself. Check the matched-title count, then run the command; a later range wins, and it prints the keys it moved. `nov align item` gives one item a key; `nov align skip` leaves out reposts and notices.
- Duplicate printed numbers (decoy sites have them) stay unmapped; `nov check` lists them.
- Raws against English aren't compared (Beyond the Timescape's raws run 4 ahead of the English). Compare titles by hand, also against Qidian's catalogue (`m.qidian.com/book/<id>/catalog/`), and report the offset.

## 7. Report

Tell the user:
- the novel (Chinese title, author, genre, Qidian standing);
- English status, with links;
- slug and source ids, and the site of each;
- which chapters were fetched and how they were checked; held chapters and any releases;
- rules added (and whether `nov reclean` ran);
- numbering offsets and any `nov align range` applied;
- any site problems.

Add new site behaviour to the table in step 3, and real pipeline gaps to `docs/backlog.md`.
