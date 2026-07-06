"""TDD inventory for the arch B schema freeze (reconciled design section 8, T1-T28).

Real tests (run against the genuinely-new word-confusion-table-v1 file + its enums):
T1-T9, T23, T28, plus the WCT half of T7/T8 via the semantic validator.

xfail tests (exercise files NOT built in this q1=A pass: reconciled-v1,
typography-snapshot-v1, s2_engine_failure-v1, canonical-identity-map-v1):
T10-T17, T19-T22, T24-T27. They are written against the reconciled design so
they go straight to GREEN once the arch3 implementation pass lands those schemas.

T18 (decision-event-v1 axis lock) is now a LIVE test: decision-event-v1 landed
in batch B3. Full event_type coverage is in tests/test_decision_event_v1.py.

DEVIATION: the prompt classed T17 (s2_failure +2) as a "real" test, but
s2_engine_failure-v1 is not built this pass (q1=A forbids the full arch3 set),
so T17 is xfail here. Flagged in the freeze declaration and session report.

Enum constants are imported, never hardcoded (PIPE-26). Constant names were read
from the regenerated build/lib/_generated_enums.py, never asserted from memory
(TEST-12).
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import _generated_enums  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402
from build.lib.wct_semantic_validator import validate_page  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "wct" / "page_0010_church_history.json"
WCT_NAME = "word-confusion-table-v1"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _wct_schema() -> dict:
    return _schema(WCT_NAME)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _accepts(schema: dict, instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=schema)


def _rejects(schema: dict, instance: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


# --------------------------------------------------------------------------- #
# Real tests: word-confusion-table-v1 file + enums
# --------------------------------------------------------------------------- #


def test_t1_wct_envelope_validates_and_missing_positions_fails() -> None:
    schema = _wct_schema()
    _accepts(schema, _fixture())
    broken = _fixture()
    del broken["positions"]
    _rejects(schema, broken)


def test_t2_contract_preservation_no_field_or_literal_renames() -> None:
    schema = _wct_schema()
    # arch A literals are hyphenated; underscore aliases must fail (A1 - not amended).
    underscored_routing = _fixture()
    underscored_routing["positions"][0]["script"]["routing"] = "normal_latin"
    _rejects(schema, underscored_routing)

    underscored_zone = _fixture()
    underscored_zone["zones"][0]["zone_type"] = "running_header"
    _rejects(schema, underscored_zone)

    # arch A field name is volume_id, not volume (Claude's rename rejected).
    renamed_field = _fixture()
    renamed_field["volume"] = renamed_field.pop("volume_id")
    _rejects(schema, renamed_field)


def test_t3_zone_bibliography_validates_bogus_fails() -> None:
    schema = _wct_schema()
    biblio = _fixture()
    biblio["zones"][0]["zone_type"] = "bibliography"
    _accepts(schema, biblio)
    assert "bibliography" in _generated_enums.WORD_CONFUSION_TABLE_V1__DEFS__WCT_ZONE_TYPE

    bogus = _fixture()
    bogus["zones"][0]["zone_type"] = "footnotes"
    _rejects(schema, bogus)


def test_t4_skip_is_span_record_null_reading_candidate_fails() -> None:
    schema = _wct_schema()
    # The fixture already carries a skip span record with candidate_id null.
    _accepts(schema, _fixture())
    skip = next(
        sr
        for sr in _fixture()["positions"][0]["span_records"]
        if sr["token_span_type"] == "skip"
    )
    assert skip["candidate_id"] is None
    assert skip["source_spans"] == []

    # A null-reading candidate is illegal: candidate_set holds real readings only.
    null_candidate = _fixture()
    null_candidate["positions"][0]["candidate_set"][0]["raw_reading"] = None
    _rejects(schema, null_candidate)


def test_t5_one_alignment_confidence_per_position() -> None:
    schema = _wct_schema()
    # alignment_confidence belongs to the position, not the span record.
    per_span = _fixture()
    per_span["positions"][0]["span_records"][0]["alignment_confidence"] = 0.9
    _rejects(schema, per_span)


def test_t6_bbox_polygon_optional_in_source_spans() -> None:
    schema = _wct_schema()
    # Azure span carries an explicit polygon; the fixture validates with it.
    _accepts(schema, _fixture())
    azure_span = next(
        sr
        for sr in _fixture()["positions"][0]["span_records"]
        if sr["engine_id"] == "azure"
    )
    assert "bbox_polygon" in azure_span["source_spans"][0]

    # Removing the polygon (ABBYY/Tesseract case) is also valid.
    no_polygon = _fixture()
    for sr in no_polygon["positions"][0]["span_records"]:
        for span in sr["source_spans"]:
            span.pop("bbox_polygon", None)
    _accepts(schema, no_polygon)


def test_t7_segmentation_invariant_skip_with_1n_fails_semantic_check() -> None:
    # The clean fixture has no invariant violations.
    assert validate_page(_fixture()) == []

    # skip must pair with gap; skip + 1:n is a semantic violation.
    violating = _fixture()
    for sr in violating["positions"][0]["span_records"]:
        if sr["token_span_type"] == "skip":
            sr["segmentation_relation"] = "1:n"
    errors = validate_page(violating)
    assert len(errors) == 1
    assert "skip" in errors[0]


def test_t8_every_span_record_has_unique_span_record_id() -> None:
    schema = _wct_schema()
    span_records = _fixture()["positions"][0]["span_records"]
    ids = [sr["span_record_id"] for sr in span_records]
    assert all(ids)
    assert len(ids) == len(set(ids))  # resolves to exactly one

    missing = _fixture()
    del missing["positions"][0]["span_records"][0]["span_record_id"]
    _rejects(schema, missing)


def test_t9_source_image_object_validates_flat_string_fails() -> None:
    schema = _wct_schema()
    _accepts(schema, _fixture())  # source_image is {path, sha256}
    flat = _fixture()
    flat["source_image"] = "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg"
    _rejects(schema, flat)


def test_t23_engine_family_extended_set_unknown_fails() -> None:
    schema = _wct_schema()
    constant = _generated_enums.WORD_CONFUSION_TABLE_V1__DEFS__ENGINE_FAMILY
    # Generated constant and get_enum agree; do not hardcode the frozenset (PIPE-26).
    assert constant == get_enum(WCT_NAME, "available_engines", "family")
    assert {"surya", "kraken", "calamari"}.issubset(constant)

    for family in ("surya", "kraken", "calamari"):
        ok = _fixture()
        ok["available_engines"][0]["family"] = family
        _accepts(schema, ok)

    unknown = _fixture()
    unknown["available_engines"][0]["family"] = "paddleocr"
    _rejects(schema, unknown)


def test_t28_enum_freshness_and_new_enums_present() -> None:
    # (a) The live drift check passes after regeneration.
    result = subprocess.run(
        [sys.executable, "build/tools/check_schema_enums_fresh.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # (b) Every new WCT enum appears as a generated constant.
    expected_constants = [
        "WORD_CONFUSION_TABLE_V1__DEFS__WCT_ZONE_TYPE",
        "WORD_CONFUSION_TABLE_V1__DEFS__TOKEN_SPAN_TYPE",
        "WORD_CONFUSION_TABLE_V1__DEFS__SEGMENTATION_RELATION",
        "WORD_CONFUSION_TABLE_V1__DEFS__HYPHENATION_STATUS",
        "WORD_CONFUSION_TABLE_V1__DEFS__SCRIPT_LABEL",
        "WORD_CONFUSION_TABLE_V1__DEFS__SCRIPT_ROUTING",
        "WORD_CONFUSION_TABLE_V1__DEFS__NORMALISATION_OP",
        "WORD_CONFUSION_TABLE_V1__DEFS__CONF_AGG",
        "WORD_CONFUSION_TABLE_V1__DEFS__LAYOUT_TOOL",
        "WORD_CONFUSION_TABLE_V1__DEFS__ZONE_SOURCE",
        "WORD_CONFUSION_TABLE_V1__DEFS__ENGINE_FAMILY",
    ]
    for name in expected_constants:
        assert hasattr(_generated_enums, name), f"missing generated constant {name}"

    # (c) Editing a WCT enum without regenerating fails the freshness check.
    tmp_root = REPO_ROOT / "tests" / "_tmp_generated_enums" / "wct_drift"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)  # standards: log/temp rotation
    tmp_schemas = tmp_root / "schemas"
    shutil.copytree(SCHEMA_DIR, tmp_schemas)
    tmp_generated = tmp_root / "_generated_enums.py"
    subprocess.run(
        [sys.executable, "build/tools/generate_schema_enums.py",
         "--schemas-dir", str(tmp_schemas), "--output", str(tmp_generated)],
        cwd=REPO_ROOT, check=True,
    )
    fresh = subprocess.run(
        [sys.executable, "build/tools/check_schema_enums_fresh.py",
         "--schemas-dir", str(tmp_schemas), "--generated-path", str(tmp_generated)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert fresh.returncode == 0, "freshly generated copy should be clean"

    wct_copy = tmp_schemas / f"{WCT_NAME}.schema.json"
    edited = json.loads(wct_copy.read_text(encoding="utf-8"))
    edited["$defs"]["wct_zone_type"]["enum"].append("table")
    wct_copy.write_text(json.dumps(edited, indent=2), encoding="utf-8")
    stale = subprocess.run(
        [sys.executable, "build/tools/check_schema_enums_fresh.py",
         "--schemas-dir", str(tmp_schemas), "--generated-path", str(tmp_generated)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert stale.returncode != 0
    assert "stale" in stale.stdout.lower()
    shutil.rmtree(tmp_root)


# --------------------------------------------------------------------------- #
# xfail tests: files NOT built in this q1=A pass (arch3 implementation pass).
# Written against the reconciled design so they flip to GREEN when built.
# --------------------------------------------------------------------------- #

_ARCH3_PENDING = "arch3 impl pass not yet landed (q1=A: design-level only)"


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t10_attestation_token_span_type_replaces_engine_votes() -> None:
    schema = _schema("reconciled-v1")
    attestation = {
        "token_span_type": "exact",
        "segmentation_relation": "1:1",
        "source_spans": [{"observation_token_id": "obs1", "source_token_id": "t1",
                          "text": "word", "bbox_canonical": {"x": 0, "y": 0, "w": 1, "h": 1},
                          "line_id": "l1"}],
    }
    _accepts(schema, attestation)
    bad = {"engine_votes": True}
    _rejects(schema, bad)


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t11_attestation_raw_vs_normalized_required_for_non_skip() -> None:
    schema = _schema("reconciled-v1")
    missing = {"token_span_type": "exact"}  # no raw_ocr / normalized
    _rejects(schema, missing)


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t12_context_verifiable_scorer_gating() -> None:
    schema = _schema("reconciled-v1")
    att = {"context_verifiable": False, "context_verifiability_reason": "embedded_greek"}
    _accepts(schema, att)


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t13_calibrated_confidence_reserved_null() -> None:
    schema = _schema("reconciled-v1")
    _accepts(schema, {"calibrated_confidence": None})
    _rejects(schema, {"calibrated_confidence": "high"})


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t14_gh_output_status_four_values() -> None:
    schema = _schema("reconciled-v1")
    for value in ("recognised_from_page", "restored_from_reference",
                  "human_confirmed", "unresolved"):
        _accepts(schema, {"greek_hebrew_provenance": {"output_status": value}})
    _rejects(schema, {"greek_hebrew_provenance": {"output_status": "guessed"}})


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t15_gh_match_key_invariant() -> None:
    # normalized_match_key must never equal display/structured/diplomatic_corrected.
    from build.lib import gh_semantic_validator  # not built this pass
    assert gh_semantic_validator is not None


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t16_gh_restored_requires_candidate_sources() -> None:
    schema = _schema("reconciled-v1")
    bad = {"greek_hebrew_provenance": {"output_status": "restored_from_reference",
                                       "candidate_sources": []}}
    _rejects(schema, bad)


@pytest.mark.xfail(reason="s2_engine_failure-v1 not built this pass (q1=A); "
                          "prompt classed T17 real but the target schema is design-level")
def test_t17_s2_failure_class_plus_two() -> None:
    schema = _schema("s2_engine_failure-v1")
    for value in ("source_payload_corrupt", "provider_version_drift"):
        _accepts(schema, {"failure_class": value})
    _rejects(schema, {"failure_class": "seventh_value"})


def test_t18_decision_event_axis_lock() -> None:
    # decision-event-v1 landed in batch B3 (arch3 impl pass); this is now a live
    # test. The strict envelope requires more than the design-sketch fragment, so
    # the instances are full valid events. Comprehensive coverage of the reconciled
    # event_type enum lives in tests/test_decision_event_v1.py.
    schema = _schema("decision-event-v1")
    workflow = {
        "schema_version": "decision-event-v1",
        "event_id": "de-sha256:" + "0" * 64,
        "event_type": "typography_tier_correction",
        "event_category": "workflow_event",
        "volume": 1,
        "actor_id": "maintainer",
        "timestamp": "2026-05-29T00:00:00Z",
        "measurement_eligible": False,
        "prior_tier": "footnote",
        "new_tier": "body",
    }
    _accepts(schema, workflow)
    # Axis lock: the same workflow event on the authority axis must fail.
    authority = dict(workflow)
    authority["event_category"] = "authority_decision"
    _rejects(schema, authority)


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t19_typography_corrected_value_gate() -> None:
    schema = _schema("typography-snapshot-v1")
    bad = {"typography_correction_payload": {"corrected_value": "not_a_tier"}}
    _rejects(schema, bad)


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t20_typography_payload_envelope_split() -> None:
    schema = _schema("typography-snapshot-v1")
    assert "snapshot_payload_hash" in schema.get("properties", {})
    assert "lifecycle_registry_hash" in schema.get("properties", {})


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t21_typography_abstention_shape() -> None:
    schema = _schema("typography-snapshot-v1")
    _accepts(schema, {"relative_size_tier": None, "abstention": True,
                      "abstention_reason": "insufficient_engines"})
    _rejects(schema, {"relative_size_tier": None, "abstention": False})


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t22_typography_single_engine_admission() -> None:
    schema = _schema("typography-snapshot-v1")
    _accepts(schema, {"typography_evidence_single_engine": True,
                      "measurement_eligible": False})


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t24_reconciled_carries_wct_page_refs() -> None:
    schema = _schema("reconciled-v1")
    assert "wct_page_refs" in schema.get("properties", {})


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t25_item16_token_identity_per_volume() -> None:
    schema = _schema("reconciled-v1")
    seed_without_volume = {"edition_id": "ed1"}  # missing volume
    _rejects(schema, seed_without_volume)


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t26_item20_identity_map() -> None:
    schema = _schema("canonical-identity-map-v1")
    mapping = {"from_canonical_token_id": "a", "to_canonical_token_id": "b",
               "mapping_kind": "rebind", "legacy_block_ids": ["blk1"],
               "migration_precision": "page_only"}
    _accepts(schema, {"mappings": [mapping]})


@pytest.mark.xfail(reason=_ARCH3_PENDING)
def test_t27_item15_alias_guard() -> None:
    from build.tools import migrate_schaff_herzog  # migration with alias guard
    assert hasattr(migrate_schaff_herzog, "resolve_alias_or_fail")
