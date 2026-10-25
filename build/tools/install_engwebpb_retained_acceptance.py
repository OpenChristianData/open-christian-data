"""Read-only preflight or guarded installation of the existing engwebpb TEI."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from hashlib import sha256
from contextlib import ExitStack
from build.tools.stage_engwebpb_retained_acceptance import ROOT,LIBRARY,WORK,WORK_ID,FORM_ID,EDITION_ID,EDITION,ACQUISITION,EVIDENCE,MANIFEST,CANDIDATE,PACKAGE_SHA,SOURCE_SHA,dependencies,projection_gate
from build.tei.engwebpb_repaired_semantic_inline_oracle import oracle
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage,validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files,_io_path,_commit_generation

def _sha(path):return sha256(_io_path(path).read_bytes()).hexdigest()
def _read(path):return json.loads(_io_path(path).read_bytes())

def preflight(stage,receipt_sha256,*,root=ROOT):
 root=root.resolve(strict=True);stage=stage.resolve(strict=True);fixture=root!=ROOT.resolve(strict=True)
 if fixture:
  marker=root/'.ocd-engwebpb-retained-install-fixture'
  if not marker.is_file() or marker.read_text()!='fixture-only\n':raise PipelineError('engwebpb root override requires fixture marker')
 if stage.parent!=(LIBRARY/'candidate-reviews').resolve(strict=True) or not stage.name.startswith('engwebpb-s-') or root==stage or root in stage.parents or len(receipt_sha256)!=64 or any(c not in '0123456789abcdef' for c in receipt_sha256):raise PipelineError('engwebpb stage/root/receipt pin differs')
 if _sha(stage/'stage-receipt.json')!=receipt_sha256:raise PipelineError('engwebpb caller receipt pin differs')
 receipt=_read(stage/'stage-receipt.json')
 if receipt.get('contract')!='ocd-engwebpb-retained-external-stage-v1' or receipt.get('status')!='staged-only' or receipt.get('work_id')!=WORK_ID or receipt.get('stage_root')!=stage.as_posix() or receipt.get('source_sha256')!=SOURCE_SHA or receipt.get('installation')!='not-performed' or receipt.get('accepted_scope_kind')!='edition' or receipt.get('included_members')!=68 or receipt.get('support_members')!=3:raise PipelineError('engwebpb receipt scope differs')
 before=_files(root/WORK);after=_files(stage/WORK)
 if before!=receipt['before'] or after!=receipt['after']:raise PipelineError('engwebpb complete preimage or stage generation changed')
 if (root/EDITION/'master.tei.xml').exists() or (root/EDITION/'acceptance.json').exists():raise PipelineError('engwebpb canonical accepted authority already exists')
 for relative in before:
  if relative not in {'work.json','state.json'} and after.get(relative)!=before[relative]:raise PipelineError('engwebpb retained authority changed: '+relative)
 expected_work=_read(root/WORK/'work.json');form=expected_work['textual_forms'][0];edition=form['editions'][0]
 if form['textual_form_id']!=FORM_ID or edition['edition_id']!=EDITION_ID or edition.get('category') is not None:raise PipelineError('engwebpb identity preimage differs')
 edition['category']='bible'
 if _read(stage/WORK/'work.json')!=expected_work:raise PipelineError('engwebpb metadata exceeds category binding')
 old_state=_read(root/WORK/'state.json');new_state=_read(stage/WORK/'state.json')
 matches=[x for x in old_state['targets'] if x['target_type']=='edition' and x['target_id']==EDITION_ID]
 newmatches=[x for x in new_state['targets'] if x['target_type']=='edition' and x['target_id']==EDITION_ID]
 if len(matches)!=1 or len(newmatches)!=1 or matches[0]['stage']!='review' or newmatches[0]['stage']!='accepted':raise PipelineError('engwebpb state transition differs')
 matches[0].update(stage=newmatches[0]['stage'],reason=newmatches[0]['reason'],updated_at=newmatches[0]['updated_at'],evidence=newmatches[0]['evidence'])
 if old_state!=new_state or newmatches[0]['evidence'][:-2]!=_read(root/WORK/'state.json')['targets'][1]['evidence'] or newmatches[0]['evidence'][-2:]!=[(EDITION/'master.tei.xml').as_posix(),(EDITION/'acceptance.json').as_posix()]:raise PipelineError('engwebpb state mutation exceeds acceptance')
 allowed={(EDITION/'master.tei.xml').relative_to(WORK).as_posix(),(EDITION/'acceptance.json').relative_to(WORK).as_posix()};prefix=EVIDENCE.relative_to(WORK).as_posix()+'/'
 if any(p not in allowed and not p.startswith(prefix) for p in set(after)-set(before)):raise PipelineError('engwebpb stage adds undeclared work files')
 bound_dependencies={p.as_posix():_sha(root/p) for p in sorted(dependencies(root))}
 if bound_dependencies!=receipt.get('dependency_files'):raise PipelineError('engwebpb caller-bound source/runtime/schema/proof dependency set differs')
 for relative in dependencies(root):
  if bound_dependencies[relative.as_posix()]!=_sha(stage/relative):raise PipelineError('engwebpb source/runtime/proof dependency changed: '+str(relative))
 manifest=SourceManifest.load(ROOT/MANIFEST if fixture else root/MANIFEST,repository_root=ROOT if fixture else root)
 package=CandidatePackage.load(stage/EVIDENCE/'inputs/package');package.verify_integrity()
 if package.sha256!=PACKAGE_SHA or package.sha256!=CandidatePackage.load(CANDIDATE).sha256 or manifest.sha256!=receipt['source_manifest_sha256']:raise PipelineError('engwebpb candidate or manifest changed')
 report=validate(manifest,package,oracle)
 if report.status!='pass' or report.sha256!=receipt['oracle_report_sha256']:raise PipelineError('engwebpb fresh source oracle changed')
 original=_io_path(stage/EVIDENCE/'inputs/package/content.tei.xml').read_bytes();master=_io_path(stage/EDITION/'master.tei.xml').read_bytes()
 if original.split(b'</teiHeader>',1)[1]!=master.split(b'</teiHeader>',1)[1] or _sha(stage/EDITION/'master.tei.xml')!=receipt['master_sha256'] or _sha(stage/EDITION/'acceptance.json')!=receipt['acceptance_sha256']:raise PipelineError('engwebpb master differs from repaired source body')
 account=_read(stage/EVIDENCE/'source-accounting.json')
 if account.get('source_lines')!=61098 or account.get('chapters')!=1189 or account.get('verses')!=31103 or account.get('source_attached_notes')!=1572 or len(account.get('included_members',[]))!=68 or account.get('excluded_members')!=[] or account.get('accepted_scope',{}).get('kind')!='edition':raise PipelineError('engwebpb source accounting differs')
 acceptance=stage/EDITION/'acceptance.json';accepted=validate_acceptance(acceptance,root=stage);validate_state(stage/WORK/'state.json',root=stage)
 if accepted['promotion']['status']!='promoted' or accepted['identity']['work_id']!=WORK_ID:raise PipelineError('engwebpb acceptance authority differs')
 gate=projection_gate(stage,acceptance)
 if gate!=receipt['projection_gate']:raise PipelineError('engwebpb separate projection gate changed')
 return dict(status='ready-for-review',work_id=WORK_ID,receipt_sha256=receipt_sha256,before_files=len(before),after_files=len(after),source_lines=61098,included_members=68,scope_kind='edition',projection_gate=gate)

def install(stage,receipt_sha256,*,root=ROOT,fail_at=None):
 root=root.resolve(strict=True);stage=stage.resolve(strict=True);target=root/WORK;source=stage/WORK
 with ExitStack() as locks:
  for p in sorted((target,source),key=lambda x:x.as_posix()):locks.enter_context(acquire_jsonl_lock(p,acquire_timeout=30.0))
  preflight(stage,receipt_sha256,root=root);receipt=_read(stage/'stage-receipt.json')
  def checkpoint(point):
   if point=='after-validated':
    if _files(target)!=receipt['after']:raise PipelineError('engwebpb installed generation differs')
    acceptance=root/EDITION/'acceptance.json';validate_acceptance(acceptance,root=root);validate_state(target/'state.json',root=root)
    if projection_gate(root,acceptance)!=receipt['projection_gate']:raise PipelineError('engwebpb installed separate projection gate changed')
   if fail_at is not None:fail_at(point)
  result=_commit_generation(root,target,source,work_id=WORK_ID,before=receipt['before'],after=receipt['after'],existed=True,replacement=False,operation_kind='engwebpb-existing-tei-repair-install',result_status='installed-and-validated',accepted_editions=1,fail_at=checkpoint)
 return result|dict(projection_gate=receipt['projection_gate'])

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--expected-sha256',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();r=preflight(a.stage,a.expected_sha256)
 if a.apply:r['installation']=install(a.stage,a.expected_sha256)
 print(json.dumps(r,sort_keys=True))
if __name__=='__main__':main()
