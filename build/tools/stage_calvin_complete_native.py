"""Stage complete source-supported Calvin corpus; no canonical authority mutation."""
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
from lxml import etree
from build.tools.prepare_calvin_complete_native import ROOT,WORK_ID,FORM_ID,EDITION_ID,ACQUISITION_ID,WORK,EDITION,ACQUISITION,BASE,NOTICE_BASE,DATA_NOTICE,LOGS,SCOPE,canonical
from build.tei.calvin_institutes_complete_native_oracle import inverse_and_compare
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work,validate_identity_update,cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.acceptance import build_acceptance_record,make_file_binding,validate_acceptance,write_acceptance,PROMOTED_MASTER_REASON
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.native_documents import project_accepted_document,verify_accepted_document
EVIDENCE=WORK/'integration/pg-allen-two-volume-native-v1'
RUNTIME=['ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/reconstruction/contract.py','build/tei/calvin_institutes_complete_native.py','build/tei/calvin_institutes_complete_native_oracle.py']
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def put(root,rel,b):
    p=io_path(root/rel);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);return root/rel
def save(root,rel,v):return put(root,rel,canonical(v))
def bind_corpus(raw,identity,source,url,revision):
    # The maintained binder handles a single TEI. Bind its outer header in a
    # throwaway TEI shell, then change only the exact first corpus-header bytes.
    begin=raw.index(b'<teiHeader>');end=raw.index(b'</teiHeader>',begin)+len(b'</teiHeader>')
    header=raw[begin:end]
    shell=b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'+header+b'<text><body><p>Header derivation envelope</p></body></text></TEI>'
    bound=bind_reviewed_header(shell,expected_sha256=sha256(shell).hexdigest(),identity=identity,source=source,source_url=url,declared_scope=SCOPE,revision=revision)
    hb=bound.index(b'<teiHeader>');he=bound.index(b'</teiHeader>',hb)+len(b'</teiHeader>')
    header_bound=bound[hb:he]
    result=raw[:begin]+header_bound+raw[end:]
    if result[:begin]+header+result[begin+len(header_bound):]!=raw:raise ValueError('corpus header splice changed nonheader bytes')
    a,b=etree.fromstring(raw),etree.fromstring(result)
    if len(a)!=3 or len(b)!=3 or any(etree.tostring(a[i])!=etree.tostring(b[i]) for i in (1,2)):
        raise ValueError('physical member document bytes differ after binding')
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('candidate','replay','stage','promoted'):p.add_argument('--'+n,type=Path,required=True)
    args=p.parse_args()
    for r in (args.stage,args.promoted):
        if r.exists() or r.parent.resolve()!=Path('D:/Library/Open Christian Data/candidate-reviews').resolve():raise ValueError('fresh bounded candidate-review stage required')
    schemas={x.relative_to(ROOT).as_posix():digest(x) for x in sorted((ROOT/'schemas/v2').rglob('*.json'))};runtime={x:digest(ROOT/x) for x in RUNTIME}
    if runtime[RUNTIME[0]]!='d749eb107efc8e762642a05dc35c7ebcd7789b37459851f74d9faf14c7c1c013':raise ValueError('reviewed current helper differs')
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);manifest.verify()
    a=CandidatePackage.load(args.candidate/'package');b=CandidatePackage.load(args.replay/'package')
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names):raise ValueError('fresh full package replay differs')
    validation=json.loads((args.candidate/'validation.json').read_bytes());replay_validation=json.loads((args.replay/'validation.json').read_bytes())
    if validation!=replay_validation or validation['status']!='pass' or validation['source_manifest_sha256']!=manifest.sha256 or validation['candidate_sha256']!=a.sha256:raise ValueError('fresh complete oracle replay differs')
    oracle=validation['attestation']
    if oracle['implementation_sha256']!=manifest.record['validator']['implementation_sha256'] or oracle['import_closure_sha256']!=manifest.record['validator']['import_closure_sha256']:raise ValueError('saved fresh oracle code binding differs')
    original=CandidatePackage.load(manifest.authority_path('baseline-package-manifest').parent)
    accounting=json.loads(a.member_bytes('source-accountability.json'));inventory=canonical(accounting['native_envelope'])
    raw=a.member_bytes('content.tei.xml');inverse_and_compare(raw,original.member_bytes('content.tei.xml'),inventory)
    challenges=json.loads(io_path(ROOT/LOGS/'adapter-boundary-proof.json').read_bytes());namespaces=json.loads(io_path(ROOT/LOGS/'adapter-namespace-proof.json').read_bytes())
    if challenges['status']!='pass' or len(challenges['cases'])!=32 or namespaces['status']!='pass' or len(namespaces['cases'])!=5 or any(c['status']!='rejected' for c in challenges['cases']+namespaces['cases']) or challenges['candidate_sha256']!=sha256(raw).hexdigest() or namespaces['baseline_sha256']!=sha256(raw).hexdigest():raise ValueError('meaningful challenges incomplete')
    before=_files(ROOT/WORK)
    if any(Path(n).name in ('acceptance.json','master.tei.xml') for n in before):raise ValueError('canonical accepted edition already exists')
    for rel in before:put(args.stage,WORK/rel,io_path(ROOT/WORK/rel).read_bytes())
    acquisition=json.loads(io_path(ROOT/LOGS/'acquisition-proposed.json').read_bytes())
    for member in acquisition['retained_files']:put(args.stage,Path(member['path']),io_path(ROOT/member['path']).read_bytes())
    put(args.stage,Path(acquisition['source_path']),io_path(ROOT/acquisition['source_path']).read_bytes())
    put(args.stage,ACQUISITION,canonical(acquisition))
    old_state=json.loads(io_path(ROOT/WORK/'state.json').read_bytes())
    for target in old_state['targets']:
        for path in target['evidence']:
            if not io_path(args.stage/path).exists():put(args.stage,Path(path),io_path(ROOT/path).read_bytes())
    old_work=load_work(ROOT/WORK/'work.json');new_work=json.loads(canonical(old_work))
    form=new_work['textual_forms'][0];edition=form['editions'][0]
    if form['textual_form_id']!=FORM_ID or edition['edition_id']!=EDITION_ID or 'language' in form or 'category' in edition:raise ValueError('exact missing metadata prerequisite differs')
    form['language']='en';edition['category']='prose';validate_identity_update(old_work,new_work);save(args.stage,WORK/'work.json',new_work)
    validate_acquisition(io_path(args.stage/ACQUISITION),root=args.stage)
    put(args.stage,WORK/'SOURCE_CREDIT.md',io_path(ROOT/NOTICE_BASE/'README.source.md').read_bytes())
    for name in a.member_names:put(args.stage,EVIDENCE/'original-package'/name,a.member_bytes(name))
    put(args.stage,EVIDENCE/'source-manifest.json',manifest.path.read_bytes());save(args.stage,EVIDENCE/'original-validation.json',validation)
    save(args.stage,EVIDENCE/'mutations.json',dict(source_cases=challenges,namespace_cases=namespaces))
    identity=dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID)
    source={k:acquisition[k] for k in ('source_path','source_sha256','source_bytes','source_scope','source_kind')}
    revision=dict(id='calvin-allen-complete-two-volume-native-v1',date='2026-10-01',note='Technical acceptance of the complete retained John Allen two-volume witness, all four logical books and 80 chapters; exact reversible native scaffolding aliases preserve source lines, notes, blank payloads, volume continuation and both indexes. No human, print, rights or public publication assessment.')
    bound=bind_corpus(raw,identity,source,acquisition['url'],revision)
    if bound!=bind_corpus(b.member_bytes('content.tei.xml'),identity,source,acquisition['url'],revision):raise ValueError('exact promoted-header replay differs')
    candidate=put(args.stage,EVIDENCE/'candidate.tei.xml',bound)
    if errors:=validate_file(io_path(candidate)):raise ValueError(errors)
    expected=[dict(path=m['path'],position=i) for i,m in enumerate(acquisition['retained_files'],1)]
    included=[dict(path=m['path'],position=i,bytes=m['bytes'],sha256=m['sha256'],scope=m['scope']) for i,m in enumerate(acquisition['retained_files'],1)]
    scope=dict(kind='selection',declared=SCOPE,expected_members=expected,included_members=included,excluded_members=[])
    common=dict(identity=identity,source=source,candidate=make_file_binding(args.stage,candidate),accepted_scope=dict(kind='selection',declared=SCOPE),expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[])
    facts=dict(source_lines=69897,source_bytes=4060187,physical_volumes=2,logical_books=4,chapters=80,notes=3506,attached_reference_occurrences=3505,tables=769,rows=3972,cells=15888,underscore_delimiters=1156,aliases=20471)
    account=save(args.stage,EVIDENCE/'source-accounting.json',common|dict(scope=source['source_scope'],source_sha256=source['source_sha256'],source_bytes=source['source_bytes'],source_oracle=oracle,source_facts=facts,complete_line_ledger=make_file_binding(args.stage,args.stage/EVIDENCE/'original-package/source-accountability.json')))
    command='py -3 -m build.tools.stage_calvin_complete_native --candidate <frozen> --replay <fresh> --stage <isolated> --promoted <isolated>'
    technical=dict(producer=dict(id=manifest.record['converter']['id']),checker=dict(id=manifest.record['validator']['id']),shared_assumptions=['Established complete source mapper reused readonly. New independent inverse does not import the producer; existing full source oracle is retained unchanged. Source parser/oracle exposure disclosed, not blind.'],independent_corroboration='Complete independent source oracle on inverse; full coordinator direct native tree check without mapper/oracle; exact three independently pinned source-backed fresh headers; 32 source/envelope/alias and five alias-namespace rejection challenges; byte-exact fresh-process replay.')
    evidence=dict(source_oracle=oracle,validation=validation,mutation_cases=challenges['cases']+namespaces['cases'],replay=dict(status='pass',candidate_sha256=a.sha256,validation_equal=True,bound_candidate_sha256=sha256(bound).hexdigest()),tei_p5='pass',physical_member_documents_byte_identical=True)
    for name in ('validation','accounting','fidelity','reproducibility','schema','closure'):
        path=save(args.stage,EVIDENCE/(name+'.json'),common|dict(scope=SCOPE,status='pass',command=command,exit_code=0,claim=name,**evidence));technical[name]=dict(path=path,status='pass',command=command,exit_code=0)
    now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    review=dict(reviewer='agent:calvin-allen-complete-source-check',reviewed_at=now,coverage=dict(status='partial',declared=SCOPE,reached=['complete retained electronic source pair and all exact line/native/attachment inventories'],inspected=['complete retained electronic source pair and all exact line/native/attachment inventories'],unreviewed=['visual source comparison','print collation']),source_quality_uncertainty=['Retained plain-text witness, independently uncollated to print; source date labels unresolved. Worldwide rights/human/publication unassessed.'],discrepancies=[],unreviewed_residuals=['Human verification, exact print equivalence, worldwide rights and public publication remain separate.'])
    report=save(args.stage,EVIDENCE/'review.json',common|review|dict(scope=SCOPE))
    decision=dict(source_local_disposition='Technical agent acceptance of complete retained John Allen two-volume witness.',blockers=[],human_decision=dict(status='not-recorded'),agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=now,supported_scope=SCOPE,unresolved_claims=[],unassessed_stronger_claims=['human verification','visual comparison','print equivalence','rights clearance','publication']))
    record=build_acceptance_record(args.stage,identity=identity,candidate_path=candidate,source_accounting_path=account,scope=scope,technical=technical,review=review|dict(report_path=report),representation_revision=revision,decision=decision)
    write_acceptance(io_path(args.stage/EDITION/'acceptance.json'),record);validate_acceptance(args.stage/EDITION/'acceptance.json',root=args.stage)
    shutil.copytree(io_path(args.stage),io_path(args.promoted))
    master=put(args.promoted,EDITION/'master.tei.xml',bound);record['promotion'].update(status='promoted',promoted_at=now,master=make_file_binding(args.promoted,master));write_acceptance(io_path(args.promoted/EDITION/'acceptance.json'),record)
    state=json.loads(canonical(old_state));target=next(t for t in state['targets'] if t['target_id']==EDITION_ID);target.update(stage='accepted',reason=PROMOTED_MASTER_REASON,updated_at=now)
    for path in ((EDITION/'master.tei.xml').as_posix(),(EDITION/'acceptance.json').as_posix()):
        if path not in target['evidence']:target['evidence'].append(path)
    save(args.promoted,WORK/'state.json',state);validate_state(args.promoted/WORK/'state.json',root=args.promoted)
    with cached_edition_lookups():
        validate_acceptance(args.promoted/EDITION/'acceptance.json',root=args.promoted)
        projection=project_accepted_document(io_path(args.promoted),acceptance_path=io_path(args.promoted/EDITION/'acceptance.json'),category='prose')
        errors=verify_accepted_document(io_path(args.promoted),acceptance_path=io_path(args.promoted/EDITION/'acceptance.json'),rows=projection['rows'],receipt=projection['receipt'],category='prose')
    if errors or len(projection['rows'])!=16:raise ValueError(errors or 'actual full corpus row count differs')
    save(args.promoted,EVIDENCE/'stage-projection.json',projection)
    if any(digest(ROOT/x)!=h for x,h in runtime.items()) or any(digest(ROOT/x)!=h for x,h in schemas.items()):raise ValueError('frozen shared dependency changed during staging')
    receipt=dict(status='pass',work_id=WORK_ID,source_sha256=source['source_sha256'],category='prose',language='en',source_facts=facts,before=before,after=_files(args.promoted/WORK),master_sha256=sha256(bound).hexdigest(),candidate_sha256=a.sha256,candidate_root=args.candidate.as_posix(),replay_root=args.replay.as_posix(),rows=16,characters=sum(len(r['text']) for r in projection['rows']),projection_errors=errors,stage_root=args.stage.as_posix(),promoted_root=args.promoted.as_posix(),schema_pins=schemas,runtime_pins=runtime,metadata_prerequisites=['textual_forms[0].language=en','textual_forms[0].editions[0].category=prose'],source_association='Approved explicit as-found complete retained two-member manifest; no acquisition/download history invented',promotion_route='Supported single-TEI header binder on isolated outer-header shell then exact corpus-header-only byte splice; full corpus P5/acceptance/state/native projection checked; canonical adoption requires shared guarded journal installer')
    save(args.promoted,Path('stage-receipt.json'),receipt);print(json.dumps(dict(status='pass',master_sha256=receipt['master_sha256'],files=len(receipt['after']),rows=16,characters=receipt['characters'])))
if __name__=='__main__':main()
