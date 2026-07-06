# Task 3 Acceptance Review: ANF, NPNF2, Hooker Batch

Date: 2026-05-06
Working directory: `C:\ocd\`

## Purpose

This report records the review actions, decisions, checks, and one narrow fix made during the acceptance review of the uncommitted ANF, NPNF2, Hooker parser/data/source/test batch.

The user requested:

- Review uncommitted ANF, NPNF2, and Hooker parser/data/source/test changes.
- Fix only clear defects needed for validation or test correctness.
- Do not commit.
- Use `py -3`.
- Do not edit schemas or generated enum files.
- Prefer parser/source/test fixes over hand-editing generated data.

No commit, staging, checkout, reset, clean, push, or schema/generated-enum edit was performed.

## Files I Intentionally Changed

I made one narrow fix outside the named ANF/NPNF2/Hooker parser trio because the review checklist explicitly said to check every new `data/structured-text/*.json` output and every new source config.

Changed:

- `build/parsers/ccel_puritan_works.py`
- `data/structured-text/flavel-method-of-grace.json`
- `sources/structured-text/flavel-method-of-grace/config.json`

The parser change adds `author_id` to both emitted metadata and source config:

- `build/parsers/ccel_puritan_works.py:1248`
- `build/parsers/ccel_puritan_works.py:1300`

The regenerated output/config now contain:

- `data/structured-text/flavel-method-of-grace.json:6` -> `"author_id": "john-flavel"`
- `sources/structured-text/flavel-method-of-grace/config.json:5` -> `"author_id": "john-flavel"`

## Why I Fixed Flavel

The initial author registry/reference check over all new structured-text outputs found:

```text
MISSING AUTHOR IDS:
flavel-method-of-grace: None
```

That was a clear output correctness defect:

- The parser already had `AUTHOR_CONFIG["flavel"]["author_id"] == "john-flavel"`.
- `build_meta()` and `write_source_config()` simply failed to emit it.
- The generated data passed schema validation because `author_id` is nullable, but it failed the stronger acceptance check: new output should reference registry-backed author IDs where available.

I did not hand-edit the generated data. I patched the parser and regenerated only the affected work:

```powershell
py -3 build/parsers/ccel_puritan_works.py --work flavel-method-of-grace --parse
```

Observed parser result:

```text
flavel-method-of-grace: 35 top-level sections, 35 chapters, ~216k words
Quality: 35 total nodes, 0 orphans
Files written: 1. Errors: 0.
```

## Commands Run And Results

### Compile Checks

Requested compile command, with the fixed Puritan parser added after the change:

```powershell
py -3 -m py_compile build/lib/ccel_thml.py build/parsers/ccel_anf.py build/parsers/ccel_npnf2.py build/parsers/gutenberg_systematics.py tests/test_ccel_anf.py tests/test_ccel_npnf2.py tests/test_hooker_gutenberg_systematics.py build/parsers/ccel_puritan_works.py
```

Result: PASS.

### Focused Tests

Requested command:

```powershell
py -3 -m pytest tests/test_ccel_anf.py tests/test_ccel_npnf2.py tests/test_hooker_gutenberg_systematics.py -q
```

Result: blocked before test collection.

Observed error:

```text
ImportError: cannot import name '__version__' from '_pytest' (unknown location)
```

Environment facts:

```text
py -3 --version -> Python 3.14.3
py -0p -> -V:3.14 * C:\Python314\python.exe
py -3 -m pip show pytest -> pytest 9.0.3 at [Python user site-packages]
```

Additional observation:

- `py -3 -I -m pytest ...` reports `No module named pytest`.
- Attempting to inspect `...\site-packages\_pytest` hit `Access denied`.

Decision: I did not repair or reinstall pytest because that would mutate the user Python environment and was outside the requested repo review.

### Structured Text Validation

Command shape:

```powershell
$files = git status --porcelain -- data/structured-text |
  ForEach-Object { $_.Substring(3) } |
  Where-Object { $_ -like 'data/structured-text/*.json' }
py -3 build/validate.py @files
```

Result: PASS.

Observed summary:

```text
Validated 73 file(s): 0 total errors, 0 total warnings
```

### Data To Source Config Pairing

Custom check over changed/new `data/structured-text` and `sources/structured-text` paths.

Result: PASS.

Observed summary:

```text
data_ids=73 source_ids=73
matching configs/provenance PASS
```

This checked:

- Every new structured-text data file had a matching `sources/structured-text/<id>/config.json`.
- Every new source config dir had a matching data file.
- Each config had `source_url`.
- Each config had `source_hash` matching `sha256:[0-9a-f]{64}`.
- `output_file`, where present, matched `data/structured-text/<id>.json`.

### Author Registry References

Custom check over all changed/new structured-text outputs.

Initial result: FAIL for `flavel-method-of-grace: None`.

After parser fix and regeneration:

```text
checked_author_ids=73
author registry references PASS
```

Named batch author IDs were also spot-checked against `data/authors/registry.json`:

```text
missing= []
```

## Parser Boundary Review

I inspected the named parser surfaces for the requested risk classes:

- `build/lib/ccel_thml.py`
- `build/parsers/ccel_anf.py`
- `build/parsers/ccel_npnf2.py`
- `build/parsers/gutenberg_systematics.py`
- `tests/test_ccel_anf.py`
- `tests/test_ccel_npnf2.py`
- `tests/test_hooker_gutenberg_systematics.py`

Findings:

- No hardcoded schema enum frozensets in the named parser configs. The parser files use `get_enum(...)` for schema enum checks.
- ANF, NPNF2, and Hooker outputs/configs have source URLs and SHA-256 source hashes.
- NPNF2 and Hooker IDs/provenance looked stable in sampled outputs.
- Broad exception paths in the named parsers are error-reporting paths that log/increment errors and exit non-zero rather than silently accepting failed outputs.
- Hooker bundling decision is documented in parser provenance notes: Polity-only output, sermons and separate tractate deferred.

Residual caution:

- `gutenberg_systematics.py` contains pre-existing and batch-adjacent Luther changes, and `ccel_puritan_works.py` contains Puritan/Flavel changes. These were visible in git status but were not the primary named batch. I only changed the Flavel author ID emission because the all-new-output review check exposed a concrete defect.

## Final Acceptance Judgement

Repo/data validation status: PASS.

Focused pytest status: not accepted in this environment, because pytest is broken before collection.

Commit readiness:

- I would not call the batch fully acceptance-complete from Codex alone because the requested focused pytest command did not run.
- I would call the batch validation-ready and internally coherent based on compile, data validation, config/provenance pairing, author registry checks, and parser boundary review.
- Run the focused pytest command from the host terminal before committing.

## Defects Remaining

No repo defect remains from the checks I completed.

External blocker:

- `py -3 -m pytest ...` fails before collection due the active Python 3.14 user-site pytest/_pytest installation.

## Rule Suggestion

Suggested project rule for `AGENTS.md`:

```markdown
## Acceptance Review Reports

When an acceptance review finds or fixes a defect outside the named parser batch
because a global review check includes it, write a short report under
`build/tools/` that records:

- the exact check that expanded scope,
- the files changed,
- why the fix was considered validation or test correctness rather than cleanup,
- the exact regeneration command, if any,
- the final pass/fail status for compile, focused tests, data validation,
  source-config pairing, provenance, and author registry references.

If `py -3 -m pytest` fails before test collection because of the local Python
environment, do not repair the user Python install during the review. Report
the exact import/environment error and mark commit readiness as conditional on
host-side pytest.
```

Rationale:

- This prevents hidden scope creep while still allowing obvious global-check defects to be fixed.
- It makes future Claude/Codex review easier because the reason for touching an apparently unrelated parser is durable.
- It avoids conflating repo correctness with local Python environment repair.
