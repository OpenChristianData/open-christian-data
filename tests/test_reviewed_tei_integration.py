import hashlib

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

ORIGINAL = b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><sourceDesc><bibl/></sourceDesc></fileDesc></teiHeader><text><body><p>Exact  text\r\n&amp; spacing.</p></body></text></TEI>'


def derive(original=ORIGINAL, **overrides):
    args = dict(expected_sha256=hashlib.sha256(ORIGINAL).hexdigest(),
                identity=dict(work_id="w", textual_form_id="f", edition_id="e", acquisition_id="a"),
                source=dict(source_sha256="a" * 64, source_bytes=17, source_path="retained/source.txt"),
                source_url="https://example.com/source", declared_scope="whole retained member",
                revision=dict(id="integration-v1", date="2026-09-10", note="Header binding only."))
    return bind_reviewed_header(original, **(args | overrides))


def test_header_binding_preserves_exact_text_and_is_deterministic():
    derived = derive()
    assert derived.split(b"</teiHeader>")[1] == ORIGINAL.split(b"</teiHeader>")[1]
    assert derived == derive()
    assert b'type="work_id">w</idno>' in derived


def test_changed_reviewed_bytes_are_rejected():
    with pytest.raises(PipelineError, match="hash mismatch"):
        derive(ORIGINAL.replace(b"Exact", b"Altered"))


@pytest.mark.parametrize("prefixed", [False, True])
@pytest.mark.parametrize("existing_source", [False, True])
def test_prose_source_description_binding_is_p5_valid_and_reversible(prefixed, existing_source, tmp_path):
    import re
    from pathlib import Path
    from lxml import etree
    from ocd_kernel.tei.acceptance import _tei_facts

    original = ORIGINAL.replace(b"<sourceDesc><bibl/>", b"<titleStmt><title>Title</title></titleStmt><publicationStmt><p>Internal.</p></publicationStmt><sourceDesc><p>Exact source.</p><p/>")
    if existing_source:
        original = original.replace(b"Exact source.", b'Exact source.<bibl><ptr target="https://example.com/source"/><idno type="sha256">' + b'a' * 64 + b'</idno></bibl>')
    if prefixed:
        original = re.sub(rb"<(\/?)([A-Za-z]+)", rb"<\1t:\2", original).replace(b"xmlns=", b"xmlns:t=")
    bound = derive(original, expected_sha256=hashlib.sha256(original).hexdigest())
    schema_path = Path(__file__).resolve().parents[1] / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    assert schema.validate(etree.fromstring(bound)), str(schema.error_log)
    binding = b'<p xmlns="http://www.tei-c.org/ns/1.0"><bibl'
    start = bound.index(binding)
    end = bound.index(b"</bibl></p>", start) + len(b"</bibl></p>")
    revision_start = bound.index(b'<revisionDesc xmlns=')
    revision_end = bound.index(b"</revisionDesc>", revision_start) + len(b"</revisionDesc>")
    assert bound[:start] + bound[end:revision_start] + bound[revision_end:] == original
    assert bound == derive(original, expected_sha256=hashlib.sha256(original).hexdigest())
    candidate = tmp_path / "candidate.xml"
    candidate.write_bytes(bound)
    facts = _tei_facts(candidate)[1]
    assert {key: facts[key] for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id")} == dict(work_id="w", textual_form_id="f", edition_id="e", acquisition_id="a")
    assert facts["source_url"] == "https://example.com/source"
    assert facts["sha256"] == facts["source_sha256"] == "a" * 64


def test_prefixed_header_keeps_original_namespace_and_text_bytes():
    import re
    original = re.sub(rb"<(\/?)([A-Za-z]+)", rb"<\1t:\2", ORIGINAL).replace(b"xmlns=", b"xmlns:t=")
    result = derive(original, expected_sha256=hashlib.sha256(original).hexdigest())
    assert result.split(b"</t:teiHeader>")[1] == original.split(b"</t:teiHeader>")[1]


def test_existing_bindings_are_not_overwritten():
    derived = derive()
    with pytest.raises(PipelineError, match="revision history"):
        derive(derived, expected_sha256=hashlib.sha256(derived).hexdigest())


def test_lightfoot_integration_rejects_known_structural_defect(tmp_path):
    from build.tools.integrate_reviewed_lightfoot import prepare
    with pytest.raises(PipelineError, match="structural fidelity is blocked"):
        prepare(tmp_path, tmp_path / "original", tmp_path / "new-stage")
    assert not (tmp_path / "new-stage").exists()


def test_conflicting_source_is_rejected():
    original = ORIGINAL.replace(b"<bibl/>", b'<bibl><ptr target="https://different.example/"/></bibl>')
    with pytest.raises(PipelineError, match="different source URL"):
        derive(original, expected_sha256=hashlib.sha256(original).hexdigest())


def test_explicit_historical_description_preserved_with_scoped_binding(tmp_path):
    from ocd_kernel.tei.acceptance import _tei_facts
    historical = b'<bibl><ptr target="https://archive.example/"/><idno type="sha256">' + b'b' * 64 + b'</idno></bibl>'
    original = ORIGINAL.replace(b'<bibl/>', historical)
    args = dict(expected_sha256=hashlib.sha256(original).hexdigest(),
                historical_source_description={'pointers': ['https://archive.example/'], 'sha256': ['b' * 64]})
    result = derive(original, **args)
    assert historical in result
    assert result.split(b'</teiHeader>')[1] == original.split(b'</teiHeader>')[1]
    candidate = tmp_path / 'candidate.xml'
    candidate.write_bytes(result)
    facts = _tei_facts(candidate)[1]
    assert facts['source_url'] == 'https://example.com/source'
    assert facts['sha256'] == 'a' * 64
    with pytest.raises(PipelineError, match='explicit evidence'):
        derive(original, **(args | {'historical_source_description': {'pointers': [], 'sha256': []}}))
    for injection in (b'<idno type="work_id">other</idno>', b'<note type="source-location">other</note>'):
        candidate.write_bytes(result.replace(b'</sourceDesc>', injection + b'</sourceDesc>'))
        with pytest.raises(PipelineError, match='outside scoped binding'):
            _tei_facts(candidate)
    duplicated = result.replace(b'</sourceDesc>', b'<bibl type="ocd-acceptance-binding"/></sourceDesc>')
    candidate.write_bytes(duplicated)
    with pytest.raises(PipelineError, match='multiple scoped'):
        _tei_facts(candidate)


def test_corpus_acceptance_facts_use_only_edition_header(tmp_path):
    from lxml import etree
    from ocd_kernel.tei.acceptance import _tei_facts
    from ocd_kernel.tei.reviewed_composition import compose_reviewed_documents
    derived = derive()
    header = etree.tostring(etree.fromstring(derived)[0])
    # Child headers are historical document metadata, not edition acceptance.
    child = ORIGINAL.replace(b'<bibl/>', b'<bibl><idno type="work_id">historical</idno></bibl>')
    members = [(child, hashlib.sha256(child).hexdigest())] * 2
    composed = compose_reviewed_documents(header, members)
    candidate = tmp_path / 'corpus.xml'
    candidate.write_bytes(composed)
    assert _tei_facts(candidate)[1]['work_id'] == 'w'
    candidate.write_bytes(composed.replace(b'</teiCorpus>', b'Unaccounted text</teiCorpus>'))
    with pytest.raises(PipelineError, match='outside'):
        _tei_facts(candidate)
    candidate.write_bytes(composed.replace(child, b'', 1))
    assert _tei_facts(candidate)[1]['work_id'] == 'w'
    candidate.write_bytes(composed.replace(child, b''))
    with pytest.raises(PipelineError, match='at least one'):
        _tei_facts(candidate)


def test_historical_revision_notes_survive_without_invented_dates_or_ids():
    from lxml import etree
    from ocd_kernel.tei.acceptance import _tei_facts
    history = b'<revisionDesc><change><date>2007-02</date>Source review</change></revisionDesc>'
    original = ORIGINAL.replace(b'</teiHeader>', history + b'</teiHeader>')
    derived = derive(original, expected_sha256=hashlib.sha256(original).hexdigest())
    tree = etree.fromstring(derived)
    changes = tree.findall('.//{http://www.tei-c.org/ns/1.0}change')
    assert len(changes) == 2
    assert etree.tostring(changes[0]) == b'<change xmlns="http://www.tei-c.org/ns/1.0"><date>2007-02</date>Source review</change>'
    assert derived.split(b'</teiHeader>')[1] == original.split(b'</teiHeader>')[1]


def test_acceptance_facts_require_complete_bound_revision_but_allow_source_history(tmp_path):
    from ocd_kernel.tei.acceptance import _tei_facts
    original = ORIGINAL.replace(b'</teiHeader>', b'<revisionDesc><change><date>2007-02</date>Source review</change></revisionDesc></teiHeader>')
    derived = derive(original, expected_sha256=hashlib.sha256(original).hexdigest())
    candidate = tmp_path / 'candidate.xml'
    candidate.write_bytes(derived)
    assert 'integration-v1' in _tei_facts(candidate)[1]['revision_changes']
    candidate.write_bytes(derived.replace(b' when="2026-09-10"', b''))
    with pytest.raises(PipelineError, match='xml:id, when, and note'):
        _tei_facts(candidate)


def test_multiple_source_catalog_ids_preserved_but_binding_conflicts_rejected(tmp_path):
    from ocd_kernel.tei.acceptance import _tei_facts
    candidate = tmp_path / 'candidate.xml'
    derived = derive().replace(b'<bibl/>', b'<bibl><idno type="STC">A</idno><idno type="STC">B</idno></bibl>')
    candidate.write_bytes(derived)
    assert _tei_facts(candidate)[1]['work_id'] == 'w'
    candidate.write_bytes(derived.replace(b'<bibl/>', b'').replace(b'</sourceDesc>', b'<bibl><idno type="work_id">other</idno></bibl></sourceDesc>'))
    with pytest.raises(PipelineError, match='conflicting TEI header idno'):
        _tei_facts(candidate)
