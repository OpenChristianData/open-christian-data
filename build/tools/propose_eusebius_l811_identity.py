"""Propose source-attested L811 language/title corrections with stable IDs."""
from pathlib import Path
from hashlib import sha256
import copy,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from ocd_kernel.library.identities import validate_record

LOG=ROOT/'reports/_logs/eusebius-l811-existing-install-20261004-v1'
WORK=ROOT/'library/works/eusebius-commentarii-in-psalmos'

def encode(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def pin(p):return sha256(p.read_bytes()).hexdigest()
def propose():
    target=LOG/'stable-greek-identity-proposal-v2.json'
    if target.exists():raise FileExistsError('Preserve L811 identity proposal')
    old=json.loads((WORK/'work.json').read_bytes());work=copy.deepcopy(old)
    expected=dict(work_id='eusebius-commentarii-in-psalmos',textual_form_id='pta-english',edition_id='pta-ef861ab3-commentarii-psalmos',acquisition_id='pta-l811-retained-ef861ab3')
    form=work['textual_forms'][0];edition=form['editions'][0]
    if len(work['textual_forms'])!=1 or len(form['editions'])!=1 or work['work_id']!=expected['work_id'] or form['textual_form_id']!=expected['textual_form_id'] or edition['edition_id']!=expected['edition_id'] or edition['acquisition_ids']!=[expected['acquisition_id']]:raise ValueError('Exact original L811 identity preimage differs')
    changes=[]
    for obj,path,key,before,after in [(form,'/textual_forms/0','language','en','grc'),(form,'/textual_forms/0','title','PTA English text','PTA Greek critical text with retained German prefaces'),(edition,'/textual_forms/0/editions/0','language','en','grc'),(edition,'/textual_forms/0/editions/0','title','Commentarii in Psalmos, PTA Tomes I-III','Commentarii in Psalmos, retained PTA Greek Tomes I-III')]:
        if obj[key]!=before:raise ValueError('Exact metadata field preimage differs '+path+'/'+key)
        obj[key]=after;changes.append(dict(path=path+'/'+key,before=before,after=after))
    validate_record('work',work,context='L811 stable Greek identity proposal')
    acquisition_path=WORK/'forms/pta-english/editions/pta-ef861ab3-commentarii-psalmos/acquisitions/pta-l811-retained-ef861ab3.json'
    acquisition_raw=acquisition_path.read_bytes();acquisition=json.loads(acquisition_raw);descriptor=ROOT/acquisition['source_path']
    if pin(descriptor)!=acquisition['source_sha256'] or descriptor.stat().st_size!=acquisition['source_bytes']:raise ValueError('Unchanged original descriptor binding differs')
    assessment=json.loads((LOG/'whole-retained-assessment-v1.json').read_bytes())
    report=dict(status='proposal-only',identity=expected,work_before=old,work_after=work,exact_intended_work_field_changes=changes,proposed_new_forms=0,proposed_new_editions=0,proposed_new_acquisitions=0,acquisition=acquisition,acquisition_path=acquisition_path.relative_to(ROOT).as_posix(),acquisition_sha256=pin(acquisition_path),acquisition_bytes_unchanged=True,source_descriptor=dict(path=acquisition['source_path'],bytes=descriptor.stat().st_size,sha256=pin(descriptor),unchanged=True),canonical_before=assessment['canonical_before'],canonical_changes_authorized='none yet; parent reviews the four work.json metadata corrections and later acceptance/state evidence separately',legacy_id_disposition='The stable pta-english identifier/path is an opaque historical ID. Current language/title fields accurately name the primary Greek text and retained German editorial prefaces; original English field values remain in exact five-file historical snapshots/crosswalk.',body_language_evidence=[dict(tome=m['tome'],root_language=m['root_language'],edition_language=m['edition_language'],preface_language=m['preface_language']) for m in assessment['members']],source_quality_qualifications=[dict(tome=m['tome'],source_statements=m['source_quality_statements']) for m in assessment['members']],superseded_proposal=dict(path=(LOG/'greek-form-identity-proposal-v1.json').relative_to(ROOT).as_posix(),sha256=pin(LOG/'greek-form-identity-proposal-v1.json'),status='historical unadopted duplicate-identity proposal'),assessment_sha256=pin(LOG/'whole-retained-assessment-v1.json'))
    target.write_bytes(encode(report));return dict(path=target.relative_to(ROOT).as_posix(),sha256=pin(target),identity=expected,work_field_changes=changes,canonical_mutation=False)

if __name__=='__main__':print(json.dumps(propose(),sort_keys=True))
