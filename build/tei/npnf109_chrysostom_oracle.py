"""Producer-independent retained-source oracle for the LIB-042 candidate."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Mapping

from lxml import etree
from jsonschema import Draft202012Validator

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ORACLE_ID = "ocd-lib042-retained-source-oracle"
ORACLE_VERSION = "20"
SOURCE_HASH = "6d0887393b4d197d7784cbea989aeb422d7e38f55711b4c4d4af85e3de680175"
SOURCE_BYTES = 3_017_592
ASSIGNED = (
    ("iv", "chrysostom-on-the-priesthood"),
    ("v", "chrysostom-exhortation-to-theodore"),
    ("vi", "chrysostom-letter-to-young-widow"),
    ("vii", "chrysostom-homilies-ignatius-and-babylas"),
    ("viii", "chrysostom-homily-on-lowliness-of-mind"),
    ("ix", "chrysostom-instructions-to-catechumens"),
    ("x", "chrysostom-three-homilies-on-power-of-demons"),
    ("xi", "chrysostom-homily-on-father-if-it-be-possible"),
    ("xii", "chrysostom-homily-on-the-paralytic"),
    ("xiii", "chrysostom-homily-to-those-not-attended-assembly"),
    ("xiv", "chrysostom-homily-against-publishing-errors"),
    ("xv", "chrysostom-two-homilies-on-eutropius"),
    ("xvi", "chrysostom-no-one-can-be-harmed"),
    ("xvii", "chrysostom-letters-to-olympias"),
    ("xviii", "chrysostom-correspondence-with-rome"),
    ("xix", "chrysostom-homilies-on-the-statues"),
)
WORK_TITLES = {
    "chrysostom-on-the-priesthood": "Treatise Concerning the Christian Priesthood",
    "chrysostom-exhortation-to-theodore": "An Exhortation to Theodore After His Fall",
    "chrysostom-letter-to-young-widow": "Letter to a Young Widow",
    "chrysostom-homilies-ignatius-and-babylas": "Homilies on S. Ignatius and S. Babylas",
    "chrysostom-homily-on-lowliness-of-mind": "Homily Concerning Lowliness of Mind",
    "chrysostom-instructions-to-catechumens": "Instructions to Catechumens",
    "chrysostom-three-homilies-on-power-of-demons": "Three Homilies Concerning the Power of Demons",
    "chrysostom-homily-on-father-if-it-be-possible": "Homily on the Passage 'Father, If It Be Possible...'",
    "chrysostom-homily-on-the-paralytic": "Homily on the Paralytic Let Down Through the Roof",
    "chrysostom-homily-to-those-not-attended-assembly": "Homily to Those Who Had Not Attended the Assembly",
    "chrysostom-homily-against-publishing-errors": "Homily Against Publishing the Errors of the Brethren",
    "chrysostom-two-homilies-on-eutropius": "Two Homilies on Eutropius",
    "chrysostom-no-one-can-be-harmed": "Treatise to Prove That No One Can Harm the Man Who Does Not Injure Himself",
    "chrysostom-letters-to-olympias": "Letters of St. Chrysostom to Olympias",
    "chrysostom-correspondence-with-rome": "Correspondence of St. Chrysostom with the Bishop of Rome",
    "chrysostom-homilies-on-the-statues": "The Homilies on the Statues to the People of Antioch",
}
TAG_MAP = {
    "div1": "div", "div2": "div", "div3": "div", "p": "p",
    "note": "note", "scripRef": "ref", "scripCom": "ref", "i": "hi",
    "br": "lb", "pb": "pb", "span": "seg", "sup": "hi",
}
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "HE": "he", "FR": "fr"}
EXPECTED_CENSUS = {
    "elements": 7723, "attributes": 19877, "text_nodes": 5200,
    "tail_nodes": 5528, "characters": 2021867,
    "non_ascii_characters": 12334,
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def strict_json(content: bytes, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"{label} duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} invalid strict JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def source_tree(content: bytes) -> etree._ElementTree:
    return etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    ).getroottree()


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id" if key == f"{{{XML_NS}}}id" else
        "xml:lang" if key == f"{{{XML_NS}}}lang" else key: value
        for key, value in node.attrib.items()
    }


def selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if isinstance(child.tag, str) and child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def target_tag(node: etree._Element) -> str:
    if node.tag == "span" and node.get("lang"):
        return "foreign"
    if node.tag == "scripCom":
        parent = node.getparent()
        return "p" if parent is not None and str(parent.tag).startswith("div") else "seg"
    try:
        return TAG_MAP[str(node.tag)]
    except KeyError as exc:
        raise ValueError(f"unsupported retained source element {node.tag!r}") from exc


def target_details(
    node: etree._Element, number: int, root_work: str | None
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = node.get("id")
    attrs = {"xml:id": "npnf109-" + (safe(source_id) if source_id else f"feature-{number:05d}")}
    dispositions: list[dict[str, str]] = []
    tag = str(node.tag)
    for name, value in node.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination = "@xml:id"
            method = "deterministic-member-prefix"
        if name == "n" and tag in {"div1", "div2", "div3", "note", "pb"}:
            attrs["n"] = value
            destination = "@n"
        elif name == "type" and tag in {"div1", "div2", "div3"}:
            attrs["type"] = value
            destination = "@type"
        elif name == "class":
            attrs["rend"] = value
            destination = "@rend"
        elif name == "place" and tag == "note":
            attrs["place"] = value
            destination = "@place"
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
            destination = "@facs"
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"] = value
            destination = "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"] = value
            destination = "@target"
        elif name == "passage" and tag == "scripCom":
            attrs["n"] = value
            destination = "@n"
        elif name == "osisRef" and tag == "scripCom":
            attrs["corresp"] = value
            destination = "@corresp"
        elif name == "lang" and tag == "span":
            if value not in LANGUAGE_MAP:
                raise ValueError("unsupported retained language code")
            attrs["xml:lang"] = LANGUAGE_MAP[value]
            destination = "@xml:lang"
            method = "declared-language-code-map"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "scripCom":
        attrs["rend" if target_tag(node) == "p" else "type"] = "scripture-commentary"
    if root_work is not None:
        attrs["corresp"] = f"#npnf109:{node.get('id')}:{root_work}"
    return attrs, dispositions


def target_attrs(node: etree._Element, number: int, root_work: str | None) -> dict[str, str]:
    return target_details(node, number, root_work)[0]


def census(nodes: list[etree._Element]) -> dict[str, int]:
    return {
        "elements": len(nodes),
        "attributes": sum(len(node.attrib) for node in nodes),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len((node.text or "") + (node.tail or "")) for node in nodes),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in nodes
        ),
    }


def closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    values = policy.get("import_closure")
    if not isinstance(values, list) or not values:
        raise ValueError("validation policy import closure missing")
    paths = tuple((root / str(item)).resolve(strict=True) for item in values)
    if len(set(paths)) != len(paths):
        raise ValueError("validation policy import closure duplicates")
    return paths


def closure_digest(root: Path, policy: Mapping[str, Any]) -> str:
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": len(path.read_bytes()),
            "sha256": digest(path.read_bytes()),
        }
        for path in closure_paths(root, policy)
    ]
    return digest(canonical({"contract": "ocd-import-closure-v1", "members": records}))


def verify_runtime_closure(root: Path, policy: Mapping[str, Any]) -> None:
    """Reject a validator running with a kernel imported from another root."""

    expected: dict[str, tuple[Path, str]] = {}
    for path in closure_paths(root, policy):
        relative = path.relative_to(root)
        parts = relative.parts
        if parts[-1] == "__init__.py":
            module_name = ".".join(parts[:-1])
        else:
            module_name = ".".join((*parts[:-1], Path(parts[-1]).stem))
        expected[module_name] = (path, digest(path.read_bytes()))

    required = {
        "ocd_kernel",
        "ocd_kernel.reconstruction",
        "ocd_kernel.reconstruction.contract",
    }
    for module_name, (expected_path, expected_sha256) in expected.items():
        module = sys.modules.get(module_name)
        if module is None:
            if module_name in required:
                raise ValueError(f"required runtime module {module_name!r} is not loaded")
            continue
        runtime_file = getattr(module, "__file__", None)
        if not runtime_file:
            raise ValueError(f"runtime module {module_name!r} has no source file")
        try:
            runtime_path = Path(str(runtime_file)).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ValueError(f"runtime module {module_name!r} source is not resolvable") from exc
        if not runtime_path.samefile(expected_path):
            raise ValueError(f"runtime module {module_name!r} loaded from the wrong root")
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        if origin and origin not in {"built-in", "frozen"}:
            try:
                origin_path = Path(str(origin)).resolve(strict=True)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise ValueError(f"runtime module {module_name!r} origin is not resolvable") from exc
            if not origin_path.samefile(expected_path):
                raise ValueError(f"runtime module {module_name!r} origin drift")
        if digest(runtime_path.read_bytes()) != expected_sha256:
            raise ValueError(f"runtime module {module_name!r} bytes drifted from import closure")


def verify_shell(content: bytes, tree: etree._ElementTree) -> None:
    if not content.startswith(b"<?xml version='1.0' encoding='UTF-8'?>"):
        raise ValueError("candidate XML prolog drift")
    if b"<!DOCTYPE" in content or b"<?xml-stylesheet" in content or b"<!--" in content:
        raise ValueError("candidate XML shell invention")
    if content.count(b"xmlns=") != 1 or b"xmlns:" in content:
        raise ValueError("candidate namespace declaration topology drift")
    if tree.docinfo.doctype:
        raise ValueError("candidate XML shell invention")
    if tree.getroot().getprevious() is not None or tree.getroot().getnext() is not None:
        raise ValueError("candidate XML shell invention")


def verify_header(tree: etree._ElementTree) -> None:
    ns = {"tei": TEI_NS}
    expected = {
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title": "NPNF1-09. St. Chrysostom: On the Priesthood; Ascetic Treatises; Select Homilies and Letters; Homilies on the Statutes",
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author": "St. Chrysostom",
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:resp": "series editor",
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name": "Philip Schaff",
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher": "Grand Rapids, MI: Christian Classics Ethereal Library",
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p": "Retained electronic-edition rights statement: Public Domain.",
    }
    for path, text in expected.items():
        values = tree.xpath(path, namespaces=ns)
        if len(values) != 1 or values[0].text != text:
            raise ValueError("candidate retained metadata/header drift")
    allowed = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc", namespaces=ns)
    if len(allowed) != 1 or [etree.QName(child).localname for child in allowed[0]] != ["titleStmt", "publicationStmt", "sourceDesc"]:
        raise ValueError("candidate complete teiHeader topology/content drift")
    pointers = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr/@target", namespaces=ns)
    if pointers != ["https://www.ccel.org/ccel/schaff/npnf109"]:
        raise ValueError("candidate retained metadata/header drift")


def source_scope(tree: etree._ElementTree) -> tuple[list[etree._Element], list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source body missing")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if [node.get("id") for node in top] != [
        "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi",
        "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi",
    ]:
        raise ValueError("retained source complete member/root coverage drift")
    by_id = {node.get("id"): node for node in top}
    selected = [by_id[scope] for scope, _ in ASSIGNED]
    return top, selected


def verify_body(source_roots: list[etree._Element], candidate_tree: etree._ElementTree) -> list[dict[str, Any]]:
    ns = {"tei": TEI_NS}
    body_values = candidate_tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=ns)
    if len(body_values) != 1:
        raise ValueError("candidate complete text shell drift")
    body = body_values[0]
    direct = [node for node in body if isinstance(node.tag, str)]
    if len(direct) != 16:
        raise ValueError("candidate source-root count drift")
    all_nodes = [node for root in source_roots for node in root.iter() if isinstance(node.tag, str)]
    if census(all_nodes) != EXPECTED_CENSUS:
        raise ValueError("retained source assigned census drift")
    expected_ids: list[str] = []
    rows: list[dict[str, Any]] = []
    target_by_source: dict[int, etree._Element] = {}
    feature_id_by_source: dict[int, str] = {}
    candidate_by_id: dict[str, list[etree._Element]] = {}
    for node in candidate_tree.getroot().iter():
        if not isinstance(node.tag, str):
            continue
        xml_id = node.get(f"{{{XML_NS}}}id")
        if xml_id is not None:
            candidate_by_id.setdefault(xml_id, []).append(node)
    number = 0
    for root_index, (source_root, (scope, work_id)) in enumerate(zip(source_roots, ASSIGNED, strict=True)):
        if source_root.get("id") != scope:
            raise ValueError("retained source assigned order drift")
        candidate_root = direct[root_index]
        for source_node in source_root.iter():
            if not isinstance(source_node.tag, str):
                raise ValueError("assigned source comment/PI requires disposition")
            number += 1
            feature_id = f"npnf109-feature-{number:05d}"
            xml_id = "npnf109-" + (safe(source_node.get("id")) if source_node.get("id") else f"feature-{number:05d}")
            expected_ids.append(xml_id)
            matches = candidate_by_id.get(xml_id, [])
            if len(matches) != 1:
                raise ValueError("candidate feature omission/duplication")
            target = matches[0]
            target_by_source[id(source_node)] = target
            feature_id_by_source[id(source_node)] = feature_id
            if etree.QName(target).localname != target_tag(source_node):
                raise ValueError("candidate feature tag drift")
            root_work = work_id if source_node is source_root else None
            expected_attrs, dispositions = target_details(
                source_node, number, root_work
            )
            if normalized_attrs(target) != expected_attrs:
                raise ValueError("candidate attributes drift")
            if (target.text or "") != (source_node.text or ""):
                raise ValueError("candidate direct text drift")
            if (target.tail or "") != (source_node.tail or ""):
                raise ValueError("candidate tail drift")
            source_parent = source_node.getparent()
            expected_parent = (
                body
                if source_node is source_root
                else target_by_source[id(source_parent)]
            )
            if target.getparent() is not expected_parent:
                raise ValueError("candidate feature hierarchy/reordering drift")
            if source_node is source_root:
                child_ordinal = root_index + 1
                parent_feature_id = None
            else:
                source_siblings = [
                    child
                    for child in source_parent
                    if isinstance(child.tag, str)
                ]
                child_ordinal = source_siblings.index(source_node) + 1
                if str(source_parent.tag).startswith("div") and source_parent.get(
                    "title"
                ) is not None:
                    child_ordinal += 1
                parent_feature_id = feature_id_by_source[id(source_parent)]
            title = source_node.get("title") if str(source_node.tag).startswith("div") else None
            heads = [child for child in target if isinstance(child.tag, str) and etree.QName(child).localname == "head"]
            if title is None and heads:
                raise ValueError("candidate title invention")
            if title is not None and (len(heads) != 1 or heads[0].text != title):
                raise ValueError("candidate retained title drift")
            rows.append({
                "ordinal": number,
                "feature_id": feature_id,
                "member": "npnf109",
                "work_id": work_id,
                "source_selector": selector(source_node),
                "source_tag": source_node.tag,
                "source_xml_id": source_node.get("id"),
                "source_attributes": dict(source_node.attrib),
                "text_present": source_node.text is not None,
                "text_sha256": digest((source_node.text or "").encode("utf-8")),
                "tail_present": source_node.tail is not None,
                "tail_sha256": digest((source_node.tail or "").encode("utf-8")),
                "tei_tag": target_tag(source_node),
                "tei_xml_id": xml_id,
                "tei_parent_id": expected_parent.get(f"{{{XML_NS}}}id"),
                "tei_child_ordinal": child_ordinal,
                "tei_attributes": expected_attrs,
                "attribute_dispositions": dispositions,
                "tei_selector": f"#{xml_id}",
                "parent_feature_id": parent_feature_id,
                "source_title_head": title,
                "disposition": "represented",
            })
    observed_ids = [
        node.get(f"{{{XML_NS}}}id")
        for node in body.iter()
        if node is not body and isinstance(node.tag, str) and etree.QName(node).localname != "head"
    ]
    if observed_ids != expected_ids:
        raise ValueError("candidate feature order/count drift")
    expected_id_set = set(expected_ids)
    for node in body.iter():
        if node is body or not isinstance(node.tag, str):
            continue
        if etree.QName(node).namespace != TEI_NS:
            raise ValueError("candidate namespace drift")
        if etree.QName(node).localname == "head":
            if etree.QName(node.getparent()).localname != "div":
                raise ValueError("candidate title invention")
        elif node.get(f"{{{XML_NS}}}id") not in expected_id_set:
            raise ValueError("candidate body invention")
    return rows


def comment_record(comment: etree._Comment, ordinal: int) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "text": comment.text or "",
        "text_sha256": digest((comment.text or "").encode("utf-8")),
        "tail": comment.tail or "",
        "tail_sha256": digest((comment.tail or "").encode("utf-8")),
    }


def expected_source_member() -> dict[str, object]:
    return {
        "name": "npnf109",
        "path": "raw/ccel/npnf1/npnf109.xml",
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_HASH,
        "disposition": "included retained member with exact assigned work subtrees",
    }


def expected_accountability(
    tree: etree._ElementTree,
    top: list[etree._Element],
    selected: list[etree._Element],
    rows: list[dict[str, Any]],
) -> dict[str, object]:
    assigned_nodes = [
        node
        for division in selected
        for node in division.iter()
        if isinstance(node.tag, str)
    ]
    assigned_identity = {id(node) for node in assigned_nodes}
    complete_nodes = [
        node for node in tree.getroot().iter() if isinstance(node.tag, str)
    ]
    excluded_nodes = [
        node for node in complete_nodes if id(node) not in assigned_identity
    ]
    embedded_comments = [
        comment
        for comment in tree.xpath("//comment()")
        if comment.getparent() is not None
    ]
    excluded_comments = []
    for comment in embedded_comments:
        division = next(
            (
                ancestor
                for ancestor in comment.iterancestors()
                if ancestor.tag == "div1"
            ),
            None,
        )
        if division is None or division.get("id") not in {scope for scope, _ in ASSIGNED}:
            excluded_comments.append(comment)
    prolog_comments = tree.xpath("/comment()")
    document = {
        "member": "npnf109",
        "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
        "standalone": False,
        "doctype": '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" "http://www.ccel.org/dtd/ThML10.dtd">',
        "pre_root_comment_count": len(prolog_comments),
        "pre_root_comments": [
            comment_record(comment, ordinal)
            for ordinal, comment in enumerate(prolog_comments, start=1)
        ],
        "pre_root_processing_instructions": [],
        "post_root_nodes": [],
        "root_tag": tree.getroot().tag,
        "root_attributes": dict(tree.getroot().attrib),
        "root_namespace_declarations": dict(tree.getroot().nsmap),
        "assigned_comment_count": 0,
        "assigned_processing_instruction_count": 0,
        "excluded_index_comment_count": len(excluded_comments),
    }
    work_map = dict(ASSIGNED)
    division_rows: list[dict[str, object]] = []
    assigned_ids = {scope for scope, _ in ASSIGNED}
    for ordinal, division in enumerate(top, start=1):
        scope = str(division.get("id"))
        assigned = scope in assigned_ids
        div2_rows = []
        if assigned:
            direct_div2 = [
                child
                for child in division
                if isinstance(child.tag, str) and child.tag == "div2"
            ]
            for child_ordinal, div2 in enumerate(direct_div2, start=1):
                div2_rows.append(
                    {
                        "level": "div2",
                        "ordinal": child_ordinal,
                        "source_xml_id": str(div2.get("id")),
                        "parent_div1_id": scope,
                        "title": div2.get("title", ""),
                        "disposition": "assigned-work-content-represented",
                        "work_id": work_map[scope],
                    }
                )
        division_rows.append(
            {
                "member": "npnf109",
                "level": "div1",
                "ordinal": ordinal,
                "source_xml_id": scope,
                "title": division.get("title", ""),
                "disposition": (
                    "assigned-work-represented"
                    if assigned
                    else "front-or-index-outside-assigned-work-scope"
                ),
                "work_id": work_map.get(scope),
                "child_div2_count": len(div2_rows),
            }
        )
        division_rows.extend(div2_rows)
    tag_counts = dict(
        sorted(Counter(str(row["source_tag"]) for row in rows).items())
    )
    assigned_census = census(assigned_nodes)
    return {
        "contract": "ocd-npnf109-source-accountability-v1",
        "schema": "npnf109.source-accountability.schema.json",
        "profile_id": "npnf109-16-work-v1",
        "source_scope": (
            "one retained NPNF ThML member (npnf109); "
            "16 exact assigned div1 work roots (iv through xix)"
        ),
        "source_members": [expected_source_member()],
        "document_accounting": [document],
        "member_accounting": [
            {
                "member": "npnf109",
                "assigned_div1": [scope for scope, _ in ASSIGNED],
                "assigned_work_ids": [work_id for _, work_id in ASSIGNED],
                "excluded_div1": [
                    str(node.get("id"))
                    for node in top
                    if node.get("id") not in assigned_ids
                ],
                "disposition": (
                    "member completely accounted; exact work roots represented and "
                    "remaining front/index divisions excluded"
                ),
            }
        ],
        "source_census": {
            "complete_document": census(complete_nodes),
            "assigned_scope": assigned_census,
            "excluded_shell_front_and_indexes": census(excluded_nodes),
        },
        "assigned_work_count": 16,
        "feature_count": len(rows),
        "attribute_count": assigned_census["attributes"],
        "feature_counts": tag_counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": 0, "rows": 0, "cells": 0},
        "excluded_index_comment_count": len(excluded_comments),
        "division_accounting": division_rows,
        "crosswalk": rows,
    }


def expected_provenance(
    tree: etree._ElementTree, selected: list[etree._Element]
) -> dict[str, object]:
    retained_head = tree.getroot().find("ThML.head")
    if retained_head is None:
        raise ValueError("retained source metadata head missing")
    dc_entries = tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/*")
    print_source_entries = tree.xpath("/ThML/ThML.head/printSourceInfo/*")
    works = [
        {
            "ordinal": ordinal,
            "source_member": "npnf109",
            "div1_id": scope,
            "work_id": work_id,
            "title": WORK_TITLES[work_id],
            "retained_division_title": division.get("title", ""),
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        }
        for ordinal, (division, (scope, work_id)) in enumerate(
            zip(selected, ASSIGNED, strict=True), start=1
        )
    ]
    return {
        "contract": "ocd-npnf109-provenance-v1",
        "status": "nonaccepted",
        "source_id": "LIB-042",
        "sources": [expected_source_member()],
        "edition": {
            "series": "Nicene and Post-Nicene Fathers, First Series",
            "volume": "IX",
            "author": "St. Chrysostom",
            "series_editor": "Philip Schaff",
            "print_source": "New York: Christian Literature Publishing Co., 1886",
            "electronic_publisher": "Grand Rapids, MI: Christian Classics Ethereal Library",
        },
        "works": works,
        "retained_metadata_evidence": {
            "head_c14n_sha256": digest(
                etree.tostring(retained_head, method="c14n", with_comments=True)
            ),
            "dc_entries": [
                {
                    "tag": node.tag,
                    "attributes": dict(node.attrib),
                    "text": node.text or "",
                    "tail": node.tail or "",
                }
                for node in dc_entries
            ],
            "print_source_entries": [
                {
                    "tag": node.tag,
                    "attributes": dict(node.attrib),
                    "text": node.text or "",
                    "tail": node.tail or "",
                }
                for node in print_source_entries
            ],
            "normalization_policy": (
                "Retained ThML head and assigned work title/credit apparatus are preserved "
                "as evidence; source config metadata is diagnostic only and is not used to "
                "supply or reconcile candidate readings."
            ),
        },
        "localized_config_conflicts": [
            {
                "scope": "all sixteen LIB-042 source configs",
                "fields": ["contributors", "source_edition", "translator"],
                "retained_authority": (
                    "npnf109 ThML head plus each assigned work's preserved title/credit apparatus"
                ),
                "disposition": (
                    "configs remain diagnostic aids; no config-only contributor, year, or edition claim is asserted"
                ),
            }
        ],
        "rights": {
            "retained_statement": "Public Domain",
            "ccel_formatting_condition": (
                "Do not sell CCEL files or derivatives of CCEL formatting."
            ),
            "attribution_readme": "README.source.md",
            "publication_state": "not_ready",
        },
        "canonical_data_written": False,
    }


EXPECTED_README = (
    "# Source attribution for LIB-042\n\n"
    "This nonaccepted reconstruction candidate was generated from the retained "
    "CCEL ThML member `raw/ccel/npnf1/npnf109.xml`. The retained metadata "
    "identifies Christian Classics Ethereal Library as the electronic publisher, "
    "states `Public Domain`, and identifies the print source as `New York: "
    "Christian Literature Publishing Co., 1886`.\n\n"
    "The project permission evidence states that CCEL permits parsing its ThML/XML "
    "and asks that CCEL files or derivatives of CCEL formatting not be sold. "
    "This package preserves that attribution and condition; it does not establish "
    "human textual acceptance or publication authorization.\n"
).encode("utf-8")


EXPECTED_UNRESOLVED = [
    {
        "id": "npnf109-print-collation-not-performed",
        "scope": "one retained electronic witness",
        "status": "unresolved",
        "question": "Do the retained CCEL witness and stated print edition differ substantively?",
        "evidence": (
            "Candidate is byte-bound to retained npnf109.xml authority; "
            "no print collation was performed."
        ),
    },
    {
        "id": "npnf109-human-textual-acceptance",
        "scope": "16 assigned works",
        "status": "unresolved",
        "question": (
            "Will the project maintainer accept this candidate after optional "
            "risk-focused human review?"
        ),
        "evidence": (
            "Technical validation is not human textual acceptance; every work remains "
            "human_review required and accepted_ir not_accepted."
        ),
    },
    {
        "id": "npnf109-publication-authorization",
        "scope": "candidate package",
        "status": "unresolved",
        "question": "Has publication been separately authorized?",
        "evidence": (
            "No publication decision is present; publication remains not_ready."
        ),
    },
]


def verify_evidence(
    source: SourceManifest,
    candidate: CandidatePackage,
    source_tree_value: etree._ElementTree,
    source_roots: list[etree._Element],
    rows: list[dict[str, Any]],
) -> None:
    body = source_tree_value.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source body missing")
    top = [
        node
        for node in body
        if isinstance(node.tag, str) and node.tag == "div1"
    ]
    accountability = strict_json(
        candidate.member_bytes("source-accountability.json"), "accountability"
    )
    accountability_schema = strict_json(
        source.authority_path("source-accountability-schema").read_bytes(),
        "source accountability schema",
    )
    errors = sorted(
        Draft202012Validator(accountability_schema).iter_errors(accountability),
        key=str,
    )
    if errors:
        raise ValueError("candidate accountability schema drift")
    if accountability != expected_accountability(
        source_tree_value, top, source_roots, rows
    ):
        raise ValueError("candidate complete accountability nested-structure drift")

    provenance = strict_json(candidate.member_bytes("provenance.json"), "provenance")
    if provenance != expected_provenance(source_tree_value, source_roots):
        raise ValueError("candidate complete provenance/rights/credit nested-structure drift")
    if candidate.member_bytes("README.source.md") != EXPECTED_README:
        raise ValueError("candidate exact source attribution/rights README drift")
    unresolved_lines = candidate.member_bytes("unresolved.jsonl").splitlines()
    try:
        unresolved = [strict_json(line + b"\n", "unresolved") for line in unresolved_lines]
    except ValueError as exc:
        raise ValueError("candidate complete unresolved evidence-shape drift") from exc
    if unresolved != EXPECTED_UNRESOLVED:
        raise ValueError("candidate complete unresolved evidence-shape drift")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    validator = source_manifest.record.get("validator")
    expected_oracle = (root / str(validator["implementation_path"])).resolve(strict=True)
    oracle_path = Path(__file__).resolve(strict=True)
    if (
        not oracle_path.samefile(expected_oracle)
        or digest(oracle_path.read_bytes()) != validator["implementation_sha256"]
    ):
        raise ValueError("independent oracle implementation binding drift")
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    policy = strict_json(policy_bytes, "validation policy")
    verify_runtime_closure(root, policy)
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("contract") != "ocd-candidate-package-v1"
        or candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id")
        != source_manifest.record.get("source_id")
        or candidate.manifest.get("source_id") != "LIB-042"
    ):
        raise ValueError("candidate source identity/status binding drift")
    if candidate.manifest.get("source_manifest") != expected_manifest:
        raise ValueError("candidate source-manifest binding drift")
    if candidate.manifest.get("converter") != source_manifest.record.get("converter") or candidate.manifest.get("package_schema") != source_manifest.record.get("package_schema"):
        raise ValueError("candidate converter/schema binding drift")
    content = source_manifest.authority_path("npnf109-retained-xml").read_bytes()
    if len(content) != SOURCE_BYTES or digest(content) != SOURCE_HASH:
        raise ValueError("retained source authority drift")
    source_value = source_tree(content)
    top, selected = source_scope(source_value)
    candidate_content = candidate.member_bytes("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, remove_pis=False, huge_tree=True)
    candidate_tree = etree.fromstring(candidate_content, parser).getroottree()
    verify_shell(candidate_content, candidate_tree)
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(candidate_tree):
        raise ValueError("candidate TEI P5 schema invalid")
    if candidate_tree.getroot().tag != f"{{{TEI_NS}}}TEI":
        raise ValueError("candidate TEI root drift")
    verify_header(candidate_tree)
    rows = verify_body(selected, candidate_tree)
    verify_evidence(source_manifest, candidate, source_value, selected, rows)
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    package_schema = source_manifest.authority_path("candidate-package-schema").read_bytes()
    xsd_bytes = source_manifest.authority_path("tei-p5-xsd").read_bytes()
    implementation = Path(__file__).resolve(strict=True).read_bytes()
    result: dict[str, object] = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": digest(implementation),
        "import_closure_sha256": closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": digest(profile_bytes),
        "package_schema_sha256": digest(package_schema),
        "source_sha256": SOURCE_HASH,
        "xsd_sha256": digest(xsd_bytes),
        "policy_sha256": digest(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = digest(canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
