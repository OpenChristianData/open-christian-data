"""Project one source-attested NPNF113 child from the verified LIB-041 mapping."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Mapping

from lxml import etree

from build.tei.npnf113_lib041_reconstruction import _convert as convert_volume
from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-npnf113-work-root-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    binding = json.loads(manifest.authority_path("work-binding").read_bytes())
    if binding.get("contract") != "ocd-npnf113-work-binding-v1":
        raise ValueError("NPNF113 work binding contract changed")
    volume_path = manifest.authority_path("aggregate-source-manifest")
    volume_manifest = SourceManifest.load(volume_path, repository_root=manifest.repository_root)
    volume = convert_volume(volume_manifest)
    if _sha(volume["content.tei.xml"]) != binding["aggregate_tei_sha256"]:
        raise ValueError("verified aggregate TEI bytes changed")
    aggregate = etree.fromstring(
        volume["content.tei.xml"],
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    ns = {"t": TEI}
    matches = aggregate.xpath(
        "./t:text/t:body/t:div[@corresp=$locator]",
        namespaces=ns,
        locator=f"#npnf113:{binding['source_root_id']}:{binding['work_id']}",
    )
    if len(matches) != 1 or len(aggregate.xpath("./t:text/t:body/t:div", namespaces=ns)) != 10:
        raise ValueError("aggregate work-root selection changed")
    source_bytes = manifest.authority_path("retained-thml").read_bytes()
    if _sha(source_bytes) != binding["source_sha256"]:
        raise ValueError("retained source bytes changed")
    source = etree.fromstring(
        source_bytes,
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True),
    )
    roots = source.xpath("//*[@id=$id]", id=binding["source_root_id"])
    if len(roots) != 1 or roots[0].tag != "div2":
        raise ValueError("retained work root changed")
    selected = roots[0]
    parent = selected.getparent()
    if parent is None or parent.get("id") != binding["source_parent_id"]:
        raise ValueError("retained work parent changed")
    if _sha(etree.tostring(selected, method="c14n")) != binding["source_root_c14n_sha256"]:
        raise ValueError("retained work subtree changed")
    if selected.get("title") != binding["source_title"]:
        raise ValueError("retained work title changed")

    document = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    document.set(XML_ID, f"npnf113-{binding['work_id']}-electronic")
    header = deepcopy(aggregate.find(f"{{{TEI}}}teiHeader"))
    if header is None:
        raise ValueError("aggregate TEI header missing")
    title = header.find(f"{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
    project = header.find(f"{{{TEI}}}encodingDesc/{{{TEI}}}projectDesc/{{{TEI}}}p")
    if title is None or project is None:
        raise ValueError("aggregate TEI header structure changed")
    title.text = binding["source_title"]
    project.text = (
        f"Complete retained NPNF113 div2 {binding['source_root_id']} as one independent work. "
        "Shared volume title and preface remain at their exact retained source locators "
        "and are accounted in source-accountability.json."
    )
    document.append(header)
    text = etree.SubElement(document, f"{{{TEI}}}text")
    body = etree.SubElement(text, f"{{{TEI}}}body")
    body.set(XML_ID, f"npnf113-{binding['work_id']}-body")
    child = deepcopy(matches[0])
    child.tail = None
    body.append(child)
    tei = etree.tostring(document, encoding="UTF-8", xml_declaration=True)

    apparatus = []
    for identifier in binding["shared_apparatus_ids"]:
        nodes = source.xpath("//*[@id=$id]", id=identifier)
        if len(nodes) != 1 or nodes[0].tag != "div2" or nodes[0].getparent() is not parent:
            raise ValueError("shared title or preface boundary changed")
        apparatus.append({
            "source_root_id": identifier,
            "title": nodes[0].get("title"),
            "source_c14n_sha256": _sha(etree.tostring(nodes[0], method="c14n")),
            "disposition": "retained-volume-shared-matter-outside-child-body",
        })
    accounting = {
        "contract": "ocd-npnf113-work-accounting-v1",
        "work_id": binding["work_id"],
        "source_path": binding["source_path"],
        "source_sha256": binding["source_sha256"],
        "source_root_id": binding["source_root_id"],
        "source_parent_id": binding["source_parent_id"],
        "source_title": binding["source_title"],
        "source_root_c14n_sha256": binding["source_root_c14n_sha256"],
        "source_element_count": len([node for node in selected.iter() if isinstance(node.tag, str)]),
        "source_attribute_count": sum(len(node.attrib) for node in selected.iter() if isinstance(node.tag, str)),
        "tei_work_c14n_sha256": _sha(etree.tostring(child, method="c14n")),
        "aggregate_tei_sha256": _sha(volume["content.tei.xml"]),
        "shared_apparatus": apparatus,
        "root_tail_disposition": "excluded-selected-root-boundary",
    }
    provenance = {
        "contract": "ocd-npnf113-work-provenance-v1",
        "status": "nonaccepted",
        "work_id": binding["work_id"],
        "textual_form_id": binding["textual_form_id"],
        "edition_id": binding["edition_id"],
        "acquisition_id": binding["acquisition_id"],
        "source_root_id": binding["source_root_id"],
        "canonical_ir_written": False,
        "publication": "not_ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual review and print collation have not occurred."},
        {"status": "unresolved", "item": "Rights clearance and publication are separate decisions."},
    ]
    readme = (
        f"# {binding['source_title']} — retained NPNF113 electronic witness\n\n"
        f"Source: `{binding['source_path']}#{binding['source_root_id']}` "
        f"(SHA-256 `{binding['source_sha256']}`).\n\n"
        "The complete source-defined child division is represented in `content.tei.xml`. "
        "The volume's shared title page and preface remain in the retained XML and their "
        "exact source roots and hashes are recorded in `source-accountability.json`. "
        "Original notes, headings, and inline order in the child are preserved.\n\n"
        "Sourced via CCEL.org. CCEL permits parsing ThML and asks for attribution; "
        "do not sell CCEL files or derivatives of CCEL formatting. "
        "The retained header states Public Domain. This candidate is nonaccepted; "
        "publication is not ready.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _json(accounting),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
