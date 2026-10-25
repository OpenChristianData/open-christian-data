"""Closed reversible archival carrier for this retained Green P5 header.

The segment tree is an annotated representation, not literal source XML.
An independent ElementTree decoder reconstructs the original QName tree;
the work-specific expected serialization hash binds its full conservation.
"""

import json
from urllib.parse import quote, unquote
from xml.etree import ElementTree as ET

from lxml import etree

NS = "http://www.tei-c.org/ns/1.0"
T = "{" + NS + "}"
PREFIX = "urn:ocd:green1888:historical-header:"


def encode(header):
    ordinal = 0
    def visit(node):
        nonlocal ordinal
        if not isinstance(node.tag, str) or not node.tag.startswith(T):
            raise ValueError("Green header archive requires TEI elements")
        ordinal += 1
        data = {"qname": node.tag, "attributes": list(node.attrib.items())}
        carrier = etree.Element(T + "seg", type="source-header-element", subtype=etree.QName(node).localname, n=str(ordinal), corresp=PREFIX + quote(json.dumps(data, ensure_ascii=False, separators=(",", ":")), safe=""))
        carrier.text, carrier.tail = node.text, node.tail
        for child in node:
            carrier.append(visit(child))
        return carrier
    return visit(header)


def decode(carrier_bytes):
    """Independently enforce the exact archive grammar and restore QName data."""
    # Parsing a standalone XML root discards its trailing whitespace. A
    # generated decoder envelope retains the original header's exact tail.
    envelope = ET.fromstring(b"<green-archive-envelope>" + carrier_bytes + b"</green-archive-envelope>")
    if len(envelope) != 1 or envelope.text:
        raise ValueError("Green archive decoder envelope differs")
    root = envelope[0]
    ordinal = 0
    def unique(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise ValueError("Repeated Green header metadata key")
            value[name] = item
        return value
    def visit(node):
        nonlocal ordinal
        ordinal += 1
        if (node.tag != T + "seg" or set(node.attrib) != {"type", "subtype", "n", "corresp"}
                or node.get("type") != "source-header-element" or node.get("n") != str(ordinal)
                or not node.get("corresp", "").startswith(PREFIX)):
            raise ValueError("Green header archive carrier grammar differs")
        encoded = node.get("corresp")[len(PREFIX):]
        data = json.loads(unquote(encoded, errors="strict"), object_pairs_hook=unique)
        if (not isinstance(data, dict) or list(data) != ["qname", "attributes"]
                or not isinstance(data["qname"], str) or not data["qname"].startswith(T)
                or data["qname"][len(T):] != node.get("subtype")
                or not isinstance(data["attributes"], list)
                or quote(json.dumps(data, ensure_ascii=False, separators=(",", ":")), safe="") != encoded):
            raise ValueError("Green header archive canonical metadata differs")
        pairs = data["attributes"]
        if (any(not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(v, str) for v in pair) for pair in pairs)
                or len({pair[0] for pair in pairs}) != len(pairs)):
            raise ValueError("Green header original ordered attributes differ")
        restored = ET.Element(data["qname"])
        for name, value in pairs:
            restored.set(name, value)
        restored.text, restored.tail = node.text, node.tail
        for child in node:
            restored.append(visit(child))
        return restored
    restored = visit(root)
    if restored.tag != T + "teiHeader":
        raise ValueError("Green archival root is not the retained header")
    return restored


def serialize_decoded(node):
    """Serialize the independently restored tree with the original namespace."""
    def visit(element, *, first=False):
        restored = etree.Element(element.tag, nsmap={None: NS} if first else None)
        for name, value in element.attrib.items():
            restored.set(name, value)
        restored.text, restored.tail = element.text, element.tail
        for child in element:
            restored.append(visit(child))
        return restored
    return etree.tostring(visit(node, first=True))
