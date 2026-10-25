from __future__ import annotations
from collections import Counter
from io import BytesIO
import hashlib, json, re
from hashlib import sha256
from pathlib import Path
from typing import Mapping
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
TEI_NS="http://www.tei-c.org/ns/1.0"
XML_NS="http://www.w3.org/XML/1998/namespace"
XML_ID="{"+XML_NS+"}id"
NS="{"+TEI_NS+"}"
_DIVISION_TAGS = ("div", "div1", "div2", "div3", "div4", "div5", "div6")

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

_PROJECTION_NAMES = {
    "div": "div",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "div5": "div",
    "div6": "div",
    "h1": "head",
    "h2": "head",
    "h3": "head",
    "h4": "head",
    "h5": "head",
    "h6": "head",
    "p": "p",
    "note": "note",
    "i": "hi",
    "b": "hi",
    "sup": "hi",
    "unclear": "unclear",
    "br": "lb",
    "scripRef": "ref",
    "a": "ref",
    "span": "seg",
    "verse": "lg",
    "index": "index",
    "l": "l",
    "ul": "list",
    "li": "item",
    "insertIndex": "anchor",
    "attr": "p",
    "ThML.body": "body",
}

def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")

def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result

def _parse_xml(content: bytes, label: str) -> etree._ElementTree:
    parser = etree.XMLParser(
        load_dtd=False,
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_comments=False,
        remove_pis=False,
        huge_tree=True,
    )
    try:
        return etree.parse(BytesIO(content), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"{label} is not well-formed XML: {exc}") from exc

def _name(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("non-element node entered the source-element census")
    return etree.QName(node).localname

def _tei_token(value: str) -> str:
    """Return the producer's schema-safe token normalization independently."""

    return re.sub(r"\s+", "-", value.strip())

def _heading_is_leading_division_child(source: etree._Element) -> bool:
    parent = source.getparent()
    if parent is None or _name(parent) not in _DIVISION_TAGS:
        return False
    for child in parent:
        if not isinstance(child.tag, str):
            continue
        return child is source
    return False

def _projected_name(source_name: str, source: etree._Element) -> str:
    if source_name in _HEADING_TAGS:
        return "head" if _heading_is_leading_division_child(source) else "ab"
    return _PROJECTION_NAMES.get(source_name, "seg")

def _source_records(
    root: etree._Element,
) -> tuple[list[etree._Element], dict[str, dict[str, object]]]:
    """Independently enumerate source elements, parent links, and element ordinals."""

    nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    if sum(1 for node in root.iter() if not isinstance(node.tag, str)):
        raise ValueError("HCC6 has an unsupported in-root comment, PI, or entity")
    by_node: dict[etree._Element, str] = {
        node: f"hcc6-n{position:06d}" for position, node in enumerate(nodes, 1)
    }
    records: dict[str, dict[str, object]] = {}
    for node in nodes:
        key = by_node[node]
        parent = node.getparent()
        if parent is None:
            parent_key = None
            ordinal = 1
        else:
            element_children = [child for child in parent if isinstance(child.tag, str)]
            parent_key = by_node.get(parent)
            ordinal = element_children.index(node) + 1
        records[key] = {
            "node": node,
            "source_key": key,
            "tag": _name(node),
            "parent_key": parent_key,
            "ordinal": ordinal,
            "attributes": list(node.attrib.items()),
        }
    return nodes, records

def _external_siblings(root: etree._Element, *, before: bool) -> list[etree._Element]:
    if before:
        cursor = root
        while cursor.getprevious() is not None:
            cursor = cursor.getprevious()
        siblings: list[etree._Element] = []
        while cursor is not root:
            siblings.append(cursor)
            cursor = cursor.getnext()
        return siblings
    siblings = []
    cursor = root.getnext()
    while cursor is not None:
        siblings.append(cursor)
        cursor = cursor.getnext()
    return siblings

def _counts(records: Mapping[str, Mapping[str, object]]) -> tuple[dict[str, int], dict[str, int]]:
    observed = Counter(str(record["tag"]) for record in records.values())
    return (
        {tag: observed.get(tag, 0) for tag in _DIVISION_TAGS},
        {tag: observed.get(tag, 0) for tag in _HEADING_TAGS},
    )

def _expected_tei_attributes(
    source_name: str, source: etree._Element
) -> dict[str, str]:
    """Build the TEI-facing attributes separately from the producer's mapper."""

    if source_name == "ThML":
        return {}
    attrs: dict[str, str] = {}
    source_type = source.get("type")
    source_class = source.get("class")
    if source_class:
        attrs["rend"] = source_class

    if source_name in _DIVISION_TAGS:
        attrs["type"] = f"ThML-{source_name}"
        if source_type:
            attrs["subtype"] = _tei_token(source_type)
        attrs["n"] = source.get("title") or source.get("n") or ""
        if not attrs["n"]:
            attrs.pop("n")
    elif source_name in _HEADING_TAGS:
        attrs["type"] = f"source-{source_name}"
    elif source_name == "i":
        attrs["rend"] = source_class or "italic"
    elif source_name in {"b", "sup"}:
        attrs["rend"] = "bold" if source_name == "b" else "superscript"
    elif source_name == "note":
        attrs["type"] = source_type or "ThML-note"
        if source.get("place"):
            attrs["place"] = source.get("place") or ""
        if source.get("n"):
            attrs["n"] = source.get("n") or ""
    elif source_name == "scripRef":
        attrs["type"] = "scripture-reference"
        attrs["target"] = source.get("osisRef") or source.get("passage") or ""
    elif source_name == "a":
        attrs["type"] = "ThML-link"
        if source.get("href"):
            attrs["target"] = source.get("href") or ""
    elif source_name == "verse":
        attrs["type"] = source_type or "ThML-verse"
    elif source_name == "ul":
        attrs["type"] = "unordered"
    elif source_name == "index":
        if source_type:
            attrs["indexName"] = source_type
        if source.get("subject1"):
            attrs["n"] = source.get("subject1") or ""
    elif source_name == "insertIndex":
        attrs["type"] = source_type or "ThML-insertIndex"
    elif source_name == "ThML.head":
        attrs["type"] = "retained-ThML-header"
    elif _PROJECTION_NAMES.get(source_name, "seg") == "seg":
        attrs["type"] = f"ThML-{source_name}"
    elif source_type and _PROJECTION_NAMES.get(source_name) in {"l", "item", "anchor"}:
        attrs["type"] = source_type
    if source.get("style"):
        if source_name in _HEADING_TAGS:
            attrs["ana"]="source-css:"+source.get("style")
        else:
            attrs["style"]=source.get("style")
    if source.get("lang"):
        attrs[f"{{{XML_NS}}}lang"] = source.get("lang")
    return attrs

def _source_content_id(
    source: etree._Element,
    source_record: Mapping[str, object],
) -> str:
    source_key = str(source_record["source_key"])
    return source.get("id") or f"hcc6-generated-{source_key[6:]}"

def _verify_external_comments(
    source_root: etree._Element, candidate_root: etree._Element
) -> None:
    source_pre = _external_siblings(source_root, before=True)
    source_post = _external_siblings(source_root, before=False)
    candidate_pre = _external_siblings(candidate_root, before=True)
    candidate_post = _external_siblings(candidate_root, before=False)
    if source_post or candidate_post:
        raise ValueError("source/candidate has an unaccounted post-root node")
    if any(not isinstance(node, etree._Comment) for node in source_pre + candidate_pre):
        raise ValueError("active PI or unsupported prolog node is present")
    if [node.text or "" for node in source_pre] != [node.text or "" for node in candidate_pre]:
        raise ValueError("candidate leading source comments drifted")

def _verify_source_projection(
    source_root: etree._Element,
    candidate_root: etree._Element,
    records: Mapping[str, Mapping[str, object]],
) -> set[etree._Element]:
    source_keys = {record["node"]: key for key, record in records.items()}
    candidate_by_id: dict[str, etree._Element] = {}
    for node in candidate_root.iter():
        if not isinstance(node.tag, str):
            continue
        content_id = node.get(XML_ID)
        if content_id is None:
            continue
        if content_id in candidate_by_id:
            raise ValueError(f"candidate duplicates XML ID {content_id!r}")
        candidate_by_id[content_id] = node

    stand_off = candidate_root.find(f"{{{TEI_NS}}}standOff")
    projection = (
        stand_off.find(f"{{{TEI_NS}}}list") if stand_off is not None else None
    )
    if projection is None or projection.get("type") != "source-projection":
        raise ValueError("candidate source projection record list is absent")
    items = projection.findall(f"{{{TEI_NS}}}item")
    expected_keys = list(records)
    if len(items) != len(expected_keys):
        raise ValueError("candidate source projection record count drifted")

    observed: dict[str, etree._Element] = {}
    for item, key in zip(items, expected_keys, strict=True):
        record = records[key]
        source = record["node"]
        if not isinstance(source, etree._Element):
            raise ValueError(f"oracle source record {key} has no element")
        content_id = _source_content_id(source, record)
        if item.attrib != {
            "n": key,
            "corresp": f"#{content_id}",
        }:
            raise ValueError(f"candidate source-record link drifted at {key}")
        if len(item) != 0 or item.text is None:
            raise ValueError(f"candidate source record is not a text-only item at {key}")
        payload = _strict_json(item.text.encode("utf-8"), f"HCC6 source record {key}")
        expected_payload = {
            "source_key": key,
            "source_element": str(record["tag"]),
            "source_attributes": [
                [name, value] for name, value in record["attributes"]
            ],
            "source_parent_key": str(record["parent_key"] or ""),
            "source_ordinal": record["ordinal"],
        }
        if payload != expected_payload:
            raise ValueError(f"candidate source record fields drifted at {key}")
        projected = candidate_by_id.get(content_id)
        if projected is None:
            raise ValueError(f"candidate source content target is absent at {key}")
        observed[key] = projected

    if len(observed) != len(records):
        raise ValueError("candidate source projection accounting is incomplete")
    expected_content_ids = {
        _source_content_id(record["node"], record)
        for record in records.values()
    }
    if set(candidate_by_id) != expected_content_ids:
        raise ValueError("candidate contains an unaccounted source-content XML ID")

    source_ids = {
        str(record["node"].get("id"))
        for record in records.values()
        if record["node"].get("id") is not None
    }
    generated_ids: set[str] = set()
    for key, record in records.items():
        source = record["node"]
        projected = observed[key]
        source_name = str(record["tag"])
        expected_local = "TEI" if source is source_root else _projected_name(source_name, source)
        if etree.QName(projected).localname != expected_local:
            raise ValueError(f"candidate mapped {source_name} to the wrong TEI element")
        content_id = _source_content_id(source, record)
        expected_attributes = {XML_ID: content_id}
        expected_attributes.update(_expected_tei_attributes(source_name, source))
        if dict(projected.attrib) != expected_attributes:
            raise ValueError(f"candidate TEI attributes or semantics drifted at {key}")
        if projected.text != source.text or projected.tail != source.tail:
            raise ValueError(f"candidate mixed text or tail drifted at {key}")
        if source.get("id") is None:
            if content_id in source_ids or content_id in generated_ids:
                raise ValueError(f"candidate generated XML ID collision at {key}")
            generated_ids.add(content_id)

    wrappers: set[etree._Element] = set()
    for parent_key, parent_record in records.items():
        source_parent = parent_record["node"]
        if source_parent is source_root:
            continue
        if not isinstance(source_parent, etree._Element):
            raise ValueError(f"oracle source parent {parent_key} has no element")
        source_name = str(parent_record["tag"])
        projected_parent = observed[parent_key]
        source_children = [
            child for child in source_parent if isinstance(child.tag, str)
        ]
        try:
            child_keys = [source_keys[child] for child in source_children]
        except KeyError as exc:
            raise ValueError("oracle source-child key inventory is incomplete") from exc
        candidate_children = [
            child for child in projected_parent if isinstance(child.tag, str)
        ]

        if source_name in _DIVISION_TAGS:
            layout: list[tuple[str, list[str]]] = []
            pending_common: list[str] = []
            saw_division = False
            for child, child_key in zip(source_children, child_keys, strict=True):
                if str(_name(child)) in _DIVISION_TAGS:
                    if pending_common:
                        layout.append(("wrapper", pending_common))
                        pending_common = []
                    layout.append(("source", [child_key]))
                    saw_division = True
                elif saw_division:
                    pending_common.append(child_key)
                else:
                    layout.append(("source", [child_key]))
            if pending_common:
                layout.append(("wrapper", pending_common))
            if len(candidate_children) != len(layout):
                raise ValueError(f"candidate division child envelope drifted at {parent_key}")
            for (kind, keys), candidate_child in zip(
                layout, candidate_children, strict=True
            ):
                if kind == "source":
                    if candidate_child is not observed[keys[0]]:
                        raise ValueError(
                            f"candidate division child order drifted at {parent_key}"
                        )
                    continue
                if (
                    etree.QName(candidate_child).localname != "div"
                    or candidate_child.attrib != {"type": "source-order-wrapper"}
                    or candidate_child.text is not None
                    or candidate_child.tail is not None
                ):
                    raise ValueError(
                        f"candidate source-order wrapper drifted at {parent_key}"
                    )
                wrapped_children = [
                    child for child in candidate_child if isinstance(child.tag, str)
                ]
                if wrapped_children != [observed[key] for key in keys]:
                    raise ValueError(
                        f"candidate source-order wrapper members drifted at {parent_key}"
                    )
                wrappers.add(candidate_child)
        elif candidate_children != [observed[key] for key in child_keys]:
            raise ValueError(f"candidate child order or parent attachment drifted at {parent_key}")

    source_head = source_root.find("./ThML.head")
    source_body = source_root.find("./ThML.body")
    if source_head is None or source_body is None:
        raise ValueError("retained HCC6 root head/body records are missing")
    mapped_head_nodes = candidate_root.xpath(
        "./t:teiHeader/t:fileDesc/t:notesStmt/"
        "t:note[@type='retained-ThML-header']/t:p/t:seg",
        namespaces={"t": TEI_NS},
    )
    mapped_body = candidate_root.find(
        f"{{{TEI_NS}}}text/{{{TEI_NS}}}body"
    )
    if (
        len(mapped_head_nodes) != 1
        or observed[source_keys[source_head]] is not mapped_head_nodes[0]
        or mapped_body is None
        or observed[source_keys[source_body]] is not mapped_body
    ):
        raise ValueError("candidate root head/body source parent attachments drifted")

    if len(observed) != len(records):
        raise ValueError("candidate source element accounting is incomplete")
    if candidate_root.text != source_root.text:
        raise ValueError("source document-root text disposition drifted")
    return set(observed.values()) | wrappers

ORACLE_ID="ocd-schaff-history-vol6-independent-retained-v1"
ORACLE_VERSION="1"
canonical=_canonical
def closure_sha(root):
    names=["build/tei/schaff_history_vol6_current_oracle.py","ocd_kernel/reconstruction/contract.py","ocd_kernel/reconstruction/verifier.py","build/lib/tei_xsd.py"]
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in names])).hexdigest()
def fingerprint(n):return (n.tag,list(n.attrib.items()),n.text,n.tail,tuple(fingerprint(c) for c in n))
def check(manifest,raw):
    manifest.verify();profile=json.loads(manifest.authority_path("profile").read_bytes());source=manifest.authority_path("primary-source").read_bytes()
    if sha256(source).hexdigest()!=profile["source_sha256"]:raise ValueError("retained source differs")
    st=_parse_xml(source,"source");sr=st.getroot();nodes,records=_source_records(sr)
    tree=_parse_xml(raw,"candidate");root=tree.getroot()
    _verify_external_comments(sr,root);represented=_verify_source_projection(sr,root,records)
    if [n.tag for n in root]!=[NS+"teiHeader",NS+"text",NS+"standOff"]:raise ValueError("whole volume shell differs")
    body=root.find(NS+"text/"+NS+"body")
    if any(n not in represented for n in body.iter()):raise ValueError("unaccounted body element")
    expected_header=etree.fromstring(profile["header_xml"].encode())
    actual_header=etree.fromstring(etree.tostring(root[0]));holder=actual_header.find(NS+"fileDesc/"+NS+"notesStmt/"+NS+"note[@type='retained-ThML-header']/"+NS+"p")
    holder.remove(holder[0])
    if fingerprint(actual_header)!=fingerprint(expected_header):raise ValueError("source-attested synthetic header differs")
    for credit in profile["credits"]:
        selected=sr.xpath(credit["source_selector"])
        if len(selected)!=1 or "".join(selected[0].itertext())!=credit["literal_text"]:raise ValueError("literal primary credit differs")
    counts=Counter(r["tag"] for r in records.values())
    if dict(sorted(counts.items()))!=profile["accounting"]["source_tag_counts"] or len(nodes)!=7754 or sum(1 for n in sr.find("ThML.body").iter())!=7654:raise ValueError("complete source census differs")
    if [n.get("id") for n in sr.find("ThML.body")]!=["i","ii","iii","iv"] or len(sr.xpath("ThML.body/div1[@id='iv']/div2"))!=6:raise ValueError("complete native boundary differs")
    from build.lib.tei_xsd import compiled_tei_schema
    compiled_tei_schema(manifest.authority_path("tei-p5-xsd")).assertValid(root)
    return dict(status="pass",source_elements=len(nodes),body_elements=7654,body_roots=4,index_count=6,notes=1353,subject_markers=6,unclear=1,bold=0,superscript=0,language_attributes=270,literal_css_attributes=14,all_source_attributes_parents_ordinals_text_tails_checked=True,p5="pass",prior_exposure="Readonly volume I source mapping and separate oracle inspected; independently adapted for the complete volume VI source, no blind claim.")
def _oracle(manifest,candidate):
    candidate.verify_integrity();profile=json.loads(manifest.authority_path("profile").read_bytes())
    if candidate.manifest["source_manifest"]["sha256"]!=manifest.sha256:raise ValueError("candidate source binding differs")
    check(manifest,candidate.member_bytes("content.tei.xml"))
    if json.loads(candidate.member_bytes("source-accountability.json"))!=profile["accounting"]:raise ValueError("source accounting differs")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("source-readme").read_bytes():raise ValueError("source credit differs")
    if [json.loads(x) for x in candidate.member_bytes("unresolved.jsonl").splitlines()]!=profile["questions"]:raise ValueError("unresolved claims differ")
    if json.loads(candidate.member_bytes("provenance.json"))!={"work_id":profile["work_id"],"source_manifest_sha256":manifest.sha256,"scope":profile["scope"],"status":"nonaccepted","native_reconstruction":True}:raise ValueError("provenance differs")
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=profile["source_sha256"],profile_sha256=sha256(manifest.authority_path("profile").read_bytes()).hexdigest(),package_schema_sha256=manifest.record["package_schema"]["sha256"],xsd_sha256=sha256(manifest.authority_path("tei-p5-xsd").read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path("validation-policy").read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
