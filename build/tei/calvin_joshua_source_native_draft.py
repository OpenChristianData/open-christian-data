"""Fail-closed work-local Joshua route for its retained CCEL source set."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import source_member_set_bytes
from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.projection.categories import commentary as core


FAMILY = "calvin-joshua-source-native-v1"
IDENTITY = {
    "work_id": "calvin-commentary-on-joshua",
    "textual_form_id": "calvin-commentary-on-joshua-english",
    "edition_id": "calvin-commentary-on-joshua-ccel-electronic",
    "acquisition_id": "calvin-joshua-direct-ccel-xml-source-set",
}
EXPECTED_MEMBER_ROWS = [
    {
        "path": "raw/ccel/calvin-commentaries/calcom07.xml",
        "bytes": 1152629,
        "sha256": "98657e5ee3b1564e7d16729a8fd4fc73b1f46439f02e750fdbe700488fc33879",
    },
    {
        "path": "raw/ccel/calvin-commentaries/commentaries.xml",
        "bytes": 8839,
        "sha256": "d5167554c4c40ac2ba320e9ec75afd2565001e0f5f84b0245832b7bfa183b08f",
    },
]
EXPECTED_PATHS = {
    "adapter": "build/tei/calvin_joshua_source_native_draft.py",
    "producer": "build/tei/calvin_joshua_projection_draft_v2.py",
    "observer": "build/tei/calvin_joshua_projection_oracle_v2.py",
    "catalogue_observer": "build/tei/calvin_joshua_catalogue_oracle_draft.py",
}
DEPENDENCIES = {
    "ocd_kernel/projection/categories/commentary.py",
    "ocd_kernel/projection/categories/commentary_source_native.py",
    "ocd_kernel/projection/native_content.py",
    "ocd_kernel/projection/native_content_check.py",
    "ocd_kernel/projection/envelope.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/library/_common.py",
    "ocd_kernel/library/identities.py",
    "ocd_kernel/library/acquisitions.py",
    "ocd_kernel/tei/acceptance.py",
    "schemas/v2/categories/commentary.schema.json",
    "schemas/v2/public-row.schema.json",
    "schemas/v2/native-content.schema.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _relative(path: Path, root: Path, label: str) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise PipelineError(f"Joshua {label} path escapes its authority root: {path}") from exc


def _acceptance_identity(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    acceptance = metadata.get("acceptance")
    identity = acceptance.get("identity") if isinstance(acceptance, Mapping) else None
    if not isinstance(identity, Mapping):
        raise PipelineError("Joshua acceptance identity is missing")
    return identity


def _known_family(metadata: Mapping[str, Any]) -> bool:
    identity = _acceptance_identity(metadata)
    if identity.get("work_id") != IDENTITY["work_id"]:
        return False
    for key in ("edition_id", "acquisition_id"):
        if identity.get(key) != IDENTITY[key]:
            raise PipelineError(f"recognized Joshua work identity has a different {key}")
    return True


def _require_identity(metadata: Mapping[str, Any], master: Path) -> None:
    acceptance = metadata.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise PipelineError("Joshua acceptance authority is missing")
    identity = _acceptance_identity(metadata)
    edition = metadata.get("edition")
    if identity.get("textual_form_id", IDENTITY["textual_form_id"]) != IDENTITY["textual_form_id"]:
        raise PipelineError("Joshua accepted textual-form identity differs")
    if getattr(edition, "textual_form_id", None) != IDENTITY["textual_form_id"]:
        raise PipelineError("Joshua edition textual-form identity differs")
    source = acceptance.get("source")
    if not isinstance(source, Mapping) or source.get("source_kind") != "retained-member-set":
        raise PipelineError("Joshua accepted source_kind must be retained-member-set")
    root, _raw, paths, _parents = core._checker_parse(master)
    namespaces = {"t": "http://www.tei-c.org/ns/1.0"}
    for key, value in IDENTITY.items():
        hits = root.xpath(
            ".//t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno[@type=$key]",
            namespaces=namespaces,
            key=key,
        )
        if len(hits) != 1 or hits[0].text != value:
            raise PipelineError(f"Joshua accepted master identity binding differs: {key}")


def _source_facts(metadata: Mapping[str, Any], root: Path) -> tuple[Mapping[str, Any], Path, Path, Path]:
    acquisition = metadata.get("acquisition")
    if not isinstance(acquisition, Mapping):
        raise PipelineError("Joshua retained-member-set acquisition is missing")
    if acquisition.get("source_kind") != "retained-member-set":
        raise PipelineError("Joshua acquisition source_kind must be retained-member-set")
    if acquisition.get("acquisition_id") != IDENTITY["acquisition_id"] or acquisition.get("edition_id") != IDENTITY["edition_id"]:
        raise PipelineError("Joshua acquisition identity differs")
    members = acquisition.get("retained_files")
    if not isinstance(members, list) or len(members) != len(EXPECTED_MEMBER_ROWS):
        raise PipelineError("Joshua acquisition must bind the exact two-member source set")
    for member, expected in zip(members, EXPECTED_MEMBER_ROWS, strict=True):
        if not isinstance(member, Mapping) or any(member.get(key) != value for key, value in expected.items()):
            raise PipelineError("Joshua retained member order, path, length, or digest differs")
    try:
        manifest_bytes = source_member_set_bytes(dict(acquisition))
    except (KeyError, TypeError, ValueError) as exc:
        raise PipelineError(f"Joshua ordered source manifest cannot be reconstructed: {exc}") from exc
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if len(manifest_bytes) != acquisition.get("source_bytes") or manifest_sha != acquisition.get("source_sha256"):
        raise PipelineError("Joshua ordered source manifest digest or length differs from acquisition")
    expected_manifest_path = (
        f"library/works/{IDENTITY['work_id']}/forms/{IDENTITY['textual_form_id']}/"
        f"editions/{IDENTITY['edition_id']}/source-member-set.json"
    )
    if acquisition.get("source_path") != expected_manifest_path:
        raise PipelineError("Joshua ordered source manifest path differs")
    manifest_path = resolve_repo_path(root, expected_manifest_path)
    if io_path(manifest_path).read_bytes() != manifest_bytes:
        raise PipelineError("Joshua retained ordered source manifest file differs from validated acquisition")
    raw_path = resolve_repo_path(root, EXPECTED_MEMBER_ROWS[0]["path"])
    catalogue_path = resolve_repo_path(root, EXPECTED_MEMBER_ROWS[1]["path"])
    for path, expected in zip((raw_path, catalogue_path), EXPECTED_MEMBER_ROWS, strict=True):
        if io_path(path).stat().st_size != expected["bytes"] or _sha(path) != expected["sha256"]:
            raise PipelineError(f"Joshua retained source member bytes differ: {expected['path']}")
    return acquisition, manifest_path, raw_path, catalogue_path


def _header(metadata: Mapping[str, Any], path: Path, raw_sha: str) -> Mapping[str, Any]:
    root, _raw, paths, _parents = core._checker_parse(path)
    header = core._checker_header(root, paths)
    core._validate_accepted_header(header, metadata)
    if header.get("retained_sha256") != raw_sha:
        raise PipelineError("Joshua master/proxy retained_sha256 must bind raw calcom07.xml")
    return header


def _bundle(metadata: Mapping[str, Any], master: Path):
    project_root = resolve_path(metadata["root"], strict=True)
    master = resolve_path(master, strict=True)
    _relative(master, project_root, "master")
    edition_root = resolve_path(master.parent, strict=True)
    bundle_root = resolve_path(edition_root / "projection" / FAMILY, strict=True)
    _relative(bundle_root, edition_root, "projection bundle")
    profile_path = resolve_path(bundle_root / "profile.json", strict=True)
    proxy = resolve_path(bundle_root / "proxy.tei.xml", strict=True)
    support = resolve_path(bundle_root / "support.json", strict=True)
    for path in (profile_path, proxy, support):
        _relative(path, bundle_root, "bundle member")
        if not io_path(path).is_file():
            raise PipelineError(f"Joshua projection bundle member is missing: {path}")
    try:
        profile = json.loads(io_path(profile_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Joshua projection profile is unreadable: {profile_path}: {exc}") from exc
    acquisition, manifest_path, raw_path, catalogue_path = _source_facts(metadata, project_root)
    if profile.get("contract") != "ocd-calvin-joshua-accepted-projection-bundle-v1":
        raise PipelineError("Joshua projection profile contract differs")
    if profile.get("role") != "derived-commentary-row-input; not a candidate or accepted master":
        raise PipelineError("Joshua projection role must identify the proxy as derived row input")
    if profile.get("identity") != IDENTITY:
        raise PipelineError("Joshua projection identity binding differs")
    bindings = {
        "master_sha256": _sha(master),
        "proxy_sha256": _sha(proxy),
        "support_sha256": _sha(support),
        "source_manifest_sha256": acquisition["source_sha256"],
        "source_manifest_bytes": acquisition["source_bytes"],
        "raw_sha256": EXPECTED_MEMBER_ROWS[0]["sha256"],
        "catalogue_sha256": EXPECTED_MEMBER_ROWS[1]["sha256"],
        "raw_relative_path": EXPECTED_MEMBER_ROWS[0]["path"],
        "catalogue_relative_path": EXPECTED_MEMBER_ROWS[1]["path"],
    }
    for key, value in bindings.items():
        if profile.get(key) != value:
            raise PipelineError(f"Joshua projection profile {key} binding differs")
    pins = profile.get("runtime_and_schema_sha256")
    if not isinstance(pins, dict) or set(pins) != DEPENDENCIES:
        raise PipelineError("Joshua runtime/schema pin set is incomplete or unexpected")
    for relative, expected_sha in pins.items():
        dependency = resolve_path(project_root / relative, strict=True)
        _relative(dependency, project_root, "runtime dependency")
        if _sha(dependency) != expected_sha:
            raise PipelineError(f"Joshua runtime/schema dependency changed: {relative}")
    for role, relative in EXPECTED_PATHS.items():
        if profile.get(role + "_path") != relative:
            raise PipelineError(f"Joshua {role} path is not the exact reviewed versioned path")
        dependency = resolve_path(project_root / relative, strict=True)
        _relative(dependency, project_root, f"{role} module")
        if _sha(dependency) != profile.get(role + "_sha256"):
            raise PipelineError(f"Joshua {role} module bytes differ")
    return profile, profile_path, proxy, support, raw_path, catalogue_path


def _load_observer(project_root: Path, path: Path, module_name: str):
    _relative(path, project_root, "observer")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PipelineError(f"cannot load Joshua observer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _observe_sources(
    metadata: Mapping[str, Any], master: Path, proxy: Path, support: Path, raw: Path, catalogue: Path
) -> None:
    project_root = resolve_path(metadata["root"], strict=True)
    body_observer = _load_observer(
        project_root,
        resolve_path(project_root / EXPECTED_PATHS["observer"], strict=True),
        "calvin_joshua_body_observer",
    )
    body = body_observer.observe(raw, master, proxy, support)
    catalogue_observer = _load_observer(
        project_root,
        resolve_path(project_root / EXPECTED_PATHS["catalogue_observer"], strict=True),
        "calvin_joshua_catalogue_observer",
    )
    catalogue_result = catalogue_observer.observe(catalogue, master, support)
    if body.get("status") != "pass" or catalogue_result.get("status") != "pass":
        raise PipelineError("Joshua independent source observers did not both pass")
    if any(
        body.get(key) != value
        for key, value in {
            "raw_sha256": _sha(raw),
            "master_sha256": _sha(master),
            "proxy_sha256": _sha(proxy),
            "support_sha256": _sha(support),
            "body_source_nodes": 10290,
            "commentary_units": 173,
        }.items()
    ):
        raise PipelineError("Joshua independent component-body observer binding or coverage differs")
    expected_partition = {
        "total_source_elements": 157,
        "body_elements_mapped": 102,
        "nonbody_nonstyle_elements_mapped": 39,
        "stylesheet_elements_retained_source_only": 16,
        "equation": "157 = 102 + 39 + 16",
        "disjoint": True,
    }
    if any(
        catalogue_result.get(key) != value
        for key, value in {
            "catalogue_sha256": _sha(catalogue),
            "master_sha256": _sha(master),
            "source_links": 47,
        }.items()
    ) or catalogue_result.get("catalogue_partition") != expected_partition:
        raise PipelineError("Joshua independent catalogue observer binding or coverage differs")


def route(metadata: Mapping[str, Any]) -> str | None:
    """Return None only for unrelated works; reserve known Joshua identity fail-closed."""
    if not _known_family(metadata):
        return None
    try:
        master = resolve_path(metadata["master_path"], strict=True)
        _require_identity(metadata, master)
        _acquisition, _manifest, raw, _catalogue = _source_facts(metadata, resolve_path(metadata["root"], strict=True))
        _header(metadata, master, _sha(raw))
        _bundle(metadata, master)
    except PipelineError:
        raise
    except (OSError, etree.XMLSyntaxError, KeyError, TypeError, ValueError, ImportError) as exc:
        raise PipelineError(f"Joshua recognized identity lacks a valid retained-source projection authority: {exc}") from exc
    return FAMILY


def project(metadata: Mapping[str, Any], family: str = FAMILY) -> dict[str, Any]:
    if family != FAMILY:
        raise PipelineError("unknown Joshua source-native family")
    master = resolve_path(metadata["master_path"], strict=True)
    _require_identity(metadata, master)
    acquisition, _manifest, raw, _catalogue = _source_facts(metadata, resolve_path(metadata["root"], strict=True))
    _header(metadata, master, _sha(raw))
    profile, profile_path, proxy, support, raw, catalogue = _bundle(metadata, master)
    header = _header(metadata, proxy, _sha(raw))
    _observe_sources(metadata, master, proxy, support, raw, catalogue)
    identity = {key: metadata["acceptance"]["identity"][key] for key in core._IDENTITY_KEYS}
    result = core.project_commentary_document(
        proxy,
        identity=identity,
        language=metadata["language"],
        representation_revision=metadata["acceptance"]["representation_revision"]["id"],
        edition_title=metadata["edition"].title,
        source_url=header["source_url"],
        source_sha256=header["source_sha256"],
        retained_sha256=header["retained_sha256"],
    )
    result["authority"] = metadata["authority"]
    receipt = core.build_commentary_receipt(result, identity=identity, authority=metadata["authority"])
    receipt.update(
        master_sha256=_sha(master),
        projection_input_sha256=_sha(proxy),
        projection_support_sha256=_sha(support),
        projection_profile_sha256=_sha(profile_path),
        projection_role=profile["role"],
        source_manifest_sha256=acquisition["source_sha256"],
    )
    result["master_sha256"] = _sha(master)
    result["receipt"] = receipt
    return result


def verify(
    metadata: Mapping[str, Any], family: str, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any], receipt: Mapping[str, Any] | None
) -> list[str]:
    try:
        if family != FAMILY:
            return ["unknown Joshua source-native family"]
        master = resolve_path(metadata["master_path"], strict=True)
        _require_identity(metadata, master)
        acquisition, _manifest, raw, catalogue = _source_facts(metadata, resolve_path(metadata["root"], strict=True))
        _header(metadata, master, _sha(raw))
        profile, profile_path, proxy, support, raw, catalogue = _bundle(metadata, master)
        if not isinstance(receipt, Mapping):
            return ["Joshua projection receipt is missing"]
        root = resolve_path(metadata["root"], strict=True)
        _observe_sources(metadata, master, proxy, support, raw, catalogue)
        proxy_header = _header(metadata, proxy, _sha(raw))
        identity = {key: metadata["acceptance"]["identity"][key] for key in core._IDENTITY_KEYS}
        standard = dict(receipt)
        standard["master_sha256"] = _sha(proxy)
        for key in ("projection_input_sha256", "projection_support_sha256", "projection_profile_sha256", "projection_role", "source_manifest_sha256"):
            standard.pop(key, None)
        errors = core.verify_commentary_document(
            proxy,
            rows,
            standard,
            identity=identity,
            language=metadata["language"],
            representation_revision=metadata["acceptance"]["representation_revision"]["id"],
            edition_title=metadata["edition"].title,
            source_url=proxy_header["source_url"],
            source_sha256=proxy_header["source_sha256"],
            retained_sha256=proxy_header["retained_sha256"],
            authority=metadata["authority"],
        )
        receipt_pins = {
            "master_sha256": _sha(master),
            "projection_input_sha256": _sha(proxy),
            "projection_support_sha256": _sha(support),
            "projection_profile_sha256": _sha(profile_path),
            "projection_role": profile["role"],
            "source_manifest_sha256": acquisition["source_sha256"],
        }
        for key, expected in receipt_pins.items():
            if receipt.get(key) != expected:
                errors.append(f"Joshua receipt {key} differs")
        return sorted(set(errors))
    except (PipelineError, OSError, etree.XMLSyntaxError, KeyError, TypeError, ValueError, ImportError, AssertionError) as exc:
        return [str(exc)]
