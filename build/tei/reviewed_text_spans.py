"""Apply finite, hash-bound reviewed spans and prove the complete preimage."""
from collections import defaultdict
from copy import deepcopy
import hashlib

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"


def _targets(tree, rows):
    groups = defaultdict(list)
    for row in rows:
        if row["passage_review"] != "pass" or row["mode"] not in {"retained", "generated"}:
            raise ValueError("Unreviewed text span or unsupported disposition")
        groups[row["target_xpath"]].append(row)
    for xpath, spans in groups.items():
        selected = tree.xpath(xpath)
        if len(selected) != 1 or not isinstance(selected[0], etree._Element) or len(selected[0]):
            raise ValueError(f"Reviewed target must be a unique scalar element: {xpath}")
        node = selected[0]
        value = node.text or ""
        spans.sort(key=lambda row: row["start"])
        cursor = 0
        for row in spans:
            start, end = row["start"], row["end"]
            if (hashlib.sha256(value.encode()).hexdigest() != row["unit_sha256"]
                    or not cursor <= start < end <= len(value)
                    or value[start:end] != row["sic"] or not row["corr"]
                    or row["sic"] == row["corr"]):
                raise ValueError(f"Reviewed text preimage or span differs: {xpath}")
            cursor = end
        if len({r["mode"] for r in spans}) != 1:
            raise ValueError("Mixed source dispositions in one target")
        yield node, value, spans


def reconstruct(master: bytes, rows: list[dict]) -> bytes:
    tree = etree.fromstring(master).getroottree()
    for node, value, spans in _targets(tree, rows):
        if spans[0]["mode"] == "generated":
            revised = value
            for row in reversed(spans):
                revised = revised[:row["start"]] + row["corr"] + revised[row["end"]:]
            node.text = revised
        else:
            node.text = value[:spans[0]["start"]] or None
            for index, row in enumerate(spans):
                choice = etree.SubElement(node, TEI + "choice")
                etree.SubElement(choice, TEI + "sic").text = row["sic"]
                etree.SubElement(choice, TEI + "corr").text = row["corr"]
                next_start = spans[index + 1]["start"] if index + 1 < len(spans) else len(value)
                choice.tail = value[row["end"]:next_start] or None
    revised = etree.tostring(tree, encoding="utf-8", xml_declaration=True)
    verify(master, revised, rows)
    return revised


def verify(master: bytes, revised: bytes, rows: list[dict]) -> dict:
    original = etree.fromstring(master).getroottree()
    actual = etree.fromstring(revised).getroottree()
    restored = deepcopy(actual)
    for source, value, spans in _targets(original, rows):
        xpath = spans[0]["target_xpath"]
        observed, = actual.xpath(xpath)
        restore, = restored.xpath(xpath)
        if spans[0]["mode"] == "generated":
            expected = value
            for row in reversed(spans):
                expected = expected[:row["start"]] + row["corr"] + expected[row["end"]:]
            if len(observed) or observed.text != expected:
                raise ValueError("Generated text repair differs")
        else:
            if (observed.text or "") != value[:spans[0]["start"]] or len(observed) != len(spans):
                raise ValueError("Retained text repair prefix or choice count differs")
            for index, (row, choice) in enumerate(zip(spans, observed, strict=True)):
                next_start = spans[index + 1]["start"] if index + 1 < len(spans) else len(value)
                if (choice.tag != TEI + "choice" or choice.attrib or choice.text
                        or len(choice) != 2 or [n.tag for n in choice] != [TEI + "sic", TEI + "corr"]
                        or choice[0].text != row["sic"] or choice[1].text != row["corr"]
                        or any(n.attrib or len(n) or n.tail for n in choice)
                        or (choice.tail or "") != value[row["end"]:next_start]):
                    raise ValueError("Retained reading, correction, or attachment differs")
        for child in list(restore):
            restore.remove(child)
        restore.text = source.text
    if etree.tostring(original, method="c14n") != etree.tostring(restored, method="c14n"):
        raise ValueError("Repair changes content or structure beyond reviewed spans")
    return {"status": "pass", "spans": len(rows), "complete_preimage_restored": True,
            "retained_readings_preserved": sum(r["mode"] == "retained" for r in rows)}
