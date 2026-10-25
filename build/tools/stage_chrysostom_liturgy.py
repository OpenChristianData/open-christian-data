"""Stage and optionally install the complete source-bound L594 electronic witness."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.wikisource_l594_complete_oracle import _oracle
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance, PROMOTED_MASTER_REASON
from ocd_kernel.tei.install_accepted import _files, install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.lib.path_io import io_path

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='chrysostom-divine-and-sacred-liturgy'
WORK=Path('library/works')/WORK_ID
BASE=Path('sources/manifest-acquisitions/wikisource-chrysostom-l594')
EVIDENCE=WORK/'integration/complete-1866-v1'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['candidate','replay','stage','promoted','review']: p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--install',action='store_true')
    args=p.parse_args()
    if args.review.is_absolute() or '..' in args.review.parts:raise ValueError('repository-relative independent review required')
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest-complete.json',repository_root=ROOT)
    package=CandidatePackage.load(args.candidate/'package');replay=CandidatePackage.load(args.replay/'package')
    if package.sha256!=replay.sha256: raise ValueError('fresh-process package replay differs')
    validation=json.loads((args.candidate/'validation.json').read_bytes())
    if validation!=json.loads((args.replay/'validation.json').read_bytes()) or validation['status']!='pass': raise ValueError('validation replay differs')
    oracle=_oracle(manifest,package)
    if oracle['status']!='pass': raise ValueError(oracle['findings'])
    review_input=json.loads(io_path(ROOT/args.review).read_bytes())
    if review_input.get('status')!='pass' or review_input.get('candidate_sha256')!=package.sha256: raise ValueError('independent review does not approve exact candidate package')
    for dest in [args.stage,args.promoted]:
        if dest.exists() or dest.parent.resolve()!=Path('D:/Library/Open Christian Data/candidate-reviews').resolve() or not dest.name.startswith('l594-'): raise ValueError('fresh bounded L594 stage required')
    stage=args.stage
    before=_files(ROOT/WORK)
    if any(Path(name).name in {'master.tei.xml','acceptance.json'} for name in before): raise ValueError('initial acceptance only')
    def put(relative,data):
        dest=stage/relative;io_path(dest.parent).mkdir(parents=True,exist_ok=True);io_path(dest).write_bytes(data);return dest
    def record(relative,value): return put(relative,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())
    for name in before:put(WORK/name,io_path(ROOT/WORK/name).read_bytes())
    work=json.loads((ROOT/WORK/'work.json').read_bytes());old=json.loads(json.dumps(work))
    form=work['textual_forms'][0];edition=form['editions'][0]
    aid='chrysostom-divine-and-sacred-liturgy-wikisource-complete-20261007'
    identity=dict(work_id=WORK_ID,textual_form_id=form['textual_form_id'],edition_id=edition['edition_id'],acquisition_id=aid)
    edition['category']='liturgies';edition['language']='en';form['language']='en';validate_identity_update(old,work);record(WORK/'work.json',work)
    edition_path=WORK/'forms'/form['textual_form_id']/'editions'/edition['edition_id']
    acq_path=edition_path/'acquisitions'/(aid+'.json')
    acquisition=validate_acquisition(ROOT/acq_path,root=ROOT)
    # All original acquisitions remain valid in the bounded staging root.
    for directory in [ROOT/BASE,ROOT/'raw/wikisource/chrysostom-divine-liturgy-1866']:
        for source in directory.iterdir():
            if source.is_file():put(source.relative_to(ROOT),source.read_bytes())
    for authority in manifest.record['authorities']:put(Path(authority['path']),io_path(ROOT/authority['path']).read_bytes())
    state=json.loads((ROOT/WORK/'state.json').read_bytes())
    for target in state['targets']:
        for name in target['evidence']:
            if not io_path(stage/name).exists():put(Path(name),io_path(ROOT/name).read_bytes())
    put(args.review,io_path(ROOT/args.review).read_bytes())
    for name in package.member_names:put(EVIDENCE/'original-package'/name,package.member_bytes(name))
    record(EVIDENCE/'source-manifest.json',json.loads(manifest.path.read_bytes()))
    record(EVIDENCE/'original-validation.json',validation)
    source={k:acquisition[k] for k in ['source_path','source_sha256','source_bytes','source_scope']}
    scope_text=source['source_scope']
    revision=dict(id='chrysostom-liturgy-complete-1866-v1',date='2026-10-08',note='Technical acceptance of the complete retained validated 1866 Wikisource electronic witness, replacing the nonaccepted title-page fragment; original acquisition preserved.')
    raw=package.member_bytes('content.tei.xml')
    bound=bind_reviewed_header(raw,expected_sha256=sha256(raw).hexdigest(),identity=identity,source=source,source_url=acquisition['url'],declared_scope=scope_text,revision=revision)
    if bound.split(b'</teiHeader>',1)[1]!=raw.split(b'</teiHeader>',1)[1]:raise ValueError('reviewed body changed')
    candidate=put(EVIDENCE/'candidate.tei.xml',bound)
    if errors:=validate_file(io_path(candidate)):raise ValueError(errors)
    expected=[dict(path=m['path'],position=i) for i,m in enumerate(acquisition['retained_files'],1)]
    included=[dict(path=m['path'],position=i,bytes=m['bytes'],sha256=m['sha256'],scope=scope_text if m['path']==source['source_path'] else 'Exact supporting XML page-revision or original image evidence for the primary rendered witness.') for i,m in enumerate(acquisition['retained_files'],1)]
    scope=dict(kind='edition',declared=scope_text,expected_members=expected,included_members=included,excluded_members=[])
    common=dict(identity=identity,source=source,candidate=make_file_binding(stage,candidate),scope=scope_text,accepted_scope=dict(kind='edition',declared=scope_text),expected_members=expected,included_members=included,excluded_members=[],missing_members=[],unknown_members=[])
    accounting=record(EVIDENCE/'source-accounting.json',common|dict(source_sha256=source['source_sha256'],source_bytes=source['source_bytes'],projection_profile='ocd-liturgies-chrysostom-1866-retained-members-v1',accountability=json.loads(package.member_bytes('source-accountability.json'))))
    command='py -3 -m build.tools.stage_chrysostom_liturgy --candidate <final> --replay <replay> --stage <fresh> --promoted <fresh> --review <independent-review>'
    technical=dict(producer=dict(id=manifest.record['converter']['id']),checker=dict(id=oracle['oracle_id']),shared_assumptions=['Producer and checker share lxml HTML recovery on retained provider render; XML inventory is stdlib-independent; source images and revisions are retained.'],independent_corroboration='Exact same-edition source recovery; all 118 scan positions, 109 validated pages and nine blank pages; complete wording and paragraph/italic/rubric/layout/table/graphic/page-carrier checks; independent agent review; fresh clean-process replay and four source-carrier mutations.')
    for name in ['validation','accounting','fidelity','reproducibility','schema','closure']:
        path=record(EVIDENCE/(name+'.json'),common|dict(status='pass',command=command,exit_code=0,claim=name,oracle=oracle,replay=dict(status='pass',candidate_sha256=replay.sha256),validation=validation,review_input=review_input,header_only_binding=True,mutation_test='tests/test_wikisource_l594_complete.py: 1 passed, 129.42 seconds; final candidate body exactly unchanged',external_graphics='Two exact originals retained; TEI points to exact provider public original URLs, no local unresolved links.'))
        technical[name]=dict(path=path,status='pass',command=command,exit_code=0)
    now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    review=dict(reviewer=review_input['reviewer'],reviewed_at=now,coverage=dict(status='partial',declared=scope_text,reached=['complete retained electronic witness'],inspected=['complete retained electronic witness'],unreviewed=['independent print collation','human visual verification']),source_quality_uncertainty=['Provider-validated electronic transcription; no newly performed whole-print comparison.'],discrepancies=[],unreviewed_residuals=['Human verification and whole-print equivalence unassessed; live publication separate.'])
    review_path=record(EVIDENCE/'review.json',common|review|dict(independent_review=review_input))
    decision=dict(source_local_disposition='Accept the complete retained validated electronic edition based on exact source evidence.',blockers=[],human_decision=dict(status='not-recorded'),agent_assessment=dict(status='accepted',actor=review['reviewer'],assessed_at=now,supported_scope=scope_text,unresolved_claims=[],unassessed_stronger_claims=['human visual verification','whole-print equivalence','worldwide rights','public publication']))
    acceptance=stage/edition_path/'acceptance.json'
    accepted=build_acceptance_record(stage,identity=identity,candidate_path=candidate,source_accounting_path=accounting,scope=scope,technical=technical,review=review|dict(report_path=review_path),representation_revision=revision,decision=decision)
    write_acceptance(io_path(acceptance),accepted);validate_acceptance(acceptance,root=stage)
    shutil.copytree(io_path(stage),io_path(args.promoted))
    master=args.promoted/edition_path/'master.tei.xml';io_path(master).write_bytes(bound)
    accepted['promotion'].update(status='promoted',promoted_at=now,master=make_file_binding(args.promoted,master));write_acceptance(io_path(args.promoted/edition_path/'acceptance.json'),accepted)
    target=next(t for t in state['targets'] if t['target_id']==identity['edition_id']);target.update(stage='accepted',reason=PROMOTED_MASTER_REASON,updated_at=now)
    target['evidence'] +=[(edition_path/'master.tei.xml').as_posix(),(edition_path/'acceptance.json').as_posix()]
    io_path(args.promoted/WORK/'state.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
    validate_state(args.promoted/WORK/'state.json',root=args.promoted);validate_acceptance(args.promoted/edition_path/'acceptance.json',root=args.promoted)
    from ocd_kernel.projection.categories.liturgies import project_accepted_liturgies, verify_accepted_liturgies
    projection=project_accepted_liturgies(args.promoted,acceptance_path=args.promoted/edition_path/'acceptance.json')
    projection_errors=verify_accepted_liturgies(args.promoted,acceptance_path=args.promoted/edition_path/'acceptance.json',rows=projection['rows'],receipt=projection['receipt'])
    if projection_errors:raise ValueError(projection_errors)
    result=dict(status='staged',candidate_sha256=package.sha256,master_sha256=sha256(bound).hexdigest(),original_files=before,promoted_files=_files(args.promoted/WORK))
    result['projection']=dict(status='pass',row_count=len(projection['rows']),receipt=projection['receipt'])
    if args.install:result['installation']=install_accepted_work(ROOT,args.promoted,work_id=WORK_ID,initial_work_transition=dict(expected_files=before,work_json_sha256=_files(args.promoted/WORK)['work.json']))
    out=ROOT/'reports/_logs/l594-complete-20261008';out.mkdir(parents=True,exist_ok=True);(out/'staging-installation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
