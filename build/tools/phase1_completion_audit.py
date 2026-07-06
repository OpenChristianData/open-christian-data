"""phase1_completion_audit.py
Audit tool that verifies all Phase 1 implementation slots meet TDD conformance,
pytest pass, and reconcile-status clean gates before declaring Phase 1 complete.

Subprocess facade pattern (important for test authors):
  Gate 1 (_gate_tdd_conformance) calls _subprocess.run directly -- the raw stdlib
  import alias, not the facade. This makes Gate 1 un-stubbable via monkeypatch and
  forces real git calls against the test's synthetic repo.

  Gates 2 and 3 call subprocess.run -- the _SubprocessFacade wrapper -- making them
  patchable with monkeypatch.setattr("build.tools.phase1_completion_audit.subprocess.run", stub).

  Why this design: selective stubbing in tests. Gate 1 must run real git log against
  a synthetic test repo; Gates 2-3 (pytest, reconcile_status) are stubbed per test.
  Stubbing subprocess.run globally would break Gate 1 -- the git log calls would hit
  the stub, defeating the TDD conformance check regardless of commit subjects.

  When writing tests, use the selective stub pattern (stub only pytest and
  reconcile_status calls; pass everything else through to _real_subprocess.run).
  See tests/test_phase1_completion_audit.py for the canonical stub implementation.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess as _subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


DEFAULT_MANIFEST_PATH = Path("plans/section-8-test-manifest.yaml")
RED_SUBJECT_RE = re.compile(r"^test[:(]")

# Maps slot number -> production file(s) that must be committed AFTER their test file.
# None = skip the ordering check for that slot.
# Slots 0-2: pre-Phase-1 production files have no clear RED anchor.
# Slot 6: reuses engine.py first created in slot 5 — can't isolate slot 6's creation commit.
# Slot 7: warning_producers/__init__.py was created pre-Phase-1 (2026-05-12).
# Slot 8: render_review_html.py was created pre-Phase-1; only derive_scan_jpegs.py is new.
# Slot 11: migrate_schaff_herzog.py skeleton was created in slot 10 before slot 11 RED tests.
# Sourced from plans/2026-05-17-phase-1-implementation.md **Files:** sections.
SLOT_PRODUCTION_FILES: dict[int, list[str] | None] = {
    0: None,
    1: None,
    2: None,
    3: ["build/lib/reconcile/__init__.py"],
    4: ["build/tools/calibration_report.py"],
    5: ["build/lib/modernisation/engine.py"],
    6: None,
    7: None,
    8: ["build/tools/derive_scan_jpegs.py"],
    9: ["build/tools/apply_review_patch.py"],
    10: ["build/tools/reconcile.py"],
    11: None,
    12: ["build/tools/export_hf_dataset.py"],
    13: ["build/tools/phase1_completion_audit.py"],
}


class _SubprocessFacade:
    CalledProcessError = _subprocess.CalledProcessError
    run = staticmethod(_subprocess.run)


subprocess = _SubprocessFacade()


def _status(passed: bool) -> str:
    return "pass" if passed else "fail"


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        print(f"error: manifest not found: {path}", file=sys.stderr)
        return None

    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML in manifest {path}: {exc}", file=sys.stderr)
        return None

    if not isinstance(manifest, dict):
        print(f"error: invalid manifest structure: {path}", file=sys.stderr)
        return None
    return manifest


def _manifest_test_paths(manifest: dict[str, Any]) -> list[str]:
    tests = manifest.get("tests")
    if not isinstance(tests, list):
        return []

    paths: list[str] = []
    for entry in tests:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            paths.append(entry["path"])
    return paths


def _manifest_slot_map(manifest: dict[str, Any]) -> dict[str, int]:
    """Return {test_path: slot} for every entry in the manifest that has a slot."""
    tests = manifest.get("tests")
    if not isinstance(tests, list):
        return {}

    result: dict[str, int] = {}
    for entry in tests:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            slot = entry.get("slot")
            if isinstance(slot, int):
                result[entry["path"]] = slot
    return result


def _first_git_subject(path: str) -> str | None:
    try:
        result = _subprocess.run(
            ["git", "log", "--reverse", "--format=%s", "--", path],
            check=True,
            capture_output=True,
            text=True,
        )
    except _subprocess.CalledProcessError:
        return None

    for line in result.stdout.splitlines():
        subject = line.strip()
        if subject:
            return subject
    return None


def _first_commit_timestamp(path: str) -> int | None:
    """Return the Unix timestamp of the earliest commit touching path, or None."""
    try:
        result = _subprocess.run(
            ["git", "log", "--reverse", "--format=%at", "--", path],
            check=True,
            capture_output=True,
            text=True,
        )
    except _subprocess.CalledProcessError:
        return None

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped:
            try:
                return int(stripped)
            except ValueError:
                pass
    return None


def _gate_tdd_conformance(
    test_paths: list[str],
    slot_map: dict[str, int] | None = None,
) -> tuple[str, list[str]]:
    # A1-D02: empty manifest is a gate failure, not a vacuous pass
    if not test_paths:
        print("error: TDD conformance gate: manifest has no test paths", file=sys.stderr)
        return "fail", []

    failing_paths: list[str] = []

    for path in test_paths:
        # A1-D01 subject-line check: first commit subject must match test[:(]
        first_subject = _first_git_subject(path)
        if first_subject is None or RED_SUBJECT_RE.match(first_subject) is None:
            failing_paths.append(path)
            continue

        # A1-D01 production-ordering check: test must pre-date every production file
        if slot_map is None:
            continue
        slot = slot_map.get(path)
        if slot is None:
            continue
        prod_files = SLOT_PRODUCTION_FILES.get(slot)
        if not prod_files:
            continue
        test_ts = _first_commit_timestamp(path)
        if test_ts is None:
            continue
        for prod_file in prod_files:
            prod_ts = _first_commit_timestamp(prod_file)
            if prod_ts is not None and prod_ts < test_ts:
                # Production predates test — TDD violation
                if path not in failing_paths:
                    failing_paths.append(path)
                break

    return _status(not failing_paths), failing_paths


def _gate_adr0013_calibration() -> str:
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_adr0013_calibration_gate.py", "-q"],
            check=True,
        )
        return _status(True)
    except subprocess.CalledProcessError:
        return _status(False)


def _gate_schaff_herzog_reviewer_clean() -> str:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "build/tools/reconcile_status.py",
                "reference/schaff/encyclopedia/1908-1914",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return "fail"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "fail"
    return _status(data.get("reviewer_clean") is True)


def _build_report(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    slot_map = _manifest_slot_map(manifest)
    tdd_conformance, failing_paths = _gate_tdd_conformance(
        _manifest_test_paths(manifest), slot_map=slot_map
    )
    adr0013_calibration = _gate_adr0013_calibration()
    schaff_herzog_reviewer_clean = _gate_schaff_herzog_reviewer_clean()
    passed = (
        tdd_conformance == "pass"
        and adr0013_calibration == "pass"
        and schaff_herzog_reviewer_clean == "pass"
    )

    return {
        "tdd_conformance": tdd_conformance,
        "adr0013_calibration": adr0013_calibration,
        "schaff_herzog_reviewer_clean": schaff_herzog_reviewer_clean,
        "pass": passed,
        "failing_paths": failing_paths,
        "manifest_path": str(manifest_path),
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"Gate 1 TDD conformance: {report['tdd_conformance'].upper()}")
    print(f"Gate 2 ADR-0013 calibration: {report['adr0013_calibration'].upper()}")
    print(
        "Gate 3 Schaff-Herzog reviewer-clean: "
        f"{report['schaff_herzog_reviewer_clean'].upper()}"
    )
    if report["failing_paths"]:
        print("Failing paths:")
        for path in report["failing_paths"]:
            print(f"- {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phase 1 completion audit.")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="path to the Section 8 test manifest",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    manifest = _load_manifest(args.manifest)
    if manifest is None:
        return 1

    report = _build_report(args.manifest, manifest)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        _print_human(report)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
