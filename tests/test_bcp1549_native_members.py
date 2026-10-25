"""Focused opt-in/public correspondence checks on the frozen complete witness."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import os
import shutil
import pytest
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import liturgies_bcp1549 as producer
from ocd_kernel.projection.categories import liturgies_bcp1549_check as checker
from build.tei.bcp1549_current_reconstruction import _convert
from build.tei.bcp1549_current_oracle import _oracle
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct, validate

ROOT=Path(__file__).resolve().parents[1]
# Raw candidate pin from the retained current-header-body-conservation receipt.
CANDIDATE_SHA256='a521f116ccfffb0234b487b46c7a1d2936f2a0360f19d8d9c1fba11b26492b87'
KW=dict(identity=producer.IDENTITY,language='en',representation_revision='bcp1549-focused',edition_title='Retained BCP1549 electronic witness',projection_profile=producer.PROFILE,source_url='http://justus.anglican.org/resources/bcp/1549/')
NS='{http://www.tei-c.org/ns/1.0}'

@pytest.fixture(scope='module')
def native_source_manifest():
    return SourceManifest.load(ROOT/'tests/fixtures/reconstruction-runtime/bcp1549-native-current.source-manifest.json',repository_root=ROOT)


@pytest.fixture(scope='module')
def native_tei(tmp_path_factory,native_source_manifest):
    destination=tmp_path_factory.mktemp('bcp1549-native')
    try:
        candidate=reconstruct(native_source_manifest,destination,_convert)
        assert sha256(candidate.member_bytes('content.tei.xml')).hexdigest()==CANDIDATE_SHA256
        assert validate(native_source_manifest,candidate,_oracle).status=='pass'
        configured=os.environ.get('OCD_BCP1549_CANDIDATE')
        selected=Path(configured) if configured else candidate.path/'content.tei.xml'
        assert sha256(selected.read_bytes()).hexdigest()==CANDIDATE_SHA256
        yield selected
    finally:
        if destination.exists():shutil.rmtree(destination)


@pytest.fixture(scope='module')
def result(native_tei):
    return producer.project_document(native_tei,**KW)

def descendants(content):
    yield content
    for child in content.get('content',[]):
        if isinstance(child,dict):yield from descendants(child)

def test_complete_native_members_and_independent_proof(result,monkeypatch,native_tei):
    assert len(result['rows'])==34
    nodes=[n for row in result['rows'] for root in row['structure'] for n in descendants(root)]
    assert sum(n.get('kind')=='table' for n in nodes)==236
    assert sum('row_span' in n.get('attributes',{}) for n in nodes)==65
    assert sum('columns' in n.get('attributes',{}) for n in nodes)==218
    assert [r['member_number'] for r in result['rows']]==list(range(1,35))
    def unavailable(*args,**kwargs):raise AssertionError('Producer disabled')
    monkeypatch.setattr(producer,'project_document',unavailable)
    import ocd_kernel.projection.native_content as native
    monkeypatch.setattr(native,'project_content',unavailable)
    assert checker.verify_document(native_tei,result['rows'],result['receipt'],**KW)==[]

@pytest.mark.parametrize('change',['missing-profile','unknown-profile','wrong-work','wrong-language'])
def test_exact_profile_identity_required(change,native_tei):
    kw=deepcopy(KW)
    if change=='missing-profile':kw['projection_profile']=None
    elif change=='unknown-profile':kw['projection_profile']='ocd-liturgies-bcp1662-retained-members-v1'
    elif change=='wrong-work':kw['identity']['work_id']='bcp-1559'
    else:kw['language']='la'
    with pytest.raises(PipelineError,match='exact identity/language/profile'):producer.project_document(native_tei,**kw)
    assert checker.verify_document(native_tei,[],{},**kw)==['BCP1549 exact identity/language/profile required']

@pytest.mark.parametrize('change',['omit','duplicate','reorder','text','rowspan'])
def test_saved_public_mutations_rejected(result,change,native_tei):
    rows=deepcopy(result['rows'])
    if change=='omit':rows.pop()
    elif change=='duplicate':rows.append(deepcopy(rows[-1]))
    elif change=='reorder':rows[0],rows[1]=rows[1],rows[0]
    elif change=='text':rows[0]['text']+=' altered'
    else:
        cell=next(n for n in descendants(rows[0]['structure'][0]) if 'row_span' in n.get('attributes',{}))
        cell['attributes']['row_span']='99'
    errors=checker.verify_document(native_tei,rows,result['receipt'],**KW)
    assert any('member source correspondence: text/labels/tables/structure/order differ' in e for e in errors)

@pytest.mark.parametrize('change',['private-header','body-source-annotation','member-order','foreign-qname','unknown-header'])
def test_master_changes_against_saved_receipt(result,tmp_path,change,native_tei):
    doc=etree.parse(str(native_tei));root=doc.getroot()
    if change=='private-header':root.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+'title').text+=' changed'
    elif change=='body-source-annotation':
        n=root.find('.//'+NS+'seg');n.set('ana',n.get('ana')+' changed')
    elif change=='member-order':
        b=root.find(NS+'text/'+NS+'body');n=b[0];b.remove(n);b.insert(1,n)
    elif change=='foreign-qname':root.find('.//'+NS+'seg').tag='{urn:foreign}seg'
    else:etree.SubElement(root.find(NS+'teiHeader/'+NS+'fileDesc'),NS+'invented')
    path=tmp_path/'changed.tei.xml';doc.write(str(path),encoding='utf-8',xml_declaration=True)
    errors=checker.verify_document(path,result['rows'],result['receipt'],**KW)
    expected={'private-header':'complete source correspondence receipt differs','body-source-annotation':'member source correspondence','member-order':'exact member order/title/body differs','foreign-qname':'namespace','unknown-header':'qualified header envelope differs'}[change]
    assert any(expected in e for e in errors),errors
