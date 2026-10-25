"""Bounded actual retained-witness and adversarial profile correspondence checks."""
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
import json
import shutil
import pytest
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import liturgies as route
from ocd_kernel.projection.categories import liturgies_bcp1662 as producer
from ocd_kernel.projection.categories.liturgies_bcp1662_check import verify_document
from build.tei.bcp1662_current_oracle import check, _oracle
from build.tei.bcp1662_current_reconstruction import _convert
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct, validate

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'tests/fixtures/reconstruction-runtime'
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
KW=dict(identity=producer.IDENTITY,language='en',representation_revision='bcp1662-focused-native-v1',edition_title='Partial1662BCP retained HTML expression',projection_profile=producer.PROFILE)

@pytest.fixture(scope='module')
def native_source_manifest():
    return SourceManifest.load(RUNTIME/'bcp1662-native-current.source-manifest.json',repository_root=ROOT)


@pytest.fixture(scope='module')
def native_tei(tmp_path_factory,native_source_manifest):
    destination=tmp_path_factory.mktemp('bcp1662-native')
    try:
        candidate=reconstruct(native_source_manifest,destination,_convert)
        assert sha256(candidate.member_bytes('content.tei.xml')).hexdigest()=='2318ed1c1954c395bf5b2791db29a26ec342347b99a4cff4024a3a9a3a1bf8ae'
        assert validate(native_source_manifest,candidate,_oracle).status=='pass'
        yield candidate.path/'content.tei.xml'
    finally:
        if destination.exists():
            shutil.rmtree(destination)


@pytest.fixture(scope='module')
def projected(native_tei):
    assert sha256(native_tei.read_bytes()).hexdigest()=='2318ed1c1954c395bf5b2791db29a26ec342347b99a4cff4024a3a9a3a1bf8ae'
    return route.project_liturgies_document(native_tei,**KW)

def test_actual_complete_native_members_and_independent_producer_disabled(projected,monkeypatch,native_tei):
    rows=projected['rows']
    assert len(rows)==25
    assert [r['member_kind'] for r in rows]==['service']*20+['calendar-part']*5
    assert [r['sequence'] for r in rows]==list(range(1,26))
    assert sum(len(r['text']) for r in rows)==558565
    assert sum(len(t['targets']) for r in rows for t in r['source_links'])==117
    monkeypatch.setattr(producer,'project_document',lambda *a,**k:pytest.fail('producer called'))
    assert route.verify_liturgies_document(native_tei,rows,json.loads(json.dumps(projected['receipt'])),**KW)==[]

@pytest.mark.parametrize('variant',['omission','duplication','order','text','role','heading','continuation','alternative','receipt-attribute','receipt-text'])
def test_saved_public_or_receipt_mutations(projected,variant,native_tei):
    rows=deepcopy(projected['rows']); receipt=deepcopy(projected['receipt'])
    def walk(n):
        yield n
        for c in n.get('content',[]):
            yield from walk(c)
    nodes=[n for r in rows for top in r['structure'] for n in walk(top)]
    if variant=='omission': rows.pop()
    elif variant=='duplication': rows.append(deepcopy(rows[-1]))
    elif variant=='order': rows[0],rows[1]=rows[1],rows[0]
    elif variant=='text': rows[0]['text']+=' alteration'
    elif variant=='role': next(n for n in nodes if n['kind']=='speech')['attributes']['source_annotations']='source-role-token:#bcp-role-invented'
    elif variant=='heading': next(n for n in nodes if n.get('attributes',{}).get('type')=='source-heading')['attributes']['subtype']='6'
    elif variant in ('continuation','alternative'):
        link=next(x for r in rows for x in r['source_links'] if x['kind']==variant)
        link['targets'][0]['token']='0'*20
    elif variant=='receipt-attribute': receipt['inventory'][-1]['attributes'].append(['invented','value'])
    elif variant=='receipt-text': receipt['inventory'][-1]['text_sha256']='0'*64
    errors=route.verify_liturgies_document(native_tei,rows,receipt,**KW)
    assert any('source correspondence' in e for e in errors)

@pytest.mark.parametrize('change',['missing-profile','unknown-profile','wrong-identity','scope'])
def test_opt_in_closed(change,native_tei):
    kw=deepcopy(KW)
    if change=='missing-profile': del kw['projection_profile']
    elif change=='unknown-profile': kw['projection_profile']='unknown'
    elif change=='wrong-identity': kw['identity']['work_id']='other'
    else: kw['scope_id']='slice'
    with pytest.raises(PipelineError): route.project_liturgies_document(native_tei,**kw)

@pytest.mark.parametrize('change',['dangling-target','who-pointer','foreign','extra-attribute','unknown-header','member-order'])
def test_native_shape_rejection_in_both_routes(projected,tmp_path,change,native_tei):
    r=etree.fromstring(native_tei.read_bytes())
    body=r.find(NS+'text/'+NS+'body')
    if change=='dangling-target': next(n for n in body.iter() if n.get('corresp')).set('corresp','#missing')
    elif change=='who-pointer':
        n=next(body.iter(NS+'sp')); n.attrib.clear(); n.set('who','#bcp-role-answer')
    elif change=='foreign': next(body.iter(NS+'seg')).tag='{urn:foreign}seg'
    elif change=='extra-attribute': next(body.iter(NS+'seg')).set('invented','x')
    elif change=='unknown-header': etree.SubElement(r[0],NS+'unknown')
    else: body.insert(0,body[1])
    p=tmp_path/(change+'.tei.xml'); p.write_bytes(etree.tostring(r))
    with pytest.raises((PipelineError,ValueError)):
        route.project_liturgies_document(p,**KW)
    errors=verify_document(p,projected['rows'],projected['receipt'],**KW)
    assert len(errors)==1 and 'correspondence' not in errors[0] and 'schema row' not in errors[0]

@pytest.mark.parametrize('change',['wording','role','heading','break','member-omit','link-target'])
def test_whole_historical_inverse_and_source_proof_rejects_mutations(change,native_tei,native_source_manifest):
    raw=native_tei.read_bytes()
    if change=='wording':
        token=b'Morning Prayer'; assert token in raw; raw=raw.replace(token,b'Changed Morning Prayer',1)
    elif change=='role': raw=raw.replace(b'source-role-token:#bcp-role-answer',b'source-role-token:#bcp-role-priest',1)
    elif change=='heading': raw=raw.replace(b'type="source-h2"',b'type="source-h3"',1)
    elif change=='break': raw=raw.replace(b'subtype="section-break"',b'subtype="invented"',1)
    elif change=='member-omit': raw=raw.replace(b'n="daily__morning.html"',b'n="missing"',1)
    else:
        doc=etree.fromstring(raw); ptr=next(n.get('corresp') for n in doc.iter() if n.get('corresp')); raw=raw.replace(('corresp="'+ptr+'"').encode(),b'corresp="#missing"',1)
    assert raw!=native_tei.read_bytes()
    manifest=native_source_manifest
    with pytest.raises(ValueError,match='alias|recover|header'):
        check(manifest,raw)

def test_old_schema_branches_reject_new_member_fields():
    path=ROOT/'tests/fixtures/library-pipeline/categories/liturgies/master.tei.xml'
    context=json.loads((path.parent/'manifest.json').read_bytes())['context']
    rows=route.project_liturgies_document(path,**context)['rows']
    row=deepcopy(rows[0]); row['member_id']='0'*20
    assert list(route._validator().iter_errors(row))
    row=deepcopy(rows[0]); row['response_model']='literal-role-annotations-without-person-or-response-links'
    assert list(route._validator().iter_errors(row))

def test_accepted_bcp_missing_unknown_and_mismatched_profile(monkeypatch):
    from ocd_kernel.projection.categories import prose
    metadata={'identity':dict(producer.IDENTITY),'root':ROOT,'acceptance':{}}
    for profile in (None,'unknown','ocd-liturgies-n18328-offices-v1'):
        monkeypatch.setattr(prose,'_accepted_projection_profile',lambda *a,**k:profile)
        with pytest.raises(PipelineError,match='profile'):
            route._accepted_office_profile(metadata)

@pytest.mark.parametrize('change',['office-field','office-profile','step-field','office-locator','unknown-link-field'])
def test_new_schema_branch_is_closed(projected,change):
    row=deepcopy(projected['rows'][0])
    if change=='office-field': row['office_id']='mixed'
    elif change=='office-profile': row['row_profile']='ocd-liturgies-n18328-offices-v1'
    elif change=='step-field': row['service_id']='mixed'
    elif change=='office-locator': row['locator']={'kind':'liturgy-office','text_part':'body','outer_division':1,'office':1}
    else:
        row=deepcopy(next(r for r in projected['rows'] if r['source_links']))
        row['source_links'][0]['invented']='x'
    assert list(route._validator().iter_errors(row))

@pytest.mark.parametrize('change',['valid','order','substitution','aggregate','physical-member','missing-member'])
def test_accepted_retained_member_bindings(tmp_path,change):
    included=[]; files=[]
    for i in range(25):
        p=tmp_path/f'member-{i}.html'; raw=f'<p>Member {i}</p>'.encode(); p.write_bytes(raw)
        member={'path':p.name,'sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
        files.append(member); included.append(member|{'position':i+1})
    source={'source_path':'member-set.json','source_sha256':'a'*64,'source_bytes':25}
    acquisition=dict(source,source_kind='retained-member-set',retained_files=files)
    if change=='order': included[0]['position'],included[1]['position']=2,1
    elif change=='substitution': included[0]['sha256']='b'*64
    elif change=='aggregate': source['source_sha256']='c'*64
    elif change=='physical-member': (tmp_path/files[0]['path']).write_bytes(b'changed source')
    elif change=='missing-member': included.pop()
    if change=='valid':
        result=route._bcp1662_aggregate_member(tmp_path,producer.IDENTITY,acquisition,source,included)
        assert result=={'path':'member-set.json','sha256':'a'*64,'bytes':25}
    else:
        with pytest.raises(PipelineError,match='scope|membership/order|member bytes|aggregate'):
            route._bcp1662_aggregate_member(tmp_path,producer.IDENTITY,acquisition,source,included)
