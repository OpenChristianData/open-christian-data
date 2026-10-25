"""Independent package checks for the retained BCP 1928 HTML route."""

from __future__ import annotations

import hashlib
import html as html_lib
import inspect
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree, html

from build.parsers import bcp1928
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    _validation_authority_bindings,
)
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-bcp-1928-independent-source-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML = "http://www.w3.org/XML/1998/namespace"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def _import_closure_sha256() -> str:
    # Use stable labels rather than absolute checkout paths: the same governed
    # implementation must verify in both the canonical checkout and worktrees.
    paths = (
        ("oracle", Path(__file__).resolve(strict=True)),
        ("source-manifest-contract", Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)),
        ("tei-validator", Path(inspect.getsourcefile(compiled_schema)).resolve(strict=True)),
    )
    digest = hashlib.sha256()
    for label, path in paths:
        digest.update(label.encode("utf-8"))
        digest.update(b"\n")
        digest.update(path.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _clean_fragment(fragment: str) -> str:
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(html_lib.unescape(fragment).replace("\xa0", " ").split())


def _independent_page_records(content: bytes, filename: str) -> list[tuple[str, str]]:
    """Extract only collect prose with a separate DOM/text path.

    This intentionally does not call the producer's extraction helpers. It is
    a narrow oracle for the candidate's source/member and text reconciliation.
    """
    source = content.decode("utf-8", errors="replace")
    source = re.sub(r"<script[^>]*>.*?</script>", " ", source, flags=re.I | re.S)
    source = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", source, flags=re.I | re.S)
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.I | re.S)
    marker = re.search(r"The\s+Collects?\s*\.", source, flags=re.I)
    raw_block = ""
    if marker:
        tail = source[marker.end():]
        close = re.search(r"</(?:center|p)\s*>", tail, flags=re.I)
        if close:
            for paragraph in re.finditer(
                r"<p[^>]*>((?:(?!</p>).)+)</p>",
                tail[close.end():],
                flags=re.I | re.S,
            ):
                candidate = _clean_fragment(paragraph.group(1))
                if candidate:
                    raw_block = paragraph.group(1)
                    break
    else:
        h2 = re.search(r"</h2\s*>", source, flags=re.I)
        if h2:
            for paragraph in re.finditer(
                r"<p[^>]*>((?:(?!</p>).)+)</p>",
                source[h2.end():],
                flags=re.I | re.S,
            ):
                candidate = _clean_fragment(paragraph.group(1))
                if candidate and re.search(r"(?:amen[.!]?|\[who\.\])$", candidate, re.I) and len(candidate.split()) >= 10:
                    raw_block = paragraph.group(1)
                    break
    if not raw_block:
        return []
    if re.search(r"The\s+Collects\s*\.", source, flags=re.I):
        raw_with_breaks = re.sub(r"<br\s*/?>", "\n", raw_block, flags=re.I)
        raw_pieces = re.split(r"(?<=Amen\.)\s*\n+\s*(?=[A-Z])", raw_with_breaks)
        cleaned = []
        for raw_piece in raw_pieces:
            piece = _clean_fragment(raw_piece)
            if piece:
                cleaned.append(
                    piece if piece.endswith("Amen.") else piece.rstrip(".") + "."
                )
        return [
            (f"{bcp1928.slugify(Path(filename).stem)}{'' if index == 0 else f'-{index + 1}'}", piece)
            for index, piece in enumerate(cleaned)
            if len(piece.split()) >= 10
        ]
    text = _clean_fragment(raw_block)
    return [(bcp1928.slugify(Path(filename).stem), text)] if len(text.split()) >= 10 else []


def _source_expectations(source_manifest: SourceManifest) -> tuple[list[dict[str, object]], dict[str, object]]:
    members = tuple(source_manifest.record["source_members"])
    expectations: list[dict[str, object]] = []
    page_without_collect: list[str] = []
    for member in members:
        path = source_manifest.repository_root / str(member["path"])
        content = path.read_bytes()
        if len(content) != int(member["bytes"]) or _sha(content) != str(member["sha256"]):
            raise ValueError(f"source member drift: {member['path']}")
        page_records = _independent_page_records(content, str(member["logical_name"]))
        if not page_records:
            page_without_collect.append(str(member["logical_name"]))
        for prayer_id, text in page_records:
            expectations.append(
                {
                    "id": prayer_id,
                    "source_path": str(member["path"]),
                    "source_page_order": int(member["order"]),
                    "text": text,
                }
            )
    return expectations, {"pages_without_collect": page_without_collect}


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    try:
        profile = _strict_json(
            source_manifest.authority_path("reconstruction-profile").read_bytes(),
            "BCP 1928 profile",
        )
        accountability = _strict_json(
            candidate.member_bytes("source-accountability.json"),
            "BCP 1928 accountability",
        )
        schema = _strict_json(
            source_manifest.authority_path("source-accountability-schema").read_bytes(),
            "BCP 1928 accountability schema",
        )
        findings.extend(error.message for error in Draft202012Validator(schema).iter_errors(accountability))

        expected, page_info = _source_expectations(source_manifest)
        observed = accountability.get("records")
        if not isinstance(observed, list):
            findings.append("accountability records are not an array")
        else:
            observed_keys = [
                {
                    "id": item.get("id"),
                    "source_path": item.get("source_path"),
                    "source_page_order": item.get("source_page_order"),
                    "text": item.get("text"),
                }
                for item in observed
                if isinstance(item, dict)
            ]
            if observed_keys != expected:
                findings.append("accountability does not match independent source extraction")
        if accountability.get("pages_without_collect") != page_info["pages_without_collect"]:
            findings.append("pages-without-collect accounting drift")
        manual_ids = {
            str(item.get("id"))
            for item in accountability.get("manual_claims", [])
            if isinstance(item, dict)
        }
        if manual_ids != {"trinity23", "trinity24"}:
            findings.append("manual alternate-witness claims are not explicitly accounted")

        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        document = etree.ElementTree(root)
        if not compiled_schema().validate(document):
            findings.extend(str(error) for error in compiled_schema().error_log)
        tei_records = []
        for node in root.xpath("//tei:div[@type='collect']", namespaces={"tei": _TEI}):
            paragraph = node.find(f"{{{_TEI}}}p")
            tei_records.append(
                {
                    "id": node.get(f"{{{_XML}}}id", "").removeprefix("collect-"),
                    "text": "" if paragraph is None else "".join(paragraph.itertext()),
                }
            )
        if len(tei_records) != 100:
            findings.append("TEI collect count drift")
        expected_tei = [{"id": item["id"], "text": item["text"]} for item in expected]
        if tei_records != expected_tei:
            findings.append("TEI collect text or order does not match independent source extraction")
        if root.xpath("//tei:div[@type='collect'][@n='trinity23'] | //tei:div[@type='collect'][@n='trinity24']", namespaces={"tei": _TEI}):
            findings.append("unbound Trinity manual claim leaked into TEI")
        provenance = _strict_json(candidate.member_bytes("provenance.json"), "BCP 1928 provenance")
        if provenance.get("source_manifest_sha256") != source_manifest.sha256:
            findings.append("provenance source-manifest binding drift")
        if provenance.get("status") != "nonaccepted":
            findings.append("candidate provenance is not nonaccepted")
    except (KeyError, TypeError, ValueError, etree.XMLSyntaxError, json.JSONDecodeError) as exc:
        findings.append(str(exc))

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
        "findings": sorted(str(item) for item in findings),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION

