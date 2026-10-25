"""Project the exact accepted fifteen-member Maclaren source-line cohort.

The accepted TEI remains authoritative. A temporary native collection keeps
each source-defined leaf and book-section heading as one public unit while a
private binding records its member, source ancestry, and line span.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents


PROFILE = "ocd-maclaren-pg-fifteen-member-source-lines-v1"
MASTER_SHA256 = "50a0967ed3b0918a32d151bb18541805d381419e17c4435218e0d0e69bf5ff7f"
SOURCE_SHA256 = "b5a6c30402e01c7520912b75870e63dac51af9d2f573f6158d64c3e020916207"
ACCOUNTING_SHA256 = "36734c8e7accc50aa213f8148ccba3cffeb97c9d3ff93f84ccb0aa43cdfe74ff"
IDENTITY = {
    "work_id": "maclaren-expositions",
    "textual_form_id": "maclaren-expositions-pg-retained-en",
    "edition_id": "maclaren-expositions-pg-fifteen-volume-cohort",
    "acquisition_id": "maclaren-expositions-pg-retained-member-set",
}
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
LEAF_TYPES = {"source-title-and-wrapper", "contents", "exposition",
              "gutenberg-license-tail", "part-end-and-separator"}
LINE_TYPES = {"source-uppercase-line", "internal-subsection", "verse-column-label"}
SOURCE_COUNTS = {"seg": 302065, "ab": 616, "milestone": 36845, "lb": 270911}
REGION_COUNTS = {"source-title-and-wrapper": 26, "contents": 26, "exposition": 1386,
                 "gutenberg-license-tail": 15, "part-end-and-separator": 7,
                 "book-section-heading": 43}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest_visible(node: ET.Element) -> str:
    digest = hashlib.sha256()
    for text in node.itertext():
        digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def route(context: dict) -> bool:
    if context["identity"]["work_id"] != IDENTITY["work_id"]:
        return False
    accepted = context["accepted"]
    if (accepted["identity"] != IDENTITY or context["language"] != "en"
            or accepted["promotion"]["master"]["sha256"] != MASTER_SHA256
            or accepted["source"]["source_sha256"] != SOURCE_SHA256
            or accepted["source"]["accounting"]["sha256"] != ACCOUNTING_SHA256
            or _sha(io_path(context["edition"].path).read_bytes()) != MASTER_SHA256):
        raise PipelineError("Maclaren route requires its exact accepted fifteen-member witness")
    return True


def _source_members(context: dict) -> list[dict]:
    accepted = context["accepted"]
    root = Path(context["root"])
    source = accepted["source"]
    if _sha(io_path(root / source["source_path"]).read_bytes()) != SOURCE_SHA256:
        raise PipelineError("Maclaren retained member-set authority differs")
    accounting_ref = source["accounting"]
    accounting_raw = io_path(root / accounting_ref["path"]).read_bytes()
    if _sha(accounting_raw) != ACCOUNTING_SHA256 or len(accounting_raw) != accounting_ref["bytes"]:
        raise PipelineError("Maclaren source accounting differs")
    accounting = json.loads(accounting_raw)
    members = accepted["scope"]["included_members"]
    if (accepted["scope"]["kind"] != "edition" or len(members) != 15
            or accounting["physical_line_count"] != 339526
            or accounting["member_count"] != 15
            or accounting["included_members"] != members
            or accepted["scope"]["excluded_members"]):
        raise PipelineError("Maclaren accepted source-member scope differs")
    for position, member in enumerate(members, 1):
        source_path = member["path"]
        if (member["position"] != position
                or not re.fullmatch(r"raw/gutenberg/sermons/maclaren/pg[0-9]+\.txt", source_path)):
            raise PipelineError("Maclaren source-member order or path differs")
        raw = io_path(root / source_path).read_bytes()
        if len(raw) != member["bytes"] or _sha(raw) != member["sha256"]:
            raise PipelineError(f"Maclaren retained source member differs: {source_path}")
    return members


def _synthetic(context: dict) -> tuple[bytes, dict]:
    if not route(context):
        raise PipelineError("Maclaren route not selected")
    members = _source_members(context)
    raw = io_path(context["edition"].path).read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise PipelineError("Maclaren accepted TEI declaration differs")
    try:
        source = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError("invalid accepted Maclaren TEI") from exc
    original_body = source.find(NS + "text/" + NS + "body")
    if (source.tag != NS + "TEI" or source.attrib != {XML + "id": "maclaren-expositions-full-cohort-v3"}
            or original_body is None or len(original_body) != 15
            or (original_body.text or "").strip()
            or any((child.tail or "").strip() for child in original_body)):
        raise PipelineError("Maclaren accepted member envelope differs")
    original_visible = _digest_visible(original_body)
    synthetic = ET.Element(NS + "TEI")
    header = ET.SubElement(synthetic, NS + "teiHeader")
    desc = ET.SubElement(header, NS + "fileDesc")
    title_stmt = ET.SubElement(desc, NS + "titleStmt")
    ET.SubElement(title_stmt, NS + "title").text = "Expositions of Holy Scripture"
    ET.SubElement(title_stmt, NS + "author").text = "Alexander Maclaren"
    ET.SubElement(ET.SubElement(desc, NS + "publicationStmt"), NS + "p").text = (
        "Virtual source-defined projection of the exact accepted fifteen-member electronic witness."
    )
    ET.SubElement(ET.SubElement(desc, NS + "sourceDesc"), NS + "bibl").text = (
        "Retained Project Gutenberg member set"
    )
    body = ET.SubElement(ET.SubElement(synthetic, NS + "text"), NS + "body")
    source_counts = Counter()
    region_counts = Counter()
    bindings = []
    member_ids = []

    for member_number, (member, source_member) in enumerate(zip(members, original_body), 1):
        ebook = Path(member["path"]).stem
        expected_id = "member-" + ebook
        if (source_member.tag != NS + "div"
                or source_member.attrib != {"type": "source-member", "n": str(member_number), XML + "id": expected_id}
                or not len(source_member)):
            raise PipelineError("Maclaren source-member identity or order differs")
        member_ids.append(expected_id)
        addresses = []
        for node in source_member.iter():
            if not isinstance(node.tag, str) or not node.tag.startswith(NS):
                raise PipelineError("Maclaren unsupported source carrier")
            if (node.tail or "").strip():
                raise PipelineError("Maclaren unexpected source tail")
            tag = node.tag.removeprefix(NS)
            if tag in ("seg", "ab", "milestone"):
                if tag == "seg":
                    allowed = {"type": "source-physical-line", XML + "space": "preserve"}
                    required = {"type", XML + "space", XML + "id", "n"}
                elif tag == "ab":
                    allowed = {XML + "space": "preserve"}
                    required = {"type", XML + "space", XML + "id", "n"}
                    if node.get("type") not in LINE_TYPES:
                        raise PipelineError("Maclaren source block role differs")
                else:
                    allowed = {"unit": "source-empty-line"}
                    required = {"unit", XML + "id", "n"}
                if set(node.attrib) != required or any(node.get(k) != v for k, v in allowed.items()) or len(node):
                    raise PipelineError("Maclaren source line attributes or children differ")
                number = node.get("n")
                if (not number or not number.isdecimal() or int(number) < 1
                        or node.get(XML + "id") != f"{ebook}-line-{int(number):06d}"):
                    raise PipelineError("Maclaren source line locator differs")
                addresses.append(int(number))
                source_counts[tag] += 1
            elif tag == "lb":
                if set(node.attrib) != {"n"} or len(node) or node.text is not None:
                    raise PipelineError("Maclaren line-break shape differs")
                source_counts[tag] += 1
        if addresses != list(range(1, len(addresses) + 1)):
            raise PipelineError(f"Maclaren physical lines out of order: {ebook}")
        if len(addresses) != len(io_path(Path(context["root"]) / member["path"]).read_bytes().splitlines()):
            raise PipelineError(f"Maclaren physical line count differs: {ebook}")

        def append_unit(nodes: list[ET.Element], kind: str, ancestry: list[str],
                        number: str | None, source_id: str | None) -> None:
            index = len(bindings) + 1
            virtual = ET.Element(NS + "div", {"type": "source-div1", "subtype": kind})
            if number is not None:
                virtual.set("n", number)
            virtual.set(XML + "id", f"maclaren-native-unit-{index:04d}")
            for node in nodes:
                virtual.append(deepcopy(node))
            line_numbers = []
            for node in virtual.iter():
                if node.tag == NS + "seg":
                    node.attrib.pop(XML + "space")
                    line_numbers.append(int(node.get("n")))
                elif node.tag == NS + "ab":
                    line_numbers.append(int(node.get("n")))
                    node.set("subtype", node.get("type"))
                    node.set("type", "source-block")
                elif node.tag == NS + "milestone":
                    line_numbers.append(int(node.get("n")))
                    node.set("unit", "source-text-break")
            if not line_numbers:
                raise PipelineError("Maclaren source unit has no physical lines")
            body.append(virtual)
            region_counts[kind] += 1
            bindings.append({"sequence": index, "member": member_number,
                             "member_id": expected_id, "source_path": member["path"],
                             "source_ancestry": ancestry, "source_type": kind,
                             "source_id": source_id, "source_number": number,
                             "first_line": min(line_numbers), "last_line": max(line_numbers),
                             "line_count": len(line_numbers)})

        def walk(division: ET.Element, ancestry: list[str]) -> None:
            kind = division.get("type")
            identifier = division.get(XML + "id")
            path = ancestry + [identifier or f"{kind}:{division.get('n')}"]
            child_divisions = [child for child in division if child.tag == NS + "div"]
            if not child_divisions:
                if kind not in LEAF_TYPES:
                    raise PipelineError("Maclaren source leaf kind differs")
                append_unit(list(division), kind, path, division.get("n"), identifier)
                return
            direct = [child for child in division if child.tag != NS + "div"]
            if direct:
                if kind != "book-section" or list(division)[:len(direct)] != direct or direct[0].tag != NS + "head" or any(child.tag != NS + "milestone" for child in direct[1:]):
                    raise PipelineError("Maclaren nested source heading differs")
                append_unit(direct, "book-section-heading", path,
                            division.get("n"), identifier)
            for child in child_divisions:
                walk(child, path)

        for child in source_member:
            if child.tag != NS + "div":
                raise PipelineError("Maclaren member child differs")
            walk(child, [expected_id])

    if (dict(source_counts) != SOURCE_COUNTS or dict(region_counts) != REGION_COUNTS
            or len(bindings) != 1503 or _digest_visible(body) != original_visible):
        raise PipelineError("Maclaren source-line coverage or visible order differs")
    virtual_bytes = ET.tostring(synthetic, encoding="utf-8", xml_declaration=True)
    binding = {"profile": PROFILE, "accepted_master_sha256": MASTER_SHA256,
               "retained_member_set_sha256": SOURCE_SHA256,
               "source_accounting_sha256": ACCOUNTING_SHA256,
               "synthetic_sha256": _sha(virtual_bytes),
               "member_ids": member_ids, "source_line_counts": dict(source_counts),
               "source_region_counts": dict(region_counts),
               "visible_text_sha256": original_visible,
               "units": bindings}
    return virtual_bytes, binding


def _native(context: dict, virtual_bytes: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="ocd-maclaren-native-") as folder:
        path = Path(folder) / "projection.tei.xml"
        path.write_bytes(virtual_bytes)
        return native_documents.project_document(
            path, identity=context["identity"], language="en",
            representation_revision=context["representation_revision"],
            edition_title=context["edition_title"],
            _allow_acceptance_metadata=True, category="sermons", collection=True)


def project(context: dict) -> dict:
    virtual_bytes, binding = _synthetic(context)
    result = _native(context, virtual_bytes)
    rows = result["rows"]
    if len(rows) != len(binding["units"]):
        raise PipelineError("Maclaren native unit count differs")
    for row, unit in zip(rows, binding["units"]):
        row["locator"]["document"] = unit["member"]
    receipt = result["receipt"]
    receipt.update(scope="accepted Maclaren fifteen-member source lines",
                   master_sha256=MASTER_SHA256, authority=deepcopy(context["authority"]),
                   source_member_binding=binding,
                   output_sha256=_sha(native_documents._json(rows)))
    receipt["warnings"] = [
        "Exact retained fifteen-member Project Gutenberg electronic cohort; source-member identities, physical lines, book-section headings, wrappers, and license tails are conserved. Print-edition lineage remains uncertain."
    ]
    result["master_sha256"] = MASTER_SHA256
    result["authority"] = deepcopy(context["authority"])
    return result


def verify(context: dict, rows: list[dict], receipt: dict) -> list[str]:
    try:
        virtual_bytes, binding = _synthetic(context)
        if not isinstance(receipt, dict):
            return ["Maclaren private receipt must be an object"]
        errors = []
        if (receipt.get("scope") != "accepted Maclaren fifteen-member source lines"
                or receipt.get("master_sha256") != MASTER_SHA256
                or receipt.get("authority") != context["authority"]
                or receipt.get("source_member_binding") != binding
                or receipt.get("output_sha256") != _sha(native_documents._json(rows))):
            errors.append("Maclaren acceptance or source-member binding differs")
        # Only locators change; the source observer reads the text structures.
        native_rows = [{**row, "locator": dict(row["locator"])} for row in rows]
        if len(native_rows) != len(binding["units"]):
            errors.append("Maclaren public source-member row count differs")
        else:
            for row, unit in zip(native_rows, binding["units"]):
                if row.get("locator", {}).get("document") != unit["member"]:
                    errors.append("Maclaren public source-member locator differs")
                    break
                row["locator"].pop("document")
        native_receipt = deepcopy(receipt)
        native_receipt.pop("authority", None)
        native_receipt.pop("source_member_binding", None)
        native_receipt["scope"] = native_documents.SCOPE
        native_receipt["master_sha256"] = binding["synthetic_sha256"]
        native_receipt["output_sha256"] = _sha(native_documents._json(native_rows))
        native_receipt["warnings"] = ["Notes and page markers remain in structure; readable text omits them."]
        with tempfile.TemporaryDirectory(prefix="ocd-maclaren-native-check-") as folder:
            path = Path(folder) / "projection.tei.xml"
            path.write_bytes(virtual_bytes)
            errors.extend(native_documents.verify_document(
                path, native_rows, native_receipt, identity=context["identity"],
                language="en", representation_revision=context["representation_revision"],
                edition_title=context["edition_title"],
                _allow_acceptance_metadata=True, category="sermons", collection=True))
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        return [f"Maclaren verification failed: {exc}"]
