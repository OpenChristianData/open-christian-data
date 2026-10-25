"""Stage Robertson Keywords' retained OCR as an internal, public-held master."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from build.tei.robertson_keywords_1906_ia_oracle import _oracle, check
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "robertson-keywords-in-the-teaching-of-jesus"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/keywords-english/editions/keywords-1906-abps"
ACQUISITION = EDITION / "acquisitions/keywords-1906-ia-keywordsinteachi01robe.json"
MANIFEST = Path("sources/structured-text/robertson-keywords-1906/closure-rebind-20261008.source-manifest.json")
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20261002/robertson-keywords-1906-closure-rebind-20261008-v1")
REPLAY = PACKAGE.with_name(PACKAGE.name + "-replay")
EVIDENCE = WORK / "integration/keywords-ocr-internal-v1"
RECONCILIATION = "reports/_logs/robertson-keywords-reconciliation-20261008-v1"
SCOPE = (
    "Internal representation of the exact retained 1906 ABPS DjVu OCR witness, with its "
    "existing scan-confirmed correction map: all 136 access-page carriers, seven chapters, "
    "front matter, indexes, bibliography, and appended matter. This preserves the reviewed "
    "OCR wording and structure, not verified print transcription. Six zero-word pages "
    "(3, 4, 6, 10, 14, 133) retain explicit gaps; later source-only inspection identifies "
    "blank leaves. Uncertain handwriting, barcode bars, uncollated OCR errors, rights, "
    "and all public text selection remain held."
)
COMMAND = "py -3 -m build.tools.accept_robertson_keywords_internal --stage <fresh-root>"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def copy(stage: Path, relative: str | Path) -> None:
    relative = Path(relative)
    source = resolve_repo_path(ROOT, relative.as_posix())
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def stage(destination: Path) -> dict[str, object]:
    destination = destination.absolute()
    if destination.exists() or not destination.parent.is_dir() or destination.parent.is_symlink() or destination.parent.is_junction():
        raise PipelineError("fresh stage under an ordinary existing parent required")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PACKAGE / "package")
    replay = CandidatePackage.load(REPLAY / "package")
    package.verify_integrity()
    replay.verify_integrity()
    if package.sha256 != "476874ce8cfb1a556c166d5c679e0c80937dcbdd3647b286ab88619fc26960c5" or package.sha256 != replay.sha256:
        raise PipelineError("reviewed package or replay changed")
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or report.findings:
        raise PipelineError("current maintained oracle did not pass")
    original = package.member_bytes("content.tei.xml")
    if hashlib.sha256(original).hexdigest() != "96996c35292eb78e524f1d504c9a71b90268d8d8344985a590b8924a7b68cf07":
        raise PipelineError("reviewed OCR TEI changed")
    for name in package.member_names:
        if package.member_bytes(name) != replay.member_bytes(name):
            raise PipelineError(f"replay member differs: {name}")
    saved = json.loads((PACKAGE / "validation.json").read_bytes())
    if saved["status"] != "pass" or saved["candidate_sha256"] != package.sha256 or saved["source_manifest_sha256"] != manifest.sha256:
        raise PipelineError("stored attestation differs")
    carriers = check(ROOT, original, package.member_bytes("source-accountability.json"), source_manifest=manifest.record)
    if carriers != {"pages": 136, "paragraphs": 1178, "lines": 3877}:
        raise PipelineError("reviewed carrier census changed")
    before = _files(ROOT / WORK)
    if any(name.endswith(("acceptance.json", "master.tei.xml")) for name in before):
        raise PipelineError("initial acceptance already exists")
    shutil.copytree(ROOT / WORK, destination / WORK)
    copy(destination, ".ocd-storage.json")
    copy(destination, MANIFEST)
    for target in json.loads((destination / WORK / "state.json").read_bytes())["targets"]:
        for reference in target.get("evidence", []):
            path = Path(reference)
            if path.parts[0] not in {"raw", "reports", "exports"} and not (destination / path).exists():
                copy(destination, path)
    acquisition = json.loads((destination / ACQUISITION).read_bytes())
    identity = dict(work_id=WORK_ID, textual_form_id="keywords-english", edition_id="keywords-1906-abps",
                    acquisition_id="keywords-1906-ia-keywordsinteachi01robe")
    source = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope", "source_kind")}
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat().replace("+00:00", "Z")
    revision = dict(id="keywords-retained-ocr-internal-v1", date=now.date().isoformat(),
                    note="Accept the retained OCR witness internally without further correction; known uncertainty and all public text remain held.")
    old = b"Nonaccepted OCR review candidate; rights and publication remain open."
    if original.count(old) != 1 or original.count(b'<revisionDesc status="candidate">') != 1:
        raise PipelineError("reviewed lifecycle header differs")
    header = original.replace(old, b"Internal OCR-witness master; printed-text accuracy, rights, and public selection remain held.", 1)
    header = header.replace(b'<revisionDesc status="candidate">', b'<revisionDesc status="approved">', 1)
    bound = bind_reviewed_header(header, expected_sha256=hashlib.sha256(header).hexdigest(), identity=identity,
                                 source=source, source_url=acquisition["url"], declared_scope=SCOPE, revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("acceptance changed the reviewed OCR body")
    evidence = destination / EVIDENCE
    evidence.mkdir(parents=True)
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(bound)
    if errors := validate_file(candidate):
        raise PipelineError(f"header-bound TEI schema failure: {errors[:3]}")
    for name in package.member_names:
        target = evidence / "inputs/package" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(package.member_bytes(name))
    shutil.copy2(PACKAGE / "validation.json", evidence / "inputs/validation.json")
    members = acquisition["retained_files"]
    expected = [dict(path=item["path"], position=pos) for pos, item in enumerate(members, 1)]
    included = [dict(path=item["path"], position=pos, bytes=item["bytes"], sha256=item["sha256"], scope=item["scope"])
                for pos, item in enumerate(members, 1) if pos in (1, 2)]
    excluded = [dict(path=item["path"], position=pos, reason="Retained comparison, scan-map, metadata or acquisition support; no separate reading text selected.")
                for pos, item in enumerate(members, 1) if pos not in (1, 2)]
    scope = dict(kind="selection", declared=SCOPE, expected_members=expected, included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=source, candidate=make_file_binding(destination, candidate),
                  expected_members=expected, included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    accounting = put(evidence / "source-accounting.json", common | dict(scope=source["source_scope"],
        accepted_scope=dict(kind="selection", declared=SCOPE), source_sha256=source["source_sha256"], source_bytes=source["source_bytes"],
        carriers=carriers, zero_word_pages=[3, 4, 6, 10, 14, 133], excluded_color_card_leaves=[0, 137],
        later_source_observation="Six zero-word leaves are blank, not demonstrated missing authored prose; original conservative TEI gaps remain unchanged.",
        source_observation=f"{RECONCILIATION}/image-evidence.json"))
    details = {
        "validation": "Fresh maintained source-manifest/package oracle passes with zero findings.",
        "accounting": "136 pages, 1178 paragraphs, 3877 lines; six zero-word leaves and copy-specific gaps explicit.",
        "fidelity": "Exact retained OCR and existing scan-confirmed mapping conservation; no exhaustive print fidelity claim.",
        "reproducibility": "Every sealed package member matches the independent-process closure-rebound replay.",
        "schema": "Header-bound candidate passes vendored TEI P5; reviewed text body is byte-identical.",
        "closure": "Fresh maintained validation verifies exact source, profile, policy, schema and oracle import bindings.",
    }
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]), checker=dict(id=manifest.record["validator"]["id"]),
        shared_assumptions=["Producer and checker share retained OCR and scan correction map; agreement does not establish print accuracy."],
        independent_corroboration="Reuse exact-body whole-page review and source-only blank-leaf/paratext observations; no fresh pixel or glyph review claimed.")
    for name, claim in details.items():
        proof = put(evidence / f"{name}.json", common | dict(scope=SCOPE, accepted_scope=dict(kind="selection", declared=SCOPE),
            status="pass", command=COMMAND, exit_code=0, claim=claim, candidate_package_sha256=package.sha256,
            source_manifest_sha256=manifest.sha256, oracle_report_sha256=report.sha256))
        technical[name] = dict(path=proof, status="pass", command=COMMAND, exit_code=0)
    review = dict(reviewer="agent:robertson-keywords-internal-ocr", reviewed_at=timestamp,
        coverage=dict(status="partial", declared=SCOPE, reached=["ocr-pages-1-136"], inspected=["ocr-pages-1-136"],
                      unreviewed=["exhaustive-print-collation"]),
        source_quality_uncertainty=["Uncollated OCR recognition errors remain possible.", "Handwriting on pages 7-9 and 135 and barcode bars on 136 remain untranscribed."],
        discrepancies=["Generic no-word gap wording is conservative; later source-only evidence identifies all six leaves as blank."],
        unreviewed_residuals=["Human verification, complete print fidelity, source-layer rights and public release eligibility."])
    review_path = put(evidence / "review.json", common | review | dict(scope=SCOPE,
        reused_evidence=[f"{RECONCILIATION}/reconciliation.md", f"{RECONCILIATION}/closure-rebind-verification.json",
                         f"{RECONCILIATION}/image-evidence.json"], prior_exposure="Inherited findings read before assessment; not blind review."))
    decision = dict(source_local_disposition="Accept the retained OCR selection internally; hold the entire work from public text selection.",
        blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=timestamp,
            supported_scope=SCOPE, unresolved_claims=[], unassessed_stronger_claims=["complete print fidelity", "rights clearance", "public eligibility", "human verification"]),
        human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(destination, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
        scope=scope, technical=technical, review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
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
    if _files(ROOT / WORK) != before:
        raise PipelineError("canonical work changed during staging")
    return dict(status="staged-and-validated", stage=destination.as_posix(), master_sha256=sha(master),
                acceptance_sha256=sha(acceptance), source_manifest_sha256=manifest.sha256,
                package_sha256=package.sha256, carriers=carriers, before=before, after=_files(destination / WORK))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.stage), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
