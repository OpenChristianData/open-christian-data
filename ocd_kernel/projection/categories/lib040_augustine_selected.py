"""Source-defined public units from three complete LIB-040 Augustine masters.

The accepted TEI remains whole. This profile only chooses public rows; excluded
preliminaries and the First John extracts remain in that accepted master.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.categories.sermons import _accepted_context

PROFILE = "ocd-lib040-augustine-selected-units-v1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
WORKS = {
    "augustine-letters-part-1": ("prose", "npnf101", "vii", "Letter", 169, 2),
    "augustine-sermons-selected-lessons": ("sermons", "npnf106", "vii", "Sermon", 97, 99),
    "augustine-homilies-on-first-john": ("sermons", "npnf107", "iv", "Homily", 10, 19),
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse(raw: bytes):
    return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))


def _bound_json(root: Path, reference: dict) -> dict:
    raw = io_path(root / reference["path"]).read_bytes()
    if len(raw) != reference["bytes"] or _sha(raw) != reference["sha256"]:
        raise PipelineError("LIB-040 selected source accounting differs")
    return json.loads(raw)


def _selection(root: Path, acceptance_path: Path, category: str):
    context = _accepted_context(root, acceptance_path, expected_category=category)
    work_id = context["identity"]["work_id"]
    spec = WORKS.get(work_id)
    if spec is None or spec[0] != category:
        raise PipelineError("LIB-040 selected work/category differs")
    _, stem, root_id, unit_type, count, direct_count = spec
    expected_identity = {
        "work_id": work_id,
        "textual_form_id": f"{work_id}-ccel-{stem}-retained-en",
        "edition_id": f"{work_id}-ccel-{stem}-electronic",
        "acquisition_id": f"{work_id}-ccel-{stem}-acquired",
    }
    if context["accepted"]["identity"] != expected_identity:
        raise PipelineError("LIB-040 selected accepted identity differs")
    accepted = context["accepted"]
    accounting_ref = accepted["source"]["accounting"]
    accounting = _bound_json(root, accounting_ref)
    source_path = f"raw/ccel/npnf1/{stem}.xml"
    if (accounting.get("projection_profile") != PROFILE or accounting.get("selected_root") != root_id
            or accounting.get("source", {}).get("source_path") != source_path
            or len(accounting.get("projection_units", [])) != direct_count):
        raise PipelineError("LIB-040 selected source profile differs")
    source_raw = io_path(root / source_path).read_bytes()
    if _sha(source_raw) != accounting["source_sha256"]:
        raise PipelineError("LIB-040 selected retained source differs")
    source_root = [node for node in _parse(source_raw).iter("div1") if node.get("id") == root_id]
    if len(source_root) != 1 or _sha(etree.tostring(source_root[0], method="c14n")) != accounting["source_root_c14n_sha256"]:
        raise PipelineError("LIB-040 selected retained root differs")
    source_direct = [node for node in source_root[0] if node.tag == "div2"]
    if len(source_direct) != direct_count:
        raise PipelineError("LIB-040 selected retained direct divisions differ")
    if work_id == "augustine-letters-part-1":
        if [node.get("id") for node in source_direct] != ["vii.i", "vii.1"] or source_direct[1].get("type") != "Division":
            raise PipelineError("LIB-040 letter envelope differs")
        source_units = list(source_direct[1])
        if (any(node.tag != "div3" or node.get("type") not in {"Letter", "Letters"} for node in source_units)
                or [(node.get("id"), node.get("type")) for node in source_units if node.get("type") == "Letters"] != [("LVI", "Letters")]):
            raise PipelineError("LIB-040 letter children differ")
    else:
        source_units = [node for node in source_direct if node.get("type") == unit_type]
        expected_other = 2 if unit_type == "Sermon" else 9
        if len(source_direct) - len(source_units) != expected_other:
            raise PipelineError("LIB-040 preliminary/extract disposition differs")
        if unit_type == "Homily" and [node.get("type") for node in source_direct[13:]] != ["Extract"] * 6:
            raise PipelineError("LIB-040 six later extracts differ")
    if len(source_units) != count:
        raise PipelineError("LIB-040 selected retained unit count differs")
    units = [{"source_id": node.get("id"), "n": node.get("n"), "type": node.get("type"),
              "source_c14n_sha256": _sha(etree.tostring(node, method="c14n"))} for node in source_units]
    if len({unit["source_id"] for unit in units}) != count:
        raise PipelineError("LIB-040 selected source IDs differ")
    technical = _bound_json(root, accepted["technical"]["accounting"])
    evidence = technical["evidence"]
    inputs = io_path(root / accounting_ref["path"]).parent / "inputs"
    validation_raw = io_path(inputs / "validation.json").read_bytes()
    validation = json.loads(validation_raw)
    if (_sha(validation_raw) != evidence["family_validation_sha256"] or validation.get("status") != "pass"
            or validation.get("findings") != [] or validation.get("candidate_sha256") != accounting["family_package_sha256"]
            or validation.get("attestation", {}).get("oracle_id") != "ocd-lib040-source-to-tei-oracle"
            or validation["attestation"].get("status") != "pass"):
        raise PipelineError("LIB-040 selected family oracle differs")
    family_raw = io_path(inputs / "family-content.tei.xml").read_bytes()
    if _sha(family_raw) != evidence["family_tei_sha256"]:
        raise PipelineError("LIB-040 selected family TEI differs")
    family_work = [node for node in _parse(family_raw).iter(NS + "div") if node.get(XML + "id") == f"lib040-{work_id}"]
    if len(family_work) != 1 or family_work[0].get("n") != root_id:
        raise PipelineError("LIB-040 selected family work differs")
    master_raw = io_path(context["edition"].path).read_bytes()
    master = _parse(master_raw)
    body = master.find(NS + "text/" + NS + "body")
    if body is None or len(body) != 1 or body[0].get(XML + "id") != f"lib040-{work_id}":
        raise PipelineError("LIB-040 selected accepted envelope differs")
    work = body[0]
    if _sha(etree.tostring(work, method="c14n")) != _sha(etree.tostring(family_work[0], method="c14n")):
        raise PipelineError("LIB-040 selected accepted work differs from oracle family")
    selected = [node for node in work.iter(NS + "div") if node.get(XML + "id") in {f"lib040-{stem}-{unit['source_id']}" for unit in units}]
    if len(selected) != count or [node.get(XML + "id") for node in selected] != [f"lib040-{stem}-{unit['source_id']}" for unit in units]:
        raise PipelineError("LIB-040 selected accepted unit order differs")
    if [node.get("n") for node in selected] != [unit["n"] for unit in units] or [node.get("type") for node in selected] != [unit["type"] for unit in units]:
        raise PipelineError("LIB-040 selected accepted unit metadata differs")
    binding = {"profile": PROFILE, "category": category, "accepted_master_sha256": _sha(master_raw),
               "retained_root_c14n_sha256": accounting["source_root_c14n_sha256"],
               "source_units": units,
               "tei_unit_c14n_sha256": [_sha(etree.tostring(node, method="c14n")) for node in selected],
               "tei_heading_sha256": [_sha(etree.tostring(node.find(NS + "head"), method="c14n")) if node.find(NS + "head") is not None else None for node in selected],
               "non_row_direct_source_ids": [node.get("id") for node in source_direct if node not in source_units],
               "work_head_c14n_sha256": _sha(etree.tostring(work[0], method="c14n"))}
    return context, master, selected, binding


def _synthetic(master, selected, category: str) -> bytes:
    copy = deepcopy(master)
    body = copy.find(NS + "text/" + NS + "body")
    body.remove(body[0])
    for node in selected:
        unit = deepcopy(node)
        unit.set("subtype", unit.get("type"))
        unit.set("type", "source-div1")
        for block in unit.iter(NS + "ab"):
            if block.get("type") == "source-inline-container":
                block.set("subtype", "source-inline-container")
                block.set("type", "source-block")
        body.append(unit)
    return etree.tostring(copy, encoding="utf-8", xml_declaration=True)


def project(root: Path, *, acceptance_path: Path, category: str):
    context, master, selected, binding = _selection(root, acceptance_path, category)
    synthetic = _synthetic(master, selected, category)
    with tempfile.TemporaryDirectory(prefix="ocd-lib040-selected-") as folder:
        path = Path(folder) / "projection.tei.xml"
        path.write_bytes(synthetic)
        result = native_documents.project_document(path, identity=context["identity"], language=context["language"],
            representation_revision=context["representation_revision"], edition_title=context["edition_title"],
            _allow_acceptance_metadata=True, category=category, collection=category == "sermons")
    if len(result["rows"]) != len(selected):
        raise PipelineError("LIB-040 selected row count differs")
    result["receipt"].update(scope="accepted LIB-040 Augustine source-selected units", authority=context["authority"], source_division_binding=binding)
    return result


def verify(root: Path, *, acceptance_path: Path, category: str, rows, receipt):
    try:
        context, master, selected, binding = _selection(root, acceptance_path, category)
        synthetic = _synthetic(master, selected, category)
        if not isinstance(receipt, dict):
            return ["LIB-040 selected receipt must be an object"]
        errors = []
        if (receipt.get("scope") != "accepted LIB-040 Augustine source-selected units"
                or receipt.get("authority") != context["authority"] or receipt.get("source_division_binding") != binding):
            errors.append("LIB-040 selected source binding differs")
        native_receipt = dict(receipt)
        for key in ("authority", "source_division_binding"):
            native_receipt.pop(key, None)
        native_receipt["scope"] = native_documents.SCOPE
        with tempfile.TemporaryDirectory(prefix="ocd-lib040-selected-check-") as folder:
            path = Path(folder) / "projection.tei.xml"
            path.write_bytes(synthetic)
            errors.extend(native_documents.verify_document(path, rows, native_receipt, identity=context["identity"],
                language=context["language"], representation_revision=context["representation_revision"],
                edition_title=context["edition_title"], _allow_acceptance_metadata=True,
                category=category, collection=category == "sermons"))
        if len(rows) != len(selected):
            errors.append("LIB-040 selected row count differs")
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [f"LIB-040 selected verification failed: {exc}"]
