"""Source-local native-compatible adaptation of the exact PG16739 TEI candidate."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/drummond-pg16739-native-prep-20260928/package/package/content.tei.xml")
DIRECT_SHA256 = "94202dc5bbd1cff9690d2a92c44ddb57bed7d20fe04b93e8da51234c48a9932c"
SOURCE = Path("raw/gutenberg/pg16739.txt")
SOURCE_SHA256 = "12f442db074bfd81db981dfb7c423120e830feb2019b2c0db253692e23624048"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = "{" + TEI + "}"
XML_ID = "{" + XML + "}id"


def direct_candidate() -> bytes:
    source = (ROOT / SOURCE).read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG16739 retained text changed")
    raw = DIRECT.read_bytes()
    if sha256(raw).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG16739 source-bound direct candidate changed")
    return raw


def adapt(raw: bytes) -> tuple[bytes, dict[str, int]]:
    if sha256(raw).hexdigest() != DIRECT_SHA256:
        raise ValueError("PG16739 direct candidate digest differs")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(raw, parser=parser)
    if root.tag != NS + "TEI" or root.get(XML_ID) != "gutenberg-drummond-greatest-thing":
        raise ValueError("PG16739 source-bound TEI identity differs")
    outer = root.find(NS + "text")
    if (outer is None or outer.attrib != {"{" + XML + "}lang": "en"}
            or len(outer) != 1 or outer[0].tag != NS + "group"
            or outer[0].attrib or len(outer[0]) != 1):
        raise ValueError("PG16739 one-member group differs")
    inner = outer[0][0]
    if (inner.tag != NS + "text" or inner.attrib != {XML_ID: "drummond-greatest-thing"}
            or len(inner) != 1 or inner[0].tag != NS + "body"):
        raise ValueError("PG16739 grouped member differs")
    body = inner[0]
    outer.remove(outer[0])
    outer.set(XML_ID, inner.get(XML_ID))
    outer.append(body)
    counts: Counter[str] = Counter()
    for node in list(body.iter()):
        if node.tag == NS + "space":
            if (node.get("type") != "source-blank-line" or node.get("unit") != "line"
                    or node.get("quantity") != "1" or node.get("subtype") != "crlf"
                    or not (node.get("n") or "").isdecimal() or len(node)
                    or (node.text or "").strip()):
                raise ValueError("PG16739 source blank-line marker differs")
            line = node.get("n")
            identifier = node.get(XML_ID)
            if identifier != f"drummond-greatest-thing-blank-{int(line):05d}":
                raise ValueError("PG16739 blank-line identifier differs")
            node.tag = NS + "div"
            node.attrib.clear()
            node.attrib.update({"type": "source-blank-line", "subtype": "crlf", "n": line, XML_ID: identifier})
            counts["space"] += 1
        elif node.tag == NS + "c":
            if (node.attrib.get("type") != "emphasis-delimiter"
                    or not (node.get("corresp") or "").startswith("#drummond-underscore-")
                    or node.text != "_" or len(node)):
                raise ValueError("PG16739 underscore delimiter differs")
            node.tag = NS + "seg"
            counts["c"] += 1
        elif node.tag == NS + "head":
            role = node.get("type")
            if role == "source-located-heading":
                level = node.get("subtype")
                if level not in {"1", "2"}:
                    raise ValueError("PG16739 located heading level differs")
                node.tag = NS + "ab"
                node.set("type", "source-h" + level)
                del node.attrib["subtype"]
                counts["located-head"] += 1
            elif role == "source-attached-title":
                node.tag = NS + "ab"
                node.set("type", "source-heading")
                node.set("subtype", "attached-title")
                counts["attached-title"] += 1
            else:
                raise ValueError("PG16739 source heading type differs")
    if dict(counts) != {"space": 665, "c": 362, "located-head": 18, "attached-title": 3}:
        raise ValueError(f"PG16739 native marker census differs: {dict(counts)}")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True), dict(counts)
