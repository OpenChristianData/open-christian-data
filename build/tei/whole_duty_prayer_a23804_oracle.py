"""Independent structural, byte-preservation, and P5 oracle for TCP A23804."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from typing import Mapping
from xml.etree import ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-tcp-a23804-independent-source-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict:
    def reject(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label}: duplicate key {key}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label}: object required")
    return value


def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _direct(parent: ET.Element | None, local: str) -> list[ET.Element]:
    if parent is None:
        return []
    expanded = f"{{{TEI_NS}}}{local}"
    return [item for item in list(parent) if item.tag == expanded]


def _descendants(parent: ET.Element, local: str) -> list[ET.Element]:
    expanded = f"{{{TEI_NS}}}{local}"
    return [item for item in parent.iter() if item.tag == expanded]


def _text(node: ET.Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _inspect(content: bytes) -> tuple[ET.Element, dict[str, int], dict[str, int], dict[str, object]]:
    builder = ET.TreeBuilder(insert_comments=True, insert_pis=True)
    root = ET.fromstring(content, parser=ET.XMLParser(target=builder))
    nodes = list(root.iter())
    elements = [item for item in nodes if isinstance(item.tag, str)]
    counts = dict(sorted(Counter(_local(item.tag) for item in elements).items()))
    census = {
        "elements": len(elements),
        "attributes": sum(len(item.attrib) for item in elements),
        "text_nodes": sum(item.text is not None for item in elements),
        "tail_nodes": sum(item.tail is not None for item in elements),
        "characters": sum(len((item.text or "") + (item.tail or "")) for item in elements),
        "comments": sum(not isinstance(item.tag, str) and getattr(item.tag, "__name__", "") == "Comment" for item in nodes),
        "processing_instructions": sum(not isinstance(item.tag, str) and getattr(item.tag, "__name__", "") == "ProcessingInstruction" for item in nodes),
    }
    header = _direct(root, "teiHeader")
    file_desc = _direct(header[0] if len(header) == 1 else None, "fileDesc")
    title_stmt = _direct(file_desc[0] if len(file_desc) == 1 else None, "titleStmt")
    source_desc = _direct(file_desc[0] if len(file_desc) == 1 else None, "sourceDesc")
    bibl_full = _direct(source_desc[0] if len(source_desc) == 1 else None, "biblFull")
    notes_stmt = _direct(bibl_full[0] if len(bibl_full) == 1 else None, "notesStmt")
    root_texts = _direct(root, "text")
    groups = _direct(root_texts[0] if len(root_texts) == 1 else None, "group")
    work_texts = _direct(groups[0] if len(groups) == 1 else None, "text")
    front = _direct(work_texts[0] if len(work_texts) == 1 else None, "front")
    body = _direct(work_texts[0] if len(work_texts) == 1 else None, "body")
    back = _direct(work_texts[0] if len(work_texts) == 1 else None, "back")
    divisions = _descendants(root, "div")
    page_breaks = _descendants(root, "pb")
    gaps = _descendants(root, "gap")
    glyphs = _descendants(root, "g")
    features: dict[str, object] = {
        "root": _local(root.tag),
        "namespace": root.tag[1:].split("}", 1)[0] if isinstance(root.tag, str) and root.tag.startswith("{") else None,
        "tei_corpus_count": len(_descendants(root, "teiCorpus")),
        "title_statement_count": len(title_stmt),
        "title_statement_titles": [_text(item) for item in _direct(title_stmt[0] if len(title_stmt) == 1 else None, "title")],
        "title_statement_authors": [_text(item) for item in _direct(title_stmt[0] if len(title_stmt) == 1 else None, "author")],
        "dlps_ids": [
            _text(item)
            for item in _direct(file_desc[0] if len(file_desc) == 1 else None, "publicationStmt")
            for item in _direct(item, "idno")
            if item.get("type") == "DLPS"
        ],
        "top_level_text_count": len(root_texts),
        "top_level_text_children": [_local(item.tag) for item in list(root_texts[0])] if len(root_texts) == 1 else [],
        "grouped_work_text_count": len(work_texts),
        "grouped_work_children": [_local(item.tag) for item in list(work_texts[0])] if len(work_texts) == 1 else [],
        "front_div_types": [item.get("type") for item in _direct(front[0] if len(front) == 1 else None, "div")],
        "body_div_types": [item.get("type") for item in _direct(body[0] if len(body) == 1 else None, "div")],
        "back_div_types": [item.get("type") for item in _direct(back[0] if len(back) == 1 else None, "div")],
        "source_notes": [_text(item) for item in _direct(notes_stmt[0] if len(notes_stmt) == 1 else None, "note")],
        "division_count": len(divisions),
        "division_types": dict(sorted(Counter(item.get("type") or "(untyped)" for item in divisions).items())),
        "head_count": len(_descendants(root, "head")),
        "page_breaks": [[item.get("n"), item.get("facs")] for item in page_breaks],
        "gap_count": len(gaps),
        "gap_reasons": dict(sorted(Counter(item.get("reason") or "(unspecified)" for item in gaps).items())),
        "glyph_references": dict(sorted(Counter(item.get("ref") or "(unreferenced)" for item in glyphs).items())),
        "graphic_count": len(_descendants(root, "graphic")),
        "facs_attribute_count": sum("facs" in item.attrib for item in elements),
        "note_signature_values": [_text(item) for item in _descendants(root, "signed")],
    }
    return root, counts, census, features


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    paths = (
        Path(__file__).resolve(),
        root / "ocd_kernel/__init__.py",
        root / "ocd_kernel/reconstruction/__init__.py",
        root / "ocd_kernel/reconstruction/contract.py",
    )
    return _sha(
        _canonical(
            [
                {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
                for path in paths
            ]
        )
    )


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source = source_manifest.authority_path("retained-tei-p5").read_bytes()
    content = candidate.member_bytes("content.tei.xml")
    profile = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "profile")
    policy = _strict_json(source_manifest.authority_path("validation-policy").read_bytes(), "policy")
    findings: list[str] = []
    expected_manifest = {
        "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if candidate.manifest.get("status") != "nonaccepted":
        findings.append("candidate is not explicitly nonaccepted")
    if candidate.manifest.get("source_id") != source_manifest.record["source_id"]:
        findings.append("candidate source identity differs")
    if candidate.manifest.get("source_manifest") != expected_manifest:
        findings.append("candidate source-manifest binding differs")
    converter_record = dict(source_manifest.record["converter"])
    if candidate.manifest.get("converter") != converter_record:
        findings.append("candidate converter binding differs")
    package_schema = dict(source_manifest.record["package_schema"])
    if candidate.manifest.get("package_schema") != package_schema:
        findings.append("candidate package-schema binding differs")
    if _sha(source) != profile["source_sha256"] or len(source) != profile["source_bytes"]:
        findings.append("retained source byte binding differs")
    if content != source:
        findings.append("candidate TEI is not byte-identical to retained TCP A23804 XML")
    identity = {
        "work_id": source_manifest.record["work_id"],
        "textual_form_id": source_manifest.record["textual_form_id"],
        "edition_id": source_manifest.record["edition_id"],
        "acquisition_id": source_manifest.record["acquisition_id"],
    }
    if policy.get("identity") != identity:
        findings.append("source policy work/edition/acquisition identity differs")
    try:
        source_root, counts, census, features = _inspect(source)
        if (counts, census, features) != (
            profile["element_counts"], profile["source_census"], profile["source_features"]
        ):
            findings.append("retained source independent census/features differ")
        title = "The whole duty of prayer containing devotions for every day in the week, and for several occasions, ordinary and extraordinary / by the author of The whole duty of man ..."
        if (
            source_root.tag != f"{{{TEI_NS}}}TEI"
            or features["tei_corpus_count"] != 0
            or features["title_statement_count"] != 1
            or features["title_statement_titles"] != [title]
            or features["title_statement_authors"] != ["Allestree, Richard, 1619-1681."]
            or features["dlps_ids"] != ["A23804"]
            or features["top_level_text_count"] != 1
            or features["top_level_text_children"] != ["group"]
            or features["grouped_work_text_count"] != 1
            or features["grouped_work_children"] != ["front", "body", "back"]
            or features["front_div_types"] != ["title_page", "preface"]
            or features["body_div_types"] != ["part", "title_page", "part"]
            or features["back_div_types"] != ["table"]
            or features["page_breaks"] == []
            or features["gap_count"] == 0
            or features["graphic_count"] != 0
            or not any(
                "No absolute certainty has yet been reached regarding the authorship" in note
                and "preponderance of opinion" in note
                for note in features["source_notes"]
            )
            or not any(
                "Additional devotions for several occasions" in note
                and "special t.p." in note
                for note in features["source_notes"]
            )
            or not any("incorrectly identified" in note and "Wing A1195A" in note for note in features["source_notes"])
            or "G. B." not in features["note_signature_values"]
        ):
            findings.append("A23804 source identity, one-work boundary, internal devotions, or qualification differs")
    except (ET.ParseError, ValueError) as exc:
        source_root, counts, census, features = None, {}, {}, {}
        findings.append(f"retained source XML/feature inspection failed: {exc}")
    acquisition_receipt = _strict_json(
        source_manifest.authority_path("acquisition-receipt").read_bytes(), "acquisition receipt"
    )
    acquisition = _strict_json(
        source_manifest.authority_path("canonical-acquisition-sidecar").read_bytes(), "acquisition sidecar"
    )
    work = _strict_json(source_manifest.authority_path("canonical-work-sidecar").read_bytes(), "work sidecar")
    if (
        acquisition_receipt.get("source_id") != "tcp-A23804"
        or acquisition_receipt.get("member", {}).get("sha256") != _sha(source)
        or acquisition.get("acquisition_id") != identity["acquisition_id"]
        or acquisition.get("edition_id") != identity["edition_id"]
        or acquisition.get("source_sha256") != _sha(source)
        or work.get("work_id") != identity["work_id"]
        or work.get("title") != "The whole duty of prayer containing devotions for every day in the week, and for several occasions, ordinary and extraordinary / by the author of The whole duty of man ..."
        or not any(
            form.get("textual_form_id") == identity["textual_form_id"]
            and any(ed.get("edition_id") == identity["edition_id"] for ed in form.get("editions", []))
            for form in work.get("textual_forms", [])
        )
    ):
        findings.append("retained acquisition/work/edition sidecar linkage differs")
    expected_accountability = policy["accountability"] | {
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source),
        "source_content_sha256": _sha(source),
        "candidate_content_bytes": len(content),
        "candidate_content_sha256": _sha(content),
        "element_counts": counts,
        "source_census": census,
        "source_features": features,
    }
    if candidate.member_bytes("source-accountability.json") != _canonical(expected_accountability):
        findings.append("source-accountability package member differs from independent source census")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-local-attribution-readme").read_bytes():
        findings.append("candidate source credit differs from its visible work-local authority")
    if candidate.member_bytes("provenance.json") != _canonical(policy["provenance"]):
        findings.append("candidate provenance differs from the exact source policy")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(row) for row in policy["unresolved"]
    ):
        findings.append("candidate unresolved-evidence record differs from the source policy")
    if source_root is not None and content == source:
        xsd_path = source_manifest.authority_path("tei-p5-xsd")
        schema = etree.XMLSchema(etree.parse(str(xsd_path)))
        candidate_root = etree.fromstring(
            content,
            etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True),
        )
        if not schema.validate(candidate_root):
            findings.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")
    roles = {item["role"]: item for item in source_manifest.record["authorities"]}
    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_digest(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": roles["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": roles["candidate-package-schema"]["sha256"],
        "source_sha256": roles["primary-source"]["sha256"],
        "xsd_sha256": roles["tei-validation-schema"]["sha256"],
        "policy_sha256": roles["independent-validation-policy"]["sha256"],
        "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
