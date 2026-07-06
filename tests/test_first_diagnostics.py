"""B8 -- first diagnostics (oracles + segmentation-diff), failing-first tests (TEST-16).

Architectural slot: Wave-3 first diagnostics (arch D plan section 3). The harness
consumes B6's vol_01 word-confusion-table pages + B7's vol_01 gold sample and
measures the two first diagnostics the research synthesis (section 5.1, R3-D4)
names before any tuning is allowed:

  1. oracle vs gold            -- candidate oracle + alignment oracle computed
                                  against a fixture gold; the gap is
                                  alignment_oracle MINUS candidate_oracle (a large
                                  gap => alignment-limited ceiling, a small gap with
                                  both low => diversity-limited). Reported by zone
                                  and by script.
  2. segmentation-difference   -- per engine pair, the fraction of shared positions
                                  where the engines disagree on token boundaries
                                  (token_span_type class), broken down by zone and
                                  by script.
  3. report-gates-tuning       -- the harness writes its reports to the exact path
                                  the B0 tuning embargo checks; with the report
                                  absent a tuning command stays blocked, with the
                                  harness output present tuning unlocks. The
                                  embargo<->report contract is a load-bearing test,
                                  not a nicety (B0 fail-closed RED gate, 3d9bc567).

These three tests are the B8 TDD contract from the arch D plan (section 2, B8 row)
-- written-failed-then-satisfied, never authored after the implementation.

The WCT pages + gold are SYNTHETIC fixtures: the B8 prompt authorises building and
testing against a small fixture gold + synthetic WCT rather than waiting on the
single reviewer's real gold (a phase-2 input). The deliverable is the measurement
code; the verdict (alignment-limited? diversity-limited?) is phase 2. The fixture
positions are proven to be genuine word-confusion-table-v1 position instances by
test_fixture_positions_are_wct_shaped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.first_diagnostics_contract import (  # noqa: E402
    ORACLE_REPORT_NAME,
    REPORTS_FIRST_SUBPATH,
    SEGMENTATION_REPORT_NAME,
    first_diagnostics_report_present,
    validate_oracle_report,
    validate_segmentation_report,
)
from build.lib.tuning_embargo import (  # noqa: E402
    TuningEmbargoError,
    check_tuning_allowed,
)
from build.tools.diagnostics import first_diagnostics as fd  # noqa: E402


# --------------------------------------------------------------------------- #
# Synthetic fixtures -- WCT position fragments + a gold-truth-by-position map.
# Token strings are ASCII and illustrative; the script label is independent of
# the glyphs for the metric, which only compares reading strings.
# --------------------------------------------------------------------------- #

ENGINES = ("tesseract", "abbyy", "surya")


def _engine_ref(engine_id: str) -> dict:
    return {
        "engine_id": engine_id,
        "family": engine_id,
        "lineage": f"{engine_id}-default",
        "engine_version": "1.0.0",
        "engine_run_id": f"{engine_id}-run-1",
    }


def _candidate(candidate_id: str, raw_reading: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "raw_reading": raw_reading,
        "candidate_key": raw_reading.casefold(),
        "normalisation_applied": [],
        "attesting_engines": ["tesseract"],
        "attesting_families": ["tesseract"],
    }


def _span(engine_id: str, candidate_id, span_type: str, raw_text=None) -> dict:
    """A span record. A skip carries no candidate and no raw_text (B6 contract)."""
    relation = {
        "exact": "1:1",
        "split": "1:n",
        "merge": "n:1",
        "skip": "gap",
        "insertion": "1:1",
    }[span_type]
    record: dict = {
        "span_record_id": f"sr-{engine_id}-{span_type}",
        "engine_id": engine_id,
        "family": engine_id,
        "lineage": f"{engine_id}-default",
        "candidate_id": candidate_id,
        "token_span_type": span_type,
        "segmentation_relation": relation,
        "source_spans": []
        if span_type == "skip"
        else [
            {
                "token_id": f"t-{engine_id}",
                "text": raw_text or "",
                "bbox": {"x": 1.0, "y": 1.0, "w": 1.0, "h": 1.0},
                "line_id": "l-1",
            }
        ],
        "raw_confidence": None if span_type == "skip" else 0.9,
        "calibrated_confidence": None,
        "raw_confidence_aggregation": "none" if span_type == "skip" else "single",
    }
    if span_type != "skip" and raw_text is not None:
        record["raw_text"] = raw_text
    return record


def _position(
    position_id: str,
    zone_type: str,
    script_label: str,
    candidate_set: list[dict],
    span_records: list[dict],
) -> dict:
    return {
        "position_id": position_id,
        "zone": {
            "zone_id": f"z-{zone_type}",
            "zone_type": zone_type,
            "track_id": "track-body",
            "column": None,
            "line_id": "l-1",
            "line_order": 0,
            "position_order": 0,
        },
        "reference_bbox": {"x": 1.0, "y": 1.0, "w": 1.0, "h": 1.0},
        "reference_bbox_source": "surya",
        "hyphenation": {
            "hyphenation_status": "none",
            "raw_line_break_evidence": [],
            "hypothesis_ids": [],
        },
        "script": {
            "image_level": {
                "label": script_label,
                "confidence": 0.9,
                "method": "unicode-block",
            },
            "text_level": {"label": script_label, "method": "unicode-block"},
            "routing": "normal-latin",
        },
        "candidate_set": candidate_set,
        "span_records": span_records,
        "available_engines": [s["engine_id"] for s in span_records],
        "comparable_engines": [
            s["engine_id"] for s in span_records if s["token_span_type"] != "skip"
        ],
        "unassigned_engines": [],
        "alignment_confidence": 0.9,
    }


def _oracle_fixture_page() -> dict:
    """Five positions with known oracle membership.

    candidate hits: P1 (faith), P3 (lord), P5 (theos)        -> 3/5 = 0.6
    alignment hits: P1, P2 (grace via oracle alignment), P3, P5 -> 4/5 = 0.8
    gap = 0.8 - 0.6 = 0.2
    """
    return {
        "positions": [
            _position(
                "P1",
                "body",
                "latin",
                [_candidate("c1", "faith"), _candidate("c1b", "fatih")],
                [
                    _span("tesseract", "c1", "exact", "faith"),
                    _span("abbyy", "c1b", "exact", "fatih"),
                ],
            ),
            # P2: correct reading "grace" was mis-aligned away; only "graoe" is in
            # this slot. The oracle-alignment pass restores "grace" -> align hit,
            # candidate miss. This is the alignment-limited signal.
            _position(
                "P2",
                "body",
                "latin",
                [_candidate("c2", "graoe")],
                [_span("tesseract", "c2", "exact", "graoe")],
            ),
            _position(
                "P3",
                "body",
                "latin",
                [_candidate("c3", "lord")],
                [_span("tesseract", "c3", "exact", "lord")],
            ),
            _position(
                "P4",
                "footnote",
                "latin",
                [_candidate("c4", "amer")],
                [_span("tesseract", "c4", "exact", "amer")],
            ),
            _position(
                "P5",
                "body",
                "greek",
                [_candidate("c5", "theos")],
                [_span("tesseract", "c5", "exact", "theos")],
            ),
        ]
    }


_ORACLE_GOLD = {
    "P1": "faith",
    "P2": "grace",
    "P3": "lord",
    "P4": "amen",
    "P5": "theos",
}
# perfect-alignment pass restores the correct reading the WCT mis-routed at P2.
_ORACLE_ALIGNMENT = {"P2": ["grace"]}


def _segmentation_fixture_page() -> dict:
    """Three engines over three positions.

    S1 body:     tess=exact, abbyy=exact, surya=split  -> surya disagrees
    S2 body:     tess=exact, abbyy=exact, surya=exact  -> all agree
    S3 footnote: tess=skip,  abbyy=exact, surya=exact  -> tesseract disagrees

    pair rates (denominator = 3 shared positions each):
      abbyy__surya:      diff at S1            -> 1/3
      abbyy__tesseract:  diff at S3            -> 1/3
      surya__tesseract:  diff at S1 and S3     -> 2/3
    """
    return {
        "positions": [
            _position(
                "S1",
                "body",
                "latin",
                [_candidate("d1", "word")],
                [
                    _span("tesseract", "d1", "exact", "word"),
                    _span("abbyy", "d1", "exact", "word"),
                    _span("surya", "d1", "split", "wo"),
                ],
            ),
            _position(
                "S2",
                "body",
                "latin",
                [_candidate("d2", "true")],
                [
                    _span("tesseract", "d2", "exact", "true"),
                    _span("abbyy", "d2", "exact", "true"),
                    _span("surya", "d2", "exact", "true"),
                ],
            ),
            _position(
                "S3",
                "footnote",
                "latin",
                [_candidate("d3", "note")],
                [
                    _span("tesseract", None, "skip"),
                    _span("abbyy", "d3", "exact", "note"),
                    _span("surya", "d3", "exact", "note"),
                ],
            ),
        ]
    }


# --------------------------------------------------------------------------- #
# Test 1 -- oracle vs gold (candidate + alignment oracle, gap = align - cand).
# --------------------------------------------------------------------------- #


def test_oracle_vs_gold():
    positions = fd.oracle_positions_from_wct(
        _oracle_fixture_page(),
        _ORACLE_GOLD,
        oracle_alignment=_ORACLE_ALIGNMENT,
    )
    report = fd.compute_oracle_accuracy(positions)

    assert report["candidate_oracle"] == pytest.approx(0.6)
    assert report["alignment_oracle"] == pytest.approx(0.8)
    # the gap is the alignment-minus-candidate difference (R3-D4 / B8 prompt).
    assert report["gap"] == pytest.approx(0.2)

    body = report["by_zone"]["body"]
    assert body["candidate_oracle"] == pytest.approx(0.75)  # P1,P3,P5 hit of P1,P2,P3,P5
    assert body["alignment_oracle"] == pytest.approx(1.0)
    assert body["gap"] == pytest.approx(0.25)

    footnote = report["by_zone"]["footnote"]
    assert footnote["candidate_oracle"] == pytest.approx(0.0)
    assert footnote["alignment_oracle"] == pytest.approx(0.0)

    latin = report["by_script"]["latin"]
    assert latin["candidate_oracle"] == pytest.approx(0.5)  # P1,P3 hit of P1,P2,P3,P4
    assert latin["alignment_oracle"] == pytest.approx(0.75)  # P1,P2,P3
    greek = report["by_script"]["greek"]
    assert greek["candidate_oracle"] == pytest.approx(1.0)

    # the emitted report satisfies the B0 first-diagnostics contract shape.
    assert validate_oracle_report(report) == []


# --------------------------------------------------------------------------- #
# Test 2 -- segmentation-difference per engine pair, by zone + script.
# --------------------------------------------------------------------------- #


def test_segmentation_difference_per_pair():
    positions = fd.segmentation_positions_from_wct(_segmentation_fixture_page())
    report = fd.compute_segmentation_difference(positions)

    pairs = report["segmentation_difference_by_engine_pair"]
    assert pairs["abbyy__surya"] == pytest.approx(1 / 3)
    assert pairs["abbyy__tesseract"] == pytest.approx(1 / 3)
    assert pairs["surya__tesseract"] == pytest.approx(2 / 3)

    # by zone: the difference must NOT silently aggregate across zones.
    body = report["by_zone"]["body"]
    assert body["abbyy__surya"] == pytest.approx(0.5)  # S1 of {S1,S2}
    assert body["abbyy__tesseract"] == pytest.approx(0.0)
    assert body["surya__tesseract"] == pytest.approx(0.5)

    footnote = report["by_zone"]["footnote"]
    assert footnote["abbyy__tesseract"] == pytest.approx(1.0)  # S3 only
    assert footnote["surya__tesseract"] == pytest.approx(1.0)
    assert footnote["abbyy__surya"] == pytest.approx(0.0)

    latin = report["by_script"]["latin"]
    assert latin["surya__tesseract"] == pytest.approx(2 / 3)

    assert validate_segmentation_report(report) == []


# --------------------------------------------------------------------------- #
# Test 3 -- report gates tuning (the embargo<->report contract holds).
# --------------------------------------------------------------------------- #


def test_report_gates_tuning(tmp_path):
    reports_root = tmp_path

    # absent report => tuning is fail-closed blocked.
    assert not first_diagnostics_report_present(reports_root)
    with pytest.raises(TuningEmbargoError):
        check_tuning_allowed("scorer_thresholds", reports_root=reports_root)

    # running the harness writes the reports the embargo checks for.
    fd.run_first_diagnostics(
        oracle_page=_oracle_fixture_page(),
        oracle_gold=_ORACLE_GOLD,
        oracle_alignment=_ORACLE_ALIGNMENT,
        segmentation_page=_segmentation_fixture_page(),
        reports_root=reports_root,
        volume="vol_01",
    )

    report_dir = reports_root / REPORTS_FIRST_SUBPATH
    assert (report_dir / ORACLE_REPORT_NAME).exists()
    assert (report_dir / SEGMENTATION_REPORT_NAME).exists()
    # markdown siblings are emitted alongside the json (section 3 report outputs).
    assert (report_dir / ORACLE_REPORT_NAME.replace(".json", ".md")).exists()
    assert (report_dir / SEGMENTATION_REPORT_NAME.replace(".json", ".md")).exists()

    # present + valid report => tuning unlocks.
    assert first_diagnostics_report_present(reports_root)
    check_tuning_allowed("scorer_thresholds", reports_root=reports_root)

    # the harness must accommodate a second volume (vol_07 representativeness)
    # without disturbing the vol_01 embargo key.
    fd.run_first_diagnostics(
        oracle_page=_oracle_fixture_page(),
        oracle_gold=_ORACLE_GOLD,
        oracle_alignment=_ORACLE_ALIGNMENT,
        segmentation_page=_segmentation_fixture_page(),
        reports_root=reports_root,
        volume="vol_07",
    )
    assert (report_dir / "vol_07_oracle_accuracy.json").exists()
    assert (report_dir / "vol_07_segmentation_difference.json").exists()


# --------------------------------------------------------------------------- #
# Test 4 -- the alignment oracle dominates the candidate oracle by construction
# (gap >= 0). Every candidate in a slot is a real reading some engine produced, so
# perfect alignment can only help: alignment_oracle >= candidate_oracle always.
# A negative gap would silently flip an alignment-limited reading to
# diversity-limited (Codex review attack 1).
# --------------------------------------------------------------------------- #


def test_alignment_oracle_dominates_candidate():
    # a slot whose candidate exists but whose span carries no raw_text -- the
    # naive "alignment from raw_text only" reading would miss it and go negative.
    page = {
        "positions": [
            _position(
                "Q1",
                "body",
                "latin",
                [_candidate("e1", "truth")],
                [_span("tesseract", "e1", "exact")],  # no raw_text
            )
        ]
    }
    positions = fd.oracle_positions_from_wct(page, {"Q1": "truth"})
    report = fd.compute_oracle_accuracy(positions)

    assert report["candidate_oracle"] == pytest.approx(1.0)
    assert report["alignment_oracle"] >= report["candidate_oracle"]
    assert report["gap"] >= 0.0


# --------------------------------------------------------------------------- #
# Test 5 -- a vacuous measurement must NOT unlock tuning. If the gold join matches
# nothing (n=0) the harness must fail closed rather than write an all-zero report
# that satisfies the embargo's shape validator (Codex review attack 3).
# --------------------------------------------------------------------------- #


def test_vacuous_report_does_not_unlock_tuning(tmp_path):
    with pytest.raises(ValueError):
        fd.run_first_diagnostics(
            oracle_page=_oracle_fixture_page(),
            oracle_gold={},  # joins nothing -> zero evaluated positions
            segmentation_page=_segmentation_fixture_page(),
            reports_root=tmp_path,
            volume="vol_01",
        )
    # nothing was written, so the embargo stays closed.
    assert not first_diagnostics_report_present(tmp_path)
    with pytest.raises(TuningEmbargoError):
        check_tuning_allowed("scorer_thresholds", reports_root=tmp_path)


# --------------------------------------------------------------------------- #
# Fixture integrity -- the synthetic positions are genuine WCT instances.
# --------------------------------------------------------------------------- #


def test_fixture_positions_are_wct_shaped():
    schema = json.loads(
        (REPO_ROOT / "schemas" / "v1" / "word-confusion-table-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    position_schema = dict(schema["$defs"]["position"])
    position_schema["$defs"] = schema["$defs"]

    pages = [_oracle_fixture_page(), _segmentation_fixture_page()]
    positions = [pos for page in pages for pos in page["positions"]]
    assert positions
    for pos in positions:
        jsonschema.validate(pos, position_schema)
