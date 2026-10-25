"""Preflight or install the reviewed Moody PG61883 work generation.

Preflight is the default. Installation requires the explicit ``--apply`` flag,
an exact stage receipt digest, and a complete passing stage whose canonical
work path is still absent. The maintained installer owns locking, journaling,
generation handoff, and rollback/recovery semantics.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import re
import sys

from lxml import etree

from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import (
    _files,
    _validate_promoted_tree,
    install_accepted_work,
    read_accepted_work,
)
from ocd_kernel.library.state import validate_state


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "d-l-moody-prevailing-prayer"
FORM_ID = "english"
EDITION_ID = "d-l-moody-prevailing-prayer-pg61883"
PROJECTION_PROFILE = "ocd-prose-moody-pg61883-source-native-v1"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
EVIDENCE = WORK / "integration/moody-pg61883-electronic-acceptance-v1"
RECEIPT_NAME = "moody-pg61883-stage-receipt.json"
PROPOSAL = ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/MOODY_PG61883_IDENTITY_PROPOSAL_20261003.json"
PROPOSAL_SHA256 = "2845700ffc24342252504f214cf268cfcf4fbfc7495efd9318f02311a2c633b3"
SOURCE_REVIEW_SHA256 = "2035b608aac8a0b069be69220f7066d8491ba2052b28e4eaa8045937c2fdff5f"
SOURCE_MANIFEST_SHA256 = "d0fa96b1f2d9ec7378c010c03cd1d50bff8d0ceca752efa5be1016d282b4de6b"
SOURCE_ARCHIVE_SHA256 = "c3e9023f2c0e1065e4f2601c21b791ef50f94f1acb31ef4c61880b7592a3ff19"
MEMBER_SET_SHA256 = "b332decb87837d629d696537ab7a59143752335c2a38b3ad6cfd3bf2e8b4c7af"
CANDIDATE_PACKAGE_SHA256 = "913bc2d562273e17fbe611cdfd5d889cde440fcfaedca2be24c4e3a6defc0b27"
CANDIDATE_TEI_SHA256 = "9037804ddb27e710c1a29982ffdf1c804e38bbab54b0d8dbcb5d2e238172d7d9"
RUNTIME_JSON_SCHEMAS = (
    Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"),
    Path("schemas/v2/acceptance.schema.json"),
    Path("schemas/v2/work.schema.json"),
    Path("schemas/v2/acquisition.schema.json"),
    Path("schemas/v2/state.schema.json"),
    Path("schemas/v2/categories/prose.schema.json"),
    Path("schemas/v2/native-content.schema.json"),
    Path("schemas/v2/public-row.schema.json"),
    Path("schemas/v2/tei/controlled-values.json"),
)
RUNTIME_XSD_ROOT = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
RUNTIME_STAGE_ENTRYPOINT = Path("build/tools/stage_moody_prevailing_prayer_61883_acceptance.py")
RUNTIME_INSTALL_ENTRYPOINT = Path(__file__).resolve().relative_to(ROOT.resolve())


def _bytes(path: Path) -> bytes:
    return io_path(path).read_bytes()


def _sha_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(_bytes(path))


def _json(path: Path) -> dict:
    value = json.loads(_bytes(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _current_runtime_modules() -> dict[str, dict]:
    modules: dict[str, set[str]] = {}
    for name, module in tuple(sys.modules.items()):
        source = getattr(module, "__file__", None)
        if not isinstance(source, str) or not source:
            continue
        try:
            path = resolve_path(Path(source), strict=True)
            relative = path.relative_to(resolve_path(ROOT, strict=True))
        except (OSError, ValueError):
            continue
        if (relative.parts[0] not in {"build", "ocd_kernel"}
                or relative.parts[:2] == ("build", "tools")
                or path.suffix.lower() != ".py"):
            continue
        modules.setdefault(relative.as_posix(), set()).add(name)
    return {
        relative: {"path": relative, "module_names": sorted(names),
                   "bytes": len(_bytes(ROOT / relative)), "sha256": _sha_file(ROOT / relative)}
        for relative, names in sorted(modules.items())
    }



def _observe_runtime_module_set(captured_modules: dict[str, dict],
                               current_modules: dict[str, dict]) -> dict:
    """Report loaded-module observations and pin every observed module byte."""
    changed_or_added = [
        path for path, item in current_modules.items()
        if path not in captured_modules
        or captured_modules[path].get("sha256") != item.get("sha256")
        or captured_modules[path].get("bytes") != item.get("bytes")
    ]
    if not current_modules or changed_or_added:
        raise ValueError(f"currently loaded first-party modules are absent or differ from the staged closure: {changed_or_added[:5]}")
    omitted_modules = sorted(set(captured_modules) - set(current_modules))
    return {
        "currently_loaded_first_party_module_paths": sorted(current_modules),
        "currently_loaded_first_party_module_snapshot_sha256": _sha_bytes(json.dumps(
            current_modules, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
        "omitted_pinned_first_party_module_paths": omitted_modules,
    }

def _current_runtime_schemas() -> list[dict]:
    paths = set(RUNTIME_JSON_SCHEMAS)
    pending = [RUNTIME_XSD_ROOT]
    while pending:
        relative = pending.pop()
        if relative in paths:
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe runtime XSD reference: {relative}")
        payload = _bytes(ROOT / relative)
        paths.add(relative)
        if relative.suffix.lower() != ".xsd":
            continue
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        schema = etree.fromstring(payload, parser=parser)
        for node in schema.iter():
            if not isinstance(node.tag, str):
                continue
            if etree.QName(node).localname not in {"include", "import", "redefine"}:
                continue
            location = node.get("schemaLocation")
            if not location:
                continue
            if "://" in location or Path(location).is_absolute():
                raise ValueError(f"runtime XSD has a nonlocal import: {location}")
            pending.append(relative.parent / Path(location))
    return [{"path": relative.as_posix(), "bytes": len(_bytes(ROOT / relative)),
             "sha256": _sha_file(ROOT / relative)}
            for relative in sorted(paths, key=lambda item: item.as_posix())]


def _verify_runtime_closure(work_root: Path) -> dict:
    closure_path = work_root / EVIDENCE.relative_to(WORK) / "runtime-closure.json"
    closure = _json(closure_path)
    if closure.get("contract") != "ocd-moody-pg61883-runtime-closure-v1":
        raise ValueError("stage runtime closure contract is unsupported")
    if closure.get("python_version") != sys.version:
        raise ValueError("Python runtime differs from the reviewed stage closure")
    current_versions = {
        name: importlib.metadata.version(distribution)
        for name, distribution in (("lxml", "lxml"), ("jsonschema", "jsonschema"),
                                   ("referencing", "referencing"))
    }
    if current_versions != closure.get("third_party_versions"):
        raise ValueError("third-party runtime versions differ from the reviewed stage closure")
    captured_modules = {item.get("path"): item for item in closure.get("first_party_loaded_modules", [])}
    current_modules = _current_runtime_modules()
    module_observation = _observe_runtime_module_set(captured_modules, current_modules)
    if _current_runtime_schemas() != closure.get("runtime_schema_files"):
        raise ValueError("current JSON schema / TEI XSD import closure differs from staged closure")
    entrypoints = {item.get("path"): item for item in closure.get("entrypoints", [])}
    for relative in (RUNTIME_STAGE_ENTRYPOINT, RUNTIME_INSTALL_ENTRYPOINT):
        key = relative.as_posix()
        current = {"path": key, "bytes": len(_bytes(ROOT / relative)), "sha256": _sha_file(ROOT / relative)}
        if entrypoints.get(key) != current:
            raise ValueError(f"runtime entrypoint differs from reviewed stage closure: {key}")
    copied = closure.get("captured_file_copies")
    if not isinstance(copied, list) or not copied:
        raise ValueError("runtime closure has no copied module/schema bytes")
    for record in copied:
        source = Path(record["source_path"])
        target = Path(record["stage_path"])
        if source.is_absolute() or ".." in source.parts or target.is_absolute() or ".." in target.parts:
            raise ValueError("unsafe path in captured runtime closure")
        source_bytes = _bytes(ROOT / source)
        staged_bytes = _bytes(work_root / target.relative_to(WORK))
        expected = record.get("sha256")
        if (_sha_bytes(source_bytes) != expected or _sha_bytes(staged_bytes) != expected
                or len(source_bytes) != record.get("bytes")):
            raise ValueError(f"captured runtime file differs: {source}")
    return {"closure": closure, "current_module_observation": module_observation}


def _assert_local_graphics(stage: Path, tei_path: Path, accounting_path: Path, *, field: str) -> list[dict]:
    from lxml import etree

    tree = etree.parse(str(io_path(tei_path)))
    urls = [node.get("url") for node in tree.xpath("//*[local-name()='graphic']")]
    if len(urls) != 18 or len(set(urls)) != 18:
        raise ValueError(f"{field} must bind 18 unique graphic URLs")
    accounting = _json(accounting_path)
    image_records = accounting.get("image_assets")
    if not isinstance(image_records, list) or len(image_records) != 18:
        raise ValueError("source accounting must declare all 18 image assets")
    by_url = {item.get("url"): item for item in image_records if isinstance(item, dict)}
    if set(urls) != set(by_url):
        raise ValueError(f"{field} graphic URLs differ from source accounting")
    results = []
    for url in urls:
        item = by_url[url]
        relative = Path(url)
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2 or relative.parts[0] != "images":
            raise ValueError(f"unsafe {field} graphic URL: {url!r}")
        payload_path = tei_path.parent / relative
        payload = _bytes(payload_path)
        digest = _sha_bytes(payload)
        if len(payload) != item.get("bytes") or digest != item.get("sha256"):
            raise ValueError(f"{field} image bytes differ from source-accounting: {url}")
        expected_path = item.get("candidate_path" if field == "candidate" else "edition_path")
        resolved_stage = resolve_path(stage, strict=True)
        resolved_payload = resolve_path(payload_path, strict=True)
        try:
            logical_path = resolved_payload.relative_to(resolved_stage).as_posix()
        except ValueError as exc:
            raise ValueError(f"{field} image resolves outside the reviewed stage: {url}") from exc
        if Path(expected_path).as_posix() != logical_path:
            raise ValueError(f"{field} image destination label is stale: {url}")
        results.append({"url": url, "path": payload_path.as_posix(), "bytes": len(payload), "sha256": digest})
    return results


def preflight(stage: Path, receipt_sha256: str) -> dict:
    stage = stage.resolve(strict=True)
    if not stage.is_dir() or ROOT.resolve() in stage.parents:
        raise ValueError("stage must be an existing external worktree directory")
    receipt_path = stage / RECEIPT_NAME
    receipt_bytes = _bytes(receipt_path)
    if _sha_bytes(receipt_bytes) != receipt_sha256:
        raise ValueError("stage receipt hash does not match the explicit reviewed pin")
    receipt = json.loads(receipt_bytes)
    if (receipt.get("status") != "staged-only"
            or receipt.get("work_id") != WORK_ID
            or receipt.get("projection_profile") != PROJECTION_PROFILE
            or Path(receipt.get("canonical_root", "")).resolve() != ROOT.resolve()):
        raise ValueError("stage receipt does not bind this canonical work and root")
    expected_stage_pins = {
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "source_member_set_sha256": MEMBER_SET_SHA256,
        "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
        "candidate_tei_sha256": CANDIDATE_TEI_SHA256,
        "independent_review_sha256": SOURCE_REVIEW_SHA256,
    }
    if any(receipt.get(key) != value for key, value in expected_stage_pins.items()):
        raise ValueError("stage receipt source/candidate/review pins differ from the reviewed generation")
    staged_work = stage / WORK
    if _files(staged_work) != receipt.get("after"):
        raise ValueError("staged work tree differs from its complete receipt manifest")
    runtime_check = _verify_runtime_closure(staged_work)
    runtime_closure = runtime_check["closure"]
    canonical_work = ROOT / WORK
    if io_path(canonical_work).exists() or io_path(canonical_work).is_symlink() or io_path(canonical_work).is_junction():
        raise ValueError("canonical work path is no longer absent; initial-install preimage changed")
    proposal = _json(PROPOSAL)
    if _sha_file(PROPOSAL) != PROPOSAL_SHA256:
        raise ValueError("reviewed identity and canonical-home preimage proposal changed")
    records = proposal.get("proposed_records", {})
    if proposal.get("canonical_write_performed") is not False:
        raise ValueError("identity proposal is no longer a read-only preimage")
    if (records.get("work.json", {}).get("work_id") != WORK_ID
            or records.get("acquisition.json", {}).get("acquisition_id") != "pg61883-retained-zip"
            or records.get("acquisition.json", {}).get("edition_id") != EDITION_ID):
        raise ValueError("identity proposal changed from reviewed Moody identities")
    acceptance_paths = sorted(io_path(staged_work).rglob("acceptance.json"))
    if len(acceptance_paths) != 1:
        raise ValueError("stage must contain exactly one accepted edition")
    acceptance_path = Path(acceptance_paths[0])
    validate_acceptance(acceptance_path, root=stage)
    validate_state(io_path(staged_work / "state.json"), root=stage)
    records = _validate_promoted_tree(stage, staged_work, work_id=WORK_ID)
    if len(records) != 1 or records[0]["identity"].get("edition_id") != EDITION_ID:
        raise ValueError("promoted tree must contain only the reviewed PG61883 edition")
    record = records[0]
    candidate_binding = record["technical"]["candidate"]
    candidate_path = stage / candidate_binding["path"]
    master_path = stage / record["promotion"]["master"]["path"]
    accounting_path = stage / record["source"]["accounting"]["path"]
    candidate_images = _assert_local_graphics(stage, candidate_path, accounting_path, field="candidate")
    edition_images = _assert_local_graphics(stage, master_path, accounting_path, field="edition")
    candidate_projection = project_accepted_prose(stage, acceptance_path=acceptance_path)
    candidate_errors = verify_accepted_prose(stage, acceptance_path=acceptance_path,
                                             rows=candidate_projection["rows"],
                                             receipt=candidate_projection["receipt"])
    if candidate_errors or not candidate_projection["rows"]:
        raise ValueError(f"maintained staged prose reader failed: {candidate_errors[:3]}")
    native_projection = project_accepted_document(stage, acceptance_path=acceptance_path, category="prose", projection_profile=PROJECTION_PROFILE)
    native_errors = verify_accepted_document(
        stage, acceptance_path=acceptance_path, rows=native_projection["rows"],
        receipt=native_projection["receipt"], category="prose", projection_profile=PROJECTION_PROFILE)
    if native_errors or not native_projection["rows"]:
        raise ValueError(f"maintained staged native document reader failed: {native_errors[:3]}")
    rows_sha256 = _sha_bytes(json.dumps(candidate_projection["rows"], sort_keys=True,
                                       separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    native_rows_sha256 = _sha_bytes(json.dumps(native_projection["rows"], sort_keys=True,
                                              separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return {
        "contract": "ocd-moody-pg61883-install-preflight-v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "ready-for-explicit-apply",
        "canonical_root": ROOT.as_posix(), "canonical_work_path": (ROOT / WORK).as_posix(),
        "canonical_work_preimage": {"exists": False},
        "identity_proposal_path": PROPOSAL.relative_to(ROOT).as_posix(),
        "identity_proposal_sha256": PROPOSAL_SHA256,
        "stage_root": stage.as_posix(), "stage_receipt_path": receipt_path.as_posix(),
        "stage_receipt_sha256": receipt_sha256, "staged_file_count": len(receipt["after"]),
        "staged_generation_sha256": _sha_bytes(json.dumps(receipt["after"], sort_keys=True,
                                                              separators=(",", ":")).encode()),
        "acceptance_sha256": _sha_file(acceptance_path),
        "master_sha256": _sha_file(master_path),
        "candidate_sha256": candidate_binding["sha256"],
        "candidate_image_count": len(candidate_images), "edition_image_count": len(edition_images),
        "prose_projection_rows": len(candidate_projection["rows"]),
        "prose_projection_rows_sha256": rows_sha256,
        "prose_projection_receipt": candidate_projection["receipt"],
        "native_document_projection_rows": len(native_projection["rows"]),
        "native_document_projection_rows_sha256": native_rows_sha256,
        "native_document_projection_receipt": native_projection["receipt"],
        "runtime_closure_sha256": _sha_file(stage / EVIDENCE / "runtime-closure.json"),
        "runtime_first_party_module_count": len(runtime_closure["first_party_loaded_modules"]),
        "runtime_preflight_module_observation": runtime_check["current_module_observation"],
        "projection_profile": PROJECTION_PROFILE,
        "runtime_schema_file_count": len(runtime_closure["runtime_schema_files"]),
        "maintained_installer": "ocd_kernel.tei.install_accepted.install_accepted_work",
        "install_mode": "initial-install; expected_old omitted; existing accepted work is a hard stop",
        "runtime_catalog_preimage": "No separate mutable catalog is owned by this install. The work identity is discovered from library/works/<work_id>/work.json; the guarded destination is absent and install_accepted_work serializes/revalidates the complete work generation.",
        "no_apply_performed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--apply", action="store_true", help="install only after all exact stage and runtime checks pass")
    args = parser.parse_args()
    if len(args.receipt_sha256) != 64 or any(char not in "0123456789abcdef" for char in args.receipt_sha256):
        raise ValueError("receipt SHA-256 must be 64 lowercase hexadecimal characters")
    packet = preflight(args.stage, args.receipt_sha256)
    if args.apply:
        # Recheck target absence immediately before entering the maintained
        # lock/journal handoff; expected_old is intentionally omitted.
        runtime_before_apply = _verify_runtime_closure(args.stage.resolve(strict=True) / WORK)
        if _sha_file(args.stage.resolve(strict=True) / EVIDENCE / "runtime-closure.json") != packet["runtime_closure_sha256"]:
            raise ValueError("runtime closure artifact changed after preflight")
        if io_path(ROOT / WORK).exists():
            raise ValueError("canonical work appeared after preflight")
        packet["installation"] = install_accepted_work(ROOT, args.stage, work_id=WORK_ID)
        live = read_accepted_work(ROOT, work_id=WORK_ID)
        live_manifest = _files(live)
        staged_manifest = _files(args.stage / WORK)
        if live_manifest != staged_manifest:
            raise ValueError("installed work differs from the reviewed staged generation")
        live_closure = _verify_runtime_closure(Path(live))
        if live_closure["closure"] != runtime_before_apply["closure"]:
            raise ValueError("installed runtime closure differs from the reviewed staged closure")
        packet["runtime_module_observations"] = {
            "preflight": packet["runtime_preflight_module_observation"],
            "before_apply": runtime_before_apply["current_module_observation"],
            "after_install": live_closure["current_module_observation"],
            "interpretation": "Each process-specific loaded-module observation is a nonempty subset of the frozen first-party closure with exact bytes. Omitted paths are reported without attributing them to caching; added or changed modules reject. The complete staged module/schema closure and copied bytes remain exact.",
        }
        live_acceptance = next(path for path in io_path(live).rglob("acceptance.json"))
        validate_acceptance(live_acceptance, root=ROOT)
        validate_state(io_path(live) / "state.json", root=ROOT)
        live_projection = project_accepted_prose(ROOT, acceptance_path=Path(live_acceptance))
        live_errors = verify_accepted_prose(ROOT, acceptance_path=Path(live_acceptance),
                                             rows=live_projection["rows"],
                                             receipt=live_projection["receipt"])
        live_rows_sha256 = _sha_bytes(json.dumps(live_projection["rows"], sort_keys=True,
                                                 separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if live_errors or live_rows_sha256 != packet["prose_projection_rows_sha256"]:
            raise ValueError("installed master reader projection differs from reviewed stage projection")
        live_native_projection = project_accepted_document(ROOT, acceptance_path=Path(live_acceptance), category="prose", projection_profile=PROJECTION_PROFILE)
        live_native_errors = verify_accepted_document(
            ROOT, acceptance_path=Path(live_acceptance), rows=live_native_projection["rows"],
            receipt=live_native_projection["receipt"], category="prose", projection_profile=PROJECTION_PROFILE)
        live_native_sha256 = _sha_bytes(json.dumps(live_native_projection["rows"], sort_keys=True,
                                                  separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if live_native_errors or live_native_sha256 != packet["native_document_projection_rows_sha256"]:
            raise ValueError("installed native document reader projection differs from reviewed stage projection")
        live_work = Path(live)
        live_record = _validate_promoted_tree(ROOT, live_work, work_id=WORK_ID)
        if len(live_record) != 1:
            raise ValueError("installed generation has an unexpected accepted-edition count")
        live_candidate = ROOT / Path(live_record[0]["technical"]["candidate"]["path"])
        live_accounting = ROOT / Path(live_record[0]["source"]["accounting"]["path"])
        live_master = ROOT / Path(live_record[0]["promotion"]["master"]["path"])
        if len(_assert_local_graphics(ROOT, live_candidate, live_accounting, field="candidate")) != 18:
            raise ValueError("installed candidate does not retain all 18 local images")
        if len(_assert_local_graphics(ROOT, live_master, live_accounting, field="edition")) != 18:
            raise ValueError("installed edition does not retain all 18 local images")
        packet["status"] = "installed-and-validated"
        packet["installed_file_count"] = len(live_manifest)
        packet["installed_work_path"] = Path(live).as_posix()
        packet["no_apply_performed"] = False
    print(json.dumps(packet, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
