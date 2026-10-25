"""Resume only assembly onward after exact notice trailing-LF framing correction."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import json
from copy import deepcopy
import build.tools.complete_baltimore1_private_release as driver
from build.tools.prepare_baltimore1_private_release import ROOT,WORK,EDITION,DATA_NOTICE,LOG as PRELOG
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2

OUT=driver.LOG;PUB=driver.PUB;RELEASE=driver.RELEASE
digest=driver.digest;save=driver.save

def main():
    if (OUT/'completion.json').exists() or RELEASE.exists():raise FileExistsError('Resume targets already complete')
    terminal=json.loads((ROOT/PRELOG/'private-release-v2-terminal.json').read_bytes())
    failed=json.loads((OUT/'assembly.command.json').read_bytes())
    if terminal['exit_code']!=1 or failed['exit_code']!=2 or 'public notice is not a safe verbatim Markdown block' not in failed['stderr']:raise ValueError('Exact notice-only assembly failure absent')
    projection=json.loads((OUT/'actual-master-projection.json').read_bytes());linkage=json.loads((OUT/'independent-projection-linkage.json').read_bytes())
    if linkage['status']!='pass' or linkage['saved_projection_sha256']!=digest(OUT/'actual-master-projection.json') or linkage['accepted_master_sha256']!=digest(ROOT/EDITION/'master.tei.xml'):raise ValueError('Preserved completed projection/check changed')
    bound=json.loads((OUT/'authority-before.json').read_bytes());schemas=json.loads((OUT/'schemas-before.json').read_bytes())
    if any(digest(ROOT/p)!=h for p,h in bound.items()) or any(digest(ROOT/p)!=h for p,h in schemas.items()):raise ValueError('Original source/runtime/metadata evidence changed before bounded resume')
    old_notice=io_path(ROOT/DATA_NOTICE).read_bytes();old_selection=(PUB/'selection.json').read_bytes()
    (OUT/'notice-before-terminal-lf-fix.md').write_bytes(old_notice)
    (OUT/'selection-before-terminal-lf-fix.json').write_bytes(old_selection)
    (OUT/'private-driver-before-terminal-lf-fix.py').write_bytes((ROOT/'build/tools/complete_baltimore1_private_release.py').read_bytes())
    notice=old_notice.rstrip(b'\n')+b'\n'
    if notice==old_notice or notice.rstrip(b'\n')!=old_notice.rstrip(b'\n'):raise ValueError('Correction is not solely trailing LF framing')
    source=Path('sources/publication-pg14551-framed/baltimore-catechism-no-1/README.source.md')
    if (ROOT/source).exists():raise FileExistsError(ROOT/source)
    (ROOT/source).parent.mkdir(parents=True,exist_ok=True);(ROOT/source).write_bytes(notice)
    io_path(ROOT/DATA_NOTICE).write_bytes(notice)
    selected=json.loads(old_selection);selection=deepcopy(selected)
    binding=dict(source_path=source.as_posix(),source_sha256=sha256(notice).hexdigest(),notice_path=DATA_NOTICE.as_posix(),notice_sha256=sha256(notice).hexdigest())
    selection['items'][0]['public_notices']=[binding]
    (PUB/'selection.json').write_bytes((json.dumps(selection,ensure_ascii=True,indent=2,sort_keys=True)+'\n').encode())
    if notice_texts_for_item(ROOT,selection['items'][0],ROOT/EDITION/'acceptance.json')!=[notice.decode()]:raise ValueError('Corrected paired notice gate differs')
    changed={p for p,h in bound.items() if digest(ROOT/p)!=h}
    expected={DATA_NOTICE.as_posix(),(PUB/'selection.json').relative_to(ROOT).as_posix()}
    if changed!=expected:raise ValueError('Changes exceed exact data notice and selection: '+str(changed))
    qualified={p:digest(ROOT/p) for p in bound}
    for p in [source,Path(__file__).relative_to(ROOT)]:qualified[p.as_posix()]=digest(ROOT/p)
    save(OUT/'notice-framing-supplement.json',dict(status='pass',original_terminal_exit=1,original_assembly_exit=2,changed_paths=sorted(changed),
        before_notice_sha256=sha256(old_notice).hexdigest(),after_notice_sha256=sha256(notice).hexdigest(),removed_only_terminal_lf_count=len(old_notice)-len(notice),
        original_selection_sha256=sha256(old_selection).hexdigest(),corrected_selection_sha256=digest(PUB/'selection.json'),
        source_notice=binding,completed_projection_and_independent_check_repeated=False,source_master_acceptance_runtime_schema_unchanged=True,
        qualification='Only two terminal LF framing characters removed from a work-local Markdown notice. License wording is byte-identical before terminal framing; immutable full retained source/master unchanged. Original failed attempts/projection/check/selection/notice/driver bytes preserved.'))
    save(OUT/'qualified-authority-before.json',qualified);save(OUT/'corrected-selection.json',selection)
    common=['--root',str(ROOT),'--selection',str(PUB/'selection.json')]
    driver.command('assembly-resume','build.scripts.export_huggingface',[*common,'--output',str(RELEASE)])
    save(OUT/'assembly.json',json.loads((RELEASE/'internal/release-report.json').read_bytes()))
    with cached_edition_lookups():verified=verify_release_v2(ROOT,RELEASE,selection=selection)
    save(OUT/'independent-verification.json',verified)
    if verified['status']!='pass':raise ValueError(verified)
    args=[*common,'--release',str(RELEASE)]
    driver.command('separate-process-verification','build.tools.check_hf_release',args)
    driver.command('statistics','build.tools.report_release_stats',args)
    driver.command('readers','build.tools.check_release_reader',[*args,'--output',str(OUT/'readers.json')])
    if notice.rstrip() not in (RELEASE/'public/README.md').read_bytes():raise ValueError('Complete license/source note omitted')
    save(OUT/'released-notice-check.json',dict(status='pass',complete_notice_embedded=True,notice_sha256=sha256(notice).hexdigest()))
    observed={p:digest(ROOT/p) for p in qualified};schema_after={p:digest(ROOT/p) for p in schemas}
    if observed!=qualified or schema_after!=schemas:raise ValueError('Final exact qualified input/schema drift')
    save(OUT/'authority-after.json',observed);save(OUT/'schema-stability.json',dict(status='pass',before=schemas,after=schema_after))
    files={p.relative_to(RELEASE).as_posix():digest(p) for p in io_glob(RELEASE,'**/*') if io_path(p).is_file()};save(OUT/'release-file-hashes.json',files)
    result=dict(status='pass',private_offline=True,publication_performed=False,checked_at=datetime.now(timezone.utc).isoformat(),work_id='baltimore-catechism-no-1',rows=1,source_lines=2620,question_answer_groups=206,
        text_characters=len(projection['rows'][0]['text']),statistics=json.loads((OUT/'statistics.json').read_bytes())['total'],
        accepted_master_sha256=digest(ROOT/EDITION/'master.tei.xml'),acceptance_sha256=digest(ROOT/EDITION/'acceptance.json'),source_sha256='d4b49653b457cc11f39df004896d072892b534e49899def16cdd75761c80993e',
        saved_projection_sha256=digest(OUT/'actual-master-projection.json'),independent_linkage_sha256=digest(OUT/'independent-projection-linkage.json'),
        authority_bindings=observed,schema_implementation_bindings=schema_after,release_file_bindings=files,release_path=str(RELEASE),
        actual_master_projection_and_independent_verification='pass',statistics_and_normal_streaming_readers='pass',complete_source_data_credit_and_license_visible=True,
        completed_projection_checks_repeated=False,notice_framing_supplement=dict(path=(OUT/'notice-framing-supplement.json').relative_to(ROOT).as_posix(),sha256=digest(OUT/'notice-framing-supplement.json')),
        remaining=['Human acceptance and full visual proofreading','Composite electronic expression;1885print equivalence not established','Independent rights clearance and public publication authorization'])
    save(OUT/'completion.json',result);save(PUB/'completion.json',result)
    readme='# Baltimore Catechism No.1: private readiness complete\n\nOne complete unchanged accepted source-transcription record, all2,620physical lines/206question-answer groups, provider header/prayers/hymns/editorial1977note/endmarkers/fulllicense privately verified. Actual-master projection, producer-disabled saved linkage, both release verifiers/statistics/normal+streaming readers pass. Own primary contributor roles and full Project Gutenberg license are human-visible. Canonical selection/completion point to this exact private package. Two local notice-formatting failures remain dated; only notice path and trailing-LF framing were corrected, without source/master/runtime changes or repeated completed projection/source gates. Human acceptance, print equivalence, rights and public publication remain separate.\n'
    (PUB/'README.md').write_text(readme,encoding='utf-8');(OUT/'README.md').write_text(readme,encoding='utf-8')
    for p in io_glob(PUB,'**/*'):
        if io_path(p).is_file():observed[p.relative_to(ROOT).as_posix()]=digest(p)
    evidence={p.relative_to(OUT).as_posix():digest(p) for p in io_glob(OUT,'**/*') if io_path(p).is_file() and RELEASE not in p.parents}
    save(OUT/'final-delivery.json',dict(status='pass',authority=observed,schemas=schema_after,release=files,evidence=evidence))
    print(json.dumps(dict(status='pass',rows=1,source_lines=2620,question_answer_groups=206,text_characters=result['text_characters'],statistics=result['statistics'])),flush=True)

if __name__=='__main__':main()
