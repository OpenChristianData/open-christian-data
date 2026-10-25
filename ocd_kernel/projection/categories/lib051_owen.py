"""Source-bound native prose projection for readable single-work LIB-051 Owen TEI."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from urllib.parse import quote

from lxml import etree

from build.tei import john_owen_lib050_oracle as oracle
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.categories.lib050_owen import (
    NS, XML, PUBLIC_ANNOTATION_PROFILE, _alias_private_source_annotations,
    _bound, _parse, _sha, _synthetic,
)
from ocd_kernel.projection.categories.sermons import _accepted_context
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header


PROFILE = "ocd-lib051-owen-readable-v1"
FINAL_PROFILE = "ocd-lib051-owen-final-three-readable-v1"
WORKS = frozenset({
    "john-owen-grotius", "john-owen-indwelling-sin", "john-owen-liturgies",
    "john-owen-pastors-people", "john-owen-perseverance", "john-owen-psalm130",
})
FINAL_WORKS = frozenset({
    "john-owen-glory", "john-owen-justification", "john-owen-pneumatologia",
})
SCOPE = "accepted LIB-051 Owen readable retained witness"


def _checked(root: Path, acceptance_path: Path):
    context = _accepted_context(root, acceptance_path, expected_category="prose")
    identity = context["accepted"]["identity"]
    work_id = identity["work_id"]
    expected_profile = PROFILE if work_id in WORKS else FINAL_PROFILE if work_id in FINAL_WORKS else None
    if expected_profile is None:
        raise PipelineError("LIB-051 readable profile is outside supported single-work witnesses")
    accounting = json.loads(_bound(root, context["accepted"]["source"]["accounting"]))
    source = accounting.get("source", {})
    if (accounting.get("projection_profile") != expected_profile
            or accounting.get("identity") != identity
            or source.get("source_path") != accounting.get("source_path")
            or source.get("source_sha256") != accounting.get("source_sha256")
            or source.get("source_bytes") != accounting.get("source_bytes")):
        raise PipelineError("LIB-051 readable source profile differs")
    original = _bound(root, accounting["original_candidate"])
    source_raw = io_path(root / source["source_path"]).read_bytes()
    if len(source_raw) != source["source_bytes"] or _sha(source_raw) != source["source_sha256"]:
        raise PipelineError("LIB-051 retained source differs")
    source_tree = oracle._parse_source(source_raw)
    metadata = oracle._metadata(source_tree)
    original_tree = _parse(original)
    expected_header = oracle._expected_header(metadata)
    if etree.tostring(original_tree[0], method="c14n", with_comments=True) != etree.tostring(expected_header, method="c14n", with_comments=True):
        raise PipelineError("LIB-051 readable original header differs from retained source")
    records = oracle._records(source_tree, Path(source["source_path"]).stem)
    original_body = original_tree.find(NS + "text/" + NS + "body")
    if original_body is None or len(original_body) != 1:
        raise PipelineError("LIB-051 readable original body differs")
    oracle._verify_readable_transcription(source_tree, records, original_body, work_id)
    accepted = context["accepted"]
    ordered_identity = {key: identity[key] for key in (
        "work_id", "textual_form_id", "edition_id", "acquisition_id",
    )}
    expected = bind_reviewed_header(
        original, expected_sha256=_sha(original), identity=ordered_identity,
        source=source, source_url=accounting["source_url"],
        declared_scope=accounting["declared_scope"],
        revision=accepted["representation_revision"],
    )
    master_raw = io_path(context["edition"].path).read_bytes()
    if expected != master_raw:
        raise PipelineError("LIB-051 accepted header or master differs from readable source binding")
    master = _parse(master_raw)
    if (master.tag != NS + "TEI" or master.get(XML + "id") != work_id
            or [node.tag for node in master] != [NS + "teiHeader", NS + "text"]):
        raise PipelineError("LIB-051 accepted TEI envelope differs")
    body = master.find(NS + "text/" + NS + "body")
    if (body is None or len(body) != 1 or body[0].tag != NS + "div"
            or body[0].get("type") != "readable-transcription"):
        raise PipelineError("LIB-051 accepted readable body differs")
    binding = {
        "profile": expected_profile, "work_id": work_id, "source_path": source["source_path"],
        "source_sha256": _sha(source_raw), "master_sha256": _sha(master_raw),
        "original_candidate_sha256": _sha(original), "source_node_count": len(records),
        "readable_c14n_sha256": _sha(etree.tostring(body[0], method="c14n")),
    }
    return context, master, body[0], metadata["title"], binding


def _native_view(master: etree._Element, readable: etree._Element, title: str) -> bytes:
    # The accepted master remains the exact readable transcription. The stock
    # native mapper receives only a reversible, source-attested projection view.
    unit = etree.Element(NS + "div")
    head = etree.SubElement(unit, NS + "head")
    head.text = title
    unit.append(deepcopy(readable))
    etree.SubElement(unit, NS + "div")
    view = _parse(_synthetic(master, unit))
    for foreign in view.iter(NS + "foreign"):
        foreign.attrib.pop("ana", None)
    for note in view.iter(NS + "note"):
        for name in ("subtype", "target"):
            if name in note.attrib:
                value = note.attrib.pop(name)
                note.set("ana", ((note.get("ana") or "") +
                         f" urn:ocd:tei-note-{name}:{quote(value, safe='')}").strip())
    return etree.tostring(view, encoding="utf-8", xml_declaration=True)


def project(root: Path, *, acceptance_path: Path) -> dict:
    context, master, readable, title, binding = _checked(root, acceptance_path)
    synthetic = _native_view(master, readable, title)
    with tempfile.TemporaryDirectory(prefix="ocd-lib051-owen-") as folder:
        path = Path(folder) / "readable.tei.xml"
        path.write_bytes(synthetic)
        result = native_documents.project_document(
            path, identity=context["identity"], language=context["language"],
            representation_revision=context["representation_revision"],
            edition_title=context["edition_title"], _allow_acceptance_metadata=True,
            category="prose",
        )
    if len(result["rows"]) != 1 or result["receipt"]["unsupported"]:
        raise PipelineError("LIB-051 readable source-defined prose row differs")
    result["rows"], alias_count = _alias_private_source_annotations(result["rows"])
    result["receipt"].update(
        scope=SCOPE, authority=context["authority"], source_binding=binding,
        accepted_master_sha256=binding["master_sha256"], synthetic_sha256=_sha(synthetic),
        public_annotation_aliases={"profile": PUBLIC_ANNOTATION_PROFILE, "count": alias_count},
    )
    return result


def verify(root: Path, *, acceptance_path: Path, rows, receipt) -> list[str]:
    try:
        context, master, readable, title, binding = _checked(root, acceptance_path)
        if (not isinstance(receipt, dict) or receipt.get("scope") != SCOPE
                or receipt.get("authority") != context["authority"]
                or receipt.get("source_binding") != binding):
            return ["LIB-051 accepted authority or source binding differs"]
        if (not isinstance(receipt.get("public_annotation_aliases"), dict)
                or receipt["public_annotation_aliases"].get("profile") != PUBLIC_ANNOTATION_PROFILE):
            return ["LIB-051 public annotation alias binding differs"]
        synthetic = _native_view(master, readable, title)
        if (receipt.get("synthetic_sha256") != _sha(synthetic)
                or receipt.get("accepted_master_sha256") != binding["master_sha256"]):
            return ["LIB-051 readable projection source differs"]
        native_receipt = dict(receipt)
        for key in ("authority", "source_binding", "accepted_master_sha256", "synthetic_sha256",
                    "public_annotation_aliases"):
            native_receipt.pop(key)
        native_receipt["scope"] = native_documents.SCOPE
        with tempfile.TemporaryDirectory(prefix="ocd-lib051-owen-check-") as folder:
            path = Path(folder) / "readable.tei.xml"
            path.write_bytes(synthetic)
            projected = native_documents.project_document(
                path, identity=context["identity"], language=context["language"],
                representation_revision=context["representation_revision"],
                edition_title=context["edition_title"], _allow_acceptance_metadata=True,
                category="prose",
            )
            expected_rows, alias_count = _alias_private_source_annotations(projected["rows"])
            if (rows != expected_rows
                    or receipt["public_annotation_aliases"] != {
                        "profile": PUBLIC_ANNOTATION_PROFILE, "count": alias_count
                    }):
                return ["LIB-051 public source annotation aliases differ"]
            return native_documents.verify_document(
                path, projected["rows"], native_receipt, identity=context["identity"],
                language=context["language"], representation_revision=context["representation_revision"],
                edition_title=context["edition_title"], _allow_acceptance_metadata=True,
                category="prose",
            )
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
