"""Install Robertson's retained Doran OCR as a bounded internal TEI selection.

The selected text is the exact DjVuXML word stream. Scan accuracy, missing OCR,
rights, and public release remain separately held in the work-local record.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from ocd_kernel.library._common import PipelineError
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record, make_file_binding, promote_accepted_master,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "robertson-harmony-of-the-gospels"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/robertson-harmony-english/editions/robertson-harmony-1922-doran"
ACQUISITION = EDITION / "acquisitions/robertson-harmony-1922-ia-harmonyofgospels00robeuoft.json"
MANIFEST = Path("sources/robertson-harmony-1922/source-manifest.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/robertson-doran-reconcile-20261008/rebound")
EVIDENCE = WORK / "integration/doran-ocr-internal-acceptance-v1"
REVISION_ID = "robertson-doran-retained-ocr-v1"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": "robertson-harmony-english",
    "edition_id": "robertson-harmony-1922-doran",
    "acquisition_id": "robertson-harmony-1922-ia-harmonyofgospels00robeuoft",
}
SCOPE = (
    "All word text in the retained Doran DjVuXML across its 362 accessible scan leaves, "
    "in source page, column, region, paragraph, and line order, with scan links. "
    "This is the retained OCR selection, not a complete transcription of the printed book: "
    "21 leaves have no OCR words; map labels, other image-only text, scan-level accuracy, "
    "and Gospel passage synchronization are unverified or absent. Public text is held."
)
COMMAND = "py -3 -m build.tools.install_robertson_harmony_doran_ocr --stage <fresh-root> --promoted <fresh-root>"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(root: Path, relative: Path, data: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_json(root: Path, relative: Path, value: object) -> Path:
    return write(root, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())


def prepare(stage: Path) -> Path:
    from build.tei.robertson_harmony_1922_oracle import _oracle

    if stage.exists() or not stage.parent.is_dir():
        raise PipelineError("Robertson stage must be fresh under an existing ordinary parent")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(CANDIDATE / "package")
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or report.findings or package.manifest.get("status") != "nonaccepted":
        raise PipelineError("current Doran source-conservation candidate did not pass")
    original = package.member_bytes("content.tei.xml")
    if sha(original) != "8b0aff72690f9f79f728582b0b4713060fa103d197b99eddc3867b5c0046993d":
        raise PipelineError("Doran reviewed OCR TEI changed")
    acquisition = json.loads((ROOT / ACQUISITION).read_bytes())
    if acquisition["acquisition_id"] != IDENTITY["acquisition_id"]:
        raise PipelineError("Doran acquisition identity changed")

    shutil.copytree(ROOT / WORK, stage / WORK)
    write(stage, MANIFEST, (ROOT / MANIFEST).read_bytes())
    members = acquisition["retained_files"]
    expected = [{"path": item["path"], "position": pos} for pos, item in enumerate(members, 1)]
    included, excluded = [], []
    for pos, item in enumerate(members, 1):
        source = resolve_repo_path(ROOT, item["path"])
        data = source.read_bytes()
        if len(data) != item["bytes"] or sha(data) != item["sha256"]:
            raise PipelineError(f"Doran retained source changed: {item['path']}")
        write(stage, Path(item["path"]), data)
        if pos in (1, 2):
            included.append({"path": item["path"], "position": pos, "bytes": len(data),
                             "sha256": sha(data), "scope": "OCR text authority" if pos == 2 else "linked scan witness; image-only content remains untranscribed"})
        else:
            excluded.append({"path": item["path"], "position": pos,
                             "reason": "Retained comparison or support evidence; no additional text selected from this member."})

    for name in package.member_names:
        write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    validation_bytes = (CANDIDATE / "validation.json").read_bytes()
    stored = json.loads(validation_bytes)
    if stored.get("status") != "pass" or stored.get("candidate_sha256") != package.sha256:
        raise PipelineError("Doran validation sidecar does not bind current package")
    write(stage, EVIDENCE / "inputs/validation.json", validation_bytes)

    # Change only the header's lifecycle words; the reviewed OCR body is untouched.
    old = b"Nonaccepted OCR-based review candidate. Scan collation, rights, human acceptance, and publication remain separate decisions."
    new = b"Internally accepted retained OCR selection. Printed-page accuracy, source rights, and public release remain separate decisions."
    if original.count(old) != 1 or original.count(b'revisionDesc status="candidate"') != 1:
        raise PipelineError("Doran reviewed header changed")
    header_only = original.replace(old, new, 1).replace(b'revisionDesc status="candidate"', b'revisionDesc status="accepted"', 1)
    if header_only.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Doran OCR body changed during header update")

    now = datetime.now(timezone.utc)
    stamp = now.isoformat().replace("+00:00", "Z")
    revision = {"id": REVISION_ID, "date": now.date().isoformat(),
                "note": "Accept the exact retained Doran OCR text as an internal selection; scan defects and public rows remain held."}
    source = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope", "source_kind")}
    bound = bind_reviewed_header(header_only, expected_sha256=sha(header_only), identity=IDENTITY,
                                 source=source, source_url=acquisition["url"], declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Doran OCR body changed during acceptance binding")
    candidate = write(stage, EVIDENCE / "candidate.tei.xml", bound)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"Doran accepted header fails TEI P5: {errors[:3]}")
    scope = {"kind": "selection", "declared": SCOPE, "expected_members": expected,
             "included_members": included, "excluded_members": excluded}
    candidate_binding = make_file_binding(stage, candidate)
    common = {"identity": IDENTITY, "source": source, "candidate": candidate_binding,
              "accepted_scope": {"kind": "selection", "declared": SCOPE},
              "expected_members": expected, "included_members": included, "excluded_members": excluded,
              "missing_members": [], "unknown_members": []}
    accounting = write_json(stage, EVIDENCE / "source-accounting.json",
                            common | {"scope": acquisition["source_scope"],
                                      "accepted_scope": {"kind": "selection", "declared": SCOPE},
                                      "source_sha256": source["source_sha256"],
                                      "source_bytes": source["source_bytes"],
                                      "ocr_words": 144689, "accessible_leaves": 362,
                                      "no_ocr_leaves": [1, 2, 3, 4, 5, 6, 9, 10, 14, 18, 40, 46, 48, 354, 355, 356, 357, 358, 359, 360, 362]})
    descriptions = {
        "validation": "Fresh maintained validation passes against the exact Doran OCR package and source manifest.",
        "accounting": "All 362 accessible leaves and 144,689 OCR words are represented; 21 leaves lack OCR and are scan-linked gaps.",
        "fidelity": "The independent oracle verifies retained OCR words, page order and layout structure; printed-page accuracy and Gospel synchronization are outside this claim.",
        "reproducibility": "The current Doran handoff has a clean-process byte-identical replay bound in current-checks.json.",
        "schema": "The header-bound TEI passes the vendored TEI P5 validator without changing the reviewed body.",
        "closure": "Source XML, scan, package, oracle, known errors and quarantine are bound to this Doran selection.",
    }
    technical = {
        "producer": {"id": manifest.record["converter"]["id"], "path": make_file_binding(stage, stage / MANIFEST)},
        "checker": {"id": manifest.record["validator"]["id"], "path": make_file_binding(stage, stage / MANIFEST)},
        "shared_assumptions": ["Producer and checker share the retained DjVuXML page/word model and TEI schema; the checker traverses source and candidate independently."],
        "independent_corroboration": "Retained scan inspection located three OCR errors and 21 leaves with no OCR; these are quarantined rather than silently corrected.",
    }
    for name, description in descriptions.items():
        proof = write_json(stage, EVIDENCE / f"{name}.json", common | {"scope": SCOPE, "status": "pass",
                           "command": COMMAND, "exit_code": 0, "description": description,
                           "oracle_report_sha256": report.sha256,
                           "source_manifest_sha256": manifest.sha256,
                           "package_sha256": package.sha256})
        technical[name] = {"path": proof, "status": "pass", "command": COMMAND, "exit_code": 0}
    coverage = {"status": "partial", "declared": SCOPE, "reached": ["ocr-leaves-1-362"],
                "inspected": ["ocr-leaves-1-362/leaf-11", "ocr-leaves-1-362/leaf-13"],
                "unreviewed": ["scan-collation", "gospel-synchronization"]}
    review = {"reviewer": "agent:robertson-doran-ocr-install", "reviewed_at": stamp, "coverage": coverage,
              "source_quality_uncertainty": ["Scan-level OCR accuracy is unverified.", "The 21 no-OCR leaves include a printed map and support matter; image-only text is not represented."],
              "discrepancies": ["Scan leaf 11 CHAIR/INTERPRETATION appears as CHAIB/INTEBPRETATION in OCR and TEI.",
                                "Scan leaf 13 DAUGHTER appears as DAUGHTEB in OCR and TEI."],
              "unreviewed_residuals": ["Other scan/OCR differences have not been exhaustively collated.",
                                       "Source columns do not establish parallel Gospel passage relationships."]}
    review_path = write_json(stage, EVIDENCE / "review.json", common | review | {"scope": SCOPE,
                             "evidence": ["integration/robertson-harmony-v2/publication-hold-20261008.md",
                                          "integration/robertson-doran-current/current-checks.json"]})
    decision = {"source_local_disposition": "Accept exact retained Doran OCR text for internal use only; exclude affected text from public rows.",
                "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                "assessed_at": stamp, "supported_scope": SCOPE,
                "unresolved_claims": ["scan-level OCR accuracy", "image-only text", "Gospel synchronization", "source-layer rights"],
                "unassessed_stronger_claims": ["complete printed book transcription", "human verification", "public release eligibility"]},
                "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
              source_accounting_path=accounting, scope=scope, technical=technical,
              review=review | {"report_path": review_path}, representation_revision=revision, decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--promoted", type=Path)
    args = parser.parse_args()
    acceptance = prepare(args.stage)
    if args.promoted is None:
        print(json.dumps({"stage_acceptance": str(acceptance)}))
        return
    promoted = promote_accepted_master(args.stage, acceptance_path=acceptance, destination=args.promoted)
    result = install_accepted_work(ROOT, promoted.destination_root, work_id=WORK_ID)
    print(json.dumps({"acceptance": str(promoted.acceptance_path), "install": result}, default=str))


if __name__ == "__main__":
    main()
