"""Exact L811 fixture root, five boundary negatives and four terminal journals."""
from pathlib import Path
import argparse,importlib.util,json,sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from build.tools import eusebius_l811_install as installer
from ocd_kernel.lib.path_io import io_path,resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files


def prove(stage,pin):
    installer.insist(installer.EXECUTION_RELEASED,'L811 execution remains coordinator-held')
    stage=resolve_path(stage,strict=True);fixture=resolve_path(installer.FIXTURE,strict=False)
    fixture_stage=resolve_path(installer.FIXTURE_STAGE,strict=False)
    canonical=installer.preflight(stage,pin)
    for path in (fixture,fixture_stage):
        if io_path(path).exists():raise FileExistsError('Preserve L811 fixture artifacts: '+path.as_posix())
    io_path(fixture).mkdir(parents=True);io_path(fixture_stage).mkdir(parents=True)
    # External frozen stage stays intact. Task fixture gets the exact old five.
    for relative in _files(stage):
        installer.copy(stage,fixture_stage,Path(relative))
        if relative!='stage-receipt.json' and not Path(relative).is_relative_to(installer.WORK):
            installer.copy(stage,fixture,Path(relative))
    for relative in installer.ORIGINAL_FILES:
        installer.copy(ROOT,fixture,installer.WORK/relative)
    installer.dump(fixture,Path(installer.FIXTURE_MARKER),dict(contract='ocd-l811-accepted-install-fixture-v1',
        work_id=installer.WORK_ID,root=fixture.as_posix()))
    receipt=dict(canonical)|dict(target_root=fixture.as_posix(),stage_path=fixture_stage.as_posix())
    # Only these two root bindings vary; all accepted generation/dependency pins
    # and canonical metadata preimages are conserved from the reviewed stage.
    installer.dump(fixture_stage,Path('stage-receipt.json'),receipt)
    fixture_pin=installer.digest(fixture_stage/'stage-receipt.json')
    installer.dump(ROOT,installer.LOG/'fixture-receipt-binding-v1.json',dict(canonical_receipt_sha256=pin,
        fixture_receipt_sha256=fixture_pin,changed_fields=['target_root','stage_path'],
        canonical_receipt=canonical,fixture_receipt=receipt))
    def unchanged():
        installer.insist(_files(fixture/installer.WORK)==installer.ORIGINAL_FILES
            and _files(ROOT/installer.WORK)==installer.ORIGINAL_FILES
            and _files(stage/installer.WORK)==canonical['after']
            and _files(fixture_stage/installer.WORK)==canonical['after'],
            'L811 rollback/canonical/stage conservation differs')
    wrong=ROOT/'.tmp_audit/eusebius-l811-arbitrary-marked-root-20261004-v1'
    if io_path(wrong).exists():raise FileExistsError('Preserve arbitrary-root negative')
    io_path(wrong).mkdir(parents=True)
    installer.dump(wrong,Path(installer.FIXTURE_MARKER),dict(contract='ocd-l811-accepted-install-fixture-v1',
        work_id=installer.WORK_ID,root=resolve_path(wrong,strict=True).as_posix()))
    wrong_before=_files(wrong);negatives=[]
    attempts=[('wrong-pin',lambda:installer.preflight(fixture_stage,'0'*64,fixture),'Immutable reviewed stage receipt differs'),
        ('arbitrary-marked-root',lambda:installer.task_roots(wrong,fixture_stage,receipt),'Arbitrary install root rejected'),
        ('stage-root-collision',lambda:installer.task_roots(fixture,fixture,receipt),'Stage/root containment collision'),
        ('stage-inside-root',lambda:installer.task_roots(fixture,fixture/installer.WORK,receipt),'Stage/root containment collision'),
        ('root-inside-stage',lambda:installer.task_roots(fixture,fixture.parent,receipt),'Stage/root containment collision')]
    for label,call,expected in attempts:
        try:call()
        except PipelineError as error:
            installer.insist(expected in str(error),'Boundary negative failed for unintended reason: '+str(error))
            negatives.append(dict(label=label,rejected=True,reason=str(error)))
        else:raise PipelineError('L811 boundary admitted '+label)
        unchanged()
    installer.insist(_files(wrong)==wrong_before,'Arbitrary-root rejection changed files')
    def corrupt(point):
        if point=='after-new-live':
            path=fixture/installer.ED/'master.tei.xml'
            io_path(path).write_bytes(io_path(path).read_bytes()+b'\n')
    try:installer.install(fixture_stage,fixture_pin,fixture,fail_at=corrupt)
    except PipelineError as error:
        corruption=dict(rejected=True,changed_at='after-new-live',actual_master_corruption=True,reason=str(error))
    else:raise PipelineError('L811 deliberately corrupted live master admitted')
    unchanged();late=[]
    for label,path in [('checkout',ROOT/'.tmp_audit/eusebius_l811_unexpected_import_v1.py'),
                       ('library',ROOT/installer.LOG/'eusebius_l811_unexpected_import_v1.py')]:
        if io_path(path).exists():raise FileExistsError('Preserve late-import source witness')
        io_path(path).write_text("MARKER = 'L811 actual late import witness'\n",encoding='utf-8')
        name='eusebius_l811_unexpected_'+label
        def import_late(point):
            if point=='after-new-live':
                specification=importlib.util.spec_from_file_location(name,path)
                module=importlib.util.module_from_spec(specification);sys.modules[name]=module
                specification.loader.exec_module(module)
        try:
            try:installer.install(fixture_stage,fixture_pin,fixture,fail_at=import_late)
            except PipelineError as error:
                installer.insist('Unadmitted or changed actual acceptance execution path' in str(error),
                                 'Actual late import failed for unintended reason: '+str(error))
                late.append(dict(label=label,rejected=True,loaded_at='after-new-live',rejected_at='after-new-live',reason=str(error),
                                 path=resolve_path(path,strict=True).as_posix(),sha256=installer.digest(path)))
            else:raise PipelineError('L811 unexpected late import admitted')
        finally:sys.modules.pop(name,None)
        unchanged()
    success=installer.install(fixture_stage,fixture_pin,fixture)
    installer.insist(_files(fixture/installer.WORK)==canonical['after']
        and _files(fixture_stage/installer.WORK)==canonical['after']
        and _files(stage/installer.WORK)==canonical['after']
        and _files(ROOT/installer.WORK)==installer.ORIGINAL_FILES,'L811 success/full conservation differs')
    journals=sorted((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
    installer.insist(len(journals)==4 and sum(installer.read(p)['phase']=='complete' for p in journals)==1
        and sum(installer.read(p)['phase']=='rolled-back' for p in journals)==3,'Exact four terminal L811 journals differ')
    durable=[]
    for ordinal,path in enumerate(journals,1):
        record=installer.read(path)
        installer.insist(record['before']==installer.ORIGINAL_FILES and record['after']==canonical['after']
            and record['existed'] is True and record['replacement'] is False,'Whole fixture journal generation maps differ')
        destination=installer.LOG/('fixture-operation-'+str(ordinal)+'.json')
        if io_path(ROOT/destination).exists():raise FileExistsError('Preserve durable operation journal')
        installer.write(ROOT,destination,io_path(path).read_bytes())
        durable.append(dict(path=destination.as_posix(),sha256=installer.digest(ROOT/destination),phase=record['phase']))
    proof=dict(status='pass',identity=installer.identity(),canonical_stage=stage.as_posix(),canonical_receipt_sha256=pin,
        fixture_stage=fixture_stage.as_posix(),fixture_receipt_sha256=fixture_pin,before=installer.ORIGINAL_FILES,
        after=canonical['after'],boundary_negatives=negatives,deliberate_live_corruption=corruption,
        late_import_negatives=late,three_actual_rollbacks=True,fixture_success_generation_exact=True,
        canonical_original_five_unchanged=True,source_and_header_unchanged=True,durable_journals=durable,
        success=success,canonical_installation='not performed')
    destination=installer.LOG/'guarded-install-fixture-proof-v1.json'
    if io_path(ROOT/destination).exists():raise FileExistsError('Preserve fixture proof')
    installer.dump(ROOT,destination,proof)
    return dict(status='pass',proof=destination.as_posix(),sha256=installer.digest(ROOT/destination))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',type=Path);parser.add_argument('--receipt-sha256',required=True)
    args=parser.parse_args();print(json.dumps(prove(args.stage,args.receipt_sha256),sort_keys=True))
