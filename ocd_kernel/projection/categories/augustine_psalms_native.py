"""Project the accepted NPNF1-08 Psalms at its source-defined division grain.

The original TEI remains the accepted authority; the temporary document only
changes the row grain and accounts two source HTML anchor comments whose
visible [4899] tail is retained.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents


PROFILE = "ocd-augustine-psalms-npnf108-direct-divisions-v1"
MASTER_SHA256 = "2baf697d2b1a6630355d1ab037e40aaab24ff36fe83ecdc3b90a71a580f58c84"
SOURCE_SHA256 = "87b60e90917e69f03c75955517fc996a0e6d22dc9862365b45c308e70e5bf784"
ACCOUNTING_SHA256 = "0ca3c6de7fc21a108b6fc1d2706b1909e4a50d373fb42452762f0e09bf9c0e02"
IDENTITY = {
    "work_id": "augustine-expositions-on-psalms",
    "textual_form_id": "augustine-expositions-on-psalms-english",
    "edition_id": "augustine-expositions-on-psalms-retained-electronic-witness",
    "acquisition_id": "augustine-expositions-on-psalms-retained-source",
}
SOURCE_PATH = "raw/ccel/npnf1/npnf108.xml"
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def route(metadata: dict) -> bool:
    identity = metadata["acceptance"]["identity"]
    if identity.get("work_id") != IDENTITY["work_id"]:
        return False
    accepted = metadata["acceptance"]
    path = Path(metadata["master_path"])
    if (identity != IDENTITY or metadata["language"] != "en"
            or accepted["source"]["source_sha256"] != SOURCE_SHA256
            or accepted["promotion"]["master"]["sha256"] != MASTER_SHA256
            or accepted["source"]["accounting"]["sha256"] != ACCOUNTING_SHA256
            or _sha(io_path(path).read_bytes()) != MASTER_SHA256):
        raise PipelineError("Augustine Psalms route requires its exact accepted witness")
    return True


def _source_comments(metadata: dict) -> list[dict]:
    root = Path(metadata["root"])
    accepted = metadata["acceptance"]
    source = io_path(root / SOURCE_PATH).read_bytes()
    if _sha(source) != SOURCE_SHA256:
        raise PipelineError("Augustine Psalms retained source differs")
    ref = accepted["source"]["accounting"]
    raw = io_path(root / ref["path"]).read_bytes()
    if _sha(raw) != ACCOUNTING_SHA256 or len(raw) != ref["bytes"]:
        raise PipelineError("Augustine Psalms source accounting differs")
    accounting = json.loads(raw)
    comments = accounting.get("comment_accounting")
    if (not isinstance(comments, list) or len(comments) != 2
            or [item.get("tail_text") for item in comments] != ["[4899]", ""]
            or [item.get("parent_feature_id") for item in comments]
               != ["npnf108-feature-19987"] * 2):
        raise PipelineError("Augustine Psalms source comment ledger differs")
    return comments


def _synthetic(metadata: dict) -> tuple[bytes, dict]:
    if not route(metadata):
        raise PipelineError("Augustine Psalms route not selected")
    comments = _source_comments(metadata)
    raw = io_path(Path(metadata["master_path"])).read_bytes()
    try:
        root = etree.fromstring(raw, etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True,
            remove_comments=False, remove_pis=False, recover=False, huge_tree=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError("invalid accepted Augustine Psalms TEI") from exc
    tree = root.getroottree()
    if tree.docinfo.doctype or root.xpath("//processing-instruction()"):
        raise PipelineError("Augustine Psalms accepted TEI declaration differs")
    body = root.find(NS + "text/" + NS + "body")
    if (root.tag != NS + "TEI" or body is None or len(body) != 1
            or (body.text or "").strip() or any((node.tail or "").strip() for node in body)):
        raise PipelineError("Augustine Psalms work envelope differs")
    work = body[0]
    children = list(work)
    if (work.tag != NS + "div" or work.get(XML_ID) != "npnf108-ii"
            or work.get("type") != "work"
            or work.get("subtype") != IDENTITY["work_id"]
            or set(work.attrib) != {XML_ID, "type", "subtype"}
            or body.text is not None or work.tail is not None
            or len(children) != 154 or children[0].tag != NS + "head"
            or children[0].attrib or children[0].tail is not None
            or any(child.tag != NS + "div" for child in children[1:])
            or any(set(child.attrib) not in ({XML_ID}, {XML_ID, "n"})
                   or (child.tail or "").strip() for child in children[1:])
            or [(node.get(XML_ID), node.get("n")) for node in children[1:4]]
               != [("npnf108-ii.i", None), ("npnf108-ii.ii", None),
                   ("npnf108-ii.iii", None)]
            or children[-1].get(XML_ID) != "npnf108-ii.CL"):
        raise PipelineError("Augustine Psalms direct divisions differ")
    source_comments = root.xpath("//comment()")
    parent = source_comments[0].getparent() if source_comments else None
    if (len(source_comments) != 2 or parent is None
            or any(marker.getparent() is not parent for marker in source_comments)
            or parent.tag != NS + "hi"
            or dict(parent.attrib) != {XML_ID: "npnf108-feature-19987", "rend": "superscript"}
            or len(parent) != 2 or parent.text != "th"
            or [marker.text or "" for marker in source_comments]
               != [item["text"] for item in comments]
            or [marker.tail or "" for marker in source_comments]
               != [item["tail_text"] for item in comments]):
        raise PipelineError("Augustine Psalms source endnote comments differ")
    original_visible = "".join(work.itertext())
    # The comments contain an HTML anchor spelling. The only visible text is
    # its first tail, [4899], copied into the parent before native projection.
    for marker in source_comments:
        tail = marker.tail or ""
        parent.remove(marker)
        parent.text = (parent.text or "") + tail
    heading = deepcopy(children[0])
    divisions = [deepcopy(child) for child in children[1:]]
    body.remove(work)
    body.text = work.text
    first_division_text = divisions[0].text or ""
    divisions[0].text = None
    heading.tail = (heading.tail or "") + first_division_text
    divisions[0].insert(0, heading)
    for division in divisions:
        division.set("type", "source-div1")
        body.append(division)
    retyped = []
    for block in body.iter(NS + "ab"):
        if block.get("type") != "scripture-commentary":
            continue
        retyped.append((block.get(XML_ID), block.get("n"), block.get("corresp")))
        block.set("type", "source-block")
        block.set("subtype", "scripture-commentary")
    if retyped != [
        ("npnf108-ii.II_1-p0.1", "Psalm II", "Bible:Ps.2"),
        ("npnf108-ii.XXXI-p0.1", "Psalm XXXI", "Bible:Ps.31"),
    ]:
        raise PipelineError("Augustine Psalms scripture marker profile differs")
    if "".join(body.itertext()) != original_visible:
        raise PipelineError("Augustine Psalms visible text differs after division mapping")
    synthetic = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    binding = {
        "profile": PROFILE, "accepted_master_sha256": MASTER_SHA256,
        "retained_source_sha256": SOURCE_SHA256,
        "source_accounting_sha256": ACCOUNTING_SHA256,
        "synthetic_sha256": _sha(synthetic),
        "division_ids": [node.get(XML_ID) for node in divisions],
        "source_comments": comments,
        "retyped_scripture_markers": [list(marker) for marker in retyped],
        "visible_text_sha256": _sha(original_visible.encode("utf-8")),
    }
    return synthetic, binding


def _native(metadata: dict, synthetic: bytes) -> dict:
    accepted = metadata["acceptance"]
    identity = {key: IDENTITY[key] for key in ("work_id", "textual_form_id", "edition_id")}
    with tempfile.TemporaryDirectory(prefix="ocd-augustine-psalms-") as folder:
        path = Path(folder) / "projection.tei.xml"
        path.write_bytes(synthetic)
        return native_documents.project_document(
            path, identity=identity, language="en",
            representation_revision=accepted["representation_revision"]["id"],
            edition_title=metadata["edition"].title,
            _allow_acceptance_metadata=True, category="commentary")


def project(metadata: dict) -> dict:
    synthetic, binding = _synthetic(metadata)
    result = _native(metadata, synthetic)
    if len(result["rows"]) != 153 or "[4899]" not in result["rows"][110]["text"]:
        raise PipelineError("Augustine Psalms row grain or visible endnote differs")
    result["master_sha256"] = MASTER_SHA256
    result["authority"] = deepcopy(metadata["authority"])
    result["receipt"].update(scope="accepted Augustine Psalms direct divisions",
                             master_sha256=MASTER_SHA256,
                             authority=deepcopy(metadata["authority"]),
                             source_division_binding=binding)
    return result


def verify(metadata: dict, rows: list[dict], receipt: dict) -> list[str]:
    try:
        synthetic, binding = _synthetic(metadata)
        if not isinstance(receipt, dict):
            return ["Augustine Psalms private receipt must be an object"]
        errors = []
        if (receipt.get("scope") != "accepted Augustine Psalms direct divisions"
                or receipt.get("master_sha256") != MASTER_SHA256
                or receipt.get("authority") != metadata["authority"]
                or receipt.get("source_division_binding") != binding):
            errors.append("Augustine Psalms acceptance or source binding differs")
        native_receipt = dict(receipt)
        for field in ("authority", "source_division_binding"):
            native_receipt.pop(field, None)
        native_receipt["scope"] = native_documents.SCOPE
        native_receipt["master_sha256"] = binding["synthetic_sha256"]
        identity = {key: IDENTITY[key] for key in ("work_id", "textual_form_id", "edition_id")}
        with tempfile.TemporaryDirectory(prefix="ocd-augustine-psalms-check-") as folder:
            path = Path(folder) / "projection.tei.xml"
            path.write_bytes(synthetic)
            errors.extend(native_documents.verify_document(
                path, rows, native_receipt, identity=identity, language="en",
                representation_revision=metadata["acceptance"]["representation_revision"]["id"],
                edition_title=metadata["edition"].title,
                _allow_acceptance_metadata=True, category="commentary"))
        if len(rows) != 153:
            errors.append("Augustine Psalms direct division count differs")
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [f"Augustine Psalms verification failed: {exc}"]
