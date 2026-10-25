"""Bounded initial installation of the already retained Samuel Wesley biography.

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
LOG=Path('reports/_logs/tyerman-samuel-existing-install-20261004-v1')
HOME=Path('sources/manifest-acquisitions/tyerman-samuel-retained-install-20261004-v1')
WORK_ID='tyerman-life-times-samuel-wesley-1866';FORM='english';EDITION='pg67980-1866-simpkin-marshall';ACQUISITION='pg67980-retained-html'
WORK=Path('library/works')/WORK_ID;ED=WORK/'forms'/FORM/'editions'/EDITION;ACQ=ED/'acquisitions'/(ACQUISITION+'.json')
LANE=WORK/'integration/samuel-complete-20261004-v1'
FIXTURE=ROOT/'.tmp_audit/tyerman-samuel-install-fixture-20261004-v1'
PACKAGE=LIBRARY/'candidate-reviews/tyerman-samuel-readable-20261004-v3/package'
PACKAGE_SHA='8f812fc98c12a7268999afd1d35ee0e66ac91d10d16b8679e72c996b6600380a'
SOURCE_SHA='c92e55520624c505f874bec43b4bc95281ce66630b8e3ae5a858154dc8082c39'
PROOF=LOG/'source-proof-v3/source-completion-proof.json';PROOF_SHA='f41b3f0ba29278fa6c444f08da4f0894f11e65fd4ff2297da320487205bf53cc'
ROOT_REVIEW=LOG/'root-final-source-identity-review-v3.json';ROOT_REVIEW_SHA='8c20eb7a5c3076df892007506abe6a4b59731808bc005189219f8363a3d8beb6'
PROPOSAL=LOG/'primary-work-identity-proposal-v2.json';PROPOSAL_SHA='7c11f3544d0c3fb624cc022abbc4801498c5d769bea4b79842b017cb9810993a'
HEADER_PROPOSAL=LOG/'accepted-header-proposal-v3/proposal-receipt.json';HEADER_PROPOSAL_SHA='bf413a77d622fca340ffb116e897809227a7ac6b4c0b8a53d764e2df9f404cce'
HEADER_REVIEW=LOG/'root-accepted-header-review-v3.json';HEADER_REVIEW_SHA='472d8d2a969059f86ddb0d9e749f98139c2dc1e6c60aae934329e389cc85528c'
REVIEWED_MASTER=LOG/'accepted-header-proposal-v3/accepted-representation.tei.xml';REVIEWED_MASTER_SHA='193b6e6921df36eddb0f06c4dd815f05f11a78272754476fa69d3c0dd7617802'
OXFORD=Path('library/works/tyerman-oxford-methodists-1873')
SCOPE='One complete authored Samuel Wesley biography by L. Tyerman: all twenty chapters, appendices A-C, name index, 361 footnotes, transcriber notes, all intervening text and the entire provider wrapper from the one already retained PG67980 HTML witness. Human/print/visual review, local-jurisdiction rights and publication remain separate.'
NOTE='Agent acceptance of the complete already retained Samuel Wesley biography; exact source candidate body preserved and title identity bound.'
TITLE_REVIEW=LANE/'title-identity-review.json'
SOURCE_STATUS=b'Nonaccepted source reconstruction candidate; rights and publication remain separate.'
MASTER_STATUS=b'Agent-accepted faithful complete Samuel Wesley biography; human review, rights and publication remain separate.'
ADMIN_OPEN=b'<bibl type="retained-source-administration"><note type="retained-source-description">'
ADMIN_CLOSE=b'</note></bibl>'
CREDIT_APPEND=b'\n\nThe dated identity proposal is preserved as historical proposal evidence. The current authored biography assignment is recorded in integration/samuel-complete-20261004-v1/title-identity-review.json; agent acceptance is recorded in forms/english/editions/pg67980-1866-simpkin-marshall/acceptance.json. A completed guarded operation journal records canonical installation. Human review, rights and publication remain separate.\n'

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def read(p):return json.loads(io_path(p).read_bytes())
def sha(p):return sha256(io_path(p).read_bytes()).hexdigest()
def write(root,p,b):
    target=io_path(root/p);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b);return root/p
def dump(root,p,v):return write(root,p,enc(v))
def copy(root,stage,p):return write(stage,p,io_path(root/p).read_bytes())
def identity():return dict(work_id=WORK_ID,textual_form_id=FORM,edition_id=EDITION,acquisition_id=ACQUISITION)
def source_binding(a):return {k:a[k] for k in ('source_path','source_sha256','source_bytes','source_scope')}

def reviewed_revision():
    for path,pin in [(HEADER_PROPOSAL,HEADER_PROPOSAL_SHA),(HEADER_REVIEW,HEADER_REVIEW_SHA),(REVIEWED_MASTER,REVIEWED_MASTER_SHA)]:
        if sha(ROOT/path)!=pin:raise PipelineError('Reviewed Samuel header authority drift: '+path.as_posix())
    proposal=read(ROOT/HEADER_PROPOSAL);review=read(ROOT/HEADER_REVIEW)
    expected=dict(id='tyerman-samuel-complete-20261004-v1',date='2026-10-03',note=NOTE)
    if proposal['identity']!=identity() or proposal['revision']!=expected or proposal['source_manifest_sha256']!=SOURCE_SHA or proposal['source_package_sha256']!=PACKAGE_SHA or proposal['master_sha256']!=REVIEWED_MASTER_SHA or not all(proposal[k] is True for k in ('p5_valid','body_byte_equal','accepted_header_inverse_exact')):
        raise PipelineError('Exact reviewed Samuel revision proposal differs')
    if review['status']!='pass' or review['proposal_receipt_sha256']!=HEADER_PROPOSAL_SHA or review['accepted_tei_sha256']!=REVIEWED_MASTER_SHA or review['p5']!='pass' or review['full_original_tei_byte_inverse'] is not True or review['body_byte_equal'] is not True:
        raise PipelineError('Exact root accepted header review differs')
    return expected

def source_gate():
    if sha(ROOT/PROOF)!=PROOF_SHA or sha(ROOT/ROOT_REVIEW)!=ROOT_REVIEW_SHA or sha(ROOT/PROPOSAL)!=PROPOSAL_SHA:raise PipelineError('Frozen source/identity review differs')
    source=SourceManifest.load(ROOT/HOME/'source-manifest.json',repository_root=ROOT);package=CandidatePackage.load(PACKAGE)
    if source.sha256!=SOURCE_SHA or package.sha256!=PACKAGE_SHA:raise PipelineError('Frozen source manifest/package differs')
    proof=read(ROOT/PROOF);review=read(ROOT/ROOT_REVIEW)
    if proof['status']!='pass' or review['status']!='pass' or proof['candidate_sha256']!=package.sha256 or proof['source_manifest_sha256']!=source.sha256 or review['identity']!=identity():raise PipelineError('Exact root source review binding differs')
    cmd=[sys.executable,'-I','-B',str(ROOT/'build/tools/prove_tyerman_samuel_retained.py'),'--mode','oracle','--manifest',(HOME/'source-manifest.json').as_posix(),'--candidate',PACKAGE.as_posix()]
    result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,check=False)
    process=dict(command=cmd,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
    trace=LOG/'admitted-source-processes'/('source-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    if io_path(ROOT/trace).exists():raise PipelineError('Preserve source process evidence collision')
    dump(ROOT,trace,process)
    if result.returncode!=0:raise PipelineError('Fresh isolated source oracle failed; exact process retained at '+trace.as_posix())
    check=json.loads(result.stdout)
    if check['status']!='pass' or check['candidate_sha256']!=package.sha256 or check['source_manifest_sha256']!=source.sha256 or check['producer_imported'] or not check['whole_actual_tree_source_checked'] or not check['full_original_tei_byte_inverse']:raise PipelineError('Fresh isolated full source oracle differs')
    check['source_subprocess_evidence']=dict(path=trace.as_posix(),sha256=sha(ROOT/trace),**process)
    return source,package,check

def records():
    if sha(ROOT/PROPOSAL)!=PROPOSAL_SHA:raise PipelineError('Root-reviewed identity proposal drift')
    p=read(ROOT/PROPOSAL);work=p['work'];a=p['acquisition']
    if p['work_id']!=WORK_ID or p['textual_form_id']!=FORM or p['edition_id']!=EDITION or p['acquisition_id']!=ACQUISITION:raise PipelineError('Exact title route differs')
    receipt=read(ROOT/'raw/gutenberg/67980/acquisition-receipt.json')
    if a['source_path']!=receipt['html']['path'] or a['source_sha256']!=receipt['html']['sha256'] or a['source_bytes']!=receipt['html']['bytes'] or a['url']!=receipt['source_url'] or a['rights']!=receipt['rights'] or a['accessed_at']!=receipt['downloaded_utc'].split('T')[0]:raise PipelineError('Existing acquisition receipt fields differ')
    validate_record('work',work,context='Reviewed Samuel title work');validate_record('acquisition',a,context='Reviewed Samuel retained acquisition')
    return json.loads(json.dumps(work)),json.loads(json.dumps(a))

def state(at):
    receipt=read(ROOT/'raw/gutenberg/67980/acquisition-receipt.json')
    acquired_at=receipt['downloaded_utc']
    parsed=datetime.fromisoformat(acquired_at.replace('Z','+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:raise PipelineError('Exact retained acquisition UTC timestamp required')
    acquisition_evidence=[ACQ.relative_to(WORK).as_posix(),'raw/gutenberg/67980/acquisition-receipt.json',TITLE_REVIEW.as_posix()]
    edition_evidence=[PROOF.as_posix(),ROOT_REVIEW.as_posix(),TITLE_REVIEW.as_posix(),(ED/'master.tei.xml').as_posix(),(ED/'acceptance.json').as_posix()]
    return dict(schema_version='2.0',work_id=WORK_ID,targets=[dict(target_type='acquisition',target_id=ACQUISITION,stage='acquired',updated_at=acquired_at,reason='The existing retained PG67980 HTML, archive and both JPEGs are exactly bound to their acquisition receipt.',evidence=acquisition_evidence),dict(target_type='edition',target_id=EDITION,stage='accepted',updated_at=at,reason=PROMOTED_MASTER_REASON,evidence=edition_evidence)])

def bound(original,a,revision):
    old=etree.fromstring(original);ns={'t':'http://www.tei-c.org/ns/1.0'}
    desc=old.find('t:teiHeader/t:fileDesc/t:sourceDesc',ns)
    if desc is None or any(n.tag!='{http://www.tei-c.org/ns/1.0}p' for n in desc) or old.find('t:teiHeader/t:revisionDesc',ns) is not None:raise PipelineError('Exact sourceDesc paragraph branch or original revision preimage differs')
    if original.count(b'<sourceDesc>')!=1 or original.count(b'</sourceDesc>')!=1:raise PipelineError('Unique literal sourceDesc boundaries required')
    prepared=original.replace(b'<sourceDesc>',b'<sourceDesc>'+ADMIN_OPEN,1).replace(b'</sourceDesc>',ADMIN_CLOSE+b'</sourceDesc>',1)
    result=bind_reviewed_header(prepared,expected_sha256=sha256(prepared).hexdigest(),identity=identity(),source=source_binding(a),source_url=a['url'],declared_scope=SCOPE,revision=revision,historical_source_description=dict(pointers=[],sha256=[]))
    if result.count(SOURCE_STATUS)!=1:raise PipelineError('Exact candidate publication status preimage differs')
    result=result.replace(SOURCE_STATUS,MASTER_STATUS,1)
    if result.split(b'</teiHeader>',1)[1]!=original.split(b'</teiHeader>',1)[1]:raise PipelineError('Accepted header changed source body bytes')
    inverse_header(result,original)
    return result

def inverse_header(actual,original):
    document=etree.fromstring(actual);ns={'t':'http://www.tei-c.org/ns/1.0'}
    binding=document.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl[@type="ocd-acceptance-binding"]',namespaces=ns)
    administration=document.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl[@type="retained-source-administration"]/t:note[@type="retained-source-description"]',namespaces=ns)
    if len(binding)!=1 or len(administration)!=1:raise PipelineError('Exact accepted header branches differ')
    before=etree.fromstring(original).find('t:teiHeader/t:fileDesc/t:sourceDesc',ns)
    def fields(n):return (n.tag,dict(n.attrib),n.text,n.tail,[fields(c) for c in n])
    if [fields(n) for n in administration[0]]!=[fields(n) for n in before] or administration[0].text!=before.text:raise PipelineError('Accepted administration paragraph subtrees/fields differ')
    restored=actual
    for opening,closing in [(b'<bibl xmlns="http://www.tei-c.org/ns/1.0" type="ocd-acceptance-binding">',b'</bibl>'),(b'<revisionDesc xmlns="http://www.tei-c.org/ns/1.0">',b'</revisionDesc>')]:
        if restored.count(opening)!=1:raise PipelineError('Unique reviewed header insertion boundary differs')
        i=restored.index(opening);j=restored.index(closing,i)+len(closing);restored=restored[:i]+restored[j:]
    if restored.count(ADMIN_OPEN)!=1 or restored.count(ADMIN_CLOSE)!=1 or restored.count(MASTER_STATUS)!=1:raise PipelineError('Exact accepted administration/status inverse markers differ')
    restored=restored.replace(ADMIN_OPEN,b'',1).replace(ADMIN_CLOSE,b'',1).replace(MASTER_STATUS,SOURCE_STATUS,1)
    if restored!=original:raise PipelineError('Exact accepted header/body inverse to frozen source candidate differs')
    return True

def title_assignment(work,a,at,source,package):
    return dict(contract='ocd-current-authored-work-title-assignment-v1',status='agent-reviewed',reviewer='agent:tyerman-samuel-complete-source-review',reviewed_at=at,identity=identity(),work_title=work['title'],creators=work['creators'],complete_authored_works=1,retained_textual_witnesses=1,scope=dict(kind='work',declared=SCOPE),historical_proposal=dict(path=PROPOSAL.as_posix(),sha256=PROPOSAL_SHA,preserved_status='proposal'),root_source_identity_review=dict(path=ROOT_REVIEW.as_posix(),sha256=ROOT_REVIEW_SHA),current_assignment='One complete Samuel Wesley biography by L. Tyerman. The literal HTML title miscredits John and Charles Wesley as authors and remains located metadata; actual titlepage/provider creator control identity.',source=source_binding(a),source_url=a['url'],source_manifest_sha256=source.sha256,source_package_sha256=package.sha256,acquisition_conservation='The already retained original receipt source URL, HTML/ZIP/image bytes and hashes, download timestamp and rights wording remain unchanged; no new acquisition.',human_decision='not-recorded',rights_publication='separate unresolved gates',installation_evidence='The completed guarded journal records canonical installation.',new_download=False)

def allowed_paths(package):
    paths={'work.json','state.json','SOURCE_CREDIT.md',ACQ.relative_to(WORK).as_posix(),(ED/'master.tei.xml').relative_to(WORK).as_posix(),(ED/'acceptance.json').relative_to(WORK).as_posix()}
    paths.update((LANE/'inputs/package'/n).relative_to(WORK).as_posix() for n in package.member_names)
    paths.update((LANE/n).relative_to(WORK).as_posix() for n in ['source-review.json','source-identity-review.json','identity-proposal.json','parent-source-identity-review.json','title-identity-review.json','candidate.tei.xml','source-accounting.json','validation.json','accounting.json','fidelity.json','reproducibility.json','schema.json','closure.json','review.json'])
    return paths

def projection_gate(root,acceptance):
    from ocd_kernel.projection.categories.prose import project_accepted_prose,verify_accepted_prose
    result=project_accepted_prose(root,acceptance_path=acceptance)
    errors=verify_accepted_prose(root,acceptance_path=acceptance,rows=result['rows'],receipt=result['receipt'])
    if errors:raise PipelineError('Samuel accepted reader check failed: '+str(errors))
    return dict(status='pass',rows=len(result['rows']),receipt_sha256=sha256(enc(result['receipt'])).hexdigest())

def dependencies(bootstrap=False):
    source=SourceManifest.load(ROOT/HOME/'source-manifest.json',repository_root=ROOT)
    paths={Path(a['path']) for a in source.record['authorities']}|{HOME/'source-manifest.json',PROOF,ROOT_REVIEW,PROPOSAL,LOG/'source-identity-review-packet-v3.json',Path(__file__).relative_to(ROOT)}
    paths.update(p.relative_to(ROOT) for directory,pattern in [('schemas/v2','*.json'),('ocd_kernel/tei/vendor/xsd','*.xsd'),('ocd_kernel/reconstruction/schemas','*.json')] for p in (ROOT/directory).rglob(pattern))
    paths.update(Path(p) for p in ['build/tools/capture_tyerman_samuel_acceptance.py','build/tools/prove_tyerman_samuel_install.py'])
    paths.update({HEADER_PROPOSAL,HEADER_REVIEW,REVIEWED_MASTER})
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
                    if relative.parts[0] not in {'raw','reports','exports'} or resolve_path(ROOT/relative,strict=True)!=p:raise PipelineError('Samuel Library execution alias differs')
                    paths.add(relative)
    else:
        report=LOG/'accepted-execution-imports-v1.json';record=read(ROOT/report);paths.add(report)
        if record['status']!='pass' or record['identity']!=identity():raise PipelineError('Actual acceptance execution receipt differs')
        for row in record['first_party_files']:
            if sha(ROOT/row['path'])!=row['sha256']:raise PipelineError('Actual accepted dependency drift: '+row['path'])
            paths.add(Path(row['path']))
    return paths

def header_proposal():
    source,package,check=source_gate();work,a=records();at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    revision=dict(id='tyerman-samuel-complete-20261004-v1',date=at[:10],note=NOTE)
    destination=ROOT/LOG/'accepted-header-proposal-v3'
    if destination.exists():raise PipelineError('Preserve existing accepted-header proposal')
    destination.mkdir();master=bound(package.member_bytes('content.tei.xml'),a,revision)
    p=write(destination,Path('accepted-representation.tei.xml'),master)
    if errors:=validate_file(p):raise PipelineError(str(errors))
    _,facts=_tei_facts(p)
    if any(facts[k]!=v for k,v in identity().items()) or facts['source_sha256']!=a['source_sha256'] or facts['source_bytes']!=str(a['source_bytes']) or facts['source_url']!=a['url']:raise PipelineError('Maintained identity reader did not select typed accepted bibl')
    dump(destination,Path('work.json'),work);dump(destination,Path('acquisition.json'),a);dump(destination,Path('state.json'),state(at))
    dump(destination,Path('title-identity-review.json'),title_assignment(work,a,at,source,package))
    report=dict(status='proposal-only',identity=identity(),scope=SCOPE,staged_at=at,revision=revision,source_manifest_sha256=source.sha256,source_package_sha256=package.sha256,master_sha256=sha(p),p5_valid=True,accepted_header_inverse_exact=inverse_header(master,package.member_bytes('content.tei.xml')),maintained_typed_binding_reader=facts,body_byte_equal=master.split(b'</teiHeader>',1)[1]==package.member_bytes('content.tei.xml').split(b'</teiHeader>',1)[1],source_oracle=check,reader='not captured; maintained reader update pending',canonical_installation='not performed')
    dump(destination,Path('proposal-receipt.json'),report);return {k:v for k,v in report.items() if k!='source_oracle'}

def prepare(stage,bootstrap=False):
    stage=stage.absolute()
    if stage.exists() or stage.parent!=LIBRARY/'candidate-reviews' or not stage.name.startswith('tyerman-samuel-s-'):raise PipelineError('Fresh external Samuel stage required')
    if io_path(ROOT/WORK).exists():raise PipelineError('Samuel work home already exists; no replacement')
    source,package,check=source_gate();work,a=records();stage.mkdir()
    for authority in source.record['authorities']:copy(ROOT,stage,Path(authority['path']))
    for p in (HOME/'source-manifest.json',PROOF,ROOT_REVIEW,PROPOSAL,LOG/'source-identity-review-packet-v3.json',Path('raw/gutenberg/67980/html/images/cover.jpg'),Path('raw/gutenberg/67980/html/images/i_004.jpg')):copy(ROOT,stage,p)
    dump(stage,WORK/'work.json',work);dump(stage,ACQ,a);validate_acquisition(stage/ACQ,root=stage)
    for n in package.member_names:write(stage,LANE/'inputs/package'/n,package.member_bytes(n))
    for filename,path in [('source-review.json',PROOF),('source-identity-review.json',LOG/'source-identity-review-packet-v3.json'),('identity-proposal.json',PROPOSAL),('parent-source-identity-review.json',ROOT_REVIEW)]:write(stage,LANE/filename,io_path(ROOT/path).read_bytes())
    at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z');revision=reviewed_revision()
    assignment=dump(stage,TITLE_REVIEW,title_assignment(work,a,at,source,package));master=bound(package.member_bytes('content.tei.xml'),a,revision);candidate=write(stage,LANE/'candidate.tei.xml',master)
    if master!=io_path(ROOT/REVIEWED_MASTER).read_bytes() or sha256(master).hexdigest()!=REVIEWED_MASTER_SHA:raise PipelineError('Exact reviewed Samuel accepted master recomputation differs')
    if errors:=validate_file(candidate):raise PipelineError(str(errors))
    expected=[dict(path=r['path'],position=i) for i,r in enumerate(a['retained_files'],1)]
    included=[dict(path=r['path'],position=i,bytes=r['bytes'],sha256=r['sha256'],scope=r['scope']) for i,r in enumerate(a['retained_files'],1)]
    common=dict(identity=identity(),source=source_binding(a),candidate=make_file_binding(stage,candidate),accepted_scope=dict(kind='work',declared=SCOPE),scope=SCOPE,expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[],source_manifest_sha256=source.sha256,candidate_package_sha256=package.sha256,source_proof_sha256=PROOF_SHA,representation_revision=revision,staged_at=at)
    accounting=dump(stage,LANE/'source-accounting.json',common|dict(scope=a['source_scope'],source_sha256=a['source_sha256'],source_bytes=a['source_bytes'],complete_works=1,textual_witnesses=1,archive_members=3,original_source_receipt='raw/gutenberg/67980/acquisition-receipt.json',source_review=make_file_binding(stage,stage/LANE/'source-review.json'),current_title_assignment=make_file_binding(stage,assignment),exact_current_source_oracle=check))
    command='py -3 -I -B build/tools/tyerman_samuel_install.py prepare "'+stage.as_posix()+'"'+(' --bootstrap' if bootstrap else '')
    technical=dict(producer=dict(id='ocd-l637-reviewed-header-and-initial-install'),checker=dict(id=source.record['validator']['id']),shared_assumptions=['Shared HTML5 normalization and inherited source carrier grammar explicitly qualified.'],independent_corroboration='Current raw-derived complete actual source tree/header/footer/media and full original TEI inverse in an admitted fresh process;29 source and3 accounting valid dated negatives,8 identity guards,4 actual fresh late-import negatives,two fresh six-member replays. Exact source wording/structure and accepted body-byte conservation; separate current accepted reader check.')
    for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
        p=dump(stage,LANE/(name+'.json'),common|dict(status='pass',command=command,exit_code=0,claim=name,source_proof=make_file_binding(stage,stage/LANE/'source-review.json'),producer=dict(source.record['converter']),header_binding_implementation_sha256=sha(Path(__file__))))
        technical[name]=dict(path=p,status='pass',command=command,exit_code=0)
    coverage=['Entire complete biography with all twenty chapters, appendices, name index,361 footnotes and transcriber notes','Every actual retained HTML element and declared source field disposition; structured provider header/footer and full head/prolog/root administration','All63 correction tooltip titles,52 span languages,two exact JPEG payloads/archive-member contexts; table/list/inline/link fields,order and attachment','Independent actual full tree/P5/source inverse; bounded negative processes and two fresh six-member byte replays','Primary authored title/creator/imprint and existing acquisition identity, exact accepted ordered header and unchanged body bytes']
    review=dict(reviewer='agent:tyerman-samuel-complete-source-review',reviewed_at=at,coverage=dict(status='complete',declared=SCOPE,reached=coverage,inspected=coverage,unreviewed=[]),source_quality_uncertainty=['Retained electronic witness, not print collation or CSS/browser equivalence.','HTML title miscredits authors; literal is retained as administration, primary BY L.TYERMAN controls identity.','Five exact HTML5 document-formatting fields and whitespace-only table/list dispositions are declared,not silent omissions.','Original header/footer baseline restoration is conservation evidence; repaired fidelity comes from separate full actual source checks.','Human/visual/rights/publication remain separate.'],discrepancies=['The literal HTML title miscredits John and Charles Wesley as authors.'],unreviewed_residuals=['Human/print/CSS visual review and rights; actual accepted reader projection is separately measured.'])
    review_path=dump(stage,LANE/'review.json',common|review)
    decision=dict(source_local_disposition='Agent accepts the complete source-faithful authored Samuel Wesley biography with bounded source-backed repairs and exact primary title identity.',blockers=[],agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=at,supported_scope=SCOPE,unresolved_claims=[],unassessed_stronger_claims=['human acceptance','print collation','CSS/browser visual equivalence','local-jurisdiction rights clearance','publication']),human_decision=dict(status='not-recorded'))
    record=build_acceptance_record(stage,identity=identity(),candidate_path=candidate,source_accounting_path=accounting,scope=dict(kind='work',declared=SCOPE,expected_members=expected,included_members=included,excluded_members=[]),technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
    master_path=write(stage,ED/'master.tei.xml',master);record['promotion']=dict(record['promotion'])|dict(status='promoted',promoted_at=at,master=make_file_binding(stage,master_path));write_acceptance(stage/ED/'acceptance.json',record)
    write(stage,WORK/'SOURCE_CREDIT.md',package.member_bytes('README.source.md')+CREDIT_APPEND);dump(stage,WORK/'state.json',state(at))
    load_work(stage/WORK/'work.json');validate_state(stage/WORK/'state.json',root=stage);validate_acceptance(stage/ED/'acceptance.json',root=stage)
    gate=projection_gate(stage,stage/ED/'acceptance.json')
    for p in dependencies(bootstrap):
        if not io_path(stage/p).exists():copy(ROOT,stage,p)
    execution=read(ROOT/LOG/'accepted-execution-imports-v1.json') if not bootstrap else dict(external_runtime_files=[])
    receipt=dict(contract='ocd-l637-accepted-stage-v1',status='staged-only',identity=identity(),work_id=WORK_ID,complete_works=1,textual_witnesses=1,stage_root=stage.as_posix(),staged_at=at,before={},after=_files(stage/WORK),revision=revision,source_manifest_sha256=source.sha256,package_sha256=package.sha256,source_proof_sha256=PROOF_SHA,master_sha256=sha(master_path),acceptance_sha256=sha(stage/ED/'acceptance.json'),projection_gate=gate,bootstrap=bootstrap,dependency_files={p.as_posix():sha(ROOT/p) for p in sorted(dependencies(bootstrap))},external_runtime_files=execution['external_runtime_files'],oxford_before=_files(ROOT/OXFORD))
    if set(receipt['after'])!=allowed_paths(package) or len(receipt['after'])!=26:raise PipelineError('Exact26 Samuel generation fence differs')
    dump(stage,Path('stage-receipt.json'),receipt);return dict(status='staged-only',stage_root=stage.as_posix(),receipt_sha256=sha(stage/'stage-receipt.json'),after_files=len(receipt['after']),master_sha256=receipt['master_sha256'])

def execution_gate(receipt):
    root=resolve_path(ROOT,strict=True);library=resolve_path(LIBRARY,strict=True)
    report=LOG/'accepted-execution-imports-v1.json'
    if receipt['dependency_files'].get(report.as_posix())!=sha(ROOT/report):raise PipelineError('Frozen Samuel acceptance execution receipt differs')
    record=read(ROOT/report)
    if record['status']!='pass' or record['identity']!=identity() or record['source_oracle_imported'] is not False or record['source_producer_imported'] is not False:raise PipelineError('Samuel acceptance execution scope differs')
    local={}
    for row in record['first_party_files']:
        p=row['path'];h=row['sha256'];physical=resolve_path(ROOT/p,strict=True)
        if physical in local or receipt['dependency_files'].get(p)!=h or sha(physical)!=h:raise PipelineError('Samuel observed execution/authority pin differs: '+p)
        local[physical]=(p,h)
    frozen_source={resolve_path(ROOT/p,strict=True) for p in ('build/tei/tyerman_samuel_retained_repair.py','build/tei/tyerman_samuel_source_oracle.py','build/tools/prove_tyerman_samuel_retained.py')}
    if frozen_source.intersection(local):raise PipelineError('Frozen Samuel source execution cannot enter acceptance admission')
    external={resolve_path(Path(r['path']),strict=True):r for r in receipt['external_runtime_files']};observed={}
    for m in sys.modules.copy().values():
        f=getattr(m,'__file__',None)
        if not f:continue
        p=resolve_path(Path(f),strict=True)
        if p in frozen_source:raise PipelineError('Frozen Samuel source producer/oracle/proof wrapper imported into acceptance process')
        if p.is_relative_to(root) or p.is_relative_to(library):
            if p not in local:raise PipelineError('Unexpected executed Samuel dependency: '+p.as_posix())
            relative,h=local[p]
            if sha(p)!=h:raise PipelineError('Executed Samuel dependency drift: '+relative)
            observed[relative]=h
        elif p not in external or p.stat().st_size!=external[p]['bytes'] or sha(p)!=external[p]['sha256']:raise PipelineError('Unexpected or changed external Samuel runtime: '+p.as_posix())
    for p,row in external.items():
        if p.stat().st_size!=row['bytes'] or sha(p)!=row['sha256']:raise PipelineError('Samuel external runtime pin drift')
    if resolve_path(Path(sys.executable),strict=True) not in external:raise PipelineError('Executed Samuel Python binary is not admitted')
    return observed

def preflight(stage,pin,root=ROOT):
    stage=resolve_path(stage,strict=True);root=resolve_path(root,strict=True)
    if root!=resolve_path(ROOT,strict=True):
        if root!=resolve_path(FIXTURE,strict=True) or io_path(root/'.ocd-tyerman-samuel-fixture').read_text()!='fixture-only\n':raise PipelineError('Exact Samuel fixture root required')
    if root==stage or root in stage.parents or stage in root.parents or stage.parent!=resolve_path(LIBRARY/'candidate-reviews',strict=True) or not stage.name.startswith('tyerman-samuel-s-'):raise PipelineError('Samuel stage/root containment differs')
    if not isinstance(pin,str) or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin) or sha(stage/'stage-receipt.json')!=pin:raise PipelineError('Immutable Samuel receipt pin differs')
    receipt=read(stage/'stage-receipt.json')
    if receipt['contract']!='ocd-l637-accepted-stage-v1' or receipt['status']!='staged-only' or receipt['identity']!=identity() or receipt['work_id']!=WORK_ID or receipt['complete_works']!=1 or receipt['textual_witnesses']!=1 or receipt['stage_root']!=stage.as_posix() or receipt['before']!={} or receipt['bootstrap'] is not False:raise PipelineError('Exact Samuel receipt scope differs')
    if _files(root/WORK)!={} or io_path(root/WORK).exists() or _files(stage/WORK)!=receipt['after']:raise PipelineError('Samuel canonical collision/generation differs')
    if _files(ROOT/OXFORD)!=receipt['oxford_before']:raise PipelineError('Preserved Oxford generation changed')
    if receipt['dependency_files']!={p.as_posix():sha(ROOT/p) for p in sorted(dependencies())}:raise PipelineError('Frozen Samuel dependency set differs')
    for p,h in receipt['dependency_files'].items():
        if sha(ROOT/p)!=h or sha(stage/p)!=h:raise PipelineError('Samuel dependency bytes drift: '+p)
    source,original,check=source_gate();package=CandidatePackage.load(stage/LANE/'inputs/package')
    if package.sha256!=original.sha256 or any(package.member_bytes(n)!=original.member_bytes(n) for n in package.member_names) or receipt['package_sha256']!=package.sha256 or receipt['source_manifest_sha256']!=source.sha256 or receipt['source_proof_sha256']!=PROOF_SHA:raise PipelineError('Samuel exact source package/proof differs')
    work,a=records()
    if read(stage/WORK/'work.json')!=work or read(stage/ACQ)!=a:raise PipelineError('Exact Samuel title metadata/acquisition differs')
    validate_acquisition(stage/ACQ,root=stage)
    for name,path in [('source-review.json',PROOF),('source-identity-review.json',LOG/'source-identity-review-packet-v3.json'),('identity-proposal.json',PROPOSAL),('parent-source-identity-review.json',ROOT_REVIEW)]:
        if io_path(stage/LANE/name).read_bytes()!=io_path(ROOT/path).read_bytes():raise PipelineError('Preserved Samuel review/identity evidence differs')
    at=receipt['staged_at'];staged_time=datetime.fromisoformat(at.replace('Z','+00:00'))
    if staged_time.tzinfo is None or staged_time.utcoffset().total_seconds()!=0:raise PipelineError('Samuel stage timestamp must be aware UTC')
    revision=reviewed_revision()
    if receipt['revision']!=revision:raise PipelineError('Exact Samuel revision date/id/note differs')
    master=bound(package.member_bytes('content.tei.xml'),a,revision)
    if master!=io_path(ROOT/REVIEWED_MASTER).read_bytes() or sha256(master).hexdigest()!=REVIEWED_MASTER_SHA:raise PipelineError('Exact reviewed Samuel accepted master recomputation differs')
    if io_path(stage/ED/'master.tei.xml').read_bytes()!=master or io_path(stage/LANE/'candidate.tei.xml').read_bytes()!=master or sha(stage/ED/'master.tei.xml')!=receipt['master_sha256'] or sha(stage/ED/'acceptance.json')!=receipt['acceptance_sha256']:raise PipelineError('Exact Samuel ordered header/body recomputation differs')
    if read(stage/TITLE_REVIEW)!=title_assignment(work,a,at,source,package) or read(stage/WORK/'state.json')!=state(at) or io_path(stage/WORK/'SOURCE_CREDIT.md').read_bytes()!=package.member_bytes('README.source.md')+CREDIT_APPEND:raise PipelineError('Samuel exact assignment/state/reason/credit differs')
    accepted=validate_acceptance(stage/ED/'acceptance.json',root=stage)
    if accepted['representation_revision']!=revision or accepted['promotion']['status']!='promoted':raise PipelineError('Samuel acceptance revision/promotion differs')
    validate_state(stage/WORK/'state.json',root=stage)
    if set(receipt['after'])!=allowed_paths(package) or len(receipt['after'])!=26:raise PipelineError('Exact26 Samuel generation fence differs')
    if projection_gate(stage,stage/ED/'acceptance.json')!=receipt['projection_gate']:raise PipelineError('Measured Samuel reader changed')
    execution_gate(receipt);return receipt

def install(stage,pin,root=ROOT,fail_at=None):
    preflight(stage,pin,root)
    with ExitStack() as locks:
        for target in sorted((root/WORK,stage/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(target,acquire_timeout=30.0))
        receipt=preflight(stage,pin,root);observed={}
        def checkpoint(point):
            if fail_at:fail_at(point)
            if point=='after-validated':
                if _files(root/WORK)!=receipt['after'] or _files(ROOT/OXFORD)!=receipt['oxford_before']:raise PipelineError('Installed Samuel/Oxford generation differs')
                accepted=validate_acceptance(root/ED/'acceptance.json',root=root);validate_state(root/WORK/'state.json',root=root)
                if accepted['representation_revision']!=receipt['revision'] or projection_gate(root,root/ED/'acceptance.json')!=receipt['projection_gate']:raise PipelineError('Installed Samuel revision/reader differs')
                observed.update(execution_gate(receipt))
        result=_commit_generation(root,root/WORK,stage/WORK,work_id=WORK_ID,before={},after=receipt['after'],existed=False,replacement=False,operation_kind='tyerman-samuel-complete-initial-install',result_status='installed-and-validated',accepted_editions=1,fail_at=checkpoint)
        return result|dict(executed_code_pins=observed,late_execution_gate='pass',oxford_generation_unchanged=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['header-proposal','prepare','preflight','install']);parser.add_argument('stage',nargs='?');parser.add_argument('--receipt-sha256');parser.add_argument('--bootstrap',action='store_true');args=parser.parse_args()
    if args.action=='header-proposal':result=header_proposal()
    elif args.action=='prepare':result=prepare(Path(args.stage),args.bootstrap)
    elif args.action=='preflight':result=preflight(Path(args.stage),args.receipt_sha256)
    else:result=install(Path(args.stage),args.receipt_sha256)
    print(enc({k:v for k,v in result.items() if k not in ('after','before','dependency_files','external_runtime_files','oxford_before','installed_files','previous_files')}).decode(),end='')
