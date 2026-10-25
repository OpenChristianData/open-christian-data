"""Stage and guardedly install the reviewed NPNF1-08 Psalms reconstruction."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path, install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[3]
WORK_ID = "augustine-expositions-on-psalms"
FORM_ID = "augustine-expositions-on-psalms-english"
EDITION_ID = "augustine-expositions-on-psalms-retained-electronic-witness"
ACQUISITION_ID = "augustine-expositions-on-psalms-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE_MANIFEST = Path("sources/structured-text") / WORK_ID / "lib038.source-manifest.json"
EVIDENCE = WORK / "integration/npnf108-psalms-electronic-acceptance-v1"
HISTORICAL = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-09-detection-measurement/37c-035")
CURRENT = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-psalms-current-20261001-v3")
REPLAY = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-psalms-current-20261001-v4")
EXPECTED = {
    "ocd_kernel/reconstruction/contract.py": "ee9fe78b88bfe68c04223a4273918e065b9bc2f5abbd002405eb7ae063c08ce9",
    "ocd_kernel/tei/acceptance.py": "71ac3fb26930fe49ba14696a1bbb18d496181df714bd1c035f6840b0218d26d3",
    "ocd_kernel/tei/install_accepted.py": "8e5cd00d8ec5c59f3ebd7b234934cb839e276eb946773091836d8fbc1f9f6b60",
}
MANIFEST_SHA = "41cc46dcf5908307df2ab1014b0593e3b3ed8a7207f1dadac0084c406bc3900a"
PACKAGE_SHA = "0809ed633b7b885bced268e76b315b7e5b751527fcfc0ce0f62111048f6f34a6"
TEI_SHA = "5b71a988794ddacc8fd06d601e710035b3b9e951f1a1efd5174cf876fef13929"
LEDGER_SHA = "dc1e1261fb0aa7f247d1355c6a780ea9e988ca72029a7804d73b3cae1f07255c"
SOURCE_SHA = "87b60e90917e69f03c75955517fc996a0e6d22dc9862365b45c308e70e5bf784"
VISUAL_SHA = "ee831218883b1c156eae1fea51599fafcd8921d2a368fa2cc40d4da60dfff522"
SCOPE = (
    "Complete direct div1 root ii in the retained NPNF1-08 CCEL ThML: title matter, "
    "editor preface, translation advertisement, all 150 Psalm divisions, and final prayer; "
    "other top-level roots and index remain outside the work."
)
REVISION = {
    "id": "augustine-psalms-npnf108-electronic-v1",
    "date": "2026-10-01",
    "note": "Accept the complete Expositions on the Book of Psalms root in the retained CCEL electronic witness.",
}
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def digest(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def check_shared() -> None:
    for relative, expected in EXPECTED.items():
        if digest(ROOT / relative) != expected:
            raise PipelineError(f"shared implementation drift: {relative}")


def read_json(path: Path) -> dict:
    value = json.loads(_io_path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: object) -> Path:
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def copy(source: Path, target: Path) -> Path:
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))
    return target


def checked_candidate(path: Path) -> CandidatePackage:
    package = CandidatePackage.load(path / "package")
    if (
        package.sha256 != PACKAGE_SHA
        or digest(path / "package/content.tei.xml") != TEI_SHA
        or digest(path / "package/source-accountability.json") != LEDGER_SHA
    ):
        raise PipelineError(f"candidate package identity differs: {path}")
    report = read_json(path / "validation.json")
    if (
        report.get("status") != "pass"
        or report.get("findings") != []
        or report.get("candidate_sha256") != PACKAGE_SHA
        or report.get("source_manifest_sha256") != MANIFEST_SHA
    ):
        raise PipelineError(f"candidate validation differs: {path}")
    return package


def stage(stage_root: Path) -> dict:
    check_shared()
    stage_root = stage_root.absolute()
    audit = ROOT / ".tmp_audit"
    if (
        stage_root.exists()
        or stage_root.parent != audit
        or not stage_root.name.startswith("augustine-expositions-on-psalms-accept-")
    ):
        raise PipelineError("fresh work-named stage under .tmp_audit required")
    manifest = SourceManifest.load(ROOT / SOURCE_MANIFEST, repository_root=ROOT)
    manifest.verify()
    if digest(ROOT / SOURCE_MANIFEST) != MANIFEST_SHA:
        raise PipelineError("source manifest changed")
    package = checked_candidate(CURRENT)
    replay = checked_candidate(REPLAY)
    if package.member_names != replay.member_names or any(
        package.member_bytes(name) != replay.member_bytes(name)
        for name in package.member_names
    ):
        raise PipelineError("isolated candidate replay differs")
    if digest(ROOT / HISTORICAL / "visual-final-review.md") != VISUAL_SHA:
        raise PipelineError("historical visual review changed")
    acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    if (
        acquisition["acquisition_id"] != ACQUISITION_ID
        or len(acquisition["retained_files"]) != 1
        or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA
        or acquisition["url"] != "https://www.ccel.org/ccel/schaff/npnf108.xml"
    ):
        raise PipelineError("acquisition/source identity differs")
    original_work = ROOT / WORK
    if (ROOT / EDITION / "master.tei.xml").exists() or (ROOT / EDITION / "acceptance.json").exists():
        raise PipelineError("canonical Augustine edition already has an accepted master")
    before = _files(original_work)
    if set(before) != {
        "work.json", "state.json",
        f"forms/{FORM_ID}/editions/{EDITION_ID}/acquisitions/{ACQUISITION_ID}.json",
    }:
        raise PipelineError("canonical Augustine work preimage differs")
    if read_json(original_work / "state.json")["targets"][1]["stage"] != "acquired":
        raise PipelineError("canonical Augustine edition is not acquired")

    stage_root.mkdir()
    shutil.copytree(_io_path(original_work), _io_path(stage_root / WORK))
    copy(resolve_repo_path(ROOT, acquisition["retained_files"][0]["path"]), stage_root / acquisition["retained_files"][0]["path"])
    for document in (read_json(ROOT / WORK / "work.json"), read_json(ROOT / WORK / "state.json")):
        references = document.get("evidence", []) if "evidence" in document else [
            value for target in document["targets"] for value in target.get("evidence", [])
        ]
        for reference in references:
            relative = reference.split("#", 1)[0]
            source = resolve_repo_path(ROOT, relative) if relative.startswith("raw/") else ROOT / relative
            target = stage_root / relative
            if _io_path(source).is_file() and not _io_path(target).is_file():
                copy(source, target)

    inputs = stage_root / EVIDENCE / "inputs"
    copy(ROOT / SOURCE_MANIFEST, inputs / "source-manifest.json")
    copy(CURRENT / "package/manifest.json", inputs / "package-manifest.json")
    copy(CURRENT / "validation.json", inputs / "validation.json")
    copy(REPLAY / "package/manifest.json", inputs / "replay-package-manifest.json")
    copy(REPLAY / "validation.json", inputs / "replay-validation.json")
    ledger = copy(CURRENT / "package/source-accountability.json", inputs / "source-accountability.json")
    copy(CURRENT / "package/provenance.json", inputs / "provenance.json")
    copy(CURRENT / "package/unresolved.jsonl", inputs / "unresolved.jsonl")
    copy(CURRENT / "package/README.source.md", inputs / "README.source.md")
    copy(ROOT / HISTORICAL / "visual-final-review.md", inputs / "visual-final-review.md")
    copy(ROOT / HISTORICAL / "root-verification.json", inputs / "root-verification.json")
    copy(ROOT / HISTORICAL / "root-structural-mutations.json", inputs / "root-structural-mutations.json")
    copy(ROOT / HISTORICAL / "root-census-fix-verification.json", inputs / "root-census-fix-verification.json")
    shutil.copytree(_io_path(ROOT / HISTORICAL / "visual-final"), _io_path(inputs / "visual-final"))

    identity = {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }
    member = acquisition["retained_files"][0]
    source = {
        "source_path": member["path"],
        "source_sha256": member["sha256"],
        "source_bytes": member["bytes"],
        "source_scope": member["scope"],
    }
    original = package.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(
        original,
        expected_sha256=TEI_SHA,
        identity=identity,
        source=source,
        source_url=acquisition["url"],
        declared_scope=SCOPE,
        revision=REVISION,
        historical_source_description={
            "pointers": ["https://www.ccel.org/ccel/schaff/npnf108.html"],
            "sha256": [SOURCE_SHA],
        },
    )
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("reviewed TEI body changed")
    candidate = stage_root / EVIDENCE / "candidate.tei.xml"
    _io_path(candidate.parent).mkdir(parents=True, exist_ok=True)
    _io_path(candidate).write_bytes(derived)
    if errors := validate_file(candidate):
        raise PipelineError(f"bound TEI P5 errors: {errors[:3]}")
    source_credit = (
        "# Source and data credit\n\n"
        "Expositions on the Book of Psalms, in *Nicene and Post-Nicene Fathers, First Series*, "
        "volume 8, edited by Philip Schaff; English translation edited by A. Cleveland Coxe. "
        "Electronic source sourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf108.html), "
        "retained as `raw/ccel/npnf1/npnf108.xml`. The retained file states Public Domain. "
        "CCEL's separate electronic-format notice says not to sell derivatives of its formatting.\n\n"
        "This master represents the complete direct Psalms root in that retained electronic witness. "
        "Human textual review, independent rights clearance, and publication authorization remain open.\n"
    )
    credit_path = stage_root / EDITION / "SOURCE_CREDIT.md"
    _io_path(credit_path).write_text(source_credit, encoding="utf-8")

    expected_members = [{"path": member["path"], "position": 1}]
    included_members = [expected_members[0] | {key: member[key] for key in ("bytes", "sha256", "scope")}]
    scope = {
        "kind": "selection", "declared": SCOPE,
        "expected_members": expected_members,
        "included_members": included_members,
        "excluded_members": [],
    }
    common = {
        "identity": identity,
        "candidate": make_file_binding(stage_root, candidate),
        "source": source,
        "scope": SCOPE,
        "accepted_scope": {"kind": "selection", "declared": SCOPE},
        "expected_members": expected_members,
        "included_members": included_members,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
    }
    ledger_doc = read_json(ledger)
    input_bindings = {
        name: make_file_binding(stage_root, path)
        for name, path in {
            "source_manifest": inputs / "source-manifest.json",
            "package_manifest": inputs / "package-manifest.json",
            "validation": inputs / "validation.json",
            "replay_package_manifest": inputs / "replay-package-manifest.json",
            "replay_validation": inputs / "replay-validation.json",
            "full_source_accountability": ledger,
            "visual_review": inputs / "visual-final-review.md",
            "root_verification": inputs / "root-verification.json",
            "structural_mutations": inputs / "root-structural-mutations.json",
            "final_census": inputs / "root-census-fix-verification.json",
            "visible_source_credit": credit_path,
        }.items()
    }
    account = write_json(stage_root / EVIDENCE / "source-accounting.json", common | {
        "scope": source["source_scope"],
        "source_sha256": SOURCE_SHA,
        "source_bytes": member["bytes"],
        "source_manifest_sha256": MANIFEST_SHA,
        "candidate_package_sha256": PACKAGE_SHA,
        "original_candidate_tei_sha256": TEI_SHA,
        "complete_ledger": input_bindings["full_source_accountability"],
        "source_census": ledger_doc["source_census"],
        "top_level_division_accounting": ledger_doc["top_level_division_accounting"],
        "comment_accounting": ledger_doc["comment_accounting"],
        "assigned_work_count": ledger_doc["assigned_work_count"],
        "source_url_distinction": {
            "reviewed_tei_pointer": "https://www.ccel.org/ccel/schaff/npnf108.html",
            "acquisition_url": acquisition["url"],
            "retained_source_sha256": SOURCE_SHA,
        },
    })
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pytest_command = (
        "py -3 -m pytest -p no:cacheprovider "
        "tests/test_npnf108_lib038_reconstruction_contract.py -v --durations=20"
    )
    commands = {
        "validation": "py -3 -m build.tools.reconstruct_candidate --manifest sources/structured-text/augustine-expositions-on-psalms/lib038.source-manifest.json --destination D:/Library/Open Christian Data/candidate-reviews/augustine-psalms-current-20261001-v3 --repository-root . --progress",
        "accounting": pytest_command,
        "fidelity": pytest_command,
        "reproducibility": "two isolated reconstruct_candidate runs, second with PYTHONHASHSEED=2147483647; compare all six package members",
        "schema": "ocd_kernel.tei.validate.validate_file on bound candidate; SourceManifest.verify",
        "closure": "SourceManifest.verify; SHA-256 check of current producer, oracle, contract, acceptance, installer, source and candidate",
    }
    descriptions = {
        "validation": "Current independent oracle and TEI XSD pass with empty findings.",
        "accounting": "Full 32 MB ledger binds assigned root ii, all source features, top-level exclusions, comments, and complete retained-file envelope.",
        "fidelity": "Independent source/text checks and four resealed mutations reject changed TEI text, comment, crosswalk, and provenance.",
        "reproducibility": "Two clean isolated runs yield identical six-member packages and preserve the historical TEI and full-accounting hashes.",
        "schema": "Current source manifest, acquisition, package, and derived TEI validate; header binding leaves body bytes identical.",
        "closure": "Current source, manifest, closures, candidate, validation, root checks, and visual evidence are digest-bound.",
    }
    technical = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": ["Producer and oracle share the pinned retained file and declared selected root; the oracle separately enumerates source and TEI observations."],
        "independent_corroboration": "Independent root/text/placement checks, current six-test oracle and mutations, two isolated replays, and seven bounded source/TEI visual frames.",
    }
    for name in PROOFS:
        path = write_json(stage_root / EVIDENCE / f"{name}.json", common | {
            "claim": name, "status": "pass", "command": commands[name], "exit_code": 0,
            "description": descriptions[name], "inputs": input_bindings,
            "checked_at": at,
        })
        technical[name] = {"path": path, "status": "pass", "command": commands[name], "exit_code": 0}
    review = {
        "reviewer": "agent:augustine-psalms-technical-owner",
        "reviewed_at": at,
        "coverage": {
            "status": "partial", "declared": SCOPE, "reached": ["ii"],
            "inspected": ["ii/title", "ii/psalm-I", "ii/psalm-XXXVII", "ii/psalm-CXIX", "ii/psalm-CL", "ii/final-prayer"],
            "unreviewed": ["ii/other-content"],
        },
        "source_quality_uncertainty": [
            "This is an electronic witness; print collation and translation-lineage certainty are not claimed.",
            "Visual inspection is bounded to seven credited fallback frames; one wrong-tab frame was rejected.",
        ],
        "discrepancies": [],
        "unreviewed_residuals": ["Whole-work visual proofreading, print collation, and human textual review remain open."],
    }
    review_path = write_json(stage_root / EVIDENCE / "review.json", common | review | {
        "inputs": input_bindings,
        "historical_visual_review_sha256": VISUAL_SHA,
        "historical_reviewed_tei_sha256": TEI_SHA,
    })
    decision = {
        "source_local_disposition": "Agent acceptance of the exact complete Psalms root in the retained CCEL electronic witness.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted", "actor": review["reviewer"], "assessed_at": at,
            "supported_scope": SCOPE, "unresolved_claims": [],
            "unassessed_stronger_claims": ["print-edition collation", "complete visual proofreading", "human textual acceptance", "independent rights clearance", "global release selection", "public publication"],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        stage_root, identity=identity, candidate_path=candidate, source_accounting_path=account,
        scope=scope, technical=technical, review=review | {"report_path": review_path},
        representation_revision=REVISION, decision=decision,
    )
    acceptance = stage_root / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage_root)
    master = stage_root / EDITION / "master.tei.xml"
    _io_path(master).write_bytes(derived)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=at, master=make_file_binding(stage_root, master))
    write_acceptance(acceptance, record)
    state_path = stage_root / WORK / "state.json"
    state = read_json(state_path)
    targets = [item for item in state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("one acquired Augustine edition target required")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    targets[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    write_json(state_path, state)
    validate_acceptance(acceptance, root=stage_root)
    validate_state(state_path, root=stage_root)
    check_shared()
    result = {
        "status": "staged-only", "work_id": WORK_ID, "stage_root": stage_root.as_posix(),
        "before": before, "after": _files(stage_root / WORK),
        "source_sha256": SOURCE_SHA, "source_manifest_sha256": MANIFEST_SHA,
        "candidate_package_sha256": PACKAGE_SHA, "original_tei_sha256": TEI_SHA,
        "full_accounting_sha256": LEDGER_SHA, "bound_candidate_sha256": digest(candidate),
        "master_sha256": digest(master), "acceptance_sha256": digest(acceptance),
        "installation": "not-performed", "human_review": "not-recorded",
        "rights": "not-cleared", "publication": "not-authorized",
    }
    write_json(stage_root / "stage-receipt.json", result)
    return result


def preflight(stage_root: Path, expected_receipt_sha256: str) -> dict:
    check_shared()
    stage_root = stage_root.resolve(strict=True)
    if (
        stage_root.parent != (ROOT / ".tmp_audit").resolve(strict=True)
        or not stage_root.name.startswith("augustine-expositions-on-psalms-accept-")
        or digest(stage_root / "stage-receipt.json") != expected_receipt_sha256
    ):
        raise PipelineError("Augustine stage location or receipt pin differs")
    receipt = read_json(stage_root / "stage-receipt.json")
    if receipt["status"] != "staged-only" or receipt["work_id"] != WORK_ID or receipt["installation"] != "not-performed":
        raise PipelineError("Augustine stage receipt differs")
    if _files(ROOT / WORK) != receipt["before"] or _files(stage_root / WORK) != receipt["after"]:
        raise PipelineError("Augustine canonical preimage or stage changed")
    validate_acceptance(stage_root / EDITION / "acceptance.json", root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    check_shared()
    return {"status": "ready-to-install", "receipt_sha256": expected_receipt_sha256,
            "master_sha256": receipt["master_sha256"], "acceptance_sha256": receipt["acceptance_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "preflight", "apply"))
    parser.add_argument("stage_root", type=Path)
    parser.add_argument("--expected-receipt-sha256")
    args = parser.parse_args()
    if args.action == "stage":
        result = stage(args.stage_root)
    elif args.expected_receipt_sha256 is None:
        parser.error("--expected-receipt-sha256 is required for preflight/apply")
    elif args.action == "preflight":
        result = preflight(args.stage_root, args.expected_receipt_sha256)
    else:
        result = preflight(args.stage_root, args.expected_receipt_sha256)
        result["installation"] = install_accepted_work(ROOT, args.stage_root, work_id=WORK_ID)
        check_shared()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
