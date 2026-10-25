"""Accepted-master bridges for the structured release categories."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError, canonical_bytes


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "library-pipeline" / "categories"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

_CASES = {
    "catechisms": ("catechisms", "westminster-shorter", "catechisms"),
    "doctrinal_documents": (
        "doctrinal-documents",
        "fixture-nicene-creed",
        "doctrinal-documents",
    ),
    "reference_entries": (
        "reference-entries",
        "fixture-eastons-bible-dictionary",
        "reference-entries",
    ),
}
_ALIASES = {
    "catechisms": "catechisms",
    "doctrinal_documents": "doctrinal_documents",
    "doctrinal-documents": "doctrinal_documents",
    "reference_entries": "reference_entries",
    "reference-entries": "reference_entries",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object fixture: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_case(category: str, fixture_id_override: str | None = None) -> tuple[str, dict[str, Any], Path]:
    normalized = _ALIASES.get(category)
    if normalized is None:
        raise ValueError(f"unsupported accepted structured category: {category}")
    directory_name, fixture_id, _library_category = _CASES[normalized]
    fixture_id = fixture_id_override or fixture_id
    directory = FIXTURE_ROOT / directory_name
    manifest = _json(directory / "manifest.json")
    cases = {
        item["fixture_id"]: item
        for item in manifest.get("fixtures", [])
        if isinstance(item, dict) and isinstance(item.get("fixture_id"), str)
    }
    case = cases.get(fixture_id)
    if case is None:
        raise AssertionError(f"missing fixture case {fixture_id}: {directory}")
    return normalized, case, directory


def _set_idno(bibl: etree._Element, kind: str, value: str) -> None:
    nodes = bibl.xpath("./tei:idno[@type=$kind]", namespaces={"tei": TEI_NS}, kind=kind)
    if nodes:
        nodes[0].text = value
        for duplicate in nodes[1:]:
            bibl.remove(duplicate)
        return
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type=kind).text = value


def _set_note(bibl: etree._Element, kind: str, value: str) -> None:
    nodes = bibl.xpath("./tei:note[@type=$kind]", namespaces={"tei": TEI_NS}, kind=kind)
    if nodes:
        nodes[0].text = value
        for duplicate in nodes[1:]:
            bibl.remove(duplicate)
        return
    etree.SubElement(bibl, f"{{{TEI_NS}}}note", type=kind).text = value


def accepted_fixture(tmp_path: Path, category: str, *, doctrinal_hierarchy: bool = False) -> tuple[Path, Path]:
    """Create a pending accepted-master fixture and return ``(root, path)``."""

    if doctrinal_hierarchy and category != "doctrinal_documents":
        raise ValueError("hierarchy fixture requires doctrinal documents")
    normalized, case, fixture_directory = _fixture_case(
        category, "fixture-westminster-confession" if doctrinal_hierarchy else None
    )
    library_category = _CASES[normalized][2]
    base = Path(tmp_path).resolve()
    slug = {"catechisms": "c", "doctrinal_documents": "d", "reference_entries": "r"}[normalized]
    identity = {"work_id": f"w-{slug}", "textual_form_id": f"f-{slug}",
                "edition_id": f"e-{slug}", "acquisition_id": f"a-{slug}"}
    edition_root = (
        base
        / "library"
        / "works"
        / identity["work_id"]
        / "forms"
        / identity["textual_form_id"]
        / "editions"
        / identity["edition_id"]
    )
    edition_root.mkdir(parents=True, exist_ok=True)

    excerpt = _json(fixture_directory / case["source_file"])
    source_original = ROOT / case["source_path"]
    if not source_original.is_file():
        raise AssertionError(f"retained source fixture is missing: {source_original}")
    source_rel = f"raw/{slug}.source"
    source_path = base / source_rel
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_original.read_bytes())
    source_sha256 = _sha(source_path)
    source_bytes = source_path.stat().st_size
    source_scope = str(excerpt["scope"])
    source_url = str(case["source_url"]).replace(" ", "%20")
    source = {
        "source_path": source_rel,
        "source_sha256": source_sha256,
        "source_bytes": source_bytes,
        "source_scope": source_scope,
    }
    included = {
        "path": source_rel,
        "position": 1,
        "bytes": source_bytes,
        "sha256": source_sha256,
        "scope": source_scope,
    }
    scope = {
        "kind": "member",
        "declared": source_scope,
        "expected_members": [{"path": source_rel, "position": 1}],
        "included_members": [included],
        "excluded_members": [],
    }

    work_root = base / "library" / "works" / identity["work_id"]
    work = {
        "schema_version": "2.0",
        "work_id": identity["work_id"],
        "title": case["edition_title"],
        "evidence": [source_url],
        "textual_forms": [
            {
                "textual_form_id": identity["textual_form_id"],
                "language": "en",
                "category": library_category,
                "editions": [
                    {
                        "edition_id": identity["edition_id"],
                        "title": case["edition_title"],
                        "language": "en",
                        "category": library_category,
                        "acquisition_ids": [identity["acquisition_id"]],
                    }
                ],
            }
        ],
    }
    _write_json(work_root / "work.json", work)
    _write_json(
        work_root / "state.json",
        {
            "schema_version": "2.0",
            "work_id": identity["work_id"],
            "targets": [
                {
                    "target_id": identity["edition_id"],
                    "target_type": "edition",
                    "stage": "review",
                    "updated_at": "2026-09-09T00:00:00Z",
                    "evidence": ["candidate.xml"],
                }
            ],
        },
    )
    acquisition = {
        "schema_version": "2.0",
        "acquisition_id": identity["acquisition_id"],
        "edition_id": identity["edition_id"],
        "provider": "retained-source-fixture",
        "url": source_url,
        "route": "born-digital",
        **source,
        "retained_files": [
            {
                **{key: included[key] for key in ("path", "bytes", "sha256", "scope")},
                "media_type": "application/octet-stream",
            }
        ],
    }
    acquisition_path = edition_root / "acquisitions" / f"{identity['acquisition_id']}.json"
    _write_json(acquisition_path, acquisition)

    tree = etree.parse(str(fixture_directory / case["tei_file"]))
    if doctrinal_hierarchy:
        # Synthetic pipeline wiring evidence, not a reconstructed source claim.
        parent = tree.xpath("//tei:div[@type='chapter']", namespaces={"tei": TEI_NS})[0]
        introduction = etree.Element(f"{{{TEI_NS}}}p")
        introduction.text = "Synthetic hierarchy introduction."
        parent.insert(1, introduction)
        etree.SubElement(parent, f"{{{TEI_NS}}}p").text = "Synthetic hierarchy conclusion."
    header = tree.xpath("/tei:TEI/tei:teiHeader", namespaces={"tei": TEI_NS})[0]
    bibl = header.xpath("./tei:fileDesc/tei:sourceDesc/tei:bibl", namespaces={"tei": TEI_NS})[0]
    if doctrinal_hierarchy:
        note = etree.SubElement(bibl.getparent(), f"{{{TEI_NS}}}note", type="source-revision")
        etree.SubElement(note, f"{{{TEI_NS}}}date").text = "1788"
        etree.SubElement(note, f"{{{TEI_NS}}}seg", type="revising-body").text = "Synthetic assembly"
        etree.SubElement(note, f"{{{TEI_NS}}}seg", type="description").text = "Synthetic source revision statement."
    pointers = bibl.xpath("./tei:ptr", namespaces={"tei": TEI_NS})
    if pointers:
        pointers[0].set("target", source_url)
        for duplicate in pointers[1:]:
            bibl.remove(duplicate)
    else:
        etree.SubElement(bibl, f"{{{TEI_NS}}}ptr", target=source_url)
    for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id"):
        _set_idno(bibl, key, identity[key])
    _set_idno(bibl, "source_sha256", source_sha256)
    _set_idno(bibl, "source_bytes", str(source_bytes))
    _set_idno(bibl, "sha256", source_sha256)
    _set_idno(bibl, "retained_sha256", source_sha256)
    _set_idno(bibl, "representation_revision", "fixture-v1")
    _set_note(bibl, "source-path", source_rel)
    _set_note(bibl, "source-location", source_rel)
    _set_note(bibl, "source-scope", source_scope)
    revision_desc = header.find(f"{{{TEI_NS}}}revisionDesc")
    if revision_desc is None:
        revision_desc = etree.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
    for change in revision_desc.xpath("./tei:change", namespaces={"tei": TEI_NS}):
        revision_desc.remove(change)
    change = etree.SubElement(
        revision_desc,
        f"{{{TEI_NS}}}change",
        when="2026-09-09",
    )
    change.set(XML_ID, "fixture-v1")
    change.text = "Bound structured category fixture."
    candidate = base / "candidate.xml"
    candidate.write_bytes(
        etree.tostring(tree, encoding="utf-8", xml_declaration=True, pretty_print=True)
    )

    from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, write_acceptance

    candidate_binding = make_file_binding(base, candidate)
    projection_context: dict[str, Any] = {
        "source_selector": excerpt["selector"],
        "source_scope": excerpt["scope"],
        "source_unit_count": excerpt["native_unit_count"],
        "source_selected_units": excerpt["selected_unit_ids"],
        "source_census": excerpt["native_units"],
        "source_excerpt_sha256": excerpt["source_excerpt_sha256"],
    }
    if doctrinal_hierarchy:
        projection_context["source_tei_unit_bindings"] = [
            {"tei_xml_id": "fixture-wcf-1647-unit-1-1", "source_unit_ids": ["1.1"]},
            {"tei_xml_id": "fixture-wcf-1647-unit-1-2", "source_unit_ids": ["1.2"]},
        ]
    if "selected_subunit_ids" in excerpt:
        projection_context["source_selected_subunits"] = excerpt["selected_subunit_ids"]
    if normalized == "doctrinal_documents":
        projection_context["document_kind"] = case["document_kind"]
    if normalized == "reference_entries":
        projection_context["entry_kind"] = case["entry_kind"]
    accounting = {
        "contract": "ocd-source-accounting-v1",
        "identity": identity,
        "source": source,
        "source_sha256": source_sha256,
        "source_bytes": source_bytes,
        "scope": source_scope,
        "accepted_scope": {"kind": "member", "declared": source_scope},
        "expected_members": scope["expected_members"],
        "included_members": scope["included_members"],
        "excluded_members": scope["excluded_members"],
        "missing_members": [],
        "unknown_members": [],
        "projection_context": projection_context,
    }
    source_accounting_path = base / "evidence" / "source-accounting.json"
    _write_json(source_accounting_path, accounting)

    technical: dict[str, Any] = {
        "producer": {"id": "producer:structured-fixture"},
        "checker": {"id": "checker:structured-fixture"},
        "shared_assumptions": ["Synthetic acceptance binds source-derived fixtures only."],
        "independent_corroboration": "The category fixture and source accounting retain independent source-derived evidence.",
    }
    for name in (
        "validation",
        "accounting",
        "fidelity",
        "reproducibility",
        "schema",
        "closure",
    ):
        proof_path = base / "evidence" / f"{name}.json"
        proof = {
            "contract": f"ocd-tei-{name}-v1",
            "identity": identity,
            "source": source,
            "candidate": candidate_binding,
            "scope": source_scope,
            "status": "pass",
            "command": "simulated-structured-acceptance",
            "exit_code": 0,
            "expected_members": scope["expected_members"],
            "included_members": scope["included_members"],
            "excluded_members": scope["excluded_members"],
            "missing_members": [],
            "unknown_members": [],
        }
        if name == "accounting":
            proof["accepted_scope"] = {"kind": "member", "declared": source_scope}
        _write_json(proof_path, proof)
        technical[name] = {
            "path": proof_path,
            "status": "pass",
            "command": "simulated-structured-acceptance",
            "exit_code": 0,
        }

    coverage = {
        "status": "partial",
        "declared": source_scope,
        "reached": [source_scope],
        "inspected": [f"{source_scope}/fixture"],
        "unreviewed": ["visual acceptance"],
    }
    review = {
        "reviewer": "agent:structured-fixture",
        "reviewed_at": "2026-09-09T00:00:00Z",
        "coverage": coverage,
        "source_quality_uncertainty": ["outside selected source scope"],
        "discrepancies": [],
        "unreviewed_residuals": ["visual acceptance not performed"],
    }
    review_path = base / "evidence" / "review.json"
    _write_json(
        review_path,
        {
            "contract": "ocd-tei-review-v1",
            "identity": identity,
            "source": source,
            "candidate": candidate_binding,
            "scope": source_scope,
            **review,
        },
    )
    decision = {
        "source_local_disposition": "API simulation only",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": "agent:structured-fixture",
            "assessed_at": "2026-09-09T00:00:00Z",
            "supported_scope": source_scope,
            "unassessed_stronger_claims": ["human acceptance"],
            "unresolved_claims": [],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        base,
        identity=identity,
        candidate_path=candidate,
        source_accounting_path=source_accounting_path,
        scope=scope,
        technical=technical,
        review={**review, "report_path": review_path},
        representation_revision={
            "id": "fixture-v1",
            "date": "2026-09-09",
            "note": "Bound structured category fixture.",
        },
        decision=decision,
        missing_members=[],
        unknown_members=[],
    )
    acceptance_path = edition_root / "acceptance.json"
    write_acceptance(acceptance_path, record)
    return base, acceptance_path


def _promote(tmp_path: Path, category: str) -> tuple[Path, Path]:
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance_path = accepted_fixture(tmp_path / "f", category)
    promoted = promote_accepted_master(
        root,
        acceptance_path=acceptance_path,
        destination=tmp_path / "p",
    )
    return promoted.destination_root, promoted.acceptance_path


@pytest.fixture
def compact_tmp(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Use a short temporary directory for Windows path limits."""

    return tmp_path_factory.mktemp("s")


@pytest.mark.parametrize("category", tuple(_CASES))
def test_accepted_structured_projection_round_trip(
    compact_tmp: Path, category: str
) -> None:
    from ocd_kernel.tei.acceptance import promote_accepted_master

    root, acceptance_path = accepted_fixture(compact_tmp / "f", category)
    module = __import__(
        f"ocd_kernel.projection.categories.{category}", fromlist=["unused"]
    )
    projector = getattr(module, f"project_accepted_{category}")
    checker = getattr(module, f"verify_accepted_{category}")
    with pytest.raises(PipelineError, match="promoted"):
        projector(root, acceptance_path=acceptance_path)
    promoted = promote_accepted_master(
        root, acceptance_path=acceptance_path, destination=compact_tmp / "p"
    )
    result = projector(
        promoted.destination_root, acceptance_path=promoted.acceptance_path
    )
    assert result["rows"]
    assert checker(
        promoted.destination_root,
        acceptance_path=promoted.acceptance_path,
        rows=result["rows"],
        receipt=result["receipt"],
    ) == []
    assert result["receipt"]["source_accounting"] is not None


@pytest.mark.parametrize("category", tuple(_CASES))
def test_accepted_structured_rejects_stale_source_accounting(
    compact_tmp: Path, category: str
) -> None:
    root, acceptance_path = _promote(compact_tmp, category)
    accounting_path = root / "evidence" / "source-accounting.json"
    accounting_path.write_bytes(accounting_path.read_bytes() + b"\n")
    module = __import__(
        f"ocd_kernel.projection.categories.{category}", fromlist=["unused"]
    )
    with pytest.raises(PipelineError, match="sha256|stale|byte mismatch"):
        getattr(module, f"project_accepted_{category}")(
            root, acceptance_path=acceptance_path
        )


@pytest.mark.parametrize("category", tuple(_CASES))
def test_accepted_structured_rejects_category_mismatch(
    compact_tmp: Path, category: str
) -> None:
    root, acceptance_path = _promote(compact_tmp, category)
    work_dirs = list((root / "library" / "works").iterdir())
    assert len(work_dirs) == 1
    work_path = work_dirs[0] / "work.json"
    record = _json(work_path)
    record["textual_forms"][0]["editions"][0]["category"] = "other"
    _write_json(work_path, record)
    module = __import__(
        f"ocd_kernel.projection.categories.{category}", fromlist=["unused"]
    )
    with pytest.raises(PipelineError, match="category"):
        getattr(module, f"project_accepted_{category}")(
            root, acceptance_path=acceptance_path
        )


@pytest.mark.parametrize("category", tuple(_CASES))
def test_accepted_structured_checker_rejects_forged_authority_and_does_not_call_producer(
    compact_tmp: Path, category: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, acceptance_path = _promote(compact_tmp, category)
    module = __import__(
        f"ocd_kernel.projection.categories.{category}", fromlist=["unused"]
    )
    projector = getattr(module, f"project_accepted_{category}")
    checker = getattr(module, f"verify_accepted_{category}")
    result = projector(root, acceptance_path=acceptance_path)
    producer_names = {
        "catechisms": "project_catechism_document",
        "doctrinal_documents": "project_doctrinal_document",
        "reference_entries": "project_reference_entries",
    }
    monkeypatch.setattr(
        module,
        producer_names[category],
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("producer called")
        ),
    )
    forged = copy.deepcopy(result["receipt"])
    forged["authority"]["master"]["sha256"] = "0" * 64
    diagnostics = checker(
        root,
        acceptance_path=acceptance_path,
        rows=result["rows"],
        receipt=forged,
    )
    assert any("authority" in item for item in diagnostics)
