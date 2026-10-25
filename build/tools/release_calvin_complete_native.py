"""Verify the canonical actual master and finish one private offline Calvin release."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from build.tools.prepare_calvin_complete_native import ROOT,WORK_ID,WORK,EDITION,BASE,NOTICE_BASE,DATA_NOTICE,LOGS,SCOPE,canonical
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.native_documents import verify_accepted_document
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader
PUB=WORK/'publication';OUT=Path('D:/Library/Open Christian Data/reports/_logs/calvin-institutes-private-release-20261001-v2')
PRIOR_OUT=Path('D:/Library/Open Christian Data/reports/_logs/calvin-institutes-private-release-20261001-v1')
# The sealed reconstruction notice is unchanged. This separate release pair
# changes only its directed data path and canonical one-LF terminal padding.
NOTICE_BASE=Path('sources/private-pg-allen-calvin-notice-v2')/WORK_ID
DATA_NOTICE=Path('data/prose')/WORK_ID/'private-offline-20261001-v2/README.md'
INSTALL=Path('reports/_logs/calvin-institutes-install-20261001-v1')
EVIDENCE=WORK/'integration/pg-allen-two-volume-native-v1'
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def read(p):return json.loads(io_path(p).read_bytes())
def save(p,v):q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(canonical(v))
def main():
    if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('reconcile existing release before regeneration')
    pin=read(ROOT/BASE/'stage-pin.json');staged=Path(pin['receipt']);stage=read(staged)
    core={p:h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
    if digest(staged)!=pin['receipt_sha256'] or stage['status']!='pass' or stage['rows']!=16 or core!=stage['after']:raise ValueError('installed frozen generation differs')
    installation=read(ROOT/INSTALL/'canonical/installation.json')
    if installation['status']!='installed-and-validated' or installation['installed_files']!=stage['after']:raise ValueError('guarded installation receipt differs')
    authority={(WORK/rel).as_posix():h for rel,h in stage['after'].items()}
    manifest=read(ROOT/BASE/'source-manifest.json')
    authority[(BASE/'source-manifest.json').as_posix()]=digest(ROOT/BASE/'source-manifest.json')
    for item in manifest['authorities']:authority[item['path']]=item['sha256']
    for rel in ('ir/calvin/calvins-institutes.gutenberg.tei.xml','metadata/source-evidence/catalog/calvins-institutes.json'):
        authority[rel]=digest(ROOT/rel)
    authority[(DATA_NOTICE).as_posix()]=digest(ROOT/DATA_NOTICE)
    authority[(NOTICE_BASE/'README.source.md').as_posix()]=digest(ROOT/NOTICE_BASE/'README.source.md')
    implementations=['ocd_kernel/projection/categories/prose.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/notices.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py','ocd_kernel/tei/acceptance.py','ocd_kernel/library/state.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/tei/reviewed_integration.py','build/tei/calvin_institutes_complete_native.py','build/tei/calvin_institutes_complete_native_oracle.py','build/tei/calvins_institutes_reconstruction.py','build/tei/calvins_institutes_oracle.py']
    frozen={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/'schemas/v2','**/*.json')}|{p:digest(ROOT/p) for p in implementations}
    if any(frozen[p]!=h for p,h in stage['schema_pins'].items()) or any(frozen[p]!=h for p,h in stage['runtime_pins'].items()):raise ValueError('current reviewed schema/runtime differs from stage')
    for p,h in authority.items():
        if digest(ROOT/p)!=h:raise ValueError('canonical authority/source evidence changed '+p)
    OUT.mkdir(parents=True);save(OUT/'authority-before.json',authority);save(OUT/'schema-implementation-before.json',frozen)
    source=NOTICE_BASE/'README.source.md';accepted_path=ROOT/EDITION/'acceptance.json'
    selection=dict(schema_version='2.0',release_id='calvin-allen-two-volume-private-offline-20261001-v2',items=[dict(item_id=WORK_ID,category='prose',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[dict(source_path=source.as_posix(),source_sha256=digest(ROOT/source),notice_path=DATA_NOTICE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTICE))])])
    save(ROOT/PUB/'selection.json',selection);save(OUT/'selection.json',selection)
    notices=notice_texts_for_item(ROOT,selection['items'][0],accepted_path)
    if len(notices)!=1 or notices[0].count('START: FULL LICENSE')!=2 or 'John Allen' not in notices[0]:raise ValueError('own exact paired credit/license notice differs')
    acq=read(ROOT/EDITION/'acquisitions/calvins-institutes-retained-source.json');footer_pins=[]
    for member in acq['retained_files']:
        raw=io_path(ROOT/member['path']).read_bytes().decode('utf-8-sig');start=raw.find('*** END OF THE PROJECT GUTENBERG EBOOK')
        if start<0:raise ValueError('provider footer not found')
        footer=raw[start:].replace('\r\n','\n').rstrip('\n')
        if footer not in notices[0]:raise ValueError('literal complete source footer missing')
        footer_pins.append(dict(source_path=member['path'],footer_text_sha256=sha256(footer.encode()).hexdigest(),complete_footer_visible=True))
    save(OUT/'notice-gate.json',dict(status='pass',paired_notice_bytes=len(notices[0].encode()),footer_bindings=footer_pins))
    projection=read(ROOT/EVIDENCE/'stage-projection.json');release=OUT/'release'
    with cached_edition_lookups():
        accepted=validate_acceptance(accepted_path,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
        prior_check=read(PRIOR_OUT/'projection-check.json')
        for name,h in read(PRIOR_OUT/'authority-before.json').items():
            if digest(ROOT/name)!=h:raise ValueError('previous canonical correspondence authority changed '+name)
        if read(PRIOR_OUT/'schema-implementation-before.json')!=frozen:raise ValueError('previous canonical correspondence runtime changed')
        if prior_check['status']!='pass' or prior_check['errors'] or projection!=read(PRIOR_OUT/'actual-master-projection.json'):raise ValueError('saved passing canonical correspondence differs')
        errors=prior_check['errors']
        master=digest(ROOT/EDITION/'master.tei.xml')
        if errors or len(projection['rows'])!=16 or projection['receipt']['master_sha256']!=master or projection['receipt']['authority']['master']['sha256']!=master:raise ValueError(errors or 'canonical actual full master binding differs')
        save(OUT/'actual-master-projection.json',projection);save(ROOT/PUB/'actual-master-projection.json',projection)
        save(OUT/'projection-check.json',dict(status='pass',errors=errors,rows=16,characters=sum(len(r['text']) for r in projection['rows']),full_master_sha256=master,receipt_document_sha256=projection['receipt']['master_sha256'],receipt_authority_master_sha256=projection['receipt']['authority']['master']['sha256'],synthetic_projection_document_used=False,prior_canonical_correspondence_reused=True,prior_proof_path=(PRIOR_OUT/'projection-check.json').as_posix(),prior_proof_sha256=digest(PRIOR_OUT/'projection-check.json'),all_prior_authority_and_runtime_pins_current=True))
        print('Saved passing canonical actual full master correspondence reused with current pins: pass',flush=True)
        assembled=assemble_release_v2(ROOT,release,selection=selection);save(OUT/'assembly.json',assembled)
        if assembled['status']!='pass':raise ValueError(assembled)
        print('Private assembly: pass',flush=True)
        for name,operation in [('independent-verification',lambda:verify_release_v2(ROOT,release,selection=selection)),('statistics',lambda:release_statistics(ROOT,release,selection)),('readers',lambda:check_reader(ROOT,release,selection))]:
            result=operation();save(OUT/(name+'.json'),result)
            if result['status']!='pass':raise ValueError(result)
            print(name+': pass',flush=True)
    visible=io_path(release/'public/README.md').read_bytes();notice=io_path(ROOT/DATA_NOTICE).read_bytes()
    if notice.rstrip() not in visible:raise ValueError('actual released README lacks exact full paired credit and licenses')
    save(OUT/'released-notice-check.json',dict(status='pass',exact_paired_notice_embedded=True,complete_both_retained_license_notices_visible=True,public_readme_sha256=sha256(visible).hexdigest()))
    for p,h in authority.items():
        if digest(ROOT/p)!=h:raise ValueError('final authority changed '+p)
    for p,h in frozen.items():
        if digest(ROOT/p)!=h:raise ValueError('final schema/runtime changed '+p)
    file_map={p.relative_to(release).as_posix():digest(p) for p in release.rglob('*') if p.is_file()};save(OUT/'release-file-hashes.json',file_map)
    stats=read(OUT/'statistics.json')
    if stats['total']['text_characters']!=3739015:raise ValueError('complete source-derived release text count differs')
    corroborations=['coordinator-acquisition-association-review.json','coordinator-diagnostic-body-review.json','coordinator-adapter-review.json','oracle-api-repair-binding.json','coordinator-staged-corpus-review.json']
    evidence={p.relative_to(OUT).as_posix():digest(p) for p in OUT.glob('*.json')}
    additional={}
    for n in corroborations:
        p=ROOT/LOGS/n
        if io_path(p).exists():additional[(LOGS/n).as_posix()]=digest(p)
    for p in [ROOT/LOGS/'adapter-boundary-proof.json',ROOT/LOGS/'adapter-namespace-proof.json',ROOT/LOGS/'notice-v2-repair.json',ROOT/INSTALL/'isolated-rollback/rollback-proof.json',ROOT/INSTALL/'canonical/installation.json',ROOT/INSTALL/'canonical/prerequisite.json',ROOT/INSTALL/'canonical/coordinator-installed-and-prerequisite-review.json',Path('D:/Library/Open Christian Data/candidate-reviews/calvin-institutes-complete-native-20261001-v2/header-replay-v2/proof.json')]:additional[p.as_posix()]=digest(p)
    completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,scope=SCOPE,source_kind='retained-member-set',source_manifest_path=acq['source_path'],source_manifest_sha256=acq['source_sha256'],source_manifest_bytes=acq['source_bytes'],retained_raw_members=acq['retained_files'],raw_source_bytes=4060187,source_physical_lines=69897,accepted_master_sha256=master,rows=16,text_characters=3739015,private_offline=True,publication_performed=False,synthetic_projection_document_used=False,guarded_installation=installation['operation'],acquisition_change='exact approved as-found association to both already-retained sources; no download/acquisition date invented',metadata_change='exact missing form.language=en and edition.category=prose; all IDs/title preserved',source_tei_mapping='Existing complete source mapper reused readonly; generated envelope aliases are reversible, full source oracle retained unchanged',release_path=release.as_posix(),evidence_path=OUT.as_posix(),authority_bindings=authority,schema_implementation_bindings=frozen,release_evidence_bindings=evidence,release_file_bindings=file_map,independent_corroboration_bindings=additional,visible_source_data_credit_and_both_pg_licenses=True,statistics_and_normal_streaming_readers='pass',remaining=['Human textual/visual review not newly performed','Independent print collation not performed; literal source year labels remain unresolved','Worldwide rights clearance unresolved','Public publication not authorized or performed'])
    save(ROOT/PUB/'completion.json',completion);save(OUT/'completion.json',completion)
    print(json.dumps(dict(status='pass',completion=(PUB/'completion.json').as_posix(),rows=16,text_characters=3739015,authority_pins=len(authority),runtime_schema_pins=len(frozen))))
if __name__=='__main__':main()
