# LLM Literary / Long-Document Translation Research Systems and Context Strategies

Scope: research systems (TransAgents, DelTA, translation-agent, TACTIC, Translating Step-by-Step, multi-turn document MT), WMT literary tasks (GuoFeng web novels), chunking, context, and glossary evidence. The goal is to judge what fits a Python zh-en xianxia pipeline (3-4k Chinese chars per chapter, 1,500-3,200 chapters, OpenRouter models): discover terms -> resolve glossary -> translate a chapter with a glossary subset plus rolling context -> deterministic validation -> store.

Research date context: October 2026. About 15 tool calls were made. Some items (MAPS, Google "translation with memory", WMT25 literary findings) could not be verified and are listed under Gaps.

## Q1. Architecture of each system, the memory it carries, and measured benefits

### Takeaway
DelTA (ICLR 2025) has the best-measured memory design. It keeps a proper-noun record table, a bilingual (source plus target) running summary, and short and long sentence windows. On GuoFeng web novels zh-en, its proper-noun consistency (LTCR-1) jumped from about 58-62 to about 86-89 for GPT-class models, with small COMET gains. The ablation shows the proper-noun table drives most of the consistency gain, and the summaries add a little quality. TransAgents front-loads a "translation guideline" (glossary, book summary, tone/style/audience) and then runs a multi-agent critique loop per chapter. Humans and LLM judges preferred its output, but its d-BLEU was very low and it omitted content.

### Cited Findings
**DelTA (Wang et al., ICLR 2025, arXiv 2410.08143)**
- Translates sentence by sentence. It keeps four memories: Proper Noun Records (each noun mapped to its first translation, updated after every sentence by an extractor LLM), a Bilingual Summary (source and target summaries, rebuilt every m=20 sentences by summarizing each segment and then merging; the source summary also records domain, style and tone), Long-Term Memory (the last l=20 sentence pairs, from which a retriever LLM picks n=2 relevant pairs), and Short-Term Memory (the last k=3 pairs). — [DelTA arXiv HTML](https://arxiv.org/html/2410.08143v1)
- GuoFeng Webnovel (V1 TEST_2, zh->en, 857 sentences in 12 docs), Sentence-level baseline -> DelTA, given as sCOMET / dCOMET / LTCR-1:
  - GPT-3.5: 77.62 / 3.07 / 61.58 -> 78.45 / 3.17 / 85.57. The plain 3-previous-sentence "Context" baseline scored 78.57 sCOMET, slightly above DelTA.
  - GPT-4o-mini: 77.87 / 3.10 / 58.82 -> 78.77 / 3.34 / 88.94.
  - Qwen2-72B: 75.15 / 2.98 / 58.00 -> 78.32 / 3.31 / 86.93.
  - Qwen2-7B: LTCR-1 rose from 37.00 to 85.50.
  - Source: [DelTA arXiv HTML](https://arxiv.org/html/2410.08143v1)
- IWSLT2017, averaged over 4 backbones: Xx->En gains over Sentence-level were +3.16 sCOMET, +0.30 dCOMET and +4.58 LTCR-1. Gains over a simple 3-previous-sentence context baseline were only +0.62 sCOMET and +1.65 LTCR-1. — [DelTA arXiv HTML](https://arxiv.org/html/2410.08143v1)
- Ablation (En->Zh, GPT-3.5), LTCR-1 at each step:
  - Sentence-level: 80.27
  - +short-term memory: 77.89 (consistency dropped slightly)
  - +long-term memory: 79.23
  - +source summary only: 76.09
  - +target summary only: 82.14
  - +bilingual summary: 82.49
  - +proper noun records: 86.44 (+3.95, with slight COMET drops)
  - COMET moved only about 0.9 points in total.
  - Source: [DelTA arXiv HTML](https://arxiv.org/html/2410.08143v1)
- DelTA beats baselines on consistency when a term recurs more than 50 sentences later. Its pronoun accuracy (APT) was 61.07, against 60.84 for Context and 56.11 for Doc2Doc. — [DelTA arXiv HTML](https://arxiv.org/html/2410.08143v1)

**TransAgents (Wu et al., TACL 2025, arXiv 2405.11804)**
- It simulates a translation company: CEO, Senior Editor, Junior Editor, Translator, Localization Specialist and Proofreader.
- Before translating, it builds a guideline. The glossary per chapter comes from an "Addition-by-Subtraction" loop: the Junior Editor proposes terms, the Senior Editor removes generic ones, and the Senior Editor then translates them in context. Chapter summaries roll up into a book summary. Tone, style and audience are set from one random chapter.
- It translates one chapter at a time through three "Trilateral" loops (Action, Critique, Judgment) for translation, localization and proofreading. A final review then checks transitions between adjacent chapters.
- The Judgment agent deliberately sees no long history, because the authors saw agents stop using long context effectively and meaning drift after several revisions.
- Source: [TransAgents arXiv HTML](https://arxiv.org/html/2405.11804v1)
- Results on the WMT2023 DLLT test set:
  - dd-BLEU was 25.0, the lowest in the comparison. HW-TSC scored 52.2, gpt-4-1106 47.8 and Google 47.3. Dd-BLEU fell by stage: 28.8 after translation, 25.5 after localization, 25.0 after proofreading.
  - Monolingual human preference win rate: 52.1% vs. the reference and 55.6% vs. GPT-4 (the authors call these margins marginal).
  - Bilingual LLM preference win rate: 66.2% vs. the reference and 55.9% vs. GPT-4.
  - Both TransAgents and GPT-4 omitted content.
  - Human evaluation covered only the first 2 chapters of each of 12 novels.
  - Source: [TransAgents arXiv HTML](https://arxiv.org/html/2405.11804v1)
- A secondary write-up summarizes it as better on long texts and weaker on short ones. — [DeepLearning.AI The Batch](https://www.deeplearning.ai/the-batch/transagents-a-system-that-boosts-literary-translation-with-a-multi-agent-workflow)

**Andrew Ng's translation-agent**
- Three steps: translate, have the LLM reflect and suggest improvements, then rewrite using those suggestions.
- The README says it is "sometimes competitive with, but also sometimes worse than, leading commercial offerings" (evaluated with BLEU) and calls the software "not mature".
- Source: [andrewyng/translation-agent](https://github.com/andrewyng/translation-agent)

**Translating Step-by-Step (Briakou, Luo, Cherry, Freitag; Google; WMT 2024)**
- Multi-turn pipeline: pre-translation research (flagging idioms and hard passages), then drafting, refining and proofreading.
- Using Gemini 1.5 Pro, it reported large gains over zero-shot prompting across 10 language pairs and state-of-the-art WMT24 results.
- Sources: [arXiv 2409.06790](https://arxiv.org/html/2409.06790v1); [ACL Anthology](https://aclanthology.org/2024.wmt-1.123)
- It was challenged by "Please Translate Again" (Wu, Aycock, Monz; EMNLP 2025). That paper found little evidence that the gains come from the explicit decomposition. Simply prompting the model to "translate again" or to self-refine did as well or better. — [arXiv 2506.04521v2](https://arxiv.org/html/2506.04521v2); [ACL Anthology](https://preview.aclanthology.org/setup/2025.emnlp-main.1031)

**TACTIC (Li et al., arXiv 2506.08403, 2025)**
- Six agents (Research, Context, Draft, Refinement, Evaluation, Score) based on cognitive translation theory. It drafts quickly and then refines iteratively.
- Reports XCOMET gains over direct LLM baselines on FLORES-200 and WMT24. Code is at github.com/weiyali126/TACTIC.
- Source: [TACTIC arXiv HTML](https://arxiv.org/html/2506.08403v2)

**Multi-turn document MT (Hu, Vamvas, Sennrich, arXiv 2503.10494, 2025)**
- Splits a document into paragraphs and translates them one turn at a time in a single chat, so earlier turns (source and its translation) stay in context. A "source-primed" variant gives the whole source document first.
- WMT24 average (dBLEU / COMET):
  - GPT-4o-mini: segment-level 31.82 / 83.04; multi-turn source-primed 32.51 / 84.38; source-primed plus ICL 32.73 / 84.42.
  - Llama-3.1-8B: 21.65 / 76.40 -> 24.23 / 79.20.
- On WMT23 zh-en with Llama-3.1-8B, BlonDE (a discourse metric) rose from 33.67 to 38.75.
- Single-turn whole-document output was noticeably shorter than the reference on the longest documents, which indicates omissions.
- TowerInstruct (a translation-tuned model) got worse with multi-turn.
- Source: [arXiv 2503.10494 HTML](https://arxiv.org/html/2503.10494v1)

**WMT 2024 Discourse-Level Literary Translation (GuoFeng corpus)**
- Top zh-en systems by d-BLEU:
  - NLP2CT-UM (50.9): GPT-4o produced 3 candidates under different context and terminology settings, and the best sentence was chosen by xCOMET.
  - HW-TSC (50.2): Chinese-Llama2 with continued pretraining and SFT, plus incremental decoding over broader context.
  - Cloudsheep (48.5): custom name dictionaries, CEDICT for idioms, and GPT-3.5/4 refinement.
  - SJTU-LoveFiction (47.2): chunk-based SFT, an editor agent and a terminology-proofreader agent.
  - Baselines: Google 47.3, GPT-4 43.7.
- Human evaluation (0-5 scale, general / discourse): NLP2CT-UM 3.96 / 4.00 and SJTU-LoveFiction 3.92 / 4.13. The two highest human scores both used explicit terminology handling.
- Source: [WMT24 findings, arXiv 2412.11732](https://arxiv.org/html/2412.11732v1)
- WMT23 introduced the zh-en web-fiction task: about 2M sentences from 179 web novels and 14 submissions from 7 teams. — [WMT23 task page](https://www2.statmt.org/wmt23/literary-translation-task.html); [WMT23 findings](https://ar5iv.labs.arxiv.org/html/2311.03127)

### Inferences
- What our pipeline should carry between chapters, by evidence strength:
  1. A persistent proper-noun/term table. This is the largest and best-evidenced consistency lever, and we already have it as the glossary. Its value grows with distance (>50 sentences), which matters at 1,500+ chapters.
  2. A target-side or bilingual running summary. Small gains, cheap if rebuilt periodically.
  3. Recent source/target text. Helps pronouns and cohesion, but in DelTA's ablation it did not help term consistency on its own.
- For a single English target, DelTA's learned, append-only first-translation table is roughly what our "discover terms -> resolve glossary" stage does, but done offline and curated. That is likely better than DelTA's online first-seen rule, which locks in early mistakes.
- The WMT24 winners map onto our design: dictionaries for names and idioms, a terminology proofreader, and selecting among multiple candidates. Multi-candidate selection is a costly option to keep for problem chapters only.

### Gaps
- DelTA's results are on 12 short GuoFeng documents (857 sentences). There is no evidence at the 1,000+ chapter scale.
- TransAgents' dd-BLEU drop and its omissions suggest its multi-stage rewriting moves away from the source. No numbers isolate the guideline's effect on consistency.
- I could not open TACTIC's README or license, or find its literary/document results.

## Q2. Code availability, license, maintenance, usability as a library

### Takeaway
None of these is a maintained pip library. DelTA/DocMTAgent (Apache-2.0) and translation-agent (MIT) have reusable prompts and logic worth reading and porting. TransAgents' repo contains outputs only, not runnable agent code.

### Cited Findings
- **DelTA (github.com/YutongWang1216/DocMTAgent)**
  - Apache-2.0. Contains prompts, inference scripts (`infer/run_infer_gpt.sh` for an OpenAI-compatible API, `run_infer_qwen.sh` for local models), data, results, and an LTCR-1 consistency evaluation script.
  - Pins Python 3.9, openai 1.51.2 and transformers 4.45. Runs from shell scripts with no documented Python API. 25 commits; the last news item is from January 2025.
  - Source: [DocMTAgent GitHub](https://github.com/YutongWang1216/DocMTAgent)
- **TransAgents (github.com/minghao-wu/transagents)**
  - Visible contents: `img/`, `outputs/` and README. No agent source code or prompts were visible.
  - The license is listed as Apache-2.0, but the README badge says CC BY 4.0.
  - Usable only through the transagents.ai web demo. About 606 stars; the last news item is TACL acceptance in April 2025.
  - Sources: [TransAgents GitHub](https://github.com/minghao-wu/transagents). A blog review likewise said the code and prompts are absent: [gonzoml](https://gonzoml.substack.com/p/perhaps-beyond-human-translation)
- **translation-agent (github.com/andrewyng/translation-agent)**
  - MIT, commercial use allowed. Installed with Poetry from a clone; no PyPI release. The authors call it "not mature".
  - Source: [translation-agent GitHub](https://github.com/andrewyng/translation-agent)
- **TACTIC**: code at github.com/weiyali126/TACTIC. — [TACTIC arXiv](https://arxiv.org/html/2506.08403v2)
- **GuoFeng corpus**: non-commercial research use only, with registration. Redistribution and modification are prohibited. — [WMT24 findings](https://arxiv.org/html/2412.11732v1)

### Inferences
- Port ideas, not dependencies. The useful pieces are small: DelTA's proper-noun extractor prompt, its summary-merge prompt, and the LTCR-1 consistency script, which could be adapted as a validation metric. translation-agent's reflect-then-improve prompts are also small.
- GuoFeng could serve as a private zh-en web-novel evaluation set, but its license blocks publishing derived data.

### Gaps
- I could not confirm last-commit dates or open issues for any of these repos.
- I did not verify from the code that translation-agent splits long texts into roughly token-sized chunks with surrounding context tags. That is my recollection only.

## Q3. Cost multiplier (LLM calls per chunk) vs. quality gain

### Takeaway
Reflection and multi-agent loops cost 3-10x+ the calls of a single translation, for gains that are small on automatic metrics (about 1-3 COMET) or uncertain (TransAgents loses about 50% d-BLEU while winning preference judgments). Cheap context (glossary plus previous text in one call) captures most of the consistency gain.

### Cited Findings
- DelTA needs about 3 LLM calls per sentence (translate, retrieve, extract nouns), plus summary calls every 20 sentences. That is about 3.2 calls per sentence, derived from Algorithm 1 because the paper gives no exact count. The authors acknowledge it is slow. Its gain over a free 3-previous-sentence context baseline was only +0.62 sCOMET and +1.65 LTCR-1 (IWSLT Xx->En). — [DelTA](https://arxiv.org/html/2410.08143v1)
- TransAgents cost about $500 for 240 chapters (about $2.08 per chapter, with GPT-4-turbo in 2024), versus about $168 per chapter for a human. Calls per chapter were not reported. — [TransAgents](https://arxiv.org/html/2405.11804v1)
- translation-agent makes 3 calls (translate, reflect, improve) and is "sometimes worse than" commercial MT. — [translation-agent](https://github.com/andrewyng/translation-agent)
- Step-by-step uses 4+ turns. "Please Translate Again" found that a simple second-pass re-translation or self-refine matched or beat it. — [arXiv 2506.04521v2](https://arxiv.org/html/2506.04521v2)
- Multi-turn document MT adds no extra calls beyond one per paragraph, and earlier turns can reuse prompt caching. Its efficiency was argued, not measured. — [arXiv 2503.10494](https://arxiv.org/html/2503.10494v1)
- The best WMT24 human-rated system made 3 candidate generations per segment plus xCOMET selection. — [WMT24 findings](https://arxiv.org/html/2412.11732v1)

### Inferences
- With ~3k chapters per novel, each extra call per chapter multiplies total cost directly. A default of 1 translation call per chapter, plus deterministic validation, plus a conditional second call (repair or re-translate only on validation failure) puts the multiplier near 1.1-1.3x. If an extra pass is wanted, the evidence favours a plain "translate again / refine" step over elaborate agent role-play.
- Term discovery and summary upkeep can be batched across chapters, for example a summary every N chapters, keeping their share of cost small.

### Gaps
- I found no paper giving token-cost vs. quality curves for literary zh-en at chapter scale.

## Q4. Chunk size, previous text vs. summaries as context, and long-output risks

### Takeaway
Long single-shot outputs risk omissions. DelTA saw up to 10 missing sentences at a 50-sentence window, and single-turn whole documents came out shorter than the reference. A 3-4k-character chapter (roughly 2-3k English words out) is within what current models handle, but omission checks are mandatory. Paragraph-level multi-turn translation, optionally source-primed with the whole chapter, was the best-measured strategy in 2025. Recent target text helps cohesion, while summaries help a little and the term table helps most.

### Cited Findings
- DelTA's window-size study (GPT-3.5, En->Zh): LTCR-1 rose from 75.09 at window size 1 to 86.94 at window size 50, but missing sentences rose from 0 to 10, and quality did not improve consistently. — [DelTA](https://arxiv.org/html/2410.08143v1)
- Single-turn whole-document translation was noticeably shorter on the longest documents (omissions). Multi-turn paragraph segments, especially with the whole source primed first, gave the best dBLEU, COMET and BlonDE. Segment-level with no context was worst for discourse. — [Hu et al. 2025](https://arxiv.org/html/2503.10494v1)
- A BUCC 2025 study found recent LLMs can get worse translating full articles than paragraph by paragraph. An MT Summit 2025 paper found document-level MT still trails sentence-based MT on some problems. Both are reported via a search summary; I did not open the papers. — [MT Summit 2025 proceedings](https://aclanthology.org/2025.mtsummit-1)
- Doc2FRC (arXiv 2609.12674) reports n-gram repetition and quality decay in direct doc-to-doc translation, and proposes fixed-range chunking. — [HF papers 2609.12674](https://huggingface.co/papers/2609.12674)
- DocHPLT compares chunks of 1, 2, 5 and 10 sentences against whole-document translation, with no clear single winner in the fragment I saw. — [DocHPLT arXiv 2508.13079](https://arxiv.org/pdf/2508.13079)
- In DelTA's ablation, previous sentences alone (short-term memory) slightly lowered term consistency. The target-side summary helped more than the source-side summary. — [DelTA](https://arxiv.org/html/2410.08143v1)
- TransAgents' judge deliberately omits long history because agents misuse long context and meaning drifts across revisions. — [TransAgents](https://arxiv.org/html/2405.11804v1)

### Inferences
- Default for us: translate the whole chapter in one call (3-4k chars is moderate). Validate paragraph count and alignment deterministically, using length ratio per paragraph and paragraph-ID markers. Retranslate only the failed paragraphs or windows. Number or tag paragraphs so omissions are detectable.
- Rolling context: include the tail of the previous chapter's English translation (the last few paragraphs) for voice and pronoun continuity, plus a short story-so-far summary in English, rather than the full previous chapter. This keeps the prompt cacheable and limits drift.

### Gaps
- No study I found isolates "previous chapter full text vs. summary" at chapter granularity for web novels.
- No omission rates were found for modern 2025-2026 frontier models on 3-4k-character zh inputs.

## Q5. Glossary injection: full glossary vs. retrieved subset; terminology consistency metrics

### Takeaway
Providing correct terms consistently improves quality and term accuracy. Wrong or random terms help much less. Consistency metrics exist: LTCR-1 measures first-translation consistency for proper nouns (script in DocMTAgent), and the WMT25 terminology task reports term accuracy. I found no direct study of a full glossary vs. a retrieved subset. A matched subset (what we do) is the norm in practical systems.

### Cited Findings
- WMT25 Terminology task (including a document-level en<->zh-TW finance track): proper terminology consistently improved both overall quality and term accuracy. Random terminology gave smaller gains. Document-level translation still lags. — [WMT25 Terminology findings, ACL Anthology 2025.wmt-1.30](https://aclanthology.org/2025.wmt-1.30.pdf)
- Erlendur (a prompt-based system) identifies the glossary terms relevant to the input, injects only those, and carries context from preceding chunks for long inputs. — via search summary of [ACL Anthology entry](https://aclanthology.org/people/robert-fjolnir-birkisson/)
- DelTA's proper-noun records are retrieved per sentence: only nouns appearing in the current source are injected. Adding them gave +3.95 LTCR-1 with a slight COMET cost. — [DelTA](https://arxiv.org/html/2410.08143v1)
- LTCR-1 / LTCR-1f measure whether repeated proper nouns keep their first translation. — [DelTA](https://arxiv.org/html/2410.08143v1); scripts at [DocMTAgent](https://github.com/YutongWang1216/DocMTAgent)
- WMT24 top human-rated systems used explicit terminology settings or a terminology proofreader agent. — [WMT24 findings](https://arxiv.org/html/2412.11732v1)
- A 2025 applied-linguistics study found glossary-based customization improved consistency over translation-memory-only setups, but terminology errors persisted in all systems. — via search summary of [reference-global](https://reference-global.com/article/10.2478/jazcas-2025-0021)

### Inferences
- The glossary is only as good as its resolution step. Wrong terms are injected confidently, so a curated glossary beats an auto-first-seen one.
- Deterministic post-checks matter: verify that each injected source term's target rendering appears, and flag pinyin leftovers or untranslated Han characters.
- A matched subset keeps prompts short. Order it deterministically to keep prompt caching effective.

### Gaps
- I found no controlled experiment comparing a full glossary vs. a retrieved subset for LLM translation. Recommending the subset rests on prompt length and cost plus the DelTA practice.
- I could not verify MAPS (He et al., multi-aspect prompting: keywords, topic and demonstrations, then candidate selection) or Google's "translation with memory" work in this session.
- I found no WMT25 literary/discourse shared-task findings. The WMT24 findings page was the most recent literary edition found.

## Q6. Recommended practical strategy for our scale and budget (synthesis)

### Takeaway
Keep the current architecture. It matches what the evidence supports (a curated term table plus local context). Add cheap, evidence-backed context and checks rather than multi-agent loops.

### Cited Findings
- The term table gives the largest consistency gain: [DelTA](https://arxiv.org/html/2410.08143v1)
- Previous context and source priming improve discourse, and long single outputs risk omission: [Hu et al. 2025](https://arxiv.org/html/2503.10494v1)
- Simple re-translation or refinement is as good as elaborate decomposition: [Please Translate Again](https://arxiv.org/html/2506.04521v2)
- Multi-agent rewriting can drift and omit: [TransAgents](https://arxiv.org/html/2405.11804v1)
- Correct terms help; random or wrong ones help much less: [WMT25 Terminology](https://aclanthology.org/2025.wmt-1.30.pdf)

### Inferences
Recommended per-chapter prompt:
1. The matched glossary subset (curated, with optional short notes on gender or rank).
2. A rolling English "story so far" plus a character/status sheet, refreshed every N chapters (for example 10-25) by one summarization call. This is a cheap analogue of DelTA's bilingual summary; the target-side summary was the more useful half.
3. The last few paragraphs of the previous chapter's English output.
4. The full chapter source with paragraph IDs.

Then:
- Validate deterministically: paragraph count and IDs, length ratio, untranslated CJK, and term adherence (an LTCR-style check against the glossary).
- On failure, run one targeted retry (paragraph window or "translate again").
- Optional: generate 2 candidates and select only for flagged chapters, as the WMT24 winner did with xCOMET.
- Skip TransAgents-style role-play and per-sentence DelTA retrieval. At 1,500-3,200 chapters the 3-10x call multipliers are not justified by the measured gains.

### Gaps
- These recommendations are not validated on xianxia data. A small A/B test is warranted, for example 20 chapters scored by LLM-judge plus term adherence: no context vs. previous tail vs. tail plus summary.
