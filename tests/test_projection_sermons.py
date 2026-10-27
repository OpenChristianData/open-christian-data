"""Real complete sermon units, independent ThML oracle, and corruption checks."""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.sermons import project_sermons_document as project,verify_sermons_document as verify
from build.lib.tei_xsd import compiled_tei_schema

ROOT=Path(__file__).resolve().parents[1]
SOURCE_ORACLE=ROOT/'plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-009/verify_original_source.py'
F=ROOT/'tests/fixtures/library-pipeline/categories/sermons'
CASES=json.loads((F/'manifest.json').read_text(encoding='utf-8'))['cases']


def test_native_whole_sermon_preserves_front_matter_and_mixed_content(tmp_path, monkeypatch):
    """Category selection, public metadata and private accounting fail closed."""
    path = tmp_path / 'native.tei.xml'
    path.write_text('''<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>
      <fileDesc><titleStmt><title>Example</title></titleStmt><publicationStmt><p>Test</p></publicationStmt>
      <sourceDesc><p>Fixture</p></sourceDesc></fileDesc></teiHeader><text xml:lang="eng">
      <front><div type="preface"><head>Preface</head><p>Introduction.</p></div></front>
      <body><div type="sermon"><head>The sermon</head><epigraph><bibl>ROMANS VI. 23.</bibl><q>Quoted passage.</q></epigraph>
      <p>Before <q><lg><l>First line</l><l>Second line</l></lg></q> after<note>Note retained.</note>.</p>
      <q><floatingText type="letter"><body><div type="address"><opener><salute>Friends,</salute></opener>
      <p>An embedded address.</p></div></body></floatingText></q><closer>AMEN.</closer></div></body>
      </text></TEI>''', encoding='utf-8')
    context = dict(identity={'work_id': 'native', 'textual_form_id': 'english', 'edition_id': 'test'},
                   language='en', representation_revision='r1', edition_title='Example')
    result = project(path, **context)
    row = result['rows'][0]
    assert len(result['rows']) == 1
    assert row['content_format'] == 'ocd-native-content-v1'
    assert row['primary_passage'] == 'ROMANS VI. 23.'
    assert row['front_matter'][0]['text'] == 'Preface\n\nIntroduction.'
    assert 'First line\nSecond line' in row['text']
    assert 'An embedded address.' in row['text'] and row['text'].endswith('AMEN.')
    assert 'Note retained.' not in row['text']
    assert 'Note retained.' in json.dumps(row['structure'])
    import ocd_kernel.projection.native_content as producer
    monkeypatch.setattr(producer, 'project_content', lambda *args: pytest.fail('producer called by checker'))
    monkeypatch.setattr(producer, 'readable_content', lambda *args: pytest.fail('renderer called by checker'))
    assert verify(path, result['rows'], result['receipt'], **context) == []
    for field, value in [('front_matter', []), ('primary_passage', 'ROMANS VI. 24.'),
                         ('text', 'Truncated'), ('sequence', 2), ('content_format', 'unknown')]:
        changed = copy.deepcopy(result['rows'])
        changed[0][field] = value
        assert verify(path, changed, result['receipt'], **context), field
    receipt = copy.deepcopy(result['receipt'])
    receipt['inventory'].pop()
    assert verify(path, result['rows'], receipt, **context)
    receipt = copy.deepcopy(result['receipt'])
    receipt['native_content_schema_sha256'] = '0'*64
    assert verify(path, result['rows'], receipt, **context)


def norm(node,exclude_notes=False):
    return ' '.join(''.join(node.xpath('.//text()[not(ancestor::note)]' if exclude_notes else './/text()')).split())


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_complete_sermons_match_retained_source_not_only_tei(case):
    path=F/case['tei_file'];out=project(path,**case['context'])
    for name,digest in case['files'].items():assert hashlib.sha256((F/name).read_bytes()).hexdigest()==digest
    source=E.parse(str(F/case['retained_file']));units=source.xpath('/sourceExcerpt/div1 | /sourceExcerpt/div2')
    assert len(units)==len(out['rows'])==len(case['selected_units'])
    collection_heads=source.xpath('/sourceExcerpt/collectionEvidence/div1/h1')
    if case['name']=='wesley':collection_heads=collection_heads[:1]
    collection=' '.join(norm(h) for h in collection_heads)
    for node,row,record in zip(units,out['rows'],case['selected_units']):
        assert node.get('id')==record['id']
        assert [(n.tag,dict(n.attrib)) for n in node.iter()]==[(n['tag'],n['attributes']) for n in record['node_accounting']]
        assert row['collection']==collection
        assert row['primary_passage']==node.find('scripCom').get('passage')
        assert row['locator']=={'kind':'sermon','number':node.get('n'),'headings':[norm(h,True) for h in node if h.tag in ('h1','h2')]}
        native_blocks=[n for n in node if n.tag in ('h1','h2','h3','p')]
        expected=[]
        for b in native_blocks:
            primary=b is node.find('p') or b.tag=='h3'
            expected.append({'kind':'paragraph' if b.tag=='p' else 'scripture-reference' if b.tag=='h3' else 'heading','number':None,'text':norm(b,True),'notes':[{'label':n.get('n'),'text':norm(n),'place':n.get('place')} for n in b.xpath('.//note')],'references':[] if primary else [{'label':norm(r),'locus':r.get('osisRef')} for r in b.xpath('.//scripRef')],'children':[]})
        assert row['structure']==expected
        assert row['text']=='\n\n'.join(norm(b,True) for b in native_blocks)
        assert sum(b['kind']=='paragraph' for b in expected)==record['paragraphs']
        notes=node.xpath('.//note')
        if notes:
            assert len(notes)==1
            statement=norm(notes[0]);m=re.fullmatch(r'Preached at (.+), (before the University), on (.+)\.',statement);assert m
            assert row['delivery']=={'statement':statement,'date':m.group(3),'place':m.group(1),'occasion':m.group(2)}
        else:assert row['delivery']==dict(statement=None,date=None,place=None,occasion=None)
    assert verify(path,out['rows'],out['receipt'],**case['context'])==[]
    assert len({r['record_id'] for r in out['rows']})==len(out['rows'])


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_sermon_tei_is_valid_p5(case):
    compiled_tei_schema(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd').assertValid(E.parse(str(F/case['tei_file'])))


@pytest.mark.requires_local_artifacts
def test_original_source_oracle_rejects_dropped_reference_mapping(tmp_path):
    tree = E.parse(str(F / 'whitefield.tei.xml'))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    ref = tree.xpath('//t:body/t:div[1]//t:ref[@type="incidental"]', namespaces=ns)[0]
    parent = ref.getparent()
    index = parent.index(ref)
    replacement = ''.join(ref.itertext()) + (ref.tail or '')
    if index:
        parent[index - 1].tail = (parent[index - 1].tail or '') + replacement
    else:
        parent.text = (parent.text or '') + replacement
    parent.remove(ref)
    changed = tmp_path / 'missing-reference.tei.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--case', 'whitefield', '--tei-path', str(changed)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    assert completed.returncode != 0
    assert 'scripture reference attachment differs' in (completed.stdout + completed.stderr)


@pytest.mark.requires_local_artifacts
@pytest.mark.parametrize('mutation', ['append', 'reorder'])
def test_original_source_oracle_rejects_source_text_or_order_drift(tmp_path, mutation):
    path = F / 'whitefield.tei.xml'
    tree = E.parse(str(path))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    unit = tree.xpath('//t:body/t:div[@xml:id="iii"]', namespaces=ns)[0]
    paragraphs = unit.xpath('./t:p', namespaces=ns)
    if mutation == 'append':
        paragraph = paragraphs[-1]
        if len(paragraph):
            paragraph[-1].tail = (paragraph[-1].tail or '') + ' Invented source text.'
        else:
            paragraph.text = (paragraph.text or '') + ' Invented source text.'
    else:
        first, second = paragraphs[:2]
        unit.remove(second)
        unit.insert(unit.index(first), second)
    changed = tmp_path / f'{mutation}-source-drift.tei.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--case', 'whitefield', '--tei-path', str(changed)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert 'block text mapping differs' in output


@pytest.mark.parametrize(
    'variant,should_fail',
    [
        ('hi_immediately_before_note', True),
        ('note_first_child_with_inline_content', True),
        ('whitespace_after_note', False),
    ],
)
def test_adjacent_note_boundary_inside_inline_prefix_fails_both_routes(tmp_path, variant, should_fail):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    paragraph = tree.xpath('//t:body/t:div[1]//t:p', namespaces=ns)[0]
    paragraph.clear()
    if variant == 'note_first_child_with_inline_content':
        paragraph.text = 'Prefix'
        note = E.SubElement(paragraph, '{http://www.tei-c.org/ns/1.0}note', n='x', place='foot')
        emphasis = E.SubElement(note, '{http://www.tei-c.org/ns/1.0}hi', rend='italic')
        emphasis.text = 'note'
        note.tail = 'tail'
    else:
        emphasis = E.SubElement(paragraph, '{http://www.tei-c.org/ns/1.0}hi', rend='italic')
        emphasis.text = 'Prefix'
        note = E.SubElement(paragraph, '{http://www.tei-c.org/ns/1.0}note', n='x', place='foot')
        note.text = 'note'
        note.tail = ' tail' if variant == 'whitespace_after_note' else 'tail'
    changed = tmp_path / 'adjacent-note-boundary.tei.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))

    if should_fail:
        with pytest.raises(PipelineError, match='adjacent note boundary'):
            project(changed, **case['context'])
        errors = verify(changed, [], {}, **case['context'])
        assert errors == ['unsupported-visible: adjacent note boundary']
    else:
        result = project(changed, **case['context'])
        assert verify(changed, result['rows'], result['receipt'], **case['context']) == []


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
@pytest.mark.parametrize('mutation',['omit','duplicate','order','text','primary','incidental','role','locator','date','place','occasion','note','subjective','provenance','master','schema','inventory','warning','exclusion','status'])
def test_source_derived_mutations_fail_with_consistent_receipts(case,mutation):
    path=F/case['tei_file'];out=project(path,**case['context']);rows=out['rows'];r=rows[0]
    if mutation=='omit':rows.pop()
    elif mutation=='duplicate':rows.append(copy.deepcopy(rows[-1]))
    elif mutation=='order':r['structure'].reverse()
    elif mutation=='text':r['text']+=' Invented words.'
    elif mutation=='primary':r['primary_passage']='Invented 1:1'
    elif mutation=='incidental':next(b for b in r['structure'] if b['references'])['references'].pop()
    elif mutation=='role':r['primary_passage']=next(b for b in r['structure'] if b['references'])['references'][0]['locus']
    elif mutation=='locator':r['locator']['number']='999'
    elif mutation in ('date','place','occasion'):r['delivery'][mutation]='Invented'
    elif mutation=='note':
        b=next((b for b in r['structure'] if b['notes']),r['structure'][0]);b['notes']=[] if b['notes'] else [{'label':'x','place':'foot','text':'Invented'}]
    elif mutation=='subjective':r['audience']='lay'
    elif mutation=='provenance':r['provenance']['edition_title']='Other book'
    elif mutation=='master':out['receipt']['master_sha256']='0'*64
    elif mutation=='schema':out['receipt']['schema_sha256']='0'*64
    elif mutation=='inventory':out['receipt']['inventory'].pop()
    elif mutation=='warning':out['receipt']['warnings']=[]
    elif mutation=='exclusion':out['receipt']['exclusions']=[]
    elif mutation=='status':out['receipt']['independent_check']={'status':'passed','human_accepted':True}
    for i,row in enumerate(rows,1):row['sequence']=i
    out['receipt']['row_count']=len(rows)
    out['receipt']['output_sha256']=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    for row,anchor in zip(rows,out['receipt']['anchors']):anchor['text_sha256']=hashlib.sha256(row['text'].encode()).hexdigest()
    assert verify(path,rows,out['receipt'],**case['context'])


@pytest.mark.parametrize('mutation',['table','attribute','namespace','loose','prolog-pi','epilog-pi','primary-conflict','duplicate-id','empty-head','empty-primary','empty-paragraph','nested-opener'])
def test_unsupported_tei_is_visible_to_both_routes(mutation,tmp_path):
    c=CASES[0];path=F/c['tei_file'];tree=E.parse(str(path));ns={'t':'http://www.tei-c.org/ns/1.0'};units=tree.xpath('//t:body/t:div',namespaces=ns);unit=units[0]
    if mutation=='empty-head':unit.find('{'+ns['t']+'}head').clear()
    elif mutation=='empty-primary':unit.xpath('t:opener/t:ref',namespaces=ns)[0].text=None
    elif mutation=='empty-paragraph':unit.find('{'+ns['t']+'}p').clear()
    elif mutation=='nested-opener':
        section=E.SubElement(unit,'{'+ns['t']+'}div',type='section')
        section.append(copy.deepcopy(unit.find('{'+ns['t']+'}opener')))
    elif mutation=='table':E.SubElement(unit,'{'+ns['t']+'}table')
    elif mutation=='attribute':unit.set('ana','invented')
    elif mutation=='namespace':unit.tag='{urn:wrong}div'
    elif mutation=='loose':unit.text='Unmapped words.'
    elif mutation=='primary-conflict':unit.xpath('.//t:ref[@type="primary"]',namespaces=ns)[-1].set('cRef','Bible:Wrong.1.1')
    elif mutation=='duplicate-id':units[1].set('{http://www.w3.org/XML/1998/namespace}id',unit.get('{http://www.w3.org/XML/1998/namespace}id'))
    raw=E.tostring(tree,encoding='utf-8')
    if mutation=='prolog-pi':raw=b'<?hidden test?>'+raw
    elif mutation=='epilog-pi':raw+=b'<?hidden test?>'
    changed=tmp_path/'bad.xml';changed.write_bytes(raw);out=project(path,**c['context'])
    with pytest.raises(PipelineError):project(changed,**c['context'])
    assert verify(changed,out['rows'],out['receipt'],**c['context'])


def test_sermon_checker_does_not_call_producer(monkeypatch):
    import ocd_kernel.projection.categories.sermons as module
    case=CASES[0];path=F/case['tei_file'];out=project(path,**case['context'])
    monkeypatch.setattr(module,'project_sermons_document',lambda *a,**k:(_ for _ in ()).throw(AssertionError('producer called')))
    assert verify(path,out['rows'],out['receipt'],**case['context'])==[]


def _with_tcp_header(tmp_path):
    """Isolate header families observed in accepted Occom N09814, not new TEI."""
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    tag = '{' + ns['t'] + '}'
    header = tree.find('t:teiHeader', ns)
    title_stmt = header.find('t:fileDesc/t:titleStmt', ns)
    E.SubElement(title_stmt, tag + 'author').text = 'Retained author'
    publication = header.find('t:fileDesc/t:publicationStmt', ns)
    E.SubElement(publication, tag + 'publisher').text = 'Retained publisher'
    availability = E.SubElement(publication, tag + 'availability')
    paragraph = E.SubElement(availability, tag + 'p')
    paragraph.text = 'Retained license: '
    E.SubElement(paragraph, tag + 'ref', target='https://example.org/license').text = 'License link'
    encoding = E.SubElement(header, tag + 'encodingDesc')
    prefixes = E.SubElement(encoding, tag + 'listPrefixDef')
    E.SubElement(prefixes, tag + 'prefixDef', ident='char', matchPattern='(.+)',
                 replacementPattern='https://example.org/chars#$1')
    profile = E.SubElement(header, tag + 'profileDesc')
    languages = E.SubElement(profile, tag + 'langUsage')
    E.SubElement(languages, tag + 'language', ident='eng').text = 'English'
    revision = E.SubElement(header, tag + 'revisionDesc')
    change = E.SubElement(revision, tag + 'change')
    E.SubElement(change, tag + 'date').text = '2007-10'
    E.SubElement(change, tag + 'label').text = 'Historical transcription'
    path = tmp_path / 'tcp-header.xml'
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    return path, case


def test_accepted_tcp_header_is_accounted_without_changing_sermon_rows(tmp_path, monkeypatch):
    import ocd_kernel.projection.categories.sermons as module

    path, case = _with_tcp_header(tmp_path)
    baseline = project(F / case['tei_file'], **case['context'])
    out = project(path, **case['context'], _allow_acceptance_metadata=True)
    assert out['rows'] == baseline['rows']
    inventory = out['receipt']['inventory']
    license_ref = next(row for row in inventory if row['attributes'].get('target') == 'https://example.org/license')
    assert {'ordinal': license_ref['ordinal'], 'reason': license_ref['role']} in out['receipt']['exclusions']
    assert 'License link' not in json.dumps(out['rows'])
    monkeypatch.setattr(module, 'project_sermons_document', lambda *a, **k: pytest.fail('checker called producer'))
    assert verify(path, out['rows'], out['receipt'], **case['context'], _allow_acceptance_metadata=True) == []
    changed = copy.deepcopy(out['receipt'])
    changed['exclusions'] = [item for item in changed['exclusions'] if item['ordinal'] != license_ref['ordinal']]
    assert verify(path, out['rows'], changed, **case['context'], _allow_acceptance_metadata=True)


def test_tcp_header_does_not_relax_ordinary_document_profile(tmp_path):
    path, case = _with_tcp_header(tmp_path)
    with pytest.raises(PipelineError):
        project(path, **case['context'])


@pytest.mark.parametrize('language', ['eng', '', 'not a language'])
def test_native_document_language_is_preserved_and_invalid_tags_rejected(tmp_path, language):
    case = CASES[0]
    path = tmp_path / 'language.xml'
    tree = E.parse(str(F / case['tei_file']))
    tree.find('{http://www.tei-c.org/ns/1.0}text').set('{http://www.w3.org/XML/1998/namespace}lang', language)
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    baseline = project(F / case['tei_file'], **case['context'])
    if language != 'eng':
        with pytest.raises(PipelineError, match='document language'):
            project(path, **case['context'])
        assert verify(path, baseline['rows'], baseline['receipt'], **case['context'])
    else:
        out = project(path, **case['context'])
        assert out['rows'] == baseline['rows']
        language_node = next(row for row in out['receipt']['inventory'] if row['tag'] == 'text')
        assert language_node['attributes']['{http://www.w3.org/XML/1998/namespace}lang'] == 'eng'
        assert {'ordinal': language_node['ordinal'], 'reason': 'source-document-language-retained-in-receipt'} in out['receipt']['warnings']
        assert verify(path, out['rows'], out['receipt'], **case['context']) == []


@pytest.mark.parametrize('mutation', ['unknown-header', 'body-license-reference'])
def test_tcp_header_support_keeps_unknown_features_and_body_references_closed(tmp_path, mutation):
    path, case = _with_tcp_header(tmp_path)
    out = project(path, **case['context'], _allow_acceptance_metadata=True)
    tree = E.parse(str(path))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    tag = '{' + ns['t'] + '}'
    if mutation == 'unknown-header':
        E.SubElement(tree.find('t:teiHeader', ns), tag + 'unsupportedMetadata').text = 'Do not silently accept'
    else:
        paragraph = tree.find('.//t:body/t:div/t:p', ns)
        assert paragraph is not None
        E.SubElement(paragraph, tag + 'ref', target='https://example.org/license').text = 'Not a scripture role'
    path.write_bytes(E.tostring(tree, encoding='utf-8'))
    with pytest.raises(PipelineError):
        project(path, **case['context'], _allow_acceptance_metadata=True)
    assert verify(path, out['rows'], out['receipt'], **case['context'], _allow_acceptance_metadata=True)


def test_bounded_primary_reference_is_independently_normalized(monkeypatch):
    from ocd_kernel.projection.categories import sermons
    case = CASES[0]
    path = F / case['tei_file']
    out = project(path, **case['context'])
    reference = out['rows'][0]['primary_reference']
    assert reference['raw'] == out['rows'][0]['primary_passage']
    assert reference['normalization_attribute'] == 'cRef'
    assert reference['scripture']['normalized']
    def forbidden(*args, **kwargs):
        raise AssertionError('checker called reference producer')
    monkeypatch.setattr(sermons, 'normalize_reference_record', forbidden)
    assert verify(path, out['rows'], out['receipt'], **case['context']) == []
    reference['scripture']['normalized'] = 'Gen.1.1'
    assert verify(path, out['rows'], out['receipt'], **case['context'])
