# Raw cleaning and checks: developer plan

Status: approved by the user 2026-10-21 (r3). Slices 1–10 built (slice 9 without G2); rollout step 2 left.
- The user approved the baseline (§1) on 2026-10-20.
- Two independent reviews and one focused follow-up review (of r2's changes) are folded in (§9).
- r3 adds only that review's remedies.

Related: [stakeholder plan](raw-cleaning-stakeholder.md) · [platform developer plan](novel-platform-developer.md) · [translation developer plan](translation-developer.md) · [backlog](../backlog.md) · [load-novel skill](../../.claude/skills/load-novel/SKILL.md).

## Terminology

| Term | Meaning |
|---|---|
| zh rules | The cleaners, checks, notes and names for raw-zh sources, in three **layers**: common zh → site → novel. |
| Site key | The novel-downloader site key (`ixdzs8`, `biquge5`, `biquges123`, `qidian`, …) from `noveldl.site_book`, or the backend name for other raw-zh backends (`import:mtl`, `lncrawl`, …). |
| Novel key | The library slug (`cultivating-in-two-worlds`). |
| Cleaner | A deterministic rewrite of one line of kept raw **text**, run before `normalize`. It returns the new line, or `None` to drop it. Cleaners fix formatting only; they assume the text is genuine. They are never applied to HTML raws. |
| Check | A verdict on one cleaned chapter's paragraphs. It returns `Finding`s and never changes the text. |
| Finding | `(check, detail)`, e.g. `("poison", "有没×9 是止×4 退入×3 (3.1/1000)")`. |
| Held | A raw-zh chapter number that a source cannot supply, because one of its current parts has a finding that is not released. |
| Release | The user's statement that a finding is a false positive. It is stored per (source, item, **raw hash**) together with the checks it clears. |
| Rules revision (`rules_rev`) | A hash of the zh rules code that cleaned and checked a version (§3.3), stored on the version. |
| Unchecked | A current raw-zh version whose `rules_rev` is not the current one: NULL, or older. |
| Translator notes | Text from the zh rules that is added to the translation system instructions for chapters from that raw source. |
| Anchor source | The raw source whose numbering counts as correct for numbering suggestions: a Qidian source if the novel has one, else the first raw source in `nov priority` that is not a decoy site. |

## 1. Approved decisions (user, 2026-10-20 / 21)

1. **Rules home: repo Python tables** in `novel_sources`, beside `hosts.py`, in three layers: common zh → site → novel (slug).
   - The user expects rules to get complicated, so a rule may be a small function.
   - A pattern moves from site to common only after it has been seen on two sites.
2. **Three kinds of rule per layer:**
   - **cleaners**: formatting only. They assume genuine content and never repair poison.
   - **checks**.
   - **translator notes**: in v1 (user choice).

   Every cleaner carries before→after examples, and one parametrized test runs them all.
3. **Flagged chapters are held** (user):
   - They are stored, but never translated.
   - Raw selection falls back to the next raw source that has a usable copy of the number.
   - Sync treats the number as not covered, so another source fetches it.
   - `nov release` clears a false positive.
   - The user restated this: poisoned chapters are never translated, and cleaning focuses on formatting.
4. **Decoy detection = novel names + site verdict.**
   - The novel layer lists recurring names, and the names check (§3.3) flags chapters where they vanish.
   - Sites known to serve decoys are marked.
5. **Numbering: a check with suggestions.** `nov check` compares title names across raw sources and suggests per-range offsets. The user applies them; nothing re-keys automatically. The command for applying them, `nov align range`, is new (§9 R4).
6. **Anchor = Qidian, else the first raw source in priority** (user, after review 1). Refinement in r3: decoy sites are skipped when picking the anchor (§9 F-O6), because their printed numbers have duplicates.
7. **Rule changes:**
   - Each version records its `rules_rev`.
   - `nov check` and the sync report count unchecked chapters.
   - The explicit `nov reclean <novel>|--all` re-runs cleaners and checks from the kept raw text and reports what changed. Nothing re-cleans automatically.
8. **Held chapters are refetched on every sync** (user, after review 1). Decoy sites never fetch (decision 12), so this applies only to other sites.
9. **Sampling method** (the load-novel skill):
   1. Sync 3–5 spread-out chapters, including the newest.
   2. Run `nov inspect`.
   3. Run `nov inspect --against <reference>`, which diffs against a clean reference copy, e.g. Qidian's free chapters.
   4. Write each new pattern as a rule with examples, and test it.
10. **Web: show only.** The novel page's Check section lists held chapters, numbering suggestions and the unchecked count. Actions stay CLI-only.
11. **Excluded:**
    - auto-alignment;
    - keeping full HTML pages (only the parser's text is kept);
    - a web Release button;
    - repairing poison;
    - the translation soft check "punctuation-only source → sentence";
    - a user-editable rules file.
12. **Decoy sites are index-only** (user, after review 2). Sync records their index, which numbering uses, but fetches no chapters. This supersedes "every chapter from them is held".
13. **Translation refuses unchecked raws** (user, after review 2). They are skipped and reported as "not checked with current rules: run `nov reclean <slug>`", like blocked chapters, while everything else is sent.
14. **The glossary pass skips unchecked raws too** (user, after the focused review): discovery, hints and summaries.

**Superseded proposals.**
- **"Rules as data" (JSON/TOML).** Replaced by Python tables (decision 1).
- **"Warn only".** Replaced by holding (decision 3) and refusing unchecked raws (decision 13).
- **"Release per content hash".** Replaced by release per raw hash (§9 R5).
- **"Raw marker counts with a threshold".** Replaced by density plus minimums (§9 R3).
- **"Fetch and hold decoy-site chapters"**, and with it the `nov add` warning. Replaced by index-only (decision 12).
- **Per-layer `rev` from `inspect.getsource`.** Replaced by a whole-file hash (§9 N2).
- **`nov reclean --dry-run`.** Dropped (§9 review 2).
- **The reverted backlog baseline, "drop paragraphs with no CJK or letters".** Rejected on evidence: it would delete legitimate `……` and `——` paragraphs (§2.3).

## 2. Verified baseline

### 2.1 Code (read 2026-10-20/21)
- **`novel_sources/clean.py`.**
  - `CleanRules(content, remove, drop, strip)` composes with `|` (`clean.py:23-37`).
  - `normalize` splits text content per line and classifies symbol-only lines as `Separator` *before* `drop`/`strip` run (`clean.py:55-62, 132-134`).
  - `_drop_title_echo` uses the title (`clean.py:187`).
  - HTML content needs a `content` selector, otherwise it raises `CleanError` (`clean.py:65-69`).
- **`novel_sources/noveldl.py`.**
  - `_RAW_RULES = CleanRules(content=())` (`:32`).
  - `fetch_chapter` returns the parser's text after t2s (`:95-105`); the HTML is discarded.
  - `fetch_index` ignores the index's `accessible` flag (`:75-93`).
  - `mtl.py` (import:mtl) also uses `_RAW_RULES` and keeps the body without its title line.
- **Raw-zh sources with HTML raws.** lncrawl, lnreader and decode_guide make RAW_ZH sources when `lang == "zh"` (`lncrawl.py:64`, `lnreader.py:164`, `decode_guide.py:94`). Their kept raws are body HTML. None exists in the library today.
- **Kept raws.**
  - `put_version` writes `raw/<sid>/<sha1(ref)>-<sha1(data)[:12]>.<type>.zst` only when it inserts (`store.py:417-469`).
  - Every raw-zh version in the library has a `raw_path` matching that pattern.
  - Nothing reads a raw back (`read_version`, `store.py:477-485`).
- **`put_version`** is one transaction.
  - The `Unchanged` branch matches the content hash against **every** version of the item, not just the current one, and only bumps `last_seen_at` (`store.py:425-434`).
  - "Current" means the newest `last_seen_at` (`store.py:489-509`).
  - Schema is v3; migrations are in `_MIGRATIONS` (`store.py:49, 146`).
  - `_move_versions` deletes versions (`store.py:411`).
- **`NovelView.to_fetch`** (`view.py:157-193`).
  - For a raw-zh source, "covered" means any raw source has a current version of the number.
  - Stored items are never refetched unless `refresh` names them.
- **`raw_chapters`** (`novel_translate/raws.py:28-43`) takes every part of a number from the first raw source in priority. Its callers are phase A, phase B, compare, `service.py:747` and `_references` (`service.py:939`).
- **Raw-zh is never selected or pinned** (`view.py:144-149`, `store.py:284`). Holding a chapter cannot affect the site, EPUB, audio or pins.
- **Alignment.**
  - `nov align` has `item`, `skip` and `copy` only (`cli.py:217-247`).
  - `RangeOverride(start, end, offset)` is over **printed** numbers, and its offset **replaces** the source offset (`alignment.py:24-31`). Nothing sets it.
  - Items of one source that share a printed number are unmapped duplicates.
- **Phase B.**
  - `_Run` is built in `estimate_translate`, `stale`, `translate`, `prune` and `_comparing` (`phase_b.py:110, 126, 153, 201, 352`).
  - The system prompt is `prompt(prompt_version) + addendum` (`:518`).
  - `input_key` is a pure hash of setup, raw hash, glossary subset, summaries and previous raw (`:427-440`). A golden of it is therefore feasible.
  - `_Run.index` adds orphans with text to the skip list and never removes them (`:567-584`).
  - `prune` deletes orphans (`:199-212`).
- **Layers (import-linter):** novel_app > (novel_sources | novel_translate | …) > novel_core. `sync()`/`store_chapters` do not know the slug (`sync.py:46-63`). Web sources sync in id order (`service.py:237-247`).
- **`library.novel_slugs`** lists every folder that has a `novel.sqlite`, including `_backup-*` (`library.py:50-53`). `nov serve`/`nov build site` open every listed novel (`service.py:265`).
- **The qidian plugin exists** (`.venv/.../plugins/sites/qidian`). For a locked chapter `parse_chapter_content` returns None (`qidian/parser.py:206-210`). Fetching without cookies has not been verified (gate G2).

### 2.2 Tests and CI
- pytest, with `-m "not live and not browser and not scale"` and `--import-mode=importlib`.
- CI (`.github/workflows/ci.yml`) runs secret scan, `lint-imports` and pytest on windows-latest.
- Helpers:
  - `novel-core/tests/conftest.py`: `Book` and `TickingClock`.
  - `novel-sources/tests/test_sync.py`: `FakeSite`.
  - `novel-translate/tests/test_phase_b.py`: `Translator` and `Novel` fakes.
  - `novel-app/tests/conftest.py`: `novels` (a temporary data dir).
- Existing test files: `test_cli_*.py`, `test_web.py`.
- `test_store.py:577-578` compares `PRAGMA table_info` of migrated and fresh stores; `:601` asserts user_version 3 and must be updated.
- There are no zh fixtures. The fixture policy is scrubbed HTML for hosts (`tools/scrub_fixture.py`).

### 2.3 Data (read-only scans of the library, 2026-10-20/21; 6,666 current raw-zh versions)

| Source | Lone or inline noise | Checks |
|---|---|---|
| All sources | lone `……` (≈7,300) and `——` (≈250) are real prose, as are `“……”` and `5555` (crying) | — |
| cultivation-chat-group (import:mtl) | `××××××××` scene breaks, `......` | highest clean poison density 2.33/1000, but with 1 distinct marker (有没) |
| biquges123 (BTT, Longevity) | obfuscated-URL watermarks such as `щщщ ••C O` and `www▪▪℃ O`: 83 found, **13 glued to prose** (`wωw▪▪C〇赵二宝闻言大喜…`, `…为我做事？”шшш¤¤￠O`) | **Longevity 第651章 (ref `/50537/654`): 6.6/1000, 3 distinct (有没, 是止, 退入), 12 hits**, confirmed by hand (说是定, 有没退入) |
| ixdzs8 (both novels) | `>`, `」`, `「」`, lone digits; `「7`, `「6`, `「9`, `「...—..」`, lone `。`; `————` inside lines and `「————”` | **691–693: 23–33 hits, 2.8–4.1/1000, 4–5 distinct**; 300–685 clean |
| biquge5 (以神通之名) | none | decoy: rest after ¶6 is only **866–1,388 CJK chars**. Listed names are in the opening of 600 (李道生) and 694–696 (陆昭) and absent from the rest. 第400章 has none in its opening. |

The poison markers are 有没, 是止, 最坏, 坏是, 然前, 退入. 还没 is excluded because it is an ordinary word.

- **Proposed poison thresholds** (≥ 2.0/1000 CJK chars, ≥ 3 distinct, ≥ 6 hits): they flag exactly the four known chapters out of 6,666. Longevity 651 sits at distinct = 3, so G1 must not raise that threshold.
- **Reclean is a no-op today.** Every kept raw, re-normalized with today's code and `v.title`, gives its stored `content_hash`. A reclean in which no cleaner fires comes back Unchanged.
- **Numbering, Longevity** (import:mtl vs biquges123): 947 unique title-name matches, all at offset 0.
- **Numbering, 以神通之名** (biquge5 vs ixdzs8): runs of 0, +1, +2, +3, +2, +3, 0, +3. They are non-monotone, and touch at duplicated printed numbers (195, 263, 360) that no range can fix.
- **No translations exist yet.** Every translate.sqlite has 0 ledger and 0 summary rows.

## 3. Design

### 3.1 Core (owner: novel-core)

**Schema v4** (migration 3→4 in `_MIGRATIONS`):
- `version.rules_rev TEXT NULL`.
- `version.raw_hash TEXT NULL`. It is the `sha1(data)[:12]` from the raw file name; the migration backfills it by parsing `raw_path`.
- `finding(version_id → version.id ON DELETE CASCADE, check TEXT, detail TEXT, PRIMARY KEY(version_id, check))`.
- `release(source_id, item_ref, raw_hash, checks_json, released_at, PRIMARY KEY(source_id, item_ref, raw_hash))`.
- `rebase_refs`, which has no callers today, also rebases `release.item_ref`.

**Model:**
- `Finding(check: str, detail: str)`.
- `NewVersion` gains `findings: tuple[Finding, ...] = ()` and `rules_rev: str | None = None`.
- `Selected` gains `rules_rev`, `findings` and `raw_hash`.

**`put_version` owns writing findings and the raw identity, in one transaction:**
- **Inserted:** as today, plus `raw_hash`, `rules_rev` and the `finding` rows.
- **Unchanged** (matches any version of the item, `store.py:425-434`):
  - When `v.raw` is given, write the raw file if missing and set the matched row's `raw_path`/`raw_hash` to this raw. This way the current version's raw is always the one its findings were computed from (§9 N3).
  - When `v.rules_rev` is not None, replace the row's findings and set its `rules_rev` (§9 O4). A put without rules never clears a hold.
- Callers that pass no zh rules (English backends, translations) are unchanged.

**Further methods:**
- `read_raw(version_id) -> RawChapter | None` decompresses the kept raw, keeping `content_type`, `final_url` and `fetched_at` from provenance.
- `release(source, refs, checks, at)` records the checks firing now. A reclean of the same raw keeps the release. A *new* check type is not covered and can still hold the chapter.

**Holds, with one rule owner in `NovelView`:**
- `held(source, item)` = the current version has a finding whose check is not in a release for (source, item, version.raw_hash).
- A source **can supply number N** iff it has a current version at N and none of its current parts at N is held (§9 R6).
- `NovelView.raw_chapters(keys) -> tuple[Selected, ...]` gives, per number, the first raw source in priority that can supply it, with all its parts. `novel_translate.raw_chapters` uses it.
- **`to_fetch` for raw-zh:**
  - `covered` = numbers that some raw source can supply.
  - Also wanted: the source's own stored items that are **held** (decision 8), subject to `only`. Released and clean items are not refetched.
  - `refresh` behaves as today.
- `view.chapters()` stays unfiltered, so pages and inspect still show held text.
- `CheckReport` gains `held: tuple[ItemNote, ...]` (detail = the findings). `raw_only` leaves out numbers whose only raw copies are held.

**Numbering** — `NovelView.numbering(anchor: SourceId) -> tuple[NumberingRun, ...]`, where `NumberingRun(source_id, printed_start, printed_end, offset, matched)`:
1. For every other raw source, take each item's **title name**: the title with `第…章`/digits removed, `（…）`/`(…)` suffixes removed, and whitespace squashed. This is a new pure helper `title_name` in `keys.py`.
2. Match names that are unique on both sides.
3. Each match gives the **absolute** `offset = anchor_key.number − printed_number`, which is the value a `RangeOverride` takes.
4. Run-length encode consecutive printed numbers with the same offset.
5. Report runs of at least 3 matches whose offset differs from what the source's current alignment already gives those printed numbers.

Applying every suggestion and recomputing yields no runs (§9 N5). Duplicate printed numbers stay unmapped, and `nov check` already reports them as duplicates. novel_app picks the anchor (decision 6: never a decoy site) and calls `numbering` beside `check`.

### 3.2 `nov align range` (novel-app; core already supports it)
`nov align range <novel> <printed start-end> <offset> --source N` appends `RangeOverride(start, end, offset)` through `set_alignment`. The last covering range wins, so appending is enough. It prints the moved keys as `align item` does (`_echo_moved`). Numbering suggestions print a ready-to-run command for each run.

### 3.3 zh rules (owner: novel-sources)

**Files:**
- `novel_sources/zh_rules.py`: types, composition, pipeline and checks.
- `novel_sources/zh_tables.py`: the `COMMON`, `SITES` and `NOVELS` layers.
- `novel_sources/zh_notes.py`: notes per site key and per slug.
- `novel_sources/zh_inspect.py`: the trace and diff for `nov inspect`.

**Types:**

```python
@dataclass(frozen=True)
class Example:
    before: str           # one kept-raw line
    after: str | None     # the cleaned line, or None when it is dropped

@dataclass(frozen=True)
class Cleaner:
    name: str
    apply: Callable[[str], str | None]
    examples: tuple[Example, ...]   # __post_init__: at least one example whose after != before

@dataclass(frozen=True)
class Layer:
    cleaners: tuple[Cleaner, ...] = ()
    keeps: tuple[str, ...] = ()     # lines that must come through this layer (and the ones above) unchanged
    markers: Markers | None = None  # poison markers and thresholds
    decoy_site: bool = False
    names: tuple[str, ...] = ()     # novel layer: recurring names for the names check
```

**Interface:**

```python
def zh_rules(slug: str, spec: SourceSpec) -> ZhRules | None:
    """The composed rules for a raw-zh source; None for any other kind."""

@dataclass(frozen=True)
class ZhRules:
    rev: str
    notes: str
    decoy_site: bool
    def version(self, raw: RawChapter, title: str, base: CleanRules, provenance: Mapping[str, object]) -> NewVersion:
        """Text raws: clean each line, then normalize with CleanRules(content=()); `base` is ignored, so sync
        and reclean cannot diverge. HTML raws: normalize with `base`, no cleaners. Then run the checks;
        the findings and rev are on the result."""
    def recheck(self, version: Version) -> NewVersion:
        """Checks only, on stored blocks (HTML raws at reclean time); same blocks, new findings and rev."""

def is_reference(spec: SourceSpec) -> bool:  # site key "qidian"
```

`base` is the source's own `clean_rules(raw)` at sync and matters for HTML raws only.

**What `rev` means for HTML raws.** It means only "checks are current". Their blocks come from the backend's own rules and are re-made only by `nov sync --refresh`. No such source exists today (§2.1). If one appears, a later change can re-normalize those raws too: lncrawl and lnreader rules are static, while decode_guide needs the guides.

**Order inside `version`** for text raws:
1. Run cleaners line by line over `raw.content` (common, then site, then novel). This happens before `normalize`, so `————`→`……` is a rewrite and never becomes a Separator.
2. `normalize`.
3. Checks, each producing at most one Finding:
   - **poison** (common `markers`): `density` = hits per 1000 CJK chars. Flag when `density ≥ 2.0`, `distinct ≥ 3` and `hits ≥ 6`. The detail gives each marker's count and the density.
   - **decoy-names** (novel `names`):
     - *opening* = the first 6 paragraphs; *rest* = the remainder.
     - Flag when **any** listed name is in the opening, **none** is in the rest, and the rest has at least **600** CJK chars.
     - A chapter whose opening has no name (biquge5 400, side-character chapters) is not flagged.

   There is no `decoy-site` finding: decoy sites are never fetched by sync (decision 12). Chapters fetched from one by hand with `--refresh` are judged by the content checks like any other.

**Revision (§9 N2).**
- `rev` = sha256 over the source bytes of `zh_rules.py`, `zh_tables.py` and `clean.py`, plus the slug and site key.
  - The bytes are read **once at import** (`Path(module.__file__).read_bytes().replace(b"\r\n", b"\n")`) into a module constant.
  - Reading at import means a long-running `nov serve` with old code loaded stamps the *old* rev. Its chapters then show as unchecked, so it fails closed (§9 F-N2).
  - Normalizing line endings keeps CRLF checkouts stable.
  - A guard test asserts that `zh_rules`/`zh_tables` import nothing from `novel_sources` except `clean`, so no rule logic sits outside the hash.
  - Hashing `clean.py` means an English-only edit there also blocks zh translation until a (free) reclean.
- `zh_notes.py` and `zh_inspect.py` are excluded: notes reach `input_key` directly, and inspect changes nothing that is stored.
- Any edit to the rule code therefore marks every zh chapter unchecked. That is deliberate: a missed change would let unchecked text through, while a spurious one costs a free local reclean.
- The trade-off is losing per-site granularity, accepted because reclean is cheap (§2.3: a no-op reclean returns Unchanged).

**Site key** comes from `site_key(spec)`: novel-downloader → `site_book(url)[0]`; any other raw-zh backend → its backend name.

**Starting set** (proposals; slice 9 settles each one on evidence):

| Layer | Rule | Evidence / gate |
|---|---|---|
| common | poison check | §2.3; G1 |
| common | keeps: `……`, `“……”`, `——`, `5555`, `××××××××`, `......` | §2.3 |
| ixdzs8 | drop lone `>`, lone digit lines, lone `」`, lone `。`; cut the digit in `「7`-style openings | §2.3, judgement 苟在两界修仙 |
| ixdzs8 | `————` → `……` inside lines; `「」`/`「————”`/`「...—..」` → the form the reference diff shows | G2 |
| ixdzs8 notes | a 」 right after an item or technique name is a formatting artifact | judgement 苟在两界修仙 |
| biquges123 | **cut** obfuscated-URL watermark spans (Latin/Cyrillic look-alikes of `www`, symbols, `C O`/`￠O`/`〇`) wherever they are in a line; drop the line only if nothing is left. Examples include the glued cases | §2.3 |
| biquge5, biquge345 | `decoy_site=True` | backlog, SKILL.md |
| novels | `names` for in-the-name-of-divine-powers (陆昭, 叶槿, 李道生) and cultivating-in-two-worlds | §2.3; G1 |

### 3.4 Sync and import (owners: novel-sources, novel-app)
- **`store_chapters`.** The `rules` and `provenance` arguments are replaced by `version: Callable[[SourceItem, RawChapter], NewVersion]`. `sync(store, source_id, source, …, zh: ZhRules | None = None)` builds it:
  - with `zh`: `zh.version(raw, item.title, source.clean_rules(raw), provenance)`;
  - without: today's `normalize` path.

  `Service._sync` and the importers pass `zh_rules(slug, spec)`.
- **Decoy sites (decision 12).** With `zh.decoy_site`, `sync()` records the index and fetches `to_fetch(sid, refresh, only=refresh ∩ only)` when `refresh` is given, and nothing otherwise. The report says `decoy site: index only`. The skill tells samplers to use `--refresh` for a decoy site, because `only` alone fetches nothing.
- **`SyncReport`** gains `held: tuple[tuple[ItemRef, tuple[Finding, ...]], ...]` (formatted only in `report.py`), `cleared: int` and `decoy_site: bool`.
- **`report.sync_lines`** prints `held: N (poison n, names n); refetched held: N, now clean M`. When another raw source exists it adds "another source picks up held numbers on its next sync".
- **The unchecked line**, `N chapters not checked with current rules: run nov reclean <slug>`, is computed in novel_app. It is printed after sync, in `nov check` and in translate (§3.6).
- **noveldl.**
  - `fetch_index` keeps a per-ref `accessible` flag.
  - `fetch_chapter` returns None **without a request** when it is False. The item becomes *unavailable*, not failed (Qidian VIP chapters).
  - Implementation verifies that no other site's parser sets the flag to False.
    Verified (novel-downloader 3.1.1): the parsers that set it False all do so for paid or locked chapters (ciweimao, ciyuanji, fanqienovel, kadokado, n17k, qidian, qqbook, ruochu, shaoniandream), matching upstream's default `fetch_inaccessible=False`. Our noveldl_sites plugins never set it.

### 3.5 Reclean, release, inspect (owner: novel-app; logic in novel-sources)

**`nov reclean <novel> | --all [--source N]`.** For each raw-zh source and each item with a current version:
- **Text raw:** `raw = read_raw(v)`, then `zh.version(raw, v.title, CleanRules(content=()), v.provenance)`, then `put_version`. `v.title` makes the title-echo step work for import:mtl, whose kept raw has no title line. The raw is passed back, so `raw_hash` and `raw_path` stay correct (§3.1).
- **HTML raw:** `zh.recheck(v)`, then `put_version` (Unchanged, with new findings and rev).

Further rules:
- `--all` uses `novel_slugs()`, which skips `_`-prefixed folders (slice 1).
- The lock is the novel lock.
- It never opens a live source.
- **It reports:**
  - rewritten (Inserted);
  - unchanged;
  - per-cleaner hit counts;
  - newly held;
  - released or now clean;
  - per translator setup, translations now stale. This is `stale()` before and after; it includes neighbours whose context changed (`phase_b.py:429-437`).

**`nov release <novel> <numbers> [--source N]`** records a release for each held item at those numbers, covering the checks firing now. It prints what it released.

**`nov inspect <novel> <numbers> [--source N] [--against M]`** is read-only.
- For each chapter it prints:
  - source and key;
  - checked or unchecked;
  - findings with their metrics (marker counts, density, name counts in opening and rest);
  - cleaner hits: rule, before → after, counts;
  - suspicious surviving paragraphs, flagged by three pure, labelled heuristics: **no CJK and not in `keeps`**, **unbalanced `「」`/`“”`**, **a Latin/Cyrillic run inside a CJK line**.
- **`--against M`:**
  - Pairs chapters by title name, not key.
  - Diffs the cleaned paragraph lists: `difflib.SequenceMatcher` over paragraphs, then over characters within replaced pairs.
  - Prints the differing spans grouped by pattern (e.g. `————` ↔ `……` ×14).

### 3.6 Translation (owner: novel-translate; composed by novel-app)

**Raw selection.** `raw_chapters` uses `NovelView.raw_chapters`. Held numbers fall back or are absent.

**One required argument for the raw-source context**, `raw_rules: Mapping[SourceId, RawRules]`, where `RawRules(notes: str, rev: str)`:
- It goes to:
  - every `_Run`;
  - the public `estimate_translate`, `stale`, `translate`, `prune` and comparison functions;
  - **phase A's `estimate_glossary` and `build_glossary`** (decision 14).
- There is no default (§9 R7).
- Service builds it from `zh_rules(slug, spec)` for each raw-zh source.
- `RawText` gains `rules_rev`, filled from `Selected`.
- A raw whose source is missing from the mapping counts as unchecked, so it fails closed.

**Unchecked refusal (decisions 13, 14).**
- A raw is **unchecked** when its `rules_rev != raw_rules[source].rev`.
- **One `_Run.refusal(raw) -> Refusal | None` decides** whether a chapter can be sent. It returns None, `"unchecked"` or `"blocked"` (`blocked_reason` names the terms); no CLI text, novel_app adds the reclean hint. A compare attempt of an unchecked chapter fails with `"unchecked (not checked with current rules)"`. It is checked in this order: unchecked, then blocked. `state()` is `current` first, so an already-current translation is never re-counted.
  - All four send paths use it: `state`, `estimate_translate`, `estimate_compare` and `compare` (`phase_b.py:275, 303-306`, which today check only `blocking`).
  - A comparison records an unchecked chapter as `Attempt(failure=reason)`.
- Unchecked chapters are not marked failed, and are not added to the setup's index (`_Run.index` `wanted`).
- `Estimate`, `TranslateReport` and the glossary `Estimate`/`GlossaryReport` gain an `unchecked` count. The CLI and web print the reclean hint.
- `compare_estimate` raises `UserError` with the hint when nothing is sendable, instead of running a $0 comparison.
- **Phase A.** `_plan` (`phase_a.py:240-256`) drops unchecked raws before computing `raws_hash`, so discovery, hints and summaries never see them.
- **Sequential mode.** A run stops at the first unchecked chapter and reports the rest as `waits for <ref>`, so the next chapters aren't translated without context and then paid for again.

**System prompt.**
- It is `instructions + notes_section + addendum`.
- `notes_section` is `""` without notes, else `"\n\n## About this source text\n" + notes`.
- The prefix is constant per source (gate G3).

**`input_key`** adds `"notes": sha256(notes)` only when the notes are not empty.

**Group requests** start a new group where the raw source changes, or where the chapter numbers skip because something between them was not sent (`_requests`, `group_request`).

**Held is not an orphan (§9 O2).**
- `StaleReport` and `_Run.orphans` list held numbers separately from orphans (`held: tuple[str, ...]`).
- `prune` leaves held numbers alone.
- `_Run.index` removes from the skip list any ref that is no longer an orphan, so a released chapter comes back without a new call (§9 R2).

### 3.7 Web (novel-app)
The novel page's Check section (`templates/novel.html:157-179`) adds:
- "Held: N", a `<details>` list capped at 200;
- "Numbering", one line per run with its `nov align range` command;
- "Not checked with current rules: N — run `nov reclean <slug>`".

The translate estimate (`_estimate.html`) shows the unchecked count beside blocked. `Service.check` returns `NovelCheck(report, numbering, unchecked)`, which `nov check` and the page both render.

### 3.8 Code-design notes
- **One owner for the "usable raw" rule** (`NovelView`). Sync coverage, translation, compare and `raw_only` read it. Rejected: a predicate passed from novel_app. `to_fetch` lives in core and would need it too, and every caller would have to remember to pass it.
- **zh rules sit behind `zh_rules()` and `ZhRules.version`/`recheck`.** Sync, import and reclean share them, so a rule behaves the same at every entry point. Rejected: a line hook on `CleanRules`. It leaks zh concerns into the English path and carries no checks, notes or revision.
- **Cleaners are line functions on kept text.** All observed noise is line-level, and kept noveldl and import:mtl raws are text. HTML raws get checks only.
- **Findings are stored, not computed when read.** Core and translate cannot import novel_sources, and holds must be visible to `to_fetch` and `raw_chapters`.
- **A release is keyed by raw hash,** and the Unchanged branch keeps the raw hash truthful.
- **`rev` hashes whole files.** It cannot miss a factory argument or a `normalize` change; it gives up per-site granularity.
- **Notes and rev travel together in `RawRules`.** One required argument; translation can tell what is unchecked without importing novel_sources.

## 4. Tests

### 4.1 Seams
- **Core:** `NovelStore`/`NovelView` through `Book` (`test_store.py`).
- **Sources:**
  - `zh_rules` public functions (new `test_zh_rules.py`);
  - `sync()` with a zh `FakeSite` variant (`test_sync.py`);
  - `NovelDownloaderSource` with `FakeFetcher` (`test_noveldl.py`).
- **Translate:** the public phase B functions with the existing `Translator` fake, extended to record the instructions it received (`test_phase_b.py`).
- **App:** the CLI (`test_cli_sync.py` and a new `test_cli_raws.py`) and the page (`test_web.py`).
- **Local-only:** a `scale`-marked calibration test over the real library (G1), never in CI.

**Fixture policy.**
- Rule examples are single lines, real where they are short.
- Check tests use synthetic chapters: filler CJK with markers or names placed at chosen densities and positions.
- Whole chapters are never committed.

### 4.2 Case matrix (named `pytest.param` ids)

| id | Layer | Setup → action | Expected |
|---|---|---|---|
| `example-<layer>-<rule>-<n>` | sources | every `Example`, through the composed layers for its site | becomes `after`, or is dropped |
| `keep-<layer>-<n>` | sources | every `keeps` line plus the library set (`……`, `“……”`, `——`, `5555`, `××××`), through common and **every** site | unchanged, still a Paragraph |
| `cleaner-needs-example` | sources | a `Cleaner` with no changing example | raises at definition |
| `dash-run-rewritten-not-separator` | sources | ixdzs8 line `————` | Paragraph `……`, not a Separator |
| `watermark-glued` | sources | biquges123 `wωw▪▪C〇赵二宝闻言大喜` and `为我做事？”шшш¤¤￠O` | watermark cut, prose kept |
| `rev-covers-factory-args` | sources | change a regex argument passed to a cleaner factory in `zh_tables.py` (temp copy) | `rev` changes |
| `rev-ignores-notes` | sources | change `zh_notes.py` | `rev` unchanged |
| `rev-stable-across-processes` | sources | compute in a subprocess and in-process; also from a CRLF copy of the three files | equal |
| `rev-read-at-import` | sources | import, then change `zh_tables.py` on disk (temp copy), read `rev` again in the same process | unchanged; a fresh process sees the new rev |
| `rules-import-guard` | sources | inspect `zh_rules`/`zh_tables` imports | only `novel_sources.clean` from novel_sources |
| `html-raw-zh-still-stores` | sources | zh lncrawl-style FakeSite with HTML raws | chapters stored with base rules, checks run, none failed |
| `poison-dense-long` | sources | 9,000 chars, 4 distinct, 3.0/1000 | finding with counts |
| `poison-dense-short` | sources | 1,800 CJK, 3 distinct, 12 hits | finding |
| `poison-common-word-only` | sources | 还没 ×20 | none |
| `poison-few-distinct` | sources | 有没 ×8 only, 2.5/1000 | none |
| `decoy-names-vanish` | sources | one name in ¶1–6, none in a 900-char rest | finding |
| `decoy-no-name-in-opening` | sources | no names in the opening | none |
| `decoy-short-rest` | sources | names in the opening, a 400-char rest without them | none |
| `findings-on-insert` / `-on-unchanged` | core | `put_version` twice, same text, different findings | second replaces findings and `rules_rev` |
| `unchanged-without-rules-keeps-findings` | core | Unchanged put with `rules_rev=None` | findings kept |
| `unchanged-takes-new-raw` | core | v1 (raw r1) and v2 (raw r2) stored; reclean r2 yields v1's content; release on r2 | v1 current with `raw_hash` r2; not held |
| `migration-3-to-4` | core | a v3 db made by the current code | `PRAGMA table_info` equals a fresh store's; `raw_hash` backfilled; user_version 4 |
| `held-not-covered` | core | A holds N, B lists N | `to_fetch(B)` includes N |
| `held-refetched-clean-not` | core | A: N held, M clean | `to_fetch(A)` has N, not M |
| `released-not-refetched` | core | A: N held, then released | `to_fetch(A)` excludes N |
| `held-part-blocks-number` | core | A: N pt1 clean, pt2 held; B: N | both parts from B |
| `release-not-new-check` | core | release `poison`, then a `decoy-names` finding | held |
| `raw-only-excludes-held` | core | only raw copy of N held | N not in `raw_only` |
| `numbering-runs` | core | anchor names 1–10; other source +2 for 3–8 and +3 for 9–10 | two runs with printed ranges |
| `numbering-round-trip` | core | source with base offset −1 and an existing range; apply every suggestion | `numbering()` returns nothing |
| `numbering-suffix-ignored` / `-repeated-name-ignored` | core | `名字（九千求月票）` vs `名字`; two `上架感言` | matched / not matched |
| `sync-held-then-other-source` | sources | sync A (poisoned N), then B | B fetches N; report lists N held |
| `sync-refetch-clears` | sources | A serves clean N on the second sync | new version current; `cleared == 1` |
| `sync-decoy-index-only` | sources | decoy-site FakeSite; sync, sync with `only`, then sync with `refresh` | index recorded, 0 fetched both times, `decoy_site` in report; `refresh` fetches only its range |
| `anchor-skips-decoy` | app | decoy site first in priority, ixdzs8 second, no Qidian | anchor is ixdzs8 |
| `sync-english-unchanged` | sources | existing FakeSite tests, `zh=None` | same results |
| `noveldl-inaccessible-unavailable` | sources | FakeFetcher index with `accessible: False` | UNAVAILABLE, no fetch call |
| `held-never-translated` | translate | N held in the only raw source | not sent; listed as held, not orphan, in `stale` |
| `held-falls-back` | translate | N held in A, clean in B | sent with B's text |
| `unchecked-refused` | translate | N's `rules_rev` older than `raw_rules`; run estimate, translate, `estimate_compare`, compare | not sent on any path; `unchecked == 1` in each estimate and report; compare records `failure="unchecked: …"`; other chapters sent |
| `unchecked-missing-source` | translate | `raw_rules` lacks N's source | unchecked |
| `unchecked-before-blocked` | translate | N unchecked and containing a blocking term | counted as unchecked, not blocked |
| `unchecked-not-indexed` | translate | translate a range containing an unchecked N | N not added to the setup's index |
| `sequential-stops-at-unchecked` | translate | sequential setup, N unchecked in N-1..N+2 | N-1 sent; N, N+1, N+2 reported `waits for nN`; no call for them |
| `group-splits-at-gap` | translate | group setup, N-1 and N+1 sendable, N unchecked | N-1 and N+1 in separate requests |
| `compare-nothing-sendable` | app | every raw unchecked | `compare_estimate` raises UserError with the reclean hint |
| `glossary-skips-unchecked` | translate | phase A estimate and build with one unchecked raw | the raw is in no discovery, hint or summary request; `unchecked == 1`; `raws_hash` equals the hash without it |
| `notes-in-system-prompt` | translate | notes for A; single, group and compare paths | each request's instructions contain the notes section |
| `no-notes-instructions-exact` | translate | no notes | instructions == `prompt(v)` (+ group addendum) |
| `no-notes-keys-unchanged` | translate | no notes | `input_key` equals a golden recorded before the change |
| `notes-change-stales` | translate | change A's notes | `stale` lists A's chapters, not B's |
| `group-splits-at-source` | translate | group setup, N from A, N+1 from B | two requests |
| `prune-keeps-held` | translate | held number with a translation; `prune` | not deleted |
| `release-republishes-free` | translate | translate N; hold N (no other raw); translate; release; translate | N listed and published again; the last run makes **no** LLM call |
| `cli-reclean-reports` | app | ixdzs8 source with kept raws, a cleaner added | rewritten/held/stale counts and per-cleaner hits printed |
| `cli-reclean-html-recheck` | app | zh HTML-raw source | findings updated, blocks unchanged |
| `cli-slugs-skip-backups` | app | `_backup-x/novel.sqlite` present | not listed; `reclean --all` leaves it at schema v3 |
| `cli-release` | app | held N | released; `nov check` no longer lists it |
| `cli-align-range` | app | `nov align range s 300-420 -2 --source 2` | keys move; diff printed |
| `cli-inspect` / `-against` | app | chapter with hits and a suspicious line / two sources with the same names at different keys | hits, metrics, suspicious lines / pairs by name, `————` ↔ `……` counted |
| `cli-check-sections` / `web-check-sections` | app | held + numbering + unchecked | three sections in `nov check` and on the page |
| `scale-calibration` (scale) | sources | real library | poison: ixdzs8 691–693 and Longevity 第651章; decoy-names: biquge5 600, 694–696; **no other finding on any stored raw** (G1) |

### 4.3 Walkthroughs (agent-run, no paid calls)
1. **On a copy of the data dir** (`NOVELS_DATA_DIR=<copy>`):
   1. Run `nov reclean --all` and record the counts.
   2. `nov check in-the-name-of-divine-powers` shows 691–693 held.
   3. `nov check my-longevity-simulation` shows 第651章 held.
   4. `nov translate … --estimate`-equivalent output shows the held chapters excluded and nothing unchecked.
2. **Sampling 苟在两界修仙:** `nov inspect cultivating-in-two-worlds 101-103`, then `--against` the Qidian free chapters (G2).
3. **Web:** `nov serve` on the copy (ask before restarting a running server). In Firefox, check the Check section and the estimate's unchecked count.

## 5. Gates
- **G1 — calibration.** The `scale-calibration` test. Acceptance:
  - exactly the listed chapters are flagged, and nothing else;
  - biquge5 400 is unflagged by names. After decision 12 that source is index-only, so it serves no new text.

  If tuning is needed, record the measured values here. Do not raise `distinct` above 3.

  **Passed 2026-10-21** on a library copy (6,620 mapped raw-zh chapters; the 46 unmapped stored ones checked once by hand, no finding). Flagged exactly: poison ixdzs8 691 (4.1/1000, 4 distinct, 32 hits), 692 (2.8, 4, 23), 693 (4.1, 5, 33), biquges123 Longevity 651 (6.6, 3, 12); decoy-names biquge5 600 (rest 908 CJK), 694 (900), 695 (866), 696 (937). Thresholds unchanged. One tuning: 有没有 is ordinary (`Markers.ordinary`): 1,437 of the library's 1,507 有没 sit in it, none in a flagged chapter. Highest clean chapter after it: 1.7/1000 with 1 distinct (biquges123 Longevity 284, 退入×3). Other rule changes, each from real lines:
  - biquges123 watermark widened (○/Ο/С ends, ＿⊙◆▲★✿☢⊕●¸ padding, ttkan look-alikes, a symbol pair without www): 121 cut, 22 glued to prose; no watermark-looking survivor by the inspect heuristics (was 29 cut, about 90 left).
  - ixdzs8 lone-noise also drops `5」` and `o` (one line each). No lone digit run longer than one digit is stored, so none is dropped. `「7`/`「6`/`「9` (3 lines, ch 600 and 640) are left: cutting the digit leaves a bare `「`, and what stood there is for the G2 diff to show.
  - No names for cultivating-in-two-worlds: it has no decoy source, so no evidence.
- **G2 — reference source.** Open: the Qidian fetch is not yet authorized. The `「」`/`「————”`/`「...—..」`/`「7` rewrite waits for it.
  - Verify the qidian plugin fetches the free chapters of 苟在两界修仙 without cookies (a web fetch, not paid).
  - Acceptance: `--against` pairs at least 3 chapters, and the `「」`/`————` rule is chosen from the diff.
  - Fallback: another clean raw source, or heuristics with the rule marked unverified.
- **G3 — prompt caching.** Only a paid call can measure it, so the user runs it. It does not block release.
- **G4 — reclean on a copy** (walkthrough 1) before the real library.

  **Passed 2026-10-21** (copy of the novel databases and raws, 859 MB). `nov reclean --all`: 6,620 rechecked, 121 rewritten (biquges123 watermark 20 + 93, ixdzs8 3 + 5), 6,499 unchanged; cleaner hits watermark 121, dash-run 105, lone-noise 28; 8 newly held, 0 cleared. A second run: 0 rewritten, 0 newly held. `nov check in-the-name-of-divine-powers`: held 7 (ixdzs8 691–693 poison, biquge5 600, 694–696 decoy-names); `nov check my-longevity-simulation`: held 1 (651); neither prints an unchecked line. Translate estimate (a setup added on the copy, a price-only stand-in, no network): 600–696 sends 5 (600, 640, 660, 675, 685), 0 unchecked, `stale` lists 691–696 as held, not orphans; Longevity 645–655 sends 10, 651 held. Web (walkthrough 3, by HTTP on the copy): the Check section shows Held 7 / Held 1 with details, Numbering 6 runs, and no unchecked line.

## 6. Security, data and rollout
- **Before the first v4 open,** copy every novel's `novel.sqlite` to `_backup-schema3-<date>`, as was done for schema 2. Slice 1 lands the `novel_slugs` `_` skip together with the migration, so no backup gets migrated (§9 N10).
- **Reclean never deletes versions.** Current moves to the new version and the old row stays.
- **Rollout:**
  1. G4 on a copy.
  2. `nov reclean --all` on the real library.
  3. `nov check` per novel.

  Until step 2 runs, translation, comparisons and the glossary pass refuse every raw as unchecked (decisions 13 and 14), so nothing poisoned can be paid for in between. `_references` (`service.py:928-946`) is unaffected.
- **Tests** use synthetic chapters and short real lines only. No secrets are involved.

## 7. Slices (each: failing test → code → green → commit when the user asks)
1. **Core v4:** `Finding`, `NewVersion` fields, `put_version` (both branches, raw identity), `read_raw`, `raw_hash`, migration, `ON DELETE CASCADE`; **`novel_slugs` skips `_`**; schema-3 backup step.
2. **Core holds:** held rule, `NovelView.raw_chapters`, `to_fetch` coverage and refetch, `release`, `CheckReport.held`, `raw_only`.
3. **zh rules skeleton:** files and types, composition, `rev` (read at import), example/keep/guard tests, poison, decoy-names, `version`/`recheck`; `sync(zh=…)`, decoy index-only, `store_chapters(version=…)`; Service and importer wiring.
4. **Reports:** sync report lines, unchecked count, `NovelCheck`, `nov check`, web Check section.
5. **`nov release`, `nov reclean`.**
6. **Translation and glossary:** `raw_chapters` via the view, `RawRules` argument, `sendable` on all send paths, phase A skip, sequential stop, system prompt, `input_key`, group split (source and gap), held-vs-orphan, un-skip, estimate/web unchecked count, `compare_estimate` refusal.
7. **`nov inspect`** with `--against`; noveldl `accessible` → unavailable.
8. **Numbering:** `title_name`, `NovelView.numbering`, the anchor, `nov align range`, check and web lines.
9. **Starting rule set:** G2 sampling, then ixdzs8 and biquges123 cleaners, notes and names, then the G1 scale test, then walkthrough 1 (G4).
10. **Load-novel skill rewrite** (sampling and rule-writing steps; the false `nov align` claim fixed) and backlog entries closed.

## 8. Definition of done
- [ ] All §4.2 cases pass; CI green (pytest, lint-imports, secret scan).
- [ ] G1 and G4 passed and recorded. G2 passed, or its fallback recorded.
- [ ] Rollout step 2 (`nov reclean --all` on the real library) run with the user's OK, and its counts reported.
- [ ] Walkthroughs reported to the user.
- [x] The skill and backlog are updated.
- [ ] No paid run was made.

## 9. Review log

**Review 1** (independent, 2026-10-20, against the baseline). All findings were accepted.
- **R1.** Findings and `rules_rev` are written inside `put_version`.
- **R2.** Un-skip.
- **R3.** Density thresholds, after a second poisoning site was found (biquges123).
- **R4.** `nov align range`.
- **R5.** Release by raw hash.
- **R6.** Per-number holds.
- **R7.** Required notes argument (now `RawRules`).
- **R8.** Backups skipped.
- **Hidden scope:** Qidian unavailable, `--against` by name, sync-lag note.
- **Questions:** refetch every sync (decision 8); anchor (decision 6); release covers the checks firing at the time.

**Review 2** (independent, 2026-10-21, against DRAFT r1). Accepted:
- **N1.** decoy-names could not flag the known decoys (rests of 866–1,388 chars). Now "any name", a rest of at least 600, and a revised G1. Verified by hand.
- **N2.** `getsource` misses factory arguments and `normalize` changes. Now a whole-file `rev`; notes moved out of it.
- **N3.** Unchanged could revive an older version with a different raw. The matched row now takes the new raw.
- **N4.** zh rules broke HTML raw-zh sources (lncrawl and the like). Now cleaners are for text only, with `recheck` for HTML. Verified.
- **N5.** Numbering offsets must be absolute over printed ranges. Round-trip test added.
- **N6.** Decoy sites would sync about 750 chapters. Now index-only (user, decision 12).
- **N7.** The watermark rule is now a cut; more ixdzs8 patterns listed.
- **N8.** Tests that a wrong implementation would pass: added released-not-refetched, mixed lasting (later dropped with `lasting`, F-O8), clean-not-refetched, no-call republish, notes on every path, exact instructions, migration `table_info`.
- **N9.** Changeover gap. Translation refuses unchecked raws (user, decision 13), and the rollout step is in the definition of done.
- **N10.** The slugs skip moves to slice 1, with a schema-3 backup.
- **Optional, adopted:** O1 (cascade, rebase release), O2 (held ≠ orphan, prune keeps held), O3 (neighbour staleness via `stale()`), O4 (no clearing without rules), O7 (no request for locked chapters).
- **Optional, not adopted:**
  - O5 (stale count on `align range`): no translations exist.
  - O6 (release guard for decoy-site): moot with index-only.
- **Dropped scope:** `--dry-run`, the `nov add` warning, two inspect heuristics, `rev-changes-per-site`.
- **Corrected:** §2.3 figures and line references.

**Focused review** (independent, 2026-10-21, of r2's changes). Verdict: ready once four items are added. All four were added in r3:
- **F-N1.** Phase A would spend on unchecked text. The glossary pass now skips it (user, decision 14).
- **F-N2.** `rev` is read once at import with line endings normalized, so a stale server fails closed.
- **F-N3.** The compare paths bypassed `state()`. One `sendable` now sits behind all four paths, and the tests cover compare.
- **F-N4.** `RawRules.rev` is now `str`; a missing source counts as unchecked; `RawText.rules_rev` added; state order fixed and tested.
- **Optional, adopted:**
  - F-O1: the meaning of rev for HTML raws is stated.
  - F-O2: `base` is ignored for text raws.
  - F-O3: the clean.py note and an import guard test.
  - F-O4: sequential runs stop at the first unchecked chapter.
  - F-O5: groups split at gaps.
  - F-O6: the anchor skips decoy sites, a refinement of decision 6.
  - F-O7: the decoy fetch rule is spelled out.
  - F-O8: `lasting` and the `decoy-site` finding are dropped as dead logic.
  - F-O9: `compare_estimate` refuses when nothing is sendable.
  - F-O10: unchecked refs are not indexed.

r3 contains only these remedies. No further independent review is planned unless the user asks or the approval changes something material.
