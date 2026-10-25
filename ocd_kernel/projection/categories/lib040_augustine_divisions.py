"""Accepted source-division rows for bounded LIB-040 Augustine electronic works."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.categories.sermons import _accepted_context

PROFILE = "ocd-lib040-augustine-direct-divisions-v1"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
WORKS = {
    "augustine-soliloquies": ("prose", "raw/ccel/npnf1/npnf107.xml", "v", 4),
    "augustine-sermon-on-the-mount": ("commentary", "raw/ccel/npnf1/npnf106.xml", "v", 3),
    "augustine-tractates-on-john": ("commentary", "raw/ccel/npnf1/npnf107.xml", "iii", 125),
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bound_json(root: Path, reference: dict) -> dict:
    raw = io_path(root / reference["path"]).read_bytes()
    if len(raw) != reference["bytes"] or _sha(raw) != reference["sha256"]:
        raise PipelineError("LIB-040 accepted evidence binding differs")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise PipelineError("LIB-040 accepted evidence must be an object")
    return value


def _evidence(root: Path, acceptance_path: Path, category: str):
    context = _accepted_context(root, acceptance_path, expected_category=category)
    identity = context["accepted"]["identity"]
    config = WORKS.get(identity["work_id"])
    if config is None or config[0] != category:
        raise PipelineError("LIB-040 direct-division work/category differs")
    source_path, root_id, count = config[1:]
    if identity != {
        "work_id": identity["work_id"],
        "textual_form_id": f"{identity['work_id']}-ccel-{Path(source_path).stem}-retained-en",
        "edition_id": f"{identity['work_id']}-ccel-{Path(source_path).stem}-electronic",
        "acquisition_id": f"{identity['work_id']}-ccel-{Path(source_path).stem}-acquired",
    }:
        raise PipelineError("LIB-040 direct-division accepted identity differs")
    accepted = context["accepted"]
    reference = accepted["source"]["accounting"]
    accounting = _bound_json(root, reference)
    units = accounting.get("projection_units")
    if (accounting.get("projection_profile") != PROFILE or accounting.get("selected_root") != root_id
            or accounting.get("source", {}).get("source_path") != source_path
            or not isinstance(units, list) or len(units) != count):
        raise PipelineError("LIB-040 direct-division source-accounting profile differs")
    source_bytes = io_path(root / source_path).read_bytes()
    if _sha(source_bytes) != accounting["source_sha256"]:
        raise PipelineError("LIB-040 retained source hash differs")
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    roots = [node for node in source.iter("div1") if node.get("id") == root_id]
    if len(roots) != 1:
        raise PipelineError("LIB-040 retained source root differs")
    root_hash = _sha(etree.tostring(roots[0], method="c14n"))
    if root_hash != accounting["source_root_c14n_sha256"]:
        raise PipelineError("LIB-040 retained source root hash differs")
    source_units = list(roots[0])
    if len(source_units) != count or any(node.tag != "div2" for node in source_units):
        raise PipelineError("LIB-040 retained direct divisions differ")
    if [(node.get("id"), node.get("n")) for node in source_units] != [(unit["source_id"], unit["n"]) for unit in units]:
        raise PipelineError("LIB-040 retained direct division IDs/order differ")
    technical = _bound_json(root, accepted["technical"]["accounting"])
    evidence = technical["evidence"]
    inputs = io_path(root / reference["path"]).parent / "inputs"
    validation_bytes = io_path(inputs / "validation.json").read_bytes()
    if _sha(validation_bytes) != evidence["family_validation_sha256"]:
        raise PipelineError("LIB-040 family oracle report hash differs")
    validation = json.loads(validation_bytes)
    if (validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("candidate_sha256") != accounting["family_package_sha256"]
            or validation.get("attestation", {}).get("oracle_id") != "ocd-lib040-source-to-tei-oracle"
            or validation["attestation"].get("status") != "pass"):
        raise PipelineError("LIB-040 family source-led oracle evidence differs")
    family_bytes = io_path(inputs / "family-content.tei.xml").read_bytes()
    if _sha(family_bytes) != evidence["family_tei_sha256"]:
        raise PipelineError("LIB-040 oracle-checked family TEI hash differs")
    family = etree.fromstring(family_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    work_nodes = [node for node in family.iter(NS + "div") if node.get(XML + "id") == f"lib040-{identity['work_id']}"]
    if len(work_nodes) != 1 or len(work_nodes[0]) != count + 1 or work_nodes[0][0].tag != NS + "head":
        raise PipelineError("LIB-040 oracle-checked family work differs")
    family_units = list(work_nodes[0])[1:]
    family_hashes = [_sha(etree.tostring(unit, method="c14n")) for unit in family_units]
    if [(node.get(XML + "id"), node.get("n"), node.get("type")) for node in family_units] != [(unit["tei_id"], unit["n"], unit["type"]) for unit in units]:
        raise PipelineError("LIB-040 family TEI division identity differs")
    return context, root_hash, family_hashes, units


def _synthetic(context, root_hash: str, family_hashes: list[str], units: list[dict], category: str):
    master_bytes = io_path(context["edition"].path).read_bytes()
    master = etree.fromstring(master_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    body = master.find(NS + "text/" + NS + "body")
    if body is None or len(body) != 1 or (body.text or "").strip():
        raise PipelineError("LIB-040 accepted body differs")
    work = body[0]
    if work.tag != NS + "div" or work.get("type") != "work" or work.get("n") != WORKS[context["identity"]["work_id"]][2] or len(work) != len(units) + 1 or work[0].tag != NS + "head" or (work.text or "").strip():
        raise PipelineError("LIB-040 accepted work envelope differs")
    children = list(work)[1:]
    if any((node.tail or "").strip() for node in work) or [(node.get(XML + "id"), node.get("n"), node.get("type")) for node in children] != [(unit["tei_id"], unit["n"], unit["type"]) for unit in units]:
        raise PipelineError("LIB-040 accepted division IDs/order differ")
    child_hashes = [_sha(etree.tostring(node, method="c14n")) for node in children]
    if child_hashes != family_hashes:
        raise PipelineError("LIB-040 accepted units differ from oracle-checked family TEI")
    copy = deepcopy(master)
    copy_body = copy.find(NS + "text/" + NS + "body")
    copy_body.remove(copy_body[0])
    for node in children:
        unit = deepcopy(node)
        if category == "commentary":
            if unit.get("type") is not None:
                unit.set("subtype", unit.get("type"))
            unit.set("type", "source-div1")
            for block in unit.iter(NS + "ab"):
                if block.get("type") == "source-inline-container":
                    block.set("subtype", "source-inline-container")
                    block.set("type", "source-block")
        copy_body.append(unit)
    binding = {"profile": PROFILE, "category": category, "accepted_master_sha256": _sha(master_bytes), "retained_work_root_c14n_sha256": root_hash, "work_head_c14n_sha256": _sha(etree.tostring(work[0], method="c14n")), "source_ids": [unit["source_id"] for unit in units], "unit_numbers": [unit["n"] for unit in units], "unit_c14n_sha256": child_hashes}
    return etree.tostring(copy, encoding="utf-8", xml_declaration=True), binding


def project(root: Path, *, acceptance_path: Path, category: str):
    context, root_hash, family_hashes, units = _evidence(root, acceptance_path, category)
    synthetic, binding = _synthetic(context, root_hash, family_hashes, units, category)
    with tempfile.TemporaryDirectory(prefix="ocd-lib040-divisions-") as folder:
        path = Path(folder) / "projection.tei.xml"
        path.write_bytes(synthetic)
        result = native_documents.project_document(path, identity=context["identity"], language=context["language"], representation_revision=context["representation_revision"], edition_title=context["edition_title"], _allow_acceptance_metadata=True, category=category)
    if len(result["rows"]) != len(units):
        raise PipelineError("LIB-040 direct-division row count differs")
    result["receipt"].update(scope="accepted LIB-040 Augustine retained direct divisions", authority=context["authority"], source_division_binding=binding)
    return result


def verify(root: Path, *, acceptance_path: Path, category: str, rows, receipt):
    try:
        context, root_hash, family_hashes, units = _evidence(root, acceptance_path, category)
        synthetic, binding = _synthetic(context, root_hash, family_hashes, units, category)
        if not isinstance(receipt, dict):
            return ["LIB-040 direct-division receipt must be an object"]
        errors = []
        if receipt.get("scope") != "accepted LIB-040 Augustine retained direct divisions" or receipt.get("authority") != context["authority"] or receipt.get("source_division_binding") != binding:
            errors.append("LIB-040 direct-division authority or source binding differs")
        native_receipt = dict(receipt)
        for key in ("authority", "source_division_binding"):
            native_receipt.pop(key, None)
        native_receipt["scope"] = native_documents.SCOPE
        with tempfile.TemporaryDirectory(prefix="ocd-lib040-divisions-verify-") as folder:
            path = Path(folder) / "projection.tei.xml"
            path.write_bytes(synthetic)
            errors.extend(native_documents.verify_document(path, rows, native_receipt, identity=context["identity"], language=context["language"], representation_revision=context["representation_revision"], edition_title=context["edition_title"], _allow_acceptance_metadata=True, category=category))
        if len(rows) != len(units):
            errors.append("LIB-040 direct-division row count differs")
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [f"LIB-040 direct-division verification failed: {exc}"]
