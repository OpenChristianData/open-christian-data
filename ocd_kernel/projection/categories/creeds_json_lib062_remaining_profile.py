"""Accepted-authority profile for exact remaining LIB062 catechism witnesses.

This stays separate from the general catechism parser. It binds the retained
JSON, source-accounting profile, original candidate body, and native Q&A rows.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.lib062_json_catechisms_oracle import _strict_json
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.catechisms import _accepted_metadata
from ocd_kernel.projection.categories.creeds_json_lib062_remaining import ROUTES, STAGEABLE, project_rows, verify_rows
from ocd_kernel.tei.install_accepted import _io_path


PROFILE = "ocd-creeds-json-lib062-remaining-v1"
CONTRACT = "ocd-creeds-json-lib062-remaining-accepted-projection-v1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _null_paths(value: object, path: str = "$") -> list[str]:
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [found for key, child in value.items() for found in _null_paths(child, f"{path}/{key}")]
    if isinstance(value, list):
        return [found for index, child in enumerate(value) for found in _null_paths(child, f"{path}/{index}")]
    return []


def _body(value: bytes) -> bytes:
    boundary = b"</teiHeader>"
    if value.count(boundary) != 1:
        raise PipelineError("accepted catechism TEI header boundary differs")
    return value.split(boundary, 1)[1]


def _metadata_header(master_bytes: bytes, source_metadata: dict[str, object]) -> None:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(master_bytes, parser)
    if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
        raise PipelineError("accepted catechism TEI declaration/comment differs")
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    items = root.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc/t:list[@type='source-metadata']/t:item", namespaces=ns)
    if len(items) != len(source_metadata):
        raise PipelineError("accepted catechism source metadata carrier count differs")
    for item, (key, value) in zip(items, source_metadata.items(), strict=True):
        if item.get("n") != key or list(item):
            raise PipelineError(f"accepted catechism source metadata key differs: {key}")
        try:
            decoded = json.loads(item.text or "")
        except json.JSONDecodeError as exc:
            raise PipelineError(f"accepted catechism source metadata scalar is invalid: {key}") from exc
        if decoded != value or type(decoded) is not type(value):
            raise PipelineError(f"accepted catechism source metadata value differs: {key}")


def _context(root: Path, acceptance_path: Path) -> dict[str, object]:
    root = root.absolute()
    metadata = _accepted_metadata(_io_path(root), _io_path(acceptance_path))
    work_id = metadata["identity"]["work_id"]
    route = ROUTES.get(work_id)
    if route is None or work_id not in STAGEABLE:
        raise PipelineError(f"accepted catechism is outside exact stageable members: {work_id}")
    if metadata["identity"]["textual_form_id"] != route.get("textual_form_id", f"{work_id}-retained-electronic"):
        raise PipelineError("accepted catechism textual form differs from exact route")
    accepted = metadata["acceptance"]
    if (metadata["language"] != "en" or accepted["source"]["source_path"] != route["source_path"]
            or accepted["source"]["source_sha256"] != route["source_sha256"]):
        raise PipelineError("accepted catechism language or retained member differs")
    account_path = root / accepted["source"]["accounting"]["path"]
    accounting = json.loads(_io_path(account_path).read_bytes())
    if not isinstance(accounting, dict) or accounting.get("projection_profile") != PROFILE:
        raise PipelineError("accepted catechism source accounting lacks exact profile")
    evidence = accounting.get("metadata_evidence")
    expected_evidence = f"library/works/{work_id}/integration/creeds-json-metadata-rebind-v1/metadata-evidence.json"
    if not isinstance(evidence, dict) or evidence.get("path") != expected_evidence:
        raise PipelineError("accepted catechism metadata evidence path differs")
    evidence_bytes = _io_path(root / expected_evidence).read_bytes()
    if _sha(evidence_bytes) != evidence.get("sha256"):
        raise PipelineError("accepted catechism metadata evidence hash differs")
    metadata_evidence = json.loads(evidence_bytes)
    if (metadata_evidence.get("source_path") != route["source_path"]
            or metadata_evidence.get("source_sha256") != route["source_sha256"]
            or metadata_evidence.get("category") != "catechisms"
            or metadata_evidence.get("language") != "en"
            or metadata_evidence.get("document_kind") != "catechism"):
        raise PipelineError("accepted catechism metadata declaration differs")
    if work_id == "heidelberg-catechism":
        basis = metadata_evidence.get("language_basis")
        if (not isinstance(basis, dict)
                or basis.get("original_language_metadata") != "German"
                or basis.get("original_language_is_not_this_electronic_text_language") is not True
                or basis.get("accepted_tei_root_xml_lang") != "en"):
            raise PipelineError("Heidelberg historical and electronic language binding differs")
    accountability_path = root / "library/works" / work_id / "integration/creeds-json-electronic-v1/inputs/package/source-accountability.json"
    if (_sha(_io_path(accountability_path).read_bytes()) != accounting.get("package_accountability_sha256")
            or accounting.get("omitted_leaf_count") != 0
            or accounting.get("duplicate_leaf_count") != 0):
        raise PipelineError("accepted catechism leaf-accountability binding differs")
    source_bytes = _io_path(root / route["source_path"]).read_bytes()
    if _sha(source_bytes) != route["source_sha256"]:
        raise PipelineError("accepted catechism retained source differs")
    document = _strict_json(source_bytes, "accepted retained catechism")
    master_bytes = _io_path(metadata["master_path"]).read_bytes()
    _metadata_header(master_bytes, document["Metadata"])
    original_path = root / "library/works" / work_id / "integration/creeds-json-electronic-v1/inputs/package/content.tei.xml"
    original_bytes = _io_path(original_path).read_bytes()
    if _sha(original_bytes) != route["candidate_content_sha256"] or _body(master_bytes) != _body(original_bytes):
        raise PipelineError("accepted catechism TEI body differs from source-oracle candidate")
    return {
        "root": root, "work_id": work_id, "route": route, "metadata": metadata,
        "document": document, "source_bytes": source_bytes, "master_bytes": master_bytes,
        "identity": metadata["identity"], "representation_revision": metadata["representation_revision"],
        "edition_title": metadata["edition"].title,
    }


def _receipt(context: dict[str, object], rows: list[dict[str, object]]) -> dict[str, object]:
    metadata = context["metadata"]
    source = context["document"]
    receipt = {
        "contract": CONTRACT, "profile": PROFILE, "status": "projected",
        "identity": {key: context["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")},
        "authority": metadata["authority"],
        "source_path": context["route"]["source_path"],
        "source_sha256": _sha(context["source_bytes"]),
        "master_sha256": _sha(context["master_bytes"]),
        "category": "catechisms", "language": "en", "row_count": len(rows),
        "rows_sha256": _sha(_canonical(rows)),
        "proof_count": sum(len(row["proofs"]) for row in rows),
        "reference_count": sum(len(proof["references"]) for row in rows for proof in row["proofs"]),
        "subquestion_count": sum(len(row["sub_questions"] or []) for row in rows),
        "retained_metadata": source["Metadata"],
        "metadata_sha256": _sha(_canonical(source["Metadata"])),
        "null_json_paths": _null_paths(source),
        "data_disposition": "Every source Number, Question, Answer, present AnswerWithProofs, Proofs Id/References, and nested SubQuestions value is projected in source order; empty proof arrays and empty proof-bearing answer strings remain explicit.",
        "unprojected_source_content": [],
        "limits": ["bounded accepted electronic witness", "rights and historical print lineage separate"],
    }
    if context["work_id"] == "heidelberg-catechism":
        receipt["question_with_proofs_count"] = sum("question_with_proofs" in row for row in rows)
        receipt["data_disposition"] = (
            "Every source Number, Question, present QuestionWithProofs, Answer, present "
            "AnswerWithProofs, Proofs Id/References value is projected in source order; "
            "empty proof arrays remain explicit."
        )
    return receipt


def project(root: Path, *, acceptance_path: Path) -> dict[str, object]:
    context = _context(root, acceptance_path)
    rows = project_rows(context, context["document"], context["master_bytes"])
    return {"rows": rows, "receipt": _receipt(context, rows)}


def verify(root: Path, *, acceptance_path: Path, rows: object, receipt: object) -> list[str]:
    try:
        if not isinstance(rows, list) or not isinstance(receipt, dict):
            return ["checker: catechism rows or receipt have the wrong type"]
        context = _context(root, acceptance_path)
        errors = verify_rows(context, rows, context["master_bytes"])
        if errors:
            return errors
        return [] if receipt == _receipt(context, rows) else ["checker: catechism receipt differs"]
    except (PipelineError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [str(exc)]
