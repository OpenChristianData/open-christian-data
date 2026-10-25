"""PIPE-015A complete source-defined devotional entries, without inferred metadata."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from lxml import etree as E
import pytest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.devotionals import project_devotionals_document as project, verify_devotionals_document as verify

ROOT=Path(__file__).resolve().parents[1]
SOURCE_ORACLE=ROOT/'plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-008/verify_original_source.py'
FIXTURE=ROOT/'tests/fixtures/library-pipeline/categories/devotionals'
MANIFEST=json.loads((FIXTURE/'manifest.json').read_text(encoding='utf-8'))
PATH=FIXTURE/'master.tei.xml'
CONTEXT=MANIFEST['context']


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp('cq')


def norm(node):return ' '.join(''.join(node.xpath('.//text()')).split())


def test_five_real_units_preserve_source_date_readings_and_paragraphs():
    out=project(PATH,**CONTEXT)
    for name,digest in MANIFEST['files'].items():assert hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest()==digest
    source=E.parse(str(FIXTURE/'retained.xml'));units=source.xpath('/sourceExcerpt/div2')
    assert len(units)==len(out['rows'])==5
    assert [len(d.xpath('p[@class="normal"]')) for d in units]==[2,1,5,1,1]
    for row,node in zip(out['rows'],units):
        assert row['locator']=={'kind':'devotional','number':node.get('n'),'heading':norm(node.find('h2'))}
        dates=node.xpath('h2/sync[@type="DayOfYear"]/@value')
        assert row['date']==(dates[0] if dates else None)
        expected_readings=[]
        for heading in node.xpath('h3[@class="scripPassage"]'):
            quote=heading.xpath('preceding-sibling::*[not(self::scripCom)][1]')[0]
            expected_readings.append({'text':norm(quote),'locus':norm(heading),
                                      'source_reference':{'normalization_status':'no-explicit-target'}})
        assert row['readings']==expected_readings
        blocks=[]
        for b in node.xpath('p[@class="normal"] | verse'):
            if b.tag=='p':blocks.append({'kind':'paragraph','text':norm(b)})
            else:blocks.append({'kind':'verse','lines':[{'text':norm(line),'rendition':line.get('class')} for line in b.findall('l')]})
        assert row['divisions']==blocks
        assert row['text']=='\n\n'.join(b['text'] if b['kind']=='paragraph' else '\n'.join(line['text'] for line in b['lines']) for b in blocks)
        assert 'occasion' not in row and 'theme' not in row
    assert verify(PATH,out['rows'],out['receipt'],**CONTEXT)==[]
    assert len(MANIFEST['unit_census'])==MANIFEST['source_unit_count']


def test_fixture_is_valid_tei_p5():
    E.XMLSchema(E.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd'))).assertValid(E.parse(str(PATH)))


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
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--category', 'devotionals', '--tei-path', str(changed)],
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
    unit = tree.xpath('//t:body/t:div[@xml:id="d0101am"]', namespaces=ns)[0]
    if mutation == 'append':
        paragraph = unit.xpath('./t:p[1]', namespaces=ns)[0]
        if len(paragraph):
            paragraph[-1].tail = (paragraph[-1].tail or '') + ' Invented source text.'
        else:
            paragraph.text = (paragraph.text or '') + ' Invented source text.'
    else:
        first, second = unit.xpath('./t:p', namespaces=ns)[:2]
        unit.remove(second)
        unit.insert(unit.index(first), second)
    changed = tmp_path / f'{mutation}-source-drift.tei.xml'
    changed.write_bytes(E.tostring(tree, encoding='utf-8', xml_declaration=True))
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', str(SOURCE_ORACLE), '--category', 'devotionals', '--tei-path', str(changed)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert 'block text mapping differs' in output


@pytest.mark.parametrize('mutation',['omit','duplicate','reverse','text','date','inferred-date','occasion','reading','paragraph','number','heading','theme','warning','exclusion','inventory','source','policy','verse-line','verse-order'])
def test_source_mutations_fail_even_with_forged_receipt(mutation):
    out=project(PATH,**CONTEXT);rows=out['rows'];r=rows[0]
    if mutation=='omit':rows.pop()
    elif mutation=='duplicate':rows.append(copy.deepcopy(rows[-1]))
    elif mutation=='reverse':rows.reverse()
    elif mutation=='text':r['text']+=' Invented'
    elif mutation=='date':r['date']='12-25'
    elif mutation=='inferred-date':rows[1]['date']='01-01'
    elif mutation=='occasion':r['occasion']='New Year service'
    elif mutation=='reading':r['readings'][0]['locus']='Invented 1:1'
    elif mutation=='paragraph':r['divisions'].reverse()
    elif mutation in ('number','heading'):r['locator'][mutation]='Wrong'
    elif mutation=='theme':r['theme']='Hope'
    elif mutation=='warning':out['receipt']['warnings']=[]
    elif mutation=='exclusion':out['receipt']['exclusions']=[]
    elif mutation=='inventory':out['receipt']['inventory'].pop()
    elif mutation=='verse-line':rows[3]['divisions'][-1]['lines'].pop()
    elif mutation=='verse-order':rows[3]['divisions'][-1]['lines'].reverse()
    elif mutation=='source':out['receipt']['master_sha256']='0'*64
    elif mutation=='policy':out['receipt']['policy_sha256']='0'*64
    for i,row in enumerate(rows,1):row['sequence']=i
    receipt=out['receipt'];receipt['row_count']=len(rows);receipt['output_sha256']=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    receipt['independent_check']={'status':'pending'}
    assert verify(PATH,rows,receipt,**CONTEXT)


@pytest.mark.parametrize('change',['table','attribute','loose','date','namespace','prolog-pi','epilog-pi'])
def test_silent_unsupported_input_fails_independently(change,tmp_path):
    tree=E.parse(str(PATH));n={'t':'http://www.tei-c.org/ns/1.0'};d=tree.xpath('//t:body/t:div',namespaces=n)[0]
    if change=='table':E.SubElement(d,'{'+n['t']+'}table')
    elif change=='attribute':d.set('ana','invented')
    elif change=='loose':d.text='Unmapped words'
    elif change=='date':d.append(copy.deepcopy(d.find('{'+n['t']+'}dateline')))
    elif change=='namespace':d.tag='{urn:wrong}div'
    raw=E.tostring(tree,encoding='utf-8')
    if change=='prolog-pi':raw=b'<?reader hidden?>'+raw
    elif change=='epilog-pi':raw+=b'<?reader hidden?>'
    p=tmp_path/'bad.xml';p.write_bytes(raw)
    out=project(PATH,**CONTEXT)
    with pytest.raises(PipelineError):project(p,**CONTEXT)
    assert verify(p,out['rows'],out['receipt'],**CONTEXT)


def test_checker_has_no_producer_dependency(monkeypatch):
    out=project(PATH,**CONTEXT)
    import ocd_kernel.projection.categories.devotionals as m
    monkeypatch.setattr(m,'project_devotionals_document',lambda *a,**k: (_ for _ in ()).throw(AssertionError('producer called')))
    assert verify(PATH,out['rows'],out['receipt'],**CONTEXT)==[]


def test_accepted_devotional_entry_checks_promoted_authority(tmp_path):
    from tests.test_projection_quotations import accepted_fixture
    from ocd_kernel.tei.acceptance import promote_accepted_master
    from ocd_kernel.projection.categories.devotionals import project_accepted_devotionals,verify_accepted_devotionals
    root,acceptance=accepted_fixture(tmp_path,'devotionals')
    with pytest.raises(PipelineError,match='promoted'):project_accepted_devotionals(root,acceptance_path=acceptance)
    promoted=promote_accepted_master(root,acceptance_path=acceptance,destination=tmp_path/'out')
    out=project_accepted_devotionals(tmp_path/'out',acceptance_path=promoted.acceptance_path)
    assert verify_accepted_devotionals(tmp_path/'out',acceptance_path=promoted.acceptance_path,rows=out['rows'],receipt=out['receipt'])==[]
    out['rows'][0]['date']='inferred'
    assert verify_accepted_devotionals(tmp_path/'out',acceptance_path=promoted.acceptance_path,rows=out['rows'],receipt=out['receipt'])


@pytest.mark.parametrize('moved',['head','cit'])
def test_devotional_opening_order_is_not_silently_rearranged(moved,tmp_path):
    tree=E.parse(str(PATH));n={'t':'http://www.tei-c.org/ns/1.0'}
    unit=tree.xpath('//t:body/t:div',namespaces=n)[0]
    unit.append(unit.find('{'+n['t']+'}'+moved))
    changed=tmp_path/'order.xml';changed.write_bytes(E.tostring(tree))
    out=project(PATH,**CONTEXT)
    with pytest.raises(PipelineError):project(changed,**CONTEXT)
    assert verify(changed,out['rows'],out['receipt'],**CONTEXT)


@pytest.mark.parametrize('change', ['omit', 'duplicate', 'reorder', 'reference-attachment', 'text'])
def test_july12_multiple_readings_are_independently_checked(change):
    out=project(PATH, **CONTEXT)
    row=next(row for row in out['rows'] if row['date']=='07-12')
    assert [r['locus'] for r in row['readings']]==['Jude 1', '1 Corinthians 1:2', '1 Peter 1:2']
    assert row['readings'][0]['text']=='“Sanctified by God the Father.”'
    readings=row['readings']
    if change=='omit': readings.pop(0)
    elif change=='duplicate': readings.append(copy.deepcopy(readings[0]))
    elif change=='reorder': readings.reverse()
    elif change=='reference-attachment': readings[0]['locus'],readings[1]['locus']=readings[1]['locus'],readings[0]['locus']
    else: readings[0]['text']+=' Invented.'
    out['receipt']['output_sha256']=hashlib.sha256(json.dumps(out['rows'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    assert verify(PATH,out['rows'],out['receipt'],**CONTEXT)


@pytest.mark.parametrize('change', ['omit', 'reorder', 'wrong-pair'])
@pytest.mark.requires_local_artifacts
def test_source_manifest_accounts_for_every_ordered_reading(change):
    import importlib.util

    spec = importlib.util.spec_from_file_location('devotional_source_oracle', SOURCE_ORACLE)
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    manifest = json.loads((PATH.parent/'manifest.json').read_text(encoding='utf-8'))
    records = manifest['selected_units']
    selected = E.parse(str(PATH.parent/'retained.xml')).xpath('/sourceExcerpt/div2')
    readings = next(record for record in records if record['id']=='d0712am')['source_readings']
    assert [reading['locus'] for reading in readings] == ['Jude 1', '1 Corinthians 1:2', '1 Peter 1:2']
    oracle._verify_tei_mapping('devotionals', selected, records, PATH)
    if change == 'omit':
        readings.pop()
    elif change == 'reorder':
        readings.reverse()
    else:
        readings[0]['locus'], readings[1]['locus'] = readings[1]['locus'], readings[0]['locus']
    with pytest.raises(ValueError, match='source readings accounting differs'):
        oracle._verify_tei_mapping('devotionals', selected, records, PATH)


@pytest.mark.requires_local_artifacts
@pytest.mark.parametrize('change', ['omit-first', 'reorder', 'reference-attachment'])
def test_original_source_oracle_rejects_multiple_reading_damage(change,tmp_path):
    tree=E.parse(str(PATH));ns={'t':'http://www.tei-c.org/ns/1.0'}
    unit=tree.xpath('//t:div[@xml:id="d0712am"]',namespaces=ns)[0]
    citations=unit.xpath('t:cit',namespaces=ns)
    assert len(citations)==3
    if change=='omit-first':unit.remove(citations[0])
    elif change=='reorder':
        unit.remove(citations[1]);unit.insert(unit.index(citations[0]),citations[1])
    else:
        a,b=[citations[i].find('{'+ns['t']+'}bibl') for i in [0,1]]
        citations[0].remove(a);citations[1].remove(b);citations[0].append(b);citations[1].append(a)
    changed=tmp_path/'readings.xml';changed.write_bytes(E.tostring(tree,encoding='utf-8'))
    completed=subprocess.run([sys.executable,'-X','utf8',str(SOURCE_ORACLE),'--category','devotionals','--tei-path',str(changed)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',check=False)
    assert completed.returncode!=0
    assert any(message in completed.stdout+completed.stderr for message in ['block text mapping differs','block mapping differs','citation reference mapping differs','mapped source text missing'])


@pytest.mark.parametrize('change', ['no-readings','no-heading','no-number','late-reading'])
def test_multiple_reading_approval_does_not_relax_other_requirements(change,tmp_path):
    tree=E.parse(str(PATH));ns={'t':'http://www.tei-c.org/ns/1.0'}
    unit=tree.xpath('//t:div[@xml:id="d0712am"]',namespaces=ns)[0]
    if change=='no-readings':
        for node in unit.xpath('t:cit',namespaces=ns):unit.remove(node)
    elif change=='no-heading':unit.remove(unit.find('{'+ns['t']+'}head'))
    elif change=='no-number':del unit.attrib['n']
    else:unit.append(unit.find('{'+ns['t']+'}cit'))
    changed=tmp_path/'requirements.xml';changed.write_bytes(E.tostring(tree,encoding='utf-8'))
    with pytest.raises(PipelineError):project(changed,**CONTEXT)
    out=project(PATH,**CONTEXT)
    assert verify(changed,out['rows'],out['receipt'],**CONTEXT)

@pytest.mark.parametrize('mutation', ['none', 'drop', 'change', 'swap'])
def test_source_reference_targets_preserve_identity_and_attachment(tmp_path, mutation):
    tree = E.parse(str(PATH))
    refs = tree.xpath('//t:body/t:div/t:cit/t:bibl/t:ref', namespaces={'t': 'http://www.tei-c.org/ns/1.0'})
    refs[0].set('cRef', 'Josh.5.12')
    refs[0].set('target', 'https://example.org/source#reading-one')
    refs[1].set('cRef', 'Song.1.4')
    candidate = tmp_path / 'references.xml'
    tree.write(str(candidate), encoding='utf-8')
    out = project(candidate, **CONTEXT)
    reference = out['rows'][0]['readings'][0]['source_reference']
    assert reference['cRef'] == 'Josh.5.12'
    assert reference['target'] == 'https://example.org/source#reading-one'
    assert reference['scripture']['normalized'] == 'Josh.5.12'
    assert reference['normalization_attribute'] == 'cRef'
    assert verify(candidate, out['rows'], out['receipt'], **CONTEXT) == []
    rows = copy.deepcopy(out['rows'])
    first = rows[0]['readings'][0]
    second = rows[1]['readings'][0]
    if mutation == 'drop':
        del first['source_reference']
    elif mutation == 'change':
        first['source_reference']['cRef'] = 'Josh.5.13'
    elif mutation == 'swap':
        first['source_reference'], second['source_reference'] = second['source_reference'], first['source_reference']
    if mutation != 'none':
        assert any('source correspondence' in error for error in verify(candidate, rows, out['receipt'], **CONTEXT))

@pytest.mark.parametrize('attribute', ['cRef', 'target'])
@pytest.mark.parametrize('value', ['', '   '])
def test_empty_source_reference_target_fails_closed(tmp_path, attribute, value):
    tree = E.parse(str(PATH))
    ref = tree.xpath('//t:body//t:ref', namespaces={'t': 'http://www.tei-c.org/ns/1.0'})[0]
    ref.set(attribute, value)
    candidate = tmp_path / 'empty-target.xml'
    tree.write(str(candidate), encoding='utf-8')
    with pytest.raises(PipelineError, match='empty source reference target'):
        project(candidate, **CONTEXT)
    original = project(PATH, **CONTEXT)
    assert any('empty source reference target' in error for error in verify(candidate, original['rows'], original['receipt'], **CONTEXT))


def test_old_devotional_mapping_receipt_is_rejected():
    out = project(PATH, **CONTEXT)
    out['receipt']['mapping_version'] = 'ocd-devotionals-bounded-v1'
    assert 'receipt correspondence: mapping_version' in verify(PATH, out['rows'], out['receipt'], **CONTEXT)


def test_source_reference_survives_typed_release_encoding(tmp_path):
    from ocd_kernel.release.features import configuration_features
    from ocd_kernel.release.typed_rows import encode_rows, check_rows
    tree = E.parse(str(PATH))
    ref = tree.xpath('//t:body//t:ref', namespaces={'t': 'http://www.tei-c.org/ns/1.0'})[0]
    ref.set('cRef', 'Josh.5.12')
    ref.set('target', 'https://example.org/source#reading-one')
    candidate = tmp_path / 'typed-target.xml'
    tree.write(str(candidate), encoding='utf-8')
    rows = project(candidate, **CONTEXT)['rows']
    features = configuration_features(rows)
    check_rows(encode_rows(rows, features), rows, features)


@pytest.mark.parametrize('mutation', ['none', 'drop', 'swap-lines', 'invent-target', 'empty-target'])
def test_body_references_keep_paragraph_and_verse_attachment(tmp_path, mutation):
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    tree = E.parse(str(PATH))
    unit = tree.xpath('//t:body/t:div', namespaces=ns)[0]
    paragraph = unit.find('t:p', ns)
    E.SubElement(paragraph, '{'+ns['t']+'}ref', type='citation', cRef='John.1.1').text = ' John 1:1'
    verse = E.SubElement(unit, '{'+ns['t']+'}lg')
    for label, target in [('First reference', '#first'), ('Second reference', '#second')]:
        line = E.SubElement(verse, '{'+ns['t']+'}l')
        line.text = 'A verse line with '
        E.SubElement(line, '{'+ns['t']+'}ref', type='citation', target=target).text = label
    if mutation == 'empty-target':
        verse[0][0].set('target', ' ')
    candidate = tmp_path / 'body-references.xml'
    tree.write(str(candidate), encoding='utf-8')
    if mutation == 'empty-target':
        with pytest.raises(PipelineError, match='empty source reference target'):
            project(candidate, **CONTEXT)
        original = project(PATH, **CONTEXT)
        assert any('empty source reference target' in e for e in verify(candidate, original['rows'], original['receipt'], **CONTEXT))
        return
    out = project(candidate, **CONTEXT)
    assert verify(candidate, out['rows'], out['receipt'], **CONTEXT) == []
    row = out['rows'][0]
    paragraph_row = next(d for d in row['divisions'] if d['kind'] == 'paragraph')
    assert len(paragraph_row['references']) == 1
    assert paragraph_row['references'][0]['raw'] == 'John 1:1'
    assert paragraph_row['references'][0]['scripture']['normalized'] == 'John.1.1'
    lines = row['divisions'][-1]['lines']
    assert [line['references'][0]['target'] for line in lines] == ['#first', '#second']
    if mutation == 'drop':
        del paragraph_row['references']
    elif mutation == 'swap-lines':
        lines[0]['references'], lines[1]['references'] = lines[1]['references'], lines[0]['references']
    elif mutation == 'invent-target':
        paragraph_row['references'][0]['target'] = 'invented'
    else:
        from ocd_kernel.release.features import configuration_features
        from ocd_kernel.release.typed_rows import encode_rows, check_rows
        features = configuration_features(out['rows'])
        check_rows(encode_rows(out['rows'], features), out['rows'], features)
        return
    assert any('source correspondence' in e for e in verify(candidate, out['rows'], out['receipt'], **CONTEXT))


@pytest.mark.parametrize('mode', ['explicit', 'unmarked', 'duplicate', 'unknown'])
def test_primary_reading_requires_explicit_source_role(tmp_path, monkeypatch, mode):
    from ocd_kernel.projection.categories import devotionals
    ns = {'t': 'http://www.tei-c.org/ns/1.0'}
    tree = E.parse(str(PATH))
    citations = tree.xpath('//t:body/t:div/t:cit', namespaces=ns)
    first = citations[0]
    if mode != 'unmarked':
        first.set('type', 'primary-reading' if mode != 'unknown' else 'guessed-primary')
    first.find('t:bibl/t:ref', ns).set('cRef', 'Josh.5.12-13')
    if mode == 'duplicate':
        first.addnext(copy.deepcopy(first))
    candidate = tmp_path / 'primary.xml'
    tree.write(str(candidate), encoding='utf-8')
    if mode in ('duplicate', 'unknown'):
        with pytest.raises(PipelineError):
            project(candidate, **CONTEXT)
        original = project(PATH, **CONTEXT)
        assert verify(candidate, original['rows'], original['receipt'], **CONTEXT)
        return
    out = project(candidate, **CONTEXT)
    reading = out['rows'][0]['readings'][0]
    assert reading.get('role') == ('primary' if mode == 'explicit' else None)
    assert reading['source_reference']['scripture']['normalized'] == 'Josh.5.12-Josh.5.13'
    def forbidden(*args, **kwargs):
        raise AssertionError('checker called reference producer')
    monkeypatch.setattr(devotionals, 'normalize_reference_record', forbidden)
    assert verify(candidate, out['rows'], out['receipt'], **CONTEXT) == []
    reading['role'] = 'primary' if mode == 'unmarked' else 'secondary'
    assert verify(candidate, out['rows'], out['receipt'], **CONTEXT)
