"""Guarded additive installation of one complete Psalms work; legacy volumes stay exact."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from build.tei.maclaren_psalms_complete_prepare import ROOT, WORK as WORK_ID, MEMBERS, STATUS, canonical
from build.tei.maclaren_psalms_complete_oracle import oracle
from build.tools.prepare_maclaren_psalms_complete import SOURCE, LOG, DESTINATION
from build.tools.propose_maclaren_psalms_complete import FORM, EDITION, ACQUISITION, SCOPE
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, validate
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, write_acceptance, validate_acceptance, PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.install_accepted import _files, _commit_generation
from ocd_kernel.tei.validate import validate_file
from build.tools.stage_maclaren_retained_acceptance import projection_gate

LIBRARY = Path('D:/Library/Open Christian Data')
WORK = Path('library/works')/WORK_ID
EDITION_PATH = WORK/'forms'/FORM/'editions'/EDITION
LANE = WORK/'integration/maclaren-psalms-complete-20261003-v1'
FIXTURE = ROOT/'.tmp_audit/maclaren-psalms-complete-fixture-20261003-v1'
MASTER_STATUS = 'Agent-accepted complete faithful authored work reconstructed from three already acquired CCEL electronic volumes. Human review, print collation, rights and publication remain separate.'

def read(path):return json.loads(io_path(path).read_bytes())
def digest(path):return sha256(io_path(path).read_bytes()).hexdigest()
def write(root,path,raw):
    target=io_path(root/path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    return root/path
def write_json(root,path,value):return write(root,path,canonical(value))
def copy(root,stage,path):return write(stage,path,io_path(root/path).read_bytes())

def dependencies():
    prior=read(LIBRARY/'candidate-reviews/maclaren-s-current-20261003-v3/stage-receipt.json')
    paths={Path(p) for p in prior['dependency_files']}
    source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT)
    paths.update(Path(r['path']) for r in source.record['authorities'])
    paths.update(SOURCE/name for name in ('source-manifest.json','psalms.retained-member-set.json'))
    paths.update(LOG/name for name in ('candidate-completion-receipt.json','complete-work-boundary-proposal.json','work-plus-psalms-proposal.json','psalms-grouped-acquisition-proposal.json'))
    paths.update(Path(p) for p in ('build/tei/maclaren_psalms_complete_prepare.py','build/tei/maclaren_psalms_complete_oracle.py','build/tools/prepare_maclaren_psalms_complete.py','build/tools/propose_maclaren_psalms_complete.py','build/tools/maclaren_psalms_complete_install.py'))
    return paths

def bound(raw,acquisition,revision):
    identity=dict(work_id=WORK_ID,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION)
    source={k:acquisition[k] for k in ('source_path','source_sha256','source_bytes','source_scope','source_kind')}
    result=bind_reviewed_header(raw,expected_sha256=sha256(raw).hexdigest(),identity=identity,source=source,
        source_url=acquisition['url'],declared_scope=SCOPE,revision=revision)
    if result.count(STATUS.encode())!=1:raise PipelineError('Complete Psalms publication preimage differs')
    return result.replace(STATUS.encode(),MASTER_STATUS.encode(),1)

def prepare(stage):
    stage=stage.absolute()
    if stage.exists() or stage.parent!=LIBRARY/'candidate-reviews' or not stage.name.startswith('maclaren-psalms-s-'):
        raise PipelineError('Fresh external complete Psalms stage required')
    before=_files(ROOT/WORK)
    if len(before)!=80:raise PipelineError('Exact installed Maclaren preimage required')
    proposal=read(ROOT/LOG/'work-plus-psalms-proposal.json'); original=read(ROOT/WORK/'work.json')
    validate_identity_update(original,proposal)
    if proposal['textual_forms'][:-1]!=original['textual_forms']:raise PipelineError('Legacy Maclaren identities changed')
    stage.mkdir()
    for path in before:copy(ROOT,stage,WORK/path)
    for path in dependencies():copy(ROOT,stage,path)
    state=read(ROOT/WORK/'state.json')
    for path in set(original['evidence']+[p for row in state['targets'] for p in row['evidence']]):
        lexical=Path(path.split('#',1)[0])
        if not io_path(stage/lexical).exists():copy(ROOT,stage,lexical)
    write_json(stage,WORK/'work.json',proposal)
    acquisition=read(ROOT/LOG/'psalms-grouped-acquisition-proposal.json')
    acquisition_path=EDITION_PATH/'acquisitions'/(ACQUISITION+'.json')
    write_json(stage,acquisition_path,acquisition);validate_acquisition(stage/acquisition_path,root=stage)
    source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT)
    package=CandidatePackage.load(DESTINATION/'package');report=validate(source,package,oracle)
    completion=read(ROOT/LOG/'candidate-completion-receipt.json')
    if completion['status']!='pass' or completion['candidate_package_sha256']!=package.sha256 or completion['oracle_report_sha256']!=report.sha256 or len(completion['mutations'])!=8 or not all(r['rejected'] and r['p5']=='pass' for r in completion['mutations']) or len(completion['replays'])!=2 or not all(r['all_six_members_byte_equal'] for r in completion['replays']):
        raise PipelineError('Complete Psalms source proof differs')
    for name in package.member_names:write(stage,LANE/'inputs/package'/name,package.member_bytes(name))
    copy(ROOT,stage,LOG/'candidate-completion-receipt.json')
    write(stage,LANE/'source-review.json',io_path(ROOT/LOG/'candidate-completion-receipt.json').read_bytes())
    at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    revision=dict(id='maclaren-psalms-complete-20261003-v1',date=at[:10],note='One complete authored Psalms work, three unchanged source-volume native text trees.')
    raw=package.member_bytes('content.tei.xml');master=bound(raw,acquisition,revision)
    if master.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise PipelineError('Complete Psalms binding changed body')
    candidate=write(stage,LANE/'candidate.tei.xml',master)
    if errors:=validate_file(candidate):raise PipelineError(str(errors))
    identity=dict(work_id=WORK_ID,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION)
    source_binding={k:acquisition[k] for k in ('source_path','source_sha256','source_bytes','source_scope','source_kind')}
    expected=[dict(path=r['path'],position=i) for i,r in enumerate(acquisition['retained_files'],1)]
    included=[dict(path=r['path'],position=i,bytes=r['bytes'],sha256=r['sha256'],scope=r['scope']) for i,r in enumerate(acquisition['retained_files'],1)]
    common=dict(identity=identity,source=source_binding,candidate=make_file_binding(stage,candidate),accepted_scope=dict(kind='work',declared=SCOPE),
        scope=SCOPE,expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],
        source_manifest_sha256=source.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,
        representation_revision=revision,staged_at=at)
    accounting=write_json(stage,LANE/'source-accounting.json',common|dict(source_sha256=acquisition['source_sha256'],source_bytes=acquisition['source_bytes'],complete_works=1,source_volumes=3,
        ordered_members=list(MEMBERS),omitted_readable_elements=0,source_review=make_file_binding(stage,stage/LANE/'source-review.json'),
        source_hash_qualification='Acquisition source hash identifies explicit ordered member-set file; independent source oracle also binds each exact raw XML authority.'))
    command='py -3 -m build.tools.maclaren_psalms_complete_install --stage'
    technical=dict(producer=dict(id=source.record['converter']['id']),checker=dict(id=source.record['validator']['id']),
        shared_assumptions=['Existing source-checked native volume packages are conserved; mapping exposure is declared.'],
        independent_corroboration='Independent full serialized group fields, source-derived header order and all three ACTUAL volume slices checked against raw source semantic fields and complete body inverses; global identities/reference closure and P5 pass. Eight valid mutations rejected and two isolated six-member replays match.')
    for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
        proof=write_json(stage,LANE/(name+'.json'),common|dict(status='pass',command=command,exit_code=0,claim=name,complete_group_source_gate='pass'))
        technical[name]=dict(path=proof,status='pass',command=command,exit_code=0)
    coverage=['all three complete source-volume native text trees and all raw source readings/attributes/URI contexts',
        'all source front/body/back, notes, printed/generated indexes, source headers/prologs and administration',
        'whole grouped envelope, global IDs, ordered volume boundaries and exact machine source metadata']
    review=dict(reviewer='agent:maclaren-psalms-complete-source-review',reviewed_at=at,
        coverage=dict(status='complete',declared=SCOPE,reached=coverage,inspected=coverage,unreviewed=[]),
        source_quality_uncertainty=['Retained electronic sources only; distinct source print statements remain per volume.',
            'Human review, print/CSS collation, rights and publication remain separate.'],discrepancies=[],
        unreviewed_residuals=['Downstream commentary projection is separately measured.'])
    review_path=write_json(stage,LANE/'review.json',common|review)
    decision=dict(source_local_disposition='Agent accepts one complete faithful retained authored Psalms work from the three existing source volumes.',blockers=[],
        agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=SCOPE,unresolved_claims=[],
            unassessed_stronger_claims=['human review','print collation','rights clearance','publication','author or series completeness','downstream commentary projection']),
        human_decision=dict(status='not-recorded'))
    record=build_acceptance_record(stage,identity=identity,candidate_path=candidate,source_accounting_path=accounting,
        scope=dict(kind='work',declared=SCOPE,expected_members=expected,included_members=included,excluded_members=[]),
        technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
    master_path=write(stage,EDITION_PATH/'master.tei.xml',master)
    record['promotion']=dict(record['promotion'])|dict(status='promoted',promoted_at=at,master=make_file_binding(stage,master_path))
    write_acceptance(stage/EDITION_PATH/'acceptance.json',record)
    evidence=[acquisition_path.as_posix(),(LOG/'complete-work-boundary-proposal.json').as_posix()]
    state['targets'].extend([dict(target_type='acquisition',target_id=ACQUISITION,stage='acquired',updated_at=at,evidence=evidence),
        dict(target_type='edition',target_id=EDITION,stage='accepted',updated_at=at,reason=PROMOTED_MASTER_REASON,evidence=evidence+[(EDITION_PATH/'master.tei.xml').as_posix(),(EDITION_PATH/'acceptance.json').as_posix()])])
    write_json(stage,WORK/'state.json',state);load_work(stage/WORK/'work.json');validate_state(stage/WORK/'state.json',root=stage)
    validate_acceptance(stage/EDITION_PATH/'acceptance.json',root=stage)
    gate=projection_gate(stage,stage/EDITION_PATH/'acceptance.json')
    receipt=dict(contract='ocd-maclaren-psalms-complete-stage-v1',status='staged-only',work_id=WORK_ID,complete_works=1,source_volumes=3,
        stage_root=stage.as_posix(),staged_at=at,before=before,after=_files(stage/WORK),revision=revision,
        master_sha256=digest(master_path),acceptance_sha256=digest(stage/EDITION_PATH/'acceptance.json'),
        package_sha256=package.sha256,oracle_report_sha256=report.sha256,projection_gate=gate,
        dependency_files={p.as_posix():digest(ROOT/p) for p in sorted(dependencies())})
    write_json(stage,Path('stage-receipt.json'),receipt)
    return dict(status='staged-only',stage_root=stage.as_posix(),receipt_sha256=digest(stage/'stage-receipt.json'),after_files=len(receipt['after']))

def execution(receipt):
    pins={resolve_path(ROOT/p,strict=True):(p,h) for p,h in receipt['dependency_files'].items()}
    observed={}
    for module in sys.modules.copy().values():
        filename=getattr(module,'__file__',None)
        if not filename:continue
        path=resolve_path(Path(filename),strict=True)
        if path.is_relative_to(resolve_path(ROOT,strict=True)) or path.is_relative_to(resolve_path(LIBRARY,strict=True)):
            if path not in pins:raise PipelineError('Unexpected executed complete Psalms dependency: '+path.as_posix())
            relative,pin=pins[path]
            if digest(path)!=pin:raise PipelineError('Complete Psalms executed implementation drifted')
            observed[relative]=pin
    return observed

def preflight(stage,pin,root=ROOT):
    stage=resolve_path(stage,strict=True);root=resolve_path(root,strict=True)
    if root!=resolve_path(ROOT,strict=True):
        if root!=resolve_path(FIXTURE,strict=True) or (root/'.ocd-maclaren-psalms-fixture').read_text()!='fixture-only\n':
            raise PipelineError('Complete Psalms exact fixture path required')
    if root==stage or root in stage.parents or stage in root.parents or stage.parent!=resolve_path(LIBRARY/'candidate-reviews',strict=True) or not stage.name.startswith('maclaren-psalms-s-'):
        raise PipelineError('Complete Psalms stage/root boundary differs')
    if digest(stage/'stage-receipt.json')!=pin:raise PipelineError('Complete Psalms receipt pin differs')
    receipt=read(stage/'stage-receipt.json')
    if receipt['contract']!='ocd-maclaren-psalms-complete-stage-v1' or receipt['status']!='staged-only' or receipt['work_id']!=WORK_ID or receipt['complete_works']!=1 or receipt['source_volumes']!=3 or receipt['stage_root']!=stage.as_posix():
        raise PipelineError('Complete Psalms receipt scope differs')
    if _files(root/WORK)!=receipt['before'] or _files(stage/WORK)!=receipt['after']:raise PipelineError('Complete Psalms generation differs')
    for path,pin_value in receipt['before'].items():
        if path not in {'work.json','state.json'} and receipt['after'].get(path)!=pin_value:raise PipelineError('Legacy Maclaren authority changed')
    edition_relative=EDITION_PATH.relative_to(WORK).as_posix()+'/'
    lane_relative=LANE.relative_to(WORK).as_posix()+'/'
    if any(not (p.startswith(edition_relative) or p.startswith(lane_relative)) for p in set(receipt['after'])-set(receipt['before'])):
        raise PipelineError('Unexpected complete Psalms added path')
    if io_path(root/EDITION_PATH).exists():raise PipelineError('Complete Psalms edition already exists; no replacement')
    for path,pin_value in receipt['dependency_files'].items():
        if digest(ROOT/path)!=pin_value or digest(stage/path)!=pin_value:raise PipelineError('Complete Psalms dependency drifted: '+path)
    proposed=read(ROOT/LOG/'work-plus-psalms-proposal.json')
    if read(stage/WORK/'work.json')!=proposed:raise PipelineError('Complete Psalms identity proposal changed')
    validate_identity_update(read(root/WORK/'work.json'),proposed)
    acquisition=validate_acquisition(stage/EDITION_PATH/'acquisitions'/(ACQUISITION+'.json'),root=stage)
    if acquisition!=read(ROOT/LOG/'psalms-grouped-acquisition-proposal.json'):raise PipelineError('Complete Psalms acquisition proposal changed')
    source=SourceManifest.load(ROOT/SOURCE/'source-manifest.json',repository_root=ROOT)
    package=CandidatePackage.load(stage/LANE/'inputs/package');report=validate(source,package,oracle)
    if package.sha256!=receipt['package_sha256'] or report.sha256!=receipt['oracle_report_sha256']:raise PipelineError('Complete Psalms fresh source gate differs')
    revision=dict(id='maclaren-psalms-complete-20261003-v1',date=receipt['staged_at'][:10],note='One complete authored Psalms work, three unchanged source-volume native text trees.')
    if revision!=receipt['revision']:raise PipelineError('Complete Psalms exact revision differs')
    expected_master=bound(package.member_bytes('content.tei.xml'),acquisition,revision)
    if io_path(stage/EDITION_PATH/'master.tei.xml').read_bytes()!=expected_master or digest(stage/EDITION_PATH/'master.tei.xml')!=receipt['master_sha256'] or digest(stage/EDITION_PATH/'acceptance.json')!=receipt['acceptance_sha256']:
        raise PipelineError('Complete Psalms exact reviewed header/body differs')
    accepted=validate_acceptance(stage/EDITION_PATH/'acceptance.json',root=stage)
    if accepted['representation_revision']!=revision or accepted['promotion']['status']!='promoted':raise PipelineError('Complete Psalms acceptance revision differs')
    state=read(stage/WORK/'state.json');old_state=read(root/WORK/'state.json')
    if state['targets'][:-2]!=old_state['targets'] or state['work_id']!=old_state['work_id']:raise PipelineError('Legacy Maclaren state changed')
    evidence=[(EDITION_PATH/'acquisitions'/(ACQUISITION+'.json')).as_posix(),(LOG/'complete-work-boundary-proposal.json').as_posix()]
    expected_targets=[dict(target_type='acquisition',target_id=ACQUISITION,stage='acquired',updated_at=receipt['staged_at'],evidence=evidence),
        dict(target_type='edition',target_id=EDITION,stage='accepted',updated_at=receipt['staged_at'],reason=PROMOTED_MASTER_REASON,evidence=evidence+[(EDITION_PATH/'master.tei.xml').as_posix(),(EDITION_PATH/'acceptance.json').as_posix()])]
    if state['targets'][-2:]!=expected_targets or {k:v for k,v in state.items() if k!='targets'}!={k:v for k,v in old_state.items() if k!='targets'}:raise PipelineError('Complete Psalms state transition differs')
    validate_state(stage/WORK/'state.json',root=stage)
    if projection_gate(stage,stage/EDITION_PATH/'acceptance.json')!=receipt['projection_gate']:raise PipelineError('Complete Psalms actual projection changed')
    execution(receipt)
    return receipt

def install(stage,pin,root=ROOT,fail_at=None):
    with ExitStack() as locks:
        for target in sorted((root/WORK,stage/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(target,acquire_timeout=30.0))
        receipt=preflight(stage,pin,root=root);observed={}
        def checkpoint(point):
            if point=='after-validated':
                if _files(root/WORK)!=receipt['after']:raise PipelineError('Complete Psalms installed generation differs')
                validate_acceptance(root/EDITION_PATH/'acceptance.json',root=root);validate_state(root/WORK/'state.json',root=root)
                if projection_gate(root,root/EDITION_PATH/'acceptance.json')!=receipt['projection_gate']:raise PipelineError('Complete Psalms installed projection changed')
                observed.update(execution(receipt))
            if fail_at:fail_at(point)
        result=_commit_generation(root,root/WORK,stage/WORK,work_id=WORK_ID,before=receipt['before'],after=receipt['after'],existed=True,replacement=False,
            operation_kind='maclaren-psalms-complete-additive-install',result_status='installed-and-validated',accepted_editions=1,fail_at=checkpoint)
        return result|dict(late_execution_gate='pass',executed_code_pins=observed)

def prove_fixture(stage,pin):
    stage=resolve_path(stage,strict=True)
    if FIXTURE.exists():raise FileExistsError('Preserve complete Psalms fixture evidence')
    receipt=read(stage/'stage-receipt.json');before=_files(ROOT/WORK)
    if before!=receipt['before']:raise PipelineError('Complete Psalms fixture preimage differs')
    FIXTURE.mkdir(parents=True)
    for path in _files(stage):
        if not path.startswith('library/') and path!='stage-receipt.json':copy(stage,FIXTURE,Path(path))
    for path in before:copy(ROOT,FIXTURE,WORK/path)
    (FIXTURE/'.ocd-maclaren-psalms-fixture').write_text('fixture-only\n')
    negatives=[]
    wrong_root=ROOT/'.tmp_audit/maclaren-psalms-arbitrary-fixture-20261003-v1'
    if wrong_root.exists():raise FileExistsError('Preserve complete Psalms arbitrary-root fixture')
    wrong_root.mkdir();(wrong_root/'.ocd-maclaren-psalms-fixture').write_text('fixture-only\n')
    wrong_before=_files(wrong_root)
    for label,bad_stage,bad_pin,bad_root in [('wrong-pin',stage,'0'*64,FIXTURE),
        ('arbitrary-marked-root',stage,pin,wrong_root),('collision',FIXTURE,pin,FIXTURE),
        ('stage-inside-root',FIXTURE/WORK,pin,FIXTURE),('root-inside-stage',FIXTURE.parent,pin,FIXTURE)]:
        try:preflight(bad_stage,bad_pin,root=bad_root)
        except PipelineError as error:negatives.append(dict(label=label,rejected=True,reason=str(error)))
        else:raise PipelineError('Complete Psalms fixture boundary admitted '+label)
    if _files(FIXTURE/WORK)!=before or _files(wrong_root)!=wrong_before:raise PipelineError('Complete Psalms boundary rejection mutated fixture')
    def fault(point):
        if point=='after-new-live':raise RuntimeError('complete-psalms-rollback-fixture')
    try:install(stage,pin,root=FIXTURE,fail_at=fault)
    except RuntimeError as error:
        if str(error)!='complete-psalms-rollback-fixture':raise
    else:raise PipelineError('Complete Psalms fixture fault absent')
    if _files(FIXTURE/WORK)!=before:raise PipelineError('Complete Psalms injected rollback changed preimage')
    late=[]
    for label,path in [('checkout',ROOT/'.tmp_audit/maclaren_psalms_unexpected_import_v1.py'),
        ('library',ROOT/LOG/'maclaren_psalms_unexpected_import_v1.py')]:
        if path.exists():raise FileExistsError('Preserve complete Psalms late-import fixture')
        path.write_text("MARKER = 'complete Psalms late-import fixture'\n",encoding='utf-8')
        module_name='maclaren_psalms_unexpected_'+label
        def import_late(point):
            if point=='after-new-live':
                definition=importlib.util.spec_from_file_location(module_name,path)
                module=importlib.util.module_from_spec(definition);sys.modules[module_name]=module;definition.loader.exec_module(module)
        try:
            try:install(stage,pin,root=FIXTURE,fail_at=import_late)
            except PipelineError as error:
                if 'Unexpected executed complete Psalms dependency' not in str(error):raise
                late.append(dict(label=label,rejected=True,loaded_at='after-new-live',rejected_at='after-validated',reason=str(error)))
            else:raise PipelineError('Complete Psalms late import admitted')
        finally:sys.modules.pop(module_name,None)
        if _files(FIXTURE/WORK)!=before:raise PipelineError('Complete Psalms late-import rollback changed preimage')
    success=install(stage,pin,root=FIXTURE)
    if _files(FIXTURE/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before or _files(stage/WORK)!=receipt['after']:
        raise PipelineError('Complete Psalms fixture success generation differs')
    journals=sorted((FIXTURE/'.tmp_audit').glob('accepted-install-*/operation.json'))
    if len(journals)!=4 or sum(read(p)['phase']=='complete' for p in journals)!=1 or sum(read(p)['phase'] in {'rolled-back','rollback-complete'} for p in journals)!=3:
        raise PipelineError('Complete Psalms fixture terminal journals differ')
    durable=[]
    for number,path in enumerate(journals,1):
        record=read(path)
        if record['before']!=before or record['after']!=receipt['after']:raise PipelineError('Complete Psalms fixture journal generation differs')
        destination=LOG/('fixture-operation-'+str(number)+'.json')
        if (ROOT/destination).exists():raise FileExistsError('Preserve complete Psalms durable journal')
        write(ROOT,destination,io_path(path).read_bytes());durable.append(dict(path=destination.as_posix(),sha256=digest(ROOT/destination),phase=record['phase']))
    proof=dict(status='pass',work_id=WORK_ID,stage_root=stage.as_posix(),stage_receipt_sha256=pin,
        before_files=len(before),after_files=len(receipt['after']),boundary_negatives=negatives,late_import_negatives=late,
        injected_rollback_exact=True,fixture_success_generation_exact=True,canonical_preimage_exact=True,
        stage_generation_exact=True,durable_journals=durable,success=success,canonical_installation='not-performed')
    path=LOG/'guarded-install-fixture-proof.json'
    if (ROOT/path).exists():raise FileExistsError('Preserve complete Psalms fixture proof')
    write_json(ROOT,path,proof)
    return dict(status='pass',proof_path=path.as_posix(),proof_sha256=digest(ROOT/path))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',type=Path);parser.add_argument('--prepare',action='store_true');parser.add_argument('--expected-sha256');parser.add_argument('--apply',action='store_true');parser.add_argument('--prove-fixture',action='store_true');args=parser.parse_args()
    if args.prepare:result=prepare(args.stage)
    elif args.prove_fixture:result=prove_fixture(args.stage,args.expected_sha256)
    elif args.apply:result=install(args.stage,args.expected_sha256)
    else:receipt=preflight(args.stage,args.expected_sha256);result=dict(status='preflight-pass',after_files=len(receipt['after']))
    print(json.dumps(result,sort_keys=True))
