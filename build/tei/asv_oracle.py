"""Independent recursive source reader and actual-tree checker for ASV only.

No producer imports, producer inventories, or producer mapping helpers are used.
JSON decoding is shared Python infrastructure; lxml reads the actual TEI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from lxml import etree
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _encoded(record):
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _decode(data):
    def pairs(values):
        names = [entry[0] for entry in values]
        if len(names) != len(set(names)):
            raise ValueError("oracle: duplicate source key")
        return dict(values)
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs)


def closure_digest():
    root = Path(__file__).resolve().parents[2]
    members = ["ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py",
               "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py"]
    return _digest(_encoded({name: _digest((root / name).read_bytes()) for name in members}))


def check_content(source_bytes, tei_bytes, accounting_bytes):
    source = _decode(source_bytes)
    leaves = []
    containers = []
    def visit(value, pointer):
        if isinstance(value, dict):
            expected = (["translation", "books"] if pointer == "" else
                        ["name", "chapters"] if re.fullmatch(r"/books/\d+", pointer) else
                        ["chapter", "verses"] if re.fullmatch(r"/books/\d+/chapters/\d+", pointer) else
                        ["verse", "text"] if re.fullmatch(r"/books/\d+/chapters/\d+/verses/\d+", pointer) else None)
            if list(value) != expected:
                raise ValueError(f"oracle: unknown source object {pointer}")
            for key, item in value.items():
                visit(item, pointer + "/" + key)
        elif isinstance(value, list):
            if not value:
                raise ValueError(f"oracle: empty source container {pointer}")
            containers.append((pointer, len(value)))
            for index, item in enumerate(value):
                visit(item, f"{pointer}/{index}")
        else:
            leaves.append((pointer, value))
    visit(source, "")
    if source.get("translation") != "ASV: American Standard Version (1901)" or len(source["books"]) != 66:
        raise ValueError("oracle: wrong ASV identity/envelope")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    tree = etree.fromstring(tei_bytes, parser)
    if tree.getroottree().docinfo.doctype:
        raise ValueError("oracle: unexpected document type")
    q = lambda local: f"{{{NS}}}{local}"
    if tree.tag != q("TEI") or dict(tree.attrib) != {f"{{{XML}}}id": "asv"}:
        raise ValueError("oracle: TEI work identity")
    if [n.tag for n in tree] != [q("teiHeader"), q("text")]:
        raise ValueError("oracle: TEI root topology")
    header = tree[0]
    expected_header = [
        ("teiHeader", {}, None, 1), ("fileDesc", {}, None, 3),
        ("titleStmt", {}, None, 1), ("title", {f"{{{XML}}}id": "asv-title"}, source["translation"], 0),
        ("publicationStmt", {}, None, 1), ("p", {}, "Nonaccepted reconstruction for review; publication is not authorized.", 0),
        ("sourceDesc", {}, None, 1), ("p", {}, "Complete retained JSON witness: raw/bible_databases/formats/json/ASV.json. The provider label is preserved; a complete physical 1901 edition is not asserted.", 0),
    ]
    observed_header = [(etree.QName(n).localname, dict(n.attrib), n.text, len(n)) for n in header.iter()]
    if observed_header != expected_header or any(n.tag != q(etree.QName(n).localname) for n in header.iter()):
        raise ValueError("oracle: header meaning or metadata drift")
    text = tree[1]
    if dict(text.attrib) or len(text) != 1 or text[0].tag != q("body") or dict(text[0].attrib):
        raise ValueError("oracle: body topology")
    body = text[0]
    index = {}
    for node in tree.iter():
        if not isinstance(node.tag, str):
            raise ValueError("oracle: unexpected XML comment/processing instruction")
        if node.tail is not None:
            raise ValueError("oracle: invented tail text")
        identity = node.get(f"{{{XML}}}id")
        if identity:
            if identity in index:
                raise ValueError("oracle: duplicate TEI identity")
            index[identity] = node
    actual_fields = []
    expected_ids = {"asv", "asv-title"}
    expected_counts = {"books": 66, "chapters": 0, "verses": 0}
    for pointer, length in containers:
        parts = pointer.split("/")
        if pointer == "/books":
            parent = body
            child_ids = [f"asv-b{i+1}" for i in range(length)]
        elif parts[-1] == "chapters":
            b = int(parts[2])+1
            parent = index.get(f"asv-b{b}")
            child_ids = [f"asv-b{b}-title"] + [f"asv-b{b}-c{i+1}" for i in range(length)]
            expected_counts["chapters"] += length
        elif parts[-1] == "verses":
            b, c = int(parts[2])+1, int(parts[4])+1
            parent = index.get(f"asv-b{b}-c{c}")
            child_ids = [f"asv-b{b}-c{c}-v{i+1}" for i in range(length)]
            expected_counts["verses"] += length
        else:
            raise ValueError(f"oracle: unknown array {pointer}")
        if parent is None or [n.get(f"{{{XML}}}id") for n in parent] != child_ids:
            raise ValueError(f"oracle: source order/attachment/omission {pointer}")
        expected_ids.update(child_ids)
    if expected_counts != {"books": 66, "chapters": 1189, "verses": 31102}:
        raise ValueError("oracle: ASV complete scope counts")
    if set(index) != expected_ids:
        raise ValueError("oracle: invented/missing identities")
    for pointer, value in leaves:
        parts = pointer.split("/")
        attr = None
        if pointer == "/translation":
            target = "asv-title"
        elif parts[-1] == "name":
            target = f"asv-b{int(parts[2])+1}-title"
        else:
            b, c = int(parts[2])+1, int(parts[4])+1
            target = f"asv-b{b}-c{c}"
            if parts[-1] == "chapter":
                ordinal = c
                attr = "n"
            else:
                v = int(parts[6])+1
                target += f"-v{v}"
                if parts[-1] == "verse":
                    ordinal = v
                    attr = "n"
                elif parts[-1] != "text":
                    raise ValueError(f"oracle: unknown scalar {pointer}")
        node = index[target]
        if attr:
            if type(value) is not int or value != ordinal or node.get(attr) != str(value):
                raise ValueError(f"oracle: source numbering {pointer}")
        elif not isinstance(value, str) or not value or node.text != value or len(node):
            raise ValueError(f"oracle: source text conservation {pointer}")
        actual_fields.append({"pointer": pointer, "value_sha256": _digest(_encoded(value)), "target": target, "attribute": attr, "disposition": "preserved"})
    for node in body.iter():
        identity = node.get(f"{{{XML}}}id")
        if node is body:
            allowed = {}; tag = "body"
        elif re.fullmatch(r"asv-b\d+", identity or ""):
            allowed = {f"{{{XML}}}id": identity, "type": "book", "n": identity[5:]}; tag = "div"
        elif (identity or "").endswith("-title"):
            allowed = {f"{{{XML}}}id": identity}; tag = "head"
        elif re.fullmatch(r"asv-b\d+-c\d+", identity or ""):
            allowed = {f"{{{XML}}}id": identity, "type": "chapter", "n": identity.split("-c")[1]}; tag = "div"
        elif re.fullmatch(r"asv-b\d+-c\d+-v\d+", identity or ""):
            allowed = {f"{{{XML}}}id": identity, "type": "verse", "n": identity.split("-v")[1], f"{{{XML}}}space": "preserve"}; tag = "ab"
        else:
            raise ValueError("oracle: unknown readable node")
        if node.tag != q(tag) or dict(node.attrib) != allowed or (tag in {"body", "div"} and node.text is not None):
            raise ValueError(f"oracle: meaningful TEI attributes/topology {identity}")
    if text.text is not None or tree.text is not None:
        raise ValueError("oracle: invented root/text prose")
    accounting = _decode(accounting_bytes)
    if accounting != {"contract": "ocd-asv-accounting-v1", "source_sha256": _digest(source_bytes), "fields": actual_fields, "excluded": []}:
        raise ValueError("oracle: incomplete source accounting")
    return expected_counts


def oracle(manifest, candidate):
    manifest.verify()
    candidate.verify_integrity()
    source_bytes = manifest.authority_path("asv-source").read_bytes()
    tei_bytes = (candidate.path / "content.tei.xml").read_bytes()
    check_content(source_bytes, tei_bytes, (candidate.path / "source-accountability.json").read_bytes())
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    schema.assertValid(etree.fromstring(tei_bytes))
    for member, authority in [("README.source.md", "asv-readme"), ("unresolved.jsonl", "asv-unresolved")]:
        if (candidate.path / member).read_bytes() != manifest.authority_path(authority).read_bytes():
            raise ValueError(f"oracle: supporting member drift {member}")
    bindings = {entry["name"]: entry["sha256"] for entry in manifest.record["authorities"]}
    expected_provenance = {"source_manifest_sha256": manifest.sha256, "authorities": bindings, "converter": dict(manifest.record["converter"]), "scope": "complete retained ASV JSON; no complete-print-edition claim"}
    if _decode((candidate.path / "provenance.json").read_bytes()) != expected_provenance:
        raise ValueError("oracle: provenance drift")
    facts = MechanicalFacts(_digest(Path(__file__).read_bytes()), closure_digest(), _digest(source_bytes),
                            bindings["asv-profile"], bindings["candidate-package-schema"], bindings["tei-p5-xsd"], bindings["asv-policy"], ())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


oracle.oracle_id = "ocd-lib023-asv-independent-oracle"
oracle.oracle_version = "1"
