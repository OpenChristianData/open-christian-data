"""Close one unchanged accepted witness using the supported current private routes."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories import prose as projector
from ocd_kernel.projection.categories import native_documents
from ocd_kernel.projection import native_content
from ocd_kernel.release.public_rows import public_rows_with_omissions
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader

ID='hodge-systematic-theology-vol-1'
WORK=Path('library/works')/ID
EDITION=WORK/'forms/hodge-systematic-theology-vol-1-english/editions/hodge-systematic-theology-vol-1-retained-electronic-witness'
PUB=WORK/'publication'
OUT=ROOT/'reports/_logs/hodge-vol1-private-release-20261002-v1'
EVIDENCE=Path('reports/_logs/hodge-vol1-current-reconciliation-20261002-v1')
MASTER_SHA='dd7b1e192c76ac52844d72e281c49e3730b872a2a94bc10308bab994d9bab106'
SOURCE=Path('raw/ccel/hodge/theology1.xml')
SOURCE_SHA='f01ffb5235657a0b21f56a1a4eb7ef95b836ba9d907f9acd1402e8a6fe450fc6'

def digest(path):return sha256(io_path(path).read_bytes()).hexdigest()
def read(path):return json.loads(io_path(path).read_bytes())
def save(path,record):
    p=io_path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')

def main():
    if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile existing completion first')
    before={(WORK/Path(p)).as_posix():h for p,h in _files(ROOT/WORK).items()}
    stable_evidence=[EVIDENCE/'staged-evidence-supplement.json',EVIDENCE/'staged-install-review.json',EVIDENCE/'coordinator-install-clearance.json',
        EVIDENCE/'rollback-proof/result.json',EVIDENCE/'rollback-proof/operation.json',
        EVIDENCE/'shared-span-proposal/coordinator-reviewed-freeze.json',
        Path('reports/_logs/hodge-vol1-coordinator-source-review-20261002-v1/source-envelope.json'),
        Path('reports/_logs/hodge-vol1-coordinator-source-review-20261002-v1/complete-wording-review.json'),
        Path('reports/_logs/hodge-vol1-install-20261002-v1/canonical/installed-audit.json'),
        Path('.tmp_audit/accepted-install-efc25b8820574789/operation.json'),
        Path('build/tools/stage_hodge_vol1_complete.py'),Path('build/tools/install_hodge_vol1_complete.py'),
        Path('build/tools/check_hodge_vol1_complete_mutations.py'),Path('build/tei/hodge_vol1_complete_reconstruction.py'),
        Path('build/tei/hodge_vol1_complete_oracle.py'),Path('tests/test_hodge_vol1_complete_install.py')]
    for p in stable_evidence:before[p.as_posix()]=digest(ROOT/p)
    for p,h in read(ROOT/EVIDENCE/'preflight.json')['input_bindings'].items():
        if p.startswith('library/works/'):continue
        if digest(ROOT/p)!=h:raise ValueError('Original non-work input drift: '+p)
        before[p]=h
    before[SOURCE.as_posix()]=digest(ROOT/SOURCE)
    # Preserve every existing source-local manifest/profile/notice, including historical acceptance inputs.
    for directory in ['sources/prose/hodge-systematic-theology-vol-1','sources/structured-text/hodge-systematic-theology-vol-1']:
        for p in io_glob(ROOT/directory,'**/*'):
            if p.is_file():before[p.relative_to(ROOT).as_posix()]=digest(p)
    implementations=['build/tools/complete_hodge_vol1_private_release.py','ocd_kernel/projection/categories/prose.py',
        'ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/categories/sermons.py',
        'ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py',
        'ocd_kernel/projection/scripture_authority.py','ocd_kernel/projection/scripture_targets.py','ocd_kernel/projection/scripture_targets_check.py',
        'ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/public_rows.py','ocd_kernel/release/notices.py',
        'ocd_kernel/release/typed_rows.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py',
        'ocd_kernel/library/identities.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/state.py','ocd_kernel/library/_common.py',
        'ocd_kernel/tei/acceptance.py']
    frozen={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/'schemas/v2','**/*.json')}
    frozen.update({p:digest(ROOT/p) for p in implementations})
    binding=dict(source_path='sources/prose/hodge-systematic-theology-vol-1/README.source.md',source_sha256=digest(ROOT/'sources/prose/hodge-systematic-theology-vol-1/README.source.md'),notice_path='data/prose/hodge-systematic-theology-vol-1/README.md',notice_sha256=digest(ROOT/'data/prose/hodge-systematic-theology-vol-1/README.md'))
    before[binding['notice_path']]=binding['notice_sha256']
    selection=dict(schema_version='2.0',release_id='hodge-vol1-private-offline-20261002-v1',items=[dict(
        item_id=ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[binding])])
    acceptance=ROOT/EDITION/'acceptance.json'
    notice=io_path(ROOT/binding['notice_path']).read_bytes()
    if notice_texts_for_item(ROOT,selection['items'][0],acceptance)!=[notice.decode()]:raise ValueError('Exact existing rich notice gate differs')
    OUT.mkdir(parents=True)
    save(OUT/'authority-before.json',before);save(OUT/'schema-implementation-before.json',frozen)
    save(OUT/'notice-gate.json',dict(status='pass',existing_source_credit_reused=True,source_directed_data_notice_prepared=True,binding=binding))
    save(OUT/'selection.json',selection);save(ROOT/PUB/'selection.json',selection)
    release=OUT/'release'
    with cached_edition_lookups():
        validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
        projection=projector.project_accepted_prose(ROOT,acceptance_path=acceptance)
        if not projection['rows'] or projection['receipt']['authority']['master']['sha256']!=MASTER_SHA:raise ValueError('Complete canonical master linkage differs')
        originals=(projector.project_accepted_prose,native_documents.project_accepted_document,native_content.project_content)
        def unavailable(*args,**kwargs):raise AssertionError('Producer disabled during independent verification')
        projector.project_accepted_prose=unavailable;native_documents.project_accepted_document=unavailable;native_content.project_content=unavailable
        try:errors=projector.verify_accepted_prose(ROOT,acceptance_path=acceptance,rows=projection['rows'],receipt=projection['receipt'])
        finally:projector.project_accepted_prose,native_documents.project_accepted_document,native_content.project_content=originals
        if errors:raise ValueError(errors)
        def walk(node):
            yield node
            for child in node.get('content',[]):
                if isinstance(child,dict):yield from walk(child)
        structures=[n for row in projection['rows'] for node in row['structure'] for n in walk(node)]
        counts={kind:sum(n.get('kind')==kind for n in structures) for kind in ('table','table-row','table-cell','note','page-break','anchor','source-reference')}
        if counts!={'table':3,'table-row':263,'table-cell':594,'note':610,'page-break':659,'anchor':7,'source-reference':2789} or sum('row_span' in n.get('attributes',{}) for n in structures)!=57 or len(projection['rows'])!=5:
            raise ValueError('Complete source-native table/span/note/link structure differs: '+str(counts))
        save(OUT/'actual-master-projection.json',projection)
        save(OUT/'projection-check.json',dict(status='pass',errors=[],rows=len(projection['rows']),master_sha256=MASTER_SHA,
            source_sha256=SOURCE_SHA,producer_disabled=True,unit_order=[r['record_id'] for r in projection['rows']],
            counts=counts,source_row_spans=57,source_roots=['i','ii','iii','iv','v'],scope=read(acceptance)['scope']['declared']))
        print('actual canonical full five-root master + independent producer-disabled checker: PASS',flush=True)
        assembled=assemble_release_v2(ROOT,release,selection=selection);save(OUT/'assembly.json',assembled)
        if assembled['status']!='pass':raise ValueError(assembled)
        print('assembly: PASS',flush=True)
        for name,action in [('independent-verification',lambda:verify_release_v2(ROOT,release,selection=selection)),
                            ('statistics',lambda:release_statistics(ROOT,release,selection)),('readers',lambda:check_reader(ROOT,release,selection))]:
            result=action();save(OUT/(name+'.json'),result)
            if result['status']!='pass':raise ValueError(result)
            print(name+': PASS',flush=True)
    visible=io_path(release/'public/README.md').read_bytes()
    if notice.rstrip() not in visible:raise ValueError('Released visible source/rights credit differs')
    save(OUT/'released-notice-check.json',dict(status='pass',exact_source_directed_notice_embedded=True,public_readme_sha256=sha256(visible).hexdigest()))
    for mapping in (before,frozen):
        for p,h in mapping.items():
            if digest(ROOT/p)!=h:raise ValueError('Final current input drift: '+p)
    if digest(ROOT/SOURCE)!=SOURCE_SHA or digest(ROOT/EDITION/'master.tei.xml')!=MASTER_SHA:raise ValueError('Accepted source/master drift')
    files={p.relative_to(release).as_posix():digest(p) for p in io_glob(release,'**/*') if p.is_file()}
    save(OUT/'release-file-hashes.json',files)
    completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=ID,edition_id='hodge-systematic-theology-vol-1-retained-electronic-witness',
        source_sha256=SOURCE_SHA,accepted_master_sha256=MASTER_SHA,acceptance_sha256=digest(acceptance),rows=len(projection['rows']),
        text_characters=read(OUT/'statistics.json')['total']['text_characters'],release_path=release.as_posix(),
        private_offline=True,publication_performed=False,authority_bindings=before,schema_implementation_bindings=frozen,release_file_bindings=files,
        prior_evidence=dict(historical_sound_body_reused_with_exact_inverse=True,complete_five_root_scope_restored=True,source_acquisition_preserved=True,stable_review_bindings={p.as_posix():before[p.as_posix()] for p in stable_evidence}),
        actual_master_projection_and_independent_verification='pass',statistics_and_normal_streaming_readers='pass',exact_source_data_credit_visible=True,
        remaining=['Human textual acceptance not recorded','Historical edition and electronic transcription rights not independently cleared','Public publication not authorized'])
    save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion)
    io_path(ROOT/PUB/'README.md').write_text('# Hodge, Systematic Theology, volume I: private completion\n\nThe complete retained CCEL electronic volume includes all five source roots: title pages, CARD and full contents, Introduction, Theology Proper, and seven fully rendered indexes. The historical sound Introduction and Theology Proper are byte-equal after removing exactly eight source-backed cell annotations. All 594 cells, 57 row spans, 42 column spans, 263 rows, 2,165 index links, 610 notes and 659 page markers are conserved. Literal hrefs remain in reversible source evidence with an independently checked target crosswalk.\n\nActual canonical master projection, independent producer-disabled verification, private assembly, independent release verification, statistics and normal/streaming readers pass. Visible source and data notices credit Charles Hodge and CCEL, distinguish Tim Perrine staff description from volume contributor roles, and qualify literal 1940 Eerdmans title pages, the separate 1871 copyright entry, and electronic 2005 metadata. CCEL formatting/permission restrictions remain visible. Human textual acceptance, physical print collation, independent rights clearance and public publication remain separate. No source acquisition, OCR work, Git action or public publication occurred.\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='pass',rows=len(projection['rows']),authority_bindings=len(before),schema_implementation_bindings=len(frozen),release_files=len(files))),flush=True)

if __name__=='__main__':main()
