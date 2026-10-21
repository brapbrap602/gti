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

What sites have done so far (update this list as you learn more):

| site | verdict |
|---|---|
| ixdzs8 | **good** for finished novels and older chapters; newest VIP chapters are poisoned; adds formatting noise (see step 5) |
| biquges123 | good (Longevity, Beyond the Timescape raws) but carries few current titles |
| biquge5 | **decoy text**: a few real paragraphs, then random sentences from other novels. Avoid |
| biquge345 | **decoy text**, same as biquge5. Avoid |
| 69shuba, ttkan | 403 to our fetcher |
| czbooks | traditional characters. Avoid unless nothing else exists |
| qidian (plugin) | official text, but only the free chapters |

## 4. Add the source and fetch only what's needed

```bash
uv run --no-sync nov add "<book url>" --lang zh --novel <slug>    # reads the index, fetches nothing
uv run --no-sync nov sync <slug> 300-302 --source <id>            # only those chapter numbers
uv run --no-sync nov sync <slug> --source <id>                    # everything the book lacks
```

- Pick an English slug for a new novel (`--novel in-the-name-of-divine-powers`). Without it, the slug comes from the site's title.
- **Test a few chapters before a full sync.** Fetch 2–3 spread-out chapters (e.g. 300, 600, newest−5) and check them (step 5) before pulling the whole book.
- `--refresh 300-302` fetches again chapters that are already stored.
- With two raw sources, one source's chapters count as "covered" for the other. Use `--source N --refresh a-b` to fetch them from the second source anyway.
- `nov priority <slug> 2,1` picks which source's text the book uses.

## 5. Check the text is real

Read chapters straight from `novel.sqlite`:
- `version(source_id, item_ref, title, blocks_json)`;
- `blocks_json` is a list of `{"type":"paragraph","runs":[{"text":…}]}`.

Use `python -X utf8 -I`, because the console is cp1252.

- **Decoy text:** the chapter starts on-story, then turns into unrelated sentences with names the novel never uses. Read past paragraph 6; the decoy usually starts there.
- **Anti-piracy swaps (poisoned VIP chapters):** the text reads fine at first, then drifts. Characters flip to their opposites (好→坏, 快→慢, 不→是, 没有→有没, 后→前, 进→退), and other names take the protagonist's place. Count the markers per chapter:

  ```python
  M = ['有没', '是止', '最坏', '坏是', '然前', '还没', '退入']
  ```

  On ixdzs8, clean chapters had 0–2 of 有没 and poisoned ones had 14–21. Find where poisoning starts by sampling (e.g. 500, 600, 650, 680, …) and use chapters before it. Finished novels are usually clean throughout.
- **Formatting noise:**
  - lone `>` or `」` paragraphs;
  - "————" for "……";
  - stray `」` after item names.

  These cause translation failures and even invented sentences (see `docs/backlog.md`). Note it in the report; normalisation isn't automatic yet.
- **Author notes:** 上架感言, 请假, 抽奖, 月票 and 总结 items appear in the index, mostly without a chapter number. Pick chapters with none in between.

## 6. Check numbering

Sites number chapters differently:
- ixdzs8 ran 2 ahead of Qidian at chapter 300 and 3 ahead near 690;
- Beyond the Timescape's raws run 4 ahead of the English.

Compare titles around the chapters you care about, across sources and against Qidian's own catalogue (`m.qidian.com/book/<id>/catalog/`). `nov align` can shift a source by a fixed offset. Otherwise, report the offset and say which numbering the chapters use.

## 7. Report

Tell the user:
- the novel (Chinese title, author, genre, Qidian standing);
- English status, with links;
- slug and source ids, and the site of each;
- which chapters were fetched and how they were checked;
- numbering offsets;
- any site problems.

Add new site behaviour to the table in step 3, and real pipeline gaps to `docs/backlog.md`.
