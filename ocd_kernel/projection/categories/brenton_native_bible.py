"""Exact accepted Brenton verse and source-table projection.

The source's two tables and one unnumbered opening paragraph are public source
units. All other verse wording comes from the independent Bible verse paths.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.envelope import canonical_row_bytes, make_row, row_text_hash

from . import bible


IDENTITY = {
    "work_id": "brenton-septuagint",
    "textual_form_id": "brenton-septuagint-retained-en",
    "edition_id": "brenton-septuagint-electronic",
}
REVISION = "brenton-electronic-whole-work-v1"
MASTER_SHA256 = "c80f8ec3035bac35a668ef97e3031baaa14688310cd284c277cb75d295a172a4"
MEMBER_SET_SHA256 = "6efc889577c804a6c02b1f722459386507cb57c74c39f4be6b19718806ab6169"
MAPPING_VERSION = "ocd-brenton-accepted-verses-and-tables-v1"
SCHEMA_PATH = bible.ROOT / "schemas/v2/categories/brenton-bible-tables.schema.json"
_TABLES = (("FRT", "00-FRTeng-Brenton.usfm", 12), ("XXA", "99-XXAeng-Brenton.usfm", 39))
_OPENING = "source-usfm:eng-Brenton/26-LAMeng-Brenton.usfm#line=8"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _context(root: Path, acceptance_path: Path, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    meta = dict(metadata) if metadata is not None else bible._accepted_metadata(root, acceptance_path)
    if (meta["identity"] != IDENTITY or meta["language"] != "en"
            or meta["acceptance"]["representation_revision"]["id"] != REVISION
            or meta["acceptance"]["source"]["source_sha256"] != MEMBER_SET_SHA256
            or meta["acceptance"]["promotion"]["master"]["sha256"] != MASTER_SHA256):
        raise PipelineError("Brenton accepted identity, revision, master, or source set differs")
    if meta["acceptance_path"] != Path(acceptance_path).resolve():
        raise PipelineError("Brenton acceptance path differs")
    raw = meta["master_path"].read_bytes()
    if _digest(raw) != MASTER_SHA256:
        raise PipelineError("Brenton accepted master bytes differ")
    members = meta["acceptance"]["scope"]["included_members"]
    acquired = meta["acquisition"].get("retained_files")
    if len(members) != 60 or not isinstance(acquired, list) or len(acquired) != 60:
        raise PipelineError("Brenton 60-member scope differs")
    for number, (member, source) in enumerate(zip(members, acquired, strict=True), 1):
        if (member["position"] != number
                or any(member[key] != source[key] for key in ("path", "bytes", "sha256"))):
            raise PipelineError(f"Brenton source member {number} binding differs")
        retained = io_path(Path(root) / member["path"]).read_bytes()
        if len(retained) != member["bytes"] or _digest(retained) != member["sha256"]:
            raise PipelineError(f"Brenton retained source member {number} bytes differ")
    meta["master_bytes"] = raw
    return meta


def _public_versification(native: str) -> str:
    if native != f"source-native:retained-member-set:{MEMBER_SET_SHA256}":
        raise PipelineError("Brenton accepted source-native versification differs")
    return f"source-native:retained-member-set:{IDENTITY['edition_id']}:{REVISION}"


def _row(*, record_id: str, text: str, locator: dict[str, Any], title: str,
         table_cells: list[dict[str, str]] | None = None) -> dict[str, Any]:
    result = make_row(
        record_id=record_id, sequence=1, **IDENTITY, category="bible", language="en",
        text=text, locator=locator, provenance={"edition_title": title},
        representation_revision=REVISION, notes=[],
    )
    result.update(notes=[], references=[], versification=locator["versification"])
    if table_cells is not None:
        result["table_cells"] = table_cells
    return result


def _schema_validator() -> Any:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
    import referencing.jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    common = json.loads(bible.COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resources([(
        common["$id"], Resource.from_contents(
            common, default_specification=referencing.jsonschema.DRAFT202012,
        ),
    )])
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    validator = _schema_validator()
    for number, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"Brenton row {number} schema mismatch: {errors[0].message}")


def _table_shape(table: Any, *, member: str, filename: str, row_count: int,
                 local: Any) -> None:
    if dict(table.attrib) != {"type": "source-table"} or len(table) != row_count or (table.text or "").strip():
        raise PipelineError(f"Brenton {member} source table shape differs")
    for number, source_row in enumerate(table, 1):
        if local(source_row.tag) != "row" or dict(source_row.attrib) != {"role": "data"} or len(source_row) != 3:
            raise PipelineError(f"Brenton {member} table row {number} shape differs")
        if (source_row.text or "").strip() or any((cell.tail or "").strip() for cell in source_row):
            raise PipelineError(f"Brenton {member} table row {number} loose text")
        for column, cell in zip(("label", "1", "2"), source_row, strict=True):
            if local(cell.tag) != "cell" or not re.fullmatch(
                rf"source-usfm:eng-Brenton/{re.escape(filename)}#line=[1-9][0-9]*",
                cell.get("corresp", ""),
            ):
                raise PipelineError(f"Brenton {member} table cell source binding differs")
            attrs = set(cell.attrib)
            if (column == "label" and (cell.get("role") != "label" or attrs != {"role", "corresp"})) or (
                column != "label" and (cell.get("n") != column or attrs != {"n", "corresp"})
            ):
                raise PipelineError(f"Brenton {member} table column {column} differs")
            children = list(cell)
            if not children or local(children[0].tag) != "note" or children[0].get("type") != "source-usfm-raw":
                raise PipelineError(f"Brenton {member} table source-line note differs")
            if any(local(child.tag) != "hi" or child.get("rend") not in {"italic", "small-caps"}
                   for child in children[1:]):
                raise PipelineError(f"Brenton {member} table inline structure differs")


def _producer_units(root: Any, paths: Mapping[Any, str], title: str, versification: str) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    tables = [node for node in root.iter() if bible._local(node.tag) == "table"]
    if len(tables) != 2:
        raise PipelineError("Brenton requires exactly two visible source tables")
    parents = bible._parents(root)
    units: list[tuple[dict, dict]] = []
    inventory: list[dict] = []
    bindings: list[dict] = []
    for table, (member, filename, count) in zip(tables, _TABLES, strict=True):
        holder = parents.get(table)
        if holder is None or bible._local(holder.tag) != "div" or holder.get("type") != "paratext" or holder.get("n") != member:
            raise PipelineError(f"Brenton {member} table ownership differs")
        _table_shape(table, member=member, filename=filename, row_count=count, local=bible._local)
        source_lines: list[list[str]] = []
        for number, source_row in enumerate(table, 1):
            cells = [
                {"column": column, "text": bible._render(cell, paths)}
                for column, cell in zip(("label", "1", "2"), source_row, strict=True)
            ]
            if cells[0]["text"] or not cells[1]["text"] or not cells[2]["text"]:
                raise PipelineError(f"Brenton {member} table row {number} visible cells differ")
            text = f"{cells[1]['text']} | {cells[2]['text']}"
            locator = {"kind": "source-table-row", "source_member": member, "row": number,
                       "source_order": 1, "versification": versification}
            row = _row(record_id=f"{IDENTITY['edition_id']}:table-{member}-{number:03d}",
                       text=text, locator=locator, title=title, table_cells=cells)
            anchor = {"record_id": row["record_id"], "tei_path": paths[source_row],
                      "text_sha256": row_text_hash(text), "source_order": 1, "locator": copy.deepcopy(locator)}
            units.append((row, anchor))
            source_lines.append([cell.get("corresp", "") for cell in source_row])
        bindings.append({"member": member, "tei_path": paths[table], "row_count": count,
                         "source_lines": source_lines})
        for node in table.iter():
            name = bible._local(node.tag)
            inventory.append({"tei_path": paths[node],
                              "disposition": "private-source-marker" if name == "note" else "source-table-public",
                              "attributes": bible._attributes(node),
                              "text_sha256": bible._hash_text(node.text or ""),
                              "tail_sha256": bible._hash_text(node.tail or "")})
    opening = [node for node in root.iter() if bible._local(node.tag) == "ab" and node.get("corresp") == _OPENING]
    if len(opening) != 1 or opening[0].get("type") != "paragraph-break" or opening[0].get("n") != "p":
        raise PipelineError("Brenton Lamentations opening paragraph differs")
    text = bible._render(opening[0], paths)
    if not text:
        raise PipelineError("Brenton Lamentations opening paragraph is empty")
    locator = {"kind": "source-paragraph", "source_member": "LAM", "source_type": "paragraph-break",
               "chapter": 1, "source_order": 1, "versification": versification}
    row = _row(record_id=f"{IDENTITY['edition_id']}:source-paragraph-LAM-001",
               text=text, locator=locator, title=title)
    units.append((row, {"record_id": row["record_id"], "tei_path": paths[opening[0]],
                        "text_sha256": row_text_hash(text), "source_order": 1,
                        "locator": copy.deepcopy(locator)}))
    return units, inventory, bindings


def _checker_units(root: Any, paths: Mapping[Any, str], parents: Mapping[Any, Any],
                   title: str, versification: str) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    from lxml import etree

    local = lambda tag: etree.QName(tag).localname
    tables = root.xpath(".//tei:table", namespaces={"tei": bible.TEI_NS})
    if len(tables) != 2:
        raise PipelineError("Brenton checker requires exactly two source tables")
    units: list[tuple[dict, dict]] = []
    inventory: list[dict] = []
    bindings: list[dict] = []
    for table, (member, filename, count) in zip(tables, _TABLES, strict=True):
        holder = parents.get(table)
        if holder is None or local(holder.tag) != "div" or holder.get("type") != "paratext" or holder.get("n") != member:
            raise PipelineError(f"Brenton checker {member} table ownership differs")
        _table_shape(table, member=member, filename=filename, row_count=count, local=local)
        source_lines: list[list[str]] = []
        for number, source_row in enumerate(table, 1):
            cells = [
                {"column": column, "text": bible._checker_render(cell, paths)}
                for column, cell in zip(("label", "1", "2"), source_row, strict=True)
            ]
            if cells[0]["text"] or not cells[1]["text"] or not cells[2]["text"]:
                raise PipelineError(f"Brenton checker {member} visible cell differs")
            text = " | ".join((cells[1]["text"], cells[2]["text"]))
            locator = {"kind": "source-table-row", "source_member": member, "row": number,
                       "source_order": 1, "versification": versification}
            row = _row(record_id=f"{IDENTITY['edition_id']}:table-{member}-{number:03d}",
                       text=text, locator=locator, title=title, table_cells=cells)
            anchor = {"record_id": row["record_id"], "tei_path": paths[source_row],
                      "text_sha256": row_text_hash(text), "source_order": 1, "locator": copy.deepcopy(locator)}
            units.append((row, anchor))
            source_lines.append([cell.get("corresp", "") for cell in source_row])
        bindings.append({"member": member, "tei_path": paths[table], "row_count": count,
                         "source_lines": source_lines})
        for node in table.iter():
            name = local(node.tag)
            attributes = {"xml:" + etree.QName(key).localname if etree.QName(key).namespace == bible.XML_NS
                          else key for key in sorted(node.attrib)}
            inventory.append({"tei_path": paths[node],
                              "disposition": "private-source-marker" if name == "note" else "source-table-public",
                              "attributes": {key: node.get(key[4:] if key.startswith("xml:") else key) for key in attributes},
                              "text_sha256": bible._hash_text(node.text or ""),
                              "tail_sha256": bible._hash_text(node.tail or "")})
    opening = root.xpath(".//tei:ab[@corresp=$pointer]", namespaces={"tei": bible.TEI_NS}, pointer=_OPENING)
    if len(opening) != 1 or opening[0].get("type") != "paragraph-break" or opening[0].get("n") != "p":
        raise PipelineError("Brenton checker Lamentations opening differs")
    text = bible._checker_render(opening[0], paths)
    if not text:
        raise PipelineError("Brenton checker Lamentations opening is empty")
    locator = {"kind": "source-paragraph", "source_member": "LAM", "source_type": "paragraph-break",
               "chapter": 1, "source_order": 1, "versification": versification}
    row = _row(record_id=f"{IDENTITY['edition_id']}:source-paragraph-LAM-001",
               text=text, locator=locator, title=title)
    units.append((row, {"record_id": row["record_id"], "tei_path": paths[opening[0]],
                        "text_sha256": row_text_hash(text), "source_order": 1,
                        "locator": copy.deepcopy(locator)}))
    return units, inventory, bindings


def _merge(base_rows: list[dict], base_anchors: list[dict], base_inventory: list[dict],
           base_exclusions: list[dict], base_warnings: list[dict], units: list[tuple[dict, dict]],
           table_inventory: list[dict], bindings: list[dict], original_paths: Mapping[Any, str],
           original_root: Any) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], dict]:
    if len(base_rows) != 29_005 or len(base_anchors) != len(base_rows) or len(units) != 52:
        raise PipelineError("Brenton verse, table, or opening paragraph counts differ")
    order = {original_paths[node]: number for number, node in enumerate(original_root.iter(), 1)}
    paired = list(zip(base_rows, base_anchors, strict=True)) + units
    if len({anchor["tei_path"] for _, anchor in paired}) != len(paired):
        raise PipelineError("Brenton source unit paths overlap")
    paired.sort(key=lambda pair: order[pair[1]["tei_path"]])
    rows: list[dict] = []
    anchors: list[dict] = []
    for number, (row, anchor) in enumerate(paired, 1):
        row["sequence"] = number
        row["locator"]["source_order"] = number
        anchor["source_order"] = number
        anchor["locator"] = copy.deepcopy(row["locator"])
        rows.append(row)
        anchors.append(anchor)
    inventory = base_inventory + table_inventory
    inventory.sort(key=lambda item: order[item["tei_path"]])
    if len(inventory) != len(order) or {item["tei_path"] for item in inventory} != set(order):
        raise PipelineError("Brenton complete TEI element inventory differs")
    opening_path = next(anchor["tei_path"] for row, anchor in units
                        if row["locator"]["kind"] == "source-paragraph")
    for item in inventory:
        if item["tei_path"] == opening_path:
            item["disposition"] = "row-content"
    warnings = [warning for warning in base_warnings if not (
        warning["tei_path"] == opening_path and warning["reason"] == "source-structural-text-not-projected-to-verse"
    )]
    warnings.append({"tei_path": opening_path, "reason": "unnumbered-source-paragraph-projected-separately"})
    warnings.extend({"tei_path": binding["tei_path"], "reason": "source-table-projected-as-ordered-rows"}
                    for binding in bindings)
    source_binding = {"profile": MAPPING_VERSION, "tables": bindings,
                      "opening_paragraph_path": opening_path,
                      "source_units": {"verses": 29_005, "table_rows": 51, "opening_paragraphs": 1}}
    return rows, anchors, inventory, base_exclusions, warnings, source_binding


def project_accepted(root: Path, *, acceptance_path: Path,
                     metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    meta = _context(root, acceptance_path, metadata)
    original, raw = bible._read(meta["master_path"])
    paths = bible._paths(original)
    header = bible._header(original)
    bible._validate_accepted_header(header, meta)
    bible._validate_accepted_member_set(original, header, meta)
    native = bible._accepted_versification(header, meta)
    public = _public_versification(native)
    units, table_inventory, bindings = _producer_units(original, paths, meta["edition"].title, public)
    stripped = copy.deepcopy(original)
    parents = bible._parents(stripped)
    for table in [node for node in stripped.iter() if bible._local(node.tag) == "table"]:
        parents[table].remove(table)
    bible._validate_elements(stripped, bible._paths(stripped))
    result = bible._projection(
        meta["master_path"], identity=IDENTITY, language="en", representation_revision=REVISION,
        edition_title=meta["edition"].title, versification=native, scope_id=None,
        source_url=header["source_url"], source_sha256=header.get("source_sha256"),
        retained_sha256=header["retained_sha256"], accessed_at=None,
        _preloaded=(stripped, raw), _already_validated=True, _source_strict=True,
    )
    (result["rows"], result["anchors"], result["inventory"], result["exclusions"],
     result["warnings"], binding) = _merge(
        result["rows"], result["anchors"], result["inventory"], result["exclusions"],
        result["warnings"], units, table_inventory, bindings, paths, original,
    )
    result["mapping_version"] = MAPPING_VERSION
    result["source_binding"]["brenton_source_units"] = binding
    result["authority"] = copy.deepcopy(meta["authority"])
    _validate_rows(result["rows"])
    receipt = bible.build_bible_receipt(result, identity=IDENTITY, authority=meta["authority"])
    receipt["schema_sha256"] = _digest(SCHEMA_PATH.read_bytes())
    result["receipt"] = receipt
    return result


def verify_accepted(root: Path, *, acceptance_path: Path,
                    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
                    receipt: Mapping[str, Any] | None = None,
                    metadata: Mapping[str, Any] | None = None) -> list[str]:
    from lxml import etree

    try:
        meta = _context(root, acceptance_path, metadata)
        if isinstance(rows, Mapping):
            if receipt is None:
                receipt = rows.get("receipt")
            rows = rows["rows"]
        original, raw, paths, parents = bible._checker_parse(meta["master_path"])
        if _digest(raw) != MASTER_SHA256:
            raise PipelineError("Brenton checker accepted master differs")
        header = bible._checker_header(original, paths)
        bible._validate_accepted_header(header, meta)
        bible._checker_validate_accepted_member_set(original, header, meta)
        native = bible._checker_accepted_versification(header, meta)
        public = _public_versification(native)
        units, table_inventory, bindings = _checker_units(original, paths, parents,
                                                           meta["edition"].title, public)
        stripped = copy.deepcopy(original)
        for table in stripped.xpath(".//tei:table", namespaces={"tei": bible.TEI_NS}):
            table.getparent().remove(table)
        stripped_paths: dict[Any, str] = {stripped: "/TEI[1]"}
        stripped_parents: dict[Any, Any] = {}
        for parent in stripped.iter():
            counts: dict[str, int] = {}
            for child in parent:
                stripped_parents[child] = parent
                kind = etree.QName(child).localname
                counts[kind] = counts.get(kind, 0) + 1
                stripped_paths[child] = f"{stripped_paths[parent]}/{kind}[{counts[kind]}]"
        expected, base_receipt = bible._checker_expected(
            meta["master_path"], identity=IDENTITY, language="en",
            representation_revision=REVISION, edition_title=meta["edition"].title,
            versification=native, scope_id=None, source_url=header["source_url"],
            source_sha256=header.get("source_sha256"), retained_sha256=header["retained_sha256"],
            accessed_at=None, authority=meta["authority"],
            _preloaded=(stripped, raw, stripped_paths, stripped_parents), _source_strict=True,
        )
        (expected, anchors, inventory, exclusions, warnings, binding) = _merge(
            expected, base_receipt["anchors"], base_receipt["inventory"],
            base_receipt["exclusions"], base_receipt["warnings"], units,
            table_inventory, bindings, paths, original,
        )
        base_receipt.update(
            mapping_version=MAPPING_VERSION, output_sha256=_digest(canonical_row_bytes(expected)),
            row_count=len(expected), anchors=anchors, inventory=inventory,
            exclusions=exclusions, warnings=warnings,
        )
        base_receipt["source_binding"]["brenton_source_units"] = binding
        base_receipt["schema_sha256"] = _digest(SCHEMA_PATH.read_bytes())
        if list(rows) != expected:
            raise PipelineError("Brenton source-derived public rows differ")
        _validate_rows(rows)
        if receipt != base_receipt:
            raise PipelineError("Brenton source-derived receipt differs")
        return []
    except (PipelineError, OSError, KeyError, TypeError, ValueError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
