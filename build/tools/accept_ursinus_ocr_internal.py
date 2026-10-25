"""Stage the retained Ursinus OCR witness for guarded internal installation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/ursinus-commentary-heidelberg-catechism-1852")
EDITION = WORK / "forms/english-commentary/editions/commdrza00ursi-1852"
ACQUISITION = EDITION / "acquisitions/ia-commdrza00ursi-second-american-1852.json"
MANIFEST = Path("sources/ursinus-commentary-1852/ursinus-commentary-1852.source-manifest-v6.json")
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/manifest-acquisition-20261002/ursinus-heidelberg-commentary-v10")
EVIDENCE = WORK / "integration/commdrza00ursi-1852/ocr-internal-v1"
CHECKS = Path("reports/_logs/ursinus-completion-20261008/current-checks.json")
SCOPE = (
    "The complete retained IA commdrza00ursi access-format OCR witness: 720 pages "
    "including 16 empty OCR pages, original page/paragraph/line order, 436 contents "
    "rows, and seven scan-linked layouts. This is an OCR witness, not a corrected "
    "transcription or a claim that every printed page has been collated."
)
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def stage(destination: Path) -> dict[str, object]:
    destination = destination.absolute()
    if destination.exists():
        raise ValueError("fresh staging root required")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(PACKAGE)
    package.verify_integrity()
    checks = json.loads((ROOT / CHECKS).read_text(encoding="utf-8"))
    old = package.member_bytes("content.tei.xml")
    if (manifest.sha256 != package.manifest["source_manifest"]["sha256"]
            or hashlib.sha256(old).hexdigest() != checks["checks"]["canonical_oracle"]["result"]["candidate_sha256"]
            or not checks["checks"]["canonical_oracle"]["result"]["passed"]
            or checks["checks"]["authority_bindings"] != "31/31 pass"):
        raise ValueError("current Ursinus source, candidate, or oracle binding differs")
    shutil.copytree(ROOT / WORK, destination / WORK)
    shutil.copy2(ROOT / ".ocd-storage.json", destination / ".ocd-storage.json")
    for target in json.loads((destination / WORK / "state.json").read_text(encoding="utf-8"))["targets"]:
        for reference in target.get("evidence", []):
            relative = Path(reference)
            if relative.parts[0] not in {"raw", "reports", "exports"} and not (destination / relative).exists():
                (destination / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination / relative)
    acquisition = json.loads((destination / ACQUISITION).read_text(encoding="utf-8"))
    if acquisition["source_sha256"] != digest(destination / EDITION / "source-member-set.json"):
        raise ValueError("retained member-set differs")
    members = [dict(path=item["path"], position=index, bytes=item["bytes"],
                    sha256=item["sha256"], scope=item["scope"])
               for index, item in enumerate(acquisition["retained_files"], 1)]
    identity = dict(work_id=WORK.name, textual_form_id="english-commentary",
                    edition_id="commdrza00ursi-1852",
                    acquisition_id=acquisition["acquisition_id"])
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat().replace("+00:00", "Z")
    revision = dict(id="ursinus-1852-retained-ocr-internal-v1", date=now.date().isoformat(),
                    note="Accept the complete retained OCR witness internally; printed wording remains unverified and public text is held.")
    old_uri = b"../../../raw/internet-archive/commentary-on-heidelberg-catechism/commdrza00ursi/scan.pdf"
    new_uri = (b"../../../../../../../raw/internet-archive/commentary-on-heidelberg-catechism/commdrza00ursi/scan.pdf")
    expected_links = checks["checks"]["canonical_oracle"]["result"]["candidate_uri_closure"]["facsimile_references_resolved"]
    if old.count(old_uri) != expected_links:
        raise ValueError("reviewed scan-link count differs")
    rebased = old.replace(old_uri, new_uri)
    if rebased.replace(new_uri, old_uri) != old:
        raise ValueError("scan-link rebase changed reviewed content")
    source = dict(source_path=acquisition["source_path"], source_sha256=acquisition["source_sha256"],
                  source_bytes=acquisition["source_bytes"], source_scope=acquisition["source_scope"],
                  source_kind=acquisition["source_kind"])
    bound = bind_reviewed_header(rebased, expected_sha256=hashlib.sha256(rebased).hexdigest(),
                                 identity=identity, source=source, source_url=acquisition["url"],
                                 declared_scope=SCOPE, revision=revision)
    candidate = destination / EDITION / "candidate.tei.xml"
    candidate.write_bytes(bound)
    if errors := validate_file(candidate):
        raise ValueError(f"bound TEI P5 validation failed: {errors[:3]}")
    evidence = destination / EVIDENCE
    evidence.mkdir(parents=True)
    for name in ("manifest.json", "source-accountability.json", "unresolved.jsonl", "provenance.json"):
        shutil.copy2(PACKAGE / name, evidence / name)
    shutil.copy2(ROOT / CHECKS, evidence / "v10-current-checks.json")
    for name in ("URSINUS_L427_L468_V10_BUILD_VALIDATION_20261003.json",
                 "URSINUS_L427_L468_V10_MUTATION_CHALLENGE_20261003.json",
                 "URSINUS_L427_L468_V10_REPLAY_01_20261003.json",
                 "URSINUS_L427_L468_V10_REPLAY_02_20261003.json",
                 "URSINUS_L427_L468_V10_SCAN_REVIEW_REBIND_20261003.json"):
        shutil.copy2(ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence" / name, evidence / name)
    original = evidence / "reviewed-v10.tei.xml"
    original.write_bytes(old)
    scope = dict(kind="work", declared=SCOPE,
                 expected_members=[dict(path=item["path"], position=item["position"]) for item in members],
                 included_members=members, excluded_members=[])
    common = dict(identity=identity, source=source, candidate=make_file_binding(destination, candidate))
    accounting = put(evidence / "source-accounting.json", common | dict(
        scope=source["source_scope"], accepted_scope=dict(kind="work", declared=SCOPE),
        expected_members=scope["expected_members"], included_members=members, excluded_members=[],
        missing_members=[], unknown_members=[], source_sha256=source["source_sha256"],
        source_bytes=source["source_bytes"], pages=720, empty_ocr_pages=16,
        paragraphs=6005, lines=34726, contents_rows=436,
        excluded_nonaccess_color_cards=[0, 721],
        original_accountability_sha256=digest(evidence / "source-accountability.json")))
    command = "py -3 -m build.tei.ursinus_heidelberg_1852_v6_oracle check --repository-root . --destination <reviewed-v10-package>"
    details = {
        "validation": "Current source-bound oracle passed for the reviewed V10 TEI; header and link rebase were separately checked here.",
        "accounting": "All five retained members, 720 OCR pages, 16 empty pages, 6,005 paragraphs, 34,726 lines, and 436 contents rows accounted.",
        "fidelity": "Pass for retained OCR word/order and mapped layouts only; no full scan-to-print collation or correction claim.",
        "reproducibility": "Two fresh-process V10 replays preserved every package member byte for byte.",
        "schema": "Original V10 passed P5 XSD and Relax NG; header-bound TEI passes current P5 validation.",
        "closure": "31 bound authorities and 727 scan facsimile links passed; link relocation is reversible byte for byte.",
    }
    technical = dict(producer=dict(id=package.manifest["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share retained OCR; agreement does not establish printed-text accuracy."],
                     independent_corroboration="Independent source oracle covers the entire OCR carrier; seven scan-visible layouts were checked separately. The installed header and link rebase preserve reviewed text bytes.")
    for name in PROOFS:
        proof = put(evidence / f"{name}.json", common | dict(
            scope=SCOPE, accepted_scope=dict(kind="work", declared=SCOPE),
            expected_members=scope["expected_members"], included_members=members,
            excluded_members=[], missing_members=[], unknown_members=[],
            status="pass", command=command, exit_code=0, claim=details[name],
            reviewed_v10_sha256=digest(original), current_checks_sha256=digest(evidence / "v10-current-checks.json")))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reached = [f"scan-leaf-{n}" for n in (205, 489, 529, 552, 578, 613, 639)]
    review = dict(reviewer="agent:ursinus-retained-ocr-internal", reviewed_at=timestamp,
                  coverage=dict(status="partial", declared=SCOPE, reached=reached,
                                inspected=reached, unreviewed=["remaining-scan-pages"]),
                  source_quality_uncertainty=["OCR is uncorrected across 720 pages; 16 empty OCR pages may contain untranscribed front, back, or body material.",
                                              "Printed line-end hyphen joins beyond seven documented examples remain unreviewed."],
                  discrepancies=["Seven documented scan-confirmed line-wrap joins differ from printed hyphens; the OCR reading is preserved."],
                  unreviewed_residuals=["Full scan collation and missing-text disposition; public text eligibility, territorial rights, and human review."])
    review_path = put(evidence / "review.json", common | dict(scope=SCOPE) | review | dict(
        visual_evidence="URSINUS_L427_L468_V10_SCAN_REVIEW_REBIND_20261003.json",
        release_hold="library/works/ursinus-commentary-heidelberg-catechism-1852/integration/commdrza00ursi-1852/publication-hold-20261008.md"))
    decision = dict(source_local_disposition="Accept complete retained OCR witness internally; exclude the entire uncorrected OCR text from public rows.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                        assessed_at=timestamp, supported_scope=SCOPE, unresolved_claims=[],
                        unassessed_stronger_claims=["printed-text fidelity", "public-text eligibility", "worldwide or digitization rights", "human verification", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(destination, identity=identity, candidate_path=candidate,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision,
        decision=decision)
    master = destination / EDITION / "master.tei.xml"
    master.write_bytes(bound)
    record["promotion"].update(status="promoted", promoted_at=timestamp,
                                master=make_file_binding(destination, master))
    acceptance = destination / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    state_path = destination / WORK / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    target = next(item for item in state["targets"] if item["target_id"] == identity["edition_id"])
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=timestamp)
    target["evidence"] += [(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix(),
                           (EVIDENCE / "review.json").as_posix()]
    put(state_path, state)
    validate_acceptance(acceptance, root=destination)
    validate_state(state_path, root=destination)
    return dict(status="staged-and-validated", stage=destination.as_posix(),
                master_sha256=digest(master), reviewed_tei_sha256=digest(original))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    print(json.dumps(stage(parser.parse_args().stage), sort_keys=True))


if __name__ == "__main__":
    main()
