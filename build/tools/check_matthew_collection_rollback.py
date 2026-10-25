"""Exercise supported first-install rollback using exact isolated generations."""
import argparse
from pathlib import Path
import json
import shutil
from hashlib import sha256
from build.tools.prepare_matthew_collection import ROOT,WORK,WORK_ID,canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.tei.install_accepted import _files,install_accepted_work
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    if a.evidence.exists():raise FileExistsError(a.evidence)
    a.evidence.mkdir(parents=True)
    stage=json.loads((a.promoted/'stage-receipt.json').read_bytes());before=_files(ROOT/WORK)
    if before!=stage['before'] or len(before)!=3:raise ValueError('Exact original three-file generation differs')
    fixture=a.evidence/'fixture';incoming=a.evidence/'incoming'
    shutil.copytree(io_path(a.promoted),io_path(incoming))
    for relative in before:
        dest=io_path(fixture/WORK/relative);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(io_path(ROOT/WORK/relative).read_bytes())
    original_work=io_path(fixture/WORK/'work.json').read_bytes()
    io_path(fixture/WORK/'work.json').write_bytes(io_path(incoming/WORK/'work.json').read_bytes())
    prepared=_files(fixture/WORK);after=_files(incoming/WORK)
    if after!=stage['after'] or len(after)!=25:raise ValueError('Promoted 25-file generation differs')
    observed={}
    class InjectedFailure(RuntimeError):pass
    def checkpoint(phase):
        if phase=='after-new-live':
            observed.update(_files(fixture/WORK))
            if observed!=after:raise ValueError('Isolated new live generation differs')
            raise InjectedFailure('intentional after-new-live failure')
    with cached_edition_lookups():
        try:install_accepted_work(fixture,incoming,work_id=WORK_ID,fail_at=checkpoint)
        except InjectedFailure:pass
        else:raise ValueError('Checkpoint was not reached')
    if _files(fixture/WORK)!=prepared:raise ValueError('Supported installer did not restore prepared original')
    operations=list((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
    if len(operations)!=1 or json.loads(operations[0].read_bytes())['phase']!='rolled-back':raise ValueError('Durable rollback journal missing')
    io_path(fixture/WORK/'work.json').write_bytes(original_work)
    if _files(fixture/WORK)!=before or _files(ROOT/WORK)!=before:raise ValueError('Exact original restoration/canonical conservation failed')
    proof=dict(status='pass',checkpoint='after-new-live',stage_receipt_sha256=sha256((a.promoted/'stage-receipt.json').read_bytes()).hexdigest(),original_before=before,prepared_before=prepared,observed_25_new_live=observed,restored_original=_files(fixture/WORK),canonical_original_unchanged=True,journal=operations[0].as_posix(),journal_sha256=sha256(operations[0].read_bytes()).hexdigest(),installer_sha256=sha256((ROOT/'ocd_kernel/tei/install_accepted.py').read_bytes()).hexdigest(),scope='Isolated supported installer rolled back exact new live generation; category-only prerequisite reverted separately to exact original three files. No canonical mutation.')
    (a.evidence/'result.json').write_bytes(canonical(proof));print(json.dumps(dict(status='pass',new_live_files=25,original_restored_files=3)))
if __name__=='__main__':main()
