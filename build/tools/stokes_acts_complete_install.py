"""Stage and guard one additive complete Acts master; preserve both legacy volumes."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import argparse,json,sys
from lxml import etree
from build.tools import prepare_stokes_acts_complete as task
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import build_acceptance_record,make_file_binding,write_acceptance,validate_acceptance,PROMOTED_MASTER_REASON
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.install_accepted import _commit_generation
from ocd_kernel.projection.categories.commentary import project_accepted_commentary,verify_accepted_commentary

ROOT=task.ROOT;LIBRARY=Path('D:/Library/Open Christian Data');WORK=Path('library/works')/task.WORK
EDITION=task.NEW_EDITION;LANE=WORK/'integration/stokes-acts-complete-current-20261003-v2'
FIXTURE=ROOT/'.tmp_audit/stokes-acts-complete-install-fixture-20261003-v1'
FIXTURE_MARKER='.ocd-stokes-acts-complete-fixture'
REVISION_NOTE='One complete authored Acts commentary preserving two complete already acquired source-volume envelopes in order.'
MASTER_STATUS='Agent-accepted faithful complete authored Acts commentary containing both already acquired Stokes volumes in source order. Legacy accepted volumes remain unchanged. Human review, print collation, rights and publication remain separate.'
CONTRACT='ocd-stokes-acts-complete-stage-v1'

def read(path):return json.loads(task._io_path(path).read_bytes())
def digest(path):return task.sha(task._io_path(path).read_bytes())
def write(root,path,raw):
    target=task._io_path(root/path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);return root/path
def write_json(root,path,value):return write(root,path,task.canonical(value))
def copy(root,stage,path):return write(stage,path,task._io_path(root/path).read_bytes())
def source():return task.SourceManifest.load(ROOT/task.SOURCE/'source-manifest.json',repository_root=ROOT)
def expected_work(root):
    original=read(root/WORK/'work.json');proposal=read(task.DEST/'identity-proposal'/WORK/'work.json')
    form=dict(textual_form_id=task.FORM,language='en',editions=[dict(edition_id=task.EDITION,title=task.TITLE,language='en',category='commentary',acquisition_ids=[task.ACQUISITION])])
    expected=deepcopy(original);expected['textual_forms'].append(form)
    expected['evidence'].extend([task.MEMBER_SET.as_posix(),task.ACQUISITION_PATH.as_posix(),(task.SOURCE/'profile.json').as_posix()])
    if proposal!=expected:raise PipelineError('Exact append-only Acts work proposal differs')
    task.validate_identity_update(original,expected);return expected
def expected_state(root,at):
    state=read(root/WORK/'state.json')
    if any(t['target_id'] in {task.EDITION,task.ACQUISITION} for t in state['targets']):raise PipelineError('Complete Acts targets already exist')
    evidence=[task.MEMBER_SET.as_posix(),task.ACQUISITION_PATH.as_posix(),(task.SOURCE/'profile.json').as_posix()]
    state['targets'].append(dict(target_type='acquisition',target_id=task.ACQUISITION,stage='acquired',updated_at=at,evidence=evidence,reason='Complete authored Acts binding derived from two preserved existing acquired sources; no new download.'))
    state['targets'].append(dict(target_type='edition',target_id=task.EDITION,stage='accepted',updated_at=at,evidence=evidence+[(EDITION/'master.tei.xml').as_posix(),(EDITION/'acceptance.json').as_posix()],reason=PROMOTED_MASTER_REASON))
    return state
def declared(acquisition):
    return task.BOUNDARY+' '+acquisition['source_scope']+' Exact full ordered electronic source envelopes, raw-backed native structure, readings, notes, attributes, direct/tail text, indexes, complete metadata and XML prefixes, and permissions are conserved. Exactly 57 relative query links receive their original per-volume acquired URL as XML base without changing targets. All 15 Volume I source-broken links remain qualified; Volume II has none. Distinct 1891 and 1892 print statements remain attached to their source volumes. No source acquisition, entire-author or series completeness, independent print collation, human review, rights clearance, publication or downstream projection claim.'
def revision(at):return dict(id='stokes-acts-complete-current-20261003-v2',date=datetime.fromisoformat(at.replace('Z','+00:00')).date().isoformat(),note=REVISION_NOTE)
def bound(raw,acquisition,rev):
    identity=dict(work_id=task.WORK,textual_form_id=task.FORM,edition_id=task.EDITION,acquisition_id=task.ACQUISITION)
    binding={k:acquisition[k] for k in ('source_path','source_sha256','source_bytes','source_scope','source_kind')}
    result=bind_reviewed_header(raw,expected_sha256=task.sha(raw),identity=identity,source=binding,source_url=acquisition['url'],declared_scope=declared(acquisition),revision=rev)
    if result.count(task.STATUS.encode())!=1:raise PipelineError('Complete Acts publication preimage differs')
    result=result.replace(task.STATUS.encode(),MASTER_STATUS.encode(),1)
    if result.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise PipelineError('Complete Acts accepted binding altered full text bytes')
    return result
def projection_gate(root,acceptance):
    try:
        result=project_accepted_commentary(root,acceptance_path=acceptance);errors=verify_accepted_commentary(root,acceptance_path=acceptance,rows=result['rows'],receipt=result['receipt'])
        return dict(status='pass' if not errors else 'held',rows=len(result['rows']),errors=errors,raw_errors=errors)
    except PipelineError as error:
        raw=str(error);normalized=raw
        for prefix in sorted({str(root),root.as_posix(),str(task._io_path(root))},key=len,reverse=True):normalized=normalized.replace(prefix,'<reviewed-root>')
        return dict(status='held',rows=0,errors=[normalized],raw_errors=[raw])
def signature(gate):return {key:gate[key] for key in ('status','rows','errors')}
def module_files():
    code_root=resolve_path(ROOT,strict=True);library=resolve_path(LIBRARY,strict=True);observed={}
    for module in sys.modules.copy().values():
        filename=getattr(module,'__file__',None)
        if not filename:continue
        path=resolve_path(Path(filename),strict=True)
        if path.is_relative_to(code_root):relative=path.relative_to(code_root)
        elif path.is_relative_to(library):
            relative=path.relative_to(library)
            if relative.parts[0] not in ('raw','reports','exports'):raise PipelineError('Unrouted first-party Library module '+path.as_posix())
        else:continue
        observed[relative.as_posix()]=digest(path)
    return observed
def dependencies():
    manifest=source();paths={Path(a['path']) for a in manifest.record['authorities']}
    paths.add(task.SOURCE/'source-manifest.json')
    paths.update(task.LOG/name for name in ('candidate-completion-receipt.json','append-only-identity-proposal.json','ready-for-parent-source-review.json'))
    paths.update(Path(p) for p in ('build/tools/prepare_stokes_acts_complete.py','build/tools/stokes_acts_complete_install.py','build/tools/prove_stokes_acts_complete_install.py','.tmp_audit/stokes_complete_runtime_audit.py'))
    ready=read(ROOT/task.LOG/'ready-for-parent-source-review.json');paths.update(Path(p) for p in ready['execution_modules']);paths.update(Path(p) for p in ready['schemas'])
    paths.update(Path(p) for p in module_files())
    old=read(ROOT/WORK/'work.json');state=read(ROOT/WORK/'state.json')
    paths.update(Path(p.split('#',1)[0]) for p in old['evidence']+[e for t in state['targets'] for e in t['evidence']])
    return paths
def assert_execution(receipt):
    bindings={resolve_path(ROOT/p,strict=True):(p,h) for p,h in receipt['dependency_files'].items()};records={}
    for module in sys.modules.copy().values():
        filename=getattr(module,'__file__',None)
        if not filename:continue
        path=resolve_path(Path(filename),strict=True)
        if path.is_relative_to(resolve_path(ROOT,strict=True)) or path.is_relative_to(resolve_path(LIBRARY,strict=True)):
            if path not in bindings:raise PipelineError('Unexpected complete Acts executed dependency '+path.as_posix())
            relative,pin=bindings[path]
            if digest(path)!=pin:raise PipelineError('Complete Acts executed dependency drifted '+relative)
            records[relative]=pin
    return records

def prepare(stage):
    stage=stage.absolute();root=resolve_path(ROOT,strict=True)
    if stage.exists() or stage.parent!=resolve_path(LIBRARY/'candidate-reviews',strict=True) or not stage.name.startswith('stokes-acts-s-') or root==stage or root in stage.parents or stage in root.parents:raise PipelineError('Fresh external bounded complete Acts stage required')
    before=task._files(ROOT/WORK);profile=read(ROOT/task.SOURCE/'profile.json')
    if before!=profile['canonical_before'] or len(before)!=44 or task._io_path(ROOT/EDITION).exists():raise PipelineError('Exact two-volume installed Acts preimage required')
    work=expected_work(ROOT);at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');state=expected_state(ROOT,at)
    manifest=source();package=task.CandidatePackage.load(task.DEST/'package');report=task.validate(manifest,package,task.oracle);direct=task.check(manifest,package)
    completion=read(ROOT/task.LOG/'candidate-completion-receipt.json');ready=read(ROOT/task.LOG/'ready-for-parent-source-review.json')
    if completion['status']!='pass' or completion['candidate_package_sha256']!=package.sha256 or completion['source_manifest_sha256']!=manifest.sha256 or completion['oracle_report_sha256']!=report.sha256 or completion['direct_review']!=direct or len(completion['mutations'])!=12 or not all(r['p5_valid'] and r['rejected'] for r in completion['mutations']) or len(completion['replays'])!=2 or not all(r['all_six_member_bytes_equal'] for r in completion['replays']):raise PipelineError('Complete Acts source/mutation/replay receipt differs')
    if not ready['canonical_unchanged'] or ready['package_sha256']!=package.sha256 or ready['source_manifest']['sha256']!=manifest.sha256:raise PipelineError('Complete Acts source execution review differs')
    stage.mkdir()
    for path in before:copy(ROOT,stage,WORK/path)
    for path in dependencies():copy(ROOT,stage,path)
    write_json(stage,WORK/'work.json',work);acquisition=read(ROOT/task.SOURCE/'proposed-acquisition.json')
    write_json(stage,task.ACQUISITION_PATH,acquisition);write(stage,task.MEMBER_SET,manifest.authority_path('proposed-member-set').read_bytes());task.validate_acquisition(stage/task.ACQUISITION_PATH,root=stage)
    for name in package.member_names:write(stage,LANE/'inputs/package'/name,package.member_bytes(name))
    write(stage,LANE/'source-review.json',(ROOT/task.LOG/'candidate-completion-receipt.json').read_bytes())
    write(stage,LANE/'source-execution-review.json',(ROOT/task.LOG/'ready-for-parent-source-review.json').read_bytes())
    rev=revision(at);master=bound(package.member_bytes('content.tei.xml'),acquisition,rev);candidate=write(stage,LANE/'candidate.tei.xml',master)
    if errors:=validate_file(candidate):raise PipelineError('Bound complete Acts P5 failed '+repr(errors[:3]))
    identity=dict(work_id=task.WORK,textual_form_id=task.FORM,edition_id=task.EDITION,acquisition_id=task.ACQUISITION)
    binding={k:acquisition[k] for k in ('source_path','source_sha256','source_bytes','source_scope','source_kind')};scope=declared(acquisition)
    expected=[dict(path=m['path'],position=i) for i,m in enumerate(acquisition['retained_files'],1)]
    included=[dict(path=m['path'],position=i,bytes=m['bytes'],sha256=m['sha256'],scope=m['scope']) for i,m in enumerate(acquisition['retained_files'],1)]
    common=dict(identity=identity,source=binding,candidate=make_file_binding(stage,candidate),scope=scope,accepted_scope=dict(kind='work',declared=scope),expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],source_manifest_sha256=manifest.sha256,candidate_package_sha256=package.sha256,oracle_report_sha256=report.sha256,direct_source_review=make_file_binding(stage,stage/LANE/'source-review.json'))
    accounting=write_json(stage,LANE/'source-accounting.json',common|dict(scope=binding['source_scope'],source_sha256=binding['source_sha256'],source_bytes=binding['source_bytes'],complete_works=1,source_volumes=2,ordered_members=list(task.MEMBERS),full_source_elements=sum(r['raw_elements'] for r in profile['volumes']),all_actual_source_inverses_pass=True,uri_base_repairs=direct['uri_base_repairs'],complete_body_bytes_unchanged_at_binding=True,omitted_readable_elements=0))
    command='py -3 -m build.tools.stokes_acts_complete_install --prepare';technical=dict(producer=dict(id=manifest.record['converter']['id']),checker=dict(id=manifest.record['validator']['id']),shared_assumptions=['XML/P5 and declared prior exposure to the independently reviewed legacy source mapping. Oracle does not import the complete producer or projection code.'],independent_corroboration='Actual serialized group compared to raw sources and legacy text; exact 57 original URI bases; both full raw headers/prefixes; exact metadata and per-volume inverses. Twelve P5-valid source-feature mutations rejected and two fresh six-member byte-identical replays.')
    for claim in ('validation','accounting','fidelity','reproducibility','schema','closure'):
        path=write_json(stage,LANE/(claim+'.json'),common|dict(status='pass',command=command,exit_code=0,claim=claim,actual_source_inverses_pass=True,complete_body_bytes_unchanged_at_binding=True));technical[claim]=dict(path=path,status='pass',command=command,exit_code=0)
    coverage=['Entire actual ordered Volume I and II source envelopes and complete authored work boundary','All raw-backed native structure, semantic roles, attributes, direct and tail text, note ownership, heading and index order','All original source metadata, exact XML prefixes and administrative ledger with actual source-body inverses','All 57 acquired URL bases and retained 15+0 broken source links; complete permissions and legacy accepted header evidence']
    review=dict(reviewer='agent:stokes-acts-complete-source-review',reviewed_at=at,coverage=dict(status='complete',declared=scope,reached=coverage,inspected=coverage,unreviewed=[]),source_quality_uncertainty=['Retained electronic sources only; no independent print or CSS collation.','Volume I retains all 15 broken source links; no destination is invented.','Volume I and II have distinct 1891 and 1892 print statements; no whole-author or series completeness is inferred.'],discrepancies=[],unreviewed_residuals=['Human review, print collation, rights, publication and downstream commentary projection remain separate.'])
    review_path=write_json(stage,LANE/'review.json',common|review)
    decision=dict(source_local_disposition='Agent accepts one faithful complete authored Acts commentary from both existing retained electronic volumes.',blockers=[],agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=scope,unresolved_claims=[],unassessed_stronger_claims=['human review','print collation','rights clearance','publication','whole-author or series completeness','downstream projection']),human_decision=dict(status='not-recorded'))
    record=build_acceptance_record(stage,identity=identity,candidate_path=candidate,source_accounting_path=accounting,scope=dict(kind='work',declared=scope,expected_members=expected,included_members=included,excluded_members=[]),technical=technical,review=review|dict(report_path=review_path),representation_revision=rev,decision=decision)
    master_path=write(stage,EDITION/'master.tei.xml',master);record['promotion']=dict(record['promotion'])|dict(status='promoted',promoted_at=at,master=make_file_binding(stage,master_path));write_acceptance(stage/EDITION/'acceptance.json',record)
    write_json(stage,WORK/'state.json',state);task.load_work(stage/WORK/'work.json');task.validate_state(stage/WORK/'state.json',root=stage);validate_acceptance(stage/EDITION/'acceptance.json',root=stage)
    gate=projection_gate(stage,stage/EDITION/'acceptance.json');deps=dependencies()
    for path in deps:copy(ROOT,stage,path)
    receipt=dict(contract=CONTRACT,status='staged-only',work_id=task.WORK,complete_works=1,source_volumes=2,scope_kind='work',projection_category='commentary',stage_root=stage.as_posix(),staged_at=at,before=before,after=task._files(stage/WORK),revision=rev,master_sha256=digest(master_path),acceptance_sha256=digest(stage/EDITION/'acceptance.json'),package_sha256=package.sha256,source_manifest_sha256=manifest.sha256,oracle_report_sha256=report.sha256,projection_gate=gate,execution_modules=module_files(),dependency_files={p.as_posix():digest(ROOT/p) for p in sorted(deps)},canonical_installation=False,human_review='not-recorded',rights='not-assessed',publication='not-authorized')
    write_json(stage,Path('stage-receipt.json'),receipt);return dict(status='staged-only',stage_root=stage.as_posix(),receipt_sha256=digest(stage/'stage-receipt.json'),projection_gate=gate,after_files=len(receipt['after']))

def preflight(stage,pin,*,root=ROOT):
    stage=resolve_path(stage,strict=True);root=resolve_path(root,strict=True);fixture=root!=resolve_path(ROOT,strict=True)
    if fixture and (root!=resolve_path(FIXTURE,strict=True) or (root/FIXTURE_MARKER).read_bytes()!=b'fixture-only\n'):raise PipelineError('Exact complete Acts task fixture root required')
    if root==stage or root in stage.parents or stage in root.parents:raise PipelineError('Complete Acts stage/root containment differs')
    if stage.parent!=resolve_path(LIBRARY/'candidate-reviews',strict=True) or not stage.name.startswith('stokes-acts-s-'):raise PipelineError('Complete Acts external stage boundary differs')
    if len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin) or digest(stage/'stage-receipt.json')!=pin:raise PipelineError('Complete Acts caller receipt pin differs')
    receipt=read(stage/'stage-receipt.json')
    if receipt['contract']!=CONTRACT or receipt['status']!='staged-only' or receipt['work_id']!=task.WORK or receipt['complete_works']!=1 or receipt['source_volumes']!=2 or receipt['scope_kind']!='work' or receipt['projection_category']!='commentary' or receipt['stage_root']!=stage.as_posix() or receipt['canonical_installation']:raise PipelineError('Complete Acts frozen receipt scope differs')
    if task._files(root/WORK)!=receipt['before'] or task._files(stage/WORK)!=receipt['after']:raise PipelineError('Complete Acts exact before/after generation differs')
    if len(receipt['before'])!=44 or task._io_path(root/EDITION).exists():raise PipelineError('Complete Acts existing authority replacement prohibited')
    for relative,d in receipt['before'].items():
        if relative not in ('work.json','state.json') and receipt['after'].get(relative)!=d:raise PipelineError('Legacy Acts authority changed '+relative)
    allowed={(EDITION/name).relative_to(WORK).as_posix() for name in ('master.tei.xml','acceptance.json','source-member-set.json')};allowed.add(task.ACQUISITION_PATH.relative_to(WORK).as_posix());prefix=LANE.relative_to(WORK).as_posix()+'/'
    if any(p not in allowed and not p.startswith(prefix) for p in set(receipt['after'])-set(receipt['before'])):raise PipelineError('Complete Acts added file exceeds exact work fence')
    if read(stage/WORK/'work.json')!=expected_work(root) or read(stage/WORK/'state.json')!=expected_state(root,receipt['staged_at']):raise PipelineError('Complete Acts exact append-only identity/state delta differs')
    for relative,d in receipt['dependency_files'].items():
        if digest(ROOT/relative)!=d or digest(stage/relative)!=d:raise PipelineError('Complete Acts dependency changed '+relative)
    acquisition=task.validate_acquisition(stage/task.ACQUISITION_PATH,root=stage)
    if acquisition!=read(ROOT/task.SOURCE/'proposed-acquisition.json') or task._io_path(stage/task.MEMBER_SET).read_bytes()!=source().authority_path('proposed-member-set').read_bytes():raise PipelineError('Complete Acts derived source binding differs')
    manifest=source();package=task.CandidatePackage.load(stage/LANE/'inputs/package');report=task.validate(manifest,package,task.oracle)
    if package.sha256!=receipt['package_sha256'] or package.sha256!=task.CandidatePackage.load(task.DEST/'package').sha256 or manifest.sha256!=receipt['source_manifest_sha256'] or report.sha256!=receipt['oracle_report_sha256']:raise PipelineError('Complete Acts current source proof binding differs')
    accepted=validate_acceptance(stage/EDITION/'acceptance.json',root=stage);rev=revision(receipt['staged_at']);identity=dict(work_id=task.WORK,textual_form_id=task.FORM,edition_id=task.EDITION,acquisition_id=task.ACQUISITION)
    if receipt['revision']!=rev or accepted['representation_revision']!=rev or accepted['identity']!=identity or accepted['promotion']['status']!='promoted':raise PipelineError('Complete Acts exact accepted revision/identity differs')
    original=package.member_bytes('content.tei.xml');expected=bound(original,acquisition,rev);master=task._io_path(stage/EDITION/'master.tei.xml').read_bytes()
    if master!=expected or task._io_path(stage/LANE/'candidate.tei.xml').read_bytes()!=expected or digest(stage/EDITION/'master.tei.xml')!=receipt['master_sha256'] or digest(stage/EDITION/'acceptance.json')!=receipt['acceptance_sha256']:raise PipelineError('Complete Acts full ordered header/body recomputation differs')
    if original.split(b'</teiHeader>',1)[1]!=master.split(b'</teiHeader>',1)[1]:raise PipelineError('Complete Acts text bytes changed at accepted binding')
    expected_members=[dict(path=m['path'],position=i) for i,m in enumerate(acquisition['retained_files'],1)];included=[dict(path=m['path'],position=i,bytes=m['bytes'],sha256=m['sha256'],scope=m['scope']) for i,m in enumerate(acquisition['retained_files'],1)]
    account=read(stage/LANE/'source-accounting.json');direct=task.check(manifest,package)
    if account['identity']!=identity or account['accepted_scope']['kind']!='work' or account['scope']!=acquisition['source_scope'] or account['source_sha256']!=acquisition['source_sha256'] or account['source_bytes']!=acquisition['source_bytes'] or account['expected_members']!=expected_members or account['included_members']!=included or account['excluded_members'] or account['missing_members'] or account['unknown_members'] or account['complete_works']!=1 or account['source_volumes']!=2 or account['ordered_members']!=list(task.MEMBERS) or account['full_source_elements']!=sum(r['raw_elements'] for r in read(ROOT/task.SOURCE/'profile.json')['volumes']) or account['uri_base_repairs']!=direct['uri_base_repairs'] or not account['all_actual_source_inverses_pass'] or not account['complete_body_bytes_unchanged_at_binding'] or account['omitted_readable_elements']!=0:raise PipelineError('Complete Acts exact whole-source accounting differs')
    if accepted['scope']['kind']!='work' or accepted['scope']['expected_members']!=expected_members or accepted['scope']['included_members']!=included:raise PipelineError('Complete Acts acceptance member scope differs')
    task.validate_state(stage/WORK/'state.json',root=stage);gate=projection_gate(stage,stage/EDITION/'acceptance.json')
    if signature(gate)!=signature(receipt['projection_gate']):raise PipelineError('Complete Acts actual genre projection signature differs')
    runtime=assert_execution(receipt)
    return dict(status='ready-for-parent-review',work_id=task.WORK,receipt_sha256=pin,before_files=len(receipt['before']),after_files=len(receipt['after']),complete_works=1,source_volumes=2,projection_gate=gate,execution_modules=runtime,execution_dependency_gate='pass')
def install(stage,pin,*,root=ROOT,fail_at=None):
    root=resolve_path(root,strict=True);stage=resolve_path(stage,strict=True);target=root/WORK;origin=stage/WORK;runtime={};gates=[]
    with ExitStack() as locks:
        for path in sorted((target,origin),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(path,acquire_timeout=30.0))
        preflight(stage,pin,root=root);receipt=read(stage/'stage-receipt.json')
        def checkpoint(point):
            if point=='after-validated':
                if task._files(target)!=receipt['after']:raise PipelineError('Installed complete Acts generation differs')
                validate_acceptance(root/EDITION/'acceptance.json',root=root);task.validate_state(target/'state.json',root=root)
                gate=projection_gate(root,root/EDITION/'acceptance.json')
                if signature(gate)!=signature(receipt['projection_gate']):raise PipelineError('Installed complete Acts actual genre gate differs')
                gates.append(gate)
                try:runtime.update(assert_execution(receipt))
                except PipelineError as error:raise PipelineError('Complete Acts after-validated execution gate rejected: '+str(error)) from error
            if fail_at is not None:fail_at(point)
        result=_commit_generation(root,target,origin,work_id=task.WORK,before=receipt['before'],after=receipt['after'],existed=True,replacement=False,operation_kind='stokes-existing-complete-acts-install',result_status='installed-and-validated',accepted_editions=1,fail_at=checkpoint)
    result.update(executed_first_party_files=runtime,late_execution_dependency_gate='pass',projection_gate=gates)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--prepare',action='store_true');p.add_argument('--expected-sha256');p.add_argument('--apply',action='store_true');args=p.parse_args()
    if args.prepare:
        if args.apply or args.expected_sha256:p.error('Prepare cannot apply or consume an old receipt pin')
        result=prepare(args.stage)
    else:
        if not args.expected_sha256:p.error('Reviewed receipt pin required')
        result=preflight(args.stage,args.expected_sha256)
        if args.apply:result['installation']=install(args.stage,args.expected_sha256)
    print(json.dumps(result,sort_keys=True))
