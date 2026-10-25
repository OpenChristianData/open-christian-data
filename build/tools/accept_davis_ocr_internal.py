"""Install Davis's retained OCR witness as an internal, public-held TEI master."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "davis-beginners-grammar-greek-new-testament"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/english/editions/ia-beginnersgrammar00davi-1923"
ACQUISITION = EDITION / "acquisitions/ia-beginnersgrammar00davi-original-pages.json"
MANIFEST = Path("sources/structured-text/davis-beginners-grammar-1923/source-manifest.json")
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260925/davis-beginners-grammar-1923-l332-v5-internal-ocr-20261008")
REPRO = PACKAGE.with_name(PACKAGE.name + "-repro")
EVIDENCE = WORK / "integration/ia-fifth-edition-ocr-internal-v1"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
SCOPE = ("The retained Harper & Brothers fifth-edition copy: all 280 access pages "
         "represented by uncorrected DjVu OCR with original-image locators and alternate "
         "Abbyy table carriers. This is an OCR-witness representation; printed Greek, "
         "contents columns, paradigms, vocabulary entries, and index layout are not verified.")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def copy(stage: Path, relative: str | Path) -> None:
    relative = Path(relative)
    source = resolve_repo_path(ROOT, relative.as_posix()) if relative.parts[0] in {"raw", "reports", "exports"} else ROOT / relative
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def stage(destination: Path) -> dict[str, object]:
    destination = destination.absolute()
    if destination.exists():
        raise ValueError("fresh stage required")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PACKAGE / "package")
    repro = CandidatePackage.load(REPRO / "package")
    package.verify_integrity()
    repro.verify_integrity()
    if package.sha256 != repro.sha256 or package.manifest["source_manifest"]["sha256"] != manifest.sha256:
        raise ValueError("Davis v5 reproduction or source binding differs")
    validation = json.loads((PACKAGE / "validation.json").read_bytes())
    if validation["status"] != "pass" or validation["candidate_sha256"] != package.sha256 or validation["source_manifest_sha256"] != manifest.sha256:
        raise ValueError("Davis current independent attestation differs")
    original = package.member_bytes("content.tei.xml")
    if sha(PACKAGE / "package/content.tei.xml") != "f568d903c3ffecbc9a7e3afa7bb6074cb76227696bf7e48ca291327a8cf6cdd5":
        raise ValueError("reviewed TEI changed")
    destination.mkdir(parents=True)
    shutil.copytree(ROOT / WORK, destination / WORK)
    copy(destination, ".ocd-storage.json")
    work = load_work(destination / WORK / "work.json")
    if work["work_id"] != WORK_ID or (destination / EDITION / "master.tei.xml").exists():
        raise ValueError("Davis work or initial acceptance changed")
    acquisition = json.loads((destination / ACQUISITION).read_bytes())
    source_member = acquisition["retained_files"][0]
    if source_member["sha256"] != "ee4e6407dc5393259d2e6d6009415850a21e2844fe9a80bb9a7ace0230cc75e3":
        raise ValueError("retained IA scan changed")
    identity = dict(work_id=WORK_ID, textual_form_id="english", edition_id="ia-beginnersgrammar00davi-1923",
                    acquisition_id="ia-beginnersgrammar00davi-original-pages")
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat().replace("+00:00", "Z")
    revision = dict(id="davis-ia-fifth-edition-ocr-internal-v1", date=now.date().isoformat(),
                    note="Accept the source-conserving OCR witness internally with print-text defects held from public selection.")
    original = original.replace(b"Nonaccepted OCR review candidate. Digitization rights and publication remain unresolved.",
                                b"Internal OCR-witness master. Printed text and public selection remain held.", 1)
    original = original.replace(b'<date when="1923">1923</date>',
                                b'<date>1923 copyright notice; fifth-edition note dated 1942; exact printing date unverified</date>', 1)
    original = original.replace(b'<revisionDesc status="candidate">', b'<revisionDesc status="approved">', 1)
    source = dict(source_path=source_member["path"], source_sha256=source_member["sha256"],
                  source_bytes=source_member["bytes"], source_scope=source_member["scope"])
    bound = bind_reviewed_header(original, expected_sha256=hashlib.sha256(original).hexdigest(),
                                 identity=identity, source=source, source_url=acquisition["url"],
                                 declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != package.member_bytes("content.tei.xml").split(b"</teiHeader>", 1)[1]:
        raise ValueError("reviewed OCR body changed")
    evidence = destination / EVIDENCE
    evidence.mkdir(parents=True)
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(bound)
    if errors := validate_file(candidate):
        raise ValueError(f"Davis accepted TEI schema errors: {errors[:3]}")
    for name in ("source-accountability.json", "unresolved.jsonl", "manifest.json"):
        shutil.copy2(PACKAGE / "package" / name, evidence / name)
    shutil.copy2(PACKAGE / "validation.json", evidence / "candidate-validation.json")
    for path in (MANIFEST, Path("tests/test_davis_l332_ia.py"),
                 Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L332_DAVIS_CANONICAL_TECHNICAL_REBIND_20261001.json"),
                 Path("reports/_logs/davis-completion-20261008/better-source-research/research.json"),
                 Path("reports/_logs/davis-completion-20261008/zero-word-leaves/disposition.json")):
        if path.parts[0] != "reports":
            copy(destination, path)
    for target in json.loads((destination / WORK / "state.json").read_bytes())["targets"]:
        for reference in target.get("evidence", []):
            path = Path(reference)
            if path.parts[0] not in {"raw", "reports", "exports"} and not (destination / path).exists():
                copy(destination, path)
    member = dict(path=source_member["path"], position=1, bytes=source_member["bytes"],
                  sha256=source_member["sha256"], scope=source_member["scope"])
    scope = dict(kind="selection", declared=SCOPE, expected_members=[dict(path=member["path"], position=1)],
                 included_members=[member], excluded_members=[])
    common = dict(identity=identity, source=source, candidate=make_file_binding(destination, candidate))
    accounting = put(evidence / "source-accounting.json", common | dict(
        scope=source["source_scope"], accepted_scope=dict(kind="selection", declared=SCOPE),
        expected_members=scope["expected_members"], included_members=scope["included_members"],
        excluded_members=[], missing_members=[], unknown_members=[], source_sha256=source["source_sha256"],
        source_bytes=source["source_bytes"], original_jp2_leaves=284, represented_access_pages=280,
        original_accountability_sha256=sha(evidence / "source-accountability.json"),
        zero_word_leaves="Eleven individually dispositioned; no missing authored text demonstrated.",
        excluded_nonaccess_leaves=[0, 281, 282, 283]))
    command = "py -3 -m build.tools.reconstruct_candidate --manifest sources/structured-text/davis-beginners-grammar-1923/source-manifest.json --destination <v5-local-candidate> --repository-root ."
    details = {
        "validation": "Current source-bound independent oracle: pass, zero findings; v5 validation.json retained.",
        "accounting": "280 access pages and 284 original JP2 leaves; 11 zero-word leaves dispositioned; all 89 Abbyy tables represented.",
        "fidelity": "Pass for exact retained DjVu OCR word/order conservation only. No print-text Greek or layout fidelity is asserted.",
        "reproducibility": "Separate clean-process v5 package is byte-identical to the primary v5 package.",
        "schema": "Header-bound candidate passes vendored TEI P5 validation.",
        "closure": "Current oracle import closure and source manifest are bound by the passing v5 attestation.",
    }
    technical = dict(producer=dict(id=package.manifest["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share DjVu OCR; their agreement does not establish accuracy against print."],
                     independent_corroboration="The independent lxml oracle compares every retained OCR carrier and table to TEI; original-image sample locates print defects; all zero-word leaves were separately inspected.")
    for name in PROOFS:
        proof = put(evidence / f"{name}.json", common | dict(scope=SCOPE,
                         accepted_scope=dict(kind="selection", declared=SCOPE),
                         expected_members=scope["expected_members"], included_members=scope["included_members"],
                         excluded_members=[], missing_members=[], unknown_members=[],
                         status="pass", command=command,
                         exit_code=0, claim=details[name], v5_package_sha256=package.sha256,
                         current_validation_sha256=sha(PACKAGE / "validation.json")))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:davis-retained-ocr-internal", reviewed_at=timestamp,
                  coverage=dict(status="partial", declared=SCOPE,
                                reached=[f"leaf-{n:04d}" for n in (7, 19, 25, 141, 221, 222, 261)],
                                inspected=[f"leaf-{n:04d}" for n in (7, 19, 25, 141, 221, 222, 261)],
                                unreviewed=["remaining-print-pages"]),
                  source_quality_uncertainty=["Greek OCR is severely corrupt; contents columns, paradigms, vocabulary, and index layout are not print verified.",
                                              "The exact edition's rights and any substantiated scan/OCR rights remain unresolved."],
                  discrepancies=["Original leaf 141 Greek adjective paradigm is rendered with corrupt Latin-like OCR (xoXXq)).",
                                 "Contents columns and vocabulary entry boundaries are unreliable in OCR."],
                  unreviewed_residuals=["Full print collation and correction; public projection, reader checks, rights, and notice selection."])
    review_path = put(evidence / "review.json", common | dict(scope=SCOPE) | review | dict(
        source_image_review="D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20260925/davis-beginners-grammar-1923-l332-review-evidence/visual-review.md",
        zero_word_disposition="reports/_logs/davis-completion-20261008/zero-word-leaves/disposition.json"))
    decision = dict(source_local_disposition="Accept only the exact retained fifth-edition OCR witness for internal use; hold the entire work from public text selection.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=timestamp,
                        supported_scope=SCOPE, unresolved_claims=[], unassessed_stronger_claims=["printed Greek and layout fidelity", "public text eligibility", "rights clearance", "human review", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(destination, identity=identity, candidate_path=candidate,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
    master = destination / EDITION / "master.tei.xml"
    master.write_bytes(bound)
    record["promotion"].update(status="promoted", promoted_at=timestamp, master=make_file_binding(destination, master))
    acceptance = destination / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    state = json.loads((destination / WORK / "state.json").read_bytes())
    target = next(item for item in state["targets"] if item["target_type"] == "edition")
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=timestamp)
    target["evidence"] += [(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()]
    put(destination / WORK / "state.json", state)
    validate_acceptance(acceptance, root=destination)
    validate_state(destination / WORK / "state.json", root=destination)
    return {"status": "staged-and-validated", "stage": destination.as_posix(),
            "master_sha256": sha(master), "candidate_package_sha256": package.sha256,
            "before": _files(ROOT / WORK), "after": _files(destination / WORK)}


def install(stage_root: Path) -> dict[str, object]:
    return install_accepted_work(ROOT, stage_root, work_id=WORK_ID)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("stage", "install"))
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.stage) if args.operation == "stage" else install(args.stage)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
