"""Prepare inspected exclusive bsb750 work sources without accepting them.

The list is intentionally narrower than the old locator-discovery inventory.
Each listed edition is one source-native complete direct-child work division;
the separately headed composite and mismatched-title cases need other routes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tools import prepare_openmgh_exclusive_manifests as manifests
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000750/tei/bsb00000750.xml")
SOURCE_SHA = "a88f93a090b6fd452a05b3cbc39a50f7bd7059cd94547f3cd712a4937243f0fc"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
WORK_ORDINALS = {
    "miracula-post-mortem-martini-vertavensis": 35,
    "passio-sancti-floriani": 5,
    "virtus-sancti-aniani-aurelianensis": 10,
    "vita-sancti-betharii": 37,
    "vita-sancti-caesarii-arelatis": 27,
    "vita-sancti-droctovei": 32,
    "vita-sancti-fidoli": 26,
    "vita-sancti-fridolini-baltheri": 19,
    "vita-sancti-iohannis-reomaensis": 28,
    "vita-sancti-leonardi": 24,
    "vita-sancti-lucii-confessoris": 1,
    "vita-sancti-maximini-trevirensis": 6,
    "vita-sancti-nicetii-lugdunensis": 29,
    "vita-sancti-severini-acaunensis": 13,
    "vita-sancti-theudarii": 30,
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def prepare(work_id: str) -> dict[str, str]:
    if work_id not in WORK_ORDINALS:
        raise ValueError(f"work is outside inspected remaining tranche: {work_id}")
    raw = Path(_io_path(ROOT / SOURCE)).read_bytes()
    if _sha(raw) != SOURCE_SHA:
        raise ValueError("extracted bsb750 source changed")
    root = etree.fromstring(raw, parser=etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False,
        huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DTD is not allowed")
    body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if body is None or len(body) != 1:
        raise ValueError("source body does not have one volume")
    volume = body[0]
    works = list(volume)
    if len(works) != 39 or any(w.tag != f"{{{TEI}}}div" or w.get("type") != "work"
                               for w in works):
        raise ValueError("source work envelope changed")
    selected = works[WORK_ORDINALS[work_id] - 1]
    preflight = json.loads(manifests.PREFLIGHT.read_bytes())
    rows = [row for row in preflight["works"] if row["work_id"] == work_id]
    if len(rows) != 1:
        raise ValueError("source discovery entry is not unique")
    row = rows[0]
    locators = row["locators"]
    first, last = (locators[0]["reference"].split("#", 1)[1],
                   locators[-1]["reference"].split("#", 1)[1])
    for xml_id in (first, last):
        matches = root.xpath("//*[@xml:id=$id]", namespaces={"xml": XML}, id=xml_id)
        if len(matches) != 1 or selected not in matches[0].iterancestors():
            raise ValueError(f"{work_id} locator not unique in inspected division: {xml_id}")
    text = " ".join(" ".join(selected.itertext()).split())
    if len(text) < 100:
        raise ValueError("selected source division has too little text")
    children = [f"{etree.QName(c).localname}:{c.get('type', '')}" for c in selected]
    local_ids = {node.get(f"{{{XML}}}id") for node in selected.iter()
                 if node.get(f"{{{XML}}}id")}
    for node in selected.iter():
        for key, value in node.attrib.items():
            if etree.QName(key).localname in {"target", "corresp", "sameAs", "ana"}:
                for target in value.split():
                    if target.startswith("#") and target[1:] not in local_ids:
                        raise ValueError(f"{work_id} has a cross-division reference: {target}")
    boundary = {
        "contract": "ocd-openmgh-exclusive-boundary-review-v1",
        "work_id": work_id,
        "scope_assertion": "whole-work-div",
        "review_status": "agent-inspected-source-boundary",
        "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA,
        "work_div_n": selected.get("n"),
        "start_xml_id": first,
        "end_xml_id": last,
        "opening_evidence": text[:90],
        "closing_evidence": text[-90:],
        "note": (f"Complete retained electronic work division {WORK_ORDINALS[work_id]} of 39. "
                 f"Direct children: {', '.join(children)}. The exact selected source tree "
                 "is retained, including source-marked prefaces, chapters, parts and "
                 "continuations. This is an electronic-witness scope, with no claim of "
                 "print collation or ownership of volume siblings."),
    }
    boundary_path = ROOT / "sources/openmgh-exclusive" / work_id / "boundary-review.json"
    manifests._write(boundary_path, _json(boundary), refresh=False)
    result = manifests._prepare(work_id, row, refresh=False)
    result["source_div_c14n_sha256"] = _sha(etree.tostring(
        selected, method="c14n", with_comments=True))
    result["boundary_sha256"] = _sha(boundary_path.read_bytes())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_ids", nargs="*", choices=sorted(WORK_ORDINALS))
    args = parser.parse_args()
    selected = args.work_ids or sorted(WORK_ORDINALS)
    for work_id in selected:
        print(json.dumps(prepare(work_id), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
