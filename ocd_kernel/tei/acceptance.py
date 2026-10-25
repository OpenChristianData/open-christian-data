"""Evidence-backed acceptance and temporary promotion for one TEI edition.

The acceptance record is deliberately a handoff, not a second catalogue.  It
binds one work/form/edition/acquisition tuple to the exact source sidecar,
candidate TEI, source and reconstruction accounting, technical checks, and a
bounded review report.  ``promote_accepted_master`` writes a complete result
under a caller-selected fresh destination; it never mutates its input root.
That makes the operation suitable for fixture and staging roots while the
current runtime remains the authority until a later adoption decision.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, resolve_path, io_iterdir

import json
from copy import deepcopy
import stat
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from ocd_kernel.lib.atomic_io import _replace_with_retry
from typing import Any, Mapping, Sequence

from lxml import etree

from ocd_kernel.lib.storage_topology import (
    LOCAL_CONFIG_NAME,
    StorageTopologyError,
    repository_relative_path,
    resolve_repo_path,
)
from ocd_kernel.library._common import PipelineError, ensure_relative_path, load_json, safe_identifier, sha256_file, within, write_json
from ocd_kernel.library.acquisitions import (
    acquisition_for_edition,
    source_sha256,
)
from ocd_kernel.library.identities import Work, discover_work, edition_by_id
from ocd_kernel.library.state import validate_state


SCHEMA_PATH = resolve_path(Path(__file__)).parents[2] / "schemas" / "v2" / "acceptance.schema.json"
ACCEPTANCE_CONTRACT = "ocd-tei-acceptance-v1"
PROMOTED_MASTER_REASON = (
    "Evidence-backed TEI is the master; human verification, rights, and publication "
    "remain separate."
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
WATSON_ACCEPTANCE_IDENTITY = (
    "watson-ten-commandments",
    "watson-ten-commandments-english",
    "watson-ten-commandments-ccel-thml",
    "watson-ten-commandments-ccel-retained",
)
WATSON_ACCEPTANCE_SOURCE_SHA = "88f65cbe3a515841a14ecd7c982880b528a32c4420ac71169485ef54ccdb89d6"
WATSON_ACCEPTANCE_SELECTION_ID = "watson-ten-commandments-all-divisions-v1"
WATSON_ACCEPTANCE_SUPPRESSED_TITLES = 7
DIVINE_CONTENTMENT_IDENTITY = (
    "watson-divine-contentment",
    "watson-divine-contentment-english",
    "watson-divine-contentment-ccel-thml",
    "watson-divine-contentment-ccel-retained",
)
DIVINE_CONTENTMENT_SOURCE = "raw/ccel/watson/contentment.xml"
DIVINE_CONTENTMENT_SOURCE_SHA = "767ed95de4c4c990480670084e8dd1ac16b6c61d50b864e8b0202e528a076d7b"
DIVINE_CONTENTMENT_SELECTION_ID = "watson-divine-contentment-complete-present-thml-v1"
DIVINE_CONTENTMENT_MANIFEST = 'sources/structured-text/watson-divine-contentment/runtime-proof-20261025-main.source-manifest.json'
DIVINE_CONTENTMENT_MANIFEST_SHA = '11f0a1bf1f70305074809eba612235db1bf35af17e4327f435355f2baec460fe'
DIVINE_CONTENTMENT_PACKAGE_SHA = 'aed04716e850d3a9e7dd5d9fa902ce90f5f1bca94d698e418448da141248990d'
DIVINE_CONTENTMENT_VALIDATION_SHA = '01427cf98c296b19558bf89f8904ac76df868ba7190c640c50cc09e7c6b22ee4'
DIVINE_CONTENTMENT_HISTORICAL_CVW_SHA = "be0e14ef0c8bf29caa5f7c6aa2446552ae03a21c258f8a4d2ae7df1f7097b3fb"
DIVINE_CONTENTMENT_HISTORICAL_MANIFEST = (
    "sources/structured-text/watson-divine-contentment/"
    "watson-divine-contentment.source-manifest.json"
)
DIVINE_CONTENTMENT_HISTORICAL_MANIFEST_SHA = "056e2f07288f95c86831de301e2b7981824236d224143207dfac8402c458e415"
DIVINE_CONTENTMENT_HISTORICAL_PACKAGE_SHA = "cd4e3b055480a4ffa086fa45956d8cc0ab098f0e99ce252d7792d5890ee3c965"
DIVINE_CONTENTMENT_HISTORICAL_VALIDATION_SHA = "7ee3a3cf8a299f572d96ece0942e803a249f80aacf2d400dff5f32a74fa47b34"
DIVINE_CONTENTMENT_HISTORICAL_ACCEPTANCE_SHA = "622e6da3701484de32b833ee7e63d8f67f8b07fd7be9c7e2b8f275cb453b1e68"
DIVINE_CONTENTMENT_INSTALLED_MASTER_SHA = "c72641deb76db40c5fb95e2152b04df683ac714dbaee73f90cb9c62c31805e8f"
DIVINE_CONTENTMENT_ORACLE_ID = "ocd-watson-independent-present-thml-oracle"
DIVINE_CONTENTMENT_ORACLE_SHA = "2899b332e826626fb732fe2ac7b5aca265913c166195f9efcdb5c2713c6ecd36"
DIVINE_CONTENTMENT_EVIDENCE = 'library/works/watson-divine-contentment/integration/runtime-proof-20261025-main/current-candidate/package'
DIVINE_CONTENTMENT_HISTORICAL_EVIDENCE = (
    "library/works/watson-divine-contentment/integration/"
    "ccel-thml-agent-handoff/inputs/package"
)
DIVINE_CONTENTMENT_HISTORICAL_VALIDATION = (
    "library/works/watson-divine-contentment/integration/"
    "ccel-thml-agent-handoff/inputs/validation.json"
)
DIVINE_CONTENTMENT_HISTORICAL_ACCEPTANCE = (
    "library/works/watson-divine-contentment/integration/"
    "ccel-thml-closure-rebind-v2/inputs/historical-acceptance.json"
)

BEATITUDES_ACCEPTANCE_IDENTITY = (
    "watson-beatitudes",
    "watson-beatitudes-route-source-form",
    "watson-beatitudes-retained-thml-route",
    "watson-beatitudes-retained-source",
)
BEATITUDES_ACCEPTANCE_SOURCE = "raw/ccel/watson/beatitudes.xml"
BEATITUDES_ACCEPTANCE_SOURCE_SHA = "d85ea8ded5de4feff3b2a9156bece9c471ffec3045eb8dc300b2784f5753f837"
BEATITUDES_ACCEPTANCE_SELECTION_ID = "watson-beatitudes-all-direct-div1-route-envelope-v1"
BEATITUDES_ACCEPTANCE_MANIFEST = 'sources/structured-text/watson-beatitudes/runtime-proof-20261025-main.source-manifest.json'
BEATITUDES_ACCEPTANCE_MANIFEST_SHA = '64a5ada40506f676e496c6f1431c36886495f1db5e11700ab0bb24b8be5696b9'
BEATITUDES_ACCEPTANCE_PACKAGE_SHA = 'bc59ce1a0133e31497aa9ba297b31ceee976bfc0230f68910f8ff009f8fb40b4'
BEATITUDES_HISTORICAL_MANIFEST = (
    "library/works/watson-beatitudes/integration/"
    "ccel-thml-agent-handoff/inputs/source-manifest.json"
)
BEATITUDES_HISTORICAL_MANIFEST_SHA = "8598d6562f80487911e6f4aa29793d9f063aa1c0201ad317c541838c1431819a"
BEATITUDES_HISTORICAL_PACKAGE_SHA = "f5a38c221caf112a9088c866a582f963e3fb9d26abaa8f37982d6a390e0be411"
BEATITUDES_HISTORICAL_VALIDATION_SHA = "b6e20dc4c824475028a3c8175f886ce2601d479943b8994cec9edbc17741e6db"
BEATITUDES_HISTORICAL_ACCEPTANCE_SHA = "d62a61fa4abae97be5654f414f11e411d967bdf13131414c5336d32ef6918fa2"
BEATITUDES_INSTALLED_MASTER_SHA = "07b0070649c6a6b8e6ebbfd300834299dc2d64cc3684e2198fc42dadb82b0aef"
BEATITUDES_ACCEPTANCE_ORACLE_ID = "ocd-watson-beatitudes-independent-source-walk"
BEATITUDES_ACCEPTANCE_ORACLE_SHA = "6dc00660c57e008755d7029ffbb0990db25bd8702db517edfa6b52c12c5e60b8"
BEATITUDES_ACCEPTANCE_EVIDENCE = 'library/works/watson-beatitudes/integration/runtime-proof-20261025-main/current-candidate/package'
BEATITUDES_HISTORICAL_EVIDENCE = (
    "library/works/watson-beatitudes/integration/"
    "ccel-thml-agent-handoff/inputs/package"
)
BEATITUDES_HISTORICAL_VALIDATION = (
    "library/works/watson-beatitudes/integration/"
    "ccel-thml-agent-handoff/inputs/validation.json"
)
BEATITUDES_HISTORICAL_ACCEPTANCE = (
    "library/works/watson-beatitudes/integration/"
    "ccel-thml-closure-rebind-v2/inputs/historical-acceptance.json"
)

RUNTIME_SUPPLEMENTS = {'watson-beatitudes': '239d1ca8d42aff08a549162a3ae8955084aa185bd2eae565f9b78f60e1b80361', 'watson-divine-contentment': '3b452021bb7341e5d25c5f2c916ee9d425accd8c186b97254817f32ef55609b1'}


@dataclass(frozen=True)
class PromotionResult:
    """Paths and digest produced by a non-destructive temporary promotion."""

    destination_root: Path
    acceptance_path: Path
    master_path: Path
    state_path: Path
    master_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "destination_root": self.destination_root.as_posix(),
            "acceptance_path": self.acceptance_path.as_posix(),
            "master_path": self.master_path.as_posix(),
            "state_path": self.state_path.as_posix(),
            "master_sha256": self.master_sha256,
        }


def _schema() -> dict[str, Any]:
    try:
        value = json.loads(io_path(SCHEMA_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot load acceptance schema: {SCHEMA_PATH}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"acceptance schema must be an object: {SCHEMA_PATH}")
    return value


def _schema_validate(record: Mapping[str, Any], *, context: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise PipelineError(f"{context} must be a JSON object")
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - project dependency
        raise PipelineError("jsonschema is required for acceptance validation") from exc
    validator = jsonschema.Draft202012Validator(
        _schema(), format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{context}{error.json_path}: {error.message}" for error in errors[:8]
        )
        if len(errors) > 8:
            details += f"; {len(errors) - 8} more schema errors"
        raise PipelineError(details)
    return dict(record)


def load_acceptance(path: Path) -> dict[str, Any]:
    """Load and schema-validate one acceptance record without filesystem checks."""

    path = Path(path)
    return _schema_validate(load_json(path), context=str(path))


def _relative(root: Path, path: Path, *, field: str) -> str:
    try:
        return resolve_path(path).relative_to(resolve_path(root)).as_posix()
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"{field} is outside the selected fixture root: {path}") from exc


def _fixture_path(root: Path, reference: str, *, field: str) -> Path:
    """Resolve a candidate/state/sidecar path strictly inside ``root``."""

    try:
        return within(root, reference, field=field)
    except PipelineError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"cannot resolve {field}: {reference}") from exc


def _evidence_path(root: Path, reference: str, *, field: str) -> Path:
    """Resolve evidence through the explicit raw/reports/exports topology.

    Candidate, master, acceptance, and state paths use ``_fixture_path`` and
    therefore cannot escape the selected temporary root.  Evidence may point
    at the configured logical ``raw``, ``reports`` or ``exports`` homes; the
    topology resolver remains the only route for those external paths.
    """

    try:
        relative = ensure_relative_path(reference, field=field)
        normalized = relative.as_posix()
        return resolve_repo_path(Path(root), normalized)
    except (PipelineError, StorageTopologyError) as exc:
        raise PipelineError(f"cannot resolve {field}: {reference}") from exc


def _binding(root: Path, value: Mapping[str, Any], *, field: str, fixture_only: bool) -> Path:
    if not isinstance(value, dict):
        raise PipelineError(f"{field} must be an object")
    reference = value.get("path")
    if not isinstance(reference, str):
        raise PipelineError(f"{field}.path must be a string")
    path = (
        _fixture_path(root, reference, field=f"{field}.path")
        if fixture_only
        else _evidence_path(root, reference, field=f"{field}.path")
    )
    if not io_path(path).is_file():
        raise PipelineError(f"{field} does not resolve to a file: {reference}")
    try:
        actual_bytes = io_path(path).stat().st_size
    except OSError as exc:
        raise PipelineError(f"cannot stat {field}: {path}") from exc
    if actual_bytes != value["bytes"]:
        raise PipelineError(
            f"{field} byte mismatch: {reference} has {actual_bytes}, expected {value['bytes']}"
        )
    actual_hash = sha256_file(path)
    if actual_hash != value["sha256"]:
        raise PipelineError(f"{field} sha256 mismatch: {reference}")
    return path


def make_file_binding(root: Path, path: str | Path, *, fixture_only: bool = True) -> dict[str, Any]:
    """Create a path/byte/hash binding for an existing evidence file.

    Absolute paths must either be inside ``root`` or be a configured external
    data-plane path.  The returned path is normalized repository-relative POSIX
    text so the record remains portable and schema-valid.
    """

    root = resolve_path(Path(root))
    candidate = Path(path)
    if not candidate.is_absolute():
        reference = candidate.as_posix()
        resolved = (
            _fixture_path(root, reference, field="binding path")
            if fixture_only
            else _evidence_path(root, reference, field="binding path")
        )
    else:
        resolved = resolve_path(candidate)
        try:
            reference = resolved.relative_to(root).as_posix()
        except (OSError, RuntimeError, ValueError):
            try:
                reference = repository_relative_path(root, resolved)
            except StorageTopologyError as exc:
                raise PipelineError(f"binding path is outside configured storage: {path}") from exc
            if fixture_only:
                raise PipelineError(f"binding path is outside fixture root: {path}")
            resolved = _evidence_path(root, reference, field="binding path")
    if not io_path(resolved).is_file():
        raise PipelineError(f"binding path does not resolve to a file: {path}")
    return {
        "path": reference.replace("\\", "/"),
        "bytes": io_path(resolved).stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _require_file(root: Path, reference: str, *, field: str) -> Path:
    # Retained source members may live under the configured raw/reports data
    # plane.  Candidate, state, and promotion destinations use the fixture
    # boundary directly; evidence members use the storage topology resolver.
    path = _evidence_path(root, reference, field=field)
    if not io_path(path).is_file():
        raise PipelineError(f"{field} does not resolve to a file: {reference}")
    return path


def _object_file(path: Path, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(io_path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"{field} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"{field} must contain a JSON object: {path}")
    return value


def _identity(record: Mapping[str, Any]) -> dict[str, str]:
    value = record.get("identity")
    if not isinstance(value, dict):
        raise PipelineError("acceptance identity must be an object")
    result: dict[str, str] = {}
    for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id"):
        raw = value.get(key)
        if not isinstance(raw, str):
            raise PipelineError(f"acceptance identity missing {key}")
        result[key] = safe_identifier(raw, field=key)
    return result


def _same_identity(value: Any, identity: Mapping[str, str], *, field: str) -> None:
    if not isinstance(value, dict):
        raise PipelineError(f"{field} identity is missing")
    for key, expected in identity.items():
        if value.get(key) != expected:
            raise PipelineError(
                f"{field} identity mismatch for {key}: {value.get(key)!r} != {expected!r}"
            )


def _member_map(items: Any, *, field: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise PipelineError(f"{field} must be a list")
    result: dict[str, dict[str, Any]] = {}
    positions: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            raise PipelineError(f"{field} entries must be objects")
        path = item.get("path")
        position = item.get("position")
        if not isinstance(path, str) or not path:
            raise PipelineError(f"{field} entry path is required")
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            raise PipelineError(f"{field} entry position is invalid: {path}")
        ensure_relative_path(path, field=f"{field}.path")
        if path in result:
            raise PipelineError(f"duplicate member path in {field}: {path}")
        if position in positions:
            raise PipelineError(f"duplicate member position in {field}: {position}")
        result[path] = item
        positions.add(position)
    return result


def _source_binding(acquisition: Mapping[str, Any], *, context: str) -> dict[str, Any]:
    """Return the singular source binding declared by an acquisition.

    A complete original-source group is preferred.  A standalone retained
    member may supply the binding when it carries its own path, byte count,
    digest, and source scope.  Multiple retained members without an original
    group remain intentionally ambiguous. An explicit retained-member-set kind
    binds a validated manifest file rather than claiming one original file.
    """

    source_hash = source_sha256(dict(acquisition), context=context)
    original_keys = ("source_path", "source_bytes", "source_scope")
    present = [key in acquisition for key in original_keys]
    if all(present):
        source_path = acquisition["source_path"]
        source_bytes = acquisition["source_bytes"]
        source_scope = acquisition["source_scope"]
    elif any(present):
        raise PipelineError(
            f"{context} has an incomplete source_path/source_bytes/source_scope group"
        )
    else:
        retained = acquisition.get("retained_files")
        if not isinstance(retained, list) or len(retained) != 1 or not isinstance(retained[0], Mapping):
            raise PipelineError(
                f"{context} requires a complete original source group or exactly one scoped retained member"
            )
        member = retained[0]
        required = ("path", "bytes", "sha256", "scope")
        if any(key not in member for key in required):
            raise PipelineError(
                f"{context} single retained member lacks path, bytes, digest, or scope"
            )
        source_path = member["path"]
        source_bytes = member["bytes"]
        source_scope = member["scope"]
        if source_hash != member["sha256"]:
            raise PipelineError(
                f"{context} source hash does not bind its single retained member"
            )
    if not isinstance(source_path, str) or not source_path:
        raise PipelineError(f"{context} source_path is missing")
    if not isinstance(source_bytes, int) or isinstance(source_bytes, bool) or source_bytes < 0:
        raise PipelineError(f"{context} source_bytes is invalid")
    if not isinstance(source_scope, str) or not source_scope.strip():
        raise PipelineError(f"{context} source_scope is missing")
    binding = {
        "source_path": source_path,
        "source_sha256": source_hash,
        "source_bytes": source_bytes,
        "source_scope": source_scope,
    }
    if acquisition.get('source_kind') == 'retained-member-set':
        binding['source_kind'] = acquisition['source_kind']
    return binding


def _validate_scope(record: Mapping[str, Any], acquisition: Mapping[str, Any], root: Path) -> None:
    scope = record["scope"]
    expected = _member_map(scope["expected_members"], field="scope.expected_members")
    included = _member_map(scope["included_members"], field="scope.included_members")
    excluded = _member_map(scope["excluded_members"], field="scope.excluded_members")
    if not included:
        raise PipelineError("accepted scope must include at least one retained member")
    if acquisition.get('source_kind') == 'retained-member-set':
        ordered = [item['path'] for item in acquisition['retained_files']]
        declared = [item['path'] for item in sorted(scope['expected_members'], key=lambda item: item['position'])]
        if declared != ordered:
            raise PipelineError('accepted member order differs from source member set')
    if set(included) & set(excluded):
        raise PipelineError("scope cannot include and exclude the same member")
    if set(included) | set(excluded) != set(expected):
        raise PipelineError(
            "scope expected_members must be exactly the union of included_members and "
            "excluded_members"
        )
    for path, item in included.items():
        if expected[path]["position"] != item["position"]:
            raise PipelineError(f"scope position mismatch for included member: {path}")
    for path, item in excluded.items():
        if expected[path]["position"] != item["position"]:
            raise PipelineError(f"scope position mismatch for excluded member: {path}")

    retained = {
        str(item["path"]): item
        for item in acquisition.get("retained_files", [])
        if isinstance(item, dict)
    }
    missing_retained = sorted(set(retained) - set(expected))
    if missing_retained:
        raise PipelineError(
            "scope contracts an acquisition envelope without an explicit member disposition: "
            + ", ".join(missing_retained)
        )
    unknown_included = sorted(set(included) - set(retained))
    if unknown_included:
        raise PipelineError(
            "scope includes members absent from the retained acquisition: "
            + ", ".join(unknown_included)
        )
    for path, item in included.items():
        source_item = retained[path]
        if item["sha256"] != source_item["sha256"] or item["bytes"] != source_item["bytes"]:
            raise PipelineError(f"included member binding disagrees with acquisition: {path}")
        member_path = _require_file(root, path, field=f"scope.included_members[{path}]")
        if io_path(member_path).stat().st_size != item["bytes"] or sha256_file(member_path) != item["sha256"]:
            raise PipelineError(f"included member bytes or digest mismatch: {path}")

    source = record["source"]
    missing = set(source["missing_members"])
    unknown = set(source["unknown_members"])
    unavailable = missing | unknown
    if not unavailable <= set(expected):
        raise PipelineError(
            "source missing/unknown members must be within the declared expected envelope"
        )
    if not unavailable <= set(excluded):
        raise PipelineError(
            "source missing/unknown members must be explicitly excluded from acceptance"
        )
    if scope["kind"] in {"work", "edition"} and (excluded or unavailable):
        raise PipelineError(
            "whole-work or whole-edition acceptance cannot hide excluded or unavailable members"
        )
    if unavailable & set(included):
        raise PipelineError("an included member cannot also be missing or unknown")
    if unavailable & set(retained):
        raise PipelineError("a retained member cannot be missing or unknown")
    if missing & unknown:
        raise PipelineError("a source member cannot be both missing and unknown")


def _header_text(root: etree._Element, local_name: str, *, attr_type: str | None = None) -> str | None:
    values: list[str] = []
    for node in root.xpath(f".//tei:{local_name}", namespaces={"tei": TEI_NS}):
        if attr_type is not None and node.get("type") != attr_type:
            continue
        value = "".join(node.itertext()).strip()
        if value:
            values.append(value)
    unique = set(values)
    if len(unique) > 1:
        label = f" {attr_type}" if attr_type else ""
        raise PipelineError(f"candidate has conflicting TEI header {local_name}{label} values")
    return values[0] if values else None


def _tei_facts(path: Path, *, identity: Mapping[str, str] | None = None) -> tuple[etree._ElementTree, dict[str, Any]]:
    if identity == {"work_id": "catholic-encyclopedia-vol01", "textual_form_id": "catholic-encyclopedia-vol01-retained-en", "edition_id": "catholic-encyclopedia-vol01-retained-electronic", "acquisition_id": "catholic-encyclopedia-vol01-acquired-member-set"}:
        from .lib025_stream_header_facts import parse_bound_header
        header_tree, has_text = parse_bound_header(io_path(path), identity=identity)
        return _tei_facts_from_tree(header_tree, source_path=path, has_text=has_text)
    try:
        tree = etree.parse(str(io_path(path)))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"candidate TEI cannot be parsed: {path}") from exc
    return _tei_facts_from_tree(tree, source_path=path)


def _tei_facts_from_tree(tree: etree._ElementTree, *, source_path: Path, has_text: bool | None = None) -> tuple[etree._ElementTree, dict[str, Any]]:
    """Common header facts; exact work may supply fully observed text presence."""
    root = tree.getroot()
    root_name = etree.QName(root).localname
    if root_name not in {"TEI", "teiCorpus"} or etree.QName(root).namespace != TEI_NS:
        raise PipelineError(f"candidate is not a TEI P5 document: {source_path}")
    if root_name == "teiCorpus":
        children = list(root)
        if len(children) < 2 or children[0].tag != f"{{{TEI_NS}}}teiHeader" or any(node.tag != f"{{{TEI_NS}}}TEI" for node in children[1:]):
            raise PipelineError("accepted corpus requires one header and at least one ordered TEI member")
        if (root.text or '').strip() or any((node.tail or '').strip() for node in children):
            raise PipelineError("accepted corpus has text outside its declared members")
        for member in children[1:]:
            if [node.tag for node in member] != [f"{{{TEI_NS}}}teiHeader", f"{{{TEI_NS}}}text"]:
                raise PipelineError("accepted corpus member must retain its own header and text")
    headers = root.xpath("./tei:teiHeader", namespaces={"tei": TEI_NS})
    if len(headers) != 1:
        raise PipelineError("candidate must contain exactly one TEI header")
    header = headers[0]
    binding_kinds = {"work_id", "textual_form_id", "edition_id", "acquisition_id",
                     "source_sha256", "source_bytes", "source_kind", "representation_revision", "sha256"}
    marked = header.xpath(".//tei:bibl[@type='ocd-acceptance-binding']", namespaces={"tei": TEI_NS})
    if len(marked) > 1:
        raise PipelineError("candidate has multiple scoped acceptance bindings")
    scoped = marked
    if scoped:
        binding = scoped[0]
        source_desc = header.find(f"{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}sourceDesc")
        parent = binding.getparent()
        if parent is source_desc:
            pass
        elif (parent is not None and parent.tag == f"{{{TEI_NS}}}p"
              and parent.getparent() is source_desc and not parent.attrib
              and len(parent) == 1 and parent[0] is binding
              and not (parent.text or "").strip()
              and not (binding.tail or "").strip()
              and not (parent.tail or "").strip()):
            pass
        else:
            raise PipelineError("candidate has unsupported scoped acceptance binding location")
    else:
        for bibl in header.xpath("./tei:fileDesc/tei:sourceDesc/tei:p/tei:bibl", namespaces={"tei": TEI_NS}):
            if any(node.get("type") in binding_kinds - {"sha256"}
                   for node in bibl.xpath(".//tei:idno", namespaces={"tei": TEI_NS})):
                raise PipelineError("candidate has unmarked acceptance binding wrapper")
    binding_header = scoped[0] if scoped else header
    facts: dict[str, Any] = {}
    for node in header.xpath(".//tei:idno", namespaces={"tei": TEI_NS}):
        kind = node.get("type")
        if scoped and scoped[0] not in node.iterancestors():
            if kind in binding_kinds - {"sha256"}:
                raise PipelineError("candidate has acceptance identity outside scoped binding")
            continue
        if kind not in binding_kinds:
            # A source may legitimately list multiple STC or other catalog IDs.
            # Only our acceptance bindings are singleton facts.
            continue
        value = "".join(node.itertext()).strip()
        if kind and value:
            if kind in facts and facts[kind] != value:
                raise PipelineError(f"candidate has conflicting TEI header idno values: {kind}")
            facts[kind] = value
    ptrs = binding_header.xpath(".//tei:ptr[@target]" if scoped else ".//tei:sourceDesc//tei:ptr[@target]", namespaces={"tei": TEI_NS})
    if ptrs:
        targets = [str(node.get("target")) for node in ptrs]
        if len(set(targets)) > 1:
            raise PipelineError("candidate has conflicting TEI header sourceDesc pointers")
        facts["source_url"] = targets[0]
    for note_type in ("source-location", "source-scope"):
        if scoped and any(scoped[0] not in node.iterancestors() for node in header.xpath(".//tei:note[@type=$kind]", kind=note_type, namespaces={"tei": TEI_NS})):
            raise PipelineError("candidate has source binding note outside scoped binding")
        value = _header_text(binding_header, "note", attr_type=note_type)
        if value is not None:
            facts[note_type] = value
    changes = header.xpath("./tei:revisionDesc/tei:change", namespaces={"tei": TEI_NS})
    if not changes:
        raise PipelineError("candidate must contain a revisionDesc/change")
    revisions: list[dict[str, str]] = []
    for change in changes:
        revision_id = change.get(XML_ID)
        revision_date = change.get("when")
        revision_note = "".join(change.itertext()).strip()
        # Retained TEI can have historical changes using child dates and no IDs.
        # Only the explicitly bound integration revision must satisfy our contract.
        if revision_id != facts.get("representation_revision"):
            continue
        if not revision_id or not revision_date or not revision_note:
            raise PipelineError("candidate revision changes require xml:id, when, and note")
        revisions.append(
            {"id": revision_id, "date": revision_date, "note": revision_note}
        )
    facts["revision_changes"] = json.dumps(revisions, sort_keys=True)
    if has_text is False or (has_text is None and "text" not in facts and not root.xpath(".//tei:text", namespaces={"tei": TEI_NS})):
        raise PipelineError("candidate TEI has no text element")
    return tree, facts


def _beatitudes_oracle():
    """Load only the manifest-pinned Watson Beatitudes independent oracle."""
    import importlib.util

    oracle_path = SCHEMA_PATH.parents[2] / (
        "sources/structured-text/watson-beatitudes/watson_beatitudes_oracle.py"
    )
    if sha256_file(oracle_path) != BEATITUDES_ACCEPTANCE_ORACLE_SHA:
        raise PipelineError("Beatitudes oracle implementation differs")
    spec = importlib.util.spec_from_file_location("ocd_watson_beatitudes_oracle", oracle_path)
    if spec is None or spec.loader is None:
        raise PipelineError("Beatitudes oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


def _check_beatitudes_for_acceptance(
    root: Path,
    acquisition: Mapping[str, Any],
    candidate_path: Path,
    identity: Mapping[str, str],
    revision: Mapping[str, str],
) -> None:
    """Replay the exact oracle and require a revision-only TEI derivation."""
    from xml.sax.saxutils import escape, quoteattr

    from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate

    actual_identity = tuple(identity[key] for key in (
        "work_id", "textual_form_id", "edition_id", "acquisition_id"
    ))
    selection = acquisition.get("source_selection")
    retained = acquisition.get("retained_files")
    if (
        actual_identity != BEATITUDES_ACCEPTANCE_IDENTITY
        or acquisition.get("source_path") != BEATITUDES_ACCEPTANCE_SOURCE
        or acquisition.get("source_sha256") != BEATITUDES_ACCEPTANCE_SOURCE_SHA
        or not isinstance(selection, dict)
        or selection.get("selection_id") != BEATITUDES_ACCEPTANCE_SELECTION_ID
        or selection.get("member_path") != BEATITUDES_ACCEPTANCE_SOURCE
        or not isinstance(retained, list)
        or len(retained) != 1
        or not isinstance(retained[0], dict)
        or retained[0].get("path") != BEATITUDES_ACCEPTANCE_SOURCE
        or retained[0].get("sha256") != BEATITUDES_ACCEPTANCE_SOURCE_SHA
    ):
        raise PipelineError("Beatitudes acceptance lacks its exact route binding")

    repository_root = SCHEMA_PATH.parents[2]
    manifest_path = repository_root / BEATITUDES_ACCEPTANCE_MANIFEST
    staged_manifest = _fixture_path(
        root, BEATITUDES_ACCEPTANCE_MANIFEST, field="Beatitudes source manifest"
    )
    if (
        sha256_file(manifest_path) != BEATITUDES_ACCEPTANCE_MANIFEST_SHA
        or sha256_file(staged_manifest) != BEATITUDES_ACCEPTANCE_MANIFEST_SHA
    ):
        raise PipelineError("Beatitudes source manifest differs")
    try:
        manifest = SourceManifest.load(manifest_path, repository_root=repository_root)
    except (OSError, ValueError) as exc:
        raise PipelineError("Beatitudes source authority closure is invalid") from exc
    validator = manifest.record["validator"]
    if (
        manifest.record.get("work_id") != identity["work_id"]
        or validator.get("id") != BEATITUDES_ACCEPTANCE_ORACLE_ID
        or validator.get("implementation_sha256") != BEATITUDES_ACCEPTANCE_ORACLE_SHA
    ):
        raise PipelineError("Beatitudes oracle route differs")
    for authority_name in ("retained-source", "work", "acquisition"):
        authority = next(
            item for item in manifest.record["authorities"]
            if item["name"] == authority_name
        )
        canonical = manifest.authority_path(authority_name)
        staged = _evidence_path(
            root, authority["path"], field=f"Beatitudes {authority_name}"
        )
        if not io_path(staged).is_file() or sha256_file(staged) != sha256_file(canonical):
            raise PipelineError(f"Beatitudes {authority_name} differs from source manifest")

    package_path = _fixture_path(root, BEATITUDES_ACCEPTANCE_EVIDENCE, field="Beatitudes package")
    try:
        package = CandidatePackage.load(package_path)
        if package.sha256 != BEATITUDES_ACCEPTANCE_PACKAGE_SHA:
            raise PipelineError("Beatitudes package manifest differs")
        validate(manifest, package, _beatitudes_oracle())
    except (OSError, ValueError) as exc:
        raise PipelineError("Beatitudes independent oracle rejected the package") from exc

    historical_manifest = _fixture_path(
        root, BEATITUDES_HISTORICAL_MANIFEST, field="historical Beatitudes manifest"
    )
    if sha256_file(historical_manifest) != BEATITUDES_HISTORICAL_MANIFEST_SHA:
        raise PipelineError("historical Beatitudes manifest differs")
    historical_package_path = _fixture_path(
        root, BEATITUDES_HISTORICAL_EVIDENCE, field="historical Beatitudes package"
    )
    historical_package = CandidatePackage.load(historical_package_path)
    historical_validation_path = _fixture_path(
        root, BEATITUDES_HISTORICAL_VALIDATION, field="historical Beatitudes validation"
    )
    historical_validation = load_json(historical_validation_path)
    historical_acceptance_path = _fixture_path(
        root, BEATITUDES_HISTORICAL_ACCEPTANCE, field="historical Beatitudes acceptance"
    )
    historical_acceptance = load_json(historical_acceptance_path)
    if (
        historical_package.sha256 != BEATITUDES_HISTORICAL_PACKAGE_SHA
        or historical_package.manifest.get("source_manifest", {}).get("sha256")
        != BEATITUDES_HISTORICAL_MANIFEST_SHA
        or sha256_file(historical_validation_path) != BEATITUDES_HISTORICAL_VALIDATION_SHA
        or historical_validation.get("status") != "pass"
        or historical_validation.get("findings") != []
        or historical_validation.get("candidate_sha256") != BEATITUDES_HISTORICAL_PACKAGE_SHA
        or historical_validation.get("source_manifest_sha256")
        != BEATITUDES_HISTORICAL_MANIFEST_SHA
        or sha256_file(historical_acceptance_path)
        != BEATITUDES_HISTORICAL_ACCEPTANCE_SHA
        or historical_acceptance.get("promotion", {}).get("master", {}).get("sha256")
        != BEATITUDES_INSTALLED_MASTER_SHA
        or package.member_names != historical_package.member_names
        or any(
            package.member_bytes(name) != historical_package.member_bytes(name)
            for name in package.member_names if name != "manifest.json"
        )
    ):
        raise PipelineError("Beatitudes historical-to-current candidate binding differs")

    original = package.member_bytes("content.tei.xml")
    revision_id = revision["id"]
    revision_date = revision["date"]
    revision_note = revision["note"]
    identity_note = (
        '<idno type="representation_revision">' + escape(revision_id) + '</idno>'
    ).encode("utf-8")
    change = (
        '<revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xml:id='
        + quoteattr(revision_id) + " when=" + quoteattr(revision_date)
        + ">" + escape(revision_note) + "</change></revisionDesc>"
    ).encode("utf-8")
    if original.count(b"</bibl>") != 1 or original.count(b"</teiHeader>") != 1:
        raise PipelineError("Beatitudes original TEI header is ambiguous")
    expected = original.replace(b"</bibl>", identity_note + b"</bibl>", 1)
    expected = expected.replace(b"</teiHeader>", change + b"</teiHeader>", 1)
    if io_path(candidate_path).read_bytes() != expected:
        raise PipelineError("Beatitudes candidate differs beyond the exact revision binding")


def _check_divine_contentment_for_acceptance(
    root: Path,
    acquisition: Mapping[str, Any],
    candidate_path: Path,
    identity: Mapping[str, str],
    revision: Mapping[str, str],
) -> None:
    """Replay the exact source-bound oracle and verify a header-only handoff."""
    from xml.sax.saxutils import escape, quoteattr

    from build.tei.watson_divine_contentment_oracle import _oracle
    from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate

    actual_identity = tuple(identity[key] for key in (
        "work_id", "textual_form_id", "edition_id", "acquisition_id"
    ))
    selection = acquisition.get("source_selection")
    retained = acquisition.get("retained_files")
    if (
        actual_identity != DIVINE_CONTENTMENT_IDENTITY
        or acquisition.get("source_path") != DIVINE_CONTENTMENT_SOURCE
        or acquisition.get("source_sha256") != DIVINE_CONTENTMENT_SOURCE_SHA
        or not isinstance(selection, dict)
        or selection.get("selection_id") != DIVINE_CONTENTMENT_SELECTION_ID
        or selection.get("member_path") != DIVINE_CONTENTMENT_SOURCE
        or not isinstance(retained, list)
        or len(retained) != 1
        or not isinstance(retained[0], dict)
        or retained[0].get("path") != DIVINE_CONTENTMENT_SOURCE
        or retained[0].get("sha256") != DIVINE_CONTENTMENT_SOURCE_SHA
    ):
        raise PipelineError("Divine Contentment acceptance lacks its exact route binding")

    repository_root = SCHEMA_PATH.parents[2]
    manifest_path = repository_root / DIVINE_CONTENTMENT_MANIFEST
    staged_manifest = _fixture_path(
        root, DIVINE_CONTENTMENT_MANIFEST, field="Divine Contentment source manifest"
    )
    if (
        sha256_file(manifest_path) != DIVINE_CONTENTMENT_MANIFEST_SHA
        or sha256_file(staged_manifest) != DIVINE_CONTENTMENT_MANIFEST_SHA
    ):
        raise PipelineError("Divine Contentment source manifest differs")
    try:
        manifest = SourceManifest.load(manifest_path, repository_root=repository_root)
    except (OSError, ValueError) as exc:
        raise PipelineError("Divine Contentment source authority closure is invalid") from exc
    validator = manifest.record["validator"]
    if (
        manifest.record.get("work_id") != identity["work_id"]
        or validator.get("id") != DIVINE_CONTENTMENT_ORACLE_ID
        or validator.get("implementation_sha256") != DIVINE_CONTENTMENT_ORACLE_SHA
    ):
        raise PipelineError("Divine Contentment oracle route differs")
    for authority_name in ("retained-source", "work", "acquisition"):
        authority = next(
            item for item in manifest.record["authorities"]
            if item["name"] == authority_name
        )
        canonical = manifest.authority_path(authority_name)
        staged = _evidence_path(
            root, authority["path"], field=f"Divine Contentment {authority_name}"
        )
        if not io_path(staged).is_file() or sha256_file(staged) != sha256_file(canonical):
            raise PipelineError(f"Divine Contentment {authority_name} differs from source manifest")

    package_path = _fixture_path(root, DIVINE_CONTENTMENT_EVIDENCE, field="Divine Contentment package")
    try:
        package = CandidatePackage.load(package_path)
        if package.sha256 != DIVINE_CONTENTMENT_PACKAGE_SHA:
            raise PipelineError("Divine Contentment package manifest differs")
        validate(manifest, package, _oracle)
    except (OSError, ValueError) as exc:
        raise PipelineError("Divine Contentment independent oracle rejected the package") from exc
    current_validation_path = _fixture_path(
        root,
        "library/works/watson-divine-contentment/integration/runtime-proof-20261025-main/current-candidate/validation.json",
        field="current Divine Contentment validation",
    )
    current_validation = _object_file(current_validation_path, field="current Divine Contentment validation")
    if (
        sha256_file(current_validation_path) != DIVINE_CONTENTMENT_VALIDATION_SHA
        or current_validation.get("status") != "pass"
        or current_validation.get("findings") != []
        or current_validation.get("candidate_sha256") != DIVINE_CONTENTMENT_PACKAGE_SHA
        or current_validation.get("source_manifest_sha256") != DIVINE_CONTENTMENT_MANIFEST_SHA
    ):
        raise PipelineError("Divine Contentment current validation sidecar differs")

    historical_manifest = _fixture_path(
        root, DIVINE_CONTENTMENT_HISTORICAL_MANIFEST,
        field="historical Divine Contentment manifest",
    )
    historical_package_path = _fixture_path(
        root, DIVINE_CONTENTMENT_HISTORICAL_EVIDENCE,
        field="historical Divine Contentment package",
    )
    historical_validation_path = _fixture_path(
        root, DIVINE_CONTENTMENT_HISTORICAL_VALIDATION,
        field="historical Divine Contentment validation",
    )
    historical_acceptance = _fixture_path(
        root, DIVINE_CONTENTMENT_HISTORICAL_ACCEPTANCE,
        field="historical Divine Contentment acceptance",
    )
    historical_cvw = _fixture_path(
        root,
        "library/works/watson-divine-contentment/integration/"
        "ccel-thml-agent-handoff/inputs/cvw/session-receipt.json",
        field="historical Divine Contentment CVW receipt",
    )
    historical_package = CandidatePackage.load(historical_package_path)
    historical_validation = _object_file(historical_validation_path, field="historical Divine Contentment validation")
    if (
        sha256_file(historical_manifest) != DIVINE_CONTENTMENT_HISTORICAL_MANIFEST_SHA
        or historical_package.sha256 != DIVINE_CONTENTMENT_HISTORICAL_PACKAGE_SHA
        or historical_package.manifest.get("source_manifest", {}).get("sha256")
        != DIVINE_CONTENTMENT_HISTORICAL_MANIFEST_SHA
        or sha256_file(historical_validation_path) != DIVINE_CONTENTMENT_HISTORICAL_VALIDATION_SHA
        or historical_validation.get("status") != "pass"
        or historical_validation.get("candidate_sha256") != DIVINE_CONTENTMENT_HISTORICAL_PACKAGE_SHA
        or historical_validation.get("source_manifest_sha256") != DIVINE_CONTENTMENT_HISTORICAL_MANIFEST_SHA
        or sha256_file(historical_acceptance) != DIVINE_CONTENTMENT_HISTORICAL_ACCEPTANCE_SHA
        or sha256_file(historical_cvw) != DIVINE_CONTENTMENT_HISTORICAL_CVW_SHA
        or sha256_file(candidate_path) != DIVINE_CONTENTMENT_INSTALLED_MASTER_SHA
        or package.member_names != historical_package.member_names
    ):
        raise PipelineError("Divine Contentment historical evidence differs")
    for member_name in package.member_names:
        if member_name != "manifest.json" and package.member_bytes(member_name) != historical_package.member_bytes(member_name):
            raise PipelineError(f"Divine Contentment reviewed package member differs: {member_name}")

    original = package.member_bytes("content.tei.xml")
    revision_id = revision["id"]
    revision_date = revision["date"]
    revision_note = revision["note"]
    identity_note = (
        '<idno type="representation_revision">' + escape(revision_id) + '</idno>'
    ).encode("utf-8")
    change = (
        '<revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xml:id='
        + quoteattr(revision_id) + " when=" + quoteattr(revision_date)
        + ">" + escape(revision_note) + "</change></revisionDesc>"
    ).encode("utf-8")
    if original.count(b"</bibl>") != 1 or original.count(b"</teiHeader>") != 1:
        raise PipelineError("Divine Contentment original TEI header is ambiguous")
    expected = original.replace(b"</bibl>", identity_note + b"</bibl>", 1)
    expected = expected.replace(b"</teiHeader>", change + b"</teiHeader>", 1)
    if io_path(candidate_path).read_bytes() != expected:
        raise PipelineError("Divine Contentment candidate differs beyond the exact revision binding")


def _check_selected_thml_for_acceptance(
    root: Path,
    acquisition: Mapping[str, Any],
    work: Mapping[str, Any],
    candidate_path: Path,
    identity: Mapping[str, str],
) -> None:
    """Validate selected ThML through its exact route checker."""
    from ocd_kernel.tei.selected_thml_check import check_selected_thml

    if identity["work_id"] != WATSON_ACCEPTANCE_IDENTITY[0]:
        check_selected_thml(root, dict(acquisition), dict(work), candidate_path)
        return

    actual_identity = tuple(identity[key] for key in (
        "work_id", "textual_form_id", "edition_id", "acquisition_id"
    ))
    selection = acquisition.get("source_selection")
    retained = acquisition.get("retained_files")
    if (
        actual_identity != WATSON_ACCEPTANCE_IDENTITY
        or not isinstance(selection, dict)
        or selection.get("selection_id") != WATSON_ACCEPTANCE_SELECTION_ID
        or not isinstance(retained, list)
        or len(retained) != 1
        or not isinstance(retained[0], dict)
        or retained[0].get("sha256") != WATSON_ACCEPTANCE_SOURCE_SHA
        or retained[0].get("path") != selection.get("member_path")
    ):
        raise PipelineError("Watson acceptance route lacks its exact acquisition binding")

    source_path = resolve_repo_path(root, retained[0]["path"])
    if sha256_file(source_path) != WATSON_ACCEPTANCE_SOURCE_SHA:
        raise PipelineError("Watson acceptance retained source bytes differ")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, recover=False,
        remove_comments=False, remove_pis=False,
    )
    try:
        source_root = etree.parse(str(io_path(source_path)), parser).getroot()
        actual = etree.parse(str(io_path(candidate_path)), parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError("Watson acceptance source or candidate XML is invalid") from exc
    units = selection.get("units")
    if not isinstance(units, list) or not units:
        raise PipelineError("Watson acceptance source selection is empty or invalid")
    selected = []
    for unit in units:
        if not isinstance(unit, dict) or not isinstance(unit.get("native_id"), str):
            raise PipelineError("Watson acceptance selection unit is invalid")
        matches = source_root.xpath(
            "/ThML/ThML.body/div1[@id=$native_id]", native_id=unit["native_id"]
        )
        if len(matches) != 1:
            raise PipelineError("Watson acceptance selected source unit is missing or ambiguous")
        selected.append(matches[0])
    if not selected:
        raise PipelineError("Watson acceptance source selection is empty")

    mismatches = []
    position = 0
    for unit in selected:
        for node in unit.iter():
            if not isinstance(node.tag, str):
                continue
            position += 1
            title = node.get("title")
            if not node.tag.startswith("div") or not title:
                continue
            headings = [
                child for child in node
                if isinstance(child.tag, str) and child.tag in {"h1", "h2", "h3"}
            ]
            if headings and not any(
                " ".join("".join(heading.itertext()).split()).casefold()
                == " ".join(title.split()).casefold()
                for heading in headings
            ):
                mismatches.append((f"src-{position}", title))
    if len(mismatches) != WATSON_ACCEPTANCE_SUPPRESSED_TITLES:
        raise PipelineError("Watson source-derived navigation title count differs")

    validation_view = deepcopy(actual)
    for target_id, title in mismatches:
        actual_targets = actual.xpath(
            "//*[@xml:id=$target_id]", namespaces={"xml": XML_NS}, target_id=target_id
        )
        view_targets = validation_view.xpath(
            "//*[@xml:id=$target_id]", namespaces={"xml": XML_NS}, target_id=target_id
        )
        if len(actual_targets) != 1 or len(view_targets) != 1:
            raise PipelineError(f"Watson division target is missing or ambiguous: {target_id}")
        if any(
            child.tag == f"{{{TEI_NS}}}head"
            and child.get(XML_ID) is None
            and child.get("type") is None
            and child.text == title
            for child in actual_targets[0]
        ):
            raise PipelineError(f"Watson navigation title is duplicated: {target_id}")
        synthetic = etree.Element(f"{{{TEI_NS}}}head")
        synthetic.text = title
        view_targets[0].insert(0, synthetic)

    with tempfile.TemporaryDirectory(prefix="ocd-watson-acceptance-check-") as scratch:
        view_path = Path(scratch) / "generic-validation-view.tei.xml"
        io_path(view_path).write_bytes(etree.tostring(
            validation_view, encoding="utf-8", xml_declaration=True
        ))
        check_selected_thml(root, dict(acquisition), dict(work), view_path)


def _check_runtime_supplement(record: Mapping[str, Any], root: Path, work_id: str) -> None:
    """Bind current oracle evidence to the unchanged historical acceptance."""
    path = _fixture_path(
        root, f"sources/structured-text/{work_id}/runtime-supplement-20261025-main.json",
        field="Watson runtime supplement",
    )
    if sha256_file(path) != RUNTIME_SUPPLEMENTS[work_id]:
        raise PipelineError("Watson runtime supplement differs")
    supplement = _object_file(path, field="Watson runtime supplement")
    if supplement.get("contract") != "ocd-watson-runtime-supplement-v1" or supplement.get("work_id") != work_id:
        raise PipelineError("Watson runtime supplement identity differs")
    accepted = _binding(root, supplement["acceptance"], field="runtime acceptance", fixture_only=True)
    if load_acceptance(accepted) != record:
        raise PipelineError("Watson runtime supplement binds another acceptance")
    for binding in supplement["bindings"]:
        _binding(root, binding, field="runtime preserved binding", fixture_only=True)
    _binding(root, supplement["validation"], field="runtime oracle validation", fixture_only=True)


def _validate_tei(
    record: Mapping[str, Any],
    root: Path,
    candidate_path: Path,
    identity: Mapping[str, str],
    acquisition: Mapping[str, Any],
) -> None:
    if identity["work_id"] in RUNTIME_SUPPLEMENTS:
        _check_runtime_supplement(record, root, identity["work_id"])
    if identity["work_id"] == DIVINE_CONTENTMENT_IDENTITY[0]:
        _check_divine_contentment_for_acceptance(
            root, acquisition, candidate_path, identity, record["representation_revision"]
        )
    elif identity["work_id"] == BEATITUDES_ACCEPTANCE_IDENTITY[0]:
        _check_beatitudes_for_acceptance(
            root, acquisition, candidate_path, identity, record["representation_revision"]
        )
    elif acquisition.get("source_selection") is not None or identity["work_id"] == WATSON_ACCEPTANCE_IDENTITY[0]:
        from ocd_kernel.library.identities import load_work

        work = load_work(root / "library" / "works" / identity["work_id"] / "work.json")
        _check_selected_thml_for_acceptance(root, acquisition, work, candidate_path, identity)
    _tree, facts = _tei_facts(candidate_path, identity=identity)
    for key, expected in identity.items():
        if facts.get(key) != expected:
            raise PipelineError(f"candidate TEI {key} does not bind acceptance identity")
    source = record["source"]
    if facts.get('source_kind') != source.get('source_kind'):
        raise PipelineError('candidate TEI source kind does not bind acquisition')
    if facts.get("source_url") != acquisition.get("url"):
        raise PipelineError("candidate TEI source URL does not bind acquisition")
    if facts.get("source_sha256") != source["source_sha256"]:
        raise PipelineError("candidate TEI source SHA-256 does not bind acquisition")
    if facts.get("source_bytes") != str(source["source_bytes"]):
        raise PipelineError("candidate TEI source byte count does not bind acquisition")
    if facts.get("source-location") != source["source_path"]:
        raise PipelineError("candidate TEI source location does not bind acquisition")
    if facts.get("source-scope") != record["scope"]["declared"]:
        raise PipelineError("candidate TEI source scope does not bind declared acceptance scope")
    revision = record["representation_revision"]
    revisions = json.loads(facts["revision_changes"])
    matching_revisions = [
        item
        for item in revisions
        if item == {
            "id": revision["id"],
            "date": revision["date"],
            "note": revision["note"],
        }
    ]
    if facts.get("representation_revision") != revision["id"] or len(matching_revisions) != 1:
        raise PipelineError("candidate TEI revision history is detached from acceptance")
    included = record["scope"]["included_members"]
    if len(included) == 1 and facts.get("sha256") != included[0]["sha256"]:
        raise PipelineError("candidate TEI retained-member hash does not bind source accounting")
    # Keep the path argument in the signature so callers can use the same
    # routine for future source-local diagnostics without introducing a second
    # source authority.
    _ = root


def _check_document_identity(
    path: Path,
    identity: Mapping[str, str],
    *,
    field: str,
    candidate: Mapping[str, Any] | None = None,
    declared_scope: str | None = None,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    document = _object_file(path, field=field)
    _same_identity(document.get("identity"), identity, field=field)
    if candidate is not None:
        if "candidate" not in document:
            raise PipelineError(f"{field} candidate binding is missing")
        value = document["candidate"]
        if (
            not isinstance(value, dict)
            or value.get("path") != candidate["path"]
            or value.get("bytes") != candidate["bytes"]
            or value.get("sha256") != candidate["sha256"]
        ):
            raise PipelineError(f"{field} candidate binding is stale")
    if declared_scope is not None:
        if "scope" not in document:
            raise PipelineError(f"{field} scope binding is missing")
        value = document["scope"]
        if isinstance(value, dict):
            value = value.get("declared")
        if value != declared_scope:
            raise PipelineError(f"{field} scope binding is stale")
    if source is not None:
        value = document.get("source")
        if not isinstance(value, dict):
            raise PipelineError(f"{field} source binding is missing")
        expected = {
            "source_path": source["source_path"],
            "source_sha256": source["source_sha256"],
            "source_bytes": source["source_bytes"],
            "source_scope": source["source_scope"],
        }
        if 'source_kind' in source:
            expected['source_kind'] = source['source_kind']
        if value != expected:
            raise PipelineError(f"{field} source binding is stale")
    return document


def _validate_proof_documents(
    record: Mapping[str, Any],
    root: Path,
    identity: Mapping[str, str],
    *,
    candidate: Mapping[str, Any],
) -> None:
    technical = record["technical"]
    declared_scope = record["scope"]["declared"]
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = technical[name]
        if proof["status"] != "pass" or proof["exit_code"] != 0:
            raise PipelineError(f"technical {name} proof is not a passing authoritative result")
        path = _binding(root, proof, field=f"technical.{name}", fixture_only=False)
        document = _check_document_identity(
            path,
            identity,
            field=f"technical.{name}",
            candidate=candidate,
            declared_scope=declared_scope,
            source=record["source"],
        )
        if document.get("status") != proof["status"]:
            raise PipelineError(f"technical {name} document status is stale")
        if document.get("command") != proof["command"]:
            raise PipelineError(f"technical {name} document command is stale")
        if document.get("exit_code") != proof["exit_code"] or document.get("exit_code") != 0:
            raise PipelineError(f"technical {name} document exit code is not authoritative")
    accounting = _object_file(
        _evidence_path(root, technical["accounting"]["path"], field="technical.accounting.path"),
        field="technical.accounting",
    )
    accepted_scope = accounting.get("accepted_scope")
    expected_scope = {
        "kind": record["scope"]["kind"],
        "declared": record["scope"]["declared"],
    }
    if accepted_scope != expected_scope:
        raise PipelineError("technical accounting accepted_scope does not bind declared scope")
    for key in (
        "expected_members",
        "included_members",
        "excluded_members",
        "missing_members",
        "unknown_members",
    ):
        if key not in accounting:
            raise PipelineError(f"technical accounting {key} binding is missing")
        expected = record["scope"].get(key, record["source"].get(key))
        if accounting[key] != expected:
            raise PipelineError(f"technical accounting {key} does not match declared scope")

    for actor_name in ("producer", "checker"):
        actor = technical[actor_name]
        if "path" in actor:
            _binding(root, actor["path"], field=f"technical.{actor_name}.path", fixture_only=False)


def _validate_review_document(
    record: Mapping[str, Any], root: Path, identity: Mapping[str, str], candidate: Mapping[str, Any]
) -> None:
    review = record["review"]
    path = _binding(root, review["report"], field="review.report", fixture_only=False)
    document = _check_document_identity(
        path,
        identity,
        field="review.report",
        candidate=candidate,
        declared_scope=record["scope"]["declared"],
        source=record["source"],
    )
    if document.get("reviewer") != review["reviewer"]:
        raise PipelineError("review report reviewer binding is stale")
    if document.get("reviewed_at") != review["reviewed_at"]:
        raise PipelineError("review report time binding is stale")
    if "coverage" not in document:
        raise PipelineError("review.report coverage binding is missing")
    if document["coverage"] != review["coverage"]:
        raise PipelineError("review report coverage binding is stale")
    coverage = review["coverage"]
    if coverage["declared"] != record["scope"]["declared"]:
        raise PipelineError("review coverage declared scope is stale")
    reached = set(coverage["reached"])
    inspected = set(coverage["inspected"])
    unreviewed = set(coverage["unreviewed"])
    def within_reached(locus: str) -> bool:
        return any(locus == parent or locus.startswith(parent.rstrip("/") + "/") for parent in reached)

    def overlaps(left: str, right: str) -> bool:
        return (
            left == right
            or left.startswith(right.rstrip("/") + "/")
            or right.startswith(left.rstrip("/") + "/")
        )

    if not all(within_reached(locus) for locus in inspected):
        raise PipelineError("review coverage inspected loci must be within reached loci")
    if any(overlaps(left, right) for left in inspected for right in unreviewed):
        raise PipelineError("review coverage inspected loci cannot be unreviewed")
    for key in ("source_quality_uncertainty", "discrepancies", "unreviewed_residuals"):
        if key not in document:
            raise PipelineError(f"review.report {key} binding is missing")
        if document[key] != review[key]:
            raise PipelineError(f"review report {key} binding is stale")
    if coverage["status"] == "partial" and not (
        coverage["unreviewed"] or review["unreviewed_residuals"]
    ):
        raise PipelineError("partial visual review must name its unreviewed residuals")
    if coverage["status"] == "complete" and coverage["unreviewed"]:
        raise PipelineError("complete visual review cannot carry unreviewed loci")


def _validate_source_documents(
    record: Mapping[str, Any], root: Path, identity: Mapping[str, str], acquisition_path: Path
) -> None:
    source = record["source"]
    source_manifest = _binding(root, source["source_manifest"], field="source.source_manifest", fixture_only=True)
    if source_manifest != resolve_path(acquisition_path):
        raise PipelineError("source manifest does not bind the selected acquisition")
    accounting = _binding(root, source["accounting"], field="source.accounting", fixture_only=False)
    document = _check_document_identity(
        accounting,
        identity,
        field="source.accounting",
        declared_scope=source["source_scope"],
        source=source,
    )
    for key in (
        "expected_members",
        "included_members",
        "excluded_members",
        "missing_members",
        "unknown_members",
    ):
        if key not in document:
            raise PipelineError(f"source.accounting {key} binding is missing")
        expected = record["scope"].get(key, source.get(key))
        if document[key] != expected:
            raise PipelineError(f"source.accounting {key} does not match declared scope")
    expected_scope = {
        "kind": record["scope"]["kind"],
        "declared": record["scope"]["declared"],
    }
    if document.get("accepted_scope") != expected_scope:
        raise PipelineError("source.accounting accepted_scope does not bind declared scope")
    if document.get("source_sha256") != source["source_sha256"]:
        raise PipelineError("source accounting source hash is stale")
    if document.get("source_bytes") != source["source_bytes"]:
        raise PipelineError("source accounting source byte count is stale")


def _validate_decision(record: Mapping[str, Any], root: Path) -> None:
    decision = record["decision"]
    blockers = decision["blockers"]
    for blocker in blockers:
        for index, evidence in enumerate(blocker["evidence"]):
            _binding(
                root,
                evidence,
                field=f"decision.blockers[{blocker['id']}].evidence[{index}]",
                fixture_only=False,
            )
    agent = decision["agent_assessment"]
    human = decision["human_decision"]
    agent_status = agent["status"]
    human_status = human["status"]
    if agent_status == "accepted" and agent.get("supported_scope") != record["scope"]["declared"]:
        raise PipelineError("accepted agent assessment supported_scope does not bind declared scope")
    if human_status != "not-recorded":
        for key in ("actor", "decided_at", "scope", "note"):
            if not human.get(key):
                raise PipelineError(f"recorded human decision requires {key}")
        if human_status == "accepted" and human["scope"] != record["scope"]["declared"]:
            raise PipelineError("recorded human decision scope does not bind declared scope")
    if agent_status == "accepted" and human_status in {"rejected", "blocked"}:
        raise PipelineError(
            "human rejection or block conflicts with the accepted agent assessment"
        )
    if blockers and (agent_status == "accepted" or human_status == "accepted"):
        raise PipelineError("recorded acceptance blockers cannot accompany an accepted decision")
    if record["promotion"]["status"] == "promoted" and not (
        agent_status == "accepted" or human_status == "accepted"
    ):
        raise PipelineError("promoted master requires an accepted agent or human decision")


def _canonical_paths(
    root: Path,
    identity: Mapping[str, str],
    *,
    discovered_works: Sequence[Work] | None = None,
    scoped: bool = False,
) -> tuple[Path, Path, Path]:
    if discovered_works is None:
        work, edition = edition_by_id(root, identity["edition_id"], work_id=identity["work_id"])
    else:
        # The caller has already validated either a complete library snapshot
        # or the exact work scope used by a single-work transaction.
        edition_id = safe_identifier(identity["edition_id"], field="edition_id")
        matches = [
            (item, edition)
            for item in discovered_works
            for edition in item.editions
            if edition.edition_id == edition_id
        ]
        if not matches:
            raise PipelineError(f"edition not found: {edition_id}")
        if len(matches) > 1:
            raise PipelineError(f"edition_id is ambiguous: {edition_id}")
        work, edition = matches[0]
    if work.work_id != identity["work_id"] or edition.textual_form_id != identity["textual_form_id"]:
        raise PipelineError("acceptance identity does not identify the declared edition")
    if discovered_works is not None:
        expected_work = root / "library" / "works" / identity["work_id"] / "work.json"
        expected_master = (
            expected_work.parent / "forms" / identity["textual_form_id"]
            / "editions" / identity["edition_id"] / "master.tei.xml"
        )
        if resolve_path(work.path) != resolve_path(expected_work) or resolve_path(edition.path) != resolve_path(expected_master):
            raise PipelineError("discovered edition does not bind the selected library root")
    edition_root = edition.path.parent
    if scoped:
        edition_root = edition_root / "scopes" / safe_identifier(
            identity["acquisition_id"], field="acquisition_id"
        )
    master_path = edition_root / "master.tei.xml"
    acceptance_path = edition_root / "acceptance.json"
    state_path = root / "library" / "works" / identity["work_id"] / "state.json"
    return master_path, acceptance_path, state_path


def validate_acceptance(path: Path, *, root: Path) -> dict[str, Any]:
    """Validate one acceptance record and all of its bound evidence."""

    return _validate_acceptance(path, root=root, discovered_works=None)


def _validate_acceptance_for_views(
    path: Path,
    *,
    root: Path,
    discovered_works: Sequence[Work],
) -> dict[str, Any]:
    """Reuse discover_library(root) from this view build only.

    The caller must have just run the canonical validating discovery for this
    exact root. This internal path retains the ordinary evidence and identity
    checks while avoiding one full discovery per acceptance.
    """

    return _validate_acceptance(path, root=root, discovered_works=discovered_works)


def _validate_acceptance_for_work(
    path: Path, *, root: Path, work_id: str
) -> dict[str, Any]:
    """Validate one acceptance against its complete work, without scanning siblings.

    This preserves per-work identity, edition, acquisition, and evidence
    checks after an atomic install. It deliberately does not establish global
    edition-ID uniqueness; corpus and release validation own that broader gate.
    """

    work = discover_work(root, work_id)
    return _validate_acceptance(path, root=root, discovered_works=(work,))


def _validate_acceptance(
    path: Path,
    *,
    root: Path,
    discovered_works: Sequence[Work] | None,
) -> dict[str, Any]:

    path = resolve_path(Path(path))
    root = resolve_path(Path(root))
    record = load_acceptance(path)
    identity = _identity(record)
    scoped = path.parent.name == identity["acquisition_id"] and path.parent.parent.name == "scopes"
    master_path, canonical_acceptance, state_path = _canonical_paths(
        root, identity, discovered_works=discovered_works, scoped=scoped
    )
    if path != resolve_path(canonical_acceptance):
        raise PipelineError(
            f"acceptance record must live beside its edition master: {path} != {canonical_acceptance}"
        )
    candidate_binding = record["technical"]["candidate"]
    candidate_path = _binding(root, candidate_binding, field="technical.candidate", fixture_only=True)
    if resolve_path(candidate_path) == resolve_path(master_path):
        raise PipelineError("candidate TEI cannot masquerade as the canonical accepted master")
    acquisition_path, acquisition = acquisition_for_edition(
        root,
        identity["work_id"],
        identity["edition_id"],
        acquisition_id=identity["acquisition_id"],
    )
    if acquisition["edition_id"] != identity["edition_id"]:
        raise PipelineError("acceptance acquisition does not bind edition")
    source = record["source"]
    acquisition_source = _source_binding(acquisition, context=str(acquisition_path))
    for key, expected in acquisition_source.items():
        if source[key] != expected:
            raise PipelineError(f"acceptance source {key} does not bind acquisition")
    source_manifest = source["source_manifest"]["path"]
    if _fixture_path(root, source_manifest, field="source.source_manifest.path") != resolve_path(acquisition_path):
        raise PipelineError("acceptance source manifest path does not bind acquisition")
    _validate_scope(record, acquisition, root)
    _validate_source_documents(record, root, identity, acquisition_path)
    _validate_tei(record, root, candidate_path, identity, acquisition)
    _validate_proof_documents(record, root, identity, candidate=candidate_binding)
    _validate_review_document(record, root, identity, candidate_binding)
    _validate_decision(record, root)

    promotion = record["promotion"]
    expected_master_reference = _relative(root, master_path, field="promotion.master.path")
    if promotion["master"]["path"] != expected_master_reference:
        raise PipelineError("promotion master path does not identify the edition master")
    expected_state_reference = _relative(root, state_path, field="promotion.state_path")
    if promotion["state_path"] != expected_state_reference:
        raise PipelineError("promotion state path does not identify the work state")
    if promotion["master"]["sha256"] != candidate_binding["sha256"] or promotion["master"]["bytes"] != candidate_binding["bytes"]:
        raise PipelineError("promotion master binding does not match candidate TEI")
    if promotion["status"] == "promoted":
        master_binding = _binding(root, promotion["master"], field="promotion.master", fixture_only=True)
        if master_binding != resolve_path(master_path):
            raise PipelineError("promotion master binding resolved to the wrong path")
        validate_state(state_path, root=root)
        state = load_json(state_path)
        target = next((item for item in state["targets"] if item.get("target_id") == identity["edition_id"]), None)
        if not isinstance(target, dict) or target.get("stage") != "accepted":
            raise PipelineError("promoted acceptance does not update edition state to accepted")
        acceptance_reference = _relative(root, path, field="acceptance path")
        if promotion["master"]["path"] not in target.get("evidence", []) or acceptance_reference not in target.get("evidence", []):
            raise PipelineError("promoted state does not bind both master and acceptance record")
    return record


def build_acceptance_record(
    root: Path,
    *,
    identity: Mapping[str, str],
    candidate_path: str | Path,
    source_accounting_path: str | Path,
    scope: Mapping[str, Any],
    technical: Mapping[str, Mapping[str, Any]],
    review: Mapping[str, Any],
    representation_revision: Mapping[str, str],
    decision: Mapping[str, Any],
    acceptance_id: str | None = None,
    promotion_status: str = "pending",
    missing_members: Sequence[str] = (),
    unknown_members: Sequence[str] = (),
    scoped: bool = False,
) -> dict[str, Any]:
    """Build a normalized acceptance record from selected evidence files.

    ``technical`` supplies six proof entries keyed by validation, accounting,
    fidelity, reproducibility, schema, and closure. Each entry contains a
    ``path``, ``status``, ``command``, and ``exit_code``; this function seals
    its bytes and digest. ``review`` supplies ``report_path``, reviewer fields,
    coverage, and optional uncertainty/discrepancy lists.
    """

    root = resolve_path(Path(root))
    identity_value = {
        key: safe_identifier(str(identity[key]), field=key)
        for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id")
    }
    work, edition = edition_by_id(root, identity_value["edition_id"], work_id=identity_value["work_id"])
    if work.work_id != identity_value["work_id"] or edition.textual_form_id != identity_value["textual_form_id"]:
        raise PipelineError("build identity does not identify the declared edition")
    acquisition_path, acquisition = acquisition_for_edition(
        root,
        identity_value["work_id"],
        identity_value["edition_id"],
        acquisition_id=identity_value["acquisition_id"],
    )
    acquisition_source = _source_binding(acquisition, context=str(acquisition_path))
    for name in ("producer", "checker", "shared_assumptions", "independent_corroboration"):
        if name not in technical:
            raise PipelineError(f"technical acceptance evidence is missing {name}")
    for name in ("producer", "checker"):
        if not isinstance(technical[name], Mapping):
            raise PipelineError(f"technical acceptance evidence {name} must be an object")
    if not isinstance(decision, Mapping):
        raise PipelineError("acceptance decision must be supplied by the caller")
    if not isinstance(review, Mapping):
        raise PipelineError("acceptance review evidence must be supplied by the caller")
    candidate_binding = make_file_binding(root, candidate_path)
    source_accounting_binding = make_file_binding(root, source_accounting_path, fixture_only=False)
    proofs: dict[str, dict[str, Any]] = {}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        value = technical.get(name)
        if not isinstance(value, Mapping):
            raise PipelineError(f"technical evidence is missing {name}")
        for field in ("path", "status", "command", "exit_code"):
            if field not in value:
                raise PipelineError(f"technical evidence {name} is missing {field}")
        binding = make_file_binding(root, value["path"], fixture_only=False)
        proofs[name] = binding | {
            "status": value.get("status"),
            "command": value.get("command"),
            "exit_code": value.get("exit_code"),
        }
    for field in (
        "report_path",
        "reviewer",
        "reviewed_at",
        "coverage",
        "source_quality_uncertainty",
        "discrepancies",
        "unreviewed_residuals",
    ):
        if field not in review:
            raise PipelineError(f"acceptance review evidence is missing {field}")
    review_report_path = review.get("report_path")
    if not isinstance(review_report_path, (str, Path)):
        raise PipelineError("review.report_path is required")
    review_value = {
        "report": make_file_binding(root, review_report_path, fixture_only=False),
        "reviewer": review.get("reviewer"),
        "reviewed_at": review.get("reviewed_at"),
        "coverage": review.get("coverage"),
        "source_quality_uncertainty": list(review.get("source_quality_uncertainty", [])),
        "discrepancies": list(review.get("discrepancies", [])),
        "unreviewed_residuals": list(review.get("unreviewed_residuals", [])),
    }
    master_path = edition.path.parent / "scopes" / identity_value["acquisition_id"] / "master.tei.xml" if scoped else edition.path
    master_reference = _relative(root, master_path, field="promotion.master.path")
    state_path = root / "library" / "works" / identity_value["work_id"] / "state.json"
    decision_value = dict(decision)
    record = {
        "schema_version": "2.0",
        "contract": ACCEPTANCE_CONTRACT,
        "acceptance_id": acceptance_id or f"{identity_value['edition_id']}-acceptance-{representation_revision['id']}",
        "identity": identity_value,
        "scope": dict(scope),
        "source": {
            "source_manifest": make_file_binding(root, acquisition_path),
            **acquisition_source,
            "accounting": source_accounting_binding,
            "missing_members": list(missing_members),
            "unknown_members": list(unknown_members),
        },
        "technical": {
            "candidate": candidate_binding,
            **proofs,
            "producer": dict(technical["producer"]),
            "checker": dict(technical["checker"]),
            "shared_assumptions": list(technical["shared_assumptions"]),
            "independent_corroboration": technical["independent_corroboration"],
        },
        "review": review_value,
        "representation_revision": dict(representation_revision),
        "decision": decision_value,
        "promotion": {
            "status": promotion_status,
            "master": candidate_binding | {"path": master_reference},
            "state_path": _relative(root, state_path, field="promotion.state_path"),
        },
    }
    _schema_validate(record, context="built acceptance")
    return record


make_acceptance = build_acceptance_record


def write_acceptance(path: Path, record: Mapping[str, Any]) -> Path:
    """Write a canonical acceptance sidecar after schema validation."""

    path = Path(path)
    validated = _schema_validate(record, context=str(path))
    write_json(path, validated)
    return path


def _is_reparse_path(path: Path) -> bool:
    """Return whether a path is a symlink/junction or another reparse point."""

    try:
        if io_path(path).is_symlink():
            return True
        attributes = getattr(io_path(path).lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise PipelineError(f"cannot inspect promotion path: {path}") from exc
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _copy_local_tree(source: Path, destination: Path) -> None:
    """Copy a fixture tree without following links or junctions."""

    if _is_reparse_path(source):
        raise PipelineError(f"promotion refuses reparse-point input root: {source}")
    io_path(destination).mkdir(parents=True, exist_ok=True)
    for child in io_iterdir(source):
        if _is_reparse_path(child):
            raise PipelineError(f"promotion refuses reparse-point input: {child}")
        target = destination / child.name
        if io_path(child).is_dir():
            _copy_local_tree(child, target)
        elif io_path(child).is_file():
            shutil.copy2(io_path(child), io_path(target))
        else:
            raise PipelineError(f"promotion refuses unsupported input path: {child}")


def _assert_local_promotion_root(root: Path) -> None:
    """Reject roots whose evidence may route through the durable data plane."""

    if (io_path(root / LOCAL_CONFIG_NAME)).exists():
        raise PipelineError(
            "promotion requires a bounded local fixture root; external data-plane configuration is present"
        )
    if _is_reparse_path(root):
        raise PipelineError(f"promotion refuses reparse-point input root: {root}")


def _assert_local_promotion_destination(destination: Path) -> None:
    """Reject an output path routed through a junction or data-plane config."""

    current = destination
    while not io_path(current).exists() and current.parent != current:
        current = current.parent
    while True:
        if _is_reparse_path(current):
            raise PipelineError(f"promotion destination is a reparse-point path: {current}")
        if (io_path(current / LOCAL_CONFIG_NAME)).is_file():
            raise PipelineError(
                "promotion destination is under external data-plane configuration"
            )
        if current.parent == current:
            break
        current = current.parent


def promote_accepted_master(
    root: Path,
    *,
    acceptance_path: Path,
    destination: Path,
    candidate_path: Path | None = None,
) -> PromotionResult:
    """Prepare an atomic accepted-master/state update in a fresh destination.

    The input ``root`` is read-only. The destination receives a copied fixture,
    the candidate bytes at the canonical edition master path, an updated
    acceptance record, and an updated state sidecar. Validation runs on the
    staged tree before its single directory rename, so a caller never observes
    a promoted TEI without its matching state update.
    """

    root_input = Path(root)
    if io_path(root_input).exists() and _is_reparse_path(root_input):
        raise PipelineError(f"promotion refuses reparse-point input root: {root_input}")
    root = resolve_path(root_input)
    acceptance_path = resolve_path(Path(acceptance_path))
    destination_input = Path(destination)
    destination = resolve_path(destination_input)
    if not io_path(root).is_dir():
        raise PipelineError(f"promotion root is missing: {root}")
    if io_path(destination).exists():
        raise PipelineError(f"promotion destination must be fresh: {destination}")
    if destination == root or root in destination.parents:
        raise PipelineError("promotion destination must be outside the input root")
    _assert_local_promotion_root(root)
    _assert_local_promotion_destination(destination_input)
    _relative(root, acceptance_path, field="acceptance_path")
    record = validate_acceptance(acceptance_path, root=root)
    identity = _identity(record)
    if record["promotion"]["status"] != "pending":
        raise PipelineError("only a pending acceptance can be promoted")
    accepted = record["decision"]["agent_assessment"]["status"] == "accepted" or record["decision"]["human_decision"]["status"] == "accepted"
    if not accepted or record["decision"]["blockers"]:
        raise PipelineError("promotion requires an accepted decision with no blockers")
    if candidate_path is not None:
        candidate_reference = _relative(root, resolve_path(Path(candidate_path)), field="candidate_path")
        if candidate_reference != record["technical"]["candidate"]["path"]:
            raise PipelineError("explicit candidate_path does not match acceptance record")

    stage = destination.parent / f".{destination.name}.p004-{uuid.uuid4().hex[:12]}"
    if io_path(stage).exists():
        raise PipelineError(f"refusing an existing promotion staging path: {stage}")
    try:
        io_path(destination.parent).mkdir(parents=True, exist_ok=True)
        _copy_local_tree(root, stage)
        staged_acceptance = stage / _relative(root, acceptance_path, field="acceptance_path")
        staged_record = load_acceptance(staged_acceptance)
        scoped = acceptance_path.parent.name == identity["acquisition_id"] and acceptance_path.parent.parent.name == "scopes"
        master_path, _canonical_acceptance, state_path = _canonical_paths(stage, identity, scoped=scoped)
        candidate = _fixture_path(stage, staged_record["technical"]["candidate"]["path"], field="technical.candidate.path")
        io_path(master_path.parent).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(io_path(candidate), io_path(master_path))
        master_binding = make_file_binding(stage, master_path)
        staged_record["promotion"] = dict(staged_record["promotion"])
        staged_record["promotion"]["status"] = "promoted"
        staged_record["promotion"]["promoted_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        staged_record["promotion"]["master"] = master_binding
        write_acceptance(staged_acceptance, staged_record)

        state = load_json(state_path)
        target = next((item for item in state.get("targets", []) if item.get("target_id") == identity["edition_id"]), None)
        if not isinstance(target, dict):
            raise PipelineError(f"edition target missing from state: {identity['edition_id']}")
        target["stage"] = "accepted"
        target["reason"] = PROMOTED_MASTER_REASON
        target["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        evidence = list(target.get("evidence", []))
        master_reference = _relative(stage, master_path, field="promotion.master.path")
        acceptance_reference = _relative(stage, staged_acceptance, field="acceptance path")
        for reference in (master_reference, acceptance_reference):
            if reference not in evidence:
                evidence.append(reference)
        target["evidence"] = evidence
        write_json(state_path, state)

        validate_acceptance(staged_acceptance, root=stage)
        validate_state(state_path, root=stage)
        _replace_with_retry(stage, destination)
    except Exception:
        if io_path(stage).exists():
            shutil.rmtree(io_path(stage))
        raise

    final_acceptance = destination / _relative(root, acceptance_path, field="acceptance_path")
    final_master, _unused_acceptance, final_state = _canonical_paths(destination, identity, scoped=scoped)
    return PromotionResult(
        destination_root=destination,
        acceptance_path=final_acceptance,
        master_path=final_master,
        state_path=final_state,
        master_sha256=sha256_file(final_master),
    )


__all__ = [
    "ACCEPTANCE_CONTRACT",
    "PromotionResult",
    "build_acceptance_record",
    "load_acceptance",
    "make_acceptance",
    "make_file_binding",
    "promote_accepted_master",
    "validate_acceptance",
    "write_acceptance",
]
