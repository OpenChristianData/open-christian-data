"""Independent source oracle for the LIB-077 Large Catechism candidate."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    _validation_authority_bindings,
)


ORACLE_ID = "ocd-lib077-luthers-large-catechism-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
START_LINE = 30
END_LINE = 4536
PART_RE = re.compile(r"^Part\s+(?:First|Second|Third|Fourth)\.", re.IGNORECASE)
SECTION_RE = re.compile(
    r"^(?:PREFACE|SHORT PREFACE OF DR\. MARTIN LUTHER|"
    r"The\s+(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\s+"
    r"(?:Commandment|Article|Petition|Sacrament)\.?|"
    r"Article\s+(?:I|II|III|IV|V|VI)\.?|"
    r"The\s+(?:Introduction|Conclusion|Close of the Commandments|Baptism)\.?|"
    r"OF\s+(?:THE\s+)?(?:BAPTISM|SACRAMENT(?:\s+OF\s+THE\s+ALTAR)?)\.?|"
    r"CONFESSION)$",
    re.IGNORECASE,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    value = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "profile")
    if value.get("work_id") != "luthers-large-catechism":
        raise ValueError("profile work scope drift")
    return value


def _source(source_manifest: SourceManifest) -> tuple[bytes, list[bytes], Mapping[str, object]]:
    members = source_manifest.record.get("source_members")
    if not isinstance(members, tuple) or len(members) != 1 or not isinstance(members[0], Mapping):
        raise ValueError("source member inventory drift")
    member = members[0]
    content = (source_manifest.repository_root / str(member["path"])).read_bytes()
    if len(content) != int(member["bytes"]) or _sha(content) != str(member["sha256"]):
        raise ValueError("source member drift")
    lines = content.split(b"\r\n")[:-1]
    if len(lines) != int(member["lines"]):
        raise ValueError("physical line count drift")
    return content, lines, member


def _decode(number: int, line: bytes) -> str:
    return line.decode("utf-8-sig" if number == 1 else "utf-8", errors="strict")


def _category(number: int) -> str:
    if number < START_LINE:
        return "gutenberg-header"
    if number == START_LINE:
        return "gutenberg-start-marker"
    if number < END_LINE:
        return "work-content"
    if number == END_LINE:
        return "gutenberg-end-marker"
    return "gutenberg-license"


def _kind(category: str, text: str) -> str:
    stripped = text.strip()
    if category in {"gutenberg-start-marker", "gutenberg-end-marker"}:
        return "marker"
    if category != "work-content":
        return "wrapper"
    if not stripped:
        return "blank"
    if PART_RE.match(stripped):
        return "part"
    if SECTION_RE.fullmatch(stripped):
        return "section"
    return "content"


def _records(content: bytes, lines: list[bytes]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(lines, 1):
        raw_record = line + b"\r\n"
        text = _decode(number, line)
        line_id = f"luthers-large-catechism-line-{number:05d}"
        result.append(
            {
                "id": line_id,
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(raw_record),
                "record_sha256": _sha(raw_record),
                "text_sha256": _sha(text.encode("utf-8")),
                "category": _category(number),
                "kind": _kind(_category(number), text),
                "disposition": "represented",
                "target": f"#{line_id}",
                "text": text,
            }
        )
        offset += len(raw_record)
    if offset != len(content):
        raise ValueError("source byte accounting does not close")
    return result


def _expected_accountability(content: bytes, member: Mapping[str, object], records: list[dict[str, object]]) -> dict[str, object]:
    crosswalk = [{key: value for key, value in record.items() if key != "text"} for record in records]
    return {
        "contract": "ocd-lib077-source-accountability-v1",
        "work_id": "luthers-large-catechism",
        "source_sha256": str(member["sha256"]),
        "source_bytes": len(content),
        "physical_lines": len(records),
        "represented_lines": len(records),
        "omitted_lines": 0,
        "duplicated_lines": 0,
        "member_census": [{"path": member["path"], "bytes": member["bytes"], "sha256": member["sha256"], "included": True, "reason": "The current LIB-077 manifest binds this sole exact retained Gutenberg member."}],
        "excluded_members": [],
        "crosswalk_sha256": _sha(_canonical(crosswalk)),
        "crosswalk": crosswalk,
    }


def _expected_provenance(profile: Mapping[str, object]) -> dict[str, object]:
    return {
        "contract": "ocd-lib077-provenance-v1",
        "work_id": "luthers-large-catechism",
        "title": profile["title"],
        "creator": profile["creator"],
        "contributor_statement": profile["contributor_statement"],
        "source_format": "Project Gutenberg UTF-8 text with BOM and CRLF framing",
        "source_url": profile["source_url"],
        "source_sha256": profile["source_sha256"],
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "technical_validation_is_human_acceptance": False,
        "rights": {"retained_statement": "Project Gutenberg wrapper states a United States public-domain basis and requires users outside the United States to check local law and the included license.", "worldwide": "unresolved", "publication": "not authorized"},
    }


def _expected_unresolved() -> list[dict[str, object]]:
    return [
        {"id": "luthers-large-catechism-identity", "kind": "identity", "status": "human-review-required", "scope": "title, creator, and contributor roles", "detail": "Retained header role assertions are preserved but not human-accepted."},
        {"id": "luthers-large-catechism-edition", "kind": "edition-witness", "status": "human-review-required", "scope": "whole retained Gutenberg witness", "detail": "Edition and witness identity remain unaccepted."},
        {"id": "luthers-large-catechism-readings", "kind": "substantive-reading-editorial", "status": "human-review-required", "scope": "all retained physical lines", "detail": "No silent correction, modernization, or editorial acceptance was performed."},
        {"id": "luthers-large-catechism-rights", "kind": "rights", "status": "human-review-required", "scope": "jurisdiction, Project Gutenberg license, and trademark terms", "detail": "Worldwide rights and publication permission remain unresolved."},
        {"id": "luthers-large-catechism-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance or publication authorization."},
    ]


def _import_closure_sha256() -> str:
    contract_path = Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)
    return _sha(_canonical({"oracle": _sha(Path(__file__).read_bytes()), "reconstruction-contract": _sha(contract_path.read_bytes())}))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    try:
        profile = _profile(source_manifest)
        content, lines, member = _source(source_manifest)
        records = _records(content, lines)
        accountability = _strict_json(candidate.member_bytes("source-accountability.json"), "accountability")
        schema = _strict_json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "accountability schema")
        findings.extend(error.message for error in Draft202012Validator(schema).iter_errors(accountability))
        if accountability != _expected_accountability(content, member, records):
            findings.append("source accountability does not match independent extraction")

        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        document = etree.ElementTree(root)
        xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
        if not xsd.validate(document):
            findings.extend(str(error) for error in xsd.error_log)
        carriers = root.xpath("//tei:div[@type='source-line']/*[self::tei:ab or self::tei:head]", namespaces={"tei": TEI_NS})
        expected_carriers = [(str(item["id"]), int(item["line"]), str(item["kind"]), str(item["category"]), str(item["text"])) for item in records]
        observed_carriers = []
        for node in carriers:
            parent = node.getparent()
            observed_carriers.append((parent.get(f"{{{XML_NS}}}id", ""), int(node.get("n", "0")), node.get("type", ""), node.get("ana", "").split()[-2] if len(node.get("ana", "").split()) >= 2 else "", "".join(node.itertext())))
        if observed_carriers != [(identifier, line, kind, f"#{category}", text) for identifier, line, kind, category, text in expected_carriers]:
            findings.append("TEI source-line carriers do not match independent source extraction")

        if _strict_json(candidate.member_bytes("provenance.json"), "provenance") != _expected_provenance(profile):
            findings.append("candidate provenance drift")
        unresolved = [_strict_json(line + b"\n", "unresolved") for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
        if unresolved != _expected_unresolved():
            findings.append("unresolved human-boundary records drift")
        if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-readme").read_bytes():
            findings.append("source README attribution drift")
        validator = source_manifest.record["validator"]
        if validator["import_closure_sha256"] != _import_closure_sha256():
            findings.append("oracle import closure drift")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError, etree.XMLSyntaxError, etree.DocumentInvalid) as exc:
        findings.append(str(exc))

    bindings = _validation_authority_bindings(source_manifest)
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _import_closure_sha256(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        **bindings,
        "findings": sorted(str(item) for item in findings),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION

