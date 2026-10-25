"""Portable closed archive grammar plus optional exact retained-header proof."""

import copy
import hashlib
import os
from pathlib import Path

from lxml import etree
import pytest

from build.tei.green_header_archive import T, encode, decode, serialize_decoded


def restore(carrier):
    return serialize_decoded(decode(etree.tostring(carrier)))


def test_header_archive_preserves_qnames_ordered_attributes_text_tail():
    header = etree.Element(T + "teiHeader", nsmap={None: T[1:-1]})
    header.set("type", "literal-role")
    header.set("{http://www.w3.org/XML/1998/namespace}id", "source-header")
    header.text = "\n  "
    header.tail = "\n  "
    child = etree.SubElement(header, T + "fileDesc")
    child.text = " literal "
    child.tail = "\n"
    nested = etree.SubElement(child, T + "titleStmt")
    nested.text = "x"
    nested.tail = " y "
    assert restore(encode(header)) == etree.tostring(header)


@pytest.mark.parametrize("case,diagnostic", [
    ("foreign-carrier", "carrier grammar"),
    ("extra-attribute", "carrier grammar"),
    ("wrong-ordinal", "carrier grammar"),
    ("wrong-type", "carrier grammar"),
    ("wrong-subtype", "canonical metadata"),
    ("wrong-prefix", "carrier grammar"),
    ("noncanonical-encoding", "canonical metadata"),
])
def test_archive_rejects_unsupported_carrier(case, diagnostic):
    source = etree.Element(T + "teiHeader", nsmap={None: T[1:-1]})
    etree.SubElement(source, T + "fileDesc")
    carrier = encode(source)
    if case == "foreign-carrier": carrier[0].tag = "{urn:foreign}seg"
    elif case == "extra-attribute": carrier[0].set("invented", "yes")
    elif case == "wrong-ordinal": carrier[0].set("n", "1")
    elif case == "wrong-type": carrier[0].set("type", "plain-text")
    elif case == "wrong-subtype": carrier[0].set("subtype", "body")
    elif case == "wrong-prefix": carrier[0].set("corresp", "urn:other:abc")
    elif case == "noncanonical-encoding": carrier[0].set("corresp", carrier[0].get("corresp").replace("%7B", "%7b"))
    with pytest.raises(ValueError, match=diagnostic): restore(carrier)


@pytest.fixture(scope="module")
def retained_header():
    default = Path(__file__).resolve().parents[1] / "reports/_logs/green-current-reconciliation-20261002-v1/historical-package/content.tei.xml"
    path = Path(os.environ.get("OCD_GREEN_RETAINED_CANDIDATE", str(default)))
    if not path.is_file():
        pytest.skip("Exact retained Green candidate unavailable; set OCD_GREEN_RETAINED_CANDIDATE")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "82c3bb7c1e1f29bd071a037f4a6056170de2986fda690d3d381b5485ef11cc7d"
    return etree.fromstring(raw).find(T + "teiHeader")


def test_all_99_retained_header_elements_have_exact_inverse(retained_header):
    assert len(list(retained_header.iter())) == 99
    assert restore(encode(retained_header)) == etree.tostring(retained_header)


@pytest.mark.parametrize("case", ["omission", "duplicate", "order", "text", "tail", "root-tail", "ordered-attribute-value"])
def test_saved_header_hash_rejects_shape_valid_mutation(retained_header, case):
    carrier = encode(retained_header)
    if case == "omission":
        carrier[0][0].remove(carrier[0][0][0])
    elif case == "duplicate":
        carrier[0][0].append(copy.deepcopy(carrier[0][0][0]))
    elif case == "order":
        parent = carrier[0][0]
        a, b = parent[0], parent[1]
        parent.remove(b); parent.insert(0, b)
    elif case == "text": carrier[0][0][0].text = "altered source wording"
    elif case == "tail": carrier[0][0][0].tail = "altered source tail"
    elif case == "root-tail": carrier.tail = "\n "
    elif case == "ordered-attribute-value":
        from urllib.parse import quote, unquote
        import json
        node = next(n for n in carrier.iter() if '"attributes":[]' not in unquote(n.get("corresp")))
        prefix, encoded = node.get("corresp").rsplit(":", 1)
        payload = json.loads(unquote(encoded))
        payload["attributes"][0][1] += " mutation"
        node.set("corresp", prefix + ":" + quote(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), safe=""))
    try:
        changed = restore(carrier)
    except ValueError as exc:
        assert "carrier grammar" in str(exc)
    else:
        assert hashlib.sha256(changed).digest() != hashlib.sha256(etree.tostring(retained_header)).digest()
