"""Prove Farrar's reviewed stage rollback and successful fixture installation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_farrar_retained_acceptance import ROOT, LOG, WORK, preflight, install, read, digest, loaded_code_pins
from build.tei.farrar_retained_native_prepare import canonical
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.library._common import PipelineError


def prove(stage, pin):
 stage=stage.resolve(strict=True)
 fixture=ROOT/'.tmp_audit/farrar-retained-install-fixture-20261003-v2'
 if fixture.exists():raise FileExistsError('Preserve existing Farrar fixture proof')
 receipt=read(stage/'stage-receipt.json')
 before=_files(ROOT/WORK)
 if before!=receipt['before']:raise PipelineError('Farrar canonical preimage differs')
 fixture.mkdir(parents=True)
 for relative in _files(stage):
  if relative.startswith('library/') or relative=='stage-receipt.json':continue
  destination=_io_path(fixture/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(stage/relative).read_bytes())
 for relative in before:
  destination=_io_path(fixture/WORK/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(ROOT/WORK/relative).read_bytes())
 (fixture/'.ocd-farrar-retained-install-fixture').write_text('fixture-only\n')
 try:preflight(stage,'0'*64,root=fixture)
 except PipelineError as error:wrong_pin=str(error)
 else:raise ValueError('Farrar wrong receipt pin admitted')
 if _files(fixture/WORK)!=before:raise ValueError('Wrong pin mutated fixture')
 wrong_root=ROOT/'.tmp_audit/farrar-retained-arbitrary-marked-root-20261003-v2'
 if wrong_root.exists():raise FileExistsError('Preserve arbitrary Farrar fixture challenge')
 wrong_root.mkdir();(wrong_root/'.ocd-farrar-retained-install-fixture').write_text('fixture-only\n')
 wrong_root_before=_files(wrong_root)
 negatives={}
 for label,bad_stage,bad_root in [('exact-fixture-root',stage,wrong_root),('stage-root-collision',fixture,fixture),('stage-inside-root',fixture/WORK,fixture),('root-inside-stage',fixture.parent,fixture)]:
  try:preflight(bad_stage,pin,root=bad_root)
  except PipelineError as error:negatives[label]=str(error)
  else:raise ValueError('Farrar root/containment guard admitted '+label)
 if _files(fixture/WORK)!=before or _files(wrong_root)!=wrong_root_before:raise ValueError('Farrar root boundary rejection mutated fixture')
 baseline=preflight(stage,pin,root=fixture)
 marker='farrar-retained-injected-after-new-live'
 def fail(point):
  if point=='after-new-live':raise RuntimeError(marker)
 try:install(stage,pin,root=fixture,fail_at=fail)
 except RuntimeError as error:
  if str(error)!=marker:raise
 else:raise ValueError('Farrar rollback fault did not fire')
 if _files(fixture/WORK)!=before or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Farrar rollback source/canonical/preimage mismatch')
 journals=list((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
 if len(journals)!=1:raise ValueError('Unique Farrar rollback journal required')
 rollback=read(journals[0]);negative_imports=[]
 import importlib.util,sys
 for label,path in [('root',ROOT/'build/tools/farrar_unexpected_import_not_authorized_v2.py'),('library',Path('D:/Library/Open Christian Data/reports/_logs/farrar-existing-install-20261003-v1/unexpected_import_not_authorized_v2.py'))]:
  if path.exists():raise FileExistsError('Preserve existing synthetic Farrar import fixture '+str(path))
  path.write_text("MARKER = 'Farrar late dependency rejection fixture'\n",encoding='utf-8');module_name='farrar_synthetic_unexpected_'+label
  def import_late(point):
   if point=='after-new-live':
    definition=importlib.util.spec_from_file_location(module_name,path);fake=importlib.util.module_from_spec(definition);sys.modules[module_name]=fake;definition.loader.exec_module(fake)
  try:
   try:install(stage,pin,root=fixture,fail_at=import_late)
   except PipelineError as error:
    if 'unexpected executed first-party dependency' not in str(error):raise
    negative_imports.append(dict(location=label,rejected=True,loaded_at='after-new-live',rejected_at='after-validated',reason=str(error),fixture_preimage_unchanged=_files(fixture/WORK)==before))
   else:raise ValueError('Farrar unexpected late loaded import admitted '+label)
  finally:
   if module_name in sys.modules:del sys.modules[module_name]
  if _files(fixture/WORK)!=before:raise ValueError('Farrar late dependency rejection failed rollback')
 if rollback['phase'] not in {'rolled-back','rollback-complete'} or rollback['before']!=before or rollback['after']!=receipt['after']:raise ValueError('Farrar rollback journal differs')
 result=install(stage,pin,root=fixture)
 if _files(fixture/WORK)!=receipt['after'] or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Farrar successful fixture generation differs')
 completed=[p for p in (fixture/'.tmp_audit').glob('accepted-install-*/operation.json') if read(p)['phase']=='complete']
 if len(completed)!=1:raise ValueError('Unique Farrar complete fixture journal required')
 durable_journals=[]
 all_journals=sorted((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
 if len(all_journals)!=4 or sum(read(p)['phase']=='complete' for p in all_journals)!=1 or sum(read(p)['phase'] in {'rolled-back','rollback-complete'} for p in all_journals)!=3:raise ValueError('Farrar exact four terminal journals required')
 for path in all_journals:
  row=read(path)
  if row['before']!=before or row['after']!=receipt['after']:raise ValueError('Farrar terminal journal generation differs')
 for number,path in enumerate(all_journals,1):
  label=read(path)['phase']+'-'+str(number)
  destination=ROOT/LOG/('fixture-v2-'+label+'-operation.json');destination.write_bytes(path.read_bytes());durable_journals.append(dict(path=destination.relative_to(ROOT).as_posix(),sha256=digest(destination)))
 loaded=loaded_code_pins(receipt)
 proof=dict(late_unexpected_import_negatives=negative_imports,boundary_negatives=negatives,actual_after_validated_loaded_code_pins=loaded,exact_ordered_header_recomputed=True,durable_journals=durable_journals,status='pass',work_id=receipt['work_id'],stage_root=stage.as_posix(),stage_receipt_sha256=pin,fixture_root=fixture.as_posix(),baseline=baseline,
  wrong_pin_rejected=wrong_pin,after_new_live_injected_and_rolled_back=True,rollback_journal=dict(path=journals[0].as_posix(),sha256=digest(journals[0]),phase=rollback['phase']),
  successful_fixture=result,complete_journal=dict(path=completed[0].as_posix(),sha256=digest(completed[0])),canonical_all_preimages_unchanged=True,stage_all_after_files_unchanged=True,before_files=len(before),after_files=len(receipt['after']),canonical_install_performed=False)
 destination=ROOT/LOG/'guarded-install-fixture-proof-v2.json';destination.write_bytes(canonical(proof))
 return dict(status='pass',proof_path=destination.as_posix(),proof_sha256=digest(destination),before_files=len(before),after_files=len(receipt['after']))


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--expected-sha256',required=True);args=p.parse_args()
 print(json.dumps(prove(args.stage,args.expected_sha256),sort_keys=True))
