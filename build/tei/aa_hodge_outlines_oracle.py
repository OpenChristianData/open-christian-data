"""Producer-independent validator for the A. A. Hodge faithful-TEI candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from build.lib.tei_xsd import compiled_tei_schema


ORACLE_ID = "ocd-aa-hodge-outlines-independent-oracle"
ORACLE_VERSION = "1"
SOURCE_SHA256 = "a81808d5a9d2037d3c1d0706de960fb13c175d3581dd131c7d505493df51fee5"
SOURCE_BYTES = 1_976_207
SOURCE_LINES = 37_553
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
_FIRST_PARTY_IMPORT_PATHS = (
    "build/__init__.py",
    "build/lib/__init__.py",
    "build/lib/tei_xsd.py",
    "build/tei/aa_hodge_outlines_oracle.py",
)
QUESTION_RE = re.compile(rb"^[\t ]*([0-9]+)\.[\t ]+")
CHAPTER_RE = re.compile(rb"^[\t ]*CHAPTER[\t ]+", re.IGNORECASE)
_EXPECTED_AUTHORITY_NAMES = (
    "retained-djvutxt",
    "local-source-config",
    "q7-diagnostic-fixture",
    "source-readme",
    "reconstruction-profile",
    "source-accountability-schema",
    "validation-policy",
    "tei-p5-xsd",
    "tei-p5-xsd-teix",
    "tei-p5-xsd-xml",
    "candidate-package-schema",
)
_EXPECTED_Q7_AUTHORITY = {
    "name": "q7-diagnostic-fixture",
    "path": "tests/fixtures/gutenberg_systematics/aa_hodge_q7_span.txt",
    "role": "bounded-diagnostic-evidence-not-whole-work-acceptance",
    "bytes": 1_630,
    "sha256": "6711666f19ca7c869c0e6601f40f5bb03ab02280976c2292c99fa9ee70e36034",
}
_EXPECTED_AUTHORITY_RECORDS = {
    "retained-djvutxt": {
        "name": "retained-djvutxt",
        "path": "raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt",
        "durable_path": "D:/Library/Open Christian Data/raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt",
        "role": "primary-source",
        "bytes": 1_976_207,
        "sha256": "a81808d5a9d2037d3c1d0706de960fb13c175d3581dd131c7d505493df51fee5",
    },
    "local-source-config": {
        "name": "local-source-config",
        "path": "sources/catechisms/aa-hodge-outlines/config.json",
        "role": "local-metadata-claim-evidence",
        "bytes": 1_324,
        "sha256": "d0e7575f9947c65edaf7435b5cd189a0dc458718a192d880a686991602489c75",
    },
    "q7-diagnostic-fixture": _EXPECTED_Q7_AUTHORITY,
    "source-readme": {
        "name": "source-readme",
        "path": "sources/catechisms/aa-hodge-outlines/README.source.md",
        "role": "local-source-readme",
        "bytes": 1_201,
        "sha256": "156879fcd495f87ade60f37fec99b3a74f23116be00fcfa96aec556fcfafd599",
    },
    "reconstruction-profile": {
        "name": "reconstruction-profile",
        "path": "sources/catechisms/aa-hodge-outlines/aa-hodge-outlines.reconstruction-profile.json",
        "role": "complete-source-feature-profile",
        "bytes": 1_936,
        "sha256": "703605c51852a544fcda606024bda7f7375bd969110ae902b3b150cfc59a5c53",
    },
    "source-accountability-schema": {
        "name": "source-accountability-schema",
        "path": "sources/catechisms/aa-hodge-outlines/aa-hodge-outlines.source-accountability.schema.json",
        "role": "complete-source-accountability-schema",
        "bytes": 2_242,
        "sha256": "3fcd40fc463e9f4575484d9e889d8692f8f5b5a2804ed97c5f9e5a9e564f7df8",
    },
    "validation-policy": {
        "name": "validation-policy",
        "path": "sources/catechisms/aa-hodge-outlines/aa-hodge-outlines.validation-policy.json",
        "role": "independent-validation-policy",
        "bytes": 1_383,
        "sha256": "d9bfdc69b3ec6d95298d91ba794aa11407846f20defd67f481f0d48498c68b55",
    },
    "tei-p5-xsd": {
        "name": "tei-p5-xsd",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
        "role": "tei-validation-schema",
        "bytes": 1_108_622,
        "sha256": "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f",
    },
    "tei-p5-xsd-teix": {
        "name": "tei-p5-xsd-teix",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
        "role": "tei-validation-schema-dependency",
        "bytes": 2_202,
        "sha256": "51ab8c0071f2abc375090829acadf7cb57c707fe17a993cdb2213e84932a6fac",
    },
    "tei-p5-xsd-xml": {
        "name": "tei-p5-xsd-xml",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
        "role": "tei-validation-schema-dependency",
        "bytes": 2_359,
        "sha256": "4f3a8348802f3bc968cbdd2a9d54a38a0549e5e4e7bc8d4338404f85f89568ba",
    },
    "candidate-package-schema": {
        "name": "candidate-package-schema",
        "path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
        "role": "candidate-package-schema",
        "bytes": 2_173,
        "sha256": "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3",
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority(source_manifest: object, name: str) -> tuple[Mapping[str, object], Path]:
    record = getattr(source_manifest, "record")
    authorities = record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("name") == name:
            return authority, getattr(source_manifest, "authority_path")(name)
    raise ValueError(f"missing authority {name}")


def _role_authority(source_manifest: object, role: str) -> Mapping[str, object]:
    authorities = getattr(source_manifest, "record").get("authorities")
    matches = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == role
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {role} authority")
    return matches[0]


def _verify_authorities(source_manifest: object) -> None:
    authorities = getattr(source_manifest, "record").get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    names = tuple(
        authority.get("name")
        for authority in authorities
        if isinstance(authority, Mapping)
    )
    if names != _EXPECTED_AUTHORITY_NAMES:
        raise ValueError("source manifest authority inventory drifted")
    for authority in authorities:
        if not isinstance(authority, Mapping) or not isinstance(
            authority.get("name"), str
        ):
            raise ValueError("source manifest authority is invalid")
        expected_record = _EXPECTED_AUTHORITY_RECORDS.get(authority["name"])
        if expected_record is None or dict(authority) != expected_record:
            raise ValueError(f"{authority['name']} authority record drift")
        content = getattr(source_manifest, "authority_path")(
            authority["name"]
        ).read_bytes()
        if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(
            content
        ):
            raise ValueError(f"{authority['name']} authority bytes drift")


def _source_lines(source_manifest: object) -> tuple[bytes, tuple[bytes, ...]]:
    _, path = _authority(source_manifest, "retained-djvutxt")
    content = path.read_bytes()
    if len(content) != SOURCE_BYTES or _sha(content) != SOURCE_SHA256:
        raise ValueError("retained source identity drift")
    if not content.endswith(b"\n") or content.count(b"\n") != SOURCE_LINES:
        raise ValueError("retained source line framing drift")
    content.decode("utf-8", errors="strict")
    lines = tuple(content.split(b"\n")[:-1])
    if len(lines) != SOURCE_LINES:
        raise ValueError("retained source line count drift")
    return content, lines


def _role(line: bytes) -> str:
    if CHAPTER_RE.match(line):
        return "chapter-candidate"
    if QUESTION_RE.match(line):
        return "question-candidate"
    return "source-line"


def _expected_tei_bytes(lines: tuple[bytes, ...]) -> bytes:
    """Independently serialize the one exact TEI projection authorized by the source."""

    def append(
        parent: etree._Element,
        name: str,
        attributes: tuple[tuple[str, str], ...] = (),
        text: str | None = None,
    ) -> etree._Element:
        child = etree.SubElement(
            parent,
            f"{{{TEI_NS}}}{name}",
            attrib=dict(attributes),
        )
        child.text = text
        return child

    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", "aa-hodge-outlines-candidate")
    header = append(root, "teiHeader")
    file_desc = append(header, "fileDesc")
    title_stmt = append(file_desc, "titleStmt")
    append(
        title_stmt,
        "title",
        text="Outlines of Theology: faithful OCR transcription candidate",
    )
    append(title_stmt, "author", text="A. A. Hodge")
    responsibility = append(title_stmt, "respStmt")
    append(responsibility, "resp", text="Exact source-line transcription")
    append(responsibility, "name", text="Open Christian Data")
    publication = append(file_desc, "publicationStmt")
    append(publication, "publisher", text="Open Christian Data")
    availability = append(
        publication,
        "availability",
        (("status", "restricted"),),
    )
    append(
        availability,
        "p",
        text=(
            "Nonaccepted candidate; publication is not authorized; "
            "human rights review is required."
        ),
    )
    source_desc = append(file_desc, "sourceDesc")
    bibl = append(
        source_desc,
        "bibl",
        ((f"{{{XML_NS}}}id", "hodge-retained-source"),),
    )
    append(bibl, "title", text="Outlines of Theology")
    append(bibl, "author", text="A. A. Hodge")
    append(
        bibl,
        "edition",
        text=(
            "Robert Carter & Bros., New York, 1879; "
            "Internet Archive DjVuTXT OCR witness"
        ),
    )
    append(
        bibl,
        "idno",
        (("type", "URI"),),
        "https://archive.org/download/outlinesoftheolo1879hodg/"
        "outlinesoftheolo1879hodg_djvu.txt",
    )
    append(bibl, "idno", (("type", "SHA-256"),), SOURCE_SHA256)
    append(
        bibl,
        "extent",
        text=f"{SOURCE_BYTES} bytes; {SOURCE_LINES} LF-terminated physical lines",
    )
    append(
        bibl,
        "note",
        (("type", "source-format"),),
        "DjVuTXT (OCR); UTF-8; no normalization or OCR cleanup",
    )
    append(
        bibl,
        "note",
        (("type", "edition-status"),),
        "Edition and textual identity require human review.",
    )
    encoding = append(header, "encodingDesc")
    project = append(encoding, "projectDesc")
    append(
        project,
        "p",
        text=(
            "Every retained OCR source line is represented once, verbatim, "
            "and in source order."
        ),
    )
    append(
        project,
        "p",
        text=(
            "catechism_qa structure is carried only as noneditorial question "
            "and chapter candidate annotations."
        ),
    )
    profile = append(header, "profileDesc")
    classification = append(profile, "textClass")
    keywords = append(classification, "keywords")
    append(keywords, "term", text="catechism_qa")
    append(keywords, "term", text="OCR transcription")
    revision = append(header, "revisionDesc")
    append(
        revision,
        "change",
        (("status", "draft"),),
        "Deterministic nonaccepted candidate generated from the pinned witness.",
    )
    text = append(root, "text")
    body = append(text, "body")
    division = append(
        body,
        "div",
        (
            (f"{{{XML_NS}}}id", "hodge-verbatim-ocr"),
            ("type", "catechism_qa"),
            ("subtype", "ocr-source-transcription"),
        ),
    )
    for number, line in enumerate(lines, start=1):
        role = _role(line)
        annotations = "#source-line"
        if role != "source-line":
            annotations += f" #{role}"
        append(
            division,
            "ab",
            (
                (f"{{{XML_NS}}}id", f"hodge-line-{number:06d}"),
                ("n", str(number)),
                ("ana", annotations),
            ),
            line.decode("utf-8"),
        )
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


def _expected_crosswalk(lines: tuple[bytes, ...]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(lines, start=1):
        source_bytes = line + b"\n"
        end = offset + len(source_bytes)
        line_id = f"hodge-line-{number:06d}"
        records.append(
            {
                "id": line_id,
                "line_number": number,
                "byte_start": offset,
                "byte_end": end,
                "bytes": len(source_bytes),
                "sha256": _sha(source_bytes),
                "role": _role(line),
                "status": "represented",
                "target": f"#{line_id}",
            }
        )
        offset = end
    if offset != SOURCE_BYTES:
        raise ValueError("independent source byte accounting does not close")
    return records


def _validate_profile_and_policy(
    source_manifest: object,
) -> tuple[dict[str, object], dict[str, object]]:
    _, profile_path = _authority(source_manifest, "reconstruction-profile")
    _, policy_path = _authority(source_manifest, "validation-policy")
    profile = _strict_json(profile_path.read_bytes(), "reconstruction profile")
    policy = _strict_json(policy_path.read_bytes(), "validation policy")
    expected_source = {
        "durable_path": "D:/Library/Open Christian Data/raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt",
        "logical_path": "raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt",
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
        "physical_lines": SOURCE_LINES,
        "terminal_lf": True,
    }
    if profile.get("source") != expected_source:
        raise ValueError("profile source identity drift")
    if profile.get("coverage") != {
        "physical_lines": SOURCE_LINES,
        "represented_lines": SOURCE_LINES,
        "omitted_lines": 0,
        "duplicated_lines": 0,
    }:
        raise ValueError("profile coverage drift")
    structure = profile.get("structure")
    if not isinstance(structure, dict) or structure.get("identity") != "catechism_qa":
        raise ValueError("profile structure identity drift")
    if (
        structure.get("question_candidates") != 1_107
        or structure.get("chapter_candidates") != 85
    ):
        raise ValueError("profile structural count drift")
    if profile.get("diagnostic_fixture") != {
        "path": "tests/fixtures/gutenberg_systematics/aa_hodge_q7_span.txt",
        "checkout_bytes": 1_630,
        "checkout_sha256": "6711666f19ca7c869c0e6601f40f5bb03ab02280976c2292c99fa9ee70e36034",
        "source_span_lines": "16538-16567",
        "source_span_lf_bytes": 1_630,
        "source_span_lf_sha256": "6711666f19ca7c869c0e6601f40f5bb03ab02280976c2292c99fa9ee70e36034",
        "whole_work_acceptance": False,
    }:
        raise ValueError("bounded diagnostic fixture identity drift")
    if (
        policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_authorized") is not False
    ):
        raise ValueError("validation policy acceptance drift")
    if policy.get("ocr_cleanup_performed") is not False:
        raise ValueError("validation policy OCR-cleanup drift")
    return profile, policy


def _validate_tei(
    source_manifest: object, candidate: object, lines: tuple[bytes, ...]
) -> None:
    content = getattr(candidate, "member_bytes")("content.tei.xml")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_blank_text=False
    )
    root = etree.fromstring(content, parser)
    _, xsd_path = _authority(source_manifest, "tei-p5-xsd")
    compiled_tei_schema(xsd_path).assertValid(etree.ElementTree(root))
    if content != _expected_tei_bytes(lines):
        raise ValueError("TEI serialized bytes drift")
    if root.tag != f"{{{TEI_NS}}}TEI" or root.attrib != {
        f"{{{XML_NS}}}id": "aa-hodge-outlines-candidate"
    }:
        raise ValueError("TEI root identity drift")
    if [child.tag for child in root] != [f"{{{TEI_NS}}}teiHeader", f"{{{TEI_NS}}}text"]:
        raise ValueError("TEI root structure drift")
    header = root[0]
    if len(header.xpath(".//*")) != 32:
        raise ValueError("TEI header invention or omission")
    expected_text = {
        "./tei:fileDesc/tei:titleStmt/tei:title": "Outlines of Theology: faithful OCR transcription candidate",
        "./tei:fileDesc/tei:titleStmt/tei:author": "A. A. Hodge",
        "./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:resp": "Exact source-line transcription",
        "./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name": "Open Christian Data",
        "./tei:fileDesc/tei:publicationStmt/tei:publisher": "Open Christian Data",
        "./tei:fileDesc/tei:publicationStmt/tei:availability/tei:p": "Nonaccepted candidate; publication is not authorized; human rights review is required.",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:title": "Outlines of Theology",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:author": "A. A. Hodge",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:edition": "Robert Carter & Bros., New York, 1879; Internet Archive DjVuTXT OCR witness",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='URI']": "https://archive.org/download/outlinesoftheolo1879hodg/outlinesoftheolo1879hodg_djvu.txt",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='SHA-256']": SOURCE_SHA256,
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:extent": "1976207 bytes; 37553 LF-terminated physical lines",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='source-format']": "DjVuTXT (OCR); UTF-8; no normalization or OCR cleanup",
        "./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='edition-status']": "Edition and textual identity require human review.",
        "./tei:encodingDesc/tei:projectDesc/tei:p[1]": "Every retained OCR source line is represented once, verbatim, and in source order.",
        "./tei:encodingDesc/tei:projectDesc/tei:p[2]": "catechism_qa structure is carried only as noneditorial question and chapter candidate annotations.",
        "./tei:profileDesc/tei:textClass/tei:keywords/tei:term[1]": "catechism_qa",
        "./tei:profileDesc/tei:textClass/tei:keywords/tei:term[2]": "OCR transcription",
        "./tei:revisionDesc/tei:change": "Deterministic nonaccepted candidate generated from the pinned witness.",
    }
    for xpath, expected in expected_text.items():
        matches = header.xpath(xpath, namespaces=NS)
        if len(matches) != 1 or matches[0].text != expected:
            raise ValueError(f"TEI metadata or provenance drift at {xpath}")
    availability = header.xpath(
        "./tei:fileDesc/tei:publicationStmt/tei:availability", namespaces=NS
    )[0]
    if availability.attrib != {"status": "restricted"}:
        raise ValueError("TEI availability drift")
    bibl = header.xpath("./tei:fileDesc/tei:sourceDesc/tei:bibl", namespaces=NS)[0]
    if bibl.attrib != {f"{{{XML_NS}}}id": "hodge-retained-source"}:
        raise ValueError("TEI source identity drift")
    change = header.xpath("./tei:revisionDesc/tei:change", namespaces=NS)[0]
    if change.attrib != {"status": "draft"}:
        raise ValueError("TEI candidate status drift")
    divisions = root.xpath("./tei:text/tei:body/tei:div", namespaces=NS)
    if len(divisions) != 1 or divisions[0].attrib != {
        f"{{{XML_NS}}}id": "hodge-verbatim-ocr",
        "type": "catechism_qa",
        "subtype": "ocr-source-transcription",
    }:
        raise ValueError("TEI catechism_qa carrier drift")
    nodes = list(divisions[0])
    if len(nodes) != SOURCE_LINES or any(
        node.tag != f"{{{TEI_NS}}}ab" for node in nodes
    ):
        raise ValueError("TEI source-line omission, duplication, or invention")
    reconstructed: list[bytes] = []
    for number, (node, source_line) in enumerate(
        zip(nodes, lines, strict=True), start=1
    ):
        expected_role = _role(source_line)
        expected_ana = "#source-line" + (
            f" #{expected_role}" if expected_role != "source-line" else ""
        )
        expected_attributes = {
            f"{{{XML_NS}}}id": f"hodge-line-{number:06d}",
            "n": str(number),
            "ana": expected_ana,
        }
        if node.attrib != expected_attributes or len(node) or node.tail is not None:
            raise ValueError(
                f"TEI source-line order or annotation drift at line {number}"
            )
        observed_text = node.text or ""
        expected_text_value = source_line.decode("utf-8")
        if observed_text != expected_text_value:
            raise ValueError(f"TEI source text drift at line {number}")
        reconstructed.append(observed_text.encode("utf-8") + b"\n")
    if b"".join(reconstructed) != b"\n".join(lines) + b"\n":
        raise ValueError("TEI lossless source reconstruction failed")


def _expected_handoff() -> tuple[dict[str, object], dict[str, object]]:
    request_core: dict[str, object] = {
        "contract": "ocd-ezraocr-request-v1",
        "work_id": "aa-hodge-outlines",
        "source_manifest_id": "aa-hodge-outlines-whole-work-v1",
        "source_members": [
            {
                "id": "outlinesoftheolo1879hodg-djvutxt",
                "bytes": SOURCE_BYTES,
                "sha256": SOURCE_SHA256,
                "physical_lines": SOURCE_LINES,
                "order": 1,
            }
        ],
        "page_census": {
            "status": "unavailable",
            "ordered_page_ids": [],
            "reason": "The retained DjVuTXT witness has no retained page-boundary markers.",
        },
        "requested_operation": "byte-identical pass-through; no OCR correction authorized",
    }
    request = {**request_core, "request_digest": _sha(_canonical(request_core))}
    result_core: dict[str, object] = {
        "contract": "ocd-ezraocr-result-v1",
        "request_digest": request["request_digest"],
        "status": "pass-through",
        "ocr_correction_status": "not-performed",
        "corrected_text_sha256": SOURCE_SHA256,
        "corrected_text_bytes": SOURCE_BYTES,
        "returned_physical_lines": SOURCE_LINES,
        "returned_page_census": request_core["page_census"],
        "unresolved_readings": {
            "scope": "all 37553 retained OCR source lines",
            "status": "human-review-required",
        },
    }
    return request, {**result_core, "result_digest": _sha(_canonical(result_core))}


def _validate_json_members(
    source_manifest: object, candidate: object, lines: tuple[bytes, ...]
) -> None:
    package = _strict_json(
        getattr(candidate, "member_bytes")("manifest.json"), "candidate manifest"
    )
    _, package_schema_path = _authority(source_manifest, "candidate-package-schema")
    package_schema = _strict_json(
        package_schema_path.read_bytes(), "candidate package schema"
    )
    errors = sorted(Draft202012Validator(package_schema).iter_errors(package), key=str)
    if errors:
        raise ValueError(f"candidate manifest schema failure: {errors[0].message}")
    manifest_path = (
        getattr(source_manifest, "path")
        .relative_to(getattr(source_manifest, "repository_root"))
        .as_posix()
    )
    expected_package = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": getattr(source_manifest, "record")["source_id"],
        "source_manifest": {
            "path": manifest_path,
            "sha256": getattr(source_manifest, "sha256"),
        },
        "converter": dict(getattr(source_manifest, "record")["converter"]),
        "package_schema": dict(getattr(source_manifest, "record")["package_schema"]),
        "members": package.get("members"),
    }
    if package != expected_package:
        raise ValueError("candidate manifest provenance or binding drift")
    records = _expected_crosswalk(lines)
    expected_counts = {
        "source_bytes": SOURCE_BYTES,
        "physical_lines": SOURCE_LINES,
        "represented_lines": SOURCE_LINES,
        "question_candidates": sum(
            item["role"] == "question-candidate" for item in records
        ),
        "chapter_candidates": sum(
            item["role"] == "chapter-candidate" for item in records
        ),
        "omitted_lines": 0,
        "duplicated_lines": 0,
    }
    accountability = _strict_json(
        getattr(candidate, "member_bytes")("source-accountability.json"),
        "source accountability",
    )
    _, accountability_schema_path = _authority(
        source_manifest, "source-accountability-schema"
    )
    accountability_schema = _strict_json(
        accountability_schema_path.read_bytes(), "source accountability schema"
    )
    errors = sorted(
        Draft202012Validator(accountability_schema).iter_errors(accountability), key=str
    )
    if errors:
        raise ValueError(f"source accountability schema failure: {errors[0].message}")
    expected_accountability = {
        "contract": "ocd-aa-hodge-outlines-source-accountability-v1",
        "profile_id": "aa-hodge-outlines-whole-work-v1",
        "source_sha256": SOURCE_SHA256,
        "counts": expected_counts,
        "crosswalk_sha256": _sha(_canonical(records)),
        "crosswalk": records,
    }
    if accountability != expected_accountability:
        raise ValueError("source-accountability crosswalk drift")
    request, result = _expected_handoff()
    expected_provenance = {
        "contract": "ocd-aa-hodge-outlines-provenance-v1",
        "work_id": "aa-hodge-outlines",
        "title": "Outlines of Theology",
        "author": "A. A. Hodge",
        "source_edition": "Robert Carter & Bros., New York, 1879. IA:outlinesoftheolo1879hodg.",
        "source_format": "DjVuTXT (OCR)",
        "source_url": "https://archive.org/download/outlinesoftheolo1879hodg/outlinesoftheolo1879hodg_djvu.txt",
        "source_sha256": SOURCE_SHA256,
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "rights": {
            "united_states": "1879 publication supports a public-domain claim; human confirmation remains required for publication",
            "worldwide": "unresolved",
            "scan_and_ocr_layer_terms": "unresolved",
        },
        "handoff_request": request,
        "handoff_result": result,
    }
    provenance = _strict_json(
        getattr(candidate, "member_bytes")("provenance.json"), "provenance"
    )
    if provenance != expected_provenance:
        raise ValueError("candidate provenance or handoff drift")
    expected_unresolved = [
        {
            "id": "hodge-ocr-readings",
            "kind": "substantive-reading",
            "status": "human-review-required",
            "scope": "all 37553 retained OCR source lines",
            "detail": "No OCR cleanup or silent normalization was performed.",
        },
        {
            "id": "hodge-edition-identity",
            "kind": "edition-witness",
            "status": "human-review-required",
            "scope": "whole work",
            "detail": "The retained scan/OCR witness is not an accepted critical or authorial edition.",
        },
        {
            "id": "hodge-rights",
            "kind": "rights",
            "status": "human-review-required",
            "scope": "worldwide and scan/OCR-layer terms",
            "detail": "Publication remains unauthorized pending human rights review.",
        },
        {
            "id": "hodge-acceptance",
            "kind": "acceptance-publication",
            "status": "human-review-required",
            "scope": "whole candidate",
            "detail": "Technical validation is not textual acceptance or publication authorization.",
        },
    ]
    unresolved_content = getattr(candidate, "member_bytes")("unresolved.jsonl")
    try:
        unresolved = [
            _strict_json(line + b"\n", "unresolved record")
            for line in unresolved_content.splitlines()
        ]
    except ValueError as exc:
        raise ValueError("unresolved evidence drift") from exc
    if unresolved != expected_unresolved:
        raise ValueError("unresolved human boundary drift")
    _, readme_path = _authority(source_manifest, "source-readme")
    if (
        getattr(candidate, "member_bytes")("README.source.md")
        != readme_path.read_bytes()
    ):
        raise ValueError("candidate README drift")


def _import_closure_sha256(repository_root: Path) -> str:
    root = Path(repository_root).resolve(strict=True)
    return _sha(_canonical([
        {"path": logical, "sha256": _sha((root / logical).read_bytes())}
        for logical in _FIRST_PARTY_IMPORT_PATHS
    ]))


def _oracle(source_manifest: object, candidate: object) -> dict[str, object]:
    getattr(source_manifest, "verify")()
    _verify_authorities(source_manifest)
    getattr(candidate, "verify_integrity")()
    source_content, lines = _source_lines(source_manifest)
    _validate_profile_and_policy(source_manifest)
    _validate_tei(source_manifest, candidate, lines)
    _validate_json_members(source_manifest, candidate, lines)
    implementation_sha256 = _sha(Path(__file__).read_bytes())
    import_closure_sha256 = _import_closure_sha256(getattr(source_manifest, "repository_root"))
    validator = getattr(source_manifest, "record")["validator"]
    if validator.get("implementation_sha256") != implementation_sha256:
        raise ValueError("oracle implementation drift")
    if validator.get("import_closure_sha256") != import_closure_sha256:
        raise ValueError("oracle import closure drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha256,
        "import_closure_sha256": import_closure_sha256,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": getattr(source_manifest, "sha256"),
        "candidate_sha256": getattr(candidate, "sha256"),
        "profile_sha256": _role_authority(
            source_manifest, "complete-source-feature-profile"
        )["sha256"],
        "package_schema_sha256": _role_authority(
            source_manifest, "candidate-package-schema"
        )["sha256"],
        "source_sha256": _sha(source_content),
        "xsd_sha256": _role_authority(source_manifest, "tei-validation-schema")[
            "sha256"
        ],
        "policy_sha256": _role_authority(
            source_manifest, "independent-validation-policy"
        )["sha256"],
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
