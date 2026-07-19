import copy
import inspect
import json
import pickle
import subprocess
from pathlib import Path

import pytest
import cvw_phase1a
import cvw_phase1a.contracts as contracts_module
import cvw_phase1a.fixture as fixture_module

from cvw_phase1a import (
    ArtifactIdentity,
    BaselineCaptureProvenance,
    BoundBaseline,
    ContractError,
    CoverageClaim,
    DependencyManifest,
    ExpectedPopulationAuthority,
    IdentityGraph,
    OutputFrame,
    RenderingRuntimeFingerprint,
    RiskPolicyMatrix,
    ScopeSnapshot,
    SourceFrame,
    VerificationBundle,
    VerificationEvent,
    assess_writer_manifest,
    assess_writer_manifest_payload,
    accept_phase1a_rollup,
    build_phase1a_bundle,
    build_phase1a_report,
    derive_fidelity_decision,
    evaluate_rollup,
    evaluate_sampling_policy,
    load_fixture,
    map_evidence_to_review_state,
    semantic_sha256_for_text,
    validate_asv_authority_payload,
    validate_phase1a_identity_graph_payload,
    validate_spurgeon_authority_payload,
    verify_historical_bcp_probe,
)
from cvw_phase1a.contracts import (
    EVIDENCE_DEPTHS,
    EscalationPolicy,
    FINDING_DISPOSITIONS,
    LIMITATION_STATES,
    RELEASE_STATES,
    REQUIRED_DEPENDENCY_ROLES,
    REVIEW_STATE_CONFIDENCES,
    RiskPolicy,
)
from cvw_phase1a.fixture import raw_environment_preflight


REPO_ROOT = Path(__file__).resolve().parents[1]
WRITER_SOURCE_AUTHORITY = {
    "bible_text_translations_parser": ("build/parsers/bible_text_translations.py",),
}
MISSING_RAW_WITNESSES = raw_environment_preflight(REPO_ROOT)
requires_laptop_raw = pytest.mark.skipif(
    bool(MISSING_RAW_WITNESSES),
    reason=(
        "Phase 1A laptop raw witnesses are absent; this skip is a vacuous pass, not verification. "
        "The ordinary CLI remains the fail-closed surface and must report environment "
        "UNKNOWN/BLOCKED. Missing: "
        + ", ".join(MISSING_RAW_WITNESSES)
    ),
)


def test_raw_bound_skip_message_calls_skip_a_vacuous_pass() -> None:
    reason = requires_laptop_raw.mark.kwargs["reason"]
    assert "vacuous pass" in reason
    assert "CLI remains the fail-closed surface" in reason
    for missing_path in MISSING_RAW_WITNESSES:
        assert missing_path in reason


def _runtime() -> RenderingRuntimeFingerprint:
    return RenderingRuntimeFingerprint.create(
        ["inputs/runtime.bin"],
        {
            "browser_engine": "test",
            "browser_version": "1",
            "launch_flags": "none",
            "css_font_fingerprint": "test-fonts",
        },
    )


def _manifest(contents: dict[str, bytes] | None = None) -> DependencyManifest:
    values = contents or {
        role: f"{role}-v1".encode("utf-8") for role in REQUIRED_DEPENDENCY_ROLES
    }
    return DependencyManifest.from_contents(
        (role, f"inputs/{role}.bin", payload) for role, payload in values.items()
    )


def _provenance() -> BaselineCaptureProvenance:
    return BaselineCaptureProvenance(
        repository_head="a" * 40,
        external_review_path=(
            "plans/2026-07-17-cvw-phase1a-governing-prior-review.md"
        ),
        external_review_sha256=ArtifactIdentity.from_bytes(b"reviewer").raw_sha256,
    )


def _currentness_kwargs(baseline: BoundBaseline) -> dict[str, object]:
    return {
        "repository_head": baseline.capture_provenance.repository_head,
        "external_review_path": (
            "plans/2026-07-17-cvw-phase1a-governing-prior-review.md"
        ),
        "external_review_bytes": b"reviewer",
    }


def test_forged_baseline_cannot_omit_live_currentness_inputs() -> None:
    bundle = VerificationBundle.create(
        subject_grain="rendering",
        subject_id="fixture-rendering",
        dependency_manifest=_manifest(),
        policy_version="policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=_runtime(),
        artifact_ids=("artifact-1",),
    )
    forged = BoundBaseline.create(
        bundle,
        BaselineCaptureProvenance(
            repository_head="f" * 40,
            external_review_path=".tmp_audit/forged-review.txt",
            external_review_sha256=ArtifactIdentity.from_bytes(b"forged-review").raw_sha256,
        ),
    )

    with pytest.raises(TypeError):
        forged.stale_reasons(bundle)


def test_baseline_currentness_rejects_arbitrary_stored_review_path_with_real_review_bytes() -> None:
    bundle = _event_bundle()
    governing_path = "plans/2026-07-17-cvw-phase1a-governing-prior-review.md"
    governing_bytes = (REPO_ROOT / governing_path).read_bytes()
    provenance = BaselineCaptureProvenance(
        repository_head="b" * 40,
        external_review_path="cvw_phase1a/fixtures/phase1a_fixture.json",
        external_review_sha256=ArtifactIdentity.from_bytes(governing_bytes).raw_sha256,
    )
    baseline = BoundBaseline.create(bundle, provenance)

    with pytest.raises(ContractError, match="designated governing external-review path"):
        baseline.stale_reasons(
        bundle,
        repository_head="b" * 40,
        external_review_path=governing_path,
            external_review_bytes=governing_bytes,
        )


def _event_bundle() -> VerificationBundle:
    fixture = load_fixture()
    actual_paths = (
        fixture["spurgeon"]["expected_population_authority_path"],
        "raw/spurgeon_sermons/html/1.html",
        "ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml",
        "cvw_phase1a/fixtures/phase1a_fixture.json",
    )
    items = [
        (role, f"inputs/{role}.bin", f"{role}-v1".encode("utf-8"))
        for role in REQUIRED_DEPENDENCY_ROLES
    ]
    authority_path = fixture["spurgeon"]["expected_population_authority_path"]
    items.extend(
        (
            "authority" if path == authority_path else "fixture",
            path,
            (REPO_ROOT / path).read_bytes() if path == authority_path else path.encode("utf-8"),
        )
        for path in actual_paths
    )
    return VerificationBundle.create(
        subject_grain="phase1a_fixture",
        subject_id="event-tests",
        dependency_manifest=DependencyManifest.from_contents(items),
        policy_version="policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=_runtime(),
        artifact_ids=("event-fixture",),
    )


def _graph() -> IdentityGraph:
    return IdentityGraph.from_payload(load_fixture()["identity_graph"])


def test_three_spurgeon_members_cannot_roll_up_to_collection() -> None:
    claim = CoverageClaim(
        subject_id="spurgeon-mtp:proof-wave",
        subject_grain="rendering",
        scope_grain="collection_member",
        numerator=3,
        denominator=3547,
        authority_id="spurgeon-census",
        authority_sha256="a" * 64,
        rollup_rule="complete-only",
        allowed_rollup_grains=("collection",),
    )

    decision = evaluate_rollup(
        claim,
        "collection",
        target_subject_id="spurgeon-mtp:collection",
        graph=_graph(),
    )

    assert decision.allowed is False
    assert decision.status == "forbidden"
    assert "identity graph forbids" in decision.reason


def test_rollup_rejects_subject_scope_grain_mismatch() -> None:
    claim = CoverageClaim(
        subject_id="asv:scrollmapper-json",
        subject_grain="rendering",
        scope_grain="canonical_record",
        numerator=1,
        denominator=1,
        authority_id="asv-canonical-record-authority",
        authority_sha256="a" * 64,
        rollup_rule="complete-only",
    )

    decision = evaluate_rollup(
        claim,
        "work",
        target_subject_id="asv",
        graph=_graph(),
    )

    assert decision.allowed is False
    assert decision.status == "forbidden"
    assert "subject grain" in decision.reason


def test_rollup_requires_explicit_target_identity_and_authoritative_relationship() -> None:
    caller_graph = IdentityGraph.from_payload(
        {
            "nodes": [
                {
                    "grain": "work",
                    "subject_id": "caller-work",
                    "authority": "caller/work.json",
                },
                {
                    "grain": "rendering",
                    "subject_id": "caller-rendering",
                    "authority": "caller/rendering.json",
                    "parent_grain": "work",
                    "parent_id": "caller-work",
                },
            ],
            "allowed_rollups": [
                {
                    "from_grain": "rendering",
                    "to_grain": "work",
                    "rule": "complete-only",
                }
            ],
        }
    )
    claim = CoverageClaim(
        subject_id="caller-rendering",
        subject_grain="rendering",
        scope_grain="rendering",
        numerator=1,
        denominator=1,
        authority_id="caller-rendering-authority",
        authority_sha256="a" * 64,
        rollup_rule="complete-only",
    )

    with pytest.raises(ContractError, match="explicit target subject"):
        evaluate_rollup(claim, "work", graph=caller_graph)
    with pytest.raises(ContractError, match="target subject"):
        evaluate_rollup(
            claim,
            "work",
            target_subject_id="unrelated-work",
            graph=caller_graph,
        )
    structural = evaluate_rollup(
        claim,
        "work",
        target_subject_id="caller-work",
        graph=caller_graph,
    )
    assert structural.structural_allowed is True
    assert structural.allowed is False
    assert structural.trust_state == "untrusted-structural"


@pytest.mark.requires_local_artifacts
def test_complete_repository_record_rollup_requires_and_uses_target_identity() -> None:
    graph = IdentityGraph.from_payload(
        {
            "nodes": [
                {
                    "grain": "work",
                    "subject_id": "asv",
                    "authority": "cvw_phase1a/fixtures/work_catalog_identity.json#asv",
                },
                {
                    "grain": "canonical_record",
                    "subject_id": "asv:record-1",
                    "authority": "data/bible-text/asv/genesis.json#record-1",
                    "parent_grain": "work",
                    "parent_id": "asv",
                },
            ],
            "allowed_rollups": [
                {
                    "from_grain": "canonical_record",
                    "to_grain": "work",
                    "rule": "complete-only",
                }
            ],
        }
    )
    claim = CoverageClaim(
        subject_id="asv:record-1",
        subject_grain="canonical_record",
        scope_grain="canonical_record",
        numerator=1,
        denominator=1,
        authority_id="asv-record-authority",
        authority_sha256="a" * 64,
        rollup_rule="complete-only",
    )

    decision = evaluate_rollup(
        claim,
        "work",
        target_subject_id="asv",
        graph=graph,
    )

    assert decision.structural_allowed is True
    assert decision.allowed is False
    assert decision.trust_state == "untrusted-structural"

    repository_authority_path = "data/bible-text/asv/genesis.json"
    repository_authority_sha256 = ArtifactIdentity.from_path(
        REPO_ROOT / repository_authority_path
    ).raw_sha256
    repository_bundle = build_phase1a_bundle(REPO_ROOT)
    assert repository_bundle.dependency_manifest.has_exact_dependency(
        "bounded-artifact",
        repository_authority_path,
        repository_authority_sha256,
    )
    repository_claim = CoverageClaim(
        subject_id="asv:genesis-1-1",
        subject_grain="canonical_record",
        scope_grain="canonical_record",
        numerator=1,
        denominator=1,
        authority_id="data/bible-text/asv/genesis.json#Gen.1.1",
        authority_sha256=repository_authority_sha256,
        rollup_rule="complete-only",
    )
    accepted = accept_phase1a_rollup(
        repository_claim,
        "work",
        target_subject_id="asv",
        repo_root=REPO_ROOT,
    )
    assert accepted.allowed is True
    assert accepted.accepted is True
    assert accepted.trust_state == "repository-accepted"


@pytest.mark.requires_local_artifacts
def test_repository_rollup_rejects_graph_consistent_claim_with_arbitrary_authority() -> None:
    hostile_claim = CoverageClaim(
        subject_id="asv:genesis-1-1",
        subject_grain="canonical_record",
        scope_grain="canonical_record",
        numerator=1,
        denominator=1,
        authority_id="caller-controlled-authority",
        authority_sha256="a" * 64,
        rollup_rule="complete-only",
    )

    with pytest.raises(ContractError, match="repository-owned roll-up authority"):
        accept_phase1a_rollup(
            hostile_claim,
            "work",
            target_subject_id="asv",
            repo_root=REPO_ROOT,
        )


def test_expected_population_authority_rejects_contradictory_count_and_ids() -> None:
    with pytest.raises(ContractError, match="count.*IDs"):
        ExpectedPopulationAuthority.known(
            "forged",
            "cvw_phase1a/fixtures/phase1a_fixture.json",
            "a" * 64,
            expected_count=3547,
            expected_ids=(
                "spurgeon-mtp:sermon-1",
                "spurgeon-mtp:sermon-15",
                "spurgeon-mtp:sermon-317",
            ),
        )

    for path in ("../outside.json", str((REPO_ROOT / "outside.json").resolve())):
        with pytest.raises(ContractError, match="repository-relative"):
            ExpectedPopulationAuthority.known("bad-path", path, "a" * 64, expected_count=1)


def test_graph_conflicting_claim_and_unknown_identity_fail_closed() -> None:
    claim = CoverageClaim(
        subject_id="spurgeon-mtp:proof-wave",
        subject_grain="rendering",
        scope_grain="collection_member",
        numerator=3,
        denominator=3,
        authority_id="spurgeon-census",
        authority_sha256="a" * 64,
        rollup_rule="complete-only",
        allowed_rollup_grains=("collection",),
    )
    assert evaluate_rollup(
        claim,
        "collection",
        target_subject_id="spurgeon-mtp:collection",
        graph=_graph(),
    ).allowed is False
    unknown = copy.copy(claim)
    unknown = CoverageClaim(
        subject_id="not-in-graph",
        subject_grain="rendering",
        scope_grain=unknown.scope_grain,
        numerator=unknown.numerator,
        denominator=unknown.denominator,
        authority_id=unknown.authority_id,
        authority_sha256=unknown.authority_sha256,
        rollup_rule=unknown.rollup_rule,
    )
    with pytest.raises(ContractError):
        evaluate_rollup(
            unknown,
            "collection",
            target_subject_id="spurgeon-mtp:collection",
            graph=_graph(),
        )


def test_identity_graph_rejects_conflicting_rollups_bad_parents_and_scope_mutation() -> None:
    fixture_graph = copy.deepcopy(load_fixture()["identity_graph"])
    conflicting = copy.deepcopy(fixture_graph)
    conflicting["allowed_rollups"].append(
        {"from_grain": "collection_member", "to_grain": "collection", "rule": "complete-only"}
    )
    with pytest.raises(ContractError, match="duplicate or conflicting"):
        IdentityGraph.from_payload(conflicting)

    bad_parent = copy.deepcopy(fixture_graph)
    bad_parent["nodes"][1]["parent_grain"] = "collection"
    with pytest.raises(ContractError, match="invalid identity parent grain"):
        IdentityGraph.from_payload(bad_parent)

    moved_scope = copy.deepcopy(fixture_graph)
    moved_scope["nodes"][1]["subject_id"] = "kjv:not-authorized"
    with pytest.raises(ContractError, match="exact authorized"):
        validate_phase1a_identity_graph_payload(moved_scope)

    moved_path = copy.deepcopy(fixture_graph)
    moved_path["nodes"][8]["authority"] = "ir/census/book-of-common-prayer.bcp-1662.census.json"
    with pytest.raises(ContractError, match="exact authorized"):
        validate_phase1a_identity_graph_payload(moved_path)


@requires_laptop_raw
def test_authority_derived_asv_population_and_adversarial_mutations() -> None:
    fixture = load_fixture()
    authority = json.loads(
        (REPO_ROOT / fixture["asv"]["expected_population_authority_path"]).read_text(
            encoding="utf-8"
        )
    )
    source_ids, verse_count, errors = validate_asv_authority_payload(authority, fixture["asv"])
    assert len(source_ids) == 66
    assert verse_count == 31102
    assert errors == ()

    wrong_mapping = copy.deepcopy(fixture["asv"])
    wrong_mapping["expected_members"][0]["id"] = "not-a-book"
    assert validate_asv_authority_payload(authority, wrong_mapping)[2]

    wrong_count = copy.deepcopy(fixture["asv"])
    wrong_count["expected_verse_count"] = verse_count - 1
    assert validate_asv_authority_payload(authority, wrong_count)[2]

    with pytest.raises(ContractError):
        validate_asv_authority_payload({"books": [{"name": "unknown"}]}, fixture["asv"])


@requires_laptop_raw
def test_spurgeon_authority_selection_count_and_hashes_are_bound() -> None:
    fixture = load_fixture()
    payload = json.loads(
        (REPO_ROOT / fixture["spurgeon"]["expected_population_authority_path"]).read_text(
            encoding="utf-8"
        )
    )
    valid = validate_spurgeon_authority_payload(payload, fixture["spurgeon"], REPO_ROOT)
    assert valid.valid is True
    assert valid.family_count == 3547
    assert valid.selected_members == (1, 15, 317)

    wrong_selection = copy.deepcopy(payload)
    wrong_selection["source"]["scope"]["selected_sermons"] = [1, 15, 318]
    assert not validate_spurgeon_authority_payload(
        wrong_selection, fixture["spurgeon"], REPO_ROOT
    ).valid

    wrong_count = copy.deepcopy(payload)
    wrong_count["source"]["file_count"] = 3546
    assert not validate_spurgeon_authority_payload(wrong_count, fixture["spurgeon"], REPO_ROOT).valid

    wrong_hash = copy.deepcopy(payload)
    wrong_hash["source"]["files"][0]["sha256"] = "0" * 64
    assert not validate_spurgeon_authority_payload(wrong_hash, fixture["spurgeon"], REPO_ROOT).valid
    wrong_fixture_hash = copy.deepcopy(fixture["spurgeon"])
    wrong_fixture_hash["selected_raw_files"][0]["sha256"] = "0" * 64
    assert not validate_spurgeon_authority_payload(
        payload, wrong_fixture_hash, REPO_ROOT
    ).valid

    malformed = {"source": {"scope": {"selected_sermons": [1]}}}
    assert not validate_spurgeon_authority_payload(malformed, fixture["spurgeon"], REPO_ROOT).valid


def test_spurgeon_full_family_membership_rejects_missing_extra_duplicate_and_nonnumeric() -> None:
    from cvw_phase1a.fixture import validate_spurgeon_family_membership

    exact = tuple(f"{member_id}.html" for member_id in range(1, 3548))
    assert validate_spurgeon_family_membership(
        exact, expected_count=3547, expected_member_names=exact
    ).errors == ()
    hostile = {
        "missing": exact[:-1],
        "extra": exact + ("3548.html",),
        "duplicate": exact + ("1.html",),
        "nonnumeric": exact[:-1] + ("appendix.html",),
        "same-count-missing-extra": exact[1:] + ("9999.html",),
    }
    for names in hostile.values():
        assert validate_spurgeon_family_membership(
            names,
            expected_count=3547,
            expected_member_names=exact,
        ).errors


@requires_laptop_raw
def test_spurgeon_membership_uses_frozen_hash_bound_exact_authority() -> None:
    fixture = load_fixture()
    spurgeon = fixture["spurgeon"]
    authority_path = spurgeon["membership_authority_path"]
    authority = json.loads((REPO_ROOT / authority_path).read_text(encoding="utf-8"))
    expected_names = tuple(
        f"{member_id}.html"
        for start, end in authority["expected_ranges"]
        for member_id in range(start, end + 1)
    )
    assert len(expected_names) == 3547
    source_authority = json.loads(
        (REPO_ROOT / spurgeon["expected_population_authority_path"]).read_text(
            encoding="utf-8"
        )
    )
    valid = validate_spurgeon_authority_payload(
        source_authority,
        spurgeon,
        REPO_ROOT,
        family_member_names=expected_names,
    )
    assert valid.valid is True

    missing_plus_extra = ("99999.html", *expected_names[1:])
    substituted = validate_spurgeon_authority_payload(
        source_authority,
        spurgeon,
        REPO_ROOT,
        family_member_names=missing_plus_extra,
    )
    assert substituted.valid is False
    assert any("authoritative" in error for error in substituted.errors)


def test_invalid_historical_manifest_satisfies_no_gate() -> None:
    assessment = assess_writer_manifest(
        REPO_ROOT / "review/writer-manifests/bible-text-asv-2026-07-06.json",
        REPO_ROOT / "schemas/v1/writer_manifest.schema.json",
        repo_root=REPO_ROOT,
    )

    assert assessment.valid is False
    assert assessment.trust_state == "legacy-untrusted"
    assert assessment.satisfies_verification_gate is False
    assert assessment.satisfies_release_gate is False


def _valid_writer_payload(data_path: str, after_sha256: str | None) -> dict:
    writer_path = REPO_ROOT / "build/parsers/bible_text_translations.py"
    return {
        "schema_version": "1.0.0",
        "writer": "parser",
        "writer_version": (
            "build/parsers/bible_text_translations.py@sha256:"
            f"{ArtifactIdentity.from_path(writer_path).raw_sha256}"
        ),
        "writer_identity": "bible_text_translations_parser",
        "run_id": "test-run",
        "started_at": "2026-07-17T00:00:00+00:00",
        "data_paths": [data_path],
        "checksums": {
            data_path: {"before_sha256": None, "after_sha256": after_sha256}
        },
        "expected_delta_counts": {data_path: {"entries_changed": 1, "fields_changed": 1}},
        "allowed_field_paths": ["/data/*"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }


def test_semantically_valid_writer_manifest_is_accounting_only() -> None:
    data_path = "data/bible-text/asv/genesis.json"
    payload = _valid_writer_payload(
        data_path,
        ArtifactIdentity.from_path(REPO_ROOT / data_path).raw_sha256,
    )
    schema = json.loads((REPO_ROOT / "schemas/v1/writer_manifest.schema.json").read_text(encoding="utf-8"))
    missing_mapping = assess_writer_manifest_payload(payload, schema, repo_root=REPO_ROOT)
    assessment = assess_writer_manifest_payload(
        payload,
        schema,
        repo_root=REPO_ROOT,
        writer_source_authority=WRITER_SOURCE_AUTHORITY,
    )

    assert missing_mapping.valid is False
    assert missing_mapping.satisfies_verification_gate is False
    assert assessment.valid is True
    assert assessment.trust_state == "trusted-accounting-only"
    assert assessment.satisfies_verification_gate is True
    assert assessment.satisfies_release_gate is False


def test_semantically_valid_deleted_file_manifest_is_accounting_only() -> None:
    data_path = "data/bible-text/asv/deleted-fixture.json"
    payload = _valid_writer_payload(data_path, None)
    payload["checksums"][data_path]["before_sha256"] = "a" * 64
    payload["expected_delta_counts"][data_path]["fields_changed"] = 0
    schema = json.loads(
        (REPO_ROOT / "schemas/v1/writer_manifest.schema.json").read_text(encoding="utf-8")
    )

    assessment = assess_writer_manifest_payload(
        payload,
        schema,
        repo_root=REPO_ROOT,
        writer_source_authority=WRITER_SOURCE_AUTHORITY,
    )

    assert assessment.valid is True
    assert assessment.trust_state == "trusted-accounting-only"
    assert assessment.satisfies_verification_gate is True
    assert assessment.satisfies_release_gate is False


def test_writer_identity_must_match_explicit_bounded_source_authority() -> None:
    data_path = "data/bible-text/asv/genesis.json"
    payload = _valid_writer_payload(
        data_path,
        ArtifactIdentity.from_path(REPO_ROOT / data_path).raw_sha256,
    )
    wrong_source = "build/parsers/bsb_bible_text.py"
    payload["writer_version"] = (
        f"{wrong_source}@sha256:{ArtifactIdentity.from_path(REPO_ROOT / wrong_source).raw_sha256}"
    )
    schema = json.loads(
        (REPO_ROOT / "schemas/v1/writer_manifest.schema.json").read_text(encoding="utf-8")
    )
    assessment = assess_writer_manifest_payload(
        payload,
        schema,
        repo_root=REPO_ROOT,
        writer_source_authority=WRITER_SOURCE_AUTHORITY,
    )
    assert assessment.valid is False
    assert assessment.satisfies_verification_gate is False
    assert any("authorized producer source" in error for error in assessment.errors)


@pytest.mark.parametrize(
    "mutation", ["writer_identity", "producer_hash", "data_paths", "checksum", "date", "delta"]
)
def test_semantically_invalid_writer_manifest_satisfies_no_gate(
    mutation: str,
) -> None:
    data_path = "data/bible-text/asv/genesis.json"
    payload = _valid_writer_payload(
        data_path,
        ArtifactIdentity.from_path(REPO_ROOT / data_path).raw_sha256,
    )
    if mutation == "writer_identity":
        payload["writer_identity"] = "unregistered-writer"
    elif mutation == "producer_hash":
        payload["writer_version"] = "build/parsers/bible_text_translations.py@v1.0.0"
    elif mutation == "data_paths":
        payload["data_paths"] = ["../outside.json"]
    elif mutation == "checksum":
        payload["checksums"] = {"data/other.json": payload["checksums"][data_path]}
    elif mutation == "delta":
        payload["expected_delta_counts"][data_path]["entries_changed"] = 0
    else:
        payload["started_at"] = "2026-07-17T00:00:00"
    schema = json.loads((REPO_ROOT / "schemas/v1/writer_manifest.schema.json").read_text(encoding="utf-8"))
    assessment = assess_writer_manifest_payload(
        payload,
        schema,
        repo_root=REPO_ROOT,
        writer_source_authority=WRITER_SOURCE_AUTHORITY,
    )

    assert assessment.valid is False
    assert assessment.trust_state == "legacy-untrusted"
    assert assessment.satisfies_verification_gate is False
    assert assessment.satisfies_release_gate is False


@pytest.mark.parametrize("target_exists", [True, False])
def test_writer_manifest_bogus_rename_satisfies_no_gate(target_exists: bool) -> None:
    data_path = "data/bible-text/asv/genesis.json"
    after = ArtifactIdentity.from_path(REPO_ROOT / data_path).raw_sha256
    payload = _valid_writer_payload(data_path, after)
    target = data_path if target_exists else "data/bible-text/asv/does-not-exist.json"
    payload["renames"] = [
        {
            "from_path": "data/bible-text/asv/invented-old-name.json",
            "to_path": target,
            "before_sha256": "0" * 64,
            "after_sha256": after,
        }
    ]
    schema = json.loads(
        (REPO_ROOT / "schemas/v1/writer_manifest.schema.json").read_text(encoding="utf-8")
    )
    assessment = assess_writer_manifest_payload(
        payload,
        schema,
        repo_root=REPO_ROOT,
        writer_source_authority=WRITER_SOURCE_AUTHORITY,
    )
    assert assessment.valid is False
    assert assessment.satisfies_verification_gate is False
    assert assessment.satisfies_release_gate is False
    assert any("rename" in error for error in assessment.errors)


def test_each_dependency_role_invalidates_bound_baseline() -> None:
    bundle = VerificationBundle.create(
        subject_grain="rendering",
        subject_id="fixture-rendering",
        dependency_manifest=_manifest(),
        policy_version="policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=_runtime(),
        artifact_ids=("artifact-1",),
    )
    baseline = BoundBaseline.create(bundle, _provenance())

    assert baseline.stale_reasons(bundle, **_currentness_kwargs(baseline)) == ()
    for role in REQUIRED_DEPENDENCY_ROLES:
        current = VerificationBundle.create(
            subject_grain=bundle.subject_grain,
            subject_id=bundle.subject_id,
            dependency_manifest=bundle.dependency_manifest.with_mutated_role(role),
            policy_version=bundle.policy_version,
            sample_algorithm_version=bundle.sample_algorithm_version,
            runtime_fingerprint=bundle.runtime_fingerprint,
            artifact_ids=bundle.artifact_ids,
        )
        reasons = baseline.stale_reasons(current, **_currentness_kwargs(baseline))
        assert any(reason.startswith(f"dependency:{role}:") for reason in reasons)

    changed_runtime = _runtime()
    changed_runtime = RenderingRuntimeFingerprint.create(
        changed_runtime.content_addressed_inputs,
        {
            "browser_engine": "different",
            "browser_version": "1",
            "launch_flags": "none",
            "css_font_fingerprint": "test-fonts",
        },
    )
    current = VerificationBundle.create(
        subject_grain=bundle.subject_grain,
        subject_id=bundle.subject_id,
        dependency_manifest=bundle.dependency_manifest,
        policy_version="policy-v2",
        sample_algorithm_version="sample-v2",
        runtime_fingerprint=changed_runtime,
        artifact_ids=bundle.artifact_ids,
    )
    reasons = baseline.stale_reasons(current, **_currentness_kwargs(baseline))
    assert "policy-version-changed" in reasons
    assert "sample-algorithm-version-changed" in reasons
    assert "render-runtime-fact-changed:browser_engine" in reasons


def test_artifactless_and_manifest_version_only_baselines_are_not_current() -> None:
    artifactless = VerificationBundle.create(
        subject_grain="rendering",
        subject_id="fixture-rendering",
        dependency_manifest=_manifest(),
        policy_version="policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=_runtime(),
    )
    with pytest.raises(ContractError, match="artifact"):
        BoundBaseline.create(artifactless, _provenance())

    bound_bundle = VerificationBundle.create(
        subject_grain="rendering",
        subject_id="fixture-rendering",
        dependency_manifest=_manifest(),
        policy_version="policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=_runtime(),
        artifact_ids=("artifact-1",),
    )
    baseline = BoundBaseline.create(bound_bundle, _provenance())
    version_only = VerificationBundle.create(
        subject_grain=bound_bundle.subject_grain,
        subject_id=bound_bundle.subject_id,
        dependency_manifest=DependencyManifest(
            bound_bundle.dependency_manifest.dependencies,
            manifest_version="2",
        ),
        policy_version=bound_bundle.policy_version,
        sample_algorithm_version=bound_bundle.sample_algorithm_version,
        runtime_fingerprint=bound_bundle.runtime_fingerprint,
        artifact_ids=bound_bundle.artifact_ids,
    )
    assert "dependency-manifest-version-changed" in baseline.stale_reasons(
        version_only, **_currentness_kwargs(baseline)
    )
    changed_artifacts = VerificationBundle.create(
        subject_grain=bound_bundle.subject_grain,
        subject_id=bound_bundle.subject_id,
        dependency_manifest=bound_bundle.dependency_manifest,
        policy_version=bound_bundle.policy_version,
        sample_algorithm_version=bound_bundle.sample_algorithm_version,
        runtime_fingerprint=bound_bundle.runtime_fingerprint,
        artifact_ids=("artifact-2",),
    )
    assert "bundle-artifacts-changed" in baseline.stale_reasons(
        changed_artifacts, **_currentness_kwargs(baseline)
    )


def test_baseline_path_and_runtime_inputs_are_repository_contained() -> None:
    with pytest.raises(ContractError):
        DependencyManifest.from_contents([("source", "../outside.bin", b"bad")])
    with pytest.raises(ContractError):
        RenderingRuntimeFingerprint.create(
            ["../outside.html"],
            {
                "browser_engine": "test",
                "browser_version": "1",
                "launch_flags": "none",
                "css_font_fingerprint": "fonts",
            },
        )


def test_baseline_consumption_revalidates_provenance_and_self_integrity() -> None:
    source, output, source_authority, output_authority = _sampling_population(("first",))
    bundle = _sampling_bundle(
        source_authority,
        output_authority,
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    baseline = BoundBaseline.create(bundle, _provenance())
    object.__setattr__(baseline.capture_provenance, "external_review_sha256", "0" * 64)
    with pytest.raises(ContractError, match="content hash"):
        baseline.stale_reasons(bundle, **_currentness_kwargs(baseline))

    baseline = BoundBaseline.create(bundle, _provenance())
    object.__setattr__(baseline, "content_sha256", "0" * 64)
    with pytest.raises(ContractError, match="content hash"):
        baseline.stale_reasons(bundle, **_currentness_kwargs(baseline))

    baseline = BoundBaseline.create(bundle, _provenance())
    reasons = baseline.stale_reasons(
        bundle,
        repository_head="c" * 40,
        external_review_path=(
            "plans/2026-07-17-cvw-phase1a-governing-prior-review.md"
        ),
        external_review_bytes=b"changed-review",
    )
    assert "baseline-capture-repository-head-changed" not in reasons
    assert "baseline-external-review-anchor-changed" in reasons


def test_observed_repository_head_change_is_informational_only_when_bound_inputs_match() -> None:
    bundle = VerificationBundle.create(
        subject_grain="rendering",
        subject_id="fixture-rendering",
        dependency_manifest=_manifest(),
        policy_version="policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=_runtime(),
        artifact_ids=("artifact-1",),
    )
    baseline = BoundBaseline.create(bundle, _provenance())

    reasons = baseline.stale_reasons(
        bundle,
        repository_head="b" * 40,
        external_review_path=(
            "plans/2026-07-17-cvw-phase1a-governing-prior-review.md"
        ),
        external_review_bytes=b"reviewer",
    )

    assert reasons == ()


@requires_laptop_raw
def test_bundle_capture_rejects_a_mixed_read_window_without_mutating_repository() -> None:
    fixture = load_fixture()
    first_path = fixture["dependencies"][0][1]
    candidate = REPO_ROOT / first_path
    original = candidate.read_bytes()
    state = {"calls": 0}

    def read_bytes(path: Path) -> bytes:
        if path == candidate:
            state["calls"] += 1
            if state["calls"] == 2:
                return original + b"controlled-test-drift"
        return path.read_bytes()

    with pytest.raises(ContractError, match="changed during snapshot read"):
        fixture_module.build_phase1a_bundle(REPO_ROOT, read_bytes=read_bytes)
    assert candidate.read_bytes() == original
    assert state["calls"] >= 2


@requires_laptop_raw
def test_bundle_capture_rechecks_already_read_dependency_after_later_read() -> None:
    fixture = load_fixture()
    first_path = REPO_ROOT / fixture["dependencies"][0][1]
    later_path = next(
        REPO_ROOT / item[1]
        for item in fixture["dependencies"]
        if item[1] != fixture["dependencies"][0][1]
    )
    original = first_path.read_bytes()
    state = {"later_read": False}

    def read_bytes(path: Path) -> bytes:
        if path == later_path:
            state["later_read"] = True
        if path == first_path and state["later_read"]:
            return original + b"controlled-whole-snapshot-drift"
        return path.read_bytes()

    with pytest.raises(ContractError, match="whole dependency snapshot changed"):
        fixture_module.build_phase1a_bundle(REPO_ROOT, read_bytes=read_bytes)
    assert first_path.read_bytes() == original
    assert state["later_read"] is True


@pytest.mark.requires_local_artifacts
def test_historical_bcp_evidence_recomputes_from_real_git_blobs() -> None:
    fixture = load_fixture()
    payload = json.loads(
        (
            REPO_ROOT
            / fixture["bcp"]["historical_contrary_evidence"]["evidence_path"]
        ).read_text(encoding="utf-8")
    )
    evidence = verify_historical_bcp_probe(REPO_ROOT, payload)
    assert evidence.valid is True
    assert evidence.historical_ledger_claim == "PASS"
    assert evidence.checker_probe_blob_identities_verified is True
    assert evidence.independent_probe_recomputed is True
    assert (evidence.expected_count, evidence.evaluated_count) == (332, 321)
    assert (evidence.absent_count, evidence.present_count, evidence.skipped_empty_count) == (
        287,
        34,
        11,
    )
    assert len(evidence.referenced_hashes) == 6

    wrong_count = copy.deepcopy(payload)
    wrong_count["expected_results"]["probe_absent_labels"] = 286
    assert not verify_historical_bcp_probe(REPO_ROOT, wrong_count).valid
    wrong_blob = copy.deepcopy(payload)
    wrong_blob["inputs"][3]["raw_sha256"] = "0" * 64
    assert not verify_historical_bcp_probe(REPO_ROOT, wrong_blob).valid
    wrong_oid = copy.deepcopy(payload)
    wrong_oid["inputs"][4]["git_blob_oid"] = "0" * 40
    assert not verify_historical_bcp_probe(REPO_ROOT, wrong_oid).valid
    wrong_algorithm = copy.deepcopy(payload)
    wrong_algorithm["algorithm"]["version"] = "invented"
    assert not verify_historical_bcp_probe(REPO_ROOT, wrong_algorithm).valid


@pytest.mark.requires_local_artifacts
def test_historical_bcp_tracker_evidence_is_frozen_and_not_live_bound() -> None:
    fixture = load_fixture()
    evidence = fixture["bcp"]["historical_contrary_evidence"]
    snapshot_path = evidence["tracker_snapshot_path"]
    snapshot_identity = ArtifactIdentity.from_path(REPO_ROOT / snapshot_path)
    assert snapshot_identity.raw_sha256 == evidence["tracker_snapshot_sha256"]

    snapshot = json.loads((REPO_ROOT / snapshot_path).read_text(encoding="utf-8"))
    assert snapshot["snapshot_version"] == "cvw-bcp-tracker-snapshot-v1"
    assert snapshot["subject_id"] == "bcp-1549"
    assert snapshot["source_path"] == "docs/DATASET_SUCCESSOR_QUEUE.md"
    assert len(snapshot["source_raw_sha256_at_capture"]) == 64
    assert snapshot["captured_at"].endswith(("+00:00", "+10:00", "+11:00"))
    assert "### Make `check_ledger` prove projected text delivery" in snapshot["excerpt"]
    assert "287 of 332" in snapshot["excerpt"]

    dependencies = {
        (dependency.role, dependency.path)
        for dependency in build_phase1a_bundle(REPO_ROOT).dependency_manifest.dependencies
    }
    assert ("historical-evidence", snapshot_path) in dependencies
    assert ("historical-evidence", "docs/DATASET_SUCCESSOR_QUEUE.md") not in dependencies


def test_baseline_provenance_tracks_latest_independent_verdict() -> None:
    baseline_payload = json.loads(
        (REPO_ROOT / "cvw_phase1a/fixtures/phase1a_baseline.json").read_text(encoding="utf-8")
    )
    provenance = baseline_payload["capture_provenance"]
    review_path = (
        "plans/2026-07-17-cvw-phase1a-governing-prior-review.md"
    )
    assert provenance["external_review_path"] == review_path
    assert provenance["external_review_sha256"] == ArtifactIdentity.from_path(
        REPO_ROOT / review_path
    ).raw_sha256


def test_raw_line_endings_change_exact_identity_but_not_explicit_semantic_digest() -> None:
    lf = b"one\ntwo\n"
    crlf = b"one\r\ntwo\r\n"
    semantic = semantic_sha256_for_text(lf)
    lf_identity = ArtifactIdentity.from_bytes(lf, semantic_digest=semantic)
    crlf_identity = ArtifactIdentity.from_bytes(crlf, semantic_digest=semantic_sha256_for_text(crlf))
    assert lf_identity.raw_sha256 != crlf_identity.raw_sha256
    assert lf_identity.semantic_sha256 == crlf_identity.semantic_sha256


def test_events_require_graph_identity_actor_timestamp_anchor_and_evidence() -> None:
    graph = _graph()
    bundle = _event_bundle()
    member_event = VerificationEvent.create(
        subject_grain="collection_member",
        subject_id="spurgeon-mtp:sermon-1",
        bundle=bundle,
        dimension="text-fidelity",
        severity="high",
        disposition="open",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="raw/spurgeon_sermons/html/1.html#body",
        evidence_refs=("ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml",),
        timestamp="2026-07-17T00:00:00+00:00",
    )
    authority = ExpectedPopulationAuthority.known(
        "spurgeon-mtp-family-census-v1",
        "ir/census/spurgeon-mtp.proof-wave.census.json",
        ArtifactIdentity.from_path(
            REPO_ROOT / "ir/census/spurgeon-mtp.proof-wave.census.json"
        ).raw_sha256,
        expected_count=3547,
    )
    scope = ScopeSnapshot.create(
        "spurgeon-mtp:collection",
        "collection",
        "collection_member",
        [
            "spurgeon-mtp:sermon-1",
            "spurgeon-mtp:sermon-15",
            "spurgeon-mtp:sermon-317",
        ],
        authority,
    )
    aggregate_event = VerificationEvent.create(
        subject_grain="collection",
        subject_id="spurgeon-mtp:collection",
        bundle=bundle,
        dimension="completeness",
        severity="high",
        disposition="limited",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="ir/census/spurgeon-mtp.proof-wave.census.json#source.scope",
        evidence_refs=("ir/census/spurgeon-mtp.proof-wave.census.json",),
        scope_snapshot=scope,
        expected_population_authority=authority,
        timestamp="2026-07-17T00:00:00+00:00",
    )
    assert member_event.actor_id == "reviewer-1"
    assert aggregate_event.scope_snapshot is not None
    assert aggregate_event.disposition == "limited"
    forged_three = ExpectedPopulationAuthority.known(
        "spurgeon-mtp-family-census-v1",
        authority.authority_path or "",
        authority.authority_sha256 or "",
        expected_ids=scope.member_ids,
    )
    forged_three_scope = ScopeSnapshot.create(
        "spurgeon-mtp:collection",
        "collection",
        "collection_member",
        scope.member_ids,
        forged_three,
    )
    with pytest.raises(ContractError, match="Phase 1A forbids aggregate accepted/closed"):
        VerificationEvent.create(
            subject_grain="collection",
            subject_id="spurgeon-mtp:collection",
            bundle=bundle,
            dimension="completeness",
            severity="high",
            disposition="closed",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="ir/census/spurgeon-mtp.proof-wave.census.json#source.scope",
            evidence_refs=("ir/census/spurgeon-mtp.proof-wave.census.json",),
            scope_snapshot=forged_three_scope,
            expected_population_authority=forged_three,
            timestamp="2026-07-17T00:00:00+00:00",
        )

    with pytest.raises(ContractError, match="aggregate closure"):
        VerificationEvent.create(
            subject_grain="collection",
            subject_id="spurgeon-mtp:collection",
            bundle=bundle,
            dimension="completeness",
            severity="high",
            disposition="closed",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="ir/census/spurgeon-mtp.proof-wave.census.json#scope",
            evidence_refs=("ir/census/spurgeon-mtp.proof-wave.census.json",),
            scope_snapshot=scope,
            expected_population_authority=authority,
            timestamp="2026-07-17T00:00:00+00:00",
        )
    arbitrary_authority = ExpectedPopulationAuthority.known(
        "invented",
        "cvw_phase1a/fixtures/phase1a_fixture.json",
        ArtifactIdentity.from_path(
            REPO_ROOT / "cvw_phase1a/fixtures/phase1a_fixture.json"
        ).raw_sha256,
        expected_count=3,
    )
    arbitrary_scope = ScopeSnapshot.create(
        "spurgeon-mtp:collection",
        "collection",
        "collection_member",
        scope.member_ids,
        arbitrary_authority,
    )
    with pytest.raises(ContractError, match="expected authority"):
        VerificationEvent.create(
            subject_grain="collection",
            subject_id="spurgeon-mtp:collection",
            bundle=bundle,
            dimension="completeness",
            severity="high",
            disposition="limited",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="cvw_phase1a/fixtures/phase1a_fixture.json",
            evidence_refs=("cvw_phase1a/fixtures/phase1a_fixture.json",),
            scope_snapshot=arbitrary_scope,
            expected_population_authority=authority,
            timestamp="2026-07-17T00:00:00+00:00",
        )
    with pytest.raises(ContractError):
        VerificationEvent.create(
            subject_grain="collection_member",
            subject_id="unknown-member",
            bundle=bundle,
            dimension="text-fidelity",
            severity="high",
            disposition="open",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="raw/spurgeon_sermons/html/1.html",
            evidence_refs=("ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml",),
            timestamp="2026-07-17T00:00:00",
        )
    with pytest.raises(ContractError):
        VerificationEvent.create(
            subject_grain="collection_member",
            subject_id="spurgeon-mtp:sermon-1",
            bundle=bundle,
            dimension="text-fidelity",
            severity="high",
            disposition="open",
            actor_id="",
            identity_graph=graph,
            anchor="raw/spurgeon_sermons/html/1.html",
            evidence_refs=(),
            timestamp="2026-07-17T00:00:00+00:00",
        )


@pytest.mark.parametrize("disposition", ("accepted", "closed"))
def test_direct_event_constructor_and_serialized_kwargs_cannot_close_aggregate(
    disposition: str,
) -> None:
    payload = {
        "subject_grain": "collection",
        "subject_id": "forged:collection",
        "bundle_hash": "a" * 64,
        "dimension": "completeness",
        "severity": "high",
        "disposition": disposition,
        "actor_id": "reviewer",
        "timestamp": "2026-07-17T00:00:00+00:00",
        "anchor": "cvw_phase1a/fixtures/phase1a_fixture.json",
        "evidence_refs": ("cvw_phase1a/fixtures/phase1a_fixture.json",),
    }

    with pytest.raises(ContractError, match="VerificationEvent.create"):
        VerificationEvent(**payload)
    serialized = json.loads(json.dumps(payload))
    with pytest.raises(ContractError, match="VerificationEvent.create"):
        VerificationEvent(**serialized)


@pytest.mark.parametrize("grain", ("collection ", "work\t", "release\n", "unknown"))
def test_event_rejects_noncanonical_and_unknown_grains_in_constructor_and_create(
    grain: str,
) -> None:
    payload = {
        "subject_grain": grain,
        "subject_id": "spurgeon-mtp:collection",
        "bundle_hash": "a" * 64,
        "dimension": "completeness",
        "severity": "high",
        "disposition": "open",
        "actor_id": "reviewer",
        "timestamp": "2026-07-17T00:00:00+00:00",
        "anchor": "cvw_phase1a/fixtures/phase1a_fixture.json",
        "evidence_refs": ("cvw_phase1a/fixtures/phase1a_fixture.json",),
    }
    with pytest.raises(ContractError, match="VerificationEvent.create"):
        VerificationEvent(**payload)
    with pytest.raises(ContractError, match="canonical known subject grain"):
        VerificationEvent.create(
            subject_grain=grain,
            subject_id="spurgeon-mtp:collection",
            bundle=_event_bundle(),
            dimension="completeness",
            severity="high",
            disposition="open",
            actor_id="reviewer",
            identity_graph=_graph(),
            anchor="cvw_phase1a/fixtures/phase1a_fixture.json",
            evidence_refs=("cvw_phase1a/fixtures/phase1a_fixture.json",),
            timestamp="2026-07-17T00:00:00+00:00",
        )


def test_direct_event_constructor_is_never_a_trust_bearing_boundary() -> None:
    common = {
        "bundle_hash": "a" * 64,
        "dimension": "completeness",
        "severity": "high",
        "actor_id": "reviewer",
        "timestamp": "2026-07-17T00:00:00+00:00",
        "anchor": "cvw_phase1a/fixtures/phase1a_fixture.json",
        "evidence_refs": ("cvw_phase1a/fixtures/phase1a_fixture.json",),
    }
    for payload in (
        {
            "subject_grain": "collection_member",
            "subject_id": "made-up-member",
            "disposition": "accepted",
            **common,
        },
        {
            "subject_grain": "collection",
            "subject_id": "made-up-collection",
            "disposition": "blocked",
            **common,
        },
    ):
        with pytest.raises(ContractError, match="VerificationEvent.create"):
            VerificationEvent(**payload)

    member = VerificationEvent.create(
        subject_grain="collection_member",
        subject_id="spurgeon-mtp:sermon-1",
        bundle=_event_bundle(),
        dimension="completeness",
        severity="high",
        disposition="closed",
        actor_id="reviewer",
        identity_graph=_graph(),
        anchor="cvw_phase1a/fixtures/phase1a_fixture.json",
        evidence_refs=("cvw_phase1a/fixtures/phase1a_fixture.json",),
        timestamp="2026-07-17T00:00:00+00:00",
    )
    assert member.disposition == "closed"


@pytest.mark.parametrize("disposition", ("accepted", "closed"))
def test_fabricated_complete_graph_and_fake_authority_cannot_close_aggregate(
    disposition: str,
) -> None:
    fake_bytes = b'{"members":["fake:1","fake:2","fake:3"]}'
    fake_path = "cvw_phase1a/fixtures/fake-authority.json"
    fake_sha256 = ArtifactIdentity.from_bytes(fake_bytes).raw_sha256
    items = [
        (role, f"inputs/{role}.bin", f"{role}-v1".encode("utf-8"))
        for role in REQUIRED_DEPENDENCY_ROLES
    ]
    items.append(("authority", fake_path, fake_bytes))
    bundle = VerificationBundle.create(
        subject_grain="phase1a_fixture",
        subject_id="fabricated-aggregate",
        dependency_manifest=DependencyManifest.from_contents(items),
        policy_version="policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=RenderingRuntimeFingerprint.create(
            ["inputs/runtime.bin"],
            {
                "browser_engine": "test",
                "browser_version": "1",
                "launch_flags": "none",
                "css_font_fingerprint": "test-fonts",
            },
        ),
        artifact_ids=("fake",),
    )
    graph = IdentityGraph.from_payload(
        {
            "nodes": [
                {"grain": "collection", "subject_id": "fake", "authority": fake_path},
                *[
                    {
                        "grain": "collection_member",
                        "subject_id": member_id,
                        "authority": fake_path,
                        "parent_grain": "collection",
                        "parent_id": "fake",
                    }
                    for member_id in ("fake:1", "fake:2", "fake:3")
                ],
            ],
            "allowed_rollups": [
                {
                    "from_grain": "collection_member",
                    "to_grain": "collection",
                    "rule": "complete-only",
                }
            ],
        }
    )
    authority = ExpectedPopulationAuthority.known(
        "fake-authority",
        fake_path,
        fake_sha256,
        expected_ids=("fake:1", "fake:2", "fake:3"),
    )
    scope = ScopeSnapshot.create(
        "fake",
        "collection",
        "collection_member",
        authority.expected_ids or (),
        authority,
    )
    with pytest.raises(ContractError, match="Phase 1A forbids aggregate accepted/closed"):
        VerificationEvent.create(
            subject_grain="collection",
            subject_id="fake",
            bundle=bundle,
            dimension="completeness",
            severity="high",
            disposition=disposition,
            actor_id="reviewer",
            identity_graph=graph,
            anchor=fake_path,
            evidence_refs=(fake_path,),
            scope_snapshot=scope,
            expected_population_authority=authority,
            timestamp="2026-07-17T00:00:00+00:00",
        )


@requires_laptop_raw
def test_spurgeon_census_and_full_membership_are_exact_bundle_dependencies() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    fixture = load_fixture()
    census_path = fixture["spurgeon"]["expected_population_authority_path"]
    census_sha256 = ArtifactIdentity.from_path(REPO_ROOT / census_path).raw_sha256
    assert bundle.dependency_manifest.has_exact_dependency(
        "authority", census_path, census_sha256
    )
    membership = next(
        dependency
        for dependency in bundle.dependency_manifest.dependencies
        if dependency.path == fixture["spurgeon"]["membership_authority_path"]
    )
    assert membership.role == "authority"
    assert membership.identity.raw_sha256 == (
        fixture["spurgeon"]["membership_authority_sha256"]
    )
    assert not hasattr(cvw_phase1a, "verify_spurgeon_expected_population_authority")


@requires_laptop_raw
def test_caller_created_full_spurgeon_graph_cannot_close_with_real_population() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    loader = getattr(cvw_phase1a, "verify_spurgeon_expected_population_authority", None)
    verified = loader(REPO_ROOT, bundle) if loader is not None else None
    authority_path = load_fixture()["spurgeon"]["expected_population_authority_path"]
    authority_sha256 = ArtifactIdentity.from_path(REPO_ROOT / authority_path).raw_sha256
    expected_ids = (
        verified.expected_ids
        if verified is not None
        else tuple(
            sorted(
                (
                    f"spurgeon-mtp:sermon-{path.stem}"
                    for path in (REPO_ROOT / "raw/spurgeon_sermons/html").glob("*.html")
                )
            )
        )
    )
    authority = ExpectedPopulationAuthority.known(
        "spurgeon-mtp-family-census-v1",
        authority_path,
        authority_sha256,
        expected_count=len(expected_ids),
    )
    graph = IdentityGraph.from_payload(
        {
            "nodes": [
                {
                    "grain": "collection",
                    "subject_id": "spurgeon-mtp:collection",
                    "authority": authority_path,
                },
                *[
                    {
                        "grain": "collection_member",
                        "subject_id": member_id,
                        "authority": authority_path,
                        "parent_grain": "collection",
                        "parent_id": "spurgeon-mtp:collection",
                    }
                    for member_id in expected_ids
                ],
            ],
            "allowed_rollups": [
                {
                    "from_grain": "collection_member",
                    "to_grain": "collection",
                    "rule": "complete-only",
                }
            ],
        }
    )
    scope = ScopeSnapshot.create(
        "spurgeon-mtp:collection",
        "collection",
        "collection_member",
        expected_ids,
        authority,
    )

    with pytest.raises(ContractError, match="Phase 1A forbids aggregate accepted/closed"):
        VerificationEvent.create(
            subject_grain="collection",
            subject_id="spurgeon-mtp:collection",
            bundle=bundle,
            dimension="completeness",
            severity="high",
            disposition="closed",
            actor_id="reviewer",
            identity_graph=graph,
            anchor=f"{authority_path}#source.scope",
            evidence_refs=(authority_path,),
            scope_snapshot=scope,
            expected_population_authority=authority,
            timestamp="2026-07-17T00:00:00+00:00",
        )


def test_contract_module_exposes_no_forgeable_verification_seals_or_factories() -> None:
    forbidden_names = {
        "VerifiedAuthorityBytes",
        "VerifiedExpectedPopulationAuthority",
        "_VERIFIED_AUTHORITY_BYTES_SEAL",
        "_VERIFIED_POPULATION_SEAL",
        "_make_verified_expected_population_authority",
    }
    assert forbidden_names.isdisjoint(vars(contracts_module))
    assert not hasattr(cvw_phase1a, "VerifiedAuthorityBytes")
    assert not hasattr(cvw_phase1a, "VerifiedExpectedPopulationAuthority")


def test_events_reject_tampered_scope_snapshot_and_unsafe_references() -> None:
    graph = _graph()
    bundle = _event_bundle()
    authority = ExpectedPopulationAuthority.known(
        "spurgeon-mtp-family-census-v1",
        "ir/census/spurgeon-mtp.proof-wave.census.json",
        ArtifactIdentity.from_path(
            REPO_ROOT / "ir/census/spurgeon-mtp.proof-wave.census.json"
        ).raw_sha256,
        expected_count=3547,
    )
    scope = ScopeSnapshot.create(
        "spurgeon-mtp:collection",
        "collection",
        "collection_member",
        (
            "spurgeon-mtp:sermon-1",
            "spurgeon-mtp:sermon-15",
            "spurgeon-mtp:sermon-317",
        ),
        authority,
    )
    tampered = copy.copy(scope)
    object.__setattr__(tampered, "snapshot_sha256", "0" * 64)
    with pytest.raises(ContractError, match="snapshot hash"):
        VerificationEvent.create(
            subject_grain="collection",
            subject_id="spurgeon-mtp:collection",
            bundle=bundle,
            dimension="completeness",
            severity="high",
            disposition="limited",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="ir/census/spurgeon-mtp.proof-wave.census.json#source.scope",
            evidence_refs=("ir/census/spurgeon-mtp.proof-wave.census.json",),
            scope_snapshot=tampered,
            expected_population_authority=authority,
            timestamp="2026-07-17T00:00:00+00:00",
        )

    for anchor, refs in (
        ("../outside#x", ("ir/census/spurgeon-mtp.proof-wave.census.json",)),
        (str((REPO_ROOT / "outside").resolve()), ("ir/census/spurgeon-mtp.proof-wave.census.json",)),
        ("ir/census/spurgeon-mtp.proof-wave.census.json", ("../outside",)),
    ):
        with pytest.raises(ContractError, match="repository-relative"):
            VerificationEvent.create(
                subject_grain="collection_member",
                subject_id="spurgeon-mtp:sermon-1",
                bundle=bundle,
                dimension="text-fidelity",
                severity="high",
                disposition="open",
                actor_id="reviewer-1",
                identity_graph=graph,
                anchor=anchor,
                evidence_refs=refs,
                timestamp="2026-07-17T00:00:00+00:00",
            )
    with pytest.raises(ContractError, match="not a bundle dependency"):
        VerificationEvent.create(
            subject_grain="collection_member",
            subject_id="spurgeon-mtp:sermon-1",
            bundle=bundle,
            dimension="text-fidelity",
            severity="high",
            disposition="open",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="docs/WORK_CATALOG.md",
            evidence_refs=("ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml",),
            timestamp="2026-07-17T00:00:00+00:00",
        )
    with pytest.raises(ContractError):
        VerificationEvent.create(
            subject_grain="collection",
            subject_id="spurgeon-mtp:collection",
            bundle=bundle,
            dimension="text-fidelity",
            severity="high",
            disposition="open",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="ir/census/spurgeon-mtp.proof-wave.census.json",
            evidence_refs=("ir/census/spurgeon-mtp.proof-wave.census.json",),
            scope_snapshot=scope,
            timestamp="2026-07-17T00:00:00+00:00",
        )


@pytest.mark.requires_local_artifacts
def test_events_are_untrusted_until_repository_context_accepts_them() -> None:
    event = VerificationEvent.create(
        subject_grain="collection_member",
        subject_id="spurgeon-mtp:sermon-1",
        bundle=_event_bundle(),
        dimension="text-fidelity",
        severity="high",
        disposition="closed",
        actor_id="attacker-controlled",
        identity_graph=_graph(),
        anchor="raw/spurgeon_sermons/html/1.html",
        evidence_refs=("ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml",),
        timestamp="2026-07-17T00:00:00+00:00",
    )

    with pytest.raises(ContractError, match="repository-owned"):
        fixture_module.accept_phase1a_event(event, REPO_ROOT)


@requires_laptop_raw
def test_repository_context_accepts_only_current_bound_member_event() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    graph = validate_phase1a_identity_graph_payload(load_fixture()["identity_graph"])
    event = VerificationEvent.create(
        subject_grain="collection_member",
        subject_id="spurgeon-mtp:sermon-1",
        bundle=bundle,
        dimension="text-fidelity",
        severity="high",
        disposition="closed",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="raw/spurgeon_sermons/html/1.html",
        evidence_refs=("ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml",),
        timestamp="2026-07-17T00:00:00+00:00",
    )

    accepted = fixture_module.accept_phase1a_event(event, REPO_ROOT)

    assert accepted is event
    copied = copy.copy(event)
    assert fixture_module.accept_phase1a_event(copied, REPO_ROOT) is copied
    round_tripped = pickle.loads(pickle.dumps(event))
    assert fixture_module.accept_phase1a_event(round_tripped, REPO_ROOT) is round_tripped

    class HostileEvent(VerificationEvent):
        pass

    forged = object.__new__(HostileEvent)
    for field in (
        "subject_grain",
        "subject_id",
        "bundle_hash",
        "dimension",
        "severity",
        "disposition",
        "actor_id",
        "timestamp",
        "anchor",
        "evidence_refs",
        "scope_snapshot",
        "expected_population_authority",
        "notes",
    ):
        object.__setattr__(forged, field, getattr(event, field))
    with pytest.raises(ContractError, match="exact VerificationEvent"):
        fixture_module.accept_phase1a_event(forged, REPO_ROOT)


@requires_laptop_raw
def test_repository_event_acceptance_binds_member_evidence_to_subject_ownership() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    graph = validate_phase1a_identity_graph_payload(load_fixture()["identity_graph"])

    unrelated_evidence = (
        "raw/bible_databases/formats/json/ASV.json",
        "docs/WORK_CATALOG.md",
    )
    for evidence_path in unrelated_evidence:
        event = VerificationEvent.create(
            subject_grain="collection_member",
            subject_id="spurgeon-mtp:sermon-1",
            bundle=bundle,
            dimension="text-fidelity",
            severity="high",
            disposition="open",
            actor_id="reviewer-1",
            identity_graph=graph,
            anchor="raw/spurgeon_sermons/html/1.html",
            evidence_refs=(evidence_path,),
            timestamp="2026-07-17T00:00:00+00:00",
        )
        with pytest.raises(ContractError, match="subject-owned|subject.*evidence"):
            fixture_module.accept_phase1a_event(event, REPO_ROOT)


@requires_laptop_raw
def test_repository_event_acceptance_rejects_a_different_member_witness() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    graph = validate_phase1a_identity_graph_payload(load_fixture()["identity_graph"])
    event = VerificationEvent.create(
        subject_grain="collection_member",
        subject_id="spurgeon-mtp:sermon-1",
        bundle=bundle,
        dimension="text-fidelity",
        severity="high",
        disposition="open",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="raw/spurgeon_sermons/html/15.html",
        evidence_refs=("ir/spurgeon/spurgeon-mtp.proof-wave.tei.xml",),
        timestamp="2026-07-17T00:00:00+00:00",
    )

    with pytest.raises(ContractError, match="graph-owned subject artifact"):
        fixture_module.accept_phase1a_event(event, REPO_ROOT)


@requires_laptop_raw
def test_repository_event_acceptance_rejects_own_anchor_plus_other_member_witness() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    graph = validate_phase1a_identity_graph_payload(load_fixture()["identity_graph"])
    event = VerificationEvent.create(
        subject_grain="collection_member",
        subject_id="spurgeon-mtp:sermon-1",
        bundle=bundle,
        dimension="text-fidelity",
        severity="high",
        disposition="open",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="raw/spurgeon_sermons/html/1.html",
        evidence_refs=("raw/spurgeon_sermons/html/15.html",),
        timestamp="2026-07-17T00:00:00+00:00",
    )

    with pytest.raises(ContractError, match="exact subject lineage"):
        fixture_module.accept_phase1a_event(event, REPO_ROOT)


@requires_laptop_raw
def test_repository_event_acceptance_rejects_canonical_record_sibling_evidence() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    graph = validate_phase1a_identity_graph_payload(load_fixture()["identity_graph"])
    event = VerificationEvent.create(
        subject_grain="canonical_record",
        subject_id="asv:genesis-1-1",
        bundle=bundle,
        dimension="text-fidelity",
        severity="high",
        disposition="accepted",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="data/bible-text/asv/exodus.json",
        evidence_refs=("data/bible-text/asv/exodus.json",),
        timestamp="2026-07-17T00:00:00+00:00",
    )

    with pytest.raises(ContractError, match="graph-owned subject artifact"):
        fixture_module.accept_phase1a_event(event, REPO_ROOT)


@requires_laptop_raw
def test_repository_event_acceptance_accepts_exact_canonical_record_evidence() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    graph = validate_phase1a_identity_graph_payload(load_fixture()["identity_graph"])
    event = VerificationEvent.create(
        subject_grain="canonical_record",
        subject_id="asv:genesis-1-1",
        bundle=bundle,
        dimension="text-fidelity",
        severity="high",
        disposition="accepted",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="data/bible-text/asv/genesis.json#Gen.1.1",
        evidence_refs=("data/bible-text/asv/genesis.json",),
        timestamp="2026-07-17T00:00:00+00:00",
    )

    assert fixture_module.accept_phase1a_event(event, REPO_ROOT) is event


@requires_laptop_raw
def test_repository_event_acceptance_rejects_real_census_with_forged_three_member_population() -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    graph = validate_phase1a_identity_graph_payload(load_fixture()["identity_graph"])
    census = next(
        dependency
        for dependency in bundle.dependency_manifest.dependencies
        if dependency.role == "authority"
        and dependency.path == "ir/census/spurgeon-mtp.proof-wave.census.json"
    )
    forged_authority = ExpectedPopulationAuthority.known(
        "forged-three-member-population",
        census.path,
        census.identity.raw_sha256,
        expected_count=3,
    )
    forged_scope = ScopeSnapshot.create(
        "spurgeon-mtp:collection",
        "collection",
        "collection_member",
        (
            "spurgeon-mtp:sermon-1",
            "spurgeon-mtp:sermon-15",
            "spurgeon-mtp:sermon-317",
        ),
        forged_authority,
    )
    event = VerificationEvent.create(
        subject_grain="collection",
        subject_id="spurgeon-mtp:collection",
        bundle=bundle,
        dimension="completeness",
        severity="high",
        disposition="limited",
        actor_id="reviewer-1",
        identity_graph=graph,
        anchor="ir/census/spurgeon-mtp.proof-wave.census.json#source.scope",
        evidence_refs=("ir/census/spurgeon-mtp.proof-wave.census.json",),
        scope_snapshot=forged_scope,
        expected_population_authority=forged_authority,
        timestamp="2026-07-17T00:00:00+00:00",
    )

    with pytest.raises(ContractError, match="repository-owned expected population"):
        fixture_module.accept_phase1a_event(event, REPO_ROOT)


@pytest.mark.parametrize("disposition", ("open", "limited"))
@requires_laptop_raw
def test_repository_event_acceptance_rejects_aggregate_without_scope_authority(
    disposition: str,
) -> None:
    bundle = build_phase1a_bundle(REPO_ROOT)
    event = object.__new__(VerificationEvent)
    for field, value in {
        "subject_grain": "collection",
        "subject_id": "spurgeon-mtp:collection",
        "bundle_hash": bundle.bundle_hash,
        "dimension": "completeness",
        "severity": "high",
        "disposition": disposition,
        "actor_id": "reviewer-1",
        "timestamp": "2026-07-17T00:00:00+00:00",
        "anchor": "ir/census/spurgeon-mtp.proof-wave.census.json#source.scope",
        "evidence_refs": ("ir/census/spurgeon-mtp.proof-wave.census.json",),
        "scope_snapshot": None,
        "expected_population_authority": None,
        "notes": "fabricated aggregate DTO",
    }.items():
        object.__setattr__(event, field, value)

    with pytest.raises(ContractError, match="scope|expected-population authority"):
        fixture_module.accept_phase1a_event(event, REPO_ROOT)


def test_work_level_sampled_evidence_does_not_map_to_record_review_state() -> None:
    work_mapping = map_evidence_to_review_state("sampled-human", "work")
    sampled_record_mapping = map_evidence_to_review_state("sampled-human", "canonical_record")
    exhaustive_record_mapping = map_evidence_to_review_state("exhaustive-human", "canonical_record")
    assert work_mapping.review_state_confidence is None
    assert sampled_record_mapping.review_state_confidence == "witness-compared"
    assert exhaustive_record_mapping.review_state_confidence == "human-reviewed"


def test_state_vocabularies_are_separate_and_production_mapping_is_schema_exact() -> None:
    schema = json.loads(
        (REPO_ROOT / "ocd_kernel/schemas/v1/review_state.schema.json").read_text(encoding="utf-8")
    )
    assert tuple(schema["$defs"]["confidence_tier"]["enum"]) == REVIEW_STATE_CONFIDENCES
    assert set(EVIDENCE_DEPTHS).isdisjoint(RELEASE_STATES)
    assert "accepted-expiring" in LIMITATION_STATES
    assert "known-wrong-non-certified" in RELEASE_STATES
    assert set(FINDING_DISPOSITIONS) == {"open", "limited", "accepted", "closed", "blocked"}


def test_runtime_placeholder_is_honestly_not_visual_evidence() -> None:
    fixture_runtime = load_fixture()["runtime"]
    runtime = RenderingRuntimeFingerprint.create(
        fixture_runtime["content_addressed_inputs"],
        fixture_runtime["recorded_environment_facts"],
        capture_status=fixture_runtime["capture_status"],
    )
    assert runtime.satisfies_visual_evidence is False
    assert runtime.capture_status == "not-captured"


def test_bundle_rejects_unbound_runtime_input_on_create_and_load() -> None:
    runtime = RenderingRuntimeFingerprint.create(
        ["unbound/runtime.js"],
        {
            "browser_engine": "test",
            "browser_version": "1",
            "launch_flags": "none",
            "css_font_fingerprint": "test-fonts",
        },
    )
    with pytest.raises(ContractError, match="runtime input.*hashed dependency"):
        VerificationBundle.create(
            subject_grain="rendering",
            subject_id="runtime-binding",
            dependency_manifest=_manifest(),
            policy_version="policy-v1",
            sample_algorithm_version="sample-v1",
            runtime_fingerprint=runtime,
            artifact_ids=("artifact",),
        )

    payload = _event_bundle().to_dict()
    payload["runtime_fingerprint"]["content_addressed_inputs"] = ["unbound/runtime.js"]
    payload["runtime_fingerprint"].pop("environment_fingerprint")
    payload["bundle_hash"] = "0" * 64
    with pytest.raises(ContractError, match="runtime input.*hashed dependency"):
        VerificationBundle.from_dict(payload)


def test_runtime_rejects_noncanonical_dot_segment_on_create_and_load() -> None:
    facts = {
        "browser_engine": "test",
        "browser_version": "1",
        "launch_flags": "none",
        "css_font_fingerprint": "test-fonts",
    }
    with pytest.raises(ContractError, match="normalized repository-relative"):
        RenderingRuntimeFingerprint.create(["inputs/./runtime.bin"], facts)
    with pytest.raises(ContractError, match="normalized repository-relative"):
        RenderingRuntimeFingerprint.from_dict(
            {
                "content_addressed_inputs": ["inputs/./runtime.bin"],
                "recorded_environment_facts": facts,
            }
        )


def _sampling_population(
    probes: tuple[str, ...],
    *,
    count: int | None = None,
) -> tuple[
    tuple[SourceFrame, ...],
    tuple[OutputFrame, ...],
    ExpectedPopulationAuthority,
    ExpectedPopulationAuthority,
]:
    population_count = count or len(probes)
    ids = tuple(f"f{index}" for index in range(population_count))
    source_authority_bytes = b"source-frame-authority-bytes"
    output_authority_bytes = b"output-frame-authority-bytes"
    source_authority = ExpectedPopulationAuthority.known(
        "source-frame-authority",
        "cvw_phase1a/fixtures/source-frame-authority.json",
        ArtifactIdentity.from_bytes(source_authority_bytes).raw_sha256,
        expected_ids=ids,
    )
    output_authority = ExpectedPopulationAuthority.known(
        "output-frame-authority",
        "cvw_phase1a/fixtures/output-frame-authority.json",
        ArtifactIdentity.from_bytes(output_authority_bytes).raw_sha256,
        expected_ids=ids,
    )
    source = tuple(
        SourceFrame(
            frame_id,
            f"text-{index}",
            ((probes[index],) if index < len(probes) else ()),
            source_authority.authority_id,
            str(source_authority.authority_sha256),
            "bounded-scope",
        )
        for index, frame_id in enumerate(ids)
    )
    output = tuple(
        OutputFrame(
            frame_id,
            f"text-{index}",
            ((probes[index],) if index < len(probes) else ()),
            output_authority.authority_id,
            str(output_authority.authority_sha256),
            "bounded-scope",
        )
        for index, frame_id in enumerate(ids)
    )
    return source, output, source_authority, output_authority


def _sampling_bundle(
    source_authority: ExpectedPopulationAuthority,
    output_authority: ExpectedPopulationAuthority,
    source_bytes: bytes,
    output_bytes: bytes,
) -> VerificationBundle:
    policy_bytes = json.dumps(
        load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    items = [
        (
            role,
            f"inputs/{role}.bin",
            policy_bytes if role == "policy" else f"{role}-v1".encode("utf-8"),
        )
        for role in REQUIRED_DEPENDENCY_ROLES
    ]
    items.extend(
        (
            ("authority", source_authority.authority_path or "", source_bytes),
            ("authority", output_authority.authority_path or "", output_bytes),
        )
    )
    return VerificationBundle.create(
        subject_grain="phase1a_fixture",
        subject_id="sampling-tests",
        dependency_manifest=DependencyManifest.from_contents(items),
        policy_version="cvw-risk-policy-v1",
        sample_algorithm_version="sample-v1",
        runtime_fingerprint=_runtime(),
        artifact_ids=("sampling-fixture",),
    )


def test_direct_bundle_constructor_enforces_all_create_invariants() -> None:
    source_bytes = b"source-frame-authority-bytes"
    output_bytes = b"output-frame-authority-bytes"
    manifest = DependencyManifest.from_contents(
        (
            ("authority", "cvw_phase1a/fixtures/source-frame-authority.json", source_bytes),
            ("authority", "cvw_phase1a/fixtures/output-frame-authority.json", output_bytes),
        )
    )
    runtime = RenderingRuntimeFingerprint.create(
        [],
        {
            "browser_engine": "test",
            "browser_version": "1",
            "launch_flags": "none",
            "css_font_fingerprint": "test-fonts",
        },
    )
    with pytest.raises(ContractError, match="dependency manifest is incomplete"):
        VerificationBundle(
            subject_grain=" phase1a_fixture ",
            subject_id=" sampling-tests ",
            dependency_manifest=manifest,
            policy_version=" policy-v1 ",
            sample_algorithm_version=" sample-v1 ",
            runtime_fingerprint=runtime,
            artifact_ids=(" duplicate ", "duplicate"),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("subject_grain", "rendering ", "canonical known subject grain"),
        ("subject_grain", "invented", "canonical known subject grain"),
        ("subject_id", " sampling-tests ", "subject_id.*normalized"),
        ("policy_version", " policy-v1 ", "policy_version.*normalized"),
        ("sample_algorithm_version", "", "sample_algorithm_version.*normalized"),
        ("artifact_ids", (" artifact ",), "artifact IDs.*normalized"),
        ("artifact_ids", ("artifact", "artifact"), "artifact IDs must be unique"),
    ),
)
def test_direct_bundle_constructor_rejects_each_noncanonical_field(
    field: str,
    value: object,
    message: str,
) -> None:
    valid = _sampling_bundle(
        *_sampling_population(("first",))[2:],
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    kwargs = {
        "subject_grain": valid.subject_grain,
        "subject_id": valid.subject_id,
        "dependency_manifest": valid.dependency_manifest,
        "policy_version": valid.policy_version,
        "sample_algorithm_version": valid.sample_algorithm_version,
        "runtime_fingerprint": valid.runtime_fingerprint,
        "artifact_ids": valid.artifact_ids,
    }
    kwargs[field] = value
    with pytest.raises(ContractError, match=message):
        VerificationBundle(**kwargs)


def test_bundle_create_rejects_noncanonical_artifact_ids() -> None:
    valid = _sampling_bundle(
        *_sampling_population(("first",))[2:],
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    create_kwargs = {
        "subject_grain": valid.subject_grain,
        "subject_id": valid.subject_id,
        "dependency_manifest": valid.dependency_manifest,
        "policy_version": valid.policy_version,
        "sample_algorithm_version": valid.sample_algorithm_version,
        "runtime_fingerprint": valid.runtime_fingerprint,
        "artifact_ids": (" sampling-fixture ",),
    }
    with pytest.raises(ContractError, match="artifact IDs.*normalized"):
        VerificationBundle.create(**create_kwargs)


def test_bundle_from_dict_rejects_noncanonical_artifact_ids() -> None:
    valid = _sampling_bundle(
        *_sampling_population(("first",))[2:],
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    serialized = valid.to_dict()
    serialized["artifact_ids"] = [" sampling-fixture "]
    with pytest.raises(ContractError, match="artifact IDs.*normalized"):
        VerificationBundle.from_dict(serialized)


def _serialized_sampling_bundle() -> dict[str, object]:
    valid = _sampling_bundle(
        *_sampling_population(("first",))[2:],
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    return valid.to_dict()


def test_manifest_from_dict_rejects_noncanonical_dependency_path() -> None:
    serialized = _serialized_sampling_bundle()
    dot_path_manifest = copy.deepcopy(serialized["dependency_manifest"])
    assert isinstance(dot_path_manifest, dict)
    policy_dependency = next(
        item for item in dot_path_manifest["dependencies"] if item["role"] == "policy"
    )
    policy_dependency["path"] = "inputs/./policy.bin"
    with pytest.raises(ContractError, match="normalized repository-relative"):
        DependencyManifest.from_dict(dot_path_manifest)


def test_bundle_from_dict_rejects_noncanonical_dependency_path() -> None:
    serialized = _serialized_sampling_bundle()
    dot_path_manifest = copy.deepcopy(serialized["dependency_manifest"])
    assert isinstance(dot_path_manifest, dict)
    policy_dependency = next(
        item for item in dot_path_manifest["dependencies"] if item["role"] == "policy"
    )
    policy_dependency["path"] = "inputs/./policy.bin"
    serialized["dependency_manifest"] = dot_path_manifest
    with pytest.raises(ContractError, match="normalized repository-relative"):
        VerificationBundle.from_dict(serialized)


def test_manifest_from_dict_rejects_noncanonical_dependency_order() -> None:
    serialized = _serialized_sampling_bundle()
    unsorted_manifest = copy.deepcopy(serialized["dependency_manifest"])
    assert isinstance(unsorted_manifest, dict)
    unsorted_manifest["dependencies"] = list(reversed(unsorted_manifest["dependencies"]))
    with pytest.raises(ContractError, match="canonically sorted"):
        DependencyManifest.from_dict(unsorted_manifest)


def test_bundle_from_dict_rejects_noncanonical_dependency_order() -> None:
    serialized = _serialized_sampling_bundle()
    unsorted_manifest = copy.deepcopy(serialized["dependency_manifest"])
    assert isinstance(unsorted_manifest, dict)
    unsorted_manifest["dependencies"] = list(reversed(unsorted_manifest["dependencies"]))
    serialized["dependency_manifest"] = unsorted_manifest
    with pytest.raises(ContractError, match="canonically sorted"):
        VerificationBundle.from_dict(serialized)


def test_manifest_and_bundle_deserialization_accept_canonical_controls() -> None:
    serialized = _serialized_sampling_bundle()
    canonical_manifest = serialized["dependency_manifest"]
    assert isinstance(canonical_manifest, dict)
    valid = VerificationBundle.from_dict(serialized)
    assert DependencyManifest.from_dict(canonical_manifest).to_dict() == canonical_manifest
    assert valid.to_dict() == serialized


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("path", "normalized repository-relative"),
        ("role", "dependency role.*normalized"),
        ("identity", "ArtifactIdentity"),
        ("raw-hash", "raw_sha256"),
        ("raw-hash-byte-length", "raw_sha256"),
    ),
)
def test_sampling_sink_revalidates_mutated_nested_dependencies(
    mutation: str,
    message: str,
) -> None:
    policy_bytes = json.dumps(
        load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    policy = RiskPolicyMatrix.from_payload(json.loads(policy_bytes)).for_tiers(["A"])
    source, output, source_authority, output_authority = _sampling_population(
        tuple(policy.mandatory_probes)
    )
    source_bytes = b"source-frame-authority-bytes"
    output_bytes = b"output-frame-authority-bytes"
    bundle = _sampling_bundle(source_authority, output_authority, source_bytes, output_bytes)

    if mutation == "path":
        dependency = next(
            item
            for item in bundle.dependency_manifest.dependencies
            if item.role == "transitive-code"
        )
        object.__setattr__(dependency, "path", "inputs/./transitive-code.bin")
    elif mutation == "role":
        dependency = next(
            item
            for item in bundle.dependency_manifest.dependencies
            if item.role == "authority" and item.path == "inputs/authority.bin"
        )
        object.__setattr__(dependency, "role", "authority ")
    else:
        dependency = next(
            item
            for item in bundle.dependency_manifest.dependencies
            if item.role == "source"
        )
        if mutation == "identity":
            object.__setattr__(dependency, "identity", object())
        elif mutation == "raw-hash":
            object.__setattr__(dependency.identity, "raw_sha256", "g" * 64)
        else:
            object.__setattr__(dependency.identity, "raw_sha256", "a" * 63)

    with pytest.raises(ContractError, match=message):
        evaluate_sampling_policy(
            policy,
            source,
            output,
            seed="seed",
            reviewer_ids=("reviewer-1",),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=bundle,
            source_authority_bytes=source_bytes,
            output_authority_bytes=output_bytes,
            policy_bytes=policy_bytes,
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )


def test_sampling_sink_accepts_unmodified_nested_dependencies() -> None:
    policy_bytes = json.dumps(
        load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    policy = RiskPolicyMatrix.from_payload(json.loads(policy_bytes)).for_tiers(["A"])
    source, output, source_authority, output_authority = _sampling_population(
        tuple(policy.mandatory_probes)
    )
    source_bytes = b"source-frame-authority-bytes"
    output_bytes = b"output-frame-authority-bytes"
    bundle = _sampling_bundle(source_authority, output_authority, source_bytes, output_bytes)
    result = evaluate_sampling_policy(
        policy,
        source,
        output,
        seed="seed",
        reviewer_ids=("reviewer-1",),
        source_authority=source_authority,
        output_authority=output_authority,
        bundle=bundle,
        source_authority_bytes=source_bytes,
        output_authority_bytes=output_bytes,
        policy_bytes=policy_bytes,
        policy_dependency_path="inputs/policy.bin",
        policy_tiers=("A",),
        scope_id="bounded-scope",
    )
    assert result.structural_passed is True


def test_caller_controlled_sampling_authorities_cannot_emit_a_repository_pass() -> None:
    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)

    result = _evaluate(
        policy,
        source,
        output,
        source_authority,
        output_authority,
    )

    assert result.passed is False
    assert result.accepted is False
    assert result.trust_state == "untrusted-structural"


@requires_laptop_raw
def test_repository_sampling_sink_rebuilds_authority_scope_and_frame_bindings() -> None:
    fixture = load_fixture()
    ids = tuple(sorted(item["id"] for item in fixture["asv"]["expected_members"]))
    policy = RiskPolicyMatrix.from_payload(fixture["risk_policy"]).for_tiers(["A"])
    mandatory = tuple(policy.mandatory_probes)
    source_authority_bytes = (
        REPO_ROOT / fixture["asv"]["expected_population_authority_path"]
    ).read_bytes()
    output_authority_bytes = (
        REPO_ROOT / "cvw_phase1a/fixtures/phase1a_fixture.json"
    ).read_bytes()
    source_authority = ExpectedPopulationAuthority.known(
        "asv-raw-json-witness-v1",
        fixture["asv"]["expected_population_authority_path"],
        ArtifactIdentity.from_bytes(source_authority_bytes).raw_sha256,
        expected_ids=ids,
    )
    output_authority = ExpectedPopulationAuthority.known(
        "asv-canonical-member-map-v1",
        "cvw_phase1a/fixtures/phase1a_fixture.json",
        ArtifactIdentity.from_bytes(output_authority_bytes).raw_sha256,
        expected_ids=ids,
    )
    scope = ScopeSnapshot.create(
        "asv:scrollmapper-json",
        "rendering",
        "canonical_file",
        ids,
        output_authority,
    )
    canonical_content = {
        member["id"]: json.dumps(
            [
                (record["chapter"], record["verse"], record["text"])
                for record in json.loads(
                    (REPO_ROOT / member["path"]).read_text(encoding="utf-8")
                )["data"]
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for member in fixture["asv"]["expected_members"]
    }
    source_frames = tuple(
        SourceFrame(
            frame_id=book_id,
            text=canonical_content[book_id],
            probes=(mandatory[index],) if index < len(mandatory) else (),
            authority_id=source_authority.authority_id,
            authority_sha256=source_authority.authority_sha256 or "",
            scope_id=scope.scope_id,
        )
        for index, book_id in enumerate(ids)
    )
    output_frames = tuple(
        OutputFrame(
            frame_id=book_id,
            text=canonical_content[book_id],
            probes=(mandatory[index],) if index < len(mandatory) else (),
            authority_id=output_authority.authority_id,
            authority_sha256=output_authority.authority_sha256 or "",
            scope_id=scope.scope_id,
        )
        for index, book_id in enumerate(ids)
    )

    result = fixture_module.accept_phase1a_sampling(
        REPO_ROOT,
        source_frames=source_frames,
        output_frames=output_frames,
        seed="repository-owned-sampling-test",
        reviewer_ids=("reviewer-1",),
        scope_snapshot=scope,
        policy_tiers=("A",),
    )

    assert result.structural_passed is True
    assert result.passed is True
    assert result.accepted is True
    assert result.trust_state == "repository-accepted"


@requires_laptop_raw
def test_repository_sampling_sink_rejects_forged_content_for_canonical_ids_and_probes() -> None:
    fixture = load_fixture()
    ids = tuple(sorted(item["id"] for item in fixture["asv"]["expected_members"]))
    policy = RiskPolicyMatrix.from_payload(fixture["risk_policy"]).for_tiers(["A"])
    mandatory = tuple(policy.mandatory_probes)
    source_bytes = (
        REPO_ROOT / fixture["asv"]["expected_population_authority_path"]
    ).read_bytes()
    output_bytes = (
        REPO_ROOT / "cvw_phase1a/fixtures/phase1a_fixture.json"
    ).read_bytes()
    source_authority = ExpectedPopulationAuthority.known(
        "asv-raw-json-witness-v1",
        fixture["asv"]["expected_population_authority_path"],
        ArtifactIdentity.from_bytes(source_bytes).raw_sha256,
        expected_ids=ids,
    )
    output_authority = ExpectedPopulationAuthority.known(
        "asv-canonical-member-map-v1",
        "cvw_phase1a/fixtures/phase1a_fixture.json",
        ArtifactIdentity.from_bytes(output_bytes).raw_sha256,
        expected_ids=ids,
    )
    scope = ScopeSnapshot.create(
        "asv:scrollmapper-json",
        "rendering",
        "canonical_file",
        ids,
        output_authority,
    )
    source_frames = tuple(
        SourceFrame(
            frame_id=book_id,
            text="FORGED-CONTENT",
            probes=(mandatory[index],) if index < len(mandatory) else (),
            authority_id=source_authority.authority_id,
            authority_sha256=source_authority.authority_sha256 or "",
            scope_id=scope.scope_id,
        )
        for index, book_id in enumerate(ids)
    )
    output_frames = tuple(
        OutputFrame(
            frame_id=book_id,
            text="FORGED-CONTENT",
            probes=(mandatory[index],) if index < len(mandatory) else (),
            authority_id=output_authority.authority_id,
            authority_sha256=output_authority.authority_sha256 or "",
            scope_id=scope.scope_id,
        )
        for index, book_id in enumerate(ids)
    )

    with pytest.raises(ContractError, match="current repository artifact content"):
        fixture_module.accept_phase1a_sampling(
            REPO_ROOT,
            source_frames=source_frames,
            output_frames=output_frames,
            seed="forged-content-review-attack",
            reviewer_ids=("reviewer-1",),
            scope_snapshot=scope,
            policy_tiers=("A",),
        )


@requires_laptop_raw
def test_repository_sampling_sink_rejects_caller_controlled_scope_and_authority() -> None:
    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    probes = tuple(policy.mandatory_probes)
    source, output, _, output_authority = _sampling_population(probes)
    caller_scope = ScopeSnapshot.create(
        "caller-controlled-scope",
        "rendering",
        "canonical_file",
        tuple(frame.frame_id for frame in output),
        output_authority,
    )

    with pytest.raises(ContractError, match="repository-owned ASV scope authority"):
        fixture_module.accept_phase1a_sampling(
            REPO_ROOT,
            source_frames=source,
            output_frames=output,
            seed="caller-controlled-sampling-test",
            reviewer_ids=("reviewer-1",),
            scope_snapshot=caller_scope,
            policy_tiers=("A",),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("subject_grain", 1),
        ("subject_id", 1),
        ("policy_version", True),
        ("sample_algorithm_version", b"sample"),
        ("artifact_ids", (123,)),
        ("artifact_ids", "ab"),
    ),
)
def test_bundle_create_and_direct_constructor_reject_non_string_trust_fields(
    field: str,
    value: object,
) -> None:
    valid = _sampling_bundle(
        *_sampling_population(("first",))[2:],
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    kwargs = {
        "subject_grain": valid.subject_grain,
        "subject_id": valid.subject_id,
        "dependency_manifest": valid.dependency_manifest,
        "policy_version": valid.policy_version,
        "sample_algorithm_version": valid.sample_algorithm_version,
        "runtime_fingerprint": valid.runtime_fingerprint,
        "artifact_ids": valid.artifact_ids,
    }
    kwargs[field] = value
    with pytest.raises(ContractError):
        VerificationBundle.create(**kwargs)
    with pytest.raises(ContractError):
        VerificationBundle(**kwargs)


@pytest.mark.parametrize(
    ("field", "untrusted", "canonical"),
    (
        ("subject_id", 123, "123"),
        ("policy_version", 123, "123"),
        ("sample_algorithm_version", 123, "123"),
        ("artifact_ids", [123], ("123",)),
    ),
)
def test_bundle_from_dict_rejects_coercible_non_string_fields(
    field: str,
    untrusted: object,
    canonical: object,
) -> None:
    valid = _sampling_bundle(
        *_sampling_population(("first",))[2:],
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    canonical_kwargs = {
        "subject_grain": valid.subject_grain,
        "subject_id": valid.subject_id,
        "dependency_manifest": valid.dependency_manifest,
        "policy_version": valid.policy_version,
        "sample_algorithm_version": valid.sample_algorithm_version,
        "runtime_fingerprint": valid.runtime_fingerprint,
        "artifact_ids": valid.artifact_ids,
    }
    canonical_kwargs[field] = canonical
    canonical_bundle = VerificationBundle.create(**canonical_kwargs)
    serialized = canonical_bundle.to_dict()
    serialized[field] = untrusted
    with pytest.raises(ContractError):
        VerificationBundle.from_dict(serialized)


def test_bundle_from_dict_rejects_non_string_bundle_hash_and_wrong_nested_shapes() -> None:
    serialized = _serialized_sampling_bundle()
    serialized["bundle_hash"] = 1
    with pytest.raises(ContractError, match="bundle_hash"):
        VerificationBundle.from_dict(serialized)

    for field, value in (
        ("dependency_manifest", []),
        ("runtime_fingerprint", []),
        ("artifact_ids", {"artifact": True}),
    ):
        hostile = _serialized_sampling_bundle()
        hostile[field] = value
        with pytest.raises(ContractError):
            VerificationBundle.from_dict(hostile)


def test_artifact_identity_and_manifest_reject_non_string_serialized_fields() -> None:
    numeric_hash = int("1" * 64)
    with pytest.raises(ContractError, match="raw_sha256"):
        ArtifactIdentity.from_dict({"raw_sha256": numeric_hash})
    with pytest.raises(ContractError, match="semantic_sha256"):
        ArtifactIdentity.from_dict(
            {"raw_sha256": "a" * 64, "semantic_sha256": numeric_hash}
        )
    with pytest.raises(ContractError, match="byte_length"):
        ArtifactIdentity.from_dict({"raw_sha256": "a" * 64, "byte_length": True})

    with pytest.raises(ContractError, match="byte_length.*non-authoritative"):
        ArtifactIdentity.from_dict({"raw_sha256": "a" * 64, "byte_length": 7})

    canonical = DependencyManifest.from_contents(
        [("source", "inputs/source.bin", b"source")]
    ).to_dict()
    for mutation in (
        {"manifest_version": 1},
        {"dependencies": "not-a-list"},
    ):
        hostile = copy.deepcopy(canonical)
        hostile.update(mutation)
        with pytest.raises(ContractError):
            DependencyManifest.from_dict(hostile)

    for field, value in (("role", 1), ("path", 123)):
        hostile = copy.deepcopy(canonical)
        hostile["dependencies"][0][field] = value
        with pytest.raises(ContractError):
            DependencyManifest.from_dict(hostile)


def test_phase1a_dependency_role_vocabulary_is_closed_at_all_boundaries() -> None:
    identity = ArtifactIdentity.from_bytes(b"bogus")
    with pytest.raises(ContractError, match="unknown dependency role"):
        contracts_module.Dependency("bogus-role", "inputs/bogus.bin", identity)

    serialized = DependencyManifest.from_contents(
        [("source", "inputs/source.bin", b"source")]
    ).to_dict()
    serialized["dependencies"][0]["role"] = "bogus-role"
    with pytest.raises(ContractError, match="unknown dependency role"):
        DependencyManifest.from_dict(serialized)

    valid = _sampling_bundle(
        *_sampling_population(("first",))[2:],
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    forged = object.__new__(contracts_module.Dependency)
    object.__setattr__(forged, "role", "bogus-role")
    object.__setattr__(forged, "path", "inputs/bogus.bin")
    object.__setattr__(forged, "identity", identity)
    dependencies = tuple(
        sorted(
            (*valid.dependency_manifest.dependencies, forged),
            key=lambda item: (item.role, item.path),
        )
    )
    object.__setattr__(valid.dependency_manifest, "dependencies", dependencies)
    with pytest.raises(ContractError, match="unknown dependency role"):
        valid.validate_trust_sink()

    assert contracts_module.Dependency(
        "source", "inputs/source.bin", ArtifactIdentity.from_bytes(b"source")
    ).role == "source"


def test_runtime_boundaries_reject_non_string_inputs_facts_and_status() -> None:
    facts = {
        "browser_engine": "test",
        "browser_version": "1",
        "launch_flags": "none",
        "css_font_fingerprint": "test-fonts",
    }
    with pytest.raises(ContractError):
        RenderingRuntimeFingerprint.create([123], facts)
    with pytest.raises(ContractError):
        RenderingRuntimeFingerprint.create(
            ["inputs/runtime.bin"], {**facts, "browser_version": 1}
        )
    with pytest.raises(ContractError):
        RenderingRuntimeFingerprint.from_dict(
            {
                "content_addressed_inputs": [123],
                "recorded_environment_facts": facts,
                "capture_status": "not-captured",
            }
        )
    with pytest.raises(ContractError):
        RenderingRuntimeFingerprint.from_dict(
            {
                "content_addressed_inputs": ["inputs/runtime.bin"],
                "recorded_environment_facts": facts,
                "capture_status": 0,
            }
        )


def test_authority_snapshot_graph_and_event_boundaries_reject_type_confusion() -> None:
    with pytest.raises(ContractError):
        ExpectedPopulationAuthority.known(
            "authority",
            "inputs/authority.json",
            "a" * 64,
            expected_ids="ab",
        )
    with pytest.raises(ContractError):
        ExpectedPopulationAuthority(
            "authority",
            "known",
            "inputs/authority.json",
            "a" * 64,
            expected_count=True,
        )
    with pytest.raises(ContractError):
        IdentityGraph.from_payload(
            {
                "nodes": [{"grain": 1, "subject_id": "id", "authority": "source"}],
                "allowed_rollups": [],
            }
        )
    authority = ExpectedPopulationAuthority.known(
        "authority", "inputs/authority.json", "a" * 64, expected_count=2
    )
    with pytest.raises(ContractError):
        ScopeSnapshot.create("scope", "collection", "collection_member", "ab", authority)

    with pytest.raises(ContractError):
        VerificationEvent(
            subject_grain="collection_member",
            subject_id="member",
            bundle_hash="a" * 64,
            dimension="completeness",
            severity="high",
            disposition="open",
            actor_id="reviewer",
            timestamp="2026-07-17T00:00:00+00:00",
            anchor="inputs/evidence.json",
            evidence_refs=("inputs/evidence.json",),
            notes=123,
        )


def test_expected_population_and_scope_consumers_reject_nested_mutation() -> None:
    authority = ExpectedPopulationAuthority.known(
        "authority", "inputs/authority.json", "a" * 64, expected_ids=("one", "two")
    )
    object.__setattr__(authority, "expected_ids", ["one", "two"])
    with pytest.raises(ContractError, match="canonical tuple"):
        contracts_module.reconcile_population(authority, ("one", "two"))

    authority = ExpectedPopulationAuthority.known(
        "authority", "inputs/authority.json", "a" * 64, expected_count=2
    )
    object.__setattr__(authority, "expected_count", True)
    with pytest.raises(ContractError, match="expected population count"):
        contracts_module.reconcile_population(authority, ("one", "two"))

    authority = ExpectedPopulationAuthority.known(
        "authority", "inputs/authority.json", "a" * 64, expected_count=2
    )
    object.__setattr__(authority, "authority_id", " relabeled ")
    with pytest.raises(ContractError, match="normalized"):
        contracts_module.reconcile_population(authority, ("one", "two"))

    clean_authority = ExpectedPopulationAuthority.known(
        "authority", "inputs/authority.json", "a" * 64, expected_count=2
    )
    scope = ScopeSnapshot.create(
        "scope", "collection", "collection_member", ("one",), clean_authority
    )
    object.__setattr__(scope, "scope_id", " scope ")
    with pytest.raises(ContractError, match="normalized"):
        scope.validate_trust_sink()


def test_provenance_and_baseline_deserialization_reject_coercible_non_strings() -> None:
    provenance = {
        "repository_head": int("1" * 40),
        "external_review_path": ".tmp_audit/reviewer.txt",
        "external_review_sha256": "b" * 64,
        "trust_statement": (
            "The external independent reviewer report/hash is the current trust anchor; "
            "the baseline self-hash checks integrity only and is not an immutable trust anchor."
        ),
    }
    with pytest.raises(ContractError, match="repository_head"):
        BaselineCaptureProvenance.from_dict(provenance)

    baseline_payload = json.loads(
        (REPO_ROOT / "cvw_phase1a/fixtures/phase1a_baseline.json").read_text(encoding="utf-8")
    )
    baseline_payload["baseline_version"] = 2
    with pytest.raises(ContractError, match="baseline_version"):
        BoundBaseline.from_dict(baseline_payload)


def test_policy_frames_and_sampling_reject_non_string_and_bool_confusion() -> None:
    escalation = copy.deepcopy(load_fixture()["risk_policy"]["tiers"][0]["failure_escalation"])
    escalation["sample_multiplier"] = True
    with pytest.raises(ContractError, match="sample_multiplier"):
        EscalationPolicy.from_payload(escalation)

    policy_payload = copy.deepcopy(load_fixture()["risk_policy"]["tiers"][0])
    policy_payload["minimum_count"] = True
    with pytest.raises(ContractError, match="minimum_count"):
        RiskPolicy.from_payload(policy_payload)

    matrix_payload = copy.deepcopy(load_fixture()["risk_policy"])
    matrix_payload["version"] = 123
    with pytest.raises(ContractError, match="version"):
        RiskPolicyMatrix.from_payload(matrix_payload)

    with pytest.raises(ContractError):
        SourceFrame("frame", 123, (), "authority", "a" * 64, "scope")
    with pytest.raises(ContractError):
        OutputFrame("frame", 123, (), "authority", "a" * 64, "scope")

    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    source, output, source_authority, output_authority = _sampling_population(
        tuple(policy.mandatory_probes)
    )
    source_bytes = b"source-frame-authority-bytes"
    output_bytes = b"output-frame-authority-bytes"
    policy_bytes = json.dumps(
        load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    bundle = _sampling_bundle(source_authority, output_authority, source_bytes, output_bytes)
    with pytest.raises(ContractError, match="reviewer IDs"):
        evaluate_sampling_policy(
            policy,
            source,
            output,
            seed="seed",
            reviewer_ids=(1,),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=bundle,
            source_authority_bytes=source_bytes,
            output_authority_bytes=output_bytes,
            policy_bytes=policy_bytes,
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )


def test_sampling_sink_revalidates_bundle_and_rejects_permissive_direct_policy() -> None:
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)
    source_bytes = b"source-frame-authority-bytes"
    output_bytes = b"output-frame-authority-bytes"
    bundle = _sampling_bundle(source_authority, output_authority, source_bytes, output_bytes)
    incomplete = DependencyManifest.from_contents(
        (
            ("authority", source_authority.authority_path or "", source_bytes),
            ("authority", output_authority.authority_path or "", output_bytes),
        )
    )
    object.__setattr__(bundle, "dependency_manifest", incomplete)
    permissive = RiskPolicy(
        tier="A",
        sample_universe="anything",
        minimum_count=0,
        minimum_rate=0.0,
        mandatory_probes=(),
        failure_escalation=EscalationPolicy(1, (), 0, False, False),
        reviewer_count=0,
        limitation_expiry_days=0,
        candidate_effect="candidate verified",
        release_effect="certified",
    )
    policy_bytes = json.dumps(
        load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with pytest.raises(ContractError, match="dependency manifest is incomplete"):
        evaluate_sampling_policy(
            permissive,
            source,
            output,
            seed="seed",
            reviewer_ids=(),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=bundle,
            source_authority_bytes=source_bytes,
            output_authority_bytes=output_bytes,
            policy_bytes=policy_bytes,
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )


def test_sampling_policy_is_selected_from_exact_bundle_bound_policy_bytes() -> None:
    policy_bytes = json.dumps(
        load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    matrix = RiskPolicyMatrix.from_payload(json.loads(policy_bytes))
    bound_policy = matrix.for_tiers(["A"])
    probes = tuple(bound_policy.mandatory_probes)
    source, output, source_authority, output_authority = _sampling_population(probes)
    source_bytes = b"source-frame-authority-bytes"
    output_bytes = b"output-frame-authority-bytes"
    bundle = _sampling_bundle(source_authority, output_authority, source_bytes, output_bytes)
    result = evaluate_sampling_policy(
        bound_policy,
        source,
        output,
        seed="seed",
        reviewer_ids=("reviewer-1",),
        source_authority=source_authority,
        output_authority=output_authority,
        bundle=bundle,
        source_authority_bytes=source_bytes,
        output_authority_bytes=output_bytes,
        policy_bytes=policy_bytes,
        policy_dependency_path="inputs/policy.bin",
        policy_tiers=("A",),
        scope_id="bounded-scope",
    )
    assert result.structural_passed is True
    assert result.candidate_effect == bound_policy.candidate_effect
    assert result.release_effect == bound_policy.release_effect

    permissive = RiskPolicy(
        tier="A",
        sample_universe=bound_policy.sample_universe,
        minimum_count=0,
        minimum_rate=0.0,
        mandatory_probes=(),
        failure_escalation=EscalationPolicy(1, (), 0, False, False),
        reviewer_count=0,
        limitation_expiry_days=0,
        candidate_effect="candidate verified",
        release_effect="certified",
    )
    with pytest.raises(ContractError, match="bundle-bound policy bytes"):
        evaluate_sampling_policy(
            permissive,
            source,
            output,
            seed="seed",
            reviewer_ids=(),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=bundle,
            source_authority_bytes=source_bytes,
            output_authority_bytes=output_bytes,
            policy_bytes=policy_bytes,
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )

    serialized_policy = copy.deepcopy(load_fixture()["risk_policy"]["tiers"][0])
    serialized_policy["candidate_effect"] = "candidate verified"
    serialized_policy["release_effect"] = "certified"
    forged_from_serialized = RiskPolicy.from_payload(serialized_policy)
    with pytest.raises(ContractError, match="bundle-bound policy bytes"):
        evaluate_sampling_policy(
            forged_from_serialized,
            source,
            output,
            seed="seed",
            reviewer_ids=("reviewer-1",),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=bundle,
            source_authority_bytes=source_bytes,
            output_authority_bytes=output_bytes,
            policy_bytes=policy_bytes,
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )


def test_sampling_sink_requires_bundle_and_actual_authority_bytes() -> None:
    parameters = inspect.signature(evaluate_sampling_policy).parameters
    assert "bundle" in parameters
    assert "source_authority_bytes" in parameters
    assert "output_authority_bytes" in parameters
    assert "policy_bytes" in parameters
    assert "policy_dependency_path" in parameters
    assert "policy_tiers" in parameters
    assert "source_authority_verification" not in parameters
    assert "output_authority_verification" not in parameters

    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)
    source_bytes = b"source-frame-authority-bytes"
    output_bytes = b"output-frame-authority-bytes"
    with pytest.raises(TypeError, match="bundle"):
        evaluate_sampling_policy(
            policy,
            source,
            output,
            seed="seed",
            reviewer_ids=("reviewer-1",),
            source_authority=source_authority,
            output_authority=output_authority,
            scope_id="bounded-scope",
        )
    bundle = _sampling_bundle(
        source_authority,
        output_authority,
        source_bytes,
        output_bytes,
    )
    result = evaluate_sampling_policy(
        policy,
        source,
        output,
        seed="seed",
        reviewer_ids=("reviewer-1",),
        source_authority=source_authority,
        output_authority=output_authority,
        bundle=bundle,
        source_authority_bytes=source_bytes,
        output_authority_bytes=output_bytes,
        policy_bytes=json.dumps(
            load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8"),
        policy_dependency_path="inputs/policy.bin",
        policy_tiers=("A",),
        scope_id="bounded-scope",
    )
    assert result.structural_passed is True

    wrong_bundle = _sampling_bundle(
        source_authority,
        output_authority,
        b"different source dependency bytes",
        output_bytes,
    )
    with pytest.raises(ContractError, match="not an exact authority dependency"):
        evaluate_sampling_policy(
            policy,
            source,
            output,
            seed="seed",
            reviewer_ids=("reviewer-1",),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=wrong_bundle,
            source_authority_bytes=source_bytes,
            output_authority_bytes=output_bytes,
            policy_bytes=json.dumps(
                load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )


def _evaluate(
    policy,
    source,
    output,
    source_authority,
    output_authority,
    reviewers=("reviewer-1",),
    producer_feature_flags=(),
):
    authority_payloads = {
        "source-frame-authority": b"source-frame-authority-bytes",
        "output-frame-authority": b"output-frame-authority-bytes",
    }
    source_bytes = authority_payloads[source_authority.authority_id]
    output_bytes = authority_payloads.get(output_authority.authority_id)
    if output_bytes is None and output_authority.authority_sha256 == source_authority.authority_sha256:
        output_bytes = source_bytes
    if output_bytes is None:
        raise AssertionError("test authority payload is not defined")
    bundle = _sampling_bundle(
        source_authority,
        output_authority,
        source_bytes,
        output_bytes,
    )
    return evaluate_sampling_policy(
        policy,
        source,
        output,
        seed="seed",
        reviewer_ids=reviewers,
        source_authority=source_authority,
        output_authority=output_authority,
        bundle=bundle,
        source_authority_bytes=source_bytes,
        output_authority_bytes=output_bytes,
        policy_bytes=json.dumps(
            load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8"),
        policy_dependency_path="inputs/policy.bin",
        policy_tiers=tuple(policy.tier.split("+")),
        scope_id="bounded-scope",
        producer_feature_flags=producer_feature_flags,
    )


def test_sampling_policy_is_independent_two_sided_and_flag_independent() -> None:
    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)
    first = _evaluate(
        policy,
        source,
        output,
        source_authority,
        output_authority,
        producer_feature_flags=("x",),
    )
    second = _evaluate(
        policy,
        source,
        output,
        source_authority,
        output_authority,
        producer_feature_flags=("different",),
    )
    assert first.structural_passed is True
    assert first.checks == second.checks
    assert first.selected_source_count == 6
    assert first.selected_output_count == 6


def test_sampling_rejects_one_sided_missing_and_concentrated_mandatory_frames() -> None:
    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)
    with pytest.raises(ContractError, match="non-empty independent"):
        _evaluate(policy, source, (), source_authority, output_authority)

    concentrated_source = list(source)
    concentrated_output = list(output)
    concentrated_source[0] = SourceFrame(
        "f0", "text-0", probes, source_authority.authority_id,
        str(source_authority.authority_sha256), "bounded-scope"
    )
    concentrated_output[0] = OutputFrame(
        "f0", "text-0", probes, output_authority.authority_id,
        str(output_authority.authority_sha256), "bounded-scope"
    )
    for index in range(1, len(probes)):
        concentrated_source[index] = SourceFrame(
            f"f{index}", f"text-{index}", (), source_authority.authority_id,
            str(source_authority.authority_sha256), "bounded-scope"
        )
        concentrated_output[index] = OutputFrame(
            f"f{index}", f"text-{index}", (), output_authority.authority_id,
            str(output_authority.authority_sha256), "bounded-scope"
        )
    evaluation = _evaluate(
        policy, tuple(concentrated_source), tuple(concentrated_output), source_authority, output_authority
    )
    assert evaluation.passed is False
    assert evaluation.mandatory_probes_satisfied is False


def test_sampling_failure_has_executable_tier_b_escalation_and_tier_cd_reviewers() -> None:
    matrix = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"])
    b_policy = matrix.for_tiers(["B"])
    b_probes = ("first", "last", "transition", "structure-carrier", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(b_probes, count=10)
    failed_output = list(output)
    original = failed_output[0]
    failed_output[0] = OutputFrame(
        original.frame_id,
        "changed",
        original.probes,
        original.authority_id,
        original.authority_sha256,
        original.scope_id,
    )
    failed = _evaluate(
        b_policy, source, tuple(failed_output), source_authority, output_authority
    )
    assert failed.passed is False
    assert failed.next_required_count_per_side == 20
    assert failed.next_required_reviewer_count == 2
    assert {"boundary", "structure-carrier"}.issubset(failed.next_required_probes)
    assert failed.candidate_blocked is True
    assert failed.release_blocked is True

    for tier, probes, count in (
        ("C", ("first-page", "last-page", "boundary", "corruption", "orphan-both-directions"), 20),
        ("D", ("first", "last", "transition", "empty", "longest", "shortest", "orphan-both-directions"), 25),
    ):
        policy = matrix.for_tiers([tier])
        source, output, source_authority, output_authority = _sampling_population(probes, count=count)
        one_reviewer = _evaluate(
            policy, source, output, source_authority, output_authority, reviewers=("one",)
        )
        assert one_reviewer.passed is False
        assert one_reviewer.reviewer_count_satisfied is False
        two_reviewers = _evaluate(
            policy, source, output, source_authority, output_authority, reviewers=("one", "two")
        )
        assert two_reviewers.structural_passed is True


def test_sampling_policy_rejects_weak_policy_and_authority_drift() -> None:
    fixture = load_fixture()
    weak = copy.deepcopy(fixture["risk_policy"])
    weak["tiers"][0]["mandatory_probes"] = []
    with pytest.raises(ContractError):
        RiskPolicyMatrix.from_payload(weak)
    policy = RiskPolicyMatrix.from_payload(fixture["risk_policy"]).for_tiers(["A"])
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)
    drifted = list(source)
    item = drifted[0]
    drifted[0] = SourceFrame(
        item.frame_id, item.text, item.probes, item.authority_id, "3" * 64, item.scope_id
    )
    with pytest.raises(ContractError, match="outside its bound authority"):
        _evaluate(policy, tuple(drifted), output, source_authority, output_authority)


def test_sampling_normalizes_reviewers_rejects_same_hash_and_requires_orphan_policy() -> None:
    matrix = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"])
    c_policy = matrix.for_tiers(["C"])
    c_probes = ("first-page", "last-page", "boundary", "corruption", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(c_probes, count=20)
    whitespace = _evaluate(
        c_policy,
        source,
        output,
        source_authority,
        output_authority,
        reviewers=("reviewer", " reviewer "),
    )
    assert whitespace.reviewer_ids == ("reviewer",)
    assert whitespace.reviewer_count_satisfied is False

    same_hash_output_authority = ExpectedPopulationAuthority.known(
        "different-label-same-content",
        "cvw_phase1a/fixtures/different-label.json",
        str(source_authority.authority_sha256),
        expected_ids=source_authority.expected_ids,
    )
    same_hash_output = tuple(
        OutputFrame(
            frame.frame_id,
            frame.text,
            frame.probes,
            same_hash_output_authority.authority_id,
            str(same_hash_output_authority.authority_sha256),
            frame.scope_id,
        )
        for frame in output
    )
    with pytest.raises(ContractError, match="independent.*content"):
        _evaluate(
            c_policy,
            source,
            same_hash_output,
            source_authority,
            same_hash_output_authority,
            reviewers=("one", "two"),
        )

    weak = copy.deepcopy(load_fixture()["risk_policy"])
    weak["tiers"][0]["mandatory_probes"] = ["first", "last", "empty", "longest", "shortest"]
    with pytest.raises(ContractError, match="bidirectional orphan"):
        RiskPolicyMatrix.from_payload(weak)


def test_sampling_rejects_identical_actual_authority_bytes_despite_different_claimed_hashes() -> None:
    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)
    identical_bytes = b"the same actual authority bytes"
    bundle = _sampling_bundle(
        source_authority,
        output_authority,
        identical_bytes,
        identical_bytes,
    )
    assert source_authority.authority_sha256 != output_authority.authority_sha256

    with pytest.raises(ContractError, match="equal actual bytes"):
        evaluate_sampling_policy(
            policy,
            source,
            output,
            seed="seed",
            reviewer_ids=("reviewer-1",),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=bundle,
            source_authority_bytes=identical_bytes,
            output_authority_bytes=identical_bytes,
            policy_bytes=json.dumps(
                load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )


def test_passing_samples_preserve_each_tier_and_combined_policy_effects() -> None:
    matrix = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"])
    tier_inputs = {
        "A": (("first", "last", "empty", "longest", "shortest", "orphan-both-directions"), 6),
        "B": (("first", "last", "transition", "structure-carrier", "orphan-both-directions"), 10),
        "C": (("first-page", "last-page", "boundary", "corruption", "orphan-both-directions"), 20),
        "D": (("first", "last", "transition", "empty", "longest", "shortest", "orphan-both-directions"), 25),
    }
    for tier, (probes, count) in tier_inputs.items():
        policy = matrix.for_tiers([tier])
        source, output, source_authority, output_authority = _sampling_population(probes, count=count)
        reviewers = ("one", "two") if tier in {"C", "D"} else ("one",)
        result = _evaluate(
            policy, source, output, source_authority, output_authority, reviewers=reviewers
        )
        assert result.structural_passed is True
        assert result.candidate_effect == policy.candidate_effect
        assert result.release_effect == policy.release_effect

    combined = matrix.for_tiers(["B", "D"])
    probes = tuple(combined.mandatory_probes)
    count = 25
    source, output, source_authority, output_authority = _sampling_population(probes, count=count)
    result = _evaluate(
        combined,
        source,
        output,
        source_authority,
        output_authority,
        reviewers=("one", "two"),
    )
    assert result.structural_passed is True
    assert result.candidate_effect == combined.candidate_effect
    assert result.release_effect == combined.release_effect
    assert "no collection-level certification from sampled members alone" in result.release_effect


def test_phase0_policy_runtime_and_identity_graph_are_explicit() -> None:
    fixture = load_fixture()
    policies = RiskPolicyMatrix.from_payload(fixture["risk_policy"])
    combined = policies.for_tiers(["B", "D"])
    graph = IdentityGraph.from_payload(fixture["identity_graph"])
    assert policies.version == "cvw-risk-policy-v1"
    assert {policy.tier for policy in policies.policies} == {"A", "B", "C", "D"}
    assert combined.minimum_count == 25
    assert combined.reviewer_count == 2
    assert graph.can_roll_up("collection_member", "collection", complete=True) is False


@pytest.mark.parametrize("role", REQUIRED_DEPENDENCY_ROLES)
@requires_laptop_raw
def test_report_controlled_dependency_mutation_is_stale(role: str) -> None:
    report = build_phase1a_report(REPO_ROOT, mutation_role=role)
    rendered = report.render()
    assert "baseline-current: STALE" in rendered
    assert f"baseline-stale-reason: dependency:{role}:" in rendered


@requires_laptop_raw
@pytest.mark.requires_local_artifacts
def test_report_does_not_generate_a_fresh_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    import cvw_phase1a
    import cvw_phase1a.fixture as fixture_module

    def fail_if_called(_: Path):
        raise AssertionError("ordinary reporting must not generate a baseline")

    monkeypatch.setattr(fixture_module, "_capture_phase1a_baseline_for_repair", fail_if_called)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    report = build_phase1a_report(REPO_ROOT)
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    rendered = report.render()
    if head_before == head_after:
        assert "baseline-current: BOUND" in rendered
    else:
        assert "baseline-current: BOUND" in rendered
        assert "baseline-capture-repository-head-changed" not in rendered
    assert not hasattr(cvw_phase1a, "build_phase1a_baseline")


def test_missing_gitignored_raw_witnesses_report_unknown_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cvw_phase1a.fixture as fixture_module

    monkeypatch.setattr(
        fixture_module,
        "raw_environment_preflight",
        lambda _root, _fixture=None: ("raw/missing-witness",),
    )
    report = build_phase1a_report(REPO_ROOT)
    assert report.exit_code == 1
    assert "environment: UNKNOWN/BLOCKED" in report.render()
    assert "raw/missing-witness" in report.render()
    assert "baseline-current: UNKNOWN" in report.render()


@requires_laptop_raw
def test_cli_has_no_write_or_arbitrary_output_capability() -> None:
    baseline = REPO_ROOT / "cvw_phase1a/fixtures/phase1a_baseline.json"
    evidence = REPO_ROOT / "cvw_phase1a/fixtures/historical_bcp_1549_probe.json"
    forbidden = REPO_ROOT / "data/cvw-cli-should-not-exist.json"
    before = (baseline.read_bytes(), evidence.read_bytes())
    for option in ("--write-baseline", "--output"):
        completed = subprocess.run(
            [
                "python",
                "-m",
                "cvw_phase1a.cli",
                option,
                forbidden.relative_to(REPO_ROOT).as_posix(),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 2
        assert "unrecognized arguments" in completed.stderr
        assert not forbidden.exists()
    ordinary = subprocess.run(
        ["python", "-m", "cvw_phase1a.cli"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ordinary.returncode == 1
    assert (baseline.read_bytes(), evidence.read_bytes()) == before
    assert not forbidden.exists()


@requires_laptop_raw
def test_cli_fixture_reports_fail_closed_historical_contradiction() -> None:
    report = build_phase1a_report(REPO_ROOT)
    rendered = report.render()
    assert report.exit_code == 1
    assert "Corpus Verification Workbench cvw-phase0-1a-v3" in rendered
    assert "spurgeon-mtp: scoped-only (3/3547" in rendered
    assert "writer-manifest: legacy-untrusted" in rendered
    assert "historical-ledger-claim=PASS" in rendered
    assert "checker-probe-blobs=VERIFIED" in rendered
    assert "historical-checker-executed=NO" in rendered
    assert "independent-probe=RECOMPUTED" in rendered
    assert "287/321 evaluated labels absent" in rendered
    assert "34 present; 11 receipt labels empty/skipped" in rendered
    assert "runtime: NOT CAPTURED" in rendered
    assert "overall-candidate: BLOCKED" in rendered


@pytest.mark.parametrize(
    "hostile_path",
    (
        "/abs/bound.bin",
        "C:/abs/bound.bin",
        "C:drive-qualified.bin",
        "//server/share/bound.bin",
        "\\\\server\\share\\bound.bin",
        "\\rooted\\bound.bin",
        "inputs\\bound.bin",
        "inputs/./bound.bin",
        "./inputs/bound.bin",
        "inputs//bound.bin",
        "inputs/../bound.bin",
        "inputs/bound.bin/",
    ),
)
def test_every_contract_path_boundary_rejects_noncanonical_repository_paths(
    hostile_path: str,
) -> None:
    identity = ArtifactIdentity.from_bytes(b"bound")
    with pytest.raises(ContractError, match="repository-relative|normalized"):
        contracts_module.Dependency("source", hostile_path, identity)

    serialized = DependencyManifest.from_contents(
        [("source", "inputs/bound.bin", b"bound")]
    ).to_dict()
    serialized["dependencies"][0]["path"] = hostile_path
    with pytest.raises(ContractError, match="repository-relative|normalized"):
        DependencyManifest.from_dict(serialized)

    with pytest.raises(ContractError, match="repository-relative|normalized"):
        RenderingRuntimeFingerprint.create(
            [hostile_path],
            {
                "browser_engine": "test",
                "browser_version": "1",
                "launch_flags": "none",
                "css_font_fingerprint": "fonts",
            },
        )


def test_rollup_requires_revalidated_real_graph_and_known_target_grain() -> None:
    claim = CoverageClaim(
        subject_id="spurgeon-mtp:proof-wave",
        subject_grain="rendering",
        scope_grain="collection_member",
        numerator=3,
        denominator=3,
        authority_id="spurgeon-census",
        authority_sha256="a" * 64,
        rollup_rule="complete-only",
        allowed_rollup_grains=("collection",),
    )

    class FakeGraph:
        def find(self, *_args):
            return object()

        def rollup_rule_for(self, *_args):
            return "complete-only"

        def can_roll_up(self, *_args, **_kwargs):
            return True

    with pytest.raises(ContractError):
        evaluate_rollup(
            claim,
            "made-up",
            target_subject_id="made-up-target",
            graph=FakeGraph(),
        )
    with pytest.raises(ContractError, match="IdentityGraph"):
        evaluate_rollup(
            claim,
            "collection",
            target_subject_id="spurgeon-mtp:collection",
            graph=FakeGraph(),
        )
    with pytest.raises(ContractError, match="canonical known subject grain"):
        evaluate_rollup(
            claim,
            "made-up",
            target_subject_id="made-up-target",
            graph=_graph(),
        )

    mutated = _graph()
    object.__setattr__(
        mutated,
        "allowed_rollups",
        [["collection_member", "collection", "complete-only"]],
    )
    with pytest.raises(ContractError):
        evaluate_rollup(
            claim,
            "collection",
            target_subject_id="spurgeon-mtp:collection",
            graph=mutated,
        )


def test_trust_sinks_reject_hostile_subclasses_and_object_new_nested_values() -> None:
    class HostileAuthority(ExpectedPopulationAuthority):
        def validate_trust_sink(self) -> None:
            return None

    authority = ExpectedPopulationAuthority.known(
        "authority", "inputs/authority.json", "a" * 64, expected_ids=("one",)
    )
    forged_authority = object.__new__(HostileAuthority)
    for field in (
        "authority_id",
        "status",
        "authority_path",
        "authority_sha256",
        "expected_count",
        "expected_ids",
        "reason",
    ):
        object.__setattr__(forged_authority, field, getattr(authority, field))
    with pytest.raises(ContractError, match="exact ExpectedPopulationAuthority"):
        contracts_module.reconcile_population(forged_authority, ("one",))

    class HostileFrame(SourceFrame):
        def validate_trust_sink(self) -> None:
            return None

    source, output, source_authority, output_authority = _sampling_population(
        ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    )
    forged_source = object.__new__(HostileFrame)
    for field in (
        "frame_id",
        "text",
        "probes",
        "authority_id",
        "authority_sha256",
        "scope_id",
    ):
        object.__setattr__(forged_source, field, getattr(source[0], field))
    with pytest.raises(ContractError, match="exact SourceFrame"):
        _evaluate(
            RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"]),
            (forged_source, *source[1:]),
            output,
            source_authority,
            output_authority,
        )

    class HostileBundle(VerificationBundle):
        def validate_trust_sink(self) -> None:
            return None

    valid_bundle = _sampling_bundle(
        source_authority,
        output_authority,
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    forged_bundle = object.__new__(HostileBundle)
    for field in (
        "subject_grain",
        "subject_id",
        "dependency_manifest",
        "policy_version",
        "sample_algorithm_version",
        "runtime_fingerprint",
        "artifact_ids",
    ):
        object.__setattr__(forged_bundle, field, getattr(valid_bundle, field))
    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    policy_bytes = json.dumps(
        load_fixture()["risk_policy"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with pytest.raises(ContractError, match="exact VerificationBundle"):
        evaluate_sampling_policy(
            policy,
            source,
            output,
            seed="seed",
            reviewer_ids=("reviewer-1",),
            source_authority=source_authority,
            output_authority=output_authority,
            bundle=forged_bundle,
            source_authority_bytes=b"source-frame-authority-bytes",
            output_authority_bytes=b"output-frame-authority-bytes",
            policy_bytes=policy_bytes,
            policy_dependency_path="inputs/policy.bin",
            policy_tiers=("A",),
            scope_id="bounded-scope",
        )

    round_tripped = pickle.loads(pickle.dumps(valid_bundle))
    assert round_tripped.to_dict() == valid_bundle.to_dict()


def test_artifact_byte_length_cannot_be_asserted_serialized_or_mutated() -> None:
    raw_sha256 = ArtifactIdentity.from_bytes(b"abc").raw_sha256
    with pytest.raises(ContractError, match="byte_length.*non-authoritative"):
        ArtifactIdentity(raw_sha256, byte_length=999)
    with pytest.raises(ContractError, match="byte_length.*non-authoritative"):
        ArtifactIdentity.from_dict({"raw_sha256": raw_sha256, "byte_length": 3})

    identity = ArtifactIdentity.from_bytes(b"abc")
    assert identity.to_dict() == {"raw_sha256": raw_sha256}
    assert ArtifactIdentity.from_dict(identity.to_dict()) == identity
    mutated_equal = ArtifactIdentity.from_bytes(b"abc")
    object.__setattr__(mutated_equal, "byte_length", 999)
    assert mutated_equal == identity
    assert hash(mutated_equal) == hash(identity)
    assert mutated_equal.to_dict() == identity.to_dict()

    manifest = DependencyManifest.from_contents(
        [("source", "inputs/source.bin", b"abc")]
    )
    nested = manifest.dependencies[0].identity
    object.__setattr__(nested, "byte_length", 999)
    with pytest.raises(ContractError, match="byte_length.*non-authoritative"):
        nested.validate_trust_sink()
    with pytest.raises(ContractError, match="byte_length.*non-authoritative"):
        contracts_module.Dependency("source", "inputs/source.bin", nested)

    source, output, source_authority, output_authority = _sampling_population(("first",))
    bundle = _sampling_bundle(
        source_authority,
        output_authority,
        b"source-frame-authority-bytes",
        b"output-frame-authority-bytes",
    )
    object.__setattr__(bundle.dependency_manifest.dependencies[0].identity, "byte_length", 999)
    with pytest.raises(ContractError, match="byte_length.*non-authoritative"):
        bundle.validate_trust_sink()


@pytest.mark.requires_local_artifacts
def test_fixture_validators_reject_coercible_non_json_values() -> None:
    class StringLike:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    class IntLike:
        def __init__(self, value: int) -> None:
            self.value = value

        def __int__(self) -> int:
            return self.value

    with pytest.raises(ContractError):
        fixture_module.validate_spurgeon_family_membership("1.html", expected_count=1)
    with pytest.raises(ContractError):
        fixture_module.validate_spurgeon_family_membership(("1.html",), expected_count=True)
    with pytest.raises(ContractError):
        fixture_module.validate_spurgeon_family_membership(
            (StringLike("1.html"),), expected_count=1
        )

    fixture = load_fixture()
    asv_authority = json.loads(
        (REPO_ROOT / fixture["asv"]["expected_population_authority_path"]).read_text(
            encoding="utf-8"
        )
    )
    hostile_asv = copy.deepcopy(fixture["asv"])
    hostile_asv["expected_members"][0]["id"] = StringLike(
        hostile_asv["expected_members"][0]["id"]
    )
    with pytest.raises(ContractError):
        validate_asv_authority_payload(asv_authority, hostile_asv)

    hostile_preflight = copy.deepcopy(fixture)
    hostile_preflight["asv"]["expected_population_authority_path"] = StringLike(
        fixture["asv"]["expected_population_authority_path"]
    )
    with pytest.raises(ContractError):
        raw_environment_preflight(REPO_ROOT, hostile_preflight)

    hostile_dependencies = copy.deepcopy(fixture)
    hostile_dependencies["dependencies"][0][0] = StringLike(
        hostile_dependencies["dependencies"][0][0]
    )
    with pytest.raises(ContractError):
        fixture_module._dependency_specs(REPO_ROOT, hostile_dependencies)

    spurgeon_payload = json.loads(
        (
            REPO_ROOT / fixture["spurgeon"]["expected_population_authority_path"]
        ).read_text(encoding="utf-8")
    )
    for mutation in ("float-count", "float-id", "custom-count"):
        hostile = copy.deepcopy(spurgeon_payload)
        if mutation == "float-count":
            hostile["source"]["file_count"] = 3547.0
        elif mutation == "float-id":
            hostile["source"]["scope"]["selected_sermons"][0] = 1.0
        else:
            hostile["source"]["file_count"] = IntLike(3547)
        assessment = validate_spurgeon_authority_payload(
            hostile,
            fixture["spurgeon"],
            REPO_ROOT,
            family_member_names=("1.html",),
        )
        assert assessment.valid is False


def test_historical_bcp_probe_never_coerces_hostile_fields_or_leaks_type_errors() -> None:
    class StringLike:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    fixture = load_fixture()
    path = fixture["bcp"]["historical_contrary_evidence"]["evidence_path"]
    payload = json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))

    hostile_commit = copy.deepcopy(payload)
    hostile_commit["commit"] = StringLike(hostile_commit["commit"])
    result = verify_historical_bcp_probe(REPO_ROOT, hostile_commit)
    assert result.valid is False
    assert result.ledger_result == "UNKNOWN"
    assert result.independent_result == "UNKNOWN"

    hostile_path = copy.deepcopy(payload)
    hostile_path["inputs"][0]["path"] = StringLike(hostile_path["inputs"][0]["path"])
    result = verify_historical_bcp_probe(REPO_ROOT, hostile_path)
    assert result.valid is False
    assert result.ledger_result == "UNKNOWN"

    scalar_inputs = copy.deepcopy(payload)
    scalar_inputs["inputs"] = "not-a-sequence"
    result = verify_historical_bcp_probe(REPO_ROOT, scalar_inputs)
    assert result.valid is False
    assert result.ledger_result == "UNKNOWN"


@pytest.mark.parametrize(
    ("field_path", "value"),
    (
        (("commit_date",), "not-an-instant"),
        (("algorithm", "description"), 17),
        (("interpretation",), {"not": "text"}),
        (("inputs", 0, "byte_length"), 1.0),
    ),
)
def test_historical_nested_authority_fields_fail_closed(
    field_path: tuple[object, ...],
    value: object,
) -> None:
    fixture = load_fixture()
    path = fixture["bcp"]["historical_contrary_evidence"]["evidence_path"]
    payload = json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))
    target: object = payload
    for key in field_path[:-1]:
        target = target[key]  # type: ignore[index]
    target[field_path[-1]] = value  # type: ignore[index]
    result = verify_historical_bcp_probe(REPO_ROOT, payload)
    assert result.valid is False
    assert result.ledger_result == "UNKNOWN"
    assert result.independent_result == "UNKNOWN"


@pytest.mark.requires_local_artifacts
def test_asv_arbitrary_verse_objects_fail_closed() -> None:
    fixture = load_fixture()
    authority = json.loads(
        (REPO_ROOT / fixture["asv"]["expected_population_authority_path"]).read_text(
            encoding="utf-8"
        )
    )
    hostile = copy.deepcopy(authority)
    hostile["books"][0]["chapters"][0]["verses"][0] = object()
    with pytest.raises(ContractError):
        validate_asv_authority_payload(hostile, fixture["asv"])


@pytest.mark.parametrize(
    ("side", "field", "value"),
    (
        ("source", "probes", ["first", "last", "empty", "longest", "shortest", "orphan-both-directions"]),
        ("output", "probes", ["first", "last", "empty", "longest", "shortest", "orphan-both-directions"]),
        ("source", "probes", ("made-up-probe",)),
        ("output", "probes", ("made-up-probe",)),
        ("source", "text", 123),
        ("output", "text", 123),
        ("source", "frame_id", 123),
        ("output", "frame_id", 123),
        ("source", "authority_id", 123),
        ("output", "scope_id", 123),
    ),
)
def test_sampling_revalidates_mutated_frames_at_consumption(
    side: str,
    field: str,
    value: object,
) -> None:
    policy = RiskPolicyMatrix.from_payload(load_fixture()["risk_policy"]).for_tiers(["A"])
    probes = ("first", "last", "empty", "longest", "shortest", "orphan-both-directions")
    source, output, source_authority, output_authority = _sampling_population(probes)
    target = source[0] if side == "source" else output[0]
    object.__setattr__(target, field, value)
    with pytest.raises(ContractError):
        _evaluate(policy, source, output, source_authority, output_authority)
