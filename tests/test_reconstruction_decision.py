from __future__ import annotations

from collections.abc import Mapping
import importlib.util
import json
from pathlib import Path

import pytest

import ocd_kernel.reconstruction as reconstruction
from ocd_kernel.reconstruction.decision import (
    blocker_record,
    catalog_decision,
    decision_path,
    decision_record,
    serialize_decision,
)


_HELPER_SPEC = importlib.util.spec_from_file_location(
    "_lib003_reconstruction_contract_helpers",
    Path(__file__).with_name("test_reconstruction_contract.py"),
)
assert _HELPER_SPEC is not None and _HELPER_SPEC.loader is not None
_HELPER_MODULE = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(_HELPER_MODULE)
_canonical = _HELPER_MODULE._canonical
_fixture = _HELPER_MODULE._fixture
_sha = _HELPER_MODULE._sha


SOURCE_ID = "fixture"
WORK_ID = "fixture-work"


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _write_validation_report(
    path: Path, report: reconstruction.ValidationReport
) -> None:
    record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": _jsonable(report.attestation),
        "findings": list(report.findings),
    }
    path.write_bytes(_canonical({**record, "report_sha256": _sha(_canonical(record))}))


def _context(tmp_path: Path, *, with_decision: bool = True) -> dict[str, object]:
    source, converter, oracle = _fixture(tmp_path)
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)
    validation = reconstruction.validate(source, candidate, oracle)
    validation_path = tmp_path / "validation.json"
    _write_validation_report(validation_path, validation)
    review = reconstruction.prepare_review(source, candidate, validation)
    decision_file = decision_path(source.path, source_id=SOURCE_ID, work_id=WORK_ID)
    if with_decision:
        decision = decision_record(
            source,
            review,
            work_id=WORK_ID,
            disposition="accepted",
            rationale="The exact fixture candidate and independent validation passed review.",
            decided_by="project-maintainer",
            decided_at="2026-08-27T00:00:00Z",
        )
        decision_file.write_bytes(serialize_decision(decision))
    return {
        "source": source,
        "candidate": candidate,
        "validation": validation,
        "validation_path": validation_path,
        "decision_path": decision_file,
        "root": tmp_path,
    }


def _catalog_decision(context: dict[str, object]) -> dict[str, object] | None:
    source = context["source"]
    assert isinstance(source, reconstruction.SourceManifest)
    candidate = context["candidate"]
    candidate_path = (
        candidate.path
        if isinstance(candidate, reconstruction.CandidatePackage)
        else candidate
    )
    return catalog_decision(
        source.path,
        repository_root=source.repository_root,
        source_id=SOURCE_ID,
        work_id=WORK_ID,
        candidate_path=candidate_path,
        validation_path=context["validation_path"],
    )


def test_generic_decision_contract_round_trips_source_local_evidence(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    observed = _catalog_decision(context)

    assert observed is not None
    assert observed["disposition"] == "accepted"
    assert observed["candidate_sha256"] == context["candidate"].sha256
    assert observed["validation_sha256"] == context["validation"].sha256
    assert observed["path"] == "fixture--fixture-work.decision.json"


def test_decision_loader_verifies_optional_text_screen_without_changing_oracle_digest(tmp_path):
    from build.lib.reconstruction_text_screen import screen_reconstruction
    from ocd_kernel.reconstruction.decision import _load_validation_report
    from ocd_kernel.reconstruction.text_quality import verify_text_quality

    context = _context(tmp_path)
    source, candidate = context["source"], context["candidate"]
    text_path = tmp_path / "text-quality.json"
    text_path.write_bytes(_canonical(screen_reconstruction(source, candidate)))
    validation_path = context["validation_path"]
    record = json.loads(validation_path.read_bytes())
    record["text_quality_sha256"] = _sha(text_path.read_bytes())
    validation_path.write_bytes(_canonical(record))
    assert verify_text_quality(text_path, record["text_quality_sha256"], source, candidate) is None
    assert _load_validation_report(validation_path, source, candidate).sha256 == context["validation"].sha256
    text_path.write_bytes(text_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="text-quality report digest mismatch"):
        _load_validation_report(validation_path, source, candidate)


def test_generic_decision_rejects_unstructured_blocked_disposition(
    tmp_path: Path,
) -> None:
    source, converter, oracle = _fixture(tmp_path)
    candidate = reconstruction.reconstruct(source, tmp_path / "candidate", converter)
    validation = reconstruction.validate(source, candidate, oracle)
    review = reconstruction.prepare_review(source, candidate, validation)

    with pytest.raises(ValueError, match="disposition is not supported"):
        decision_record(
            source,
            review,
            work_id=WORK_ID,
            disposition="blocked",
            rationale="An unstructured rationale is not a technical blocker record.",
            decided_by="project-maintainer",
            decided_at="2026-08-27T00:00:00Z",
        )


def _technical_blocker(context: dict[str, object]) -> dict[str, object]:
    source = context["source"]
    assert isinstance(source, reconstruction.SourceManifest)
    evidence_path = source.repository_root / "acquisition-evidence.txt"
    evidence_path.write_text(
        "The retained source member is unavailable from the named acquisition route.\n",
        encoding="utf-8",
        newline="\n",
    )
    relative_evidence = evidence_path.relative_to(source.repository_root).as_posix()
    return blocker_record(
        source.path,
        repository_root=source.repository_root,
        source_id=SOURCE_ID,
        work_id=WORK_ID,
        blocker={
            "kind": "acquisition",
            "dependency": "named fixture source acquisition",
            "evidence": [
                {"path": relative_evidence, "sha256": _sha(evidence_path.read_bytes())}
            ],
            "attempted_routes": [
                {
                    "route": "retained fixture member",
                    "outcome": "source member unavailable",
                    "evidence_refs": [relative_evidence],
                }
            ],
            "owner": "source-acquisition",
            "next_action": "Acquire the exact retained fixture source member.",
            "reopening_condition": "The source member is retained and hashable.",
        },
        decided_by="technical-reviewer",
        decided_at="2026-08-27T00:00:00Z",
    )


def test_structured_blocker_round_trips_when_declared_source_is_unavailable(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, with_decision=False)
    source = context["source"]
    assert isinstance(source, reconstruction.SourceManifest)
    record = _technical_blocker(context)
    context["decision_path"].write_bytes(serialize_decision(record))
    source.authority_path("source-part-0").unlink()

    observed = catalog_decision(
        source.path,
        repository_root=source.repository_root,
        source_id=SOURCE_ID,
        work_id=WORK_ID,
    )

    assert observed is not None
    assert observed["disposition"] == "blocked"
    assert observed["blocker"]["kind"] == "acquisition"
    assert observed["blocker"]["owner"] == "source-acquisition"
    assert "candidate_sha256" not in observed


def test_structured_blocker_accepts_configured_external_raw_evidence(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    library_root = tmp_path / "library"
    repository_root.mkdir()
    (repository_root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library_root)}) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_path = repository_root / "sources" / "fixture.source-manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_bytes(
        _canonical(
            {
                "contract": "ocd-source-manifest-v1",
                "source_id": SOURCE_ID,
                "work_id": WORK_ID,
            }
        )
    )
    evidence_relative = "raw/fixture/acquisition-evidence.txt"
    evidence_path = library_root / evidence_relative
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_bytes(b"retained acquisition evidence\n")

    record = blocker_record(
        manifest_path,
        repository_root=repository_root,
        source_id=SOURCE_ID,
        work_id=WORK_ID,
        blocker={
            "kind": "source",
            "dependency": "exact retained source evidence",
            "evidence": [
                {"path": evidence_relative, "sha256": _sha(evidence_path.read_bytes())}
            ],
            "attempted_routes": [
                {
                    "route": "configured raw storage",
                    "outcome": "retained evidence proves the source dependency",
                    "evidence_refs": [evidence_relative],
                }
            ],
            "owner": "source-acquisition",
            "next_action": "Acquire the missing retained source member.",
            "reopening_condition": "The exact member is retained and hashable.",
        },
        decided_by="technical-reviewer",
        decided_at="2026-08-27T00:00:00Z",
    )

    assert record["blocker"]["evidence"][0]["path"] == evidence_relative


def test_structured_blocker_rejects_stale_evidence(tmp_path: Path) -> None:
    context = _context(tmp_path, with_decision=False)
    source = context["source"]
    assert isinstance(source, reconstruction.SourceManifest)
    record = _technical_blocker(context)
    context["decision_path"].write_bytes(serialize_decision(record))
    (source.repository_root / "acquisition-evidence.txt").write_text(
        "drifted evidence\n", encoding="utf-8", newline="\n"
    )

    with pytest.raises(ValueError, match="evidence digest is stale"):
        catalog_decision(
            source.path,
            repository_root=source.repository_root,
            source_id=SOURCE_ID,
            work_id=WORK_ID,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("kind", "effort", "kind is not admissible"),
        ("owner", "", "owner must be a nonempty string"),
        ("next_action", "", "next_action must be a nonempty string"),
        ("reopening_condition", "", "reopening_condition must be a nonempty string"),
    ],
)
def test_structured_blocker_requires_admissible_complete_evidence(
    tmp_path: Path,
    field: str,
    value: str,
    match: str,
) -> None:
    context = _context(tmp_path, with_decision=False)
    record = _technical_blocker(context)
    blocker = dict(record["blocker"])
    blocker[field] = value
    record["blocker"] = blocker

    with pytest.raises(ValueError, match=match):
        blocker_record(
            context["source"].path,
            repository_root=context["source"].repository_root,
            source_id=SOURCE_ID,
            work_id=WORK_ID,
            blocker=blocker,
            decided_by="technical-reviewer",
            decided_at="2026-08-27T00:00:00Z",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "candidate",
        "validator",
        "policy",
        "schema",
        "closure",
        "decision",
        "evidence_path",
    ],
)
def test_generic_decision_evidence_mutations_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    context = _context(tmp_path)
    source = context["source"]
    assert isinstance(source, reconstruction.SourceManifest)

    if mutation == "source":
        source.authority_path("source-part-0").write_bytes(b"source drift")
    elif mutation == "candidate":
        candidate = context["candidate"]
        candidate.path.joinpath("content.tei.xml").write_bytes(b"candidate drift")
    elif mutation == "validator":
        validator = source.record["validator"]
        assert isinstance(validator, Mapping)
        (source.repository_root / str(validator["implementation_path"])).write_bytes(
            b"validator drift\n"
        )
    elif mutation == "policy":
        source.authority_path("independent-validation-policy").write_bytes(
            b"policy drift\n"
        )
    elif mutation == "schema":
        source.authority_path("candidate-package-schema").write_bytes(b"schema drift\n")
    elif mutation == "closure":
        record = json.loads(source.path.read_bytes())
        record["validator"]["import_closure_sha256"] = "b" * 64
        source.path.write_bytes(_canonical(record))
    elif mutation == "decision":
        decision_path = context["decision_path"]
        record = json.loads(decision_path.read_bytes())
        record["disposition"] = "machine-approved"
        decision_path.write_bytes(_canonical(record))
    else:
        context["candidate"] = context["root"] / "missing-candidate"

    with pytest.raises(ValueError):
        _catalog_decision(context)


def _work() -> dict[str, object]:
    return {
        "work_id": WORK_ID,
        "reconstruction_state": {
            "retained_source": "not_assessed",
            "tei_candidate": "not_started",
            "validation": "not_run",
            "human_review": "not_started",
            "accepted_ir": "not_accepted",
            "blocker": None,
            "publication": "not_ready",
            "routes": [],
        },
    }


def test_work_catalog_uses_explicit_runtime_evidence_not_manifest_paths(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, with_decision=False)
    source = context["source"]
    assert isinstance(source, reconstruction.SourceManifest)
    manifest = json.loads(source.path.read_bytes())
    manifest["candidate_path"] = str(context["candidate"].path)
    manifest["validation_path"] = str(context["validation_path"])
    import build.tools.count_dataset_records as catalog_module

    without_runtime_evidence = _work()
    catalog_module._attach_reconstruction_route(
        without_runtime_evidence,
        manifest,
        source.path,
        source.repository_root / "sources",
        association="source_hash",
        scope="work",
        verified=True,
        blocker=None,
    )
    assert without_runtime_evidence["reconstruction_state"]["tei_candidate"] == (
        "route_available"
    )

    with_runtime_evidence = _work()
    catalog_module._attach_reconstruction_route(
        with_runtime_evidence,
        manifest,
        source.path,
        source.repository_root / "sources",
        association="source_hash",
        scope="work",
        verified=True,
        blocker=None,
        candidate_path=context["candidate"].path,
        validation_path=context["validation_path"],
    )
    assert with_runtime_evidence["reconstruction_state"]["tei_candidate"] == "verified"
    assert with_runtime_evidence["reconstruction_state"]["validation"] == "verified"


def test_partial_runtime_evidence_never_accepts_or_publishes_a_work(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, with_decision=True)
    source = context["source"]
    assert isinstance(source, reconstruction.SourceManifest)
    import build.tools.count_dataset_records as catalog_module

    work = _work()
    catalog_module._attach_reconstruction_route(
        work,
        json.loads(source.path.read_bytes()),
        source.path,
        source.repository_root / "sources",
        association="source_hash",
        scope="partial",
        verified=True,
        blocker=None,
        candidate_path=context["candidate"].path,
        validation_path=context["validation_path"],
    )

    state = work["reconstruction_state"]
    assert state["tei_candidate"] == "partial"
    assert state["validation"] == "partial"
    assert state["human_review"] == "required"
    assert state["accepted_ir"] == "not_accepted"
    assert state["publication"] == "not_ready"
    assert state["routes"][0]["decision"]["disposition"] == "accepted"


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_complete_route_decisions_fail_independent_of_order(
    reverse: bool,
) -> None:
    import build.tools.count_dataset_records as catalog_module

    work = _work()
    routes = [
        {
            "association": "source_hash",
            "manifest": f"sources/{disposition}.source-manifest.json",
            "scope": "work",
            "source_id": disposition,
            "verification": "verified",
            "candidate_verification": "verified",
            "validation_verification": "verified",
            "decision": {"disposition": disposition},
        }
        for disposition in ("accepted", "rejected")
    ]
    if reverse:
        routes.reverse()
    work["reconstruction_state"]["routes"] = routes

    with pytest.raises(ValueError, match="multiple source-local decisions"):
        catalog_module._derive_reconstruction_state(work)


@pytest.mark.parametrize("reverse", [False, True])
def test_complete_route_precedence_over_partial_route_is_order_independent(
    reverse: bool,
) -> None:
    import build.tools.count_dataset_records as catalog_module

    work = _work()
    routes = [
        {
            "association": "source_hash",
            "manifest": "sources/full.source-manifest.json",
            "scope": "work",
            "source_id": "full",
            "verification": "verified",
        },
        {
            "association": "source_hash",
            "manifest": "sources/partial.source-manifest.json",
            "scope": "partial",
            "source_id": "partial",
            "verification": "verified",
        },
    ]
    if reverse:
        routes.reverse()
    work["reconstruction_state"]["routes"] = routes

    catalog_module._derive_reconstruction_state(work)

    state = work["reconstruction_state"]
    assert state["retained_source"] == "manifest_bound"
    assert state["blocker"] is None
    assert state["publication"] == "not_ready"


@pytest.mark.parametrize("reverse", [False, True])
def test_partial_evidence_failure_is_route_local_when_complete_candidate_exists(
    reverse: bool,
) -> None:
    import build.tools.count_dataset_records as catalog_module

    work = _work()
    routes = [
        {
            "association": "source_hash",
            "manifest": "sources/full.source-manifest.json",
            "scope": "work",
            "source_id": "full",
            "verification": "verified",
            "candidate_verification": "verified",
            "validation_verification": "verified",
        },
        {
            "association": "source_hash",
            "manifest": "sources/partial.source-manifest.json",
            "scope": "partial",
            "source_id": "partial",
            "verification": "verified",
            "candidate_verification": "blocked",
            "validation_verification": "blocked",
            "blocker": "partial alternate evidence is stale",
        },
    ]
    if reverse:
        routes.reverse()
    work["reconstruction_state"]["routes"] = routes

    catalog_module._derive_reconstruction_state(work)

    state = work["reconstruction_state"]
    assert state["retained_source"] == "manifest_bound"
    assert state["tei_candidate"] == "verified"
    assert state["validation"] == "verified"
    assert state["human_review"] == "required"
    assert state["accepted_ir"] == "not_accepted"
    assert state["blocker"] is None
    assert state["publication"] == "not_ready"


@pytest.mark.parametrize("reverse", [False, True])
def test_partial_structured_blocker_is_route_local_when_complete_route_exists(
    reverse: bool,
) -> None:
    import build.tools.count_dataset_records as catalog_module

    work = _work()
    routes = [
        {
            "association": "source_hash",
            "manifest": "sources/full.source-manifest.json",
            "scope": "work",
            "source_id": "full",
            "verification": "verified",
        },
        {
            "association": "source_hash",
            "manifest": "sources/partial.source-manifest.json",
            "scope": "partial",
            "source_id": "partial",
            "verification": "verified",
            "decision": {
                "disposition": "blocked",
                "blocker": {
                    "dependency": "partial route source acquisition",
                },
            },
        },
    ]
    if reverse:
        routes.reverse()
    work["reconstruction_state"]["routes"] = routes

    catalog_module._derive_reconstruction_state(work)

    state = work["reconstruction_state"]
    assert state["retained_source"] == "manifest_bound"
    assert state["tei_candidate"] == "route_available"
    assert state["validation"] == "validator_available"
    assert state["human_review"] == "required"
    assert state["accepted_ir"] == "not_accepted"
    assert state["blocker"] is None
    assert state["publication"] == "not_ready"
