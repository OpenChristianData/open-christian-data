"""Assert the entire new live generation, then exact restoration in an isolated root."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
from build.tools.prepare_bcp1559_current import ROOT,WORK,BASE,canonical
from build.tools.install_bcp1559_current import install
from ocd_kernel.library._common import io_path,io_glob,PipelineError
from ocd_kernel.tei.install_accepted import _files

def main():
    pin=json.loads((ROOT/BASE/'stage-pin.json').read_bytes());promoted=Path(pin['receipt']).parent
    stage=Path(json.loads((promoted/'stage-receipt.json').read_bytes())['stage_root'])
    isolated=Path('D:/Library/Open Christian Data/candidate-reviews/bcp1559-rollback-20261002-v1')
    if isolated.exists():raise FileExistsError(isolated)
    shutil.copytree(io_path(stage),io_path(isolated))
    target=isolated/WORK
    resolved=target.resolve();bound=(isolated/'library/works').resolve()
    if resolved.parent!=bound or resolved.name!='bcp-1559':raise ValueError('unbounded isolated target')
    shutil.rmtree(io_path(target))
    before=_files(ROOT/WORK)
    for name,digest in before.items():
        raw=io_path(ROOT/WORK/name).read_bytes()
        if sha256(raw).hexdigest()!=digest:raise ValueError('canonical preimage changed')
        destination=io_path(target/name);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
    stage_record=json.loads((promoted/'stage-receipt.json').read_bytes())
    if before!=stage_record['before'] or _files(target)!=before:raise ValueError('isolated preimage differs')
    observed={}
    def fail(phase):
        if phase=='after-new-live':
            actual=_files(target)
            if actual!=stage_record['after']:raise ValueError('new live generation not exact')
            observed.update(phase=phase,new_live_all_hashes=actual,new_live_hash_count=len(actual))
            (evidence/'after-new-live.json').write_bytes(canonical(observed))
            raise PipelineError('deliberate isolated after-new-live injection')
    evidence=ROOT/'reports/_logs/bcp1559-current-reconciliation-20261002-v1/isolated-install-v1'
    try:install(isolated,promoted,pin['receipt_sha256'],evidence,fail_at=fail)
    except PipelineError as error:
        if str(error)!='deliberate isolated after-new-live injection':raise
    else:raise ValueError('injection not reached')
    if not observed or _files(target)!=before or _files(ROOT/WORK)!=before:raise ValueError('original restoration/canonical conservation failed')
    journals=[]
    for path in io_glob(isolated/'.tmp_audit','**/operation.json'):
        record=json.loads(io_path(path).read_bytes());journals.append(dict(path=path.as_posix(),phase=record['phase'],sha256=sha256(io_path(path).read_bytes()).hexdigest()))
    if len(journals)!=1 or journals[0]['phase']!='rolled-back':raise ValueError('terminal rollback journal absent')
    record=dict(status='pass',isolated_root=isolated.as_posix(),source_stage=stage.as_posix(),frozen_receipt_sha256=pin['receipt_sha256'],observed=observed,original_restoration=before,original_file_count=len(before),canonical_unchanged=True,journals=journals)
    (ROOT/'reports/_logs/bcp1559-current-reconciliation-20261002-v1/rollback-proof.json').write_bytes(canonical(record));print(json.dumps(record))
if __name__=='__main__':main()
