"""Focused Spurgeon source-layer omission and exact inverse mutations."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release import public_rows as boundary
from ocd_kernel.release.work_metadata import compose_work_metadata

ITEM=boundary.SPURGEON_ITEM
ACCEPTANCE,MASTER=boundary.PG_ITEMS[ITEM]

def digest(value):
    return sha256(canonical_bytes(value)).hexdigest()

def paragraph(text, attrs=None):
    return {'kind':'paragraph','attributes':attrs or {},
            'content':[{'kind':'text','text':text}]}

def fixture(monkeypatch):
    link=boundary._spurgeon_reference()
    modern={'kind':'paragraph','attributes':{'style':'class:normal'},
            'content':[{'kind':'text','text':'[Set a browser start page to '},
                       {'kind':'source-reference','attributes':{'source_target':link['target']},
                        'content':[{'kind':'text','text':link['target']}]},
                       {'kind':'text','text':'.]'}]}
    centered={'kind':'division','attributes':{'style':'class:Center','type':'centered-front-matter'},
              'content':[paragraph('Historical preface '+str(i)) for i in range(4)]+[modern]}
    front={'kind':'division','attributes':{'type':'thml-div1'},'content':[centered]}
    # The accepted position is front.content[3], with three preceding front blocks.
    front['content']=[paragraph('Earlier '+str(i)) for i in range(3)]+[centered]
    markers=[{'kind':'source-marker','attributes':{'number':'01-01','unit':'source-text-break',
              'source_annotations':boundary.SPURGEON_MARKER},'content':[]} for _ in range(369)]
    margins=[paragraph('Morning, January 1',{'style':'style:margin-bottom:0in'}) for _ in range(732)]
    caps=[{'kind':'emphasis','attributes':{'style':'style:font-variant:small-caps'},
           'content':[{'kind':'text','text':'Spurgeon'}]} for _ in range(48)]
    work={'kind':'division','attributes':{'type':'work'},'content':[front]+markers+margins+caps}
    row={'record_id':'spurgeon-synthetic','structure':[work],
         'source_references':[{'raw':'first'},{'raw':'second'},link]}
    row['text']=readable_content(work)
    monkeypatch.setattr(boundary,'SPURGEON_PRIVATE_ROW_SHA256',digest(row))
    row['license']=boundary.SPURGEON_LICENSE
    monkeypatch.setattr(boundary,'SPURGEON_PARAGRAPH_SHA256',digest(modern))
    return [row]

def transform(rows):
    return boundary.public_rows_with_omissions(rows,item_id=ITEM,
               acceptance_sha256=ACCEPTANCE,master_sha256=MASTER)

def restore(rows,receipt):
    return boundary.restore_private_source_locations(rows,receipt,item_id=ITEM,
               acceptance_sha256=ACCEPTANCE,master_sha256=MASTER)

def test_single_modern_paragraph_and_presentation_are_reversible(monkeypatch):
    private=fixture(monkeypatch)
    public,receipt=transform(private)
    assert restore(public,receipt)==private
    assert len(public[0]['structure'][0]['content'][0]['content'][3]['content'])==4
    assert len(public[0]['source_references'])==2
    assert 'browser start page' not in public[0]['text']
    assert 'Morning, January 1' in public[0]['text']
    assert not _scan(public,'synthetic Spurgeon')
    fields=[field for entry in receipt['inner']['omissions'] for field in entry['fields']]
    assert len(fields)==1149
    assert sum(field['private']==boundary.SPURGEON_MARKER for field in fields)==369
    assert all(node['attributes']['source_annotations']=='source-unit:DayOfYear'
               for node in public[0]['structure'][0]['content'][1:370])
    assert all(node['attributes']=={} for node in public[0]['structure'][0]['content'][370:1102])

@pytest.mark.parametrize('mutation',['text','day','date','historical','class','link','reference','receipt_paragraph','receipt_reference','receipt_field','authority','license'])
def test_public_text_links_dates_roles_and_receipt_cannot_drift(monkeypatch,mutation):
    private=fixture(monkeypatch)
    public,receipt=transform(private)
    public,receipt=deepcopy(public),deepcopy(receipt)
    work=public[0]['structure'][0]
    if mutation=='text': public[0]['text']='changed'
    elif mutation=='day': work['content'][1]['attributes']['source_annotations']='other'
    elif mutation=='date': work['content'][1]['attributes']['number']='02-02'
    elif mutation=='historical': work['content'][370]['content'][0]['text']='changed'
    elif mutation=='class': work['content'][0]['content'][3]['attributes']['style']='class:other'
    elif mutation=='link': public[0]['source_references'].append({'raw':'unexpected'})
    elif mutation=='reference': public[0]['source_references'].pop()
    elif mutation=='receipt_paragraph': receipt['removed_paragraph']['content'][0]['text']='changed'
    elif mutation=='receipt_reference': receipt['removed_reference']['target']='changed'
    elif mutation=='receipt_field': receipt['inner']['omissions'][0]['fields'].pop()
    elif mutation=='license': public[0]['license']='different rights scope'
    else: receipt['authority']['spurgeon_scope_evidence_sha256']='0'*64
    with pytest.raises(PipelineError): restore(public,receipt)

def test_old_generic_or_pg_receipt_cannot_bypass_spurgeon_contract(monkeypatch):
    private=fixture(monkeypatch)
    public,receipt=transform(private)
    with pytest.raises(PipelineError):
        restore(public,receipt['inner'])

def test_wrong_accepted_authority_refuses_public_transform(monkeypatch):
    private=fixture(monkeypatch)
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(private,item_id=ITEM,
            acceptance_sha256='0'*64,master_sha256=MASTER)


def test_wrong_selected_license_refuses_public_transform(monkeypatch):
    private=fixture(monkeypatch)
    private[0]['license']='unreviewed rights scope'
    with pytest.raises(PipelineError):
        transform(private)


def test_real_release_pretransform_license_and_metadata_match_exact_scope():
    root=Path(__file__).resolve().parents[1]
    accepted_path=(root/'library/works/spurgeons-morning-evening/forms/spurgeons-morning-evening-english/editions/spurgeons-morning-evening-ccel-thml-electronic/acceptance.json')
    projected=project_accepted_prose(root,acceptance_path=accepted_path)
    licensed=[dict(row,license=boundary.SPURGEON_LICENSE) for row in projected['rows']]
    private,receipt=compose_work_metadata(root,licensed,projected['receipt'])
    assert boundary._spurgeon_private_row_matches(private[0])
    public,omissions=boundary.public_rows_with_omissions(
        private,item_id=ITEM,acceptance_sha256=digest_bytes(accepted_path.read_bytes()),
        master_sha256=receipt['master_sha256'])
    assert boundary.restore_private_source_locations(
        public,omissions,item_id=ITEM,
        acceptance_sha256=digest_bytes(accepted_path.read_bytes()),
        master_sha256=receipt['master_sha256'])==private
    assert not _scan(public,'Spurgeon release pretransform')


def digest_bytes(value):
    return sha256(value).hexdigest()
