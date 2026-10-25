"""Stage two accepted Creeds.json metadata rebinds without installing them.

The accepted TEI and decision remain unchanged. Each copied complete work
generation adds only source-evidenced edition classification and a sealed
projection declaration in accepted source accounting.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "ocd-creeds-json-two-metadata-rebind-stage-v1"
PROJECTION_PROFILE = "ocd-creeds-json-accepted-tree-v1"
RECEIPTS = Path("D:/Library/Open Christian Data/reports/runs/creeds-json-acceptance-stage-20260926")
ROUTES = {
    "belgic-confession-of-faith": {
        "member": "raw/Creeds.json/creeds/belgic_confession_of_faith.json",
        "source_sha256": "61e0e7d28f1d9c9613221d9f82272c6e256196a3776341eac9c8691e58d2f8dd",
        "format": "Canon", "kind": "canon", "original_language": "French",
        "body_clause": "We all believe in our hearts and confess with our mouths",
        "manifest": "sources/doctrinal-documents/lib063-creeds-json/belgic-confession-of-faith/belgic-confession-of-faith.source-manifest.json",
        "prior_receipt_sha256": "841858f4ca8329807f30beefed8f0d5bc18416ebe709c999b3e354d1be046499",
    },
    "chalcedonian-definition": {
        "member": "raw/Creeds.json/creeds/chalcedonian_definition.json",
        "source_sha256": "10d6f69284569ff9b7caa22171edfc5d7515777987a1bb08af7e2a8ce985973f",
        "format": "Creed", "kind": "creed", "original_language": "Greek",
        "body_clause": "Therefore, following the holy fathers, we all with one accord teach men",
        "manifest": "sources/doctrinal-documents/lib063-creeds-json/chalcedonian-definition/chalcedonian-definition.source-manifest.json",
        "prior_receipt_sha256": "159ee70832a581de9ef501361f2314f8497b6c193e3ec09969774e5e26ec39f4",
    },
}


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _put_json(root: Path, relative: Path, value: object) -> Path:
    path = _io_path(root / relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return path


def _copy_file(root: Path, stage: Path, relative: Path) -> None:
    source = _io_path(root / relative)
    if not source.is_file():
        raise PipelineError(f"required dependency missing: {relative}")
    target = _io_path(stage / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_work(root: Path, stage: Path, relative: Path, expected: dict[str, str]) -> None:
    if _files(root / relative) != expected:
        raise PipelineError("canonical accepted work differs from prior complete generation")
    for member in expected:
        _copy_file(root, stage, relative / member)
    if _files(stage / relative) != expected:
        raise PipelineError("copied accepted generation differs")


def _evidence(root: Path, work_id: str, route: dict[str, str], master: Path) -> dict[str, object]:
    source_rel = Path(route["member"])
    source_bytes = _io_path(root / source_rel).read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != route["source_sha256"]:
        raise PipelineError("exact retained Creeds.json member changed")
    source = json.loads(source_bytes)
    if not isinstance(source, dict) or not isinstance(source.get("Metadata"), dict):
        raise PipelineError("retained Creeds.json metadata is missing")
    metadata = source["Metadata"]
    if (metadata.get("CreedFormat") != route["format"]
            or metadata.get("OriginalLanguage") != route["original_language"]):
        raise PipelineError("source document format or original-language label differs")
    data = source.get("Data")
    if work_id == "belgic-confession-of-faith":
        if not isinstance(data, list) or len(data) != 37 or not isinstance(data[0], dict):
            raise PipelineError("Belgic article envelope differs")
        content = data[0].get("Content")
    else:
        if not isinstance(data, dict):
            raise PipelineError("Chalcedonian content envelope differs")
        content = data.get("Content")
    if not isinstance(content, str) or route["body_clause"] not in content:
        raise PipelineError("retained English body clause differs")
    tree = etree.parse(str(_io_path(master)), etree.XMLParser(resolve_entities=False, no_network=True))
    if tree.getroot().get("{http://www.w3.org/XML/1998/namespace}lang") != "en":
        raise PipelineError("accepted TEI does not declare English representation language")
    return {
        "contract": "ocd-creeds-json-source-metadata-evidence-v1",
        "work_id": work_id,
        "source_path": source_rel.as_posix(),
        "source_sha256": route["source_sha256"],
        "source_bytes": len(source_bytes),
        "category": "doctrinal-documents",
        "language": "en",
        "document_kind": route["kind"],
        "kind_basis": {"json_pointer": "/Metadata/CreedFormat", "source_value": route["format"]},
        "language_basis": {
            "json_pointer": "/Data/0/Content" if isinstance(data, list) else "/Data/Content",
            "body_clause": route["body_clause"],
            "accepted_tei_root_xml_lang": "en",
            "original_language_metadata": route["original_language"],
            "original_language_is_not_this_electronic_text_language": True,
        },
    }


def prepare(work_id: str, *, stage: Path) -> dict[str, object]:
    if work_id not in ROUTES:
        raise PipelineError(f"work is not individually declared: {work_id}")
    route = ROUTES[work_id]
    stage = stage.absolute()
    if _io_path(stage).exists() or not _io_path(stage.parent).is_dir():
        raise PipelineError("stage must be fresh under an existing parent")
    if ROOT in stage.parents or RECEIPTS in stage.parents:
        raise PipelineError("stage overlaps protected input")
    receipt_path = RECEIPTS / work_id / "stage-receipt.json"
    if _sha(receipt_path) != route["prior_receipt_sha256"]:
        raise PipelineError("first acceptance receipt differs")
    prior = _read(receipt_path)
    if prior.get("work_id") != work_id or prior.get("status") != "staged-only":
        raise PipelineError("first acceptance receipt identity differs")
    work = Path("library/works") / work_id
    edition = work / "forms" / f"{work_id}-retained-electronic" / "editions" / f"{work_id}-creeds-json"
    master = edition / "master.tei.xml"
    acceptance = edition / "acceptance.json"
    accounting = work / "integration/creeds-json-electronic-v1/source-accounting.json"
    evidence = work / "integration/creeds-json-metadata-rebind-v1/metadata-evidence.json"
    before = _files(ROOT / work)
    if before != prior["after"]:
        raise PipelineError("canonical work differs from the 21-file accepted generation")
    old_acceptance = validate_acceptance(_io_path(ROOT / acceptance), root=_io_path(ROOT))
    if old_acceptance["identity"]["work_id"] != work_id or old_acceptance["promotion"]["status"] != "promoted":
        raise PipelineError("accepted identity or promotion differs")
    if _sha(ROOT / master) != old_acceptance["promotion"]["master"]["sha256"]:
        raise PipelineError("accepted master differs")
    manifest = SourceManifest.load(ROOT / route["manifest"], repository_root=ROOT)
    if manifest.record["work_id"] != work_id:
        raise PipelineError("source manifest work binding differs")
    changed_sources = {str(work / "work.json"), accounting.as_posix()}
    if any(item["path"] in changed_sources for item in manifest.record["authorities"]):
        raise PipelineError("source manifest directly binds metadata-changing files")
    _copy_work(ROOT, stage, work, before)
    for relative in (
        Path(route["member"]), Path(route["manifest"]),
        Path(route["manifest"]).parent / "config.json",
        Path("raw/Creeds.json/README.md"),
    ):
        _copy_file(ROOT, stage, relative)
    old_work = _read(ROOT / work / "work.json")
    new_work = _read(stage / work / "work.json")
    forms = new_work["textual_forms"]
    if len(forms) != 1 or len(forms[0]["editions"]) != 1:
        raise PipelineError("expected one form and one edition")
    selected = forms[0]["editions"][0]
    if selected.get("edition_id") != old_acceptance["identity"]["edition_id"]:
        raise PipelineError("edition identity differs")
    if "category" in selected or "language" in selected:
        raise PipelineError("category or language already declared")
    metadata = _evidence(ROOT, work_id, route, ROOT / master)
    selected["category"] = metadata["category"]
    selected["language"] = metadata["language"]
    validate_identity_update(old_work, new_work)
    _put_json(stage, work / "work.json", new_work)
    load_work(_io_path(stage / work / "work.json"))
    evidence_path = _put_json(stage, evidence, metadata)
    old_accounting = _read(ROOT / accounting)
    updated_accounting = _read(stage / accounting)
    if old_accounting != updated_accounting or "document_kind" in updated_accounting or "projection_profile" in updated_accounting:
        raise PipelineError("accepted source accounting precondition differs")
    updated_accounting["document_kind"] = metadata["document_kind"]
    updated_accounting["projection_profile"] = PROJECTION_PROFILE
    updated_accounting["metadata_evidence"] = {
        "path": evidence.as_posix(),
        "bytes": evidence_path.stat().st_size,
        "sha256": _sha(evidence_path),
    }
    _put_json(stage, accounting, updated_accounting)
    new_acceptance = _read(stage / acceptance)
    if new_acceptance != old_acceptance:
        raise PipelineError("copied acceptance differs from current acceptance")
    new_acceptance["source"]["accounting"]["bytes"] = _io_path(stage / accounting).stat().st_size
    new_acceptance["source"]["accounting"]["sha256"] = _sha(stage / accounting)
    old_source = dict(old_acceptance["source"])
    new_source = dict(new_acceptance["source"])
    old_source.pop("accounting")
    new_source.pop("accounting")
    if old_source != new_source or any(new_acceptance[key] != old_acceptance[key]
                                       for key in old_acceptance if key != "source"):
        raise PipelineError("metadata rebind changed acceptance identity, decision, or proof")
    write_acceptance(_io_path(stage / acceptance), new_acceptance)
    validated = validate_acceptance(_io_path(stage / acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    if validated["decision"] != old_acceptance["decision"] or _sha(stage / master) != _sha(ROOT / master):
        raise PipelineError("accepted decision or master changed")
    after = _files(stage / work)
    allowed = {"work.json", accounting.relative_to(work).as_posix(),
               acceptance.relative_to(work).as_posix(), evidence.relative_to(work).as_posix()}
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    if changed != allowed:
        raise PipelineError(f"metadata rebind changed unexpected work paths: {sorted(changed ^ allowed)}")
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": work_id,
        "prepared_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
        "prior_acceptance_receipt_sha256": route["prior_receipt_sha256"],
        "source_manifest_sha256": _sha(ROOT / route["manifest"]),
        "source_manifest_refreshed": False,
        "before": before, "after": after, "changed_paths": sorted(changed),
        "master_sha256": _sha(stage / master), "decision_preserved": True,
        "metadata_evidence": metadata,
        "limits": ["electronic witness classification only", "no print language or lineage claim", "no rights or publication decision"],
    }
    _put_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, choices=sorted(ROUTES))
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.work, stage=args.stage)
    print(json.dumps({key: result[key] for key in ("work_id", "status", "stage_root", "changed_paths", "master_sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
