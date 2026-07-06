# CCEL-as-gold aligner — durable design record

> Recorded 2026-07-04 from the maintainer's project notes (verdict 2026-06-01, superseded as a
> workstream by the gold-free corrector — `DESIGN_gold_free_corrector_locked.md`). These facts were
> not in the committed docs at recording time; they constrain any future revival of CCEL-seeded
> gold. Aligner code: `build/tools/ocr_pipeline/align_ccel_to_wct.py` (committed `ad685911`,
> non-body filter fix `863ca725`).

- **Review unit = the DISAGREEMENT, not the page.** Align CCEL tokens to reconciled OCR; agreement → gold on CCEL's independent authority (no review); disagreement → the existing reviewer queue for adjudication against the scan crop. Effort scales with disagreement count. Ride the existing arch7 machinery (`reconcile_s3.py` → `reviewer_queue.json`; `queue_assembly.disagreement_score`; `ccel_gold.py` mark/withdraw/supersede events ARE the confirm/reject actions) — do NOT build a parallel per-page confirm step.
- **Schema forces a PROPOSAL artifact, not a gold record.** `gold-record-v1` has no machine-proposed state (`verified` requires non-empty `ground_truth_text`; `unverifiable` requires null). `extract_ccel_page_gold.py` emits `status:"PROPOSAL_NOT_GOLD"`; the maintainer spot-confirm mints real records (`output_status:"restored_from_reference"`). The machine never asserts gold.
- **Provenance flag:** `encyc01.xml`'s ThML header = "Grand Rapids, MI: Baker Book House, 1951" — CCEL transcribed the 1951 Baker reprint, not the 1908–1914 Funk & Wagnalls scans the pipeline uses. Baker reprints were photo-offset of the original plates; word-for-word + same-pagination spot-checks (page 1 vs `leaf_0037.jpg`, page 100 vs `page_0100.jpg`) support a text/pagination match — but state the edition mismatch wherever CCEL-derived gold is cited.
- **Agreement = same token after NFKC+casefold, NOT visual proximity** — a visually-close-but-different OCR reading IS the disagreement the maintainer must see. (Confusion-weighted Needleman-Wunsch reusing `wct_builder.confusion_distance` + `s3_reconciler._best_candidate`.)
- **Calibration caution:** page_0010 showed raw 50% disagreement — inflated by un-tuned two-column reading-order scramble (`LINE_BAND_PX`), not "50% of OCR is wrong". Tune reading order before interpreting disagreement rates.
- **Why the workstream was superseded:** the M2/M3 10-page run showed the agreements-only gold is circular (reads ~100% oracle accuracy by construction); the non-circular signal is human-adjudicated disagreements vs the image. Cached source: `raw/ccel/schaff/encyc01.xml` (gitignored).
