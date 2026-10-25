"""Finish only unfinished checks after assembly succeeded before wrapper status error."""
from datetime import datetime, timezone
from pathlib import Path
import json
import build.tools.complete_baltimore1_private_release as driver
from build.tools.prepare_baltimore1_private_release import ROOT, EDITION, DATA_NOTICE, LOG as PRELOG
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release.verify import verify_release_v2

OUT=driver.LOG; PUB=driver.PUB; RELEASE=driver.RELEASE
digest=driver.digest; save=driver.save

def main():
    if (OUT/'completion.json').exists(): raise FileExistsError('Already complete')
    terminal_path=ROOT/PRELOG/'private-release-resume-v3-terminal.json'
    terminal=json.loads(terminal_path.read_bytes())
    assembly=json.loads((OUT/'assembly-resume.command.json').read_bytes())
    result=json.loads(assembly['stdout'])
    report=json.loads((RELEASE/'internal/release-report.json').read_bytes())
    if terminal['exit_code']!=1 or "KeyError: 'status'" not in terminal['stderr'] or assembly['exit_code']!=0 or result['assembly']!='pass' or result['verification']!='pass' or report['status']!='pass':
        raise ValueError('Exact post-success wrapper failure differs')
    qualified=json.loads((OUT/'qualified-authority-before.json').read_bytes())
    schemas=json.loads((OUT/'schemas-before.json').read_bytes())
    if any(digest(ROOT/p)!=h for p,h in qualified.items()) or any(digest(ROOT/p)!=h for p,h in schemas.items()): raise ValueError('Completed proof inputs drifted')
    for p in [Path(__file__).relative_to(ROOT),terminal_path.relative_to(ROOT)]: qualified[p.as_posix()]=digest(ROOT/p)
    save(OUT/'finish-authority-before.json',qualified)
    save(OUT/'assembly-wrapper-supplement.json',dict(status='pass',assembly_exit_code=0,assembly_report_sha256=digest(RELEASE/'internal/release-report.json'),failed_resume_terminal_sha256=digest(terminal_path),qualification='Assembly and its verification succeeded. The work-local command wrapper incorrectly required status instead of assembly/verification keys. Original driver and failure preserved; no assembly/projection/source checks repeated.'))
    save(OUT/'assembly.json',report)
    selection=json.loads((PUB/'selection.json').read_bytes())
    projection=json.loads((OUT/'actual-master-projection.json').read_bytes())
    with cached_edition_lookups(): verified=verify_release_v2(ROOT,RELEASE,selection=selection)
    save(OUT/'independent-verification.json',verified)
    if verified['status']!='pass': raise ValueError(verified)
    common=['--root',str(ROOT),'--selection',str(PUB/'selection.json')]
    args=[*common,'--release',str(RELEASE)]
    driver.command('separate-process-verification','build.tools.check_hf_release',args)
    driver.command('statistics','build.tools.report_release_stats',args)
    driver.command('readers','build.tools.check_release_reader',[*args,'--output',str(OUT/'readers.json')])
    notice=io_path(ROOT/DATA_NOTICE).read_bytes()
    if notice.rstrip() not in (RELEASE/'public/README.md').read_bytes(): raise ValueError('Complete notice omitted')
    save(OUT/'released-notice-check.json',dict(status='pass',complete_notice_embedded=True,notice_sha256=digest(ROOT/DATA_NOTICE)))
    observed={p:digest(ROOT/p) for p in qualified}; schema_after={p:digest(ROOT/p) for p in schemas}
    if observed!=qualified or schema_after!=schemas: raise ValueError('Final qualified inputs/schema drift')
    save(OUT/'authority-after.json',observed); save(OUT/'schema-stability.json',dict(status='pass',before=schemas,after=schema_after))
    files={p.relative_to(RELEASE).as_posix():digest(p) for p in io_glob(RELEASE,'**/*') if io_path(p).is_file()}
    save(OUT/'release-file-hashes.json',files)
    result=dict(status='pass',private_offline=True,publication_performed=False,checked_at=datetime.now(timezone.utc).isoformat(),work_id='baltimore-catechism-no-1',rows=1,source_lines=2620,question_answer_groups=206,text_characters=len(projection['rows'][0]['text']),statistics=json.loads((OUT/'statistics.json').read_bytes())['total'],accepted_master_sha256=digest(ROOT/EDITION/'master.tei.xml'),acceptance_sha256=digest(ROOT/EDITION/'acceptance.json'),source_sha256='d4b49653b457cc11f39df004896d072892b534e49899def16cdd75761c80993e',saved_projection_sha256=digest(OUT/'actual-master-projection.json'),independent_linkage_sha256=digest(OUT/'independent-projection-linkage.json'),authority_bindings=observed,schema_implementation_bindings=schema_after,release_file_bindings=files,release_path=str(RELEASE),actual_master_projection_and_independent_verification='pass',statistics_and_normal_streaming_readers='pass',complete_source_data_credit_and_license_visible=True,completed_projection_source_assembly_checks_repeated=False,notice_framing_supplement=dict(path=(OUT/'notice-framing-supplement.json').relative_to(ROOT).as_posix(),sha256=digest(OUT/'notice-framing-supplement.json')),assembly_wrapper_supplement_sha256=digest(OUT/'assembly-wrapper-supplement.json'),remaining=['Human acceptance and full visual proofreading','Composite electronic expression; 1885 print equivalence not established','Independent rights clearance and public publication authorization'])
    save(OUT/'completion.json',result); save(PUB/'completion.json',result)
    readme='# Baltimore Catechism No.1: private readiness complete\n\nOne complete unchanged accepted source-transcription record preserves all 2,620 physical lines and 206 question-answer groups, including provider wrapper, prayers, hymns, editorial context and full license. Actual-master projection, producer-disabled independent linkage, both release verifiers, statistics and normal/streaming readers pass. Primary contributor roles and the full Project Gutenberg license are human-visible. Local notice path/framing and command-wrapper failures remain dated; completed source, projection and assembly gates were not repeated. Canonical selection/completion identify this exact private package. Human acceptance, print equivalence, rights clearance and public publication remain separate.\n'
    (PUB/'README.md').write_text(readme,encoding='utf-8'); (OUT/'README.md').write_text(readme,encoding='utf-8')
    for p in io_glob(PUB,'**/*'):
        if io_path(p).is_file(): observed[p.relative_to(ROOT).as_posix()]=digest(p)
    evidence={p.relative_to(OUT).as_posix():digest(p) for p in io_glob(OUT,'**/*') if io_path(p).is_file() and RELEASE not in p.parents}
    save(OUT/'final-delivery.json',dict(status='pass',authority=observed,schemas=schema_after,release=files,evidence=evidence))
    print(json.dumps(dict(status='pass',rows=1,source_lines=2620,question_answer_groups=206,text_characters=result['text_characters'],statistics=result['statistics'])),flush=True)

if __name__=='__main__': main()
