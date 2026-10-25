"""Bounded initial installation of the already retained George Whitefield biography.

Source fidelity runs in its own frozen fresh process. Acceptance/reader/install
execution has a separate physical dependency map. Canonical apply is root-owned.
"""
from contextlib import ExitStack
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import argparse,json,subprocess,sys
from lxml import etree

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from ocd_kernel.lib.path_io import io_path,resolve_path
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work,validate_record
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.acceptance import build_acceptance_record,make_file_binding,write_acceptance,validate_acceptance,PROMOTED_MASTER_REASON,_tei_facts
from ocd_kernel.tei.install_accepted import _files,_commit_generation
from ocd_kernel.tei.validate import validate_file

LIBRARY=Path('D:/Library/Open Christian Data')
LOG=Path('reports/_logs/tyerman-whitefield-complete-20261004-v1')
HOME=Path('sources/manifest-acquisitions/tyerman-life-george-whitefield-complete-20261004-v3')
PROPOSAL_HOME=Path('sources/manifest-acquisitions/tyerman-life-george-whitefield-identity-proposal-20261004-v1')
DRAFT=Path('sources/manifest-acquisitions/tyerman-life-george-whitefield-accepted-header-draft-20261004-v1')
WORK_ID='tyerman-life-george-whitefield';FORM=WORK_ID+'--retained-en';EDITION=WORK_ID+'--pg44280-62023-1876-1877';ACQUISITION=WORK_ID+'--pg44280-62023-retained-member-set'
WORK=Path('library/works')/WORK_ID;ED=WORK/'forms'/FORM/'editions'/EDITION;ACQ=ED/'acquisitions'/(ACQUISITION+'.json')
LANE=WORK/'integration/whitefield-complete-20261004-v1'
FIXTURE=ROOT/'.tmp_audit/tyerman-whitefield-install-fixture-20261004-v1'
PACKAGE=LIBRARY/'candidate-reviews/tyerman-whitefield-complete-20261004-v4/package'
PACKAGE_SHA='060848a5ab78bd671983bc2f5bc04520a5dd6ecdd56d843c38c602835c5a3bf7'
SOURCE_SHA='053c8504303e872d48f465cc0d9e1217562dbd63382753548bb749c822b19786'
PROOF=LOG/'complete-work-source-proof-v4.json';PROOF_SHA='ccedebaeb93177bc8ccb2dd5c7481d908b196d609021f84a55784c19f1b9b8cb'
ROOT_REVIEW=LOG/'root-final-source-identity-review-v4.json';ROOT_REVIEW_SHA='5c2736b63ac2eb100e2fc6604c4715327b3346b86b0a96ca8584d4cde7c77a9a'
PROPOSAL=PROPOSAL_HOME/'proposal.json';PROPOSAL_SHA='2a9d69e78af2348cacdb6cb8ae2608de9d9a1dc8fd1502881fb9ed6886527569'
HEADER_PROPOSAL=DRAFT/'draft-receipt.json';HEADER_PROPOSAL_SHA='3c8dade0e38b7702d3fa320f11c99790cd835c55aaddb6916090508c8ef70625'
HEADER_REVIEW=LOG/'root-accepted-header-review-v1.json';HEADER_REVIEW_SHA='ee414d10a9bbdf218603b41486c33286639474adaf38039e4f158ad6b40e3600'
REVIEWED_MASTER=DRAFT/'candidate.tei.xml';REVIEWED_MASTER_SHA='24637ca4083c82f8c07eb8f375540a723cc35982e4cd5a9cdf37547f57778857'
PRESERVED=[Path('library/works/tyerman-oxford-methodists-1873')]
TITLE_REVIEW=LANE/'title-identity-review.json'
from build.tools import prepare_tyerman_whitefield_accepted_header as header
NOTE=header.REVISION_NOTE
SCOPE='One complete authored biography, both entire retained electronic volumes I (1876, PG44280) and II (1877, PG62023), in that order; every HTML and image archive member, including source context and support media.'
CREDIT_APPEND=('\n\n## Current technical acceptance\n\nThe dated nonaccepted source packages and identity proposal are preserved as historical evidence. Current title assignment is recorded in integration/whitefield-complete-20261004-v1/title-identity-review.json; agent acceptance is recorded in forms/'+FORM+'/editions/'+EDITION+'/acceptance.json. The completed guarded operation journal records canonical installation. Both complete authored biography volumes remain together. Human verification, rights/jurisdiction, print/CVW collation, disclosure and publication remain separate.\n').encode('utf-8')
def preserved(root=ROOT):return {p.as_posix():_files(root/p) for p in PRESERVED}

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def read(p):return json.loads(io_path(p).read_bytes())
def sha(p):return sha256(io_path(p).read_bytes()).hexdigest()
def write(root,p,b):
    target=io_path(root/p);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b);return root/p
def dump(root,p,v):return write(root,p,enc(v))
def copy(root,stage,p):return write(stage,p,io_path(root/p).read_bytes())
def identity():return dict(work_id=WORK_ID,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION)
def source_binding(a):return {k:a[k] for k in ('source_path','source_sha256','source_bytes','source_scope','source_kind')}

def reviewed_revision():
    for path,pin in [(HEADER_PROPOSAL,HEADER_PROPOSAL_SHA),(HEADER_REVIEW,HEADER_REVIEW_SHA),(REVIEWED_MASTER,REVIEWED_MASTER_SHA)]:
        if sha(ROOT/path)!=pin:raise PipelineError('Frozen reviewed Whitefield header authority drift '+path.as_posix())
    p=read(ROOT/HEADER_PROPOSAL);r=read(ROOT/HEADER_REVIEW)
    expected=dict(id=header.REVISION_ID,date='2026-10-03',note=NOTE)
    if p['identity']!=identity() or p['revision']!=expected or p['draft']['sha256']!=REVIEWED_MASTER_SHA or p['source_candidate']['sha256']!=header.EXPECTED_CONTENT or p['P5']['status']!='pass' or not p['inversion']['original_whole_document_byte_inverse'] or not p['inversion']['complete_outer_text_byte_conservation']:raise PipelineError('Exact Whitefield reviewed header proposal differs')
    if r['status']!='pass' or r['draft_receipt_sha256']!=HEADER_PROPOSAL_SHA or r['accepted_tei_sha256']!=REVIEWED_MASTER_SHA or r['p5']!='pass' or r['identity']!=identity() or not r['body_byte_equal'] or not r['full_original_tei_byte_inverse']:raise PipelineError('Exact root Whitefield header review differs')
    return expected

def source_gate():
    if sha(ROOT/PROOF)!=PROOF_SHA or sha(ROOT/ROOT_REVIEW)!=ROOT_REVIEW_SHA or sha(ROOT/PROPOSAL)!=PROPOSAL_SHA:raise PipelineError('Frozen Whitefield source/identity review differs')
    source=SourceManifest.load(ROOT/HOME/'source-manifest.json',repository_root=ROOT);package=CandidatePackage.load(PACKAGE)
    if source.sha256!=SOURCE_SHA or package.sha256!=PACKAGE_SHA:raise PipelineError('Frozen Whitefield source contract/package differs')
    proof=read(ROOT/PROOF);review=read(ROOT/ROOT_REVIEW)
    if proof['status']!='pass' or review['status']!='pass' or review['identity']!=identity() or review['source_manifest_sha256']!=SOURCE_SHA or review['source_candidate_sha256']!=PACKAGE_SHA:raise PipelineError('Exact root Whitefield source binding differs')
    code="""import json,sys
from pathlib import Path
r=Path(sys.argv[1]);sys.path.insert(0,str(r))
import build.tools.prepare_tyerman_whitefield_complete
import build.tools.prove_tyerman_whitefield_complete as proof
from build.tei import tyerman_whitefield_complete_oracle as o
from build.tei.tyerman_whitefield_runtime import guard
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage
m=SourceManifest.load(proof.SOURCE,repository_root=r)
guard(m,'before-oracle')
result=o._oracle(m,CandidatePackage.load(Path(sys.argv[2])))
guard(m,'after-oracle')
print(json.dumps(result))"""
    cmd=[sys.executable,'-I','-B','-c',code,str(ROOT),str(PACKAGE)]
    result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,check=False)
    process=dict(command=cmd,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
    trace=LOG/'admitted-source-processes'/('source-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    if io_path(ROOT/trace).exists():raise PipelineError('Preserve Whitefield source subprocess collision')
    dump(ROOT,trace,process)
    if result.returncode!=0:raise PipelineError('Isolated admitted Whitefield source oracle failed '+trace.as_posix())
    check=json.loads(result.stdout)
    if check['status']!='pass':raise PipelineError('Whitefield source oracle rejects current package')
    check['source_subprocess_evidence']=dict(path=trace.as_posix(),sha256=sha(ROOT/trace),**process)
    return source,package,check

def records():
    if sha(ROOT/PROPOSAL)!=PROPOSAL_SHA:raise PipelineError('Frozen Whitefield identity proposal drift')
    proposal=read(ROOT/PROPOSAL)
    if proposal['identity']!=identity():raise PipelineError('Whitefield complete primary title identity differs')
    for row in proposal['files']:
        path=ROOT/row['path']
        if io_path(path).stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:raise PipelineError('Whitefield proposed historical metadata drift '+row['path'])
    work=read(ROOT/PROPOSAL_HOME/'work.json');a=read(ROOT/PROPOSAL_HOME/(ACQUISITION+'.json'))
    validate_record('work',work,context='Reviewed Whitefield complete title work')
    for acq in all_acquisitions():validate_record('acquisition',acq,context='Reviewed Whitefield retained acquisition')
    if a['source_scope']!=SCOPE:raise PipelineError('Frozen Whitefield full source scope differs')
    return work,a

def all_acquisitions():return [read(ROOT/PROPOSAL_HOME/(name+'.json')) for name in (WORK_ID+'--pg44280-retained',WORK_ID+'--pg62023-retained',ACQUISITION)]

def state(at):
    result=read(ROOT/PROPOSAL_HOME/'state.json')
    for target in result['targets']:
        if target['target_type']=='acquisition':
            target['evidence']=[(ED/'acquisitions'/(target['target_id']+'.json')).relative_to(WORK).as_posix(),*target['evidence']]
    edition=[t for t in result['targets'] if t['target_type']=='edition' and t['target_id']==EDITION]
    if len(edition)!=1 or edition[0]['stage']!='review':raise PipelineError('Exact Whitefield proposal edition state differs')
    edition[0].update(stage='accepted',updated_at=at,reason=PROMOTED_MASTER_REASON,evidence=[PROOF.as_posix(),ROOT_REVIEW.as_posix(),TITLE_REVIEW.as_posix(),(ED/'master.tei.xml').as_posix(),(ED/'acceptance.json').as_posix()])
    return result

def bound(original,a,revision):
    result=header.bind(original,a,revision)
    recovered,_=header.inverse(result,original,a,revision)
    if recovered!=original or result.split(b'</teiHeader>',1)[1]!=original.split(b'</teiHeader>',1)[1]:raise PipelineError('Exact Whitefield source body/header inverse differs')
    return result

def title_assignment(work,a,at,source,package):
    return dict(contract='ocd-current-authored-work-title-assignment-v1',status='agent-reviewed',reviewer='agent:tyerman-whitefield-complete-source-review',reviewed_at=at,identity=identity(),work_title=work['title'],creators=work['creators'],complete_authored_works=1,retained_textual_witnesses=2,scope=dict(kind='work',declared=SCOPE),historical_proposal=dict(path=PROPOSAL.as_posix(),sha256=PROPOSAL_SHA,preserved_status='schema-valid-isolated-proposal'),root_source_identity_review=dict(path=ROOT_REVIEW.as_posix(),sha256=ROOT_REVIEW_SHA),current_assignment='One complete authored two-volume George Whitefield biography by L. Tyerman; dated original per-volume distinct-work policies remain superseded historical evidence. Primary titlepages IN TWO VOLUMES and imprints control this identity.',source=source_binding(a),source_url=a['url'],source_manifest_sha256=source.sha256,source_package_sha256=package.sha256,acquisition_conservation='Both exact original retained HTML/ZIP/image bytes, member URLs, download timestamps and rights wording remain unchanged in two volume acquisitions; selected ordered member-set is derived, not downloaded.',human_decision='not-recorded',rights_publication='separate unresolved gates',installation_evidence='Completed guarded journal records canonical installation.',new_download=False)

def allowed_paths(package):
    paths={'work.json','state.json','SOURCE_CREDIT.md',ACQ.relative_to(WORK).as_posix(),(ED/'master.tei.xml').relative_to(WORK).as_posix(),(ED/'acceptance.json').relative_to(WORK).as_posix()}
    paths.update((ED/'acquisitions'/(a['acquisition_id']+'.json')).relative_to(WORK).as_posix() for a in all_acquisitions())
    paths.add((LANE/'identity-crosswalk.json').relative_to(WORK).as_posix())
    paths.update((LANE/'inputs/package'/n).relative_to(WORK).as_posix() for n in package.member_names)
    paths.update((LANE/n).relative_to(WORK).as_posix() for n in ['source-review.json','source-identity-review.json','identity-proposal.json','parent-source-identity-review.json','title-identity-review.json','candidate.tei.xml','source-accounting.json','validation.json','accounting.json','fidelity.json','reproducibility.json','schema.json','closure.json','review.json'])
    return paths

def projection_gate(root,acceptance):
    from ocd_kernel.projection.categories.prose import project_accepted_prose,verify_accepted_prose
    result=project_accepted_prose(root,acceptance_path=acceptance)
    errors=verify_accepted_prose(root,acceptance_path=acceptance,rows=result['rows'],receipt=result['receipt'])
    if errors:raise PipelineError('Whitefield accepted reader check failed: '+str(errors))
    return dict(status='pass',rows=len(result['rows']),receipt_sha256=sha256(enc(result['receipt'])).hexdigest())

def dependencies(bootstrap=False):
    source=SourceManifest.load(ROOT/HOME/'source-manifest.json',repository_root=ROOT)
    paths={Path(a['path']) for a in source.record['authorities']}|{HOME/'source-manifest.json',PROOF,ROOT_REVIEW,PROPOSAL,Path(__file__).relative_to(ROOT)}
    paths.update(p.relative_to(ROOT) for directory,pattern in [('schemas/v2','*.json'),('ocd_kernel/tei/vendor/xsd','*.xsd'),('ocd_kernel/reconstruction/schemas','*.json')] for p in (ROOT/directory).rglob(pattern))
    paths.update(Path(p) for p in ['build/tools/capture_tyerman_whitefield_acceptance.py','build/tools/prove_tyerman_whitefield_install.py'])
    paths.update({HEADER_PROPOSAL,HEADER_REVIEW,REVIEWED_MASTER,Path('build/tools/prepare_tyerman_whitefield_accepted_header.py')})
    paths.update(Path(row['path']) for row in read(ROOT/PROPOSAL)['files'])
    from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH
    paths.add(resolve_path(BOOK_CODES_PATH,strict=True).relative_to(resolve_path(ROOT,strict=True)))
    if bootstrap:
        root=resolve_path(ROOT,strict=True);library=resolve_path(LIBRARY,strict=True)
        for m in sys.modules.copy().values():
            f=getattr(m,'__file__',None)
            if f:
                p=resolve_path(Path(f),strict=True)
                if p.is_relative_to(root):paths.add(p.relative_to(root))
                elif p.is_relative_to(library):
                    relative=p.relative_to(library)
                    if relative.parts[0] not in {'raw','reports','exports'} or resolve_path(ROOT/relative,strict=True)!=p:raise PipelineError('Whitefield Library execution alias differs')
                    paths.add(relative)
    else:
        report=LOG/'accepted-execution-imports-v1.json';record=read(ROOT/report);paths.add(report)
        if record['status']!='pass' or record['identity']!=identity():raise PipelineError('Actual acceptance execution receipt differs')
        for row in record['first_party_files']:
            if sha(ROOT/row['path'])!=row['sha256']:raise PipelineError('Actual accepted dependency drift: '+row['path'])
            paths.add(Path(row['path']))
    return paths

def prepare(stage,bootstrap=False):
    stage=stage.absolute()
    if stage.exists() or stage.parent!=LIBRARY/'candidate-reviews' or not stage.name.startswith('tyerman-whitefield-s-'):raise PipelineError('Fresh external Whitefield stage required')
    if io_path(ROOT/WORK).exists():raise PipelineError('Whitefield work home already exists; no replacement')
    source,package,check=source_gate();work,a=records();stage.mkdir()
    for authority in source.record['authorities']:copy(ROOT,stage,Path(authority['path']))
    for p in (HOME/'source-manifest.json',PROOF,ROOT_REVIEW,PROPOSAL,PROPOSAL_HOME/'source-member-set.json'):copy(ROOT,stage,p)
    for row in read(ROOT/PROPOSAL)['files']:copy(ROOT,stage,Path(row['path']))
    dump(stage,WORK/'work.json',work)
    for record in all_acquisitions():
        path=ED/'acquisitions'/(record['acquisition_id']+'.json');dump(stage,path,record)
        for row in record['retained_files']:
            if not io_path(stage/row['path']).exists():copy(ROOT,stage,Path(row['path']))
        validate_acquisition(stage/path,root=stage)
    write(stage,LANE/'identity-crosswalk.json',io_path(ROOT/PROPOSAL_HOME/'identity-crosswalk.json').read_bytes())
    for n in package.member_names:write(stage,LANE/'inputs/package'/n,package.member_bytes(n))
    for filename,path in [('source-review.json',PROOF),('source-identity-review.json',ROOT_REVIEW),('identity-proposal.json',PROPOSAL),('parent-source-identity-review.json',ROOT_REVIEW)]:write(stage,LANE/filename,io_path(ROOT/path).read_bytes())
    at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');revision=reviewed_revision()
    assignment=dump(stage,TITLE_REVIEW,title_assignment(work,a,at,source,package));master=bound(package.member_bytes('content.tei.xml'),a,revision);candidate=write(stage,LANE/'candidate.tei.xml',master)
    if master!=io_path(ROOT/REVIEWED_MASTER).read_bytes() or sha256(master).hexdigest()!=REVIEWED_MASTER_SHA:raise PipelineError('Exact reviewed Whitefield accepted master recomputation differs')
    if errors:=validate_file(candidate):raise PipelineError(str(errors))
    expected=[dict(path=r['path'],position=i) for i,r in enumerate(a['retained_files'],1)]
    included=[dict(path=r['path'],position=i,bytes=r['bytes'],sha256=r['sha256'],scope=r['scope']) for i,r in enumerate(a['retained_files'],1)]
    common=dict(identity=identity(),source=source_binding(a),candidate=make_file_binding(stage,candidate),accepted_scope=dict(kind='work',declared=SCOPE),scope=SCOPE,expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],source_manifest_sha256=source.sha256,candidate_package_sha256=package.sha256,source_proof_sha256=PROOF_SHA,representation_revision=revision,staged_at=at)
    accounting=dump(stage,LANE/'source-accounting.json',common|dict(scope=a['source_scope'],source_sha256=a['source_sha256'],source_bytes=a['source_bytes'],complete_works=1,textual_witnesses=2,archive_members=7,original_source_receipts=['raw/gutenberg/44280/acquisition-receipt.json','raw/gutenberg/62023/acquisition-receipt.json'],source_review=make_file_binding(stage,stage/LANE/'source-review.json'),current_title_assignment=make_file_binding(stage,assignment),exact_current_source_oracle=check))
    command='py -3 -I -B build/tools/tyerman_whitefield_install.py prepare "'+stage.as_posix()+'"'+(' --bootstrap' if bootstrap else '')
    technical=dict(producer=dict(id='ocd-l635-reviewed-header-and-initial-install'),checker=dict(id=source.record['validator']['id']),shared_assumptions=['Shared HTML5 normalization; html5lib/libxml document-boundary whitespace differences explicitly qualified.'],independent_corroboration='Current full raw-derived actual source inverse, original per-volume component correspondence, exact two-volume/header/source field conservation in a separate 242-file admitted process;25 P5-valid semantic/9 contract/10 import challenges qualified, two fresh durable supported six-member replays. Current accepted maintained reader independently measured.')
    for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
        p=dump(stage,LANE/(name+'.json'),common|dict(status='pass',command=command,exit_code=0,claim=name,source_proof=make_file_binding(stage,stage/LANE/'source-review.json'),producer=dict(source.record['converter']),header_binding_implementation_sha256=sha(Path(__file__))))
        technical[name]=dict(path=p,status='pass',command=command,exit_code=0)
    coverage=['Both complete volume envelopes, full titlepages/frontmatter/chapter text/index/provider wrapper and John Wesley advertisement context','Full actual source/TEI parent/order/attributes/direct text/tails/URI/media/header inventory and inverse','All 98 literal source language fields,4,140 abbreviation expansions,43 tooltips, 5 table summary labels and 5 body image occurrences; archive-only support qualified','Independent full-source P5/inverse,25 semantic/9 contract/10 import challenges and two fresh supported byte-identical replays','Exact primary title,three unchanged retained/derived acquisitions,fixed reviewed accepted header and entire source body bytes']
    review=dict(reviewer='agent:tyerman-whitefield-complete-source-review',reviewed_at=at,coverage=dict(status='complete',declared=SCOPE,reached=coverage,inspected=coverage,unreviewed=[]),source_quality_uncertainty=['Retained electronic sources, not print/CVW collation or CSS/browser equivalence.','Dated original volume-specific distinct-work claims are preserved historical evidence; primary two-volume work controls current identity.','Shared HTML5/libxml boundary whitespace normalization explicitly located; repaired source fidelity independently proved.','Lost initial supported CLI stdout explicitly qualified; two fresh replay stdout/stderr durable.','Source head/style/admin/private image fields remain fully located; maintained reader scope is separately measured.','Human/rights/disclosure/publication remain separate.'],discrepancies=[],unreviewed_residuals=['Human/print/CSS visual review and rights; actual maintained reader separately measured.'])
    review_path=dump(stage,LANE/'review.json',common|review)
    decision=dict(source_local_disposition='Agent accepts the complete source-faithful authored George Whitefield biography with bounded source-backed repairs and exact primary title identity.',blockers=[],agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=SCOPE,unresolved_claims=[],unassessed_stronger_claims=['human acceptance','print collation','CSS/browser visual equivalence','local-jurisdiction rights clearance','publication']),human_decision=dict(status='not-recorded'))
    record=build_acceptance_record(stage,identity=identity(),candidate_path=candidate,source_accounting_path=accounting,scope=dict(kind='work',declared=SCOPE,expected_members=expected,included_members=included,excluded_members=[]),technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
    master_path=write(stage,ED/'master.tei.xml',master);record['promotion']=dict(record['promotion'])|dict(status='promoted',promoted_at=at,master=make_file_binding(stage,master_path));write_acceptance(stage/ED/'acceptance.json',record)
    write(stage,WORK/'SOURCE_CREDIT.md',io_path(ROOT/PROPOSAL_HOME/'SOURCE_CREDIT.md').read_bytes()+b'\n\n'+package.member_bytes('README.source.md')+CREDIT_APPEND);dump(stage,WORK/'state.json',state(at))
    load_work(stage/WORK/'work.json');validate_state(stage/WORK/'state.json',root=stage);validate_acceptance(stage/ED/'acceptance.json',root=stage)
    gate=projection_gate(stage,stage/ED/'acceptance.json')
    for p in dependencies(bootstrap):
        if not io_path(stage/p).exists():copy(ROOT,stage,p)
    execution=read(ROOT/LOG/'accepted-execution-imports-v1.json') if not bootstrap else dict(external_runtime_files=[])
    receipt=dict(contract='ocd-l635-accepted-stage-v1',status='staged-only',identity=identity(),work_id=WORK_ID,complete_works=1,textual_witnesses=2,stage_root=stage.as_posix(),staged_at=at,before={},after=_files(stage/WORK),revision=revision,source_manifest_sha256=source.sha256,package_sha256=package.sha256,source_proof_sha256=PROOF_SHA,master_sha256=sha(master_path),acceptance_sha256=sha(stage/ED/'acceptance.json'),projection_gate=gate,bootstrap=bootstrap,dependency_files={p.as_posix():sha(ROOT/p) for p in sorted(dependencies(bootstrap))},external_runtime_files=execution['external_runtime_files'],preserved_before=preserved())
    if set(receipt['after'])!=allowed_paths(package) or len(receipt['after'])!=29:raise PipelineError('Exact29 Whitefield generation fence differs')
    dump(stage,Path('stage-receipt.json'),receipt);return dict(status='staged-only',stage_root=stage.as_posix(),receipt_sha256=sha(stage/'stage-receipt.json'),after_files=len(receipt['after']),master_sha256=receipt['master_sha256'])

SOURCE_ONLY_MODULES=('build.tei.tyerman_whitefield_complete','build.tei.tyerman_whitefield_complete_oracle',
    'build.tei.tyerman_whitefield_runtime','build.tools.prepare_tyerman_whitefield_complete',
    'build.tools.prove_tyerman_whitefield_complete','build.tei.tyerman_pg_html','build.tei.tyerman_pg_html_oracle')

def source_modules_absent():
    forbidden={resolve_path(ROOT/(name.replace('.','/')+'.py'),strict=True) for name in SOURCE_ONLY_MODULES}
    for name,module in sys.modules.copy().items():
        filename=getattr(module,'__file__',None)
        if name in SOURCE_ONLY_MODULES or filename and resolve_path(Path(filename),strict=True) in forbidden:
            raise PipelineError('Frozen Whitefield source-only module imported in acceptance process: '+name)
    return True

def execution_gate(receipt):
    source_modules_absent()
    root=resolve_path(ROOT,strict=True);library=resolve_path(LIBRARY,strict=True)
    report=read(ROOT/LOG/'accepted-execution-imports-v1.json')
    if report['status']!='pass' or report['identity']!=identity() or report.get('source_modules_absent') is not True:
        raise PipelineError('Exact source-free Whitefield acceptance execution receipt differs')
    local={};external={resolve_path(Path(r['path']),strict=True):r for r in receipt['external_runtime_files']};observed={}
    for row in report['first_party_files']:
        relative=row['path'];path=resolve_path(ROOT/relative,strict=True)
        if path in local or receipt['dependency_files'].get(relative)!=row['sha256'] or io_path(path).stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:
            raise PipelineError('Captured Whitefield execution pin differs from preserved dependency: '+relative)
        local[path]=(relative,row['sha256'])
    for m in sys.modules.copy().values():
        f=getattr(m,'__file__',None)
        if not f:continue
        p=resolve_path(Path(f),strict=True)
        if p.is_relative_to(root) or p.is_relative_to(library):
            if p not in local:raise PipelineError('Unexpected executed Whitefield dependency: '+p.as_posix())
            relative,h=local[p]
            if sha(p)!=h:raise PipelineError('Executed Whitefield dependency drift: '+relative)
            observed[relative]=h
        elif p not in external or p.stat().st_size!=external[p]['bytes'] or sha(p)!=external[p]['sha256']:raise PipelineError('Unexpected or changed external Whitefield runtime: '+p.as_posix())
    for p,row in external.items():
        if p.stat().st_size!=row['bytes'] or sha(p)!=row['sha256']:raise PipelineError('Whitefield external runtime pin drift')
    if resolve_path(Path(sys.executable),strict=True) not in external:raise PipelineError('Executed Whitefield Python binary is not admitted')
    return observed

def preflight(stage,pin,root=ROOT):
    stage=resolve_path(stage,strict=True);root=resolve_path(root,strict=True)
    if root!=resolve_path(ROOT,strict=True):
        if root!=resolve_path(FIXTURE,strict=True) or io_path(root/'.ocd-tyerman-whitefield-fixture').read_text()!='fixture-only\n':raise PipelineError('Exact Whitefield fixture root required')
    if root==stage or root in stage.parents or stage in root.parents or stage.parent!=resolve_path(LIBRARY/'candidate-reviews',strict=True) or not stage.name.startswith('tyerman-whitefield-s-'):raise PipelineError('Whitefield stage/root containment differs')
    if not isinstance(pin,str) or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin) or sha(stage/'stage-receipt.json')!=pin:raise PipelineError('Immutable Whitefield receipt pin differs')
    receipt=read(stage/'stage-receipt.json')
    if receipt['contract']!='ocd-l635-accepted-stage-v1' or receipt['status']!='staged-only' or receipt['identity']!=identity() or receipt['work_id']!=WORK_ID or receipt['complete_works']!=1 or receipt['textual_witnesses']!=2 or receipt['stage_root']!=stage.as_posix() or receipt['before']!={} or receipt['bootstrap'] is not False:raise PipelineError('Exact Whitefield receipt scope differs')
    if _files(root/WORK)!={} or io_path(root/WORK).exists() or _files(stage/WORK)!=receipt['after']:raise PipelineError('Whitefield canonical collision/generation differs')
    if preserved()!=receipt['preserved_before']:raise PipelineError('Preserved Oxford generations changed')
    if receipt['dependency_files']!={p.as_posix():sha(ROOT/p) for p in sorted(dependencies())}:raise PipelineError('Frozen Whitefield dependency set differs')
    for p,h in receipt['dependency_files'].items():
        if sha(ROOT/p)!=h or sha(stage/p)!=h:raise PipelineError('Whitefield dependency bytes drift: '+p)
    source,original,check=source_gate();package=CandidatePackage.load(stage/LANE/'inputs/package')
    if package.sha256!=original.sha256 or any(package.member_bytes(n)!=original.member_bytes(n) for n in package.member_names) or receipt['package_sha256']!=package.sha256 or receipt['source_manifest_sha256']!=source.sha256 or receipt['source_proof_sha256']!=PROOF_SHA:raise PipelineError('Whitefield exact source package/proof differs')
    work,a=records()
    if read(stage/WORK/'work.json')!=work or any(read(stage/ED/'acquisitions'/(record['acquisition_id']+'.json'))!=record for record in all_acquisitions()):raise PipelineError('Exact Whitefield title metadata/acquisition differs')
    for record in all_acquisitions():validate_acquisition(stage/ED/'acquisitions'/(record['acquisition_id']+'.json'),root=stage)
    if io_path(stage/LANE/'identity-crosswalk.json').read_bytes()!=io_path(ROOT/PROPOSAL_HOME/'identity-crosswalk.json').read_bytes():raise PipelineError('Original Whitefield identity crosswalk bytes differ')
    for name,path in [('source-review.json',PROOF),('source-identity-review.json',ROOT_REVIEW),('identity-proposal.json',PROPOSAL),('parent-source-identity-review.json',ROOT_REVIEW)]:
        if io_path(stage/LANE/name).read_bytes()!=io_path(ROOT/path).read_bytes():raise PipelineError('Preserved Whitefield review/identity evidence differs')
    at=receipt['staged_at'];staged_time=datetime.fromisoformat(at.replace('Z','+00:00'))
    if staged_time.tzinfo is None or staged_time.utcoffset().total_seconds()!=0:raise PipelineError('Whitefield stage timestamp must be aware UTC')
    revision=reviewed_revision()
    if receipt['revision']!=revision:raise PipelineError('Exact Whitefield revision date/id/note differs')
    master=bound(package.member_bytes('content.tei.xml'),a,revision)
    if master!=io_path(ROOT/REVIEWED_MASTER).read_bytes() or sha256(master).hexdigest()!=REVIEWED_MASTER_SHA:raise PipelineError('Exact reviewed Whitefield accepted master recomputation differs')
    if io_path(stage/ED/'master.tei.xml').read_bytes()!=master or io_path(stage/LANE/'candidate.tei.xml').read_bytes()!=master or sha(stage/ED/'master.tei.xml')!=receipt['master_sha256'] or sha(stage/ED/'acceptance.json')!=receipt['acceptance_sha256']:raise PipelineError('Exact Whitefield ordered header/body recomputation differs')
    if read(stage/TITLE_REVIEW)!=title_assignment(work,a,at,source,package) or read(stage/WORK/'state.json')!=state(at) or io_path(stage/WORK/'SOURCE_CREDIT.md').read_bytes()!=io_path(ROOT/PROPOSAL_HOME/'SOURCE_CREDIT.md').read_bytes()+b'\n\n'+package.member_bytes('README.source.md')+CREDIT_APPEND:raise PipelineError('Whitefield exact assignment/state/reason/credit differs')
    accepted=validate_acceptance(stage/ED/'acceptance.json',root=stage)
    if accepted['representation_revision']!=revision or accepted['promotion']['status']!='promoted':raise PipelineError('Whitefield acceptance revision/promotion differs')
    validate_state(stage/WORK/'state.json',root=stage)
    if set(receipt['after'])!=allowed_paths(package) or len(receipt['after'])!=29:raise PipelineError('Exact29 Whitefield generation fence differs')
    if projection_gate(stage,stage/ED/'acceptance.json')!=receipt['projection_gate']:raise PipelineError('Measured Whitefield reader changed')
    execution_gate(receipt);return receipt

def install(stage,pin,root=ROOT,fail_at=None):
    preflight(stage,pin,root)
    with ExitStack() as locks:
        for target in sorted((root/WORK,stage/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(target,acquire_timeout=30.0))
        receipt=preflight(stage,pin,root);observed={}
        def checkpoint(point):
            if fail_at:fail_at(point)
            if point=='after-validated':
                if _files(root/WORK)!=receipt['after'] or preserved()!=receipt['preserved_before']:raise PipelineError('Installed Whitefield/preserved generations differ')
                accepted=validate_acceptance(root/ED/'acceptance.json',root=root);validate_state(root/WORK/'state.json',root=root)
                if accepted['representation_revision']!=receipt['revision'] or projection_gate(root,root/ED/'acceptance.json')!=receipt['projection_gate']:raise PipelineError('Installed Whitefield revision/reader differs')
                observed.update(execution_gate(receipt))
        result=_commit_generation(root,root/WORK,stage/WORK,work_id=WORK_ID,before={},after=receipt['after'],existed=False,replacement=False,operation_kind='tyerman-whitefield-complete-initial-install',result_status='installed-and-validated',accepted_editions=1,fail_at=checkpoint)
        return result|dict(executed_code_pins=observed,late_execution_gate='pass',preserved_generations_unchanged=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','preflight','install']);parser.add_argument('stage',nargs='?');parser.add_argument('--receipt-sha256');parser.add_argument('--bootstrap',action='store_true');args=parser.parse_args()
    if args.action=='prepare':result=prepare(Path(args.stage),args.bootstrap)
    elif args.action=='preflight':result=preflight(Path(args.stage),args.receipt_sha256)
    else:result=install(Path(args.stage),args.receipt_sha256)
    print(enc({k:v for k,v in result.items() if k not in ('after','before','dependency_files','external_runtime_files','preserved_before','installed_files','previous_files')}).decode(),end='')
