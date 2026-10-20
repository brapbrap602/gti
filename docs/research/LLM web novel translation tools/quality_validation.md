# Automatic quality estimation and deterministic validation for LLM zh->en web-novel translation

Context: per-chapter gate before storing a translated chapter, in a Python (uv, Windows, CPU-only) pipeline. Known failures: looped passages (one chapter had a passage about 94 times), CJK/pinyin leakage, dropped or merged chapters, missing or wrong chapter titles and numbers, glossary drift, omissions and truncation. Research date: 2026-10-20. Several "last release" dates could not be confirmed from the pages fetched. Those cases are listed under Gaps rather than guessed.

## 1. Reference-free neural QE metrics (COMET/CometKiwi, xCOMET, MetricX-24, GEMBA/LLM-judge): quality, license, size, CPU feasibility

### Takeaway
On WMT23 zh->en, the strongest reference-free metrics (XCOMET-QE, MetricX-23-QE) score close to the best reference-based ones. However, every strong learned QE model is either non-commercial (CometKiwi and xCOMET use CC-BY-NC-SA-4.0) or 1B+ parameters. All are segment-level models with input caps of about 512-1536 tokens, so a whole chapter has to be split into segments and the scores averaged. MetricX-24 (Apache-2.0) is the only permissively licensed, top-tier option. On a CPU desktop, a learned QE score is best used as an optional or sampled signal, not a per-chapter hard gate. The hard gate should come from the deterministic checks in sections 2-5.

### Cited Findings
**WMT23 metrics task, zh->en results** (the source and MQM test set closest to this use case; WMT24 MQM used en-de, en-es and ja-zh, not zh-en):
- System-level Pearson on zh->en (task8). GEMBA-MQM (QE) 0.991, CometKiwi (QE) 0.963, docWMT22CometKiwiDA (QE) 0.965, XCOMET-Ensemble 0.927, XCOMET-QE-Ensemble 0.892, MetricX-23-QE 0.859, COMET 0.898, BLEU 0.734, chrF 0.809. — [WMT23 Metrics Findings, Table 8](https://aclanthology.org/2023.wmt-1.51.pdf)
- Segment-level Pearson on zh->en (task9). XCOMET-Ensemble 0.650, XCOMET-QE-Ensemble 0.647, MetricX-23-QE 0.647, MetricX-23 0.625, GEMBA-MQM 0.449, CometKiwi 0.442, docWMT22CometKiwiDA 0.387, COMET 0.396, BLEURT-20 0.378. — [WMT23 Metrics Findings, Table 9](https://aclanthology.org/2023.wmt-1.51.pdf)
- So GEMBA-MQM (a GPT-4 judge) is excellent at system level but only mid-pack per segment. For per-chapter gating, segment-level performance is what matters. — [WMT23 Metrics Findings](https://aclanthology.org/2023.wmt-1.51.pdf)
- WMT23 found that "reference-based metrics struggle for zh→en due to the reference quality". It also concluded that "strong QE metrics can be better alternatives in such scenarios" and that "reference-free metrics were strong contenders this year". — [WMT23 Metrics Findings](https://aclanthology.org/2023.wmt-1.51.pdf)
- Larger CometKiwi models did not help zh->en at segment level: CometKiwi-XXL 0.390, CometKiwi-XL 0.430, CometKiwi (wmt22) 0.442. — [WMT23 Metrics Findings, appendix tables](https://aclanthology.org/2023.wmt-1.51.pdf)
- CometKiwi's 2022 paper reported much lower MQM correlation for zh-en than for en-de and en-ru, at roughly 0.2-0.27. — [CometKiwi 2022 paper](https://arxiv.org/pdf/2209.06243) (figures as summarized by the search result; not re-verified in the PDF)
- WMT24 overall: MetricX-24-Hybrid-QE ranked second among reference-free metrics with a 0.714 average correlation, against 0.640 for the CometKiwi baseline. — [MetricX-24 paper](https://arxiv.org/pdf/2410.03983) / WMT24 findings summary (no zh-en MQM breakdown found)
- WMT25 merged the metrics and QE tasks into one "Automated Translation Evaluation" task with three subtasks: segment scores, error spans, and correction. It found that "large LLMs perform strongly at the system level, while reference-based baseline metrics outperform LLMs at the segment level". It also found that balancing precision and recall in error-span detection "remains a persistent challenge". WMT25 general MT moved to document-level sources with multiple paragraphs. — [WMT25 findings (search summary)](https://preview.aclanthology.org/setup/2025.wmt-1.22); [arXiv 2508.14909](https://arxiv.org/pdf/2508.14909v1)

**CometKiwi (wmt22-cometkiwi-da)**
- License cc-by-nc-sa-4.0. The repository is gated: you accept the terms on Hugging Face and log in. It is fine-tuned from microsoft/infoxlm-large and covers about 94 languages. Run it with `pip install "unbabel-comet>=2.0.0"` and `comet-score --model Unbabel/wmt22-cometkiwi-da`. — [HF model card](https://huggingface.co/Unbabel/wmt22-cometkiwi-da)
- The COMET code is Apache-2.0, but each model has its own license (see LICENSE.models.md). wmt23-cometkiwi-da-xl is 3.5B parameters and wmt23-cometkiwi-da-xxl is 10.7B. `--gpus 0` runs on CPU, and the README warns that CPU unit tests "take a long time". — [Unbabel/COMET GitHub](https://github.com/Unbabel/COMET)
- DocCOMET (`--enable-context`, with context sentences separated by `</s>`) adds document context. The README example uses wmt20-comet-qe-da. — [Unbabel/COMET GitHub](https://github.com/Unbabel/COMET)

**xCOMET**
- XCOMET-XL has about 3.5B parameters on an XLM-R XL base, uses CC-BY-NC-SA-4.0, and says commercial use requires authorization from Unbabel. It outputs error spans (`--to_json`, `metadata.error_spans`). — [HF XCOMET-XL](https://huggingface.co/Unbabel/XCOMET-XL)
- XCOMET-XXL has 10.7B parameters. — [Unbabel/COMET GitHub](https://github.com/Unbabel/COMET)

**MetricX-24**
- Apache-2.0. Hybrid models come in Large, XL and XXL, each with a bf16 variant that uses 50% less memory. XXL gives the best human agreement and Large the best speed. QE mode uses the `--qe` flag with an empty reference. Maximum input is 1536 tokens. Scores are 0-25 and lower is better. — [google-research/metricx](https://github.com/google-research/metricx)
- It is initialized from mT5 and fine-tuned on WMT'15-'22 DA and MQM data. Synthetic data was added to reduce bias against long translations. — [HF metricx-24-hybrid-large-v2p6](https://huggingface.co/google/metricx-24-hybrid-large-v2p6)

**GEMBA-MQM / LLM-as-judge**
- GEMBA-MQM uses GPT-4 with a fixed three-shot, language-agnostic prompt that marks error spans (MQM categories and severities). The authors caution against using it in academic comparisons because it depends on a proprietary black-box model. — [GEMBA-MQM paper](https://arxiv.org/pdf/2310.13988)
- Repository: MicrosoftTranslator/GEMBA (listed in the WMT23 metric table). — [WMT23 Metrics Findings](https://aclanthology.org/2023.wmt-1.51.pdf)
- A GEMBA-MQM-style prompt adapted to zh->en chat translation reached 79.17% pairwise accuracy and 0.774 Pearson against human rankings. LLM outputs showed more "Unnatural Style" errors than mistranslations. — [MQM-Chat](https://arxiv.org/pdf/2408.16390)

### Inferences
- **Licensing.** If the novel site is ever monetized, CometKiwi and xCOMET are off-limits without Unbabel's permission. MetricX-24 (Apache-2.0) and an LLM judge carry no such restriction.
- **CPU cost.** wmt22-cometkiwi-da uses InfoXLM-large, which is roughly XLM-R-large size (about 560M parameters, from general knowledge; not stated on the card). On a desktop CPU it should score a chapter's 100-300 segments in tens of seconds to a few minutes. That is feasible but not free. XL and XXL models (3.5B-10.7B) are impractical on CPU per chapter. No measured CPU benchmark was found, so time it locally.
- **Document length.** No learned QE model scores a 3-5k-word chapter in one pass, because of the 512-1536-token caps. You need paragraph-level scoring after alignment, then aggregation (mean plus the count of low-scoring paragraphs). A low-scoring paragraph is a better omission or hallucination signal than the chapter mean.
- **LLM judge.** Since the pipeline already calls an LLM, an ESA/MQM-style error-span pass on sampled or flagged chapters is probably the best value for semantic QA. Segment-level reliability is moderate (zh->en 0.449 for GEMBA-MQM), so use it for triage and retranslation decisions, not as an absolute score.
- **Fit to the known failures.** None of these metrics is needed to catch the known failure modes (loops, leakage, truncation, chapter merges). Those are deterministic.

### Gaps
- Exact last-release dates for unbabel-comet on PyPI could not be confirmed: the PyPI page failed to load and the GitHub page showed no Releases. The same goes for the metricx repository, which shows no dates.
- No zh-en MQM results for WMT24 or WMT25 metrics were retrieved, and no WMT25 per-language segment table was retrieved.
- No measured CPU throughput figures were found for CometKiwi or MetricX.
- No measured Windows install issues were found. COMET pulls in PyTorch and PyTorch Lightning, which work on Windows CPU in general; this is not verified here.
- MetricX-24 Large's parameter count is not on the card (mT5-large is about 1.2B, from general knowledge).

## 2. Language ID vs Unicode regex for CJK/pinyin leakage

### Takeaway
For detecting leakage, a Unicode-range regex (Han, CJK punctuation, fullwidth forms) is the correct primary check. It is exact, has zero dependencies, and runs in microseconds per chapter. Language-ID models add little, because the target is English and any Han character in it is a defect. Pinyin leakage, such as untranslated names or "Xianzun", is a glossary and dictionary problem, not a language-ID problem. If you want a statistical language-ID check per paragraph, lingua-py (Apache-2.0, Rust core) is the best fit for short text. fastText lid.176 uses a share-alike license (CC-BY-SA-3.0), and GlotLID warns that it is weak on short text.

### Cited Findings
- **lingua-py.** Apache-2.0, v2.2.0, Rust core with Python bindings since 2.0.0, requires Python 3.12+, installed with `pip install lingua-language-detector`. Runtime memory is "a few dozen megabytes". Low-accuracy mode loses accuracy below 120 characters. `detect_multiple_languages_of` handles mixed-language text but is experimental. — [lingua-py GitHub](https://github.com/pemistahl/lingua-py)
- **lingua-py speed.** On 3,000 texts per language: CLD2 took 8.65 s, lingua low-accuracy multithreaded 11.81 s, lingua high-accuracy 21.13 s, and langdetect 10 min 43.96 s. — [lingua-py GitHub](https://github.com/pemistahl/lingua-py)
- lingua's high-accuracy Chinese accuracy is 100% on single characters, word pairs and sentences. — [lingua Chinese accuracy report](https://raw.githubusercontent.com/pemistahl/lingua-py/main/accuracy-reports/lingua-high-accuracy/Chinese.txt)
- **fastText lid.176.** CC-BY-SA-3.0, 176 languages. The .bin file is 126 MB and the .ftz is 917 kB; the .bin is "faster and slightly more accurate". — [fastText language identification](https://fasttext.cc/docs/en/language-identification.html)
- **GlotLID.** Apache-2.0 "plus notices". V3 covers about 2,100 labels. For Python 3.10+ it recommends `pip install fasttext-numpy2-wheel` instead of `fasttext`. It is "primarily trained on longer sentences" and not suited to very short text. — [GlotLID GitHub](https://github.com/cisnlp/GlotLID)
- GalTransl's own "language mismatch" check (语言不通) is a character-set test (non-GBK characters for a Chinese target), not a model. Its "residual Japanese" check (残留日文) looks for leftover kana. — [GalTransl GitHub](https://github.com/xd2333/GalTransl)

### Inferences
- **Regex check.** Count `[㐀-䶿一-鿿豈-﫿\U00020000-\U0002FA1F]` plus CJK punctuation (`　-〿`, `＀-￯`). Use a hard fail when the count is above a small threshold, for example 0 Han characters outside an allowlist. Also flag lines whose Latin-letter ratio is low.
- **Pinyin heuristics.** Catch pinyin with a syllable-inventory regex over capitalized tokens that are not in the glossary. Tone-marked vowels (āáǎà...) are a strong signal. A separate check: glossary source terms whose target should appear but where a pinyin romanization appears instead.
- **langdetect.** It is slow and nondeterministic unless seeded (general knowledge). Skip it.
- **cld3.** The pip package (pycld3) needs protobuf and a compiler toolchain on Windows (general knowledge; not verified this session). Skip it.

### Gaps
- No head-to-head benchmark of lingua, fastText and GlotLID on mixed zh/en or pinyin-heavy English was found.
- The cld3 Windows install status and last release were not verified.
- The lingua-py release date for v2.2.0 was not shown on the page.

## 3. Repetition and degeneration detection, and truncation detection

### Takeaway
Use cheap, deterministic signals that would each have caught the 94-times loop. First, the zlib compression ratio of the chapter compared with a baseline from good chapters; Whisper rejects text with a ratio above 2.4. Second, the share of duplicate lines and paragraphs. Third, the max count and coverage of repeated n-grams. Fourth, a tail-loop check. For truncation, check the API `finish_reason` (anything other than a normal stop is a fail) and the target/source length ratio against the per-novel distribution.

### Cited Findings
- **Whisper's compression check.** `compression_ratio(text) = len(text_bytes) / len(zlib.compress(text_bytes))`. — [whisper/utils.py](https://raw.githubusercontent.com/openai/whisper/main/whisper/utils.py)
- Whisper's transcribe has `compression_ratio_threshold = 2.4` by default ("If the gzip compression ratio is above this value, treat as failed") and falls back or re-decodes when it is exceeded. — [whisper/transcribe.py](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)
- **Published degeneration detector.** A lightweight detector flags outputs "dominated by a single token", with "high-coverage repeated n-grams across multiple granularities", or with "tail-loop behaviours". — [DharmaOCR paper (search summary)](https://arxiv.org/pdf/2604.14314)
- **GalTransl's problem analysis** (`problemAnalyze.problemList` in config.yaml) includes:
  - 词频过高: a term repeats more than 20 times.
  - 比日文长: output more than 1.3x the source length; 比日文长严格 is a stricter variant.
  - 丢失换行 / 多加换行: missing or extra line breaks.
  - 标点错漏: punctuation errors.
  - 字典使用: glossary not followed.
  - 引入英文: English introduced.

  Flagged lines are saved with a `problem` field and can be retranslated in bulk with `retranslKey`. License GPL-3.0. The latest update log entry is "2026.8: v8, adds Agent mode". — [GalTransl GitHub](https://github.com/xd2333/GalTransl)
- **Repetition in training data.** Research links LLM repetition to repetitive patterns in training data. — [Repetition In Repetition Out](https://arxiv.org/pdf/2310.10226)

### Inferences
Suggested gates (to calibrate on your own good chapters):
- **Whole-chapter compression.** Normal English prose compresses at about 2.5-3.5x with zlib on chapter-sized text. That is higher than Whisper's 2.4, which was tuned for short 30-second segments, so do not reuse 2.4 as-is. Compute the ratio over the chapter and flag at, say, the baseline p99 or a fixed value of about 4. A passage repeated 94 times would push the ratio far above that.
- **Duplicate paragraphs.** `max(Counter(normalized_paragraphs).values()) >= 3` for paragraphs longer than about 40 characters is a near-certain loop. Also compute the share of characters in duplicated paragraphs.
- **Repeated n-grams.** Flag a chapter when any word 8-gram occurs much more often in the target than its counterpart in the source, or when the top repeated 20-gram covers more than about 5% of tokens.
- **Tail loop.** Flag when the last N characters consist of a repeated period.
- **Truncation.** Any `finish_reason` of `length`/`max_tokens` is a hard fail. Also flag when the last paragraph has no terminal punctuation, and when the length ratio falls below the novel's p1 (see section 4).
- GalTransl and AiNiee-style checks happen per line or segment with automatic retranslation. Copying that "flag, then retranslate only the flagged unit" loop beats rejecting whole chapters.

### Gaps
- AiNiee's specific degeneration and repetition checks could not be found in this session's searches. Look at its GitHub source directly.
- No published threshold for whole-chapter zlib ratios on English fiction was found. Calibrate locally.

## 4. Alignment checks: length ratio, paragraph counts, sentence alignment for omissions

### Takeaway
For zh->en, the commonly cited norm is about 1.5-1.7 Chinese characters per English word, varying by genre (literary closer to 1:1, technical up to about 2:1). Use a per-novel learned distribution (median and percentiles of English words per source Han character) rather than a fixed constant. Paragraph-count alignment, with tolerance for the LLM merging or splitting paragraphs, catches gross omissions and merges. Embedding-based alignment (Bertalign/LaBSE) can pinpoint omitted passages but costs a ~470M-parameter model on CPU and is GPL-3.0. Use it only for chapters flagged by the cheap checks.

### Cited Findings
- **Length norms.** Translators cite about 1.7 Chinese characters per English word; 1.5 is "widely accepted" but statistically shaky. Literary text tends toward about 1:1 and technical text toward 2:1. — [ProZ thread](https://fin.proz.com/forum/chinese/317428-urgent_how_to_estimate_english_target_word_count.html); [ProZ thread 2](https://kor.proz.com/forum/chinese/82325-about_how_many_chinese_characters_to_english_words_in_chi_eng_texts.html)
- A Unicode mailing-list estimate gives 1.4-1.8 characters per word for commercial translation. — [Unicode ML](https://www.unicode.org/mail-arch/unicode-ml/y2003-m03/0104.html)
- LDC parallel corpora give about 1.7 characters per word. — [Language Log via gwern](https://www.gwern.net/docs/www/itre.cis.upenn.edu/e280f55b8517ffaa885a61e3b7b86280dbdd92a4.html)
- **Bertalign.** GPL-3.0. It uses LaBSE via sentence-transformers plus faiss, supports 25 languages including zh and en, and handles 1-1, 1-many, many-1 and many-many alignments. The README reports no zh-en accuracy and no CPU speed figures. Strict F1 is 0.936 on de-fr Text+Berg. — [Bertalign GitHub](https://github.com/bfsujason/bertalign)
- **GalTransl's length rule.** Translation more than 1.3x the source length is flagged; that is for ja->zh, so the threshold does not transfer. — [GalTransl GitHub](https://github.com/xd2333/GalTransl)

### Inferences
- **Cheap omission and merge checks:**
  - Ratio = English words / source Han characters. Flag below p1 or above p99 of the novel's history, with a cold-start band of roughly 0.4-0.9 words per character (from the 1.1-2.5 characters-per-word range, widened).
  - Paragraph-count ratio between target and source. Flag outside about 0.7-1.3, since LLMs merge short dialogue lines.
  - A chapter whose length is close to twice the median is a likely merged chapter. Detect it more directly by finding a second chapter heading pattern ("Chapter \d+") inside the body.
- **Embedding alignment, flagged chapters only:**
  - Embed source and target paragraphs with LaBSE, or a smaller multilingual model such as paraphrase-multilingual-MiniLM (general knowledge).
  - Run monotonic DP alignment and report source paragraphs with no target match above a similarity threshold. Those are omission candidates.
  - LaBSE is about 470M parameters (general knowledge). On CPU, embedding 200-400 paragraphs takes seconds to tens of seconds.
  - Bertalign's GPL-3.0 license matters only if you distribute the pipeline. A local tool is fine, or reimplement the small DP.

### Gaps
- No published per-genre zh->en length norms for web novels were found. The numbers above come from translator practice and corpus estimates.
- No CPU timing for Bertalign or LaBSE on chapter-sized text was found.

## 5. Terminology adherence and production QA tools (Xbench, Okapi CheckMate)

### Takeaway
Production localization QA is almost entirely deterministic. Its checks are untranslated or empty segments, target equal to source, key-term mismatch, number mismatch, consistency, repeated words, length outliers, pattern and tag parity, and corrupted characters. All of these port directly to per-chapter checks. Terminology adherence is a simple rule: when a glossary source term occurs in the source, the expected target form (or an approved variant) must occur in the target. Also flag known wrong variants and pinyin forms.

### Cited Findings
- **Okapi CheckMate checks:**
  - repeated words
  - corrupted characters
  - source and target pattern matching
  - inline code differences
  - length ("Translation suspiciously longer or shorter than the source")
  - missing translations
  - leading and trailing spaces
  - LanguageTool integration

  Threshold values sit on its "Quality Check Configuration" page, which was not retrieved. — [Okapi CheckMate](https://okapiframework.org/wiki/index.php/CheckMate)
- **Xbench checks:**
  - untranslated segments
  - source text left in the target
  - Key Term Mismatch: segments whose source contains a glossary term but whose target lacks the mandated translation; whole-word matching by default
  - numeric mismatch
  - source-side and target-side inconsistency

  Version 3.0 (paid) adds URL, CamelCase and unpaired-symbol checks; 2.9 (free) is no longer developed. — [Satsuma comparison](https://www.satsuma.com.br/en/what-are-the-differences-between-xbench-2-9-and-3-0/); [Pangeanic on Xbench](https://blog.pangeanic.com/xbench); [ProZ key-term thread](https://chi.proz.com/forum/localization/312401-xbecnh_how_to_qa_against_a_list_of_words.html); [Spanish Xbench guide](https://www.traductores.org.ar/wp-content/uploads/2020/07/2019-Control-de-calidad-con-Apsic-Xbench.pdf)
- **GalTransl's 字典使用 check** flags lines where GPT-dictionary glossary terms were not translated as specified. — [GalTransl GitHub](https://github.com/xd2333/GalTransl)

### Inferences
**Applicable per-chapter checks** (hard = reject or retranslate; soft = log):
1. **Hard:** API `finish_reason` was not a normal stop.
2. **Hard:** Han or CJK-punctuation characters present (regex).
3. **Hard:** duplicated paragraph repeated 3 or more times, a compression-ratio outlier, or a tail loop.
4. **Hard:** chapter title or number is missing, or its number does not match the source chapter number. Parse "Chapter N" from the target title and compare it with the source's 第N章, including Chinese-numeral conversion.
5. **Hard:** a second chapter heading inside the body (merged chapter).
6. **Hard:** empty or near-empty output, or a length ratio below the novel's p1.
7. **Soft (hard if high):** paragraph-count ratio outside 0.7-1.3.
8. **Soft:** glossary key-term mismatch rate, with per-term counts kept to track drift across chapters. Also check consistency: the same source term should not be rendered with different target forms across chapters, which mirrors Xbench's "target inconsistency".
9. **Soft:** pinyin-like capitalized tokens that are not in the glossary or an English dictionary. Tone marks count as hard.
10. **Soft:** numbers in the source (Arabic, or converted Chinese numerals) missing from the target. This is noisy in fiction, so log only.
11. **Optional:** a learned QE score per paragraph (MetricX-24 Large QE with Apache-2.0, or CometKiwi if non-commercial use is acceptable), or an LLM MQM/ESA judge on flagged or sampled chapters.

**Ordering and cost.** Checks 1-10 are pure Python (`re`, `zlib`, `collections`), take well under 100 ms per chapter, and need no Windows install friction. Optional neural checks add hundreds of MB to several GB of model weights plus PyTorch.

### Gaps
- CheckMate's default length thresholds were not retrieved.
- No published LLM-localization tool (Lokalise, Crowdin AI and others) automated-QA spec was retrieved for comparison.
- No research was found on detecting term drift in LLM web-novel translation specifically.
