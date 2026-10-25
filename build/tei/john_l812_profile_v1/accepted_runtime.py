"""Isolated L812 accepted-reader postimage; delegates all other works unchanged."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import jsonschema
from referencing import Registry, Resource
import referencing.jsonschema

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.categories.sermons import _accepted_context
from ocd_kernel.projection.native_content import readable_content

HERE = Path(__file__).resolve().parent
PROFILE_PATH = HERE / "john_l812_leaf_v5.py"
SOURCE_PROJECTION_PATH = HERE / "source_projection.py"
NATIVE_SCHEMA_RELATIVE = Path("schemas/v2/native-content.schema.json")
PROSE_SCHEMA_RELATIVE = Path("schemas/v2/categories/prose.schema.json")
COMMON_SCHEMA_RELATIVE = Path("schemas/v2/public-row.schema.json")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _module(path: Path, module_name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load isolated L812 module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _validator(root: Path):
    prose = json.loads(io_path(root / PROSE_SCHEMA_RELATIVE).read_text(encoding="utf-8"))
    common = json.loads(io_path(root / COMMON_SCHEMA_RELATIVE).read_text(encoding="utf-8"))
    native = json.loads(io_path(root / NATIVE_SCHEMA_RELATIVE).read_text(encoding="utf-8"))
    spec = referencing.jsonschema.DRAFT202012
    registry = Registry().with_resources([
        (common["$id"], Resource.from_contents(common, default_specification=spec)),
        (native["$id"], Resource.from_contents(native, default_specification=spec)),
    ])
    result = jsonschema.Draft202012Validator(
        prose, registry=registry, format_checker=jsonschema.FormatChecker())
    result.check_schema(prose)
    return result


def _validate_rows(rows, root: Path):
    validator = _validator(root)
    for index, row in enumerate(rows, 1):
        problems = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if problems:
            raise ValueError(f"L812 prose row {index} fails postimage schema: {problems[0].message}")


def _source_profile_projection(context):
    leaf = _module(PROFILE_PATH, "ocd_l812_leaf_v3_runtime")
    leaf.verify_runtime_authorities(Path(context["root"]))
    master_raw = io_path(context["edition"].path).read_bytes()
    leaf.verify_master(master_raw)
    if context["authority"]["master"]["sha256"] != _sha(master_raw):
        raise ValueError("validated accepted master authority changed during L812 projection")
    adapter = _module(SOURCE_PROJECTION_PATH, "ocd_l812_source_projection_runtime")
    proof = adapter.project(master_raw, root=Path(context["root"]))
    content = proof["native_projection"].get("content")
    if not isinstance(content, list):
        raise ValueError("L812 body projection content is missing")
    divisions = [node for node in content
                 if node.get("kind") == "division"]
    if (len(divisions) != 2
            or divisions[0].get("attributes") != {"type": "praefatio", "language": "eng"}
            or divisions[1].get("attributes") != {
                "type": "edition", "number": "urn:cts:pta:pta0200.pta001.pta-syc1",
                "language": "syc"}):
        raise ValueError("L812 source units or their source languages differ")
    # Keep inter-unit whitespace in the parallel structure: each row carries
    # its leading source text and complete selected source division.
    groups = [[], []]
    division_index = -1
    for node in content:
        if node.get("kind") == "division":
            division_index += 1
            if division_index > 1:
                raise ValueError("unexpected third L812 body division")
        if division_index < 0:
            groups[0].append(node)
        else:
            groups[division_index].append(node)
    if division_index != 1:
        raise ValueError("L812 two-unit source boundary is incomplete")
    rows = []
    for sequence, (unit, structure) in enumerate(zip(divisions, groups, strict=True), 1):
        language = unit["attributes"]["language"]
        row_structure = [{"kind": "segment", "attributes": {"type": "l812-source-unit"},
                          "content": structure}]
        visible = readable_content(row_structure[0])
        unit_path = f"/TEI/text/body/div[{sequence}]"
        rows.append({
            **context["identity"],
            "record_id": context["edition"].edition_id + ":native:" + _sha(unit_path.encode("utf-8"))[:20],
            "sequence": sequence,
            "language": language,
            "representation_revision": context["representation_revision"],
            "provenance": {"edition_title": context["edition_title"]},
            "category": "prose",
            "content_format": "ocd-native-content-v1",
            "structure": row_structure,
            "text": visible,
            "locator": {"kind": "native-unit", "text_part": "body", "unit": sequence},
        })
    _validate_rows(rows, Path(context["root"]))
    schema_hashes = {
        "schema_sha256": _sha(io_path(Path(context["root"]) / PROSE_SCHEMA_RELATIVE).read_bytes()),
        "common_schema_sha256": _sha(io_path(Path(context["root"]) / COMMON_SCHEMA_RELATIVE).read_bytes()),
        "native_content_schema_sha256": _sha(io_path(Path(context["root"]) / NATIVE_SCHEMA_RELATIVE).read_bytes()),
    }
    receipt = {
        "scope": "tei-document; context derived from validated acceptance",
        "mapping_version": leaf.PROFILE,
        "projection_profile": leaf.PROFILE,
        "master_sha256": _sha(master_raw),
        **schema_hashes,
        "output_sha256": _sha(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")),
        "row_count": len(rows),
        "anchors": [{"unit_id": f"body/div[{i}]", "record_id": row["record_id"],
                     "text_sha256": _sha(row["text"].encode("utf-8"))}
                    for i, row in enumerate(rows, 1)],
        "source_profile": {"source_sha256": leaf.SOURCE_SHA256,
                           "source_bytes": leaf.SOURCE_BYTES,
                           "source_master_sha256": _sha(master_raw),
                           "carrier_count": proof["private_ledger_count"],
                           "carrier_ledger_sha256": proof["private_ledger_sha256"],
                           "source_comment_count": proof["source_comment_count"],
                           "source_comment_ledger_sha256": proof["source_comment_ledger_sha256"],
                           "prolog_processing_instructions": 2},
        "warnings": [
            "This accepted electronic witness is the retained Syriac surviving Part III only; Parts I-II and English Part III are absent from the retained source.",
            "The English preface remains a separately identified English source unit; the edition division remains Syriac.",
            "Source-critical apparatus labels are generated reader context; complete raw relations and source trees remain in the private acceptance evidence.",
            "Human acceptance, rights review, and public publication are not established by this agent electronic-witness projection.",
        ],
        "unsupported": [],
        "independent_check": {"status": "pass", "method": "L812 source-profile raw/master observer plus native-content observer"},
        "authority": context["authority"],
    }
    return {"rows": rows, "receipt": receipt}


def select_context(root, context, *, category, collection=False, projection_profile=None):
    """Select only the source-bound L812 record from the validated context."""
    from ocd_kernel.lib.path_io import resolve_path
    if resolve_path(context.get("root")) != resolve_path(root):
        raise ValueError("L812 accepted context root differs from caller")
    leaf = _module(PROFILE_PATH, "ocd_l812_leaf_v3_select")
    return leaf.select_accepted(context, category=category, collection=collection,
                                projection_profile=projection_profile) is not None


def project_accepted_document(root, *, acceptance_path, category, collection=False,
                              projection_profile=None):
    context = _accepted_context(root, acceptance_path, expected_category=category)
    leaf = _module(PROFILE_PATH, "ocd_l812_leaf_v3_dispatch")
    selected = leaf.select_accepted(context, category=category, collection=collection,
                                    projection_profile=projection_profile)
    if selected is None:
        return native_documents.project_accepted_document(
            root, acceptance_path=acceptance_path, category=category,
            collection=collection, projection_profile=projection_profile)
    return _source_profile_projection(context)


def verify_accepted_document(root, *, acceptance_path, rows, receipt, category,
                             collection=False, projection_profile=None):
    try:
        context = _accepted_context(root, acceptance_path, expected_category=category)
        leaf = _module(PROFILE_PATH, "ocd_l812_leaf_v3_verify")
        selected = leaf.select_accepted(context, category=category, collection=collection,
                                        projection_profile=projection_profile)
        if selected is None:
            return native_documents.verify_accepted_document(
                root, acceptance_path=acceptance_path, rows=rows, receipt=receipt,
                category=category, collection=collection,
                projection_profile=projection_profile)
        expected = _source_profile_projection(context)
        errors = []
        if rows != expected["rows"]:
            errors.append("L812 rows differ from current source-derived accepted projection")
        if receipt != expected["receipt"]:
            errors.append("L812 receipt differs from current source, schema, or acceptance bindings")
        try:
            _validate_rows(rows, Path(context["root"]))
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
        return errors
    except Exception as exc:
        # This work-local adapter normalizes expected gate failures only; any
        # unrelated runtime error remains visible to the stage process.
        from ocd_kernel.library._common import PipelineError
        if isinstance(exc, (PipelineError, OSError, ValueError, KeyError, TypeError)):
            return [str(exc)]
        raise
