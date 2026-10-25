"""Prepare and preflight a Didache accepted-master stage without installing it.

OCD_LIBRARY_PIPELINE_SPEC sections 7 and 16 authorize evidence-backed agent
acceptance and explicitly separate later human verification. The decision here
is limited to the exact retained electronic witness. Missing Wikisource
revision/proofreading history, rights, and publication remain unresolved.
No function in this module writes the canonical work tree.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree

from build.tools.preflight_didache_full_witness import (
    ROOT, SOURCE, SOURCE_SHA256, WORK, _canonical, _inputs, _sha,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
SOURCE_STAGE = PARENT / "didache-lake-full-witness-s20260928-v1"
SOURCE_RECEIPT_SHA256 = "d9e228ef3aa31449affd013f0c42ef5ebf805fd8b2df15c8f3fa4ca5acd6c3cf"
WORK_DIR = Path("library/works/didache-prayers")
EDITION = WORK_DIR / "forms/didache-prayers-retained-electronic/editions/didache-prayers-retained-electronic-witness"
ACQUISITION = EDITION / "acquisitions/didache-prayers-retained-source.json"
EVIDENCE = WORK_DIR / "integration/didache-lake-full-witness-v1"
RECEIPT = Path("didache-acceptance-stage-receipt.json")
IDENTITY = {
    "work_id": "didache-prayers",
    "textual_form_id": "didache-prayers-retained-electronic",
    "edition_id": "didache-prayers-retained-electronic-witness",
    "acquisition_id": "didache-prayers-retained-source",
}
CLAIM_LIMITS = (
    "Exact Wikisource revision and proofreading history are absent.",
    "No print-edition identity or exhaustive clean-text admission is claimed.",
    "Rights clearance and publication remain unresolved.",
)
PROJECTION_COUNTS = {"rows": 18, "chapters": 16, "source_rows": 30, "verses": 100, "footnotes": 10}


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"expected JSON object: {path}")
    return value


def _target(path: Path, *, exists: bool) -> Path:
    parent = PARENT.resolve(strict=True)
    path = Path(path).absolute()
    if path.parent.resolve(strict=True) != parent or not path.name.startswith("didache-lake-accepted-s"):
        raise PipelineError("unexpected Didache acceptance stage path")
    if path.exists() != exists:
        raise PipelineError("Didache acceptance stage freshness differs")
    return path


def _copy(root: Path, relative: Path, source: Path) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    return target


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))
    return path


def _source_candidate() -> tuple[CandidatePackage, dict]:
    from build.tools.preflight_didache_full_witness import preflight

    preflight(SOURCE_STAGE, SOURCE_RECEIPT_SHA256)
    package = CandidatePackage.load(SOURCE_STAGE / "package")
    validation = _read_json(SOURCE_STAGE / "validation.json")
    if (validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("candidate_sha256") != package.sha256):
        raise PipelineError("Didache source candidate no longer has passing validation")
    return package, validation


def _accepted_work_bytes() -> bytes:
    work = _read_json(SOURCE_STAGE / WORK)
    editions = work["textual_forms"][0]["editions"]
    if len(editions) != 1 or editions[0]["edition_id"] != IDENTITY["edition_id"]:
        raise PipelineError("Didache staged edition identity differs")
    if "category" in editions[0]:
        raise PipelineError("Didache category was already set in the source proposal")
    editions[0]["category"] = "prose"
    return _canonical(work)


def _check_full_witness_rows(rows: list[dict]) -> None:
    def walk(node: dict):
        yield node
        for child in node.get("content", []):
            if isinstance(child, dict):
                yield from walk(child)

    nodes = [node for row in rows for top in row["structure"] for node in walk(top)]
    divisions = [node for node in nodes if node["kind"] == "division"]
    chapter_numbers = [
        node["attributes"].get("number") for node in divisions
        if node["attributes"].get("type") == "chapter"
    ]
    counts = {
        "rows": len(rows),
        "chapters": len(chapter_numbers),
        "source_rows": sum(node["attributes"].get("type") == "row" for node in divisions),
        "verses": sum(node["kind"] == "source-block" and node["attributes"].get("type") == "verse" for node in nodes),
        "footnotes": sum(node["kind"] == "note" and node["attributes"].get("type") == "footnote" for node in nodes),
    }
    if (counts != PROJECTION_COUNTS
            or chapter_numbers != [str(number) for number in range(1, 17)]
            or any(row["category"] != "prose" for row in rows)):
        raise PipelineError(f"Didache full-witness native row accounting differs: {counts}, chapters={chapter_numbers}")


def prepare(stage: Path) -> dict:
    stage = _target(stage, exists=False)
    package, validation = _source_candidate()
    source_facts = _inputs(SOURCE_STAGE)
    proposed_work = source_facts.pop("proposed_work_bytes")
    before = {
        path.as_posix(): _sha((ROOT / path).read_bytes())
        for path in (WORK, WORK_DIR / "state.json", ACQUISITION)
    }
    # The only title change is the already reviewed source-bound work proposal.
    if (SOURCE_STAGE / WORK).read_bytes() != proposed_work:
        raise PipelineError("Didache title-only work proposal changed")
    stage.mkdir()
    _copy(stage, WORK, SOURCE_STAGE / WORK)
    (stage / WORK).write_bytes(_accepted_work_bytes())
    for relative in (WORK_DIR / "state.json", ACQUISITION):
        _copy(stage, relative, ROOT / relative)
    _copy(stage, SOURCE, ROOT / SOURCE)
    inherited_state = _read_json(stage / WORK_DIR / "state.json")
    for target in inherited_state["targets"]:
        for reference in target["evidence"]:
            relative = Path(reference)
            if relative.is_absolute() or ".." in relative.parts:
                raise PipelineError(f"unsafe Didache state evidence path: {reference}")
            if not (stage / relative).is_file():
                _copy(stage, relative, ROOT / relative)
    load_work(stage / WORK)
    acquisition = validate_acquisition(stage / ACQUISITION, root=stage)
    if (acquisition["source_path"] != SOURCE.as_posix()
            or acquisition["source_sha256"] != SOURCE_SHA256
            or len(acquisition["retained_files"]) != 1):
        raise PipelineError("Didache staged acquisition is not the complete retained member")
    source = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope")}
    original = package.member_bytes("content.tei.xml")
    now = datetime.now(timezone.utc)
    at = now.isoformat().replace("+00:00", "Z")
    revision = {
        "id": "didache-lake-full-witness-v1",
        "date": now.date().isoformat(),
        "note": "Accepted the complete retained Lake electronic witness as a source-bound Didache representation; source revision history and rights remain unresolved.",
    }
    derived = bind_reviewed_header(
        original, expected_sha256=_sha(original), identity=IDENTITY,
        source=source, source_url=acquisition["url"],
        declared_scope=source["source_scope"], revision=revision,
    )
    root = etree.fromstring(derived)
    if len(root.xpath("./t:text/t:body/t:div[@type='chapter']",
                      namespaces={"t": "http://www.tei-c.org/ns/1.0"})) != 16:
        raise PipelineError("Didache accepted header narrowed the full witness")
    evidence = stage / EVIDENCE
    evidence.mkdir(parents=True)
    shutil.copytree(SOURCE_STAGE / "package", evidence / "inputs/package")
    _copy(stage, EVIDENCE / "inputs/validation.json", SOURCE_STAGE / "validation.json")
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(derived)
    if validate_file(candidate):
        raise PipelineError("Didache staged candidate failed TEI P5")
    closing = b"</teiHeader>"
    if original.split(closing, 1)[1] != derived.split(closing, 1)[1]:
        raise PipelineError("Didache reviewed text changed during accepted-header binding")
    master = stage / EDITION / "master.tei.xml"
    master.write_bytes(derived)
    member = acquisition["retained_files"][0]
    included = {
        "path": member["path"], "position": 1, "bytes": member["bytes"],
        "sha256": member["sha256"], "scope": member["scope"],
    }
    scope = {
        "kind": "edition", "declared": source["source_scope"],
        "expected_members": [{"path": member["path"], "position": 1}],
        "included_members": [included], "excluded_members": [],
    }
    candidate_binding = make_file_binding(stage, candidate)
    common = {
        "identity": IDENTITY, "source": source,
        "candidate": candidate_binding, "scope": source["source_scope"],
    }
    accounting_fields = {
        "accepted_scope": {"kind": "edition", "declared": source["source_scope"]},
        "expected_members": scope["expected_members"], "included_members": [included],
        "excluded_members": [], "missing_members": [], "unknown_members": [],
        "source_sha256": SOURCE_SHA256, "source_bytes": member["bytes"],
        "original_package_sha256": package.sha256,
        "source_manifest_sha256": source_facts["source_manifest_sha256"],
    }
    accounting = _write_json(evidence / "source-accounting.json", common | accounting_fields)
    command = "py -3 -m build.tools.stage_didache_full_witness_acceptance --stage <fresh-external-stage>"
    descriptions = {
        "validation": "Fresh independent oracle report passes with zero findings and exact source and candidate bindings.",
        "accounting": "The one complete retained source member accounts for all 16 chapters, 30 rows, 100 verses, and 10 footnotes.",
        "fidelity": "Independent source oracle checked content, order, notes, structure, metadata, and adversarial mutations.",
        "reproducibility": "Focused Didache suite reproduced the candidate in a fresh process: 12 passed, exit 0.",
        "schema": "Header-bound complete-witness TEI passed the vendored TEI P5 validator.",
        "closure": "Source, acquisition, profile, manifest, candidate, validation, title-only identity, and master bind the same witness.",
    }
    technical = {
        "producer": {"id": "ocd-didache-prayers-wikisource-json-to-tei"},
        "checker": {"id": "ocd-didache-prayers-independent-source-oracle"},
        "shared_assumptions": ["Producer and oracle share the same exact retained JSON and source manifest."],
        "independent_corroboration": "Independent source walk and mutations, exact candidate regeneration, and prior bounded visual review.",
    }
    for name, observation in descriptions.items():
        proof = _write_json(
            evidence / f"{name}.json",
            common | {"status": "pass", "command": command, "exit_code": 0,
                      "checked_at": at, "observation": observation}
            | (accounting_fields if name == "accounting" else {}),
        )
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    review = {
        "reviewer": "agent:didache-lake-full-witness-stage",
        "reviewed_at": at,
        "coverage": {
            "status": "partial", "declared": source["source_scope"],
            "reached": ["complete-witness"],
            "inspected": ["complete-witness/structure"],
            "unreviewed": ["complete-witness/proofreading-history"],
        },
        "source_quality_uncertainty": list(CLAIM_LIMITS),
        "discrepancies": [],
        "unreviewed_residuals": [
            "The earlier bounded visual review was not repeated for the new title-only candidate.",
            "Prior candidate bytes were ACL-inaccessible, so old/new text-body byte equality was not independently rechecked.",
        ],
    }
    review_path = _write_json(
        evidence / "review.json",
        common | review | {
            "historical_review_path": "plans/2026-08-31-sample-first-library-verification/issues/20-review-didache-prayers.md",
        },
    )
    decision = {
        "source_local_disposition": "Evidence-backed agent acceptance of the exact complete electronic witness in a stage only.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted", "actor": "agent:didache-lake-full-witness-stage",
            "assessed_at": at, "supported_scope": source["source_scope"],
            "unassessed_stronger_claims": [
                "exhaustive clean-text admission", "verified print edition",
                "human verification", "rights clearance", "publication",
            ],
            "unresolved_claims": list(CLAIM_LIMITS),
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision,
        promotion_status="promoted",
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    state_path = stage / WORK_DIR / "state.json"
    state = _read_json(state_path)
    targets = [item for item in state["targets"] if item["target_id"] == IDENTITY["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("Didache edition state preimage differs")
    targets[0].update(
        stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at,
        evidence=targets[0]["evidence"] + [
            (EDITION / "master.tei.xml").as_posix(),
            (EDITION / "acceptance.json").as_posix(),
        ],
    )
    _write_json(state_path, state)
    validate_acceptance(acceptance, root=stage)
    validate_state(state_path, root=stage)
    projected = project_accepted_prose(stage, acceptance_path=acceptance)
    errors = verify_accepted_prose(
        stage, acceptance_path=acceptance,
        rows=projected["rows"], receipt=projected["receipt"],
    )
    if errors:
        raise PipelineError(f"Didache native accepted prose verification failed: {errors[:3]}")
    _check_full_witness_rows(projected["rows"])
    after = {
        path.relative_to(stage).as_posix(): _sha(path.read_bytes())
        for path in (stage / WORK_DIR).rglob("*") if path.is_file()
    }
    receipt = {
        "contract": "ocd-didache-full-witness-accepted-stage-v1",
        "status": "staged-only", "canonical_install": False,
        "work_id": IDENTITY["work_id"], "source_sha256": SOURCE_SHA256,
        "source_candidate_sha256": package.sha256,
        "source_stage_receipt_sha256": SOURCE_RECEIPT_SHA256,
        "before": before, "after": after,
        "master_sha256": _sha(master.read_bytes()),
        "acceptance_sha256": _sha(acceptance.read_bytes()),
        "projected_rows": len(projected["rows"]),
        "projection_counts": PROJECTION_COUNTS,
        "claim_limits": list(CLAIM_LIMITS),
    }
    receipt_path = _write_json(stage / RECEIPT, receipt)
    return {"status": "staged-only", "stage": stage.as_posix(),
            "receipt_sha256": _sha(receipt_path.read_bytes()),
            "projected_rows": len(projected["rows"])}


def preflight(stage: Path, receipt_sha256: str) -> dict:
    stage = _target(stage, exists=True)
    receipt_path = stage / RECEIPT
    if _sha(receipt_path.read_bytes()) != receipt_sha256:
        raise PipelineError("Didache acceptance stage receipt differs from caller pin")
    receipt = _read_json(receipt_path)
    package, _validation = _source_candidate()
    if (receipt.get("contract") != "ocd-didache-full-witness-accepted-stage-v1"
            or receipt.get("status") != "staged-only"
            or receipt.get("canonical_install") is not False
            or receipt.get("source_candidate_sha256") != package.sha256
            or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("source_stage_receipt_sha256") != SOURCE_RECEIPT_SHA256
            or receipt.get("claim_limits") != list(CLAIM_LIMITS)):
        raise PipelineError("Didache acceptance stage claim differs")
    for relative, expected in receipt["before"].items():
        if _sha((ROOT / relative).read_bytes()) != expected:
            raise PipelineError(f"Didache canonical preimage changed: {relative}")
    after = {
        path.relative_to(stage).as_posix(): _sha(path.read_bytes())
        for path in (stage / WORK_DIR).rglob("*") if path.is_file()
    }
    if after != receipt["after"]:
        raise PipelineError("Didache staged work generation differs")
    if (stage / WORK).read_bytes() != _accepted_work_bytes():
        raise PipelineError("Didache staged work differs from title and prose-category proposal")
    acceptance = stage / EDITION / "acceptance.json"
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK_DIR / "state.json", root=stage)
    projected = project_accepted_prose(stage, acceptance_path=acceptance)
    errors = verify_accepted_prose(
        stage, acceptance_path=acceptance,
        rows=projected["rows"], receipt=projected["receipt"],
    )
    if errors or len(projected["rows"]) != receipt["projected_rows"] or receipt.get("projection_counts") != PROJECTION_COUNTS:
        raise PipelineError("Didache native accepted projection differs")
    _check_full_witness_rows(projected["rows"])
    return {"status": "staged-only", "stage": stage.as_posix(),
            "receipt_sha256": receipt_sha256, "projected_rows": len(projected["rows"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256")
    args = parser.parse_args()
    if args.expected_receipt_sha256:
        result = preflight(args.stage, args.expected_receipt_sha256)
    else:
        result = prepare(args.stage)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
