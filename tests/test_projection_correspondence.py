"""Independent real-source examples plus synthetic isolated corruption controls."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import canonical_row_bytes, project_document, project_accepted
from ocd_kernel.projection.receipt import build_correspondence_receipt
from ocd_kernel.release.verify import verify_document, verify_accepted

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/library-pipeline"
VARIATION = FIXTURES / "correspondence/variation.tei.xml"
MASTER = next((FIXTURES / "library").rglob("master.tei.xml"))
CONTEXT = dict(identity={"work_id": "work", "textual_form_id": "form", "edition_id": "edition"}, language="en", representation_revision="test-v1", edition_title="Example edition")


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("p")


def produce(path=VARIATION, **kwargs):
    context = dict(CONTEXT, **kwargs)
    projection = project_document(path, **context)
    receipt = build_correspondence_receipt(projection, identity=context["identity"])
    return projection["rows"], receipt, context


def write_minimal_tei(tmp_path, text_markup, name="synthetic.tei.xml"):
    """Write a self-contained TEI document for one isolated correspondence case."""

    path = tmp_path / name
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader/>
  <text>"""
        + text_markup
        + """</text>
</TEI>
""",
        encoding="utf-8",
    )
    return path


def test_hand_derived_variation_and_private_boundary():
    rows, receipt, context = produce()
    assert [r["text"] for r in rows] == ["Alpha beta gamma.1 2", "cooperate again ¹⁄₂.", "Amen."]
    # The excluded title-page paragraph is still a native carrier occurrence;
    # public IDs therefore remain stable when the projection is scoped.
    assert [r["record_id"] for r in rows] == [
        "edition:unit-000002",
        "edition:unit-000003",
        "edition:unit-000004",
    ]
    assert rows[0]["notes"] == [{"text": "First note. Second paragraph.", "place": "foot", "label": "1"}]
    assert rows[1]["locator"] == {
        "kind": "paragraph",
        "text_part": "body",
        "part_titles": [],
        "divisions": [
            {"order": 1, "type": "chapter", "titles": ["A Heading"]},
            {"order": 1, "type": "subsection", "titles": ["Subdivision"]},
        ],
        "paragraph": 1,
    }
    assert rows[2]["language"] == "la"
    assert rows[0]["references"][1]["target_record_id"] == "edition:unit-000004"
    assert rows[0]["references"][0]["target_note"] == 1
    assert rows[0]["references"][0]["source_note"] is None
    public = canonical_row_bytes(rows).decode()
    for secret in ("xml_id", "tei_path", "original_target", "C:/private", "Private review person", "Printed title"):
        assert secret not in public
    assert receipt["exclusions"] and receipt["warnings"]
    assert verify_document(VARIATION, rows, receipt, **context) == []


def test_f1_and_f6_locator_distinguishes_parts_and_retains_part_headings(tmp_path):
    path = write_minimal_tei(
        tmp_path,
        """
<front><head>Preface</head><p xml:id="front-p">Preface paragraph.</p></front>
<body><head>Body</head><p xml:id="body-p">Body paragraph.</p></body>
<back><head>Appendix</head><p xml:id="back-p">Appendix paragraph.</p></back>
""",
        "parts.tei.xml",
    )
    rows, receipt, context = produce(path)
    assert [row["text"] for row in rows] == [
        "Preface paragraph.",
        "Body paragraph.",
        "Appendix paragraph.",
    ]
    assert [row["locator"]["text_part"] for row in rows] == ["front", "body", "back"]
    assert [row["locator"]["part_titles"] for row in rows] == [
        ["Preface"],
        ["Body"],
        ["Appendix"],
    ]
    assert not any(item["reason"] == "excluded-heading" for item in receipt["exclusions"])
    assert verify_document(path, rows, receipt, **context) == []


def test_f4_and_f7_locator_pairs_division_order_type_and_titles(tmp_path):
    path = write_minimal_tei(
        tmp_path,
        """
<body>
  <div type="chapter" xml:id="chapter-one">
    <head>Book One</head><head>Of Faith</head>
    <div type="section" xml:id="section-one">
      <head>Chapter I</head><p xml:id="nested-p">Nested paragraph.</p>
    </div>
  </div>
</body>
""",
        "divisions.tei.xml",
    )
    rows, receipt, context = produce(path)
    assert rows[0]["locator"] == {
        "kind": "paragraph",
        "text_part": "body",
        "part_titles": [],
        "divisions": [
            {"order": 1, "type": "chapter", "titles": ["Book One", "Of Faith"]},
            {"order": 1, "type": "section", "titles": ["Chapter I"]},
        ],
        "paragraph": 1,
    }
    assert verify_document(path, rows, receipt, **context) == []


def test_f5_record_ids_use_complete_source_carrier_order(tmp_path):
    full_rows, _full_receipt, full_context = produce()
    content = VARIATION.read_text(encoding="utf-8").replace(
        '<p xml:id="p1">',
        '<div type="section" xml:id="excerpt"><p xml:id="p1">',
        1,
    ).replace(
        '</p>\n<div type="subsection"',
        '</p></div>\n<div type="subsection"',
        1,
    )
    path = tmp_path / "scoped.tei.xml"
    path.write_text(content, encoding="utf-8")
    scoped_rows, scoped_receipt, scoped_context = produce(path, scope_id="excerpt")
    assert len(scoped_rows) == 1
    assert scoped_rows[0]["record_id"] == full_rows[0]["record_id"] == "edition:unit-000002"
    assert scoped_rows[0]["sequence"] == 1
    assert verify_document(path, scoped_rows, scoped_receipt, **scoped_context) == []
    assert verify_document(VARIATION, full_rows, _full_receipt, **full_context) == []


@pytest.mark.parametrize("omitted", ["note", "pb", "anchor"])
def test_f2_omitted_inline_boundary_cannot_join_words(tmp_path, omitted):
    insertion = {
        "note": '<note xml:id="join-note" place="foot" n="9">omitted</note>',
        "pb": '<pb n="join-page"/>',
        "anchor": '<anchor xml:id="join-anchor"/>',
    }[omitted]
    content = VARIATION.read_text(encoding="utf-8").replace(
        "Alpha ", f"Alpha{insertion}beta ", 1
    )
    path = tmp_path / f"ambiguous-{omitted}.tei.xml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(PipelineError, match="ambiguous"):
        produce(path)

    rows, receipt, context = produce()
    receipt["master_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    diagnostics = verify_document(path, rows, receipt, **context)
    assert any(
        re.search(r"unsupported-visible: omitted inline element creates an ambiguous alphanumeric boundary", error)
        for error in diagnostics
    ), diagnostics


@pytest.mark.parametrize(
    "omitted_pair",
    [("note", "pb"), ("pb", "anchor"), ("anchor", "note")],
)
def test_f2_consecutive_omitted_inline_boundaries_cannot_join_words(
    tmp_path, omitted_pair
):
    snippets = {
        "note": '<note xml:id="join-note-pair" place="foot" n="10">omitted</note>',
        "pb": '<pb n="join-page-pair"/>',
        "anchor": '<anchor xml:id="join-anchor-pair"/>',
    }
    insertion = "".join(snippets[name] for name in omitted_pair)
    content = VARIATION.read_text(encoding="utf-8").replace(
        "Alpha ", f"Alpha{insertion}beta ", 1
    )
    path = tmp_path / f"ambiguous-{'-'.join(omitted_pair)}.tei.xml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(PipelineError, match="ambiguous"):
        produce(path)

    rows, receipt, context = produce()
    receipt["master_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    diagnostics = verify_document(path, rows, receipt, **context)
    assert any(
        "unsupported-visible: omitted inline element creates an ambiguous alphanumeric boundary" in error
        for error in diagnostics
    ), diagnostics


def test_f3_unsupported_script_character_fails_visibly(tmp_path):
    path = write_minimal_tei(
        tmp_path,
        '<body><p xml:id="script-p">Value <hi rend="superscript">x</hi>.</p></body>',
        "unsupported-script.tei.xml",
    )
    with pytest.raises(PipelineError, match="unsupported.*script"):
        produce(path)

    rows, receipt, context = produce()
    receipt["master_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    diagnostics = verify_document(path, rows, receipt, **context)
    assert any(
        "unsupported-visible: unsupported superscript script character" in error
        for error in diagnostics
    ), diagnostics


def test_f3_nested_script_styles_fail_visibly(tmp_path):
    path = write_minimal_tei(
        tmp_path,
        '<body><p xml:id="nested-script-p">Value <hi rend="superscript"><hi rend="subscript">1</hi></hi>.</p></body>',
        "nested-script.tei.xml",
    )
    with pytest.raises(PipelineError, match="nested.*script"):
        produce(path)

    rows, receipt, context = produce()
    receipt["master_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    diagnostics = verify_document(path, rows, receipt, **context)
    assert any(
        "unsupported-visible: nested super/subscript spans" in error
        for error in diagnostics
    ), diagnostics


def test_real_source_inventory_is_independent_of_tei_traversal():
    rows, receipt, context = produce(MASTER)
    source_path = FIXTURES / "retained/npnf204.vii.ii.i.thml.xml"
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == "d16a6d825621cde9b93c5ed54489521895b9b9e44098b38bd61c437b927faafa"
    source = etree.parse(str(source_path))
    paragraphs = source.xpath("/div3/p")
    # Hand-inspected source has four direct paragraphs, not six: two other p
    # elements are bodies of notes on the fourth paragraph.
    assert len(paragraphs) == len(rows) == 4
    assert rows[0]["text"] == "On the Incarnation of the Word."
    assert rows[1]["text"] == "————————————"
    assert len(rows[3]["notes"]) == 2
    assert "Macarius (worthy of that name)" in rows[3]["text"]
    assert "See Contra Gentes" not in rows[3]["text"]
    for source_p, row in zip(paragraphs, rows):
        # Source-native XPath selects text by note ancestry. Neither the TEI
        # producer nor its checker supplies this selection or its boundaries.
        pieces = source_p.xpath(".//text()[not(ancestor::note)]")
        assert " ".join("".join(pieces).split()) == row["text"]
    assert verify_document(MASTER, rows, receipt, **context) == []


@pytest.mark.parametrize("change", ["omit", "duplicate", "reorder", "text", "locator", "identity", "note", "reference", "target-note", "source-note", "boolean-sequence", "private-top", "private-nested"])
def test_internally_consistent_forged_receipt_cannot_grade_its_own_rows(change):
    rows, receipt, context = produce()
    if change == "omit": rows.pop()
    elif change == "duplicate": rows.append(copy.deepcopy(rows[0]))
    elif change == "reorder": rows.reverse()
    elif change == "text": rows[0]["text"] = "Invented text"
    elif change == "locator": rows[0]["locator"]["paragraph"] = 99
    elif change == "identity": rows[0]["work_id"] = "other"
    elif change == "note": rows[0]["notes"] = []
    elif change == "reference": rows[0]["references"][0]["target_record_id"] = "edition:unit-000003"
    elif change == "target-note": rows[0]["references"][0]["target_note"] = 2
    elif change == "source-note": rows[0]["references"][0]["source_note"] = 1
    elif change == "boolean-sequence": rows[0]["sequence"] = True
    elif change == "private-top": rows[0]["assessment"] = "private"
    else: rows[0]["provenance"]["source_sha256"] = "a" * 64
    receipt["output_sha256"] = hashlib.sha256(canonical_row_bytes(rows)).hexdigest()
    receipt["row_count"] = len(rows)
    for anchor, row in zip(receipt["anchors"], rows):
        anchor["text_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    receipt["independent_check"] = {"status": "pass", "errors": []}
    assert verify_document(VARIATION, rows, receipt, **context)


@pytest.mark.parametrize("field", ["inventory", "anchors", "references", "warnings", "exclusions"])
def test_omitted_accounting_rejected(field):
    rows, receipt, context = produce()
    receipt[field].pop()
    assert verify_document(VARIATION, rows, receipt, **context)


def test_excerpt_preserves_original_target_and_scope(tmp_path):
    content = VARIATION.read_text(encoding="utf-8").replace('<ref type="note" target="#n1">1</ref>', '<ref type="note" target="#n2">1</ref>')
    # Scope is the chapter containing the row; use a new division enclosing p1.
    content = content.replace('<p xml:id="p1">', '<div type="section" xml:id="excerpt"><p xml:id="p1">').replace('</p>\n<div type="subsection"', '</p></div>\n<div type="subsection"')
    path = tmp_path / "excerpt.xml"
    path.write_text(content, encoding="utf-8")
    rows, receipt, context = produce(path, scope_id="excerpt")
    assert len(rows) == 1
    assert all(r["resolution"] == "outside-projection" for r in rows[0]["references"])
    assert receipt["references"][0]["original_target"] == "#n2"
    assert verify_document(path, rows, receipt, **context) == []


def test_empty_explicit_scope_cannot_expand_to_whole_document():
    with pytest.raises(PipelineError, match="scope"):
        produce(scope_id="")


@pytest.mark.parametrize("old,new,reason,diagnostic", [
    ('target="#n1"', 'target="#missing"', "unresolved", "unresolved complete-TEI target"),
    ('target="#n1"', 'target="#p1"', "note", "note pointer target is not a note"),
    ('target="#n1"', 'target="https://example.com/note"', "unsupported", "note references require @target with a complete local target"),
    ('target="#n1"', 'target="" cRef="#n1"', "unsupported", "reference requires exactly one of @target or @cRef"),
    ('<p xml:id="p1">', '<p xml:id="p1" style="red">', "unsupported", "unsupported-visible: p/@style"),
    ('<p xml:id="p1">', '<p xml:id="p1" rend="rubric">', "unsupported", "unsupported-visible: p/@rend"),
    ('<p xml:id="p1">', '<p xml:id="p1" ana="se:label">', "unsupported", "unsupported-visible: p/@ana"),
    ('type="chapter"', 'type="sermon"', "unsupported", "category semantics sermon"),
    ('<p xml:id="p1">', '<p xml:id="p2">', "duplicate", "invalid TEI: ID p2 already defined"),
    ('<p xml:id="p1">', '<p xml:id="">', "empty xml:id", "invalid TEI: xml:id"),
    ('xml:lang="en"', 'xml:lang=""', "xml:lang", "invalid xml:lang"),
    ('<body>', '<body>unwrapped', "unsupported", "unwrapped container text"),
    ('<body>', '<body><!-- omitted annotation -->', "unsupported", "XML comments are not mapped"),
    ('<body>', '<body><?private note?>', "unsupported", "processing instructions are not mapped"),
    ('<p xml:id="p1">', '<text><body><p>Hidden block.</p></body></text><p xml:id="p1">', "unsupported", "exactly one text required"),
    ('<p xml:id="p1">', '<body><p>Hidden block.</p></body><p xml:id="p1">', "unsupported", "nested text container"),
    ('<p xml:id="p1">', '<table><row><cell>lost</cell></row></table><p xml:id="p1">', "unsupported", "unsupported-visible: table"),
])
def test_unsupported_or_invalid_tei_fails_before_output(tmp_path, old, new, reason, diagnostic):
    path = tmp_path / "bad.xml"
    path.write_text(VARIATION.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    with pytest.raises(PipelineError, match=reason):
        produce(path)
    rows, receipt, context = produce()
    receipt["master_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    errors = verify_document(path, rows, receipt, **context)
    assert any(diagnostic in error for error in errors), errors


def test_f10_new_division_vocabulary_requires_an_explicit_policy_decision(tmp_path, monkeypatch):
    rows, receipt, context = produce()
    controlled_path = (ROOT / "schemas/v2/tei/controlled-values.json").resolve()
    original_read_text = Path.read_text

    def read_text_with_new_category(self, *args, **kwargs):
        value = original_read_text(self, *args, **kwargs)
        if self.resolve() != controlled_path:
            return value
        controlled = json.loads(value)
        division_context = next(
            item for item in controlled["contexts"] if item["context"] == "div/@type"
        )
        division_context["values"].append("new-category")
        return json.dumps(controlled)

    monkeypatch.setattr(Path, "read_text", read_text_with_new_category)
    with pytest.raises(PipelineError, match="projection policy does not exhaustively classify"):
        produce()
    errors = verify_document(VARIATION, rows, receipt, **context)
    assert any(
        "projection policy" in error and "classif" in error for error in errors
    ), errors


def test_f11_local_c_ref_is_not_an_xml_id_pointer(tmp_path):
    path = tmp_path / "local-cref.tei.xml"
    path.write_text(
        VARIATION.read_text(encoding="utf-8").replace(
            'target="#n1"', 'cRef="#n1"', 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(PipelineError, match="cRef|target"):
        produce(path)
    rows, receipt, context = produce()
    receipt["master_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    errors = verify_document(path, rows, receipt, **context)
    assert any("cRef cannot identify a local TEI target" in error for error in errors), errors


@pytest.mark.parametrize("name,expected", [
    ("stokes-subscript", "12¹⁄₂"), ("eusebius-subscript", "271₁.₂"),
    ("kempis-title-page", None),
    ("kempis-half-title-page", None), ("baxter-subsection", None),
])
def test_real_tei003_examples(name, expected):
    path = ROOT / f"tests/fixtures/tei-conformance/positive/{name}.tei.xml"
    rows, receipt, context = produce(path)
    if expected: assert expected in rows[0]["text"]
    else: assert not rows
    assert verify_document(path, rows, receipt, **context) == []


_CONFORMANCE_ROOT = ROOT / "tests/fixtures/tei-conformance"
_REAL_FIXTURES = json.loads((_CONFORMANCE_ROOT / "manifest.json").read_text(encoding="utf-8"))["fixtures"]
_SUPPORTED_EXCERPTS = {"baxter-subsection", "eusebius-subscript", "greenleaf-small-caps", "kempis-half-title-page", "kempis-title-page", "stokes-subscript", "underhill-half-title-page", "underhill-title-page"}


@pytest.mark.parametrize("fixture", _REAL_FIXTURES, ids=lambda f: f["id"])
def test_every_tei003_fixture_has_deliberate_supported_or_visible_failure(fixture):
    path = _CONFORMANCE_ROOT / fixture["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == fixture["sha256"]
    if fixture["id"] in _SUPPORTED_EXCERPTS:
        rows, receipt, context = produce(path)
        assert verify_document(path, rows, receipt, **context) == []
        if not rows:
            assert receipt["exclusions"]  # No false claim of projected headings.
    else:
        with pytest.raises(PipelineError, match="unsupported-visible|unresolved complete-TEI"):
            produce(path)
        rows, receipt, context = produce()
        receipt["master_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        errors = verify_document(path, rows, receipt, **context)
        assert any(
            error.startswith("unsupported-visible:")
            or error.startswith("unresolved complete-TEI target:")
            for error in errors
        ), errors


def test_second_process_reproduces_exact_result():
    rows, receipt, _ = produce()
    code = "from tests.test_projection_correspondence import produce; import json; r,s,_=produce(); print(json.dumps([r,s],sort_keys=True))"
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout) == [rows, receipt]


def test_real_acceptance_boundary_in_temporary_fixture(tmp_path):
    from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance
    from ocd_kernel.tei.acceptance import promote_accepted_master
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    with pytest.raises(PipelineError, match="promoted"):
        project_accepted(root, acceptance_path=path)
    destination = tmp_path / "promoted"
    result = promote_accepted_master(root, acceptance_path=path, destination=destination)
    projection = project_accepted(destination, acceptance_path=result.acceptance_path)
    identity = {k: record["identity"][k] for k in CONTEXT["identity"]}
    receipt = build_correspondence_receipt(projection, identity=identity)
    assert verify_accepted(destination, acceptance_path=result.acceptance_path, rows=projection["rows"], receipt=receipt) == []
    receipt["authority"]["acceptance"]["sha256"] = "0" * 64
    assert verify_accepted(destination, acceptance_path=result.acceptance_path, rows=projection["rows"], receipt=receipt)
    master = destination / record["promotion"]["master"]["path"]
    master.write_bytes(master.read_bytes().replace(b"</body>", b"<p>Unaccepted addition.</p></body>"))
    with pytest.raises(PipelineError):
        project_accepted(destination, acceptance_path=result.acceptance_path)
    assert verify_accepted(destination, acceptance_path=result.acceptance_path, rows=projection["rows"], receipt=receipt)


def test_doctype_rejected_in_utf16(tmp_path):
    path = tmp_path / "entity.xml"
    text = VARIATION.read_text(encoding="utf-8").replace('<?xml version="1.0" encoding="utf-8"?>', '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE TEI [<!ENTITY hidden "invented">]>')
    path.write_bytes(text.encode("utf-16"))
    with pytest.raises(PipelineError, match="DTD"):
        produce(path)
    rows, receipt, context = produce()
    assert verify_document(path, rows, receipt, **context)


def test_two_note_targets_on_one_row_remain_distinct(tmp_path):
    path = tmp_path / "two-notes.xml"
    text = VARIATION.read_text(encoding="utf-8").replace(' gamma.', '<note xml:id="n3" place="foot">Third.</note> gamma.').replace('target="#n2">2', 'target="#n3">2')
    path.write_text(text, encoding="utf-8")
    rows, receipt, context = produce(path)
    assert [r["target_note"] for r in rows[0]["references"]] == [1, 2]
    assert verify_document(path, rows, receipt, **context) == []


def test_empty_source_occurrence_is_retained_with_explicit_warning(tmp_path):
    path = tmp_path / "empty.xml"
    path.write_text(VARIATION.read_text(encoding="utf-8").replace('</body>', '<p> </p></body>'), encoding="utf-8")
    rows, receipt, context = produce(path)
    assert rows[-1]["text"] == ""
    assert any(w["reason"] == "empty-native-paragraph" for w in receipt["warnings"])
    assert verify_document(path, rows, receipt, **context) == []


def test_duplicate_equal_acquisition_ids_cannot_enter_projection(tmp_path):
    from tests.test_tei_acceptance import _fixture_root, _master_path, _write_valid_acceptance
    from ocd_kernel.tei.acceptance import promote_accepted_master
    root = _fixture_root(tmp_path)
    master = _master_path(root)
    token = '<idno type="acquisition_id">ccel-npnf204-retained-xml</idno>'
    master.write_text(master.read_text(encoding="utf-8").replace(token, token + token), encoding="utf-8")
    acceptance_path, _ = _write_valid_acceptance(root)
    destination = tmp_path / "promoted"
    result = promote_accepted_master(root, acceptance_path=acceptance_path, destination=destination)
    with pytest.raises(PipelineError, match="exactly one"):
        project_accepted(destination, acceptance_path=result.acceptance_path)
    rows, receipt, _ = produce()
    assert verify_accepted(destination, acceptance_path=result.acceptance_path, rows=rows, receipt=receipt)


def test_excerpt_accounts_for_ancestor_headings_used_in_its_locator():
    rows, receipt, context = produce(scope_id="selected")
    assert rows[0]["locator"]["divisions"][0]["titles"] == ["A Heading"]
    parent_heading = "/TEI[1]/text[1]/body[1]/div[1]/head[1]"
    entries = [item for item in receipt["inventory"] if item["tei_path"].startswith(parent_heading)]
    assert entries and all(item["disposition"] == "locator-heading" for item in entries)
    assert not any(item["tei_path"].startswith(parent_heading) for item in receipt["exclusions"])
    assert verify_document(VARIATION, rows, receipt, **context) == []


def test_external_reference_target_survives_public_projection(tmp_path, monkeypatch):
    path = write_minimal_tei(tmp_path, '<body><p xml:id="p1">Read <ref cRef="John.3.16-18">John 3:16–18</ref>.</p></body>')
    rows, receipt, context = produce(path)
    assert rows[0]['references'][0]['source_target'] == 'John.3.16-18'
    assert rows[0]['references'][0]['scripture']['normalized'] == 'John.3.16-John.3.18'
    import ocd_kernel.projection.envelope as producer
    def forbidden(*args, **kwargs):
        raise AssertionError('checker called reference producer')
    monkeypatch.setattr(producer, 'normalize_reference_record', forbidden)
    forged = copy.deepcopy(receipt)
    forged['book_codes_sha256'] = '0' * 64
    assert any('book_codes_sha256' in error for error in verify_document(path, rows, forged, **context))
    assert verify_document(path, rows, receipt, **context) == []
    rows[0]['references'][0]['source_target'] = 'Gen.1.1'
    assert verify_document(path, rows, receipt, **context)
