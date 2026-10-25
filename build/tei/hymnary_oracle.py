"""Independent LIB-087 CSV boundaries and source-to-TEI verification."""
from __future__ import annotations

import csv
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-lib087-hymnary-independent-csv-tei-oracle"
ORACLE_VERSION = "1"
T = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_FIELD = re.compile(rb'"(?:[^"]|""|(?<=\\)"(?=[^",\r\n]))*"|[^",\r\n]*')
_ODD_QUOTE = re.compile(rb'(?<=\\)"(?![",\r\n]|$)')


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("LIB-087 " + message)


def _source_rows(content: bytes):
    """Independent regex field boundaries plus strict stdlib CSV interpretation."""
    content.decode("utf-8")
    csv.field_size_limit(20_000_000)
    offset = 3 if content.startswith(b"\xef\xbb\xbf") else 0
    while offset < len(content):
        start = offset
        fields = []
        while True:
            match = _FIELD.match(content, offset)
            _require(match is not None, f"invalid field at byte {offset}")
            raw = match.group()
            quoted_offsets = [offset + item.start() for item in _ODD_QUOTE.finditer(raw)]
            parse_view = _ODD_QUOTE.sub(b'""', raw).decode("utf-8")
            parsed = list(csv.reader(io.StringIO(parse_view, newline=""), strict=True)) if raw else [[""]]
            _require(len(parsed) == 1 and len(parsed[0]) == 1, "isolated source field is not singular")
            fields.append({"start": offset, "end": match.end(), "value": parsed[0][0], "anomalies": quoted_offsets})
            offset = match.end()
            if offset == len(content):
                break
            marker = content[offset:offset + 1]
            if marker == b",":
                offset += 1
                continue
            if marker == b"\n":
                offset += 1
                break
            if content[offset:offset + 2] == b"\r\n":
                offset += 2
                break
            raise ValueError(f"LIB-087 invalid row separator at byte {offset}")
        yield start, offset, fields


def _field_text(node: ET.Element) -> str:
    value = node.text or ""
    for child in node:
        _require(not len(child), "unexpected nested field markup")
        if child.tag == T + "lb":
            _require(set(child.attrib) == {"n"} and child.text is None, "line-break attributes drifted")
            _require(child.get("n") in {"CRLF", "LF", "CR"}, "unknown source line ending")
            value += {"CRLF": "\r\n", "LF": "\n", "CR": "\r"}[child.get("n")]
        else:
            mapping = {"#hymnary-control-0008": 8, "#hymnary-control-000f": 15, "#hymnary-control-0010": 16}
            _require(child.tag == T + "g" and set(child.attrib) == {"ref"} and child.get("ref") in mapping, "unknown field glyph or markup")
            code = mapping[child.get("ref")]
            _require(child.text == f"[source control U+{code:04X}]", "source-control disclosure changed")
            value += chr(code)
        value += child.tail or ""
    return value


def _closure(repository_root: Path) -> str:
    paths = ["build/tei/hymnary_oracle.py", "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py"]
    return _sha(_json([{"path": path, "sha256": _sha((repository_root / path).read_bytes())} for path in sorted(paths)]))


def _header_contract(config: dict, source_digest: str):
    """Independent closed header specification; no shared header writer."""
    def n(tag, text=None, attrs=None, children=()):
        return (T + tag, tuple(sorted((attrs or {}).items())), text, None, tuple(children))
    chars = []
    for code in (8, 15, 16):
        chars.append(n("char", attrs={XML_ID: f"hymnary-control-{code:04x}"}, children=[
            n("desc", f"RETAINED SOURCE CONTROL U+{code:04X}"),
            n("mapping", f"U+{code:04X}", {"type": "source-codepoint"}),
            n("note", "The source character cannot occur literally in XML 1.0. Its intended editorial reading is unresolved."),
        ]))
    return n("teiHeader", children=[
        n("fileDesc", children=[
            n("titleStmt", children=[n("title", config["title"]), n("author")]),
            n("publicationStmt", children=[n("publisher", "Open Christian Data"), n("availability", attrs={"status": "restricted"}, children=[n("p", "Nonaccepted retained-source reconstruction. Provider rights claims and requested attribution remain source assertions; no publication authorization is implied.")])]),
            n("sourceDesc", children=[n("bibl", children=[n("ptr", attrs={"target": config["source_url"]}), n("idno", source_digest, {"type": "sha256"}), n("note", config["source_edition"], {"type": "print-source"})])]),
        ]),
        n("encodingDesc", children=[n("p", "Every retained CSV row and all eight fields are preserved in source order. Field text retains literal backslashes and anomalous quotes. Line endings are explicit; glyph references preserve XML-forbidden control codepoints. No deduplication, year coercion, language inference, spelling correction, or generated JSON authority is used."), n("charDecl", children=chars)]),
    ])


def _signature(node):
    return (node.tag, tuple(sorted(node.attrib.items())), node.text, node.tail, tuple(_signature(child) for child in node))


def _verify_rows(content: bytes, tei: bytes, accounting: dict, policy: dict, profile: dict | None = None) -> list[dict]:
    source = iter(_source_rows(content))
    header_start, header_end, header = next(source)
    columns = [field["value"] for field in header]
    _require(columns == policy["columns"], "source column labels drifted")
    _require(accounting["csv_sha256"] == _sha(content) and accounting["csv_bytes"] == len(content), "accounting source binding drifted")
    _require((accounting["bom_bytes"], accounting["header_start"], accounting["header_end"], accounting["header_sha256"]) == (header_start, header_start, header_end, _sha(content[header_start:header_end])), "header/BOM accounting drifted")
    _require(accounting["columns"] == columns and accounting["unaccounted_bytes"] == 0, "accounting scope drifted")
    count = 0
    header_seen = False
    anomalies = []
    controls = []
    digest = hashlib.sha256()
    empty = [0] * 8
    endings = Counter()
    for _, node in ET.iterparse(io.BytesIO(tei), events=("end",)):
        if node.tag != T + "div":
            continue
        if node.get("type") == "source-field-labels":
            _require(not header_seen and count == 0 and node.attrib == {"type": "source-field-labels"}, "header repeated or misplaced")
            _require(len(node) == 2 and node[0].tag == T + "head" and node[0].text == "Retained CSV field labels" and node[1].tag == T + "list", "header structure drifted")
            _require(node.text is None and not node[0].attrib and not len(node[0]) and node[0].tail is None and not node[1].attrib and node[1].text is None and node[1].tail is None, "invented source-header markup or text")
            _require(len(node[1]) == len(header), "header field count drifted")
            for column, (item, field) in enumerate(zip(node[1], header, strict=True), 1):
                _require(item.tag == T + "item" and item.attrib == {"n": str(column), "corresp": f'oldest_pd_instances.csv#bytes-{field["start"]}-{field["end"]}'} and _field_text(item) == field["value"], "header source attachment drifted")
                _require(item.tail is None, "invented source-header tail")
            header_seen = True
            node.clear()
            continue
        _require(header_seen and node.get("type") == "hymn-record", "unexpected TEI division")
        count += 1
        source_row = next(source, None)
        _require(source_row is not None, "invented TEI record")
        start, end, fields = source_row
        _require(len(fields) == 8, "source row field count drifted")
        record_id = f"hymnary-row-{count:05d}"
        _require(node.attrib == {XML_ID: record_id, "type": "hymn-record", "n": str(count)}, "record ID or order drifted")
        _require(len(node) == 3 and [child.tag for child in node] == [T + "head", T + "ab", T + "list"], "record structure drifted")
        _require(node.text is None and all(child.tail is None for child in node), "invented record text")
        _require(node[2].attrib == {"type": "source-metadata"} and len(node[2]) == 6 and node[2].text is None, "metadata container drifted")
        targets = [node[0], node[1]]
        for column, item in enumerate(node[2], 3):
            _require(item.tag == T + "item" and item.attrib == {"n": str(column)} and item.text is None and item.tail is None and len(item) == 2, "metadata item drifted")
            _require(item[0].tag == T + "label" and not item[0].attrib and not len(item[0]) and item[0].text == columns[column - 1] + ": " and item[0].tail is None and item[1].tail is None and item[1].tag == T + "seg", "metadata label or attachment drifted")
            targets.append(item[1])
        expected_fields = []
        for column, (target, field) in enumerate(zip(targets, fields, strict=True), 1):
            payload = field["value"].encode("utf-8")
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
            empty[column - 1] += field["value"] == ""
            endings.update(re.findall(r"\r\n|\r|\n", field["value"]))
            pointer = f'oldest_pd_instances.csv#bytes-{field["start"]}-{field["end"]}'
            attrs = {"n": str(column), "corresp": pointer}
            if column == 2:
                attrs["type"] = "hymn-text"
            elif column > 2:
                attrs["type"] = "source-field"
            _require(target.attrib == attrs and _field_text(target) == field["value"], f"field text, semantics or attachment drifted at row {count}, column {column}")
            expected_fields.append({"column": column, "start": field["start"], "end": field["end"], "raw_sha256": _sha(content[field["start"]:field["end"]]), "value_sha256": _sha(field["value"].encode()), "tei_corresp": pointer})
            anomalies.extend({"kind": "source-quoting", "status": "unresolved", "row": count, "column": column, "byte_offset": offset, "tei_id": record_id, "detail": "Literal backslash and anomalous quote retained; intended editorial escaping is unresolved."} for offset in field["anomalies"])
            controls.extend({"kind": "source-control", "status": "unresolved", "row": count, "column": column, "character_offset": index, "codepoint": f"U+{ord(char):04X}", "tei_id": record_id, "detail": "Original codepoint represented explicitly; intended reading unresolved."} for index, char in enumerate(field["value"]) if ord(char) < 32 and char not in "\r\n\t")
        expected_row = {"row": count, "start": start, "end": end, "raw_sha256": _sha(content[start:end]), "tei_id": record_id, "fields": expected_fields}
        _require(count <= len(accounting["rows"]) and accounting["rows"][count - 1] == expected_row, "source byte-range accountability drifted")
        node.clear()
    _require(next(source, None) is None and count == policy["data_rows"] == len(accounting["rows"]), "source or candidate row omission")
    _require(accounting["source_quote_anomalies"] == anomalies and accounting["source_control_anomalies"] == controls, "source anomaly accounting drifted")
    _require([row["byte_offset"] for row in anomalies] == policy["anomalous_quote_byte_offsets"], "quote policy drifted")
    observed = {code: sum(row["codepoint"] == code for row in controls) for code in policy["xml_controls"]}
    _require(observed == policy["xml_controls"] and sum(observed.values()) == len(controls), "control policy drifted")
    if profile is not None:
        named_endings = {{"\r\n": "CRLF", "\r": "CR", "\n": "LF"}[ending]: total for ending, total in endings.items()}
        _require(profile["data_fields"] == count * 8 and profile["empty_fields_by_column"] == empty and profile["line_endings"] == named_endings and profile["ordered_field_sha256"] == digest.hexdigest(), "complete-source feature profile drifted")
        _require(profile["controls"] == {key: value for key, value in observed.items() if value}, "profile control census drifted")
    return anomalies + controls


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict:
    source_manifest.verify()
    candidate.verify_integrity()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    policy = json.loads(policy_bytes)
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    _require(all(profile[key] == policy[key] for key in ("work_id", "archive_sha256", "csv_sha256", "data_rows", "columns")), "profile and policy scope disagree")
    _require(policy["work_id"] == source_manifest.record["work_id"] == "hymnary-pd", "work binding drifted")
    archive = source_manifest.authority_path("retained-archive").read_bytes()
    _require(_sha(archive) == policy["archive_sha256"], "archive digest drifted")
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        names = package.namelist()
        _require(sorted(names) == sorted([policy["csv_member"], *policy["excluded_archive_members"]]), "archive member envelope drifted")
        members = [{"name": name, "bytes": len(package.read(name)), "sha256": _sha(package.read(name)), "disposition": "represented-csv" if name == policy["csv_member"] else policy["excluded_archive_members"][name]} for name in names]
        source = package.read(policy["csv_member"])
    _require(_sha(source) == policy["csv_sha256"], "CSV member hash drifted")
    _require(source_manifest.authority_path("retained-csv").read_bytes() == source, "extracted CSV differs from archive member")
    _require(profile["archive_members"] == [{key: row[key] for key in ("name", "bytes", "sha256")} for row in members], "profile ZIP inventory drifted")
    accounting_bytes = candidate.member_bytes("source-accountability.json")
    accounting = json.loads(accounting_bytes)
    _require(accounting_bytes == _json(accounting), "accounting is not canonical unique-key JSON")
    _require(set(accounting) == {"contract", "csv_sha256", "csv_bytes", "bom_bytes", "header_start", "header_end", "header_sha256", "columns", "rows", "source_quote_anomalies", "source_control_anomalies", "unaccounted_bytes", "archive_members"} and accounting["contract"] == "ocd-lib087-hymnary-source-accountability-v1", "accounting contract drifted")
    _require(accounting["archive_members"] == members, "ZIP support accounting drifted")
    tei = candidate.member_bytes("content.tei.xml")
    unresolved = _verify_rows(source, tei, accounting, policy, profile)
    _require(candidate.member_bytes("unresolved.jsonl") == b"".join(_json(row) for row in unresolved), "unresolved ledger drifted")
    expected_provenance = {"contract": "ocd-lib087-hymnary-provenance-v1", "status": "nonaccepted", "work_id": "hymnary-pd", "source_manifest_sha256": source_manifest.sha256, "archive_sha256": _sha(archive), "csv_sha256": _sha(source), "policy_sha256": _sha(policy_bytes), "generated_json_is_authority": False, "publication_authorized": False}
    _require(candidate.member_bytes("provenance.json") == _json(expected_provenance), "provenance or authority drifted")
    _require(candidate.member_bytes("README.source.md") == source_manifest.authority_path("source-attribution-readme").read_bytes(), "attribution drifted")
    schema_path = source_manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    root = etree.fromstring(tei, etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True))
    _require(schema.validate(root), f"TEI schema failure: {schema.error_log.last_error}")
    config = json.loads(source_manifest.authority_path("work-config").read_bytes())
    _require(root.tag == T + "TEI" and not root.attrib and root.text is None and len(root) == 2 and [child.tag for child in root] == [T + "teiHeader", T + "text"], "TEI document shape drifted")
    _require(_signature(root[0]) == _header_contract(config, _sha(source)), "complete metadata/character declaration header drifted")
    text = root[1]
    _require(not text.attrib and text.text is None and text.tail is None and len(text) == 2 and [child.tag for child in text] == [T + "front", T + "body"], "TEI matter order drifted")
    _require(all(not child.attrib and child.text is None and child.tail is None for child in text), "invented matter text or attributes")
    _require(len(text[0]) == 1 and len(text[1]) == policy["data_rows"] and all(child.tag == T + "div" and child.tail is None for matter in text for child in matter), "unaccounted matter child or tail")
    ns = {"t": T[1:-1]}
    _require(root.xpath("string(t:teiHeader/t:fileDesc/t:titleStmt/t:title)", namespaces=ns) == config["title"], "header title drifted")
    _require(root.xpath("string(t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno)", namespaces=ns) == _sha(source), "header source hash drifted")
    _require(root.xpath("string(t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:ptr/@target)", namespaces=ns) == config["source_url"], "header source URL drifted")
    _require(root.xpath("string(t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:note)", namespaces=ns) == config["source_edition"], "header edition drifted")
    facts = MechanicalFacts(validator_implementation_sha256=_sha(Path(__file__).read_bytes()), validator_import_closure_sha256=_closure(source_manifest.repository_root), source_sha256=_sha(source), profile_sha256=_sha(profile_bytes), policy_sha256=_sha(policy_bytes), package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()), xsd_sha256=_sha(schema_path.read_bytes()), findings=())
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
