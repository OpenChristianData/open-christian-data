"""Stage a bounded agent acceptance of Lightfoot's repaired PG 50857 witness.

The historical flat master and blocked acceptance remain untouched. This tool
requires the exact current structured candidate and reruns its independent oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree
from build.tei.lightfoot_colossians_philemon_oracle import _oracle
from ocd_kernel.library._common import PipelineError
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
WORK = Path("library/works/lightfoot-colossians-philemon")
EDITION = WORK / "forms/lightfoot-english/editions/pg50857"
EVIDENCE = WORK / "integration/structured-electronic-agent-handoff-v2"
MANIFEST = Path("sources/commentaries/lightfoot-colossians-philemon/lightfoot-colossians-philemon.source-manifest.json")
SOURCE = Path("raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt")
REVIEW_ROOT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-10-structural-audit")
RECEIPTS = (
    "97-lightfoot-repair-handoff.md",
    "106-lightfoot-current-admission-20260922.md",
    "113-lightfoot-current-locus-review-20260924.md",
    "114-lightfoot-current-additional-loci-review-20260925.md",
    "115-lightfoot-agent-review-handoff-20260925.md",
    "116-lightfoot-remaining-loci-review-20260925.md",
)
SOURCE_SHA = "a97cb49964906a2c158a0444cfdc3b0daf13261620c919a90f1333a98ac0b913"
MANIFEST_SHA = "18ad9da1fba21ceac902c1c79eabbb5b8b0e8a366b5dea1e4c638f6c0e2b6600"
PACKAGE_SHA = "bd07672259b8a1d0898243035ae76bd1724f748bfa1ba8d6dee466ebf4a9bd08"
TEI_SHA = "cf5546f92b83cd67d15ca9f79b4b216c8c06e0e1850b5daf17861c693e6cf088"
HISTORICAL_ACCEPTANCE_SHA = "a8ae66b09494be0bb0816925d59e25f2fbc4139744b26dfaa48907cdf0f99b82"
HISTORICAL_MASTER_SHA = "0c3dc837da00b018c5414831c20050ddfe06fe505fae90dae03899550f30d82f"
IDENTITY = {
    "work_id": "lightfoot-colossians-philemon",
    "textual_form_id": "lightfoot-english",
    "edition_id": "pg50857",
    "acquisition_id": "pg50857-text",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _copy(stage: Path, relative: Path, data: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _write(stage: Path, relative: Path, value: object) -> Path:
    return _copy(stage, relative, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def prepare(root: Path, package_home: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    package_home = package_home.resolve(strict=True)
    if stage.exists():
        raise PipelineError("Lightfoot acceptance stage must be fresh")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    package = CandidatePackage.load(package_home / "package")
    if manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA:
        raise PipelineError("Lightfoot source manifest or candidate package changed")
    original = package.member_bytes("content.tei.xml")
    if _sha(original) != TEI_SHA or package.manifest.get("status") != "nonaccepted":
        raise PipelineError("Lightfoot reviewed TEI changed")
    source_bytes = resolve_repo_path(root, SOURCE.as_posix()).read_bytes()
    if _sha(source_bytes) != SOURCE_SHA:
        raise PipelineError("Lightfoot retained source changed")
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or report.findings:
        raise PipelineError("Lightfoot independent oracle did not pass")
    recorded_validation = json.loads((package_home / "validation.json").read_text(encoding="utf-8"))
    if (recorded_validation.get("status") != "pass"
            or recorded_validation.get("source_manifest_sha256") != MANIFEST_SHA
            or recorded_validation.get("candidate_sha256") != PACKAGE_SHA
            or recorded_validation.get("report_sha256") != report.sha256):
        raise PipelineError("Lightfoot recorded validation is not current")
    receipt_bytes = {name: (root / REVIEW_ROOT / name).read_bytes() for name in RECEIPTS}
    for name, content in receipt_bytes.items():
        source_marker = MANIFEST_SHA if name.startswith("106-") else SOURCE_SHA
        if source_marker.encode() not in content or TEI_SHA.encode() not in content:
            raise PipelineError(f"Lightfoot review receipt lost exact pair: {name}")
    acquisition = json.loads((root / EDITION / "acquisitions/pg50857-text.json").read_text(encoding="utf-8"))
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != len(source_bytes)):
        raise PipelineError("Lightfoot acquisition no longer binds exact retained source")
    historical_acceptance = (root / EDITION / "acceptance.json").read_bytes()
    historical_master = (root / EDITION / "master.tei.xml").read_bytes()
    if (_sha(historical_acceptance) != HISTORICAL_ACCEPTANCE_SHA
            or _sha(historical_master) != HISTORICAL_MASTER_SHA):
        raise PipelineError("Lightfoot historical acceptance or flat master changed")
    old_acceptance = json.loads(historical_acceptance)
    if (old_acceptance["decision"]["agent_assessment"]["status"] != "blocked"
            or old_acceptance["decision"]["blockers"][0]["id"] != "missing-source-structure"):
        raise PipelineError("Lightfoot historical structural hold changed")
    now = datetime.now(timezone.utc)
    revision = {
        "id": "lightfoot-structured-electronic-v2",
        "date": now.date().isoformat(),
        "note": "Accept the repaired structured TEI for the retained PG 50857 electronic witness.",
    }
    source = {
        "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA,
        "source_bytes": len(source_bytes),
        "source_scope": retained[0]["scope"],
    }
    derived = bind_reviewed_header(
        original, expected_sha256=TEI_SHA, identity=IDENTITY, source=source,
        source_url=acquisition["url"], declared_scope=source["source_scope"], revision=revision,
    )
    header = etree.fromstring(original).find("{http://www.tei-c.org/ns/1.0}teiHeader")
    header_end = ("</" + (header.prefix + ":" if header.prefix else "") + "teiHeader>").encode("utf-8")
    if derived.split(header_end, 1)[1] != original.split(header_end, 1)[1]:
        raise PipelineError("Lightfoot reviewed TEI body changed during header binding")
    shutil.copytree(root / WORK, stage / WORK)
    _copy(stage, SOURCE, source_bytes)
    _copy(stage, MANIFEST, (root / MANIFEST).read_bytes())
    staged_state = json.loads((stage / WORK / "state.json").read_text(encoding="utf-8"))
    for target in staged_state["targets"]:
        for reference in target["evidence"]:
            relative = Path(reference)
            if relative.is_absolute() or ".." in relative.parts:
                raise PipelineError("Lightfoot state evidence path is unsafe")
            if (stage / WORK / relative).is_file() or (stage / relative).is_file():
                continue
            _copy(stage, relative, (root / relative).read_bytes())
    evidence = stage / EVIDENCE
    for name in package.member_names:
        _copy(stage, EVIDENCE / "inputs/current-package" / name, package.member_bytes(name))
    _copy(stage, EVIDENCE / "inputs/current-package/manifest.json", (package_home / "package/manifest.json").read_bytes())
    _copy(stage, EVIDENCE / "inputs/validation.json", (package_home / "validation.json").read_bytes())
    _copy(stage, EVIDENCE / "inputs/historical-acceptance.json", historical_acceptance)
    _copy(stage, EVIDENCE / "inputs/historical-flat-master.tei.xml", historical_master)
    for name, content in receipt_bytes.items():
        _copy(stage, EVIDENCE / "inputs/reviews" / name, content)
    candidate = _copy(stage, EVIDENCE / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"Lightfoot acceptance TEI XSD failed: {errors[:3]}")
    scope = {
        "kind": "edition", "declared": source["source_scope"],
        "expected_members": [{"path": SOURCE.as_posix(), "position": 1}],
        "included_members": [{"path": SOURCE.as_posix(), "position": 1,
                              "bytes": len(source_bytes), "sha256": SOURCE_SHA,
                              "scope": source["source_scope"]}],
        "excluded_members": [],
    }
    common = {
        "identity": IDENTITY, "source": source,
        "candidate": make_file_binding(stage, candidate), "scope": source["source_scope"],
        "accepted_scope": {"kind": "edition", "declared": source["source_scope"]},
        "expected_members": scope["expected_members"],
        "included_members": scope["included_members"],
        "excluded_members": [], "missing_members": [], "unknown_members": [],
    }
    _write(stage, EVIDENCE / "source-accounting.json", common | {
        "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes),
        "current_manifest_sha256": MANIFEST_SHA,
        "current_package_sha256": PACKAGE_SHA,
    })
    command = "py -3 -m build.tools.prepare_lightfoot_structured_acceptance --stage <fresh-path>"
    technical = {
        "producer": {"id": package.manifest["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": ["Producer and oracle share the retained source and declared profile; the oracle independently traverses source roles and TEI structure."],
        "independent_corroboration": "Current independent oracle pass, source-line and structural mutation proof, deterministic reconstruction, and 33 exact-pair visual risk loci.",
    }
    proof_details = {
        "validation": "Current independent oracle passed and the header-derived TEI passed the vendored XSD.",
        "accounting": "The only retained source member and complete source-line crosswalk bind exact PG 50857 bytes.",
        "fidelity": "Structural repair covers 17 regions, range occurrences, paragraphs, native notes and joins; 33 current-pair visual risk loci show no wording or order discrepancy.",
        "reproducibility": "106 records two clean-process reproductions of identical TEI and package members; reviewed TEI body is byte-identical after header binding.",
        "schema": "Current candidate and header-derived acceptance TEI pass the vendored TEI P5 XSD.",
        "closure": "Current source manifest, candidate package, validation and review receipts are hash-bound in inputs; current oracle passed.",
    }
    input_bindings = {
        "source_manifest": make_file_binding(stage, stage / MANIFEST),
        "package_manifest": make_file_binding(stage, evidence / "inputs/current-package/manifest.json"),
        "validation": make_file_binding(stage, evidence / "inputs/validation.json"),
        "reviews": [make_file_binding(stage, evidence / "inputs/reviews" / name) for name in RECEIPTS],
        "historical_acceptance": make_file_binding(stage, evidence / "inputs/historical-acceptance.json"),
        "historical_flat_master": make_file_binding(stage, evidence / "inputs/historical-flat-master.tei.xml"),
    }
    for name, description in proof_details.items():
        path = _write(stage, EVIDENCE / f"{name}.json", common | {
            "status": "pass", "command": command, "exit_code": 0,
            "description": description, "inputs": input_bindings,
            "current_oracle_report_sha256": report.sha256,
        })
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    coverage = {
        "status": "partial", "declared": source["source_scope"],
        "reached": ["complete-retained-electronic-witness"],
        "inspected": ["complete-retained-electronic-witness/documented-risk-loci-33"],
        "unreviewed": ["complete-retained-electronic-witness/unsampled-source-text-outside-33-risk-loci"],
    }
    review = {
        "reviewer": "agent:lightfoot-structured-electronic-review",
        "reviewed_at": now.isoformat().replace("+00:00", "Z"),
        "coverage": coverage,
        "source_quality_uncertainty": ["Printed source typography and table geometry are not established from the retained electronic transcription."],
        "discrepancies": [],
        "unreviewed_residuals": ["Visual review sampled 33 documented risk loci rather than every source line or page."],
    }
    review_path = _write(stage, EVIDENCE / "review.json", common | review | {
        "review_receipts": input_bindings["reviews"],
        "current_oracle_report_sha256": report.sha256,
        "unassessed": ["human acceptance", "rights", "publication", "original print typography"],
    })
    decision = {
        "source_local_disposition": "Agent acceptance of the exact retained PG 50857 electronic witness and repaired structured TEI.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted", "actor": review["reviewer"],
            "assessed_at": review["reviewed_at"],
            "supported_scope": source["source_scope"],
            "unassessed_stronger_claims": ["exhaustive visual proofreading", "original print geometry or font identity", "human textual acceptance", "rights clearance", "publication"],
            "unresolved_claims": [],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate,
        source_accounting_path=evidence / "source-accounting.json", scope=scope,
        technical=technical, review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, default=Path("D:/Library/Open Christian Data/candidate-reviews/structural-resolution-20260910/lightfoot-current-20260922"))
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.candidate, args.stage)
    print(json.dumps({"status": "validated-pending", "acceptance_path": str(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
