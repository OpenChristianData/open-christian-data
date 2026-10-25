"""Preserve the first six-line epitaph and literal shared triplex heading."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

def _convert(manifest: SourceManifest):
    manifest.verify()
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    boundary = json.loads(manifest.authority_path("boundary-review").read_bytes())
    work = json.loads(manifest.authority_path("work-sidecar").read_bytes())
    raw = manifest.authority_path("extracted-xml").read_bytes()
    if profile["contract"] != "ocd-georgii-primum-profile-v1" or sha256(raw).hexdigest() != profile["source_sha256"] or work["work_id"] != profile["work_id"] or work["title"] not in (profile["original_work_title"], profile["work_title"]):
        raise ValueError("source/profile/work identity changed")
    source = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if source.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE forbidden")
    volume = source.find(f"{TEI}text/{TEI}body/{TEI}div")
    if len(volume) != 3 or volume[2].get("n") != "Carmina" or len(volume[2]) != 1:
        raise ValueError("volume/Carmina inventory changed")
    ab = volume[2][0]
    if ab.tag != TEI + "ab" or len(ab) != 959:
        raise ValueError("epitaph source carrier changed")
    selected = list(ab)[89:96]
    if sha256(b"".join(etree.tostring(e, method="c14n", with_comments=True, with_tail=True) for e in selected)).hexdigest() != profile["selection_c14n_sha256"]:
        raise ValueError("entire first-epitaph selection changed")
    excerpt = deepcopy(ab)
    for node in list(excerpt):
        excerpt.remove(node)
    for node in selected:
        excerpt.append(deepcopy(node))
    root = etree.Element(TEI + "TEI", nsmap={None: TEI[1:-1]})
    root.set(XML_ID, "ocd-lambertus-epitaphium-georgii-primum-bsb720-electronic-v1")
    fd = etree.SubElement(etree.SubElement(root, TEI + "teiHeader"), TEI + "fileDesc")
    etree.SubElement(etree.SubElement(fd, TEI + "titleStmt"), TEI + "title").text = profile["work_title"]
    original = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    fd.append(deepcopy(original.find(TEI + "publicationStmt")))
    etree.SubElement(etree.SubElement(fd, TEI + "notesStmt"), TEI + "note").text = profile["source_qualification"]
    etree.SubElement(fd, TEI + "sourceDesc").append(deepcopy(original.find(f"{TEI}sourceDesc/{TEI}biblFull")))
    wrapper = etree.SubElement(etree.SubElement(etree.SubElement(root, TEI + "text"), TEI + "body"), TEI + "div", type="work", n=profile["work_title"])
    wrapper.append(excerpt)
    accounting = dict(boundary, contract="ocd-georgii-primum-accounting-v1", edition_id=profile["edition_id"], acquisition_id=profile["acquisition_id"], zip_disposition="Retained acquisition package only; extracted XML is textual authority.")
    provenance = dict(contract="ocd-georgii-primum-provenance-v1", status="nonaccepted", work_id=work["work_id"], edition_id=profile["edition_id"], acquisition_id=profile["acquisition_id"], source_sha256=sha256(raw).hexdigest(), canonical_ir_written=False, publication="not-authorized")
    unresolved = [dict(status="unresolved", item="Close visual/print comparison and human review are not recorded."), dict(status="unresolved", item="Independent rights clearance and publication remain separate.")]
    readme = (f"# {profile['work_title']} retained electronic candidate\n\nThe complete first six-line epitaph only, with the shared triplex heading preserved as context. {profile['source_qualification']} Source publication and print bibliography are preserved. Monumenta Germaniae Historica and the Bavarian State Library request source attribution.\n").encode()
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True), "source-accountability.json": _json(accounting), "provenance.json": _json(provenance), "unresolved.jsonl": b"".join(_json(e) for e in unresolved), "README.source.md": readme}

_convert.converter_id = "ocd-georgii-primum-to-tei"
_convert.converter_version = "1"
