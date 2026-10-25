"""Independent source-led checks for unchanged Methodius First1KGreek TEI."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


TEI = "{http://www.tei-c.org/ns/1.0}"
ORACLE_ID = "ocd-methodius-first1kgreek-independent-source-reader"
ORACLE_VERSION = "1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def closure_digest() -> str:
    files = [Path(__file__).resolve(), Path(ET.__file__).resolve(), Path(etree.__file__).resolve()]
    return _sha(_json([{"path": path.name, "sha256": _sha(path.read_bytes())} for path in files]))


def source_inventory(content: bytes) -> dict[str, object]:
    root = ET.fromstring(content)
    body = root.find(f"{TEI}text/{TEI}body")
    if root.tag != f"{TEI}TEI" or body is None:
        raise ValueError("source has no TEI root/body")
    edition = body.find(f"{TEI}div")
    if edition is None or edition.get("type") != "edition":
        raise ValueError("source lacks the CTS edition division")
    books = edition.findall(f"{TEI}div[@subtype='book']")
    title = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title")
    license_node = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}publicationStmt/{TEI}availability/{TEI}licence")
    source_desc = root.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}sourceDesc")
    return {
        "root": root.tag,
        "cts_edition": edition.get("n"),
        "title": "".join(title.itertext()).strip() if title is not None else None,
        "license_target": license_node.get("target") if license_node is not None else None,
        "edition_names_bonwetsch": source_desc is not None and "Bonwetsch" in "".join(source_desc.itertext()),
        "edition_names_1917": source_desc is not None and "1917" in "".join(source_desc.itertext()),
        "book_chapter_counts": [
            {"book": book.get("n"), "chapters": len(book.findall(f"{TEI}div[@subtype='chapter']"))}
            for book in books
        ],
        "element_counts": dict(sorted(Counter(node.tag.removeprefix(TEI) for node in root.iter()).items())),
        "source_text_sha256": _sha("".join(root.itertext()).encode("utf-8")),
    }


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    source = manifest.authority_path("retained-tei").read_bytes()
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    policy = json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    for field in ("work_id", "textual_form_id", "edition_id", "acquisition_id"):
        if manifest.record.get(field) != policy["provenance"].get(field):
            findings.append(f"source/catalog {field} identity mismatch")
    if (
        receipt.get("manifest_row") != "L813 Methodius only"
        or receipt.get("repository_revision") != manifest.record.get("repository_revision")
        or receipt.get("source_path") != policy["provenance"]["source_path"]
        or receipt.get("sha256") != profile["source_sha256"]
        or receipt.get("bytes") != profile["source_bytes"]
        or receipt.get("official_path") != "data/tlg2959/tlg001/tlg2959.tlg001.opp-grc1.xml"
        or "https://creativecommons.org/licenses/by-sa/4.0/" not in receipt.get("license_statement", "")
    ):
        findings.append("pinned acquisition receipt does not bind the exact L813 source and license")
    content = candidate.member_bytes("content.tei.xml")
    if source_inventory(source) != profile["member_inventory"]:
        findings.append("source title, edition, license, structure, or text differs from independently recorded inventory")
    if _sha(source) != profile["source_sha256"] or len(source) != profile["source_bytes"]:
        findings.append("source bytes differ from recorded source identity")
    if content != source:
        findings.append("candidate differs from the complete retained TEI member; byte conservation failed")
    try:
        parsed = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        findings.append(f"candidate XML parse failure: {exc}")
    else:
        schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-validation-schema"))))
        if not schema.validate(parsed):
            findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if account.get("source_sha256") != _sha(source) or account.get("candidate_sha256") != _sha(content) or account.get("member_inventory") != profile["member_inventory"]:
        findings.append("source accountability identity or inventory differs")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("readme").read_bytes():
        findings.append("source attribution README differs")
    if json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]:
        findings.append("provenance differs from policy")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(item) for item in policy["unresolved"]):
        findings.append("unresolved ledger differs from policy")
    roles = {authority["role"]: authority for authority in manifest.record["authorities"]}
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure_digest(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": roles["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": roles["candidate-package-schema"]["sha256"],
        "source_sha256": roles["primary-source"]["sha256"],
        "xsd_sha256": roles["tei-validation-schema"]["sha256"],
        "policy_sha256": roles["independent-validation-policy"]["sha256"],
        "findings": findings,
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
