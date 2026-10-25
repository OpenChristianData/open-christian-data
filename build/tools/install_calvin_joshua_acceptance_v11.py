"""Guarded Joshua accepted-work install caller; default is preflight only.

This task-local CLI deliberately refuses to run while the maintained Joshua
adapter still expects the preceding v5 producer/oracle locations. It never writes
canonical files unless ``--apply`` is supplied together with the exact SHA-256
of a previously reviewed preflight receipt. The actual install is delegated to
``ocd_kernel.tei.install_accepted.install_accepted_work``.
"""
from __future__ import annotations

import argparse
import builtins
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
BASE = REPO / ".tmp_audit/calvin-joshua-accepted-unit-draft"
IDENTITY = {
    "work_id": "calvin-commentary-on-joshua",
    "textual_form_id": "calvin-commentary-on-joshua-english",
    "edition_id": "calvin-commentary-on-joshua-ccel-electronic",
    "acquisition_id": "calvin-joshua-direct-ccel-xml-source-set",
}
FAMILY = "calvin-joshua-source-native-v1"
MASTER_SHA256 = "3a0d7ddad2b593715447a39ccaa658242f105548ab969b2ff48f8c0bc7dac97a"
PROXY_SHA256 = "c945502e2794a1baba2ed91fadeefb38a896f19c1a1d3d27bedcc9d6ecbb1587"
SUPPORT_SHA256 = "6eb9864f5d9c134ce42b9105f2726b6a71a8505d353a14d171652d9b7cda8897"
SOURCE_SET_SHA256 = "658155230f5efda75c1076c0e7f37ff919ff5c844d4584f6815200f4bd3d3e05"
RECONSTRUCTION_MANIFEST_SHA256 = "427da31af1a1c0b26afa973fbb673fbc58fab9ce84ee2b5290d51e04279cf047"
RECONSTRUCTION_ACCOUNTABILITY_SHA256 = "89b8016f818d3d843ba27e53bce584476eb7c410fd7315b84573f9abdac57a1c"
RECONSTRUCTION_PACKAGE_MANIFEST_SHA256 = "d5aacfa3660f0c689937487f8e03c8f2f06b703699bd1511172ba1a2b35aae60"
RECONSTRUCTION_CONTENT_SHA256 = "490cdd6af6ffa59a5ac6e52f410692b5d96c9858bc1ae274e880f958a51a1c4b"
HEADER_BINDING_RECEIPT_SHA256 = "db5a54fedbc26890325255b309a3b6447557575036dc10a50ee07b4108cab68e"
RAW_SHA256 = "98657e5ee3b1564e7d16729a8fd4fc73b1f46439f02e750fdbe700488fc33879"
CATALOGUE_SHA256 = "d5167554c4c40ac2ba320e9ec75afd2565001e0f5f84b0245832b7bfa183b08f"
EXPECTED_PATHS = {
    "adapter": "ocd_kernel/projection/categories/calvin_joshua_source_native.py",
    "producer": "build/tei/calvin_joshua_projection_draft_v6.py",
    "observer": "build/tei/calvin_joshua_projection_oracle_v6.py",
    "catalogue_observer": "build/tei/calvin_joshua_catalogue_oracle_v4.py",
}
STAGE_REL = Path("library/works") / IDENTITY["work_id"]
EDITION_REL = Path(
    "forms/calvin-commentary-on-joshua-english/editions/"
    "calvin-commentary-on-joshua-ccel-electronic"
)
WORK_ROOT = REPO / "ocd_kernel/projection/categories"
PREFLIGHT_PREFIX = "calvin-joshua-guarded-install-preflight-"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def file_map(root: Path) -> dict[str, dict[str, Any]]:
    """Hash the complete work generation, rejecting links and special nodes."""
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if is_reparse(path):
            raise RuntimeError(f"refusing reparse point in work generation: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError(f"refusing non-file work-generation entry: {path}")
        data = path.read_bytes()
        result[path.relative_to(root).as_posix()] = {
            "bytes": len(data),
            "sha256": sha_bytes(data),
        }
    if not result:
        raise RuntimeError(f"work generation is empty: {root}")
    return result


def is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError(f"cannot inspect path safety: {path}") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(attrs & getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def assert_safe_root(path: Path, *, label: str) -> Path:
    lexical = Path(os.path.abspath(path))
    cursor = lexical
    while cursor != cursor.parent:
        if cursor.exists() and is_reparse(cursor):
            raise RuntimeError(f"{label} traverses a reparse point: {cursor}")
        cursor = cursor.parent
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or is_reparse(resolved):
        raise RuntimeError(f"{label} must be a real directory: {path}")
    cursor = resolved
    while cursor != cursor.parent:
        if is_reparse(cursor):
            raise RuntimeError(f"{label} contains a reparse-point ancestor: {cursor}")
        cursor = cursor.parent
    return resolved


def assert_absent_plain_target(target: Path, root: Path) -> None:
    lexical_root = Path(os.path.abspath(root))
    cursor = Path(os.path.abspath(target))
    try:
        cursor.relative_to(lexical_root)
    except ValueError as exc:
        raise RuntimeError(f"Joshua live target escapes the selected library root: {target}") from exc
    while cursor != lexical_root:
        if is_reparse(cursor):
            raise RuntimeError(f"Joshua live target path contains a reparse point: {cursor}")
        if cursor == target and cursor.exists():
            raise RuntimeError(f"Joshua live target must be absent for initial install: {target}")
        cursor = cursor.parent


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {label} JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object: {path}")
    return value


def _assert_final_adapter_paths() -> tuple[Any, Path]:
    """Load the live adapter only after requiring coordinator's v6 path patch."""
    import importlib.util

    path = REPO / EXPECTED_PATHS["adapter"]
    spec = importlib.util.spec_from_file_location("calvin_joshua_guard_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load maintained Joshua adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = getattr(module, "EXPECTED_PATHS", None)
    if observed != EXPECTED_PATHS:
        raise RuntimeError(
            "maintained adapter path patch is not final v6; canonical preflight is disabled"
        )
    if getattr(module, "FAMILY", None) != FAMILY or getattr(module, "IDENTITY", None) != IDENTITY:
        raise RuntimeError("maintained adapter identity/family pin differs")
    return module, path


def _edition_paths(work: Path) -> tuple[Path, Path, Path, Path, Path]:
    edition = work / EDITION_REL
    master = edition / "master.tei.xml"
    acceptance = edition / "acceptance.json"
    acquisition = edition / "acquisitions/calvin-joshua-direct-ccel-xml-source-set.json"
    bundle = edition / "projection" / FAMILY
    return master, acceptance, acquisition, bundle / "profile.json", bundle


def _source_pins(stage_root: Path, metadata: dict[str, Any]) -> dict[str, str]:
    from ocd_kernel.lib.storage_topology import resolve_repo_path

    root = stage_root
    manifest_rel = metadata["acquisition"].get("source_path")
    if manifest_rel != (
        f"library/works/{IDENTITY['work_id']}/forms/{IDENTITY['textual_form_id']}/"
        f"editions/{IDENTITY['edition_id']}/source-member-set.json"
    ):
        raise RuntimeError("ordered source-manifest path differs from the Joshua acquisition")
    source_set = resolve_repo_path(root, manifest_rel)
    raw = resolve_repo_path(root, "raw/ccel/calvin-commentaries/calcom07.xml")
    catalogue = resolve_repo_path(root, "raw/ccel/calvin-commentaries/commentaries.xml")
    actual = {
        "source_member_set": sha_file(source_set),
        "component_raw": sha_file(raw),
        "shared_catalogue": sha_file(catalogue),
    }
    expected = {
        "source_member_set": SOURCE_SET_SHA256,
        "component_raw": RAW_SHA256,
        "shared_catalogue": CATALOGUE_SHA256,
    }
    if actual != expected:
        raise RuntimeError(f"retained source bytes differ from reviewed pins: {actual}")
    return actual


def _verify_reconstruction_source_proof(stage_root: Path, source_work: Path) -> dict[str, str]:
    integration = source_work / "integration/joshua-electronic-acceptance-v1"
    proof_path = integration / "reconstruction-source-proof-v6.json"
    manifest_copy_path = integration / "reconstruction-source-manifest-v6.json"
    package_root = integration / "reconstruction-candidate-package-v6"
    accountability_path = package_root / "source-accountability.json"
    package_manifest_path = package_root / "manifest.json"
    content_path = package_root / "content.tei.xml"
    receipt_path = integration / "acceptance-header-binding-receipt-v11.json"
    values = {
        "source_manifest": sha_file(manifest_copy_path),
        "source_accountability": sha_file(accountability_path),
        "candidate_package_manifest": sha_file(package_manifest_path),
        "candidate_content_tei": sha_file(content_path),
        "header_binding_receipt": sha_file(receipt_path),
    }
    expected = {
        "source_manifest": RECONSTRUCTION_MANIFEST_SHA256,
        "source_accountability": RECONSTRUCTION_ACCOUNTABILITY_SHA256,
        "candidate_package_manifest": RECONSTRUCTION_PACKAGE_MANIFEST_SHA256,
        "candidate_content_tei": RECONSTRUCTION_CONTENT_SHA256,
        "header_binding_receipt": HEADER_BINDING_RECEIPT_SHA256,
    }
    if values != expected:
        raise RuntimeError(f"v6 reconstruction evidence bytes differ from reviewed pins: {values}")
    current_manifest = REPO / "sources/commentaries/calvin/title-units/joshua/calvin-joshua.source-manifest-v6.json"
    if sha_file(current_manifest) != RECONSTRUCTION_MANIFEST_SHA256:
        raise RuntimeError("current Joshua v6 source manifest differs from reviewed bytes")
    proof = _load_json(proof_path, label="v6 reconstruction source proof")
    account = _load_json(accountability_path, label="v6 reconstruction accountability")
    package = _load_json(package_manifest_path, label="v6 reconstruction package manifest")
    receipt = _load_json(receipt_path, label="v11 acceptance header inverse receipt")
    binding = {
        "source_manifest": {"path": "sources/commentaries/calvin/title-units/joshua/calvin-joshua.source-manifest-v6.json", "sha256": RECONSTRUCTION_MANIFEST_SHA256},
        "candidate_package_root": package_root.relative_to(stage_root).as_posix(),
        "candidate_package_manifest": {"path": package_manifest_path.relative_to(stage_root).as_posix(), "sha256": RECONSTRUCTION_PACKAGE_MANIFEST_SHA256},
        "candidate_content_tei": {"path": content_path.relative_to(stage_root).as_posix(), "sha256": RECONSTRUCTION_CONTENT_SHA256},
        "candidate_content_tei_sha256": RECONSTRUCTION_CONTENT_SHA256,
        "candidate_source_accountability": {"path": accountability_path.relative_to(stage_root).as_posix(), "sha256": RECONSTRUCTION_ACCOUNTABILITY_SHA256},
        "header_binding_receipt_path": receipt_path.relative_to(stage_root).as_posix(),
        "header_binding_receipt_sha256": HEADER_BINDING_RECEIPT_SHA256,
    }
    if proof.get("status") != "pass" or any(proof.get(key) != value for key, value in binding.items()):
        raise RuntimeError("staged reconstruction proof does not bind the reviewed v6 source evidence")
    if package.get("source_manifest", {}).get("sha256") != RECONSTRUCTION_MANIFEST_SHA256:
        raise RuntimeError("staged candidate package manifest does not bind the v6 source manifest")
    members = package.get("members")
    if not isinstance(members, list) or len(members) != 5:
        raise RuntimeError("retained source candidate package member list differs")
    for row in members:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise RuntimeError("retained source candidate package member entry is invalid")
        path = package_root / row["name"]
        if not path.is_file() or path.stat().st_size != row.get("bytes") or sha_file(path) != row.get("sha256"):
            raise RuntimeError(f"retained source candidate package member differs: {row.get('name')}")
    title_binding = account.get("catalogue_title_binding")
    if proof.get("catalogue_title_binding") != title_binding:
        raise RuntimeError("staged source title binding differs from exact v6 accountability")
    if (
        receipt.get("bound_output", {}).get("sha256") != MASTER_SHA256
        or receipt.get("acceptance_binding_inverse", {}).get("exact_v6_input_candidate_sha256") != RECONSTRUCTION_CONTENT_SHA256
        or receipt.get("acceptance_binding_inverse", {}).get("inverse_tree_equals_input_candidate") is not True
    ):
        raise RuntimeError("staged header receipt does not prove the reviewed source/master inverse")
    return values | {"source_proof": sha_file(proof_path)}


def _verify_stage(stage_root: Path, adapter: Any) -> dict[str, Any]:
    from ocd_kernel.tei.acceptance import validate_acceptance
    from ocd_kernel.tei.install_accepted import _validate_promoted_tree
    from ocd_kernel.tei.validate import validate_file

    source_work = stage_root / STAGE_REL
    reconstruction_pins = _verify_reconstruction_source_proof(stage_root, source_work)
    records = _validate_promoted_tree(stage_root, source_work, work_id=IDENTITY["work_id"])
    if len(records) != 1 or records[0]["identity"] != IDENTITY:
        raise RuntimeError("staged accepted edition identity differs")
    _, acceptance, acquisition, profile_path, bundle = _edition_paths(source_work)
    validated = validate_acceptance(acceptance, root=stage_root)
    if validated["identity"] != IDENTITY:
        raise RuntimeError("maintained acceptance validation returned a different identity")
    profile = _load_json(profile_path, label="Joshua profile")
    if profile.get("identity") != IDENTITY:
        raise RuntimeError("projection profile identity differs")
    if profile.get("master_sha256") != MASTER_SHA256 or profile.get("proxy_sha256") != PROXY_SHA256:
        raise RuntimeError("projection profile master/proxy pin differs")
    if SUPPORT_SHA256 == "PENDING_V18_STAGE_SUPPORT_SHA256":
        raise RuntimeError("Joshua installer preflight is disabled until the exact v18 stage support digest is frozen")
    support_actual = sha_file(bundle / "support.json")
    if profile.get("support_sha256") != support_actual:
        raise RuntimeError("projection profile support digest does not bind the exact support bytes")
    if SUPPORT_SHA256 == "PENDING_V18_STAGE_SUPPORT_SHA256":
        raise RuntimeError("Joshua installer preflight is disabled until the exact v18 stage support digest is frozen")
    if support_actual != SUPPORT_SHA256:
        raise RuntimeError("projection support differs from the reviewed exact v18 stage pin")
    if profile.get("raw_sha256") != RAW_SHA256 or profile.get("catalogue_sha256") != CATALOGUE_SHA256:
        raise RuntimeError("projection primary raw-source/catalogue pin differs")
    if profile.get("source_manifest_sha256") != SOURCE_SET_SHA256:
        raise RuntimeError("projection aggregate retained-member-set pin differs")
    if {key: profile.get(key + "_path") for key in EXPECTED_PATHS} != EXPECTED_PATHS:
        raise RuntimeError("projection profile paths are not the final v6 path contract")
    if profile.get("adapter_sha256") != sha_file(adapter.__file__):
        raise RuntimeError("profile does not pin the current maintained Joshua adapter")
    for key, relative in EXPECTED_PATHS.items():
        if key == "adapter":
            continue
        if profile.get(key + "_sha256") != sha_file(REPO / relative):
            raise RuntimeError(f"profile {key} digest does not match current code")
    actual = {
        "master": sha_file(_edition_paths(source_work)[0]),
        "proxy": sha_file(bundle / "proxy.tei.xml"),
        "support": sha_file(bundle / "support.json"),
        "profile": sha_file(profile_path),
        "acceptance": sha_file(acceptance),
        "acquisition": sha_file(acquisition),
    }
    if actual["master"] != MASTER_SHA256 or actual["proxy"] != PROXY_SHA256 or actual["support"] != SUPPORT_SHA256:
        raise RuntimeError(f"staged candidate/projection bytes differ from reviewed pins: {actual}")
    master, *_ = _edition_paths(source_work)
    proxy = bundle / "proxy.tei.xml"
    if validate_file(master) or validate_file(proxy):
        raise RuntimeError("maintained P5 validation failed for master or derived proxy")
    source_pins = _source_pins(stage_root, {"acquisition": _load_json(acquisition, label="acquisition")})
    generation = file_map(source_work)
    generation_sha = sha_bytes(json.dumps(generation, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {
        "work_path": str(source_work),
        "identity": IDENTITY,
        "files": generation,
        "generation_sha256": generation_sha,
        "authority_sha256": actual,
        "source_sha256": source_pins,
        "reconstruction_source_sha256": reconstruction_pins,
        "p5": {"master": "pass", "proxy": "pass"},
    }


def _closure_snapshot(opened: set[str], *, roots: tuple[Path, ...]) -> dict[str, Any]:
    modules: dict[str, dict[str, str]] = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        try:
            path = Path(filename).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if path.suffix != ".py" or not any(path.is_relative_to(root) for root in roots):
            continue
        modules[name] = {"path": str(path), "sha256": sha_file(path)}
    resources = []
    for raw in sorted(opened):
        path = Path(raw)
        if not path.is_file() or path.suffix.lower() not in {".json", ".xsd", ".rng", ".sch", ".xml"}:
            continue
        resources.append({"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    return {"modules": modules, "opened_resources": resources}


class OpenCapture:
    """Record opened project JSON/XSD and TEI resources during one gate."""

    def __init__(self) -> None:
        self.opened: set[str] = set()
        self._builtins_open = builtins.open
        self._io_open = io.open
        self._path_open = Path.open

    def _record(self, value: Any) -> None:
        try:
            path = Path(os.fspath(value)).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        if path.suffix.lower() in {".json", ".xsd", ".rng", ".sch", ".xml"}:
            self.opened.add(str(path))

    def __enter__(self) -> "OpenCapture":
        def builtin_open(file: Any, *args: Any, **kwargs: Any):
            self._record(file)
            return self._builtins_open(file, *args, **kwargs)

        def io_open(file: Any, *args: Any, **kwargs: Any):
            self._record(file)
            return self._io_open(file, *args, **kwargs)

        def path_open(path: Path, *args: Any, **kwargs: Any):
            self._record(path)
            return self._path_open(path, *args, **kwargs)

        builtins.open = builtin_open
        io.open = io_open
        Path.open = path_open
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        builtins.open = self._builtins_open
        io.open = self._io_open
        Path.open = self._path_open


def _xsd_closure() -> list[dict[str, Any]]:
    from lxml import etree

    pending = [REPO / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"]
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in seen:
            continue
        seen.add(path)
        document = etree.parse(str(path))
        for node in document.xpath(
            "//x:include|//x:import|//x:redefine",
            namespaces={"x": "http://www.w3.org/2001/XMLSchema"},
        ):
            location = node.get("schemaLocation")
            if location:
                pending.append(path.parent / location)
    return [
        {"path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)}
        for path in sorted(seen)
    ]


def _runtime_proof(capture: OpenCapture, adapter: Any) -> dict[str, Any]:
    roots = (REPO,)
    closure = _closure_snapshot(capture.opened, roots=roots)
    xsd = _xsd_closure()
    seen = {item["path"] for item in closure["opened_resources"]}
    for item in xsd:
        path = (REPO / item["path"]).resolve(strict=True)
        if str(path) not in seen:
            closure["opened_resources"].append(
                {"path": str(path), "bytes": item["bytes"], "sha256": item["sha256"]}
            )
    closure["opened_resources"].sort(key=lambda item: item["path"])
    entrypoints = {
        "guarded_installer": Path(__file__).resolve(),
        "adapter": Path(adapter.__file__).resolve(),
    }
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if path and name in {
            "ocd_kernel.tei.install_accepted",
            "ocd_kernel.tei.acceptance",
            "ocd_kernel.tei.validate",
            "ocd_kernel.projection.categories.commentary",
            "ocd_kernel.projection.categories.commentary_source_native",
            "ocd_kernel.projection.categories.commentary_group_policy",
        }:
            entrypoints[name] = Path(path).resolve()
    closure["entrypoints"] = {
        name: {"path": str(path), "sha256": sha_file(path)}
        for name, path in sorted(entrypoints.items())
    }
    closure["xsd_import_closure"] = xsd
    return closure


def _assert_runtime_unchanged(closure: dict[str, Any]) -> None:
    expected_paths = []
    expected_paths.extend(closure.get("modules", {}).values())
    expected_paths.extend(closure.get("entrypoints", {}).values())
    expected_paths.extend(closure.get("opened_resources", []))
    expected_paths.extend(closure.get("xsd_import_closure", []))
    for item in expected_paths:
        raw_path = item.get("path")
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO / path
        if (
            not path.is_file()
            or ("bytes" in item and path.stat().st_size != item["bytes"])
            or sha_file(path) != item["sha256"]
        ):
            raise RuntimeError(f"runtime, entrypoint, JSON, schema, or source pin changed after review: {path}")


def _assert_no_pinned_runtime_drift(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    before_modules = before.get("modules", {})
    after_modules = after.get("modules", {})
    for name, pinned in before_modules.items():
        if after_modules.get(name) != pinned:
            raise RuntimeError(f"loaded first-party module changed during installation: {name}")
    if before.get("entrypoints") != after.get("entrypoints"):
        raise RuntimeError("installer/readback entrypoint hashes changed during installation")
    if before.get("xsd_import_closure") != after.get("xsd_import_closure"):
        raise RuntimeError("P5 XSD import closure changed during installation")
    prior_resources = {item["path"]: item for item in before.get("opened_resources", [])}
    for path, item in prior_resources.items():
        if item not in after.get("opened_resources", []):
            # Resource path roots may differ between staging and readback; the
            # prior bytes are still checked directly by _assert_runtime_unchanged.
            _assert_runtime_unchanged({"opened_resources": [item]})
    module_additions = [
        item
        for name, item in sorted(after_modules.items())
        if name not in before_modules
    ]
    before_resources = {item["path"] for item in before.get("opened_resources", [])}
    resource_additions = [
        item
        for item in after.get("opened_resources", [])
        if item["path"] not in before_resources
    ]
    return {"first_party_module_additions": module_additions, "resource_additions": resource_additions}


def _new_install_journal(library_root: Path, prior_names: set[str]) -> dict[str, Any] | None:
    audit = library_root / ".tmp_audit"
    try:
        candidates = sorted(
            path for path in audit.glob("accepted-install-*")
            if path.is_dir() and path.name not in prior_names
        )
    except OSError:
        return None
    if len(candidates) != 1:
        return None
    operation = candidates[0]
    journal_path = operation / "operation.json"
    try:
        journal = _load_json(journal_path, label="installer operation journal")
    except RuntimeError:
        return {"operation": str(operation), "phase": "journal-unreadable"}
    return {
        "operation": str(operation),
        "journal_path": str(journal_path),
        "journal_sha256": sha_file(journal_path),
        "phase": journal.get("phase"),
        "status": journal.get("result_status"),
    }


def _preflight(library_root: Path, stage_root: Path, capture: OpenCapture) -> dict[str, Any]:
    """Read-only complete-generation and current-target guard."""
    from ocd_kernel.lib.storage_topology import resolve_repo_path
    from ocd_kernel.projection.categories import commentary
    from ocd_kernel.tei.install_accepted import _validate_promoted_tree

    adapter, adapter_path = _assert_final_adapter_paths()
    source_work = stage_root / STAGE_REL
    target = library_root / STAGE_REL
    assert_absent_plain_target(target, library_root)
    source_proof = _verify_stage(stage_root, adapter)
    acceptance = _edition_paths(source_work)[1]
    metadata = commentary._accepted_metadata(stage_root, acceptance)
    if metadata.get("acceptance", {}).get("identity") != IDENTITY:
        raise RuntimeError("maintained accepted-metadata identity differs")
    family = adapter.route(metadata)
    if family != FAMILY:
        raise RuntimeError(f"maintained Joshua adapter selected unexpected family: {family}")
    adapter_projection = adapter.project(metadata, family)
    adapter_errors = adapter.verify(
        metadata, family, adapter_projection["rows"], adapter_projection["receipt"]
    )
    if adapter_errors:
        raise RuntimeError(f"Joshua adapter projection check failed: {adapter_errors[:5]}")
    acceptance = _edition_paths(source_work)[1]
    shared_projection = commentary.project_accepted_commentary(
        stage_root, acceptance_path=acceptance
    )
    if shared_projection["rows"] != adapter_projection["rows"]:
        raise RuntimeError("maintained commentary dispatcher output differs from direct Joshua adapter rows")
    if len(shared_projection["rows"]) != 173:
        raise RuntimeError(f"maintained Joshua commentary projection row count differs: {len(shared_projection['rows'])}")
    shared_errors = commentary.verify_accepted_commentary(
        stage_root,
        acceptance_path=acceptance,
        rows=shared_projection["rows"],
        receipt=shared_projection["receipt"],
    )
    if shared_errors:
        raise RuntimeError(f"maintained commentary dispatcher verification failed: {shared_errors[:5]}")
    row_bytes = json.dumps(
        shared_projection["rows"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    # Resolve one source member again through the configured repository topology
    # so the guard records the current raw authority independently of stage copy.
    raw_live = resolve_repo_path(REPO, "raw/ccel/calvin-commentaries/calcom07.xml")
    if sha_file(raw_live) != RAW_SHA256:
        raise RuntimeError("current canonical retained raw source differs from the reviewed pin")
    catalogue_live = resolve_repo_path(REPO, "raw/ccel/calvin-commentaries/commentaries.xml")
    if sha_file(catalogue_live) != CATALOGUE_SHA256:
        raise RuntimeError("current canonical shared catalogue differs from the reviewed pin")
    return {
        "status": "preflight-pass-no-apply",
        "identity": IDENTITY,
        "library_root": str(library_root),
        "stage_root": str(stage_root),
        "live_target": str(target),
        "live_target_absent": True,
        "adapter_path": str(adapter_path),
        "adapter_sha256": sha_file(adapter_path),
        "stage": source_proof,
        "projection": {
            "family": family,
            "row_count": len(shared_projection["rows"]),
            "rows_sha256": sha_bytes(row_bytes),
            "rows": shared_projection["rows"],
            "verified_errors": shared_errors,
        },
        "live_raw_source_sha256": sha_file(raw_live),
        "live_catalogue_sha256": sha_file(catalogue_live),
        "runtime_closure": _runtime_proof(capture, adapter),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", required=True, type=Path)
    parser.add_argument("--stage-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="install only after a reviewed preflight receipt is supplied")
    parser.add_argument("--preflight-receipt", type=Path, help="receipt generated by the default no-apply run")
    parser.add_argument("--preflight-sha256", help="exact reviewed preflight receipt SHA-256")
    args = parser.parse_args()

    install_state: dict[str, Any] = {
        "attempted": False,
        "returned": False,
        "operation": None,
    }
    try:
        stage_root = assert_safe_root(args.stage_root, label="staging root")
        library_root = assert_safe_root(args.library_root, label="library root")
        expected_library = resolve_expected_library_root()
        if library_root != expected_library:
            raise RuntimeError(
                f"selected library root is not the canonical Workspace installation root: {library_root} != {expected_library}"
            )
        with OpenCapture() as capture:
            preflight = _preflight(library_root, stage_root, capture)
        receipt_data = json.dumps(preflight, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        receipt_sha = sha_bytes(receipt_data)
        receipt_path = BASE / f"{PREFLIGHT_PREFIX}{preflight['stage']['generation_sha256']}.json"
        if args.apply:
            if args.preflight_receipt is None or args.preflight_sha256 is None:
                raise RuntimeError("--apply requires --preflight-receipt and --preflight-sha256")
            approved_path = args.preflight_receipt.resolve(strict=True)
            approved_bytes = approved_path.read_bytes()
            if sha_bytes(approved_bytes) != args.preflight_sha256:
                raise RuntimeError("reviewed preflight receipt digest differs")
            approved = _load_json(approved_path, label="reviewed preflight receipt")
            if approved.get("stage", {}).get("generation_sha256") != preflight["stage"]["generation_sha256"]:
                raise RuntimeError("stage generation changed after preflight review")
            if approved.get("stage_root") != str(stage_root) or approved.get("library_root") != str(library_root):
                raise RuntimeError("stage or configured library root differs from reviewed preflight")
            if approved.get("live_target") != preflight["live_target"]:
                raise RuntimeError("live installation target differs from reviewed preflight")
            if approved.get("stage", {}).get("files") != preflight["stage"]["files"]:
                raise RuntimeError("full staged work file map changed after preflight review")
            if approved.get("stage", {}).get("authority_sha256") != preflight["stage"]["authority_sha256"]:
                raise RuntimeError("candidate/projection/authority pins changed after preflight review")
            if approved.get("adapter_sha256") != preflight["adapter_sha256"]:
                raise RuntimeError("maintained adapter changed after preflight review")
            if approved.get("stage", {}).get("source_sha256") != preflight["stage"]["source_sha256"]:
                raise RuntimeError("retained-source pins changed after preflight review")
            if approved.get("projection") != preflight.get("projection"):
                raise RuntimeError("exact maintained projection rows changed after preflight review")
            if approved.get("runtime_closure") != preflight.get("runtime_closure"):
                raise RuntimeError("loaded first-party code/opened schema-resource closure changed after review")
            if approved.get("live_target_absent") is not True:
                raise RuntimeError("reviewed preflight did not prove an absent target")
            _assert_runtime_unchanged(preflight["runtime_closure"])
            immediate_map = file_map(stage_root / STAGE_REL)
            if immediate_map != approved["stage"]["files"]:
                raise RuntimeError("complete staged work bytes changed immediately before install")
            _, immediate_acceptance, immediate_acquisition, immediate_profile, immediate_bundle = _edition_paths(stage_root / STAGE_REL)
            immediate_authorities = {
                "master": sha_file(_edition_paths(stage_root / STAGE_REL)[0]),
                "proxy": sha_file(immediate_bundle / "proxy.tei.xml"),
                "support": sha_file(immediate_bundle / "support.json"),
                "profile": sha_file(immediate_profile),
                "acceptance": sha_file(immediate_acceptance),
                "acquisition": sha_file(immediate_acquisition),
            }
            if immediate_authorities != approved["stage"]["authority_sha256"]:
                raise RuntimeError("accepted authority bytes changed immediately before install")
            assert_absent_plain_target(library_root / STAGE_REL, library_root)
            immediate_preapply = {
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "target_absent": True,
                "source_generation_sha256": preflight["stage"]["generation_sha256"],
                "file_count": len(immediate_map),
                "authority_sha256": immediate_authorities,
            }
            result_path = BASE / f"calvin-joshua-guarded-install-result-{preflight['stage']['generation_sha256']}.json"
            if result_path.exists():
                raise RuntimeError(f"refusing to overwrite prior installation result: {result_path}")
            from ocd_kernel.tei.install_accepted import install_accepted_work, read_accepted_work
            with OpenCapture() as post_capture:
                install_state["attempted"] = True
                audit_root = library_root / ".tmp_audit"
                prior_operations = {
                    path.name for path in audit_root.glob("accepted-install-*")
                    if path.is_dir()
                } if audit_root.exists() else set()
                try:
                    installed = install_accepted_work(library_root, stage_root, work_id=IDENTITY["work_id"])
                except (OSError, RuntimeError, ValueError) as install_error:
                    install_state["journal"] = _new_install_journal(library_root, prior_operations)
                    phase = (install_state["journal"] or {}).get("phase")
                    if phase == "complete":
                        install_state["performed"] = True
                    elif phase in {"rolled-back", "recovered-old"}:
                        install_state["performed"] = False
                    raise install_error
                install_state["returned"] = True
                install_state["operation"] = installed.get("operation")
                live_work = read_accepted_work(library_root, work_id=IDENTITY["work_id"])
                installed_map = file_map(live_work)
                if installed_map != preflight["stage"]["files"]:
                    raise RuntimeError("installed readback file map differs from reviewed staged generation")
                from ocd_kernel.projection.categories import commentary
                acceptance = _edition_paths(live_work)[1]
                metadata = commentary._accepted_metadata(library_root, acceptance)
                projection = commentary.project_accepted_commentary(library_root, acceptance_path=acceptance)
                errors = commentary.verify_accepted_commentary(
                    library_root,
                    acceptance_path=acceptance,
                    rows=projection["rows"],
                    receipt=projection["receipt"],
                )
                if errors:
                    raise RuntimeError(f"post-install maintained readback projection failed: {errors[:5]}")
                live_adapter, _live_adapter_path = _assert_final_adapter_paths()
                post_runtime = _runtime_proof(post_capture, live_adapter)
                runtime_additions = _assert_no_pinned_runtime_drift(
                    preflight["runtime_closure"], post_runtime
                )
                _assert_runtime_unchanged(preflight["runtime_closure"])
                post_stage_proof = _verify_stage(library_root, live_adapter)
                if post_stage_proof["files"] != preflight["stage"]["files"]:
                    raise RuntimeError("post-readback maintained authorities differ from the reviewed generation")
                post_source = _source_pins(
                    library_root,
                    {"acquisition": _load_json(_edition_paths(live_work)[2], label="readback acquisition")},
                )
                if post_source != preflight["stage"]["source_sha256"]:
                    raise RuntimeError("post-readback retained source bytes differ from preflight")
                post_rows_sha = sha_bytes(
                    json.dumps(projection["rows"], sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
                if (
                    len(projection["rows"]) != 173
                    or post_rows_sha != preflight["projection"]["rows_sha256"]
                ):
                    raise RuntimeError("post-readback commentary rows differ from the reviewed 173-row projection")
            result = {
                "status": installed["status"],
                "operation": installed["operation"],
                "reviewed_preflight_receipt": str(approved_path),
                "reviewed_preflight_sha256": args.preflight_sha256,
                "installed_file_count": len(installed_map),
                "generation_sha256": preflight["stage"]["generation_sha256"],
                "readback_work_path": str(live_work),
                "acceptance_sha256": sha_file(acceptance),
                "row_count": len(projection["rows"]),
                "rows_sha256": post_rows_sha,
                "verified_errors": errors,
                "immediate_preapply": immediate_preapply,
                "post_readback_file_map": installed_map,
                "post_readback_checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "post_readback_runtime_closure": post_runtime,
                "audited_lazy_runtime_additions": runtime_additions,
                "canonical_install_performed": True,
            }
            result_bytes = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            result_path.write_bytes(result_bytes)
            print(json.dumps({"result_path": str(result_path), "result_sha256": sha_bytes(result_bytes), **result}, sort_keys=True))
            return 0

        if receipt_path.exists():
            if receipt_path.read_bytes() != receipt_data:
                raise RuntimeError(f"preflight receipt already exists with different bytes: {receipt_path}")
        else:
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_bytes(receipt_data)
        print(json.dumps({
            "status": preflight["status"],
            "identity": preflight["identity"],
            "stage_root": preflight["stage_root"],
            "generation_sha256": preflight["stage"]["generation_sha256"],
            "master_sha256": preflight["stage"]["authority_sha256"]["master"],
            "proxy_sha256": preflight["stage"]["authority_sha256"]["proxy"],
            "row_count": preflight["projection"]["row_count"],
            "rows_sha256": preflight["projection"]["rows_sha256"],
            "receipt_path": str(receipt_path),
            "receipt_sha256": receipt_sha,
            "canonical_install_performed": False,
        }, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        performed: bool | None = install_state.get("performed")
        if performed is None:
            performed = True if install_state["returned"] else (None if install_state["attempted"] else False)
        print(json.dumps({
            "status": "failed-after-install-call" if performed is True else ("install-outcome-needs-journal-review" if performed is None else "refused"),
            "reason": str(exc),
            "installer_call_attempted": install_state["attempted"],
            "installer_call_returned": install_state["returned"],
            "operation": install_state["operation"],
            "installer_journal": install_state.get("journal"),
            "canonical_install_performed": performed,
        }, sort_keys=True), file=sys.stderr)
        return 2


def resolve_expected_library_root() -> Path:
    """Return the maintained install root; raw junctions do not reroute library work."""
    from ocd_kernel.lib.storage_topology import resolve_repo_path

    expected = REPO.resolve(strict=True)
    live_work = resolve_repo_path(expected, "library/works/calvin-commentary-on-joshua")
    if live_work != expected / "library/works/calvin-commentary-on-joshua":
        raise RuntimeError("maintained library work path does not resolve inside the Workspace root")
    return expected


if __name__ == "__main__":
    raise SystemExit(main())
