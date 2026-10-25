"""Independently compare the retained Evangelical Churches XML with readable TEI."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote

from lxml import etree


WORK_ID = "john-owen-evangelical-churches"
SOURCE_SHA256 = "fa7afc08f59e7298af01650dbe455afd2d145c8109fa55eeb17e0835f369c4c1"
NS = {"tei": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
PARSER = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)


def compare(source_bytes: bytes, candidate_bytes: bytes) -> dict[str, object]:
    if sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("retained source hash differs")
    source = etree.fromstring(source_bytes, PARSER)
    candidate = etree.fromstring(candidate_bytes, PARSER)
    body = source.find("ThML.body")
    readable = candidate.xpath(
        "./tei:text/tei:body/tei:div/tei:div[@type='readable-transcription']",
        namespaces=NS,
    )
    if body is None or len(readable) != 1 or candidate.get(XML_ID) != WORK_ID:
        raise ValueError("source or work-local TEI envelope differs")
    source_divisions = body.findall("div1")
    tei_divisions = readable[0].xpath("./tei:div[@type='source-division']", namespaces=NS)
    source_ids = [node.get("id") for node in source_divisions]
    if source_ids != ["i", "ii", "iii", "iv"] or [
        node.get(XML_ID) for node in tei_divisions
    ] != [f"{WORK_ID}--{source_id}" for source_id in source_ids]:
        raise ValueError("the first part, answer, second part, or indexes differ")
    titles = [node.get("title") for node in source_divisions]
    if not (
        source_divisions[0].get("type") == "Work"
        and source_divisions[1].get("type") == "Work"
        and source_divisions[2].get("type") == "Work"
        and titles[3] == "Indexes"
        and "Inquiry" in titles[0]
        and "Stillingfleet" in titles[1]
        and "True Nature" in titles[2]
        and "The first part." in "".join(source_divisions[0].findall("div2")[0].itertext())
        and "[The second part.]" in "".join(source_divisions[2].findall("div2")[0].itertext())
    ):
        raise ValueError("source work/part boundary evidence differs")

    source_nodes = list(body.iter())
    tei_nodes = list(readable[0].iter())
    if len(source_nodes) != len(tei_nodes):
        raise ValueError("readable carrier count differs")
    source_ordinals = {id(node): position for position, node in enumerate(source_nodes)}
    tei_ordinals = {id(node): position for position, node in enumerate(tei_nodes)}
    target_ids = {node.get(XML_ID) for node in tei_nodes if node.get(XML_ID)}
    links = 0
    for position, (original, rendered) in enumerate(zip(source_nodes, tei_nodes), 77):
        if rendered.get("corresp") != f"#evangelicalchurches-node-{position:06d}":
            raise ValueError(f"node order or source correspondence differs at {position}")
        if original.text != rendered.text:
            raise ValueError(f"direct text differs at {position}")
        if position != 77 and original.tail != rendered.tail:
            raise ValueError(f"tail text differs at {position}")
        expected_attributes = " ".join(
            f"urn:ocd:thml-attribute:{quote(key, safe='')}:{quote(value, safe='')}"
            for key, value in original.attrib.items()
        )
        if expected_attributes != (rendered.get("ana") or ""):
            raise ValueError(f"source attributes differ at {position}")
        if position != 77:
            source_parent = original.getparent()
            tei_parent = rendered.getparent()
            if source_ordinals[id(source_parent)] != tei_ordinals[id(tei_parent)]:
                raise ValueError(f"source attachment differs at {position}")
        if original.tag == "note" and etree.QName(rendered).localname != "note":
            raise ValueError(f"note semantics differ at {position}")
        if original.tag == "a" and (href := original.get("href")) and "#" in href:
            prefix, fragment = href.rsplit("#", 1)
            expected_target = f"{prefix}#{WORK_ID}--{fragment}"
            if rendered.get("target") != expected_target or f"{WORK_ID}--{fragment}" not in target_ids:
                raise ValueError(f"local link target differs at {position}")
            links += 1
    return {
        "status": "pass",
        "source_sha256": SOURCE_SHA256,
        "candidate_sha256": sha256(candidate_bytes).hexdigest(),
        "body_carriers": len(source_nodes),
        "source_divisions": source_ids,
        "local_fragment_links_checked": links,
        "check_scope": "node order, text, tail, source attributes, parent attachment, notes, local links, and work parts",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.source.read_bytes(), args.candidate.read_bytes()), sort_keys=True))


if __name__ == "__main__":
    main()
