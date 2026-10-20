# Open-source ebook/document translators and web-novel LLM translators (as of 2026-10-20)

Method note: repository metadata (stars, license, last push) came from the GitHub REST API on 2026-10-20. Package versions came from the PyPI JSON API. Mechanism claims were checked in shallow clones of the source, not only READMEs, wherever "source" is cited. Source links use `blob/HEAD/` paths. Clones were inspected only, never executed.

## 1. What each tool does, its formats, and its zh->en suitability (with repo metadata)

### Takeaway
Two families exist. (a) Format-preserving ebook/PDF translators: bilingual_book_maker, the Calibre Ebook Translator, epub-translator, PDFMathTranslate and BabelDOC, and TranslateBooksWithLLMs. (b) Glossary-centric novel/game translators from the CJK fan-translation scene: LinguaGacha/KeywordGacha, AiNiee, GalTransl, auto-novel, Glossarion, and lncrawl-translator. Family (b) is mostly JP->ZH. The tools closest to our zh->en, per-chapter, glossary-plus-context pipeline are lncrawl-translator, Glossarion and TranslateBooksWithLLMs. None of them uses a SQLite chapter store keyed by novel the way we do.

### Cited Findings

**Metadata snapshot (GitHub API, 2026-10-20)**

| Repo | Stars | License | Last push | Lang |
|---|---|---|---|---|
| yihong0618/bilingual_book_maker | 9,894 | MIT | 2026-09-30 | Python |
| bookfere/Ebook-Translator-Calibre-Plugin | 2,656 | GPL-3.0 | 2026-10-08 | Python |
| PDFMathTranslate/PDFMathTranslate | 37,705 | AGPL-3.0 | 2026-10-20 | Python |
| funstory-ai/BabelDOC | 9,733 | AGPL-3.0 | 2026-08-05 | Python |
| hydropix/TranslateBooksWithLLMs | 2,533 | AGPL-3.0 | 2026-10-13 (tag v1.5.16) | Python |
| oomol-lab/epub-translator | 871 | MIT | 2026-09-18 | Python |
| KazKozDev/book-translator ("Tolmach") | 122 | AGPL-3.0 | 2026-10-11 | Python |
| Shirochi-stack/Glossarion | 125 | AGPL-3.0 | 2026-10-20 | Python |
| lncrawl/lightnovel-crawler | 2,669 | GPL-3.0 | 2026-10-19 | Python |
| lncrawl/translator | 2 | Apache-2.0 | 2026-08-04 | Python |
| immersive-translate/immersive-translate | 19,385 | none (issues/releases repo, product is proprietary) | 2026-10-18 | n/a |
| xxnuo/MTranServer | 4,717 | Apache-2.0 | 2026-10-19 | C++ |
| UlionTse/translators | 2,697 | GPL-3.0 | 2026-01-26 | Python |
| nidhaloff/deep-translator | 2,046 | Apache-2.0 | 2024-07-23 | Python |

Source for all rows: GitHub REST API `repos/{owner}/{repo}`, for example https://api.github.com/repos/yihong0618/bilingual_book_maker. Other counts were read from repo pages: AiNiee about 6.4k stars and AGPL-3.0 ([repo](https://github.com/NEKOparapa/AiNiee)); LinguaGacha about 2.6k stars, release v0.130.0 dated 2026-10-20 ([repo](https://github.com/neavo/LinguaGacha)); GalTransl about 2.4k stars and GPL-3.0 ([repo](https://github.com/xd2333/GalTransl)); auto-novel about 1.2k stars and GPL-3.0 ([repo](https://github.com/auto-novel/auto-novel)).

**PyPI (2026-10-20):** `bbook-maker` 1.3.1 (2026-09-30, MIT, py>=3.10). `epub-translator` 0.1.10 (2026-05-08, MIT, py 3.11-3.13). `lncrawl-translator` 0.2.2 (2026-07-31, py>=3.9). `BabelDOC` 0.6.4 (2026-07-16, py 3.10-3.13). `pdf2zh` 1.9.11 (2025-07-11). `pdf2zh-next` 2.9.0 (2026-05-15). `translators` 6.0.4 (2026-01-21). `deep-translator` 1.11.4 (2023-06-28, stale). Source: https://pypi.org/pypi/{name}/json, for example https://pypi.org/pypi/lncrawl-translator/json

**Ebook/document translators**

- **bilingual_book_maker (bbm):** a CLI that makes bilingual books from epub, txt, md, srt and pdf. PDF input produces a txt and attempts an epub. Install with `pip install -U bbook_maker`. Backends include OpenAI/Anthropic-format endpoints, any OpenAI-compatible `--api_base`, Gemini, Qwen, Groq, Ollama, LiteLLM, DeepL, Google, Caiyun and Tencent. Custom providers live in `bbm_providers.json`. — [repo README](https://github.com/yihong0618/bilingual_book_maker)
- **Calibre "Ebook Translator" plugin (bookfere), v2.4.2:** the GUI plugin translates any Calibre format (48 input / 20 output formats claimed) plus .srt. Engines are listed in `engines/` (google, deepl, openai, anthropic, genai, deepseek, baidu, youdao, microsoft) plus a `custom.py` engine that parses JSON/XML responses. It requires Calibre >= 5 and is not usable as a standalone library. — [repo](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin); version from [`__init__.py`](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin/blob/HEAD/__init__.py)
- **oomol-lab/epub-translator:** an MIT Python library that translates EPUBs with LLMs while preserving the original text. Translations are inserted by replacing the original or appending text or blocks. — [repo](https://github.com/oomol-lab/epub-translator)
- **PDFMathTranslate (pdf2zh):** a layout-preserving translator for scientific PDFs (formulas, charts, TOC). It offers a CLI, GUI, Docker, MCP and a Zotero plugin. Development of 2.0 moved to PDFMathTranslate-next. It has low relevance to plain-text novels. — [repo](https://github.com/PDFMathTranslate/PDFMathTranslate)
- **BabelDOC:** the PDF translation engine underneath pdf2zh-next. It only supports OpenAI-compatible LLMs, and its README warns that "All APIs of BabelDOC should be considered as internal APIs, and any direct use of BabelDOC is not supported." — [repo](https://github.com/funstory-ai/BabelDOC)
- **TranslateBooksWithLLMs (TBL):** an app with a web UI, CLI and Docker. It handles EPUB, SRT, DOCX, text-based PDF and TXT. Providers include Ollama, OpenAI-compatible servers, OpenAI, Gemini, Mistral, DeepSeek, Poe, OpenRouter (`--provider openrouter`) and NVIDIA NIM. Its glossary docs use a Chinese-novel example (李凡青 -> Li Fanqing), so zh->en novels are an explicit target. — [repo](https://github.com/hydropix/TranslateBooksWithLLMs); [docs/GLOSSARY.md](https://github.com/hydropix/TranslateBooksWithLLMs/blob/HEAD/docs/GLOSSARY.md)
- **KazKozDev/book-translator ("Tolmach"):** translates EPUB, PDF, DOCX and "full novels" with local Ollama models. It is AGPL-3.0 with 122 stars. — [GitHub API](https://api.github.com/repos/KazKozDev/book-translator)

**Browser/immersive-translate-style tools**

- Immersive Translate is a proprietary freemium extension; its GitHub repo has no license. Open alternatives:
  - Read Frog (mengxi-ream/read-frog), listed as "Open Source Immersive Translate". It supports 20+ AI providers via the Vercel AI SDK, plus custom OpenAI-compatible endpoints. — [GitHub](https://github.com/mengxi-ream/read-frog); [Chrome Web Store](https://chromewebstore.google.com/detail/modkelfkcfjpgbfmnbnllalkiogfofhb)
  - KISS Translator, an open-source extension for Chrome, Edge and Firefox. — [alternativeto](https://alternativeto.net/software/immersive-translate/?p=3)
  - MTranServer, an offline MT server (not an LLM) that exposes `/imme` and `/kiss` endpoints mimicking those plugins. — [repo](https://github.com/xxnuo/MTranServer); [docsearch](https://docsearch.algolia.com/mcp/docs/repo/xxnuo/mtranserver)
  - MouseTooltipTranslator, an MIT Chrome extension with 1,356 stars. — [GitHub API](https://api.github.com/repos/ttop32/MouseTooltipTranslator)
- These are interactive reading aids with no batch, glossary-store pipeline, so their reuse value for us is nil.

**Web-novel/CJK translators**

- **lightnovel-crawler (lncrawl):** a crawler and ebook generator, GPL-3.0, Python 3.9+. Its README says it "Translates while it downloads: Multi-engine translation with failover, driven by `lncrawl-translator`", and that "A per-novel glossary keeps character and place names consistent." Server mode (`lncrawl server --port 8181`) gives a multi-user library with a reader. — [repo](https://github.com/lncrawl/lightnovel-crawler)
- **lncrawl/translator (`lncrawl-translator`):** an Apache-2.0 "stateless translation engine behind lightnovel-crawler" for metadata and HTML chapters. Its main targets are CN/KR/JP->EN. Backends are OpenAI-compatible LLMs, DeepL, Baidu, and a keyless Bing lane, which is the default. — [repo](https://github.com/lncrawl/translator)
- **Glossarion:** a PySide6 desktop GUI for novels, manga, subtitles and documents, with KR/JP/CN presets. It handles EPUB, TXT, PDF, SRT/ASS/LRC, MD, JSON, CSV, HTML and images. — [repo](https://github.com/Shirochi-stack/Glossarion)
- **LinguaGacha (neavo):** a "next-gen" translator for novels, games and subtitles in 16 languages. It handles TXT, EPUB, PDF, MD, subtitles, and many game engine formats (RenPy, Godot, RPG Maker, WolfRPG). It is now a TypeScript/Electron app with an "AGENT" mode. The checkout has no LICENSE file; the README asks for attribution and requires the author's authorization for commercial use. — [README_EN](https://github.com/neavo/LinguaGacha/blob/HEAD/README_EN.md)
- **KeywordGacha:** a glossary-generation tool by the same author. Its README now says LinguaGacha supersedes it ("建议直接使用 LG 一次性完成 术语+翻译+审校"). It also states that a high-quality glossary is "the most important means" of translation quality. — [README](https://github.com/neavo/KeywordGacha)
- **AiNiee:** an AGPL-3.0 tool for games (Mtool, RenPy, Translator++), EPUB/TXT, subtitles, and Word/PDF/MD/PPT. It has an AI glossary and an "AI forbidden translation" table, plus multi-key round-robin. — [repo](https://github.com/NEKOparapa/AiNiee)
- **GalTransl:** GPL-3.0, for JP->ZH visual novels. It has GPT dictionaries, pre/post dictionaries, conditional dictionaries, and problem detection. — [repo](https://github.com/xd2333/GalTransl)
- **auto-novel:** the site behind n.novelia.top, a JP light-novel machine-translation site (Kotlin server, Vue web, TypeScript translator package). The README warns it is "not designed for personal deployment." — [repo](https://github.com/auto-novel/auto-novel)
- **Small zh/web-novel repos from GitHub search** (search API, 2026-10-20):
  - stenlysayd/novel_epub_translator (MIT, 2 stars)
  - Rann27/lwntl ("AI-powered desktop app for translating Light Novels and Web Novels, with glossary management and multi-provider", TypeScript, 2 stars)
  - qw02/llm-novel-translator (AGPL-3.0 Chrome extension, "series-specific glossary", 2 stars)
  - DebanganThakuria/arcane-translator (Apache-2.0 Go/SvelteKit local-first CN/KR/JP reader, 0 stars)
  - PapaKoftes/ManuScribe (offline multi-pass, 0 stars)
  - oodadoudou/Transoria ("novel translation, glossary management", 75 stars, no license)
  - seizue/Shuka (C#, Chinese web novel downloader plus MTL, MIT, 7 stars)
  - Abdullahhani69/AI-novel-scraper-translator (Ollama, 0 stars)
  - shahriar-ahmed-seam/ln-translator (two-pass ES->EN with a persistent cross-volume glossary)

  Source: GitHub search API, for example https://api.github.com/search/repositories?q=novel+translation+glossary

### Inferences
- For zh->en web novels specifically, lncrawl-translator (built for CN->EN chapters, with glossary and new-term return), Glossarion and TBL are the most on-target. The CJK-scene tools (LinguaGacha, AiNiee, GalTransl, auto-novel) are JP->ZH-first, but their glossary and QA mechanics are language-agnostic and the most mature.
- The xianxia-specific repos are tiny (0-3 stars). No large, maintained "xianxia LLM translator" project exists to reuse wholesale.

### Gaps
- No primary-source star counts for SakuraLLM, Read Frog or KISS Translator: the GitHub API rate limit was hit.
- No r/noveltranslations or r/LocalLLaMA threads surfaced in two searches; see Q7.

## 2. Importable library or app only, and API surface

### Takeaway
Only three tools are real importable Python libraries: `lncrawl-translator` (`TranslatorService`), `epub-translator` (`translate()` plus `LLM`), and `bbook-maker`, which is CLI-first. BabelDOC disclaims its API. Everything else is a GUI, web app or plugin. For a uv project, lncrawl-translator is the only one whose API matches a "translate one chapter with a glossary" call, and even it is HTML-oriented and synchronous.

### Cited Findings
- **lncrawl-translator:**
  - A thread-safe synchronous `TranslatorService` facade with `detect`, `translate_text` and `translate_html`. The two translate methods accept a `threading.Event` for cancellation and a timeout; errors share a `TranslatorError` base.
  - `create_app()` mounts a FastAPI-style dashboard.
  - HTTP: `POST /translate/text` (batched short strings) and `POST /translate/html` (one chapter per call). The HTTP API is unauthenticated by design.
  - Python 3.9+, on PyPI and GHCR.
  - [repo](https://github.com/lncrawl/translator)
- **epub-translator:** `pip install epub-translator` (Python 3.11-3.13).
  - `LLM(key, url, model, token_encoding, cache_path, timeout, temperature, top_p, retry_times=5, retry_interval_seconds=6.0, log_dir…)`
  - `translate(source_path, target_path, target_language, submit, user_prompt, max_group_tokens=2600, concurrency=1, llm|translation_llm+fill_llm, on_progress, on_fill_failed, max_retries=5)`
  - `SubmitKind` (REPLACE / APPEND_TEXT / APPEND_BLOCK), and `FillFailedEvent` with `error_message`, `retried_count` and `over_maximum_retries`.
  - Token counters: `total_tokens`, `input_tokens`, `input_cache_tokens`, `output_tokens`.
  - [repo](https://github.com/oomol-lab/epub-translator)
- **bbm:** installed as `bbook_maker` and driven via the CLI (`make_book.py` / `bbook_maker args`). The README documents no library API. — [repo](https://github.com/yihong0618/bilingual_book_maker)
- **BabelDOC:** the README points users to pdf2zh-next's `high_level.do_translate_async_stream` and says direct use "is not supported". — [repo](https://github.com/funstory-ai/BabelDOC)
- **PDFMathTranslate:** has a Python API and an HTTP API (docs/APIS.md). — [repo](https://github.com/PDFMathTranslate/PDFMathTranslate)
- **TBL:** a web UI (localhost:5000), a CLI `translate.py` (`-i -o -sl -tl -m --provider --parallel --refine --text-cleanup --tts`), Docker, and a glossary REST API. It contains a `translation_api.py` but documents no library API. — [repo](https://github.com/hydropix/TranslateBooksWithLLMs); [GLOSSARY.md TOC "REST API"](https://github.com/hydropix/TranslateBooksWithLLMs/blob/HEAD/docs/GLOSSARY.md)
- **Glossarion:** a GUI launched via `src/translator_gui.py`; no programmatic API is documented. — [repo](https://github.com/Shirochi-stack/Glossarion)
- **GUI apps with no library API:** LinguaGacha (Electron, plus a `docs/CLI.md`), AiNiee (PyQt) and GalTransl (desktop plus terminal runner). — [LinguaGacha](https://github.com/neavo/LinguaGacha); [AiNiee](https://github.com/NEKOparapa/AiNiee); [GalTransl](https://github.com/xd2333/GalTransl)
- **`deep-translator`:** a library with ChatGPT support from v1.11.0 (`pip install deep-translator[ai]`). It is a one-shot `translate(text)` wrapper with no glossary or context. Last release was 1.11.4 in 2023-06. — [repo](https://github.com/nidhaloff/deep-translator); [PyPI JSON](https://pypi.org/pypi/deep-translator/json)
- **`translators`:** 39 traditional MT web services (Google, Bing, Baidu, Youdao, Caiyun, DeepL…) and **no LLM engines**. Its debug tips mention 429s from high-frequency requests. — [repo](https://github.com/UlionTse/translators)

### Inferences
- Don't adopt `translators` or `deep-translator`. Neither has a glossary or context, and the LLM support in `deep-translator` is a thin OpenAI call on a package that has been stale since 2023.
- Wrapping lncrawl-translator would bring in a GPL-adjacent ecosystem (the translator itself is Apache-2.0), YAML config and an HTTP-first design. Copying its prompt and parse patterns (Q3, Q6) is cheaper than depending on it.

### Gaps
- epub-translator's internal grouping algorithm is not documented in the README.

## 3. Glossary/terminology support and how it is injected into prompts

### Takeaway
The near-universal pattern is to inject only the glossary entries whose source term occurs in the current chunk. LinguaGacha, AiNiee, GalTransl, auto-novel, lncrawl-translator, TBL, Glossarion and bbm all do this, which matches our "matched glossary subset" design. The notable variations are:
- glossary-free LLM term discovery returned alongside the translation (lncrawl-translator's `<NEW_TERMS>`)
- character gender entries injected for pronoun correctness (TBL, Glossarion)
- placeholder substitution instead of prompting (Calibre plugin, Sakura fallback)
- keeping the glossary in the fresh tail message so the prompt cache survives (bbm)

### Cited Findings
- **lncrawl-translator:**
  - Test `filter_glossary({"萧炎": "Xiao Yan", "药老": "Yao Lao"}, ["萧炎走了进来"]) == {"萧炎": "Xiao Yan"}` shows only present terms are sent. — [tests/test_prompts.py](https://github.com/lncrawl/translator/blob/HEAD/tests/test_prompts.py)
  - The prompt renders "Glossary — use these exact translations for these terms, every time they occur:" followed by `- src => dst` lines. — [translator/engines/prompts.py](https://github.com/lncrawl/translator/blob/HEAD/translator/engines/prompts.py)
  - With `extract_terms`, the system prompt asks for `<NEW_TERMS>{json}</NEW_TERMS>` after `<TRANSLATION>…</TRANSLATION>`: proper nouns NOT in the glossary, keyed by the exact source-text term, with the rendering actually used as the value ("Never use a translated term as a key"). — [prompts.py](https://github.com/lncrawl/translator/blob/HEAD/translator/engines/prompts.py)
  - The pipeline drops new_terms already in the glossary and merges the rest into a `running_glossary` across chapters. — [core/pipeline.py](https://github.com/lncrawl/translator/blob/HEAD/translator/core/pipeline.py)
  - Non-LLM engines enforce glossaries differently: Bing wraps terms in dictionary markup, and DeepL and Baidu tests assert terms are "enforced". — [tests](https://github.com/lncrawl/translator/tree/HEAD/tests)
- **TBL:**
  - "The glossary block is injected into the LLM system prompt only for chunks where a term actually appears." The block has a `# GLOSSARY - REQUIRED TRANSLATIONS` / `MANDATORY` header and lines like `- 李凡青 -> Li Fanqing  [character]` with categories.
  - "Entries may also carry a character gender, which is injected into every chunk so pronouns stay correct even where the source omits the subject."
  - The docs cover a per-chunk filter, auto-extract via LLM/NER, an "Auto mode" (one extra LLM call to derive glossary and style), and correcting the glossary mid-translation.
  - [docs/GLOSSARY.md](https://github.com/hydropix/TranslateBooksWithLLMs/blob/HEAD/docs/GLOSSARY.md); [README](https://github.com/hydropix/TranslateBooksWithLLMs)
- **Glossarion:**
  - `glossary_compressor.py` "Filters glossary entries based on source text to reduce token usage". It supports a token-efficient CSV with `=== SECTION ===` headers, JSON, and a raw-name fallback.
  - The shared `glossary_matching.py` treats any entry that carries a gender as a personal name.
  - `gender_tracking.py` resolves character gender ("automatic_chapter_gender").
  - AI glossary extraction from EPUB/TXT, duplicate merging, and JSON/MD import/export with validation.
  - [src/glossary_compressor.py](https://github.com/Shirochi-stack/Glossarion/blob/HEAD/src/glossary_compressor.py); [src/glossary_matching.py](https://github.com/Shirochi-stack/Glossarion/blob/HEAD/src/glossary_matching.py); [src/gender_tracking.py](https://github.com/Shirochi-stack/Glossarion/blob/HEAD/src/gender_tracking.py); [README](https://github.com/Shirochi-stack/Glossarion)
- **AiNiee:** `build_glossary_prompt` calls `GlossaryHelper.collect_matched_rows(...)` with optional `case_sensitive` and `whole_word` matching. It emits a `原文|译文|备注` (source|translation|note) table, and only matched rows are included. — [ModuleFolders/Domain/PromptBuilder/PromptBuilder.py](https://github.com/NEKOparapa/AiNiee/blob/HEAD/ModuleFolders/Domain/PromptBuilder/PromptBuilder.py)
- **LinguaGacha:** the prompt builder receives `activated_glossary_entries` ("runner 已按原文完成激活", i.e. activated against the source text). It appends a preceding-context block and then a glossary block (`src -> dst` plus notes). Sakura models get the special format "根据以下术语表（可以为空）…". — [src/backend/batch-translation/work-unit/work-unit-prompt-builder.ts](https://github.com/neavo/LinguaGacha/blob/HEAD/src/backend/batch-translation/work-unit/work-unit-prompt-builder.ts)
- **GalTransl:** "GPT dictionary" entries (characters, pronouns, hard terms) are sent only when the term appears in the current names or sentences. Separate pre-translation and post-translation replacement dictionaries exist, plus a conditional post-dictionary with `[or]`/`[and]` and "!" (replace-if-absent) syntax. — [repo README](https://github.com/xd2333/GalTransl); [GalTransl/Dictionary.py](https://github.com/xd2333/GalTransl/blob/HEAD/GalTransl/Dictionary.py)
- **auto-novel:** the OpenAI prompt filters glossary entries with `lines.some(line => line.includes(jp))` and prefixes "翻译的时候参考下面的术语表". The Sakura prompt uses the same "根据以下术语表" format, and one fallback path does a raw `replaceAll(wordJp, glossary[wordJp])` with longest keys first. — [packages/translator/src/translator/openai-prompt.ts](https://github.com/auto-novel/auto-novel/blob/HEAD/packages/translator/src/translator/openai-prompt.ts); [sakura-prompt.ts](https://github.com/auto-novel/auto-novel/blob/HEAD/packages/translator/src/translator/sakura-prompt.ts)
- **Calibre Ebook Translator:** the glossary is placeholder substitution, not prompting. `replace()` swaps each source term for a numbered placeholder (`format(wid,'06')`) before translation, and `restore()` regex-substitutes the target term back afterwards. — [lib/translation.py](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin/blob/HEAD/lib/translation.py)
- **bbm:**
  - `--glossary/--terminology` takes `term → translation` lines, and `Glossary.matches(source_text)` selects the entries per unit.
  - `--glossary-auto on` learns renderings from the context-compaction "handoff report". The report is parsed from a `<renderings>` block that tolerates truncation, with sanity bounds (term <= 60 chars, rendering <= 120, not sentence-shaped).
  - The learned glossary merges into the pinned one with conflict reporting.
  - Design rule: "Anything that varies per unit (the glossary block) rides in the fresh tail message, never in the prefix", which preserves prompt caching.
  - [book_maker/glossary.py](https://github.com/yihong0618/bilingual_book_maker/blob/HEAD/book_maker/glossary.py); [book_maker/session_context.py](https://github.com/yihong0618/bilingual_book_maker/blob/HEAD/book_maker/session_context.py); [README](https://github.com/yihong0618/bilingual_book_maker)
- **BabelDOC:**
  - `--glossary-files` takes CSV files with `source`, `target` and optional `tgt_lng` columns. Matching terms are added to the LLM prompt.
  - Automatic term extraction is on by default (`--no-auto-extract-glossary`, `--save-auto-extracted-glossary`, `--term-pool-max-workers`).
  - [repo](https://github.com/funstory-ai/BabelDOC)
- **AiNiee and novel_epub_translator (other mechanisms):**
  - AiNiee has a "forbidden translation" (keep-as-is) table. — [repo](https://github.com/NEKOparapa/AiNiee)
  - novel_epub_translator extracts categorized entities (characters, organizations, locations, power systems, artifacts, terminology) from the first 4 chapters into `glossary.json`. A separate `repair_map.json` post-pass rewrites only text nodes, longest-match first. — [repo](https://github.com/stenlysayd/novel_epub_translator)
- **epub-translator:** no glossary; only a free-form `user_prompt`. — [repo](https://github.com/oomol-lab/epub-translator)

### Inferences
- Our "resolve glossary, then send the matched subset" design is the industry consensus. Worth adding:
  - (a) a `NEW_TERMS` side-channel in the translation call to feed term discovery, with keys forced to be exact source substrings so we can verify them deterministically
  - (b) gender/pronoun attributes on character entries, which matters for zh, where pronouns are often dropped (DITING's "zero-pronoun resolution" dimension, Q7)
  - (c) category tags in the injected lines
  - (d) putting the per-chapter glossary block after the stable prefix (system prompt plus style) so OpenRouter/provider prompt caching hits
- TBL injects into the system prompt, which bbm's analysis says defeats prefix caching.
- Placeholder substitution (Calibre) is brittle for Chinese, because terms nest and overlap (e.g. 萧炎 inside 萧炎哥哥) and placeholders break grammar. Prefer prompt injection plus post-validation.

### Gaps
- How Glossarion orders or prioritizes entries when the compressed glossary is still large was not determined.

## 4. Chunking, context strategy, batching, caching and resume

### Takeaway
- **Chunking:** token-budgeted groups (TBL 450 tokens default, epub-translator 2,600, Calibre merge 1,800 chars, bbm `--accumulated_num`).
- **Context:** either the "last N source/translation pairs" window (bbm window mode, LinguaGacha precedings, GalTransl `contextNum`, Glossarion rolling history) or bbm's novel session mode. Session mode is an append-only conversation for prompt caching, compacted into a model-written "handoff report" at a token budget.
- **Resume:** per-item caches keyed by content (Calibre, epub-translator `cache_path`, GalTransl cache with `retranslKey`, novel_epub_translator chapter/paragraph hashes, Glossarion `translation_progress.json`, bbm `--resume`).

### Cited Findings
- **bbm context modes:**
  - Window mode (`--use_context`) "re-sends the last few (source, translation) pairs on every request, which costs roughly six extra copies of the book for three paragraphs of context."
  - Session mode (`--use_context session`) keeps one append-only history whose byte-stable prefix is billed at the cache rate ("0.1-0.23x on current endpoints").
  - At `--context-compact-at` (default 8192 tokens, min 1500) the model writes a handoff report (summary, style, and optionally `<renderings>`). It is saved as `<book>_handoff.md` and seeds the next window. The seed is bounded, because "an unbounded seed is a death loop."
  - [session_context.py](https://github.com/yihong0618/bilingual_book_maker/blob/HEAD/book_maker/session_context.py); [README](https://github.com/yihong0618/bilingual_book_maker)
- **bbm other flags:**
  - `--block_size` merges paragraphs and `--accumulated_num` sets a token threshold per request.
  - `--batch/--batch-use` uses the OpenAI Batch API, which is refused for EPUB.
  - `--resume` cannot be combined with `--parallel-workers`.
  - Ctrl+C leaves a `_bilingual_temp` file, and `--test` translates only the first paragraphs.
  - [README](https://github.com/yihong0618/bilingual_book_maker)
- **LinguaGacha:**
  - The prompt includes a "preceding context" block of the previous items' source lines.
  - A planner with a token-count cache and a worker pool splits work units.
  - On failure, multi-item units are halved for 2 rounds (`TRANSLATION_HALVING_ROUNDS = 2`), then single items get 1 retry (`TRANSLATION_SINGLE_RETRY_LIMIT = 1`) before being marked ERROR. The code comment says quality control was moved to the AGENT flow, so batch translation does only "limited convergence".
  - It has item and file caches in `src/backend/cache/`.
  - [work-unit-prompt-builder.ts](https://github.com/neavo/LinguaGacha/blob/HEAD/src/backend/batch-translation/work-unit/work-unit-prompt-builder.ts); [planning/translation-retry.ts](https://github.com/neavo/LinguaGacha/blob/HEAD/src/backend/batch-translation/planning/translation-retry.ts); [src/backend/cache](https://github.com/neavo/LinguaGacha/tree/HEAD/src/backend/cache)
- **GalTransl:** `gpt.contextNum` sets how many recent translated lines are re-supplied when a multi-turn session resets. Its `transl_cache` JSON can be edited to force retranslation, either by deleting the `pre_zh` line or by setting `retranslKey` to a problem name to retranslate every sentence flagged with that problem. — [README](https://github.com/xd2333/GalTransl); [GalTransl/Cache.py](https://github.com/xd2333/GalTransl/blob/HEAD/GalTransl/Cache.py)
- **Glossarion:** a rolling history window with configurable "contextual memory depth" and chunking for long chapters. It translates chapters in parallel with concurrent chunks and stores progress in `translation_progress.json` for resume. — [README](https://github.com/Shirochi-stack/Glossarion); [src/history_manager.py](https://github.com/Shirochi-stack/Glossarion/blob/HEAD/src/history_manager.py)
- **TBL:**
  - Token chunking with `MAX_TOKENS_PER_CHUNK=450`, and `--parallel N` on cloud providers only (Ollama stays at 1).
  - Checkpoint/resume.
  - An optional `--refine` second pass for literary polish.
  - [README](https://github.com/hydropix/TranslateBooksWithLLMs)
- **epub-translator:** groups capped by `max_group_tokens` (default 2600), concurrency with order preserved, and a `cache_path` for cache and resume. — [repo](https://github.com/oomol-lab/epub-translator)
- **Calibre plugin:** the "merge" option (`merge_enabled`, `merge_length` 1800) concatenates paragraphs with a separator. `is_alignment()` checks that the split counts of original and translation match. The cache persists per book identity, and the cache listing records engine, language and merge_length. — [lib/config.py](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin/blob/HEAD/lib/config.py); [lib/cache.py](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin/blob/HEAD/lib/cache.py); [README](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin)
- **lncrawl-translator:** HTML is one chapter per call. `HtmlContext` (context lines) is threaded into the user turn, and short strings are batched as a JSON array. — [prompts.py](https://github.com/lncrawl/translator/blob/HEAD/translator/engines/prompts.py)
- **novel_epub_translator:** a thread pool (default 3 workers) and a chapter/paragraph hash cache so reruns skip completed work. — [repo](https://github.com/stenlysayd/novel_epub_translator)
- **BabelDOC:** `--max-pages-per-part` splits large docs, there is a translation cache (`--ignore-cache`), and `--qps` defaults to 4. — [repo](https://github.com/funstory-ai/BabelDOC)

### Inferences
- Our unit is one chapter. A typical xianxia chapter is 2-4k Chinese characters, roughly 3-6k tokens in and out, so we don't need sub-chapter chunking except as a fallback.
- LinguaGacha's halving-on-failure is a good fallback to adopt: if a chapter fails validation twice, split it at paragraph boundaries and translate the halves.
- bbm's measured economics support a stable prefix (system prompt, style guide, maybe a novel synopsis), with the variable glossary and rolling context in the tail.
- For rolling context, a handoff summary (bbm) is cheaper than raw previous-chapter text. GalTransl's `contextNum` and Glossarion's "memory depth" are both about N prior translated lines.
- A "retranslate everything flagged with problem X" key (GalTransl `retranslKey`) maps naturally onto SQLite: keep a validation-flags table and add a CLI "retranslate where flag = …".

### Gaps
- Glossarion's exact history format (full prior chapter vs. summary) is not documented in the README.

## 5. OpenAI-compatible/OpenRouter support, retry, rate limits and cost tracking

### Takeaway
- **OpenRouter:** explicitly supported by bbm (`--api_base https://openrouter.ai/api/v1`), TBL (`--provider openrouter`) and Glossarion (`or/*` prefix). Most others accept any OpenAI-compatible base URL.
- **Retry and rate limits:** usually simple (fixed RPM intervals, multi-key rotation, exponential backoff). lncrawl-translator has the most structured router: client-side RPM, cooldowns and quota-aware failover.
- **Cost tracking:** essentially absent. epub-translator exposes token counters (including cached input tokens) and bbm reasons about cache-rate economics; nobody records dollar cost.

### Cited Findings
- **bbm:**
  - OpenRouter example `--api_base https://openrouter.ai/api/v1`; custom providers in `bbm_providers.json`. — [README](https://github.com/yihong0618/bilingual_book_maker)
  - Its ChatGPT translator sets `REQUEST_LIMITS = {"timeout": 300.0, "max_retries": 1}`. It handles `RateLimitError, APIConnectionError, APITimeoutError, InternalServerError` and uses tenacity `retry_if_exception_type`. — [book_maker/translator/chatgptapi_translator.py](https://github.com/yihong0618/bilingual_book_maker/blob/HEAD/book_maker/translator/chatgptapi_translator.py)
- **TBL:** OpenRouter "200+ models", comma-separated API keys rotated on rate limit, `REQUEST_TIMEOUT` 900 s; no cost tracking mentioned. — [README](https://github.com/hydropix/TranslateBooksWithLLMs)
- **Glossarion:** 40+ providers including OpenRouter (`or/*`) and any OpenAI-compatible base URL. It auto-retries timeouts, truncations and 5xx errors, rotates multiple keys on 429/5xx, and uses exponential backoff; no cost tracking. — [README](https://github.com/Shirochi-stack/Glossarion)
- **lncrawl-translator:** "Client-side rate limiting, retries, cooldowns, and quota-aware failover across lanes." `core/limits.py` computes the interval as `60.0 / settings.rpm` and keeps per-engine failure cooldowns, with "a much longer cooldown" for quota-tier failures. The router benches failing engines and reports `retry_at`. It also strips `<think>…</think>` reasoning blocks and code fences before parsing. — [README](https://github.com/lncrawl/translator); [core/limits.py](https://github.com/lncrawl/translator/blob/HEAD/translator/core/limits.py); [core/router.py](https://github.com/lncrawl/translator/blob/HEAD/translator/core/router.py); [engines/prompts.py](https://github.com/lncrawl/translator/blob/HEAD/translator/engines/prompts.py)
- **AiNiee:** `RequestLimiter` is a simple RPM gate (`request_interval = 60 / rpm_limit`, with a lock) with a 600,000-token request cap, plus multi-key round-robin. — [ModuleFolders/Infrastructure/RequestLimiter/RequestLimiter.py](https://github.com/NEKOparapa/AiNiee/blob/HEAD/ModuleFolders/Infrastructure/RequestLimiter/RequestLimiter.py); [README](https://github.com/NEKOparapa/AiNiee)
- **epub-translator:** any OpenAI-compatible URL, `retry_times` 5 and `retry_interval_seconds` 6.0, plus token counters `input_cache_tokens` etc. — [repo](https://github.com/oomol-lab/epub-translator)
- **Calibre plugin:** settings include `concurrency_limit` (default 1), `request_attempt` (default 3) and `request_interval` (default 5 s); engines include openai, anthropic, deepseek, genai and custom. — [lib/config.py](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin/blob/HEAD/lib/config.py); [engines/](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin/tree/HEAD/engines)
- **BabelDOC:** only OpenAI-compatible LLMs (`--openai-base-url`), with `--qps` 4. — [repo](https://github.com/funstory-ai/BabelDOC)
- **arcane-translator:** Bedrock, Anthropic, and a LiteLLM gateway; no OpenRouter. It stores data in SQLite. — [repo](https://github.com/DebanganThakuria/arcane-translator)

### Inferences
- Nobody provides cost tracking we could reuse. OpenRouter returns usage and cost per generation, so our store should record tokens, cached tokens and cost per chapter attempt ourselves.
- lncrawl-translator's limits and router (RPM pacing, cooldown with `retry_at`, failure-class-specific benching) are the cleanest pattern to copy for a single-provider OpenRouter client with model fallbacks.
- Stripping `<think>` blocks before parsing is needed for reasoning models routed via OpenRouter.

### Gaps
- No tool documents handling of OpenRouter-specific features (provider routing, `usage: {include: true}`, cache-control) found.

## 6. Validation and quality checks

### Takeaway
The CJK fan-translation tools have the richest deterministic checks, which suit our "deterministic validation" stage:
- line/paragraph count match
- residual source script
- returned-original or high similarity
- glossary-not-applied
- placeholder/markup preservation
- punctuation mismatch
- repetition (word frequency)
- abnormal length ratio
- English or wrong-language introduced
- empty or refused responses

Most failures trigger a retry, and some are only flagged for later re-translation.

### Cited Findings
- **AiNiee `ResponseChecker`:** basic checks are always on:
  - refusal or format error (no special chars)
  - line count mismatch
  - empty lines
  - numbered order (`check_dict_order`, catching shifted or merged lines)

  Optional checks: newline count per multiline block, returned-original (translation equals source), residual source-language text, single/multi-line reply format, and placeholder preservation. A separate `TranslationResultCheck` covers exclusion lists, placeholder residue, numbered-prefix leakage and leaked "example text" from the prompt. — [ModuleFolders/Domain/ResponseChecker/ResponseChecker.py](https://github.com/NEKOparapa/AiNiee/blob/HEAD/ModuleFolders/Domain/ResponseChecker/ResponseChecker.py); [TranslationResultCheck.py](https://github.com/NEKOparapa/AiNiee/blob/HEAD/ModuleFolders/Domain/TranslationResultCheck/TranslationResultCheck.py)
- **LinguaGacha proofreading warning codes:** `FOREIGN_CHAR_RESIDUE` (with fragments), `SIMILARITY` (source vs. translation), `LINE_COUNT_MISMATCH`, `GLOSSARY` (per-entry `glossary_applications` with an `applied: bool` per field), `TEXT_PRESERVE` (protected code or markup fragments) and `PUNCTUATION_MISMATCH`. — [src/shared/proofreading/proofreading-types.ts](https://github.com/neavo/LinguaGacha/blob/HEAD/src/shared/proofreading/proofreading-types.ts); [proofreading-evaluator.ts](https://github.com/neavo/LinguaGacha/blob/HEAD/src/shared/proofreading/proofreading-evaluator.ts); [agent/workspace/schema.ts](https://github.com/neavo/LinguaGacha/blob/HEAD/src/backend/agent/workspace/schema.ts)
- **GalTransl problem list:**
  - 词频过高: a character repeated more than 20 times and far more than in the source
  - 标点错漏: brackets, quotes or colons mismatched
  - 残留日文: leftover kana, or output identical to the source
  - 丢失换行 / 多加换行: lost or added newlines
  - 比日文长: longer than 1.3x the source; a strict zero-tolerance variant also exists
  - 字典使用: GPT dictionary not followed
  - 引入英文: English introduced where the source has none
  - 语言不通 / 缺控制符: wrong language / missing control codes

  Problems are recorded per sentence and drive `retranslKey`. — [plugins/problem_common/problem_common.py](https://github.com/xd2333/GalTransl/blob/HEAD/plugins/problem_common/problem_common.py); [README](https://github.com/xd2333/GalTransl)
- **Glossarion QA scanner:** checks for duplicate content, non-English fragments, spacing and formatting problems, and repetitive patterns. "AI Hunter" detects duplicate chapters by TF-IDF similarity. Reports come out as HTML, JSON or CSV, and a Retranslation GUI exists. — [README](https://github.com/Shirochi-stack/Glossarion); [src/ai_hunter_enhanced.py](https://github.com/Shirochi-stack/Glossarion/blob/HEAD/src/ai_hunter_enhanced.py)
- **lncrawl-translator:** `parse_text_response` raises if the JSON array is missing or the element count differs. The HTML prompt forbids adding, removing, merging or reordering paragraphs, and output must sit between `<TRANSLATION>` markers. — [engines/prompts.py](https://github.com/lncrawl/translator/blob/HEAD/translator/engines/prompts.py)
- **Calibre plugin:** `is_alignment()` compares segment counts split by the merge separator. — [lib/cache.py](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin/blob/HEAD/lib/cache.py)
- **bbm:** reports how a handoff glossary was recovered (`source`, `dropped` counts), so that "a model answering the section with prose is a degraded run, not a clean one" is visible. — [session_context.py](https://github.com/yihong0618/bilingual_book_maker/blob/HEAD/book_maker/session_context.py)
- **ManuScribe:** a three-pass Translate, Refine, Verify pipeline at temperature 0. The verify pass outputs `OK` or `ALTERED: reason`. Row flags are `alignment` (advisory), `glossary_violation` (automatic) and `check` (user). — [repo](https://github.com/PapaKoftes/ManuScribe)
- **epub-translator:** `on_fill_failed` reports recoverable vs. critical XML-fill failures with retry counts. — [repo](https://github.com/oomol-lab/epub-translator)

### Inferences
For zh->en xianxia, a deterministic validator could combine:
- **Han residue:** any CJK Unified Ideographs in the output outside allowed quotes.
- **Paragraph count parity:** match the source paragraph count, with tolerance.
- **Length-ratio bounds:** English characters per Chinese character, roughly 2.5-5x; tune empirically.
- **Glossary-applied check:** for each matched source term, its target rendering appears at least once (case-insensitive), or the term is in an "allowed miss" list.
- **Repetition / degenerate loops:** n-gram frequency, as GalTransl's 词频过高.
- **Leaked prompt artifacts:** "Glossary", "Translation:", markdown fences, `<think>`.
- **Refusal/empty detection:** empty or refused responses.
- **Similarity to previous chapter output:** catches duplicated chapters, as Glossarion's AI Hunter does.

LinguaGacha's per-entry `applied: bool` record is a good schema for storing glossary compliance in SQLite.

### Gaps
- The exact SIMILARITY threshold in LinguaGacha and GalTransl's residual-detection regexes were not extracted.

## 7. Ideas worth borrowing, known weaknesses, and community/benchmark evidence

### Takeaway
No project matches our design end to end. The most reusable ideas are lncrawl-translator's `NEW_TERMS` contract, bbm's cache-aware session plus handoff compaction, TBL/Glossarion gender-carrying glossary entries, LinguaGacha/AiNiee/GalTransl deterministic checks with flag-driven retranslation, and LinguaGacha's batch-halving retry. Weaknesses common to the field are GUI-only packaging, copyleft licenses (AGPL/GPL on most), no cost accounting, and JP-centric defaults. The research benchmark DITING (zh->en web novels) supports DeepSeek-class Chinese-trained models.

### Cited Findings
- **DITING benchmark (arXiv 2510.09116):**
  - The first comprehensive zh->en web-novel translation evaluation framework, with 18K+ expert-annotated sentence pairs.
  - Six dimensions: idiom translation, lexical ambiguity, terminology localization, tense consistency, zero-pronoun resolution and cultural safety.
  - It tested 14 models and found "Chinese-trained LLMs surpass larger foreign counterparts", with DeepSeek-V3 the most faithful and stylistically coherent (overall 5.16 vs. GPT-4o 5.09).
  - AgentEval, a multi-agent evaluator, correlated best with human judgments.
  - [arXiv abstract](https://arxiv.org/abs/2510.09116); [PDF](https://arxiv.org/pdf/2510.09116)
- **Chapter-to-chapter (Ch2Ch) literary translation:** proposes zh-en context-aware translation at chapter granularity; fine-tuning LLMs in that setting improves over baselines. — [arXiv 2407.08978](https://arxiv.org/html/2407.08978v1)
- **Community/vendor advice (secondary, unverified):** for xianxia, compile the complete cultivation system first (realms, sub-realms, energy types), plus a character list with pinyin and a fixed honorifics policy (shixiong, shifu), and a separate glossary for techniques, treasures and pills. — [lexilit.com guide](https://lexilit.com/chinese-web-novels-in-english)
- **llmgateway vendor guide:** chunk with "a running glossary in each prompt" when exceeding the context window. — [llmgateway.io](https://llmgateway.io/models/translation)
- **Weaknesses and limits stated by projects themselves:**
  - BabelDOC's API is unsupported for direct use. — [repo](https://github.com/funstory-ai/BabelDOC)
  - auto-novel is "not designed for personal deployment." — [README](https://github.com/auto-novel/auto-novel)
  - LinguaGacha requires the author's authorization for commercial use and attribution in releases. — [README_EN](https://github.com/neavo/LinguaGacha/blob/HEAD/README_EN.md)
  - bbm refuses `--batch` on EPUB and cannot combine `--resume` with `--parallel-workers`. — [README](https://github.com/yihong0618/bilingual_book_maker)
  - lncrawl-translator's HTTP API is unauthenticated by design. — [repo](https://github.com/lncrawl/translator)
  - TBL runs Ollama only at parallel 1, and PDF output loses the original layout. — [README](https://github.com/hydropix/TranslateBooksWithLLMs)
  - LinguaGacha's own comment says batch translation does only "limited convergence", with quality control moved to the agent flow. — [translation-retry.ts](https://github.com/neavo/LinguaGacha/blob/HEAD/src/backend/batch-translation/planning/translation-retry.ts)
- **Concrete borrowable artifacts:**
  - lncrawl-translator `<TRANSLATION>`/`<NEW_TERMS>` output contract and `filter_glossary`. — [prompts.py](https://github.com/lncrawl/translator/blob/HEAD/translator/engines/prompts.py)
  - bbm's two load-bearing rules for prompt caching and its handoff glossary harvesting with sanity bounds. — [session_context.py](https://github.com/yihong0618/bilingual_book_maker/blob/HEAD/book_maker/session_context.py)
  - TBL's glossary block wording and category tags, gender injected into every chunk, and mid-translation glossary correction. — [GLOSSARY.md](https://github.com/hydropix/TranslateBooksWithLLMs/blob/HEAD/docs/GLOSSARY.md)
  - GalTransl's pre/post/conditional dictionaries (deterministic pre-normalization of the source, e.g. variant characters, and post-fix of the output). — [Dictionary.py](https://github.com/xd2333/GalTransl/blob/HEAD/GalTransl/Dictionary.py)
  - AiNiee's whole-word and case-sensitive glossary match options and its "forbidden translation" (keep-verbatim) list. — [PromptBuilder.py](https://github.com/NEKOparapa/AiNiee/blob/HEAD/ModuleFolders/Domain/PromptBuilder/PromptBuilder.py)

### Inferences
- **Recommendation for a Python/uv project:** don't take a runtime dependency on any of these. Copy patterns instead.
  - lncrawl-translator is Apache-2.0 and the safest to borrow code from, with attribution.
  - bbm and epub-translator are MIT.
  - The richest QA tools (AiNiee, GalTransl, Glossarion, TBL, BabelDOC/pdf2zh) are AGPL or GPL, so their code should not be copied into a non-GPL project; ideas only.
- The `NEW_TERMS` side-channel overlaps with our separate "discover terms" stage. It could replace or augment it, and it is cheaper because it rides on the translation call. The risk is unvetted renderings entering the glossary, so route them to a "proposed" status for resolution rather than auto-pinning, unlike lncrawl's `running_glossary.update`.
- Zero-pronoun resolution is a top zh->en failure mode (DITING), so character gender in the glossary is high-value for xianxia, with its many shixiong/shimei characters.

### Gaps
- No primary Reddit (r/noveltranslations, r/LocalLLaMA) threads on LLM novel workflows surfaced in two searches, including a `site:reddit.com` query. Community practice is represented only by secondary vendor guides and the GitHub projects above.
- GitHub issue trackers were not mined for per-tool bug patterns, because the unauthenticated GitHub API rate limit was hit. Weaknesses above come from READMEs and source comments, not issues.
- SakuraLLM (JP->ZH model used by auto-novel and LinguaGacha) was not profiled; it is not relevant to zh->en.
