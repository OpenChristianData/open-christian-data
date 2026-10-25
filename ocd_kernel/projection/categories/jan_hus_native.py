"""Project the exact accepted Jan Hus electronic witness at its 31 source divisions."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents


PROFILE = "ocd-jan-hus-wikisource-source-divisions-v1"
MASTER_SHA256 = "c25488f2f2eea1daba67cf4cbbc45aaa1f09491c0d22030e9c9bce897ac431cf"
ACCEPTANCE_SHA256 = "7a336d6919dc50df18608af4783a81a2bc856ed396f27cfc77d78383c9901b50"
SOURCE_SHA256 = "d34272bbd5479e4b04eb04a06c871ed20c38c37b3c2b61073b7b4aa5cfe34570"
ACCOUNTING_SHA256 = "69aadb73fd444e397754deb242dd210b1bd52a9651f6d161318fe27c395beedd"
ACQUISITION_SHA256 = "b14397e4b0925b4cba6a159908f584b88589d19a1aa69be573322651aa11dfa2"
IDENTITY = {
    "work_id": "jan-hus-de-ecclesia-the-church",
    "textual_form_id": "jan-hus-de-ecclesia-the-church-wikisource-retained",
    "edition_id": "jan-hus-de-ecclesia-the-church-wikisource-electronic",
    "acquisition_id": "jan-hus-de-ecclesia-wikisource-complete-render-acquired-20261008",
}
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def route(context: dict) -> bool:
    if context["identity"]["work_id"] != IDENTITY["work_id"]:
        return False
    accepted = context["accepted"]
    authority = context["authority"]
    if (accepted["identity"] != IDENTITY or context["language"] != "en"
            or accepted["promotion"]["master"]["sha256"] != MASTER_SHA256
            or accepted["source"]["source_sha256"] != SOURCE_SHA256
            or accepted["source"]["accounting"]["sha256"] != ACCOUNTING_SHA256
            or authority["acceptance"]["sha256"] != ACCEPTANCE_SHA256
            or authority["master"]["sha256"] != MASTER_SHA256
            or authority["acquisition"]["sha256"] != ACQUISITION_SHA256
            or _sha(io_path(context["edition"].path).read_bytes()) != MASTER_SHA256):
        raise PipelineError("Jan Hus route requires its exact accepted source and edition")
    return True


def _synthetic(context: dict) -> tuple[bytes, dict]:
    if not route(context):
        raise PipelineError("Jan Hus route not selected")
    raw = io_path(context["edition"].path).read_bytes()
    try:
        root = etree.fromstring(raw, etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True,
            remove_comments=False, remove_pis=False, recover=False, huge_tree=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError("invalid accepted Jan Hus TEI") from exc
    tree = root.getroottree()
    body = root.find(NS + "text/" + NS + "body")
    if (tree.docinfo.doctype or root.xpath("//processing-instruction() | //comment()")
            or root.tag != NS + "TEI" or body is None or len(body) != 1
            or body.text is not None or body[0].tail is not None):
        raise PipelineError("Jan Hus accepted work envelope differs")
    wrapper = body[0]
    units = list(wrapper)
    if (wrapper.tag != NS + "div"
            or dict(wrapper.attrib) != {"type": "complete-electronic-transcription"}
            or wrapper.text is not None or len(units) != 31
            or any(unit.tag != NS + "div" or unit.get(XML_ID) is None
                   or unit.tail is not None for unit in units)
            or len({unit.get(XML_ID) for unit in units}) != 31):
        raise PipelineError("Jan Hus source division grain differs")
    original_visible = "".join(wrapper.itertext())
    unit_ids = [unit.get(XML_ID) for unit in units]
    unit_types = [unit.get("type") for unit in units]
    # Only the source's empty outer envelope changes; every source unit and
    # its descendants, attributes, text, notes, and order remain intact.
    for unit in [deepcopy(unit) for unit in units]:
        body.append(unit)
    body.remove(wrapper)
    if "".join(body.itertext()) != original_visible:
        raise PipelineError("Jan Hus visible source text differs")
    synthetic = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    binding = {
        "profile": PROFILE,
        "accepted_master_sha256": MASTER_SHA256,
        "accepted_source_sha256": SOURCE_SHA256,
        "source_accounting_sha256": ACCOUNTING_SHA256,
        "source_unit_ids": unit_ids,
        "source_unit_types": unit_types,
        "source_visible_sha256": _sha(original_visible.encode("utf-8")),
        "synthetic_sha256": _sha(synthetic),
    }
    return synthetic, binding


def _project_native(context: dict, synthetic: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="ocd-jan-hus-") as folder:
        path = Path(folder) / "projection.tei.xml"
        path.write_bytes(synthetic)
        return native_documents.project_document(
            path, identity=context["identity"], language="en",
            representation_revision=context["representation_revision"],
            edition_title=context["edition_title"], category="prose",
            _allow_acceptance_metadata=True,
            acquisition_id=IDENTITY["acquisition_id"])


def project(context: dict) -> dict:
    synthetic, binding = _synthetic(context)
    result = _project_native(context, synthetic)
    if len(result["rows"]) != 31:
        raise PipelineError("Jan Hus source division count differs")
    result["master_sha256"] = MASTER_SHA256
    result["authority"] = deepcopy(context["authority"])
    result["receipt"].update(
        scope="accepted Jan Hus Wikisource source divisions",
        master_sha256=MASTER_SHA256,
        authority=deepcopy(context["authority"]),
        source_division_binding=binding)
    return result


def verify(context: dict, rows: list[dict], receipt: dict) -> list[str]:
    try:
        synthetic, binding = _synthetic(context)
        if not isinstance(receipt, dict):
            return ["Jan Hus private receipt must be an object"]
        errors = []
        if (receipt.get("scope") != "accepted Jan Hus Wikisource source divisions"
                or receipt.get("master_sha256") != MASTER_SHA256
                or receipt.get("authority") != context["authority"]
                or receipt.get("source_division_binding") != binding):
            errors.append("Jan Hus acceptance or source division binding differs")
        native_receipt = dict(receipt)
        native_receipt.pop("authority", None)
        native_receipt.pop("source_division_binding", None)
        native_receipt["scope"] = native_documents.SCOPE
        native_receipt["master_sha256"] = binding["synthetic_sha256"]
        with tempfile.TemporaryDirectory(prefix="ocd-jan-hus-check-") as folder:
            path = Path(folder) / "projection.tei.xml"
            path.write_bytes(synthetic)
            errors.extend(native_documents.verify_document(
                path, rows, native_receipt, identity=context["identity"],
                language="en", representation_revision=context["representation_revision"],
                edition_title=context["edition_title"], category="prose",
                _allow_acceptance_metadata=True,
                acquisition_id=IDENTITY["acquisition_id"]))
        if len(rows) != 31:
            errors.append("Jan Hus source division count differs")
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [f"Jan Hus verification failed: {exc}"]
