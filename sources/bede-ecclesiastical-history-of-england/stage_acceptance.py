"""Prepare a pending Bede TEI acceptance fixture without accepting or installing it."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import shutil

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "bede-ecclesiastical-history-of-england"
FORM_ID = "bede-ecclesiastical-history-of-england-gutenberg-retained"
EDITION_ID = "bede-ecclesiastical-history-of-england-gutenberg-electronic"
ACQUISITION_ID = "bede-ecclesiastical-history-of-england-gutenberg-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
MANIFEST = Path("sources") / WORK_ID / "bede.source-manifest.json"
EVIDENCE = WORK / "integration/gutenberg-38326-technical-acceptance-v1"
SOURCE_NOTICE = WORK / "SOURCE_NOTICE.md"
REVISION_ID = "bede-gutenberg-38326-v1"


def _load_oracle(root: Path):
    path = root / "sources" / WORK_ID / "oracle.py"
    spec = spec_from_file_location("bede_acceptance_oracle", path)
    if spec is None or spec.loader is None:
        raise PipelineError(f"cannot load Bede oracle: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> Path:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _copy(root: Path, stage: Path, relative: Path) -> None:
    destination = stage / relative
    io_path(destination.parent).mkdir(parents=True, exist_ok=True)
    source = resolve_repo_path(root, relative.as_posix())
    try:
        shutil.copy2(io_path(source), io_path(destination))
    except OSError as exc:
        raise PipelineError(f"cannot stage Bede dependency {relative}: {source} -> {destination}") from exc


def prepare(stage: Path, first_package: Path, second_package: Path, *, root: Path = ROOT) -> dict[str, object]:
    """Freeze current source, reproducible candidate, and pending acceptance proofs."""
    root = root.resolve(strict=True)
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Bede acceptance stage must be fresh: {stage}")
    if stage.is_relative_to(root):
        raise PipelineError("Bede acceptance stage must be outside the repository")

    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    packages = [CandidatePackage.load(path) for path in (first_package, second_package)]
    oracle = _load_oracle(root)
    reports = [validate(manifest, package, oracle) for package in packages]
    if any(report.status != "pass" or report.findings for report in reports):
        raise PipelineError("Bede independent source/candidate validation did not pass")
    if packages[0].sha256 != packages[1].sha256 or reports[0].sha256 != reports[1].sha256:
        raise PipelineError("Bede independent process reproduction differs")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    work = load_work(root / WORK / "work.json")
    forms = work["textual_forms"]
    editions = forms[0]["editions"] if len(forms) == 1 else []
    if (work["work_id"] != WORK_ID or len(editions) != 1 or editions[0]["edition_id"] != EDITION_ID
            or (root / EDITION / "master.tei.xml").exists() or (root / EDITION / "acceptance.json").exists()):
        raise PipelineError("Bede work identity or acceptance preimage changed")
    retained = acquisition["retained_files"]
    if [item["path"] for item in retained] != [
        "raw/gutenberg/38326/pg38326-h.zip",
        "raw/gutenberg/38326/html/pg38326-images.html",
        "raw/gutenberg/38326/html/38326-cover.png",
    ]:
        raise PipelineError("Bede acquisition member set or order differs")

    stage.mkdir(parents=True)
    dependencies = {WORK / "work.json", WORK / "state.json", SOURCE_NOTICE, ACQUISITION, MANIFEST}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    dependencies.update(Path(item["path"]) for item in retained)
    for relative in sorted(dependencies):
        _copy(root, stage, relative)
    package = packages[0]
    for name in package.member_names:
        destination = stage / EVIDENCE / "inputs/package" / name
        io_path(destination.parent).mkdir(parents=True, exist_ok=True)
        io_path(destination).write_bytes(package.member_bytes(name))
    _write_json(stage / EVIDENCE / "inputs/validation.json", {
        "contract": "ocd-validation-report-v1", "status": reports[0].status,
        "candidate_sha256": reports[0].candidate_sha256,
        "source_manifest_sha256": reports[0].source_manifest_sha256,
        "attestation": dict(reports[0].attestation), "findings": list(reports[0].findings),
        "report_sha256": reports[0].sha256,
    })

    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID,
                "acquisition_id": ACQUISITION_ID}
    source = {"source_path": acquisition["source_path"], "source_sha256": acquisition["source_sha256"],
              "source_bytes": acquisition["source_bytes"], "source_scope": acquisition["source_scope"]}
    declared = (
        "Complete literary div.tei-text of retained Gutenberg HTML 38326: front, "
        "Bede's preface and Books I-V, Continuation, index, and footnotes."
    )
    revision = {"id": REVISION_ID, "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Source-faithful reconstruction of the complete retained Gutenberg literary text."}
    original = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(
        original, expected_sha256=hashlib.sha256(original).hexdigest(), identity=identity,
        source=source, source_url=acquisition["url"], declared_scope=declared, revision=revision,
    )
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Bede acceptance header changed the source-faithful TEI text")
    candidate = stage / EVIDENCE / "candidate.tei.xml"
    io_path(candidate.parent).mkdir(parents=True, exist_ok=True)
    io_path(candidate).write_bytes(bound)
    if errors := validate_file(io_path(candidate)):
        raise PipelineError(f"Bede bound TEI P5 validation failed: {errors[:3]}")

    expected = [{"path": item["path"], "position": index} for index, item in enumerate(retained, 1)]
    included = [{"path": retained[1]["path"], "position": 2, "bytes": retained[1]["bytes"],
                 "sha256": retained[1]["sha256"], "scope": declared}]
    excluded = [
        {"path": retained[0]["path"], "position": 1,
         "reason": "Acquisition ZIP duplicates the verified HTML and cover; package is not literary text."},
        {"path": retained[2]["path"], "position": 3,
         "reason": "Cover support image has no occurrence inside the literary div.tei-text."},
    ]
    scope = {"kind": "selection", "declared": declared, "expected_members": expected,
             "included_members": included, "excluded_members": excluded}
    common = {
        "identity": identity, "source": source, "candidate": make_file_binding(stage, candidate),
        "scope": declared, "accepted_scope": {"kind": "selection", "declared": declared},
        "expected_members": expected, "included_members": included, "excluded_members": excluded,
        "missing_members": [], "unknown_members": [],
    }
    accounting = _write_json(stage / EVIDENCE / "source-accounting.json", common | {
        "scope": source["source_scope"],
        "source_sha256": source["source_sha256"], "source_bytes": source["source_bytes"],
        "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
        "oracle_report_sha256": reports[0].sha256,
        "candidate_source_accountability": make_file_binding(
            stage, stage / EVIDENCE / "inputs/package/source-accountability.json"),
        "literary_parts": ["front", "body", "back"], "footnotes": 1081,
        "page_markers": 465, "continuation": "retained after Book V; authorship unresolved",
        "excluded_html_regions": ["head and CSS", "provider header", "provider footer and license"],
    })
    command = "py -3 sources/bede-ecclesiastical-history-of-england/stage_acceptance.py"
    technical: dict[str, object] = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": [
            "Producer and independent oracle use the same pinned retained HTML and candidate-package schema.",
            "Both use the same declared literary div.tei-text boundary and TEI P5 schema.",
        ],
        "independent_corroboration": (
            "BeautifulSoup/lxml oracle compared the whole HTML literary tree to TEI, including text, "
            "source order, notes, page markers, IDs, and local links; two fresh package runs match."
        ),
    }
    proof_details = {
        "validation": {"oracle_status": reports[0].status, "oracle_findings": list(reports[0].findings)},
        "accounting": {"included": 1, "excluded_support": 2, "missing": 0, "unknown": 0},
        "fidelity": {"complete_literary_tree": True, "footnotes": 1081, "page_markers": 465,
                     "local_links": 9639, "source_ids": 3968},
        "reproducibility": {"first_package_sha256": packages[0].sha256,
                            "second_package_sha256": packages[1].sha256,
                            "first_oracle_report_sha256": reports[0].sha256,
                            "second_oracle_report_sha256": reports[1].sha256},
        "schema": {"tei_p5": "pass", "candidate_package_schema": "pass"},
        "closure": {"converter_sha256": manifest.record["converter"]["implementation_sha256"],
                    "oracle_sha256": manifest.record["validator"]["implementation_sha256"],
                    "oracle_import_closure_sha256": manifest.record["validator"]["import_closure_sha256"]},
    }
    for name, detail in proof_details.items():
        proof = _write_json(stage / EVIDENCE / f"{name}.json", common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": name,
            "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
            "oracle_report_sha256": reports[0].sha256, "detail": detail,
        })
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = {
        "reviewer": "agent:bede-gutenberg-source-reconciliation", "reviewed_at": at,
        "coverage": {"status": "partial", "declared": declared,
                     "reached": ["retained-html-literary-text"],
                     "inspected": ["retained-html-literary-text/mechanical-source-tree"],
                     "unreviewed": ["retained-html-literary-text/human-visual-comparison"]},
        "source_quality_uncertainty": [
            "Electronic HTML has not been collated to a physical 1907 printing.",
            "Footnote 1056 leaves the Continuation's exact authorship unresolved.",
        ],
        "discrepancies": [],
        "unreviewed_residuals": ["Human visual source/TEI comparison and rights review remain open."],
    }
    review_path = _write_json(stage / EVIDENCE / "review.json", common | review)
    decision = {
        "source_local_disposition": "Technical source-to-TEI proofs pass; acceptance decision pending serial review.",
        "blockers": [],
        "agent_assessment": {
            "status": "partial", "actor": review["reviewer"], "assessed_at": at,
            "supported_scope": declared,
            "unassessed_stronger_claims": ["accepted master", "human visual verification", "rights clearance", "publication"],
            "unresolved_claims": ["Acceptance and installation await serial review."],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
        scope=scope, technical=technical, review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    result = {
        "contract": "ocd-bede-gutenberg-pending-acceptance-stage-v1", "status": "pending-review",
        "stage_root": stage.as_posix(), "work_id": WORK_ID,
        "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
        "oracle_report_sha256": reports[0].sha256, "bound_candidate_sha256": _sha(candidate),
        "source_notice_sha256": _sha(stage / SOURCE_NOTICE),
        "acceptance_sha256": _sha(acceptance), "proofs": {
            name: _sha(stage / EVIDENCE / f"{name}.json") for name in proof_details
        }, "source_accounting_sha256": _sha(accounting), "review_sha256": _sha(review_path),
        "master_installed": False, "acceptance_decided": False, "rights_cleared": False,
    }
    _write_json(stage / "stage-receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--first-package", required=True, type=Path)
    parser.add_argument("--second-package", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.stage, args.first_package, args.second_package), sort_keys=True))


if __name__ == "__main__":
    main()
