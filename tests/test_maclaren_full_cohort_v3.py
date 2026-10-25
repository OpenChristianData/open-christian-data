from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei import maclaren_expositions_structure_map_v3 as map_v3
from build.tei import maclaren_expositions_structured_oracle_v3 as oracle_v3
from build.tei import maclaren_expositions_structured_v3 as producer_v3
from build.tools import project_maclaren_expositions_v3 as publication_v3


ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "sources/sermons/maclaren-expositions/full-cohort-v3/source-structure-map.json"
CANDIDATE = ROOT / "sources/sermons/maclaren-expositions/full-cohort-v3/content.tei.xml"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


@pytest.fixture(scope="module")
def candidate_bytes() -> bytes:
    return CANDIDATE.read_bytes()


def _tree(candidate_bytes: bytes) -> etree._Element:
    return etree.fromstring(candidate_bytes, etree.XMLParser(huge_tree=True))


def _bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _line(root: etree._Element, pg: str, number: int) -> etree._Element:
    result = root.xpath(
        f"//*[@xml:id='pg{pg}-line-{number:06d}']",
        namespaces={"xml": XML},
    )
    assert len(result) == 1
    return result[0]


def test_full_cohort_v3_passes_independent_source_oracle(candidate_bytes: bytes) -> None:
    report = oracle_v3.check_candidate(ROOT, candidate_bytes)
    assert report["status"] == "pass"
    assert report["source_members"] == 15
    assert report["source_lines"] == 339526
    assert report["source_parts"] == 26
    assert report["mapped_markers"] == 1444
    assert report["exposition_heads"] == 1386
    assert report["book_section_heads"] == 43
    assert report["internal_subsections"] == 14
    assert report["verse_column_labels"] == 1
    assert report["nonexact_toc_title_cases_with_adjacent_epigraphs"] == 28


def test_full_cohort_v3_reproduces_exact_map_and_candidate(candidate_bytes: bytes) -> None:
    mapped = map_v3.inventory(ROOT)
    mapped_text = json.dumps(mapped, ensure_ascii=False, indent=2) + "\n"
    assert mapped_text == MAP.read_text(encoding="utf-8")
    assert producer_v3.render(ROOT) == candidate_bytes


def test_oracle_rejects_an_omitted_source_line(candidate_bytes: bytes) -> None:
    root = _tree(candidate_bytes)
    carrier = _line(root, "7069", 300)
    carrier.getparent().remove(carrier)
    with pytest.raises(ValueError, match="omitted, duplicated, or reordered"):
        oracle_v3.check_candidate(ROOT, _bytes(root))


def test_oracle_rejects_a_duplicated_source_line(candidate_bytes: bytes) -> None:
    root = _tree(candidate_bytes)
    carrier = _line(root, "8381", 4499)
    carrier.addnext(deepcopy(carrier))
    with pytest.raises((ValueError, etree.XMLSyntaxError)):
        oracle_v3.check_candidate(ROOT, _bytes(root))


def test_oracle_rejects_correction_of_a_retained_title_typo(candidate_bytes: bytes) -> None:
    root = _tree(candidate_bytes)
    carrier = _line(root, "7069", 19333)
    assert carrier.text == "THE OLD STORE AN THE NEW"
    carrier.text = "THE OLD STORE AND THE NEW"
    with pytest.raises(ValueError, match="text or carrier changed"):
        oracle_v3.check_candidate(ROOT, _bytes(root))


def test_oracle_rejects_detached_nonexact_title_epigraph(candidate_bytes: bytes) -> None:
    root = _tree(candidate_bytes)
    carrier = _line(root, "8381", 4499)
    paragraph = carrier.getparent()
    exposition = paragraph.getparent()
    assert exposition.get("type") == "exposition"
    nested = etree.Element(
        f"{{{TEI}}}div",
        {"type": "exposition", "n": "nested-mutation", f"{{{XML}}}id": "epigraph-attachment-mutation"},
    )
    exposition.insert(exposition.index(paragraph), nested)
    for sibling in list(exposition)[exposition.index(nested) + 1:]:
        nested.append(sibling)
    with pytest.raises(ValueError, match="lost its adjacent scripture epigraph"):
        oracle_v3.check_candidate(ROOT, _bytes(root))


def test_publication_projection_view_is_exact_and_fails_closed_on_remaining_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ocd_kernel.projection.categories import maclaren_native

    # Exercise the current generic profile; the accepted native route is
    # exercised separately by test_maclaren_native.py.
    monkeypatch.setattr(maclaren_native, "route", lambda context: False)
    result = publication_v3.attempt(ROOT)
    proof = result["projection_view"]
    assert proof["actual_master_sha256"] == publication_v3.EXPECTED_MASTER_SHA256
    assert proof["original_root_xml_id"] == publication_v3.EXPECTED_ROOT_ID
    assert proof["root_id_reference_count"] == 0
    assert proof["only_mutation_is_exact_root_attribute_deletion"]
    assert proof["master_reconstructed_exactly_from_view_and_omitted_bytes"]
    assert proof["text_subtree_unchanged"]
    assert proof["actual_text_subtree_c14n_sha256"] == proof["projection_view_text_subtree_c14n_sha256"]
    assert proof["actual_element_count"] == proof["projection_view_element_count"]
    assert proof["actual_xml_id_count"] == proof["projection_view_xml_id_count"] + 1
    assert result["status"] == "blocked"
    assert result["view_projector_error"] == "PipelineError: unsupported-visible: bibl@xml:id"
    assert result["independent_verifier_errors"] == ["unsupported-visible: attribute"]
    diagnostics = result["profile_diagnostics_after_only_permitted_mutation"]
    assert diagnostics["unknown_attribute_counts"]["bibl@xml:id"] == 15
    assert diagnostics["direct_body_child_count"] == 15
    assert diagnostics["native_sermon_unit_count"] == 0
    assert diagnostics["unsupported_division_type_counts"]["source-member"] == 15
