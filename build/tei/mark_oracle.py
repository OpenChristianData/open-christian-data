"""Producer-independent oracle for the retained whole-Mark candidate."""

from __future__ import annotations

import ast
import hashlib
import html
import json
import platform
from pathlib import Path
import re
import sys
from typing import Mapping
from urllib.parse import quote

from lxml import etree
from jsonschema import Draft202012Validator

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-mark-source-to-tei-oracle"
ORACLE_VERSION = "1"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SAFE = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
_EXTRA = {
    "&emdash;": "-",
    "&mdash;": "-",
    "&ndash;": "-",
    "&lsquo;": "'",
    "&rsquo;": "'",
    "&ldquo;": '"',
    "&rdquo;": '"',
    "&nbsp;": " ",
}
def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(content: bytes, label: str) -> dict[str, object]:
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


def _profile_mapping(profile: Mapping[str, object]) -> dict[str, dict[str, str]]:
    if (
        profile.get("contract") != "ocd-mark-rich-tei-profile-v2"
        or profile.get("profile_id") != "mark-rich-tei-v1"
        or profile.get("version") != 2
    ):
        raise ValueError("Mark reconstruction profile identity mismatch")
    dispositions = profile.get("feature_dispositions")
    if not isinstance(dispositions, dict) or not dispositions:
        raise ValueError("Mark reconstruction profile has no feature dispositions")
    result: dict[str, dict[str, str]] = {}
    for source_tag, disposition in dispositions.items():
        if (
            not isinstance(source_tag, str)
            or not isinstance(disposition, dict)
            or not isinstance(disposition.get("tei"), str)
            or set(disposition) - {"tei", "type"}
            or ("type" in disposition and not isinstance(disposition["type"], str))
        ):
            raise ValueError("Mark reconstruction profile feature mapping is invalid")
        result[source_tag] = {str(key): str(value) for key, value in disposition.items()}
    return result


def _entity(match: re.Match[str]) -> str:
    value = match.group(0)
    if value in _SAFE:
        return value
    if value in _EXTRA:
        return _EXTRA[value]
    decoded = html.unescape(value)
    return "" if decoded == value else decoded


def _source_body(content: bytes) -> etree._Element:
    try:
        text = content.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", content, 0, 1, "replacement found")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _entity, text)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        root = etree.fromstring(text.encode("utf-8"), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Mark source is not parseable") from exc
    bodies = [
        item
        for item in root
        if isinstance(item.tag, str) and etree.QName(item).localname == "ThML.body"
    ]
    if len(bodies) != 1:
        raise ValueError("Mark source body count mismatch")
    return bodies[0]


def _selector(node: etree._Element, body: etree._Element) -> str:
    chain: list[str] = []
    cursor = node
    while cursor is not body:
        parent = cursor.getparent()
        if parent is None:
            raise ValueError("Mark source node escaped body")
        local = etree.QName(cursor).localname
        occurrence = 0
        for sibling in parent:
            if isinstance(sibling.tag, str) and etree.QName(sibling).localname == local:
                occurrence += 1
            if sibling is cursor:
                break
        chain.insert(0, f"{local}[{occurrence}]")
        cursor = parent
    result = "/ThML/ThML.body[1]/" + "/".join(chain)
    return result + (
        "[@id=" + json.dumps(node.get("id")) + "]" if node.get("id") else ""
    )


def _expected_attributes(
    tag: str,
    source_id: str | None,
    source: Mapping[str, str],
    tei_id: str,
    source_id_map: Mapping[str, str],
) -> tuple[dict[str, str], list[dict[str, object]]]:
    attrs = {"xml:id": tei_id}
    rend = [
        f"source-{name}:{source[name]}"
        for name in ("class", "style", "progress", "type")
        if source.get(name)
    ]
    if tag == "i":
        rend.insert(0, "italic")
    if rend:
        attrs["rend"] = "; ".join(rend)
    if tag in {"div", "div1", "div2"}:
        attrs["type"] = (
            {"i": "title-page", "ii": "contents", "xix": "indexes"}.get(
                source_id, "chapter"
            )
            if tag == "div1"
            else ("commentary-section" if tag == "div2" else "source-division")
        )
    elif tag == "a":
        attrs["type"] = "source-navigation"
    elif tag in {"scripRef", "scripCom"}:
        attrs["type"] = "scripture" if tag == "scripRef" else "scripture-commentary"
        if source.get("osisRef"):
            attrs["corresp"] = "urn:osis:" + quote(source["osisRef"], safe=":.-")
            if tag == "scripRef":
                attrs["cRef"] = source["osisRef"].replace("Bible:", "")
        if source.get("passage"):
            attrs["n"] = source["passage"]
        if source.get("parsed"):
            attrs["source"] = "urn:ccel-thml-parsed:" + quote(
                source["parsed"], safe=""
            )
    elif tag == "note" and source.get("n"):
        attrs["n"] = source["n"]
    elif tag == "insertIndex":
        attrs["unit"] = "source-index"
    elif tag == "blockquote":
        attrs["type"] = "block"
    elif tag == "verse":
        attrs["type"] = "verse"
    elif tag in {"h1", "h2", "h3", "h4"}:
        attrs["type"] = "heading"
    dispositions: list[dict[str, object]] = []
    for name, value in source.items():
        item: dict[str, object] = {
            "source_name": name,
            "source_value": value,
            "disposition": "represented",
        }
        if name == "id":
            item.update(target_name="xml:id", target_value=tei_id)
        elif name in {"class", "style", "progress", "type"}:
            item.update(target_name="rend", target_value=attrs["rend"])
        elif name in {"prev", "next"}:
            destination = source_id_map.get(value)
            if destination is None:
                item.update(
                    disposition="excluded",
                    reason_code="unresolved-source-pointer",
                    reason="source pointer names no element in the retained ThML body",
                )
            else:
                attrs[name] = f"#{destination}"
                item.update(target_name=name, target_value=attrs[name])
        elif name == "href":
            base, separator, fragment = value.rpartition("#")
            if not separator or fragment not in source_id_map:
                raise ValueError("Mark source href is unresolved")
            attrs["target"] = base + "#" + source_id_map[fragment]
            item.update(target_name="target", target_value=attrs["target"])
        elif name == "title":
            item.update(
                target_name="child::head[@type='source-title']", target_value=value
            )
        elif name == "n":
            item.update(target_name="n", target_value=attrs["n"])
        elif name == "osisRef":
            item.update(target_name="corresp", target_value=attrs["corresp"])
        elif name == "parsed":
            item.update(target_name="source", target_value=attrs["source"])
        elif name == "passage":
            item.update(target_name="n", target_value=attrs["n"])
        else:
            raise ValueError(f"unmapped Mark source attribute: {name}")
        dispositions.append(item)
    return attrs, dispositions


def _verify_crosswalk(
    source_bytes: bytes,
    tei_bytes: bytes,
    accountability: Mapping[str, object],
    profile_mapping: Mapping[str, Mapping[str, str]],
) -> int:
    body = _source_body(source_bytes)
    source_elements = [
        item for item in body.iterdescendants() if isinstance(item.tag, str)
    ]
    if len(source_elements) != 2405:
        raise ValueError("Mark independent source inventory is not 2,405")
    crosswalk = accountability.get("crosswalk")
    if not isinstance(crosswalk, list) or len(crosswalk) != 2405:
        raise ValueError("Mark crosswalk omission or duplication")
    source_ids = [item.get("id") for item in source_elements if item.get("id")]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Mark source IDs are duplicated")
    unavailable = set(source_ids) | {"mark-whole-body"}
    tei_ids: list[str] = []
    for ordinal, source in enumerate(source_elements, start=1):
        source_id = source.get("id")
        if source_id:
            tei_id = source_id
        else:
            stem = f"mark-generated-{ordinal:05d}"
            tei_id = stem
            suffix = 1
            while tei_id in unavailable:
                tei_id = f"{stem}-{suffix}"
                suffix += 1
            unavailable.add(tei_id)
        tei_ids.append(tei_id)
    source_id_map = {
        source_id: tei_id
        for source_id, tei_id in zip(source_ids, [
            tei_ids[index]
            for index, item in enumerate(source_elements)
            if item.get("id")
        ], strict=True)
    }
    try:
        tei = etree.fromstring(tei_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Mark candidate TEI is not parseable") from exc
    if etree.QName(tei).text != f"{{{_TEI_NS}}}TEI" or not compiled_schema().validate(tei):
        raise ValueError("Mark candidate failed TEI P5 XSD")
    tei_body = tei.find(f".//{{{_TEI_NS}}}body")
    if tei_body is None or tei_body.get(_XML_ID) != "mark-whole-body":
        raise ValueError("Mark TEI body identity mismatch")
    observed_ids = [
        item.get(_XML_ID)
        for item in tei_body.iterdescendants()
        if item.get(_XML_ID) in set(tei_ids)
    ]
    if observed_ids != tei_ids:
        raise ValueError("Mark TEI feature order, omission, or duplication")
    expected_descendants = len(source_elements) + sum(
        item.get("title") is not None for item in source_elements
    )
    if len(list(tei_body.iterdescendants())) != expected_descendants:
        raise ValueError("Mark TEI contains omitted or invented body events")
    excluded = 0
    disposition_count = 0
    for ordinal, (source, observed, tei_id) in enumerate(
        zip(source_elements, crosswalk, tei_ids, strict=True), start=1
    ):
        if not isinstance(observed, dict):
            raise ValueError("Mark crosswalk entry is not an object")
        tag = etree.QName(source).localname
        if tag not in profile_mapping:
            raise ValueError(f"Mark independent inventory found unmapped tag {tag}")
        source_attrs = {
            etree.QName(name).localname: value
            for name, value in sorted(source.attrib.items())
        }
        expected_attrs, expected_dispositions = _expected_attributes(
            tag, source.get("id"), source_attrs, tei_id, source_id_map
        )
        declared_type = profile_mapping[tag].get("type")
        if declared_type is not None and expected_attrs.get("type") != declared_type:
            raise ValueError(f"Mark profile type mapping is not honored for {tag}")
        disposition_count += len(expected_dispositions)
        excluded += sum(item["disposition"] == "excluded" for item in expected_dispositions)
        parent = source.getparent()
        if parent is body:
            parent_id = "mark-whole-body"
        else:
            parent_id = tei_ids[source_elements.index(parent)]
        sibling_ordinal = [
            item for item in parent if isinstance(item.tag, str)
        ].index(source) + 1
        expected_core = {
            "feature_id": f"mark-feature-{ordinal:05d}",
            "source_selector": _selector(source, body),
            "source_tag": tag,
            "source_xml_id": source.get("id"),
            "attributes": source_attrs,
            "direct_text": source.text or "",
            "tail_text": source.tail or "",
            "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
            "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
            "tei_tag": profile_mapping[tag]["tei"],
            "tei_xml_id": tei_id,
            "tei_parent_id": parent_id,
            "tei_child_ordinal": sibling_ordinal,
            "tei_attributes": expected_attrs,
            "attribute_dispositions": expected_dispositions,
            "disposition": "represented",
            "tei_selector": f"#{tei_id}",
        }
        for key, value in expected_core.items():
            if observed.get(key) != value:
                raise ValueError(f"Mark crosswalk {key} mutation at feature {ordinal}")
        assertion = observed.get("assertion")
        if not isinstance(assertion, dict) or assertion != {
            "id": f"mark-account-{ordinal:05d}",
            "profile": "mark-rich-tei-v1",
            "role": "source-feature-accountability",
            "layer": "witness-evidence",
            "status": "represented",
            "asserted_by": "ocd-mark-thml-to-tei",
            "method": "exact-source-feature-crosswalk",
            "evidence": [{"type": "source-selector", "value": expected_core["source_selector"]}],
            "subject": {"type": "tei-xml-id", "value": tei_id},
            "destination": {"type": "tei-xml-id", "value": tei_id},
        }:
            raise ValueError(f"Mark assertion mutation at feature {ordinal}")
        targets = tei.xpath(
            "//*[@xml:id=$value]",
            value=tei_id,
            namespaces={"xml": "http://www.w3.org/XML/1998/namespace"},
        )
        if len(targets) != 1:
            raise ValueError("Mark TEI target omission or duplication")
        target = targets[0]
        actual_attrs = {
            ("xml:id" if name == _XML_ID else name): value
            for name, value in target.attrib.items()
        }
        if (
            etree.QName(target).localname != profile_mapping[tag]["tei"]
            or actual_attrs != expected_attrs
            or (target.text or "") != (source.text or "")
            or (target.tail or "") != (source.tail or "")
            or target.getparent().get(_XML_ID) != parent_id
        ):
            raise ValueError("Mark TEI feature misattachment, invention, or text mutation")
        title = source.get("title")
        heads = target.xpath(
            "./tei:head[@type='source-title']", namespaces={"tei": _TEI_NS}
        )
        if title is not None and (len(heads) != 1 or heads[0].text != title):
            raise ValueError("Mark source title projection mutation")
    if (
        accountability.get("contract") != "ocd-mark-source-accountability-v1"
        or accountability.get("schema") != "mark.source-accountability.schema.json"
        or accountability.get("feature_count") != 2405
        or accountability.get("attribute_disposition_count") != disposition_count
        or accountability.get("deliberately_excluded_attribute_count") != excluded
        or accountability.get("omitted_feature_count") != 0
        or accountability.get("unresolved_feature_count") != 0
    ):
        raise ValueError("Mark accountability summary mutation")
    return len(source_elements)


def _verify_header(
    tei_bytes: bytes,
    *,
    source_sha256: str,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
) -> None:
    header_policy = policy.get("tei_header")
    identity = profile.get("identity")
    if not isinstance(header_policy, dict) or not isinstance(identity, dict):
        raise ValueError("bound Mark header authorities are invalid")
    transcription = identity.get("source_transcription")
    if not isinstance(transcription, dict):
        raise ValueError("bound Mark transcription identity is invalid")
    if (
        header_policy.get("title") != transcription.get("title")
        or header_policy.get("author") != transcription.get("author")
        or header_policy.get("availability_status") != "restricted"
    ):
        raise ValueError("bound Mark header policy contradicts the profile")

    def element(name: str, attributes: dict[str, str] | None = None, text: str | None = None):
        node = etree.Element(f"{{{_TEI_NS}}}{name}", attributes or {})
        node.text = text
        return node

    expected = etree.Element(f"{{{_TEI_NS}}}teiHeader", nsmap={None: _TEI_NS})
    file_desc = element("fileDesc")
    expected.append(file_desc)
    title_stmt = element("titleStmt")
    title_stmt.append(element("title", text=str(header_policy["title"])))
    title_stmt.append(element("author", text=str(header_policy["author"])))
    contributors = header_policy.get("contributors")
    if not isinstance(contributors, list) or any(not isinstance(item, str) for item in contributors):
        raise ValueError("bound Mark header contributors are invalid")
    for contributor in contributors:
        resp_stmt = element("respStmt")
        resp_stmt.append(element("resp", text="Contributor"))
        resp_stmt.append(element("name", text=contributor))
        title_stmt.append(resp_stmt)
    file_desc.append(title_stmt)
    publication_stmt = element("publicationStmt")
    publication_stmt.append(element("publisher", text="Open Christian Data"))
    availability = element("availability", {"status": "restricted"})
    availability.append(element("p", text=str(header_policy["rights_statement"])))
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    source_desc = element("sourceDesc")
    bibl = element("bibl")
    bibl.append(element("ptr", {"target": str(header_policy["source_url"])}))
    bibl.append(element("idno", {"type": "sha256"}, source_sha256))
    bibl.append(
        element("note", {"type": "print-source"}, str(header_policy["print_source"]))
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    observed_root = etree.fromstring(tei_bytes)
    observed = observed_root.find(f"{{{_TEI_NS}}}teiHeader")
    def record(node: etree._Element) -> tuple[object, ...]:
        text = node.text or ""
        if not text.strip():
            text = ""
        return (
            etree.QName(node).text,
            tuple(sorted(node.attrib.items())),
            text,
            tuple(record(child) for child in node if isinstance(child.tag, str)),
        )

    if observed is None or record(observed) != record(expected):
        raise ValueError("Mark TEI header metadata, rights, or provenance mutation")


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    paths = {
        Path(__file__).resolve(),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/tei/validate.py").resolve(strict=True),
    }
    forbidden = tuple(policy.get("forbidden_import_prefixes", []))
    records = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("oracle closure contains forbidden dynamic import or execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"oracle closure contains forbidden import {name}")
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha(path.read_bytes()),
            }
        )
    return _sha(
        (json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    candidate_manifest = candidate.manifest
    expected_source_path = source_manifest.path.relative_to(root).as_posix()
    if (
        candidate_manifest.get("source_manifest")
        != {"path": expected_source_path, "sha256": source_manifest.sha256}
        or candidate_manifest.get("converter") != source_manifest.record["converter"]
        or candidate_manifest.get("package_schema")
        != source_manifest.record["package_schema"]
        or candidate_manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("Mark candidate weakened an authority binding")
    source = source_manifest.authority_path("retained-thml").read_bytes()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    permission = source_manifest.authority_path("ccel-permission").read_bytes()
    profile = _json(profile_bytes, "Mark reconstruction profile")
    profile_mapping = _profile_mapping(profile)
    accountability = _json(
        candidate.member_bytes("source-accountability.json"),
        "source-accountability.json",
    )
    accountability_schema_bytes = source_manifest.authority_path(
        "source-accountability-schema"
    ).read_bytes()
    accountability_schema = _json(
        accountability_schema_bytes, "Mark source-accountability schema"
    )
    schema_errors = sorted(
        Draft202012Validator(accountability_schema).iter_errors(accountability), key=str
    )
    if schema_errors:
        raise ValueError(
            f"Mark source-accountability schema failure: {schema_errors[0].message}"
        )
    tei_bytes = candidate.member_bytes("content.tei.xml")
    count = _verify_crosswalk(
        source,
        tei_bytes,
        accountability,
        profile_mapping,
    )
    provenance = _json(candidate.member_bytes("provenance.json"), "provenance.json")
    authorities = provenance.get("authorities")
    expected_authorities = {
        str(item["name"]): {
            "path": item["path"],
            "sha256": item["sha256"],
            "bytes": item["bytes"],
            "role": item["role"],
        }
        for item in source_manifest.record["authorities"]
    }
    rights = provenance.get("rights")
    if (
        provenance.get("contract") != "ocd-mark-candidate-provenance-v1"
        or provenance.get("status") != "nonaccepted"
        or authorities != expected_authorities
        or not isinstance(rights, dict)
        or rights.get("permission_authority") != "ccel-permission"
        or rights.get("status") != "human-review-required-for-acceptance"
        or b"sourced via CCEL.org" not in candidate.member_bytes("README.source.md")
        or b"do not sell CCEL files or derivatives of their formatting" not in permission
    ):
        raise ValueError("Mark provenance or rights mutation")
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
        if line.strip()
    ]
    if {item.get("id") for item in unresolved} != {
        "mark-print-collation-not-performed",
        "mark-rights-acceptance-review",
    }:
        raise ValueError("Mark unresolved ledger mutation")
    policy = _json(policy_bytes, "Mark validation policy")
    _verify_header(
        tei_bytes,
        source_sha256=_sha(source),
        profile=profile,
        policy=policy,
    )
    if policy.get("required_feature_count") != count:
        raise ValueError("Mark validation policy was weakened")
    xsd = source_manifest.authority_path("tei-p5-xsd").read_bytes()
    implementation = Path(__file__).resolve()
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(xsd),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(
        (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
