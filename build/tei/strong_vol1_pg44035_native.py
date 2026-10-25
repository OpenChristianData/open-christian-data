"""Source-local native adaptation of Strong's complete PG44035 witness."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/pg44035.txt")
SOURCE_SHA256 = "2e397c9b34b9e2881abbb6185d893014736c6eed8ffe4c4bac1d9a53efee0261"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/strong-systematic-theology-vol1-current-20260928-v1/package/content.tei.xml")
DIRECT_SHA256 = "efc9c47908f80855364b2652c13ec605cbdb41b0750204d1374540996d9eb65e"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
EXPECTED = {"title-page-line": 15, "contents-line": 205, "source-line-space": 26601}


def direct_candidate() -> bytes:
    if sha256((ROOT / SOURCE).read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG44035 retained plain text differs")
    raw = DIRECT.read_bytes()
    if sha256(raw).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG44035 current source-bound TEI differs")
    return raw


def adapt(raw: bytes) -> tuple[bytes, dict[str, int]]:
    if sha256(raw).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG44035 direct candidate digest differs")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(raw, parser)
    if root.tag != TEI + "TEI":
        raise ValueError("PG44035 direct TEI document differs")
    counts: Counter[str] = Counter()
    for node in root.iter():
        if node.tag == TEI + "ab" and node.get("type") in ("title-page-line", "contents-line"):
            kind = node.get("type")
            if (node.get("subtype") is not None or node.get(XML_SPACE) != "preserve"
                    or not (node.get("n") or "").isdecimal()):
                raise ValueError("PG44035 source block carrier differs")
            node.set("type", "source-block")
            node.set("subtype", kind)
            counts[kind] += 1
        elif node.tag == TEI + "seg" and node.get("type") == "source-line":
            if (node.get(XML_SPACE) != "preserve" or node.get("subtype") is not None
                    or not (node.get("n") or "").isdecimal()):
                raise ValueError("PG44035 source line whitespace carrier differs")
            del node.attrib[XML_SPACE]
            node.set("subtype", "xml-space-preserve")
            counts["source-line-space"] += 1
    if dict(counts) != EXPECTED:
        raise ValueError(f"PG44035 source carrier census differs: {dict(counts)}")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True), dict(counts)
