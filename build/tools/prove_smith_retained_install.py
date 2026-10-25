"""Prove Smith's reviewed stage rollback and successful fixture installation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build.tools.install_smith_retained_acceptance import ROOT, LOG, WORK, preflight, install, read, digest
from build.tei.smith_retained_native_prepare import canonical
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.library._common import PipelineError


def prove(stage, pin):
 stage=stage.resolve(strict=True)
 fixture=ROOT/'.tmp_audit/smith-retained-install-fixture-20261003-v2'
 if fixture.exists():raise FileExistsError('Preserve existing Smith fixture proof')
 receipt=read(stage/'stage-receipt.json')
 before=_files(ROOT/WORK)
 if before!=receipt['before']:raise PipelineError('Smith canonical preimage differs')
 fixture.mkdir(parents=True)
 for relative in _files(stage):
  if relative.startswith('library/') or relative=='stage-receipt.json':continue
  destination=_io_path(fixture/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(stage/relative).read_bytes())
 for relative in before:
  destination=_io_path(fixture/WORK/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(ROOT/WORK/relative).read_bytes())
 (fixture/'.ocd-smith-retained-install-fixture').write_text('fixture-only\n')
 try:preflight(stage,'0'*64,root=fixture)
 except PipelineError as error:wrong_pin=str(error)
 else:raise ValueError('Smith wrong receipt pin admitted')
 if _files(fixture/WORK)!=before:raise ValueError('Wrong pin mutated fixture')
 baseline=preflight(stage,pin,root=fixture)
 marker='smith-retained-injected-after-new-live'
 def fail(point):
  if point=='after-new-live':raise RuntimeError(marker)
 try:install(stage,pin,root=fixture,fail_at=fail)
 except RuntimeError as error:
  if str(error)!=marker:raise
 else:raise ValueError('Smith rollback fault did not fire')
 if _files(fixture/WORK)!=before or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Smith rollback source/canonical/preimage mismatch')
 journals=list((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
 if len(journals)!=1:raise ValueError('Unique Smith rollback journal required')
 rollback=read(journals[0])
 if rollback['phase'] not in {'rolled-back','rollback-complete'} or rollback['before']!=before or rollback['after']!=receipt['after']:raise ValueError('Smith rollback journal differs')
 result=install(stage,pin,root=fixture)
 if _files(fixture/WORK)!=receipt['after'] or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Smith successful fixture generation differs')
 completed=[p for p in (fixture/'.tmp_audit').glob('accepted-install-*/operation.json') if read(p)['phase']=='complete']
 if len(completed)!=1:raise ValueError('Unique Smith complete fixture journal required')
 proof=dict(status='pass',work_id=receipt['work_id'],stage_root=stage.as_posix(),stage_receipt_sha256=pin,fixture_root=fixture.as_posix(),baseline=baseline,
  wrong_pin_rejected=wrong_pin,after_new_live_injected_and_rolled_back=True,rollback_journal=dict(path=journals[0].as_posix(),sha256=digest(journals[0]),phase=rollback['phase']),
  successful_fixture=result,complete_journal=dict(path=completed[0].as_posix(),sha256=digest(completed[0])),canonical_all_preimages_unchanged=True,stage_all_after_files_unchanged=True,before_files=len(before),after_files=len(receipt['after']),canonical_install_performed=False)
 destination=ROOT/LOG/'guarded-install-fixture-proof-v2.json';destination.write_bytes(canonical(proof))
 return dict(status='pass',proof_path=destination.as_posix(),proof_sha256=digest(destination),before_files=len(before),after_files=len(receipt['after']))


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--expected-sha256',required=True);args=p.parse_args()
 print(json.dumps(prove(args.stage,args.expected_sha256),sort_keys=True))
