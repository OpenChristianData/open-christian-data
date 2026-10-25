"""Capture source-line context for held flat and fragmentary bsb829 identities."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/openmgh/bsb00000829/tei/bsb00000829.xml"
SOURCE_SHA = "cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
INVENTORY = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-remainder-inventory-20260926.json"
INVENTORY_SHA = "48fba348fb14f5db2d2c04a230457d9dc37d463c0b023901626f3382e3ede55d"
OUTPUT = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-remainder-flat-boundaries-20260926.json"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _read(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _line(node: etree._Element) -> str:
    siblings = list(node.getparent())
    start = siblings.index(node)
    chunks = [node.tail or ""]
    for sibling in siblings[start + 1:]:
        if sibling.tag == f"{TEI}lb":
            break
        chunks.extend(sibling.itertext())
        chunks.append(sibling.tail or "")
    return " ".join(" ".join(chunks).split())[:240]


def inspect() -> dict:
    if sha256(_read(SOURCE)).hexdigest() != SOURCE_SHA or sha256(_read(INVENTORY)).hexdigest() != INVENTORY_SHA:
        raise ValueError("pinned source or remainder inventory changed")
    inventory = json.loads(_read(INVENTORY))
    document = etree.fromstring(_read(SOURCE),
                                etree.XMLParser(resolve_entities=False, no_network=True,
                                                huge_tree=True))
    volume = document.find(f"{TEI}text/{TEI}body")[0]
    rows = []
    for work in inventory["works"]:
        if work["source_division_ordinal"] == 21:
            continue
        div = volume[work["source_division_ordinal"] - 1]
        ids = {node.get(XML_ID): node for node in div.iter() if node.get(XML_ID)}
        locators = []
        for identifier in work["declared_locator_ids"]:
            node = ids[identifier]
            if node.tag != f"{TEI}lb":
                raise ValueError(f"non-line locator: {work['work_id']} {identifier}")
            sibling_lines = [child for child in node.getparent() if child.tag == f"{TEI}lb"]
            ordinal = sibling_lines.index(node)
            locators.append({"xml_id": identifier, "line_ordinal_zero_based": ordinal,
                             "previous": _line(sibling_lines[ordinal - 1]) if ordinal else None,
                             "line": _line(node),
                             "next": _line(sibling_lines[ordinal + 1])
                             if ordinal + 1 < len(sibling_lines) else None})
        rows.append({"work_id": work["work_id"], "division": work["source_division_ordinal"],
                     "native_part_ordinal": work["native_part_ordinal"],
                     "declared_locator_ids": work["declared_locator_ids"],
                     "source_order_ids": work["locator_order_in_source"],
                     "locators": locators})
    return {"contract": "ocd-openmgh-bsb829-flat-boundaries-v1",
            "source_sha256": SOURCE_SHA, "inventory_sha256": INVENTORY_SHA,
            "work_count": len(rows), "works": rows}


def main() -> int:
    value = inspect()
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if OUTPUT.exists() and OUTPUT.read_bytes() != content:
        raise ValueError("existing boundary excerpts differ")
    OUTPUT.write_bytes(content)
    print(json.dumps({"works": len(value["works"]), "receipt": OUTPUT.as_posix(),
                      "sha256": sha256(content).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
