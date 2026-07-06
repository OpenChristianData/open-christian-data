# NPNF2 Session 2A — Audit Findings

Date: 2026-05-06  
Reviewer: Claude Sonnet 4.6  
Scope: `prompts/t7-3-npnf2.md`, Session 2A (NPNF2-04 Athanasius + NPNF2-05 Gregory of Nyssa)  
Codex report reviewed: `review/npnf2-session-2a-claude-review.md`

---

## Coverage

| Deliverable | Status | Evidence / Notes |
|---|---|---|
| `build/lib/ccel_thml.py` — shared ThML helpers | ✓ Done | Committed in `6834035`; 81 lines; preprocessing, entity handling, text extraction, scripture refs, word counts. [Verified] |
| `build/parsers/ccel_npnf2.py` — NPNF2 parser | ✓ Done | Committed in `6834035` as 842 lines; full VOLUME_CONFIG for Sessions 2A–2C. Parser strategy decision in docstring. [Verified] |
| `tests/test_ccel_npnf2.py` | ✓ Done | Committed. Covers node counts, word counts, provenance for all 2A–2C outputs. [Verified] |
| NPNF2-04: 20 outputs (19 Athanasius + Eusebius) | ✓ Done | All 20 files present in `data/structured-text/`. [Verified] |
| NPNF2-05: 15 Gregory of Nyssa outputs | ✓ Done | All 15 files present. [Verified] |
| Source configs (35 total) | ✓ Done | Spot-checked 2 samples — both exist. [Verified] |
| Provenance fields on every record | ✓ Done | Both samples have `source_type`, `source_url`, `source_file`, `source_hash`, `translator`. [Verified] |
| Author registry updated | ✓ Done | Committed with Athanasius, Gregory of Nyssa, Eusebius works lists updated. [Verified] |
| `py_compile` passes | ~ Inspected | Report says passed. Can't re-run. No syntax issues visible in code read. |
| `pytest`: 81 pass, 1 pre-existing failure | ~ Inspected | Report says 81 passed. Can't re-run. |
| `validate.py --all`: 0 errors | ~ Inspected | Report says 0 errors, 1,324 warnings (pre-existing jsonschema issue). Can't re-run. |
| Parser strategy documented | ✓ Done | Docstring explains new-file decision with rationale. [Verified] |
| Pilot parses before full batch | ✓ Done | Incarnation (58 nodes), Life of Antony (46), Great Catechism (42). [Inspected] |
| 10-second crawl delay + user-agent | ✓ Done | `CRAWL_DELAY = 10`, `UA = "OpenChristianData/1.0..."` present. [Verified] |
| SHA-256 on every downloaded file | ✓ Done | `source_hash: "sha256:bd625..."` in provenance. [Verified] |
| `raw/INVENTORY.md` updated | ~ Inspected | Git-ignored; can't verify. Report says updated. |
| `LAST_SESSION.md` updated | ~ Inspected | Git-ignored. Report says updated. |
| Committed | ✗ Report wrong | **All Session 2A work is committed in `6834035` (10:39 AM today).** Report claims "no commit, no staging." |

---

## Correctness Issues

**Report falsely claims "no commit, no staging."** [Verified]  
All Session 2A deliverables — parser, shared helpers, tests, 35 data files, source configs, registry — are committed in `6834035`. The report's commit status field is wrong and would cause a reviewer to treat already-committed work as pending.

**Report is silent on a separate body of uncommitted work.** [Verified]  
The current working tree has 83 lines of new council author configs added to `ccel_npnf2.py` (FIRST_NICAEA, FIRST_CONSTANTINOPLE, COUNCIL_EPHESUS, COUNCIL_CHALCEDON, SECOND_CONSTANTINOPLE, THIRD_CONSTANTINOPLE, SECOND_NICAEA), matching test updates replacing `ecumenical-councils-canons-and-decrees` with 7 individual outputs, registry changes deleting the collective `ecumenical-councils` author, and 9 untracked data/source files (7 councils + 2 Gregory of Nazianzus splits). None of this appears in the report. It belongs to Session 2C scope (npnf214), not 2A.

**`source_sha256` vs `source_hash`** [Inspected]  
The prompt's DoD checklist lists `source_sha256` as a required provenance field. The actual data uses `source_hash: "sha256:bd625..."` (schema-valid). The hash is intact — naming convention difference only. Report claims user approved this mid-session; unverifiable without transcript.

**Editorial filtering is broad.** [Inspected — flagged in report]  
`_EDITORIAL_TITLE_PATTERNS` excludes any div2 titled "Introduction", "Preface", "Note", "Prolegomena", "Appendix", "Excursus", and 15 other patterns (case-insensitive, word-boundary). For patristic texts some of these titles may be authorial rather than editorial. No programmatic spot-check against raw XML was performed. See Action Required in `npnf2-session-2a-claude-review.md`.

---

## Out-of-Scope Changes

The committed parser (`6834035`) includes a full VOLUME_CONFIG spanning Sessions 2A through 2C — npnf204 through npnf214. Fine architecture but broader than the report acknowledges.

The uncommitted working-tree changes are out of scope for Session 2A:
- 7 individual council author configs in `ccel_npnf2.py`
- Test fixtures updated for 7 individual council outputs
- Registry refactored to remove collective `ecumenical-councils` author
- 9 untracked output files (7 councils + 2 Gregory of Nazianzus splits)

Early Session 2C work, not completed, should not be staged with Session 2A files.

---

## Verdict

Codex delivered the Session 2A core work correctly — 35 works parsed, validated, and committed with clean provenance and OCD conventions followed — but the handoff report is materially inaccurate: it claims "no commit" when all the work is committed, and is silent on a separate set of uncommitted out-of-scope changes sitting in the working tree.
