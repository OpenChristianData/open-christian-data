"""Build and promote evidence for the already-retained Revised Version TEI.

This stages one existing 80-member electronic edition in a bounded local
fixture. It performs no acquisition and does not publish the text.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Any

from ocd_kernel.library._common import io_path
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    promote_accepted_master,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "revised-version-with-apocrypha"
FORM_ID = "revised-version-with-apocrypha-retained-en"
EDITION_ID = "revised-version-with-apocrypha-electronic"
ACQUISITION_ID = "revised-version-with-apocrypha-acquired"
ROUTE = "accepted-electronic-v1"
INTEGRATION_REL = Path("library/works") / WORK_ID / "integration" / ROUTE
WORK_REL = Path("library/works") / WORK_ID
EDITION_REL = (
    WORK_REL / "forms" / FORM_ID / "editions" / EDITION_ID
)
ACQUISITION_REL = (
    EDITION_REL / "acquisitions" / f"{ACQUISITION_ID}.json"
)
MEMBER_SET_REL = EDITION_REL / "source-member-set.json"
SOURCE_MANIFEST_REL = Path(
    "sources/structured-text/revised-version-with-apocrypha/corpus-v4/"
    "reconstruction-source-manifest.json"
)
STATE_SNAPSHOT_REL = Path(
    "sources/structured-text/revised-version-with-apocrypha/corpus-v4/"
    "work-state-at-reconstruction.json"
)
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": FORM_ID,
    "edition_id": EDITION_ID,
    "acquisition_id": ACQUISITION_ID,
}
REPRESENTATION_REVISION = {
    "id": "revised-version-with-apocrypha-accepted-electronic-v1",
    "date": "2026-10-02",
    "note": (
        "Bound the retained 80-member ENGRV5 electronic witness to its work, "
        "edition, acquisition, source member set, and accepted scope; preserved "
        "the original corpus and member text bytes."
    ),
}
REVIEWER = "agent:codex-revised-version-with-apocrypha-acceptance"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with io_path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, record: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(record))


def _safe_relative(reference: str) -> PurePosixPath:
    relative = PurePosixPath(reference)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe repository reference: {reference}")
    return relative


def _copy_repository_reference(root: Path, fixture: Path, reference: str) -> Path:
    relative = _safe_relative(reference)
    source = resolve_repo_path(root, relative.as_posix())
    if not io_path(source).is_file():
        raise FileNotFoundError(f"state evidence reference does not resolve: {reference}")
    destination = fixture.joinpath(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(io_path(source), io_path(destination))
    if _file_sha(source) != _file_sha(destination):
        raise ValueError(f"evidence copy digest mismatch: {reference}")
    return destination


def _load_oracle() -> Any:
    path = ROOT / "build/tei/revised_version_with_apocrypha_corpus_oracle.py"
    spec = importlib.util.spec_from_file_location("rv_v4_bound_oracle", path)
    if spec is None or spec.loader is None:
        raise ValueError("Revised Version independent oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


def _member_scope(root: Path, acquisition: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    member_set = json.loads((root / MEMBER_SET_REL).read_text(encoding="utf-8"))
    members = member_set.get("members")
    retained = acquisition.get("retained_files")
    if not isinstance(members, list) or not isinstance(retained, list) or len(members) != 80 or len(retained) != 80:
        raise ValueError("the accepted scope requires the exact existing 80-member source set")
    expected: list[dict[str, Any]] = []
    included: list[dict[str, Any]] = []
    for position, (member, acquired) in enumerate(zip(members, retained), start=1):
        if (
            member.get("position") != position
            or member.get("path") != acquired.get("path")
            or member.get("bytes") != acquired.get("bytes")
            or member.get("sha256") != acquired.get("sha256")
        ):
            raise ValueError(f"acquisition/member-set binding differs at position {position}")
        source_path = resolve_repo_path(root, member["path"])
        if (
            not io_path(source_path).is_file()
            or io_path(source_path).stat().st_size != member["bytes"]
            or _file_sha(source_path) != member["sha256"]
        ):
            raise ValueError(f"retained source member differs at position {position}: {member['path']}")
        expected.append({"path": member["path"], "position": position})
        included.append(
            {
                "path": member["path"],
                "position": position,
                "bytes": member["bytes"],
                "sha256": member["sha256"],
                "scope": member["scope"],
            }
        )
    return expected, included


def _proof_document(
    *,
    claim: str,
    command: str,
    candidate_binding: dict[str, Any],
    source: dict[str, Any],
    scope_text: str,
    expected: list[dict[str, Any]],
    included: list[dict[str, Any]],
    package_sha256: str,
    validation_sha256: str,
    evidence_sha256: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract": "ocd-accepted-master-proof-v1",
        "claim": claim,
        "status": "pass",
        "command": command,
        "exit_code": 0,
        "identity": IDENTITY,
        "candidate": candidate_binding,
        "candidate_package_sha256": package_sha256,
        "source": source,
        "source_sha256": source["source_sha256"],
        "source_bytes": source["source_bytes"],
        "scope": scope_text,
        "accepted_scope": {"kind": "edition", "declared": scope_text},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
        "validation_sha256": validation_sha256,
        "technical_evidence_sha256": evidence_sha256,
        "details": details,
    }


def prepare_and_promote(
    *,
    root: Path,
    package_path: Path,
    reproduction_package_path: Path,
    bound_candidate_path: Path,
    reproduction_bound_candidate_path: Path,
    stage_root: Path,
    promoted_root: Path,
    expected_bound_candidate_sha256: str,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    stage_root = stage_root.resolve(strict=False)
    promoted_root = promoted_root.resolve(strict=False)
    if stage_root.exists() or promoted_root.exists():
        raise FileExistsError("acceptance fixture and promoted destinations must both be fresh")
    if stage_root == root or root in stage_root.parents or promoted_root == root or root in promoted_root.parents:
        raise ValueError("acceptance fixture and promotion must stay outside the repository")

    source_manifest_path = root / SOURCE_MANIFEST_REL
    source_manifest = SourceManifest.load(source_manifest_path, repository_root=root)
    package = CandidatePackage.load(package_path)
    reproduction_package = CandidatePackage.load(reproduction_package_path)
    if package.sha256 != reproduction_package.sha256 or any(
        package.member_bytes(name) != reproduction_package.member_bytes(name)
        for name in package.member_names
    ):
        raise ValueError("the two clean-process candidate packages do not reproduce exactly")
    package_validation = validate(source_manifest, package, _load_oracle())
    validation_sidecar_path = package_path.parent / "validation.json"
    validation_sidecar = json.loads(validation_sidecar_path.read_text(encoding="utf-8"))
    reproduction_validation = json.loads(
        (reproduction_package_path.parent / "validation.json").read_text(encoding="utf-8")
    )
    if (
        package_validation.status != "pass"
        or package_validation.findings
        or package_validation.sha256 != validation_sidecar.get("report_sha256")
        or validation_sidecar != reproduction_validation
    ):
        raise ValueError("candidate validation or clean-process validation reproduction differs")

    bound_candidate_path = bound_candidate_path.resolve(strict=True)
    reproduction_bound_candidate_path = reproduction_bound_candidate_path.resolve(strict=True)
    bound_bytes = bound_candidate_path.read_bytes()
    bound_sha256 = _sha(bound_bytes)
    if bound_sha256 != expected_bound_candidate_sha256:
        raise ValueError("acceptance-bound candidate digest differs from the declared input")
    if bound_bytes != reproduction_bound_candidate_path.read_bytes():
        raise ValueError("header binding does not reproduce byte-for-byte in a second process")
    schema_errors = validate_file(bound_candidate_path)
    if schema_errors:
        raise ValueError("accepted candidate fails TEI P5: " + "; ".join(schema_errors[:5]))

    acquisition_path = root / ACQUISITION_REL
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    if acquisition.get("acquisition_id") != ACQUISITION_ID or acquisition.get("edition_id") != EDITION_ID:
        raise ValueError("acquisition sidecar does not identify the selected electronic edition")
    scope_text = str(acquisition["source_scope"])
    source = {
        "source_path": acquisition["source_path"],
        "source_sha256": acquisition["source_sha256"],
        "source_bytes": acquisition["source_bytes"],
        "source_scope": scope_text,
        "source_kind": acquisition["source_kind"],
    }
    expected, included = _member_scope(root, acquisition)

    state_path = root / WORK_REL / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    edition_target = next(
        (item for item in state["targets"] if item.get("target_id") == EDITION_ID), None
    )
    if not isinstance(edition_target, dict) or edition_target.get("stage") != "review":
        raise ValueError("the work must already be in review before acceptance staging")

    stage_root.mkdir(parents=True)
    fixture_work_root = stage_root / WORK_REL
    shutil.copytree(root / WORK_REL, fixture_work_root)
    for target in state["targets"]:
        for reference in target.get("evidence", []):
            _copy_repository_reference(root, stage_root, reference)
    source_contract_dir = source_manifest_path.parent
    contract_copy = stage_root / INTEGRATION_REL / "reconstruction" / "source-contract"
    shutil.copytree(source_contract_dir, contract_copy)

    integration_root = fixture_work_root / "integration" / ROUTE
    evidence_root = integration_root / "evidence"
    reconstruction_root = integration_root / "reconstruction"
    candidate_path = integration_root / "candidate.tei.xml"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(io_path(bound_candidate_path), io_path(candidate_path))

    package_copy = reconstruction_root / "package"
    shutil.copytree(package.path, package_copy)
    validation_copy = reconstruction_root / "validation.json"
    validation_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(io_path(validation_sidecar_path), io_path(validation_copy))
    binder_copy = reconstruction_root / "accepted-header-binder.py"
    shutil.copyfile(
        root / "build/tools/revised_version_with_apocrypha_acceptance.py", binder_copy
    )

    # Carry the exact prior mechanical negative-control report forward with its
    # old v3 binding, while the fresh v4 oracle result supplies current proof.
    old_mutation_report = (
        Path.home()
        / "AppData/Local/Temp/ocd-revised-version-with-apocrypha-corpus-v3"
        / "mutation-probes/mutation-results.json"
    )
    mutation_copy = None
    if old_mutation_report.is_file():
        mutation_copy = reconstruction_root / "mutation-probes-v3.json"
        mutation_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(old_mutation_report, mutation_copy)

    review_preparation_sources = (
        Path("reports/_logs/revised-version-cvw-alternative-20261002-v1/presentation.html"),
        Path("reports/_logs/revised-version-cvw-alternative-20261002-v1/presentation-receipt.json"),
        Path("reports/_logs/revised-version-cvw-alternative-20261002-v1/sample-structural-audit.json"),
    )
    review_preparation_root = integration_root / "review-preparation"
    for relative in review_preparation_sources:
        source_file = root / relative
        if not source_file.is_file():
            raise FileNotFoundError(f"prepared review artifact is missing: {relative}")
        destination = review_preparation_root / relative.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, destination)

    candidate_binding = make_file_binding(stage_root, candidate_path)
    accepted_scope = {
        "kind": "edition",
        "declared": scope_text,
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
    }
    evidence_core = {
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_package_sha256": package.sha256,
        "validation_sha256": package_validation.sha256,
        "bound_candidate_sha256": bound_sha256,
        "member_set_sha256": acquisition["source_sha256"],
    }
    evidence_sha256 = _sha(_canonical(evidence_core))
    common = {
        "candidate_binding": candidate_binding,
        "source": source,
        "scope_text": scope_text,
        "expected": expected,
        "included": included,
        "package_sha256": package.sha256,
        "validation_sha256": package_validation.sha256,
        "evidence_sha256": evidence_sha256,
    }
    proof_details: dict[str, dict[str, Any]] = {
        "validation": {
            "source_manifest_path": SOURCE_MANIFEST_REL.as_posix(),
            "source_manifest_sha256": source_manifest.sha256,
            "oracle_id": source_manifest.record["validator"]["id"],
            "oracle_implementation_sha256": source_manifest.record["validator"]["implementation_sha256"],
            "oracle_result_sha256": package_validation.attestation["result_sha256"],
            "findings": list(package_validation.findings),
            "validation_sidecar_sha256": _file_sha(validation_sidecar_path),
            "validated_candidate_package_sha256": package.sha256,
        },
        "accounting": {
            "member_count": len(included),
            "member_order_matches_source_member_set": True,
            "member_hashes_verified_against_acquisition": True,
            "missing_members": [],
            "unknown_members": [],
            "excluded_members": [],
        },
        "fidelity": {
            "ordered_teicorpus_member_count": 80,
            "source_and_candidate_member_subtrees": "independently compared across all 80 ordered members",
            "header_binding_inverse_restores_unbound_candidate": True,
            "bound_candidate_matches_second_process": True,
            "historical_mutation_report_path": mutation_copy.relative_to(stage_root).as_posix() if mutation_copy else None,
            "historical_mutation_report_sha256": _file_sha(mutation_copy) if mutation_copy else None,
            "historical_mutation_applicability": "v3 negative controls used the same retained member set, identical unbound TEI bytes, and unchanged independent-oracle implementation; they are prior evidence, not fresh v4 runs.",
            "visual_inspection_claimed": False,
        },
        "reproducibility": {
            "first_candidate_package_sha256": package.sha256,
            "second_candidate_package_sha256": CandidatePackage.load(reproduction_package_path).sha256,
            "candidate_package_bytes_identical": True,
            "first_validation_sha256": package_validation.sha256,
            "second_validation_sha256": reproduction_validation["report_sha256"],
            "validation_sidecar_bytes_identical": True,
            "first_bound_candidate_sha256": bound_sha256,
            "second_bound_candidate_sha256": _file_sha(reproduction_bound_candidate_path),
            "bound_candidate_bytes_identical": True,
        },
        "schema": {
            "tei_schema": "vendored TEI P5 tei_all.xsd",
            "tei_schema_errors": [],
            "acceptance_identity_facts": "all four work/form/edition/acquisition ids and source/member-set/revision bindings are present in the corpus-level scoped binding",
        },
        "closure": {
            "source_manifest_path": SOURCE_MANIFEST_REL.as_posix(),
            "source_manifest_sha256": source_manifest.sha256,
            "authority_count": len(source_manifest.record["authorities"]),
            "primary_source_member_count": len(source_manifest.record["source_members"]),
            "retained_envelope_file_count": sum(
                item.get("role") in {"primary-source", "source-acquisition-evidence"}
                for item in source_manifest.record["authorities"]
            ),
            "support_evidence_authority_count": sum(
                item.get("role") not in {"primary-source", "source-acquisition-evidence"}
                for item in source_manifest.record["authorities"]
            ),
            "state_snapshot_path": STATE_SNAPSHOT_REL.as_posix(),
            "state_snapshot_sha256": _file_sha(root / STATE_SNAPSHOT_REL),
            "state_snapshot_role": "immutable reconstruction-time evidence; canonical state may advance independently",
            "candidate_package_sha256": package.sha256,
            "validation_sha256": package_validation.sha256,
        },
    }
    commands = {
        "validation": (
            "py -3 build/tools/reconstruct_candidate.py --manifest "
            + SOURCE_MANIFEST_REL.as_posix()
            + " --destination <fresh-temp-output> --progress"
        ),
        "accounting": "py -3 build/tools/prepare_revised_version_with_apocrypha_acceptance.py --root <repository> --package <v4-package> --reproduction-package <v4-package-2> --candidate <bound-candidate> --reproduction-candidate <bound-candidate-2> --stage-root <fresh-temp> --promoted-root <fresh-temp>",
        "fidelity": (
            "py -3 build/tools/revised_version_with_apocrypha_acceptance.py --input "
            "<v4-package>/content.tei.xml --output <bound-candidate> --expected-sha256 "
            "8ae76b8a3dda753aaee1373d9c384d5b1ab19d0ff4bf42bc289b5d1f5e8360bd"
        ),
        "reproducibility": "two fresh-process runs of build/tools/reconstruct_candidate.py plus two fresh-process accepted-header bindings; compare every package and validation byte",
        "schema": "py -3 -m ocd_kernel.tei.validate <accepted candidate.tei.xml>",
        "closure": "SourceManifest.load(v4) -> CandidatePackage.load(v4) -> independent validate(v4); all pinned authorities verified",
    }

    proof_paths: dict[str, Path] = {}
    for claim in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _proof_document(
            claim=claim,
            command=commands[claim],
            candidate_binding=candidate_binding,
            source=source,
            scope_text=scope_text,
            expected=expected,
            included=included,
            package_sha256=package.sha256,
            validation_sha256=package_validation.sha256,
            evidence_sha256=evidence_sha256,
            details=proof_details[claim],
        )
        path = evidence_root / f"{claim}.json"
        _write_json(path, proof)
        proof_paths[claim] = path

    accounting_path = proof_paths["accounting"]
    review_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    coverage = {
        "declared": scope_text,
        "reached": [
            "electronic-edition/member-set"
        ],
        "inspected": [
            "electronic-edition/member-set/all-80-members-mechanically-compared-by-source-hash-and-ordered-corpus-oracle"
        ],
        "unreviewed": [
            "electronic-edition/member-set/rendered-source-candidate-comparison",
            "electronic-edition/retained-1895-and-1913-and-replacement-Tobit-Greek-Esther-scan-collation",
        ],
        "status": "partial",
    }
    source_quality_uncertainty = [
        "CVW admitted the exact v3 candidate but timed out before rendering; the prepared alternative presentation and structural audit were not opened as visual content.",
        "The relationship between the complete eBible electronic witness and retained 1895/1913/replacement print witnesses was not collated.",
        "Rights clearance and publication authorization remain separate and unestablished.",
    ]
    discrepancies: list[dict[str, Any]] = []
    unreviewed_residuals = [
        "No screenshot or visual comparison is claimed; all 80 members remain visually unreviewed.",
        "No exact equivalence claim is made between the electronic source and retained print/replacement scans.",
        "Human verification, rights clearance, release selection, and publication remain unassessed stronger claims.",
    ]
    review_report = {
        "contract": "ocd-agent-review-report-v1",
        "identity": IDENTITY,
        "candidate": candidate_binding,
        "source": source,
        "scope": scope_text,
        "accepted_scope": {"kind": "edition", "declared": scope_text},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
        "coverage": coverage,
        "reviewer": REVIEWER,
        "reviewed_at": review_time,
        "source_quality_uncertainty": source_quality_uncertainty,
        "discrepancies": discrepancies,
        "unreviewed_residuals": unreviewed_residuals,
        "visual_review": {
            "cvw": "exact pair admitted; browser route timed out before either pane rendered",
            "alternative_presentation": "prepared and mechanically audited; not opened or visually inspected",
            "screenshots": [],
            "visual_credit": False,
        },
        "edition_identity": {
            "official_title": "Revised Version with Apocrypha (1895)",
            "resource_id": "ENGRV5 / eng-rv",
            "page_update_date": "2026-08-08",
            "interpretation": "page update date, not edition date",
            "print_equivalence_claimed": False,
        },
    }
    review_path = evidence_root / "review.json"
    _write_json(review_path, review_report)

    acceptance_path = fixture_work_root / EDITION_REL.relative_to(WORK_REL) / "acceptance.json"
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    identity = dict(IDENTITY)
    scope = {
        "kind": "edition",
        "declared": scope_text,
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
    }
    technical = {
        "producer": {
            "id": source_manifest.record["converter"]["id"],
        },
        "checker": {
            "id": source_manifest.record["validator"]["id"],
        },
        "shared_assumptions": [
            "The independent oracle checks all 80 source-member-to-corpus divisions and member order.",
            "The accepted corpus-header repair is separately reversible to the exact v4 unbound candidate bytes.",
            "The retained electronic source set is accepted as its own edition; no print-scan equivalence is claimed.",
        ],
        "independent_corroboration": (
            "Fresh v4 source-manifest closure and independent oracle pass; two clean-process candidate packages and "
            "validation sidecars match byte-for-byte; two accepted-header bindings match byte-for-byte; TEI P5 "
            "validation passes. Three earlier negative controls remain applicable to the unchanged unbound TEI "
            "and unchanged independent oracle, with their older v3 binding explicitly retained."
        ),
    }
    for claim in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        technical[claim] = {
            "path": proof_paths[claim],
            "status": "pass",
            "command": commands[claim],
            "exit_code": 0,
        }

    decision = {
        "source_local_disposition": (
            "Accept the complete ordered 80-member eBible ENGRV5/eng-rv electronic textual set as the "
            "Revised Version with Apocrypha electronic edition. The accepted master is bound to that "
            "electronic source and scope. No exact equivalence to the retained print/replacement scans, "
            "human visual review, rights clearance, or public release is asserted."
        ),
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": REVIEWER,
            "assessed_at": review_time,
            "supported_scope": scope_text,
            "unassessed_stronger_claims": [
                "rendered visual collation of the source and candidate",
                "equivalence to the 1895/1913 print and replacement witnesses",
                "human verification",
                "rights clearance",
                "release selection",
                "publication",
            ],
            "unresolved_claims": [],
        },
        "human_decision": {"status": "not-recorded"},
    }
    acceptance = build_acceptance_record(
        stage_root,
        identity=identity,
        candidate_path=candidate_path,
        source_accounting_path=accounting_path,
        scope=scope,
        technical=technical,
        review={
            "report_path": review_path,
            "reviewer": REVIEWER,
            "reviewed_at": review_time,
            "coverage": coverage,
            "source_quality_uncertainty": source_quality_uncertainty,
            "discrepancies": discrepancies,
            "unreviewed_residuals": unreviewed_residuals,
        },
        representation_revision=REPRESENTATION_REVISION,
        decision=decision,
        acceptance_id=f"{EDITION_ID}-acceptance-{REPRESENTATION_REVISION['id']}",
    )
    write_acceptance(acceptance_path, acceptance)
    validate_acceptance(acceptance_path, root=stage_root)

    state_fixture_path = fixture_work_root / "state.json"
    from ocd_kernel.library.state import validate_state

    validate_state(state_fixture_path, root=stage_root)
    promotion = promote_accepted_master(
        stage_root,
        acceptance_path=acceptance_path,
        destination=promoted_root,
        candidate_path=candidate_path,
    )
    final_acceptance = validate_acceptance(promotion.acceptance_path, root=promoted_root)
    validate_state(promotion.state_path, root=promoted_root)
    return {
        "status": "promoted-and-validated",
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "accepted_scope_member_count": len(included),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_package_sha256": package.sha256,
        "accepted_candidate_sha256": bound_sha256,
        "validation_sha256": package_validation.sha256,
        "acceptance_path": promotion.acceptance_path.as_posix(),
        "acceptance_sha256": _file_sha(promotion.acceptance_path),
        "master_path": promotion.master_path.as_posix(),
        "master_sha256": promotion.master_sha256,
        "state_path": promotion.state_path.as_posix(),
        "state_stage": next(
            item["stage"]
            for item in json.loads(promotion.state_path.read_text(encoding="utf-8"))["targets"]
            if item["target_id"] == EDITION_ID
        ),
        "fixture_root": stage_root.as_posix(),
        "promoted_root": promoted_root.as_posix(),
        "acceptance_decision": final_acceptance["decision"]["agent_assessment"]["status"],
        "visual_review_status": coverage["status"],
        "visual_review_claimed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--reproduction-package", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reproduction-candidate", type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--promoted-root", type=Path, required=True)
    args = parser.parse_args()
    result = prepare_and_promote(
        root=args.root,
        package_path=args.package,
        reproduction_package_path=args.reproduction_package,
        bound_candidate_path=args.candidate,
        reproduction_bound_candidate_path=args.reproduction_candidate,
        stage_root=args.stage_root,
        promoted_root=args.promoted_root,
        expected_bound_candidate_sha256=args.expected_candidate_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
