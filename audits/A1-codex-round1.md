# Phase A1 — Codex audit, round 1

## Methodology
I read `AGENTS.md`, `plans/2026-05-17-phase-1-implementation.md`, `build/tools/phase1_completion_audit.py`, `plans/section-8-test-manifest.yaml`, and `git show --date=iso-strict --stat --patch f3ba9282`; I did not read `audits/A1-claude-round1.md`. I ran the requested per-slot grep shape via `git log --all --oneline --grep="[Ss]lot.{0,3}<N>\b"` for slots 0-13; every one returned `no matches for grep '[Ss]lot.{0,3}<N>\b'`, so I used slot-heading keyword fallbacks from the plan. I then inspected candidate commits with `git show -s --date=iso-strict --format='%h%x09%ad%x09%s'` and `git diff-tree --no-commit-id --name-only -r`, searched `^test:` and `^test\(` subjects, ran the five requested `--diff-filter=A` spot checks, and ran `py -3 build/tools/phase1_completion_audit.py --json`, which emitted `{"adr0013_calibration": "pass", "failing_paths": [], "manifest_path": "plans\\section-8-test-manifest.yaml", "pass": true, "schaff_herzog_reviewer_clean": "pass", "tdd_conformance": "pass"}`.

## Per-slot verdict
| Slot | RED commit | GREEN commit | RED-before-GREEN? | Verdict |
|---|---|---|---|---|
| 0 | `1c6b1008` @ `2026-05-17T15:26:08+10:00` | `3ae89e45` @ `2026-05-17T15:34:08+10:00` | yes | VERIFIED |
| 1 | `445818df` @ `2026-05-17T15:54:10+10:00` | `3e9dff03` @ `2026-05-17T16:13:14+10:00` | yes | VERIFIED |
| 2 | `abd81ecc` @ `2026-05-17T16:32:53+10:00` | `285d7f7b` @ `2026-05-17T17:30:35+10:00` | yes | VERIFIED |
| 3 | `133a77fc` @ `2026-05-17T22:25:32+10:00` | `2facb6bf` @ `2026-05-17T22:55:24+10:00` | yes | VERIFIED |
| 4 | `53a165df` @ `2026-05-18T10:32:35+10:00` | `44dc0de0` @ `2026-05-18T14:02:01+10:00` | yes | VERIFIED |
| 5 | `27eee92c` @ `2026-05-18T15:02:15+10:00` | `01e8160a` @ `2026-05-18T15:14:10+10:00` | yes | VERIFIED |
| 6 | `2b32773e` @ `2026-05-18T16:11:34+10:00` | `31f560fe` @ `2026-05-18T16:30:07+10:00` | yes | VERIFIED |
| 7 | `88223441` @ `2026-05-18T17:43:55+10:00` | `76852329` @ `2026-05-18T18:47:37+10:00` | yes | VERIFIED |
| 8 | `22c5bb26` @ `2026-05-18T19:14:22+10:00` | `4297b81b` @ `2026-05-18T19:35:03+10:00` | yes | VERIFIED |
| 9 | `6aca06ad` @ `2026-05-18T20:25:20+10:00` | `57e873cf` @ `2026-05-18T20:37:41+10:00` | yes | VERIFIED |
| 10 | `77322247` @ `2026-05-19T08:48:49+10:00` | `dd87cb2d` @ `2026-05-19T09:39:02+10:00` | yes | VERIFIED |
| 11 | `b090b506` @ `2026-05-19T13:08:37+10:00` | `3852f7c3` @ `2026-05-19T14:26:02+10:00` | yes | VERIFIED |
| 12 | `639142d4` @ `2026-05-19T16:56:28+10:00` | `6223b080` @ `2026-05-19T17:10:12+10:00` | yes | VERIFIED |
| 13 | `99527d7b` @ `2026-05-19T18:09:34+10:00` | `81ef835a` @ `2026-05-19T18:32:20+10:00` | yes | VERIFIED |

## Commit f3ba9282
- Old regex: `RED_SUBJECT_RE = re.compile(r"^test\([a-z-]+\):")`
- New regex: `RED_SUBJECT_RE = re.compile(r"^test[:(]")`
- Author-date: `2026-05-19T18:54:21+10:00`
- Verdict: legitimate
- Evidence (per affected commit):
  - `1c6b1008` — Slot 0 RED test commit touched only `tests/test_phase1_lexicon_rename_no_regression.py`; old regex excluded the real `test:` subject.
  - `445818df` — Slot 1 RED test commit touched only `tests/`; old regex excluded the real `test:` subject.
  - `abd81ecc` — Slot 2 RED test commit touched only `tests/`; old regex excluded the real `test:` subject.
  - `133a77fc` — Slot 3 RED test commit touched `tests/fixtures/` and `tests/test_reconcile/`; old regex excluded the real `test:` subject.
  - `55331c17` and `659329fc` — Slot 2 RED-test repair commits touched only `tests/`; not production commits mislabeled as tests.
  - `a7e64b20` and `caa867e4` — Slot 3 / adjacent RED-test repair commits touched only `tests/`; benign under the relaxed regex.
  - `27eee92c`, `2b32773e`, `88223441`, `22c5bb26`, `6aca06ad`, `77322247`, `b090b506`, `639142d4`, and `99527d7b` — already matched the old parenthetical convention and do not justify the relaxation by themselves.

## Audit script vacuous-pass surface
- `phase1_completion_audit.py:47` — the gate discovers test paths dynamically from the manifest, not from fixed slots: `def _manifest_test_paths(manifest: dict[str, Any]) -> list[str]:`
- `phase1_completion_audit.py:49` — malformed or absent `tests` returns an empty list, not a failure: `if not isinstance(tests, list):`
- `phase1_completion_audit.py:50` — empty manifest test list becomes `[]`: `return []`
- `phase1_completion_audit.py:77` — TDD conformance accepts only the supplied list and has no slot 0-13 coverage check: `def _gate_tdd_conformance(test_paths: list[str]) -> tuple[str, list[str]]:`
- `phase1_completion_audit.py:83` — zero failing paths means pass, so an empty manifest passes vacuously: `return _status(not failing_paths), failing_paths`
- `phase1_completion_audit.py:61` — the ordering probe uses `git log`, not author-date comparison: `result = _subprocess.run(`
- `phase1_completion_audit.py:62` — the command is path-level first-subject only: `["git", "log", "--reverse", "--format=%s", "--", path],`
- `phase1_completion_audit.py:80` — the check only inspects the first subject for each test path: `first_subject = _first_git_subject(path)`
- `phase1_completion_audit.py:81` — it verifies subject prefix, not RED-before-GREEN production ordering: `if first_subject is None or RED_SUBJECT_RE.match(first_subject) is None:`
- `phase1_completion_audit.py:115` — report construction delegates Gate 1 entirely to manifest paths: `tdd_conformance, failing_paths = _gate_tdd_conformance(_manifest_test_paths(manifest))`
- Severity: blocks-Phase-2

## Section 8 spot check (5 tests)
| Test | Test-add SHA + date | Production-add SHA + date | Order OK? |
|---|---|---|---|
| `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py` vs `schemas/v1/reconciled_record.schema.json` | `445818df` @ `2026-05-17T15:54:10+10:00` | `3e9dff03` @ `2026-05-17T16:13:14+10:00` | yes |
| `tests/test_reconcile/test_anchor_graph.py` vs `build/lib/reconcile/anchor_graph.py` | `133a77fc` @ `2026-05-17T22:25:32+10:00` | `2facb6bf` @ `2026-05-17T22:55:24+10:00` | yes |
| `tests/test_adr0013_calibration_gate.py` vs `build/tools/calibration_report.py` | `53a165df` @ `2026-05-18T10:32:35+10:00` | `44dc0de0` @ `2026-05-18T14:02:01+10:00` | yes |
| `tests/test_warning_producer_language_confidence.py` vs `build/lib/warning_producers/language_confidence.py` | `88223441` @ `2026-05-18T17:43:55+10:00` | `76852329` @ `2026-05-18T18:47:37+10:00` | yes |
| `tests/test_review_patch_round_trip.py` vs `build/tools/apply_review_patch.py` | `6aca06ad` @ `2026-05-18T20:25:20+10:00` | `57e873cf` @ `2026-05-18T20:37:41+10:00` | yes |

## Defects flagged
1. Gate 1 can pass vacuously if `plans/section-8-test-manifest.yaml` has no `tests` list, has an empty `tests` list, or omits a slot; the script does not independently require slots 0-13 or compare RED commits against GREEN production commits — severity: blocks-Phase-2.

## Convergence flags
The per-slot Git evidence I inspected supports RED-before-GREEN ordering for slots 0-13, and the `f3ba9282` regex relaxation is legitimate for real `test:` RED commits from slots 0-3. The convergence blocker is implementation quality in `build/tools/phase1_completion_audit.py`: its current `tdd_conformance: pass` is consistent with the manifest, but it is not strong enough to prove the Phase 1 plan's per-slot TDD gate.
