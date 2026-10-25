"""Read, extract, verify, and inspect exact metadata evidence.

BindingVerifier owns caches for one verification operation. Extraction verifies
its snapshot with a separate fresh verifier before returning. Inspection reports
changed bytes without adopting them or weakening strict verification.
"""
from __future__ import annotations

import copy
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from build.lib import source_metadata_contract as contract
from build.lib.source_metadata_contract import (
    EvidenceError, MetadataError, sha256_bytes, schema_enum, _resolve,
    _read_packet_value, _json_equal,
)

def _archive_member(path: Path, member: str) -> bytes:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                return archive.read(member)
        with tarfile.open(path, mode="r:*") as archive:
            handle = archive.extractfile(member)
            if handle is None:
                raise KeyError(member)
            return handle.read()
    except (KeyError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise EvidenceError(f"archive member is unavailable: {path}::{member}") from exc

def _xml_id_value(
    data: bytes, identifier: str, *,
    cache: dict[tuple[str, str | None], dict[str, list[ET.Element]]] | None = None,
    cache_key: tuple[str, str | None] | None = None,
) -> str:
    index = cache.get(cache_key) if cache is not None and cache_key is not None else None
    if index is None:
        index = _xml_id_index(data, identifier)
        if cache is not None and cache_key is not None:
            cache[cache_key] = index
    matches = index.get(identifier, [])
    if len(matches) != 1:
        raise EvidenceError(f"xml_id locator must resolve uniquely: {identifier} ({len(matches)} matches)")
    return " ".join("".join(matches[0].itertext()).split())

def _xml_id_index(data: bytes, identifier: str) -> dict[str, list[ET.Element]]:
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"cannot parse XML for xml_id locator {identifier!r}") from exc
    index: dict[str, list[ET.Element]] = {}
    for element in root.iter():
        identifiers = {element.get("xml:id"), element.get("{http://www.w3.org/XML/1998/namespace}id"), element.get("id")}
        for value in identifiers - {None}:
            index.setdefault(value, []).append(element)
    return index

def _locator_value(
    data: bytes, locator: Mapping[str, Any], *, encoding: str = "utf-8",
    xml_cache: dict[tuple[str, str | None], dict[str, list[ET.Element]]] | None = None,
    cache_key: tuple[str, str | None] | None = None,
    check_expected: bool = True,
) -> Any:
    if encoding not in schema_enum("text_encoding"):
        raise EvidenceError(f"unsupported declared text encoding: {encoding}")
    kind = locator["kind"]
    if check_expected and kind in {"json_pointer", "xml_id"} and encoding != "utf-8":
        raise EvidenceError(f"{kind} locator does not use a declared text encoding; omit encoding or use utf-8")
    value = locator["value"]
    expected = locator["expected"]
    if kind == "json_pointer":
        actual = _read_packet_value(data, value)
        if check_expected and not _json_equal(actual, expected):
            raise EvidenceError(f"JSON pointer {value!r} expected {expected!r}, got {actual!r}")
        return actual
    if kind == "text":
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError as exc:
            if not check_expected:
                raise
            raise EvidenceError(f"text locator cannot decode {encoding} bytes: {value!r}") from exc
        if not check_expected and (not isinstance(value, str) or value not in text):
            raise KeyError(value)
        if value not in text:
            raise EvidenceError(f"text locator not found: {value!r}")
        if not isinstance(expected, str) or not expected or expected not in text:
            if not check_expected:
                raise KeyError(expected)
            raise EvidenceError(f"text locator expected excerpt is absent: {expected!r}")
        if text.count(expected) != 1:
            if not check_expected:
                raise KeyError(expected)
            raise EvidenceError("text locator expected excerpt is not unique")
        start = text.index(expected)
        if value not in text[start : start + len(expected)]:
            if not check_expected:
                raise KeyError(value)
            raise EvidenceError("text locator value and expected excerpt do not identify one scope")
        return expected
    if kind == "xml_id":
        actual = _xml_id_value(data, value, cache=xml_cache, cache_key=cache_key)
        if check_expected and (not isinstance(expected, str) or actual != expected):
            raise EvidenceError(f"xml_id {value!r} expected exact text {expected!r}, got {actual!r}")
        return actual
    if kind == "whole_file":
        if not check_expected:
            return True if expected is True else data.decode(encoding)
        if isinstance(expected, str):
            try:
                actual = data.decode(encoding)
            except UnicodeDecodeError as exc:
                raise EvidenceError(f"whole_file expected text but bytes are not {encoding}") from exc
            if actual != expected:
                raise EvidenceError("whole_file expected text differs")
        elif expected is not True:
            raise EvidenceError("whole_file expected must be exact text or true")
        return True
    if kind == "archive_listing":
        # The archive is opened by _verify_binding; this marker is checked there.
        return True
    if not check_expected:
        raise EvidenceError(f"unsupported locator kind: {kind!r}")
    raise EvidenceError(f"unsupported locator kind: {kind}")

def _verify_binding(
    root: Path,
    binding: Mapping[str, Any],
    *,
    cache: dict[tuple[str, str | None], tuple[bytes, str, bytes, str | None, str]] | None = None,
    xml_cache: dict[tuple[str, str | None], dict[str, list[ET.Element]]] | None = None,
) -> dict[str, Any]:
    path_text = binding["path"]
    member = binding.get("member")
    cache_key = (path_text, member)
    cached = cache.get(cache_key) if cache is not None else None
    if cached is None:
        path = _resolve(root, path_text, field="evidence path")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise EvidenceError(f"evidence path is unavailable: {path_text}") from exc
        actual_hash = sha256_bytes(data)
        if len(data) != binding["bytes"]:
            raise EvidenceError(f"evidence byte count mismatch for {path_text}")
        if actual_hash != binding["sha256"]:
            raise EvidenceError(f"evidence hash mismatch for {path_text}: {actual_hash}")
        selected = data
        member_hash: str | None = None
        if member:
            if not isinstance(member, str) or member.startswith("/") or "\\" in member or any(
                part in {".", ".."} for part in PurePosixPath(member).parts
            ):
                raise EvidenceError(f"archive member is not normalized: {member!r}")
            selected = _archive_member(path, member)
            member_hash = sha256_bytes(selected)
        cached = (data, actual_hash, selected, member_hash, str(path))
        if cache is not None:
            cache[cache_key] = cached
    data, actual_hash, selected, member_hash, path_value = cached
    path = Path(path_value)
    if len(data) != binding["bytes"]:
        raise EvidenceError(f"evidence byte count mismatch for {path_text}")
    if actual_hash != binding["sha256"]:
        raise EvidenceError(f"evidence hash mismatch for {path_text}: {actual_hash}")
    if member:
        if "member_bytes" not in binding or "member_sha256" not in binding:
            raise EvidenceError(
                f"archive member binding requires member_bytes and member_sha256: "
                f"{path_text}::{member}"
            )
        if "member_bytes" in binding and len(selected) != binding["member_bytes"]:
            raise EvidenceError(f"archive member byte count mismatch for {path_text}::{member}")
        if "member_sha256" in binding and member_hash != binding["member_sha256"]:
            raise EvidenceError(f"archive member hash mismatch for {path_text}::{member}")
    locator = binding["locator"]
    if locator["kind"] == "archive_listing":
        names = _archive_names(path, label=path_text)
        if locator["value"] not in names:
            raise EvidenceError(f"archive listing does not contain {locator['value']!r}")
        if locator.get("expected") is not True:
            raise EvidenceError("archive_listing expected must be true")
    else:
        _locator_value(selected, locator, encoding=binding.get("encoding", "utf-8"), xml_cache=xml_cache, cache_key=cache_key)
    return {
        "path": path_text,
        "member": member,
        "sha256": actual_hash,
        "bytes": len(data),
        "role": binding["role"],
    }


def _archive_names(path: Path, *, label: str | None = None) -> list[str]:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                return archive.namelist()
        with tarfile.open(path, mode="r:*") as archive:
            return archive.getnames()
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise EvidenceError(f"cannot inspect archive listing: {label if label is not None else path}") from exc


class BindingVerifier:
    """Verify bindings against one operation's cached, validated source bytes.

    Create a new verifier for every independent check. No cache is shared across
    extractions, reviews, or callers; callers never manage cache dictionaries.
    """

    def __init__(self, root: Path):
        self._root = Path(root)
        self._payloads = {}
        self._xml = {}

    def verify(self, binding: Mapping[str, Any]) -> dict[str, Any]:
        return _verify_binding(
            self._root, binding, cache=self._payloads, xml_cache=self._xml,
        )


def _current_locator(data: bytes, locator: Mapping[str, Any], *, path: Path, member: str | None, encoding: str = "utf-8") -> tuple[Any, str | None]:
    """Observe a locator without requiring the historical expected value."""
    try:
        if locator.get("kind") == "archive_listing":
            member_name = str(locator["value"])
            if member_name not in _archive_names(path):
                raise KeyError(member_name)
            return True, None
        return _locator_value(data, locator, encoding=encoding, check_expected=False), None
    except (UnicodeDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        return None, str(exc)

def extract_bindings(root: Path, requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract reusable exact bindings from explicit selectors, without inference.

    XML IDs use XML's byte-declared encoding. JSON pointers use UTF-8.
    Text requests use one-based inclusive line ranges and an explicit encoding.
    """
    if not isinstance(requests, list) or not requests:
        raise contract.MetadataError("extraction input requires a nonempty requests array")
    try:
        root = Path(root)
    except (TypeError, ValueError) as exc:
        raise MetadataError(f"data root must be a filesystem path: {root!r}") from exc
    payloads = {}
    xml_cache = {}
    result = {}
    for request in requests:
        if not isinstance(request, dict):
            raise contract.MetadataError("extraction request must be an object")
        allowed = {"id", "path", "member", "kind", "value", "encoding", "start_line", "end_line", "role"}
        if set(request) - allowed or not {"id", "path", "kind", "role"} <= set(request):
            raise contract.MetadataError("invalid extraction request keys")
        identifier = request["id"]
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise contract.MetadataError("extraction ids must be nonempty and unique")
        path_text = request["path"]
        if not isinstance(path_text, str):
            raise contract.MetadataError("extraction path must be a normalized repository-relative POSIX path")
        path = contract._resolve(root, path_text, field="extraction path")
        member = request.get("member")
        if member is not None:
            contract._normal_relative(member, field="archive member")
        key = (path_text, member)
        if key not in payloads:
            try:
                raw = path.read_bytes()
            except (OSError, RuntimeError) as exc:
                raise contract.MetadataError(f"cannot read extraction source {path_text}: {exc}") from exc
            selected = _archive_member(path, member) if member else raw
            payloads[key] = (raw, selected)
        raw, selected = payloads[key]
        kind = request["kind"]
        if not isinstance(kind, str):
            raise contract.MetadataError("extraction kind must be a string")
        if kind not in {"xml_id", "json_pointer", "text"}:
            raise contract.MetadataError(f"unsupported extraction kind: {kind}")
        if kind in {"xml_id", "json_pointer"}:
            if not isinstance(request.get("value"), str):
                raise contract.MetadataError(f"{kind} extraction requires a string value")
            if "start_line" in request or "end_line" in request:
                raise contract.MetadataError(f"{kind} extraction does not accept line ranges")
        elif "value" in request:
            raise contract.MetadataError("text extraction uses start_line/end_line, not value")
        encoding = request.get("encoding", "utf-8")
        if not isinstance(encoding, str) or encoding not in contract.schema_enum("text_encoding"):
            raise contract.MetadataError(f"unsupported encoding: {encoding}")
        if kind == "xml_id":
            value = request["value"]
            expected = _xml_id_value(selected, value, cache=xml_cache, cache_key=key)
        elif kind == "json_pointer":
            value = request["value"]
            expected = contract._read_packet_value(selected, value)
        elif kind == "text":
            if "encoding" not in request:
                raise contract.MetadataError("text extraction requires explicit encoding")
            start, end = request.get("start_line"), request.get("end_line")
            try:
                lines = selected.decode(encoding).splitlines(keepends=True)
            except UnicodeDecodeError as exc:
                raise contract.MetadataError(f"text extraction cannot decode {encoding}: {path_text}") from exc
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
                raise contract.MetadataError("text extraction requires a valid one-based inclusive line range")
            value = expected = "".join(lines[start - 1:end])
        binding = {"path": request["path"], "bytes": len(raw), "sha256": contract.sha256_bytes(raw),
                   "role": request["role"], "locator": {"kind": kind, "value": value, "expected": expected}}
        if member:
            binding.update(member=member, member_bytes=len(selected), member_sha256=contract.sha256_bytes(selected))
        if "encoding" in request:
            binding["encoding"] = encoding
        validator = contract.jsonschema.Draft202012Validator(contract._schema_for("binding"))
        errors = list(validator.iter_errors(binding))
        if errors:
            raise contract.MetadataError(f"invalid extracted binding: {errors[0].message}")
        _locator_value(selected, binding["locator"], encoding=encoding, xml_cache=xml_cache, cache_key=key)
        result[identifier] = binding
    # Verify freshly read bytes against the extraction snapshot before returning.
    fresh = BindingVerifier(root)
    for binding in result.values():
        fresh.verify(binding)
    return {"notice": "Exact extracted bindings; role and claim applicability still require independent review.", "bindings": result}


def inspect_binding(root: Path, binding: Mapping[str, Any], reference: str) -> dict[str, Any]:
    path_text = binding["path"]
    try:
        path = contract._resolve(root, path_text, field="evidence path")
    except (contract.MetadataError, contract.EvidenceError) as exc:
        return {
            "kind": "evidence_binding",
            "reference": reference,
            "path": path_text,
            "status": "unverifiable",
            "historical": copy.deepcopy(binding),
            "current": None,
            "changes": [],
            "reason": str(exc),
        }
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {
            "kind": "evidence_binding",
            "reference": reference,
            "path": path_text,
            "status": "missing",
            "historical": copy.deepcopy(binding),
            "current": None,
            "changes": ["path_missing"],
            "reason": "evidence path is missing",
        }
    except OSError as exc:
        return {
            "kind": "evidence_binding",
            "reference": reference,
            "path": path_text,
            "status": "unverifiable",
            "historical": copy.deepcopy(binding),
            "current": {"path": str(path)},
            "changes": [],
            "reason": f"evidence path cannot be read: {exc}",
        }
    raw_sha = contract.sha256_bytes(raw)
    current: dict[str, Any] = {"path": path_text, "resolved_path": str(path), "sha256": raw_sha, "bytes": len(raw)}
    changes: list[str] = []
    if raw_sha != binding["sha256"]:
        changes.append("file_hash")
    if len(raw) != binding["bytes"]:
        changes.append("file_bytes")
    member = binding.get("member")
    selected = raw
    if member is not None:
        try:
            selected = _archive_member(path, member)
            member_sha = contract.sha256_bytes(selected)
            current.update(member=member, member_sha256=member_sha, member_bytes=len(selected))
            if member_sha != binding.get("member_sha256"):
                changes.append("member_hash")
            if len(selected) != binding.get("member_bytes"):
                changes.append("member_bytes")
        except FileNotFoundError:
            return {
                "kind": "evidence_binding",
                "reference": reference,
                "path": path_text,
                "status": "missing",
                "historical": copy.deepcopy(binding),
                "current": current,
                "changes": [*changes, "member_missing"],
                "reason": f"archive member is missing: {member}",
            }
        except (KeyError, OSError, contract.EvidenceError, ValueError) as exc:
            return {
                "kind": "evidence_binding",
                "reference": reference,
                "path": path_text,
                "status": "unverifiable",
                "historical": copy.deepcopy(binding),
                "current": current,
                "changes": changes,
                "reason": f"archive member cannot be read: {exc}",
            }
    actual, locator_error = _current_locator(selected, binding["locator"], path=path, member=member, encoding=binding.get("encoding", "utf-8"))
    expected = binding["locator"].get("expected")
    if locator_error is not None:
        return {
            "kind": "evidence_binding",
            "reference": reference,
            "path": path_text,
            "status": "unverifiable",
            "historical": copy.deepcopy(binding),
            "current": current,
            "changes": changes,
            "reason": f"current selector cannot be verified: {locator_error}",
        }
    current["selector_value"] = copy.deepcopy(actual)
    if not contract._json_equal(actual, expected):
        changes.append("selector_value")
    status = "changed" if changes else "unchanged"
    if status == "unchanged":
        try:
            BindingVerifier(root).verify(binding)
        except (contract.MetadataError, OSError, ValueError, KeyError, TypeError) as exc:
            status = "unverifiable"
            current["verification_error"] = str(exc)
    return {
        "kind": "evidence_binding",
        "reference": reference,
        "path": path_text,
        "status": status,
        "historical": copy.deepcopy(binding),
        "current": current,
        "changes": changes,
        "selector_status": "unchanged" if contract._json_equal(actual, expected) else "changed",
    }
