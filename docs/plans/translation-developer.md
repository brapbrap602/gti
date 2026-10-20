# Translation pipeline: developer plan

Status: approved by the user 2026-10-20 (r3). Not built; implementation needs the user's go-ahead. The baseline (§1) was approved by the user on 2026-10-20. Three independent reviews are folded in (§9).
Related: [stakeholder plan](translation-stakeholder.md) · [platform v1 developer plan](novel-platform-developer.md) · [reader UI plan](reader-ui-developer.md) · research: [LLM web novel translation tools](../research/LLM%20web%20novel%20translation%20tools.md) (notes in `docs/research/LLM web novel translation tools/`).

## 1. Approved decisions (user, 2026-10-20)

1. **Goal.** Build a reusable LLM translation pipeline on OpenRouter models. It must work on any chapter range of any novel that has raws. First uses:
   - Longevity 1495–1781 (replacing the MtlTings text)
   - CCG past the official text
   - all of Transcendental Mechanic (TM)

   Re-translating chapters that already have English is a later run of the same pipeline.
2. **Official English is not an authority.** The user suspects it is also a poor machine translation. It provides hints only.
3. **Release 1 is the whole pipeline,** built as glossary-first slices (§7). This supersedes the earlier "release 1 = glossary tooling only".
4. **Two phases.**
   - **Phase A** is a glossary pass over a whole novel. It produces glossary entries and per-chapter summaries.
   - **Phase B** translates against the glossary as it stands.
   - During Phase B the model reports new terms through a side channel. They are saved as `proposed` and never block. The next Phase A run scores them.
5. **Name gate.** Only low-confidence entries need review: the vote split, or the existing English disagrees. Phase B skips any chapter containing an unresolved low-confidence entry and reports it as **blocked**, naming the term.
6. **Manual glossary work** is expected at the start and throughout: adding and seeding terms before Phase A, aliases, notes, gender, bulk edit. Manual entries are locked by default. **Phase A never overwrites anything the user has edited.**
7. **Glossary editing** happens on a web page in `nov serve`, with matching CLI operations.
8. **Translator setups.** One `my-translation` source per setup. A setup's identity is model + prompt version + context mode + reasoning setting. There can be any number of setups for comparing. A setup's identity never changes, so a change means a new setup.
9. **Publishing is manual.**
   - Each setup has a publish switch, **off by default**. While it is off, the site, EPUB and audio ignore the setup, even where it is the only English.
   - New setups rank last. The user ranks or pins a setup, then builds and deploys as today.
   - Once a setup is on, re-runs replace its published text on the next build.
10. **Budget.**
    - A cost estimate is shown before every job.
    - Each job has a dollar cap. **The default is $1**, overridable per run.
    - A job stops at the cap, and stops at once on out-of-credit or key-limit errors.
    - Every call's real charged cost is recorded, including failed attempts.
11. **Context mode is a setup option.**
    - `parallel` (default): glossary subset + previous chapter's raw tail + story so far, from Phase A summaries. Several chapters run at once.
    - `sequential`: the same, plus the previous chapter's translated tail from this setup. One chapter at a time.
12. **Validation is deterministic.**
    - A hard failure gets one retry. If that also fails, the chapter is not stored and is reported.
    - A soft failure is stored, with its flags recorded.
13. **LLM layer: pydantic-ai, latest version** (user's choice). §2.4 has the verification.
14. **Out of scope for release 1:**
    - multi-agent or reflection loops
    - neural quality scores
    - automatic re-translation of stale chapters
    - scheduled runs
    - auto-ranking
    - OpenRouter Batch API
    - labelling LLM chapters on the published site
15. **Official English keeps syncing.** Chapters covered only by `my-translation` text still count as missing for official-en sources, so official text is fetched when it appears. Ranking stays manual.
16. **Privacy.** OpenRouter `data_collection: "deny"` is **off by default** and can be turned on per setup.

## 2. Verified baseline

Paths are relative to the repo root. Core = `packages/novel-core/src/novel_core`, App = `packages/novel-app/src/novel_app`.

### 2.1 Store and selection
- **`NovelStore`** (Core/store.py:161) owns `novel.sqlite`.
  - Each public method is one transaction.
  - `SCHEMA_VERSION = 2` (store.py:49), with `_MIGRATIONS = {1: _add_volumes}`. All 8 real stores are at `user_version` 2.
  - Migrations run automatically on open, with no backup. Older code refuses a newer schema.
- **`upsert_source`** (:219): sources are keyed by `(backend, url)`. A repeat call overwrites `lang`, `kind` and `config`.
- **`record_index`** (:285) marks every ref missing from the list it is given as vanished. Callers must pass the full cumulative list.
  - If `SourceItem.number` is None, the number is parsed from the title (model.py:52-66).
- **`put_version`** (:394) sets the item to OK.
  - Same title and blocks → `Unchanged`. It bumps `last_seen`, which makes that version current, and **keeps the old version's provenance**.
  - Otherwise → `Inserted`.
  - So provenance cannot serve as a per-run ledger (§3.5).
- **`mark_item(source, ref, FAILED, reason)`** (:448) persists into `check().failed`. `put_version` clears it.
- **`select()`** (Core/selection.py:57-89) receives every non-raw source (view.py:131-132). Sources missing from `priority` rank after it, in id order.
  - So a new my-translation source **is published wherever it is the only text** today.
- **`check()`** (view.py:189-207):
  - `expected` covers every key of every non-raw source.
  - `mixed_parts` iterates every source.
- **`to_fetch`** (view.py:150-176): for non-raw sources, a number counts as covered if **anything selected** has it.
  - So a published LLM translation would stop official sync for those numbers. Decision 15 changes this.
- **Library counts** (App/pages.py:160-172) count `MY_TRANSLATION` numbers from every source, published or not.

### 2.2 Data (real data dir, read 2026-10-20)
- **Longevity**
  - Priority is `[1,2,7,3,4,5,6]`.
  - Raw-zh sources: 4 (MtlTings, 369–1781) and 6 (biquges123, 1–1551). They overlap on 369–1551.
  - 3 is MtlTings my-translation, 990–1781.
  - 5 is Calibre, labelled **official-en but holding MtlTings text** for 990–1781.
  - Official English (source 7) covers 1–1494.
  - For 1495–1781, source 4 has all 287 chapters.
- **CCG**
  - Raw source 2 runs up to 3173, with odd items: #3165 parts 0, 2 and 3; two unnumbered.
  - Official English ends at 3165.
  - Raw/EN pairs: 3,164.
- **TM**
  - One raw source: items 1–1464 contiguous, plus one item misnumbered **4411** at position 1465.
  - Raw titles are English (from MtlTings); bodies are Chinese.
  - About 13 MB of raw text, roughly 5M characters.
- Average raw chapter is roughly 3–4k Chinese characters (inferred).

### 2.3 Jobs and app
- **`Service`** (App/service.py:77):
  - `_ops` maps a kind to `_prepare`, which returns `(lock target, work)`.
  - `start` queues the job on a worker thread (`nov serve`, 2 workers by default; cli.py:337).
  - `run` runs the job inline for the CLI.
- **Locks** are per target (the novel slug), live in `app.sqlite`, and are held with a heartbeat.
  - Priority and pin changes take no lock.
  - `build-site` locks only `_site` (service.py:189-202).
  - `nov serve` shutdown ends running jobs as cancelled (cli.py:346).
- **`Job.progress`** raises `Cancelled` (jobs.py:136-139), so only the coordinating thread may call it. On cancel, `_execute` ends with an empty `Outcome()` (jobs.py:331-346).
- **Problems:** a later job of the same `(target, kind)` clears earlier problems, whatever its arguments (jobs.py:240-258).
- **Web:** FastAPI + Jinja + htmx.
  - `WEB_JOBS` / `JOB_LABELS` whitelists (web/app.py:37-54).
  - The per-novel page is `novel.html`.
  - Compare works between any two non-raw sources.
  - The page cache is stamped on `novel.sqlite` writes.
- **Tests:**
  - `addopts -m "not live and not browser" --import-mode=importlib`.
  - Fakes are injected by monkeypatching Service seams (App/tests/conftest.py `site`).
  - Real SQLite in `tmp_path`.
  - CI (`.github/workflows/ci.yml`, windows-latest): `uv sync --locked`, secret scan, `lint-imports`, pytest.
- **import-linter layers:** `novel_app` → `novel_sources | novel_publish | novel_audio` → `novel_core`.
- Secrets come only from the environment. `tools/secret_scan.py` catches `sk-or-` keys in tracked files.
- `opencc` is already in `uv.lock`.
- **The repo license is GPL-3.0-only.** Copying code from GPL-3.0 tools such as GalTransl is license-compatible, with attribution. AGPL tools (AiNiee, Glossarion) remain ideas only.

### 2.4 LLM layer (verified in a throwaway venv against a local fake server; no OpenRouter calls)
- **Package:** `pydantic-ai-slim[openrouter]` 2.58.0 (2026-10-20).
  - It pulls `openai>=3.26` (3.35.1), `genai-prices`, `opentelemetry-api`, `logfire-api`, `pydantic-graph`, `httpx2` and `anyio`.
  - It needs pydantic ≥2.12; the repo has 2.13.5. No conflicts.
- **`OpenRouterModel` / `OpenRouterProvider`:**
  - The provider wraps an `AsyncOpenAI` client.
  - Settings: `openrouter_models` (fallbacks), `openrouter_provider` (routing, `max_price`, `data_collection`), `openrouter_reasoning`.
  - `extra_body` passes anything else.
- **Cost:**
  - The real charged cost is in each `ModelResponse.provider_details['cost']`.
  - `result.usage` holds tokens only; its `cost` is a genai-prices estimate, often None.
  - Every retried request carries its own cost.
  - When a run raises, for example after `output_retries` is exhausted, the messages are only available through `capture_run_messages()`.
- **Errors:**
  - HTTP errors raise `ModelHTTPError(status_code, body, headers)`.
  - 402 is not retried.
  - The openai SDK retries 429/5xx twice by default and honours `Retry-After`. `max_retries` can be set per run.
  - Truncated tool output raises `IncompleteToolCall`. Empty output on a length stop raises `UnexpectedModelBehavior`.
- **Output:** output tool by default; `NativeOutput` only for model profiles that support it.
  - An `@output_validator` raising `ModelRetry` re-prompts inside the same run, bounded by `output_retries`.
- **Threads:**
  - `run_sync` in a worker thread creates a per-thread event loop.
  - An httpx client is bound to its loop, so use **one provider, client and model per worker thread**.
  - Set `PYDANTIC_AI_NO_BANNER=1` to suppress the startup banner.
- **Tests:** `FunctionModel`, `TestModel`, `agent.override(model=…)`, `models.ALLOW_MODEL_REQUESTS=False`.
  - This does not block plain httpx calls, so the price lookup must sit behind the same seam (§3.2).
- **Not used:**
  - The official `openrouter` SDK 1.3.69 pins `pydantic<2.13`, which conflicts with the repo, and pydantic-ai cannot use it as a transport.
  - litellm: heavy, and two releases were compromised in March 2026.
- **Known pydantic-ai issues to watch:**
  - #10381: an unknown `finish_reason` raises.
  - #10004: missing provider-preference keys (use `extra_body`).

## 3. Design

### 3.1 Core changes (owner: novel-core)
- **Migration 2 → 3** adds `source.published BOOLEAN NOT NULL DEFAULT 1`, so every existing source stays published. `SCHEMA_VERSION = 3`.
  - The `sa.Column` gets `server_default="1"`, so created and migrated stores match.
  - The existing `test_open_migrates_a_version_1_store` (test_store.py:553) must also drop the new column in its downgraded fixture.
- **`published` lives only on `SourceInfo`** (default True). It is set at creation by `upsert_source(spec, *, published=True)`, and a repeat upsert never changes it.
- `NovelStore.set_published(source, on)` is a quick operation, like `set_priority`.
- **`set_pin` refuses an unpublished source,** as it already refuses raw-zh. `set_published(off)` on a pinned source is refused with a message naming the pin ranges.
- **`NovelView._selection`** passes only sources that are non-raw **and** published. This covers the site, EPUB and audio.
  - Compare and `chapters(source)` still see every source.
- **`check()`:** `expected`, gaps and `mixed_parts` ignore unpublished sources. `failed` still lists their items.
- **`to_fetch`:** for an official-en source, numbers whose selected text comes from a `MY_TRANSLATION` source do **not** count as covered (decision 15).
  - Today this also changes Longevity: MtlTings (source 3) stops blocking official fetches for 1495+. There is no official text past 1494 anywhere today, so nothing is fetched now.
- **App library counts** (pages.py:166) count only published sources.
- Alternative rejected: keeping the flag in `config_json`. That is backend-owned and overwritten by every upsert.

### 3.2 New package `novel-translate` (`packages/novel-translate/src/novel_translate`)
- **Layer:** sits beside `novel_sources | novel_publish | novel_audio`. It depends on `novel_core` only, and `novel_app` composes it.
- **Dependencies:**
  - `pydantic-ai-slim[openrouter]>=2.58`
  - `opencc`
  - `pyahocorasick`
  - `pypinyin` (pinyin soft check)

  No tenacity: `models.py` has its own short retry loop (§3.5 step 6).
- **Modules and their public interface** (names are proposals):

| Module | Owns | Public interface |
|---|---|---|
| `tstore.py` | `translate.sqlite` per novel: own `user_version` migrations, WAL, `busy_timeout`. Glossary entries, aliases, candidates, summaries, revision; translation ledger; spend log; validation norms | `TranslateStore.open/create(novel_dir)`; glossary: `entries(filter)`, `apply(edits) -> revision`, `matcher() -> Matcher`; ledger: `record(attempt)`, `latest(setup_url) -> {ref: LedgerRow}`, `spend(setup_url)`; `norms()` / `set_norms()` |
| `matching.py` | Aho-Corasick over the zh keys and aliases | `Matcher.match(text) -> Match(entries, blocking, subset_hash)`, longest match first, no overlaps. `subset_hash` = sha256 of the exact prompt lines (`zh → en (category, gender, note)`), sorted |
| `discover.py` | Pure new-word discovery | `candidates(chapters: Iterable[str], known: Set[str]) -> list[Candidate]`. Passes are bounded: count n-grams 2–8 with min-frequency pruning per length before computing PMI and entropy. Thresholds are named constants |
| `models.py` | The model seam: pydantic-ai agents, cost, errors, prices, HTTP retry | `LLM` (from a `ModelFactory`; one provider, client and model per thread; SDK `max_retries=0`; request timeout 180 s; takes a `cancel: threading.Event`); `classify(batch)`, `hint(terms, en_text)`, `summarize(raw)`, `translate(request, max_tokens) -> Attempted`; `price(model) -> Price`. Every call returns or raises with `Charged(cost, tokens, gen_ids, attempts)`. `OutOfCredit` is fatal; `CallFailed(reason, charged)` |
| `budget.py` | Spend against a cap, safe across threads | `Budget(cap)`; `reserve(estimate) -> Reservation \| None`; `settle(reservation, actual)`; `spent`, `reserved` |
| `phase_a.py` | Glossary pass | `estimate_glossary(...) -> Estimate`; `build_glossary(novel: NovelStore, ts: TranslateStore, llm, budget, options, progress) -> GlossaryReport` |
| `validate.py` | Pure checks | `check(source: SourceChapter, out: Translated, match: Match, norms: Norms) -> Findings(hard, soft)` |
| `setups.py` | Setup identity ↔ SourceSpec | `TranslatorSetup(model, prompt_version, context, reasoning, data_collection)`; `.spec()` → `SourceSpec("translate:openrouter", "openrouter:<model>?prompt=<v>&context=<mode>&reasoning=<r>&dc=<allow\|deny>", "en", MY_TRANSLATION, config)`; `register(store, setup)` upserts with `published=False` and refuses a config mismatch for an existing URL |
| `phase_b.py` | Translation run | `estimate_translate(...)`; `translate(novel, ts, setup, keys \| "stale", llm, budget, workers, progress) -> TranslateReport`; `stale(novel, ts, setup) -> StaleReport(stale, orphans)` |
| `prompts/` | Versioned prompt files (`v1.md` …); a version is never edited after first use | loaded by `models.py` |

**Raw input (shared by both phases).** For each chapter key, take one raw text: the first raw-zh source in `rank(priority)` order that has a current version for that number. Parts are kept as separate keys.
- Phase A uses the same rule, so Longevity's overlapping raw sources 4 and 6 are counted once.

### 3.3 Glossary model (in `translate.sqlite`)
- **`term`:**
  - `id`, `zh` (OpenCC t2s-normalized, unique), `category` (person|place|sect|technique|realm|item|title|other)
  - `en`, `status`, `gender`, `notes`
  - `origin` (manual|discovered|side-channel|hint-import), `confidence`
  - `updated_at`, `edited_at` (set by any user edit, never cleared), `first_chapter`, `occurrences`
- **`alias`:** `(zh → term_id)`. Aliases match like keys.
- **`candidate`:** `(term_id, en, votes, origin: llm|official-en|mtl-glossary|side-channel, examples_json)`.
- **`summary`:** `(number, part, raw_hash, model, text)`.
- **`meta`:** `revision`, incremented by every glossary write. Used as a cache key (§3.7).
- **Statuses and who changes them:**

| Status | Injected in Phase B | Blocks a chapter | Set by | Phase A may change status/`en` |
|---|---|---|---|---|
| `proposed` (side-channel, unscored) | no | no | Phase B side channel | yes, if never edited |
| `needs_review` | no | **yes** | Phase A (low confidence) | yes, if never edited |
| `accepted` | yes | no | Phase A (high confidence), user pick | re-vote only with `--revote`, if never edited |
| `locked` | yes | no | user (manual add defaults here), lock action | **never** |
| `rejected` (not a term) | no | no | Phase A (non-term) or user | only if never edited; discovery skips it |

- **Low confidence:** the top candidate holds less than 70% of LLM votes, **or** official-EN hints exist and their majority rendering differs from the top proposal (casefold, strip articles). The threshold is a named constant.
- **Edit rule:** Phase A writes are conditional, `UPDATE … WHERE id=? AND edited_at IS NULL`. It may still **add candidates** to an edited entry, which shows up on the page as new evidence. An edit made before or during a run always wins.
- **Hint import:** `nov glossary import-hints <novel> <file>` loads the MtlTings `active_glossary.json` as `mtl-glossary` candidates. Candidates only, never renderings. It is a small one-off reader, kept because it seeds Longevity.

### 3.4 Phase A: glossary pass (Service op `glossary-build`, lock: novel)
1. Load one raw text per chapter (§3.2), normalized with OpenCC t2s.
2. **Discover:** `candidates()` over all chapters, minus known zh (any status), plus every `proposed` entry.
3. **Sample:** up to 3 occurrences per candidate, with ±80 characters of context.
4. **Classify and propose:** batches of about 30 candidates per call.
   - Each candidate is shown with its 3 snippets and gets one rendering per snippet; these are its 3 votes.
   - The model also returns: is it a term, category, aliases, gender for persons.
   - Non-terms become `rejected`, with origin `discovered`.
5. **Official-EN hints:**
   - For each term, sample up to 3 chapter numbers where the raw contains it **and the selected version's source is `official-en`**.
     - On real data this excludes Longevity 1495+, where MtlTings source 3 is selected.
     - Mislabelled Calibre source 5 never feeds hints, because it is never selected.
   - One call per chapter pair, carrying that chapter's terms and its English text.
   - Answers are tallied as `official-en` candidates.
6. **Resolve:** set `accepted` or `needs_review` per §3.3, and tally the candidates.
7. **Summaries:** for every chapter whose `raw_hash` changed or has no summary, a summary of at most 120 words (cheap model).
8. **Estimate (before the job).** An **upper bound**:
   - Summaries for every chapter that needs one (exact count × average size).
   - Classification: the candidate count from a cheap frequency-only pre-pass. The build classifies **at most that many**; the rest wait for the next run.
   - Hints: 3 calls per term, at most.

   Shown with "upper bound".
9. **Budget and progress:**
   - Each call reserves its estimate first and settles with the actual cost.
   - `progress` is reported per batch from the coordinating thread.
   - Workers are a run option (default 4).
- **Steps are resumable.** Summaries are tracked by `raw_hash`, classification by term existence, and hints by `term.hinted_at`.
  - A run stopped by the budget or a cancel resolves whatever it tallied before stopping.
  - The next run continues each step.
- **Re-runs are incremental:** only new candidates, `proposed` entries, changed-raw chapters and unhinted terms are processed. `--revote` re-tallies unedited `accepted` entries.
- **A whole-novel Phase A costs more than the $1 default.** Longevity is about 6M raw characters, so summaries alone are about $0.6–2 on cheap models. The form shows the estimate; the user raises the cap or runs it in stretches.
- **Phase A model** is a run option. A default model is set in config after gate G2.
- **Scale check:** discovery over TM (about 5M characters) must finish in under 5 minutes and under 2 GB RAM on the user's PC. This is a local test in slice 4, not CI.

### 3.5 Phase B: translate (Service op `translate`, lock: novel)
1. **Register the setup's source** (create it unpublished if new).
   - Items are recorded **cumulatively**: existing refs whose raw key still exists, plus this range.
   - Each item has ref `n<number>` or `n<number>p<part>`, with explicit `number`/`part` copied from the raw key and `ref_numbered=False`.
   - **Orphans** are refs whose raw key no longer exists, for example TM `n4411` after the raw is realigned to 1465.
     - Orphans without a version are dropped from the index.
     - Orphans with a version are added to the setup source's `AlignmentRules.skip`. They then have no key, so they are never published and cause no gaps or grid cells. Their versions are kept, and `stale()` and the novel page report them.
     - The user removes them with `nov translate prune <novel> <setup>`, which drops them from the index.
2. **For each key in the range, in order:**
   - **Skip** if the ledger's latest `ok` row for (setup, ref) has `input_key` equal to the newly computed key (resume).
     - `input_key` = sha256 of the canonical JSON (sorted keys) of:
       - setup url
       - raw content_hash
       - `subset_hash`
       - summary-**text** hashes of the 10 preceding keys
       - previous key's raw content_hash
       - in sequential mode, the previous key's stored content_hash
     - Consequences:
       - A changed raw re-summarizes that chapter, which stales at most the next 10.
       - Changing the Phase A model never re-summarizes.
       - Translating before any Phase A and then running Phase A stales everything. The form says so.
       - In sequential mode, one re-translation stales every later chapter.
     - `stale()` considers only `ok` ledger rows.
   - **Blocked** if `match.blocking` is non-empty: `mark_item(FAILED, "blocked: <zh> (<candidates>)")`. Not sent.
   - **Otherwise** reserve the chapter's estimate: (input tokens + output allowance) × price × 2, covering the in-run validator retry.
     - Output allowance = 1.6 × source tokens, doubled when `reasoning != off`.
     - `max_tokens` = output allowance.
     - If the reservation is refused, the run stops with "budget reached".
     - Otherwise the chapter is submitted to the pool: `workers` threads (run option, default 4; forced to 1 in sequential mode).
3. **Request.** A stable system prompt comes first (prompt file + style rules), so prompt caching works. Then:
   - story so far (the last 10 chapter summaries, oldest first)
   - previous chapter raw tail (last 3 paragraphs)
   - [sequential] previous translated tail (last 3 paragraphs)
   - glossary subset lines
   - source paragraphs with integer ids
4. **Output type:** `Translated(title, paragraphs: list[Para(id, text)], new_terms: list[NewTerm(zh, en, category)])`.
   - The output validator runs the hard **content** checks (§3.6). A failure raises `ModelRetry`, and `output_retries=1` gives exactly one targeted retry.
   - A cut-off (`IncompleteToolCall` / `UnexpectedModelBehavior` on length) is retried **once** outside the agent, with `max_tokens` × 1.5 and `output_retries=0`.
     - The retry **reserves its own cost first**. If the reservation is refused, the chapter fails as `budget`.
     - At most 3 requests per chapter, each reserved before it is sent.
   - Cost: each run, including the cut-off re-run, gets its own `capture_run_messages()` context, which captures only the first run inside it. `provider_details['cost']` is summed over the captured responses, also when the run raises.
   - A second failure → ledger row `failed`, then `mark_item(FAILED, "invalid: <check>")`. Nothing is stored in `novel.sqlite`.
5. **Store**, through a single writer: the coordinating thread drains results.
   - `put_version(source, ref, NewVersion(title="Chapter N: <title>", blocks=[Paragraph…], provenance={setup, model, prompt, raw_source, raw_hash, glossary_revision}))`.
   - Then a ledger row: (setup url, ref, input_key, content_hash, outcome, cost, tokens, generation_ids, attempts, soft_flags, at).
   - The ledger is the source of truth for staleness, cost and flags. It is correct even when `put_version` returns `Unchanged`.
   - **Write order:**
     1. A spend row, always, for every attempt.
     2. `put_version`.
     3. The ledger `ok` row.
   - A crash between steps 2 and 3 means the chapter is re-translated on resume. The extra cost is bounded, and no chapter is lost.
   - `new_terms` → `proposed` entries. Existing zh and rejected terms are ignored.
6. **Errors.**
   - `OutOfCredit` (402, or a key-limit `limit_source`) stops submitting at once, drains in-flight calls, and is a job error.
   - **429 / 5xx.** The openai SDK cannot cap its Retry-After wait: `_base_client.py` honours up to 120 s, and that limit isn't configurable. So SDK retries are off (`max_retries=0`).
     - `models.py` retries at most 3 times, waiting `cancel.wait(min(retry_after or backoff, 60))`, with headers read from `ModelHTTPError.headers`.
     - The request timeout is 180 s.
     - After that → `CallFailed` → the chapter is `FAILED`.
7. **Cancel.** It happens through `Cancelled` (web), KeyboardInterrupt (CLI Ctrl-C), or `nov serve` shutdown.
   - The coordinator polls `wait(timeout=0.5)`, so Ctrl-C works on Windows.
   - On any of them it:
     - sets the shared `cancel` event, so retry waits end at once
     - stops submitting
     - waits for in-flight calls (at most one request timeout)
     - stores their valid results and ledger rows
     - writes the spend summary to the job log
     - re-raises
   - A **second** Ctrl-C during the drain abandons it. It logs the in-flight chapters as lost (their cost may be unrecorded) and exits.
   - Workers are joined before a normal exit.
8. **Report:** chapters translated, skipped (current), blocked, failed, orphans, cost total and soft-flag counts, written to the job log.
   - Blocked and failed chapters persist on items via `mark_item`. They appear in the novel page's check, not just in job problems.

**Staleness:** `stale(novel, ts, setup)` recomputes `input_key` for each ref in the ledger and returns those that differ, plus orphans. It is computed on demand (CLI, form, stale panel) and cached by (novel.sqlite stamp, glossary revision).

### 3.6 Validation (`validate.py`, pure)
Norms (length range, loop ratio) are stored **per novel** in `translate.sqlite`, with defaults until gate G2.

Hard content checks (any one fails the attempt):

| id | Rule (default) |
|---|---|
| `cjk` | any CJK ideograph or CJK punctuation in title or paragraphs |
| `ids` | output ids ≠ source ids: missing, extra or duplicated (merging two source paragraphs into one id fails, deliberately) |
| `empty` | any paragraph empty when its source paragraph is not |
| `loop` | the same normalized paragraph (≥40 chars) appears more than 2 times, or zlib ratio > `loop_ratio` (default 3.2) |
| `length` | English words / Chinese characters outside `length_range` (default `[0.35, 1.10]`) |
| `heading` | a body paragraph matching `^\s*chapter\s+\d+` (merged chapters) |

Cut-off is handled by the caller (§3.5 step 4), not the validator.

Soft checks (stored with flags):

| id | Rule |
|---|---|
| `term` | an injected entry's `en` (case-insensitive) missing from the output while its zh occurs in the source |
| `pinyin` | the pypinyin syllables of a person term's zh appear as a word sequence in the output |
| `title` | empty or generic title ("Chapter N") |

### 3.7 App (novel-app)
- **Service ops (with lock):**
  - `glossary-build(novel, model, cap, revote, workers)`
  - `translate(novel, setup, range|stale, cap, workers)`
- **Quick operations (no lock):**
  - `glossary-edit(novel, edits)`
  - `set-published(novel, source, on)`
  - `add-setup(novel, setup)`
  - `prune-orphans(novel, setup)`
- **`estimate(novel, op, args) -> Estimate(chapters, calls, usd, upper_bound: bool)`.** It uses `LLM.price(model)`, read from OpenRouter `/api/v1/models` and cached for 1 hour.
- **Injection:** the `LLM` factory is injected into `Service` like `tts`; tests replace it.
- **The OpenRouter key** is read from `OPENROUTER_API_KEY` when a job starts or an estimate is made.
  - If it is missing → `UserError("set OPENROUTER_API_KEY")`.
  - `nov serve` inherits the environment it was started in.
  - The key never goes into logs, provenance or the ledger.
- **CLI:**
  - `nov glossary build <novel> [--model M] [--cap USD] [--revote] [--workers N] [--yes]`
  - `nov glossary list <novel> [--status S] [--search Q]`
  - `nov glossary add|set|lock|reject <novel> …`
  - `nov glossary import-hints <novel> <file>`
  - `nov translate setup add|list <novel> …`
  - `nov translate run <novel> <setup> <range|--stale> [--cap USD] [--workers N] [--yes]` (prints the estimate and asks for confirmation unless `--yes`)
  - `nov translate stale|prune <novel> <setup>`
  - `nov publish <novel> <source> on|off`
  - TM #4411 is fixed with the existing `nov align item` before translating (gate G1).
- **Web, novel page:**
  - **Sources table:** a **Publish** toggle. A translation setup row also shows chapters, cost to date (from the ledger), flagged, stale and orphan counts.
  - **Translate form:**
    - Fields: setup, range or "stale", cap (default $1, must be > 0), workers.
    - Changing it fetches the estimate via htmx; **Start** is enabled only once an estimate shows.
    - Blocked and failed counts link to the check section.
  - **Add setup form:** model (free text, validated against the `/models` list), prompt version (select), context, reasoning, data collection.
  - **Glossary** link with counts by status.
- **Web, Glossary page** `/novels/{n}/glossary`:
  - **Tabs:** Needs review (default) · All · Proposed · Locked · Rejected. Plus search by zh or en, and a category filter.
  - **Row:** zh, category, en (editable), status, occurrences, first chapter, an "edited" mark.
  - **Expanded row:**
    - candidates with vote counts by origin (official-EN usage is visible there)
    - 3 snippets with the term highlighted
    - aliases, gender, notes
  - **Actions:** pick a candidate, edit, lock, reject, revive. **Bulk:** select rows → accept top, lock, reject, set category.
  - **Add term** form at the top. The default status is locked.
  - **Stale panel:** per setup, the stale and orphan counts with "translate stale" (prefills the Translate form). Computed on demand and cached by glossary revision.
  - Edits go through htmx and swap only the row.
- **UI states:**

| State | Glossary page | Translate form |
|---|---|---|
| empty glossary | "No entries yet" + **Build glossary** button + Add term form (works before any build) | Start allowed (no blocking terms) |
| novel has no raw-zh source | Build disabled: "no Chinese raws for this novel" | form disabled with same reason |
| no `OPENROUTER_API_KEY` | Build disabled with "set OPENROUTER_API_KEY and restart nov serve" | same; no estimate |
| `/models` unreachable | estimate shows "price unavailable"; Start disabled | same |
| no setups | — | "Add a translator setup" form shown instead |
| glossary build running | banner "build running: edits are kept" | Start shows "novel busy" (lock) |
| novel locked by another job | Build shows "novel busy: <job>" | same |
| job errors | job panel + check section as today | |

- **Large runs.** `nov serve` has 2 workers, so long runs can occupy both. The docs recommend running big backfills from the CLI. The per-novel lock means sync and builds of **that** novel wait until the run ends.

### 3.8 Code-design notes
- **`translate.sqlite` has one owner** (`TranslateStore`). Phase A, Phase B, CLI and web all change the glossary through typed edits. The prompt subset, staleness and cost to date are views derived from its tables.
- **`novel-core` gains only the publish switch** and its consequences: selection, check, `to_fetch`, pin refusal.
  - Glossary and translation concepts stay out of the core.
  - Rejected: glossary tables in `novel.sqlite`. That gives two migration owners for one file, and every vote would invalidate the app's page cache.
  - Rejected: provenance as the ledger, because `Unchanged` keeps the old provenance.
- **The model seam is `LLM`,** a deep module: callers pass domain requests and get `Charged` results.
  - pydantic-ai, OpenRouter settings, retry policy, cost extraction, price lookup and error classification all stay inside it.
  - Tests inject a `FunctionModel`-backed factory and a fake price table. The adapter's own tests use a fake HTTP transport with recorded OpenRouter bodies.
- **Validation is pure.** It runs in the output validator for the retry, and again before storing.
- **Setups are immutable values;** the URL encodes their identity. Run options (workers, cap) and per-novel norms are not part of a setup.
- **Single writer per store in a run:** the coordinator writes both stores. This keeps `progress` and `Cancelled` on one thread and avoids write contention. Quick edits from the web run concurrently, under WAL and `busy_timeout`.

## 4. Tests

### 4.1 Seams and harness
1. **Pure (CI):**
   - `matching`, `discover`, `validate` (named `pytest.param` cases)
   - `budget` (thread-safe reserve/settle)
   - `setups`
2. **Package integration (CI):**
   - `phase_a` / `phase_b` with real SQLite in `tmp_path`, using fixture-built `NovelStore`s with raw, official and mislabelled sources
   - a `FunctionModel` script keyed by prompt kind
   - a fake price table
   - `models.ALLOW_MODEL_REQUESTS = False` in the package `conftest`
3. **Adapter (CI):**
   - `models.py` against an `httpx.MockTransport`-backed `AsyncOpenAI` client, serving recorded OpenRouter bodies
   - **one `live` test** making one cheap real call (gate G1), excluded by default
4. **App (CI):** Service, CLI and web (TestClient) with an injected `LLM` factory, following the `site` fixture pattern.
5. **Browser (local, `browser` marker):** one Firefox walkthrough of the glossary page.
6. **Core (CI):** `test_store.py` additions.
7. **Local scale check** (`slow`-style, skipped in CI): TM-size discovery time and memory (§3.4).

### 4.2 Case matrix

| id | Layer | Setup | Action | Expected | Invariant |
|---|---|---|---|---|---|
| C1 | core | store at schema v2 with 2 sources | open | `user_version` 3, both `published` | existing sites unchanged |
| C2 | core | upsert new source `published=False`, then upsert same (backend,url) with True | — | stays False | switch owned by user |
| C3 | core | unpublished my-translation is the only text for 5..9 | `selection()` | 5..9 absent; `chapters(src)` lists them | trial never publishes |
| C4 | core | same, `set_published(on)` | `selection()` | 5..9 from it | |
| C5 | core | unpublished setup covers 1..3 of a raw-only novel; one FAILED item | `check()` | no gaps or mixed_parts from it; FAILED item listed | |
| C6 | core | unpublished source | `set_pin` | refused; and `set_published(off)` on a pinned source refused | |
| C7 | core | official-en source lacks 10; published my-translation has 10 | `to_fetch(official)` | includes 10 | official keeps syncing |
| C7b | core | unpublished my-translation has 10; raw-zh source A lacks 10 while raw B has it | `to_fetch(official)`, `to_fetch(A)` | official includes 10; raw branch unchanged (A excludes 10) | |
| C1b | core | existing `test_open_migrates_a_version_1_store` adjusted; created vs migrated store | compare `PRAGMA table_info(source)` | identical | one schema |
| C8 | app | library row with an unpublished setup | `library_row` | its numbers not counted | |
| M1 | pure | entries 天元 / 天元宗 / alias 天元老祖 | match "天元宗弟子" | only 天元宗 | longest first |
| M2 | pure | needs_review entry present | match | in `blocking`, not injected | name gate |
| M3 | pure | same entries, different insertion order | subset_hash | equal; changes when an injected entry's note changes | deterministic |
| M4 | pure | traditional-script raw 萬劍宗, entry 万剑宗 | match after OpenCC | matched | normalization |
| D1 | pure | synthetic chapters with a planted 4-char sect name ×20 | candidates | includes it; excludes common-word fixture | |
| V1–V12 | pure | named params: clean; one CJK char; id missing; ids merged; empty para; paragraph ×3; 94× loop; ratio low; ratio high; "Chapter 12" in body; term missing (soft); pinyin name (soft) | `check` | per §3.6 | |
| BU1 | pure | cap 1.0; 4 threads reserving 0.3 each | reserve | exactly 3 granted until one settles | no overshoot |
| A1 | pkg | fake votes 3/3 same | build | `accepted` | |
| A2 | pkg | votes 2/1 | build | `needs_review` | |
| A3 | pkg | votes agree, official-EN hint differs | build | `needs_review`, both candidates with origins | official not authority |
| A4 | pkg | locked entry; candidate disagrees | build | unchanged | locked never changes |
| A5 | pkg | the fake model, *inside* the classify call for the batch holding term T, applies a user edit to T | build | T keeps the user's `en`/status; new candidates added | edit wins |
| A5b | pkg | user picked T before the run | build `--revote` | T unchanged | edits never overwritten |
| A6 | pkg | two raw sources overlapping | build | each number counted once | one raw per number |
| A7 | pkg | cap below second batch reservation | build | stops after first; "budget reached" | cap |
| A7b | pkg | cap stops the run during hints | build, then build again with a higher cap | the second run finishes the hints; 0 repeat classify calls; terms tallied before the stop resolved | resumable steps |
| A8 | pkg | fake raises OutOfCredit | build | stops; job error | |
| A9 | pkg | rerun with no changes | build | 0 model calls | incremental |
| A10 | pkg | mislabelled official-en source holding MT, not selected for 5 | build hints | no hint call for chapter 5 | hints only from selected official |
| B1 | pkg | 3 chapters, clean fake | translate 1-3 | 3 versions; number/part copied; source unpublished; 3 ledger rows with cost | |
| B2 | pkg | translate 1-2, then 3-4 | — | refs 1..4 present, none vanished | cumulative index |
| B3 | pkg | rerun same | — | 0 calls | resume |
| B3b | pkg | edit term in ch 2; fake returns identical text on re-run | translate --stale | ch 2 not stale afterwards (ledger updated although `Unchanged`) | ledger is truth |
| B4 | pkg | edit term occurring only in ch 2 | stale() | [2] | per-chapter staleness |
| B5 | pkg | needs_review term in ch 2 | translate 1-3 | 1,3 stored; 2 FAILED "blocked: …"; a later clean run of another setup leaves it listed in check | blocked persists |
| B6 | pkg | fake returns a loop, then clean | translate | stored, attempts=2, cost = sum of both | one retry |
| B7 | pkg | loop twice | translate | not stored; FAILED "invalid: loop"; ledger `failed` with both attempts' cost; budget charged | paid failures counted |
| B7b | pkg | cut-off then clean | translate | stored; attempts=2; second request's `max_tokens` = 1.5×; cost = sum of both runs; separate reservation taken | |
| B3c | pkg | raw of ch 2 changes (Phase A re-summarizes 2) | stale() | {2..12} | input_key definition |
| B8 | pkg | soft term miss | translate | stored; ledger `soft_flags=["term:…"]` | |
| B9 | pkg | new_terms in output | translate | `proposed`; not injected next run; never blocks | side channel |
| B10 | pkg | 4 workers; fake blocks on an Event; cancel set after 2 submits, then Event released | translate | no submissions after cancel; in-flight results stored; Cancelled re-raised; spend in log | paid work kept |
| B10b | pkg | same, with KeyboardInterrupt raised in the coordinator | translate | same as B10; workers joined | CLI Ctrl-C |
| B11 | adapter+pkg | 429 Retry-After 1, then OK | translate | stored; one ledger row | |
| B11b | adapter | 429 Retry-After 300; cancel event set after 0.1 s | call | returns `CallFailed(cancelled)` within 1 s | responsive cancel |
| B12 | pkg | sequential mode | translate 1-3 | prompt 2 holds ch1 translated tail; input_key of 3 changes when 2 re-translated | |
| B13 | pkg | register same URL, different config | register | refused | immutable setup |
| B14 | pkg | **published** setup; raw item at 4411, translated as `n4411`; raw realigned to 1465 | translate 1465 / selection / check / prune | `n4411` in skip, reported orphan, absent from selection and grid, no gaps 1466–4410; `n1465` created; prune drops `n4411` | no orphan published |
| B15 | pkg | cap allows 2 chapters' reservations with 4 workers; fake returns one validator retry and one cut-off | translate 1-8 | at most 2 in flight, then "budget reached"; spent ≤ cap with retries active | no overshoot |
| P1–P8 | adapter | recorded bodies: success+cost; success without cost (fallback tokens×price); 402; 429; 500; length; finish error; 200+error | call | cost per body or fallback; OutOfCredit; retried; CallFailed; cut-off; CallFailed; CallFailed | |
| S1 | app | missing key | start translate / estimate | UserError, no job row | |
| S2 | app | translate via Service with fake | run | job done; blocked/failed listed | |
| S3 | app | CLI `translate run` without --yes, answer n | — | no calls | estimate confirm |
| S4 | app | web glossary page | GET, POST pick, POST add | row swapped; status changes; revision bumps; stale count updates | |
| S5 | app | web publish toggle and add setup | POST | `published` flips; setup row appears unpublished | |
| S6 | app | web states table §3.7 (no raws, no key, no setups, locked novel) | GET | messages and disabled controls as specified | |
| W | browser | glossary review flow in Firefox | — | as S4 visually; keyboard focus stays on row | |

### 4.3 Walkthroughs (agent-run; results reported to the user)
- **W1.** Phase A on a **scratch copy** of the Longevity data dir, with the cheapest model. The cap is **approved by the user beforehand** from the shown estimate (likely $1–3). If the cap stops it, run it again to show it resumes. Report:
  - entries by status
  - 10 sampled `needs_review` with candidates
  - cost against the estimate
- **W2.** Glossary page: review 5 entries, lock 1, add 1 manual term. Then `nov translate stale` reflects the edits.
- **W3.** Two setups (two models) translate Longevity 1495–1504 on the scratch copy:
  - Compare one chapter between them and against MtlTings (source 3).
  - Build the site to a scratch dir: unpublished setups are absent.
  - Publish one and rank it above 3: those 10 chapters switch.
- **W4.** Cancel mid-run, from the web and with Ctrl-C in the CLI. Paid results are kept, and the job log shows the spend.
- **W5.** TM: align #4411 → 1465, translate 1–5, check shows no false gaps.

## 5. Gates

| Gate | Resolves | Acceptance |
|---|---|---|
| G1 | Real OpenRouter behaviour, and the TM numbering fix | The `live` test passes with the user's key: cost > 0 recorded, `generation_id` present, `data_collection` allow and deny both accepted for the chosen cheap model. TM #4411 realigned with `nov align item`, `check` clean. |
| G2 | Default models, norms, context mode | A trial of 20–50 Longevity 1495+ chapters across 2–3 setups (user approves the spend). Hard-check false-positive rate under 5% on chapters a human judges fine. Norms saved per novel; the user picks the default Phase A and Phase B models. |
| G3 | Glossary page usability | The W2 browser walkthrough passes; screenshots shown to the user. |

## 6. Security and data
- **Key:** env only; never in logs, provenance, the ledger or the job table. The secret scan already covers `sk-or-`.
- **Raw text** is sent to OpenRouter and its providers. `data_collection` is allowed by default, and `deny` is a per-setup option (decision 16).
- `translate.sqlite` lives beside `novel.sqlite` in the user's data dir.
- **Migration 2→3** is additive. Older code refuses the newer store (existing behaviour), so the app must be updated in one step.

## 7. Slices (each: failing test → code → green → commit)
0. **Workspace:**
   - new package skeleton, dependencies, `uv.lock`
   - import-linter layer
   - `PYDANTIC_AI_NO_BANNER`
   - `ALLOW_MODEL_REQUESTS=False` conftest
1. **Core:** publish switch + selection/check/`to_fetch`/pin + app library counts (C1–C8).
2. **Model seam:** `models.py` + `budget.py` (P1–P8, BU1). The G1 live test is written here (run with the user's key).
3. **TranslateStore glossary + matching** (M1–M4) and typed edits.
4. **Discovery + Phase A** (D1, A1–A10, local scale check) and CLI `glossary build|list|add|set|lock|reject|import-hints`.
5. **Glossary web page** (S4, S6 glossary states, W) and the novel page glossary link. Gate G3.
6. **Validation** (V1–V12).
7. **Setups + ledger + Phase B** (B1–B15) and CLI `translate setup|run|stale|prune`, `publish`.
8. **Translate UI:** add-setup form, Translate form with estimate, publish toggle, setup stats, stale panel (S1–S3, S5, S6).
9. **Walkthroughs W1–W5,** then the gate G2 trial and calibration (the user approves the spend).

## 8. Definition of done
- All CI layers green on windows-latest. `lint-imports` passes with `novel_translate` in the middle layer.
- Gates G1–G3 passed and recorded in §10.
- On the real data: the Longevity glossary is built and reviewed by the user. A setup is published and deployed for 1495–1781 **only if the user chooses to**.
- The plan is updated with implementation notes, and memory is updated.

## 9. Review log
- **r0 baseline review** (independent, 2026-10-20). Folded in:
  - the publish switch
  - `translate.sqlite`
  - cumulative index and explicit number/part
  - realigning TM #4411
  - one raw per number
  - Phase A conflict rule
  - `subset_hash` snapshot
  - cancel keeps paid results
  - blocked chapters as FAILED items
  - per-chapter staleness
  - immutable setup identity
  - import-linter and dependency updates
  - recorded-response tests plus a `live` test
  - default norms until G2
- **r1 draft review** (fresh, 2026-10-20). Folded in:
  - migration numbering (2→3)
  - a ledger in `translate.sqlite` instead of provenance (cost of failed attempts via `capture_run_messages`; `NovelStore.provenance()` dropped)
  - edits never overwritten by Phase A, including `--revote`
  - hints only where the selected version is official-en
  - `to_fetch` change (user: always fetch official)
  - norms per novel and workers as a run option, outside setup identity
  - budget reservations
  - Ctrl-C and shutdown handling with capped Retry-After
  - Phase A upper-bound estimate and scale check
  - library counts and `mixed_parts` limited to published sources
  - pin refusal for unpublished sources
  - orphan handling (`prune`)
  - price lookup behind the seam
  - `subset_hash` and `input_key` defined exactly
  - one client per thread
  - WAL / `busy_timeout`
  - UI states table
  - cut-off retried outside the validator
  - tenacity and the semaphore dropped
  - User answers: official always fetched; default cap $1; `data_collection` allowed by default.
  - Kept although listed as optional cuts: `pypinyin` soft check (cheap, catches a known MtlTings failure) and `import-hints` (seeds Longevity).
- **r2 focused review** (fresh, 2026-10-20). Folded in:
  - Own Retry-After loop with a 60 s cap and a cancel event; SDK retries off; 180 s timeout (B11b).
  - `max_tokens` and reasoning allowance defined; the cut-off retry reserves separately (B7b, B15).
  - Phase A steps resumable via `hinted_at`; classification capped at the estimate; W1 cap approved by the user (A7b).
  - Orphans with versions go to `AlignmentRules.skip` (B14 on a published setup).
  - `server_default` and the existing migration test fixed (C1b).
  - `published` only on `SourceInfo`, via the `upsert_source` keyword.
  - `input_key` defined exactly (B3c).
  - Write order spend → `put_version` → ledger.
  - One `capture_run_messages` context per run.
  - Second Ctrl-C abandons the drain.
  - `to_fetch` negative cases (C7b); pin-range message.
  - Stakeholder wording on ranking.
  - Verdict: ready for user approval with gates G1–G3.

## 10. Implementation notes
(empty)
