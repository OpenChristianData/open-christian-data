"""Provisional fixture provenance and frozen-reference accounting.

Comparing an excerpt with its bound reference detects changes to that excerpt.
It is not a fresh source reconstruction oracle or an acceptance decision.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


class ConformanceError(ValueError):
    """An evidence binding is missing, malformed, or stale."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConformanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _digest(value: Any, context: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ConformanceError(f"{context}: expected lowercase SHA-256")
    return value


def _relative(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ConformanceError(f"{context}: expected relative POSIX path")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or path.as_posix() != value or any(part in (".", "..") for part in path.parts):
        raise ConformanceError(f"{context}: expected normalized contained path")
    return value


def _contained(root: Path, value: Any) -> Path:
    relative = _relative(value, "fixture path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ConformanceError(f"fixture path escapes package: {relative}")
    current = root.resolve()
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ConformanceError(f"fixture path uses a symlink or junction: {relative}")
    return path


def _bound_bytes(path: Path, expected: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConformanceError(f"cannot read bound file: {path}") from exc
    if sha256(data).hexdigest() != _digest(expected, str(path)):
        raise ConformanceError(f"stale SHA-256 binding: {path}")
    return data


@dataclass(frozen=True)
class FixturePackage:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str

    def fixture(self, fixture_id: str) -> dict[str, Any]:
        for record in self.manifest["fixtures"]:
            if record["id"] == fixture_id:
                return record
        raise ConformanceError(f"unknown fixture: {fixture_id}")

    def reference(self, fixture_id: str) -> bytes:
        record = self.fixture(fixture_id)
        return _bound_bytes(_contained(self.root, record["path"]), record["sha256"])


def load_fixture_package(manifest_path: Path) -> FixturePackage:
    """Check local fixture hashes and provenance declarations, without live I/O.

    A successful load verifies the frozen evidence package only. Call
    ``verify_live_origin`` separately to recheck retained input bytes.
    """
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConformanceError(f"invalid fixture manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "provisional":
        raise ConformanceError("fixture manifest must explicitly remain provisional")
    if manifest.get("schema_version") != "tei-conformance-fixtures-v1":
        raise ConformanceError("unsupported fixture manifest schema version")
    if set(manifest) - {"schema_version", "status", "purpose", "source_oracle_policy", "namespaces",
                        "fixtures", "exclusions", "coverage_gaps"}:
        raise ConformanceError("fixture manifest contains unknown fields")
    records = manifest.get("fixtures")
    if not isinstance(records, list) or not records:
        raise ConformanceError("fixture manifest must contain fixtures")
    ids: set[str] = set()
    paths: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ConformanceError("fixture record must be an object")
        if set(record) != {"id", "path", "sha256", "kind", "title", "origin", "patterns",
                           "transformations", "expected", "evidence", "limits"}:
            raise ConformanceError("fixture record has missing or unknown fields")
        fixture_id = record.get("id")
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id in ids:
            raise ConformanceError(f"missing or duplicate fixture identity: {fixture_id}")
        ids.add(fixture_id)
        for field in ("kind", "title"):
            if not isinstance(record[field], str) or not record[field].strip():
                raise ConformanceError(f"{fixture_id}: missing {field}")
        path = _relative(record.get("path"), fixture_id)
        if path in paths:
            raise ConformanceError(f"duplicate fixture path: {path}")
        paths.add(path)
        _bound_bytes(_contained(manifest_path.parent, path), record.get("sha256"))
        origin = record.get("origin")
        if not isinstance(origin, dict):
            raise ConformanceError(f"{fixture_id}: missing provenance")
        if set(origin) - {"kind", "tei_path", "tei_sha256", "selector", "source_authorities", "source_members", "identity"}:
            raise ConformanceError(f"{fixture_id}: unknown provenance fields")
        origin_kind = origin.get("kind", "tei-excerpt")
        if origin_kind == "tei-excerpt":
            _relative(origin.get("tei_path"), fixture_id)
            _digest(origin.get("tei_sha256"), fixture_id)
        elif origin_kind == "retained-source-only":
            if origin.get("tei_path") is not None or origin.get("tei_sha256") is not None:
                raise ConformanceError(f"{fixture_id}: source-only derivative cannot claim an original TEI")
            if record.get("kind") != "synthetic-derivative" or not record.get("transformations"):
                raise ConformanceError(f"{fixture_id}: source-only fixture must explicitly describe its derivative")
        else:
            raise ConformanceError(f"{fixture_id}: unknown provenance kind {origin_kind!r}")
        identity = origin.get("identity")
        if (not isinstance(origin.get("selector"), str) or not origin["selector"].strip()
                or not isinstance(identity, dict)
                or not any(isinstance(value, str) and value.strip() for value in identity.values())):
            raise ConformanceError(f"{fixture_id}: missing source selector or identity")
        for group in ("source_authorities", "source_members"):
            bindings = origin.get(group)
            if not isinstance(bindings, list) or not bindings:
                raise ConformanceError(f"{fixture_id}: missing {group}")
            for binding in bindings:
                if not isinstance(binding, dict):
                    raise ConformanceError(f"{fixture_id}: invalid {group} binding")
                _relative(binding.get("path"), fixture_id)
                _digest(binding.get("sha256"), fixture_id)
                if group == "source_members" and not binding.get("locator"):
                    raise ConformanceError(f"{fixture_id}: missing retained source locator")
        for field in ("patterns", "transformations", "evidence", "limits"):
            if not isinstance(record.get(field), list):
                raise ConformanceError(f"{fixture_id}: {field} must be an explicit list")
        if not isinstance(record.get("expected"), dict):
            raise ConformanceError(f"{fixture_id}: missing expected outcomes")
    return FixturePackage(manifest_path.parent.resolve(), manifest, sha256(raw).hexdigest())


def verify_live_origin(package: FixturePackage, fixture_id: str, repository_root: Path) -> dict[str, Any]:
    """Recheck exact original TEI/source bytes through the storage boundary.

    This proves hash freshness, not that a declared selector faithfully covers
    the source. Source-family oracle execution remains separate.
    """
    record = package.fixture(fixture_id)
    package.reference(fixture_id)
    origin = record["origin"]
    bindings = [*origin["source_authorities"], *origin["source_members"]]
    if origin.get("kind", "tei-excerpt") == "tei-excerpt":
        bindings.insert(0, {"path": origin["tei_path"], "sha256": origin["tei_sha256"]})
    origin_bytes: bytes | None = None
    for binding in bindings:
        data = _bound_bytes(resolve_repo_path(repository_root, binding["path"]), binding["sha256"])
        if binding["path"] == origin.get("tei_path"):
            origin_bytes = data
    selected_nodes: int | None = None
    if origin_bytes is not None:
        try:
            selected = parse_xml(origin_bytes).xpath(
                origin["selector"], namespaces={"tei": "http://www.tei-c.org/ns/1.0",
                                                "xml": "http://www.w3.org/XML/1998/namespace"})
        except etree.XPathError as exc:
            raise ConformanceError(f"{fixture_id}: invalid original TEI selector") from exc
        if (not isinstance(selected, list) or not selected
                or not all(isinstance(node, etree._Element) for node in selected)):
            raise ConformanceError(f"{fixture_id}: original TEI selector selects no element evidence")
        selected_nodes = len(selected)
    return {"status": "hashes-current", "fixture_id": fixture_id,
            "checked_bindings": len(bindings), "origin_tei_selected_nodes": selected_nodes,
            "source_locator_validation": "descriptive-locators-not-machine-verified",
            "source_oracle": "not-rerun"}


def parse_xml(data: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(data, parser)
    tree = root.getroottree()
    if tree.docinfo.doctype:
        raise ConformanceError("DTD/entity declarations are outside the conformance input contract")
    return tree


def _events(tree: etree._ElementTree) -> tuple[tuple[Any, ...], ...]:
    """Preserve expanded names, attributes, exact text, and attachment order."""
    events: list[tuple[Any, ...]] = []

    def visit(node: etree._Element) -> None:
        if not isinstance(node.tag, str):
            # Comments and processing instructions are not source text.
            if node.tail:
                events.append(("text", node.tail))
            return
        events.append(("start", node.tag, tuple(sorted(node.attrib.items()))))
        if node.text:
            events.append(("text", node.text))
        for child in node:
            visit(child)
        events.append(("end", node.tag))
        if node.tail:
            events.append(("text", node.tail))

    visit(tree.getroot())
    return tuple(events)


@dataclass(frozen=True)
class ReferenceAccounting:
    status: str
    fixture_id: str
    reference_sha256: str
    candidate_sha256: str
    issues: tuple[str, ...]
    source_fidelity: str = "not-assessed-by-reference-comparison"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_reference(candidate: bytes, package: FixturePackage, fixture_id: str) -> ReferenceAccounting:
    """Compare a candidate excerpt with its immutable manifest-bound reference."""
    reference = package.reference(fixture_id)
    expected = _events(parse_xml(reference))
    actual = _events(parse_xml(candidate))
    issues: list[str] = []
    if actual != expected:
        expected_counts, actual_counts = Counter(expected), Counter(actual)
        if expected_counts - actual_counts:
            issues.append("reference-content-omitted-or-changed")
        if actual_counts - expected_counts:
            issues.append("reference-content-added-duplicated-or-changed")
        if expected_counts == actual_counts:
            issues.append("reference-order-or-attachment-changed")
    return ReferenceAccounting(
        "matches-frozen-reference" if not issues else "differs-from-frozen-reference",
        fixture_id, sha256(reference).hexdigest(), sha256(candidate).hexdigest(), tuple(issues),
    )
