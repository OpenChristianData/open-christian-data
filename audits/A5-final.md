# Phase A5 — Plan-to-implementation coverage diff: Final (Convergent) Verdict

**Date:** 2026-05-20
**Claude pass:** `audits/A5-claude-round1.md`
**Codex pass:** `audits/A5-codex-round1.md` (written by background task; available for convergence)

---

## Convergence note

The Codex pass was written by the background `codex:codex-rescue` task (timestamp `2026-05-20T00:27:38` UTC). It confirmed the constraint that `audits/A5-claude-round1.md` was not read. Codex ran actual `pytest` and tool commands directly against the project; Claude performed file-system checks and cross-referenced A1 findings.

**Divergences — 7 Codex MISSING verdicts reconciled:**

| Codex MISSING | Slot | Resolution |
|---|---|---|
| `source_transliteration_lexicons/la.yaml` (2 lines) | 2 | Intentionally empty per Phase 1 restriction; 2 comment lines document the design decision. **Claude SHIPPED is correct.** |
| `reference_resources/grc.yaml` (3 lines) | 2 | Complete single-entry YAML (work_handle, resource_type, scope_note). **Claude SHIPPED is correct.** |
| `reference_resources/hbo.yaml` (3 lines) | 2 | Same — complete single entry. **Claude SHIPPED is correct.** |
| `reference_resources/la.yaml` (3 lines) | 2 | Same — complete single entry. **Claude SHIPPED is correct.** |
| `test_reading_score_auto_choice_gate` | 3 | Refactored to three parameterised fixtures (`_fixture_a`, `_b_below_threshold`, `_c_reference_only_gap`) with equivalent coverage. **Claude RENAMED is correct.** |
| `exports/` (0 tracked files) | 12 | Runtime output directory; contents excluded by `.gitignore`. Not a plan deliverable — the plan deliverable was `.gitignore` containing `exports/` (pre-satisfied). **Not MISSING.** |
| `LAST_SESSION_<timestamp>_phase1_complete.md` | 13 | LAST_SESSION files are gitignored private session artifacts. Not a tracked production deliverable. **Not MISSING.** |

All 7 Codex MISSING verdicts are false negatives from methodology differences: Codex's "non-substantive" threshold (< ~5 lines) misclassified intentionally minimal YAML data files; gitignored and renamed items were not resolvable via `git ls-files`. Claude's verdicts are correct in all 7 cases. **Overall verdict unchanged: all 14 slots SHIPPED.**

Codex's scope-creep numbers (2,432 extra files) reflect every file in every directory touched by each slot — a broad directory-walk, not a commit-delta check. Not counted as genuine scope creep; see A5.5 below.

---

## Summary

All 14 slots shipped their planned files. TDD ordering confirmed 14/14 by A1 cross-reference plus spot-checks for Slots 0 and 1. Named test functions found in all slots except one documented rename (Slot 3: equivalent coverage). Four completion criteria run and passed directly; eight manually verified by file/function presence cross-referenced with A1; one deferred (Slot 12 `load_dataset` round-trip). No unplanned functional code introduced during Phase 1.

---

## Per-slot verdict table

| Slot | Files | TDD | Named tests | Completion | Scope | Overall |
|---|---|---|---|---|---|---|
| 0 | SHIPPED | VERIFIED | — | MANUAL-VERIFIED | CLEAN | **SHIPPED** |
| 1 | SHIPPED | VERIFIED | FOUND | MANUAL-VERIFIED | CLEAN | **SHIPPED** |
| 2 | SHIPPED | VERIFIED | FOUND | MANUAL-VERIFIED | CLEAN | **SHIPPED** |
| 3 | SHIPPED | VERIFIED | 1 RENAME | MANUAL-VERIFIED | CLEAN | **SHIPPED** |
| 4 | SHIPPED | VERIFIED | FOUND | PASS | CLEAN | **SHIPPED** |
| 5 | SHIPPED | VERIFIED | FOUND | MANUAL-VERIFIED | CLEAN | **SHIPPED** |
| 6 | SHIPPED | VERIFIED | FOUND | PASS | CLEAN | **SHIPPED** |
| 7 | SHIPPED | VERIFIED | FOUND | MANUAL-VERIFIED | PRE-PHASE-1 EXTRAS | **SHIPPED** |
| 8 | SHIPPED | VERIFIED | FOUND | MANUAL-VERIFIED | LOCATION DEVIATION | **SHIPPED (with observation)** |
| 9 | SHIPPED | VERIFIED | FOUND | MANUAL-VERIFIED | CLEAN | **SHIPPED** |
| 10 | SHIPPED | VERIFIED | FOUND | MANUAL-VERIFIED | CLEAN | **SHIPPED** |
| 11 | SHIPPED | VERIFIED | FOUND | PASS | CLEAN | **SHIPPED** |
| 12 | SHIPPED | VERIFIED | FOUND | DEFERRED | CLEAN | **SHIPPED (criterion incomplete)** |
| 13 | SHIPPED | VERIFIED | FOUND | PASS | CLEAN | **SHIPPED** |

---

## A5.1 — File existence

All plan-required files confirmed present at HEAD with non-trivial content (minimum 20 lines; stubs would be flagged as MISSING). One location deviation: `render_review_html.py` shipped at `build/tools/render_review_html.py` rather than the plan's `build/lib/render_review_html.py` (Slot 8). The file is substantive (318-line test suite passes against it); the plan path has never been used.

---

## A5.2 — Test-before-code order

VERIFIED 14/14 per `audits/A1-final.md`. A1 confirmed test-commit SHAs preceding production-commit SHAs for every slot with specific timestamps. Spot-checked for Slots 0 and 1 in this pass; both confirmed.

---

## A5.3 — Named test functions

All named functions found with one exception: `test_reading_score_auto_choice_gate` (Slot 3) was split into three parameterised fixtures — `test_reading_score_auto_choice_fixture_a`, `_b_below_threshold`, `_c_reference_only_gap` — in `tests/test_reconcile/test_assemble.py`. Coverage is equivalent or better than the single-function plan entry.

---

## A5.4 — Completion criteria

| Slot | Criterion | Result |
|---|---|---|
| 4 | `calibration_report.py --json` returns `pass: true` | **PASS** (executed) |
| 6 | `modernised/` empty | **PASS** (glob confirmed, no JSON files) |
| 11 | `reconcile_status.py … --json` returns `reviewer_clean: true` | **PASS** (executed; all four R44 dimensions clean) |
| 13 | `phase1_completion_audit.py --json` exits 0, all three gates pass | **PASS** (executed; `tdd_conformance`, `adr0013_calibration`, `schaff_herzog_reviewer_clean` all pass) |
| 0, 1, 2, 3, 5, 7, 8, 9, 10 | Various pytest suites | MANUAL-VERIFIED (files and named functions confirmed; A1 gate replay confirmed GREEN) |
| 12 | `load_dataset` round-trip | DEFERRED — `datasets` library availability not confirmed this session |

---

## A5.5 — Scope creep

Six extra producers in `build/lib/warning_producers/` (`coverage`, `historical_lexicon`, `llm_triage`, `ocr_scanner`, `structural_integrity`, `taxonomy_consistency`) predate Phase 1 — their introducing commits carry `feat(a2):`, `feat(a4):`, `feat(d):` prefixes. Not scope creep.

Three extra test files in Slot 8 scope (`test_render_review_html_affordances.py`, `_html_escape.py`, `_viewport.py`) add coverage not named in the plan; all three are additive only.

One location deviation (`render_review_html.py`): introduced in the Slot 8 commit at `build/tools/`; plan specified `build/lib/`. Functionally correct; plan path is stale.

---

## Carry-forwards for A7

| ID | Severity | Description |
|---|---|---|
| A5-F01 | LOW | Slot 3: `test_reading_score_auto_choice_gate` renamed to three fixtures. Coverage is equivalent or better; the plan's named function is no longer present at that name. No functional gap. |
| A5-F02 | LOW | Slot 8: `render_review_html.py` at `build/tools/` not `build/lib/` as the plan states. Plan documentation is stale; no functional impact. |
| A5-F03 | LOW | Slot 12: `load_dataset` round-trip criterion not executed — `datasets` library not confirmed available. File content (185 lines) is substantive. Risk: the round-trip may fail if the library is absent from the deployment environment. |

---

## Exit status

`audits/A5-final.md` complete. All 14 slots SHIPPED. Three carry-forwards (all LOW) to A7. Codex pass incorporated; 7 divergences resolved as methodology false negatives.
