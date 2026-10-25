"""Source-defined Canon unit mapping for declared retained Creeds.json members.

The exact source label is never renumbered. Prefatory and concluding units
remain ordered text units with front/back locators; Roman-labelled canons remain
articles. The complete JSON tree stays in the accepted carrier and receipt.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.doctrinal_documents import _validate_rows


ROOT = Path(__file__).resolve().parents[3]
ROUTES = json.loads((ROOT / "build/tools/creeds_json_canon_variant_routes.json").read_text(encoding="utf-8"))


def shape(work_id: str, document: dict[str, object]) -> dict[str, object]:
    route = ROUTES.get(work_id)
    if route is None:
        raise PipelineError(f"Canon variant is outside the declared source members: {work_id}")
    metadata = document.get("Metadata")
    data = document.get("Data")
    if (not isinstance(metadata, dict) or metadata.get("CreedFormat") != "Canon"
            or not isinstance(data, list) or len(data) != route["row_count"]
            or [item.get("Article") if isinstance(item, dict) else None for item in data] != route["labels"]):
        raise PipelineError("Canon variant source envelope or label sequence differs")
    for index, item in enumerate(data):
        fields = {"Article", "Title", "Content"}
        if route.get("source_proof_groups"):
            fields |= {"ContentWithProofs", "Proofs", "ProofsWithScripture"}
        if (not isinstance(item, dict) or set(item) != fields
                or not all(isinstance(item[key], str) and item[key]
                           for key in fields - {"Proofs", "ProofsWithScripture"})):
            raise PipelineError(f"Canon variant source unit {index + 1} has unsupported fields")
        if route.get("source_proof_groups"):
            parsed, raw = item["Proofs"], item["ProofsWithScripture"]
            if not isinstance(parsed, list) or not isinstance(raw, list) or len(parsed) != len(raw):
                raise PipelineError("Canon source proof groups differ")
            for left, right in zip(parsed, raw, strict=True):
                for proof in (left, right):
                    if (not isinstance(proof, dict) or set(proof) != {"Id", "References"}
                            or type(proof["Id"]) is not int or proof["Id"] < 1
                            or not isinstance(proof["References"], list)
                            or any(not isinstance(ref, str) or not ref for ref in proof["References"])):
                        raise PipelineError("Canon source proof fields differ")
                if left["Id"] != right["Id"] or not right["References"]:
                    raise PipelineError("Canon source proof IDs or raw labels differ")
            if len({proof["Id"] for proof in parsed}) != len(parsed):
                raise PipelineError("Canon source proof IDs repeat")
    front = route["front_indices"]
    back = route["back_indices"]
    if (not isinstance(front, list) or not isinstance(back, list)
            or any(not isinstance(i, int) or i < 0 or i >= len(data) for i in front + back)
            or set(front) & set(back) or len(set(front + back)) != len(front + back)):
        raise PipelineError("Canon variant source part indices differ")
    return route


def _part(route: dict[str, object], index: int) -> str:
    if index in route["front_indices"]:
        return "front"
    if index in route["back_indices"]:
        return "back"
    return "body"


def project_units(context: dict[str, object], document: dict[str, object], loci: dict[str, str]) -> list[dict[str, object]]:
    """Project source-labelled units using producer carrier anchors."""
    route = shape(context["work_id"], document)
    if route.get("source_proof_groups") and hashlib.sha256(context["source_bytes"]).hexdigest() != route["source_sha256"]:
        raise PipelineError("Canon proof source bytes differ from the exact route")
    identity = {key: context["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")}
    metadata = document["Metadata"]
    provenance = {
        "edition_title": context["edition_title"], "source_title": metadata["Title"],
        "source_url": context["source_url"], "source_location": context["source_path"],
    }
    rows = []
    for index, item in enumerate(document["Data"]):
        sequence = index + 1
        path = f"$/Data/{index}"
        anchor = loci.get(path + "#item")
        if not anchor:
            raise PipelineError(f"Canon variant has no accepted TEI unit anchor: {path}")
        part = _part(route, index)
        unit_type = "article" if part == "body" else "text"
        number, title, content = (item[key] for key in ("Article", "Title", "Content"))
        # Raw and machine reference lists differ in length; bind them by source proof ID.
        proofs = [
            {"id": parsed["Id"], "references": [{"raw": "\n".join(raw["References"]),
                                                   "osis": list(parsed["References"])}]}
            for parsed, raw in zip(item["Proofs"], item["ProofsWithScripture"], strict=True)
        ] if route.get("source_proof_groups") else []
        rows.append({
            **identity,
            "record_id": f"{identity['edition_id']}:unit-{sequence:06d}",
            "sequence": sequence, "category": "doctrinal_documents", "language": "en",
            "representation_revision": context["accepted"]["representation_revision"]["id"],
            "text": content, "document_id": context["work_id"], "document_kind": "canon",
            "unit_type": unit_type, "number": number, "title": title, "content": content,
            "content_blocks": [content], "content_with_proofs": item.get("ContentWithProofs"), "proofs": proofs,
            "revision_history": [], "parent_path": ["Data"],
            "locator": {
                "kind": "unit", "text_part": part, "part_titles": [],
                "divisions": [{"order": sequence, "type": unit_type, "number": number, "titles": [title]}],
                "unit": anchor, "unit_path": ["Data", str(index)], "source_order": sequence,
            },
            "provenance": provenance,
        })
    _validate_rows(rows)
    return rows


def verify_units(context: dict[str, object], rows: list[dict[str, object]], crosswalk: dict[tuple[str, str], str]) -> list[str]:
    """Independently derive every row from retained source and oracle crosswalk."""
    source = context["document"]
    route = shape(context["work_id"], source)
    if route.get("source_proof_groups") and hashlib.sha256(context["source_bytes"]).hexdigest() != route["source_sha256"]:
        return ["checker: Canon proof source bytes differ from the exact route"]
    units = source["Data"]
    if len(rows) != len(units):
        return ["checker: Canon variant row count differs from retained Data"]
    identity = context["identity"]
    for index, (source_unit, row) in enumerate(zip(units, rows, strict=True)):
        sequence = index + 1
        path = f"$/Data/{index}"
        anchor = crosswalk.get((path, "item"))
        if not anchor:
            return [f"checker: Canon variant unit {sequence} has no source carrier"]
        label = source_unit["Article"]
        title = source_unit["Title"]
        content = source_unit["Content"]
        part = "front" if index in route["front_indices"] else "back" if index in route["back_indices"] else "body"
        kind = "article" if part == "body" else "text"
        proofs = []
        if route.get("source_proof_groups"):
            for proof_index, proof in enumerate(source_unit["ProofsWithScripture"]):
                machine = source_unit["Proofs"][proof_index]
                proofs.append({"id": proof["Id"], "references": [{
                    "raw": "\n".join(proof["References"]),
                    "osis": [value for value in machine["References"]]}]})
        expected = {
            "work_id": identity["work_id"], "textual_form_id": identity["textual_form_id"],
            "edition_id": identity["edition_id"],
            "record_id": f"{identity['edition_id']}:unit-{sequence:06d}",
            "sequence": sequence, "category": "doctrinal_documents", "language": "en",
            "representation_revision": context["accepted"]["representation_revision"]["id"],
            "text": content, "document_id": context["work_id"], "document_kind": "canon",
            "unit_type": kind, "number": label, "title": title, "content": content,
            "content_blocks": [content], "content_with_proofs": source_unit.get("ContentWithProofs"), "proofs": proofs,
            "revision_history": [], "parent_path": ["Data"],
            "locator": {
                "kind": "unit", "text_part": part, "part_titles": [],
                "divisions": [{"order": sequence, "type": kind, "number": label, "titles": [title]}],
                "unit": anchor, "unit_path": ["Data", str(index)], "source_order": sequence,
            },
            "provenance": {
                "edition_title": context["edition_title"], "source_title": source["Metadata"]["Title"],
                "source_url": context["source_url"], "source_location": context["source_path"],
            },
        }
        if row != expected:
            return [f"checker: Canon variant row {sequence} differs from source and carrier"]
    _validate_rows(rows)
    return []
