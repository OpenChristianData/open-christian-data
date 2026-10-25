"""Exact accepted Calvin collection: historical source body in member order.

The catalogue and electronic headers stay in the accepted master and private
receipt. No Bible scope or verse association is inferred from source links.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.projection.envelope import row_text_hash
from ocd_kernel.projection.categories import commentary as core


FAMILY = "calvin-collection-source-native-v1"
VERSION = "ocd-calvin-collection-source-body-v1"
TEI = "http://www.tei-c.org/ns/1.0"
NS = f"{{{TEI}}}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
IDENTITY = {
    "work_id": "calvin-commentaries",
    "textual_form_id": "calvin-commentaries-retained-ccel-en",
    "edition_id": "calvin-commentaries-retained-ccel-electronic",
    "acquisition_id": "calvin-commentaries-direct-ccel-xml-set",
}
MASTER_SHA256 = "e20338cfe4174b8bb73659791191e938f6fb193f7a30983abc21fade3485dcce"
SOURCE_SHA256 = "ebeca8edeb83afe01ae9e82477713d178884ca2b45c21daf71dc688b5b6ccfb3"
PROFILE = "sources/commentaries/calvin/calvin-commentaries-title-selection-profile.json"
PROFILE_SHA256 = "98ca44ed9ca890eaeea398ee4690ae0d8f145fcb60c4194421e448a13d5e4b38"
PROVIDER_PARAGRAPHS = {
    "CHRISTIAN CLASSICS ETHEREAL LIBRARY GRAND RAPIDS, MI",
    "http://www.ccel.org",
}
_GENERATED_LOCATOR = re.compile(r"[ivxlcdm]+(?:\.[ivxlcdm]+)*-p\d+(?:\.\d+)?\Z")
_DIV_NUMBER = re.compile(r"[ivxlcdm0-9]+(?:\.[ivxlcdm0-9]+)*\Z")
_SOURCE_DIVS = {"source-div1", "source-div2", "source-div3", "source-div4"}
_SEMANTIC_RENDITIONS = {
    "hi": {"italic", "bold", "superscript", "smallcaps"},
    "foreign": {"Greek"},
    "seg": {"Greek", "Hebrew"},
    "div": {"Commentary", "Index", "Greek", "Hebrew"},
    "p": {"SCRIPTURE", "bbook", "bref"},
    "list": {"Index1"},
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _local(node: Any) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _visible(node: Any) -> str:
    return " ".join("".join(node.itertext()).split())


def _profile(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = Path(metadata["root"]) / PROFILE
    raw = path.read_bytes()
    if _sha(raw) != PROFILE_SHA256:
        raise PipelineError("Calvin title-group source profile differs")
    data = json.loads(raw)
    groups = data.get("groups")
    if not isinstance(groups, list) or len(groups) != 19 or sum(len(g.get("members", [])) for g in groups) != 45:
        raise PipelineError("Calvin source-attested title-group profile differs")
    return groups


def route(metadata: Mapping[str, Any]) -> str | None:
    identity = metadata["acceptance"]["identity"]
    if identity.get("work_id") != IDENTITY["work_id"]:
        return None
    if (identity != IDENTITY or metadata.get("language") != "en"
            or metadata["acceptance"]["source"].get("source_kind") != "retained-member-set"
            or metadata["acceptance"]["source"].get("source_sha256") != SOURCE_SHA256
            or metadata["acceptance"]["representation_revision"].get("id")
            != "calvin-commentaries-retained-collection-v1"
            or len(metadata["acceptance"]["scope"].get("included_members", [])) != 46
            or metadata["acceptance"]["scope"].get("excluded_members")
            or _sha(Path(metadata["master_path"]).read_bytes()) != MASTER_SHA256):
        raise PipelineError("Calvin collection route requires its exact accepted identity and complete source")
    _profile(metadata)
    return FAMILY


def _source_header(root: Any, metadata: Mapping[str, Any]) -> dict[str, str]:
    header = root.find(NS + "teiHeader")
    desc = header.find(NS + "fileDesc/" + NS + "sourceDesc") if header is not None else None
    if desc is None:
        raise PipelineError("Calvin collection source description is missing")
    children = list(desc)
    included = metadata["acceptance"]["scope"]["included_members"]
    if len(children) != 47 or len(included) != 46:
        raise PipelineError("Calvin collection requires 46 source witnesses and one acceptance binding")
    for ordinal, (bibl, expected) in enumerate(zip(children[:-1], included), 1):
        if _local(bibl) != "bibl" or bibl.get("type") != ("catalogue" if ordinal == 1 else "component"):
            raise PipelineError(f"Calvin source bibliography {ordinal} differs")
        ids = {node.get("type"): (node.text or "").strip() for node in bibl if _local(node) == "idno"}
        notes = [node for node in bibl if _local(node) == "note" and node.get("type") == "source-path"]
        if (ids.get("filename") != Path(expected["path"]).name
                or ids.get("sha256") != expected["sha256"]
                or ids.get("bytes") != str(expected["bytes"])
                or len(notes) != 1 or (notes[0].text or "").strip() != expected["path"]):
            raise PipelineError(f"Calvin source bibliography {ordinal} differs from accepted member")
    binding = children[-1]
    if _local(binding) != "bibl" or binding.get("type") != "ocd-acceptance-binding":
        raise PipelineError("Calvin acceptance binding is missing")
    ids = {node.get("type"): (node.text or "").strip() for node in binding if _local(node) == "idno"}
    pointer = [node.get("target") for node in binding if _local(node) == "ptr"]
    if (len(pointer) != 1 or pointer[0] != metadata["acquisition"].get("url")
            or any(ids.get(key) != value for key, value in IDENTITY.items())
            or ids.get("source_kind") != "retained-member-set"
            or ids.get("source_sha256") != SOURCE_SHA256
            or ids.get("representation_revision") != "calvin-commentaries-retained-collection-v1"):
        raise PipelineError("Calvin acceptance binding differs from validated authority")
    result = {"source_url": pointer[0], "source_sha256": SOURCE_SHA256,
              "retained_sha256": SOURCE_SHA256}
    core._validate_accepted_header(result, metadata)
    return result


def _members(root: Any, groups: list[dict[str, Any]]) -> list[tuple[int, int, str, Any, Any]]:
    text = root.find(NS + "text")
    body = text.find(NS + "body") if text is not None else None
    if body is None or len(body) != 19:
        raise PipelineError("Calvin collection requires one body with 19 title groups")
    result = []
    for group_ordinal, (group, expected) in enumerate(zip(body, groups), 1):
        children = list(group)
        if (group.tag != NS + "div" or group.get("type") != "commentary-title-group"
                or group.get("n") != str(group_ordinal)
                or len(children) != len(expected["members"]) + 1
                or children[0].tag != NS + "head"
                or _visible(children[0]) != expected["title"]):
            raise PipelineError(f"Calvin title group {group_ordinal} differs from source-attested profile")
        for in_group, (member, filename) in enumerate(zip(children[1:], expected["members"]), 1):
            if (member.tag != NS + "div" or member.get("type") != "source-member"
                    or member.get("n") != filename or len(member) != 2
                    or [child.get("type") for child in member] != ["source-ThML.head", "source-ThML.body"]):
                raise PipelineError(f"Calvin component {filename} differs from accepted source shape")
            result.append((group_ordinal, in_group, filename, member[0], member[1]))
    if [item[2] for item in result] != [f"calcom{number:02d}.xml" for number in range(1, 46)]:
        raise PipelineError("Calvin collection component order differs")
    return result


def _public_et(unit: ET.Element, removed: Counter[str]) -> ET.Element:
    """Drop electronic imprint/image carriers and private locator/style attributes."""
    public = copy.deepcopy(unit)
    for parent in list(public.iter()):
        for child in list(parent):
            provider = child.tag == NS + "p" and _visible(child) in PROVIDER_PARAGRAPHS
            graphic = child.tag == NS + "graphic"
            if provider or graphic:
                if (child.tail or "").strip() or graphic and ((child.text or "").strip() or len(child)):
                    raise PipelineError("Calvin private carrier contains visible neighboring text")
                parent.remove(child)
                removed["provider-paragraph" if provider else "image-reference"] += 1
    for node in public.iter():
        tag = _local(node)
        n = node.get("n")
        if n is not None and not (
            tag == "ref" and _GENERATED_LOCATOR.fullmatch(n) is None
            or tag == "div" and node.get("type") in _SOURCE_DIVS and _DIV_NUMBER.fullmatch(n)
            or tag == "div" and node.get("type") == "source-div" and n.startswith("Bible:")
        ):
            node.attrib.pop("n", None)
        if node.get("rend") not in _SEMANTIC_RENDITIONS.get(tag, ()):
            node.attrib.pop("rend", None)
        if tag in {"add", "unclear"}:
            node.attrib.pop(XML_ID, None)
            node.attrib.pop("corresp", None)
    return public


def _public_lxml(unit: Any, removed: Counter[str]) -> Any:
    """Independent lxml construction for the checker; source bytes remain input."""
    public = copy.deepcopy(unit)
    for parent in public.iter():
        for child in tuple(parent):
            if child.tag == NS + "p" and _visible(child) in PROVIDER_PARAGRAPHS:
                if (child.tail or "").strip():
                    raise PipelineError("Calvin provider paragraph has a visible tail")
                parent.remove(child)
                removed["provider-paragraph"] += 1
            elif child.tag == NS + "graphic":
                if len(child) or (child.text or "").strip() or (child.tail or "").strip():
                    raise PipelineError("Calvin source graphic has visible text")
                parent.remove(child)
                removed["image-reference"] += 1
    for node in public.iter():
        tag = etree.QName(node).localname
        n = node.get("n")
        if n is not None:
            retained_number = (
                tag == "ref" and re.fullmatch(r"[ivxlcdm]+(?:\.[ivxlcdm]+)*-p\d+(?:\.\d+)?", n) is None
                or tag == "div" and node.get("type") in {"source-div1", "source-div2", "source-div3", "source-div4"}
                and re.fullmatch(r"[ivxlcdm0-9]+(?:\.[ivxlcdm0-9]+)*", n) is not None
                or tag == "div" and node.get("type") == "source-div" and n.startswith("Bible:")
            )
            if not retained_number:
                del node.attrib["n"]
        meaningful_rend = (
            tag == "hi" and node.get("rend") in {"italic", "bold", "superscript", "smallcaps"}
            or tag == "foreign" and node.get("rend") == "Greek"
            or tag == "seg" and node.get("rend") in {"Greek", "Hebrew"}
            or tag == "div" and node.get("rend") in {"Commentary", "Index", "Greek", "Hebrew"}
            or tag == "p" and node.get("rend") in {"SCRIPTURE", "bbook", "bref"}
            or tag == "list" and node.get("rend") == "Index1"
        )
        if not meaningful_rend:
            node.attrib.pop("rend", None)
        if tag in {"add", "unclear"}:
            node.attrib.pop(XML_ID, None)
            node.attrib.pop("corresp", None)
    return public


def _project(metadata: Mapping[str, Any], *, independent: bool) -> dict[str, Any]:
    if route(metadata) != FAMILY:
        raise PipelineError("unknown Calvin collection family")
    master = Path(metadata["master_path"])
    if independent:
        raw = master.read_bytes()
        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                                 remove_comments=False, remove_pis=False)
        root = etree.fromstring(raw, parser=parser)
        if any(not isinstance(node.tag, str) for node in root.iter()):
            raise PipelineError("Calvin checker rejects hidden XML constructs")
    else:
        root, raw = core._read_root(master)
    if _sha(raw) != MASTER_SHA256:
        raise PipelineError("Calvin collection master hash differs")
    groups = _profile(metadata)
    source_binding = _source_header(root, metadata)
    members = _members(root, groups)
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    removed: Counter[str] = Counter()
    unit_count = 0
    for document, (group_ordinal, in_group, filename, source_head, source_body) in enumerate(members, 1):
        base_path = (f"/TEI[1]/text[1]/body[1]/div[{group_ordinal}]"
                     f"/div[{in_group}]")
        inventory.append({"tei_path": base_path + "/div[1]", "disposition": "private-electronic-header",
                          "member": filename, "descendant_count": sum(1 for _ in source_head.iter())})
        emitted = 0
        for direct_ordinal, unit in enumerate(source_body, 1):
            unit_count += 1
            path = base_path + f"/div[2]/div[{direct_ordinal}]"
            if independent:
                shadow = _public_lxml(unit, removed)
                structure, readable = observe_content(etree.tostring(shadow, encoding="utf-8", with_tail=False))
            else:
                shadow = _public_et(unit, removed)
                structure = native_content.project_content(shadow)
                readable = native_content.readable_content(structure)
            inventory.append({"tei_path": path, "disposition": "historical-source-body-unit",
                              "member": filename, "source_type": unit.get("type"),
                              "source_text_sha256": _sha("".join(unit.itertext()).encode("utf-8")),
                              "public_structure_sha256": _sha(json.dumps(structure, ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":")).encode("utf-8"))})
            if not readable.strip():
                exclusions.append({"tei_path": path, "reason": "no-visible-source-text",
                                   "member": filename})
                continue
            emitted += 1
            sequence = len(rows) + 1
            identity = metadata["acceptance"]["identity"]
            row = {
                "work_id": identity["work_id"],
                "textual_form_id": identity["textual_form_id"],
                "edition_id": identity["edition_id"],
                "record_id": f"{identity['edition_id']}:source-body-{sequence:06d}",
                "sequence": sequence,
                "category": "commentary", "language": "en", "text": readable,
                "representation_revision": "calvin-commentaries-retained-collection-v1",
                "provenance": {"edition_title": metadata["edition"].title,
                               "source_title": groups[group_ordinal - 1]["title"],
                               "source_location": filename,
                               "source_credit": "sourced via CCEL.org"},
                "content_format": "ocd-native-content-v1", "structure": [structure],
                "locator": {"kind": "native-unit", "text_part": "body",
                            "unit": sequence, "document": document},
            }
            rows.append(row)
            anchors.append({"record_id": row["record_id"], "tei_path": path,
                            "text_sha256": row_text_hash(readable),
                            "source_order": unit_count, "locator": copy.deepcopy(row["locator"])})
        inventory.append({"tei_path": base_path, "disposition": "source-member-summary",
                          "member": filename, "group": group_ordinal,
                          "direct_units": len(source_body), "emitted_rows": emitted})
    if (len(members) != 45 or unit_count != 786 or len(rows) != 756
            or len(exclusions) != 30 or removed != {"provider-paragraph": 90,
                                                    "image-reference": 10}):
        raise PipelineError("Calvin source-body row or private-omission accounting differs")
    inventory.append({"disposition": "private-shared-catalogue-and-profile",
                      "source_members": 46, "title_groups": 19,
                      "profile_sha256": PROFILE_SHA256,
                      "provider_paragraphs_omitted": 90,
                      "image_references_omitted": 10})
    result = {"rows": rows, "anchors": anchors, "inventory": inventory,
              "references": [], "warnings": [], "exclusions": exclusions,
              "unsupported": [], "master_sha256": MASTER_SHA256, "scope_id": None,
              "mapping_version": VERSION, "assembler_version": core.ASSEMBLER_VERSION,
              "source_binding": source_binding, "authority": metadata["authority"]}
    if not independent:
        core._validate_rows(rows)
    result["receipt"] = core.build_commentary_receipt(result, identity={
        key: IDENTITY[key] for key in core._IDENTITY_KEYS})
    return result


def project(metadata: Mapping[str, Any], family: str = FAMILY) -> dict[str, Any]:
    if family != FAMILY:
        raise PipelineError("unknown Calvin collection family")
    return _project(metadata, independent=False)


def verify(metadata: Mapping[str, Any], family: str, rows: Any, receipt: Any) -> list[str]:
    if family != FAMILY:
        return ["unknown Calvin collection family"]
    try:
        expected = _project(metadata, independent=True)
    except (PipelineError, OSError, etree.XMLSyntaxError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
    if isinstance(rows, Mapping):
        if receipt is None:
            receipt = rows.get("receipt")
        rows = rows.get("rows")
    if not isinstance(rows, list):
        return ["Calvin collection rows must be a list"]
    errors = []
    if len(rows) != len(expected["rows"]):
        errors.append("Calvin collection row count differs")
    for ordinal, (actual, wanted) in enumerate(zip(rows, expected["rows"]), 1):
        if actual != wanted:
            errors.append(f"Calvin collection row {ordinal} differs")
            if len(errors) > 30:
                break
    if receipt != expected["receipt"]:
        errors.append("Calvin collection private receipt differs")
    return errors
