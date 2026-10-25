"""Prepare reversible aliases around the existing complete Green text tree."""

from collections import Counter
import copy
import json
from urllib.parse import quote
from xml.etree import ElementTree as ET

from lxml import etree

from build.tools.preflight_green_current import ROOT, LOG, digest, save
from ocd_kernel.projection.native_content import project_content
from ocd_kernel.library._common import PipelineError

NS = "{http://www.tei-c.org/ns/1.0}"
PREFIX = "urn:ocd:green1888:source-role:"
TITLE_TAGS = {"titlePage", "docTitle", "titlePart", "docImprint", "pubPlace", "publisher", "docDate"}


def main():
    raw = (LOG / "historical-package/content.tei.xml").read_bytes()
    if digest(raw) != "82c3bb7c1e1f29bd071a037f4a6056170de2986fda690d3d381b5485ef11cc7d":
        raise ValueError("Exact existing Green candidate differs")
    old = etree.fromstring(raw)
    tree = copy.deepcopy(old)
    text = tree.find(NS + "text")
    before_nodes = list(old.find(NS + "text").iter())
    changes = []
    for ordinal, node in enumerate(text.iter(), 1):
        tag = etree.QName(node).localname
        attrs = list(node.attrib.items())
        case = None
        if tag in TITLE_TAGS:
            node.tag = NS + ("div" if tag == "titlePage" else "ab")
            node.attrib.clear()
            node.set("type", "source-title-page" if tag == "titlePage" else "source-block")
            node.set("subtype", tag)
            node.set("ana", PREFIX + quote(json.dumps({"tag": tag, "attributes": attrs}, ensure_ascii=False, separators=(",", ":")), safe=""))
            case = "printed-title-role"
        elif tag == "note" and node.get("target"):
            # corresp retains the literal source back-reference; no new target.
            node.attrib.clear()
            for name, value in attrs:
                node.set("corresp" if name == "target" else name, value)
            case = "note-back-reference"
        elif tag == "corr" and etree.QName(node.getparent()).localname != "choice":
            if attrs != [("rend", "[space]")] or node.text or len(node):
                raise ValueError("Source standalone correction scope differs")
            node.tag = NS + "seg"
            node.set("type", "source-editorial-correction")
            node.set("subtype", "corr")
            node.set("ana", PREFIX + quote(json.dumps({"tag": tag, "attributes": attrs}, ensure_ascii=False, separators=(",", ":")), safe=""))
            case = "standalone-empty-correction"
        if case:
            changes.append({"ordinal": ordinal, "case": case, "source_tag": tag, "source_attributes": attrs, "current_tag": etree.QName(node).localname, "current_attributes": list(node.attrib.items())})
    counts = dict(Counter(c["case"] for c in changes))
    if counts != {"printed-title-role": 8, "note-back-reference": 12, "standalone-empty-correction": 1}:
        raise ValueError("Exact 21 Green aliases differ")
    restored = copy.deepcopy(text)
    restored_nodes = list(restored.iter())
    for change in changes:
        node = restored_nodes[change["ordinal"] - 1]
        node.tag = NS + change["source_tag"]
        node.attrib.clear()
        for name, value in change["source_attributes"]:
            node.set(name, value)
    old_text = etree.tostring(old.find(NS + "text"))
    if etree.tostring(restored) != old_text:
        raise ValueError("Whole text tree inverse is not byte-exact")
    if len(list(text.iter())) != len(before_nodes):
        raise ValueError("Alias added/omitted native carriers")
    probes = []
    for part in text:
        try:
            result = project_content(ET.fromstring(etree.tostring(part)))
            probes.append({"section": etree.QName(part).localname, "status": "pass", "rendered_characters": len(result.get("text", ""))})
        except PipelineError as exc:
            probes.append({"section": etree.QName(part).localname, "status": "rejected", "reason": str(exc)})
    candidate = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
    save(LOG / "body-adapter-v2.tei.xml", candidate)
    report = {"status": "inverse-pass", "historical_candidate_sha256": digest(raw), "candidate_sha256": digest(candidate), "whole_text_nodes": len(before_nodes), "whole_text_inverse_bytes_equal": True, "historical_text_serialization_sha256": digest(old_text), "changes": changes, "alias_counts": counts, "native_probes": probes, "source_text_tails_hierarchy_ids_preserved": True, "shared_changes": False,
              "semantic_qualification": "Explicit original printed-title tag/attributes retained as reversible source-role annotation; note back-reference exact same URI under corresp; empty corr rendition [space] remains an explicit source-editorial-correction marker, without fabricating a literal space or altered spelling. All 12 ordered sic/corr choices remain unchanged."}
    report["native_probes"] = [{k: v for k, v in item.items() if k != "rendered_characters"} | {"grammar_only": True} for item in probes]
    save(LOG / "body-adapter-inverse-v2.json", (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps({k: v for k, v in report.items() if k != "changes"}))


if __name__ == "__main__":
    main()
