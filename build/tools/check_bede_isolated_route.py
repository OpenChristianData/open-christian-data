"""Test a one-field category prerequisite in an isolated exact accepted tree."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json,sys,importlib.util
from ocd_kernel.library._common import io_path,io_glob,PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose,verify_accepted_prose
ROOT=Path(__file__).resolve().parents[2]
PRE=ROOT/'reports/_logs/bede-pg38326-downstream-preflight-20261001'
STAGE=Path('D:/Library/Open Christian Data/reports/_logs/bede-pg38326-downstream-preflight-20261001/isolated-category-check-v3')
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def main():
    pre=json.loads(io_path(PRE/'preflight.json').read_bytes())
    if STAGE.exists():raise FileExistsError('Preserve existing isolated diagnostic')
    runtime={p.relative_to(ROOT).as_posix():sha256(io_path(p).read_bytes()).hexdigest() for p in io_glob(ROOT/'schemas/v2','**/*.json')}
    for name in ['ocd_kernel/projection/categories/prose.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py']:runtime[name]=sha256(io_path(ROOT/name).read_bytes()).hexdigest()
    for name,h in pre['current_authority_bindings'].items():
        b=io_path(ROOT/name).read_bytes()
        if sha256(b).hexdigest()!=h:raise ValueError('Authority changed '+name)
        p=io_path(STAGE/name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
    for name in runtime:
        p=io_path(STAGE/name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(io_path(ROOT/name).read_bytes())
    freeze=json.loads(io_path(ROOT/'reports/_logs/barclay-correction-choice-support-20261001/coordinator-reviewed-freeze.json').read_bytes())
    baseline={}
    sys.dont_write_bytecode=True
    import ocd_kernel.projection as package
    for short in ('native_content','native_content_check'):
        name='ocd_kernel.projection.'+short;p=STAGE/'ocd_kernel/projection'/(short+'.py')
        spec=importlib.util.spec_from_file_location(name,p);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);setattr(package,short,module)
    wp=Path('library/works/bede-ecclesiastical-history-of-england/work.json');before=io_path(ROOT/wp).read_bytes();v=json.loads(before)
    edition=v['textual_forms'][0]['editions'][0]
    if 'category' in edition:raise ValueError('Not absent category preimage')
    edition['category']='prose';after=canonical(v);io_path(STAGE/wp).write_bytes(after)
    outcome=dict(checked_at=datetime.now(timezone.utc).isoformat(),canonical_authority_changed=False,isolated_root=STAGE.as_posix(),one_field_patch='textual_forms[0].editions[0].category=prose',work_before_sha256=sha256(before).hexdigest(),work_after_sha256=sha256(after).hexdigest(),runtime_bindings=runtime,current_coordinator_freeze_sha256=sha256(io_path(ROOT/'reports/_logs/barclay-correction-choice-support-20261001/coordinator-reviewed-freeze.json').read_bytes()).hexdigest(),canonical_shared_three_files_under_edit=False)
    try:
        with cached_edition_lookups():
            projection=project_accepted_prose(STAGE,acceptance_path=STAGE/pre['acceptance_path']);errors=verify_accepted_prose(STAGE,acceptance_path=STAGE/pre['acceptance_path'],rows=projection['rows'],receipt=projection['receipt'])
        outcome.update(status='pass' if not errors else 'verification-failed',errors=errors,rows=len(projection['rows']),characters=sum(len(r['text']) for r in projection['rows']))
        io_path(PRE/'isolated-actual-master-projection.json').write_bytes(canonical(projection))
    except PipelineError as e:outcome.update(status='supported-route-rejected',exception_type=type(e).__name__,literal_error=str(e))
    for name,h in pre['current_authority_bindings'].items():
        if sha256(io_path(ROOT/name).read_bytes()).hexdigest()!=h:raise ValueError('Canonical changed '+name)
    outcome['current_runtime_after']={name:sha256(io_path(ROOT/name).read_bytes()).hexdigest() for name in runtime}
    for name,h in runtime.items():
        if name not in baseline and outcome['current_runtime_after'][name]!=h:raise ValueError('Unrelated runtime changed '+name)
    io_path(PRE/'isolated-route-check.json').write_bytes(canonical(outcome));print(json.dumps(outcome))
if __name__=='__main__':main()
