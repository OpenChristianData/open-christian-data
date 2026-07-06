# OCR Research Synthesis — 2026-05-31

Deep research on OCR corpora, benchmark datasets, evaluation metrics, and multi-engine
reconciliation methods applicable to the Schaff-Herzog pipeline. Synthesized from two
parallel reports (deep-research workflow + independent ChatGPT 4o report) and cross-diffed.

Sources: GT4HistComment, GT4HistOCR, Patrologia Graeca corpus, IMPACT, GRPOLY-DB,
OCR-D, eScriptorium, Reul et al. 2018, Romanello et al. 2021, arXiv 2409.04117,
arXiv 2502.01205, arXiv 2605.27750, and others catalogued in the bibliography.

---

## Key findings that affect this pipeline

1. **No single engine dominates across scripts.** Kraken+Ciaconna ~7% CER on 19th-c polytonic
   Greek vs Tesseract ~13% (Romanello 2021). No engine dominates Latin either. Multi-engine
   reconciliation is empirically warranted.

2. **Confidence scores are NOT cross-engine comparable.** Commercial engines: ECE 1.1-3.6%.
   Open-source: ECE 10.3-22.6% (arXiv 2409.04117). ABBYY confidence=0.9 and Tesseract
   confidence=0.9 mean different things. NOTE: S3 uses attestation counts not raw confidence
   scores, so this concern does NOT apply to the current reconciler design — it is already correct.

3. **Confidence-weighted voting beats majority vote.** Cross-fold training + confidence-weighted
   voting reduces errors up to 53% over single-model baseline (Reul et al. 2018). Active learning
   via disagreement selection adds a further 16%.

4. **LLM post-correction is language-dependent and has hallucination failure modes.** GPT-4o:
   58.1% CER improvement on 18th-c English, only 11.9% on Finnish. Llama models insert wrapper
   phrases requiring mandatory removal (arXiv 2502.01205). Confirms the no-unattested-canonical-text
   constraint in llm_evidence_provider.py.

5. **VLM visual confabulation is a concrete failure mode for Greek.** VLMs generate fluent Greek
   text that does not correspond to the image (arXiv 2605.27750). Relevant when scan_crop (arch8)
   brings image inputs into the LLM consultation. The current text-only consultation is already
   sound; flag this for arch8.

6. **PAGE XML is the de facto GT standard** (OCR-D, eScriptorium, Transkribus). Adopt for
   gold sample annotation via eScriptorium; keep custom JSON schemas as the internal canonical
   format (migration cost not justified).

7. **Multi-column encyclopedia layout GT does not exist** as a published benchmark. The closest
   are GT4HistComment (commentary layout, 19th-c Latin+Greek) and Patrologia Graeca (bilingual
   Greek-Latin columns). A Schaff-Herzog-specific gold sample is unavoidable.

---

## Top corpora to inspect

| Rank | Corpus | Why relevant | Access |
|------|--------|-------------|--------|
| 1 | GT4HistComment + GT4HistCommentLayout | 3,356 GT lines, 19th-c Latin+polytonic Greek, commentary layout; includes engine benchmarks (Kraken, Tesseract) | CC-BY; GitHub: AjaxMultiCommentary/GT-commentaries-OCR |
| 2 | GT4HistOCR (arXiv 1809.05501) | 313,173 line pairs, 15th-19th-c, German Fraktur + Early Modern Latin; largest open training set for Tesseract/Calamari fine-tuning | CC-BY 4.0; Zenodo |
| 3 | Patrologia Graeca Corpus (arXiv 2603.09470) | 19th-c bilingual Greek-Latin theological, complex column layout, degraded polytonic Greek; YOLO layout + CRNN recognition | Open; calfa-co/Patrologia-Graeca on GitHub |
| 4 | IMPACT Corpus (impacts-connect.eu) | 45K+ samples, 18 languages, 10 scripts including Greek and Hebrew; PAGE XML | Mixed CC |
| 5 | GRPOLY-DB | Greek polytonic historical, 15,084 lines; Tesseract+ABBYY benchmarks | Academic licence; ICDAR proceedings |
| 6 | OCR-D GT corpus (ocr-d.de) | Historical German/Latin PAGE XML; multi-column layouts, footnotes, marginalia | CC-BY-SA |
| 7 | GT4HistCommentLayout (AjaxMultiCommentary) | Layout annotations for the GT4HistComment pages; region type + reading order | CC-BY |
| 8 | ENP — Europeana Newspapers (PRImA) | Multi-column historical newspaper PAGE XML; region outlines, type labels, reading order | PRImA; check licence |

---

## Top methods and tools

| Rank | Method/Tool | What it improves | Source |
|------|-------------|-----------------|--------|
| 1 | Cross-fold voting + confidence-weighted character-level reconciliation | S3 reconciler: 46-53% error reduction over single-model | Reul et al. 2018 (arXiv 1802.10038) |
| 2 | Per-engine confidence recalibration (Platt scaling) | S4 reliability matrix: makes confidence comparable across families | arXiv 2409.04117 |
| 3 | OCR-D evaluation framework (dinglehopper, ocrevalUAtion) | CER/WER + layout + reading-order in one framework | ocr-d.de/en/spec/ocrd_eval.html |
| 4 | eScriptorium (Kiessling et al.) | S5 reviewer: open-source annotation + correction, Kraken integration, PAGE XML output | escriptorium.readthedocs.io |
| 5 | Active learning — maximal-disagreement selection | Gold sample growth: 16% additional improvement | Reul et al. 2018 |
| 6 | Kraken + Ciaconna/Pogretra pretrained models | Greek accuracy: ~7% vs ~13% CER on 19th-c polytonic Greek | AjaxMultiCommentary/OCR-kraken-models |
| 7 | dinglehopper | PAGE-aware CER/WER evaluation | qurator-spk/dinglehopper |
| 8 | ocrevalUAtion | Cross-format eval: PAGE, ALTO, hOCR, ABBYY/FineReader XML | impactcentre/ocrevalUAtion |
| 9 | Google low-cost OCR correction (Abdulkader & Casey) | Reviewer queue scoring: word-error probability from engine features | research.google.com/pubs/archive/35525.pdf |
| 10 | MEMOE multi-evidence multi-engine OCR | S3 architecture precedent: beyond majority voting | Borovikov; ResearchGate |

---

## Gaps in the current pipeline design (as of 2026-05-31 research)

1. **WCT alignment too word-centred for Greek/Hebrew.** Word-level alignment loses signal on
   composed/decomposed diacritics and combining marks. Add grapheme-level confusion layer.
   (Plan B addresses multi-char confusions in the confusion model.)

2. **Layout GT not yet a first-class artefact.** Multi-column column-order errors are invisible
   to CER/WER but catastrophic for publication. Gold sample must include PAGE XML layout
   annotations (region types, column order, article boundaries).

3. **Reading-order error not tracked.** Add to S4 metric suite. OCR-D evaluation spec includes it.

4. **Greek is tractable; Hebrew has no specialist lane.** GT4HistComment + Ciaconna handle Greek.
   Hebrew needs a custom snippet gold set.

5. **Unicode normalisation policy not explicit as a pipeline stage.** Store raw engine text,
   normalised comparison text, and publication text separately. (NFKC already in wct_builder.py.)

6. **Engine correlation is declared, not measured at runtime.** family_independence.py measures
   same-wrong-string rates but the measurement must run on real data before the family map is
   trusted. Plan A adds the kraken-greek lane; the independence measurement should run after.

7. **LLM visual attestation gate is a future concern (arch8).** When scan_crop brings image
   inputs into LLM consultation, add cross-family attestation requirement to prevent correlated
   hallucination from passing the attestation check. Not a current issue — text-only consultation
   is already sound.

8. **Active learning feedback loop not yet wired.** gold_strata.py uses S1 sidecar proxies.
   Add S3 disagreement-driven sampling after real WCT files exist.

---

## What is already built (confirmed by code investigation)

| Research recommendation | Existing implementation | File |
|---|---|---|
| Alignment before truth choice | WCT Layer-1 boundary | wct_builder.py |
| NFKC normalisation | S8 normalisation step | wct_builder.py |
| Engine family independence measurement | B9 same-wrong-string measurement | family_independence.py |
| LLM no-unattested-canonical-text | agreed_unattested block | llm_evidence_provider.py |
| Three-state LLM evidence | B12 admit_for_resolution / evidence_only / exclude | llm_evidence_provider.py |
| Beta-Binomial credible interval calibration | B16 B→A gate | calibration.py |
| Gold strata stratification | B7 | gold_strata.py |
| Reviewer queue assembly | arch7 MVP | queue_assembly.py |
| OCR error models for Greek + Hebrew | grc.yaml, hbo.yaml | build/lib/ocr_error_models/ |
| S3 uses attestation counts not raw confidence | attesting_families count | s3_reconciler.py |

---

## Plans produced (2026-05-31)

- **Plan A** (`plans/2026-05-31-ocr-research-integration-A.md`): Calamari retirement + Kraken Greek lane (Ciaconna model). Chip spawned.
- **Plan B** (`prompts/codex-plan-b-wct-multichar-transducer.md`): wct_builder.py loads multi-char confusions from YAML. Chip spawned.
- **Plan C** (`prompts/codex-plan-c-cer-evaluation-harness.md`): build/tools/evaluate_cer.py — CER/WER harness against external GT. Chip spawned.
- **Plan D** (`prompts/codex-plan-d-disagreement-awareness.md`): queue_assembly.py disagreement_score + reconcile/classify.py correlated-family labeling. Chip spawned.

**Deferred (explicit gates):**
- gold_strata.py S3 disagreement feedback — gate: real WCT files on disk
- llm_evidence_provider.py cross-family attestation — gate: arch8 scan_crop implementation

---

## Bibliography (key sources)

- Romanello et al. 2021 — GT4HistComment, Kraken+Ciaconna benchmarks: https://arxiv.org/pdf/2110.06817
- GT4HistComment dataset: https://github.com/AjaxMultiCommentary/GT-commentaries-OCR
- Reul et al. 2018 — cross-fold voting + active learning: https://arxiv.org/abs/1802.10038
- Springmann et al. 2017 — confidence-weighted voting: https://arxiv.org/pdf/1711.09670
- GT4HistOCR: https://zenodo.org/records/1344132
- Patrologia Graeca Corpus 2026: https://arxiv.org/abs/2603.09470
- arXiv 2409.04117 — engine confidence calibration comparison (ECE gap)
- arXiv 2502.01205 — LLM post-correction language dependence (Hamalainen 2025)
- arXiv 2605.27750 — Greek VLM visual grounding failures (CRITICAL for arch8)
- arXiv 2603.02803 — Structure-aware text recognition for Ancient Greek
- OCR-D evaluation spec: https://ocr-d.de/en/spec/ocrd_eval.html
- eScriptorium: https://escriptorium.readthedocs.io
- dinglehopper: https://github.com/qurator-spk/dinglehopper
- ocrevalUAtion: https://github.com/impactcentre/ocrevalUAtion
- Google low-cost correction: https://research.google.com/pubs/archive/35525.pdf
- MEMOE multi-engine OCR: https://www.researchgate.net/publication/252980446
- Nikolaou et al. 2022 — survey of 65 historical document datasets: https://link.springer.com/article/10.1007/s10032-022-00405-8
- HTR-United catalogue: https://htr-united.github.io
- Hebrew OCR post-correction: https://arxiv.org/abs/2307.16213
- ENP dataset (PRImA): https://www.primaresearch.org/datasets/ENP

---

## 2026-06-05 update — gap analysis, direction, and the real-word-error problem

A ground-up reread of this synthesis against the built pipeline surfaced that the highest-return research-attested techniques are **unsupervised** (gold-free) and largely **unbuilt**. The build has the multi-engine alignment and the gold-gated reliability matrix, but skipped the unsupervised middle of the canonical post-OCR pipeline (align -> vote -> lexicon rescore -> LM rescore).

### Research-attested techniques not yet built (gold-free)

| Technique | Source | Status before this date |
|---|---|---|
| Character-column voting | Reul et al. 2018 (~46-53% single-engine error reduction) | Not built. The WCT does confusion-weighted character alignment for slot membership only (`wct_builder.py`), then stops — it never votes within a slot. |
| Lexicality rescoring (domain lexicon / profiler) | ocrd_cis, PoCoTo | Signal present at weight 0.0 in `s3_reconciler.py`; unused. |
| In-corpus n-gram / character LM rescoring | post-OCR LM literature; lightweight cousin of LLM correction | Not built. |
| Active-learning max-disagreement sample selection | Reul et al. 2018 (+16%) | Flagged gap; not wired. |

These four are scoped as the **gold-free corrector stack (P1-P5)** in `docs/BUILD_ROADMAP_2026-06-05.md` and `docs/DESIGN_BRIEF_gold_free_corrector.md`, to run before human adjudication and validated against a surrogate rather than gated behind human gold (ADR-0015). The unweighted character vote is gold-free; only the confidence-*weighted* layer needs human gold.

### The real-word-error problem (the residual danger)

OCR errors split into **non-word errors** (output is not a real word — caught by any dictionary) and **real-word errors** (output is a valid but wrong word — invisible to lexical and most LM checks). Source: Kukich 1992 (taxonomy). Key consequences for this pipeline:

- Lexical filtering **concentrates** the danger: as non-word errors are removed, the residual is increasingly real-word errors — the last fraction of a percent is the hard, dangerous kind.
- The detection method in early work (Mays/Damerau/Mercer 1991, trigrams) is superseded; modern LLMs are genuinely strong real-word-error detectors (world knowledge). But the corrector itself can **inject** real-word errors at permissive levels — Levchenko 2025 and the Greek VLM confabulation finding (arXiv 2605.27750) show post-OCR correction can manufacture fluent, plausible, wrong text.
- Correlated engine agreement on the same wrong real word defeats cross-engine checks — hence family independence is load-bearing, and the M2 "genuine multi-engine agreement errors" finding is the worst case.
- **Real-word-error rate is measurable exactly only against a trusted reference** (the surrogate: output is a valid lexical word AND output != gold). Off the surrogate, on the corpus, it is *estimated* via an LLM/VLM detector pass plus a human-adjudicated sample. It must be reported as a first-class metric per correction level, distinct from CER (DESIGN_BRIEF HR4).
- The minimiser for human time is routing, not blanket trust: protected classes (proper names, numbers, dates, Scripture references, Greek, Hebrew) are the real-word-error reservoir and route to human/VLM regardless of engine agreement (DESIGN_BRIEF HR5).

### Canonical-text and reference decisions recorded

- **ADR-0014** — canonical text may be a machine-*composed* reading past the attestation gate, carrying per-character provenance and a derivation level (0-3); publication threshold set by surrogate-measured false-correction rate.
- **ADR-0015** — surrogate (Jewish Encyclopedia 1906; paired diplomatic text + facsimiles, same edition, non-circular) is a validator, not a runtime prerequisite; the auto-accept threshold targets ~0.1% false-correction (the 99.9% first-pass bar).

### Bibliography additions

- Kukich 1992 — Techniques for automatically correcting words in text (non-word vs real-word taxonomy): ACM Computing Surveys 24(4).
- Mays, Damerau & Mercer 1991 — context-based spelling correction (trigram method; superseded by modern LLM detection).
- Levchenko 2025 — LLM historical-OCR correction introduces period distortions / can degrade results: arXiv 2510.06743.
