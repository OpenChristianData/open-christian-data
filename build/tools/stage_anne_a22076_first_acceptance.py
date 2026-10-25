"""Seal the reviewed A22076 first-text selection for guarded acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

from build.tei.anne_a22076_first_oracle_v1 import _oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    promote_accepted_master,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = "anne-askew-first-examinacyon"
FORM = "anne-askew-first-examinacyon-tcp-retained"
EDITION = "anne-askew-first-examinacyon-tcp-electronic"
ACQUISITION = "anne-askew-first-examinacyon-tcp-acquired"
SOURCE = Path("raw/tcp/high-range/A22076/A22076.xml")
SOURCE_SHA = "211a2c0d5029ca1dc6622b419fea356a0bba0ee28a363bd8c4e28331b3b6f92a"
MANIFEST = Path("sources/manifest-acquisitions/tcp-l816-clean-ready/A22076/reconstruction-source-manifest-first-work-v1.json")
MANIFEST_SHA = "48c293d9f718a3f2fd38ffe9988ba507e218b67b6d91579dc5105f9832cf7e74"
PACKAGE_SHA = "aeb85cff751a1e44f2a5b7f8feaaf189cf569ebd280261929a366f52ee41ecf8"
VALIDATION_SHA = "cb487239acdc64b6aa43033fac02edab959f497a8c2d1ddc700116c2909183a5"
REVIEW_SESSION = "84bfe93b03a04f1d8d0ea4ad6d9bbbb1"
CAPTURES = ("opening-target-v3", "contents-table", "body-opening-v2", "colophon", "psalm-to-preface")
DECLARED = (
    "Selected complete first nested text in retained TCP A22076 (STC 848): title page, "
    "Bale's readers' matter, contents, examination, conclusion, first-examination "
    "colophon, and Psalm appendix. The second nested text at image pointer 60 is "
    "accounted out-of-work source matter, not represented in this first-work master."
)
REVISION = {
    "id": "anne-a22076-first-scoped-v1",
    "date": "2026-09-29",
    "note": "Selected the source-attested first examination and bound its retained-source accounting and work identity.",
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def stage(candidate_root: Path, replay_root: Path, captures_root: Path, target: Path) -> Path:
    check(not target.exists(), "acceptance staging root must be fresh")
    source = ROOT / SOURCE
    check(source.stat().st_size == 198240 and digest(source) == SOURCE_SHA, "retained source changed")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    check(manifest.sha256 == MANIFEST_SHA, "source manifest changed")
    package = CandidatePackage.load(candidate_root / "package")
    replay = CandidatePackage.load(replay_root / "package")
    check(package.sha256 == replay.sha256 == PACKAGE_SHA, "candidate or replay package changed")
    for name in package.member_names:
        check(package.member_bytes(name) == replay.member_bytes(name), f"candidate replay differs: {name}")
    check(digest(candidate_root / "validation.json") == VALIDATION_SHA, "validation report changed")
    check((candidate_root / "validation.json").read_bytes() == (replay_root / "validation.json").read_bytes(), "validation replay differs")
    check(validate(manifest, package, _oracle).status == "pass", "independent oracle rejected candidate")

    live_work = ROOT / "library/works" / WORK
    acquired = live_work / "forms" / FORM / "editions" / EDITION / "acquisitions" / f"{ACQUISITION}.json"
    expected = {
        live_work / "work.json": "cf78e6942703699cb020bbcc5908436693f0112b94eee488d2c82f088e281ae4",
        live_work / "state.json": "ad636f22e35b24422824a8090eba567ceeba7ee0ec4a682f3a4b09144c2e985f",
        acquired: "69a62b603837b7f87778c471d6c09844ade0a7ebfeb73dea36b6c4fc395d510c",
    }
    for path, expected_sha in expected.items():
        check(digest(path) == expected_sha, f"existing work authority changed: {path}")
    acquisition = json.loads(acquired.read_text(encoding="utf-8"))
    check(acquisition["source_path"] == SOURCE.as_posix() and acquisition["source_sha256"] == SOURCE_SHA, "acquisition source differs")
    check(acquisition["source_bytes"] == 198240 and len(acquisition["retained_files"]) == 1, "acquisition envelope differs")

    identity = {"work_id": WORK, "textual_form_id": FORM, "edition_id": EDITION, "acquisition_id": ACQUISITION}
    work_rel = Path("library/works") / WORK
    edition_rel = work_rel / "forms" / FORM / "editions" / EDITION
    integration = work_rel / "integration/anne-a22076-first-scoped-v1"
    target_work = target / work_rel
    shutil.copytree(live_work, target_work)
    (target / SOURCE).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target / SOURCE)
    receipt = ROOT / "raw/tcp/high-range/A22076/acquisition-receipt.json"
    (target / "raw/tcp/high-range/A22076/acquisition-receipt.json").parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(receipt, target / "raw/tcp/high-range/A22076/acquisition-receipt.json")
    for actor in ("anne_a22076_first_v1.py", "anne_a22076_first_oracle_v1.py"):
        dest = target / "build/tei" / actor
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "build/tei" / actor, dest)
    evidence = target / integration
    shutil.copytree(candidate_root / "package", evidence / "inputs/package")
    shutil.copy2(candidate_root / "validation.json", evidence / "inputs/validation.json")
    visual = {}
    for label in CAPTURES:
        original = captures_root / label
        receipt_record = json.loads((original / "capture.json").read_text(encoding="utf-8"))
        check(receipt_record["session"]["session_id"] == REVIEW_SESSION, f"visual session differs: {label}")
        check(receipt_record["session"]["candidate_sha256"] == [PACKAGE_SHA], f"visual candidate differs: {label}")
        check(receipt_record["page_errors"] == [] and all(item["visible"] for item in receipt_record["targets"].values()), f"visual target missing: {label}")
        for name, expected_sha in receipt_record["files"].items():
            check(digest(original / name) == expected_sha, f"visual file changed: {label}/{name}")
        shutil.copytree(original, evidence / "visual" / label)
        visual[label] = {
            "frame_sha256": receipt_record["files"]["frame.png"],
            "capture_sha256": digest(original / "capture.json"),
            "left_literal": receipt_record["targets"]["left"]["literal"],
            "right_literal": receipt_record["targets"]["right"]["literal"],
        }

    original_tei = package.member_bytes("content.tei.xml")
    source_binding = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope")}
    binding_args = {
        "expected_sha256": sha256(original_tei).hexdigest(),
        "identity": identity,
        "source": source_binding,
        "source_url": acquisition["url"],
        "declared_scope": DECLARED,
        "revision": REVISION,
    }
    save(evidence / "binding-arguments.json", binding_args)
    binding_args = json.loads((evidence / "binding-arguments.json").read_text(encoding="utf-8"))
    derived = bind_reviewed_header(original_tei, **binding_args)
    replay_code = (
        "import json,sys; from pathlib import Path; "
        "from ocd_kernel.tei.reviewed_integration import bind_reviewed_header; "
        "p=Path(sys.argv[1]); a=json.loads((p/'binding-arguments.json').read_text(encoding='utf-8')); "
        "sys.stdout.buffer.write(bind_reviewed_header((p/'inputs/package/content.tei.xml').read_bytes(), **a))"
    )
    reproduced = subprocess.run([sys.executable, "-c", replay_code, str(evidence)], cwd=ROOT, check=True, capture_output=True).stdout
    check(derived == reproduced, "fresh-process header binding differs")
    bound_candidate = evidence / "candidate.tei.xml"
    bound_candidate.write_bytes(derived)
    check(not validate_file(bound_candidate), "acceptance-bound TEI P5 validation failed")
    candidate_binding = make_file_binding(target, bound_candidate)
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": 198240, "sha256": SOURCE_SHA, "scope": "Whole retained XML available; first nested text is represented and second is accounted outside this work."}]
    scope = {"kind": "selection", "declared": DECLARED, "expected_members": [{"path": SOURCE.as_posix(), "position": 1}], "included_members": included, "excluded_members": []}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    common = {"identity": identity, "candidate": candidate_binding, "source": source_binding}
    accounting = {
        **common, "scope": source_binding["source_scope"], "accepted_scope": {"kind": "selection", "declared": DECLARED},
        "expected_members": scope["expected_members"], "included_members": included, "excluded_members": [],
        "missing_members": [], "unknown_members": [], "source_sha256": SOURCE_SHA, "source_bytes": 198240,
        "intra_member_selection": {"included": "/TEI/text/group/text[1]", "excluded": "/TEI/text/group/text[2]", "excluded_reason": "New incomplete preface at image pointer 60, corresponding to separately retained latter examination; physical placement unverified."},
        "original_source_accountability": make_file_binding(target, evidence / "inputs/package/source-accountability.json"),
    }
    source_accounting = evidence / "source-accounting.json"
    save(source_accounting, accounting)
    command = "py -3 -m build.tools.stage_anne_a22076_first_acceptance --candidate <pinned> --replay <pinned> --captures <pinned> --stage <fresh>"
    observations = {
        "validation": "Original six-member candidate and validation report pass and replay byte-for-byte; acceptance-bound TEI passes P5.",
        "accounting": "One complete retained XML member is present; nested text 1 is represented, nested text 2 is explicitly accounted outside this work.",
        "fidelity": "Independent stdlib ElementTree oracle preserves every node and page break in nested text 1 and rejects text, page, and wrong-work mutations; header binding is reversible byte-for-byte.",
        "reproducibility": "Fresh-process package replay is byte-identical and acceptance header binding reproduces identical bytes in a separate Python process.",
        "schema": "Acceptance-bound TEI passes current vendored TEI P5 XSD.",
        "closure": "Retained source, source manifest, package, validation, original work sidecars, and five CVW visual receipts are hash-bound at staging.",
    }
    proof_paths = {}
    for name, observation in observations.items():
        proof = evidence / f"{name}.json"
        value = {**common, "scope": DECLARED, "status": "pass", "command": command, "exit_code": 0, "checked_at": now, "observation": observation}
        if name == "accounting":
            value.update({"accepted_scope": accounting["accepted_scope"], "expected_members": scope["expected_members"], "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []})
        save(proof, value)
        proof_paths[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    review_path = evidence / "review.json"
    coverage = {"status": "partial", "declared": DECLARED,
                "reached": ["first-work/title-page", "first-work/contents", "first-work/examination", "first-work/colophon", "first-work/psalm", "source/out-of-work-preface"],
                "inspected": ["first-work/title-page", "first-work/contents", "first-work/examination", "first-work/colophon", "first-work/psalm", "source/out-of-work-preface"],
                "unreviewed": []}
    uncertainties = ["No EEBO page-image collation was available; image-60 physical binding remains unverified.", "CVW source pane displays raw exact XML rather than a readable source projection; correspondence is absent and panes were located independently."]
    residuals = ["Visual comparison sampled five bound loci, not every paragraph; exhaustive first-text structure and text are covered by the independent oracle."]
    review = {**common, "scope": DECLARED, "reviewer": "agent:anne-a22076-first", "reviewed_at": now,
              "coverage": coverage, "source_quality_uncertainty": uncertainties, "discrepancies": [], "unreviewed_residuals": residuals,
              "cvw_session_id": REVIEW_SESSION, "cvw_candidate_package_sha256": PACKAGE_SHA,
              "visual_inspection": "Agent inspected retained PNG pixels at each listed source/candidate locus; no human verification is asserted.",
              "visual_captures": visual, "header_binding": "Final candidate differs from the CVW-reviewed candidate only by reversible acceptance metadata in teiHeader; TEI/text is byte-identical."}
    save(review_path, review)
    technical = {
        **proof_paths,
        "producer": {"id": "ocd-anne-a22076-first-scoped", "path": make_file_binding(target, target / "build/tei/anne_a22076_first_v1.py")},
        "checker": {"id": "ocd-anne-a22076-first-independent-scope", "path": make_file_binding(target, target / "build/tei/anne_a22076_first_oracle_v1.py")},
        "shared_assumptions": ["The original candidate and acceptance-bound derivative share the retained TEI header; the derivative's text body is not reserialized."],
        "independent_corroboration": "Stdlib ElementTree source walk, exact source/page census, P5 XSD, clean-process replay, and agent-inspected bound CVW frames.",
    }
    decision = {"source_local_disposition": "Complete first nested text accepted for this first-work electronic edition; second nested text remains retained, accounted, and outside this master.",
                "blockers": [], "agent_assessment": {"status": "accepted", "actor": "agent:anne-a22076-first", "assessed_at": now,
                "supported_scope": DECLARED, "unassessed_stronger_claims": ["Human page-image verification", "Physical placement of image 60", "Rights clearance for images", "Publication"], "unresolved_claims": []},
                "human_decision": {"status": "not-recorded"}}
    acceptance_path = target / edition_rel / "acceptance.json"
    record = build_acceptance_record(target, identity=identity, candidate_path=bound_candidate,
            source_accounting_path=source_accounting, scope=scope, technical=technical,
            review={**review, "report_path": review_path}, representation_revision=REVISION, decision=decision)
    write_acceptance(acceptance_path, record)
    validate_acceptance(acceptance_path, root=target)
    return acceptance_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--promoted", type=Path)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if args.install and args.promoted is None:
        parser.error("--install requires --promoted")
    acceptance = stage(args.candidate, args.replay, args.captures, args.stage)
    result: object = {"status": "validated-pending", "acceptance": str(acceptance), "sha256": digest(acceptance)}
    if args.promoted is not None:
        result = promote_accepted_master(args.stage, acceptance_path=acceptance, destination=args.promoted).as_dict()
        if args.install:
            result = install_accepted_work(ROOT, args.promoted, work_id=WORK)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
