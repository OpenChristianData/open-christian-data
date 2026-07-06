"""B9 -- family-independence measurement -> family map + policy version (TEST-16).

Architectural slot: Wave-3 family-map readiness gate (arch D plan section 2, B9
row; lock section 3). B9 consumes B7's vol_01 gold + B8's diagnostics inputs and
produces the family-grouping map for the active engine set, measured (never
assumed) on the bake-off sample, recorded, and tied to a matrix-policy version.
The readiness flip is what later un-blocks B11's class-1 training.

These tests are the B9 TDD contract from the arch D plan -- written-failed-then-
satisfied, never authored after the implementation:

  1. same-wrong-string by pair  -- paired-disagreement / same-wrong-string /
                                   gold-accuracy measured correctly per engine pair
                                   on a fixture with a known answer; the five ABBYY
                                   lineages collapse to ONE family.
  2. readiness flip             -- family_map_readiness flips true ONLY when all
                                   lock-section-3 conjuncts hold (family_diversity_count
                                   >= 2 + independent check); a fixture missing a
                                   conjunct does not flip.
  3. < 2-family contingency     -- a fixture measuring one independent family produces
                                   the contingency branch (class-1 stays blocked,
                                   contingency recorded), never a silent readiness flip.

Independence is "measured on the vol_01 bake-off (same-wrong-string /
paired-disagreement / gold-accuracy), never assumed from different software" (lock
section 3). The fixtures are SYNTHETIC with known same-wrong-string overlaps -- the
real family verdict is phase 2 (real vol_01 bake-off + real diagnostics). The B9
deliverable is the measurement code + map writer + readiness-flip logic, provably
correct on fixtures.
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

from build.lib import family_independence as fi  # noqa: E402
from build.lib.class1_gate import evaluate_class1  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402

FAMILY_MAP_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "family-map-v1.schema.json"


# --------------------------------------------------------------------------- #
# Synthetic fixtures. Each position carries a gold reading (the independent
# check) and the per-engine reading at that position. Token strings are ASCII
# and illustrative; the measurement only compares reading strings.
# --------------------------------------------------------------------------- #

# Five ABBYY scan lineages -- one declared family -- plus two distinct engines.
FIVE_ABBYY_LINEAGES = (
    "abbyy-base",
    "abbyy-haucgoog",
    "abbyy-dli",
    "abbyy-haucgoog-c1",
    "abbyy-haucgoog-c2",
)
ABBYY_FAMILIES = {engine: "abbyy" for engine in FIVE_ABBYY_LINEAGES}
THREE_FAMILY_SET = {
    **ABBYY_FAMILIES,
    "tesseract": "tesseract",
    "surya": "surya",
}
# The pair fixture measures exactly these three engines (declare == measure).
PAIR_FAMILIES = {"tesseract": "tesseract", "abbyy": "abbyy", "surya": "surya"}


def _pos(gold, **engine_tokens):
    return fi.AlignedPosition(gold=gold, engine_tokens=dict(engine_tokens))


def _pair_fixture():
    """Three engines, four positions, with a known same-wrong-string answer.

    P1 all correct; P2 tess&abbyy share the SAME WRONG string 'graoe' (surya
    correct); P3 tess&surya share the same wrong 'lcrd' (abbyy correct); P4 abbyy
    alone wrong (no pair shares a wrong string).

    Denominator per pair = 4 (gold present, both engines present).
      same-wrong   tess__abbyy: P2                -> 1/4 = 0.25
      same-wrong   surya__tesseract: P3           -> 1/4 = 0.25
      same-wrong   abbyy__surya: none             -> 0/4 = 0.0
      disagreement tess__abbyy: P3,P4             -> 2/4 = 0.5
      disagreement surya__tesseract: P2 only      -> 1/4 = 0.25
      disagreement abbyy__surya: P2,P3,P4         -> 3/4 = 0.75
      gold-acc tesseract: P1,P4 -> 0.5; abbyy: P1,P3 -> 0.5; surya: P1,P2,P4 -> 0.75
    """
    return [
        _pos("faith", tesseract="faith", abbyy="faith", surya="faith"),
        _pos("grace", tesseract="graoe", abbyy="graoe", surya="grace"),
        _pos("lord", tesseract="lcrd", abbyy="lord", surya="lcrd"),
        _pos("amen", tesseract="amen", abbyy="arnen", surya="amen"),
    ]


# --------------------------------------------------------------------------- #
# Test 1 -- same-wrong-string by pair; five ABBYY lineages collapse to one family.
# --------------------------------------------------------------------------- #


def test_same_wrong_string_and_disagreement_by_pair():
    positions = _pair_fixture()

    same_wrong = fi.same_wrong_string_by_pair(positions)
    assert same_wrong["abbyy__tesseract"] == pytest.approx(0.25)
    assert same_wrong["surya__tesseract"] == pytest.approx(0.25)
    assert same_wrong["abbyy__surya"] == pytest.approx(0.0)

    disagreement = fi.paired_disagreement_by_pair(positions)
    assert disagreement["abbyy__tesseract"] == pytest.approx(0.5)
    assert disagreement["surya__tesseract"] == pytest.approx(0.25)
    assert disagreement["abbyy__surya"] == pytest.approx(0.75)

    gold_acc = fi.gold_accuracy_by_engine(positions)
    assert gold_acc["tesseract"] == pytest.approx(0.5)
    assert gold_acc["abbyy"] == pytest.approx(0.5)
    assert gold_acc["surya"] == pytest.approx(0.75)


def test_five_abbyy_lineages_collapse_to_one_family():
    # No cross-family dependence -> the only grouping is the declared-family
    # collapse. The five ABBYY scan lineages count as ONE family (lock section 3:
    # "the five ABBYY scans are one family"), tesseract and surya stay distinct.
    same_wrong = {}  # no measured cross-family dependence
    blocks = fi.group_families(
        THREE_FAMILY_SET, same_wrong, dependence_threshold=fi.DEFAULT_DEPENDENCE_THRESHOLD
    )

    assert len(blocks) == 3
    abbyy_block = next(b for b in blocks if "abbyy" in b["declared_families"])
    assert sorted(abbyy_block["engine_ids"]) == sorted(FIVE_ABBYY_LINEAGES)
    assert abbyy_block["declared_families"] == ["abbyy"]
    # diversity counts independence blocks, not nominal engines.
    assert fi.family_diversity_count(blocks) == 3


def test_measured_dependence_collapses_nominally_distinct_families():
    # "never assumed from different software": two declared-distinct engines whose
    # measured same-wrong-string clears the dependence threshold collapse into one
    # independence block, dropping the diversity count.
    same_wrong = {"surya__tesseract": fi.DEFAULT_DEPENDENCE_THRESHOLD + 0.1}
    blocks = fi.group_families(
        {"tesseract": "tesseract", "surya": "surya", "abbyy-base": "abbyy"},
        same_wrong,
        dependence_threshold=fi.DEFAULT_DEPENDENCE_THRESHOLD,
    )
    # tesseract+surya merge -> {tess,surya} and {abbyy} = 2 blocks (not 3).
    assert fi.family_diversity_count(blocks) == 2
    merged = next(b for b in blocks if b["merged_by_dependence"])
    assert sorted(merged["engine_ids"]) == ["surya", "tesseract"]


# --------------------------------------------------------------------------- #
# Test 2 -- readiness flip: true ONLY when every lock-section-3 conjunct holds.
# --------------------------------------------------------------------------- #


def test_readiness_flips_only_when_all_conjuncts_hold():
    # diversity >= 2 AND an independent check present -> flips true.
    assert fi.evaluate_readiness(family_diversity_count=2, independent_check_present=True) is True
    assert fi.evaluate_readiness(family_diversity_count=5, independent_check_present=True) is True
    # missing a conjunct -> does NOT flip.
    assert fi.evaluate_readiness(family_diversity_count=1, independent_check_present=True) is False
    assert fi.evaluate_readiness(family_diversity_count=2, independent_check_present=False) is False
    assert fi.evaluate_readiness(family_diversity_count=1, independent_check_present=False) is False


def test_family_map_flips_readiness_on_two_independent_families():
    family_map = fi.build_family_map(
        engine_families=PAIR_FAMILIES,
        positions=_pair_fixture(),
        policy_version="matrix-policy-v1",
        input_sample_id="vol_01-bakeoff",
        effective_date="2026-05-30",
    )
    assert family_map["family_diversity_count"] == 3
    assert family_map["independent_check_present"] is True
    assert family_map["family_map_readiness"] is True
    assert "contingency" not in family_map
    # carries policy version + input sample id + effective date (lock section 3).
    assert family_map["policy_version"] == "matrix-policy-v1"
    assert family_map["input_sample_id"] == "vol_01-bakeoff"
    assert family_map["effective_date"] == "2026-05-30"

    # the readiness flip is exactly what un-blocks class-1 (B11): a now-ready map
    # feeds the existing class-1 gate and a consensus+independent-check token passes.
    result = evaluate_class1(
        family_map_readiness=family_map["family_map_readiness"],
        family_diversity_count=family_map["family_diversity_count"],
        independent_check_present=True,
        event_type="choose_attestation",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is True


def test_no_independent_check_does_not_flip():
    # positions present but no gold anywhere -> independence cannot be anchored;
    # the readiness flag must stay false (missing the independent-check conjunct).
    positions = [
        _pos(None, tesseract="faith", abbyy="faith", surya="grace"),
        _pos(None, tesseract="lord", abbyy="word", surya="lord"),
    ]
    family_map = fi.build_family_map(
        engine_families=PAIR_FAMILIES,
        positions=positions,
        policy_version="matrix-policy-v1",
        input_sample_id="vol_01-bakeoff-nogold",
        effective_date="2026-05-30",
    )
    assert family_map["independent_check_present"] is False
    assert family_map["family_map_readiness"] is False


# --------------------------------------------------------------------------- #
# Test 3 -- < 2-family contingency: one family -> contingency, class-1 blocked,
# never a silent readiness flip.
# --------------------------------------------------------------------------- #


def test_single_family_triggers_contingency_never_flips():
    # Only ABBYY lineages present -> exactly one declared family -> one independence
    # block, even though gold anchors the measurement. Readiness must NOT flip.
    positions = [
        _pos("faith", **{lineage: "faith" for lineage in FIVE_ABBYY_LINEAGES}),
        _pos("grace", **{lineage: "graoe" for lineage in FIVE_ABBYY_LINEAGES}),
    ]
    family_map = fi.build_family_map(
        engine_families=ABBYY_FAMILIES,
        positions=positions,
        policy_version="matrix-policy-v1",
        input_sample_id="vol_01-bakeoff-abbyy-only",
        effective_date="2026-05-30",
    )

    assert family_map["family_diversity_count"] == 1
    # gold was present, but one family can never satisfy the >= 2 conjunct.
    assert family_map["independent_check_present"] is True
    assert family_map["family_map_readiness"] is False

    contingency = family_map["contingency"]
    assert contingency["class1_blocked"] is True
    # the recorded status + recommended action are schema-valid (not invented).
    assert contingency["status"] in get_enum("family-map-v1", "contingency", "status")
    assert contingency["recommended_action"] in get_enum(
        "family-map-v1", "contingency", "recommended_action"
    )

    # the gate stays closed for class-1 even on an otherwise-eligible token: the
    # contingency never relaxes the bar to keep flowing (lock section 3 / arch D section 4).
    result = evaluate_class1(
        family_map_readiness=family_map["family_map_readiness"],
        family_diversity_count=family_map["family_diversity_count"],
        independent_check_present=True,
        event_type="choose_attestation",
        is_dictionary_pass_only=False,
    )
    assert result.allowed is False
    assert result.weak_reason == "no_family_map_readiness"


def test_dependence_collapse_to_one_family_also_triggers_contingency():
    # Two declared families that measure as dependent collapse to one block -> the
    # contingency fires on the MEASURED count, not the nominal one.
    positions = [
        _pos("faith", tesseract="faith", surya="faith"),
        _pos("grace", tesseract="graoe", surya="graoe"),  # same wrong
        _pos("lord", tesseract="lcrd", surya="lcrd"),  # same wrong
        _pos("amen", tesseract="amer", surya="amer"),  # same wrong
    ]
    # tess__surya same-wrong = 3/4 = 0.75 >> threshold -> collapse to one family.
    family_map = fi.build_family_map(
        engine_families={"tesseract": "tesseract", "surya": "surya"},
        positions=positions,
        policy_version="matrix-policy-v1",
        input_sample_id="vol_01-bakeoff-correlated",
        effective_date="2026-05-30",
    )
    assert family_map["family_diversity_count"] == 1
    assert family_map["family_map_readiness"] is False
    assert family_map["contingency"]["class1_blocked"] is True


# --------------------------------------------------------------------------- #
# Recorded artifact -- the family map validates against family-map-v1 and the
# writer round-trips it. reports/ is gitignored, so the artifact is regenerable,
# never committed (same posture as B8 diagnostics).
# --------------------------------------------------------------------------- #


def _family_map_schema() -> dict:
    return json.loads(FAMILY_MAP_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_built_family_map_validates_against_schema():
    for engine_families, positions in (
        (PAIR_FAMILIES, _pair_fixture()),
        (ABBYY_FAMILIES, [_pos("faith", **{l: "faith" for l in FIVE_ABBYY_LINEAGES})]),
    ):
        family_map = fi.build_family_map(
            engine_families=engine_families,
            positions=positions,
            policy_version="matrix-policy-v1",
            input_sample_id="vol_01-bakeoff",
            effective_date="2026-05-30",
        )
        jsonschema.validate(family_map, _family_map_schema())


def test_writer_round_trips_and_fails_closed_on_empty(tmp_path):
    family_map = fi.build_family_map(
        engine_families=PAIR_FAMILIES,
        positions=_pair_fixture(),
        policy_version="matrix-policy-v1",
        input_sample_id="vol_01-bakeoff",
        effective_date="2026-05-30",
    )
    out_path = fi.write_family_map(tmp_path, family_map)
    assert out_path.exists()
    reloaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert reloaded["family_map_readiness"] is True
    jsonschema.validate(reloaded, _family_map_schema())

    # an empty engine set / no positions is a precondition error, never a written
    # "not ready" map that looks like a real measurement (REL-02 fail-closed).
    with pytest.raises(ValueError):
        fi.build_family_map(
            engine_families={},
            positions=[],
            policy_version="matrix-policy-v1",
            input_sample_id="empty",
            effective_date="2026-05-30",
        )


# --------------------------------------------------------------------------- #
# Codex B9 review regressions -- "measured, never assumed" and gate-integrity.
# --------------------------------------------------------------------------- #


def test_declared_but_unmeasured_engine_does_not_count_as_a_family():
    # Codex attack 5: declare two families but measure only one -> the unmeasured
    # family must NOT count toward diversity (it produced no evidence), readiness
    # must not flip, and the omission is recorded -- never silent.
    positions = [_pos("faith", **{"abbyy-base": "faith"})]
    family_map = fi.build_family_map(
        engine_families={"abbyy-base": "abbyy", "surya": "surya"},
        positions=positions,
        policy_version="matrix-policy-v1",
        input_sample_id="vol_01-bakeoff-partial",
        effective_date="2026-05-30",
    )
    assert family_map["engine_set"] == ["abbyy-base"]
    assert family_map["family_diversity_count"] == 1
    assert family_map["family_map_readiness"] is False
    assert family_map["unmeasured_declared_engines"] == ["surya"]
    assert family_map["contingency"]["class1_blocked"] is True


def test_measured_engine_without_declared_family_is_a_precondition_error():
    # a position references an engine with no declared family -> fail closed.
    with pytest.raises(ValueError):
        fi.build_family_map(
            engine_families={"tesseract": "tesseract"},
            positions=[_pos("faith", tesseract="faith", surya="faith")],
            policy_version="matrix-policy-v1",
            input_sample_id="vol_01-bakeoff-undeclared",
            effective_date="2026-05-30",
        )


def test_writer_rejects_a_contradictory_count_or_readiness(tmp_path):
    # Codex attack 1: the schema cannot assert count == len(family_groups); the
    # writer guard must reject a hand-built payload that flips readiness with a
    # contradictory count before it is ever persisted.
    base = fi.build_family_map(
        engine_families=PAIR_FAMILIES,
        positions=_pair_fixture(),
        policy_version="matrix-policy-v1",
        input_sample_id="vol_01-bakeoff",
        effective_date="2026-05-30",
    )
    contradictory = dict(base)
    contradictory["family_groups"] = base["family_groups"][:1]  # 1 block
    contradictory["family_diversity_count"] = 2  # lies about the count
    with pytest.raises(ValueError):
        fi.write_family_map(tmp_path, contradictory)

    forged = dict(base)
    forged["family_diversity_count"] = 1
    forged["family_groups"] = base["family_groups"][:1]
    forged["family_map_readiness"] = True  # one family can never be ready
    with pytest.raises(ValueError):
        fi.write_family_map(tmp_path, forged)


def test_writer_rejects_malformed_effective_date(tmp_path):
    # Codex attack 4: effective_date must be a real ISO date; empty / malformed
    # strings are rejected by the schema pattern (jsonschema format is annotation
    # only without a checker).
    for bad_date in ("", "not-a-date", "2026/05/30"):
        family_map = fi.build_family_map(
            engine_families=PAIR_FAMILIES,
            positions=_pair_fixture(),
            policy_version="matrix-policy-v1",
            input_sample_id="vol_01-bakeoff",
            effective_date=bad_date,
        )
        with pytest.raises(Exception):
            fi.write_family_map(tmp_path, family_map)
