"""Propose additive Second Samuel identities without writing a canonical work home."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
import json
from lxml import etree
from build.tei.blaikie_second_samuel_scope import ROOT, WORK_ID as LEGACY_WORK_ID, MEMBERS, BOUNDARY, sha
from build.tei.blaikie_second_samuel_prepare import canonical
from ocd_kernel.library.identities import validate_record, load_work
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _files, _io_path

WORK_ID='blaikie-second-book-of-samuel'
WORK_TITLE='The Second Book of Samuel'
MEMBER='blaikie-expositor2sam'
IDENTITY=dict(work_id=WORK_ID,textual_form_id=WORK_ID+'--retained-en',edition_id=WORK_ID+'--ccel-electronic',acquisition_id=WORK_ID+'--ccel-acquired')
WORK=Path('library/works')/WORK_ID
LEGACY_WORK=Path('library/works')/LEGACY_WORK_ID
IDENTITY_DIR=Path('sources/commentaries/expositors-bible/blaikie-second-samuel-title-identity-20261003-v1')
SCRATCH=ROOT/'.tmp_audit/blaikie-second-samuel-title-proposal-20261003-v1'
EVIDENCE=WORK/'integration/title-identity-20261003-v1'
SPEC=MEMBERS[MEMBER]
LEGACY_IDENTITY=dict(work_id=LEGACY_WORK_ID,textual_form_id=SPEC['form'],edition_id=SPEC['edition'],acquisition_id=SPEC['acquisition'])
LEGACY_ACQ=LEGACY_WORK/'forms'/SPEC['form']/'editions'/SPEC['edition']/'acquisitions'/(SPEC['acquisition']+'.json')
EDITION=WORK/'forms'/IDENTITY['textual_form_id']/'editions'/IDENTITY['edition_id']
ACQUISITION=EDITION/'acquisitions'/(IDENTITY['acquisition_id']+'.json')

def read(path):return json.loads(_io_path(path).read_bytes())
def pin(path):
 data=_io_path(ROOT/path).read_bytes();return dict(path=Path(path).as_posix(),bytes=len(data),sha256=sha(data))
def write(root,path,raw):
 target=_io_path(root/path)
 if target.exists():raise FileExistsError('Preserve identity proposal '+str(target))
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
def collision_check():
 if _io_path(ROOT/WORK).exists():raise ValueError('Title-specific canonical work path already exists')
 found=[]
 for p in (ROOT/'library/works').glob('*/work.json'):
  record=read(p);ids=[record['work_id']]
  for form in record['textual_forms']:
   ids.append(form['textual_form_id'])
   for edition in form['editions']:ids.extend([edition['edition_id'],*edition.get('acquisition_ids',[])])
  found.extend(set(ids)&set(IDENTITY.values()))
 if found:raise ValueError('Additive Second Samuel identity collision '+repr(found))
 return dict(status='pass',new_canonical_home_absent=True,all_four_ids_unique=True)

def propose():
 if SCRATCH.exists() or (ROOT/IDENTITY_DIR).exists():raise FileExistsError('Fresh complete scratch identity proposal required')
 collisions=collision_check();before=_files(ROOT/LEGACY_WORK);original=read(ROOT/LEGACY_ACQ);raw=_io_path(ROOT/SPEC['path']).read_bytes()
 if sha(raw)!=SPEC['sha256'] or len(raw)!=SPEC['bytes']:raise ValueError('Retained source changed')
 parsed=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False));head=parsed.find('ThML.head')
 title=head.findtext('.//DC.Title');author=next(n.text for n in head.findall('.//DC.Creator') if n.get('sub')=='Author' and n.get('scheme')=='short-form')
 page=''.join(parsed.find("ThML.body/div1[@id='i']").itertext())
 if title!="The Expositor's Bible: The Second Book of Samuel" or 'THE SECOND BOOK' not in page or '1898.' not in page:raise ValueError('Primary work title boundary changed')
 acquisition=deepcopy(original);acquisition['acquisition_id']=IDENTITY['acquisition_id'];acquisition['edition_id']=IDENTITY['edition_id']
 if {k:v for k,v in acquisition.items() if k not in {'acquisition_id','edition_id'}}!={k:v for k,v in original.items() if k not in {'acquisition_id','edition_id'}}:raise ValueError('Acquisition source fields changed')
 oldstate=read(ROOT/LEGACY_WORK/'state.json');oldtargets=[r for r in oldstate['targets'] if r['target_id'] in {SPEC['acquisition'],SPEC['edition']}]
 if len(oldtargets)!=2 or any(r['stage']!='acquired' for r in oldtargets):raise ValueError('Legacy acquired target lineage changed')
 crosswalk_path=EVIDENCE/'old-to-new-identity.json';credit_path=WORK/'SOURCE_CREDIT.md'
 crosswalk=dict(contract='ocd-additive-complete-work-identity-crosswalk-v1',asserted_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),legacy_identity=LEGACY_IDENTITY,new_identity=IDENTITY,work_title=WORK_TITLE,primary_electronic_title=title,author=author,source_boundary=BOUNDARY,primary_title_page=page,source=pin(SPEC['path']),original_acquisition=pin(LEGACY_ACQ),original_acquisition_record=original,new_acquisition_record=acquisition,acquisition_changed_fields=['acquisition_id','edition_id'],accessed_at_preserved=dict(present='accessed_at' in original,value=original.get('accessed_at')),rights_preserved=dict(present='rights' in original,value=original.get('rights')),original_target_timestamps={r['target_type']:r['updated_at'] for r in oldtargets},legacy_catalog_before=before,legacy_author_catalog_is_lineage_only=True,legacy_catalog_files_unchanged=True,no_download_or_new_source=True,qualified_source_scope='Original acquisition scope/warnings remain verbatim as historical lineage. This primary title-page/chapter boundary establishes the distinct authored book; human review, print collation, rights and publication remain separate.',collision_check=collisions)
 evidence=[crosswalk_path.as_posix(),SPEC['path'],credit_path.as_posix(),LEGACY_ACQ.as_posix()]
 edition=dict(edition_id=IDENTITY['edition_id'],title=title,language='en',category='commentary',acquisition_ids=[IDENTITY['acquisition_id']],containing_source=dict(title="The Expositor's Bible",locator='Separately titled Second Samuel volume: title page i; complete chapters I-XXXIII in ii-xxxiv; generated indexes xxxv',evidence=[SPEC['path'],crosswalk_path.as_posix()]))
 work=dict(schema_version='2.0',work_id=WORK_ID,title=WORK_TITLE,creators=[dict(name=author,role='author',evidence=[SPEC['path']])],evidence=evidence,textual_forms=[dict(textual_form_id=IDENTITY['textual_form_id'],language='en',editions=[edition])])
 targets=[]
 for row in oldtargets:
  target=deepcopy(row);target['target_id']=IDENTITY['acquisition_id' if row['target_type']=='acquisition' else 'edition_id']
  target['evidence']=list(dict.fromkeys([*row['evidence'],ACQUISITION.as_posix(),crosswalk_path.as_posix(),credit_path.as_posix()]));targets.append(target)
 state=dict(schema_version='2.0',work_id=WORK_ID,targets=targets)
 for kind,record in [('work',work),('state',state),('acquisition',acquisition)]:validate_record(kind,record,context='Second Samuel additive title-specific scratch proposal')
 scratch_files={WORK/'work.json':canonical(work),WORK/'state.json':canonical(state),ACQUISITION:canonical(acquisition),crosswalk_path:canonical(crosswalk)}
 credit=('# Source credit: '+WORK_TITLE+'\n\nDistinct complete authored book by '+author+'. '+BOUNDARY+'\n\nExisting source: '+SPEC['path']+'; SHA-256 '+SPEC['sha256']+'; '+str(SPEC['bytes'])+' bytes. Original acquired URL: '+original['url']+'.\n\nThis is an additive identity for already retained source; no download or new source process. Original author-catalog files and IDs remain unchanged. Acquisition fields, absent access-date/rights fields and old state timestamps are preserved. Its original author-cohort scope/warnings remain historical lineage, not a complete-series assertion or rights clearance.\n\nSourced via CCEL.org. CCEL-produced electronic files and derivatives of their formatting must not be sold; excerpts must credit CCEL.org. Exact retained permission follows.\n\n'+_io_path(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_text(encoding='utf8')).encode('utf8')
 scratch_files[credit_path]=credit
 for path,data in scratch_files.items():write(SCRATCH,path,data)
 for relative in before:write(SCRATCH,LEGACY_WORK/relative,_io_path(ROOT/LEGACY_WORK/relative).read_bytes())
 references=set([SPEC['path'],*work['evidence'],*(p for target in targets for p in target['evidence'])])
 for reference in references:
  path=Path(reference.split('#',1)[0])
  if not _io_path(SCRATCH/path).exists():write(SCRATCH,path,_io_path(ROOT/path).read_bytes())
 load_work(SCRATCH/WORK/'work.json');validate_acquisition(SCRATCH/ACQUISITION,root=SCRATCH);validate_state(SCRATCH/WORK/'state.json',root=SCRATCH)
 if _files(ROOT/LEGACY_WORK)!=before or _io_path(ROOT/WORK).exists():raise ValueError('Proposal changed canonical homes or legacy bytes')
 for label,path in [('work',WORK/'work.json'),('state',WORK/'state.json'),('acquisition',ACQUISITION),('old-to-new-identity',crosswalk_path),('SOURCE_CREDIT',credit_path)]:write(ROOT,IDENTITY_DIR/(label+('.md' if label=='SOURCE_CREDIT' else '.json')),scratch_files[path])
 proposal=dict(contract='ocd-second-samuel-additive-title-identity-proposal-v1',status='schema-valid-scratch-proposal',work_id=WORK_ID,work_title=WORK_TITLE,identity=IDENTITY,legacy_identity=LEGACY_IDENTITY,new_work=WORK.as_posix(),edition=EDITION.as_posix(),acquisition=ACQUISITION.as_posix(),crosswalk=crosswalk_path.as_posix(),scratch_root=SCRATCH.as_posix(),source_boundary=BOUNDARY,legacy_catalog_before=before,complete_authored_works=1,retained_sources=1,excluded_works=['First Samuel','Joshua'],canonical_writes=False,schema_and_physical_validators='work, state and acquisition pass',files={relative.as_posix():dict(bytes=len(data),sha256=sha(data)) for relative,data in scratch_files.items()},proposal_authorities=[pin(IDENTITY_DIR/(label+('.md' if label=='SOURCE_CREDIT' else '.json'))) for label in ['work','state','acquisition','old-to-new-identity','SOURCE_CREDIT']],collision_check=collisions)
 write(ROOT,IDENTITY_DIR/'proposal.json',canonical(proposal));print(json.dumps(dict(status='pass',proposal=IDENTITY_DIR.as_posix()+'/proposal.json',sha256=sha((ROOT/IDENTITY_DIR/'proposal.json').read_bytes()),scratch_work_files=len(_files(SCRATCH/WORK)),legacy_files_preserved=len(before))))
 return proposal

if __name__=='__main__':propose()
