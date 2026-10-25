"""Resume unfinished release gates after the exact notice terminal-LF repair."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader
from build.tools import complete_modern_scepticism_private_release as prior

ROOT=prior.ROOT;LOG=prior.LOG;PUB=prior.PUB;BASE=prior.BASE;ID=prior.ID
OUT=ROOT/'reports/_logs/modern-scepticism-private-release-20261002-v2'
save=prior.save;read=prior.read;digest=prior.digest

def main():
    if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Fresh unfinished-gates output required')
    if (ROOT/LOG/'private-release-v1.exit').read_text().strip()!='1':raise ValueError('Original assembly failure exit not retained')
    old_notice_path=Path('data/prose')/ID/'README.md';path=ROOT/old_notice_path
    old=path.read_bytes();new=old.rstrip(b'\n')+b'\n'
    old_before=read(prior.OUT/'authority-before.json');frozen=read(prior.OUT/'schema-implementation-before.json')
    if sha256(old).hexdigest()!=old_before[old_notice_path.as_posix()] or old==new:raise ValueError('Only exact old multi-LF notice may change')
    for mapping in (old_before,frozen):
        for p,h in mapping.items():
            if digest(ROOT/p)!=h:raise ValueError('Prior proof input drift before notice correction:'+p)
    if read(prior.OUT/'projection-check.json')['status']!='pass':raise ValueError('Already-completed canonical independent check absent')
    projection=read(prior.OUT/'actual-master-projection.json')
    if digest(ROOT/prior.EDITION/'master.tei.xml')!=prior.MASTER_SHA or projection['receipt']['authority']['master']['sha256']!=prior.MASTER_SHA:raise ValueError('Actual master differs from completed proof')
    (ROOT/LOG/'data-notice.before-terminal-lf.md').write_bytes(old)
    path.write_bytes(new)
    repair={'status':'pass','allowed_delta':'Only extra terminal LF bytes removed; full notice/license wording unchanged. Paired source notice, accepted26-file generation, master/source/projection/runtime unchanged.',
        'data_notice_path':old_notice_path.as_posix(),'before_sha256':sha256(old).hexdigest(),'after_sha256':sha256(new).hexdigest(),
        'before_terminal_lf_count':len(old)-len(old.rstrip(b'\n')),'after_terminal_lf_count':1,'exact_body_before_terminal_lf_equal':old.rstrip(b'\n')==new.rstrip(b'\n'),
        'source_notice_sha256':digest(ROOT/BASE/'README.source.md'),'failed_v1_preserved':True,'no_completed_gates_repeated':True}
    save(ROOT/LOG/'notice-terminal-lf-repair.json',repair)
    before=dict(old_before);before[old_notice_path.as_posix()]=sha256(new).hexdigest()
    added=[LOG/'notice-terminal-lf-repair.json',LOG/'data-notice.before-terminal-lf.md',LOG/'private-release-v1.exit',LOG/'private-release-v1.log',
       LOG/'coordinator-installed-generation-review.json',prior.OUT.relative_to(ROOT)/'authority-before.json',prior.OUT.relative_to(ROOT)/'schema-implementation-before.json',
       prior.OUT.relative_to(ROOT)/'projection-check.json',prior.OUT.relative_to(ROOT)/'actual-master-projection.json']
    for p in added:before[p.as_posix()]=digest(ROOT/p)
    frozen['build/tools/resume_modern_scepticism_private_release.py']=digest(Path(__file__))
    binding=dict(source_path=(BASE/'README.source.md').as_posix(),source_sha256=digest(ROOT/BASE/'README.source.md'),notice_path=old_notice_path.as_posix(),notice_sha256=sha256(new).hexdigest())
    selection=dict(schema_version='2.0',release_id='modern-scepticism-private-offline-20261002-v2',items=[dict(item_id=ID,category='prose',acceptance_path=(prior.EDITION/'acceptance.json').as_posix(),public_notices=[binding])])
    if notice_texts_for_item(ROOT,selection['items'][0],io_path(ROOT/prior.EDITION/'acceptance.json'))!=[new.decode()]:raise ValueError('Corrected notice gate differs')
    OUT.mkdir(parents=True)
    save(OUT/'authority-before.json',before);save(OUT/'schema-implementation-before.json',frozen)
    save(OUT/'selection.json',selection);save(ROOT/PUB/'selection.json',selection)
    save(OUT/'notice-gate.json',dict(status='pass',binding=binding,terminal_lf_repair=repair))
    save(OUT/'actual-master-projection.json',projection);save(OUT/'projection-check.json',read(prior.OUT/'projection-check.json'))
    print('completed canonical producer-disabled proof reused with unchanged inputs: PASS',flush=True)
    release=OUT/'release'
    with cached_edition_lookups():
        result=assemble_release_v2(ROOT,release,selection=selection);save(OUT/'assembly.json',result)
        if result['status']!='pass':raise ValueError(result)
        print('assembly: PASS',flush=True)
        for name,action in [('independent-verification',lambda:verify_release_v2(ROOT,release,selection=selection)),('statistics',lambda:release_statistics(ROOT,release,selection)),('readers',lambda:check_reader(ROOT,release,selection))]:
            result=action();save(OUT/(name+'.json'),result)
            if result['status']!='pass':raise ValueError(result)
            print(name+': PASS',flush=True)
    visible=io_path(release/'public/README.md').read_bytes()
    if new.rstrip() not in visible:raise ValueError('Full released notice/terms differ')
    save(OUT/'released-notice-check.json',dict(status='pass',exact_full_notice_embedded=True,public_readme_sha256=sha256(visible).hexdigest()))
    for mapping in (before,frozen):
        for p,h in mapping.items():
            if digest(ROOT/p)!=h:raise ValueError('Final current input drift:'+p)
    files={p.relative_to(release).as_posix():digest(p) for p in io_glob(release,'**/*') if p.is_file()};save(OUT/'release-file-hashes.json',files)
    completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=ID,edition_id=ID+'-gutenberg-electronic',source_sha256=prior.SOURCE_SHA,
        accepted_master_sha256=prior.MASTER_SHA,acceptance_sha256=digest(ROOT/prior.EDITION/'acceptance.json'),rows=20,text_characters=read(OUT/'statistics.json')['total']['text_characters'],
        release_path=release.as_posix(),private_offline=True,publication_performed=False,authority_bindings=before,schema_implementation_bindings=frozen,release_file_bindings=files,
        actual_master_projection_and_independent_verification='pass',statistics_and_normal_streaming_readers='pass',exact_source_data_credit_visible=True,
        prior_evidence=dict(whole_source_proof_and_ten_mutations_reused=True,complete_body_conserved_after59_alias_inverse=True,source_acquisition_preserved=True,
           completed_canonical_proof_reused_without_rerun=True,notice_terminal_lf_repair=repair),source_normalized_characters=731071,
        count_qualification='Plain text differs through structured-note omission and whitespace, not narrowed scope.',remaining=['Human textual acceptance not recorded','Physical print collation not performed','Worldwide rights clearance not recorded','Public publication not authorized'])
    save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion)
    io_path(ROOT/PUB/'README.md').write_text('# Modern Scepticism: private completion\n\nThe complete retained volume includes four front units, eleven lectures and the explanatory paper, and four back units. All 181 structured notes, 526 page labels, 362 note links, 26 contents rows/40 cells and 33 rules are conserved. The historical full text becomes byte-identical after reversing only 59 native carrier aliases.\n\nThe canonical master and independent producer-disabled linkage proof pass. Private assembly, independent release verifier, statistics and normal/streaming readers pass with 20 rows and 674,384 plain-text characters. Complete source-normalized 731,071 includes note bodies and different block whitespace; the work scope is unchanged. Full retained Project Gutenberg terms and source/electronic credits are visible. A first failed assembly is retained; only terminal blank lines in the data notice were removed before resuming unfinished gates. Source, master, identities, acquisition and the paired source notice remain unchanged.\n\nHuman acceptance, physical print collation, worldwide rights clearance and public publication remain separate. No acquisition, OCR, Git or public publication occurred.\n',encoding='utf-8',newline='\n')
    print(prior.json.dumps(dict(status='pass',rows=20,authority_bindings=len(before),schema_implementation_bindings=len(frozen),release_files=len(files))),flush=True)

if __name__=='__main__':main()
