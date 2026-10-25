"""Reversible native-carrier adaptation of the complete PG22088 TEI candidate."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import re

from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "raw/gutenberg/pg22088.txt"
SOURCE_SHA256 = "18e63c1d0bf11c66d6a6fdda83c19de9005c50b06831785a3507fcd1b6a49073"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/newman-apologia-pg22088-agent-20260928-r1/package/content.tei.xml")
DIRECT_SHA256 = "6f08cc2c2ecd6922536e33b1a606546d871ccfbc0a8835073c79245e15971a5c"
TEI = "{http://www.tei-c.org/ns/1.0}"
EXPECTED = {
    "source-whitespace": 1360,
    "source-column-fragment": 743,
    "numbered-list": 47,
    "numbered-verse-group": 1,
    "numbered-embedded-letter": 9,
    "recipient-address": 8,
    "recipient-address-line": 8,
    "table-cell-source-n": 667,
}
ADAPTED_SHA256 = "147d92cb62c29a243fc84aeb40c3ec1863c1306328d42a938d0aa60145ec71b1"
_NUMBER = re.compile(r"[1-9][0-9]*(?:-[1-9][0-9]*)?\Z")


def direct_candidate() -> bytes:
    if sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG22088 retained plain text differs")
    content = DIRECT.read_bytes()
    if sha256(content).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG22088 current source-bound TEI differs")
    return content


def adapt(raw: bytes) -> tuple[bytes, dict[str, int]]:
    if sha256(raw).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG22088 direct candidate digest differs")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(raw, parser)
    if root.tag != TEI + "TEI":
        raise ValueError("PG22088 direct TEI root differs")
    counts: Counter[str] = Counter()
    for node in root.iter():
        if node.tag == TEI + "ab" and node.get("type") == "source-whitespace":
            if node.get("subtype") is not None:
                raise ValueError("PG22088 whitespace role already has a subtype")
            node.set("type", "source-block")
            node.set("subtype", "source-whitespace")
            counts["source-whitespace"] += 1
        elif node.tag == TEI + "seg" and (node.get("part") or node.get("function")):
            part = node.attrib.pop("part", None)
            function = node.attrib.pop("function", None)
            if (node.get("type") != "source-line-fragment" or node.get("subtype") is not None
                    or part not in {"I", "F", "N"} or function is None
                    or re.fullmatch(r"source-column-[a-z]+-[0-9]+-[0-9]+", function) is None):
                raise ValueError("PG22088 source-column fragment differs")
            node.set("subtype", f"source-part-{part}__{function}")
            counts["source-column-fragment"] += 1
        elif node.tag in {TEI + "list", TEI + "lg", TEI + "floatingText"} and node.get("n") is not None:
            kind = {TEI + "list": "numbered-list", TEI + "lg": "numbered-verse-group",
                    TEI + "floatingText": "numbered-embedded-letter"}[node.tag]
            number = node.attrib.pop("n")
            role = node.get("type")
            if (not _NUMBER.fullmatch(number) or not role or "__source_n_" in role):
                raise ValueError(f"PG22088 {kind} source coordinate differs")
            node.set("type", f"{role}__source_n_{number}")
            counts[kind] += 1
        elif node.tag == TEI + "address":
            if dict(node.attrib) != {"type": "source-recipient"}:
                raise ValueError("PG22088 recipient address differs")
            node.tag = TEI + "seg"
            node.set("type", "source-recipient-address")
            counts["recipient-address"] += 1
        elif node.tag == TEI + "addrLine":
            if node.attrib:
                raise ValueError("PG22088 recipient address line differs")
            node.tag = TEI + "seg"
            node.set("type", "source-recipient-address-line")
            counts["recipient-address-line"] += 1
        elif node.tag == TEI + "cell" and node.get("n") is not None:
            number = node.attrib.pop("n")
            role = node.get("role")
            if not role or "__source_n_" in role or not number or "__source_n_" in number:
                raise ValueError("PG22088 table-cell source coordinate differs")
            node.set("role", f"{role}__source_n_{number}")
            counts["table-cell-source-n"] += 1
    if dict(counts) != EXPECTED:
        raise ValueError(f"PG22088 native carrier census differs: {dict(counts)}")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True), dict(counts)


def partition(adapted: bytes) -> tuple[bytes, bytes, bytes]:
    """Separate source-attested provider divisions from the accepted work text."""
    if sha256(adapted).hexdigest() != ADAPTED_SHA256:
        raise ValueError("PG22088 complete adapted candidate differs")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(adapted, parser)
    scope = root.find(TEI + "text/" + TEI + "body/" + TEI + "div")
    if scope is None or scope.get("type") != "retained-source" or len(scope) != 9:
        raise ValueError("PG22088 source divisions differ")
    header, license = scope[0], scope[-1]
    if ((header.get("type"), header.get("n")) != ("gutenberg-header", "1")
            or (license.get("type"), license.get("n")) != ("gutenberg-license", "13823")
            or scope[1].get("type") != "title-page" or scope[1].get("n") != "33"
            or scope[-2].get("type") != "additional-notes" or scope[-2].get("n") != "13140"):
        raise ValueError("PG22088 source-attested work boundary differs")
    header_bytes = etree.tostring(header, encoding="UTF-8", xml_declaration=True)
    license_bytes = etree.tostring(license, encoding="UTF-8", xml_declaration=True)
    scope.remove(header)
    scope.remove(license)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True), header_bytes, license_bytes
