"""Two-work assessment bridge from accepted Creeds.json TEI to doctrinal rows.

This is a bounded projection candidate, not a release adapter. It consumes the
accepted TEI JSON scalar carriers, preserves all source metadata in its private
receipt, and checks every carrier against retained JSON independently.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree

from build.tei.creeds_json_lib063_oracle import _strict_json, _verify_json_node
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import edition_by_id
from ocd_kernel.projection.categories.doctrinal_documents import _validate_rows
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTRACT = "ocd-two-creeds-json-accepted-bridge-assessment-v1"
KINDS = {"Canon": "canon", "Creed": "creed"}
WORKS = {"belgic-confession-of-faith", "chalcedonian-definition"}
SOURCE_PATHS = {
    "belgic-confession-of-faith": "raw/Creeds.json/creeds/belgic_confession_of_faith.json",
    "chalcedonian-definition": "raw/Creeds.json/creeds/chalcedonian_definition.json",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json(path: Path) -> dict[str, object]:
    value = _strict_json(_io_path(path).read_bytes(), str(path))
    return value


def _context(root: Path, acceptance_path: Path) -> dict[str, object]:
    accepted = validate_acceptance(_io_path(acceptance_path), root=_io_path(root))
    identity = accepted["identity"]
    work_id = identity["work_id"]
    if work_id not in WORKS or accepted["promotion"]["status"] != "promoted":
        raise PipelineError("bridge requires one of two promoted Creeds.json works")
    work, edition = edition_by_id(_io_path(root), identity["edition_id"], work_id=identity["work_id"])
    if work.work_id != work_id or edition.textual_form_id != identity["textual_form_id"]:
        raise PipelineError("accepted work/edition identity differs")
    if edition.record.get("category") != "doctrinal-documents" or edition.record.get("language") != "en":
        raise PipelineError("source-evidenced edition category/language rebind is missing")
    accounting = _json(root / accepted["source"]["accounting"]["path"])
    kind = accounting.get("document_kind")
    evidence = accounting.get("metadata_evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("path"), str):
        raise PipelineError("accepted metadata evidence binding is missing")
    if evidence["path"] != f"library/works/{work_id}/integration/creeds-json-metadata-rebind-v1/metadata-evidence.json":
        raise PipelineError("metadata evidence path differs from the bounded work route")
    metadata_evidence = _json(root / evidence["path"])
    if (_sha(_io_path(root / evidence["path"]).read_bytes()) != evidence.get("sha256")
            or _io_path(root / evidence["path"]).stat().st_size != evidence.get("bytes")
            or kind != metadata_evidence.get("document_kind")
            or metadata_evidence.get("work_id") != work_id):
        raise PipelineError("accepted source metadata evidence differs")
    source = accepted["source"]
    if source["source_path"] != SOURCE_PATHS[work_id]:
        raise PipelineError("accepted retained member is outside the two-work route")
    source_bytes = _io_path(root / source["source_path"]).read_bytes()
    if _sha(source_bytes) != source["source_sha256"]:
        raise PipelineError("retained source bytes differ from acceptance")
    document = _strict_json(source_bytes, "retained Creeds.json member")
    if not isinstance(document.get("Metadata"), dict) or "Data" not in document:
        raise PipelineError("retained Creeds.json member has no Metadata/Data envelope")
    if KINDS.get(document["Metadata"].get("CreedFormat")) != kind:
        raise PipelineError("document kind does not bind retained CreedFormat")
    master = root / accepted["promotion"]["master"]["path"]
    return {
        "root": root, "accepted": accepted, "identity": identity,
        "work_id": work_id, "edition_title": edition.title,
        "kind": kind, "master": master, "master_bytes": _io_path(master).read_bytes(),
        "source_bytes": source_bytes, "document": document,
        "source_path": source["source_path"],
        "source_url": _json(root / source["source_manifest"]["path"])["url"],
        "accounting": accounting,
    }


def _children(node: ET.Element, *, tag: str, type_name: str | None = None) -> list[ET.Element]:
    result = list(node)
    if any(child.tag != TEI + tag or (type_name is not None and child.get("type") != type_name)
           for child in result):
        raise PipelineError(f"accepted JSON tree has unexpected {tag} children")
    return result


def _decode(node: ET.Element, path: str, loci: dict[str, str]) -> object:
    kind = node.get("type")
    identifier = node.get(XML_ID)
    if node.tag != TEI + "div" or not identifier or path in loci:
        raise PipelineError("accepted JSON node identity or path differs")
    loci[path] = identifier
    if kind == "json-object":
        result: dict[str, object] = {}
        for ordinal, wrapper in enumerate(_children(node, tag="div", type_name="json-member"), 1):
            children = list(wrapper)
            if (wrapper.get("n") != str(ordinal) or len(children) != 2
                    or children[0].tag != TEI + "head" or children[0].get("type") != "json-key"
                    or not isinstance(children[0].text, str) or not children[0].text
                    or children[0].text in result):
                raise PipelineError("accepted JSON member order or key differs")
            key = children[0].text
            loci[f"{path}/{key}#member"] = wrapper.get(XML_ID) or ""
            result[key] = _decode(children[1], f"{path}/{key}", loci)
        return result
    if kind == "json-array":
        values = []
        for index, wrapper in enumerate(_children(node, tag="div", type_name="json-item")):
            children = list(wrapper)
            if wrapper.get("n") != str(index) or len(children) != 1:
                raise PipelineError("accepted JSON item order differs")
            loci[f"{path}/{index}#item"] = wrapper.get(XML_ID) or ""
            values.append(_decode(children[0], f"{path}/{index}", loci))
        return values
    if kind == "json-string":
        children = list(node)
        if (len(children) != 1 or children[0].tag != TEI + "ab"
                or children[0].get("type") != "json-scalar" or len(children[0])):
            raise PipelineError("accepted JSON string carrier differs")
        return children[0].text or ""
    raise PipelineError(f"unsupported accepted JSON scalar: {kind}")


def _producer_tree(context: dict[str, object]) -> tuple[dict[str, object], dict[str, str]]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    root = ET.fromstring(context["master_bytes"], parser=parser)
    if root.tag != TEI + "TEI":
        raise PipelineError("accepted TEI root differs")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1:
        raise PipelineError("accepted TEI body envelope differs")
    carrier = body[0]
    if (carrier.tag != TEI + "div" or carrier.get("type") != "retained-json-document"
            or carrier.get("corresp") != context["source_path"] or len(carrier) != 3):
        raise PipelineError("accepted retained JSON document carrier differs")
    byte_block, semantic = carrier[1], carrier[2]
    if (byte_block.get("type") != "retained-byte-stream" or len(byte_block) != 1
            or byte_block[0].tag != TEI + "ab" or byte_block[0].get("type") != "base64-application-json"):
        raise PipelineError("accepted retained-byte carrier differs")
    try:
        decoded_bytes = base64.b64decode(byte_block[0].text or "", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PipelineError("accepted retained-byte carrier is not base64") from exc
    if decoded_bytes != context["source_bytes"]:
        raise PipelineError("accepted retained-byte carrier differs from source")
    if semantic.get("type") != "json-semantic-tree" or len(semantic) != 1:
        raise PipelineError("accepted semantic JSON carrier differs")
    loci: dict[str, str] = {}
    decoded = _decode(semantic[0], "$", loci)
    if decoded != context["document"]:
        raise PipelineError("accepted TEI semantic JSON differs from retained source")
    return decoded, loci


def _rows(context: dict[str, object], document: dict[str, object], loci: dict[str, str]) -> list[dict[str, object]]:
    metadata = document["Metadata"]
    data = document["Data"]
    work_id = context["work_id"]
    if work_id == "belgic-confession-of-faith":
        if not isinstance(data, list) or len(data) != 37:
            raise PipelineError("Belgic source does not have 37 ordered articles")
        units = []
        for index, item in enumerate(data):
            if (not isinstance(item, dict) or set(item) != {"Article", "Title", "Content"}
                    or not all(isinstance(item[key], str) and item[key] for key in item)
                    or item["Article"] != str(index + 1)):
                raise PipelineError(f"Belgic article {index + 1} shape or number differs")
            units.append((index + 1, item["Article"], item["Title"], item["Content"], f"$/Data/{index}"))
    elif work_id == "chalcedonian-definition":
        if not isinstance(data, dict) or set(data) != {"Content"} or not isinstance(data["Content"], str) or not data["Content"]:
            raise PipelineError("Chalcedonian source has unsupported Data fields")
        units = [(1, None, None, data["Content"], "$/Data")]
    else:
        raise PipelineError("work is outside two-work bridge")
    identity = {key: context["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")}
    if not isinstance(metadata.get("Title"), str) or not metadata["Title"]:
        raise PipelineError("source metadata title is missing")
    provenance = {
        "edition_title": context["edition_title"],
        "source_title": metadata["Title"],
        "source_url": context["source_url"],
        "source_location": context["source_path"],
    }
    rows: list[dict[str, object]] = []
    for sequence, number, title, content, path in units:
        anchor = loci.get(f"{path}#item") if work_id == "belgic-confession-of-faith" else loci.get(f"{path}/Content#member")
        if not anchor:
            raise PipelineError(f"accepted TEI has no source unit anchor: {path}")
        division = {"order": sequence, "type": "article", "number": number, "titles": [title]} if title is not None else None
        rows.append({
            **identity,
            "record_id": f"{identity['edition_id']}:unit-{sequence:06d}",
            "sequence": sequence, "category": "doctrinal_documents", "language": "en",
            "representation_revision": context["accepted"]["representation_revision"]["id"],
            "text": content, "document_id": work_id, "document_kind": context["kind"],
            "unit_type": "article" if number is not None else "text",
            "number": number, "title": title, "content": content,
            "content_blocks": [content], "content_with_proofs": None,
            "proofs": [], "revision_history": [], "parent_path": ["Data"],
            "locator": {
                "kind": "unit", "text_part": "body", "part_titles": [],
                "divisions": [division] if division is not None else [],
                "unit": anchor,
                "unit_path": ["Data", str(sequence - 1)] if number is not None else ["Data", "Content"],
                "source_order": sequence,
            },
            "provenance": provenance,
        })
    _validate_rows(rows)
    return rows


def _receipt(context: dict[str, object], rows: list[dict[str, object]], loci: dict[str, str]) -> dict[str, object]:
    metadata = context["document"]["Metadata"]
    return {
        "contract": CONTRACT,
        "status": "assessment-only",
        "identity": {key: context["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")},
        "master_sha256": _sha(context["master_bytes"]),
        "source_sha256": _sha(context["source_bytes"]),
        "source_path": context["source_path"],
        "category": "doctrinal_documents", "language": "en",
        "document_kind": context["kind"],
        "row_count": len(rows), "rows_sha256": _sha(_canonical(rows)),
        "metadata_disposition": "All retained Metadata fields are bound here as source metadata; only Title and CreedFormat also inform public rows. OriginalLanguage is the historical work label, not the English electronic text language.",
        "retained_metadata": metadata,
        "metadata_sha256": _sha(_canonical(metadata)),
        "source_carrier_count": len(loci),
        "unit_anchors": [row["locator"]["unit"] for row in rows],
        "data_disposition": "All Data fields are projected exactly: Belgic Article/Title/Content in 37 ordered rows or Chalcedonian Content in one row. No proof or revision is inferred from prose.",
        "unprojected_source_content": [],
        "limits": ["bounded accepted electronic witness", "not a release", "rights and historical print lineage separate"],
    }


def project(root: Path, *, acceptance_path: Path) -> dict[str, object]:
    context = _context(root, acceptance_path)
    document, loci = _producer_tree(context)
    rows = _rows(context, document, loci)
    return {"rows": rows, "receipt": _receipt(context, rows, loci)}


def _oracle_tree(context: dict[str, object]) -> dict[str, object]:
    """Independently challenge the full accepted TEI against retained JSON."""
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, remove_pis=False)
    root = etree.fromstring(context["master_bytes"], parser)
    if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
        raise PipelineError("independent checker rejects TEI declarations or comments")
    original = _io_path(context["root"] / "library/works" / context["work_id"] / "integration/creeds-json-electronic-v1/inputs/package/content.tei.xml").read_bytes()
    boundary = b"</teiHeader>"
    if (context["master_bytes"].count(boundary) != 1 or original.count(boundary) != 1
            or context["master_bytes"].split(boundary, 1)[1] != original.split(boundary, 1)[1]):
        raise PipelineError("independent checker accepted TEI body differs from source-oracle candidate")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or len(body[0]) != 3:
        raise PipelineError("independent checker body shape differs")
    byte_block = body[0][1]
    if byte_block.get("type") != "retained-byte-stream" or len(byte_block) != 1:
        raise PipelineError("independent checker retained-byte block differs")
    if base64.b64decode(byte_block[0].text or "", validate=True) != context["source_bytes"]:
        raise PipelineError("independent checker retained-byte content differs")
    semantic = body[0][2]
    if semantic.get("type") != "json-semantic-tree" or len(semantic) != 1:
        raise PipelineError("independent checker semantic tree differs")
    state: dict[str, object] = {
        "next_ordinal": 1, "objects": 0, "arrays": 0, "members": 0,
        "items": 0, "strings": 0, "numbers": 0, "booleans": 0,
        "nulls": 0, "crosswalk": [],
    }
    _verify_json_node(semantic[0], context["document"], work_id=context["work_id"], path="$", state=state)
    accounting = _json(context["root"] / "library/works" / context["work_id"] / "integration/creeds-json-electronic-v1/inputs/package/source-accountability.json")
    state["crosswalk"] = sorted(state["crosswalk"], key=lambda row: row["ordinal"])
    if state["crosswalk"] != accounting["crosswalk"]:
        raise PipelineError("independent checker crosswalk differs from accepted package")
    if any(state[name] != accounting["json_counts"][name] for name in
           ("objects", "arrays", "members", "items", "strings", "numbers", "booleans", "nulls")):
        raise PipelineError("independent checker JSON counts differ")
    return state


def verify(root: Path, *, acceptance_path: Path, rows: list[dict[str, object]], receipt: dict[str, object]) -> list[str]:
    """Re-derive rows from retained JSON and independently check every TEI node."""
    try:
        context = _context(root, acceptance_path)
        state = _oracle_tree(context)
        source = context["document"]
        data = source["Data"]
        if context["work_id"] == "belgic-confession-of-faith":
            if not isinstance(data, list) or len(data) != 37:
                raise PipelineError("checker: Belgic source article count differs")
            native = list(data)
        else:
            if not isinstance(data, dict) or set(data) != {"Content"}:
                raise PipelineError("checker: Chalcedonian Data fields differ")
            native = [data]
        if len(rows) != len(native):
            return ["checker: doctrinal row count differs from retained Data"]
        crosswalk = {(item["json_path"], item["kind"]): item["tei_xml_id"] for item in state["crosswalk"]}
        edition_title = context["edition_title"]
        original_title = source["Metadata"].get("Title")
        provenance = {
            "edition_title": edition_title, "source_title": original_title,
            "source_url": context["source_url"], "source_location": context["source_path"],
        }
        identity = {key: context["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")}
        for sequence, (item, row) in enumerate(zip(native, rows, strict=True), 1):
            is_article = context["work_id"] == "belgic-confession-of-faith"
            if (not isinstance(item, dict) or set(item) != ({"Article", "Title", "Content"} if is_article else {"Content"})):
                raise PipelineError(f"checker: source unit {sequence} has unprojected fields")
            number = item["Article"] if is_article else None
            title = item["Title"] if is_article else None
            content = item["Content"]
            if (not isinstance(content, str) or not content
                    or (is_article and (number != str(sequence) or not isinstance(title, str) or not title))):
                raise PipelineError(f"checker: source unit {sequence} content/number differs")
            path = f"$/Data/{sequence - 1}" if is_article else "$/Data/Content"
            anchor = crosswalk.get((path, "item" if is_article else "member"))
            if not anchor:
                raise PipelineError(f"checker: source unit {sequence} has no TEI anchor")
            expected = {
                **identity,
                "record_id": f"{identity['edition_id']}:unit-{sequence:06d}",
                "sequence": sequence, "category": "doctrinal_documents", "language": "en",
                "representation_revision": context["accepted"]["representation_revision"]["id"],
                "text": content, "document_id": context["work_id"], "document_kind": context["kind"],
                "unit_type": "article" if is_article else "text",
                "number": number, "title": title, "content": content,
                "content_blocks": [content], "content_with_proofs": None,
                "proofs": [], "revision_history": [], "parent_path": ["Data"],
                "locator": {
                    "kind": "unit", "text_part": "body", "part_titles": [],
                    "divisions": [{"order": sequence, "type": "article", "number": number, "titles": [title]}] if is_article else [],
                    "unit": anchor,
                    "unit_path": ["Data", str(sequence - 1)] if is_article else ["Data", "Content"],
                    "source_order": sequence,
                },
                "provenance": provenance,
            }
            if row != expected:
                return [f"checker: row {sequence} differs from source and TEI anchor"]
        _validate_rows(rows)
        expected_receipt = {
            "contract": CONTRACT, "status": "assessment-only",
            "identity": identity,
            "master_sha256": _sha(context["master_bytes"]),
            "source_sha256": _sha(context["source_bytes"]),
            "source_path": context["source_path"],
            "category": "doctrinal_documents", "language": "en",
            "document_kind": context["kind"],
            "row_count": len(native), "rows_sha256": _sha(_canonical(rows)),
            "metadata_disposition": "All retained Metadata fields are bound here as source metadata; only Title and CreedFormat also inform public rows. OriginalLanguage is the historical work label, not the English electronic text language.",
            "retained_metadata": source["Metadata"],
            "metadata_sha256": _sha(_canonical(source["Metadata"])),
            "source_carrier_count": len(state["crosswalk"]),
            "unit_anchors": [row["locator"]["unit"] for row in rows],
            "data_disposition": "All Data fields are projected exactly: Belgic Article/Title/Content in 37 ordered rows or Chalcedonian Content in one row. No proof or revision is inferred from prose.",
            "unprojected_source_content": [],
            "limits": ["bounded accepted electronic witness", "not a release", "rights and historical print lineage separate"],
        }
        if receipt != expected_receipt:
            return ["checker: receipt differs from full source/TEI accounting"]
        return []
    except (PipelineError, ValueError, binascii.Error, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        raise PipelineError("projection assessment destination must be fresh")
    output = project(args.root, acceptance_path=args.acceptance)
    errors = verify(args.root, acceptance_path=args.acceptance, rows=output["rows"], receipt=output["receipt"])
    if errors:
        raise PipelineError(f"independent checker rejected projection: {errors[:3]}")
    args.destination.mkdir(parents=True)
    for name, value in (("rows.json", output["rows"]), ("receipt.json", output["receipt"])):
        (args.destination / name).write_bytes(_canonical(value) + b"\n")
    summary = {
        "contract": CONTRACT,
        "status": "assessment-only",
        "work_id": output["receipt"]["identity"]["work_id"],
        "row_count": len(output["rows"]),
        "independent_verification": "pass",
        "rows_sha256": _sha((args.destination / "rows.json").read_bytes()),
        "receipt_sha256": _sha((args.destination / "receipt.json").read_bytes()),
        "source_carrier_count": output["receipt"]["source_carrier_count"],
        "scope": "Exact accepted Creeds.json electronic witness; no canonical public rows installed",
    }
    (args.destination / "assessment.json").write_bytes(_canonical(summary) + b"\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
