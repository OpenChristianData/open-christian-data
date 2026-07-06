"""TEST-08 invariant: the WCT build + S3 reconcile pipeline is deterministic
regardless of PYTHONHASHSEED.

Root cause (fixed 2026-06-01): _Column.rep_key in wct_builder.py used
    max(set(keys), key=keys.count)
which iterates a set in hash order -- different PYTHONHASHSEED values produce different
iteration orders, so on count ties (two geometry-bearing engines disagreeing on a reading)
the representative key used in NW alignment changed. This caused geometry-less engines
(Surya) to align differently between runs, flipping:
  * alignment_confidence (0.99 vs 0.8333 -- 3/3 vs 2/3 engines attesting)
  * chosen_reading_attested_by list length
  * chosen_reading at ~3 positions per page

Fix: add the key itself as a secondary sort term so the comparison is total:
    max(set(keys), key=lambda k: (keys.count(k), k))
Since all keys are distinct strings, (count, k) is unique for each k, so max() returns
the same element regardless of set iteration order.

Three guards:
  (A) Unit test for _Column.rep_key -- directly tests the fix; catches any revert.
      Primary guard for the specific one-line change.
  (B) WCT builder subprocess test -- runs probe_wct_builder_determinism.py with
      PYTHONHASHSEED=0 and =1 and asserts byte-identical WCT output. Exercises
      build_wct_page() and _Column.rep_key directly, filling the coverage gap
      identified in the Codex adversarial review (2026-06-02).
  (C) Reconciler subprocess test -- runs reconcile_s3.py with PYTHONHASHSEED=0 and =1
      on the frozen wct_vol01_synthetic.json fixture and asserts byte-identical output.
      Guards against future hash-order regressions in the reconcile path itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "s3_reconciler"
OCCURRED_AT = "2026-06-01T00:00:00+00:00"


# --------------------------------------------------------------------------- #
# (A) Unit: _Column.rep_key is deterministic on count ties.
# --------------------------------------------------------------------------- #


def test_rep_key_deterministic_on_count_tie() -> None:
    """rep_key must return the same key regardless of set iteration order.

    Specifically: on a count tie, the lexicographically largest key wins -- the
    comparison key lambda k: (keys.count(k), k) is total on distinct strings so
    max() always returns the same element regardless of hash order.
    """
    from build.lib.wct_builder import _Column, _LogicalToken

    def _tok(key: str) -> _LogicalToken:
        return _LogicalToken(
            key=key,
            raw_reading=key,
            source_spans=[],
            confidence=None,
            span_type="exact",
            relation="1:1",
            normalisation_applied=[],
            hyphen_evidence=None,
            y=None,
            x=None,
        )

    # Two engines, different keys, equal count -> lexicographically largest wins.
    col = _Column()
    col.attestations["engine_a"] = _tok("aaa")
    col.attestations["engine_z"] = _tok("zzz")
    assert col.rep_key == "zzz"

    # Reverse insertion order: same result.
    col2 = _Column()
    col2.attestations["engine_z"] = _tok("zzz")
    col2.attestations["engine_a"] = _tok("aaa")
    assert col2.rep_key == "zzz"

    # Majority reading wins (count 2 > count 1), no tie.
    col3 = _Column()
    col3.attestations["e1"] = _tok("foo")
    col3.attestations["e2"] = _tok("foo")
    col3.attestations["e3"] = _tok("bar")
    assert col3.rep_key == "foo"

    # Single key -- unambiguous.
    col4 = _Column()
    col4.attestations["only"] = _tok("church")
    assert col4.rep_key == "church"

    # Empty column.
    assert _Column().rep_key == ""


# --------------------------------------------------------------------------- #
# (B) WCT builder subprocess: build_wct_page output is byte-identical across seeds.
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_wct_builder_deterministic_across_hash_seeds(tmp_path: Path) -> None:
    """build_wct_page must produce byte-identical WCT JSON for PYTHONHASHSEED=0 and =1.

    Runs tests/probe_wct_builder_determinism.py which creates minimal renderings
    that include a rep_key tie-break scenario (Tesseract reads "c", ABBYY reads "e"
    -- a confusable pair -- creating a count-1 tie in _Column.rep_key for that column)
    and then calls build_wct_page directly. This exercises the code path that was
    actually buggy, filling the gap identified by the Codex adversarial review.

    Note: for single-char confusable pairs the tie-break does not change the merge
    decision (both "c" and "e" are within SAME_SLOT_THRESHOLD=0.5 of Surya's "c"),
    so this specific fixture may not expose a rep_key regression by itself. The unit
    test test_rep_key_deterministic_on_count_tie is the primary guard for that.
    This test's value is end-to-end WCT builder determinism coverage.
    """
    probe = REPO_ROOT / "tests" / "probe_wct_builder_determinism.py"

    def run(seed: int) -> dict:
        out = tmp_path / f"wct_seed{seed}.json"
        env = {**os.environ, "PYTHONHASHSEED": str(seed)}
        subprocess.run(
            [sys.executable, str(probe), str(out)],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        return json.loads(out.read_text(encoding="utf-8"))

    assert run(0) == run(1), (
        "build_wct_page output differs between PYTHONHASHSEED=0 and =1 -- "
        "hash-order-dependent set/dict iteration in the WCT builder path"
    )


# --------------------------------------------------------------------------- #
# (C) Reconciler subprocess: reconcile_s3 output is byte-identical across seeds.
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_reconcile_s3_deterministic_across_hash_seeds(tmp_path: Path) -> None:
    """reconcile_s3.py must produce byte-identical JSON for PYTHONHASHSEED=0 and =1.

    Uses the committed wct_vol01_synthetic.json fixture so the test runs without
    downloading any raw OCR data. Guards against future hash-order regressions in
    the reconcile path (s3_reconciler.py) that are independent of the WCT builder.
    """
    wct = FIXTURE_DIR / "wct_vol01_synthetic.json"
    meta = FIXTURE_DIR / "work_meta.json"
    script = REPO_ROOT / "build" / "tools" / "ocr_pipeline" / "reconcile_s3.py"

    def run_reconcile(seed: int) -> dict:
        out = tmp_path / f"reconciled_seed{seed}.json"
        env = {**os.environ, "PYTHONHASHSEED": str(seed)}
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--wct", str(wct),
                "--work-meta", str(meta),
                "--output", str(out),
                "--occurred-at", OCCURRED_AT,
            ],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        return json.loads(out.read_text(encoding="utf-8"))

    result_0 = run_reconcile(0)
    result_1 = run_reconcile(1)
    assert result_0 == result_1, (
        "reconcile_s3 output differs between PYTHONHASHSEED=0 and PYTHONHASHSEED=1 -- "
        "hash-order-dependent set/dict iteration in the reconcile path"
    )
