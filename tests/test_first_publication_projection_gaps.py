from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.lib.path_io import io_path
from ocd_kernel.projection import native_content
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection.categories import prose
from ocd_kernel.projection.categories.bible import (
    _checker_header as _checker_bible_header,
    _checker_parse as _parse_bible_for_check,
    _checker_validate as _validate_bible_for_check,
    _header as _bible_header,
    _paths as _bible_paths,
    _validate_elements as _validate_bible_elements,
    _read as _read_bible,
)
from ocd_kernel.projection.categories.catechisms import (
    project_accepted_catechisms,
    verify_accepted_catechisms,
    _accepted_local_binding,
)
from ocd_kernel.projection.categories.commentary import (
    _validate_elements as _validate_commentary_elements,
    _paths as _commentary_paths,
    _read_root as _read_commentary_root,
)


ROOT = Path(__file__).resolve().parents[1]


def _native_kinds(value):
    if isinstance(value, dict):
        if isinstance(value.get("kind"), str):
            yield value["kind"]
        for child in value.values():
            yield from _native_kinds(child)
    elif isinstance(value, list):
        for child in value:
            yield from _native_kinds(child)


def _acceptance(work_id: str) -> Path:
    paths = list((ROOT / "library" / "works" / work_id).rglob("acceptance.json"))
    assert len(paths) == 1
    return paths[0]


def _selected_acceptance(item_id: str) -> Path:
    selection = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts/first-publication-20261009-v2/selection.json"
    document = json.loads(selection.read_text(encoding="utf-8"))
    item = next(entry for entry in document["items"] if entry["item_id"] == item_id)
    return ROOT / item["acceptance_path"]


def test_retained_bible_links_are_distinct_and_unmapped_tables_fail_closed() -> None:
    acceptance = _acceptance("brenton-septuagint")
    master = acceptance.with_name("master.tei.xml")
    root, _ = _read_bible(master)
    produced = _bible_header(root)
    checked_root, _, paths, parents = _parse_bible_for_check(master)
    checked = _checker_bible_header(checked_root, paths)

    for header in (produced, checked):
        assert header["source_url"] == "https://ebible.org/eng-Brenton/"
        assert header["package_url"] == "https://ebible.org/Scriptures/eng-Brenton_usfm.zip"
    with pytest.raises(PipelineError, match="table"):
        _validate_bible_elements(root, _bible_paths(root))
    with pytest.raises(PipelineError, match="table"):
        _validate_bible_for_check(checked_root, paths, parents)


def test_retained_catechism_publisher_header_projects_and_verifies() -> None:
    catechism = _selected_acceptance(
        "westminster-shorter-catechism--westminster-shorter-catechism-creeds-json-retained"
    )
    result = project_accepted_catechisms(ROOT, acceptance_path=catechism)
    assert verify_accepted_catechisms(
        ROOT, acceptance_path=catechism, rows=result["rows"], receipt=result["receipt"]
    ) == []


def test_keil_body_metadata_stays_closed_until_its_text_scopes_are_projected() -> None:
    acceptance = _acceptance("keil-delitzsch")
    root, _ = _read_commentary_root(acceptance.with_name("master.tei.xml"))
    with pytest.raises(PipelineError, match="note/@space"):
        _validate_commentary_elements(root, _commentary_paths(root))


def test_recognized_xml_model_hint_is_accounted_and_unknown_pis_are_rejected() -> None:
    raw = (
        b'<?xml version="1.0"?>'
        b'<?xml-model href="https://raw.githubusercontent.com/PatristicTextArchive/Schema/master/tei-pta.rng" '
        b'schematypens="http://relaxng.org/ns/structure/1.0"?>'
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"/>'
    )
    comments, instructions = native_documents._source_document_marker_ledger(raw)
    assert comments == []
    assert instructions == [{
        "parent_path": "#document",
        "child_index": 0,
        "target": "xml-model",
        "text": (
            'href="https://raw.githubusercontent.com/PatristicTextArchive/Schema/master/tei-pta.rng" '
            'schematypens="http://relaxng.org/ns/structure/1.0"'
        ),
        "tail": "",
        "disposition": "private-xml-model-hint",
    }]
    with pytest.raises(PipelineError, match="processing instruction"):
        native_documents._source_document_marker_ledger(
            raw.replace(b"tei-pta.rng", b"unreviewed.rng")
        )


def test_accepted_zip_bibles_keep_package_urls_out_of_source_urls() -> None:
    package_only = (
        "eng-web-c--eng-web-c-electronic-2020",
        "engwebpb--engwebpb-electronic-2020",
        "engwmb--engwmb-electronic-2022",
        "geneva-bible-1599--ebible-enggnv-usfm",
        "isaac-leeser-tanakh--ebible-englee-leeser-1853",
        "original-douay-rheims--original-douay-rheims-electronic",
        "tyndale-new-testament-1534--engtnt-ebible-electronic-1534",
    )
    for item_id in package_only:
        master = _selected_acceptance(item_id).with_name("master.tei.xml")
        root, _ = _read_bible(master)
        produced = _bible_header(root)
        checked_root, _, paths, _ = _parse_bible_for_check(master)
        checked = _checker_bible_header(checked_root, paths)
        assert produced == checked
        assert produced["source_url"] is None
        assert produced["package_url"].casefold().endswith(".zip")

    master = _selected_acceptance(
        "anderson-1864-new-testament--anderson-1864-new-testament-electronic"
    ).with_name("master.tei.xml")
    root, _ = _read_bible(master)
    produced = _bible_header(root)
    checked_root, _, paths, _ = _parse_bible_for_check(master)
    checked = _checker_bible_header(checked_root, paths)
    assert produced == checked
    assert produced["source_url"] == produced["package_url"]
    assert not produced["source_url"].casefold().endswith(".zip")


def test_provider_source_ref_cannot_point_to_a_zip_package() -> None:
    master = _acceptance("brenton-septuagint").with_name("master.tei.xml")
    root, _ = _read_bible(master)
    source_desc = next(node for node in root.iter() if node.tag.endswith("sourceDesc"))
    next(node for node in source_desc.iter() if node.tag.endswith("ref")).set(
        "target", "https://example.org/source.zip"
    )
    with pytest.raises(PipelineError, match="provider ref points to a ZIP"):
        _bible_header(root)

    checked_root, _, paths, _ = _parse_bible_for_check(master)
    source_desc = checked_root.xpath(".//*[local-name()='sourceDesc']")[0]
    source_desc.xpath(".//*[local-name()='ref']")[0].set(
        "target", "https://example.org/source.zip"
    )
    with pytest.raises(PipelineError, match="provider ref points to a ZIP"):
        _checker_bible_header(checked_root, paths)


@pytest.mark.parametrize(("item_id", "comment_count"), [
    ("amphilochius-epistula-synodalis--pta-ef861ab3-amphilochius-epistula-synodalis", 2),
    ("anonymous-vita-sancti-cononis-bidanae--pta-ef861ab3-vita-sancti-cononis-bidanae-grc1", 38),
    ("hesychius-commentarius-magnus-in-psalmos--pta-ef861ab3-hesychius-commentarius-magnus-in-psalmos", 67),
    ("severian-de-fide-et-lege-naturae--pta-ef861ab3-severian-de-fide-et-lege-naturae", 6),
])
def test_pta_editorial_comments_are_private_and_accounted(item_id: str, comment_count: int) -> None:
    acceptance = _selected_acceptance(item_id)
    result = native_documents.project_accepted_document(
        ROOT, acceptance_path=acceptance, category="prose"
    )

    comments = result["receipt"]["source_comments"]
    assert len(comments) == comment_count
    assert {comment["disposition"] for comment in comments} == {
        "private-pta-editorial-comment"
    }
    assert native_documents.verify_accepted_document(
        ROOT,
        acceptance_path=acceptance,
        rows=result["rows"],
        receipt=result["receipt"],
        category="prose",
    ) == []
    if item_id == "anonymous-vita-sancti-cononis-bidanae--pta-ef861ab3-vita-sancti-cononis-bidanae-grc1":
        assert sum(kind == "original-text" for row in result["rows"]
                   for kind in _native_kinds(row["structure"])) == 2
        assert result["receipt"]["projection_profile"] == native_content.PTA_ANONYMOUS_VITA_PROFILE


def test_methodius_accepted_header_projects_and_verifies() -> None:
    acceptance = _selected_acceptance(
        "methodius-symposium--bonwetsch-1917-first1k-opp-grc1"
    )
    result = native_documents.project_accepted_document(
        ROOT, acceptance_path=acceptance, category="prose"
    )
    assert native_documents.verify_accepted_document(
        ROOT,
        acceptance_path=acceptance,
        rows=result["rows"],
        receipt=result["receipt"],
        category="prose",
    ) == []


def test_john_of_ephesus_l812_projects_and_verifies() -> None:
    acceptance = _selected_acceptance(
        "john-of-ephesus-ecclesiastical-history--pta-ef861ab3-john-ecclesiastical-history-part-iii"
    )
    result = prose.project_accepted_prose(ROOT, acceptance_path=acceptance)
    assert prose.verify_accepted_prose(
        ROOT, acceptance_path=acceptance, rows=result["rows"], receipt=result["receipt"]
    ) == []


def test_critical_apparatus_keeps_variants_structured_and_renders_only_lemma() -> None:
    from xml.etree import ElementTree as ET

    from ocd_kernel.projection.native_content import project_content, readable_content
    from ocd_kernel.projection.native_content_check import observe_content, verify_content

    source = (
        b'<p xmlns="http://www.tei-c.org/ns/1.0">Before '
        b'<w xml:id="source-word">word</w> '
        b'<app type="variant" xml:id="app-1">'
        b'<lem wit="#A">base text</lem><rdg wit="#B">alternate text</rdg>'
        b'</app> <gap reason="missing" unit="word" quantity="2"/> '
        b'<gap reason="damage" unit="character" quantity="2"/> after.</p>'
    )
    content = project_content(ET.fromstring(source))
    observed, expected_text = observe_content(source)
    apparatus = next(node for node in content["content"]
                     if node.get("kind") == "critical-apparatus")

    assert content == observed
    assert readable_content(content) == expected_text == (
        "Before word base text [missing: 2 words] [damage: 2 characters] after."
    )
    assert [node["attributes"]["source_element"] for node in apparatus["content"]] == [
        "lem", "rdg"
    ]
    assert apparatus["content"][0]["attributes"]["source_attributes"] == {"wit": "#A"}
    assert apparatus["content"][1]["attributes"]["source_attributes"] == {"wit": "#B"}
    assert verify_content(source, content, expected_text) == []


def test_accepted_binding_normalizes_long_windows_paths_before_containment(tmp_path: Path) -> None:
    root = tmp_path / "library-root"
    relative = Path(*(f"segment-{index}-{'x' * 48}" for index in range(4))) / "acquisition.json"
    path = root / relative
    io_path(path).parent.mkdir(parents=True, exist_ok=True)
    io_path(path).write_text("{}", encoding="utf-8")

    assert len(str(path)) > 260
    binding = _accepted_local_binding(root, path, field="acquisition")
    assert binding["path"] == relative.as_posix()

