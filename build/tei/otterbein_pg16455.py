"""Reconstruct the retained PG 16455 HTML as one source-bound TEI document."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping
import zipfile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-otterbein-pg16455-complete-html-to-tei-v1"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_PATH = "raw/gutenberg/16455/html/pg16455-images.html"
SOURCE_SHA = "49221d85bf34139c6ddad71dcd31076da47236042cf346fd93da39da1a2d7362"
SOURCE_BYTES = 823187
PROFILE_ID = "otterbein-pg16455-retained-html-v1"
POLICY_ID = "otterbein-pg16455-retained-html-policy-v1"
ORACLE_ID = "ocd-otterbein-pg16455-independent-html-oracle-v1"
IDENTITY = {
    "work_id": "otterbein-hymnal",
    "textual_form_id": "otterbein-hymnal-gutenberg-retained",
    "edition_id": "otterbein-hymnal-gutenberg-electronic",
    "acquisition_id": "otterbein-hymnal-gutenberg-acquired",
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _strict(path: Path, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes().decode("utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _account_paths(root: etree._Element) -> dict[etree._Element, str]:
    return {node: root.getroottree().getpath(node) for node in root.getroottree().iter()}


def _safe_id(value: str) -> str:
    return "ob-" + re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _append_source_unit(parent: etree._Element, child: etree._Element, mapped: etree._Element, tail: str | None, node_ids: Mapping[etree._Element, str]) -> None:
    source_unit = etree.SubElement(parent, f"{{{TEI}}}div", type="source-unit")
    source_unit.set(XML_ID, f"otterbein-unit-{node_ids[child]}")
    if mapped.tag in {f"{{{TEI}}}{name}" for name in ("hi", "ref", "num", "lb", "anchor", "seg", "graphic")}:
        etree.SubElement(source_unit, f"{{{TEI}}}p").append(mapped)
    else:
        source_unit.append(mapped)
    if tail and tail.strip():
        tail_div = etree.SubElement(parent, f"{{{TEI}}}div", type="source-tail")
        etree.SubElement(tail_div, f"{{{TEI}}}p").text = tail
    else:
        source_unit.tail = tail


def _map_html(node: etree._Element, *, node_ids: Mapping[etree._Element, str], source_ids: Mapping[str, str]) -> etree._Element:
    if not isinstance(node.tag, str):
        marker = etree.Element(f"{{{TEI}}}pb", type="source-comment")
        comment = (node.text or "").strip()
        page = re.fullmatch(r'script:\s*pg\("([0-9]+)"\)', comment)
        if page is None:
            raise ValueError(f"unmapped HTML comment: {comment[:80]!r}")
        marker.set("n", page.group(1))
        marker.set(XML_ID, node_ids[node])
        return marker

    tag = node.tag.casefold()
    classes = (node.get("class") or "").split()
    if tag == "div" and "hymn" in classes:
        name = "div"
        number = "".join(node.xpath("./h3/span[contains(concat(' ', normalize-space(@class), ' '), ' num ')]/text()"))
        attrs = {"type": "hymn", "n": number} if number.isdigit() else {"type": "hymn"}
    elif tag == "div" and "verse" in classes:
        name, attrs = "lg", {"type": "stanza"}
    elif tag in {"html", "head", "body", "div", "header", "footer", "blockquote"}:
        name = "div"
        attrs = {"type": "gutenberg-header" if tag == "header" else "gutenberg-footer" if tag == "footer" else "source-blockquote" if tag == "blockquote" else "source-container"}
    elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        # HTML headings may follow prose. A nested division keeps each TEI head
        # in the required leading position while preserving source order.
        heading_div = etree.Element(f"{{{TEI}}}div", type="source-heading")
        heading = etree.SubElement(heading_div, f"{{{TEI}}}head", type=f"source-{tag}")
        if node.get("id"):
            heading.set(XML_ID, source_ids[node.get("id")])
        if node.get("lang"):
            heading.set("{http://www.w3.org/XML/1998/namespace}lang", node.get("lang"))
        if node.text:
            heading.text = node.text
        for child in node:
            mapped_child = _map_html(child, node_ids=node_ids, source_ids=source_ids)
            mapped_child.tail = child.tail
            heading.append(mapped_child)
        return heading_div
    elif tag == "p" and "argument" in classes:
        name, attrs = "note", {"type": "source-argument"}
    elif tag == "p" and "author" in classes:
        name, attrs = "signed", {}
    elif tag == "p" and classes and all(item in {"l", "t", "t2", "t3", "t4", "t5", "tw", "tr"} for item in classes):
        name, attrs = "l", {"rend": " ".join(classes)}
    elif tag == "p":
        name, attrs = "p", {}
    elif tag in {"span", "small", "i", "strong", "b", "em"}:
        if tag == "span" and "num" in classes:
            name, attrs = "num", {"type": "hymn-number"}
        elif tag == "span" and "xnum" in classes:
            name, attrs = "num", {"type": "source-reference-number"}
        else:
            name = "hi"
            attrs = {"rend": "italic" if tag in {"i", "em"} else "bold" if tag in {"strong", "b"} else "small" if tag == "small" else " ".join(classes) or "inline"}
    elif tag == "a":
        href = node.get("href")
        if href:
            name = "ref"
            attrs = {"target": "#" + source_ids[href[1:]] if href.startswith("#") and href[1:] in source_ids else href}
        else:
            name, attrs = "anchor", {}
    elif tag == "br":
        name, attrs = "lb", {}
    elif tag == "hr":
        name, attrs = "milestone", {"unit": "source-rule"}
    elif tag == "table":
        # HTML section wrappers do not have TEI table equivalents. Flatten
        # them while keeping each source row/cell and all intervening text in
        # order; TEI tables contain rows directly.
        result = etree.Element(f"{{{TEI}}}table")
        if node.get("id"):
            result.set(XML_ID, source_ids[node.get("id")])
        result.text = node.text
        for section in node:
            if not isinstance(section.tag, str):
                mapped_section = _map_html(section, node_ids=node_ids, source_ids=source_ids)
                mapped_section.tail = section.tail
                result.append(mapped_section)
                continue
            if section.tag.casefold() in {"tbody", "thead", "tfoot"}:
                if section.text:
                    if len(result):
                        result[-1].tail = (result[-1].tail or "") + section.text
                    else:
                        result.text = (result.text or "") + section.text
                for row in section:
                    mapped_row = _map_html(row, node_ids=node_ids, source_ids=source_ids)
                    mapped_row.tail = row.tail
                    result.append(mapped_row)
                if section.tail:
                    if len(result):
                        result[-1].tail = (result[-1].tail or "") + section.tail
                    else:
                        result.text = (result.text or "") + section.tail
            else:
                mapped_row = _map_html(section, node_ids=node_ids, source_ids=source_ids)
                mapped_row.tail = section.tail
                result.append(mapped_row)
        return result
    elif tag in {"tbody", "thead", "tfoot"}:
        name, attrs = "row", {"type": tag}
    elif tag == "tr":
        name, attrs = "row", {}
    elif tag in {"td", "th"}:
        name, attrs = "cell", {"rend": f"source-{tag}"}
        if node.get("colspan", "1").isdigit() and int(node.get("colspan", "1")) > 1:
            attrs["cols"] = node.get("colspan")
        if node.get("rowspan", "1").isdigit() and int(node.get("rowspan", "1")) > 1:
            attrs["rows"] = node.get("rowspan")
    elif tag in {"ul", "ol"}:
        name, attrs = "list", {"type": "ordered" if tag == "ol" else "unordered"}
    elif tag == "li":
        name, attrs = "item", {}
    elif tag == "pre":
        name, attrs = "p", {"rend": "source-preformatted"}
    elif tag == "img":
        name, attrs = "graphic", {"url": node.get("src", "")}
    elif tag in {"meta", "link", "input"}:
        name, attrs = "milestone", {"unit": f"source-{tag}"}
    else:
        name, attrs = "seg", {"type": f"source-html-{tag}"}

    result = etree.Element(f"{{{TEI}}}{name}")
    for key, value in attrs.items():
        result.set(key, value)
    if "id" in node.attrib:
        result.set(XML_ID, source_ids[node.get("id")])
    if node.get("lang"):
        result.set("{http://www.w3.org/XML/1998/namespace}lang", node.get("lang"))
    if node.get("title") and name not in {"milestone", "graphic"}:
        result.set("n", node.get("title"))
    if node.text:
        if name == "div" and node.text.strip():
            direct_text = etree.SubElement(result, f"{{{TEI}}}p", rend="source-direct-text")
            direct_text.text = node.text
        else:
            result.text = node.text
    for index, child in enumerate(node, 1):
        mapped = _map_html(child, node_ids=node_ids, source_ids=source_ids)
        if tag in {"html", "body", "div", "header", "footer", "blockquote"} and not (tag == "div" and "verse" in classes):
            _append_source_unit(result, child, mapped, child.tail, node_ids)
        else:
            mapped.tail = child.tail
            result.append(mapped)
    return result


def _tei(source_root: etree._Element, profile: Mapping[str, object], node_ids: Mapping[etree._Element, str], source_ids: Mapping[str, str]) -> bytes:
    identity = profile["identity"]
    assert isinstance(identity, Mapping)
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "otterbein-hymnal-candidate")
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = str(identity["work_title"])
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Edmund S. Lorenz"
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}p").text = "Nonaccepted source-bound review candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI}}}bibl")
    etree.SubElement(bibl, f"{{{TEI}}}title").text = str(identity["source_title"])
    etree.SubElement(bibl, f"{{{TEI}}}author").text = "Edmund S. Lorenz"
    etree.SubElement(bibl, f"{{{TEI}}}publisher").text = "United Brethren Publishing House"
    etree.SubElement(bibl, f"{{{TEI}}}pubPlace").text = "Dayton, Ohio"
    etree.SubElement(bibl, f"{{{TEI}}}date", when="1892").text = "1892"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="project-gutenberg").text = "16455"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="source-sha256").text = SOURCE_SHA
    encoding = etree.SubElement(header, f"{{{TEI}}}encodingDesc")
    etree.SubElement(encoding, f"{{{TEI}}}p").text = "The complete decoded HTML body text stream is preserved in order. HTML structure is mapped to TEI carriers and inventoried in source-accountability.json."
    revision = etree.SubElement(header, f"{{{TEI}}}revisionDesc", status="candidate")
    etree.SubElement(revision, f"{{{TEI}}}change", when="2026-09-30").text = "Created as a new independent nonaccepted reconstruction from the retained PG 16455 source."
    text = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text, f"{{{TEI}}}body")
    work_div = etree.SubElement(body, f"{{{TEI}}}div", type="complete-source-work")
    work_div.set(XML_ID, "otterbein-hymnal-complete-source-work")
    source_body = source_root.find(".//body")
    if source_body is None:
        raise ValueError("retained HTML has no body")
    work_div.text = source_body.text
    for child in source_body:
        mapped = _map_html(child, node_ids=node_ids, source_ids=source_ids)
        _append_source_unit(work_div, child, mapped, child.tail, node_ids)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile_path = source_manifest.authority_path("reconstruction-profile")
    policy_path = source_manifest.authority_path("validation-policy")
    profile = _strict(profile_path, "Otterbein profile")
    policy = _strict(policy_path, "Otterbein policy")
    if profile.get("profile_id") != PROFILE_ID or policy.get("policy_id") != POLICY_ID or policy.get("oracle_id") != ORACLE_ID:
        raise ValueError("Otterbein profile or policy identity drifted")
    source_path = source_manifest.authority_path("retained-html")
    source = source_path.read_bytes()
    if len(source) != SOURCE_BYTES or _sha(source) != SOURCE_SHA:
        raise ValueError("retained Otterbein HTML identity drifted")
    root = html.document_fromstring(source)
    ids: dict[str, str] = {}
    for node in root.iter():
        if isinstance(node.tag, str) and node.get("id"):
            key = node.get("id")
            if key in ids:
                raise ValueError(f"duplicate source id: {key}")
            ids[key] = _safe_id(key)
    paths = _account_paths(root)
    node_ids = {node: f"otterbein-source-node-{index:05d}" for index, node in enumerate(root.getroottree().iter(), 1)}
    for node in root.getroottree().iter():
        if isinstance(node.tag, str) and node.get("id"):
            node_ids[node] = ids[node.get("id")]
    content = _tei(root, profile, node_ids, ids)
    body = root.find(".//body")
    assert body is not None
    body_text = "".join(body.itertext())
    body_nodes = list(body.iter())
    hymns = body.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " hymn ")]')
    stanzas = body.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " verse ")]')
    links = body.xpath('.//a[@href]')
    comments = [node for node in body.iter() if not isinstance(node.tag, str)]
    page_numbers = []
    for node in comments:
        match = re.fullmatch(r'script:\s*pg\("([0-9]+)"\)', (node.text or "").strip())
        if match is None:
            raise ValueError(f"unknown body comment: {(node.text or '')[:80]!r}")
        page_numbers.append(match.group(1))
    zip_path = source_manifest.authority_path("acquisition-package")
    cover_path = source_manifest.authority_path("cover-image")
    with zipfile.ZipFile(zip_path) as archive:
        members = {entry.filename: archive.read(entry) for entry in archive.infolist() if not entry.is_dir()}
    if set(members) != {"pg16455-images.html", "16455-cover.png"} or members["pg16455-images.html"] != source or _sha(members["16455-cover.png"]) != _sha(cover_path.read_bytes()):
        raise ValueError("archive members differ from the acquired HTML and cover")
    carriers = []
    for index, node in enumerate(root.getroottree().iter(), 1):
        p = paths.get(node, root.getroottree().getpath(node))
        in_body = node is body or body in node.iterancestors()
        carrier = {
            "source_index": index,
            "selector": p,
            "node_kind": "element" if isinstance(node.tag, str) else "comment",
            "source_name": str(node.tag) if isinstance(node.tag, str) else "#comment",
            "attributes": dict(node.attrib) if isinstance(node.tag, str) else {},
            "direct_text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_sha256": _sha((node.tail or "").encode("utf-8")),
            "disposition": "represented" if in_body and node is not body else "boundary-or-support-metadata",
            "tei_xml_id": node_ids[node] if in_body and node is not body else "not-applicable",
        }
        carriers.append(carrier)
    member_census = [
        {"path": SOURCE_PATH, "bytes": len(source), "sha256": SOURCE_SHA, "role": "primary-source", "decision": "include", "reason": "Canonical acquisition names this extracted HTML as the principal textual source."},
        {"path": "raw/gutenberg/16455/pg16455-h.zip", "bytes": zip_path.stat().st_size, "sha256": _sha(zip_path.read_bytes()), "role": "acquisition-package", "decision": "account-only", "reason": "Container for the selected HTML and retained cover; not a second witness."},
        {"path": "raw/gutenberg/16455/html/16455-cover.png", "bytes": cover_path.stat().st_size, "sha256": _sha(cover_path.read_bytes()), "role": "support-media", "decision": "account-only", "reason": "The HTML body contains no literal image reference to this cover."},
    ]
    source_ids = [node.get("id") for node in root.iter() if isinstance(node.tag, str) and node.get("id")]
    hrefs = [node.get("href") for node in links]
    internal = [href[1:] for href in hrefs if href and href.startswith("#")]
    account = {
        "contract": "ocd-otterbein-pg16455-source-accountability-v1",
        "profile_id": PROFILE_ID,
        "identity": dict(IDENTITY),
        "source": {"path": SOURCE_PATH, "bytes": len(source), "sha256": _sha(source)},
        "member_census": member_census,
        "document_inventory": {"encoding": "UTF-8", "root_tag": str(root.tag), "head_metadata": [{"tag": str(n.tag), "attributes": dict(n.attrib), "text_sha256": _sha((n.text or "").encode("utf-8"))} for n in root.xpath("./head/*") if isinstance(n.tag, str)], "element_count": sum(isinstance(n.tag, str) for n in root.getroottree().iter()), "comment_count": sum(not isinstance(n.tag, str) for n in root.getroottree().iter())},
        "body_text": {"character_count": len(body_text), "sha256": _sha(body_text.encode("utf-8")), "mapping": "exact-decoded-order"},
        "scope_counts": {"body_elements": len(body_nodes), "hymns": len(hymns), "stanzas": len(stanzas), "page_comments": len(page_numbers), "page_marker_numbers": page_numbers, "links": len(hrefs), "internal_links": len(internal), "external_links": len(hrefs)-len(internal), "source_link_targets": hrefs, "source_ids": source_ids, "body_images": len(body.xpath('.//img[@src]'))},
        "carrier_inventory": carriers,
        "coverage": {"expected_body_nodes": len(body_nodes), "represented_body_nodes": sum(n is body or body in n.iterancestors() for n in root.getroottree().iter()), "unmapped_body_nodes": 0, "top_level_complete_work_count": 1, "candidate_tei_document_count": 1},
        "unresolved_ids": ["otterbein-print-collation", "otterbein-page-image-comparison", "otterbein-rights-review", "otterbein-human-acceptance", "otterbein-publication-decision"],
    }
    authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in source_manifest.record["authorities"]}
    unresolved = [
        {"id":"otterbein-print-collation","status":"unresolved","kind":"witness","detail":"The retained electronic transcription has not been collated against a print exemplar."},
        {"id":"otterbein-page-image-comparison","status":"unresolved","kind":"visual","detail":"The retained package has a cover only; source page images are not available in this acquisition."},
        {"id":"otterbein-source-anomaly-h186","status":"unresolved","kind":"source-anomaly","detail":"The previously recorded h186 Cowper-byline attachment question remains for human review; this reconstruction preserves the retained HTML placement without editorial reassignment."},
        {"id":"otterbein-source-anomaly-h469-h470","status":"unresolved","kind":"source-anomaly","detail":"The previously recorded h469/h470 terminal-period placement question remains for human review; this reconstruction preserves the retained HTML text and order."},
        {"id":"otterbein-rights-review","status":"unresolved","kind":"rights","detail":"The Project Gutenberg notice is preserved; applicable rights and jurisdiction have not been cleared."},
        {"id":"otterbein-human-acceptance","status":"unresolved","kind":"acceptance","detail":"This technical candidate has not been accepted as an edition master."},
        {"id":"otterbein-publication-decision","status":"unresolved","kind":"publication","detail":"Publication is not authorized."},
    ]
    provenance = {"contract":"ocd-otterbein-pg16455-candidate-provenance-v1","status":"nonaccepted","ticket_id":"L743","work_id":IDENTITY["work_id"],"source_id":source_manifest.record["source_id"],"source_manifest_sha256":source_manifest.sha256,"identity":profile["identity"],"rights":{"status":"review-required","notice":"The retained Project Gutenberg notice is represented in the candidate; no rights clearance is implied."},"candidate_boundary":{"human_acceptance_status":"unresolved","publication_status":"not-authorized","canonical_master_written":False,"lifecycle_state_changed":False},"authorities":authorities}
    return {"content.tei.xml":content,"source-accountability.json":_json(account),"provenance.json":_json(provenance),"unresolved.jsonl":b"".join(_json(item) for item in unresolved),"README.source.md":source_manifest.authority_path("source-attribution-readme").read_bytes()}


def _producer_closure(root: Path) -> str:
    members = []
    for logical in ("build/tei/otterbein_pg16455.py", "ocd_kernel/reconstruction/contract.py"):
        data = (root / logical).read_bytes()
        members.append({"path": logical, "bytes": len(data), "sha256": _sha(data)})
    return _sha(_json({"contract": "ocd-otterbein-pg16455-producer-closure-v1", "members": members, "lxml": list(etree.LXML_VERSION), "libxml2": list(etree.LIBXML_VERSION)}))


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
