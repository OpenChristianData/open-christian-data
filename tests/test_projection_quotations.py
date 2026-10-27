"""PIPE-008 real repeated quotation occurrences and source-derived challenges."""
import copy
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

from lxml import etree as E
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.quotations import project_quotations_document as project, verify_quotations_document as verify
from build.lib.tei_xsd import compiled_tei_schema

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ORACLE = ROOT / 'plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-008/verify_original_source.py'
FIXTURE = ROOT / 'tests/fixtures/library-pipeline/categories/quotations'
MANIFEST = json.loads((FIXTURE / 'manifest.json').read_text(encoding='utf-8'))
PATH = FIXTURE / 'master.tei.xml'
CONTEXT = MANIFEST['context']


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp('cq')


def norm(node):
    return ' '.join(''.join(node.xpath('.//text()')).split())


@pytest.mark.requires_local_artifacts
@pytest.mark.parametrize('category,change', [
    ('quotations', 'number'), ('quotations', 'number-removed'),
    ('quotations', 'paragraph'), ('quotations', 'heading'),
    ('devotionals', 'number'), ('devotionals', 'date'),
    ('devotionals', 'date-removed'), ('devotionals', 'date-invented'),
    ('devotionals', 'heading'),
])
def test_original_source_oracle_rejects_locator_attribute_drift(tmp_path, category, change):
    path = FIXTURE.parent / category / 'master.tei.xml'
    tree = E.parse(str(path))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    unit = tree.xpath('//t:body/t:div', namespaces=ns)[0]
    expected = change.split('-')[0]
    if change == 'number':
        unit.set('n', 'invented')
    elif change == 'number-removed':
        del unit.attrib['n']
    elif change == 'paragraph':
        unit.find('t:cit', ns).set('n', '999')
        expected = 'paragraph position'
    elif change == 'heading':
        # Keep the real heading text in the unit: a substring check is insufficient.
        unit.find('t:head', ns).text += ' Invented title.'
    elif change == 'date':
        unit.find('t:dateline/t:date', ns).text = '12-25'
    elif change == 'date-removed':
        unit.remove(unit.find('t:dateline', ns))
    else:
        unit = tree.xpath('//t:body/t:div[not(t:dateline)]', namespaces=ns)[0]
        dateline = E.SubElement(unit, '{'+ns['t']+'}dateline')
        E.SubElement(dateline, '{'+ns['t']+'}date').text = '01-01'
    changed = tmp_path / 'attribute-drift.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8'))
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--category', category, '--tei-path', str(changed)],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=False,
    )
    assert completed.returncode != 0
    assert f'source {expected} mapping differs' in completed.stdout + completed.stderr


def forged_receipt(result):
    receipt = result['receipt']
    receipt['row_count'] = len(result['rows'])
    receipt['output_sha256'] = hashlib.sha256(json.dumps(result['rows'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    receipt['independent_check'] = {'status':'pending'}
    for row, anchor in zip(result['rows'],receipt['anchors']):
        anchor['record_id'] = row['record_id']
        anchor['text_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
    return receipt


@pytest.mark.requires_local_artifacts
@pytest.mark.parametrize('category,change', [
    ('quotations', 'author'), ('quotations', 'work'),
    ('devotionals', 'rendition'), ('devotionals', 'rendition-removed'),
    ('devotionals', 'reading-title'),
])
def test_original_source_oracle_rejects_invented_labels_and_rendition(tmp_path, category, change):
    tree = E.parse(str(FIXTURE.parent/category/'master.tei.xml'))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    if change in {'author', 'work', 'reading-title'}:
        bibl = tree.xpath('//t:body/t:div/t:cit/t:bibl', namespaces=ns)[0]
        name = 'author' if change == 'author' else 'title'
        E.SubElement(bibl, '{'+ns['t']+'}'+name).text = 'Invented label'
        expected = 'source citation labels mapping differs' if category == 'quotations' else 'ordered source reading pairs differ'
    else:
        line = tree.xpath('//t:body/t:div/t:lg/t:l[@rend]', namespaces=ns)[0]
        if change == 'rendition':
            line.set('rend', 'invented-rend')
        else:
            del line.attrib['rend']
        expected = 'source verse rendition mapping differs'
    changed = tmp_path/'label-drift.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8'))
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--category', category, '--tei-path', str(changed)],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=False,
    )
    assert completed.returncode != 0
    assert expected in completed.stdout + completed.stderr


def test_real_source_oracle_and_closed_schema():
    out = project(PATH, **CONTEXT)
    for name, digest in MANIFEST['files'].items():
        assert hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest() == digest
    source = E.parse(str(FIXTURE/'retained.xml'))
    native = source.xpath('/sourceExcerpt/div2')
    assert len(out['rows']) == len(native) == 5
    assert [x['id'] for x in MANIFEST['selected_units']] == [x.get('id') for x in native]
    for row, node in zip(out['rows'],native):
        if node.get('id')=='d0710pm':
            p=node.xpath('p[@id="d0710pm-p3"]')[0]
            match=re.search(r'aphorism of ([^,]+), (“[^”]+”)',''.join(p.itertext()))
            assert match
            expected_text=match.group(2);citation={'author':match.group(1),'work':None,'locus':None}
        else:
            p=node.xpath('p[@class="passage"]')[0];expected_text=norm(p)
            citation={'author':None,'work':None,'locus':norm(node.xpath('h3[@class="scripPassage"]')[0])}
        assert row['text']==expected_text
        assert row['citation']==citation
        assert row['locator'] == {'kind':'quotation','number':node.get('n'),'heading':norm(node.find('h2')),'paragraph':list(node.findall('p')).index(p)+1}
        assert row['provenance']['edition_title'] == MANIFEST['source_title']
    # Two genuinely repeated source quotations retain separate occurrence identities.
    assert out['rows'][0]['text'] == out['rows'][3]['text']
    assert out['rows'][1]['text'] == out['rows'][4]['text']
    assert len({r['record_id'] for r in out['rows']}) == 5
    assert verify(PATH,out['rows'],out['receipt'],**CONTEXT) == []
    assert out['receipt']['independent_check']['status'] == 'pending'
    assert len(MANIFEST['unit_census']) == MANIFEST['source_unit_count']
    assert sum(x['disposition']=='selected' for x in MANIFEST['unit_census']) == 5


def test_missing_source_container_labels_remain_nullable_without_losing_occurrence_position(tmp_path):
    """Mutate a controlled TEI copy from the retained fixture; occurrence and cit@n stay bound."""
    baseline = project(PATH, **CONTEXT)
    tree = E.parse(str(PATH))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    unit = tree.xpath('//t:body/t:div[1]', namespaces=ns)[0]
    heading = unit.find('{http://www.tei-c.org/ns/1.0}head')
    assert heading is not None
    unit.remove(heading)
    unit.attrib.pop('n', None)
    changed = tmp_path / 'missing-container-labels.tei.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))

    out = project(changed, **CONTEXT)
    row = out['rows'][0]
    assert row['record_id'] == baseline['rows'][0]['record_id']
    assert row['sequence'] == 1
    assert row['locator'] == {'kind': 'quotation', 'number': None, 'heading': None, 'paragraph': 2}
    assert row['text'] == baseline['rows'][0]['text']
    assert verify(changed, out['rows'], out['receipt'], **CONTEXT) == []

    blank_number = E.parse(str(PATH))
    blank_number.xpath('//t:body/t:div[1]', namespaces=ns)[0].set('n', '   ')
    blank_number_path = tmp_path / 'blank-container-number.tei.xml'
    blank_number_path.write_bytes(E.tostring(blank_number, encoding='utf-8', xml_declaration=True))
    with pytest.raises(PipelineError, match='native unit type/identity/number'):
        project(blank_number_path, **CONTEXT)
    blank_number_errors = verify(blank_number_path, baseline['rows'], baseline['receipt'], **CONTEXT)
    assert any('native identity' in error for error in blank_number_errors)

    blank_heading = E.parse(str(PATH))
    heading = blank_heading.xpath('//t:body/t:div[1]/t:head', namespaces=ns)[0]
    for child in list(heading):
        heading.remove(child)
    heading.text = '   '
    blank_heading_path = tmp_path / 'blank-container-heading.tei.xml'
    blank_heading_path.write_bytes(E.tostring(blank_heading, encoding='utf-8', xml_declaration=True))
    with pytest.raises(PipelineError, match='supplied heading'):
        project(blank_heading_path, **CONTEXT)
    blank_heading_errors = verify(blank_heading_path, baseline['rows'], baseline['receipt'], **CONTEXT)
    assert any('supplied heading' in error for error in blank_heading_errors)


def test_fixture_is_valid_tei_p5():
    compiled_tei_schema(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd').assertValid(E.parse(str(PATH)))


@pytest.mark.requires_local_artifacts
def test_original_source_oracle_rejects_dropped_inline_mapping(tmp_path):
    tree = E.parse(str(PATH))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    feature = tree.xpath('//t:body/t:div[1]//t:hi', namespaces=ns)[0]
    parent = feature.getparent()
    index = parent.index(feature)
    replacement = ''.join(feature.itertext()) + (feature.tail or '')
    if index:
        parent[index - 1].tail = (parent[index - 1].tail or '') + replacement
    else:
        parent.text = (parent.text or '') + replacement
    parent.remove(feature)
    changed = tmp_path / 'missing-inline.tei.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--category', 'quotations', '--tei-path', str(changed)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    assert completed.returncode != 0
    assert 'inline feature mapping differs' in (completed.stdout + completed.stderr)


@pytest.mark.requires_local_artifacts
@pytest.mark.parametrize('mutation', ['append', 'reorder'])
def test_original_source_oracle_rejects_source_text_or_order_drift(tmp_path, mutation):
    tree = E.parse(str(PATH))
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    if mutation == 'append':
        quote = tree.xpath('//t:body/t:div[1]/t:cit/t:quote', namespaces=ns)[0]
        if len(quote):
            quote[-1].tail = (quote[-1].tail or '') + ' Invented source text.'
        else:
            quote.text = (quote.text or '') + ' Invented source text.'
    else:
        body = tree.xpath('/t:TEI/t:text/t:body', namespaces=ns)[0]
        first, second = list(body)[:2]
        body.remove(second)
        body.insert(body.index(first), second)
    changed = tmp_path / f'{mutation}-source-drift.tei.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--category', 'quotations', '--tei-path', str(changed)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert any(message in output for message in ('block text mapping differs', 'mapped source text missing'))


@pytest.mark.parametrize('mutation',['omit','duplicate','reverse','text','number','heading','collapse','invent-author','invent-work','cited-id','context','private','warning','exclusion','inventory','unsupported','source','policy'])
def test_forged_internal_consistency_cannot_hide_source_drift(mutation):
    out=project(PATH,**CONTEXT); rows=out['rows']
    if mutation=='omit':rows.pop()
    elif mutation=='duplicate':rows.append(copy.deepcopy(rows[-1]))
    elif mutation=='reverse':rows.reverse()
    elif mutation=='text':rows[0]['text']+=' Made up.'
    elif mutation in ('number','heading'):rows[0]['locator'][mutation]='Invented'
    elif mutation=='collapse':out['rows']=rows[:2]
    elif mutation=='invent-author':rows[0]['citation']['author']='Unknown author'
    elif mutation=='invent-work':rows[0]['citation']['work']='Invented work'
    elif mutation=='cited-id':rows[0]['citation']['work_id']='invented'
    elif mutation=='context':rows[0]['context']='vague'
    elif mutation=='private':rows[0]['provenance']['source_path']='raw/private.xml'
    elif mutation=='warning':out['receipt']['warnings']=[]
    elif mutation=='exclusion':out['receipt']['exclusions']=[]
    elif mutation=='inventory':out['receipt']['inventory'].pop()
    elif mutation=='unsupported':out['receipt']['unsupported']=['hidden']
    elif mutation=='source':out['receipt']['master_sha256']='0'*64
    elif mutation=='policy':out['receipt']['policy_sha256']='0'*64
    for i,row in enumerate(out['rows'],1):row['sequence']=i
    assert verify(PATH,out['rows'],forged_receipt(out),**CONTEXT)


@pytest.mark.parametrize('change',['table','attribute','loose','duplicate-id','namespace','doctype','prolog-pi','epilog-pi','inner-order','paragraph-number'])
def test_unsupported_input_fails_both_routes(change,tmp_path):
    root=E.parse(str(PATH));n={'t':'http://www.tei-c.org/ns/1.0'};d=root.xpath('//t:body/t:div',namespaces=n)
    if change=='table':E.SubElement(d[0],'{'+n['t']+'}table')
    elif change=='attribute':d[0].set('ana','invented')
    elif change=='loose':d[0].text='Unmapped words'
    elif change=='duplicate-id':d[1].set('{http://www.w3.org/XML/1998/namespace}id',d[0].get('{http://www.w3.org/XML/1998/namespace}id'))
    elif change=='namespace':d[0].tag='{urn:wrong}div'
    elif change=='inner-order':d[0].append(d[0][0])
    elif change=='paragraph-number':d[0][1].set('n','not-a-number')
    raw=E.tostring(root,encoding='utf-8')
    if change=='doctype':raw=b'<!DOCTYPE TEI [<!ENTITY x "danger">]>'+raw
    elif change=='prolog-pi':raw=b'<?reader hidden?>'+raw
    elif change=='epilog-pi':raw+=b'<?reader hidden?>'
    p=tmp_path/'bad.xml';p.write_bytes(raw)
    out=project(PATH,**CONTEXT)
    with pytest.raises(PipelineError):project(p,**CONTEXT)
    assert verify(p,out['rows'],out['receipt'],**CONTEXT)


@pytest.mark.parametrize('bad_number',['007','+7',' 7 ','٧'])
def test_noncanonical_citation_numbers_fail_both_routes(bad_number,tmp_path):
    root=E.parse(str(PATH));n={'t':'http://www.tei-c.org/ns/1.0'}
    citation=root.xpath('//t:body/t:div[1]/t:cit',namespaces=n)[0]
    citation.set('n',bad_number)
    changed=tmp_path/'bad-citation-number.xml';changed.write_bytes(E.tostring(root,encoding='utf-8',xml_declaration=True))
    out=project(PATH,**CONTEXT)
    with pytest.raises(PipelineError,match='quotation paragraph number'):project(changed,**CONTEXT)
    errors=verify(changed,out['rows'],out['receipt'],**CONTEXT)
    assert any('quotation paragraph number' in error for error in errors)


def test_checker_does_not_call_producer(monkeypatch):
    out=project(PATH,**CONTEXT)
    import ocd_kernel.projection.categories.quotations as m
    monkeypatch.setattr(m,'project_quotations_document',lambda *a,**k: (_ for _ in ()).throw(AssertionError('producer called')))
    assert verify(PATH,out['rows'],out['receipt'],**CONTEXT)==[]


@pytest.mark.parametrize('category',['quotations','devotionals'])
@pytest.mark.parametrize('forged',[{'status':'passed'},'passed',{'status':'pending','rights_cleared':True}])
def test_receipt_cannot_smuggle_approval(category,forged):
    import importlib
    module=importlib.import_module('ocd_kernel.projection.categories.'+category)
    f=ROOT/'tests/fixtures/library-pipeline/categories'/category
    m=json.loads((f/'manifest.json').read_text(encoding='utf-8'));p=f/'master.tei.xml'
    out=getattr(module,'project_'+category+'_document')(p,**m['context'])
    out['receipt']['independent_check']=forged
    assert any('independent_check' in e for e in getattr(module,'verify_'+category+'_document')(p,out['rows'],out['receipt'],**m['context']))


@pytest.mark.parametrize('category',['quotations','devotionals'])
def test_complete_selected_node_accounting_and_unselected_limits(category):
    f=ROOT/'tests/fixtures/library-pipeline/categories'/category
    m=json.loads((f/'manifest.json').read_text(encoding='utf-8'))
    units=E.parse(str(f/'retained.xml')).xpath('/sourceExcerpt/div2')
    assert [d.get('id') for d in units]==[d['id'] for d in m['selected_units']]
    selected=[d for d in m['unit_census'] if d['disposition']=='selected']
    assert len(selected)==len(units)
    assert [d['id'] for d in selected]==[d.get('id') for d in units]
    for node,record in zip(units,m['selected_units']):
        assert [(x.tag,dict(x.attrib)) for x in node.iter()]==[(x['tag'],x['attributes']) for x in record['node_accounting']]
        assert record['source_heading']==norm(node.find('h2'))
        assert record['source_number']==node.get('n')
        assert record['selection_reason']
        if record['quote_span']:
            span=record['quote_span'];p=node.xpath('p[@id=$i]',i=span['source_paragraph_id'])[0];text=''.join(p.itertext())
            assert hashlib.sha256(text.encode()).hexdigest()==span['source_text_sha256']
            assert text[span['start']:span['end']]==record['source_quote']
            assert span['author_literal'] in text
        else:
            heading=node.xpath('h3[@class="scripPassage"]')[0]
            opening=heading.xpath('preceding-sibling::*[not(self::scripCom)][1]')[0] if category=='devotionals' else node.xpath('p[@class="passage"]')[0]
            assert record['source_quote']==norm(opening)
            assert record['source_locus']==norm(node.xpath('h3[@class="scripPassage"]')[0])
    assert all(d['support_assessment']=='not assessed; not sampled' for d in m['unit_census'] if d['disposition']!='selected')


def test_named_author_partial_mapping_accounts_unselected_descendants():
    record = next(item for item in MANIFEST['selected_units'] if item['id'] == 'd0710pm')
    ledger = {item['xpath']: item for item in record['node_accounting']}
    assert ledger['/ThML/ThML.body/div1[8]/div2[20]/h3']['disposition'] == 'outside-quotation-scope'
    assert ledger['/ThML/ThML.body/div1[8]/div2[20]/h3/scripRef']['disposition'] == 'outside-quotation-scope'
    assert all(
        item['disposition'] == 'outside-quotation-scope'
        for item in record['node_accounting']
        if item['xpath'].startswith('/ThML/ThML.body/div1[8]/div2[20]/p[3]/i')
    )
    assert {item['target'] for item in record['mapped_text_spans']} == {'quote', 'author'}
    paragraph = E.parse(str(FIXTURE / 'retained.xml')).xpath('/sourceExcerpt/div2[@id="d0710pm"]/p[@id="d0710pm-p3"]')[0]
    source_text = ''.join(paragraph.itertext())
    for span in record['mapped_text_spans']:
        assert source_text[span['start']:span['end']] == span['text']


def accepted_fixture(tmp_path, category):
    """Real source/TEI, with explicitly simulated acceptance evidence in temp only."""
    from ocd_kernel.tei.acceptance import build_acceptance_record,write_acceptance,make_file_binding
    f=ROOT/'tests/fixtures/library-pipeline/categories'/category
    m=json.loads((f/'manifest.json').read_text(encoding='utf-8'))
    identity={**m['context']['identity'],'acquisition_id':'fixture-retained-morneve'}
    base=tmp_path/'f';edition=base/'library/works'/identity['work_id']/'forms'/identity['textual_form_id']/'editions'/identity['edition_id']
    edition.mkdir(parents=True)
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    work={'schema_version':'2.0','work_id':identity['work_id'],'title':m['source_title'],'textual_forms':[{'textual_form_id':identity['textual_form_id'],'editions':[{'edition_id':identity['edition_id'],'title':m['source_title'],'language':'en','category':category}]}],'evidence':['https://www.ccel.org/ccel/spurgeon/morneve.html']}
    write(base/'library/works'/identity['work_id']/'work.json',work)
    write(base/'library/works'/identity['work_id']/'state.json',{'schema_version':'2.0','work_id':identity['work_id'],'targets':[{'target_id':identity['edition_id'],'target_type':'edition','stage':'review','updated_at':'2026-09-08T00:00:00Z','evidence':['candidate.xml']}]})
    retained=base/'retained/excerpt.xml';retained.parent.mkdir();retained.write_bytes((f/'retained.xml').read_bytes())
    included={'path':'retained/excerpt.xml','sha256':hashlib.sha256(retained.read_bytes()).hexdigest(),'bytes':retained.stat().st_size,'scope':'selected source-native div2 units listed in fixture manifest'}
    source={'source_path':m['source_path'],'source_sha256':m['source_sha256'],'source_bytes':2136777,'source_scope':'Morning and Evening retained ThML'}
    acquisition={'schema_version':'2.0','acquisition_id':identity['acquisition_id'],'edition_id':identity['edition_id'],'provider':'Christian Classics Ethereal Library','url':'https://www.ccel.org/ccel/spurgeon/morneve.xml',**source,'retained_files':[{**included,'media_type':'application/xml'}],'route':'born-digital'}
    write(edition/'acquisitions'/f"{identity['acquisition_id']}.json",acquisition)
    scope={'kind':'member','declared':included['scope'],'expected_members':[{'path':included['path'],'position':1}],'included_members':[{**included,'position':1}],'excluded_members':[]}
    tree=E.parse(str(f/'master.tei.xml'));ns='http://www.tei-c.org/ns/1.0';header=tree.find('{'+ns+'}teiHeader');sd=header.find('.//{'+ns+'}sourceDesc')
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


def test_accepted_quotation_entry_binds_authority_without_caller_overrides(tmp_path):
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.projection.categories.quotations import project_accepted_quotations,verify_accepted_quotations
    root,acceptance=accepted_fixture(tmp_path,'quotations')
    with pytest.raises(PipelineError,match='promoted'):project_accepted_quotations(root,acceptance_path=acceptance)
    promoted=promote_accepted_master(root,acceptance_path=acceptance,destination=tmp_path/'out')
    out=project_accepted_quotations(tmp_path/'out',acceptance_path=promoted.acceptance_path)
    assert verify_accepted_quotations(tmp_path/'out',acceptance_path=promoted.acceptance_path,rows=out['rows'],receipt=out['receipt'])==[]
    out['receipt']['authority']['master']['sha256']='0'*64
    assert verify_accepted_quotations(tmp_path/'out',acceptance_path=promoted.acceptance_path,rows=out['rows'],receipt=out['receipt'])
