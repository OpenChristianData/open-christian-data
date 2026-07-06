# Phase A7 — Final verdict and remediation list

**Date:** 2026-05-20
**Inputs:** `audits/A1-final.md` through `audits/A6-final.md`
**Author:** Claude (synthesis — no Codex pass for A7)

---

## Decision brief

- Phase 1 is **substantially complete and correct**: 14/14 slots shipped with verified TDD ordering, 12/12 schemas valid, 7/7 Codex dispatches verified.
- Six defects are HIGH severity; none block Phase 2 from operating.
- Go/no-go: **Phase 2 begins now.** Two HIGH defects (catalog pd_anchor, Psychotherapy body) should land as early Phase 2 fixes before content analysis runs on vol_09 or the catalog is used for anchor decisions.
- Fourteen additional defects (MEDIUM through LOW) run in parallel with Phase 2, prioritised below.

---

## Per-phase verdict

### A1 — TDD conformance gate replay

**Verdict: VERIFIED (14/14 slots) + VACUOUS (audit tooling, 4 structural weaknesses)**

Both reviewers independently confirmed test-commit SHAs preceded production-commit SHAs for all 14 slots; `f3ba9282` regex relaxation verified legitimate. The gate passes on actual git history. However, `phase1_completion_audit.py` does not compare test-commit timestamps against production-commit timestamps, passes on an empty manifest, and the Slot 13 self-referential test does not exercise the gate against real git history. The TDD ordering is sound; the gate is not a formal proof.

---

### A2 — Vacuous-pass inventory

**Verdict: DEFECT (5 SUSPECT producers, 2 crashers fixed)**

Two crashers (`text_suspicion`, `historical_lexicon`) were fixed with a guard in `text_extractor.py`; the fix is verified by a 45-test suite. Five producers (`attested_by_reference_resolution`, `structural_integrity`, `within_edition_divergence`, `modernisation_coverage_consistency`, `llm_triage`) exit before executing domain logic on any reconciled_record — zero-warning output is indistinguishable from a genuine pass. One producer (`structural_integrity`) reads `data[]`, which reconciled_record does not use. Reviewer UI is VACUOUS and workbench is NEVER-POPULATED, both expected until Phase B.

---

### A3 — Content sampling

**Verdict: VERIFIED (90% parser_clean) + 1 DEFECT (Psychotherapy body absent)**

54/60 entries are parser_clean. One genuine parser failure: `Psychotherapy` (vol_09, position 60%) is missing its body entirely from `source/vol_09.json` despite a full §1–§7 article in the ThML source. Five entries are `ocr_structural` (DjVu artifacts ingested as articles — parser faithfully reproduced them). Two false structural claims in the planning material were confirmed by both reviewers.

---

### A4 — Schema re-verification

**Verdict: VERIFIED (12/12 schema valid) + DEFECT (catalog pd_anchor misleading)**

All 12 records pass schema validation. The catalog declares `ccel/schaff/encyclopedia/1908-1914/thml` as the global `pd_anchor` but 9/12 per-record `meta.pd_anchor` values are `ia-ocr`, correctly reflecting that CCEL files for those volumes are stubs. Records are correct; catalog declaration is misleading because no per-volume override mechanism exists. The alias mapping (`ccel-thml` → canonical ID) is out-of-band and undocumented.

---

### A5 — Plan-to-implementation coverage diff

**Verdict: VERIFIED (14/14 slots SHIPPED, 3 LOW carry-forwards)**

All 14 slots shipped planned files with non-trivial implementations. Codex's 7 MISSING verdicts were false negatives: 4 from too-strict a "substantive" threshold applied to intentionally minimal YAML data files, 1 from a renamed/refactored test function (equivalent coverage), 1 from a gitignored runtime directory, and 1 from a gitignored session artifact. Claude and Codex agree on all functional deliverables after divergence resolution. Three LOW carry-forwards: one test rename, one plan-path deviation, one unverified library dependency.

---

### A6 — Codex trust audit

**Verdict: VERIFIED (7/7 dispatches)**

All seven Codex dispatches (two read-only audits, three implementation slots, two test-write slots) produced diffs that match their claimed deliverables. No OVERCLAIM or PARTIAL verdicts. Minor deviations (one outside-allowlist `requirements.txt` addition, one `.gitignore` pre-satisfaction, hook-required writer-manifest artefacts) were disclosed in commit messages and either necessary or anticipated.

---

## Consolidated carry-forward table

All defects from A1–A6, deduplicated, sorted by severity.

| ID | Phase | Severity | Description | Proposed sizing |
|---|---|---|---|---|
| A1-D01 | A1 | HIGH | `_gate_tdd_conformance` does not compare test-commit timestamps against production-commit timestamps. A developer could commit all production code first, add `test:`-prefixed files second, and the gate would PASS. Fix: add per-slot test-path → production-path map; compare first-commit timestamps. | medium (half-day) |
| A1-D02 | A1 | HIGH | Empty manifest passes vacuously — `_gate_tdd_conformance` returns `"pass"` for zero test paths. Fix: add preflight assertion `if not test_paths: return "fail"`. | small (<2h) |
| A2-D01 | A2 | HIGH | 5 SUSPECT producers (`attested_by_reference_resolution`, `structural_integrity`, `within_edition_divergence`, `modernisation_coverage_consistency`, `llm_triage`) have no schema-type guard. Zero-warning result is indistinguishable from a genuine pass. Fix: add a schema-type guard to each producer that returns an explicit SKIP status for non-applicable record types. | medium (half-day) |
| A2-D02 | A2 | HIGH | `structural_integrity` reads `record.get("data")` — reconciled_record stores content in `blocks[]`, not `data[]`. The producer exits before executing any check on every reconciled_record. Fix: add `blocks[]` support or an explicit SKIP guard with documented reason. | medium (half-day) |
| A3-F01 | A3 | HIGH | `Psychotherapy` entry in `source/vol_09.json` has a heading but no body. The ThML has a full §1–§7 article. Genuine parser failure — content was not ingested. Fix: debug `build/parsers/ccel_schaff_herzog.py` boundary logic for vol_09 position 354; reparse and re-reconcile. | medium (half-day) |
| A4-D01 | A4 | HIGH | Catalog declares `ccel/schaff/encyclopedia/1908-1914/thml` as the global `pd_anchor_decision.chosen_rendering`, but 9/12 per-record `meta.pd_anchor` values are `ia-ocr`. The catalog has no per-volume override mechanism. Fix: add a per-volume `pd_anchor` table to the catalog schema and populate it with the volume-conditional logic; or update `chosen_rendering` to document conditionality. Records do not need to change. | medium (half-day) |
| A1-D03 | A1 | MEDIUM | `plans/section-8-test-manifest.yaml` omits plan-required test files that predate Phase 1 or were created without a `test:` subject (`test_a1_schemas.py`, `test_generated_enums.py`, `test_lang_classifier.py`). Fix: track per-function first-Phase-1-commit rather than per-file first-commit; add a manifest annotation for pre-existing files naming the Phase-1 commit that added the required test function. | large (own slot) |
| A1-D04 | A1 | MEDIUM | `test_phase1_completion_audit_replays_both_gates` (Slot 13 self-referential test) does not call the audit script against real git history — it passes even when the strict regex would fail Slots 0–3. Fix: refactor to use a temporary git repo fixture with committed test files in both `test:` and `test(scope):` format. | small (<2h) |
| A2-D03 | A2 | MEDIUM | Text extraction for reconciled_record blocks is not implemented. `text_suspicion` and `historical_lexicon` are excluded from block text analysis; the minimal guard is correct for Phase 1 but must be resolved for Phase B. Fix: implement `_extract_reconciled_record()` in `text_extractor.py`; update producers that need block-text access. | large (own slot, Phase B) |
| A2-D04 | A2 | MEDIUM | `_write_producer_metrics()` does not create parent directories for slash-containing `resource_id` values. Pre-existing crash history in dead-letter. Currently mitigated by existing dirs — not permanently fixed. Fix: add `parent.mkdir(parents=True, exist_ok=True)` before the write. | small (<2h) |
| A3-F02 | A3 | MEDIUM | 4 non-entries ingested as encyclopedia articles: `JCOES WOT CIRCULATE` (vol 03), `END OF VOL. V` (vol 05), `OANISATIONS` (vol 08), `END OF VOLUME X` (vol 10). Parser's `is_article_heading()` / `is_running_header()` classifiers did not exclude these. Fix: update classifiers to reject end-of-volume markers and numeric table fragments. | small (<2h) |
| A3-F03 | A3 | MEDIUM | Two false structural claims in `plans/2026-05-19-phase1-adversarial-review-and-own-ocr.md`: (1) "page_number is null across all 12 volumes" — false (CCEL vols have page numbers); (2) "DjVu format uses `\x0c` as page boundaries" — false (page markers are standalone digit lines). Fix: correct the planning document before the next A-phase session. | small (<2h) |
| A4-D02 | A4 | MEDIUM | Rendering_id alias mapping (`ccel-thml` → canonical ID; `ia-ocr` → canonical ID) is out-of-band knowledge not documented in the schema, catalog, or any project file. Automated referential integrity checks must carry the alias table externally. Fix: add an `aliases` field to the catalog, or migrate records to use full canonical rendering IDs. | small (<2h) |
| A2-D05 | A2 | LOW | `coverage_strategy_unset` (info severity) fires on all 12 volumes. Not a bug; the strategy field is genuinely unset. Needs bulk resolution before warning counts are meaningful. Fix: set the coverage strategy field in the catalog or records, or suppress the warning once the strategy is documented. | small (<2h) |
| A3-F04 | A3 | LOW | `DINAND` (vol 05, position 20%): headword severely truncated (likely `FERDINAND`); cannot identify the corresponding article without the scan. May be a duplicate or orphan. Fix: verify against vol 05 scan at the relevant page; update or remove the entry. | small (<2h) |
| A3-F05 | A3 | LOW | False positive page assignments at IA volume starts: standalone small digits in bibliography sections are misread as page markers by `is_page_marker()`. Confirmed in vol_06 (LIUDGER, SAINT: page=3) and likely vol_05 (DINAND: page=2). Fix: tighten `is_page_marker()` to require greater context (e.g., minimum surrounding blank lines or minimum digit value). | medium (half-day) |
| A4-D03 | A4 | LOW | Schema does not constrain `rendering_id` to catalog-registered values. An arbitrary string passes schema validation. Fix: add an `$ref` or `enum` constraint, or add a post-schema referential integrity check to the validation pipeline. | small (<2h) |
| A5-F01 | A5 | LOW | `test_reading_score_auto_choice_gate` (Slot 3 plan entry) no longer exists at that name — refactored to three parameterised fixtures with equivalent coverage. Plan documentation is stale. Fix: update `plans/section-8-test-manifest.yaml` and the locked plan to reflect the current fixture names. | small (<2h) |
| A5-F02 | A5 | LOW | `render_review_html.py` shipped at `build/tools/` rather than the plan's `build/lib/`. The location is arguably more appropriate (it is a CLI-facing tool, not a library module). Fix: update the plan to reflect the actual path. | small (<2h) |
| A5-F03 | A5 | LOW | `load_dataset` round-trip criterion (Slot 12) was not executed — `datasets` library availability not confirmed. Fix: confirm `datasets` is installed in the project environment; run the round-trip; mark the criterion as passed. | small (<2h) |

*Excluded from table: A2-D06 (Reviewer UI VACUOUS — expected until Phase B) and A2-D07 (Workbench NEVER-POPULATED — expected until Phase B produce cross-rendering disagreements). These are sequencing constraints, not defects.*

---

## Go/no-go recommendation

**Phase 2 begins now. No HIGH defect blocks Phase 2 from operating.**

**Reasoning:**

All 14 slots are shipped with non-trivial implementations and git-verified TDD ordering. The HIGH defects are:
- **A1-D01, A1-D02**: Weaknesses in audit tooling, not production code. The underlying commit ordering is correct; only the formal proof of ordering is weak.
- **A2-D01, A2-D02**: Warning-producer gaps that Phase 2/Phase B is designed to address. They don't prevent Phase 2 from running — they prevent the checkers from detecting certain classes of defects in Phase 2 output.
- **A3-F01**: Data quality gap in vol_09. Does not prevent Phase 2 from processing the other 11 volumes. Must be fixed before any Phase 2 content analysis treats vol_09 as a complete source.
- **A4-D01**: Catalog pd_anchor declaration is misleading, but per-record `meta.pd_anchor` is correct. Phase 2 should read per-record anchors, not the global catalog declaration. Must be fixed before any Phase 2 tooling interprets the catalog's `chosen_rendering` as authoritative for all volumes.

**Which HIGH defects must land before Phase 2's first slot closes:**
- **A4-D01** (catalog fix) — fix and commit before any Phase 2 tool reads `catalog.json` for anchor decisions.
- **A3-F01** (Psychotherapy body) — fix and commit before Phase 2 content analysis runs on vol_09.

**Which fixes run in parallel with Phase 2:**
- A1-D01 + A1-D02 + A1-D04: Bundle into one audit tooling commit as Phase 2's first sub-slot.
- A1-D03: Assign to a dedicated audit slot (large — own slot).
- A2-D01 + A2-D02 + A2-D04: Phase B first sub-slot (producer guard fixes).
- A2-D03: Phase B own slot (block-text extraction).
- A3-F02 + A3-F03 + A4-D02 + A4-D03: Land with the A4-D01 catalog fix (all small, bundle in one commit).
- A2-D05, A3-F04, A3-F05, A4-D03, A5-F01, A5-F02, A5-F03: Opportunistic — any Phase 2 slot.

---

## Exit status

`audits/A7-final.md` complete. Six HIGH defects, six MEDIUM, eight LOW. Two HIGH defects (A4-D01, A3-F01) must land before Phase 2's first slot closes. All others run in parallel. **Phase 2: go.**
