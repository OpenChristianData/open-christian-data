"""Exact accepted-prose route for seven single-work LIB-050 Owen witnesses.

The faithful master retains head, readable transcription, and evidence in that
order. Only a checked readable view is passed to the stock native row mapper.
"""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from urllib.parse import quote

from lxml import etree

from build.tei import john_owen_lib050_oracle as oracle
from build.tools.prepare_owen_communion_candidate import _scope as communion_scope
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.categories.sermons import _accepted_context
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

PROFILE = "ocd-lib050-owen-three-child-v1"
EVANGELICAL_WORK = "john-owen-evangelical-churches"
EVANGELICAL_PROFILE = "ocd-lib050-owen-evangelical-whole-work-v1"
COMMUNION_WORK = "john-owen-communion"
COMMUNION_PROFILE = "ocd-lib050-owen-communion-div1-i-v1"
WORKS = frozenset({
    "john-owen-apostasy", "john-owen-church-love", "john-owen-death-of-death",
    "john-owen-display-arminianism", "john-owen-divine-justice",
    "john-owen-eshcol", "john-owen-faith-elect",
})
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
SCOPE = "accepted LIB-050 Owen three-child retained witness"
EVANGELICAL_SCOPE = "accepted complete Evangelical Churches retained witness"
COMMUNION_SCOPE = "accepted Communion div1#i through printed page 274"
PUBLIC_ANNOTATION_PREFIX = "source-annotation:"
PUBLIC_ANNOTATION_PROFILE = "ocd-private-source-annotation-alias-v1"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse(raw: bytes) -> etree._Element:
    return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False,
                                                 no_network=True, remove_comments=False,
                                                 remove_pis=False, huge_tree=True))


def _bound(root: Path, reference: dict) -> bytes:
    raw = io_path(root / reference["path"]).read_bytes()
    if len(raw) != reference["bytes"] or _sha(raw) != reference["sha256"]:
        raise PipelineError("LIB-050 bound evidence differs")
    return raw


def _checked(root: Path, acceptance_path: Path):
    context = _accepted_context(root, acceptance_path, expected_category="prose")
    identity = context["accepted"]["identity"]
    work_id = identity["work_id"]
    if work_id in WORKS:
        projection_profile = PROFILE
    elif work_id == EVANGELICAL_WORK:
        projection_profile = EVANGELICAL_PROFILE
    elif work_id == COMMUNION_WORK:
        projection_profile = COMMUNION_PROFILE
    else:
        raise PipelineError("LIB-050 projection work is outside declared scopes")
    accounting = json.loads(_bound(root, context["accepted"]["source"]["accounting"]))
    source = accounting.get("source", {})
    if (accounting.get("projection_profile") != projection_profile
            or source.get("source_path") != accounting.get("source_path")
            or source.get("source_sha256") != accounting.get("source_sha256")
            or source.get("source_bytes") != accounting.get("source_bytes")
            or accounting.get("identity") != identity):
        raise PipelineError("LIB-050 source profile differs")
    original = _bound(root, accounting["original_candidate"])
    source_raw = io_path(root / source["source_path"]).read_bytes()
    if len(source_raw) != source["source_bytes"] or _sha(source_raw) != source["source_sha256"]:
        raise PipelineError("LIB-050 retained source differs")
    source_tree = etree.parse(io.BytesIO(source_raw), etree.XMLParser(resolve_entities=False,
        load_dtd=False, no_network=True, remove_comments=False, remove_pis=False, huge_tree=True))
    if work_id == COMMUNION_WORK:
        _, scoped_divisions = communion_scope(source_raw)
        if (accounting.get("excluded_source_divisions") != scoped_divisions[1:]
                or "div1#i" not in accounting.get("declared_scope", "")):
            raise PipelineError("Communion scoped source accounting differs")
    if work_id == EVANGELICAL_WORK:
        source_body = source_tree.getroot().find("ThML.body")
        if source_body is None:
            raise PipelineError("Evangelical Churches retained body is absent")
        source_divisions = list(source_body)
        if ([node.get("id") for node in source_divisions] != ["i", "ii", "iii", "iv"]
                or [node.get("type") for node in source_divisions] != ["Work", "Work", "Work", None]
                or "Inquiry" not in (source_divisions[0].get("title") or "")
                or "Stillingfleet" not in (source_divisions[1].get("title") or "")
                or "True Nature" not in (source_divisions[2].get("title") or "")
                or source_divisions[3].get("title") != "Indexes"):
            raise PipelineError("Evangelical Churches source divisions differ")
    original_tree = _parse(original)
    expected_header = oracle._expected_header(oracle._metadata(source_tree))
    if etree.tostring(original_tree[0], method="c14n", with_comments=True) != etree.tostring(expected_header, method="c14n", with_comments=True):
        raise PipelineError("LIB-050 original header differs from retained source")
    accepted = context["accepted"]
    ordered_identity = {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id")}
    expected = bind_reviewed_header(original, expected_sha256=_sha(original), identity=ordered_identity,
        source=source, source_url=accounting["source_url"],
        declared_scope=accounting["declared_scope"], revision=accepted["representation_revision"])
    master_raw = io_path(context["edition"].path).read_bytes()
    if expected != master_raw:
        raise PipelineError("LIB-050 accepted header or master differs from reviewed source binding")
    master = _parse(master_raw)
    if (master.tag != NS + "TEI" or master.get(XML + "id") != work_id
            or [node.tag for node in master] != [NS + "teiHeader", NS + "text"]):
        raise PipelineError("LIB-050 accepted TEI envelope differs")
    body = master.find(NS + "text/" + NS + "body")
    if body is None or len(body) != 1 or body[0].tag != NS + "div" or dict(body[0].attrib) != {"type": "retained-source-member"} or len(body[0]) != 3:
        raise PipelineError("LIB-050 retained member three-child envelope differs")
    division = body[0]
    head, readable, evidence = division
    if work_id == EVANGELICAL_WORK:
        actual_divisions = [node.get(XML + "id") for node in readable]
        expected_divisions = [f"{EVANGELICAL_WORK}--{source_id}" for source_id in ("i", "ii", "iii", "iv")]
        if actual_divisions != expected_divisions or any(node.get("type") != "source-division" for node in readable):
            raise PipelineError("Evangelical Churches readable divisions differ")
    if work_id == COMMUNION_WORK:
        if ([node.get(XML + "id") for node in readable] != [f"{COMMUNION_WORK}--i"]
                or any(node.get("type") != "source-division" for node in readable)):
            raise PipelineError("Communion readable boundary includes sibling material")
    metadata = oracle._metadata(source_tree)
    if (head.tag != NS + "head" or dict(head.attrib) or len(head) or head.text != metadata["title"]
            or readable.tag != NS + "div" or readable.get("type") != "readable-transcription"
            or evidence.tag != NS + "div" or dict(evidence.attrib) != {"type": "retained-evidence"}
            or len(evidence) != 2 or any((node.tail or "").strip() for node in (head, readable, evidence))):
        raise PipelineError("LIB-050 head/readable/evidence order differs")
    raw_node, ledger = evidence
    if (raw_node.tag != NS + "ab" or dict(raw_node.attrib) != {"type": "exact-retained-source-bytes", "subtype": "base64", "n": _sha(source_raw)}
            or ledger.tag != NS + "div" or dict(ledger.attrib) != {"type": "complete-xml-node-transcription"}):
        raise PipelineError("LIB-050 retained evidence envelope differs")
    try:
        decoded = base64.b64decode((raw_node.text or "").encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise PipelineError("LIB-050 retained source base64 differs") from exc
    if decoded != source_raw:
        raise PipelineError("LIB-050 retained source bytes differ")
    records = oracle._records(source_tree, Path(source["source_path"]).stem)
    if len(ledger) != len(records):
        raise PipelineError("LIB-050 source node ledger count differs")
    for index, (node, record) in enumerate(zip(ledger, records, strict=True), 1):
        if (node.tag != NS + "ab" or dict(node.attrib) != {XML + "id": record["feature_id"], "type": "source-xml-node", "subtype": record["kind"], "n": str(index)}
                or len(node) or (node.tail or "").strip() or json.loads(node.text or "null") != record):
            raise PipelineError(f"LIB-050 source node ledger differs at {index}")
    if work_id == COMMUNION_WORK:
        scoped_tree = oracle._parse_source(source_raw)
        scoped_body = scoped_tree.getroot().find("ThML.body")
        for sibling in list(scoped_body)[1:]:
            scoped_body.remove(sibling)
        oracle._verify_readable_transcription(
            scoped_tree, oracle._records(scoped_tree, Path(source["source_path"]).stem),
            division, work_id,
        )
    else:
        oracle._verify_readable_transcription(source_tree, records, division, work_id)
    binding = {"profile": projection_profile, "work_id": work_id, "source_path": source["source_path"],
               "source_sha256": _sha(source_raw), "master_sha256": _sha(master_raw),
               "original_candidate_sha256": _sha(original), "source_node_count": len(records),
               "processing_instruction_count": sum(record["kind"] == "processing-instruction" for record in records),
               "head_c14n_sha256": _sha(etree.tostring(head, method="c14n")),
               "readable_c14n_sha256": _sha(etree.tostring(readable, method="c14n")),
               "evidence_c14n_sha256": _sha(etree.tostring(evidence, method="c14n"))}
    return context, master, division, binding


def _synthetic(master: etree._Element, division: etree._Element, *, split_evangelical: bool = False) -> bytes:
    doc = deepcopy(master)
    body = doc.find(NS + "text/" + NS + "body")
    body.remove(body[0])
    unit = etree.Element(NS + "div", {"type": "source-div1"})
    head, readable, _evidence = division
    unit.append(deepcopy(head))
    for child in readable:
        unit.append(deepcopy(child))
    for node in unit.iter():
        if node.tag == NS + "ab" and node.get("type") in {"scripture-context", "source-attribute-text"}:
            source_type = node.get("type")
            node.set("type", "source-block")
            node.set("subtype", source_type)
        elif node.tag == NS + "milestone" and node.get("unit") == "source-comment":
            node.set("unit", "source-insert-index")
            node.set("type", "source-comment")
        elif node.tag == NS + "date" and (node.get("ana") is not None or node.get("n") is not None):
            node.tag = NS + "seg"
            node.set("type", "source-date")
            if node.get("when") is not None:
                when = node.attrib.pop("when")
                node.set("ana", ((node.get("ana") or "") + " urn:ocd:tei-date-when:" + quote(when, safe="")).strip())
        elif node.tag == NS + "cell" and node.get("rows") is not None:
            rows = node.attrib.pop("rows")
            node.set("ana", ((node.get("ana") or "") + " urn:ocd:tei-cell-rows:" + quote(rows, safe="")).strip())
        elif node.tag == NS + "graphic" and node.get("width") is not None:
            width = node.attrib.pop("width")
            node.set("ana", ((node.get("ana") or "") + " urn:ocd:tei-graphic-width:" + quote(width, safe="")).strip())
    if split_evangelical:
        parts = list(unit)
        expected = [f"{EVANGELICAL_WORK}--{source_id}" for source_id in ("i", "ii", "iii", "iv")]
        if len(parts) != 5 or parts[0].tag != NS + "head" or [part.get(XML + "id") for part in parts[1:]] != expected:
            raise PipelineError("Evangelical Churches projected division boundary differs")
        for part in parts[1:]:
            row_unit = etree.Element(NS + "div", {"type": "source-div1"})
            row_unit.append(part)
            body.append(row_unit)
    else:
        body.append(unit)
    return etree.tostring(doc, encoding="utf-8", xml_declaration=True)


def _source_annotation_id(node: dict) -> str | None:
    attributes = node.get("attributes")
    if not isinstance(attributes, dict):
        return None
    annotations = attributes.get("source_annotations")
    if not isinstance(annotations, str):
        return None
    prefix = "urn:ocd:thml-attribute:id:"
    for token in annotations.split():
        if token.startswith(prefix):
            from urllib.parse import unquote
            return unquote(token[len(prefix):])
    return None


def _alias_private_source_annotations(rows):
    """Replace private source URNs with deterministic, work-local labels."""
    output = deepcopy(rows)
    count = 0

    def visit(value):
        nonlocal count
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "source_annotations" and isinstance(child, str):
                    aliases = []
                    for token in child.split():
                        if "urn:ocd:" in token.lower():
                            count += 1
                            token = f"{PUBLIC_ANNOTATION_PREFIX}{count:05d}"
                        aliases.append(token)
                    value[key] = " ".join(aliases)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(output)
    return output, count


def _paragraph_ids(value: object) -> list[str | None]:
    if isinstance(value, dict):
        result = [_source_annotation_id(value)] if value.get("kind") == "paragraph" else []
        for child in value.values():
            result.extend(_paragraph_ids(child))
        return result
    if isinstance(value, list):
        return [item for child in value for item in _paragraph_ids(child)]
    return []


def _verify_evangelical_row_map(source_raw: bytes, rows: object) -> list[str]:
    """Check public division and paragraph boundaries directly against retained XML."""
    source = _parse(source_raw)
    body = source.find("ThML.body")
    if body is None or not isinstance(rows, list) or len(rows) != 4:
        return ["Evangelical Churches source or four-row scope differs"]
    divisions = list(body)
    if [node.get("id") for node in divisions] != ["i", "ii", "iii", "iv"]:
        return ["Evangelical Churches source division order differs"]
    for position, (source_division, row) in enumerate(zip(divisions, rows, strict=True), 1):
        if not isinstance(row, dict) or row.get("sequence") != position or row.get("category") != "prose" or row.get("language") != "en" or row.get("work_id") != EVANGELICAL_WORK:
            return [f"Evangelical Churches public row identity differs at {position}"]
        structure = row.get("structure")
        if not isinstance(structure, list) or len(structure) != 1 or not isinstance(structure[0], dict):
            return [f"Evangelical Churches public row structure differs at {position}"]
        children = structure[0].get("content")
        if (not isinstance(children, list) or not children or not isinstance(children[0], dict)
                or _source_annotation_id(children[0]) != source_division.get("id")
                or any(not isinstance(child, dict) or child.get("kind") != "text" or str(child.get("text", "")).strip() for child in children[1:])):
            return [f"Evangelical Churches public division differs at {position}"]
        expected = [node.get("id") for node in source_division.iter() if node.tag in {"p", "argument"}]
        if _paragraph_ids(structure) != expected:
            return [f"Evangelical Churches public paragraph order differs at {position}"]
    return []


def project(root: Path, *, acceptance_path: Path) -> dict:
    context, master, division, binding = _checked(root, acceptance_path)
    split_evangelical = binding["work_id"] == EVANGELICAL_WORK
    synthetic = _synthetic(master, division, split_evangelical=split_evangelical)
    with tempfile.TemporaryDirectory(prefix="ocd-lib050-owen-") as folder:
        path = Path(folder) / "readable.tei.xml"
        path.write_bytes(synthetic)
        result = native_documents.project_document(path, identity=context["identity"],
            language=context["language"], representation_revision=context["representation_revision"],
            edition_title=context["edition_title"], _allow_acceptance_metadata=True, category="prose")
    if len(result["rows"]) != (4 if split_evangelical else 1):
        raise PipelineError("LIB-050 source-defined prose row count differs")
    if split_evangelical:
        source_raw = io_path(root / binding["source_path"]).read_bytes()
        problems = _verify_evangelical_row_map(source_raw, result["rows"])
        if problems:
            raise PipelineError(problems[0])
    result["rows"], alias_count = _alias_private_source_annotations(result["rows"])
    scope = (EVANGELICAL_SCOPE if binding["work_id"] == EVANGELICAL_WORK else
             COMMUNION_SCOPE if binding["work_id"] == COMMUNION_WORK else SCOPE)
    result["receipt"].update(scope=scope, authority=context["authority"], source_binding=binding,
                             accepted_master_sha256=binding["master_sha256"], synthetic_sha256=_sha(synthetic),
                             public_annotation_aliases={"profile": PUBLIC_ANNOTATION_PROFILE, "count": alias_count})
    return result


def verify(root: Path, *, acceptance_path: Path, rows, receipt) -> list[str]:
    try:
        context, master, division, binding = _checked(root, acceptance_path)
        scope = (EVANGELICAL_SCOPE if binding["work_id"] == EVANGELICAL_WORK else
                 COMMUNION_SCOPE if binding["work_id"] == COMMUNION_WORK else SCOPE)
        if not isinstance(receipt, dict) or receipt.get("scope") != scope or receipt.get("authority") != context["authority"] or receipt.get("source_binding") != binding:
            return ["LIB-050 accepted authority or source binding differs"]
        if (not isinstance(receipt.get("public_annotation_aliases"), dict)
                or receipt["public_annotation_aliases"].get("profile") != PUBLIC_ANNOTATION_PROFILE):
            return ["LIB-050 public annotation alias binding differs"]
        split_evangelical = binding["work_id"] == EVANGELICAL_WORK
        synthetic = _synthetic(master, division, split_evangelical=split_evangelical)
        if receipt.get("synthetic_sha256") != _sha(synthetic) or receipt.get("accepted_master_sha256") != binding["master_sha256"]:
            return ["LIB-050 readable projection source differs"]
        native_receipt = dict(receipt)
        for key in ("authority", "source_binding", "accepted_master_sha256", "synthetic_sha256", "public_annotation_aliases"):
            native_receipt.pop(key)
        native_receipt["scope"] = native_documents.SCOPE
        with tempfile.TemporaryDirectory(prefix="ocd-lib050-owen-check-") as folder:
            path = Path(folder) / "readable.tei.xml"
            path.write_bytes(synthetic)
            projected = native_documents.project_document(path, identity=context["identity"],
                language=context["language"], representation_revision=context["representation_revision"],
                edition_title=context["edition_title"], _allow_acceptance_metadata=True, category="prose")
            expected_rows, alias_count = _alias_private_source_annotations(projected["rows"])
            if (rows != expected_rows
                    or receipt["public_annotation_aliases"] != {
                        "profile": PUBLIC_ANNOTATION_PROFILE, "count": alias_count
                    }):
                return ["LIB-050 public source annotation aliases differ"]
            errors = native_documents.verify_document(path, projected["rows"], native_receipt, identity=context["identity"],
                language=context["language"], representation_revision=context["representation_revision"],
                edition_title=context["edition_title"], _allow_acceptance_metadata=True, category="prose")
            if split_evangelical:
                source_raw = io_path(root / binding["source_path"]).read_bytes()
                if _sha(source_raw) != binding["source_sha256"]:
                    return ["Evangelical Churches retained source changed"]
                errors.extend(_verify_evangelical_row_map(source_raw, projected["rows"]))
            return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
