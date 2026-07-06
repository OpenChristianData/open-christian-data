# OCR Engine Data Inventory

*Last updated 2026-05-31 (commit `3c1b0764`+).*

Reference catalogue of what each OCR engine in the pipeline produces, what the sidecar extracts, and what stays in raw or is not captured. Use this when deciding which engine to use for a task, or when adding a new consumer that reads sidecar fields.

---

## Current engine roster

Five active OCR sources run or normalise corpus-wide via the S1 runner harness.
Calamari remains documented for audit history but is no longer active.

| Engine | Status | Runner | Source |
|--------|--------|--------|--------|
| Tesseract 5.5 | Active | `build/parsers/s1_tesseract_runner.py` | Local binary, `pytesseract` |
| Surya | Active | `build/parsers/s1_surya_runner.py` | Venv `surya-py312` |
| ABBYY (IA) | Active | `build/parsers/s1_abbyy_normalizer.py` | Pre-computed by Internet Archive |
| Kraken | Active | `build/parsers/s1_kraken_runner.py` | Venv `kraken-py312`, general historical models |
| Kraken (Greek) | Active | `build/parsers/s1_kraken_greek_runner.py` | Venv `kraken-py312`, Ciaconna/Pogretra models |
| Calamari | Retired 2026-05-31 | `build/parsers/s1_calamari_runner.py` | Tested; insufficient quality on NSH scans |

Cloud engines (Google Cloud Vision, AWS Textract, Azure AI Vision, Azure Document Intelligence) were used during the evaluation phase. See [Cloud engines (retired)](#cloud-engines-retired) below.

---

## S1 sidecar format (all current engines)

Every S1 sidecar conforms to `schemas/v1/sidecar-page-v1.schema.json`. Top-level structure:

```json
{
  "schema_version": "sidecar-page-v1",
  "manifest_id": "sm-sha256:...",
  "rendering_id": "<lineage>/<work>/<edition>/v1",
  "page_native_id": "page_0010",
  "page_sequence": 10,
  "page_dimensions_native": {"width": 3000, "height": 4500, "unit": "pixel"},
  "blocks": [...],
  "parsed_keys_index": [...],
  "page_extras_carried": {...},
  "page_extras_carried_keys": [...],
  "page_extras_jcs_sha256": "sha256:...",
  "source_payload_sha256": "sha256:..."
}
```

Block hierarchy: `blocks[].lines[].words[]`. Each line has `line_native_id`, `source_raw`, `confidence`, `bbox_native`, `words`. Each word has `word_native_id`, `source_raw`, `confidence`, `bbox_native`. The `observation_token_id` hash uniquely identifies each token across rendering lineages.

`page_extras_carried` carries all engine-specific metadata that does not fit the normalized block structure. It has `additionalProperties: true` — the schema imposes no constraint on its keys. `observed_line` and `observed_word` have `additionalProperties: false`; new per-line or per-word fields require a schema change to `sidecar-page-v1.schema.json`.

---

## Per-engine inventory

### Tesseract 5.5 PSM=1

**Venv:** `tesseract-py314` (uses system `tesseract.exe` via `pytesseract`).

**Languages:** `eng+grc+heb+lat+deu+fra+syr` — handles Greek, Hebrew, Latin, German, French, Syriac in multilingual passages.

**Worker:** `build/tools/ocr_runners/tesseract_page.py` uses `pytesseract.image_to_pdf_or_hocr` (hOCR output). Per-line structural attributes are parsed from the hOCR and emitted as a side-channel.

**Sidecar fields extracted:**

| Where | Field | Notes |
|---|---|---|
| `page_extras_carried` | `engine_version` | pytesseract-reported version string |
| `page_extras_carried` | `tesseract_line_attrs` | Dict `{line_native_id: {x_size, baseline, x_descenders, x_ascenders}}`. `x_size` is x-height in pixels — bimodal on Schaff-Herzog (~50–60px headwords, ~65–74px body text). `baseline` is `[slope, intercept]` polynomial. Added 2026-05-31. |
| line | `source_raw`, `confidence`, `bbox_native` | Axis-aligned bbox; confidence = mean of word confidences |
| word | `source_raw`, `confidence`, `bbox_native` | Axis-aligned bbox; confidence from hOCR `x_wconf` (0–100 scaled to 0–1) |

**Raw artefact:** `reports/s1-sidecars/tesseract-py314-v1/vol_NN/raw/page_NNNN.tesseract.hocr`.

**Available in hOCR, not extracted:** `ocr_par` paragraph grouping, `ocr_textfloat` (sidebar regions), `ocr_separator` (rule lines), symbol-level data.

---

### Surya

**Venv:** `surya-py312`. Uses `surya.recognition.RecognitionPredictor` (0.8+ API) with a `FoundationPredictor` + `DetectionPredictor` init before the page loop (preflight gate added 2026-05-31).

**Current sidecar fields extracted:**

| Where | Field | Notes |
|---|---|---|
| `page_extras_carried` | `api_used` | API variant used (`RecognitionPredictor` vs legacy) |
| `page_extras_carried` | `engine_version` | `surya.__version__` |
| `page_extras_carried` | `surya_original_text_good` | Dict `{line_native_id: bool}` — model-own trust flag per line. Added 2026-05-31. Present only when the API populates `TextLine.original_text_good`. |
| line | `source_raw`, `confidence`, `bbox_native` | `confidence` from `TextLine.confidence` |
| word | `source_raw`, `confidence`, `bbox_native` | Reads from `TextLine.words` where available; falls back to whitespace-split with `bbox_native: null` |

**Raw artefact:** `reports/s1-sidecars/surya-py312-v1/vol_NN/raw/page_NNNN.surya.raw.json`.

**Available in raw, not extracted:** `TextWord.polygon` (richer word-boundary polygon beyond axis-aligned bbox). Deferred to heading-detection work.

**Throughput (no GPU, 5034px NSH scans, benchmarked 2026-06-01):**

| Config | Time/page | Peak RAM | Notes |
|---|---|---|---|
| Full resolution (5034px) | ~350s | ~8 GB | Baseline |
| `--max-width 2500` | ~185s | ~6.2 GB | Recommended — no quality loss |
| `--max-width 3000` | ~202s | — | Conservative option |

Word-sequence accuracy at `--max-width 2500` vs full resolution: 96.6% match.
Mean confidence is essentially unchanged; in practice the downsampled output
is marginally better on diacritics and rare proper nouns (PIL resize gives
Surya a cleaner input than JPEG compression artifacts at native resolution).

**Run Surya separately, not through the fanout.** The fanout runs all engines
sequentially; Surya's cost dominates and there is no way to run it alone via
that script. Use the individual runner:

```
py -3 build/parsers/s1_surya_runner.py \
    --volume 1 --pages 10-20 \
    --max-width 2500 --throttle test
```

For unattended overnight runs use `--throttle overnight` (idle CPU priority).
A full vol 1 pass (543 images) at `--max-width 2500` takes approximately 27
hours; plan for multi-night segments of ~170 pages.

**Downscaling audit trail:** when `--max-width` is set, `surya_inference_width`
and `surya_scale_to_native` are written into `page_extras_carried` so each
sidecar is self-describing. The manifest records `surya_max_width` in
`bundle_extras_carried`.

---

### ABBYY (Internet Archive pre-computed)

**Source:** Internet Archive's ABBYY FineReader OCR output, delivered as hOCR HTML alongside the JPEG scans. Not an active API call — the normalizer reads the pre-computed files.

**Parser:** `build/parsers/s1_abbyy_normalizer.py`.

**Sidecar fields extracted:**

| Where | Field | Notes |
|---|---|---|
| `page_extras_carried` | `engine_version` | IA-reported ABBYY version if present |
| line | `source_raw`, `confidence`, `bbox_native` | Bbox from hOCR `bbox` attribute |
| word | `source_raw`, `confidence`, `bbox_native` | Per-word confidence from ABBYY `x_wconf` |

**Known limitation:** ABBYY reports `x_fsize 9` uniformly for all words on Schaff-Herzog pages — headword small-caps and body text cannot be distinguished by font-size attribute. See `docs/` for the OCR-attribute analysis (2026-05-19 incident).

**Raw artefact:** `.hocr` files in `raw/internet-archive/schaff-herzog-pages/`.

---

### Kraken

**Venv:** `kraken-py312`. Uses `kraken.blla` for line segmentation and `kraken.rpred` for recognition. Model files at `~/ocr-engines/kraken-models/` (preflight gate verifies non-empty files before the page loop).

**Current sidecar fields extracted:**

| Where | Field | Notes |
|---|---|---|
| `page_extras_carried` | `engine_version` | `kraken.__version__` |
| `page_extras_carried` | `model_id` | Path or ID of the model used |
| `page_extras_carried` | `kraken_char_confidences` | Dict `{line_native_id: [float, ...]}` — full per-character confidence list (the mean of this list is the `confidence` field on the line). Added 2026-05-31. |
| `page_extras_carried` | `kraken_line_polygons` | Dict `{line_native_id: [[x,y], ...]}` — line boundary polygon from `blla` segmenter. Added 2026-05-31. Present only when the record exposes a `boundary` / `polygon` attribute. |
| line | `source_raw`, `confidence`, `bbox_native` | Bbox is the axis-aligned envelope of the segmenter result |
| word | `source_raw`, `confidence`, `bbox_native: null` | Whitespace-split words inherit line confidence; individual bboxes not available from Kraken 7.x |

**Raw artefact:** `reports/s1-sidecars/kraken-py312-v1/vol_NN/raw/page_NNNN.kraken.raw.json`.

**Available in raw, not extracted:** engine-native segmentation and recognition record fields not mapped into `blocks`, `kraken_char_confidences`, or `kraken_line_polygons`.

---

### Kraken (Greek specialist) — kraken-greek-py312-v1

**Venv:** `kraken-py312` (same as standard Kraken lane).

**Model discovery:** Prefers model filenames containing `ciaconna`, `greek`, `grc`, `pogretra`,
`polytonic`, `ancient`; falls back to general historical models if no Greek-specialist model
is installed. See `plans/2026-05-31-ocr-research-integration-A.md` Task 1 for model install.

**ENGINE_FAMILY:** `"kraken"` — both Kraken lanes collapse to one independence block in
`family_independence.py` by declaration. Independence between Kraken and Kraken-Greek is
low by construction (same architecture, partially overlapping training); treat them as
one family.

**Sidecar fields:** Same structure as Kraken. Side-channel keys are `kraken_greek_char_confidences`
and `kraken_greek_line_polygons` (not `kraken_*`) to avoid collision when both sidecars exist.

**Raw artefact:** `reports/s1-sidecars/kraken-greek-py312-v1/vol_NN/raw/page_NNNN.kraken-greek.raw.json`.

**Why add this lane:** Romanello et al. (2021) benchmark shows Kraken with Ciaconna achieves
~7% CER on 19th-century polytonic Greek vs ~13% for Tesseract — a near-2x improvement on
Greek-dense pages. Standard Kraken uses general historical models trained primarily on
Latin/German. Schaff-Herzog contains inline Greek in every volume.

---

### Calamari (retired 2026-05-31)

**Venv:** `calamari-py311`. Uses `calamari_ocr` with a checkpoint ensemble (`~/ocr-engines/calamari-models/antiqua_historical/`). Retired after testing on NSH scans; retained for audit history, not active corpus production.

**Current sidecar fields extracted:**

| Where | Field | Notes |
|---|---|---|
| `page_extras_carried` | `engine_version` | Calamari version string |
| `page_extras_carried` | `model_id` | Model directory path |
| line | `source_raw`, `confidence`, `bbox_native` | Bbox spans full page width (accepted known limitation — `blla` segmentation not used; Calamari provides line text but full-width geometry) |
| word | `source_raw`, `confidence`, `bbox_native: null` | Whitespace-split; individual word bboxes not available |

**Known limitation:** Line bbox always covers the full scan width (`x=0, w=page_width`). Downstream geometry consumers cannot use Calamari line boxes for column detection or zone classification. This was one reason Calamari was not retained.

---

## Engine selection guidance

| Task | Recommended engine(s) | Reason |
|---|---|---|
| Full-volume baseline OCR | Tesseract | Unlimited, deterministic, seven language packs |
| Full-volume neural OCR | Surya or Kraken | Free, GPU-optional, strong on historical print |
| Per-character confidence analysis | Kraken | `kraken_char_confidences` in extras |
| Line-level geometry / column detection | Kraken | `kraken_line_polygons` in extras |
| Model trust signal per line | Surya | `surya_original_text_good` in extras |
| Reconciliation against IA source | ABBYY | Pre-computed, zero API cost, matches IA page set |
| Heading-detection baseline | Tesseract | `x_size` bimodal split (via `tesseract_line_attrs`) is the only engine that exposes usable small-caps signal on Schaff-Herzog |

---

## When to re-parse vs re-OCR

**Re-parse** (read the raw artefact and update the sidecar): use when the field you need was already captured by the engine but not extracted into the current sidecar. Current S1 raw artefacts exist for ABBYY hOCR, Tesseract hOCR, Surya raw JSON, Kraken raw JSON, and Kraken Greek raw JSON.

**Re-OCR** (run the engine again): required when the field requires a different API call or config. Examples: switching Tesseract from TSV to hOCR output; running Kraken with a different model.

---

## Schaff-Herzog page-count baseline

**Vol 01 image breakdown:**

| Prefix | Count | Content |
|---|---|---|
| `leaf_*.jpg` | 52 | Front matter (separately scanned sequence) |
| `page_*.jpg` | 491 | Body pages |
| **Total** | **543** | All images returned by `*.jpg` glob |

Runners that glob a single prefix (`leaf_*.jpg` or `page_*.jpg`) silently process only one set. Use `*.jpg` glob for full coverage. This caused a silent benchmark undercount during development (2026-05-31).

Estimated total across all 13 volumes: ~6,383 body pages. Volumes 2–13 were not fully fetched as of 2026-05-25 (probe pages only).

---

## Cloud engines (retired)

The following engines were evaluated during the initial phase. None are active in the current corpus pipeline. Their raw artefacts and sidecars remain on local disk for cross-check use if needed.

### Google Cloud Vision `document_text_detection`

**Quota when active:** 1,000 pages/month free tier, 950 soft cap.

**Parsed sidecar fields (historical):**

| Where | Field | Notes |
|---|---|---|
| block | `bbox`, `bbox_polygon`, `block_type` | `TEXT` / `TABLE` / `PICTURE` / `RULER` / `BARCODE` |
| line | `bbox` only | Lines reconstructed from word y-coordinates |
| word | `bbox`, `bbox_polygon`, `confidence`, `low_confidence`, `languages`, `break_after` | `languages` caught embedded Hebrew/Greek/Latin/German. `break_after` flagged hyphenated headwords across line breaks |

**Raw artefact:** `page_NNNN.gcv.raw.json`.

**Available in raw, not extracted:** per-symbol confidence, per-symbol `detectedBreak`.

---

### AWS Textract `detect_document_text`

**Quota when active:** 1,000 pages/month free tier (first 3 months), then $1.50/1k.

**Parsed sidecar fields (historical):**

| Where | Field | Notes |
|---|---|---|
| top-level | `page_rotation` | From PAGE block `Geometry.RotationAngle` |
| line | `bbox`, `bbox_polygon` | Normalised 0–1 converted to pixels |
| word | `bbox`, `bbox_polygon`, `confidence`, `text_type`, `low_confidence` | `text_type` is `PRINTED` or `HANDWRITING` |

**Raw artefact:** `page_NNNN.textract.raw.json`.

---

### Azure AI Vision Image Analysis v4.0 (`features=read`)

**Quota when active:** 5,000 pages/month free tier, 4,750 soft cap.

**Parsed sidecar fields (historical):**

| Where | Field | Notes |
|---|---|---|
| line | `bbox`, `bbox_polygon` | 4-point polygon preserved |
| word | `bbox`, `bbox_polygon`, `confidence`, `low_confidence` | 4-point polygon per word |

**Raw artefact:** `page_NNNN.azure.raw.json`.

---

### Azure Document Intelligence `prebuilt-read`

**Quota when active:** 500 pages/month free tier, 480 soft cap.

**Parsed sidecar fields (historical):**

| Where | Field | Notes |
|---|---|---|
| top-level | `page_rotation`, `model_id`, `content`, `paragraphs[]`, `styles[]`, `page_spans` | `paragraphs[].role` classified `title` / `sectionHeading` / `pageHeader` / `pageFooter` / `pageNumber` / `footnote` — the only engine with automatic structural classification |
| line | `bbox`, `bbox_polygon` | Inch-to-pixel conversion when needed |
| word | `bbox`, `bbox_polygon`, `confidence`, `low_confidence` | 4-point polygon |

**Raw artefact:** `page_NNNN.docint.raw.json`.
