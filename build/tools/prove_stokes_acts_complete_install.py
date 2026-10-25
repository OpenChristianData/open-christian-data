"""Exact fixture proof of pinned complete Acts install and late-import rollback."""
from pathlib import Path
import argparse,importlib.util,json,sys
from build.tools import stokes_acts_complete_install as installer
from ocd_kernel.library._common import PipelineError

def fixture(stage,pin):
    stage=stage.resolve(strict=True);receipt=installer.read(stage/'stage-receipt.json');root=installer.FIXTURE
    if root.exists():raise PipelineError('Preserve previous complete Acts fixture')
    root.mkdir(parents=True);(root/installer.FIXTURE_MARKER).write_bytes(b'fixture-only\n')
    for relative in receipt['before']:installer.copy(installer.ROOT,root,installer.WORK/relative)
    for relative in receipt['dependency_files']:installer.copy(installer.ROOT,root,Path(relative))
    before=installer.task._files(root/installer.WORK);events=[];journals={}
    def bind_journal(case,phase):
        found={p for p in (root/'.tmp_audit').glob('accepted-install-*/operation.json')}
        remaining=found-{Path(p) for p in journals}
        if len(remaining)!=1:raise PipelineError('Expected one new actual complete Acts operation journal')
        path=remaining.pop();record=installer.read(path)
        if record['phase']!=phase or record['before']!=receipt['before'] or record['after']!=receipt['after'] or record['work_id']!=installer.task.WORK:raise PipelineError('Actual complete Acts terminal journal differs')
        destination=installer.task.LOG/'fixture-journals'/(case+'.operation.json')
        installer.task.write(destination,path.read_bytes());journals[path.as_posix()]=dict(case=case,phase=phase,original_sha256=installer.digest(path),durable_copy=(installer.ROOT/destination).as_posix(),durable_sha256=installer.digest(installer.ROOT/destination),record=record)
        return record
    def exact_before():
        if installer.task._files(root/installer.WORK)!=before:raise PipelineError('Complete Acts fixture did not restore exact legacy before generation')
    try:installer.preflight(stage,'0'*64,root=root)
    except PipelineError as error:
        if 'caller receipt pin differs' not in str(error):raise
        events.append(dict(case='wrong-caller-pin',rejected=True,reason=str(error),exact_before=True))
    else:raise PipelineError('Wrong complete Acts receipt pin admitted')
    exact_before()
    arbitrary=installer.ROOT/'.tmp_audit/stokes-acts-correctly-marked-wrong-root-20261003-v1'
    if arbitrary.exists():raise PipelineError('Preserve prior misplaced fixture root')
    arbitrary.mkdir();(arbitrary/installer.FIXTURE_MARKER).write_bytes(b'fixture-only\n')
    try:installer.preflight(stage,pin,root=arbitrary)
    except PipelineError as error:
        if 'Exact complete Acts task fixture root required' not in str(error):raise
        events.append(dict(case='correct-marker-wrong-root',rejected=True,reason=str(error),exact_before=True))
    else:raise PipelineError('Arbitrary marked complete Acts fixture admitted')
    child=root/'stokes-acts-s-contained-stage';child.mkdir()
    for label,contained in [('stage-inside-root',child),('root-inside-stage',root.parent)]:
        try:installer.preflight(contained,pin,root=root)
        except PipelineError as error:
            if 'stage/root containment differs' not in str(error):raise
            events.append(dict(case=label,rejected=True,reason=str(error),exact_before=True))
        else:raise PipelineError('Complete Acts containment admitted '+label)
        exact_before()
    checkpoints=[]
    def after_new(point):
        checkpoints.append(point)
        if point=='after-new-live':
            if installer.task._files(root/installer.WORK)!=receipt['after']:raise PipelineError('New complete Acts generation not live at rollback checkpoint')
            raise PipelineError('Injected complete Acts failure after new live generation')
    try:installer.install(stage,pin,root=root,fail_at=after_new)
    except PipelineError as error:
        if 'Injected complete Acts failure' not in str(error):raise
        exact_before();bind_journal('after-new-live','rolled-back');events.append(dict(case='after-new-live',rejected=True,reason=str(error),exact_before=True,checkpoints=checkpoints))
    else:raise PipelineError('Complete Acts injected rollback did not fail')
    probes=[('checkout',installer.ROOT/'.tmp_audit/stokes-acts-unexpected-execution-20261003-v1.py'),('library',installer.LIBRARY/'candidate-reviews/stokes-acts-unexpected-execution-20261003-v1.py')]
    for label,path in probes:
        if path.exists():raise PipelineError('Preserve previous unexpected import probe '+str(path))
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'FIXTURE_IMPORT_ONLY = True\n')
        module_name='stokes_acts_unexpected_'+label;points=[]
        def late(point):
            points.append(point)
            if point=='after-new-live':
                if installer.task._files(root/installer.WORK)!=receipt['after']:raise PipelineError('Late import fixture lacks exact new generation')
                spec=importlib.util.spec_from_file_location(module_name,path)
                if spec is None or spec.loader is None:raise PipelineError('Fixture import spec unavailable')
                module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module;spec.loader.exec_module(module)
        try:installer.install(stage,pin,root=root,fail_at=late)
        except PipelineError as error:
            if 'Complete Acts after-validated execution gate rejected: Unexpected complete Acts executed dependency' not in str(error):raise
            if 'after-new-live' not in points:raise PipelineError('Late import did not reach new live generation')
            exact_before();bind_journal('late-'+label+'-import','rolled-back');events.append(dict(case='late-'+label+'-import-after-new-live',rejected=True,reason=str(error),actual_after_validated_guard_rejected=True,exact_before=True,checkpoints=points,probe=dict(path=path.as_posix(),sha256=installer.digest(path))))
        else:raise PipelineError('Unexpected late complete Acts import admitted')
        finally:sys.modules.pop(module_name,None)
    success=installer.install(stage,pin,root=root)
    after=installer.task._files(root/installer.WORK)
    if after!=receipt['after'] or success['late_execution_dependency_gate']!='pass':raise PipelineError('Complete Acts final fixture readback differs')
    for relative,value in before.items():
        if relative not in ('work.json','state.json') and after[relative]!=value:raise PipelineError('Complete Acts fixture changed legacy authority')
    installer.validate_acceptance(root/installer.EDITION/'acceptance.json',root=root);installer.task.validate_state(root/installer.WORK/'state.json',root=root)
    bind_journal('success','complete')
    if len(journals)!=4:raise PipelineError('Four actual complete Acts terminal journals required')
    result=dict(status='pass',fixture_root=root.as_posix(),stage_root=stage.as_posix(),stage_receipt_sha256=pin,complete_works=1,source_volumes=2,before=before,after=after,cases=events,success=success,journals=journals,execution_modules=installer.assert_execution(receipt),legacy_authority_exact=True,canonical_installation=False)
    destination=installer.task.LOG/'complete-install-fixture-proof.json';installer.task.write(destination,installer.task.canonical(result))
    print(json.dumps(dict(status='pass',proof=(installer.ROOT/destination).as_posix(),sha256=installer.digest(installer.ROOT/destination),cases=len(events),before_files=len(before),after_files=len(after))))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--expected-sha256',required=True);a=p.parse_args();fixture(a.stage,a.expected_sha256)
