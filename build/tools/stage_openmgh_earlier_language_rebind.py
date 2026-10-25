"""Stage a source-bound Latin metadata rebind for three accepted openMGH works.

The accepted TEI remains byte-identical. This command prepares a separate,
hash-bound generation for review; it never installs into the canonical library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from lxml import etree

from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path, _put_json
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (
    build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _write_json_durable
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.categories.poetry import project_accepted_poetry, verify_accepted_poetry


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "ocd-openmgh-three-language-rebind-stage-v1"
SOURCES = {
    "actus-sancti-eremberti": (
        Path("raw/openmgh/bsb00000752/tei/bsb00000752.xml"),
        "620b80ade431a814ebf41296cdf88476d9a39741cdba1925c0cd75fb9772c98a",
    ),
    "anulus-et-baculus-verses": (
        Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml"),
        "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac",
    ),
    "bernald-avoiding-communion-with-excommunicates": (
        Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml"),
        "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac",
    ),
}
IDS = (
    "actus-sancti-eremberti",
    "anulus-et-baculus-verses",
    "bernald-avoiding-communion-with-excommunicates",
)
BODY_CLAUSES = {
    "actus-sancti-eremberti": "Erembertus igitur sanctus atque religiosus ortus erat territorio",
    "anulus-et-baculus-verses": "Anulus et baculus duo sunt insignia",
    "bernald-avoiding-communion-with-excommunicates": "Noli catholicam semper mentem aliqua scismaticorum communione polluere.",
}
CATEGORIES = {
    "actus-sancti-eremberti": "prose",
    "anulus-et-baculus-verses": "poetry",
    "bernald-avoiding-communion-with-excommunicates": "prose",
}
STAGE_RECEIPTS = {
    "actus-sancti-eremberti": "actus-eremberti-openmgh-electronic-acceptance-stage-20260926.json",
    "anulus-et-baculus-verses": "anulus-openmgh-electronic-acceptance-stage-20260926.json",
    "bernald-avoiding-communion-with-excommunicates": "bernald-openmgh-electronic-acceptance-stage-20260926.json",
}
REQUIRED_PROOFS = (
    "validation", "accounting", "fidelity", "reproducibility", "schema", "closure"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _closure_sha(stage: Path, inputs: list[str]) -> str:
    entries = [
        {"path": relative, "sha256": _sha(stage / relative)}
        for relative in inputs
    ]
    content = (
        json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return hashlib.sha256(content).hexdigest()


def _copy(root: Path, stage: Path, relative: Path) -> None:
    source = _io_path(root / relative)
    target = _io_path(stage / relative)
    if not source.is_file():
        raise PipelineError(f"required staged dependency missing: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _paths(work_id: str) -> tuple[Path, Path, Path, Path]:
    work = Path("library/works") / work_id
    edition = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic"
    manifest = Path("sources/openmgh-exclusive") / work_id / "source-manifest.json"
    boundary = manifest.parent / "boundary-review.json"
    return work, edition, manifest, boundary


def _source_check(source_tree: etree._ElementTree, work_id: str, boundary: dict) -> dict:
    source_path, source_sha = SOURCES[work_id]
    xml_ns = "http://www.w3.org/XML/1998/namespace"
    tei_ns = "http://www.tei-c.org/ns/1.0"
    located = []
    for key in ("start_xml_id", "end_xml_id"):
        matches = source_tree.xpath(
            "//*[@xml:id=$value]", namespaces={"xml": xml_ns}, value=boundary[key]
        )
        if len(matches) != 1:
            raise PipelineError(f"{work_id}: {key} is not unique in retained XML")
        located.append(matches[0])
    works = [
        node for node in located[0].iterancestors()
        if node.tag == f"{{{tei_ns}}}div" and node.get("type") == "work"
    ]
    if len(works) != 1 or works[0] not in located[1].iterancestors():
        raise PipelineError(f"{work_id}: language evidence crosses a work boundary")
    text = " ".join(" ".join(works[0].itertext()).split())
    clause = BODY_CLAUSES[work_id]
    if clause not in text:
        raise PipelineError(f"{work_id}: selected Latin body clause differs")
    if boundary.get("work_id") != work_id or boundary.get("source_sha256") != source_sha:
        raise PipelineError(f"{work_id}: inspected source boundary differs")
    return {
        "language": "la",
        "basis": f"The selected retained work body is Latin {CATEGORIES[work_id]}; the cited clause occurs in that body, and both XML locators remain in one inspected work division.",
        "source_path": source_path.as_posix(),
        "source_sha256": source_sha,
        "start_xml_id": boundary["start_xml_id"],
        "end_xml_id": boundary["end_xml_id"],
        "body_clause": clause,
    }


def _prepare_one(root: Path, stage: Path, work_id: str, source_tree: etree._ElementTree) -> dict:
    work, edition, manifest_rel, boundary_rel = _paths(work_id)
    acceptance_rel = edition / "acceptance.json"
    master_rel = edition / "master.tei.xml"
    before = _files(root / work)
    old_acceptance = validate_acceptance(root / acceptance_rel, root=root)
    old_manifest = _read(root / manifest_rel)
    old_manifest_sha = _sha(root / manifest_rel)
    old_work = _read(root / work / "work.json")
    original_receipt_rel = Path("plans/2026-09-22-source-preflight") / STAGE_RECEIPTS[work_id]
    original_receipt = _read(root / original_receipt_rel)
    if old_acceptance["identity"]["work_id"] != work_id:
        raise PipelineError(f"{work_id}: accepted identity differs")
    if old_acceptance["promotion"]["status"] != "promoted":
        raise PipelineError(f"{work_id}: acceptance is not promoted")
    if old_acceptance["promotion"]["master"]["sha256"] != _sha(root / master_rel):
        raise PipelineError(f"{work_id}: promoted master hash differs")
    # The original acceptance stage added the category to work.json but
    # retained the pre-acceptance work hash in the source manifest. Prove that
    # this is the sole preexisting drift before renewing the binding.
    old_work_authorities = [
        item for item in old_manifest["authorities"] if item["name"] == "work-sidecar"
    ]
    if len(old_work_authorities) != 1:
        raise PipelineError(f"{work_id}: original work authority is not unique")
    preacceptance_work = json.loads(json.dumps(old_work))
    preacceptance_editions = [
        item for form in preacceptance_work["textual_forms"]
        for item in form["editions"]
        if item["edition_id"] == old_acceptance["identity"]["edition_id"]
    ]
    if len(preacceptance_editions) != 1 or preacceptance_editions[0].pop("category", None) != CATEGORIES[work_id]:
        raise PipelineError(f"{work_id}: accepted category drift is not the expected one")
    prior_bytes = (
        json.dumps(preacceptance_work, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if (len(prior_bytes) != old_work_authorities[0]["bytes"]
            or hashlib.sha256(prior_bytes).hexdigest() != old_work_authorities[0]["sha256"]):
        raise PipelineError(f"{work_id}: original manifest drift is not solely the accepted category")
    acquisition_rel = edition / "acquisitions" / f"{work_id}-openmgh-acquired.json"
    acquisition_key = acquisition_rel.relative_to(work).as_posix()
    profile_rel = manifest_rel.parent / "reconstruction-profile.json"
    profile_before = _read(root / profile_rel)
    if (original_receipt.get("work_id") != work_id
            or original_receipt["before"].get("work.json") != old_work_authorities[0]["sha256"]
            or original_receipt["before"].get(acquisition_key) != profile_before["acquisition_sha256"]
            or original_receipt["after"].get(acquisition_key) != _sha(root / acquisition_rel)
            or original_receipt["after"].get("work.json") != _sha(root / work / "work.json")):
        raise PipelineError(f"{work_id}: original receipt does not explain metadata drift")
    boundary = _read(root / boundary_rel)
    evidence = _source_check(source_tree, work_id, boundary)
    _io_path(stage / work).parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_io_path(root / work), _io_path(stage / work))
    _copy(root, stage, manifest_rel)
    for authority in old_manifest["authorities"]:
        relative = Path(str(authority["path"]))
        if relative != work / "work.json":
            _copy(root, stage, relative)
    acquisition_record = _read(root / acquisition_rel)
    for member in acquisition_record["retained_files"]:
        relative = Path(str(member["path"]))
        if relative != SOURCES[work_id][0]:
            _copy(root, stage, relative)
    _copy(root, stage, SOURCES[work_id][0].parent.parent / "acquisition-receipt.json")
    for item in (old_manifest["converter"], old_manifest["validator"]):
        _copy(root, stage, Path(str(item["implementation_path"])))
    _copy(root, stage, Path(str(old_manifest["package_schema"]["path"])))
    _copy(root, stage, Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"))
    _copy(root, stage, Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd"))
    policy = _read(root / "sources/openmgh-exclusive/validation-policy.json")
    for relative in policy["closure_inputs"]:
        _copy(root, stage, Path(relative))
    _copy(root, stage, boundary_rel)

    new_work = _read(stage / work / "work.json")
    editions = [
        edition_record for form in new_work["textual_forms"]
        for edition_record in form["editions"]
        if edition_record["edition_id"] == old_acceptance["identity"]["edition_id"]
    ]
    if len(editions) != 1 or "language" in editions[0]:
        raise PipelineError(f"{work_id}: edition language precondition differs")
    editions[0]["language"] = "la"
    validate_identity_update(old_work, new_work)
    _put_json(stage, work / "work.json", new_work)
    load_work(_io_path(stage / work / "work.json"))

    manifest_record = _read(stage / manifest_rel)
    prior_closure_sha = manifest_record["validator"]["import_closure_sha256"]
    manifest_record["validator"]["import_closure_sha256"] = _closure_sha(
        stage, policy["closure_inputs"]
    )
    profile = _read(stage / profile_rel)
    profile["acquisition_sha256"] = _sha(stage / acquisition_rel)
    _put_json(stage, profile_rel, profile)
    profile_authorities = [
        item for item in manifest_record["authorities"]
        if item["name"] == "reconstruction-profile"
    ]
    if len(profile_authorities) != 1 or profile_authorities[0]["sha256"] != _sha(root / profile_rel):
        raise PipelineError(f"{work_id}: reconstruction profile binding differs")
    profile_authorities[0]["bytes"] = _io_path(stage / profile_rel).stat().st_size
    profile_authorities[0]["sha256"] = _sha(stage / profile_rel)
    bound = [item for item in manifest_record["authorities"] if item["name"] == "work-sidecar"]
    if len(bound) != 1 or bound[0]["path"] != (work / "work.json").as_posix():
        raise PipelineError(f"{work_id}: source manifest work authority differs")
    bound[0]["bytes"] = _io_path(stage / work / "work.json").stat().st_size
    bound[0]["sha256"] = _sha(stage / work / "work.json")
    _put_json(stage, manifest_rel, manifest_record)
    manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)

    candidate_root = stage.parent / f"{stage.name}-{work_id}-current-candidate"
    if _io_path(candidate_root).exists():
        raise PipelineError(f"candidate destination must be fresh: {candidate_root}")
    process = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest",
         manifest_rel.as_posix(), "--destination", str(candidate_root),
         "--repository-root", str(stage)],
        cwd=root, check=False, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if process.returncode != 0:
        raise PipelineError(
            f"{work_id}: current candidate regeneration failed: {process.stderr[-1800:]}"
        )
    package = CandidatePackage.load(candidate_root / "package")
    report = _read(candidate_root / "validation.json")
    if (report.get("status") != "pass" or report.get("findings") != []
            or report.get("candidate_sha256") != package.sha256
            or report.get("source_manifest_sha256") != manifest.sha256):
        raise PipelineError(f"{work_id}: renewed independent oracle failed")
    original_package = CandidatePackage.load(
        root / Path(old_acceptance["technical"]["candidate"]["path"]).parent / "inputs/package"
    )
    if package.member_names != original_package.member_names or any(
        package.member_bytes(name) != original_package.member_bytes(name)
        for name in package.member_names if name != "manifest.json"
    ):
        raise PipelineError(f"{work_id}: reconstructed TEI or source accounting changed")
    integration = work / "integration/openmgh-earlier-language-rebind-v1"
    _io_path(stage / integration).mkdir(parents=True, exist_ok=True)
    shutil.copytree(_io_path(candidate_root / "package"), _io_path(stage / integration / "package"))
    _io_path(stage / integration / "oracle-validation.json").write_bytes(
        _io_path(candidate_root / "validation.json").read_bytes()
    )
    _put_json(stage, integration / "language-evidence.json", {
        "contract": "ocd-openmgh-source-language-evidence-v1", "work_id": work_id,
        "boundary_path": boundary_rel.as_posix(), "boundary_sha256": _sha(root / boundary_rel),
        **evidence,
    })
    historical_manifest = integration / "historical-source-manifest.json"
    _io_path(stage / historical_manifest).write_bytes(_io_path(root / manifest_rel).read_bytes())
    _io_path(stage / integration / "historical-reconstruction-profile.json").write_bytes(
        _io_path(root / profile_rel).read_bytes()
    )
    old_accounting_rel = Path(old_acceptance["source"]["accounting"]["path"])
    accounting = _read(stage / old_accounting_rel)
    accounting.update(
        source_manifest_sha256=manifest.sha256,
        candidate_package_sha256=package.sha256,
        oracle_report_sha256=report["report_sha256"],
    )
    _put_json(stage, integration / "source-accounting.json", accounting)
    technical = {
        key: old_acceptance["technical"][key]
        for key in ("producer", "checker", "shared_assumptions", "independent_corroboration")
    }
    command = "py -3 -m build.tools.stage_openmgh_earlier_language_rebind"
    for name in REQUIRED_PROOFS:
        historical = old_acceptance["technical"][name]
        proof = _read(stage / historical["path"])
        proof.update(
            status="pass", command=command, exit_code=0,
            language_evidence=make_file_binding(stage, stage / integration / "language-evidence.json"),
            current_source_manifest=make_file_binding(stage, stage / manifest_rel),
            current_package_manifest=make_file_binding(stage, stage / integration / "package/manifest.json"),
            current_oracle_validation=make_file_binding(stage, stage / integration / "oracle-validation.json"),
            historical_proof=historical,
            accepted_master_sha256=_sha(stage / master_rel),
            conclusion="Source-bound edition language metadata is Latin; reconstructed package text and accepted TEI master are unchanged.",
        )
        _put_json(stage, integration / f"{name}.json", proof)
        technical[name] = {
            "path": (integration / f"{name}.json").as_posix(),
            "status": "pass", "command": command, "exit_code": 0,
        }
    review = dict(old_acceptance["review"])
    review["report_path"] = review.pop("report")["path"]
    new_acceptance = build_acceptance_record(
        stage, identity=old_acceptance["identity"],
        candidate_path=stage / old_acceptance["technical"]["candidate"]["path"],
        source_accounting_path=stage / integration / "source-accounting.json",
        scope=old_acceptance["scope"], technical=technical, review=review,
        representation_revision=old_acceptance["representation_revision"],
        decision=old_acceptance["decision"],
        acceptance_id=old_acceptance["acceptance_id"], promotion_status="promoted",
    )
    new_acceptance["promotion"]["promoted_at"] = old_acceptance["promotion"]["promoted_at"]
    write_acceptance(_io_path(stage / acceptance_rel), new_acceptance)
    validate_acceptance(stage / acceptance_rel, root=stage)
    validate_state(stage / work / "state.json", root=stage)
    project, verify = (
        (project_accepted_poetry, verify_accepted_poetry)
        if CATEGORIES[work_id] == "poetry"
        else (project_accepted_prose, verify_accepted_prose)
    )
    projection = project(stage, acceptance_path=stage / acceptance_rel)
    if not projection or not projection.get("rows"):
        raise PipelineError(f"{work_id}: accepted {CATEGORIES[work_id]} projection produced no rows")
    errors = verify(
        stage, acceptance_path=stage / acceptance_rel,
        rows=projection["rows"], receipt=projection["receipt"],
    )
    if errors:
        raise PipelineError(f"{work_id}: independent {CATEGORIES[work_id]} projection check failed: {errors[:3]}")
    projection_status = "pass"
    if _sha(stage / master_rel) != _sha(root / master_rel):
        raise PipelineError(f"{work_id}: accepted master changed")
    after = _files(stage / work)
    return {
        "work_id": work_id, "language": "la", "before": before, "after": after,
        "changed_paths": sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path)),
        "source_manifest_path": manifest_rel.as_posix(),
        "source_manifest_before_sha256": old_manifest_sha,
        "source_manifest_after_sha256": manifest.sha256,
        "acceptance_before_sha256": _sha(root / acceptance_rel),
        "acceptance_after_sha256": _sha(stage / acceptance_rel),
        "master_sha256": _sha(root / master_rel),
        "oracle_report_sha256": report["report_sha256"],
        "oracle_closure_before_sha256": prior_closure_sha,
        "oracle_closure_after_sha256": manifest_record["validator"]["import_closure_sha256"],
        "projection_status": projection_status,
        "projection_rows": len(projection["rows"]),
    }


def prepare(root: Path, stage: Path, receipt: Path) -> dict:
    root = root.resolve(strict=True)
    stage, receipt = stage.absolute(), receipt.absolute()
    if _io_path(stage).exists() or _io_path(receipt).exists():
        raise PipelineError("stage and receipt must be fresh")
    if root == stage or root in stage.parents:
        raise PipelineError("stage must be outside the canonical repository")
    if not _io_path(stage.parent).is_dir():
        raise PipelineError("stage parent is missing")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    trees = {}
    for source_path, source_sha in set(SOURCES.values()):
        if _sha(root / source_path) != source_sha:
            raise PipelineError(f"retained extracted XML changed: {source_path}")
        trees[source_path] = etree.parse(str(_io_path(root / source_path)), parser)
    _io_path(stage).mkdir()
    results = [_prepare_one(root, stage, work_id, trees[SOURCES[work_id][0]]) for work_id in IDS]
    external = {}
    changed_external = {
        (Path("sources/openmgh-exclusive") / work_id / name).as_posix()
        for work_id in IDS for name in ("source-manifest.json", "reconstruction-profile.json")
    }
    for relative, proposed_sha in _files(stage).items():
        if relative.startswith("library/works/"):
            continue
        original_sha = _sha(root / relative)
        if original_sha != proposed_sha and relative not in changed_external:
            raise PipelineError(f"unexpected external stage change: {relative}")
        external[relative] = {
            "before_sha256": original_sha,
            "proposed_sha256": proposed_sha,
        }
    if {path for path, hashes in external.items() if hashes["before_sha256"] != hashes["proposed_sha256"]} != changed_external:
        raise PipelineError("all three source manifests and profiles must be rebound")
    receipt_record = {
        "contract": CONTRACT, "status": "staged-only",
        "canonical_root": root.as_posix(), "stage_root": stage.as_posix(),
        "sources": [
            {"path": source_path.as_posix(), "sha256": source_sha}
            for source_path, source_sha in sorted(set(SOURCES.values()))
        ],
        "works": results, "external_dependencies": external,
    }
    _io_path(receipt).write_text(
        json.dumps(receipt_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return receipt_record


def preflight(receipt: Path, work_id: str) -> tuple[dict, dict, Path, Path]:
    record = _read(receipt.resolve(strict=True))
    if record.get("contract") != CONTRACT or record.get("status") != "staged-only":
        raise PipelineError("language rebind receipt contract differs")
    if work_id not in IDS or len(record.get("works", [])) != len(IDS):
        raise PipelineError("three-work language rebind receipt is incomplete")
    rows = [row for row in record["works"] if row.get("work_id") == work_id]
    if len(rows) != 1 or {row["work_id"] for row in record["works"]} != set(IDS):
        raise PipelineError("language rebind work inventory differs")
    row = rows[0]
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    source_path, source_sha = SOURCES[work_id]
    if root == stage or root in stage.parents or _sha(root / source_path) != source_sha:
        raise PipelineError("canonical root, stage, or extracted source differs")
    work, edition, manifest_rel, _boundary = _paths(work_id)
    profile_rel = manifest_rel.parent / "reconstruction-profile.json"
    expected_external_changes = {manifest_rel.as_posix(), profile_rel.as_posix()}
    for relative, hashes in record["external_dependencies"].items():
        if relative.startswith("sources/openmgh-exclusive/") and not relative.startswith(
            f"sources/openmgh-exclusive/{work_id}/"
        ) and relative != "sources/openmgh-exclusive/validation-policy.json":
            continue
        if _sha(stage / relative) != hashes["proposed_sha256"]:
            raise PipelineError(f"staged external dependency changed: {relative}")
        if _sha(root / relative) != hashes["before_sha256"]:
            raise PipelineError(f"canonical external dependency changed: {relative}")
        if ((hashes["before_sha256"] != hashes["proposed_sha256"])
                != (relative in expected_external_changes)):
            raise PipelineError(f"unexpected external change: {relative}")
    if _files(root / work) != row["before"] or _files(stage / work) != row["after"]:
        raise PipelineError(f"{work_id}: canonical or staged work generation changed")
    if row["changed_paths"] != sorted(
        path for path in set(row["before"]) | set(row["after"])
        if row["before"].get(path) != row["after"].get(path)
    ):
        raise PipelineError(f"{work_id}: work changed-file inventory differs")
    acceptance_rel = edition / "acceptance.json"
    master_rel = edition / "master.tei.xml"
    if (row["before"][master_rel.relative_to(work).as_posix()] != row["master_sha256"]
            or row["after"][master_rel.relative_to(work).as_posix()] != row["master_sha256"]
            or row["before"]["state.json"] != row["after"]["state.json"]):
        raise PipelineError(f"{work_id}: master or state changed in metadata-only stage")
    if row["acceptance_before_sha256"] != _sha(root / acceptance_rel):
        raise PipelineError(f"{work_id}: installed acceptance changed")
    if row["acceptance_after_sha256"] != _sha(stage / acceptance_rel):
        raise PipelineError(f"{work_id}: staged acceptance changed")
    manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    if (manifest.sha256 != row["source_manifest_after_sha256"]
            or _sha(root / manifest_rel) != row["source_manifest_before_sha256"]):
        raise PipelineError(f"{work_id}: source manifest binding differs")
    current = work / "integration/openmgh-earlier-language-rebind-v1"
    package = CandidatePackage.load(stage / current / "package")
    oracle = _read(stage / current / "oracle-validation.json")
    if (oracle.get("status") != "pass" or oracle.get("findings") != []
            or oracle.get("candidate_sha256") != package.sha256
            or oracle.get("source_manifest_sha256") != manifest.sha256
            or oracle.get("report_sha256") != row["oracle_report_sha256"]):
        raise PipelineError(f"{work_id}: current source oracle binding differs")
    accepted = validate_acceptance(stage / acceptance_rel, root=stage)
    validate_state(stage / work / "state.json", root=stage)
    edition_record = [
        item for form in _read(stage / work / "work.json")["textual_forms"]
        for item in form["editions"]
        if item["edition_id"] == accepted["identity"]["edition_id"]
    ]
    if len(edition_record) != 1 or edition_record[0].get("language") != "la":
        raise PipelineError(f"{work_id}: staged edition language differs")
    return record, row, root, stage


def install(receipt: Path, work_id: str) -> dict:
    record, row, root, stage = preflight(receipt, work_id)
    work, edition, manifest_rel, _boundary = _paths(work_id)
    profile_rel = manifest_rel.parent / "reconstruction-profile.json"
    acceptance_rel = edition / "acceptance.json"
    target = root / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight(receipt, work_id)
        operation = root / "library/.sidecar-operations" / f"openmgh-earlier-language-{uuid.uuid4().hex[:16]}"
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming = operation / "incoming"
        previous = operation / "previous"
        failed_new = operation / "failed-new"
        backup_profile = operation / "profile-before.json"
        backup_manifest = operation / "manifest-before.json"
        next_profile = operation / "profile-after.json"
        next_manifest = operation / "manifest-after.json"
        journal = operation / "operation.json"
        state = {
            "contract": CONTRACT, "work_id": work_id,
            "receipt": receipt.resolve(strict=True).as_posix(),
            "before": row["before"], "after": row["after"],
            "external_before": {
                path.as_posix(): record["external_dependencies"][path.as_posix()]["before_sha256"]
                for path in (profile_rel, manifest_rel)
            },
            "external_after": {
                path.as_posix(): record["external_dependencies"][path.as_posix()]["proposed_sha256"]
                for path in (profile_rel, manifest_rel)
            },
            "phase": "created",
        }
        _write_json_durable(journal, state)
        moved = live = profile_live = manifest_live = False
        try:
            shutil.copytree(_io_path(stage / work), _io_path(incoming))
            for relative, before_path, after_path in (
                (profile_rel, backup_profile, next_profile),
                (manifest_rel, backup_manifest, next_manifest),
            ):
                shutil.copy2(_io_path(root / relative), _io_path(before_path))
                shutil.copy2(_io_path(stage / relative), _io_path(after_path))
                if (_sha(before_path) != state["external_before"][relative.as_posix()]
                        or _sha(after_path) != state["external_after"][relative.as_posix()]):
                    raise PipelineError(f"{work_id}: copied external sidecar differs")
            if _files(incoming) != row["after"] or _files(target) != row["before"]:
                raise PipelineError(f"{work_id}: copied or canonical work generation differs")
            state["phase"] = "prepared"
            _write_json_durable(journal, state)
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            state["phase"] = "previous-moved"
            _write_json_durable(journal, state)
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            state["phase"] = "new-work-live"
            _write_json_durable(journal, state)
            os.replace(_io_path(next_profile), _io_path(root / profile_rel))
            profile_live = True
            state["phase"] = "new-profile-live"
            _write_json_durable(journal, state)
            os.replace(_io_path(next_manifest), _io_path(root / manifest_rel))
            manifest_live = True
            state["phase"] = "new-manifest-live"
            _write_json_durable(journal, state)
            if (_files(target) != row["after"]
                    or _sha(root / profile_rel) != state["external_after"][profile_rel.as_posix()]
                    or _sha(root / manifest_rel) != state["external_after"][manifest_rel.as_posix()]):
                raise PipelineError(f"{work_id}: installed generation differs")
            SourceManifest.load(root / manifest_rel, repository_root=root)
            validate_acceptance(root / acceptance_rel, root=root)
            validate_state(root / work / "state.json", root=root)
            state["phase"] = "complete"
            _write_json_durable(journal, state)
            return {"status": "installed-and-validated", "work_id": work_id,
                    "operation": operation.as_posix(), "before_count": len(row["before"]),
                    "after_count": len(row["after"])}
        except BaseException:
            try:
                if manifest_live:
                    if _sha(root / manifest_rel) != state["external_after"][manifest_rel.as_posix()]:
                        raise PipelineError("manifest changed before rollback")
                    shutil.copy2(_io_path(backup_manifest), _io_path(root / manifest_rel))
                if profile_live:
                    if _sha(root / profile_rel) != state["external_after"][profile_rel.as_posix()]:
                        raise PipelineError("profile changed before rollback")
                    shutil.copy2(_io_path(backup_profile), _io_path(root / profile_rel))
                if live:
                    if _files(target) != row["after"]:
                        raise PipelineError("live work changed before rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row["before"]:
                        raise PipelineError("previous work changed before rollback")
                    os.replace(_io_path(previous), _io_path(target))
                state["phase"] = "rolled-back" if moved else "failed-before-swap"
                _write_json_durable(journal, state)
            except BaseException as error:
                state.update(phase="recovery-required", rollback_error=str(error))
                _write_json_durable(journal, state)
                raise PipelineError(f"rollback requires recovery: {operation}") from error
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--preflight", choices=IDS)
    parser.add_argument("--apply", choices=IDS)
    args = parser.parse_args()
    if args.preflight and args.apply:
        parser.error("--preflight and --apply are mutually exclusive")
    if args.apply:
        result = install(args.receipt, args.apply)
    elif args.preflight:
        _record, row, _root, _stage = preflight(args.receipt, args.preflight)
        result = {"status": "ready", "work_id": args.preflight,
                  "before_count": len(row["before"]), "after_count": len(row["after"])}
    else:
        if args.stage is None:
            parser.error("preparation requires --stage")
        staged = prepare(args.repository_root, args.stage, args.receipt)
        result = {"status": staged["status"], "works": [x["work_id"] for x in staged["works"]]}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
