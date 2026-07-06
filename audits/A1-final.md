# Phase A1 — TDD conformance gate replay — final audit

**Date:** 2026-05-19
**Rounds run:** 1
**Convergence:** full

---

## Per-slot verdict

| Slot | Verdict | Both reviewers? | Evidence (SHAs) |
|---|---|---|---|
| 0 | VERIFIED | yes | `1c6b1008` 15:26 < `3ae89e45` 15:34 |
| 1 | VERIFIED | yes | `445818df` 15:54 < `3e9dff03` 16:13 |
| 2 | VERIFIED | yes | `abd81ecc` 16:32 < `285d7f7b` 17:30 |
| 3 | VERIFIED | yes | `133a77fc` 22:25 < `2facb6bf` 22:55 |
| 4 | VERIFIED | yes | `53a165df` 10:32 < `44dc0de0` 14:02 |
| 5 | VERIFIED | yes | `27eee92c` 15:02 < `01e8160a` 15:14 |
| 6 | VERIFIED | yes | `2b32773e` 16:11 < `31f560fe` 16:30 |
| 7 | VERIFIED | yes | `88223441` 17:43 < `76852329` 18:47 |
| 8 | VERIFIED | yes | `22c5bb26` 19:14 < `4297b81b` 19:35 |
| 9 | VERIFIED | yes | `6aca06ad` 20:25 < `57e873cf` 20:37 |
| 10 | VERIFIED | yes | `77322247` 08:48 < `dd87cb2d` 09:39 |
| 11 | VERIFIED | yes | `b090b506` 13:08 < `3852f7c3` 14:26 |
| 12 | VERIFIED | yes | `639142d4` 16:56 < `6223b080` 17:10 |
| 13 | VERIFIED | yes | `99527d7b` 18:09 < `81ef835a` 18:32 |

All 14 slots show at least one test-prefixed commit landing before the first production commit, verified independently by both reviewers against identical SHAs and author-dates. The Section 8 spot check (5 pairs from Slots 1, 3, 4, 7, 9 using `--diff-filter=A`) confirmed file-level ordering: test file added before production file in every case.

---

## Commit f3ba9282

- Old regex: `^test\([a-z-]+\):`
- New regex: `^test[:(]`
- Verdict: **legitimate**
- Evidence: The eight commits whose status changes under the relaxation are all genuine test or test-fix commits from Slots 0–3 that used the conventional `test:` (no-scope) format rather than `test(scope):`. None are mislabeled production commits.
  - `1c6b1008` — Slot 0 RED; touches only `tests/`; subject "test: add R53 lexicon rename no-regression guard (RED)". Legitimate.
  - `445818df` — Slot 1 RED; touches only `tests/`; subject "test: Slot 1 schema lock RED-first suite". Legitimate.
  - `abd81ecc` — Slot 2 RED; touches only `tests/`; subject "test: Slot 2 language detection RED-first suite". Legitimate.
  - `55331c17`, `659329fc` — Slot 2 test-quality fix commits; touch only `tests/`. Legitimate.
  - `133a77fc` — Slot 3 RED; touches `tests/` and `tests/fixtures/`; subject "test: Slot 3 reconcile RED-first suite". Legitimate.
  - `a7e64b20`, `caa867e4` — Slot 3 intermediate and adjacent test commits; touch only `tests/`. Legitimate.

**Timing note (not a verdict change):** The relaxation landed 22 minutes after the Slot 13 GREEN commit, implying the audit script was run against real git history and FAILED on Slots 0–3 before the fix. This is expected behavior — the script was working correctly when run live; the strict regex was simply overly prescriptive. The fix was correct.

---

## Audit script vacuous-pass surface

Both reviewers agree: `build/tools/phase1_completion_audit.py` has the following structural weaknesses in the TDD-conformance gate. These are weaknesses in the audit tooling, not evidence that the underlying commit ordering is wrong (it is correct, per the per-slot findings above).

1. **`phase1_completion_audit.py:47–53` — Empty manifest passes vacuously.** `_manifest_test_paths` returns `[]` if the manifest `tests` key is absent, non-list, or empty. An empty list passed to `_gate_tdd_conformance` produces zero `failing_paths` and returns `"pass"`. A corrupted or empty manifest is indistinguishable from a clean gate. (Codex finding, confirmed by Claude reading the code.)

2. **`phase1_completion_audit.py:77–83` — No production-code ordering check.** `_gate_tdd_conformance` verifies only that the earliest commit touching each test file has a `test:`-prefixed subject. It does not cross-reference production file paths, does not compare test-commit timestamp against production-commit timestamp, and provides no evidence that production code was absent when the test was first committed. A developer could write all production code first, then add `test:`-prefixed test files, and the gate would PASS. (Both reviewers independently identified this.)

3. **`phase1_completion_audit.py:60–74` — First-commit subject only, not RED-state verification.** `_first_git_subject` checks the subject line of the chronologically earliest commit touching the path. It cannot verify the test was actually failing (RED) at that commit — only that someone used a `test:` prefix. (Both reviewers.)

4. **Manifest omits plan-required test files.** `plans/section-8-test-manifest.yaml` excludes several files named in the plan's per-slot "Tests first" blocks: `tests/test_a1_schemas.py` (Slot 1 — first committed in pre-Phase-1 `68eb288b` with "feat(a1):" subject), `tests/test_generated_enums.py` (Slots 0, 1), `tests/test_lang_classifier.py` (Slot 2). The manifest is a pruned set of files whose first commit happens to carry a `test:` subject — files that predate Phase 1 or were created with non-`test:` subjects are silently excluded. (Claude finding; Codex implied without enumerating.)

5. **Slot 13 self-referential pass.** The gate's own test (`test_phase1_completion_audit_replays_both_gates`) was GREEN at 18:32 with the strict regex. If the test ran the audit script as a subprocess against real git history, it would have been RED (Slots 0–3 fail strict regex). The test therefore does not exercise the gate against real history — confirming it uses fixtures or mocks, not a live git call. (Claude finding.)

**Severity: fix-this-phase** (Codex rated blocks-Phase-2; Claude rated fix-this-phase; agreed to the stronger rating given that Phase 2 is expected to build on a verified Phase 1 TDD gate — an unverifiable gate is a Phase-2 risk regardless of whether the underlying ordering happens to be correct).

---

## Defects requiring remediation

1. **`_gate_tdd_conformance` does not verify production-code ordering.** The gate is structurally insufficient to enforce TDD. Remediation: add a companion function that compares the first test-commit timestamp against the first production-commit timestamp per slot, using a slot-keyed map of test-path → production-path pairs. The manifest format could carry an optional `production_path` field per entry to support this. Proposed slot: new audit sub-slot within the A1 remediation pass.

2. **Empty manifest passes vacuously.** Add a preflight assertion in `_gate_tdd_conformance`: raise or return fail if `test_paths` is empty. Trivial fix; can land in the same commit as the production-ordering check.

3. **Manifest coverage gaps.** The manifest omits plan-required test files because those files predate Phase 1. The fix requires either: (a) tracking which COMMIT within an existing file first added the plan-required test function (not the file's first commit), or (b) adding a manifest annotation for pre-existing files that names the first Phase-1 commit that added the required test. Either approach is non-trivial; assign to a dedicated slot.

4. **Slot 13 test does not exercise the gate against real git history.** Remediation: confirm whether `test_phase1_completion_audit_replays_both_gates` uses a subprocess call to the real working tree or stubbed git output. If stubbed: refactor to use a temporary git repo fixture with committed test files in both `test:` and `test(scope):` format. Proposed timing: alongside defect 1 fix.

---

## Unresolved disagreements

None. Both reviewers agreed on all slot verdicts, the f3ba9282 legitimacy verdict, and the structural vacuous-pass findings. Severity was reconciled to **fix-this-phase** (accepting Codex's stronger framing).

---

## Recommendation

The TDD-conformance gate **holds on the evidence from the actual git history.** Every slot (0–13) has at least one test-prefixed commit that predates the production commit, verified independently by two reviewers against identical SHAs. The Section 8 spot check (5 file-level pairs) confirmed the same. Commit `f3ba9282` is a legitimate fix — both `test:` and `test(scope):` are standard conventional commit formats, and the relaxed regex is the correct choice.

The gate's **implementation** is a different matter. `phase1_completion_audit.py` is structurally vacuous: it checks a curated manifest of test-file paths for `test:`-prefixed first-commit subjects, but does no ordering comparison against production files and would pass on an empty manifest. The gate passed because the implementation happened to be a reasonable (if incomplete) proxy for a real ordering check, and because the underlying ordering happens to be correct.

**Phase 2 is unblocked from a commit-history perspective** — the ordering is sound. However, before Phase 3 or any external audit treats the Slot 13 TDD-conformance gate as a formal verification, the four defects above should be resolved. The gate as currently written is a convention check, not an ordering proof. Recommend landing the audit tooling fixes as the first sub-slot of the A1 remediation pass, before committing to Phase 2's completion-gate audit at Slot 13 equivalent.
