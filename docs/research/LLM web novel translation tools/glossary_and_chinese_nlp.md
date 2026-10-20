# Glossary / Terminology Management and Chinese NLP for Xianxia CN->EN Translation

Research date: 2026-10-20. Package versions, dates, stars, licenses and wheel availability were read directly from the PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) and GitHub REST API (`https://api.github.com/repos/<owner>/<repo>`) on that date. "Win wheel" means a `win_amd64`/`abi3` or pure `py3-none-any` wheel exists for the latest release, so `uv add` should not need a C compiler.

## 1. Automatic term extraction from Chinese text: which tools work for xianxia invented terms?

### Takeaway
Classic Chinese segmenters/NER (jieba, HanLP, pkuseg, LAC, LTP, THULAC, spaCy zh, Stanza) are trained on news/web text and will split or miss invented xianxia terms (sect names, techniques, realms, pill names). Only person/place NER is somewhat reliable. The best fit for a uv/Windows pipeline is: (a) a cheap statistical new-word-discovery pass (n-gram frequency + mutual information + left/right entropy, implementable in ~100 lines of Python with no deps) to generate candidates across the whole novel; then (b) an LLM (via OpenRouter) to classify, filter, and render the candidates, i.e. the KeywordGacha approach. jieba-py / rjieba are fine as lightweight segmenters if one is needed; HanLP 2.x is the strongest classical NER but pulls in torch + transformers.

### Cited Findings

**Status table (latest release, license, stars, Windows/py3.12-3.13 install)**

| Tool | Latest release | License | Stars | Install on Win/py3.12-3.13 | Source |
|---|---|---|---|---|---|
| jieba (original) | 0.42.1, 2020-01-20; repo last push 2024-08-21 | MIT | 35.2k | sdist only (pure Python, builds fine without compiler) | [PyPI](https://pypi.org/project/jieba/), [GitHub](https://github.com/fxsjy/jieba) |
| jieba-py (maintained fork) | 0.46.12, 2026-04-20; requires py>=3.10 | MIT | n/a | pure-Python wheel; keeps `import jieba`, conflicts with original jieba (uninstall first); paddle mode removed | [PyPI](https://pypi.org/project/jieba-py), [GitHub](https://github.com/bukun/jieba-py) |
| rjieba (Rust jieba-rs binding) | 0.2.1, 2026-04-25 | MIT | 37 | `cp38-abi3-win_amd64` wheel, so works on 3.12/3.13 | [PyPI](https://pypi.org/project/rjieba/), [GitHub](https://github.com/messense/rjieba-py) |
| HanLP 2.x (`hanlp`) | 2.1.5, 2026-09-15 (repo pushed same day) | Apache-2.0 | 36.5k | pure wheel, but requires `torch>=1.6`, `transformers`, `sentencepiece`; `[full]`/`[tf]` extras pull TensorFlow 2.16 (py3.12) / 2.21 (py3.13) | [PyPI](https://pypi.org/project/hanlp/), [GitHub](https://github.com/hankcs/HanLP) |
| pyhanlp (HanLP 1.x, Java via JPype) | 0.1.89, 2025-01-16; tested on py3.6-3.13 incl. Windows per its page | Apache-2.0 | n/a | needs a JVM | [PyPI](https://pypi.org/project/pyhanlp/) |
| pkuseg | 0.0.25, 2020-06-27; repo last push 2022-11 | MIT | 6.7k | wheels only for cp35-cp37; would need source build on 3.12 | [PyPI](https://pypi.org/project/pkuseg/), [GitHub](https://github.com/lancopku/pkuseg-python) |
| spacy-pkuseg (Explosion fork) | 1.0.1, 2025-07-14 | MIT | 73 | cp312 and cp313 wheels | [PyPI](https://pypi.org/project/spacy-pkuseg/), [GitHub](https://github.com/explosion/spacy-pkuseg) |
| spaCy | 3.8.16, 2026-08-24; py>=3.9,<3.15 | MIT | n/a | cp312/cp313 wheels; zh pipelines use spacy-pkuseg for segmentation | [PyPI](https://pypi.org/project/spacy/), [spacy-pkuseg summary](https://www.pypi.org/project/spacy-pkuseg) |
| Baidu LAC | 2.1.2, 2021-05-25; repo last push 2021-05 | Apache-2.0 | 4.0k | sdist only; depends on PaddlePaddle; effectively abandoned | [PyPI](https://pypi.org/project/LAC/), [GitHub](https://github.com/baidu/lac) |
| LTP (HIT-SCIR) | ltp 4.2.14, 2024-06-08 (repo pushed 2026-03); `ltp-extension` has `cp37-abi3` wheels | no SPDX license detected by GitHub (check repo; historically free for non-commercial/academic use) | 5.3k | pure wheel + abi3 Rust extension; neural models need torch | [PyPI](https://pypi.org/project/ltp/), [GitHub](https://github.com/HIT-SCIR/ltp) |
| THULAC | 0.2.2, 2022-11-07; repo last push 2022-01 | MIT on GitHub | 2.1k | pure wheel | [PyPI](https://pypi.org/project/thulac/), [GitHub](https://github.com/thunlp/THULAC-Python) |
| Stanza | 1.15.0, 2026-10-01; py>=3.9 | Apache-2.0 | 7.9k | pure wheel, needs torch | [PyPI](https://pypi.org/project/stanza/), [GitHub](https://github.com/stanfordnlp/stanza) |
| SmoothNLP (has new-word discovery) | 0.4.0, 2020-06-17; repo **archived** | GPL-3.0 | 622 | pure wheel; archived, avoid | [PyPI](https://pypi.org/project/smoothnlp/), [GitHub](https://github.com/smoothnlp/SmoothNLP) |
| KeywordGacha (LLM glossary extraction) | changelog v0.20.2 dated 2025-06-12 per README; repo pushed 2026-09-22 | GitHub shows no SPDX license (badge present) | 923 | GUI app, portable Windows exe (double-click `app.exe`); no documented CLI/library API | [GitHub](https://github.com/neavo/KeywordGacha), [DeepWiki](https://deepwiki.com/neavo/KeywordGacha) |
| LinguaGacha (sibling translator with built-in term extraction) | repo pushed 2026-10-20 | GitHub shows no SPDX license | 2.6k | GUI app | [GitHub](https://github.com/neavo/LinguaGacha) |

**Capabilities**
- jieba supports precise/full/search segmentation, POS tagging (`jieba.posseg`, which tags `nr` person, `ns` place, `nt` organization, `nz` other proper noun), keyword extraction via TF-IDF and TextRank (`jieba.analyse`), user dictionaries (`load_userdict`/`add_word`), and HMM-based discovery of out-of-vocabulary words — [jieba README](https://github.com/fxsjy/jieba)
- A jieba fork exists because the original is no longer maintained; it targets py>=3.10, drops Py2 and paddle mode, and uses pyproject.toml — [jieba-py PyPI](https://pypi.org/project/jieba-py)
- KeywordGacha uses LLMs for NER/semantic analysis to extract and categorize names and terms that need consistent translation; it supports 16 languages including Chinese, user-defined term types, txt/epub/md input, and output to Excel/JSON (plus a KVJSON output added in v0.20.1) that LinguaGacha can import — [GitHub](https://github.com/neavo/KeywordGacha), [DeepWiki](https://deepwiki.com/neavo/KeywordGacha)
- KeywordGacha supports OpenAI, Anthropic, Google GenAI, VolcEngine, DeepSeek and local endpoints (so any OpenAI-compatible endpoint, which would include OpenRouter); claims "90%+ hit rate vs manually built glossaries" — vendor claim, no independent benchmark — [DeepWiki](https://deepwiki.com/neavo/KeywordGacha)
- New-word discovery principle: internal cohesion measured by mutual information (凝固度), external freedom by left/right neighbor entropy (自由度); candidates are n-grams scoring high on both, then stopword-trimmed and filtered against a known dictionary — [Tencent Cloud article](https://developer.cloud.tencent.com/article/2416088), [joca.cn paper](https://www.joca.cn/CN/Y2020/V40/I12/3513), [kenlm oov.py reference](https://portrait.gitee.com/sheeplu/kenlm/blob/master/oov.py)
- LinguaGacha's glossary guidance: run the agent's term extraction, then manually check names and genders; include only proper nouns; avoid common words, honorifics and whole sentences; split compound terms — [LinguaGacha wiki: Glossary](https://github.com/neavo/LinguaGacha/wiki/Glossary)

### Inferences
- Xianxia terms like 青云宗, 九转玄功, 筑基期, 太乙金仙, 储物戒 recur heavily within a novel but rarely in news corpora. Frequency + MI + left/right entropy over a full novel (millions of characters) should surface them well, because they are internally cohesive and appear in varied contexts. Segmenters trained on news (jieba dict, pkuseg, LAC, THULAC) will often split them into common words. This is inferred from how the algorithm works; I found no benchmark on web-novel corpora.
- jieba `posseg` `nr`/`ns`/`nt`/`nz` tags give reasonable person/place candidates for Chinese names (surname + 1-2 characters). They are weak for epithets (e.g. 血魔老祖) and technique names. Use them as a candidate source, not as the final categorizer.
- Recommended pipeline: (1) normalize with OpenCC (t2s) → (2) n-gram MI/entropy candidate mining over the whole novel (no dependency; optionally rjieba/jieba-py to drop candidates that are already common dictionary words) → (3) rank by frequency, keep the top N → (4) an LLM batch prompt with a few context snippets per candidate assigns category (person/place/sect/technique/item/realm/creature/title), English rendering and aliases, and rejects non-terms → (5) human review of high-frequency entries. This is what KeywordGacha does internally, but it is a GUI app with no license shown, so reimplementing the small LLM step in-house is easier than embedding it.
- HanLP 2.x has the best classical Chinese NER, but its torch + transformers dependency (multi-GB on Windows) is not worth it when an LLM pass is already planned. Skip LAC (Paddle, abandoned), original pkuseg (no py3.12 wheels), SmoothNLP (archived, GPL), and THULAC (stale).

### Gaps
- No benchmark found comparing these tools on web-novel/xianxia text. No accuracy figures exist for invented-term extraction.
- HanLP 2.x pretrained model download sizes were not verified in this session.
- The LTP license could not be confirmed (GitHub reports no SPDX license). Check the repo LICENSE before use.
- KeywordGacha's license and exact JSON output schema were not shown on the README. The `chinese-new-word-discovery` repo name given in the brief could not be found at the guessed GitHub path.

## 2. Bilingual term alignment from aligned raw/English chapter pairs

### Takeaway
Chapter-level pairs need sentence alignment first. Bertalign (LaBSE-based, designed and evaluated for Chinese-English literary text) or vecalign are the right tools; hunalign is weaker for ZH-EN without a dictionary. Word aligners (eflomal/fast_align statistical; SimAlign/awesome-align embedding-based) can then mine term-to-rendering pairs. With an existing candidate term list and an LLM budget, a simpler and likely more robust route skips word alignment. For each glossary term, take the English chapter(s) where it occurs (or the aligned sentence) and ask the LLM "how is X rendered here?". Then aggregate by frequency to detect the de-facto rendering and inconsistencies. Because the English quality is questionable, mined renderings should be suggestions with frequency counts, not ground truth.

### Cited Findings

| Tool | Latest | License | Stars | Notes | Source |
|---|---|---|---|---|---|
| Bertalign (bfsujason) | repo pushed 2026-05-04 | GPL-3.0 | 162 | LaBSE sentence embeddings; paper targets Chinese-English literary parallel corpora | [GitHub](https://github.com/bfsujason/bertalign) |
| `bertalign` on PyPI | 2.0.1, 2026-07-31, py>=3.12 | GPL-3.0-or-later | — | **third-party repackage** (homepage github.com/chikingsley/bertalign), not the original author | [PyPI](https://pypi.org/project/bertalign/) |
| vecalign | repo pushed 2026-07-04 | Apache-2.0 | 201 | linear time/space; needs only bilingual sentence embeddings (e.g. LaBSE/LASER) | [GitHub](https://github.com/thompsonb/vecalign), [paper](https://preview.aclanthology.org/landing_page/D19-1136) |
| hunalign | last push 2021-05 | LGPL-3.0 | 132 | length + dictionary based; C++ binary | [GitHub](https://github.com/danielvarga/hunalign) |
| lingtrain-aligner | 1.0.3, 2025-05-17 | — | — | LaBSE support (~1.8 GB weights) | [PyPI](https://pypi.org/project/lingtrain-aligner/0.9.4) |
| sentence-transformers (to run LaBSE) | 6.1.0, 2026-09-18, py>=3.10 | Apache-2.0 | — | pure wheel, needs torch | [PyPI](https://pypi.org/project/sentence-transformers/) |
| SimAlign | 0.4, 2023-11-07 | MIT | 397 | mBERT/XLM-R embeddings, no parallel training needed | [GitHub](https://github.com/cisnlp/simalign), [paper](https://arxiv.org/pdf/2004.08728) |
| awesome-align | 0.1.7, 2022-01-01; last push 2022-03 | BSD-3-Clause | 388 | mBERT, can fine-tune on parallel data | [PyPI](https://pypi.org/project/awesome-align/0.1.6/), [GitHub](https://github.com/neulab/awesome-align) |
| eflomal | 2.0.0, 2024-06-20; sdist only (C extension, needs compiler on Windows) | GPL-3.0 | 148 | fast statistical (Bayesian IBM-style) aligner | [PyPI](https://pypi.org/project/eflomal/), [GitHub](https://github.com/robertostling/eflomal) |
| fast_align | last push 2022-07 | Apache-2.0 | 768 | C++ binary, must build | [GitHub](https://github.com/clab/fast_align) |

- Bertalign's paper is titled as improved word-embedding-based sentence alignment for Chinese-English literary parallel corpora (Liu & Zhu 2023, Digital Scholarship in the Humanities). A corpus project used Bertalign alignment followed by LaBSE checking and manual revision for ZH-EN literary text — [Benjamins](https://www.benjamins.com/catalog/scl.129.02dov)
- LaBSE-based alignment reaches state of the art and handles texts with significant breaks in parallelism; evaluated with a manually aligned Mo Yan novel — [arXiv 2403.11921](https://arxiv.org/pdf/2403.11921)
- Vecalign beat Hunalign on Bible-verse alignment; a 2021 study found Vecalign performs well on literary texts with some remaining issues — [Vecalign paper](https://preview.aclanthology.org/landing_page/D19-1136), [RASLAN/MUNI](https://www.ics.muni.cz/en/research/publications/1809760)
- eflomal outperformed SimAlign and awesome-align (not fine-tuned) in a Romansh study, and both of those beat fast_align — [arXiv 2306.08702](https://arxiv.org/pdf/2306.08702)
- SimAlign reports contextual-embedding alignment ~5 F1 points above eflomal for English-German, with mixed results on other pairs — [SimAlign paper](https://arxiv.org/pdf/2004.08728)
- LaBSE itself works as a word aligner, and fine-tuning helps — per search summary of a 2022 Findings of EMNLP paper; VectorAlign on PyPI uses LaBSE for word alignment — [VectorAlign PyPI](https://pypi.org/project/vectoralign/)

### Inferences
- Fan/MTL English for web novels often merges, splits or drops paragraphs, and sometimes skips content. Embedding-based aligners that allow 1-n/n-1 and skips (Bertalign/vecalign) suit this better than length-based hunalign.
- Word alignment of transliterated names is easy for statistical aligners because names are frequent and consistent. Mapping techniques like 九转玄功 → "Nine Revolutions Mystic Art" is a multi-token span, where word aligners produce fragmentary links. The LLM-per-term approach handles span-to-span mapping naturally.
- A pragmatic mining recipe: for each candidate term, sample K chapter pairs where the term occurs (chapter-level is enough; sentence alignment is optional), give the LLM the Chinese snippet plus the English chapter text (or the aligned window), ask for the rendering, and tally the results. Majority rendering plus variance gives both a glossary suggestion and a measure of how inconsistent the existing English is. Sentence alignment with Bertalign/vecalign mainly saves tokens (send aligned windows instead of whole chapters).
- License: Bertalign and eflomal are GPL-3.0. Using them as standalone tools in a private pipeline is fine, but vendoring their code into a redistributed project triggers GPL obligations. vecalign (Apache-2.0) and SimAlign (MIT) are permissive.
- Windows friction: eflomal (sdist with C extension) and fast_align/hunalign (C++ builds) are the hardest. SimAlign/awesome-align/Bertalign/vecalign are Python plus torch/sentence-transformers. awesome-align (last release 2022) may hit `transformers` version pins.

### Gaps
- No published ZH-EN web-novel benchmark for any of these aligners was found.
- No paper was found evaluating LLM-based bilingual term-pair mining specifically for novels, though the approach is widely used by tools like KeywordGacha/LinguaGacha (monolingual extraction only).
- Not verified whether SimAlign/awesome-align install cleanly against current `transformers`/torch on py3.13.

## 3. Glossary formats, injection strategies, consistency enforcement

### Takeaway
The de-facto community format for LLM novel/game translators is a flat list of `{src, dst, info}` entries: LinguaGacha/KeywordGacha as JSON/XLSX, GalTransl as TSV `src<TAB>dst<TAB>note`, Sakura as `src->dst #note`. TBX (ISO 30042) is overkill. Store a richer per-novel JSON/TOML (src, dst, category, aliases, status, notes) and export to `src->dst #info` lines for prompts. Inject only the entries whose source (or alias) appears in the current chunk, using Aho-Corasick (`pyahocorasick`, with cp312/313 Windows wheels). After translation, post-check that each matched entry's `dst` (or an accepted variant) appears in the output. GalTransl's built-in "字典使用" problem check does exactly this.

### Cited Findings
- LinguaGacha glossary: `.json` or `.xlsx`. JSON is either a list of `{"src": ..., "dst": ..., "info": ...}` (info = description such as gender or category) or a simple `{src: dst}` map. Case sensitivity is per entry in the UI. A "hit" column shows usage. Presets are stored in `userdata/glossary/` — [LinguaGacha wiki: Glossary](https://github.com/neavo/LinguaGacha/wiki/Glossary)
- GalTransl has three dictionaries: a pre-translation find/replace on the source (also used to unify variants, which reduces GPT dict input), a GPT dictionary (TSV: source term, translation, optional note; general `Dict/通用GPT字典.txt` and per-project `项目GPT字典.txt`), and a post-translation find/replace on the output with conditional rules (`pre_jp/post_jp<TAB>condition<TAB>find<TAB>replace`) — [GalTransl GitHub](https://github.com/GalTransl/GalTransl)
- GalTransl includes a GPT-dict entry in a request only when the term appears in the current batch's names or sentences, and advises limiting the dict to character settings and words the model gets wrong — [GalTransl GitHub](https://github.com/GalTransl/GalTransl)
- GalTransl `problemAnalyze` checks (default on) include: word repeated >20x, punctuation errors, leftover source script, missing/extra line breaks, output >1.3x source length, **字典使用 (GPT dictionary terms not used as specified)**, and wrong target language. Problems are stored in the cache, can be batch-retranslated by type (`retranslKey`), and changed source text triggers retranslation — [GalTransl GitHub](https://github.com/GalTransl/GalTransl)
- Sakura-style dictionary lines are `src->dst #note`, and GalTransl-style lines are whitespace/tab separated with an optional note. Loaders turn both into `{src, dst, info}` and render each entry into the prompt as `src->dst #info` — [trans_sakura.py](https://huggingface.co/datasets/dlxjj/comicocr/blob/main/modules/translators/trans_sakura.py)
- Licenses/stars: GalTransl GPL-3.0, 2.4k stars, pushed 2026-10-20; AiNiee AGPL-3.0, 6.4k stars, pushed 2026-10-19 (glossary documented on its wiki page "表格 - AI术语表"); SakuraLLM GPL-3.0, 4.8k stars — [GalTransl](https://github.com/GalTransl/GalTransl), [AiNiee](https://github.com/NEKOparapa/AiNiee), [SakuraLLM](https://github.com/SakuraLLM/SakuraLLM)
- pyahocorasick: 2.3.1, 2026-04-27, py>=3.10, BSD-3-Clause (+ public domain), cp312/cp313 wheels, 1.1k stars. Fast, memory-efficient multi-pattern search — [PyPI](https://pypi.org/project/pyahocorasick/), [GitHub](https://github.com/WojciechMula/pyahocorasick)
- OpenCC: `opencc` binding 1.4.2, 2026-08-22, Apache-2.0, cp312/cp313 wheels; OpenCC repo 10.1k stars, pushed 2026-10-19. `opencc-python-reimplemented` (pure Python, 0.1.7, 2023-02) is the fallback; `opencc-python` 0.1 is an obsolete CLI wrapper — [opencc PyPI](https://pypi.org/project/opencc/), [OpenCC GitHub](https://github.com/BYVoid/OpenCC), [opencc-python-reimplemented PyPI](https://pypi.org/project/opencc-python-reimplemented/), [opencc-python PyPI](https://pypi.org/project/opencc-python/)
- translate-toolkit (3.20.0, 2026-09-11, GPL-3.0-or-later, py>=3.11) reads and writes TBX/CSV/PO if TBX export is ever required — [PyPI](https://pypi.org/project/translate-toolkit/)

### Inferences
- Suggested per-novel schema (superset of the community `{src,dst,info}`): `{src, dst, category: person|place|sect|technique|item|realm|creature|title|other, aliases: [zh variants], dst_variants: [accepted English variants], status: candidate|approved|rejected|locked, gender?, notes, first_chapter, freq}`. Export `src->dst #category; gender; notes` lines for prompts. This keeps compatibility with LinguaGacha/AiNiee JSON (`src/dst/info`) for interop.
- Matching: build one Aho-Corasick automaton over all `src` + `aliases` (OpenCC-normalized to simplified). Scan each chunk and inject the matched entries, plus maybe a small always-on set (protagonist, main sect). Resolve overlaps longest-match-first, so 青云宗主 does not also inject 青云 unless it is a separate entry. Python-side `str.find` loops would also work at glossary sizes of a few thousand; pyahocorasick is the low-friction faster option.
- Post-check: for each injected entry whose src occurs in the chunk, verify that `dst` or one of `dst_variants` appears in the output (case-insensitive, word-boundary). Flag misses for retranslation or review, as GalTransl does. Also check the reverse: a locked rendering appearing for a different source term suggests a collision.
- Aliases: Chinese novels refer to the same entity many ways (full name, given name, 师兄/师尊 forms, epithets). Store aliases as separate src keys pointing to one entity id, so matching injects the canonical entry and the post-check accepts the entity's English variants.
- Normalize source text with OpenCC t2s (or s2t if the corpus is traditional) before both extraction and matching, so traditional-character chapters do not create duplicate terms.

### Gaps
- AiNiee's exact glossary JSON schema was not retrieved (its wiki page was linked but not fetched).
- No empirical study was found comparing "inject matched subset" against "inject full glossary" for LLM translation consistency. GalTransl's practice is the best available precedent.

## 4. Pinyin romanization (pypinyin)

### Takeaway
pypinyin is the standard library: MIT, 5.4k stars, pure Python with no Windows friction, actively maintained. It is useful for deterministic name romanization (e.g. 林动 → "Lin Dong") and for checking that an LLM-proposed name rendering is the pinyin of the source. Polyphonic surnames need its surname mode (or explicit glossary overrides).

### Cited Findings
- pypinyin latest 0.55.0, 2025-07-20, MIT, pure-Python wheel; repo (mozillazg/python-pinyin) 5.4k stars, last push 2026-10-18 — [PyPI](https://pypi.org/project/pypinyin/), [GitHub](https://github.com/mozillazg/python-pinyin)
- pypinyin supports tone styles (`Style.NORMAL` for toneless), heteronym (polyphone) output, phrase-based disambiguation, and a surname mode (`lazy_pinyin`/`pinyin` options, and `pypinyin.contrib` style) — [GitHub README](https://github.com/mozillazg/python-pinyin)

### Inferences
- Xianxia translation convention: person names are pinyin with the surname first and the given name joined (Lin Dong, Xiao Yan). Sects, techniques and realms are usually translated semantically (Azure Cloud Sect), and translators vary. pypinyin covers only the first case. Category should decide whether to romanize or translate.
- A cheap automated check: for `category == person`, compare `dst` to `''.join(lazy_pinyin(src))` (case/space-insensitive) and flag mismatches for review. This catches LLM hallucinated romanizations.

### Gaps
- I did not verify pypinyin's surname-mode API name in its current version in this session. Check the README (`Style`, `heteronym`, surname handling) before coding.
