"""Close the complete retained volume with current private supported routes."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories import prose as projector,native_documents
from ocd_kernel.projection import native_content
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader
from build.tools.prepare_modern_scepticism_current import ROOT,WORK_ID as ID,WORK,EDITION,BASE,LOG,SOURCE,SOURCE_SHA

PUB=WORK/'publication'
OUT=ROOT/'reports/_logs/modern-scepticism-private-release-20261002-v1'
MASTER_SHA='fb8d4b5c24eef296b3e0f33468056172751a7e47a2678e8dacc444bf903c6107'

def digest(path):return sha256(io_path(path).read_bytes()).hexdigest()
def read(path):return json.loads(io_path(path).read_bytes())
def save(path,record):
    p=io_path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')
def walk(n):
    yield n
    for c in n.get('content',[]):
        if isinstance(c,dict):yield from walk(c)

def main():
    if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile existing completion first')
    before={(WORK/Path(p)).as_posix():h for p,h in _files(ROOT/WORK).items()}
    stable=[LOG/'staged-install-review.json',LOG/'coordinator-install-clearance.json',LOG/'rollback-proof/result.json',LOG/'rollback-proof/operation.json',
        LOG/'whole-text-inverse-proof.json',LOG/'retained-package-reconciliation.json',LOG/'historical-mutation-receipt.json',LOG/'current-alias-mutations/result.json',
        LOG/'current-candidate-v2.exit',LOG/'current-replay-v2.exit',LOG/'stage-v1.exit',LOG/'install-prerequisites-v1.exit',
        Path('reports/_logs/modern-scepticism-coordinator-source-review-20261002-v1/alias-inverse-review.json'),
        Path('reports/_logs/modern-scepticism-install-20261002-v1/canonical/installed-audit.json'),
        Path('reports/_logs/modern-scepticism-install-20261002-v1/canonical/installation.json'),
        Path('build/tools/stage_modern_scepticism_current.py'),Path('build/tools/install_modern_scepticism_current.py'),
        Path('build/tools/check_modern_scepticism_current_mutations.py'),Path('build/tei/modern_scepticism_current_reconstruction.py'),
        Path('build/tei/modern_scepticism_current_oracle.py'),Path('tests/test_modern_scepticism_current_install.py')]
    for p in stable:before[p.as_posix()]=digest(ROOT/p)
    installation=read(ROOT/'reports/_logs/modern-scepticism-install-20261002-v1/canonical/installation.json')
    journal=Path(installation['operation'])/'operation.json'
    before[journal.relative_to(ROOT).as_posix()]=digest(journal)
    for path in [Path('reports/_logs/modern-scepticism-install-20261002-v1/installed-generation-review.json'),LOG/'canonical-install.exit',LOG/'friction-observations.json']:
        before[path.as_posix()]=digest(ROOT/path)
    for a in read(ROOT/BASE/'source-manifest.json')['authorities']:
        if digest(ROOT/a['path'])!=a['sha256']:raise ValueError('Frozen source/authority drift: '+a['path'])
        before[a['path']]=a['sha256']
    for directory in (BASE,Path('sources/structured-text')/ID,Path('sources/manifest-acquisitions/pg42957-modern-scepticism')):
        for p in io_glob(ROOT/directory,'**/*'):
            if p.is_file():before[p.relative_to(ROOT).as_posix()]=digest(p)
    implementations=['build/tools/complete_modern_scepticism_private_release.py','ocd_kernel/projection/categories/prose.py',
        'ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/categories/sermons.py',
        'ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py',
        'ocd_kernel/projection/scripture_authority.py','ocd_kernel/projection/scripture_targets.py','ocd_kernel/projection/scripture_targets_check.py',
        'ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/public_rows.py','ocd_kernel/release/notices.py',
        'ocd_kernel/release/typed_rows.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py',
        'ocd_kernel/library/identities.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/state.py','ocd_kernel/library/_common.py',
        'ocd_kernel/tei/acceptance.py']
    frozen={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/'schemas/v2','**/*.json')}
    frozen.update({p:digest(ROOT/p) for p in implementations})
    binding=dict(source_path=(BASE/'README.source.md').as_posix(),source_sha256=digest(ROOT/BASE/'README.source.md'),
                 notice_path=(Path('data/prose')/ID/'README.md').as_posix(),notice_sha256=digest(ROOT/'data/prose'/ID/'README.md'))
    before[binding['notice_path']]=binding['notice_sha256']
    selection=dict(schema_version='2.0',release_id='modern-scepticism-private-offline-20261002-v1',items=[dict(item_id=ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[binding])])
    acceptance=ROOT/EDITION/'acceptance.json';notice=io_path(ROOT/binding['notice_path']).read_bytes()
    if notice_texts_for_item(ROOT,selection['items'][0],io_path(acceptance))!=[notice.decode()]:raise ValueError('Maintained canonical notice gate differs')
    OUT.mkdir(parents=True)
    save(OUT/'authority-before.json',before);save(OUT/'schema-implementation-before.json',frozen)
    save(OUT/'notice-gate.json',dict(status='pass',complete_retained_PG_license_visible=True,binding=binding))
    save(OUT/'selection.json',selection);save(ROOT/PUB/'selection.json',selection)
    release=OUT/'release'
    with cached_edition_lookups():
        validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
        projection=read(ROOT/WORK/'integration/pg42957-complete-native-v1/stage-projection.json')
        if projection['receipt']['authority']['master']['sha256']!=MASTER_SHA or digest(ROOT/EDITION/'master.tei.xml')!=MASTER_SHA:raise ValueError('Actual canonical master linkage differs')
        originals=(projector.project_accepted_prose,native_documents.project_accepted_document,native_content.project_content)
        def unavailable(*args,**kwargs):raise AssertionError('Producer disabled during independent check')
        projector.project_accepted_prose=unavailable;native_documents.project_accepted_document=unavailable;native_content.project_content=unavailable
        try:errors=projector.verify_accepted_prose(ROOT,acceptance_path=acceptance,rows=projection['rows'],receipt=projection['receipt'])
        finally:projector.project_accepted_prose,native_documents.project_accepted_document,native_content.project_content=originals
        if errors:raise ValueError(errors)
        nodes=[n for row in projection['rows'] for s in row['structure'] for n in walk(s)]
        counts={k:sum(n.get('kind')==k for n in nodes) for k in ('table','table-row','table-cell','note','source-reference','horizontal-rule')}
        if counts!={'table':1,'table-row':26,'table-cell':40,'note':181,'source-reference':915,'horizontal-rule':33} or len(projection['rows'])!=20:raise ValueError('Complete native counts differ')
        units=[r['structure'][0]['attributes']['type'] for r in projection['rows']]
        expected=['project_gutenberg_header','title_page','preface','contents']+['lecture']*11+['explanatory_paper','footnotes','notes_and_printer','transcribers_notes','project_gutenberg_footer']
        if units!=expected:raise ValueError('Complete volume unit order differs')
        save(OUT/'actual-master-projection.json',projection)
        save(OUT/'projection-check.json',dict(status='pass',errors=[],producer_disabled=True,saved_projection_reused=True,
             canonical_master_equals_projected_promoted_master=True,master_sha256=MASTER_SHA,rows=20,unit_types=units,counts=counts,
             source_normalized_characters=731071,plain_text_characters=674384,count_qualification='All front/back units and structured notes retained; native plain text omits note bodies and uses distinct whitespace normalization.'))
        print('actual canonical master linkage + independent producer-disabled verification: PASS',flush=True)
        result=assemble_release_v2(ROOT,release,selection=selection);save(OUT/'assembly.json',result)
        if result['status']!='pass':raise ValueError(result)
        print('assembly: PASS',flush=True)
        for name,action in [('independent-verification',lambda:verify_release_v2(ROOT,release,selection=selection)),('statistics',lambda:release_statistics(ROOT,release,selection)),('readers',lambda:check_reader(ROOT,release,selection))]:
            result=action();save(OUT/(name+'.json'),result)
            if result['status']!='pass':raise ValueError(result)
            print(name+': PASS',flush=True)
    visible=io_path(release/'public/README.md').read_bytes()
    if notice.rstrip() not in visible:raise ValueError('Released complete notice differs')
    save(OUT/'released-notice-check.json',dict(status='pass',exact_full_notice_embedded=True,public_readme_sha256=sha256(visible).hexdigest()))
    for mapping in (before,frozen):
        for p,h in mapping.items():
            if digest(ROOT/p)!=h:raise ValueError('Final current input drift:'+p)
    files={p.relative_to(release).as_posix():digest(p) for p in io_glob(release,'**/*') if p.is_file()}
    save(OUT/'release-file-hashes.json',files)
    completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=ID,edition_id=ID+'-gutenberg-electronic',
        source_sha256=SOURCE_SHA,accepted_master_sha256=MASTER_SHA,acceptance_sha256=digest(acceptance),rows=20,
        text_characters=read(OUT/'statistics.json')['total']['text_characters'],release_path=release.as_posix(),
        private_offline=True,publication_performed=False,authority_bindings=before,schema_implementation_bindings=frozen,release_file_bindings=files,
        actual_master_projection_and_independent_verification='pass',statistics_and_normal_streaming_readers='pass',exact_source_data_credit_visible=True,
        prior_evidence=dict(whole_source_proof_and_ten_mutations_reused=True,complete_historical_body_conserved_after59_alias_inverse=True,source_acquisition_preserved=True),
        source_normalized_characters=731071,count_qualification='Plain-text count differs through structured-note omission and whitespace, not narrowed scope.',
        remaining=['Human textual acceptance not recorded','Physical print collation not performed','Worldwide rights clearance not recorded','Public publication not authorized'])
    save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion)
    io_path(ROOT/PUB/'README.md').write_text('# Modern Scepticism: private completion\n\nOne complete retained 1871 volume: provider start marker, title page, Harrowby preface, contents, eleven lectures, explanatory paper, footnotes, notes/printer, transcriber notes and provider end marker. The exact historical body is conserved after reversing 59 supported carrier aliases. All 181 structured notes, 526 page-label references, 362 note links, 26 table rows/40 cells and 33 rules remain. The 20 public rows have 674,384 plain-text characters; complete source-normalized 731,071 includes note bodies and different block whitespace. This count distinction does not narrow the work.\n\nCanonical accepted-master linkage, producer-disabled independent verification, private assembly, independent verifier, statistics and normal/streaming readers pass. Full retained Project Gutenberg license and primary/electronic credits are visible in source/data/release notices. The requesting society is not assigned aggregate authorship. Physical print collation, human acceptance, worldwide rights clearance and public publication remain separate. No source acquisition, OCR, Git or public publication occurred.\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(status='pass',rows=20,authority_bindings=len(before),schema_implementation_bindings=len(frozen),release_files=len(files))),flush=True)

if __name__=='__main__':main()
