# OCD Standards Sweep Results — 2026-04-12

## Summary

Reviewed all 65 Python files in `build/` against CODING_DEFAULTS.md `[reviewer-checked]` rules using 4 parallel subagents.

## Raw Numbers

| Batch | Files | Clean | Violations |
|---|---|---|---|
| Parsers (batch 1) | 8 | 4 | 4 |
| Parsers (batch 2) | 15 | 7 | 8 |
| Scripts | 17 | 6 | 11 |
| Libs/tools/patches | 25 | 9 | 16 |
| **Total** | **65** | **26 (40%)** | **39 (60%)** |

## Violation Breakdown

| Rule | Count | Description |
|---|---|---|
| REL-03 | 29 | No `.log` file (15 are patch scripts, now exempt) |
| PY-06 | 14 | Module-level side effects |
| PY-07 | 2 | Dead imports |
| DATE-01 | 1 | Naive datetime |
| Bug | 1 | Undefined variable (`church_fathers.py` line 388) |

## Meta-Patterns

### 1. REL-03 is a template problem, not a knowledge gap

Every file written after standards were formalized passes. Every older file and patch script fails. The curation prompt that generates patch scripts has no logging boilerplate.

**Resolution:** Added REL-03 exemption for one-shot patch scripts. Remaining 10 older parsers need logging added (see `prompts/STANDARDS_FIXES.md`).

### 2. PY-06's `logging.basicConfig` variant is copy-paste contagion

8+ files have `logging.basicConfig(...)` at module level. Pattern was copied from earliest parsers. Correct pattern (`setup_logging()` from `main()`) exists in newer files but never propagated.

### 3. Patch scripts are a distinct category

15 patch scripts share: idempotent, small, one-shot, manually run, no API. They ALL violated REL-03 because the rule was designed for scheduled automation. Exemption added.

### 4. Auto-checker could catch the #1 PY-06 variant

`logging.basicConfig()` outside a function def is AST-detectable. Adding to `standards_check.py` would catch most PY-06 violations automatically.

### 5. Quality = f(when written)

| Era | Files | Violation rate |
|---|---|---|
| Recent (last 2 weeks) | ~8 | 0% |
| Older (pre-standards) | ~57 | ~68% |

Standards ARE working for new code. Backlog is legacy.

### 6. Libraries are exemplary

All 4 `build/lib/*.py` modules pass cleanly. Most import-sensitive = most carefully written.

## Actions Taken

- `CODING_DEFAULTS.md` REL-03 exemption for one-shot patch scripts
- `.claude/agents/python-standards-reviewer.md` rewritten (references `[reviewer-checked]` tags, not stale rule numbers)
- `prompts/STANDARDS_FIXES.md` written with all fixes grouped and prioritised
- `church_fathers.py` line 388 bug confirmed (undefined `skipped_files`)

## Coverage Caveat

Several large files were truncated by agents and only partially reviewed: `ccel_hodge_systematic.py`, `bcp1928.py`, `audit_data_accuracy.py`. These should be fully reviewed when the fixes are applied.
