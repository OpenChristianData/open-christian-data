"""Inventory the 26 bsb829 holds remaining after the distinct 24-part tranche."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000829/tei/bsb00000829.xml")
SOURCE_SHA = "cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb829-inspected-batch-20260926.json")
BATCH_SHA = "6623a27ea9998fbd9fad1379eafa3fc6b58d887ad00b8b42b92f5441e86cf947"
DIRECT = Path(r"D:\Library\Open Christian Data\candidate-reviews\openmgh-bsb829-parts-20260926\receipt.json")
DIRECT_SHA = "55443bc3df3528ac772651c2cfc0a93f2c309a954ce4db4408028825f5fee7f1"
OUTPUT = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-remainder-inventory-20260926.json"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _read(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _sha(path: Path) -> str:
    return sha256(_read(path)).hexdigest()


def _work_locators(work: dict) -> list[str]:
    editions = [edition for form in work["textual_forms"]
                for edition in form["editions"]]
    if len(editions) != 1:
        raise ValueError(f"ambiguous work edition: {work['work_id']}")
    locators = editions[0]["containing_source"]["locator"].split("; ")
    if len(locators) not in (2, 3, 4) or any(not value.startswith(SOURCE.as_posix() + "#")
                                             for value in locators):
        raise ValueError(f"non-source locator: {work['work_id']}")
    return [value.split("#", 1)[1] for value in locators]


def _short(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())[:180]


def _ancestors(node: etree._Element, div: etree._Element) -> list[dict]:
    result = []
    for ancestor in (node, *node.iterancestors()):
        if ancestor is div:
            break
        parent = ancestor.getparent()
        result.append({"tag": etree.QName(ancestor).localname,
                       "type": ancestor.get("type"), "xml_id": ancestor.get(XML_ID),
                       "sibling_ordinal_zero_based": list(parent).index(ancestor)})
    return result


def build() -> dict:
    for path, expected in ((ROOT / SOURCE, SOURCE_SHA), (ROOT / BATCH, BATCH_SHA),
                           (DIRECT, DIRECT_SHA)):
        if _sha(path) != expected:
            raise ValueError(f"frozen source/receipt changed: {path}")
    batch = json.loads(_read(ROOT / BATCH))
    direct = json.loads(_read(DIRECT))
    completed = {item["work_id"] for item in direct["candidates"]}
    remaining = sorted(set(batch["holds"]) - completed)
    if len(remaining) != 26:
        raise ValueError("expected 26 remaining bsb829 holds")
    document = etree.fromstring(_read(ROOT / SOURCE),
                                etree.XMLParser(resolve_entities=False, no_network=True,
                                                huge_tree=True))
    volume = document.find(f"{TEI}text/{TEI}body")[0]
    divisions = list(volume)
    id_nodes: dict[str, list[etree._Element]] = {}
    for node in document.iter():
        identifier = node.get(XML_ID)
        if identifier:
            id_nodes.setdefault(identifier, []).append(node)
    rows = []
    for work_id in remaining:
        work_path = ROOT / "library/works" / work_id / "work.json"
        work = json.loads(_read(work_path))
        locators = _work_locators(work)
        if any(len(id_nodes.get(identifier, [])) != 1 for identifier in locators):
            raise ValueError(f"locator is absent or repeated: {work_id}")
        selected = [id_nodes[identifier][0] for identifier in locators]
        source_divisions = [i for i, div in enumerate(divisions, start=1)
                            if all(div in (node, *node.iterancestors())
                                   for node in selected)]
        if len(source_divisions) != 1:
            raise ValueError(f"declared pair crosses source divisions: {work_id}")
        ordinal = source_divisions[0]
        div = divisions[ordinal - 1]
        native_parts = [part for part in div if part.tag == f"{TEI}div"
                        and part.get("type") == "part"
                        and all(part in (node, *node.iterancestors())
                                for node in selected)]
        if len(native_parts) > 1:
            raise ValueError(f"more than one native part: {work_id}")
        part = native_parts[0] if native_parts else None
        nodes = list(div.iter())
        ordered = sorted(selected, key=nodes.index)
        start, end = ordered[0], ordered[-1]
        first, last = start.get(XML_ID), end.get(XML_ID)
        start_index, end_index = nodes.index(start), nodes.index(end)
        rows.append({"work_id": work_id, "work_title": work["title"],
                     "work_sidecar": (Path("library/works") / work_id / "work.json").as_posix(),
                     "work_sidecar_sha256": _sha(work_path),
                     "frozen_hold": batch["holds"][work_id],
                     "source_division_ordinal": ordinal,
                     "division_child_count": len(div),
                     "native_part_ordinal": list(div).index(part) + 1 if part is not None else None,
                     "native_part_count": sum(child.tag == f"{TEI}div" and child.get("type") == "part"
                                              for child in div),
                     "declared_locator_ids": locators,
                     "locator_count": len(locators),
                     "locator_order_in_source": [node.get(XML_ID) for node in ordered],
                     "locator_nodes": [{"xml_id": node.get(XML_ID),
                                        "source_order_index": nodes.index(node),
                                        "tag": etree.QName(node).localname,
                                        "ancestry": _ancestors(node, div),
                                        "context": _short(node.getparent())}
                                       for node in selected],
                     "start_xml_id": first, "end_xml_id": last,
                     "start_node_index": start_index, "end_node_index": end_index,
                     "start_ancestry": _ancestors(start, div),
                     "end_ancestry": _ancestors(end, div),
                     "division_opening": _short(div),
                     "start_context": _short(start.getparent()),
                     "end_context": _short(end.getparent()),
                     "division_closing": " ".join(" ".join(div.itertext()).split())[-180:]})
    return {"contract": "ocd-openmgh-bsb829-remainder-inventory-v1",
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "frozen_batch_path": BATCH.as_posix(), "frozen_batch_sha256": BATCH_SHA,
            "completed_parts_receipt": DIRECT.as_posix(),
            "completed_parts_receipt_sha256": DIRECT_SHA,
            "remaining_count": 26, "works": rows}


def main() -> int:
    value = build()
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if OUTPUT.exists() and OUTPUT.read_bytes() != content:
        raise ValueError("existing remainder inventory differs")
    OUTPUT.write_bytes(content)
    groups: dict[int, list[str]] = {}
    for row in value["works"]:
        groups.setdefault(row["source_division_ordinal"], []).append(row["work_id"])
    print(json.dumps({"remaining": len(value["works"]),
                      "division_groups": {str(k): len(v) for k, v in groups.items()},
                      "receipt": OUTPUT.as_posix(), "sha256": sha256(content).hexdigest()},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
