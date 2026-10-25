"""Independent verifier for the LIB-027 Boethius faithful-TEI candidate."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping
from xml.parsers import expat

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate


ORACLE_ID = "ocd-boethius-theological-tractates-independent-oracle"
ORACLE_VERSION = "1"
SOURCE_PATH = "raw/ccel/boethius/tracts.xml"
SOURCE_SHA256 = "406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8"
SOURCE_BYTES = 162_005
SELECTED_DIV1 = "iv"
DIV1_IDS = ("i", "ii", "iii", "iv", "v")
TRACTATE_IDS = ("iv.i", "iv.ii", "iv.iii", "iv.iv", "iv.v")
EXPECTED_COUNTS = {
    "b": 3,
    "div1": 1,
    "div2": 5,
    "h2": 1,
    "h3": 1,
    "i": 188,
    "note": 59,
    "p": 297,
    "pb": 64,
    "scripRef": 1,
    "span": 60,
    "sup": 1,
    "sync": 88,
    "unclear": 9,
}
TAG_MAP = {
    "b": "hi",
    "div1": "div",
    "div2": "div",
    "h2": "ab",
    "h3": "ab",
    "i": "hi",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripRef": "ref",
    "span": "foreign",
    "sup": "hi",
    "sync": "anchor",
    "unclear": "unclear",
}
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
RIGHTS_STATEMENT = (
    "The local source config labels the underlying text public domain. CCEL "
    "permits parsing its ThML; do not sell CCEL files or derivatives of CCEL "
    "formatting. Attribution is included in README.source.md. Human acceptance "
    "and publication remain absent."
)


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
        raise ValueError(f"{label} must be a JSON object")
    return value


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _parse_source(content: bytes) -> etree._ElementTree:
    try:
        root = etree.fromstring(
            content,
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                remove_blank_text=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("oracle rejected malformed retained Boethius XML") from exc
    return etree.ElementTree(root)


def _source_scope(
    tree: etree._ElementTree,
) -> tuple[list[etree._Element], etree._Element]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("oracle found no retained ThML.body")
    divisions = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if tuple(node.get("id") for node in divisions) != DIV1_IDS:
        raise ValueError("oracle div1 census or order drift")
    matches = [node for node in divisions if node.get("id") == SELECTED_DIV1]
    if len(matches) != 1:
        raise ValueError("oracle selected div1 census drift")
    tractates = [node for node in matches[0] if node.tag == "div2"]
    if tuple(node.get("id") for node in tractates) != TRACTATE_IDS:
        raise ValueError("oracle five-tract member census drift")
    return divisions, matches[0]


def _source_spans(content: bytes) -> list[dict[str, object]]:
    parser = expat.ParserCreate()
    stack: list[dict[str, object]] = []
    records: list[dict[str, object]] = []

    def opened(name: str, attributes: dict[str, str]) -> None:
        selected = bool(stack and stack[-1]["selected"]) or (
            name == "div1" and attributes.get("id") == SELECTED_DIV1
        )
        item: dict[str, object] = {
            "tag": name,
            "start": parser.CurrentByteIndex,
            "selected": selected,
        }
        stack.append(item)
        if selected:
            records.append(item)

    def closed(name: str) -> None:
        if not stack:
            raise ValueError("oracle byte parser stack underflow")
        item = stack.pop()
        if item["tag"] != name:
            raise ValueError("oracle byte parser topology mismatch")
        if not item["selected"]:
            return
        start = int(item["start"])
        opening_end = content.find(b">", start) + 1
        if content[start:opening_end].rstrip().endswith(b"/>"):
            end = opening_end
        else:
            end = content.find(b">", parser.CurrentByteIndex) + 1
        if opening_end <= 0 or end < opening_end:
            raise ValueError("oracle byte parser found an incomplete tag")
        raw = content[start:end]
        item.update(end=end, bytes=len(raw), sha256=_sha(raw))

    parser.StartElementHandler = opened
    parser.EndElementHandler = closed
    try:
        parser.Parse(content, True)
    except expat.ExpatError as exc:
        raise ValueError("oracle byte parser rejected retained source") from exc
    if stack or len(records) != 778 or any("end" not in item for item in records):
        raise ValueError("oracle byte-span census drift")
    return records


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _el(
    localname: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    normalized: dict[str, str] = {}
    for name, value in (attributes or {}).items():
        if name == "xml:id":
            normalized[XML_ID] = value
        elif name == "xml:lang":
            normalized[XML_LANG] = value
        else:
            normalized[name] = value
    node = etree.Element(
        f"{{{TEI_NS}}}{localname}",
        normalized,
        nsmap={None: TEI_NS} if localname == "TEI" else None,
    )
    if text is not None:
        node.text = text
    return node


def _target_attributes(source: etree._Element, ordinal: int) -> dict[str, str]:
    source_id = source.get("id")
    result = {
        "xml:id": "boethius-" + (
            _safe_id(source_id) if source_id else f"feature-{ordinal:04d}"
        )
    }
    tag = str(source.tag)
    if tag == "b":
        result["rend"] = "bold"
    elif tag == "i":
        result["rend"] = "italic"
    elif tag == "sup":
        result["rend"] = "superscript"
    elif tag in {"div1", "div2", "h2", "h3"}:
        result["type"] = f"source-{tag}"
    elif tag == "p":
        if source.get("class"):
            result["rend"] = str(source.get("class"))
        if source.get("style"):
            result["rendition"] = str(source.get("style"))
    elif tag == "note" and source.get("n"):
        result["n"] = str(source.get("n"))
    elif tag == "pb":
        if source.get("n"):
            result["n"] = str(source.get("n"))
        if source.get("href"):
            result["facs"] = str(source.get("href"))
    elif tag == "scripRef":
        result["type"] = "scripture"
        if source.get("passage"):
            result["cRef"] = str(source.get("passage"))
        if source.get("osisRef"):
            result["target"] = str(source.get("osisRef"))
    elif tag == "span":
        if source.get("lang") == "EL":
            result["xml:lang"] = "grc"
        if source.get("class"):
            result["rend"] = str(source.get("class"))
    return result


def _normalized_attributes(node: etree._Element) -> dict[str, str]:
    return {
        ("xml:id" if name == XML_ID else "xml:lang" if name == XML_LANG else name): value
        for name, value in node.attrib.items()
    }


def _project(
    source: etree._Element,
    parent: etree._Element,
    spans: list[dict[str, object]],
    rows: list[dict[str, object]],
    parent_feature: str | None,
    scope_root: etree._Element,
) -> None:
    ordinal = len(rows) + 1
    span = spans[ordinal - 1]
    if span["tag"] != source.tag:
        raise ValueError("oracle source element and byte orders disagree")
    feature = f"boethius-feature-{ordinal:04d}"
    target = _el(TAG_MAP[str(source.tag)], _target_attributes(source, ordinal))
    target.text = source.text or ""
    target.tail = "" if source is scope_root else source.tail or ""
    parent.append(target)
    rows.append(
        {
            "feature_id": feature,
            "parent_feature_id": parent_feature,
            "source_selector": _selector(source),
            "source_tag": source.tag,
            "source_xml_id": source.get("id"),
            "source_attributes": dict(source.attrib),
            "source_direct_text": source.text or "",
            "source_tail_text": "" if source is scope_root else source.tail or "",
            "source_direct_text_sha256": _sha((source.text or "").encode("utf-8")),
            "source_tail_text_sha256": _sha(
                ("" if source is scope_root else source.tail or "").encode("utf-8")
            ),
            "source_byte_start": span["start"],
            "source_byte_end": span["end"],
            "source_byte_count": span["bytes"],
            "source_bytes_sha256": span["sha256"],
            "tei_tag": TAG_MAP[str(source.tag)],
            "tei_xml_id": target.get(XML_ID),
            "tei_parent_id": parent.get(XML_ID),
            "tei_child_ordinal": len(parent),
            "tei_attributes": _normalized_attributes(target),
            "disposition": "represented-exactly",
        }
    )
    for child in source:
        if not isinstance(child.tag, str) or child.tag not in TAG_MAP:
            raise ValueError("oracle found unsupported selected-scope node")
        _project(child, target, spans, rows, feature, scope_root)


def _config(source_manifest: SourceManifest) -> dict[str, object]:
    record = _strict_json(
        source_manifest.authority_path("local-source-config").read_bytes(),
        "Boethius source config",
    )
    pinned = {
        "resource_id": "boethius-theological-tractates",
        "title": "The Theological Tractates",
        "author": "Boethius",
        "contributors": [
            "H.F. Stewart (translator, 1918)",
            "E.K. Rand (translator, 1918)",
        ],
        "source_hash": f"sha256:{SOURCE_SHA256}",
        "source_url": "https://www.ccel.org/ccel/boethius/tracts.xml",
        "source_format": "ThML XML",
        "license": "public-domain",
        "output_file": "data/structured-text/boethius-theological-tractates.json",
        "notes": "CCEL confirmed OK to parse. Crawl-delay 10s per robots.txt. Extracted from div1 id='iv' (all five div2 tractates).",
    }
    if any(record.get(key) != value for key, value in pinned.items()):
        raise ValueError("oracle detected authoritative config metadata drift")
    return record


def _expected_surfaces(
    source_manifest: SourceManifest,
) -> tuple[dict[str, bytes], dict[str, object]]:
    source = source_manifest.authority_path("retained-thml").read_bytes()
    if len(source) != SOURCE_BYTES or _sha(source) != SOURCE_SHA256:
        raise ValueError("oracle retained source identity mismatch")
    config = _config(source_manifest)
    tree = _parse_source(source)
    divisions, selected = _source_scope(tree)
    features = [node for node in selected.iter() if isinstance(node.tag, str)]
    counts = dict(sorted(Counter(str(node.tag) for node in features).items()))
    attributes = sum(len(node.attrib) for node in features)
    if len(features) != 778 or counts != EXPECTED_COUNTS or attributes != 1_208:
        raise ValueError("oracle selected source census drift")
    spans = _source_spans(source)

    root = _el("TEI", {"xml:id": "boethius-theological-tractates-lib027"})
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", text=str(config["title"])))
    title_stmt.append(_el("author", text=str(config["author"])))
    for name, role in (
        ("H.F. Stewart", "translator, 1918"),
        ("E.K. Rand", "translator, 1918"),
    ):
        responsibility = _el("respStmt")
        responsibility.append(_el("resp", text=role))
        responsibility.append(_el("name", text=name))
        title_stmt.append(responsibility)
    file_desc.append(title_stmt)
    publication = _el("publicationStmt")
    publication.append(_el("publisher", text="Open Christian Data"))
    availability = _el("availability", {"status": "restricted"})
    availability.append(_el("p", text=RIGHTS_STATEMENT))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _el("sourceDesc")
    bibliography = _el("bibl")
    bibliography.append(_el("ptr", {"target": str(config["source_url"])}))
    bibliography.append(_el("idno", {"type": "sha256"}, SOURCE_SHA256))
    bibliography.append(
        _el("note", {"type": "print-source"}, str(config["source_edition"]))
    )
    source_desc.append(bibliography)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    text = _el("text")
    body = _el("body", {"xml:id": "boethius-theological-tractates-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, object]] = []
    _project(selected, body, spans, rows, None, selected)

    division_accounting = [
        {
            "ordinal": ordinal,
            "div1_id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": (
                "selected-work-represented"
                if node.get("id") == SELECTED_DIV1
                else "excluded-sibling-work"
            ),
        }
        for ordinal, node in enumerate(divisions, start=1)
    ]
    tractate_accounting = [
        {
            "ordinal": ordinal,
            "div2_id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": "represented-exactly",
        }
        for ordinal, node in enumerate(
            [child for child in selected if child.tag == "div2"], start=1
        )
    ]
    accountability = {
        "contract": "ocd-boethius-theological-tractates-source-accountability-v1",
        "schema": "boethius-theological-tractates.source-accountability.schema.json",
        "profile_id": "boethius-theological-tractates-div1-iv-v1",
        "source_scope": "ThML.body/div1[@id='iv'] with all five direct div2 tractates",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": SOURCE_BYTES,
            "sha256": SOURCE_SHA256,
        },
        "selected_byte_range": {
            "start": spans[0]["start"],
            "end": spans[0]["end"],
            "bytes": spans[0]["bytes"],
            "sha256": spans[0]["sha256"],
        },
        "feature_count": 778,
        "attribute_count": 1_208,
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "invented_feature_count": 0,
        "division_accounting": division_accounting,
        "tractate_accounting": tractate_accounting,
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-boethius-theological-tractates-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": SOURCE_PATH,
            "bytes": SOURCE_BYTES,
            "sha256": SOURCE_SHA256,
            "url": config["source_url"],
            "format": config["source_format"],
            "edition": config["source_edition"],
        },
        "scope": {"div1_id": SELECTED_DIV1, "div2_ids": list(TRACTATE_IDS)},
        "work": {
            "resource_id": config["resource_id"],
            "title": config["title"],
            "author": config["author"],
            "author_id": config["author_id"],
            "contributors": config["contributors"],
            "language": config["language"],
            "original_language": config["original_language"],
            "license_claim": config["license"],
            "schema_type": config["schema_type"],
            "work_kind": config["work_kind"],
        },
        "human_acceptance": "absent",
        "publication": "not_ready",
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "boethius-print-collation-not-performed",
            "status": "unresolved",
            "question": "Does the retained CCEL XML differ from the identified 1918 print edition?",
            "evidence": "This candidate is bound to the retained CCEL XML; no print collation was performed.",
        },
        {
            "id": "boethius-human-acceptance-and-publication",
            "status": "unresolved",
            "question": "Will a maintainer accept this candidate and separately authorize publication?",
            "evidence": "Technical verification is not human textual acceptance, a rights decision, or publication authorization.",
        },
    ]
    surfaces = {
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": source_manifest.authority_path(
            "source-local-attribution-readme"
        ).read_bytes(),
    }
    return surfaces, accountability


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    paths = policy.get("oracle_import_closure")
    forbidden = policy.get("forbidden_oracle_imports")
    if not isinstance(paths, list) or not paths or not isinstance(forbidden, list):
        raise ValueError("oracle validation policy closure is invalid")
    records = []
    for logical in paths:
        if not isinstance(logical, str):
            raise ValueError("oracle closure path is invalid")
        path = (root / logical).resolve(strict=True)
        content = path.read_bytes()
        text = content.decode("utf-8")
        if any(isinstance(name, str) and name in text for name in forbidden):
            raise ValueError("oracle has forbidden producer or converter import")
        records.append({"path": logical, "sha256": _sha(content)})
    return _sha(_canonical(records))


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != source_manifest.record.get("source_id")
        or candidate.manifest.get("source_manifest")
        != {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "sha256": source_manifest.sha256,
        }
    ):
        raise ValueError("candidate authority or boundary drift")

    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "Boethius reconstruction profile")
    policy = _strict_json(policy_bytes, "Boethius validation policy")
    if (
        profile.get("contract")
        != "ocd-boethius-theological-tractates-reconstruction-profile-v1"
        or profile.get("profile_id") != "boethius-theological-tractates-div1-iv-v1"
        or profile.get("feature_count") != 778
        or profile.get("attribute_count") != 1_208
        or policy.get("contract")
        != "ocd-boethius-theological-tractates-validation-policy-v1"
        or policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_state") != "not_ready"
    ):
        raise ValueError("Boethius profile or policy drift")

    expected, accountability = _expected_surfaces(source_manifest)
    for name, content in expected.items():
        if candidate.member_bytes(name) != content:
            raise ValueError(f"candidate {name} is not the complete faithful projection")

    accountability_observed = _strict_json(
        candidate.member_bytes("source-accountability.json"),
        "candidate source accountability",
    )
    schema_bytes = source_manifest.authority_path("source-accountability-schema").read_bytes()
    schema = _strict_json(schema_bytes, "source-accountability schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(accountability_observed), key=str
    )
    if errors:
        raise ValueError(f"source accountability schema failure: {errors[0].message}")
    if accountability_observed != accountability:
        raise ValueError("candidate source accountability drift")

    tei_content = candidate.member_bytes("content.tei.xml")
    try:
        tei = etree.ElementTree(etree.fromstring(tei_content))
        compiled = etree.XMLSchema(
            etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
        )
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError) as exc:
        raise ValueError("direct TEI P5 validation setup failed") from exc
    if not compiled.validate(tei):
        raise ValueError(f"direct TEI P5 XSD failure: {compiled.error_log.last_error}")

    root = source_manifest.repository_root
    implementation = Path(__file__).resolve(strict=True)
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": SOURCE_SHA256,
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    manifest = SourceManifest.load(
        arguments.source_manifest, repository_root=arguments.repository_root
    )
    report = validate(manifest, CandidatePackage.load(arguments.candidate), _oracle)
    print(report.sha256)


if __name__ == "__main__":
    main()


__all__: tuple[str, ...] = ()
