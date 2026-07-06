# Data Structure Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `data/` to `work-kind/author/work` keying with canonical author+work registries as the single source of truth, without changing any record content or published-dataset output.

**Architecture:** Four reusable tools — (1) a file-classifier that separates record files from auxiliary files, (2) author+work registries maintained under `sources/registries/` and generated into `data/`, (3) a post-build **metadata-stamp** pass that projects the registries onto each output file's `meta` envelope (the SSOT denormalizer, correction-ledger-aware), (4) a path-migration tool that moves record files + their review sidecars and updates parser output paths. The four tools are proven end-to-end on one pilot category (catechisms), then rolled out per category. Parsers are **not** rewritten; the stamp pass owns canonical `meta` fields, so per-parser surgery is avoided.

**Tech Stack:** Python 3, `pytest` (`-p no:cacheprovider`), JSON Schema (`schemas/v1/`), the existing writer-manifest gate (`build/lib/writer_identities.py`), the review-sidecar API (`build/lib/review_state.py`), git for history-preserving moves.

---

## Assumptions and scope

- **Registry location (§9-B):** maintained registries live at `sources/registries/authors.json` and `sources/registries/works.json`; the `data/authors/registry.json` + `data/works/registry.json` copies are generated. Confirmed by the user ("ok") and consistent with the existing `sources/witnesses/registry.json` precedent.
- **church-fathers is excluded** (`data/church-fathers/`, its configs, and its author-registry junk rows like `"1 Corinthians"`). No file under `church-fathers/` moves; its registry rows are left untouched.
- **No record content changes.** Only `meta` canonical fields (author/work) are normalized and file paths move. Per-schema record-id fields (`entry_id`, `document_id`, verse refs) are never touched (§9-D).
- **Canonical names use short form** (`A. A. Hodge`, `C. H. Spurgeon`); long forms go in `aliases`.
- **Every `data/`-mutating tool emits a writer manifest** under `review/writer-manifests/<run_id>.json` naming a writer registered in `build/lib/writer_identities.py`, per the existing gate.

This plan covers **Phases 0–5 concretely** (the four tools + the catechisms pilot). **Phase 6 (per-category rollout)** is a repeatable template plus the category inventory — each category is executed by repeating the pilot steps, because the per-parser output-path edit differs by parser and is specified when that category is tackled. **Phase 7** is docs + cutover. Do not start Phase 6 until the pilot (Phase 5) is green.

## Component / file map

| File | Responsibility | Phase |
|---|---|---|
| `build/tools/redesign/classify_data_files.py` | Scan `data/`, classify every file as `record` / `auxiliary` / `registry`; emit a manifest | 0 |
| `schemas/v1/work_registry.schema.json` | Schema for the works registry | 1 |
| `sources/registries/authors.json`, `sources/registries/works.json` | Maintained SSOT registries | 1 |
| `build/tools/redesign/generate_registries.py` | Generate `data/{authors,works}/registry.json` from `sources/registries/` | 1 |
| `build/lib/redesign/meta_resolver.py` | Pure function: `(author_id, work_id, source_cfg) -> canonical meta fields` | 2 |
| `build/tools/redesign/stamp_metadata.py` | Apply `meta_resolver` to output files; correction-ledger-aware; emit writer manifest | 2 |
| `build/tools/redesign/migrate_paths.py` | Compute old→new record paths; git-move; migrate sidecars; emit writer manifest | 3 |
| `build/tools/redesign/verify_redesign.py` | Per-schema id check, no-drift check, count check, sidecar-orphan check | 4 |
| `build/lib/writer_identities.py` | Register new writer names (modify) | 1–3 |

## §9 traceability

| §9 finding | Addressed by |
|---|---|
| §9-A file classification | Phase 0 (`classify_data_files.py`); only `record` files move |
| §9-B registry governance | Phase 1 (`sources/registries/` maintained, `data/` generated) |
| §9-C parser regen contracts | Phase 2 (stamp pass is correction-ledger-aware; Phase 6 per-parser regen classification) |
| §9-D record-id reality | Phase 4 (`verify_redesign.py` checks each schema's own id field, not a global `entry_id`) |
| §9-E work_id == resource_id | Phase 1 (works registry `work_id` defaults to `resource_id`; mapping table for exceptions) |
| §9-F sidecar migration | Phase 3 (`migrate_paths.py` rewrites sidecar path + embedded `record_path` + checksum) |

---

## Phase 0 — File classifier (§9-A)

### Task 0.1: Classifier with a failing test

**Files:**
- Create: `build/tools/redesign/classify_data_files.py`
- Test: `tests/test_classify_data_files.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classify_data_files.py
from pathlib import Path
import json
from build.tools.redesign.classify_data_files import classify_file

def test_record_file(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"meta": {"id": "x"}, "data": [{"entry_id": "x.1"}]}), encoding="utf-8")
    assert classify_file(p) == "record"

def test_manifest_is_auxiliary(tmp_path):
    p = tmp_path / "_manifest.json"
    p.write_text(json.dumps({"generated_at": "2026-01-01"}), encoding="utf-8")
    assert classify_file(p) == "auxiliary"

def test_registry_is_registry(tmp_path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"authors": []}), encoding="utf-8")
    assert classify_file(p) == "registry"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `py -3 -m pytest -p no:cacheprovider tests/test_classify_data_files.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the classifier**

```python
# build/tools/redesign/classify_data_files.py
"""Classify every file under data/ for the structure redesign migration.

record    -> {meta, data} dataset output; eligible for the path move.
registry  -> a *registry.json file (authors/works); not a record, not moved by path rules.
auxiliary -> manifests, catalogs, lexicon/hymn special shapes; handled by their own rules.
"""
from __future__ import annotations
import json
from pathlib import Path

def classify_file(path: Path) -> str:
    if path.name == "registry.json":
        return "registry"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "auxiliary"
    if isinstance(doc, dict) and "meta" in doc and "data" in doc:
        return "record"
    return "auxiliary"
```

- [ ] **Step 4: Run test, verify it passes**

Run: `py -3 -m pytest -p no:cacheprovider tests/test_classify_data_files.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add build/tools/redesign/classify_data_files.py tests/test_classify_data_files.py
git commit -m "feat(redesign): file classifier (record/auxiliary/registry)"
```

### Task 0.2: Manifest emitter + baseline snapshot

**Files:**
- Modify: `build/tools/redesign/classify_data_files.py` (add `build_manifest`, CLI)
- Test: `tests/test_classify_data_files.py` (add)

- [ ] **Step 1: Add the failing test**

```python
def test_build_manifest_counts(tmp_path):
    from build.tools.redesign.classify_data_files import build_manifest
    (tmp_path / "a.json").write_text('{"meta":{},"data":[]}', encoding="utf-8")
    (tmp_path / "_manifest.json").write_text('{}', encoding="utf-8")
    m = build_manifest(tmp_path)
    assert m["counts"]["record"] == 1
    assert m["counts"]["auxiliary"] == 1
```

- [ ] **Step 2: Run, verify fail.** `py -3 -m pytest -p no:cacheprovider tests/test_classify_data_files.py::test_build_manifest_counts -v`

- [ ] **Step 3: Implement `build_manifest` + a `__main__` CLI** that walks a root, classifies each `*.json`, and writes `plans/redesign-file-classification.json` with `{generated_at, counts, by_path: {rel_path: class}}`. Exclude `data/church-fathers/**`. Use `datetime.now(timezone.utc)`.

```python
from datetime import datetime, timezone

def build_manifest(root: Path, *, exclude_prefixes=("church-fathers",)) -> dict:
    by_path, counts = {}, {"record": 0, "auxiliary": 0, "registry": 0}
    for p in sorted(root.rglob("*.json")):
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] in exclude_prefixes:
            continue
        cls = classify_file(p)
        by_path[rel.as_posix()] = cls
        counts[cls] += 1
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "counts": counts, "by_path": by_path}
```

- [ ] **Step 4: Run test, verify pass.**

- [ ] **Step 5: Generate the real baseline and eyeball it**

Run: `py -3 -m build.tools.redesign.classify_data_files data > plans/redesign-file-classification.json` (wire the CLI to take the root arg and print JSON).
Expected: `record` ≈ 1,370, `auxiliary` ≈ 88, matching the verified scan. Confirm `hymns` and `lexicon` files land in `auxiliary` or `record` as appropriate, and note any surprises in the manifest.

- [ ] **Step 6: Commit** (the tool + test only; `plans/` is gitignored).

```bash
git add build/tools/redesign/classify_data_files.py tests/test_classify_data_files.py
git commit -m "feat(redesign): classification manifest emitter + baseline"
```

---

## Phase 1 — Registries under sources/ (§9-B, §9-E)

### Task 1.1: Works-registry schema

**Files:**
- Create: `schemas/v1/work_registry.schema.json`
- Test: `tests/test_work_registry_schema.py`

- [ ] **Step 1: Failing test** — assert the schema loads, requires `works`, and that each work requires `work_id`, `title`, `slug`, `work_kind`, with `work_id`/`slug` matching `^[a-z0-9]+(-[a-z0-9]+)*$`. Mirror `schemas/v1/author_registry.schema.json` (read it first for house style: `$schema` draft 2020-12, `x-ocd-schema-version`, `additionalProperties: false`).

```python
# tests/test_work_registry_schema.py
import json, jsonschema
from pathlib import Path
SCH = json.loads(Path("schemas/v1/work_registry.schema.json").read_text(encoding="utf-8"))

def test_valid_minimal():
    doc = {"works": [{"work_id": "calvin-commentaries", "title": "Calvin's Commentaries",
                      "slug": "john-calvin", "work_kind": "commentary", "author_ids": ["john-calvin"],
                      "aliases": []}]}
    jsonschema.validate(doc, SCH)

def test_rejects_bad_work_id():
    doc = {"works": [{"work_id": "Calvin Commentaries", "title": "x", "slug": "x",
                      "work_kind": "commentary", "author_ids": [], "aliases": []}]}
    try:
        jsonschema.validate(doc, SCH); assert False
    except jsonschema.ValidationError:
        pass
```

- [ ] **Step 2: Run, verify fail** (schema file missing).
- [ ] **Step 3: Write `schemas/v1/work_registry.schema.json`.** Required per work: `work_id`, `title`, `slug`, `work_kind`, `author_ids` (array — empty for institutional/anonymous), `aliases`. Optional: `original_publication_year`, `original_language`, `tradition`, `era`, `audience`, `contributor_ids`. `work_kind` enum references the same values as the schemas (do not hardcode — list them from `get_enum`, see AGENTS.md).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Regenerate enum constants if any enum was touched:** `py -3 build/tools/generate_schema_enums.py` then `py -3 build/tools/check_schema_enums_fresh.py`. Expected: fresh.
- [ ] **Step 6: Commit.**

```bash
git add schemas/v1/work_registry.schema.json tests/test_work_registry_schema.py
git commit -m "feat(redesign): work registry schema"
```

### Task 1.2: Relocate the authors registry to sources/, seed works registry

**Files:**
- Create: `sources/registries/authors.json` (moved content), `sources/registries/works.json`
- Test: `tests/test_registries_source_of_truth.py`

- [ ] **Step 1: Failing test** — assert `sources/registries/authors.json` validates against `author_registry.schema.json` and `sources/registries/works.json` validates against `work_registry.schema.json`; assert every `work.author_ids[*]` exists in the authors registry; assert every `work_id` is unique.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3:** Copy the current `data/authors/registry.json` to `sources/registries/authors.json` (this becomes the maintained SSOT). **Build `sources/registries/works.json`** by enumerating every `record`-classified source: one work per `resource_id`. Default `work_id = resource_id`, `slug` = canonical author slug for single-author works (or source slug otherwise), `title`/`work_kind`/`author_ids` resolved from the existing config + author registry. Exclude church-fathers. Where short-form author names need fixing (e.g. folder slug `calvin` → author `john-calvin`), set the canonical `display_name`/`author_id` now and record the long form in `aliases`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit.**

```bash
git add sources/registries/ tests/test_registries_source_of_truth.py
git commit -m "feat(redesign): relocate authors registry to sources/, seed works registry"
```

### Task 1.3: Registry generator (sources/ → data/) + writer registration

**Files:**
- Create: `build/tools/redesign/generate_registries.py`
- Modify: `build/lib/writer_identities.py` (register `dataset_redesign_writer`)
- Test: `tests/test_generate_registries.py`

- [ ] **Step 1: Failing test** — `generate_registries(sources_dir, data_dir)` writes `data/authors/registry.json` byte-equal to the validated `sources/registries/authors.json` (plus the generated `data/works/registry.json`), and returns a writer-manifest dict whose registered-writer field is registered in the allowlist.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3:** Implement the generator: load + validate each `sources/registries/*.json`, write the `data/` copies with `newline="\n"`, compute before/after sha256, return a writer manifest naming the registered writer `dataset_redesign_writer`. Add `"dataset_redesign_writer": "tool"` to `_REGISTERED` in `build/lib/writer_identities.py`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5:** Run for real; write the manifest to `review/writer-manifests/redesign-registries-<date>.json`; `git diff --stat data/authors/registry.json` should show only formatting if content matched.
- [ ] **Step 6:** Run the fast suite: `py -3 -m pytest -p no:cacheprovider -m "not slow" -q`. Expected: green.
- [ ] **Step 7: Commit** (force-add the writer manifest per `.claude/rules/git.md`: `git add -f review/writer-manifests/redesign-registries-*.json`).

---

## Phase 2 — Metadata stamp / denormalizer (§3, §9-C)

### Task 2.1: Pure meta resolver

**Files:**
- Create: `build/lib/redesign/meta_resolver.py`
- Test: `tests/test_meta_resolver.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_meta_resolver.py
from build.lib.redesign.meta_resolver import resolve_meta_fields

AUTHORS = {"john-calvin": {"display_name": "John Calvin", "birth_year": 1509, "death_year": 1564}}
WORKS = {"calvin-commentaries": {"title": "Calvin's Commentaries", "author_ids": ["john-calvin"],
                                 "work_kind": "commentary", "original_publication_year": 1551}}

def test_resolves_author_and_title():
    out = resolve_meta_fields(work_id="calvin-commentaries", authors=AUTHORS, works=WORKS)
    assert out["author"] == "John Calvin"
    assert out["title"] == "Calvin's Commentaries"
    assert out["author_birth_year"] == 1509

def test_unknown_work_raises():
    try:
        resolve_meta_fields(work_id="nope", authors=AUTHORS, works=WORKS); assert False
    except KeyError:
        pass
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3:** Implement `resolve_meta_fields(*, work_id, authors, works) -> dict` returning only the canonical fields the registries own (`author`, `author_birth_year`, `author_death_year`, `title`, `original_publication_year`, `original_language`, `tradition`, `era`, `audience`). Raise `KeyError` on unknown ids — never silently default (AGENTS.md "no silent failures").
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit.**

### Task 2.2: Stamp tool — correction-ledger-aware (§9-C)

**Files:**
- Create: `build/tools/redesign/stamp_metadata.py`
- Test: `tests/test_stamp_metadata.py`

- [ ] **Step 1: Read first** `build/lib/parser_regen_safety.py` (the correction-preservation API) so the stamp never overwrites a field carrying an applied correction. Record which fields are correction-owned.
- [ ] **Step 2: Failing test** — given an output file and the registries, the tool rewrites `meta` author/title/etc. to the resolved values, leaves `data[]` byte-identical, and **skips** any field listed in that file's correction ledger.

```python
def test_stamp_rewrites_meta_only(tmp_path):
    from build.tools.redesign.stamp_metadata import stamp_file
    rec = {"meta": {"id": "calvin-commentaries", "work_id": "calvin-commentaries",
                    "author": "Calvin", "title": "old"}, "data": [{"entry_id": "x.1"}]}
    p = tmp_path / "genesis.json"; p.write_text(__import__("json").dumps(rec), encoding="utf-8")
    stamp_file(p, authors=AUTHORS, works=WORKS, corrections=set())
    out = __import__("json").loads(p.read_text(encoding="utf-8"))
    assert out["meta"]["author"] == "John Calvin"
    assert out["meta"]["title"] == "Calvin's Commentaries"
    assert out["data"] == [{"entry_id": "x.1"}]   # records untouched
```

- [ ] **Step 3:** Implement `stamp_file(path, *, authors, works, corrections)`: read the file, require `meta.work_id` (fall back to `meta.id`), resolve canonical fields, overwrite each **unless** `(work_id, field)` is in `corrections`, write back with `newline="\n"`. A batch `stamp_paths(paths, ...)` returns a writer manifest (registered writer `dataset_redesign_writer`) with before/after checksums.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5:** Validate a stamped pilot file: `py -3 build/validate.py <file>`. Expected: valid.
- [ ] **Step 6: Commit.**

---

## Phase 3 — Path migration + sidecars (§9-F)

### Task 3.1: Path mapper

**Files:**
- Create: `build/tools/redesign/migrate_paths.py`
- Test: `tests/test_migrate_paths.py`

- [ ] **Step 1: Failing test** — `compute_new_path(old_path, record_meta, works, authors)` maps `data/commentaries/calvin/genesis.json` → `data/commentaries/john-calvin/genesis.json` using the work's resolved author slug; asserts work-level elision (single-work kind → unit directly under author); asserts a multi-work structured-text file maps under `author/work/`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3:** Implement `compute_new_path`. Input: old path + the file's classification (must be `record`) + registries. Build the new path `data/<kind>/<author-slug>/<...>` per §4. Only `record` files (from the Phase-0 manifest) are mapped; `auxiliary`/`registry` raise or are skipped.
- [ ] **Step 4: Run, verify pass.**

### Task 3.2: Mover with sidecar migration

**Files:**
- Modify: `build/tools/redesign/migrate_paths.py`
- Test: `tests/test_migrate_paths.py` (add)

- [ ] **Step 1: Read first** `build/lib/review_state.py` — `derive_sidecar_path` and the `record_path` field stored inside each sidecar.
- [ ] **Step 2: Failing test** — moving a record with an existing sidecar (a) git-moves the record, (b) moves the sidecar to its new derived path, (c) rewrites the sidecar's internal `record_path`, (d) refreshes any stored checksum, (e) reports zero orphaned sidecars.
- [ ] **Step 3:** Implement `migrate(mapping, *, repo_root)`: for each old→new, `git mv` the record (preserves history per GIT-04), recompute `derive_sidecar_path` for old and new, `git mv` the sidecar if present, rewrite its `record_path`, refresh checksum, accumulate a writer manifest. Add an `--dry-run` that prints the full move set without touching disk.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** (tool + tests).

### Task 3.3: Update parser output paths

- [ ] For the parser owning the category being migrated, read its output-path logic (e.g. `OUTPUT_DIR` / `output_file` in the config) and update it to emit to the new `author/work` path, so a future re-run reproduces the new layout rather than reverting it. This is **per-parser** and is done inside each Phase-6 category pass, not globally. Verify by re-running the parser to a temp dir and diffing the path.

---

## Phase 4 — Verification harness (§9-D)

### Task 4.1: Per-schema id + no-drift + count + orphan checks

**Files:**
- Create: `build/tools/redesign/verify_redesign.py`
- Test: `tests/test_verify_redesign.py`

- [ ] **Step 1:** Build the per-schema record-id-field map (read each `schemas/v1/<kind>.schema.json` to find its record id field — `entry_id`, `document_id`, etc.; some have none). Store as a constant dict with a test asserting it covers every in-scope `schema_type`.
- [ ] **Step 2: Failing tests** for four checks:
  - `check_record_ids_unchanged(before_index, after_index)` — for each schema, the multiset of its record-id field is identical before/after (skips schemas with no id field, asserting record count instead).
  - `check_no_drift(file, authors, works)` — `meta.author`/`meta.title` equal the registry-resolved values.
  - `check_counts(before_manifest, after_manifest)` — record count per category unchanged.
  - `check_no_orphan_sidecars(repo_root)` — every `review/state/**` sidecar's `record_path` points to an existing file.
- [ ] **Step 3:** Implement the four functions.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit.**

---

## Phase 5 — Pilot: catechisms end-to-end

Catechisms is the pilot: 15 flat, mostly single-author files, the simplest surface, and it exercises every design decision (rename, registry resolve, stamp, move, sidecar, verify).

- [ ] **Step 1:** Snapshot baseline — run the Phase-0 classifier and Phase-4 `before_index` over `data/catechisms/`. Save to `plans/`.
- [ ] **Step 2:** Confirm each catechism's `work_id`/`author_id`/slug in `sources/registries/works.json` (Task 1.2). Resolve any short-form name (e.g. Heidelberg → author `zacharias-ursinus`, or institutional slug if no single author). Leave blank over guessing per the OCD curation rule.
- [ ] **Step 3:** Run the **stamp** pass on `data/catechisms/**` (Phase 2). `py -3 build/validate.py` each file. Expected: all valid, `meta.author` canonical.
- [ ] **Step 4:** `migrate_paths --dry-run` over the catechism record set; eyeball the move map; then run for real (Phase 3). Verify sidecars followed.
- [ ] **Step 5:** Update the catechism parser output paths (Task 3.3) and re-run the parser to a temp dir; diff against the moved tree — must match (proves regeneration reproduces the new layout).
- [ ] **Step 6:** Run the Phase-4 harness (`after_index` vs `before_index`): record-ids unchanged, no drift, counts equal, zero orphan sidecars.
- [ ] **Step 7:** Full suite: `py -3 -m pytest -p no:cacheprovider -q --basetemp "$env:TEMP/ocd-pytest-$PID"`. Expected: green.
- [ ] **Step 8: Commit** the pilot (record moves as `R100` renames per GIT-04 where content is unchanged; force-add the writer manifests). Group: one commit for the stamp, one for the move, one for the parser-path update.

**STOP. Do not proceed to Phase 6 until the pilot is green and reviewed.** What the pilot teaches (sidecar edge cases, name-resolution gaps, parser-path quirks) updates the Phase-6 template before rollout.

---

## Phase 6 — Per-category rollout (template)

For each category below, repeat the pilot steps (2–8) scoped to that category. The only category-specific work is **name/work resolution** and the **per-parser output-path edit** (Task 3.3). Order easiest→hardest so the harness catches issues on simple shapes first.

| Order | Category | Files | Notes / known risk |
|---|---|---|---|
| 1 | `doctrinal-documents` | 39 | flat; many institutional/anonymous → source/work slug |
| 2 | `prayers`, `hymns`, `devotionals` | ~8 | already nested; mostly slug renames |
| 3 | `sermons` | 43 | mixed flat + nested (spurgeon-mtp chunked); multi-author check |
| 4 | `bible-text` | 132 | no author → edition slug (`bsb`,`kjv`); the 193-no-`entry_id` set lives here (§9-D), verify by verse-ref count |
| 5 | `reference` | 113 | institutional; `schaff/` nested + has `auxiliary` catalogs (Phase 0 must exclude those from the move) |
| 6 | `commentaries` | 494 | nested per author; `OUTPUT_BASE` in `sword_commentary.py` + HelloAO parsers; largest move |
| 7 | `structured-text` | 289 | the `author-work` squash → `author/work/`; the most path churn; multi-work-per-author is the norm here |
| — | `lexicon`, `topical-reference` | 2 | mostly `auxiliary`/single; handle case-by-case |

- [ ] For each category, before its move: classify parser regen behavior (§9-C) as pure / merge / correction-ledger-dependent by reading its parser; if correction-ledger-dependent, pass the ledger into the stamp pass.
- [ ] After each category: run the full verification harness and the full test suite; commit per category.
- [ ] **church-fathers is skipped entirely.**

---

## Phase 7 — Docs and cutover

- [ ] **Step 1:** Update `README.md` "Repository structure" section to the new `work-kind/author/work` tree and the `sources/registries/` SSOT note. American English.
- [ ] **Step 2:** Add a short rule to `AGENTS.md` / `.claude/rules/` documenting: registries are maintained in `sources/registries/` and generated into `data/`; the `data/` copies are not hand-edited (resolves the §9-B governance gap permanently).
- [ ] **Step 3:** Update `docs/DESIGN_data_structure_redesign.md` status from DO-NOT-SHIP to "Implemented" with the rollout date.
- [ ] **Step 4:** Update `docs/DATASET_PROJECT_STATE.md` (the dataset anchor) Part 2 with the new layout and registry model.
- [ ] **Step 5:** Final whole-repo verification harness run + full suite. Commit docs.

---

## Self-review notes

- **Spec coverage:** every §3/§4 rule and all six §9 findings map to a phase (see the §9 traceability table and the component map). The naming convention (§3.3) is applied in Task 1.2.
- **No record mutation:** stamp touches `meta` only (Task 2.2 test asserts `data` unchanged); verification re-checks per-schema record ids (Phase 4).
- **Governance:** registries maintained in `sources/`, generated into `data/`, every mutation gated by a writer manifest (Phases 1–3).
- **Reversibility:** path moves are git renames; `--dry-run` precedes every real move; the pilot gates the rollout.
- **Known deferral:** the per-parser output-path edit (Task 3.3) and per-parser regen classification (§9-C) are specified per-category in Phase 6 rather than unrolled here, because they depend on each parser's internals — read the parser when you reach its category. This is the one place the plan is template-not-code, by necessity.
