"""Draft one additive authored Joshua identity using the existing acquisition."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from build.tei.blaikie_joshua_retained_native_prepare import ROOT,LOG,SOURCE_DIR,canonical
from ocd_kernel.library.identities import validate_record,load_work,immutable_identity
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.lib.path_io import io_path

OLD='expositors-bible--william-g-blaikie'
WORK='blaikie-book-of-joshua'
FORM=WORK+'--retained-en'
EDITION=WORK+'--ccel-electronic'
ACQUISITION=WORK+'--acquired'
MEMBER='blaikie-expositorjosh'
OLD_FORM=OLD+'--'+MEMBER+'--retained-en'
OLD_EDITION=OLD+'--'+MEMBER+'--ccel-electronic'
OLD_ACQUISITION=OLD+'--'+MEMBER+'--acquired'
OLD_REL=Path('library/works')/OLD
OLD_ACQ=OLD_REL/'forms'/OLD_FORM/'editions'/OLD_EDITION/'acquisitions'/(OLD_ACQUISITION+'.json')
REL=Path('library/works')/WORK
ACQ_REL=REL/'forms'/FORM/'editions'/EDITION/'acquisitions'/(ACQUISITION+'.json')
PROPOSAL=LOG/'title-identity-proposal-v2'
CROSSWALK=PROPOSAL/'identity-crosswalk.json'
RAW=Path('raw/ccel/expositors-bible/blaikie_expositorjosh.xml')

def digest(raw):return sha256(raw).hexdigest()
def pins(base):return {p.relative_to(base).as_posix():digest(p.read_bytes()) for p in sorted(base.rglob('*')) if p.is_file()}

def records():
 acquisition=json.loads((ROOT/OLD_ACQ).read_bytes())
 raw=(ROOT/RAW).read_bytes()
 if digest(raw)!='7a2be4c01ca4ed8ecf37aa6905a161c126ac8cc4752e00448126ae363d2139b3' or len(raw)!=823168:raise ValueError('Joshua raw authority differs')
 source=ET.fromstring(raw);head=source.find('ThML.head')
 title=head.findtext('.//DC.Title')
 if title!="The Expositor's Bible: The Book of Joshua":raise ValueError('Primary title differs')
 book_title=title.partition(': ')[2]
 author=next(n.text for n in head.findall('.//DC.Creator') if n.get('sub')=='Author' and n.get('scheme')=='short-form')
 body=source.find('ThML.body');titlepage=' '.join(''.join(body[0].itertext()).split())
 if 'THE BOOK OF JOSHUA' not in titlepage or 'WILLIAM GARDEN BLAIKIE' not in titlepage:raise ValueError('Primary title page authored identity differs')
 roots=[n.get('id') for n in body]
 if roots[0]!='i' or roots[1]!='ii' or roots[-2]!='xxxiv' or roots[-1]!='xxxv' or len(roots)!=35:raise ValueError('Complete Joshua boundary differs')
 edition=dict(edition_id=EDITION,title=title,language='en',category='commentary',acquisition_ids=[ACQUISITION])
 work=dict(schema_version='2.0',work_id=WORK,title=book_title,
  creators=[dict(name=author,role='author',evidence=[RAW.as_posix()])],
  evidence=[RAW.as_posix(),CROSSWALK.as_posix(),(LOG/'source-inventory-read-only-preflight.json').as_posix(),(LOG/'candidate-completion-receipt-v3.json').as_posix(),OLD_ACQ.as_posix()],
  textual_forms=[dict(textual_form_id=FORM,language='en',editions=[edition])])
 new_acquisition=deepcopy(acquisition);new_acquisition.update(acquisition_id=ACQUISITION,edition_id=EDITION)
 if {k:v for k,v in new_acquisition.items() if k not in {'acquisition_id','edition_id'}}!={k:v for k,v in acquisition.items() if k not in {'acquisition_id','edition_id'}}:raise ValueError('Nonidentity acquisition field changed')
 old_state=json.loads((ROOT/OLD_REL/'state.json').read_bytes());targets=[]
 for old_id,new_id in [(OLD_ACQUISITION,ACQUISITION),(OLD_EDITION,EDITION)]:
  row=deepcopy(next(n for n in old_state['targets'] if n['target_id']==old_id))
  if row['stage']!='acquired':raise ValueError('Joshua legacy target unexpectedly advanced')
  row['target_id']=new_id;row['evidence']+=[CROSSWALK.as_posix()];targets.append(row)
 state=dict(schema_version='2.0',work_id=WORK,targets=targets)
 crosswalk=dict(contract='ocd-existing-retained-authored-work-identity-crosswalk-v1',status='proposal',
  complete_authored_work_count=1,complete_source_member_count=1,
  previous=dict(work_id=OLD,textual_form_id=OLD_FORM,edition_id=OLD_EDITION,acquisition_id=OLD_ACQUISITION,acquisition_path=OLD_ACQ.as_posix(),acquisition_sha256=digest((ROOT/OLD_ACQ).read_bytes()),role='legacy author catalog lineage only'),
  proposed=dict(work_id=WORK,title=book_title,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION,acquisition_path=ACQ_REL.as_posix()),
  primary_source=dict(path=RAW.as_posix(),sha256=digest(raw),bytes=len(raw),literal_title=title,literal_author=author,title_page_text=titlepage,printed_edition_statement=head.findtext('.//published'),source_url=acquisition['url']),
  authored_boundary=dict(front=['i'],body=roots[1:-1],back=['xxxv'],chapters='I through XXXIII including substantive introductory Chapter I',shared_material='No Samuel content; Joshua owns its title page, notes, verses and generated indexes',containers='The Expositors Bible series and inherited author catalog are containers'),
  acquisition_remap=dict(changed_fields=['acquisition_id','edition_id'],every_nonidentity_field_and_absence_exactly_preserved=True,absent_fields=[k for k in ('accessed_at','rights','source_kind','source_selection') if k not in acquisition],legacy_source_scope_and_warnings='Preserved verbatim as historical acquisition qualification; present title identity follows the independent raw-backed complete-work boundary'),
  no_download=True,no_new_source=True,legacy_records_unchanged=True,source_package_role='Frozen author-container v3 candidate is complete Joshua source proof and lineage; the accepted header will bind the new authored-work identity',
  source_package_sha256='bbddb9ff7e13e5b1aba72851a5a640649abbea4620588e5c702cd48c34f70e4d',source_receipt_path=(LOG/'candidate-completion-receipt-v3.json').as_posix(),source_receipt_sha256=digest((ROOT/LOG/'candidate-completion-receipt-v3.json').read_bytes()),
  remaining=['Parent route review and final immutable stage','Human visual/print review, rights clearance and publication remain separate'])
 for name,record in [('work',work),('state',state),('acquisition',new_acquisition)]:validate_record(name,record,context='Joshua title identity proposal '+name)
 return work,state,new_acquisition,crosswalk

def main():
 destination=ROOT/PROPOSAL
 if destination.exists():raise FileExistsError('Preserve Joshua identity proposal')
 old_before=pins(ROOT/OLD_REL)
 work,state,acquisition,crosswalk=records();new_ids={WORK,FORM,EDITION,ACQUISITION}
 collisions=[]
 for path in (ROOT/'library/works').glob('*/work.json'):
  identity=immutable_identity(load_work(path));observed={identity['work_id'],*identity['forms'],*identity['editions'],*identity['acquisitions']}
  if new_ids&observed:collisions.append(dict(path=path.relative_to(ROOT).as_posix(),ids=sorted(new_ids&observed)))
 if collisions or (ROOT/REL).exists():raise ValueError('Canonical title identity collision '+repr(collisions))
 destination.mkdir(parents=True);fixture=destination/'fixture';base=fixture/REL
 (fixture/ACQ_REL).parent.mkdir(parents=True);(fixture/ACQ_REL).write_bytes(canonical(acquisition))
 (base/'work.json').write_bytes(canonical(work));(base/'state.json').write_bytes(canonical(state))
 (base/'SOURCE_CREDIT.md').write_bytes((ROOT/SOURCE_DIR/(MEMBER+'.README.source.md')).read_bytes())
 (fixture/RAW).parent.mkdir(parents=True);(fixture/RAW).write_bytes((ROOT/RAW).read_bytes())
 validated=validate_acquisition(fixture/ACQ_REL,root=fixture)
 if validated!=acquisition:raise ValueError('Fixture acquisition readback differs')
 if pins(ROOT/OLD_REL)!=old_before:raise ValueError('Legacy catalog changed during proposal')
 crosswalk['legacy_generation_before_after']=old_before;crosswalk['canonical_id_collision_check']='none';crosswalk['schema_and_actual_fixture_acquisition_validation']='pass'
 (ROOT/CROSSWALK).write_bytes(canonical(crosswalk))
 report=dict(status='proposal-validated',work_id=WORK,work_title=work['title'],no_canonical_writes=True,legacy_generation_byte_unchanged=True,legacy_file_count=len(old_before),crosswalk_path=CROSSWALK.as_posix(),crosswalk_sha256=digest((ROOT/CROSSWALK).read_bytes()),proposal_generation=pins(base),source_preserved=True)
 (destination/'proposal-receipt.json').write_bytes(canonical(report));print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
