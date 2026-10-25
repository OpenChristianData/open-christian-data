"""Pinned read-only preflight and atomic guarded one-work First Samuel installation."""
from __future__ import annotations
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
import argparse,json,sys
from build.tools.stage_blaikie_first_samuel_title_acceptance import ROOT,LOG,LIBRARY,WORK,WORK_ID,EVIDENCE,MEMBERS,SOURCE_DIR,CANDIDATES,edition_path,acquisition_path,dependencies,projection_gate,read,sha,declared_scope,recompute_header,REVISION_NOTE,expected_work,expected_state,boundary_check,component_artifacts,ORIGINAL,PROPOSAL,assert_original,expected_acquisition,source_credit,identity_review
from build.tei.blaikie_first_samuel_retained_native_oracle import _oracle as oracle
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,validate
from ocd_kernel.tei.acceptance import validate_acceptance,PROMOTED_MASTER_REASON
from ocd_kernel.tei.install_accepted import _files,_io_path,_commit_generation

def digest(path):return sha(_io_path(path).read_bytes())

def preflight(stage,receipt_sha256,*,root=ROOT):
 root=resolve_path(root,strict=True);stage=resolve_path(stage,strict=True);fixture=root!=resolve_path(ROOT,strict=True)
 if fixture:
  exact=resolve_path(ROOT/'.tmp_audit/blaikie-first-samuel-title-install-fixture-20261003-v2',strict=True)
  if root!=exact:raise PipelineError('First Samuel fixture root exceeds exact task boundary')
  marker=root/'.ocd-blaikie-first-samuel-install-fixture'
  if not marker.is_file() or marker.read_bytes()!=b'fixture-only\n':raise PipelineError('First Samuel root override requires exact fixture marker')
 if stage.parent!=resolve_path(LIBRARY/'candidate-reviews',strict=True) or not stage.name.startswith('blaikie-first-samuel-title-s-') or root==stage or root in stage.parents or stage in root.parents:raise PipelineError('First Samuel stage/root boundary differs')
 if len(receipt_sha256)!=64 or any(c not in '0123456789abcdef' for c in receipt_sha256) or digest(stage/'stage-receipt.json')!=receipt_sha256:raise PipelineError('First Samuel caller receipt pin differs')
 receipt=read(stage/'stage-receipt.json')
 if receipt.get('contract')!='ocd-blaikie-first-samuel-title-external-stage-v1' or receipt.get('work_id')!=WORK_ID or receipt.get('status')!='staged-only' or receipt.get('stage_root')!=stage.as_posix() or receipt.get('complete_work_count')!=1 or receipt.get('source_member_count')!=1 or receipt.get('accepted_scope_kind')!='work' or receipt.get('projection_category')!='commentary' or receipt.get('installation')!='not-performed' or receipt.get('excluded_work_targets')!='Original Second Samuel and Joshua identities, acquisitions and states preserved unchanged':raise PipelineError('First Samuel receipt finite complete-work/source scope differs')
 before=_files(root/WORK);after=_files(stage/WORK)
 if before or _io_path(root/WORK).exists() or receipt.get('new_title_home_previously_absent') is not True:raise PipelineError('Title-specific First Samuel home is not absent')
 if assert_original(root)['original_author_container_preimages']!=receipt.get('original_author_container_preimages') or _files(stage/ORIGINAL)!=receipt['original_author_container_preimages'] or receipt.get('original_author_container_unchanged') is not True:raise PipelineError('Original Blaikie author container changed')
 if before!=receipt['before'] or after!=receipt['after']:raise PipelineError('First Samuel complete canonical preimage or frozen stage generation changed')
 for relative in before:
  if relative not in {'work.json','state.json'} and after.get(relative)!=before[relative]:raise PipelineError('First Samuel retained source-part authority changed '+relative)
 work=expected_work(root);state=expected_state(root,receipt['staged_at'])
 if work!=read(stage/WORK/'work.json') or state!=read(stage/WORK/'state.json'):raise PipelineError('First Samuel exact selected First Samuel category and accepted-edition delta differs')
 allowed={'work.json','state.json','SOURCE_CREDIT.md'}
 allowed.add(acquisition_path(MEMBERS['blaikie-expositor8']).relative_to(WORK).as_posix())
 if read(stage/acquisition_path(MEMBERS['blaikie-expositor8']))!=expected_acquisition(root) or _io_path(stage/WORK/'SOURCE_CREDIT.md').read_bytes()!=source_credit(root):raise PipelineError('Title-specific acquisition or visible source credit differs')
 if _io_path(stage/EVIDENCE/'identity-crosswalk.json').read_bytes()!=_io_path(root/PROPOSAL/'old-to-new-identity-crosswalk.json').read_bytes():raise PipelineError('Title-specific durable identity crosswalk differs')
 if read(stage/EVIDENCE/'title-identity-review.json')!=identity_review(root):raise PipelineError('Current reviewed title identity outcome differs')
 for spec in MEMBERS.values():
  edition=edition_path(spec)
  if _io_path(root/edition/'master.tei.xml').exists() or _io_path(root/edition/'acceptance.json').exists():raise PipelineError('First Samuel accepted authority already exists; no replacement')
  allowed.update((edition/name).relative_to(WORK).as_posix() for name in ('master.tei.xml','acceptance.json'))
 prefix=EVIDENCE.relative_to(WORK).as_posix()+'/'
 if any(path not in allowed and not path.startswith(prefix) for path in set(after)-set(before)):raise PipelineError('First Samuel staged additions exceed complete-work boundary')
 dep=dependencies(ROOT);observed={p.as_posix():digest(ROOT/p) for p in sorted(dep)}
 if observed!=receipt.get('dependency_files'):raise PipelineError('First Samuel pinned code/source/schema/proof dependency set changed')
 for path in dep:
  if digest(stage/path)!=observed[path.as_posix()]:raise PipelineError('First Samuel staged dependency differs '+path.as_posix())
 if [r['complete_work_id'] for r in receipt['complete_works']]!=list(MEMBERS):raise PipelineError('First Samuel ordered one-complete-work receipt differs')
 for key,spec in MEMBERS.items():
  row=next(r for r in receipt['complete_works'] if r['complete_work_id']==key);edition=edition_path(spec);lane=EVIDENCE/key
  authority=ROOT if fixture else root;manifest=SourceManifest.load(authority/SOURCE_DIR/(key+'.source-manifest.json'),repository_root=authority);package=CandidatePackage.load(stage/lane/'inputs/package')
  if package.sha256!=CandidatePackage.load(CANDIDATES/'package').sha256 or package.sha256!=row['candidate_package_sha256'] or manifest.sha256!=row['source_manifest_sha256']:raise PipelineError('First Samuel complete source/candidate receipt binding differs')
  report=validate(manifest,package,oracle)
  if report.status!='pass' or report.sha256!=row['oracle_report_sha256']:raise PipelineError('First Samuel fresh whole complete-work source gate differs')
  original=package.member_bytes('content.tei.xml');master=_io_path(stage/edition/'master.tei.xml').read_bytes();accepted=validate_acceptance(stage/edition/'acceptance.json',root=stage)
  if original.split(b'</teiHeader>',1)[1]!=master.split(b'</teiHeader>',1)[1] or digest(stage/edition/'master.tei.xml')!=row['master_sha256'] or digest(stage/edition/'acceptance.json')!=row['acceptance_sha256']:raise PipelineError('First Samuel complete readable body or accepted authority changed')
  date=datetime.fromisoformat(receipt['staged_at'].replace('Z','+00:00')).date().isoformat();revision=dict(id=key+'-complete-current-20261003-v1',date=date,note=REVISION_NOTE)
  if accepted['representation_revision']!=revision:raise PipelineError('First Samuel ordered header revision differs')
  acq=validate_acquisition(stage/acquisition_path(spec),root=stage);source={k:acq[k] for k in ('source_path','source_sha256','source_bytes','source_scope')}
  if 'source_kind' in acq:source['source_kind']=acq['source_kind']
  identity=dict(work_id=WORK_ID,textual_form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition'])
  expected=recompute_header(original,identity=identity,source=source,source_url=acq['url'],declared=declared_scope(key,acq),revision=revision)
  if master!=expected or _io_path(stage/lane/'candidate.tei.xml').read_bytes()!=expected:raise PipelineError('First Samuel entire ordered header recomputation differs')
  members=[dict(path=r['path'],position=i) for i,r in enumerate(acq['retained_files'],1)];included=[dict(path=r['path'],position=i,bytes=r['bytes'],sha256=r['sha256'],scope=r.get('scope') or acq['source_scope']) for i,r in enumerate(acq['retained_files'],1)];account=read(stage/lane/'source-accounting.json')
  if row['source_members']!=spec['members'] or row['source_sha256']!=acq['source_sha256'] or account['source_sha256']!=acq['source_sha256'] or account['source_bytes']!=acq['source_bytes'] or account['accepted_scope']['kind']!='work' or account['expected_members']!=members or account['included_members']!=included or account['excluded_members'] or account['missing_members'] or account['unknown_members'] or account['complete_work_count']!=1 or account['source_member_count']!=1 or account['source_members']!=spec['members'] or account['full_source_elements']!=sum(component_artifacts(m)[1]['source']['elements'] for m in spec['members']) or account['administrative_comments']!=sum(component_artifacts(m)[1]['source']['comments'] for m in spec['members']):raise PipelineError('First Samuel explicit complete work and all source-member accounting differs')
  if accepted['promotion']['status']!='promoted' or accepted['identity']!=identity or accepted['scope']['kind']!='work' or accepted['scope']['expected_members']!=members or accepted['scope']['included_members']!=included:raise PipelineError('First Samuel accepted complete-work identity/member scope differs')
  if projection_gate(stage,stage/edition/'acceptance.json')!=row['projection_gate']:raise PipelineError('First Samuel actual commentary projection gate changed')
 validate_state(stage/WORK/'state.json',root=stage)
 return dict(status='ready-for-parent-review',work_id=WORK_ID,receipt_sha256=receipt_sha256,before_files=len(before),after_files=len(after),complete_work_count=1,source_member_count=1,scope_kind='work',dependency_files=len(dep),projection_gate={r['complete_work_id']:r['projection_gate'] for r in receipt['complete_works']})

def assert_executed_dependencies(receipt):
 records={};bound={resolve_path(ROOT/p,strict=True):(p,pin) for p,pin in receipt['dependency_files'].items()};code_root=resolve_path(ROOT,strict=True);library=resolve_path(LIBRARY,strict=True)
 for module in sys.modules.copy().values():
  file=getattr(module,'__file__',None)
  if not file:continue
  path=resolve_path(Path(file),strict=True)
  if path.is_relative_to(code_root) or path.is_relative_to(library):
   binding=bound.get(path)
   if binding is None:raise PipelineError('First Samuel unexpected or drifted executed dependency: '+path.as_posix())
   relative,pin=binding
   if sha(_io_path(path).read_bytes())!=pin:raise PipelineError('First Samuel unexpected or drifted executed dependency: '+relative)
   records[relative]=pin
 return [dict(path=p,sha256=records[p]) for p in sorted(records)]

def install(stage,receipt_sha256,*,root=ROOT,fail_at=None):
 root=resolve_path(root,strict=True);stage=resolve_path(stage,strict=True);target=root/WORK;source=stage/WORK
 with ExitStack() as locks:
  for path in sorted((target,source,root/ORIGINAL),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(path,acquire_timeout=30.0))
  preflight(stage,receipt_sha256,root=root);receipt=read(stage/'stage-receipt.json');runtime=[]
  def checkpoint(point):
   if point=='after-validated':
    if _files(root/ORIGINAL)!=receipt['original_author_container_preimages'] or _files(stage/ORIGINAL)!=receipt['original_author_container_preimages']:raise PipelineError('Original Blaikie container changed during installation')
    if _files(target)!=receipt['after']:raise PipelineError('First Samuel installed complete generation differs')
    for key,spec in MEMBERS.items():
     acceptance=root/edition_path(spec)/'acceptance.json';validate_acceptance(acceptance,root=root);row=next(r for r in receipt['complete_works'] if r['complete_work_id']==key)
     if projection_gate(root,acceptance)!=row['projection_gate']:raise PipelineError('First Samuel installed actual commentary gate differs')
    validate_state(target/'state.json',root=root);runtime.extend(assert_executed_dependencies(receipt))
   if fail_at is not None:fail_at(point)
  result=_commit_generation(root,target,source,work_id=WORK_ID,before=receipt['before'],after=receipt['after'],existed=False,replacement=False,operation_kind='blaikie-first-samuel-additive-title-work-install',result_status='installed-and-validated',accepted_editions=1,fail_at=checkpoint)
 result['executed_first_party_files']=runtime;result['late_execution_dependency_gate']='pass';return result

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--expected-sha256',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();r=preflight(a.stage,a.expected_sha256)
 if a.apply:r['installation']=install(a.stage,a.expected_sha256)
 print(json.dumps(r,sort_keys=True))
