"""Diagnose and, when possible, project Maclaren's accepted v3 master.

The accepted master remains authoritative and unchanged.  The only permitted
projection-view mutation is deletion of the document-root ``TEI@xml:id``.
The resulting evidence binds that view back to the accepted master and proves
that the complete ``text`` subtree is unchanged.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories import sermons
from ocd_kernel.tei.acceptance import validate_acceptance


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "maclaren-expositions"
WORK = Path("library/works") / WORK_ID
EDITION = (
    WORK
    / "forms/maclaren-expositions-pg-retained-en/editions"
    / "maclaren-expositions-pg-fifteen-volume-cohort"
)
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
STATE = WORK / "state.json"
EVIDENCE = WORK / "integration/full-cohort-v3/acceptance-v1"
OUTPUT = EVIDENCE / "actual-master-projection-view-attempt.json"
EXPECTED_ACCEPTANCE_SHA256 = (
    "41a8a57d264b6bacbd7383fe2147b57a4560d3617b507bcaed8e08ced4978b01"
)
EXPECTED_MASTER_SHA256 = (
    "50a0967ed3b0918a32d151bb18541805d381419e17c4435218e0d0e69bf5ff7f"
)
EXPECTED_ROOT_ID = "maclaren-expositions-full-cohort-v3"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _attribute_name(name: str) -> str:
    if name.startswith(f"{{{XML_NS}}}"):
        return "xml:" + etree.QName(name).localname
    return name


def build_projection_view(raw: bytes) -> tuple[bytes, dict]:
    """Delete only the unreferenced root xml:id and return mutation proof."""
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
    actual = etree.fromstring(raw, parser)
    if actual.tag != f"{{{TEI_NS}}}TEI":
        raise PipelineError("Maclaren accepted master is not a TEI root")
    root_id = actual.get(XML_ID)
    if root_id != EXPECTED_ROOT_ID:
        raise PipelineError("Maclaren accepted master root xml:id differs")

    references = []
    substring_collisions = []
    for node in actual.iter():
        for name, value in node.attrib.items():
            if node is actual and name == XML_ID:
                continue
            tokens = value.split()
            if any(token == root_id or token.endswith("#" + root_id) for token in tokens):
                references.append(
                    {
                        "element": etree.QName(node).localname,
                        "attribute": _attribute_name(name),
                        "value": value,
                    }
                )
            elif root_id in value:
                substring_collisions.append(
                    {
                        "element": etree.QName(node).localname,
                        "attribute": _attribute_name(name),
                        "value": value,
                    }
                )
    if references:
        raise PipelineError("Maclaren root xml:id is referenced and cannot be omitted")

    marker = f' xml:id="{root_id}"'.encode("utf-8")
    root_end = raw.find(b">", raw.find(b"<TEI"))
    offset = raw.find(marker)
    if root_end < 0 or offset < 0 or offset >= root_end or raw.count(marker) != 1:
        raise PipelineError("Maclaren root xml:id is not one exact removable byte slice")
    view = raw[:offset] + raw[offset + len(marker) :]
    restored = view[:offset] + marker + view[offset:]
    if restored != raw:
        raise PipelineError("Maclaren projection view has a mutation beyond root xml:id")

    projected = etree.fromstring(view, parser)
    if projected.get(XML_ID) is not None:
        raise PipelineError("Maclaren projection view retained the root xml:id")
    actual_text = actual.find(f"{{{TEI_NS}}}text")
    projected_text = projected.find(f"{{{TEI_NS}}}text")
    if actual_text is None or projected_text is None:
        raise PipelineError("Maclaren projection view has no complete text subtree")
    actual_text_bytes = etree.tostring(actual_text, method="c14n", with_comments=False)
    projected_text_bytes = etree.tostring(projected_text, method="c14n", with_comments=False)
    if actual_text_bytes != projected_text_bytes:
        raise PipelineError("Maclaren projection view changed the text subtree")

    proof = {
        "contract": "ocd-maclaren-root-id-projection-view-v1",
        "actual_master_sha256": _sha_bytes(raw),
        "projection_view_sha256": _sha_bytes(view),
        "original_root_xml_id": root_id,
        "omitted_attribute": "TEI@xml:id",
        "omitted_utf8_bytes": len(marker),
        "omitted_byte_offset": offset,
        "only_mutation_is_exact_root_attribute_deletion": True,
        "master_reconstructed_exactly_from_view_and_omitted_bytes": True,
        "root_id_reference_count": 0,
        "substring_collision_count": len(substring_collisions),
        "substring_collisions": substring_collisions,
        "actual_text_subtree_c14n_sha256": _sha_bytes(actual_text_bytes),
        "projection_view_text_subtree_c14n_sha256": _sha_bytes(projected_text_bytes),
        "text_subtree_unchanged": True,
        "actual_element_count": sum(1 for _ in actual.iter()),
        "projection_view_element_count": sum(1 for _ in projected.iter()),
        "actual_xml_id_count": sum(1 for node in actual.iter() if node.get(XML_ID)),
        "projection_view_xml_id_count": sum(1 for node in projected.iter() if node.get(XML_ID)),
    }
    return view, proof


def structural_diagnostics(view: bytes) -> dict:
    """Census all profile incompatibilities after the sole permitted mutation."""
    doc = etree.fromstring(
        view,
        etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True),
    )
    profile = json.loads(sermons.SCHEMA.read_text(encoding="utf-8"))["x-ocd-profile"]
    namespaces = {"t": TEI_NS}
    unknown_elements: Counter[str] = Counter()
    unknown_attributes: Counter[str] = Counter()
    unsupported_division_types: Counter[str] = Counter()
    pending = [(doc, False)]
    while pending:
        node, inside_header = pending.pop()
        tag = etree.QName(node).localname
        header = inside_header or tag == "teiHeader"
        elements = sermons._ACCEPTANCE_HEADER_ELEMENTS if header else profile["elements"]
        attributes = sermons._ACCEPTANCE_HEADER_ATTRIBUTES if header else profile["attributes"]
        if tag not in elements:
            unknown_elements[("header:" if header else "text:") + tag] += 1
        allowed = set(attributes.get(tag, [])) if tag in elements else set()
        for name in node.attrib:
            normalized = _attribute_name(name)
            if normalized not in allowed:
                unknown_attributes[f"{tag}@{normalized}"] += 1
        if tag == "div" and node.get("type") not in profile["division_types"]:
            unsupported_division_types[str(node.get("type"))] += 1
        pending.extend((child, header) for child in reversed(node))
    body = doc.find("t:text/t:body", namespaces=namespaces)
    direct = [] if body is None else [
        {
            "tag": etree.QName(node).localname,
            "type": node.get("type"),
            "xml_id": node.get(XML_ID),
        }
        for node in body
    ]
    return {
        "unknown_element_counts": dict(sorted(unknown_elements.items())),
        "unknown_attribute_counts": dict(sorted(unknown_attributes.items())),
        "unsupported_division_type_counts": dict(sorted(unsupported_division_types.items())),
        "direct_body_children": direct,
        "direct_body_child_count": len(direct),
        "native_sermon_unit_count": sum(
            1 for item in direct if item["tag"] == "div" and item["type"] == "sermon" and item["xml_id"]
        ),
    }


def attempt(root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    acceptance_path = root / ACCEPTANCE
    master_path = root / MASTER
    if _sha(acceptance_path) != EXPECTED_ACCEPTANCE_SHA256:
        raise PipelineError("Maclaren acceptance record changed")
    if _sha(master_path) != EXPECTED_MASTER_SHA256:
        raise PipelineError("Maclaren accepted master changed")
    validate_acceptance(acceptance_path, root=root)
    validate_state(root / STATE, root=root)
    load_work(root / WORK / "work.json")
    context = sermons._accepted_context(root, acceptance_path)

    direct_error = None
    try:
        sermons.project_accepted_sermons(root, acceptance_path=acceptance_path)
    except PipelineError as exc:
        direct_error = f"{type(exc).__name__}: {exc}"
    if direct_error != "PipelineError: unsupported-visible: TEI@xml:id":
        raise PipelineError("Maclaren direct actual-master projector result changed")

    raw = master_path.read_bytes()
    view, proof = build_projection_view(raw)
    diagnostics = structural_diagnostics(view)
    with tempfile.TemporaryDirectory(prefix="maclaren-projection-view-") as temporary:
        view_path = Path(temporary) / "master.projection-view.tei.xml"
        view_path.write_bytes(view)
        kwargs = {
            "identity": context["identity"],
            "language": context["language"],
            "representation_revision": context["representation_revision"],
            "edition_title": context["edition_title"],
            "_allow_acceptance_metadata": True,
        }
        projected = None
        producer_error = None
        try:
            projected = sermons.project_sermons_document(view_path, **kwargs)
        except PipelineError as exc:
            producer_error = f"{type(exc).__name__}: {exc}"
        if projected is None:
            verifier_errors = sermons.verify_sermons_document(view_path, [], {}, **kwargs)
        else:
            verifier_errors = sermons.verify_sermons_document(
                view_path,
                projected["rows"],
                projected["receipt"],
                **kwargs,
            )

    result = {
        "contract": "ocd-maclaren-actual-master-projection-view-attempt-v1",
        "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "work_id": WORK_ID,
        "category": "sermons",
        "acceptance_path": ACCEPTANCE.as_posix(),
        "acceptance_sha256": EXPECTED_ACCEPTANCE_SHA256,
        "actual_master_path": MASTER.as_posix(),
        "actual_master_sha256": EXPECTED_MASTER_SHA256,
        "initial_actual_master_projector": {
            "projector": "ocd_kernel.projection.categories.sermons.project_accepted_sermons",
            "error": direct_error,
        },
        "projection_view": proof,
        "profile_diagnostics_after_only_permitted_mutation": diagnostics,
        "view_projector": "ocd_kernel.projection.categories.sermons.project_sermons_document",
        "independent_verifier": "ocd_kernel.projection.categories.sermons.verify_sermons_document",
        "view_projector_error": producer_error,
        "independent_verifier_errors": verifier_errors,
        "row_count": len(projected["rows"]) if projected is not None else 0,
        "receipt": projected["receipt"] if projected is not None else None,
        "shared_code_changed": False,
        "accepted_master_changed": False,
    }
    if projected is not None and not verifier_errors:
        result.update(status="pass", readiness="technically-projected")
    else:
        result.update(
            status="blocked",
            readiness="not-ready-for-publication",
            blocker=(
                "The sermons profile still rejects the faithful accepted structure after "
                "the sole permitted root-identity omission."
            ),
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-evidence", action="store_true")
    args = parser.parse_args()
    result = attempt()
    if args.write_evidence:
        output = ROOT / OUTPUT
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(_json_bytes(result))
        print(json.dumps({"path": OUTPUT.as_posix(), "sha256": _sha(output), "status": result["status"]}, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
