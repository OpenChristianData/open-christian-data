"""Stage a versioned Watson Beatitudes closure rebind without installing it.

The historical candidate, manifest, acceptance, master, and CVW records remain
unchanged. Current code is replayed through the independent oracle, and all five
substantive candidate members must equal the historical package byte for byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools import prepare_watson_beatitudes_acceptance as historical
from build.tools.reconstruct_candidate import run as reconstruct_candidate
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_glob, io_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    _beatitudes_oracle,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


ROOT = historical.ROOT
WORK = historical.WORK
EDITION = historical.EDITION
ACQUISITION = historical.ACQUISITION
SOURCE = historical.SOURCE
HISTORICAL_MANIFEST = historical.MANIFEST
CURRENT_MANIFEST = HISTORICAL_MANIFEST.with_name(
    "watson-beatitudes.source-manifest-v2.json"
)
CURRENT_MANIFEST_SHA = "836a866dd1eeb9b304cb702c23361632e2ea17703935d72557ebaa2f69db3e6e"
CURRENT_PACKAGE_SHA = "e1d3002b2fe37f861cca5c5c4a81991b4301068abf1b2564a0a88a50e6a85136"
INSTALLED_ACCEPTANCE_SHA = "d62a61fa4abae97be5654f414f11e411d967bdf13131414c5336d32ef6918fa2"
INSTALLED_MASTER_SHA = "07b0070649c6a6b8e6ebbfd300834299dc2d64cc3684e2198fc42dadb82b0aef"
HISTORICAL_EVIDENCE = WORK / "integration/ccel-thml-agent-handoff"
EVIDENCE = WORK / "integration/ccel-thml-closure-rebind-v2"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, digest: str | None = None) -> bytes:
    content = io_path(path).read_bytes()
    if digest is not None and _sha(content) != digest:
        raise PipelineError(f"Beatitudes binding differs: {path}")
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


def _historical_inputs(root: Path) -> tuple[dict, bytes, CandidatePackage]:
    historical_manifest = _read(root / HISTORICAL_MANIFEST, historical.MANIFEST_SHA)
    current_manifest = SourceManifest.load(root / CURRENT_MANIFEST, repository_root=root)
    if current_manifest.sha256 != CURRENT_MANIFEST_SHA:
        raise PipelineError("current Beatitudes source manifest differs")
    _read(resolve_repo_path(root, SOURCE.as_posix()), historical.SOURCE_SHA)
    _read(root / WORK / "work.json", historical.WORK_SHA)
    _read(root / ACQUISITION, historical.ACQUISITION_SHA)
    installed = json.loads(_read(root / EDITION / "acceptance.json", INSTALLED_ACCEPTANCE_SHA))
    master = _read(root / EDITION / "master.tei.xml", INSTALLED_MASTER_SHA)
    if installed["promotion"]["master"]["sha256"] != _sha(master):
        raise PipelineError("installed Beatitudes acceptance and master disagree")
    old = CandidatePackage.load(root / HISTORICAL_EVIDENCE / "inputs/package")
    old_validation = json.loads(_read(
        root / HISTORICAL_EVIDENCE / "inputs/validation.json",
        historical.VALIDATION_SHA,
    ))
    if (
        old.sha256 != historical.PACKAGE_SHA
        or old.manifest.get("source_manifest", {}).get("sha256") != historical.MANIFEST_SHA
        or _sha(old.member_bytes("content.tei.xml")) != historical.TEI_SHA
        or old_validation.get("status") != "pass"
        or old_validation.get("findings") != []
        or old_validation.get("candidate_sha256") != historical.PACKAGE_SHA
        or old_validation.get("source_manifest_sha256") != historical.MANIFEST_SHA
        or old_validation.get("attestation", {}).get("source_sha256") != historical.SOURCE_SHA
        or historical_manifest != _read(
            root / HISTORICAL_EVIDENCE / "inputs/source-manifest.json",
            historical.MANIFEST_SHA,
        )
    ):
        raise PipelineError("historical Beatitudes package or independent validation differs")
    for name, digest in (
        ("review.json", installed["review"]["report"]["sha256"]),
        ("closure.json", installed["technical"]["closure"]["sha256"]),
    ):
        _read(root / HISTORICAL_EVIDENCE / name, digest)
    return installed, master, old


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = historical._check_stage(root, stage)
    installed, master, old = _historical_inputs(root)
    stage.mkdir()
    evidence = stage / EVIDENCE
    io_path(evidence).mkdir(parents=True)
    current_root = evidence / "current-candidate"
    summary = reconstruct_candidate(
        manifest=CURRENT_MANIFEST.as_posix(),
        destination=str(current_root),
        repository_root=str(root),
    )
    current = CandidatePackage.load(current_root / "package")
    current_manifest = SourceManifest.load(root / CURRENT_MANIFEST, repository_root=root)
    validate(current_manifest, current, _beatitudes_oracle())
    current_validation_path = current_root / "validation.json"
    current_validation = json.loads(_read(current_validation_path))
    if (
        summary.get("status") != "pass"
        or current.sha256 != CURRENT_PACKAGE_SHA
        or current_validation.get("status") != "pass"
        or current_validation.get("findings") != []
        or current_validation.get("candidate_sha256") != CURRENT_PACKAGE_SHA
        or current_validation.get("source_manifest_sha256") != CURRENT_MANIFEST_SHA
        or current_validation.get("attestation", {}).get("source_sha256") != historical.SOURCE_SHA
    ):
        raise PipelineError("current Beatitudes independent validation differs")
    for name in current.member_names:
        if name != "manifest.json" and current.member_bytes(name) != old.member_bytes(name):
            raise PipelineError(f"current Beatitudes member differs from historical: {name}")

    for relative in (
        WORK / "work.json", WORK / "state.json", ACQUISITION,
        HISTORICAL_MANIFEST, CURRENT_MANIFEST,
        historical.TICKET, historical.REPORT,
    ):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, SOURCE, _read(resolve_repo_path(root, SOURCE.as_posix()), historical.SOURCE_SHA))
    _copy(stage, EDITION / "master.tei.xml", master)
    for path in io_glob(root / HISTORICAL_EVIDENCE, "**/*"):
        if io_path(path).is_file():
            _copy(stage, path.relative_to(root), _read(path))
    old_acceptance = _copy(
        stage, EVIDENCE / "inputs/historical-acceptance.json",
        _read(root / EDITION / "acceptance.json", INSTALLED_ACCEPTANCE_SHA),
    )

    revision = dict(installed["representation_revision"])
    original = current.member_bytes("content.tei.xml")
    derived = historical._derived(original, revision)
    if derived != master or _sha(derived) != INSTALLED_MASTER_SHA:
        raise PipelineError("rebound Beatitudes candidate changes the accepted master")
    candidate = _copy(stage, EVIDENCE / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"rebound Beatitudes TEI failed vendored XSD: {errors}")

    acquisition = json.loads(_read(root / ACQUISITION, historical.ACQUISITION_SHA))
    source = {
        "source_path": SOURCE.as_posix(),
        "source_sha256": historical.SOURCE_SHA,
        "source_bytes": len(_read(resolve_repo_path(root, SOURCE.as_posix()))),
        "source_scope": acquisition["source_scope"],
    }
    scope = dict(installed["scope"])
    common = dict(
        identity=historical.IDENTITY,
        source=source,
        candidate=make_file_binding(stage, candidate),
        scope=scope["declared"],
        accepted_scope=dict(kind=scope["kind"], declared=scope["declared"]),
        expected_members=scope["expected_members"],
        included_members=scope["included_members"],
        excluded_members=scope["excluded_members"],
        missing_members=[],
        unknown_members=[],
    )
    account = evidence / "source-accounting.json"
    _write(account, common | {
        "source_sha256": historical.SOURCE_SHA,
        "source_bytes": source["source_bytes"],
        "historical_accounting": make_file_binding(
            stage, stage / HISTORICAL_EVIDENCE / "source-accounting.json"
        ),
        "current_accountability_sha256": _sha(current.member_bytes("source-accountability.json")),
    })
    details = {
        "validation": {
            "current_validation": make_file_binding(stage, current_validation_path),
            "current_manifest_sha256": CURRENT_MANIFEST_SHA,
            "current_package_sha256": CURRENT_PACKAGE_SHA,
            "historical_validation": make_file_binding(
                stage, stage / HISTORICAL_EVIDENCE / "inputs/validation.json"
            ),
        },
        "accounting": {
            "source_sha256": historical.SOURCE_SHA,
            "selected_carrier_count": len(acquisition["source_selection"]["units"]),
        },
        "fidelity": {
            "historical_tei_sha256": historical.TEI_SHA,
            "current_tei_sha256": _sha(original),
            "accepted_master_sha256": INSTALLED_MASTER_SHA,
            "all_five_substantive_members_identical": True,
        },
        "reproducibility": {
            "preview_package_sha256": CURRENT_PACKAGE_SHA,
            "staged_package_sha256": current.sha256,
            "all_five_substantive_members_identical": True,
        },
        "schema": {
            "vendored_xsd": "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
            "validation_errors": [],
        },
        "closure": {
            "historical_manifest_sha256": historical.MANIFEST_SHA,
            "current_manifest_sha256": CURRENT_MANIFEST_SHA,
            "historical_package_sha256": historical.PACKAGE_SHA,
            "current_package_sha256": CURRENT_PACKAGE_SHA,
            "historical_acceptance": make_file_binding(stage, old_acceptance),
        },
    }
    technical = dict(installed["technical"])
    technical["independent_corroboration"] = (
        "The current independent oracle validates a newly sealed package; its five "
        "substantive members match the historical reviewed package byte for byte. "
        "The accepted TEI master is unchanged."
    )
    command = "py -3 -m build.tools.prepare_watson_beatitudes_rebind --stage <fresh-external-root>"
    for name in PROOFS:
        proof = evidence / f"{name}.json"
        _write(proof, common | {
            "status": "pass", "command": command, "exit_code": 0, "details": details[name],
        })
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)

    review = dict(installed["review"])
    review.pop("report", None)
    review_report = evidence / "review.json"
    _write(review_report, common | review | {
        "historical_review": make_file_binding(
            stage, stage / HISTORICAL_EVIDENCE / "review.json"
        ),
        "no_new_pixel_review": True,
        "applicability": (
            "The source and all five substantive candidate members are byte-identical "
            "to the historical four-locus review; only the package manifest changed."
        ),
    })
    decision = json.loads(json.dumps(installed["decision"]))
    record = build_acceptance_record(
        stage,
        identity=historical.IDENTITY,
        candidate_path=candidate,
        source_accounting_path=account,
        scope=scope,
        technical=technical,
        review=review | {"report_path": review_report},
        representation_revision=revision,
        decision=decision,
    )
    # This refreshes technical evidence for an already promoted, unchanged master.
    # Preserve its recorded decision and promotion history exactly.
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
