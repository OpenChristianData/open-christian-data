"""Independent source-tree and readable-structure oracle for held hymn routes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canon(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _closure(root: Path) -> str:
    paths = ("build/tei/l671_l674_semantic_oracle.py", "ocd_kernel/reconstruction/contract.py",
             "ocd_kernel/reconstruction/verifier.py", "ocd_kernel/tei/validate.py")
    return _sha(_canon([{"path": item, "sha256": _sha((root / item).read_bytes())} for item in paths]))


def _role(node: etree._Element) -> str:
    classes = set((node.get("class") or "").split())
    if "hymn" in classes: return "hymn"
    if "verse" in classes: return "verse"
    if node.tag.lower() == "table" and "poem" in classes: return "poem"
    if node.tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}: return "heading-" + node.tag.lower()
    if node.tag.lower() == "blockquote": return "quotation"
    return "html-" + node.tag.lower()


def _source(manifest: SourceManifest, profile: dict) -> tuple[etree._Element, list[dict]]:
    archive_raw = manifest.authority_path("retained-archive").read_bytes()
    if _sha(archive_raw) != profile["archive_sha256"]: raise ValueError("archive hash/source identity mismatch")
    with ZipFile(manifest.authority_path("retained-archive")) as zf:
        if zf.testzip() is not None: raise ValueError("retained ZIP CRC failure")
        members = [{"path": info.filename, "bytes": info.file_size, "crc32": f"{info.CRC:08x}", "sha256": _sha(zf.read(info))}
                   for info in zf.infolist() if not info.is_dir()]
        if members != profile["archive_members"]: raise ValueError("complete archive member set changed")
        raw = zf.read(profile["html_member"])
    extraction = "retained-html" if any(a["name"] == "retained-html" for a in manifest.record["authorities"]) else "extracted-html"
    if raw != manifest.authority_path(extraction).read_bytes() or _sha(raw) != profile["html_sha256"]:
        raise ValueError("archive/extraction identity mismatch")
    body = html.fromstring(raw.decode("utf-8", errors="strict")).find(".//body")
    if body is None: raise ValueError("source body missing")
    if len(body) != profile.get("body_direct_children", len(body)): raise ValueError("source body direct boundary changed")
    return body, members


def _expected_rows(body: etree._Element) -> tuple[list[tuple[str, str, str, str, str, str | None, str | None]], str]:
    """Independent preorder ledger of source element paths, parents, and text slots."""
    elements: list[tuple[str, str, str, str, str, str | None, str | None]] = []
    text: list[str] = []

    def walk(node: etree._Element, path: str, parent_path: str) -> None:
        tag = node.tag.lower()
        attrs = dict(sorted(node.attrib.items()))
        descriptor = "source-tag:" + tag + ";source-attributes:" + json.dumps(attrs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        target_tag = "ref" if tag == "a" else "seg"
        elements.append((path, parent_path, _role(node), descriptor, target_tag, node.get("href") if tag == "a" else None, node.get("id")))
        if node.get("id"): text.append("")
        if node.text:
            text.append(node.text)
        for index, child in enumerate(node, 1):
            if isinstance(child.tag, str):
                walk(child, f"{path}/{index}", path)
            else:
                comment_path = f"{path}/{index}"
                elements.append((comment_path, path, "source-comment", None, "seg", None, None))
                if child.text: text.append(child.text)
            if child.tail:
                text.append(child.tail)

    if body.text: text.append(body.text)
    for index, node in enumerate(body, 1):
        if isinstance(node.tag, str):
            walk(node, f"body/{index}", "body")
        else:
            elements.append((f"body/{index}", "body", "source-comment", None, "seg", None, None))
            if node.text: text.append(node.text)
        if node.tail: text.append(node.tail)
    return elements, "".join(text)


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    root = manifest.repository_root
    profile_raw = manifest.authority_path("profile").read_bytes(); profile = json.loads(profile_raw)
    policy_raw = manifest.authority_path("policy").read_bytes(); policy = json.loads(policy_raw)
    source_body, members = _source(manifest, profile)
    xml = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    schema = compiled_schema()
    if not schema.validate(tree): raise ValueError("candidate is not TEI P5: " + str(schema.error_log[:1]))
    row = profile["ticket_id"]
    expected_root_id = "pg" + str(profile["ebook_id"]) + "-" + str(profile["work_id"])
    if etree.QName(tree).localname != "TEI" or tree.get(XML_ID) != expected_root_id: raise ValueError("one-work root identity mismatch")
    title = tree.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
    if title is None or title.text != profile["title"]: raise ValueError("candidate title/edition mismatch")
    body = tree.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if body is None or body.get("n") != row: raise ValueError("TEI work body is missing or bound to another manifest row")
    targets = body.xpath(".//tei:seg[@n] | .//tei:ref[@n]", namespaces={"tei": TEI})
    actual = []
    for item in targets:
        parent = item.getparent()
        parent_path = parent.get("n") if etree.QName(parent).localname in {"seg", "ref"} else "body"
        actual.append((item.get("n"), parent_path, item.get("type"), item.get("rend"), etree.QName(item).localname,
                       item.get("target"), item.get(XML_ID)))
    expected, source_text = _expected_rows(source_body)
    if actual != expected: raise ValueError("readable source element hierarchy, role, attributes, or order changed")
    # Content text is represented only by explicit p carriers, in exact order.
    target_text = "".join(body.itertext())
    if target_text != source_text: raise ValueError("source wording, ordering, or text/tail content changed")
    source_anchor_count = sum(1 for node in source_body.iter() if isinstance(node.tag, str) and node.tag.lower() == "a")
    target_ref_count = len(body.xpath(".//tei:ref[@n]", namespaces={"tei": TEI}))
    ids = [node.get(XML_ID) for node in tree.iter() if node.get(XML_ID)]
    if target_ref_count != source_anchor_count or len(ids) != len(set(ids)):
        raise ValueError("source anchors are not represented by unique linked TEI refs")
    source_ids = [node.get("id") for node in source_body.iter() if isinstance(node.tag, str) and node.get("id")]
    tei_source_ids = [node.get(XML_ID) for node in body.iter() if node.get(XML_ID)]
    source_internal_targets = [node.get("href")[1:] for node in source_body.iter()
                               if isinstance(node.tag, str) and node.get("href", "").startswith("#")]
    missing_internal_targets = sorted(set(source_internal_targets) - set(source_ids))
    tei_internal_targets = [node.get("target")[1:] for node in body.xpath(".//tei:ref[starts-with(@target, '#')]", namespaces={"tei": TEI})]
    if tei_source_ids != source_ids or tei_internal_targets != source_internal_targets or missing_internal_targets:
        raise ValueError("source IDs or internal reference targets are missing, unresolved, or false")
    if not any(item[2] in {"hymn", "verse", "poem", "quotation"} or item[2].startswith("heading-") for item in actual):
        raise ValueError("candidate lacks readable source-role structure")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if (account.get("ticket_id") != row or account.get("source_id") != profile["source_id"] or
        account.get("work_id") != profile["work_id"] or account.get("edition_id") != profile["edition_id"] or
        account.get("archive_sha256") != profile["archive_sha256"] or account.get("html_sha256") != profile["html_sha256"] or
        account.get("archive_members") != members or account.get("carriers") != profile["carriers"] or
        account.get("source_anchor_count") != source_anchor_count or account.get("tei_ref_count") != target_ref_count or
        account.get("source_id_count") != len(source_ids) or account.get("source_ids_sha256") != _sha(_canon(source_ids)) or
        account.get("source_internal_ref_count") != len(source_internal_targets) or
        account.get("unresolved_internal_target_count") != len(missing_internal_targets) or
        account.get("tei_sha256") != _sha(xml)):
        raise ValueError("candidate source-accountability does not bind the current complete source")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("readme").read_bytes(): raise ValueError("source notice changed")
    if json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]: raise ValueError("provenance status changed")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canon(item) for item in policy["unresolved"]): raise ValueError("unresolved human decisions changed")
    closure = _closure(root)
    if closure != manifest.record["validator"]["import_closure_sha256"]: raise ValueError("oracle closure hash changed")
    facts = MechanicalFacts(validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure, source_sha256=_sha(archive_raw := manifest.authority_path("retained-archive").read_bytes()),
        profile_sha256=_sha(profile_raw), package_schema_sha256=_sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(manifest.authority_path("tei-p5-xsd").read_bytes()), policy_sha256=_sha(policy_raw), findings=())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-l671-l674-readable-hymn-source-oracle"
_oracle.oracle_version = "1"
_oracle.implementation_path = Path(__file__).resolve()
