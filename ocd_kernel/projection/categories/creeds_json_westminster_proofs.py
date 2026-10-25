"""Preserve Westminster confession chapters, sections, and source proof order."""

from __future__ import annotations

import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.doctrinal_documents import _validate_rows


ROOT = Path(__file__).resolve().parents[3]
ROUTES = json.loads((ROOT / "build/tools/creeds_json_westminster_proofs_route.json").read_text(encoding="utf-8"))


def shape(work_id: str, document: dict[str, object]) -> dict[str, object]:
    route = ROUTES.get(work_id)
    if route is None:
        raise PipelineError(f"Westminster proof route is outside the declared source: {work_id}")
    metadata = document.get("Metadata")
    chapters = document.get("Data")
    if (not isinstance(metadata, dict) or metadata.get("CreedFormat") != "Confession"
            or not isinstance(chapters, list) or len(chapters) != route["chapter_count"]):
        raise PipelineError("nested confession source envelope differs")
    count = 0
    proof_count = 0
    reference_count = 0
    for chapter_index, chapter in enumerate(chapters):
        if (not isinstance(chapter, dict) or set(chapter) != {"Chapter", "Title", "Sections"}
                or not isinstance(chapter["Chapter"], str) or not chapter["Chapter"]
                or not isinstance(chapter["Title"], str) or not chapter["Title"]
                or not isinstance(chapter["Sections"], list) or not chapter["Sections"]):
            raise PipelineError(f"nested confession chapter {chapter_index + 1} differs")
        if chapter["Chapter"] != route["chapter_labels"][chapter_index]:
            raise PipelineError(f"nested confession chapter label {chapter_index + 1} differs")
        for section_index, section in enumerate(chapter["Sections"]):
            if (not isinstance(section, dict) or set(section) != {"Section", "Content", "ContentWithProofs", "Proofs"}
                    or not isinstance(section["Section"], str) or not section["Section"]
                    or not isinstance(section["Content"], str) or not section["Content"]
                    or not isinstance(section["ContentWithProofs"], str) or not section["ContentWithProofs"]
                    or not isinstance(section["Proofs"], list) or not section["Proofs"]):
                raise PipelineError(f"nested confession section {chapter_index + 1}/{section_index + 1} differs")
            for proof in section["Proofs"]:
                if (not isinstance(proof, dict) or set(proof) != {"Id", "References"}
                        or not isinstance(proof["Id"], int) or isinstance(proof["Id"], bool) or proof["Id"] < 1
                        or not isinstance(proof["References"], list) or not proof["References"]
                        or any(not isinstance(ref, str) or not ref for ref in proof["References"])):
                    raise PipelineError(f"Westminster proof at section {chapter_index + 1}/{section_index + 1} differs")
                proof_count += 1
                reference_count += len(proof["References"])
            count += 1
    if (count != route["row_count"] or proof_count != route["proof_count"]
            or reference_count != route["reference_count"]):
        raise PipelineError("Westminster section/proof/reference census differs")
    return route


def project_units(context: dict[str, object], document: dict[str, object], loci: dict[str, str]) -> list[dict[str, object]]:
    """Project each Section as a row with its exact Chapter parent."""
    shape(context["work_id"], document)
    identity = {key: context["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")}
    rows = []
    for chapter_index, chapter in enumerate(document["Data"]):
        for section_index, section in enumerate(chapter["Sections"]):
            sequence = len(rows) + 1
            path = f"$/Data/{chapter_index}/Sections/{section_index}"
            anchor = loci.get(path + "#item")
            if not anchor:
                raise PipelineError(f"nested confession section has no accepted TEI anchor: {path}")
            content = section["Content"]
            rows.append({
                **identity,
                "record_id": f"{identity['edition_id']}:unit-{sequence:06d}",
                "sequence": sequence, "category": "doctrinal_documents", "language": "en",
                "representation_revision": context["accepted"]["representation_revision"]["id"],
                "text": content, "document_id": context["work_id"], "document_kind": "confession",
                "unit_type": "section", "number": section["Section"], "title": None, "content": content,
                "content_blocks": [content], "content_with_proofs": section["ContentWithProofs"],
                "proofs": [
                    {"id": proof["Id"], "references": [{"raw": ref, "osis": [ref]} for ref in proof["References"]]}
                    for proof in section["Proofs"]
                ],
                "revision_history": [], "parent_path": ["Data", str(chapter_index)],
                "locator": {
                    "kind": "unit", "text_part": "body", "part_titles": [],
                    "divisions": [
                        {"order": chapter_index + 1, "type": "chapter", "number": chapter["Chapter"], "titles": [chapter["Title"]]},
                        {"order": section_index + 1, "type": "section", "number": section["Section"], "titles": []},
                    ],
                    "unit": anchor, "unit_path": ["Data", str(chapter_index), "Sections", str(section_index)],
                    "source_order": sequence,
                },
                "provenance": {
                    "edition_title": context["edition_title"], "source_title": document["Metadata"]["Title"],
                    "source_url": context["source_url"], "source_location": context["source_path"],
                },
            })
    _validate_rows(rows)
    return rows


def verify_units(context: dict[str, object], rows: list[dict[str, object]], crosswalk: dict[tuple[str, str], str]) -> list[str]:
    """Derive section rows afresh from retained JSON and oracle item anchors."""
    source = context["document"]
    shape(context["work_id"], source)
    chapters = source["Data"]
    expected_count = sum(len(chapter["Sections"]) for chapter in chapters)
    if len(rows) != expected_count:
        return ["checker: nested confession row count differs from source sections"]
    sequence = 0
    for chapter_index, chapter in enumerate(chapters):
        for section_index, section in enumerate(chapter["Sections"]):
            sequence += 1
            path = f"$/Data/{chapter_index}/Sections/{section_index}"
            anchor = crosswalk.get((path, "item"))
            if not anchor:
                return [f"checker: nested confession section {sequence} has no TEI item"]
            identity = context["identity"]
            content = section["Content"]
            expected = {
                "work_id": identity["work_id"], "textual_form_id": identity["textual_form_id"],
                "edition_id": identity["edition_id"],
                "record_id": f"{identity['edition_id']}:unit-{sequence:06d}",
                "sequence": sequence, "category": "doctrinal_documents", "language": "en",
                "representation_revision": context["accepted"]["representation_revision"]["id"],
                "text": content, "document_id": context["work_id"], "document_kind": "confession",
                "unit_type": "section", "number": section["Section"], "title": None, "content": content,
                "content_blocks": [content], "content_with_proofs": section["ContentWithProofs"],
                "proofs": [
                    {"id": original["Id"], "references": [
                        {"raw": citation, "osis": [citation]} for citation in original["References"]
                    ]}
                    for original in section["Proofs"]
                ],
                "revision_history": [], "parent_path": ["Data", str(chapter_index)],
                "locator": {
                    "kind": "unit", "text_part": "body", "part_titles": [],
                    "divisions": [
                        {"order": chapter_index + 1, "type": "chapter", "number": chapter["Chapter"], "titles": [chapter["Title"]]},
                        {"order": section_index + 1, "type": "section", "number": section["Section"], "titles": []},
                    ],
                    "unit": anchor, "unit_path": ["Data", str(chapter_index), "Sections", str(section_index)],
                    "source_order": sequence,
                },
                "provenance": {
                    "edition_title": context["edition_title"], "source_title": source["Metadata"]["Title"],
                    "source_url": context["source_url"], "source_location": context["source_path"],
                },
            }
            if rows[sequence - 1] != expected:
                return [f"checker: nested confession row {sequence} differs from source and carrier"]
    _validate_rows(rows)
    return []
