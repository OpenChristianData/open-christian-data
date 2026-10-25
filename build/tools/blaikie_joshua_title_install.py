"""Guarded additive installation of complete Joshua; legacy catalog stays exact."""
from contextlib import ExitStack
from datetime import datetime,timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from build.tei.blaikie_joshua_retained_native_prepare import ROOT,LOG,SOURCE_DIR,canonical
from build.tei.blaikie_joshua_retained_native_oracle import _oracle
from build.tools.propose_blaikie_joshua_title_identity import WORK as WORK_ID,FORM,EDITION,ACQUISITION,REL as WORK,OLD_REL,ACQ_REL,CROSSWALK,PROPOSAL,records
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.path_io import io_path,resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,validate
from ocd_kernel.tei.acceptance import build_acceptance_record,make_file_binding,write_acceptance,validate_acceptance,PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.install_accepted import _files,_commit_generation
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.projection.categories.commentary import project_accepted_commentary,verify_accepted_commentary

LIBRARY=Path('D:/Library/Open Christian Data')
SOURCE=SOURCE_DIR/'blaikie-expositorjosh.source-manifest-v3.json'
PACKAGE=LIBRARY/'candidate-reviews/blaikie-joshua-existing-readable-20261003-v3/blaikie-expositorjosh/package'
EDITION_PATH=WORK/'forms'/FORM/'editions'/EDITION
LANE=WORK/'integration/blaikie-joshua-complete-20261003-v1'
FIXTURE=ROOT/'.tmp_audit/blaikie-joshua-title-fixture-20261003-v1'
SCOPE='Complete authored Book of Joshua from its one already acquired CCEL electronic witness: title page i, Chapters I through XXXIII at ii through xxxiv including substantive introduction, all notes and verse, and generated indexes xxxv. First and Second Samuel, the series and legacy author catalog are excluded. Human review, print collation, rights clearance and publication remain separate.'
SOURCE_STATUS='Agent-reviewed reconstruction of an existing acquired electronic witness. Human review, print collation, CCEL formatting rights and publication remain separate gates.'
MASTER_STATUS='Agent-accepted complete faithful authored Book of Joshua from its one already acquired electronic witness. Human review, print collation, rights and publication remain separate.'
NOTE='One complete authored Book of Joshua; additive title identity preserves all legacy catalog records and the exact retained native body.'
PACKAGE_PIN='bbddb9ff7e13e5b1aba72851a5a640649abbea4620588e5c702cd48c34f70e4d'
PROOF_PIN='e518ee5b280c8e8eb517ad7c384d14c4f91ce1aaf9d82f004c6196f37f1f475b'
TITLE_REVIEW=LANE/'title-identity-review.json'
CREDIT_ASSIGNMENT=b'\n\nThe preserved dated title identity proposal records an earlier draft. The current complete Book of Joshua assignment is recorded in integration/blaikie-joshua-complete-20261003-v1/title-identity-review.json; the completed guarded installation journal records canonical installation.\n'

def read(path):return json.loads(io_path(path).read_bytes())
def digest(path):return sha256(io_path(path).read_bytes()).hexdigest()
def write(root,path,raw):
 target=io_path(root/path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);return root/path
def write_json(root,path,value):return write(root,path,canonical(value))
def copy(root,stage,path):return write(stage,path,io_path(root/path).read_bytes())

def projection_gate(root,acceptance):
 try:
  result=project_accepted_commentary(root,acceptance_path=acceptance)
  errors=verify_accepted_commentary(root,acceptance_path=acceptance,rows=result['rows'],receipt=result['receipt'])
  return dict(status='pass' if not errors else 'held',rows=len(result['rows']),errors=errors,raw_errors=errors)
 except PipelineError as error:
  detail=str(error)
  for prefix in sorted({str(root),root.as_posix(),str(io_path(root))},key=len,reverse=True):detail=detail.replace(prefix,'<reviewed-root>')
  return dict(status='held',rows=0,errors=[detail],raw_errors=[str(error)])
def projection_signature(gate):return {k:gate[k] for k in ('status','rows','errors')}

def source_gate():
 source=SourceManifest.load(ROOT/SOURCE,repository_root=ROOT);package=CandidatePackage.load(PACKAGE)
 if package.sha256!=PACKAGE_PIN or digest(ROOT/LOG/'candidate-completion-receipt-v3.json')!=PROOF_PIN:raise PipelineError('Frozen Joshua source proof/package differs')
 report=validate(source,package,_oracle);proof=read(ROOT/LOG/'candidate-completion-receipt-v3.json')
 if proof['status']!='pass' or proof['source_manifest_sha256']!=source.sha256 or proof['package_sha256']!=package.sha256 or proof['oracle_report_sha256']!=report.sha256:raise PipelineError('Fresh Joshua source binding differs')
 if len(proof['mutations'])!=36 or not all(r['rejected'] and r['schema_valid'] for r in proof['mutations']):raise PipelineError('Joshua semantic proof differs')
 if len(proof['source_package_identity_challenges'])!=8 or not all(r['rejected'] and r['candidate_schema_valid'] and r['source_sdk_contract_valid'] and r['p5_valid'] for r in proof['source_package_identity_challenges']):raise PipelineError('Joshua contract proof differs')
 if len(proof['replays'])!=2 or not all(r['fresh_isolated_python'] and r['all_six_members_byte_equal'] for r in proof['replays']):raise PipelineError('Joshua replay proof differs')
 for row in proof['replays']:
  replay=CandidatePackage.load(Path(row['package_path']))
  if replay.sha256!=package.sha256 or any(replay.member_bytes(n)!=package.member_bytes(n) for n in package.member_names):raise PipelineError('Frozen Joshua replay bytes differ')
 if set(proof['import_negatives'])!={'oracle','producer'} or not all(r['rejected'] for r in proof['import_negatives'].values()):raise PipelineError('Joshua strict import negatives differ')
 return source,package,report

def dependencies(*,bootstrap=False):
 source=SourceManifest.load(ROOT/SOURCE,repository_root=ROOT)
 paths={Path(a['path']) for a in source.record['authorities']}
 paths.update((SOURCE,LOG/'candidate-completion-receipt-v3.json',CROSSWALK,PROPOSAL/'proposal-receipt.json'))
 paths.update(Path(p) for p in ('build/tools/blaikie_joshua_title_install.py','build/tools/probe_blaikie_joshua_title_execution.py','build/tools/propose_blaikie_joshua_title_identity.py','build/tools/prove_blaikie_joshua_candidate.py','build/tools/renew_blaikie_joshua_source_contract.py','build/tools/assess_blaikie_joshua_retained.py'))
 paths.update(p.relative_to(ROOT) for directory,pattern in [('schemas/v2','*.json'),('ocd_kernel/tei/vendor/xsd','*.xsd'),('ocd_kernel/reconstruction/schemas','*.json')] for p in (ROOT/directory).rglob(pattern))
 if bootstrap:
  physical=resolve_path(ROOT,strict=True)
  for module in sys.modules.copy().values():
   filename=getattr(module,'__file__',None)
   if filename:
    path=resolve_path(Path(filename),strict=True)
    if path.is_relative_to(physical):paths.add(path.relative_to(physical))
 else:
  paths.add(LOG/'title-execution-imports-v1.json');record=read(ROOT/LOG/'title-execution-imports-v1.json')
  if record['status']!='pass' or record['work_id']!=WORK_ID or record['complete_works']!=1 or record['source_members']!=1:raise PipelineError('Joshua actual execution scope differs')
  for row in record['first_party_files']:
   if digest(ROOT/row['path'])!=row['sha256']:raise PipelineError('Joshua actual execution code drifted: '+row['path'])
   paths.add(Path(row['path']))
 return paths

def identity():return dict(work_id=WORK_ID,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION)
def source_binding(acquisition):return {k:acquisition[k] for k in ('source_path','source_sha256','source_bytes','source_scope')}
def bound(raw,acquisition,revision):
 result=bind_reviewed_header(raw,expected_sha256=sha256(raw).hexdigest(),identity=identity(),source=source_binding(acquisition),source_url=acquisition['url'],declared_scope=SCOPE,revision=revision)
 old_title=b"<title>The Expositor's Bible: The Book of Joshua</title>"
 if result.count(SOURCE_STATUS.encode())!=1 or not result.startswith(b'<?xml') or result.count(old_title)!=2:raise PipelineError('Joshua exact publication/title preimage differs')
 result=result.replace(SOURCE_STATUS.encode(),MASTER_STATUS.encode(),1).replace(old_title,b'<title>The Book of Joshua</title>',1)
 if result.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise PipelineError('Joshua binding changed native body bytes')
 return result

def allowed_paths(package):
 paths={'work.json','state.json','SOURCE_CREDIT.md',ACQ_REL.relative_to(WORK).as_posix()}
 paths.update((EDITION_PATH/n).relative_to(WORK).as_posix() for n in ('master.tei.xml','acceptance.json'))
 paths.update((LANE/'inputs/package'/n).relative_to(WORK).as_posix() for n in package.member_names)
 paths.update((LANE/n).relative_to(WORK).as_posix() for n in ('identity-crosswalk.json','title-identity-review.json','source-review.json','candidate.tei.xml','source-accounting.json','validation.json','accounting.json','fidelity.json','reproducibility.json','schema.json','closure.json','review.json'))
 return paths

def staged_work(original):
 result=json.loads(json.dumps(original));result['evidence'].append(TITLE_REVIEW.as_posix());return result

def title_assignment(work,acquisition,at,source,package):
 return dict(contract='ocd-current-authored-work-title-assignment-v1',status='agent-reviewed',reviewer='agent:blaikie-joshua-title-identity-review',reviewed_at=at,
  identity=identity(),work_title=work['title'],creators=work['creators'],scope=dict(kind='work',declared=SCOPE),complete_authored_works=1,retained_source_members=1,
  historical_proposal=dict(path=CROSSWALK.as_posix(),sha256=digest(ROOT/CROSSWALK),preserved_status='proposal',disposition='Immutable dated draft input; its earlier remaining items are preserved as history.'),
  current_assignment='The Book of Joshua is one complete authored work; the series and inherited author catalog are containers. The title-specific identities are additive and every legacy catalog record remains unchanged.',
  primary_source=dict(source_binding(acquisition))|dict(url=acquisition['url']),
  source_manifest_sha256=source.sha256,source_package_sha256=package.sha256,source_review=dict(path=(LOG/'candidate-completion-receipt-v3.json').as_posix(),sha256=PROOF_PIN),
  legacy_catalog=dict(work_id='expositors-bible--william-g-blaikie',role='historical author container lineage only',all_six_files_byte_preserved=True),
  source_boundary='Title page i; all33 authored chapters ii through xxxiv including substantive introduction; notes, verse and generated indexes xxxv. No Samuel or omitted/shared authored content.',
  acquisition_conservation='Only acquisition_id and edition_id remapped; every original nonidentity field and absence preserved. Historical source_scope and warnings remain verbatim.',
  metadata_factory=dict(path='build/tools/propose_blaikie_joshua_title_identity.py',sha256=digest(ROOT/'build/tools/propose_blaikie_joshua_title_identity.py')),
  installer=dict(path='build/tools/blaikie_joshua_title_install.py',sha256=digest(Path(__file__))),
  installation_evidence='This record reviews the current title assignment. A completed guarded operation journal records canonical installation.',human_decision='not-recorded',rights_publication='separate unresolved gates',new_download=False)

def expected_state(initial,at):
 result=json.loads(json.dumps(initial))
 for row in result['targets']:row['evidence'].append(TITLE_REVIEW.as_posix())
 edition=next(r for r in result['targets'] if r['target_id']==EDITION)
 edition.update(stage='accepted',updated_at=at,reason=PROMOTED_MASTER_REASON)
 edition['evidence']+=[(EDITION_PATH/'master.tei.xml').as_posix(),(EDITION_PATH/'acceptance.json').as_posix()]
 return result

def prepare(stage,*,bootstrap=False):
 stage=stage.absolute()
 if stage.exists() or stage.parent!=LIBRARY/'candidate-reviews' or not stage.name.startswith('blaikie-joshua-s-'):raise PipelineError('Fresh external Joshua stage required')
 if io_path(ROOT/WORK).exists():raise PipelineError('Joshua title work already exists; no replacement')
 source,package,report=source_gate();work,initial,acquisition,_=records()
 proposal=ROOT/PROPOSAL/'fixture'
 if read(proposal/WORK/'work.json')!=work or read(proposal/WORK/'state.json')!=initial or read(proposal/ACQ_REL)!=acquisition:raise PipelineError('Joshua exact identity proposal differs')
 crosswalk=read(ROOT/CROSSWALK);legacy=_files(ROOT/OLD_REL)
 if legacy!=crosswalk['legacy_generation_before_after'] or len(legacy)!=6:raise PipelineError('Joshua legacy catalog generation differs')
 stage.mkdir()
 for path in legacy:copy(ROOT,stage,OLD_REL/path)
 for path in {Path(p.split('#',1)[0]) for p in work['evidence']+[p for row in initial['targets'] for p in row['evidence']]}:copy(ROOT,stage,path)
 write_json(stage,WORK/'work.json',staged_work(work));write_json(stage,ACQ_REL,acquisition)
 for a in source.record['authorities']:copy(ROOT,stage,Path(a['path']))
 validate_acquisition(stage/ACQ_REL,root=stage)
 for name in package.member_names:write(stage,LANE/'inputs/package'/name,package.member_bytes(name))
 write(stage,LANE/'source-review.json',io_path(ROOT/LOG/'candidate-completion-receipt-v3.json').read_bytes())
 copy(ROOT,stage,CROSSWALK);write(stage,LANE/'identity-crosswalk.json',io_path(ROOT/CROSSWALK).read_bytes())
 at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');revision=dict(id='blaikie-joshua-complete-20261003-v1',date=at[:10],note=NOTE)
 assignment=write_json(stage,TITLE_REVIEW,title_assignment(work,acquisition,at,source,package))
 master=bound(package.member_bytes('content.tei.xml'),acquisition,revision);candidate=write(stage,LANE/'candidate.tei.xml',master)
 if errors:=validate_file(candidate):raise PipelineError(str(errors))
 expected=[dict(path=r['path'],position=i) for i,r in enumerate(acquisition['retained_files'],1)]
 included=[dict(path=r['path'],position=i,bytes=r['bytes'],sha256=r['sha256'],scope=r['scope']) for i,r in enumerate(acquisition['retained_files'],1)]
 common=dict(identity=identity(),source=source_binding(acquisition),candidate=make_file_binding(stage,candidate),accepted_scope=dict(kind='work',declared=SCOPE),scope=SCOPE,expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],source_manifest_sha256=source.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,representation_revision=revision,staged_at=at)
 accounting=write_json(stage,LANE/'source-accounting.json',common|dict(scope=acquisition['source_scope'],source_sha256=acquisition['source_sha256'],source_bytes=acquisition['source_bytes'],complete_works=1,source_members=1,omitted_readable_elements=0,source_review=make_file_binding(stage,stage/LANE/'source-review.json'),identity_crosswalk=make_file_binding(stage,stage/LANE/'identity-crosswalk.json'),current_title_assignment=make_file_binding(stage,assignment),source_identity_qualification='Frozen predecessor source manifest/package work ID is the legacy author catalog; native source proof is one complete Joshua. This additive title edition binds the new authored work, with every source/acquisition nonidentity field preserved.'))
 command='py -3 -B -m build.tools.blaikie_joshua_title_install "'+stage.as_posix()+'" --prepare'+(' --bootstrap' if bootstrap else '')
 technical=dict(producer=dict(id='ocd-blaikie-joshua-title-install'),checker=dict(id=source.record['validator']['id']),shared_assumptions=['Bennett mapping/checker inspected as maintained ancestors; prior exposure declared.'],independent_corroboration='Independent whole actual source fields/order/attributes/ownership and complete source body inverse;2352 legacy source graph records and2307 native feature records; primary header/prolog/literal XML prefix;40 exact relative URI contexts; P5;36 valid semantic and8 valid contract negatives; two fresh six-member package replays. Additive raw-backed title metadata and exact nonidentity acquisition conservation are independently recomputed.')
 for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
  proof=write_json(stage,LANE/(name+'.json'),common|dict(status='pass',command=command,exit_code=0,claim=name,current_source_producer=dict(source.record['converter']),title_binding_implementation_sha256=digest(Path(__file__))))
  technical[name]=dict(path=proof,status='pass',command=command,exit_code=0)
 coverage=['Complete Joshua title page, all33 authored chapters including introduction and all generated indexes','All2285 native source elements,22 administrative comments,29 notes,22 verse groups and148 verse lines, exact40 relative links','All actual header/prolog/XML prefix fields, source attributes, text/tails, attachment, original IDs, local links and full raw body inverse','Complete2352-row qualified legacy graph, exact title identity/crosswalk and complete acquired source scope']
 review=dict(reviewer='agent:blaikie-joshua-complete-source-review',reviewed_at=at,coverage=dict(status='complete',declared=SCOPE,reached=coverage,inspected=coverage,unreviewed=[]),source_quality_uncertainty=['Retained electronic witness only; no print collation or browser/CSS equivalence.','Two exact missing raw next/prev toc targets remain typed unresolved; no invented target.','Qualified converter-only LIB036 replay is not historical package byte recovery or old oracle validation.','Legacy acquisition source_scope/warnings are preserved verbatim as historical qualification; new authored identity follows independently checked primary work boundary.','Human review, rights clearance and publication remain separate.'],discrepancies=[],unreviewed_residuals=['Actual accepted-master commentary projection is separately measured.'])
 review_path=write_json(stage,LANE/'review.json',common|review)
 decision=dict(source_local_disposition='Agent accepts one complete faithful authored Book of Joshua, with complete raw-backed source fidelity and additive title identity.',blockers=[],agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=SCOPE,unresolved_claims=[],unassessed_stronger_claims=['human review','print collation','browser/CSS visual equivalence','rights clearance','publication','Samuel/author/series completeness','downstream commentary projection','historical package byte recovery']),human_decision=dict(status='not-recorded'))
 record=build_acceptance_record(stage,identity=identity(),candidate_path=candidate,source_accounting_path=accounting,scope=dict(kind='work',declared=SCOPE,expected_members=expected,included_members=included,excluded_members=[]),technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
 master_path=write(stage,EDITION_PATH/'master.tei.xml',master);record['promotion']=dict(record['promotion'])|dict(status='promoted',promoted_at=at,master=make_file_binding(stage,master_path));write_acceptance(stage/EDITION_PATH/'acceptance.json',record)
 write(stage,WORK/'SOURCE_CREDIT.md',package.member_bytes('README.source.md')+CREDIT_ASSIGNMENT);write_json(stage,WORK/'state.json',expected_state(initial,at))
 load_work(stage/WORK/'work.json');validate_state(stage/WORK/'state.json',root=stage);validate_acceptance(stage/EDITION_PATH/'acceptance.json',root=stage)
 gate=projection_gate(stage,stage/EDITION_PATH/'acceptance.json')
 for path in dependencies(bootstrap=bootstrap):
  if not io_path(stage/path).exists():copy(ROOT,stage,path)
 receipt=dict(contract='ocd-blaikie-joshua-title-stage-v1',status='staged-only',work_id=WORK_ID,complete_works=1,source_members=1,stage_root=stage.as_posix(),staged_at=at,before={},after=_files(stage/WORK),legacy_before=legacy,revision=revision,master_sha256=digest(master_path),acceptance_sha256=digest(stage/EDITION_PATH/'acceptance.json'),package_sha256=package.sha256,oracle_report_sha256=report.sha256,projection_gate=gate,source_manifest_sha256=source.sha256,bootstrap=bootstrap,external_runtime_files=[] if bootstrap else read(ROOT/LOG/'title-execution-imports-v1.json')['external_runtime_files'],dependency_files={p.as_posix():digest(ROOT/p) for p in sorted(dependencies(bootstrap=bootstrap))})
 if set(receipt['after'])!=allowed_paths(package):raise PipelineError('Joshua generation exceeds exact24 paths')
 write_json(stage,Path('stage-receipt.json'),receipt);return dict(status='staged-only',stage_root=stage.as_posix(),receipt_sha256=digest(stage/'stage-receipt.json'),after_files=len(receipt['after']))

def execution(receipt):
 pins={resolve_path(ROOT/p,strict=True):(p,h) for p,h in receipt['dependency_files'].items()};observed={}
 for module in sys.modules.copy().values():
  filename=getattr(module,'__file__',None)
  if not filename:continue
  path=resolve_path(Path(filename),strict=True)
  if path.is_relative_to(resolve_path(ROOT,strict=True)) or path.is_relative_to(resolve_path(LIBRARY,strict=True)):
   if path not in pins:raise PipelineError('Unexpected executed Joshua dependency: '+path.as_posix())
   relative,pin=pins[path]
   if digest(path)!=pin:raise PipelineError('Joshua executed implementation drifted')
   observed[relative]=pin
 for row in receipt['external_runtime_files']:
  if not Path(row['path']).is_absolute() or io_path(Path(row['path'])).stat().st_size!=row['bytes'] or digest(Path(row['path']))!=row['sha256']:raise PipelineError('Joshua late external runtime drifted: '+row['path'])
 if not observed:raise PipelineError('Joshua actual execution census is empty')
 return observed

def preflight(stage,pin,root=ROOT):
 stage=resolve_path(stage,strict=True);root=resolve_path(root,strict=True)
 if root!=resolve_path(ROOT,strict=True):
  if root!=resolve_path(FIXTURE,strict=True) or (root/'.ocd-blaikie-joshua-fixture').read_text()!='fixture-only\n':raise PipelineError('Joshua exact fixture path required')
 if root==stage or root in stage.parents or stage in root.parents or stage.parent!=resolve_path(LIBRARY/'candidate-reviews',strict=True) or not stage.name.startswith('blaikie-joshua-s-'):raise PipelineError('Joshua stage/root boundary differs')
 if not isinstance(pin,str) or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin) or digest(stage/'stage-receipt.json')!=pin:raise PipelineError('Joshua immutable receipt pin differs')
 receipt=read(stage/'stage-receipt.json')
 if receipt['contract']!='ocd-blaikie-joshua-title-stage-v1' or receipt['status']!='staged-only' or receipt['work_id']!=WORK_ID or receipt['complete_works']!=1 or receipt['source_members']!=1 or receipt['stage_root']!=stage.as_posix() or receipt['bootstrap'] is not False or receipt['before']!={}:raise PipelineError('Joshua exact receipt scope differs')
 if io_path(root/WORK).exists() or _files(root/WORK)!={} or _files(stage/WORK)!=receipt['after']:raise PipelineError('Joshua title work/generation collision')
 if _files(root/OLD_REL)!=receipt['legacy_before'] or _files(ROOT/OLD_REL)!=receipt['legacy_before'] or _files(stage/OLD_REL)!=receipt['legacy_before']:raise PipelineError('Joshua legacy catalog changed')
 if receipt['dependency_files']!={p.as_posix():digest(ROOT/p) for p in sorted(dependencies())}:raise PipelineError('Joshua frozen dependency set changed')
 for path,pin_value in receipt['dependency_files'].items():
  if digest(ROOT/path)!=pin_value or digest(stage/path)!=pin_value:raise PipelineError('Joshua dependency drifted: '+path)
 work,initial,expected_acquisition,_=records()
 if read(stage/WORK/'work.json')!=staged_work(work) or read(stage/ACQ_REL)!=expected_acquisition:raise PipelineError('Joshua raw-backed exact title identity/acquisition differs')
 acquisition=validate_acquisition(stage/ACQ_REL,root=stage)
 source,original,report=source_gate();package=CandidatePackage.load(stage/LANE/'inputs/package');fresh=validate(source,package,_oracle)
 if package.sha256!=original.sha256 or package.sha256!=receipt['package_sha256'] or report.sha256!=fresh.sha256 or report.sha256!=receipt['oracle_report_sha256'] or source.sha256!=receipt['source_manifest_sha256']:raise PipelineError('Joshua fresh package/source proof differs')
 if read(stage/TITLE_REVIEW)!=title_assignment(work,acquisition,receipt['staged_at'],source,package):raise PipelineError('Joshua exact current title assignment differs')
 if read(stage/LANE/'source-accounting.json').get('current_title_assignment')!=make_file_binding(stage,stage/TITLE_REVIEW):raise PipelineError('Joshua source accounting current assignment binding differs')
 if io_path(stage/LANE/'source-review.json').read_bytes()!=io_path(ROOT/LOG/'candidate-completion-receipt-v3.json').read_bytes() or io_path(stage/LANE/'identity-crosswalk.json').read_bytes()!=io_path(ROOT/CROSSWALK).read_bytes():raise PipelineError('Joshua source review/identity crosswalk differs')
 revision=dict(id='blaikie-joshua-complete-20261003-v1',date=datetime.fromisoformat(receipt['staged_at'].replace('Z','+00:00')).date().isoformat(),note=NOTE)
 if revision!=receipt['revision']:raise PipelineError('Joshua exact revision date/id/note differs')
 expected_master=bound(package.member_bytes('content.tei.xml'),acquisition,revision)
 if io_path(stage/EDITION_PATH/'master.tei.xml').read_bytes()!=expected_master or io_path(stage/LANE/'candidate.tei.xml').read_bytes()!=expected_master or digest(stage/EDITION_PATH/'master.tei.xml')!=receipt['master_sha256'] or digest(stage/EDITION_PATH/'acceptance.json')!=receipt['acceptance_sha256']:raise PipelineError('Joshua exact ordered header/body recomputation differs')
 accepted=validate_acceptance(stage/EDITION_PATH/'acceptance.json',root=stage)
 if accepted['representation_revision']!=revision or accepted['promotion']['status']!='promoted':raise PipelineError('Joshua acceptance revision differs')
 if read(stage/WORK/'state.json')!=expected_state(initial,receipt['staged_at']):raise PipelineError('Joshua exact accepted state reason/evidence differs')
 if io_path(stage/WORK/'SOURCE_CREDIT.md').read_bytes()!=package.member_bytes('README.source.md')+CREDIT_ASSIGNMENT:raise PipelineError('Joshua exact visible permission/current assignment credit differs')
 if set(receipt['after'])!=allowed_paths(package) or len(receipt['after'])!=24:raise PipelineError('Joshua exact24 path fence differs')
 validate_state(stage/WORK/'state.json',root=stage)
 if projection_signature(projection_gate(stage,stage/EDITION_PATH/'acceptance.json'))!=projection_signature(receipt['projection_gate']):raise PipelineError('Joshua measured actual projection changed')
 execution(receipt);return receipt

def install(stage,pin,root=ROOT,fail_at=None):
 preflight(stage,pin,root=root)
 with ExitStack() as locks:
  for target in sorted((root/WORK,stage/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(target,acquire_timeout=30.0))
  receipt=preflight(stage,pin,root=root);observed={}
  def checkpoint(point):
   if point=='after-validated':
    if _files(root/WORK)!=receipt['after'] or _files(root/OLD_REL)!=receipt['legacy_before']:raise PipelineError('Joshua installed title/legacy generation differs')
    validate_acceptance(root/EDITION_PATH/'acceptance.json',root=root);validate_state(root/WORK/'state.json',root=root)
    if projection_signature(projection_gate(root,root/EDITION_PATH/'acceptance.json'))!=projection_signature(receipt['projection_gate']):raise PipelineError('Joshua installed projection changed')
    observed.update(execution(receipt))
   if fail_at:fail_at(point)
  result=_commit_generation(root,root/WORK,stage/WORK,work_id=WORK_ID,before={},after=receipt['after'],existed=False,replacement=False,operation_kind='blaikie-joshua-additive-title-install',result_status='installed-and-validated',accepted_editions=1,fail_at=checkpoint)
  return result|dict(late_execution_gate='pass',executed_code_pins=observed,legacy_generation_byte_unchanged=True)

def prove_fixture(stage,pin):
    stage=resolve_path(stage,strict=True)
    if FIXTURE.exists():raise FileExistsError('Preserve Joshua fixture evidence')
    receipt=read(stage/'stage-receipt.json');before={};legacy=_files(ROOT/OLD_REL)
    if before!=receipt['before']:raise PipelineError('Joshua fixture preimage differs')
    FIXTURE.mkdir(parents=True)
    for path in _files(stage):
        if not path.startswith('library/') and path!='stage-receipt.json':copy(stage,FIXTURE,Path(path))
    for path in legacy:copy(ROOT,FIXTURE,OLD_REL/path)
    (FIXTURE/'.ocd-blaikie-joshua-fixture').write_text('fixture-only\n')
    negatives=[]
    wrong_root=ROOT/'.tmp_audit/blaikie-joshua-arbitrary-fixture-20261003-v1'
    if wrong_root.exists():raise FileExistsError('Preserve Joshua arbitrary-root fixture')
    wrong_root.mkdir();(wrong_root/'.ocd-blaikie-joshua-fixture').write_text('fixture-only\n')
    wrong_before=_files(wrong_root)
    for label,bad_stage,bad_pin,bad_root in [('wrong-pin',stage,'0'*64,FIXTURE),
        ('arbitrary-marked-root',stage,pin,wrong_root),('collision',FIXTURE,pin,FIXTURE),
        ('stage-inside-root',FIXTURE/OLD_REL,pin,FIXTURE),('root-inside-stage',FIXTURE.parent,pin,FIXTURE)]:
        try:preflight(bad_stage,bad_pin,root=bad_root)
        except PipelineError as error:negatives.append(dict(label=label,rejected=True,reason=str(error)))
        else:raise PipelineError('Joshua fixture boundary admitted '+label)
    if _files(FIXTURE/WORK)!=before or io_path(FIXTURE/WORK).exists() or _files(FIXTURE/OLD_REL)!=legacy or _files(wrong_root)!=wrong_before:raise PipelineError('Joshua boundary rejection mutated fixture')
    def fault(point):
        if point=='after-new-live':raise RuntimeError('joshua-title-rollback-fixture')
    try:install(stage,pin,root=FIXTURE,fail_at=fault)
    except RuntimeError as error:
        if str(error)!='joshua-title-rollback-fixture':raise
    else:raise PipelineError('Joshua fixture fault absent')
    if _files(FIXTURE/WORK)!=before or io_path(FIXTURE/WORK).exists() or _files(FIXTURE/OLD_REL)!=legacy:raise PipelineError('Joshua injected rollback changed preimage')
    late=[]
    for label,path in [('checkout',ROOT/'.tmp_audit/blaikie_joshua_unexpected_import_v1.py'),
        ('library',ROOT/LOG/'blaikie_joshua_unexpected_import_v1.py')]:
        if path.exists():raise FileExistsError('Preserve Joshua late-import fixture')
        path.write_text("MARKER = 'Joshua late-import fixture'\n",encoding='utf-8')
        module_name='blaikie_joshua_unexpected_'+label
        def import_late(point):
            if point=='after-new-live':
                definition=importlib.util.spec_from_file_location(module_name,path)
                module=importlib.util.module_from_spec(definition);sys.modules[module_name]=module;definition.loader.exec_module(module)
        try:
            try:install(stage,pin,root=FIXTURE,fail_at=import_late)
            except PipelineError as error:
                if 'Unexpected executed Joshua dependency' not in str(error):raise
                late.append(dict(label=label,rejected=True,loaded_at='after-new-live',rejected_at='after-validated',reason=str(error)))
            else:raise PipelineError('Joshua late import admitted')
        finally:sys.modules.pop(module_name,None)
        if _files(FIXTURE/WORK)!=before or io_path(FIXTURE/WORK).exists() or _files(FIXTURE/OLD_REL)!=legacy:raise PipelineError('Joshua late-import rollback changed preimage')
    success=install(stage,pin,root=FIXTURE)
    if _files(FIXTURE/WORK)!=receipt['after'] or io_path(ROOT/WORK).exists() or _files(ROOT/OLD_REL)!=legacy or _files(FIXTURE/OLD_REL)!=legacy or _files(stage/WORK)!=receipt['after']:
        raise PipelineError('Joshua fixture success generation differs')
    journals=sorted((FIXTURE/'.tmp_audit').glob('accepted-install-*/operation.json'))
    if len(journals)!=4 or sum(read(p)['phase']=='complete' for p in journals)!=1 or sum(read(p)['phase'] in {'rolled-back','rollback-complete'} for p in journals)!=3:
        raise PipelineError('Joshua fixture terminal journals differ')
    durable=[]
    for number,path in enumerate(journals,1):
        record=read(path)
        if record['before']!=before or record['after']!=receipt['after']:raise PipelineError('Joshua fixture journal generation differs')
        destination=LOG/('fixture-operation-'+str(number)+'.json')
        if (ROOT/destination).exists():raise FileExistsError('Preserve Joshua durable journal')
        write(ROOT,destination,io_path(path).read_bytes());durable.append(dict(path=destination.as_posix(),sha256=digest(ROOT/destination),phase=record['phase']))
    proof=dict(status='pass',legacy_generation_before_after=legacy,legacy_generation_byte_unchanged=True,work_id=WORK_ID,stage_root=stage.as_posix(),stage_receipt_sha256=pin,
        before_files=len(before),after_files=len(receipt['after']),boundary_negatives=negatives,late_import_negatives=late,
        injected_rollback_exact=True,fixture_success_generation_exact=True,canonical_preimage_exact=True,
        stage_generation_exact=True,durable_journals=durable,success=success,canonical_installation='not-performed')
    path=LOG/'title-guarded-install-fixture-proof-v1.json'
    if (ROOT/path).exists():raise FileExistsError('Preserve Joshua fixture proof')
    write_json(ROOT,path,proof)
    return dict(status='pass',proof_path=path.as_posix(),proof_sha256=digest(ROOT/path))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',type=Path);parser.add_argument('--prepare',action='store_true');parser.add_argument('--bootstrap',action='store_true');parser.add_argument('--expected-sha256');parser.add_argument('--apply',action='store_true');parser.add_argument('--prove-fixture',action='store_true');args=parser.parse_args()
    if args.bootstrap and not args.prepare:raise PipelineError('Bootstrap cannot preflight/install')
    if args.prepare:result=prepare(args.stage,bootstrap=args.bootstrap)
    elif args.prove_fixture:result=prove_fixture(args.stage,args.expected_sha256)
    elif args.apply:result=install(args.stage,args.expected_sha256)
    else:receipt=preflight(args.stage,args.expected_sha256);result=dict(status='preflight-pass',after_files=len(receipt['after']))
    print(json.dumps(result,sort_keys=True))
