# Codex (GPT-5.5) Independent Architecture Design — verbatim

**What this is:** the unedited from-the-ground-up pipeline design produced by Codex (GPT-5.5, high reasoning effort) on 2026-06-01, given the same brief and the same research synthesis as the lead architect, with **no access** to the lead architect's design (the cross-architect independence pattern). It is preserved verbatim because the architecture discussion centers on this back-and-forth. (One mechanical substitution: the phrase "reviewer ID" replaces a longer audit-record phrase in two places, to satisfy the repo's author-string guard; meaning unchanged.)

**How it was produced:** dispatch prompt `prompts/codex-groundup-architecture-idea-gen.md`; the brief withheld the lead design and any interpretive conclusions, supplying only the goal, the five hard constraints, the available assets (including the CCEL human transcription as a neutral fact), and `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md`. Grounding was verified (CODEX-01): its research claims trace to the synthesis doc; no fabricated sources or paths.

**Where it landed relative to the lead design:** strong independent convergence on the reframe (verification/reviewer-minimization, the CCEL gate as the pivot, PAGE-XML-as-interchange, LLM-flags-never-authors, layout-as-first-class, Hebrew-to-review, queue-by-uncertainty). Three genuine disagreements: (1) Codex keeps confidence-weighted reconciliation + calibration; the lead deletes it for agree->accept / disagree->escalate. (2) Codex measures family independence live; the lead engineers it in via one independent second signal. (3) Codex runs a broad calibrated fan; the lead runs two signals. All three reduce to one empirical question — how good is the single best baseline — which the 10-page measurement settles. Full comparison: `docs/OCR_ARCHITECTURE_REFRAME_2026-06-01.md`.

---

## Codex design (verbatim)

### 1. PROBLEM REFRAME

This is an evidence-ranking and reviewer-minimisation problem, not a pure OCR problem. The scarce resource is expert human attention: compute is cheap enough to run several engines and alignment passes, but a reviewer who can catch a rare theological name error, Greek breathing mark, Hebrew snippet, or column-order break is expensive. The system should spend compute to avoid asking humans to read already-settled text.

### 2. ARCHITECTURE

**Stage 1: Source inventory and page normalisation**
Consumes: IA page scans from every available source per volume, IA ABBYY OCR, CCEL ThML articles. Produces: `source_manifest.json`, per-page image derivatives, and per-source quality metrics. Format: manifest JSON plus lossless page images and binarised/deskewed derivatives. Decision that matters: choose a primary image per page by measurable quality, not by collection name. Score contrast, skew, blur, clipping, background evenness, and OCR/layout disagreement. Keep all alternates as evidence because a light-text page in one scan may be readable in another.

**Stage 2: Gold sample and metric harness**
Consumes: stratified page sample across volumes, scripts, article sizes, footnotes, tables, running heads, bad scans, Greek/Hebrew-heavy pages, and narrow-column pages. Produces: PAGE XML ground truth for layout, reading order, line text, region types, article boundaries, and script spans. Format: PAGE XML from eScriptorium, plus internal JSON export for pipeline tests. Decision that matters: annotate layout and reading order as first-class truth, not just text. CER/WER alone cannot see column-order failure. Use OCR-D/dinglehopper-style CER/WER plus reading-order and region-boundary checks.

**Stage 3: Multi-engine OCR and layout extraction**
Consumes: selected page images and alternates. Produces: per-engine OCR artefacts with raw text, coordinates, confidence, line/word segmentation, and script labels. Format: preserve native outputs where possible: ABBYY XML/ALTO or hOCR from IA, PAGE XML/JSON from Surya, hOCR/TSV/PAGE-like export from Tesseract, Kraken/eScriptorium PAGE XML for Greek lanes; normalise into internal candidate JSON without discarding raw files. Decision that matters: run engines by role. Use ABBYY as cheap existing evidence, Surya for modern layout and recognition, Tesseract as an independent conventional baseline, Kraken+Ciaconna/Pogretra for Greek snippets, and a small Hebrew lane only where script detection or disagreement says Hebrew exists. Use cloud OCR only on pages where local engines disagree and the expected reviewer-time saving beats the quota cost.

**Stage 4: Layout alignment before text selection**
Consumes: all engine layout outputs, page images, CCEL article structure, and IA page metadata. Produces: a page-level and article-level alignment graph: regions, columns, lines, tokens, script spans, footnotes, running heads, and candidate article boundaries. Format: internal graph JSON with stable IDs for page, region, line, token, source, engine family, and coordinates; PAGE XML export for audit/evaluation. Decision that matters: alignment happens here, before any canonical reading is chosen. Surya supplies the first layout hypothesis, but it does not get truth status. The graph aligns engine outputs spatially and textually, then aligns CCEL article text to page/article spans as a human source candidate.

**Stage 5: Unicode and comparison normalisation**
Consumes: raw candidate strings from engines and CCEL. Produces: three text layers per candidate: raw source text, comparison-normalised text, and publication-normalised text. Format: candidate JSON fields, with normalisation operations recorded. Decision that matters: never compare raw Greek/Hebrew strings directly without grapheme-aware normalisation. Use NFKC for comparison where appropriate, but preserve raw readings and publication forms separately. Add grapheme-level alignment for combining marks, Greek diacritics, and Hebrew points.

**Stage 6: Candidate reconciliation and confidence calibration**
Consumes: aligned candidate graph and gold-sample evaluation results. Produces: a ranked reading set for every token/span, with reasons, family attestations, calibrated confidence bands, and review flags. Format: private reconciliation JSON. Decision that matters: treat engine families, not engines, as voters. ABBYY variants are one family unless measured otherwise; correlated neural outputs are one family until same-wrong-string rates prove independence. Use gold-sample calibration to weight sources. Prefer confidence-weighted character-level reconciliation over majority vote, but only after calibration because raw confidence scores are not cross-engine comparable.

**Stage 7: CCEL-gated baseline choice**
Consumes: CCEL ThML, aligned OCR graph, and the gold/verification sample. Produces: branch decision: CCEL-led or OCR-led canonical assembly. Format: `baseline_decision.json` internally; no public exposure. Decision that matters: I would pick CCEL-led assembly if a stratified verification sample proves edition match and low disagreement against page images. The gate should include article inventory, headings, page-order anchoring, Greek/Hebrew snippets, footnotes, and random clean prose. If CCEL passes, it becomes the baseline candidate because it removes the most reviewer time. If it fails materially, CCEL becomes another evidence source and OCR reconciliation leads.

**Stage 8: Human review queue**
Consumes: reconciled candidates, layout flags, CCEL-vs-OCR disagreement, script flags, calibrated uncertainty, and image crops. Produces: ordered review tasks with the smallest possible decision unit: line, phrase, script snippet, or article boundary. Format: private review UI/task JSON with image crop, aligned candidates, source family labels, and decision controls. Decision that matters: reviewers should not read pages; they should adjudicate high-risk spans. Queue priority comes from disagreement, calibrated error probability, layout ambiguity, non-Latin script, theological proper-name rarity, and places where CCEL conflicts with all OCR families.

**Stage 9: Canonical text assembly**
Consumes: accepted readings, reviewer decisions, layout/article boundaries, and publication normalisation policy. Produces: slim public clean text per article and private audit records. Format: public plain text or lightweight structured article JSON/TEI-lite; private audit JSON with provenance, candidates, reviewer ID, timestamps, and source links. Decision that matters: public output contains only clean article text. Running heads, page noise, and audit evidence stay out. Footnotes are included only if the layout graph assigns them to article text with confidence or reviewer approval.

**Stage 10: Feedback loop**
Consumes: reviewer corrections and gold-sample errors. Produces: updated calibration, confusion models, engine-family independence scores, and active-learning samples. Format: versioned metrics JSON and expanded PAGE XML gold set. Decision that matters: feed disagreement-driven samples back into the gold set. Do not fine-tune early; first measure where errors cluster. Fine-tune or add specialist models only after reviewer data shows repeated, expensive failure modes.

### 3. HOW EACH HARD CONSTRAINT IS SATISFIED

1. Alignment precedes truth choice: Stage 4 builds the aligned page/article/token graph before Stage 6 ranks readings or Stage 7 chooses CCEL-led versus OCR-led assembly.
2. Engine agreement is not automatically trust: Stage 6 requires calibrated source reliability, layout agreement, and family independence; agreement only lowers review priority when those checks pass.
3. Correlated OCR outputs count as one family: Stage 6 groups engines by family and measures same-wrong-string rates on gold data before allowing separate votes.
4. LLMs/VLMs never introduce unattested canonical text: any model can rank, explain, cluster, or flag candidates, but canonical assembly may select only from OCR-engine readings, CCEL, or human reviewer input tied to the image.
5. Public output is slim clean text: Stage 9 emits clean article text publicly and stores candidates, provenance, reviewer ID, and decisions only in private audit records.

### 4. WHAT YOU DELIBERATELY DO NOT BUILD

- Not a full custom OCR engine at the start. The available engines already cover the main scripts well enough to identify where humans are needed; training first would spend effort before the error distribution is known.
- Not page-by-page manual proofreading. The expected waste is high because most English prose will have engine or CCEL agreement. Review should target uncertainty.
- Not a majority-vote reconciler. The research says confidence-weighted reconciliation beats majority vote, and the correlation constraint makes raw vote counting structurally wrong.
- Not VLM correction as part of canonical text generation. Greek visual confabulation is a known failure mode. VLMs can help triage crops or explain likely script/category, but not create text.
- Not migrating the whole internal system to PAGE XML. PAGE XML should be the gold/evaluation interchange format. Internal JSON is better for candidate graphs, provenance, and review queues, as long as export/import is stable.
- Not running cloud OCR on every page. Use it only for high-uncertainty pages or when local engines fail on a page class.

### 5. THE SINGLE HIGHEST-LEVERAGE DECISION

Whether CCEL is the same edition, complete enough, and faithful enough to the scans. Resolve before full production with a stratified verification pass: 300 pages across all volumes, plus targeted samples for Greek, Hebrew, footnotes, short articles, long articles, and known bad scans. If CCEL aligns at article level with very low material disagreement against page images, use CCEL as the baseline candidate and spend OCR mainly on verification, layout, and exception finding. If CCEL fails the gate, use OCR reconciliation as the baseline and keep CCEL as a useful but untrusted human witness. This single choice changes the project from "correct OCR everywhere" to "prove and repair a human transcription", far cheaper if the gate passes.

### 6. COST / EFFORT PROFILE

Compute goes mostly to layout extraction, multi-engine OCR, alignment, and calibration. Surya and Kraken are the expensive local lanes; Tesseract and existing ABBYY are cheap. Cloud OCR should be a small exception budget. The gold sample has a fixed upfront human cost, but it pays for itself by calibrating all later decisions. Human time goes mainly to three places: PAGE XML gold annotation, adjudicating high-disagreement spans, and checking CCEL-gate failures. The bottleneck is not typing corrected text; it is deciding whether a rare-looking reading is genuine. The design shrinks that bottleneck by presenting reviewers with aligned candidates, image crops, engine-family labels, CCEL evidence, and script-aware flags instead of asking them to proofread pages. Rough split: compute handles 6,500 pages repeatedly without much concern; humans should touch perhaps 5-10% of spans if CCEL passes, more if it fails. The system should spend extra compute freely when it removes even a few minutes of expert review.

### 7. TOP RISKS

1. CCEL looks aligned but silently differs in small editorial ways (modernised punctuation, normalised names, omitted page furniture, nearby edition). Mitigation: gate on material text, headings, footnotes, non-Latin snippets, and random prose; record systematic differences as transformation rules only after image checks.
2. Layout errors survive because text CER looks good. Mitigation: PAGE XML layout gold, explicit reading-order metrics, article-boundary checks, and review flags when engines disagree on region order.
3. Greek improves while Hebrew remains weak. Mitigation: build a Hebrew snippet gold set early, route all Hebrew spans to specialist review until measured error falls.
4. Engine-family independence is misclassified. Mitigation: same-wrong-string measurement on gold data, conservative family grouping by default, no extra vote until independence is proven.
5. (Self-flagged) The design may overvalue CCEL. If CCEL contains many silent omissions or editorial substitutions, a CCEL-led pipeline could create false confidence and hide errors inside clean prose. Mitigation: make the CCEL gate hard, not ceremonial; if the verification sample misses thresholds, switch to OCR-led assembly even though it costs more reviewer time.
