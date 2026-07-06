# Phase A1 — Claude audit, round 1

## Methodology

Read `plans/2026-05-17-phase-1-implementation.md` (all slot "Tests first" blocks), `build/tools/phase1_completion_audit.py`, and the full diff of commit `f3ba9282` via `git show`. Read `plans/section-8-test-manifest.yaml` to understand what test paths the gate actually checks. Ran `git log --format="%h %ai %s"` across all 80 most recent commits to map the chronological sequence, then ran per-slot `--grep="[Ss]lot.N\b"` queries plus `--grep="^test:"` and `--grep="^test("` to enumerate all test-prefixed commits. For the Section 8 spot check, ran `git log --diff-filter=A` against specific test and production files from the manifest to compare first-add commit dates. For commit `f3ba9282`, captured old and new regexes from the diff and identified which commit subjects change status under the relaxation.

---

## Per-slot verdict

| Slot | RED commit | GREEN commit | RED-before-GREEN? | Verdict |
|---|---|---|---|---|
| 0 | `1c6b1008` 2026-05-17 15:26 | `3ae89e45` 2026-05-17 15:34 | yes | VERIFIED |
| 1 | `445818df` 2026-05-17 15:54 | `3e9dff03` 2026-05-17 16:13 | yes | VERIFIED |
| 2 | `abd81ecc` 2026-05-17 16:32 | `285d7f7b` 2026-05-17 17:30 | yes | VERIFIED |
| 3 | `133a77fc` 2026-05-17 22:25 | `2facb6bf` 2026-05-17 22:55 | yes | VERIFIED |
| 4 | `53a165df` 2026-05-18 10:32 | `44dc0de0` 2026-05-18 14:02 | yes | VERIFIED |
| 5 | `27eee92c` 2026-05-18 15:02 | `01e8160a` 2026-05-18 15:14 | yes | VERIFIED |
| 6 | `2b32773e` 2026-05-18 16:11 | `31f560fe` 2026-05-18 16:30 | yes | VERIFIED |
| 7 | `88223441` 2026-05-18 17:43 | `76852329` 2026-05-18 18:47 | yes | VERIFIED |
| 8 | `22c5bb26` 2026-05-18 19:14 | `4297b81b` 2026-05-18 19:35 | yes | VERIFIED |
| 9 | `6aca06ad` 2026-05-18 20:25 | `57e873cf` 2026-05-18 20:37 | yes | VERIFIED |
| 10 | `77322247` 2026-05-19 08:48 | `dd87cb2d` 2026-05-19 09:39 | yes | VERIFIED |
| 11 | `b090b506` 2026-05-19 13:08 | `3852f7c3` 2026-05-19 14:26 | yes | VERIFIED |
| 12 | `639142d4` 2026-05-19 16:56 | `6223b080` 2026-05-19 17:10 | yes | VERIFIED |
| 13 | `99527d7b` 2026-05-19 18:09 | `81ef835a` 2026-05-19 18:32 | yes | VERIFIED |

**Notes on per-slot findings:**

- **Slot 0**: The `--grep="[Ss]lot.0\b"` query returns only the GREEN commit (`3ae89e45`, subject `refactor(R53): rename lexicons el → grc...`). The RED commit (`1c6b1008`, "test: add R53 lexicon rename no-regression guard (RED)") is confirmed via the chronological git log. The GREEN uses `refactor` not `feat`, but this is the correct production commit for the slot.

- **Slot 2**: Two test-quality fix commits (`55331c17` 16:41, `659329fc` 16:54) land between the RED and GREEN. Both carry `test:` subjects. Ordering is preserved.

- **Slot 3**: A post-GREEN mini-slot for `mixed_script` runs immediately after: RED `caa867e4` 23:08 ("test: mixed_script flag RED suite") followed by GREEN `048d30d9` 23:15 ("feat: mixed_script diagnostic flag on classify_block output"). The `mixed_script` feature is not a named slot in the plan and these commits are NOT in the manifest. They follow the RED-before-GREEN discipline but are outside the gate's scope.

- **Slot 11**: A second GREEN commit for Slot 11 appears post-regex-relaxation at `51b88f35` 2026-05-19 19:04 ("feat(schaff-data): Slot 11 data phase — migrate + patch source_pages"). This is a data-phase complement to the migration script GREEN (`3852f7c3`). The test RED commit (`b090b506`) predates both GREENs.

- **Slot 13**: Two git stash entries (`a761a308`, `ef47a214`, both at 18:26) appear between the RED and GREEN for Slot 13 — these are git mechanics, not substantive commits.

---

## Commit f3ba9282

- Old regex: `^test\([a-z-]+\):`
- New regex: `^test[:(]`
- Author-date: 2026-05-19 18:54:21 +1000
- Verdict: **legitimate** — the relaxation is technically correct; `test:` (no scope) is an equally valid conventional commit format. The old regex was overly specific.

**Timing concern (not a defect verdict, but a convergence flag):** The Slot 13 GREEN commit (`81ef835a`) landed at 18:32 with the strict regex. The regex relaxation (`f3ba9282`) landed 22 minutes later at 18:54. This sequence implies the audit script was run against real git history and FAILED because Slots 0–3 use `test:` subjects. The Slot 13 test (`test_phase1_completion_audit_replays_both_gates`) was already GREEN at 18:32, which means it did not run the gate against actual Slots 0–3 commit history — otherwise the test would have been RED with the strict regex. This makes the Slot 13 test itself a vacuous pass (see Audit script section below).

**Evidence per affected commit — commits whose status changes under the relaxation:**

- `1c6b1008` — "test: add R53 lexicon rename no-regression guard (RED)" — Slot 0 RED; uses `test:` (no scope); OLD regex fails, new regex passes. This is a genuine test-first commit for Slot 0. Relaxation is legitimate.
- `445818df` — "test: Slot 1 schema lock RED-first suite" — Slot 1 RED; uses `test:` (no scope); OLD regex fails, new regex passes. Genuine test-first commit. Relaxation is legitimate.
- `abd81ecc` — "test: Slot 2 language detection RED-first suite" — Slot 2 RED; uses `test:` (no scope); OLD regex fails, new regex passes. Genuine test-first commit. Relaxation is legitimate.
- `55331c17` — "test: fix Slot 2 RED test gaps" — Slot 2 test-fix (intermediate); uses `test:`; OLD regex fails, new regex passes. Intermediate test-fix commit, not a production commit. Relaxation is legitimate.
- `659329fc` — "test: fix Slot 2 RED test quality" — Slot 2 test-fix (intermediate); same as above. Legitimate.
- `133a77fc` — "test: Slot 3 reconcile RED-first suite" — Slot 3 RED; uses `test:` (no scope); OLD regex fails, new regex passes. Genuine test-first commit. Relaxation is legitimate.
- `a7e64b20` — "test: fix schema path depth in test_match_explanations" — Slot 3 intermediate test-fix; uses `test:`; legitimate.
- `caa867e4` — "test: mixed_script flag RED suite" — post-Slot-3 mini-slot; uses `test:`; legitimate.

No commits newly passing under the new regex appear to be mislabeled production commits. All affected commits are genuine test or test-fix commits that used the `test:` (no-scope) conventional format.

---

## Audit script vacuous-pass surface

- `phase1_completion_audit.py:77–83` — **`_gate_tdd_conformance` checks only the first-commit subject, not ordering.** The function iterates over `test_paths` from the manifest and for each path calls `_first_git_subject(path)`, which returns the subject of the chronologically EARLIEST commit touching that file. It then checks whether this subject matches `RED_SUBJECT_RE`. This is a proxy for "test was written first" but does NOT verify that the corresponding production commits come AFTER the test commit. A developer could write production code in a commit with any non-`test:` subject first, then add tests in a `test:`-prefixed commit, and the gate would still PASS — because the test file's first commit would be the `test:` commit added after. The gate has no reference to the production file paths and does no cross-file ordering check. Severity: **fix-this-phase**.

- `phase1_completion_audit.py:47–53` — **Manifest is a curated subset of the plan's §8 requirements.** `_manifest_test_paths` returns only the paths explicitly listed in `plans/section-8-test-manifest.yaml`. The manifest has 110 lines and 44 test paths across Slots 0–12 (no Slot 13 entry beyond the manifest file itself). Notable omissions vs. the plan's per-slot "Tests first" blocks:
  - `tests/test_a1_schemas.py` — the plan's Slot 1 "Tests first" begins with `test_reconciled_record_round_trip` in this file, but the file was first committed on 2026-05-12 (commit `68eb288b`, subject "feat(a1): land foundation schemas, libraries, and tests") — 5 days before Phase 1. Its first commit subject is "feat", which would FAIL `RED_SUBJECT_RE`. The manifest excludes this file, making the gate's Slot 1 pass silent on the plan's first-named Slot 1 test.
  - `tests/test_generated_enums.py` — the plan's Slot 0 and Slot 1 completion criteria both cite this file; it is absent from the manifest.
  - `tests/test_lang_classifier.py` — the plan's Slot 2 completion criterion cites this file; absent from the manifest.
  - `tests/test_reconcile/test_integration.py` is in the manifest for Slot 3, but `tests/test_reconcile/test_match_explanations.py` also appears; the plan cites both, and these are manifested.
  Severity: **fix-this-phase** (manifest coverage gap means the gate does not replay all plan-named §8 tests).

- `phase1_completion_audit.py:80` — **No early-return path skips the ordering check.** Every path in `test_paths` is iterated. If `_first_git_subject` returns `None` (no commits for the path — file doesn't exist in git history), the path is added to `failing_paths` and the gate FAILS. This is correct behaviour; missing test files are correctly treated as failures.

- `phase1_completion_audit.py:60–74` — **`_first_git_subject` uses author-date order (via `--reverse`), not topological order.** `git log --reverse` reverses by author-date. If a developer amended commits or rebased, author-date and topology could diverge. In this repo's linear history this is not a current concern, but it is a structural fragility.

- **Self-referential gate**: Slot 13's own test (`test_phase1_completion_audit_replays_both_gates`) in commit `99527d7b` (18:09) was GREEN with the strict regex at the Slot 13 GREEN commit (18:32). This means the test does not exercise the gate against the real git commit history for Slots 0–3 — otherwise the test would have been RED under the strict regex until the relaxation landed. The Slot 13 gate passes its own TDD check only because the test doesn't replay real history.

---

## Section 8 spot check

| Test | Test-add SHA + date | Production-add SHA + date | Order OK? |
|---|---|---|---|
| Slot 1: `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py` | `445818df` 2026-05-17 15:54 | `3e9dff03` 2026-05-17 16:13 (first schema in Slot 1 GREEN) | yes |
| Slot 3: `tests/test_reconcile/test_anchor_graph.py` | `133a77fc` 2026-05-17 22:25 | `2facb6bf` 2026-05-17 22:55 (reconcile core GREEN) | yes |
| Slot 4: `tests/test_adr0013_calibration_gate.py` | `53a165df` 2026-05-18 10:32 | `44dc0de0` 2026-05-18 14:02 (calibration report GREEN) | yes |
| Slot 7: `tests/test_warning_producer_attestation_coverage.py` | `88223441` 2026-05-18 17:43 | `76852329` 2026-05-18 18:47 (checkers GREEN) | yes |
| Slot 9: `tests/test_review_patch_round_trip.py` | `6aca06ad` 2026-05-18 20:25 | `57e873cf` 2026-05-18 20:37 (apply/inspect CLI GREEN) | yes |

Note: `tests/test_a1_schemas.py` (plan's Slot 1 primary test) was first added in `68eb288b` 2026-05-12 ("feat(a1):" subject — 5 days pre-Phase-1) versus production `schemas/v1/reconciled_record.schema.json` first added in `3e9dff03` 2026-05-17 16:13. The test file predates the production schema, but its first-commit subject is "feat" — it would FAIL the gate if included in the manifest. The manifest's Slot 1 entries use substitute test files created with `test:` subjects.

---

## Defects flagged

1. **`_gate_tdd_conformance` does not verify production-code ordering.** The gate only checks the first commit subject of each test file — it provides no evidence that the production commit for any slot came AFTER the test commit. A slot that committed production code first and tests second (with a `test:` subject) would PASS the gate. Severity: **fix-this-phase**. Remediation: add `_first_production_subject(path)` per slot, cross-check commit timestamps, fail if production timestamp < test timestamp.

2. **Manifest omits plan-required test files.** `tests/test_a1_schemas.py`, `tests/test_generated_enums.py`, `tests/test_lang_classifier.py` are named in the plan's per-slot "Tests first" blocks but absent from the manifest. The omission is partly forced (pre-existing `test_a1_schemas.py` has a "feat" first-commit subject), but it means the gate does not verify the plan's stated RED-first requirements for these files. Severity: **fix-this-phase**. Remediation: extend the gate to check first-MODIFICATION (not first-creation) commit subject for pre-existing test files; add missing manifest entries.

3. **Slot 13 self-referential vacuous pass.** `test_phase1_completion_audit_replays_both_gates` (the gate's own test) does not exercise the gate against real git history for Slots 0–3. This is inferred from the fact that the test was GREEN at 18:32 with the strict regex, while the regex was relaxed 22 minutes later. The test is likely written against fixture or mock data, not a live git subprocess call. Severity: **fix-this-phase**. Remediation: verify the test runs `phase1_completion_audit.py` as a subprocess against the real working tree, not against stubbed git output.

---

## Convergence flags

1. **f3ba9282 timing vs. Slot 13 test scope.** My verdict is LEGITIMATE but the timing (22-minute gap between Slot 13 GREEN and the relaxation) implies the Slot 13 test doesn't test against real git history. Codex's pass may confirm or challenge this interpretation.

2. **Manifest completeness.** I found three plan-required test files absent from the manifest. Codex may find additional omissions or may have a different interpretation of which omissions are material.

3. **`mixed_script` mini-slot.** Commits `caa867e4` / `048d30d9` / `27b52672` form a mini RED-GREEN cycle outside the named Slot 0–13 sequence, not in the manifest. Whether this warrants a VACUOUS finding for Slot 3 (since it adds test-first content to the Slot 3 production code base but isn't part of the named slots) needs Codex's view.

4. **`test_phase1_completion_audit_replays_both_gates` implementation.** I have not read the actual test file to confirm it uses real vs. mocked git. Codex should read it directly.
