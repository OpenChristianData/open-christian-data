import copy
from pathlib import Path

import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document


@pytest.mark.parametrize('invalid', [None, 'duplicate', 'empty', 'relative-url', 'unknown'])
def test_entry_attribution_is_explicit_and_attached(tmp_path, invalid, monkeypatch):
    note = '<note type="source-attribution"><seg type="source-title">Original volume</seg><seg type="source-credit">Source provider</seg><seg type="source-location">Page 12</seg><ref type="source-url" target="https://example.org/source">Source</ref></note>'
    if invalid == 'duplicate':
        note = note.replace('</note>', '<seg type="source-credit">Other</seg></note>')
    elif invalid == 'empty':
        note = note.replace('Source provider', '')
    elif invalid == 'relative-url':
        note = note.replace('https://example.org/source', '../source')
    elif invalid == 'unknown':
        note = note.replace('source-credit', 'guess-credit')
    path = tmp_path / 'attribution.xml'
    path.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Collection</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Collection source</p></sourceDesc></fileDesc></teiHeader><text><body><div><p>First entry.</p>'+note+'</div><div><p>Second entry.</p></div></body></text></TEI>', encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Collection', category='prose', _allow_acceptance_metadata=True)
    if invalid:
        with pytest.raises(PipelineError):
            project_document(path, **context)
        assert verify_document(path, [], {}, **context)
        return
    result = project_document(path, **context)
    rows = result['rows']
    assert rows[0]['provenance'] == {'edition_title':'Collection', 'source_title':'Original volume', 'source_credit':'Source provider', 'source_location':'Page 12', 'source_url':'https://example.org/source'}
    assert rows[1]['provenance'] == {'edition_title':'Collection'}
    assert rows[0]['text'] == 'First entry.'
    from ocd_kernel.projection.categories import native_documents
    monkeypatch.setattr(native_documents, '_entry_attribution', lambda *args: pytest.fail('producer called'))
    assert verify_document(path, rows, result['receipt'], **context) == []
    changed = copy.deepcopy(rows)
    changed[0]['provenance'], changed[1]['provenance'] = changed[1]['provenance'], changed[0]['provenance']
    assert verify_document(path, changed, result['receipt'], **context)


def test_corpus_rows_keep_volume_positions_and_distinct_record_ids(tmp_path):
    header = '<teiHeader><fileDesc><titleStmt><title>Volumes</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Sources</p></sourceDesc></fileDesc></teiHeader>'
    parts = ['<TEI>'+header+'<text xml:lang="en"><front><p>Front '+str(i)+'</p></front><body><div><p>Same text</p></div></body></text></TEI>' for i in (1, 2)]
    path = tmp_path / 'corpus.xml'
    path.write_text('<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'+header+''.join(parts)+'</teiCorpus>', encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Volumes', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    rows = result['rows']
    assert [r['locator']['document'] for r in rows] == [1, 1, 2, 2]
    assert len({r['record_id'] for r in rows}) == 4
    assert [r['text'] for r in rows] == ['Front 1', 'Same text', 'Front 2', 'Same text']
    assert verify_document(path, rows, result['receipt'], **context) == []
    for mutation in ('document', 'omit', 'reorder'):
        changed = copy.deepcopy(rows)
        if mutation == 'document':
            changed[2]['locator']['document'] = 1
        elif mutation == 'omit':
            del changed[2:]
        else:
            changed = changed[2:] + changed[:2]
        assert verify_document(path, changed, result['receipt'], **context)


def test_private_bibliography_and_tei_version_are_accounted(tmp_path):
    raw = '<TEI xmlns="http://www.tei-c.org/ns/1.0" version="4.9.0"><teiHeader><fileDesc><titleStmt><title>Work</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><bibl><editor>Recorded editor</editor><publisher>Recorded publisher</publisher><respStmt><resp>Translation</resp><name>Recorded name</name></respStmt></bibl></sourceDesc></fileDesc></teiHeader><text><body><div><p>Source text.</p></div></body></text></TEI>'
    path = tmp_path / 'version.xml'
    path.write_text(raw, encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Work', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert result['rows'][0]['text'] == 'Source text.'
    assert 'Recorded editor' not in str(result['rows'])
    assert result['receipt']['inventory'][0]['attributes']['version'] == '4.9.0'
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    changed = copy.deepcopy(result['receipt'])
    changed['inventory'][0]['attributes']['version'] = '4.9.1'
    assert verify_document(path, result['rows'], changed, **context)
    path.write_text(raw.replace('version="4.9.0"', 'version="invented"'), encoding='utf-8')
    with pytest.raises(PipelineError, match='version'):
        project_document(path, **context)
    assert verify_document(path, result['rows'], result['receipt'], **context)


def test_stokes_accepted_source_description_bibl_is_private_and_exact(tmp_path):
    header = ('<teiHeader><fileDesc><titleStmt><title>Acts</title></titleStmt>'
              '<publicationStmt><p>Private</p></publicationStmt>'
              '<sourceDesc><p>Retained print statement <bibl>Recorded source</bibl></p></sourceDesc>'
              '</fileDesc></teiHeader>')
    raw = ('<TEI xmlns="http://www.tei-c.org/ns/1.0">' + header
           + '<text><body><div type="source-div1"><p>Public text.</p></div></body></text></TEI>')
    path = tmp_path / 'stokes.xml'
    path.write_text(raw, encoding='utf-8')
    context = dict(identity={'work_id':'expositors-bible--g-t-stokes','textual_form_id':'form','edition_id':'edition'},
                   language='en', representation_revision='revision', edition_title='Acts',
                   category='commentary', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert result['rows'][0]['text'] == 'Public text.'
    assert 'Recorded source' not in str(result['rows'])
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    for identity, modified, invalid_shape in (
        ('expositors-bible--alfred-plummer', raw, True),
        ('expositors-bible--g-t-stokes', raw.replace('<bibl>Recorded source</bibl>', '<bibl>One</bibl><bibl>Two</bibl>'), True),
        ('expositors-bible--g-t-stokes', raw.replace('<sourceDesc><p>Retained print statement <bibl>Recorded source</bibl></p></sourceDesc>', '<sourceDesc><p>Retained print statement</p><bibl>Recorded source</bibl></sourceDesc>'), False),
    ):
        path.write_text(modified, encoding='utf-8')
        invalid = dict(context)
        invalid['identity'] = dict(context['identity'], work_id=identity)
        if invalid_shape:
            with pytest.raises(PipelineError):
                project_document(path, **invalid)
        else:
            project_document(path, **invalid)
        assert verify_document(path, result['rows'], result['receipt'], **invalid)


def test_native_poetry_preserves_whole_edition_and_rejects_loss(tmp_path):
    from ocd_kernel.projection.categories.poetry import _uses_native_edition
    path = tmp_path / 'poetry.xml'
    path.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Poetry edition</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Retained edition</p></sourceDesc></fileDesc></teiHeader><text><front><div><p>Preface</p></div></front><body><div type="book"><head>Book One</head><lg type="stanza"><l>First line</l><l>Second line</l></lg></div></body><back><div><p>Closing matter</p></div></back></text></TEI>', encoding='utf-8')
    assert _uses_native_edition(path)
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Poetry edition', category='poetry', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert [r['category'] for r in result['rows']] == ['poetry'] * 3
    assert [r['locator']['text_part'] for r in result['rows']] == ['front','body','back']
    assert 'First line\nSecond line' in result['rows'][1]['text']
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    for mutation in ('front', 'line', 'category', 'extra', 'order'):
        rows = copy.deepcopy(result['rows'])
        if mutation == 'front':
            rows.pop(0)
        elif mutation == 'line':
            rows[1]['structure'][0]['content'][1]['content'].pop()
        elif mutation == 'category':
            rows[1]['category'] = 'prose'
        elif mutation == 'extra':
            rows[1]['invented'] = 'field'
        else:
            rows.reverse()
        assert verify_document(path, rows, result['receipt'], **context)


def test_native_prose_reference_locations_and_ranges(tmp_path, monkeypatch):
    path = tmp_path / 'references.xml'
    path.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Test</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text><body><div><p>Read <ref cRef="John.3.16-18">John 3</ref>.</p><div><p>See <ref target="https://example.org">source</ref>.</p></div></div></body></text></TEI>', encoding='utf-8')
    context = dict(identity={'work_id':'w','textual_form_id':'f','edition_id':'e'}, language='en', representation_revision='test', edition_title='Test', category='prose')
    result = project_document(path, **context)
    references = result['rows'][0]['source_references']
    assert [ref['source_child_path'] for ref in references] == [[0, 0], [1, 0, 0]]
    assert references[0]['scripture']['normalized'] == 'John.3.16-John.3.18'
    assert references[1]['normalization_status'] == 'unsupported-explicit-target'
    from ocd_kernel.projection.categories import native_documents
    monkeypatch.setattr(native_documents, '_prose_references', lambda *args: pytest.fail('producer called'))
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    references[0]['source_child_path'] = [1, 0, 0]
    assert verify_document(path, result['rows'], result['receipt'], **context)


def test_one_member_corpus_keeps_member_and_rejects_missing_member(tmp_path):
    header = '<teiHeader><fileDesc><titleStmt><title>One member</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader>'
    member = '<TEI>'+header+'<text xml:lang="en"><body><div><p>Only member text.</p></div></body></text></TEI>'
    path = tmp_path / 'single-member.xml'
    path.write_text('<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'+header+member+'</teiCorpus>', encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='One member', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert len(result['rows']) == 1
    assert result['rows'][0]['locator'] == {'kind': 'native-unit', 'text_part': 'body', 'unit': 1, 'document': 1}
    assert result['rows'][0]['text'] == 'Only member text.'
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    path.write_text('<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'+header+'</teiCorpus>', encoding='utf-8')
    with pytest.raises(PipelineError, match='at least one prose document'):
        project_document(path, **context)
    assert verify_document(path, result['rows'], result['receipt'], **context)


def test_accepted_header_css_and_candidate_status_stay_private_and_checked(tmp_path):
    header = '<teiHeader><fileDesc><titleStmt><title>Header</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc><encodingDesc><tagsDecl><rendition xml:id="r1" scheme="css" selector=".title">font-weight:bold</rendition></tagsDecl></encodingDesc><revisionDesc status="candidate"><change>Source-bound candidate</change></revisionDesc></teiHeader>'
    path = tmp_path / 'header.xml'
    raw = '<TEI xmlns="http://www.tei-c.org/ns/1.0">'+header+'<text><body><div><p>Public text.</p></div></body></text></TEI>'
    path.write_text(raw, encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Header', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert result['rows'][0]['text'] == 'Public text.'
    assert 'font-weight' not in str(result['rows'])
    private = [item for item in result['receipt']['inventory'] if item['tag'] == 'rendition']
    assert len(private) == 1 and private[0]['role'] == 'bibliographic-header'
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    tampered = copy.deepcopy(result['receipt'])
    next(item for item in tampered['inventory'] if item['tag'] == 'rendition')['text_sha256'] = '0' * 64
    assert verify_document(path, result['rows'], tampered, **context)
    for original, replacement in (('status="candidate"', 'status="invented"'), ('scheme="css"', 'scheme="unknown"'), ('<tagsDecl><rendition', '<unknown><rendition')):
        modified = raw.replace(original, replacement)
        if replacement.startswith('<unknown>'):
            modified = modified.replace('</tagsDecl>', '</unknown>')
        path.write_text(modified, encoding='utf-8')
        with pytest.raises(PipelineError):
            project_document(path, **context)
        assert verify_document(path, result['rows'], result['receipt'], **context)


def test_native_auto_index_comments_are_private_and_bound(tmp_path):
    markers = ('<!-- added reason="insertIndex" class="scripRef" -->'
               '<!-- Start of automatically inserted scripRef index -->'
               '<p>Index text.</p>'
               '<!-- End of scripRef index -->'
               '<!-- /added -->')
    raw = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Indexed</title></titleStmt>'
           '<publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader>'
           '<text><body><div><p>Main text.</p>'+markers+'</div></body></text></TEI>')
    path = tmp_path / 'comments.xml'
    path.write_text(raw, encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Indexed', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert 'Main text.' in result['rows'][0]['text'] and 'Index text.' in result['rows'][0]['text']
    assert 'insertIndex' not in str(result['rows'])
    comments = result['receipt']['source_comments']
    assert len(comments) == 4
    assert [row['child_index'] for row in comments] == [1, 2, 4, 5]
    assert all(row['disposition'] == 'private-auto-index-marker' for row in comments)
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    changed = copy.deepcopy(result['receipt'])
    changed['source_comments'][0]['text'] = ' other reason '
    assert verify_document(path, result['rows'], changed, **context)
    for altered in (raw.replace('class="scripRef"', 'class="unknown"'),
                    raw.replace('<p>Index text.</p>', ''),
                    raw.replace('<!-- /added -->', '<!-- /added -->visible'),
                    raw.replace('<!-- /added -->', '<!-- Copyright notice -->')):
        path.write_text(altered, encoding='utf-8')
        with pytest.raises(PipelineError):
            project_document(path, **context)
        assert verify_document(path, result['rows'], result['receipt'], **context)
    path.write_text(raw.replace('</div>', ''), encoding='utf-8')
    with pytest.raises(PipelineError, match='invalid native sermon XML'):
        project_document(path, **context)
    assert verify_document(path, result['rows'], result['receipt'], **context)


def test_copyright_prolog_comment_is_retained_as_rights_notice_handoff(tmp_path):
    root = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Work</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader><text><body><div><p>Text.</p></div></body></text></TEI>'
    notice = '<!-- Copyright Christian Classics Ethereal Library -->'
    path = tmp_path / 'rights-comment.xml'
    path.write_text(notice+root, encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Work', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert result['rows'][0]['text'] == 'Text.'
    assert result['receipt']['source_comments'] == [{'parent_path': '#document', 'child_index': 0, 'text': ' Copyright Christian Classics Ethereal Library ', 'tail': '', 'disposition': 'source-rights-notice-handoff'}]
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    path.write_text(notice.replace('Copyright', 'Unreviewed')+root, encoding='utf-8')
    with pytest.raises(PipelineError, match='prolog comment'):
        project_document(path, **context)
    assert verify_document(path, result['rows'], result['receipt'], **context)


def test_nested_auto_index_wrapper_and_quartet_keep_document_order(tmp_path):
    quartet = ('<!-- added reason="insertIndex" class="scripRef" -->'
               '<!-- Start of automatically inserted scripRef index -->'
               '<p>Indexed reference.</p>'
               '<!-- End of scripRef index -->'
               '<!-- /added -->')
    body = ('<body><div><p>Before.</p></div><!-- added reason="AutoIndexing" -->'
            '<div>'+quartet+'</div><!-- /added --></body>')
    root = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Work</title></titleStmt>'
            '<publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader><text>'+body+'</text></TEI>')
    path = tmp_path / 'nested-comments.xml'
    path.write_text(root, encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Work', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert [row['text'] for row in result['rows']] == ['Before.', 'Indexed reference.']
    assert [row['disposition'] for row in result['receipt']['source_comments']] == ['private-auto-index-wrapper'] + ['private-auto-index-marker']*4 + ['private-auto-index-wrapper']
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    altered = copy.deepcopy(result['receipt'])
    altered['source_comments'][5]['text'] = ' /forged '
    assert verify_document(path, result['rows'], altered, **context)
    path.write_text(root.replace('reason="AutoIndexing"', 'reason="Unknown"'), encoding='utf-8')
    with pytest.raises(PipelineError, match='auto-index wrapper'):
        project_document(path, **context)
    assert verify_document(path, result['rows'], result['receipt'], **context)


def test_nested_source_header_metadata_is_private_and_fail_closed(tmp_path):
    header = ('<teiHeader><fileDesc><titleStmt><title>Work</title></titleStmt>'
              '<publicationStmt><p>Private</p></publicationStmt>'
              '<notesStmt><note type="retained-thml-header" corresp="urn:source"><seg type="source-element" subtype="ThML.head" n="{}" corresp="urn:source"><seg type="source-element">Electronic metadata</seg></seg></note>'
              '<note type="source-navigation-title-inventory"><list type="source-navigation-titles"><item n="i" corresp="#chapter-i">Chapter I</item></list></note></notesStmt>'
              '<sourceDesc><bibl><ref type="source-witness" target="https://example.org/witness">Witness</ref><date type="source-record-created" when="2000-07-09">2000-07-09</date></bibl></sourceDesc></fileDesc>'
              '<encodingDesc><tagsDecl><rendition xml:id="sheet" scheme="css">.title { font-weight: bold; }</rendition></tagsDecl></encodingDesc>'
              '<profileDesc><textClass><keywords><term type="ccel">Proofed</term></keywords></textClass></profileDesc></teiHeader>')
    raw = '<TEI xmlns="http://www.tei-c.org/ns/1.0">'+header+'<text><body><div><p>Public text.</p></div></body></text></TEI>'
    path = tmp_path / 'source-header.xml'
    path.write_text(raw, encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Work', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert result['rows'][0]['text'] == 'Public text.'
    assert 'Electronic metadata' not in str(result['rows'])
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    for old, new in (('type="source-record-created"', 'unknown="x"'), ('<item n="i"', '<unknown n="i"'), ('scheme="css"', 'scheme="unknown"')):
        path.write_text(raw.replace(old, new), encoding='utf-8')
        with pytest.raises(PipelineError):
            project_document(path, **context)
        assert verify_document(path, result['rows'], result['receipt'], **context)


def test_readable_corpus_unit_excludes_bound_machine_source_evidence(tmp_path):
    import base64
    import hashlib
    import json

    source = b'<ThML>retained source</ThML>'
    digest = hashlib.sha256(source).hexdigest()
    header = ('<teiHeader><fileDesc><titleStmt><title>Work</title></titleStmt>'
              '<publicationStmt><p>Private</p></publicationStmt><sourceDesc><bibl>'
              '<idno type="source_sha256">'+digest+'</idno><idno type="sha256">'+digest+'</idno>'
              '</bibl></sourceDesc></fileDesc></teiHeader>')
    member_header = '<teiHeader><fileDesc><titleStmt><title>Member</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader>'
    node = {'attributes': [], 'feature_id': 'source-node-1', 'kind': 'element', 'namespace_declarations': [],
            'ordinal': 1, 'parent_ordinal': None, 'payload_sha256': '0'*64, 'pi_target': None,
            'qname': 'ThML', 'scope': 'root', 'sibling_ordinal': 1, 'tail': '', 'text': ''}
    evidence = ('<div type="exact-source-evidence"><ab type="exact-retained-source-bytes" subtype="base64" n="'+digest+'">'
                +base64.b64encode(source).decode()+'</ab><div type="complete-xml-node-transcription">'
                '<ab xml:id="source-node-1" type="source-xml-node" subtype="element" n="1">'
                +json.dumps(node)+'</ab></div></div>')
    raw = ('<teiCorpus xmlns="http://www.tei-c.org/ns/1.0">'+header+'<TEI>'+member_header+
           '<text><body><div type="retained-source-member"><div type="readable-transcription"><p>Readable text.</p></div>'
           +evidence+'</div></body></text></TEI></teiCorpus>')
    path = tmp_path / 'source-evidence.xml'
    path.write_text(raw, encoding='utf-8')
    context = dict(identity={'work_id':'work','textual_form_id':'form','edition_id':'edition'}, language='en', representation_revision='revision', edition_title='Work', category='prose', _allow_acceptance_metadata=True)
    result = project_document(path, **context)
    assert len(result['rows']) == 1 and result['rows'][0]['text'] == 'Readable text.'
    assert base64.b64encode(source).decode() not in str(result['rows'])
    assert result['receipt']['anchors'][0]['unit_id'].endswith('/body/*[1]/div[1]')
    assert sum(item['reason'] == 'machine-source-evidence' for item in result['receipt']['exclusions']) == 4
    assert verify_document(path, result['rows'], result['receipt'], **context) == []
    tampered = copy.deepcopy(result['receipt'])
    tampered['exclusions'].pop()
    assert verify_document(path, result['rows'], tampered, **context)
    for altered in (raw.replace(base64.b64encode(source).decode(), base64.b64encode(b'forged').decode()),
                    raw.replace('type="exact-source-evidence"', 'type="unknown"'),
                    raw.replace('</ab><div type="complete-xml-node-transcription">', '<p>Hidden</p></ab><div type="complete-xml-node-transcription">'),
                    raw.replace(json.dumps(node)+'</ab>', json.dumps(node)+'<p>Hidden</p></ab>'),
                    raw.replace('</div></body>', '<p>Hidden text</p></div></body>')):
        path.write_text(altered, encoding='utf-8')
        with pytest.raises(PipelineError):
            project_document(path, **context)
        assert verify_document(path, result['rows'], result['receipt'], **context)
