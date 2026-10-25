"""Bounded Whitefield installation boundary, rollback and success evidence."""
from pathlib import Path
import argparse,importlib.util,json,sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from build.tools import tyerman_whitefield_install as installer
from ocd_kernel.lib.path_io import io_path,resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files

def prove(stage,pin):
    stage=resolve_path(stage,strict=True);fixture=installer.FIXTURE
    if fixture.exists():raise FileExistsError('Preserve Whitefield fixture evidence')
    receipt=installer.read(stage/'stage-receipt.json');before={};preserved=installer.preserved()
    if receipt['bootstrap'] or receipt['before']!=before or installer.sha(stage/'stage-receipt.json')!=pin:
        raise PipelineError('Exact installable Whitefield fixture receipt required')
    fixture.mkdir(parents=True)
    for path in _files(stage):
        if not path.startswith('library/') and path!='stage-receipt.json':installer.copy(stage,fixture,Path(path))
    for work,files in preserved.items():
        for path in files:installer.copy(ROOT,fixture,Path(work)/path)
    (fixture/'.ocd-tyerman-whitefield-fixture').write_text('fixture-only\n',encoding='utf-8')
    wrong=ROOT/'.tmp_audit/tyerman-whitefield-arbitrary-fixture-20261004-v1'
    if wrong.exists():raise FileExistsError('Preserve Whitefield arbitrary-root evidence')
    wrong.mkdir();(wrong/'.ocd-tyerman-whitefield-fixture').write_text('fixture-only\n',encoding='utf-8');wrong_before=_files(wrong)
    def unchanged():
        if _files(fixture/installer.WORK)!=before or io_path(fixture/installer.WORK).exists() or installer.preserved(fixture)!=preserved or installer.preserved()!=preserved or io_path(ROOT/installer.WORK).exists() or _files(stage/installer.WORK)!=receipt['after']:
            raise PipelineError('Whitefield fixture/legacy/stage/canonical conservation differs')
    negatives=[]
    for label,bad_stage,bad_pin,bad_root in [('wrong-pin',stage,'0'*64,fixture),('arbitrary-marked-root',stage,pin,wrong),('collision',fixture,pin,fixture),('stage-inside-root',fixture/installer.PRESERVED[0],pin,fixture),('root-inside-stage',fixture.parent,pin,fixture)]:
        try:installer.preflight(bad_stage,bad_pin,root=bad_root)
        except PipelineError as error:negatives.append(dict(label=label,rejected=True,reason=str(error)))
        else:raise PipelineError('Whitefield boundary admitted '+label)
        unchanged()
    if _files(wrong)!=wrong_before:raise PipelineError('Whitefield arbitrary-root rejection changed files')
    def fault(point):
        if point=='after-new-live':raise RuntimeError('whitefield-fixture-after-new-live')
    try:installer.install(stage,pin,root=fixture,fail_at=fault)
    except RuntimeError as error:
        if str(error)!='whitefield-fixture-after-new-live':raise
    else:raise PipelineError('Whitefield injected rollback fault absent')
    unchanged();late=[]
    for label,path in [('checkout',ROOT/'.tmp_audit/tyerman_whitefield_unexpected_import_v1.py'),('library',ROOT/installer.LOG/'tyerman_whitefield_unexpected_import_v1.py')]:
        if io_path(path).exists():raise FileExistsError('Preserve Whitefield unexpected-import witness')
        io_path(path).write_text("MARKER = 'Whitefield late import witness'\n",encoding='utf-8');name='tyerman_whitefield_unexpected_'+label
        def import_late(point):
            if point=='after-new-live':
                definition=importlib.util.spec_from_file_location(name,path)
                module=importlib.util.module_from_spec(definition);sys.modules[name]=module;definition.loader.exec_module(module)
        try:
            try:installer.install(stage,pin,root=fixture,fail_at=import_late)
            except PipelineError as error:
                if 'Unexpected executed Whitefield dependency' not in str(error):raise
                late.append(dict(label=label,rejected=True,loaded_at='after-new-live',rejected_at='after-validated',reason=str(error),path=path.as_posix(),sha256=installer.sha(path)))
            else:raise PipelineError('Whitefield late import admitted')
        finally:sys.modules.pop(name,None)
        unchanged()
    success=installer.install(stage,pin,root=fixture)
    if _files(fixture/installer.WORK)!=receipt['after'] or _files(stage/installer.WORK)!=receipt['after'] or io_path(ROOT/installer.WORK).exists() or installer.preserved()!=preserved or installer.preserved(fixture)!=preserved:
        raise PipelineError('Whitefield success fixture generation differs')
    journals=sorted((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
    if len(journals)!=4 or sum(installer.read(p)['phase']=='complete' for p in journals)!=1 or sum(installer.read(p)['phase'] in {'rolled-back','rollback-complete'} for p in journals)!=3:
        raise PipelineError('Whitefield exact four terminal journals differ')
    durable=[]
    for number,path in enumerate(journals,1):
        record=installer.read(path)
        if record['before']!=before or record['after']!=receipt['after']:raise PipelineError('Whitefield complete journal maps differ')
        destination=installer.LOG/('fixture-operation-'+str(number)+'.json')
        if io_path(ROOT/destination).exists():raise FileExistsError('Preserve Whitefield durable journal')
        installer.write(ROOT,destination,io_path(path).read_bytes());durable.append(dict(path=destination.as_posix(),sha256=installer.sha(ROOT/destination),phase=record['phase']))
    proof=dict(status='pass',identity=installer.identity(),stage_root=stage.as_posix(),stage_receipt_sha256=pin,before=before,after=receipt['after'],preserved_before_after=preserved,boundary_negatives=negatives,late_import_negatives=late,injected_rollback_exact=True,fixture_success_generation_exact=True,canonical_preimage_exact=True,durable_journals=durable,success=success,canonical_installation='not performed')
    target=installer.LOG/'guarded-install-fixture-proof-v1.json'
    if io_path(ROOT/target).exists():raise FileExistsError('Preserve Whitefield fixture proof')
    installer.dump(ROOT,target,proof);return dict(status='pass',proof_path=target.as_posix(),proof_sha256=installer.sha(ROOT/target))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',type=Path);parser.add_argument('--receipt-sha256',required=True);args=parser.parse_args()
    print(json.dumps(prove(args.stage,args.receipt_sha256),sort_keys=True))
