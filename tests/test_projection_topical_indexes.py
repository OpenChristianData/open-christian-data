"""Complete native topics, independent original-source proof, and corruption tests."""
import copy
import hashlib
import json
from pathlib import Path
import re

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.topical_indexes import project_topical_indexes_document as project, verify_topical_indexes_document as verify
from build.lib.tei_xsd import compiled_tei_schema

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / 'tests/fixtures/library-pipeline/categories/topical-indexes'
CASES = json.loads((F / 'manifest.json').read_text(encoding='utf-8'))['cases']
NS = {'t': 'http://www.tei-c.org/ns/1.0'}


def norm(node):
    return ' '.join(''.join(node.xpath('.//text()')).split())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_complete_topics_match_native_source_boundaries_and_references(case):
    out = project(F / case['tei_file'], **case['context'])
    for name, digest in case['files'].items(): assert hashlib.sha256((F / name).read_bytes()).hexdigest() == digest
    expected = []
    if case['name'] == 'torrey':
        source = [json.loads(line) for line in (F / case['retained_file']).read_text(encoding='utf-8').splitlines()]
        for record in source:
            items = []
            for value in record['definitions']:
                # Independent literal suffix oracle: no verse resolution or invented groups.
                match = re.search(r'--(.*)$', value)
                refs = [{'kind': 'source-reference-run', 'label': ' '.join(match[1].split()), 'target': None}] if match else []
                items.append({'text': ' '.join(value.split()), 'references': refs})
            expected.append((record['term'], items))
    else:
        source = E.parse(str(F / case['retained_file']))
        for entry in source.xpath('/sourceExcerpt/entryFree'):
            markup = E.tostring(entry.find('def'), encoding='unicode', with_tail=False)
            chunks = re.split(r'<lb\s*/>', markup)
            assert re.fullmatch(r'<def>\s*', chunks[0])
            items = []
            for chunk in chunks[1:]:
                fragment = E.fromstring(('<sample>' + chunk.removesuffix('</def>') + '</sample>').encode())
                refs = [{'kind': 'scripture' if r.get('osisRef') else 'topic', 'label': norm(r), 'target': r.get('osisRef') or r.get('target')} for r in fragment.xpath('ref')]
                items.append({'text': norm(fragment), 'references': refs})
            expected.append((entry.get('n'), items))
    assert len(out['rows']) == len(expected) == 2
    for row, (topic, items), selected in zip(out['rows'], expected, case['selected_units'], strict=True):
        assert row['category'] == 'topical_indexes'
        assert row['topic'] == selected['topic'] == topic
        assert row['locator'] == {'kind': 'topic', 'heading': topic}
        assert row['items'] == items
        assert len(items) == selected['items']
        assert row['text'] == '\n\n'.join(i['text'] for i in items)
    assert verify(F / case['tei_file'], out['rows'], out['receipt'], **case['context']) == []


@pytest.mark.requires_local_artifacts
def test_original_sources_and_complete_censuses_match_independent_decoders():
    from build.tei.naves_topical_bible_oracle import _inflate_source

    for case in CASES:
        for path, digest in case['source_bindings'].items(): assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        if case['name'] == 'torrey':
            path = ROOT / next(iter(case['source_bindings']))
            lines = path.read_bytes().splitlines(keepends=True)
            assert (F / case['retained_file']).read_bytes() == b''.join(lines[:2])
            assert len(lines) == len(case['source_unit_census']) == 623
            for i, (line, entry) in enumerate(zip(lines, case['source_unit_census'], strict=True), 1):
                record = json.loads(line)
                assert entry == {'ordinal': i, 'topic': record['term'], 'definition_count': len(record['definitions']), 'record_sha256': hashlib.sha256(line).hexdigest(), 'disposition': 'selected-complete-topic' if i <= 2 else 'outside-bounded-selection'}
        else:
            native = ROOT / 'raw/naves_topical/modules/lexdict/zld/nave'
            _, records = _inflate_source(*(native.joinpath(n).read_bytes() for n in ('dict.idx', 'dict.dat', 'dict.zdx', 'dict.zdt')))
            assert len(records) == len(case['source_unit_census']) == 5322
            for record, entry in zip(records, case['source_unit_census'], strict=True):
                assert entry == {'ordinal': record['ordinal'], 'topic': record['dictionary_key'], 'payload_sha256': record['payload_body_sha256'], 'disposition': 'selected-complete-topic' if record['ordinal'] <= 2 else 'outside-bounded-selection'}
            excerpts = E.parse(str(F / case['retained_file'])).xpath('/sourceExcerpt/entryFree')
            for original, excerpt in zip(records[:2], excerpts, strict=True):
                assert E.tostring(E.fromstring(original['payload']), method='c14n') == E.tostring(excerpt, method='c14n')


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_topical_tei_passes_bundled_p5(case):
    compiled_tei_schema(ROOT / 'ocd_kernel/tei/vendor/xsd/tei_all.xsd').assertValid(E.parse(str(F / case['tei_file'])))


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
@pytest.mark.parametrize('change', ['omit', 'duplicate', 'order', 'topic', 'locator', 'text', 'item-loss', 'item-order', 'reference-loss', 'reference-target', 'reference-role', 'inferred-topic', 'provenance'])
def test_semantic_corruption_fails_despite_consistent_output_receipt(case, change):
    out = project(F / case['tei_file'], **case['context']); rows = out['rows']; row = rows[0]
    if change == 'omit': rows.pop()
    elif change == 'duplicate': rows.append(copy.deepcopy(rows[-1]))
    elif change == 'order': rows.reverse()
    elif change == 'topic': row['topic'] = 'Invented topic'
    elif change == 'locator': row['locator']['heading'] = 'Invented locator'
    elif change == 'text': row['text'] += ' Invented words.'
    elif change == 'item-loss': row['items'].pop()
    elif change == 'item-order': row['items'].reverse()
    elif change == 'reference-loss': row['items'][0]['references'].pop()
    elif change == 'reference-target': row['items'][0]['references'][0]['target'] = 'Invented.1.1'
    elif change == 'reference-role': row['items'][0]['references'][0]['kind'] = 'topic'
    elif change == 'inferred-topic': row['theme'] = 'Invented theme'
    elif change == 'provenance': row['provenance']['edition_title'] = 'Another source'
    for i, row in enumerate(rows, 1): row['sequence'] = i
    out['receipt']['row_count'] = len(rows)
    out['receipt']['output_sha256'] = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for row, anchor in zip(rows, out['receipt']['anchors']): anchor['text_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
    assert any('correspondence' in e for e in verify(F / case['tei_file'], rows, out['receipt'], **case['context']))


@pytest.mark.parametrize('field', ['scope', 'mapping_version', 'master_sha256', 'schema_sha256', 'common_schema_sha256', 'output_sha256', 'row_count', 'anchors', 'inventory', 'warnings', 'exclusions', 'unsupported', 'independent_check'])
def test_every_private_receipt_claim_is_checked(field):
    case = CASES[0]; out = project(F / case['tei_file'], **case['context'])
    out['receipt'][field] = {'status': 'passed'} if field == 'independent_check' else 'forged'
    assert verify(F / case['tei_file'], out['rows'], out['receipt'], **case['context'])


@pytest.mark.parametrize('change', ['table', 'attribute', 'namespace', 'loose', 'duplicate-id', 'order', 'empty-topic', 'empty-reference', 'unknown-reference', 'prolog-pi', 'epilog-pi'])
def test_unsupported_structure_fails_visibly(change, tmp_path):
    case = CASES[0]; path = F / case['tei_file']; tree = E.parse(str(path)); units = tree.xpath('//t:body/t:div', namespaces=NS); unit = units[0]
    if change == 'table': E.SubElement(unit, '{' + NS['t'] + '}table')
    elif change == 'attribute': unit.set('ana', 'invented')
    elif change == 'namespace': unit.tag = '{urn:wrong}div'
    elif change == 'loose': unit.text = 'Unmapped words.'
    elif change == 'duplicate-id': units[1].set('{http://www.w3.org/XML/1998/namespace}id', unit.get('{http://www.w3.org/XML/1998/namespace}id'))
    elif change == 'order': unit.append(unit[0])
    elif change == 'empty-topic': unit[0].text = None
    elif change == 'empty-reference': unit.xpath('.//t:ref', namespaces=NS)[0].text = None
    elif change == 'unknown-reference': unit.xpath('.//t:ref', namespaces=NS)[0].set('type', 'inferred')
    raw = E.tostring(tree)
    if change == 'prolog-pi': raw = b'<?hidden test?>' + raw
    elif change == 'epilog-pi': raw += b'<?hidden test?>'
    changed = tmp_path / 'bad.xml'; changed.write_bytes(raw)
    with pytest.raises(PipelineError): project(changed, **case['context'])
    out = project(path, **case['context'])
    assert verify(changed, out['rows'], out['receipt'], **case['context'])


def test_checker_does_not_call_producer(monkeypatch):
    import ocd_kernel.projection.categories.topical_indexes as module
    case = CASES[0]; out = project(F / case['tei_file'], **case['context'])
    monkeypatch.setattr(module, 'project_topical_indexes_document', lambda *a, **k: (_ for _ in ()).throw(AssertionError('producer called')))
    assert verify(F / case['tei_file'], out['rows'], out['receipt'], **case['context']) == []


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("ti")


def accepted_topic_fixture(tmp_path):
    category = "topical-indexes"
    """Real source/TEI, with explicitly simulated acceptance evidence in temp only."""
    from ocd_kernel.tei.acceptance import build_acceptance_record,write_acceptance,make_file_binding
    f=F
    case=CASES[0]
    logical,digest=next(iter(case['source_bindings'].items()))
    m={'context':case['context'],'source_title':case['title'],'source_path':logical,'source_sha256':digest}
    identity={**m['context']['identity'],'acquisition_id':'fixture-retained-topics'}
    base=tmp_path/'f';edition=base/'library/works'/identity['work_id']/'forms'/identity['textual_form_id']/'editions'/identity['edition_id']
    edition.mkdir(parents=True)
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    work={'schema_version':'2.0','work_id':identity['work_id'],'title':m['source_title'],'textual_forms':[{'textual_form_id':identity['textual_form_id'],'editions':[{'edition_id':identity['edition_id'],'title':m['source_title'],'language':'en','category':category}]}],'evidence':['fixture://torrey']}
    write(base/'library/works'/identity['work_id']/'work.json',work)
    write(base/'library/works'/identity['work_id']/'state.json',{'schema_version':'2.0','work_id':identity['work_id'],'targets':[{'target_id':identity['edition_id'],'target_type':'edition','stage':'review','updated_at':'2026-09-08T00:00:00Z','evidence':['candidate.xml']}]})
    retained=base/'retained/excerpt.xml';retained.parent.mkdir();retained.write_bytes((f/case['retained_file']).read_bytes())
    included={'path':'retained/excerpt.xml','sha256':hashlib.sha256(retained.read_bytes()).hexdigest(),'bytes':retained.stat().st_size,'scope':'selected complete topic records listed in fixture manifest'}
    source={'source_path':m['source_path'],'source_sha256':m['source_sha256'],'source_bytes':(ROOT/logical).stat().st_size,'source_scope':'Torrey retained JSONL'}
    acquisition={'schema_version':'2.0','acquisition_id':identity['acquisition_id'],'edition_id':identity['edition_id'],'provider':'retained fixture witness','url':'fixture://torrey',**source,'retained_files':[{**included,'media_type':'application/xml'}],'route':'born-digital'}
    write(edition/'acquisitions'/f"{identity['acquisition_id']}.json",acquisition)
    scope={'kind':'member','declared':included['scope'],'expected_members':[{'path':included['path'],'position':1}],'included_members':[{**included,'position':1}],'excluded_members':[]}
    tree=E.parse(str(f/case['tei_file']));ns='http://www.tei-c.org/ns/1.0';header=tree.find('{'+ns+'}teiHeader');sd=header.find('.//{'+ns+'}sourceDesc')
    b=E.SubElement(sd,'{'+ns+'}bibl');E.SubElement(b,'{'+ns+'}ptr',target=acquisition['url'])
    facts={**identity,'source_sha256':source['source_sha256'],'source_bytes':str(source['source_bytes']),'sha256':included['sha256'],'representation_revision':'fixture-v1'}
    for key,value in facts.items():E.SubElement(b,'{'+ns+'}idno',type=key).text=value
    E.SubElement(b,'{'+ns+'}note',type='source-location').text=source['source_path']
    E.SubElement(b,'{'+ns+'}note',type='source-scope').text=scope['declared']
    rd=E.SubElement(header,'{'+ns+'}revisionDesc');change=E.SubElement(rd,'{'+ns+'}change',when='2026-09-08');change.set('{http://www.w3.org/XML/1998/namespace}id','fixture-v1');change.text='Bound category fixture.'
    candidate=base/'candidate.xml';candidate.write_bytes(E.tostring(tree,encoding='utf-8'))
    binding=make_file_binding(base,candidate)
    accounting={'contract':'ocd-source-accounting-v1','identity':identity,'source':source,'source_sha256':source['source_sha256'],'source_bytes':source['source_bytes'],'scope':source['source_scope'],'accepted_scope':{'kind':'member','declared':scope['declared']},**{k:scope[k] for k in ['expected_members','included_members','excluded_members']},'missing_members':[],'unknown_members':[]}
    source_accounting=base/'evidence/source-accounting.json';write(source_accounting,accounting)
    technical={'producer':{'id':'producer:category-fixture'},'checker':{'id':'checker:category-fixture'},'shared_assumptions':['Synthetic acceptance labels test the authority API only.'],'independent_corroboration':'Separate source-derived category tests prove the real selected text.'}
    for name in ['validation','accounting','fidelity','reproducibility','schema','closure']:
        path=base/'evidence'/f'{name}.json';doc={'contract':f'ocd-tei-{name}-v1','identity':identity,'source':source,'candidate':binding,'scope':scope['declared'],'status':'pass','command':'simulated-acceptance-api-fixture','exit_code':0,**{k:scope[k] for k in ['expected_members','included_members','excluded_members']},'missing_members':[],'unknown_members':[]}
        if name=='accounting':doc['accepted_scope']={'kind':'member','declared':scope['declared']}
        write(path,doc);technical[name]={'path':path,'status':'pass','command':'simulated-acceptance-api-fixture','exit_code':0}
    coverage={'status':'partial','declared':scope['declared'],'reached':[scope['declared']],'inspected':[scope['declared']+'/API-fixture'],'unreviewed':['visual acceptance']}
    review={'reviewer':'agent:category-fixture','reviewed_at':'2026-09-08T00:00:00Z','coverage':coverage,'source_quality_uncertainty':['outside selected scope'],'discrepancies':[],'unreviewed_residuals':['visual acceptance not performed']}
    review_path=base/'evidence/review.json';write(review_path,{'contract':'ocd-tei-review-v1','identity':identity,'source':source,'candidate':binding,'scope':scope['declared'],**review})
    decision={'source_local_disposition':'API simulation only','blockers':[],'agent_assessment':{'status':'accepted','actor':'agent:category-fixture','assessed_at':'2026-09-08T00:00:00Z','supported_scope':scope['declared'],'unassessed_stronger_claims':['real acceptance'],'unresolved_claims':[]},'human_decision':{'status':'not-recorded'}}
    record=build_acceptance_record(base,identity=identity,candidate_path=candidate,source_accounting_path=source_accounting,scope=scope,technical=technical,review={**review,'report_path':review_path},representation_revision={'id':'fixture-v1','date':'2026-09-08','note':'Bound category fixture.'},decision=decision,missing_members=[],unknown_members=[])
    path=edition/'acceptance.json';write_acceptance(path,record)
    return base,path



@pytest.mark.requires_local_artifacts
def test_accepted_topic_entry_derives_context_and_rejects_forged_authority(tmp_path):
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.projection.categories.topical_indexes import project_accepted_topical_indexes, verify_accepted_topical_indexes
    root, acceptance = accepted_topic_fixture(tmp_path)
    with pytest.raises(PipelineError, match='promoted'):
        project_accepted_topical_indexes(root, acceptance_path=acceptance)
    promoted = promote_accepted_master(root, acceptance_path=acceptance, destination=tmp_path/'out')
    out = project_accepted_topical_indexes(tmp_path/'out', acceptance_path=promoted.acceptance_path)
    assert verify_accepted_topical_indexes(tmp_path/'out', acceptance_path=promoted.acceptance_path, rows=out['rows'], receipt=out['receipt']) == []
    out['receipt']['authority']['master']['sha256'] = '0'*64
    assert verify_accepted_topical_indexes(tmp_path/'out', acceptance_path=promoted.acceptance_path, rows=out['rows'], receipt=out['receipt'])


@pytest.mark.parametrize('mutation', ['none', 'drop', 'change', 'move'])
def test_explicit_item_label_preserves_attachment(tmp_path, mutation):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    item = tree.xpath('//t:body/t:div/t:list/t:item', namespaces=NS)[0]
    label = E.Element('{'+NS['t']+'}label')
    label.text = 'Explicit heading'
    label.tail = item.text
    item.text = None
    item.insert(0, label)
    path = tmp_path / 'label.xml'
    tree.write(str(path), encoding='utf-8')
    out = project(path, **case['context'])
    assert out['rows'][0]['items'][0]['label'] == 'Explicit heading'
    assert out['rows'][0]['items'][0]['text'].startswith('Explicit heading')
    assert verify(path, out['rows'], out['receipt'], **case['context']) == []
    from ocd_kernel.release.features import configuration_features
    from ocd_kernel.release.typed_rows import encode_rows, check_rows
    features = configuration_features(out['rows'])
    check_rows(encode_rows(out['rows'], features), out['rows'], features)
    rows = copy.deepcopy(out['rows'])
    first = rows[0]['items'][0]
    if mutation == 'drop': del first['label']
    elif mutation == 'change': first['label'] = 'Invented'
    elif mutation == 'move': rows[0]['items'][1]['label'] = first.pop('label')
    if mutation != 'none':
        assert any('topical correspondence' in error for error in verify(path, rows, out['receipt'], **case['context']))


@pytest.mark.parametrize('invalid', ['empty', 'multiple', 'after-text'])
def test_invalid_explicit_item_label_fails_both_routes(tmp_path, invalid):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    item = tree.xpath('//t:body/t:div/t:list/t:item', namespaces=NS)[0]
    label = E.Element('{'+NS['t']+'}label')
    label.text = ' ' if invalid == 'empty' else 'Heading'
    label.tail = item.text
    item.text = 'Before' if invalid == 'after-text' else None
    item.insert(0, label)
    if invalid == 'multiple': item.insert(1, copy.deepcopy(label))
    path = tmp_path / 'invalid-label.xml'
    tree.write(str(path), encoding='utf-8')
    with pytest.raises(PipelineError, match='item label'):
        project(path, **case['context'])
    out = project(F / case['tei_file'], **case['context'])
    assert any('item label' in error for error in verify(path, out['rows'], out['receipt'], **case['context']))


@pytest.mark.parametrize('mutation', ['none', 'drop', 'swap', 'move', 'empty', 'untyped'])
def test_explicit_alternative_topics_preserve_role_order_and_attachment(tmp_path, mutation):
    case = CASES[0]
    tree = E.parse(str(F / case['tei_file']))
    unit = tree.xpath('//t:body/t:div', namespaces=NS)[0]
    for index, text in enumerate(['Alternate label', 'Another label'], 1):
        head = E.Element('{'+NS['t']+'}head', type='alternate')
        head.text = text
        unit.insert(index, head)
    if mutation == 'empty': unit[1].text = ' '
    if mutation == 'untyped': del unit[1].attrib['type']
    path = tmp_path / 'alternate-topics.xml'
    tree.write(str(path), encoding='utf-8')
    if mutation in ('empty', 'untyped'):
        with pytest.raises(PipelineError, match='alternate topic heading'):
            project(path, **case['context'])
        original = project(F / case['tei_file'], **case['context'])
        assert any('alternate topic heading' in e for e in verify(path, original['rows'], original['receipt'], **case['context']))
        return
    out = project(path, **case['context'])
    assert out['rows'][0]['alternative_topics'] == ['Alternate label', 'Another label']
    assert 'alternative_topics' not in out['rows'][1]
    assert verify(path, out['rows'], out['receipt'], **case['context']) == []
    if mutation == 'drop': del out['rows'][0]['alternative_topics']
    elif mutation == 'swap': out['rows'][0]['alternative_topics'].reverse()
    elif mutation == 'move': out['rows'][1]['alternative_topics'] = out['rows'][0].pop('alternative_topics')
    else: return
    assert any('topical correspondence' in e for e in verify(path, out['rows'], out['receipt'], **case['context']))
