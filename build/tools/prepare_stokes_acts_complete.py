"""Prove one complete Acts candidate and a bounded append-only identity proposal."""
from copy import deepcopy
from hashlib import sha256
import json,subprocess,sys
from pathlib import Path
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei.stokes_acts_complete_prepare import ROOT,WORK,MEMBERS,TITLE,STATUS,SOURCE,LOG,convert,canonical
from build.tei.stokes_acts_complete_oracle import IMPORTS,PRODUCER_IMPORTS,closure,check,oracle
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct,validate
from ocd_kernel.library.acquisitions import source_member_set_bytes,validate_acquisition
from ocd_kernel.library.identities import validate_identity_update,load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _files,_io_path

DEST=Path('D:/Library/Open Christian Data/candidate-reviews/stokes-acts-complete-20261003-v2')
FORM=WORK+'--acts-complete-retained-en';EDITION=WORK+'--acts-complete-ccel-electronic';ACQUISITION=WORK+'--acts-complete-retained-member-set'
NEW_EDITION=Path('library/works')/WORK/'forms'/FORM/'editions'/EDITION
MEMBER_SET=NEW_EDITION/'source-member-set.json';ACQUISITION_PATH=NEW_EDITION/'acquisitions'/(ACQUISITION+'.json')
BOUNDARY='One authored Acts commentary in two volumes by G.T. Stokes. Volume I Preface defines the early narrative before Paul conversion/Cornelius; Volume II Preface explicitly terminates the survey and describes this volume together with the previous one. Complete source titles, common author/editor, contents and ordered volume envelopes establish one work. Chapters and per-volume indexes are parts; The Expositors Bible is the surrounding series. No entire-author or series completeness claim.'

def sha(raw):return sha256(raw).hexdigest()
def pin(path):
 raw=_io_path(ROOT/path).read_bytes();return dict(path=Path(path).as_posix(),bytes=len(raw),sha256=sha(raw))
def write(path,raw):
 target=_io_path(ROOT/path)
 if target.exists():raise FileExistsError('Preserve prior Acts grouping evidence '+str(path))
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)

def manifest():
 workpath=Path('library/works')/WORK;before=_files(ROOT/workpath);rows=[];authorities=[];readme_parts=[];retained=[]
 def retained_write(path,raw):
  target=_io_path(ROOT/path)
  if target.exists():
   if target.read_bytes()!=raw:raise ValueError('Existing incomplete source authority differs '+str(path))
  else:write(path,raw)
 def authority(name,path,role):authorities.append(dict(name=name,role=role,**pin(path)))
 for position,member in enumerate(MEMBERS,1):
  raw_path=Path('raw/ccel/expositors-bible')/('stokes_expositoracts'+str(position)+'.xml');raw=(ROOT/raw_path).read_bytes();primary=ET.fromstring(raw)
  edition=workpath/'forms'/(WORK+'--'+member+'--retained-en')/'editions'/(WORK+'--'+member+'--ccel-electronic');master=edition/'master.tei.xml';acceptance=edition/'acceptance.json';acq=edition/'acquisitions'/(WORK+'--'+member+'--acquired.json')
  package_path=workpath/'integration/stokes-retained-current-20261003-v1'/member/'inputs/package';package=CandidatePackage.load(ROOT/package_path)
  acquired=json.loads((ROOT/acq).read_bytes());rows.append(dict(member_id=member,volume=position,raw_sha256=sha(raw),raw_bytes=len(raw),raw_elements=sum(1 for n in primary.iter()),title=primary.findtext('.//DC.Title'),package_sha256=package.sha256,master_sha256=pin(master)['sha256'],acceptance_sha256=pin(acceptance)['sha256'],acquisition_sha256=pin(acq)['sha256'],source_url=acquired['url']))
  authority(member+'-raw',raw_path,'primary-source')
  for name in package.member_names:authority(member+'-'+('manifest' if name=='manifest.json' else name),package_path/name,'existing-source-package-lineage')
  authority(member+'-master',master,'unchanged-legacy-master');authority(member+'-acceptance',acceptance,'unchanged-legacy-acceptance');authority(member+'-acquisition',acq,'primary-acquired-uri-authority')
  readme_parts.append(package.member_bytes('README.source.md').decode('utf8'))
  retained.append(dict(path=raw_path.as_posix(),bytes=len(raw),sha256=sha(raw),media_type='application/xml',scope='Entire already acquired Stokes Acts Volume '+str(position)+' in complete work source order'))
 for ordinal,path in enumerate(sorted(before)):
  retained_path=workpath/path
  if path in {'work.json','state.json'}:
   retained_path=SOURCE/('legacy-'+path);retained_write(retained_path,_io_path(ROOT/workpath/path).read_bytes())
  authority('inherited-file-'+str(ordinal),retained_path,'unchanged-inherited-work-authority')
 profile=dict(contract='ocd-stokes-acts-complete-profile-v1',complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),title=TITLE,boundary=BOUNDARY,volumes=rows,canonical_before=before)
 policy=dict(contract='ocd-stokes-acts-complete-policy-v1',ordered_members=list(MEMBERS),complete_works=1,acquired_volumes=2,actual_group_and_raw_inverse=True,exact_metadata=True,uri_base_addition_only=True,no_acquisition=True,oracle_imports=list(IMPORTS),producer_imports=list(PRODUCER_IMPORTS))
 readme=('# Stokes: The Acts of the Apostles, one complete retained electronic work\n\n'+BOUNDARY+'\n\nOne candidate TEI preserves both entire source volume envelopes once in order. The inherited author catalog identity and every legacy master, acceptance, source record and ID remain unchanged. Exactly 57 relative query refs receive only their original acquired volume URL as XML base; targets remain literal and no cross-volume target is invented. Every raw header field, CSS, source document prefix and full legacy accepted header remain visible in their owning volume records. All15 volumeI source-broken links remain qualified; volumeII has0. No acquisition or download.\n\nHuman review, print collation, rights and publication remain separate. Sourced via CCEL.org. Do not sell CCEL electronic files or derivatives of their formatting; exact retained permission and each source credit follow.\n\n'+'\n\n'.join(readme_parts)+'\n\n## Retained permission evidence\n\n'+(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_text(encoding='utf8')).encode('utf8')
 scope=TITLE+', complete two-volume retained electronic commentary, Volume I then Volume II. Each entire source XML is preserved; certain print edition lineage, human review, rights and publication remain separate. Derived binding of existing sources, no acquisition or download.'
 urls=[row['source_url'] for row in rows]
 acquired=dict(schema_version='2.0',acquisition_id=ACQUISITION,edition_id=EDITION,provider='CCEL',url=urls[0],route='born-digital',source_path=MEMBER_SET.as_posix(),source_kind='retained-member-set',source_scope=scope,retained_files=retained,warnings=['Derived ordered binding of two existing acquired source records; no source download or new provider acquisition.','Derived entry URL is the original Volume I acquired URL; member URLs in source order: '+', '.join(urls)+'. No provider entry URL or download is invented.','CCEL formatting, attribution, human/print review, rights and publication remain separate.'])
 descriptor=source_member_set_bytes(acquired);acquired.update(source_bytes=len(descriptor),source_sha256=sha(descriptor))
 for name,value in [('profile.json',canonical(profile)),('policy.json',canonical(policy)),('README.source.md',readme),('proposed-source-member-set.json',descriptor),('proposed-acquisition.json',canonical(acquired))]:retained_write(SOURCE/name,value)
 for name,path,role in [('complete-profile','profile.json','complete-source-feature-profile'),('complete-policy','policy.json','independent-validation-policy'),('complete-readme','README.source.md','source-rights-attribution'),('proposed-member-set','proposed-source-member-set.json','derived-ordered-existing-source-set'),('proposed-acquisition','proposed-acquisition.json','append-only-derived-existing-acquisition-binding')]:authority(name,SOURCE/path,role)
 authority('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema');authority('package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema');authority('ccel-permission',Path('sources/commentaries/expositors-bible/ccel-permission.md'),'source-rights-evidence')
 authority('acquisition-schema',Path('schemas/v2/acquisition.schema.json'),'acquisition-validation-schema')
 for ordinal,path in enumerate(sorted(set(IMPORTS+PRODUCER_IMPORTS))):authority('implementation-'+str(ordinal),Path(path),'observed-import-implementation-dependency')
 record=dict(contract='ocd-source-manifest-v1',source_id='ccel-stokes-acts-complete-v1',work_id=WORK,ticket_id='existing-stokes-acts-complete-work-reconciliation',authorities=authorities,
  converter=dict(id=convert.converter_id,version=convert.converter_version,callable='convert',implementation_path='build/tei/stokes_acts_complete_prepare.py',implementation_sha256=pin(Path('build/tei/stokes_acts_complete_prepare.py'))['sha256']),
  validator=dict(id=oracle.oracle_id,version=oracle.oracle_version,callable='oracle',implementation_path='build/tei/stokes_acts_complete_oracle.py',implementation_sha256=pin(Path('build/tei/stokes_acts_complete_oracle.py'))['sha256'],import_closure_sha256=closure()),
  package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=pin(Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'))['sha256']),scope=dict(kind='complete-existing-authored-work',source_volumes=2,complete_works=1,new_acquisition=False),source_order=dict(ordered_members=list(MEMBERS)))
 write(SOURCE/'source-manifest.json',canonical(record));return SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT)

def finish_proposal(source,stage,before):
 workpath=Path('library/works')/WORK
 original=json.loads(source.authority_path('inherited-file-'+str(sorted(before).index('work.json'))).read_bytes())
 inherited_state=json.loads(source.authority_path('inherited-file-'+str(sorted(before).index('state.json'))).read_bytes())
 support={}
 references=set(original.get('evidence',[]))
 for target in inherited_state['targets']:references.update(target.get('evidence',[]))
 for reference in sorted(references):
  relative=Path(reference.split('#',1)[0])
  if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe inherited evidence reference '+reference)
  origin=_io_path(ROOT/relative);destination=_io_path(stage/relative)
  if destination.exists():
   if destination.read_bytes()!=origin.read_bytes():raise ValueError('Inherited evidence differs '+reference)
  else:
   destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(origin.read_bytes())
  support[reference]=pin(relative)
 staged_work=load_work(stage/workpath/'work.json');validate_identity_update(original,staged_work)
 validate_acquisition(stage/ACQUISITION_PATH,root=stage);validate_state(stage/workpath/'state.json',root=stage)
 after=_files(stage/workpath)
 if any(after[p]!=value for p,value in before.items() if p not in {'work.json','state.json'}):raise ValueError('Identity proposal changed legacy authority')
 report=dict(status='schema-valid-proposal-only',complete_works=1,source_volumes=2,form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION,proposal_root=stage.as_posix(),before=before,after=after,inherited_evidence_support=support,canonical_unchanged=_files(ROOT/workpath)==before,source_member_set_sha256=sha(source.authority_path('proposed-member-set').read_bytes()),source_member_set_bytes=len(source.authority_path('proposed-member-set').read_bytes()),canonical_installation=False,new_download=False)
 write(LOG/'append-only-identity-proposal.json',canonical(report));return report

def proposal(source):
 stage=DEST/'identity-proposal';stage.mkdir(exist_ok=False);workpath=Path('library/works')/WORK;before=_files(ROOT/workpath)
 def save(relative,raw):
  path=_io_path(stage/relative);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
 for relative in before:save(workpath/relative,_io_path(ROOT/workpath/relative).read_bytes())
 for authority in source.record['authorities']:save(Path(authority['path']),_io_path(ROOT/authority['path']).read_bytes())
 original=json.loads(_io_path(ROOT/workpath/'work.json').read_bytes());work=deepcopy(original);state=json.loads(_io_path(ROOT/workpath/'state.json').read_bytes())
 if any(f['textual_form_id']==FORM for f in work['textual_forms']):raise ValueError('Proposed complete-work identity already exists')
 work['textual_forms'].append(dict(textual_form_id=FORM,language='en',editions=[dict(edition_id=EDITION,title=TITLE,language='en',category='commentary',acquisition_ids=[ACQUISITION])]))
 references=[MEMBER_SET.as_posix(),ACQUISITION_PATH.as_posix(),(SOURCE/'profile.json').as_posix()]
 work['evidence'].extend(references);validate_identity_update(original,work)
 from datetime import datetime,timezone
 at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
 for identity,kind in [(ACQUISITION,'acquisition'),(EDITION,'edition')]:state['targets'].append(dict(target_type=kind,target_id=identity,stage='acquired',updated_at=at,evidence=references,reason='Complete authored Acts binding derived from two preserved existing acquired sources; no new download.'))
 save(workpath/'work.json',canonical(work));save(workpath/'state.json',canonical(state));save(MEMBER_SET,source.authority_path('proposed-member-set').read_bytes());save(ACQUISITION_PATH,source.authority_path('proposed-acquisition').read_bytes())
 return finish_proposal(source,stage,before)

def prove(source,package,proof_name='proof'):
 baseline=validate(source,package,oracle);schema=etree.XMLSchema(etree.parse(str(source.authority_path('tei-p5-xsd'))));root=etree.fromstring(package.member_bytes('content.tei.xml'));ns='{http://www.tei-c.org/ns/1.0}';xml='{http://www.w3.org/XML/1998/namespace}';proofdir=DEST/proof_name;proofdir.mkdir(exist_ok=False);results=[]
 for label in ['volume-order','volume-identity','first-volume-text','second-volume-tail','cross-volume-note-ownership','uri-base','uri-target','complete-source-header','source-document-prefix','extra-volume-payload','outer-payload','volume-omission']:
  changed=deepcopy(root);group=changed.find(ns+'text/'+ns+'group')
  if label=='volume-order':first=group[0];group.remove(first);group.append(first)
  elif label=='volume-identity':group[0].set(xml+'id','wrong-volume')
  elif label=='first-volume-text':next(n for n in group[0].iter(ns+'p') if n.text).text+=' ALTERED'
  elif label=='second-volume-tail':next(n for n in group[1].iter() if n.tail and n.getparent().tag==ns+'p').tail+=' ALTERED'
  elif label=='cross-volume-note-ownership':note=next(group[0].iter(ns+'note'));note.getparent().remove(note);next(group[1].iter(ns+'p')).append(note)
  elif label=='uri-base':next(n for n in group[0].iter(ns+'ref') if n.get(xml+'base')).set(xml+'base','https://example.invalid/')
  elif label=='uri-target':next(n for n in group[1].iter(ns+'ref') if n.get(xml+'base')).set('target','?wrong=target')
  elif label=='complete-source-header':changed.find('.//'+ns+'note[@type="complete-source-head-field"]').text+=' ALTERED'
  elif label=='source-document-prefix':changed.find('.//'+ns+'note[@type="source-document-prefix"]').text+=' ALTERED'
  elif label=='extra-volume-payload':etree.SubElement(next(group[0].iter(ns+'p')),ns+'seg').text='Unacquired payload'
  elif label=='outer-payload':stand=etree.SubElement(changed,ns+'standOff');items=etree.SubElement(stand,ns+'list');etree.SubElement(items,ns+'item').text='Unacquired outer payload'
  elif label=='volume-omission':group.remove(group[1])
  schema.assertValid(changed);directory=proofdir/label;directory.mkdir()
  for name in package.member_names:(directory/name).write_bytes(package.member_bytes(name))
  altered=etree.tostring(changed,encoding='UTF-8',xml_declaration=True);(directory/'content.tei.xml').write_bytes(altered);record=json.loads((directory/'manifest.json').read_bytes())
  for item in record['members']:
   if item['name']=='content.tei.xml':item.update(bytes=len(altered),sha256=sha(altered))
  (directory/'manifest.json').write_bytes(canonical(record));mutant=CandidatePackage.load(directory)
  try:validate(source,mutant,oracle)
  except ValueError as error:results.append(dict(label=label,p5_valid=True,rejected=True,reason=str(error)))
  else:raise ValueError('Stokes complete oracle admitted mutation '+label)
 replays=[]
 for number in (1,2):
  destination=proofdir/('fresh-process-'+str(number));subprocess.run([sys.executable,'-B','-m','build.tei.stokes_acts_complete_prepare',str(destination),'--source-manifest',str(source.path)],cwd=ROOT,check=True,capture_output=True)
  replay=CandidatePackage.load(destination)
  if any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise ValueError('Stokes complete fresh replay differs')
  replays.append(dict(path=destination.as_posix(),package_sha256=replay.sha256,all_six_member_bytes_equal=True))
 negatives=[]
 for module,extra in [('build.tei.stokes_acts_complete_oracle','ocd_kernel.tei.writer'),('build.tei.stokes_acts_complete_prepare','ocd_kernel.reconstruction.verifier')]:
  try:closure(module,extra)
  except ValueError as error:negatives.append(dict(module=module,rejected=True,reason=str(error)))
  else:raise ValueError('Unexpected complete import admitted')
 result=dict(status='pass',complete_works=1,acquired_volumes=2,candidate_package_sha256=package.sha256,source_manifest_sha256=source.sha256,oracle_report_sha256=baseline.sha256,direct_review=check(source,package),mutations=results,replays=replays,import_negatives=negatives,canonical_installation=False)
 write(LOG/'candidate-completion-receipt.json',canonical(result));return result

if __name__=='__main__':
 proof_name='proof'
 if sys.argv[1:]==['--resume-manifest']:
  if (ROOT/SOURCE/'source-manifest.json').exists() or any(DEST.iterdir()):raise ValueError('Manifest resume admits only incomplete source metadata and an empty destination')
  source=manifest();package=reconstruct(source,DEST/'package',convert);print(json.dumps(dict(package_sha256=package.sha256,direct=check(source,package)['status'])));proposal(source)
 elif sys.argv[1:]==['--resume-proof-v2']:
  source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT);package=CandidatePackage.load(DEST/'package');proof_name='proof-v2'
  proposal_receipt=json.loads((ROOT/LOG/'append-only-identity-proposal.json').read_bytes())
  if not proposal_receipt['canonical_unchanged'] or _files(ROOT/Path('library/works')/WORK)!=proposal_receipt['before']:raise ValueError('Canonical source work changed before proof resume')
 elif sys.argv[1:]==['--resume-proposal-and-proof']:
  source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT);package=CandidatePackage.load(DEST/'package')
  before=json.loads(source.authority_path('complete-profile').read_bytes())['canonical_before']
  if _files(ROOT/Path('library/works')/WORK)!=before:raise ValueError('Canonical source work changed before proposal resume')
  finish_proposal(source,DEST/'identity-proposal',before)
 else:
  if sys.argv[1:]:raise ValueError('Unexpected completion arguments')
  DEST.mkdir(exist_ok=False);source=manifest();package=reconstruct(source,DEST/'package',convert);print(json.dumps(dict(package_sha256=package.sha256,direct=check(source,package)['status'])));proposal(source)
 proof=prove(source,package,proof_name);print(json.dumps(dict(status=proof['status'],package_sha256=package.sha256,receipt_sha256=pin(LOG/'candidate-completion-receipt.json')['sha256'])))
