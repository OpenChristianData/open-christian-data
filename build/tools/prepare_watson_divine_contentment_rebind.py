"""Stage a versioned Divine Contentment acceptance evidence refresh."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from build.tools import prepare_watson_divine_contentment_acceptance as historical
from build.tools import prepare_watson_divine_contentment_closure_rebind as closure
from build.tei.watson_divine_contentment_oracle import _oracle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_glob, io_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.validate import validate_file

ROOT = historical.ROOT
WORK = historical.WORK
EDITION = historical.EDITION
ACQUISITION = historical.ACQUISITION
SOURCE = historical.SOURCE
HISTORICAL_MANIFEST = historical.MANIFEST
CURRENT_MANIFEST = closure.CURRENT_MANIFEST
CURRENT_MANIFEST_SHA = "0503cd1648a9bcc34974015679d82aedbc89cedcdc1de346a847433c5aebea6e"
CURRENT_PACKAGE_SHA = "7eec9872424493a480b8a70bdb1adfea3e2f284726d1d929851d2e1d99b919c1"
CURRENT_VALIDATION_SHA = "e2fd5c0f82ef69a304f2f28c070fdd4329d3fa24fb878470e1692043fa42c0bc"
INSTALLED_ACCEPTANCE_SHA = "622e6da3701484de32b833ee7e63d8f67f8b07fd7be9c7e2b8f275cb453b1e68"
INSTALLED_MASTER_SHA = closure.MASTER_SHA
CURRENT_CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/watson-divine-contentment-closure-rebind-20260926")
HISTORICAL_EVIDENCE = WORK / "integration/ccel-thml-agent-handoff"
EVIDENCE = WORK / "integration/ccel-thml-closure-rebind-v2"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, digest: str | None = None) -> bytes:
    content = io_path(path).read_bytes()
    if digest is not None and _sha(content) != digest:
        raise PipelineError(f"Divine Contentment binding differs: {path}")
    return content


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    io_path(target).write_bytes(content)
    return target


def _write(path: Path, value: object) -> None:
    _copy(path.parent, Path(path.name), (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8"))


def _check_stage(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Divine Contentment stage must be fresh: {stage}")
    resolved = stage.resolve()
    for area in (root.resolve(), CURRENT_CANDIDATE.resolve()):
        if resolved == area or area in resolved.parents or resolved in area.parents:
            raise PipelineError("Divine Contentment stage overlaps a protected input")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Divine Contentment stage parent must be an ordinary directory")
    return stage


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _check_stage(root, stage)
    _read(root / HISTORICAL_MANIFEST, historical.MANIFEST_SHA)
    manifest = SourceManifest.load(root / CURRENT_MANIFEST, repository_root=root)
    if manifest.sha256 != CURRENT_MANIFEST_SHA:
        raise PipelineError("current Divine Contentment manifest differs")
    source_bytes = _read(resolve_repo_path(root, SOURCE.as_posix()), historical.SOURCE_SHA)
    work_bytes = _read(root / WORK / "work.json")
    acquisition_bytes = _read(root / ACQUISITION)
    installed_bytes = _read(root / EDITION / "acceptance.json", INSTALLED_ACCEPTANCE_SHA)
    installed = json.loads(installed_bytes)
    master = _read(root / EDITION / "master.tei.xml", INSTALLED_MASTER_SHA)
    if installed["promotion"]["master"]["sha256"] != INSTALLED_MASTER_SHA:
        raise PipelineError("installed Divine Contentment promotion differs")
    historical_package = CandidatePackage.load(root / HISTORICAL_EVIDENCE / "inputs/package")
    historical_validation = json.loads(_read(
        root / HISTORICAL_EVIDENCE / "inputs/validation.json", historical.VALIDATION_SHA
    ))
    if (
        historical_package.sha256 != historical.PACKAGE_SHA
        or historical_package.manifest.get("source_manifest", {}).get("sha256") != historical.MANIFEST_SHA
        or historical_validation.get("status") != "pass"
        or historical_validation.get("candidate_sha256") != historical.PACKAGE_SHA
        or historical_validation.get("source_manifest_sha256") != historical.MANIFEST_SHA
        or _read(root / HISTORICAL_EVIDENCE / "inputs/source-manifest.json", historical.MANIFEST_SHA)
        != _read(root / HISTORICAL_MANIFEST, historical.MANIFEST_SHA)
    ):
        raise PipelineError("historical Divine Contentment evidence differs")
    _read(root / HISTORICAL_EVIDENCE / "inputs/cvw/session-receipt.json", historical.SESSION_SHA)
    for relative, digest in (
        ("review.json", installed["review"]["report"]["sha256"]),
        ("closure.json", installed["technical"]["closure"]["sha256"]),
    ):
        _read(root / HISTORICAL_EVIDENCE / relative, digest)
    current = CandidatePackage.load(CURRENT_CANDIDATE / "package")
    current_validation = json.loads(_read(CURRENT_CANDIDATE / "validation.json", CURRENT_VALIDATION_SHA))
    report = validate(manifest, current, _oracle)
    if (
        current.sha256 != CURRENT_PACKAGE_SHA
        or report.status != "pass"
        or current_validation.get("status") != "pass"
        or current_validation.get("findings") != []
        or current_validation.get("candidate_sha256") != CURRENT_PACKAGE_SHA
        or current_validation.get("source_manifest_sha256") != CURRENT_MANIFEST_SHA
        or current_validation.get("report_sha256") != report.sha256
        or current.member_names != historical_package.member_names
    ):
        raise PipelineError("current Divine Contentment oracle evidence differs")
    for name in current.member_names:
        if name != "manifest.json" and current.member_bytes(name) != historical_package.member_bytes(name):
            raise PipelineError(f"Divine Contentment current member differs: {name}")
    derived = historical._bind_existing_header(current.member_bytes("content.tei.xml"), json.loads(acquisition_bytes), installed["representation_revision"])
    if derived != master:
        raise PipelineError("current Divine Contentment source no longer reproduces accepted master")

    stage.mkdir()
    evidence = stage / EVIDENCE
    current_root = evidence / "current-candidate"
    for path in io_glob(CURRENT_CANDIDATE / "package", "*"):
        if io_path(path).is_file():
            _copy(stage, EVIDENCE / "current-candidate/package" / path.name, _read(path))
    _copy(stage, EVIDENCE / "current-candidate/validation.json", _read(CURRENT_CANDIDATE / "validation.json", CURRENT_VALIDATION_SHA))
    for relative, content in (
        (WORK / "work.json", work_bytes), (WORK / "state.json", _read(root / WORK / "state.json")),
        (ACQUISITION, acquisition_bytes), (HISTORICAL_MANIFEST, _read(root / HISTORICAL_MANIFEST)),
        (CURRENT_MANIFEST, _read(root / CURRENT_MANIFEST)),
        (historical.TICKET, _read(root / historical.TICKET)),
        (historical.REPORT, _read(root / historical.REPORT)),
    ):
        _copy(stage, relative, content)
    _copy(stage, SOURCE, source_bytes)
    _copy(stage, EDITION / "master.tei.xml", master)
    for path in io_glob(root / HISTORICAL_EVIDENCE, "**/*"):
        if io_path(path).is_file():
            _copy(stage, path.relative_to(root), _read(path))
    old_acceptance = _copy(stage, EVIDENCE / "inputs/historical-acceptance.json", installed_bytes)
    candidate = _copy(stage, EVIDENCE / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"Divine Contentment TEI failed vendored XSD: {errors}")

    acquisition = json.loads(acquisition_bytes)
    scope = dict(installed["scope"])
    source = {
        "source_path": SOURCE.as_posix(), "source_sha256": historical.SOURCE_SHA,
        "source_bytes": len(source_bytes), "source_scope": acquisition["source_scope"],
    }
    common = dict(
        identity=historical.IDENTITY, source=source, candidate=make_file_binding(stage, candidate),
        scope=scope["declared"], accepted_scope=dict(kind=scope["kind"], declared=scope["declared"]),
        expected_members=scope["expected_members"], included_members=scope["included_members"],
        excluded_members=scope["excluded_members"], missing_members=[], unknown_members=[],
        absent_native_carriers=list(historical.MISSING),
    )
    account = evidence / "source-accounting.json"
    _write(account, common | {
        "source_sha256": historical.SOURCE_SHA,
        "source_bytes": len(source_bytes),
        "present_native_carriers": list(historical.PRESENT),
        "source_completeness_gap": {"absent_native_ids": list(historical.MISSING),
            "expected_chapters": ["VI", "VII"],
            "disposition": "unresolved; no replacement text inferred"},
        "historical_accounting": make_file_binding(stage, stage / HISTORICAL_EVIDENCE / "source-accounting.json"),
        "current_accountability_sha256": _sha(current.member_bytes("source-accountability.json")),
    })
    details = {
        "validation": {"current_validation": make_file_binding(stage, current_root / "validation.json"),
            "current_manifest_sha256": CURRENT_MANIFEST_SHA, "current_package_sha256": CURRENT_PACKAGE_SHA,
            "historical_validation": make_file_binding(stage, stage / HISTORICAL_EVIDENCE / "inputs/validation.json")},
        "accounting": {"source_sha256": historical.SOURCE_SHA,
            "selected_carrier_count": len(acquisition["source_selection"]["units"]),
            "absent_native_carriers": list(historical.MISSING)},
        "fidelity": {"historical_tei_sha256": historical.TEI_SHA,
            "current_tei_sha256": _sha(current.member_bytes("content.tei.xml")),
            "accepted_master_sha256": INSTALLED_MASTER_SHA,
            "all_five_substantive_members_identical": True},
        "reproducibility": {"current_package_sha256": CURRENT_PACKAGE_SHA,
            "staged_package_sha256": CandidatePackage.load(current_root / "package").sha256,
            "all_five_substantive_members_identical": True},
        "schema": {"vendored_xsd": "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "validation_errors": []},
        "closure": {"historical_manifest_sha256": historical.MANIFEST_SHA,
            "current_manifest_sha256": CURRENT_MANIFEST_SHA,
            "historical_package_sha256": historical.PACKAGE_SHA,
            "current_package_sha256": CURRENT_PACKAGE_SHA,
            "historical_cvw_session": make_file_binding(stage, stage / HISTORICAL_EVIDENCE / "inputs/cvw/session-receipt.json"),
            "historical_acceptance": make_file_binding(stage, old_acceptance)},
    }
    technical = dict(installed["technical"])
    technical["independent_corroboration"] = (
        "The current independent oracle validates a newly sealed package; its five substantive "
        "members match the historical reviewed package byte for byte. Native ix/x and expected "
        "chapters VI/VII remain absent from this witness. The accepted TEI master is unchanged."
    )
    command = "py -3 -m build.tools.prepare_watson_divine_contentment_rebind --stage <fresh-external-root>"
    for name in PROOFS:
        proof = evidence / f"{name}.json"
        _write(proof, common | {"status": "pass", "command": command, "exit_code": 0,
                               "details": details[name]})
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    review = dict(installed["review"])
    review.pop("report", None)
    review_report = evidence / "review.json"
    _write(review_report, common | review | {
        "historical_review": make_file_binding(stage, stage / HISTORICAL_EVIDENCE / "review.json"),
        "no_new_pixel_review": True,
        "applicability": "The retained source and all five substantive candidate members are byte-identical to the historical three-locus review; only the package manifest changed.",
    })
    record = build_acceptance_record(
        stage, identity=historical.IDENTITY, candidate_path=candidate,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | {"report_path": review_report},
        representation_revision=dict(installed["representation_revision"]),
        decision=json.loads(json.dumps(installed["decision"])),
    )
    record["promotion"] = json.loads(json.dumps(installed["promotion"]))
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage))


if __name__ == "__main__":
    main()
