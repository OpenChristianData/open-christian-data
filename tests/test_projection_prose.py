"""PIPE-012B source-native prose evidence and independent corruption checks."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prose import project_prose_document, project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.envelope import canonical_row_bytes
from ocd_kernel.projection.receipt import build_correspondence_receipt
from ocd_kernel.release.verify import verify_document, verify_accepted

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/library-pipeline/categories/prose"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
CASES = MANIFEST["fixtures"]


def test_native_prose_keeps_complete_divisions_and_rejects_consistent_corruption(tmp_path, monkeypatch):
    from ocd_kernel.projection.categories.native_documents import verify_document as verify_native
    path = tmp_path / 'native.tei.xml'
    path.write_text('''<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>
      <titleStmt><title>Example</title></titleStmt><publicationStmt><p>Test</p></publicationStmt>
      <sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text><front>
      <div type="title_page"><p>Title.</p></div></front><body><div type="part"><head>Part One</head>
      <div type="chapter"><head>Chapter One</head><p>Before <list><item>First</item><item>Second</item></list> after.</p>
      <p>A word<g ref="char:punc">▪</g> and <gap reason="illegible"><desc>UNKNOWN</desc></gap>.</p>
      <lg><l>First line</l><l>Second line</l></lg></div></div></body></text></TEI>''', encoding='utf-8')
    context = dict(identity={'work_id': 'native', 'textual_form_id': 'english', 'edition_id': 'test'},
                   language='en', representation_revision='r1', edition_title='Example')
    result = project_prose_document(path, **context)
    assert len(result['rows']) == 2
    assert [row['locator'] for row in result['rows']] == [
        {'kind': 'native-unit', 'text_part': 'front', 'unit': 1},
        {'kind': 'native-unit', 'text_part': 'body', 'unit': 1}]
    assert 'First\n\nSecond' in result['rows'][1]['text']
    assert 'word▪' in result['rows'][1]['text']
    assert 'UNKNOWN' in result['rows'][1]['text']
    assert result['rows'][1]['text'].endswith('First line\nSecond line')
    import ocd_kernel.projection.native_content as producer
    monkeypatch.setattr(producer, 'project_content', lambda *args: pytest.fail('producer called by checker'))
    monkeypatch.setattr(producer, 'readable_content', lambda *args: pytest.fail('renderer called by checker'))
    assert verify_native(path, result['rows'], result['receipt'], category='prose', **context) == []
    for mutation in ('omit', 'reorder', 'structure', 'locator'):
        rows = copy.deepcopy(result['rows'])
        if mutation == 'omit':
            rows.pop(0)
        elif mutation == 'reorder':
            rows.reverse()
        elif mutation == 'structure':
            rows[1]['structure'][0]['content'].pop()
        else:
            rows[1]['locator']['text_part'] = 'back'
        receipt = copy.deepcopy(result['receipt'])
        receipt['row_count'] = len(rows)
        receipt['output_sha256'] = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        assert verify_native(path, rows, receipt, category='prose', **context), mutation


def test_native_prose_allows_and_validates_document_language_on_tei_root(tmp_path):
    from ocd_kernel.library._common import PipelineError
    from ocd_kernel.projection.categories.native_documents import verify_document as verify_native

    path = tmp_path / 'root-language.tei.xml'
    source = '''<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="en"><teiHeader><fileDesc>
      <titleStmt><title>Example</title></titleStmt><publicationStmt><p>Test</p></publicationStmt>
      <sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text><body>
      <div type="chapter"><head>Chapter</head><p>Words in a <list><item>list</item></list>.</p></div>
      </body></text></TEI>'''
    path.write_text(source, encoding='utf-8')
    context = dict(identity={'work_id': 'native-root-language', 'textual_form_id': 'english', 'edition_id': 'test'},
                   language='en', representation_revision='r1', edition_title='Example')

    projection = project_prose_document(path, **context)
    assert len(projection['rows']) == 1
    assert verify_native(path, projection['rows'], projection['receipt'], category='prose', **context) == []

    path.write_text(source.replace('xml:lang="en"', 'xml:lang="en_US"'), encoding='utf-8')
    with pytest.raises(PipelineError, match='invalid native document language'):
        project_prose_document(path, **context)
    assert verify_native(path, projection['rows'], projection['receipt'], category='prose', **context)


def test_real_table_is_native_structure_with_independent_check(tmp_path):
    from ocd_kernel.projection.categories.native_documents import verify_document as verify_native
    path = tmp_path / 'table.tei.xml'
    path.write_text('''<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>
      <titleStmt><title>Example</title></titleStmt><publicationStmt><p>Test</p></publicationStmt>
      <sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text><body>
      <div type="chapter"><head>Table chapter</head><table><row>
      <cell><p>First</p></cell><cell><p>Second</p></cell>
      </row></table></div></body></text></TEI>''', encoding='utf-8')
    context = dict(identity={'work_id': 'native', 'textual_form_id': 'english', 'edition_id': 'table'},
                   language='en', representation_revision='r1', edition_title='Example')
    result = project_prose_document(path, **context)
    assert result['rows'][0]['structure'][0]['content'][-1]['kind'] == 'table'
    assert 'First' in result['rows'][0]['text'] and 'Second' in result['rows'][0]['text']
    assert verify_native(path, result['rows'], result['receipt'], category='prose', **context) == []


def test_foreign_rendition_is_preserved_and_independently_checked(tmp_path):
    from ocd_kernel.projection.categories.native_documents import verify_document as verify_native

    path = tmp_path / "foreign-rendition.tei.xml"
    path.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
        '<titleStmt><title>Example</title></titleStmt><publicationStmt><p>Test</p></publicationStmt>'
        '<sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text><body>'
        '<div type="chapter"><p>In <foreign xml:lang="el" rend="class=Greek">theos</foreign>.</p>'
        '</div></body></text></TEI>',
        encoding="utf-8",
    )
    context = dict(
        identity={"work_id": "native", "textual_form_id": "english", "edition_id": "foreign"},
        language="en", representation_revision="r1", edition_title="Example",
    )
    result = project_prose_document(path, **context)
    foreign = result["rows"][0]["structure"][0]["content"][0]["content"][1]
    assert foreign["kind"] == "foreign-text"
    assert foreign["attributes"] == {"language": "el", "style": "class=Greek"}
    assert verify_native(path, result["rows"], result["receipt"], category="prose", **context) == []

    rows = copy.deepcopy(result["rows"])
    rows[0]["structure"][0]["content"][0]["content"][1]["attributes"]["style"] = "class=Hebrew"
    receipt = copy.deepcopy(result["receipt"])
    receipt["output_sha256"] = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert verify_native(path, rows, receipt, category="prose", **context)


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("pr")


def project(case):
    path = FIXTURES / case["tei_file"]
    context = case["context"]
    result = project_prose_document(path, **context)
    receipt = build_correspondence_receipt(result, identity=context["identity"])
    return path, result["rows"], receipt, context


def normalized(text):
    return " ".join(text.split())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_real_source_paragraphs_and_notes_match_without_manufactured_chunks(case):
    path, rows, receipt, context = project(case)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case["tei_sha256"]
    retained = FIXTURES / case["retained_excerpt_file"]
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == case["retained_excerpt_sha256"]
    source = etree.parse(str(retained))
    # Source-native selection is independent of the TEI mapper and its checker.
    paragraphs = source.xpath(case.get("source_paragraph_xpath", "/*[local-name()='div3']/*[local-name()='p'] | /*/*[local-name()='div3']/*[local-name()='p']"))
    assert [p.get("id") for p in paragraphs] == case["source_paragraph_ids"]
    assert len(paragraphs) == len(rows) == case["source_paragraph_count"]
    for source_p, row in zip(paragraphs, rows):
        # Division names come from retained source metadata, not the TEI output.
        assert row["locator"]["divisions"][-1]["titles"] == [normalized(source_p.getparent().get("title"))]
        words = source_p.xpath(".//text()[not(ancestor::note)]")
        assert row["text"] == normalized("".join(words))
        notes = source_p.xpath(".//note")
        assert [n["text"] for n in row["notes"]] == [normalized("".join(n.xpath(".//text()"))) for n in notes]
    assert [r["sequence"] for r in rows] == list(range(1, len(rows) + 1))
    assert len({r["record_id"] for r in rows}) == len(rows)
    assert all(r["locator"]["kind"] == "paragraph" and r["category"] == "prose" for r in rows)
    assert verify_document(path, rows, receipt, **context) == []


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
@pytest.mark.parametrize("mutation", ["omit", "duplicate", "reorder", "text", "split", "invent-section", "wrong-locator", "private", "lost-note"])
def test_source_derived_mutations_fail_despite_consistent_receipts(case, mutation):
    path, rows, receipt, context = project(case)
    if mutation == "omit": rows.pop()
    elif mutation == "duplicate": rows.append(copy.deepcopy(rows[-1]))
    elif mutation == "reorder": rows.reverse()
    elif mutation == "text": rows[-1]["text"] += " Invented words."
    elif mutation == "split":
        original = rows[-1]
        cut = len(original["text"]) // 2
        extra = copy.deepcopy(original)
        original["text"], extra["text"] = original["text"][:cut], original["text"][cut:]
        rows.append(extra)
    elif mutation == "invent-section": rows[0]["locator"]["divisions"].append({"order": 1, "type": "section", "titles": ["Invented section"]})
    elif mutation == "wrong-locator": rows[0]["locator"]["text_part"] = "back"
    elif mutation == "private": rows[0]["provenance"]["source_path"] = "private/path"
    else:
        carrying = next((r for r in rows if r["notes"]), None)
        if carrying is None:
            rows[0]["notes"] = [{"text": "Invented note", "place": "foot", "label": "1"}]
        else: carrying["notes"].pop()
    for index, row in enumerate(rows, 1): row["sequence"] = index
    receipt["output_sha256"] = hashlib.sha256(canonical_row_bytes(rows)).hexdigest()
    receipt["row_count"] = len(rows)
    for row, anchor in zip(rows, receipt["anchors"]):
        anchor["text_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    assert verify_document(path, rows, receipt, **context)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_unsupported_structure_has_independent_diagnostic(case, tmp_path):
    path, rows, receipt, context = project(case)
    changed = tmp_path / "unsupported.xml"
    text = path.read_text(encoding="utf-8").replace("</body>", "<formula>Unmapped material</formula></body>")
    changed.write_text(text, encoding="utf-8")
    with pytest.raises(PipelineError, match="unsupported-visible"):
        project_prose_document(changed, **context)
    receipt["master_sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
    assert any("unsupported-visible: formula" in e for e in verify_document(changed, rows, receipt, **context))


def test_accepted_prose_requires_promoted_authority_and_checks_it_independently(tmp_path):
    from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance
    from ocd_kernel.lib.path_io import io_path
    from ocd_kernel.tei.acceptance import promote_accepted_master
    root = _fixture_root(tmp_path)
    acceptance, record = _write_valid_acceptance(root)
    with pytest.raises(PipelineError, match="promoted"):
        project_accepted_prose(root, acceptance_path=acceptance)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path / "out")
    result = project_accepted_prose(tmp_path / "out", acceptance_path=promoted.acceptance_path)
    identity = {k: record["identity"][k] for k in ("work_id", "textual_form_id", "edition_id")}
    receipt = result["receipt"]
    assert receipt == build_correspondence_receipt(result, identity=identity)
    assert verify_accepted(tmp_path / "out", acceptance_path=promoted.acceptance_path, rows=result["rows"], receipt=receipt) == []
    prefixed = project_accepted_prose(io_path(tmp_path / "out"), acceptance_path=io_path(promoted.acceptance_path))
    assert prefixed == result
    assert verify_accepted(io_path(tmp_path / "out"), acceptance_path=io_path(promoted.acceptance_path), rows=result["rows"], receipt=receipt) == []
    assert verify_accepted_prose(io_path(tmp_path / "out"), acceptance_path=io_path(promoted.acceptance_path), rows=result["rows"], receipt=receipt) == []
    outside = tmp_path / "outside-acceptance.json"
    outside.write_bytes(promoted.acceptance_path.read_bytes())
    with pytest.raises(PipelineError, match="outside"):
        project_accepted_prose(tmp_path / "out", acceptance_path=outside)
    assert any("outside" in error for error in verify_accepted(tmp_path / "out", acceptance_path=outside, rows=result["rows"], receipt=receipt))
    result["rows"][0]["text"] += " False."
    receipt["output_sha256"] = hashlib.sha256(canonical_row_bytes(result["rows"])).hexdigest()
    assert verify_accepted(tmp_path / "out", acceptance_path=promoted.acceptance_path, rows=result["rows"], receipt=receipt)


def test_prose_rows_reproduce_in_a_second_process():
    expected = [canonical_row_bytes(project(c)[1]).hex() for c in CASES]
    code = "from tests.test_projection_prose import CASES,project,canonical_row_bytes; import json; print(json.dumps([canonical_row_bytes(project(c)[1]).hex() for c in CASES]))"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == expected


def test_real_shapes_and_unsectioned_envelope_are_not_invented():
    by_shape = {case["shape"]: case for case in CASES}
    assert set(by_shape) == {"chaptered", "sectioned", "unsectioned"}
    _, chapters, _, _ = project(by_shape["chaptered"])
    assert [r["locator"]["divisions"][-1]["order"] for r in chapters] == [1] * 2 + [2] * 13
    assert all(r["locator"]["divisions"][-1]["type"] == "chapter" for r in chapters)
    _, sections, _, _ = project(by_shape["sectioned"])
    assert all(r["locator"]["divisions"][-1]["type"] == "section" for r in sections)
    case = by_shape["unsectioned"]
    source = etree.parse(str(FIXTURES / case["retained_excerpt_file"]))
    assert source.getroot().get("id") == "iv.ii"
    assert not source.xpath("/div2/*[starts-with(local-name(), 'div')]")
    all_ids = source.xpath("/div2/p/@id")
    assert len(all_ids) == 17
    assert all_ids == case["complete_source_direct_paragraph_ids"]
    assert set(all_ids) == set(case["source_paragraph_ids"]) | set(case["excluded_source_paragraph_ids"])
    assert not set(case["source_paragraph_ids"]) & set(case["excluded_source_paragraph_ids"])
    _, unsectioned, _, _ = project(case)
    assert all([d["type"] for d in r["locator"]["divisions"]] == ["work"] for r in unsectioned)
    assert all(r["locator"]["divisions"][0]["titles"] == [source.getroot().get("title")] for r in unsectioned)


@pytest.mark.parametrize("change", ["private", "category", "locator"])
def test_category_entry_point_enforces_its_closed_schema(monkeypatch, change):
    import ocd_kernel.projection.envelope as common
    case = CASES[0]
    result = common.project_document(FIXTURES / case["tei_file"], **case["context"])
    if change == "private": result["rows"][0]["provenance"]["source_path"] = "private/path"
    elif change == "category": result["rows"][0]["category"] = "poetry"
    else: result["rows"][0]["locator"]["kind"] = "invented-chunk"
    monkeypatch.setattr(common, "project_document", lambda *a, **k: result)
    with pytest.raises(PipelineError, match="invalid prose public row"):
        project_prose_document(FIXTURES / case["tei_file"], **case["context"])


def test_native_section_label_and_title_remain_distinct(tmp_path):
    path = tmp_path / 'label-title.xml'
    path.write_text('''<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>
    <titleStmt><title>Fixture</title></titleStmt><publicationStmt><p>Fixture</p></publicationStmt>
    <sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text><body>
    <div type="book" n="I"><head type="label">Book I</head><head type="title">Of Prayer</head><p>Body.</p></div>
    </body></text></TEI>''', encoding='utf-8')
    context = dict(identity={'work_id':'fixture','textual_form_id':'en','edition_id':'edition'}, language='en', representation_revision='r1', edition_title='Fixture')
    out = project_prose_document(path, **context)
    from ocd_kernel.projection.categories.native_documents import verify_document
    assert verify_document(path, out['rows'], out['receipt'], category='prose', **context) == []
    headings = out['rows'][0]['structure'][0]['content'][:2]
    assert [h['kind'] for h in headings] == ['heading', 'heading']
    assert [h['attributes']['type'] for h in headings] == ['label', 'title']
    assert [h['content'] for h in headings] == [[{'kind': 'text', 'text': 'Book I'}], [{'kind': 'text', 'text': 'Of Prayer'}]]
    from ocd_kernel.release.features import configuration_features
    from ocd_kernel.release.typed_rows import encode_rows, check_rows
    features = configuration_features(out['rows'])
    check_rows(encode_rows(out['rows'], features), out['rows'], features)
    for index in (0, 1):
        rows = copy.deepcopy(out['rows'])
        rows[0]['structure'][0]['content'][index]['content'][0]['text'] = 'Changed'
        assert verify_document(path, rows, out['receipt'], category='prose', **context)
