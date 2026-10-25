"""LIB-087 retained Hymnary CSV to nonaccepted, source-accounted TEI."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

from lxml import etree

from build.tei.hymnary_csv import read_rows
from build.tei.hymnary_text import append_source_text, character_declarations
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.writer import stamp_header


CONVERTER_ID = "ocd-lib087-hymnary-retained-csv-to-tei"
CONVERTER_VERSION = "1"
T = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _producer_closure(root: Path) -> str:
    paths = ["build/__init__.py", "build/tei/__init__.py", "build/tei/hymnary_reconstruction.py", "build/tei/hymnary_csv.py", "build/tei/hymnary_text.py", "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/tei/__init__.py", "ocd_kernel/tei/writer.py", "ocd_kernel/tei/normalization.py", "ocd_kernel/tei/projection_profile.py"]
    return _sha(_json([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in sorted(paths)]))


def _build(content: bytes, policy: dict, config: dict) -> tuple[bytes, dict, list[dict]]:
    if _sha(content) != policy["csv_sha256"]:
        raise ValueError("LIB-087 retained CSV hash drifted")
    rows = iter(read_rows(content))
    heading = next(rows)
    columns = [field.value for field in heading.fields]
    if columns != policy["columns"]:
        raise ValueError("LIB-087 CSV field labels drifted")
    cursor = heading.end
    records = []
    anomalies = []
    controls = []
    header = stamp_header(title=config["title"], author="", contributors=[], source_url=config["source_url"], source_sha256=_sha(content), print_source=config["source_edition"], rights_statement="Nonaccepted retained-source reconstruction. Provider rights claims and requested attribution remain source assertions; no publication authorization is implied.")
    encoding = etree.SubElement(header, T + "encodingDesc")
    etree.SubElement(encoding, T + "p").text = "Every retained CSV row and all eight fields are preserved in source order. Field text retains literal backslashes and anomalous quotes. Line endings are explicit; glyph references preserve XML-forbidden control codepoints. No deduplication, year coercion, language inference, spelling correction, or generated JSON authority is used."
    encoding.append(character_declarations())
    stream = io.BytesIO()
    with etree.xmlfile(stream, encoding="UTF-8") as writer:
        writer.write_declaration()
        with writer.element(T + "TEI", nsmap={None: T[1:-1]}):
            writer.write(header)
            with writer.element(T + "text"):
                with writer.element(T + "front"):
                    front = etree.Element(T + "div", type="source-field-labels")
                    etree.SubElement(front, T + "head").text = "Retained CSV field labels"
                    labels = etree.SubElement(front, T + "list")
                    for column, field in enumerate(heading.fields, 1):
                        item = etree.SubElement(labels, T + "item", n=str(column), corresp=f"oldest_pd_instances.csv#bytes-{field.start}-{field.end}")
                        append_source_text(item, field.value)
                    writer.write(front)
                with writer.element(T + "body"):
                    for number, row in enumerate(rows, 1):
                        if row.start != cursor or len(row.fields) != 8:
                            raise ValueError("LIB-087 unexplained row boundary or field count")
                        cursor = row.end
                        record_id = f"hymnary-row-{number:05d}"
                        div = etree.Element(T + "div", {XML_ID: record_id, "type": "hymn-record", "n": str(number)})
                        metadata = None
                        fields = []
                        for column, field in enumerate(row.fields, 1):
                            pointer = f"oldest_pd_instances.csv#bytes-{field.start}-{field.end}"
                            if column == 1:
                                target = etree.SubElement(div, T + "head", n="1", corresp=pointer)
                            elif column == 2:
                                target = etree.SubElement(div, T + "ab", type="hymn-text", n="2", corresp=pointer)
                            else:
                                if metadata is None:
                                    metadata = etree.SubElement(div, T + "list", type="source-metadata")
                                item = etree.SubElement(metadata, T + "item", n=str(column))
                                etree.SubElement(item, T + "label").text = columns[column - 1] + ": "
                                target = etree.SubElement(item, T + "seg", type="source-field", n=str(column), corresp=pointer)
                            append_source_text(target, field.value)
                            fields.append({"column": column, "start": field.start, "end": field.end, "raw_sha256": _sha(content[field.start:field.end]), "value_sha256": _sha(field.value.encode("utf-8")), "tei_corresp": pointer})
                            for offset in field.anomalous_quote_offsets:
                                anomalies.append({"kind": "source-quoting", "status": "unresolved", "row": number, "column": column, "byte_offset": offset, "tei_id": record_id, "detail": "Literal backslash and anomalous quote retained; intended editorial escaping is unresolved."})
                            for index, char in enumerate(field.value):
                                if ord(char) < 32 and char not in "\r\n\t":
                                    controls.append({"kind": "source-control", "status": "unresolved", "row": number, "column": column, "character_offset": index, "codepoint": f"U+{ord(char):04X}", "tei_id": record_id, "detail": "Original codepoint represented explicitly; intended reading unresolved."})
                        records.append({"row": number, "start": row.start, "end": row.end, "raw_sha256": _sha(content[row.start:row.end]), "tei_id": record_id, "fields": fields})
                        writer.write(div)
    if cursor != len(content) or len(records) != policy["data_rows"]:
        raise ValueError("LIB-087 complete source row coverage drifted")
    if [row["byte_offset"] for row in anomalies] != policy["anomalous_quote_byte_offsets"]:
        raise ValueError("LIB-087 quoting anomaly census drifted")
    observed_controls = {code: sum(row["codepoint"] == code for row in controls) for code in policy["xml_controls"]}
    if observed_controls != policy["xml_controls"] or sum(observed_controls.values()) != len(controls):
        raise ValueError("LIB-087 control-character census drifted")
    accountability = {"contract": "ocd-lib087-hymnary-source-accountability-v1", "csv_sha256": _sha(content), "csv_bytes": len(content), "bom_bytes": heading.start, "header_start": heading.start, "header_end": heading.end, "header_sha256": _sha(content[heading.start:heading.end]), "columns": columns, "rows": records, "source_quote_anomalies": anomalies, "source_control_anomalies": controls, "unaccounted_bytes": 0}
    return stream.getvalue(), accountability, anomalies + controls


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    if _producer_closure(source_manifest.repository_root) != source_manifest.record["producer_import_closure_sha256"]:
        raise ValueError("LIB-087 producer dependency closure drifted")
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if any(profile[key] != policy[key] for key in ("work_id", "archive_sha256", "csv_sha256", "data_rows", "columns")):
        raise ValueError("LIB-087 complete-source profile and policy disagree")
    config = json.loads(source_manifest.authority_path("work-config").read_bytes())
    archive = source_manifest.authority_path("retained-archive").read_bytes()
    if _sha(archive) != policy["archive_sha256"]:
        raise ValueError("LIB-087 archive binding drifted")
    with zipfile.ZipFile(io.BytesIO(archive)) as retained:
        names = retained.namelist()
        if sorted(names) != sorted([policy["csv_member"], *policy["excluded_archive_members"]]):
            raise ValueError("LIB-087 retained ZIP member envelope drifted")
        members = [{"name": name, "bytes": len(retained.read(name)), "sha256": _sha(retained.read(name)), "disposition": "represented-csv" if name == policy["csv_member"] else policy["excluded_archive_members"][name]} for name in names]
        csv_bytes = retained.read(policy["csv_member"])
    if source_manifest.authority_path("retained-csv").read_bytes() != csv_bytes:
        raise ValueError("LIB-087 extracted review CSV differs from retained ZIP member")
    tei, accounting, unresolved = _build(csv_bytes, policy, config)
    accounting["archive_members"] = members
    provenance = {"contract": "ocd-lib087-hymnary-provenance-v1", "status": "nonaccepted", "work_id": "hymnary-pd", "source_manifest_sha256": source_manifest.sha256, "archive_sha256": _sha(archive), "csv_sha256": _sha(csv_bytes), "policy_sha256": _sha(source_manifest.authority_path("validation-policy").read_bytes()), "generated_json_is_authority": False, "publication_authorized": False}
    return {"content.tei.xml": tei, "source-accountability.json": _json(accounting), "provenance.json": _json(provenance), "unresolved.jsonl": b"".join(_json(row) for row in unresolved), "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
