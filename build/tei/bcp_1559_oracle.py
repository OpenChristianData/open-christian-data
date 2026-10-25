"""Producer-independent package oracle for the retained 1559 BCP expression."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    _validation_authority_bindings,
)
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-bcp-1559-independent-source-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML = "http://www.w3.org/XML/1998/namespace"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def _import_closure_sha256() -> str:
    root = Path(__file__).resolve(strict=True).parents[2]
    paths = (
        Path(__file__).resolve(strict=True),
        Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True),
        Path(inspect.getsourcefile(compiled_schema)).resolve(strict=True),
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\n")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    profile = _strict_json(source_manifest.authority_path("bcp1559-profile").read_bytes(), "BCP 1559 profile")
    primary = sorted(
        (item for item in source_manifest.record["authorities"] if item["role"] == "primary-source"),
        key=lambda item: str(item["path"]),
    )
    for member in primary:
        path = source_manifest.authority_path(str(member["name"]))
        content = path.read_bytes()
        if len(content) != int(member["bytes"]) or _sha(content) != str(member["sha256"]):
            findings.append(f"source member drift: {member['path']}")

    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    document = etree.ElementTree(root)
    if not compiled_schema().validate(document):
        findings.extend(str(error) for error in compiled_schema().error_log)
    observed = {
        "services": set(root.xpath("//tei:div[@type='service']/@xml:id", namespaces={"tei": _TEI})),
        "labels": set(root.xpath("//tei:label/@xml:id", namespaces={"tei": _TEI})),
        "rubrics": set(root.xpath("//tei:p[@rend='rubric']/@xml:id", namespaces={"tei": _TEI})),
        "speaker_units": set(root.xpath("//tei:sp/@xml:id", namespaces={"tei": _TEI})),
        "paragraphs": set(root.xpath("//tei:p[not(@rend='rubric') and @xml:id]/@xml:id", namespaces={"tei": _TEI})),
        "collects": set(root.xpath("//tei:div[@type='collect']/@xml:id", namespaces={"tei": _TEI})),
    }
    accountability = _strict_json(candidate.member_bytes("source-accountability.json"), "BCP 1559 accountability")
    features = accountability.get("features")
    if not isinstance(features, dict):
        findings.append("accountability features are not an object")
    else:
        for name, expected_count in profile["expected_features"].items():
            feature = features.get(name)
            if not isinstance(feature, dict):
                findings.append(f"missing accountability feature: {name}")
                continue
            expected_ids = set(str(value) for value in feature.get("ids", []))
            if int(feature.get("count", -1)) != int(expected_count):
                findings.append(f"accountability count drift: {name}")
            if expected_ids != observed[name]:
                findings.append(f"TEI ID reconciliation drift: {name}")
    if int(accountability.get("tei", {}).get("bytes", -1)) != len(candidate.member_bytes("content.tei.xml")):
        findings.append("accountability TEI byte count drift")
    if accountability.get("tei", {}).get("sha256") != _sha(candidate.member_bytes("content.tei.xml")):
        findings.append("accountability TEI digest drift")

    bindings = _validation_authority_bindings(source_manifest)
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _import_closure_sha256(),
        "runtime": _runtime(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        **bindings,
        "findings": sorted(findings),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
