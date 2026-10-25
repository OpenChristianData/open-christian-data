"""Complete only PG38326's unchanged accepted literary master privately."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from lxml import html
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.projection.categories.prose import verify_accepted_prose
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader
ROOT=Path(__file__).resolve().parents[2]
WORK=Path('library/works/bede-ecclesiastical-history-of-england');PUB=WORK/'publication'
PRE=Path('reports/_logs/bede-pg38326-downstream-preflight-20261001')
OUT=Path('D:/Library/Open Christian Data/reports/_logs/bede-pg38326-private-release-20261001-v2')
SOURCE_NOTE=Path('sources/private-pg38326/bede-ecclesiastical-history-of-england/README.source.md')
DATA_NOTE=Path('data/prose/bede-ecclesiastical-history-of-england/README.md')
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def read(p):return json.loads(io_path(p).read_bytes())
def save(p,v):q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(canonical(v))
def main():
    if OUT.exists() or (ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile existing release first')
    pre=read(ROOT/PRE/'preflight.json');install=read(ROOT/PRE/'category-prerequisite-installation.json')
    if install['status']!='pass' or pre['prior_search']['exact_assigned_id_matches']:raise ValueError('Prior/install evidence differs')
    before=dict(pre['current_authority_bindings']);before[(WORK/'work.json').as_posix()]=install['after']['work.json']
    for p,h in before.items():
        if digest(ROOT/p)!=h:raise ValueError('Authority changed '+p)
    implementations=['ocd_kernel/projection/categories/prose.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/notices.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py','ocd_kernel/tei/acceptance.py','ocd_kernel/library/state.py','ocd_kernel/reconstruction/contract.py']
    frozen={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/'schemas/v2','**/*.json')}|{p:digest(ROOT/p) for p in implementations}
    freeze=read(ROOT/'reports/_logs/barclay-correction-choice-support-20261001/coordinator-reviewed-freeze.json')
    if any(frozen[p]!=h for p,h in freeze['runtime_bindings'].items()):raise ValueError('Reviewed freeze differs')
    OUT.mkdir(parents=True);save(OUT/'authority-before.json',before);save(OUT/'schema-implementation-before.json',frozen)
    for p,name in [(SOURCE_NOTE,'draft-source-README.md'),(DATA_NOTE,'draft-data-README.md')]:
        payload=io_path(ROOT/PRE/name).read_bytes();q=io_path(ROOT/p)
        if q.exists() and q.read_bytes()!=payload:raise FileExistsError('Maintained notice differs '+str(p))
        q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(payload);before[p.as_posix()]=digest(q)
    selection=dict(schema_version='2.0',release_id='bede-pg38326-private-offline-20261001-v2',items=[dict(item_id=WORK.name,category='prose',acceptance_path=pre['acceptance_path'],public_notices=[dict(source_path=SOURCE_NOTE.as_posix(),source_sha256=digest(ROOT/SOURCE_NOTE),notice_path=DATA_NOTE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTE))])])
    save(ROOT/PUB/'selection.json',selection);save(OUT/'selection.json',selection)
    acceptance=ROOT/pre['acceptance_path'];notices=notice_texts_for_item(ROOT,selection['items'][0],acceptance)
    source=html.fromstring(io_path(ROOT/pre['source_path']).read_bytes().decode('utf-8'));footer_nodes=source.xpath('//*[@id="pg-footer"]')
    if len(footer_nodes)!=1:raise ValueError('Not one actual retained footer')
    footer=''.join(footer_nodes[0].itertext()).replace('\r','').strip()+'\n'
    if sha256(footer.encode()).hexdigest()!=read(ROOT/PRE/'draft-notice-evidence.json')['footer_parsed_text_sha256']:raise ValueError('Retained footer draft binding differs')
    if len(notices)!=1 or footer not in notices[0] or 'A. M. Sellar' not in notices[0]:raise ValueError('Complete own footer/credits missing')
    save(OUT/'notice-gate.json',dict(status='pass',complete_retained_footer_visible=True,retained_footer_text_sha256=sha256(footer.encode()).hexdigest(),source_notice_sha256=digest(ROOT/SOURCE_NOTE),data_notice_sha256=digest(ROOT/DATA_NOTE),literary_master_unchanged=True))
    projection=read(ROOT/PRE/'canonical-actual-master-projection.json');release=OUT/'release'
    with cached_edition_lookups():
        validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
        errors=verify_accepted_prose(ROOT,acceptance_path=acceptance,rows=projection['rows'],receipt=projection['receipt'])
        if errors or len(projection['rows'])!=58 or projection['receipt']['master_sha256']!=pre['accepted_master_sha256'] or projection['receipt']['authority']['master']['sha256']!=pre['accepted_master_sha256']:raise ValueError(errors or 'Saved actual accepted master projection differs')
        save(OUT/'actual-master-projection.json',projection);save(ROOT/PUB/'actual-master-projection.json',projection)
        save(OUT/'projection-check.json',dict(status='pass',errors=errors,rows=58,characters=sum(len(r['text']) for r in projection['rows']),full_master_sha256=pre['accepted_master_sha256'],receipt_document_sha256=projection['receipt']['master_sha256'],receipt_authority_master_sha256=projection['receipt']['authority']['master']['sha256'],synthetic_projection_document_used=False,saved_canonical_projection_reused=True))
        print('Saved current canonical actual-master projection independently verified: pass',flush=True)
        assembly=assemble_release_v2(ROOT,release,selection=selection);save(OUT/'assembly.json',assembly)
        if assembly['status']!='pass':raise ValueError(assembly)
        for name,op in [('independent-verification',lambda:verify_release_v2(ROOT,release,selection=selection)),('statistics',lambda:release_statistics(ROOT,release,selection)),('readers',lambda:check_reader(ROOT,release,selection))]:
            result=op();save(OUT/(name+'.json'),result)
            if result['status']!='pass':raise ValueError(result)
            print(name+': pass',flush=True)
    visible=io_path(release/'public/README.md').read_bytes();notice=io_path(ROOT/DATA_NOTE).read_bytes()
    if notice.rstrip() not in visible:raise ValueError('Actual release lacks exact complete credit/license')
    save(OUT/'released-notice-check.json',dict(status='pass',exact_notice_embedded=True,complete_retained_footer_in_human_visible_readme=True,public_readme_sha256=sha256(visible).hexdigest()))
    for p,h in before.items():
        if digest(ROOT/p)!=h:raise ValueError('Final authority changed '+p)
    for p,h in frozen.items():
        if digest(ROOT/p)!=h:raise ValueError('Runtime changed '+p)
    files={p.relative_to(release).as_posix():digest(p) for p in release.rglob('*') if p.is_file()};save(OUT/'release-file-hashes.json',files);stats=read(OUT/'statistics.json')
    if stats['total']['text_characters']!=851417:raise ValueError('Full literal scope character count differs')
    evidence={p.relative_to(OUT).as_posix():digest(p) for p in OUT.glob('*.json')}
    completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,source_path=pre['source_path'],source_sha256=pre['source_sha256'],accepted_master_sha256=pre['accepted_master_sha256'],rows=58,text_characters=851417,release_path=release.as_posix(),evidence_path=OUT.as_posix(),private_offline=True,publication_performed=False,reconstruction_performed=False,master_source_acquisition_state_unchanged=True,only_authority_change='Authorized exact edition.category=prose guarded prerequisite; all other metadata preserved',category_installation_path=(PRE/'category-prerequisite-installation.json').as_posix(),category_installation_sha256=digest(ROOT/PRE/'category-prerequisite-installation.json'),authority_bindings=before,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,actual_master_projection_and_independent_verification='pass',statistics_and_normal_streaming_readers='pass',synthetic_projection_document_used=False,full_retained_pg_footer_visible=True,source_scope='Complete retained literary container: front matter, preface, BooksI–V, Continuation, index and1081footnotes; provider header/footer outside literarymaster, fullfooter carried as visible rights notice.',remaining=['Human textual/visual review not newly performed','Independent print collation not performed','Continuation attribution remains qualified as retained note1056','Independent rights clearance unresolved','Public publication not authorized or performed'])
    save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion)
    (ROOT/PUB/'README.md').write_text('# Bede PG38326 private offline completion\n\nThe existing complete accepted literary master is unchanged. Its normal native prose route emits58ordered records, with retained notes/page markers in structure. Independent verification, statistics and normal/streaming readers pass. Sellar/title/imprint/provider credits and the complete retained PGfooter/license are human-visible in the released README. Provider wrapper exclusion from the literary master remains explicit.\n\nOnly the authorized missing edition.category=prose prerequisite was added through locked, pinned journaled generation replacement; isolated failure injection restored the exact original generation. All other metadata, source, acquisition, state and accepted master remain unchanged. Existing source reconstruction receipts remain dated; no fresh reconstruction or old-proof reseal is claimed. Human/print/rights/Continuation attribution and public publication remain separate.\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='pass',rows=58,characters=851417,authority=len(before),schemas_and_implementations=len(frozen),completion_sha256=digest(ROOT/PUB/'completion.json'))))
if __name__=='__main__':main()
