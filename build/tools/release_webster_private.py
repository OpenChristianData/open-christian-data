"""Finish only the complete installed Webster electronic witness privately."""
import json,subprocess,sys
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from build.tools.prepare_webster_current import ROOT,WORK_ID,WORK,EDITION,BASE,SOURCE,SOURCE_SHA,LOG,DATA_NOTICE,SCOPE,canonical
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader
PUB=WORK/'publication';OUT=Path('D:/Library/Open Christian Data/reports/_logs/webster-private-release-20261002-v1');INSTALL=Path('reports/_logs/webster-install-20261002-v1/canonical')
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def read(p):return json.loads(io_path(p).read_bytes())
def save(p,v):
 q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(canonical(v))
def main():
 if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile existing completion')
 stage=read(ROOT/LOG/'stage-pin.json');MASTER_SHA=stage['master_sha256'];installed=read(ROOT/INSTALL/'installed-audit.json')['all_hashes'];current={p:h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
 if installed!=current or digest(ROOT/EDITION/'master.tei.xml')!=MASTER_SHA or digest(ROOT/SOURCE)!=SOURCE_SHA:raise ValueError('Installed authority differs')
 for p,h in stage['schema_pins'].items():
  if digest(ROOT/p)!=h:raise ValueError('Frozen schema/runtime differs '+p)
 authority={(WORK/Path(p)).as_posix():h for p,h in installed.items()}
 for directory in (ROOT/BASE,ROOT/LOG,ROOT/INSTALL,ROOT/'reports/_logs/webster-coordinator-source-review-20261002-v1'):
  for path in io_glob(directory,'**/*'):
   if io_path(path).is_file():authority[path.relative_to(ROOT).as_posix()]=digest(path)
 for p in [SOURCE,DATA_NOTICE,Path('sources/bible-text/webster/webster.source-manifest.json'),Path('build/tei/webster_reconstruction.py'),Path('build/tei/webster_oracle.py'),Path('raw/bible_databases/LICENSE'),Path('raw/bible_databases/README.md'),Path('reports/_logs/webster-coordinator-source-review-20261002-v1/review.json')]:authority[p.as_posix()]=digest(ROOT/p)
 names=['build/tei/webster_current_reconstruction.py','build/tei/webster_current_oracle.py','build/tools/prepare_webster_current.py','build/tools/run_webster_current.py','build/tools/package_webster_current.py','build/tools/stage_webster_current.py','build/tools/install_webster_current.py','build/tools/replay_webster_accepted.py','build/tools/check_webster_saved_projection.py','build/tools/release_webster_private.py','ocd_kernel/projection/categories/bible.py','ocd_kernel/projection/envelope.py','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/notices.py','ocd_kernel/release/typed_rows.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py','ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/reconstruction/contract.py']
 frozen=dict(stage['schema_pins'])|{p:digest(ROOT/p) for p in names}
 extra_schemas=['release-selection.schema.json','release-report.schema.json','source-metadata.schema.json']
 frozen.update({('schemas/v2/'+p):digest(ROOT/'schemas/v2'/p) for p in extra_schemas})
 for p in ['ocd_kernel/release/selection.py','ocd_kernel/release/features.py','ocd_kernel/release/work_metadata.py','ocd_kernel/release/public_allowlist.py','ocd_kernel/release/public_rows.py','build/lib/source_metadata.py']:
  frozen[p]=digest(ROOT/p)
 OUT.mkdir(parents=True);save(OUT/'authority-before.json',authority);save(OUT/'schema-implementation-before.json',frozen)
 acceptance=ROOT/EDITION/'acceptance.json';notice=io_path(ROOT/BASE/'README.source.md').read_bytes()
 if io_path(ROOT/DATA_NOTICE).read_bytes()!=notice or not notice.endswith(b'\n') or notice.endswith(b'\n\n'):raise ValueError('Paired notice/one-LF differs')
 selection=dict(schema_version='2.0',release_id='webster-private-offline-20261002-v1',items=[dict(item_id=WORK_ID,category='bible',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[stage['notice']])]);save(OUT/'selection.json',selection);save(ROOT/PUB/'selection.json',selection)
 with cached_edition_lookups():
  validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
  texts=notice_texts_for_item(ROOT,selection['items'][0],acceptance)
  if texts!=[notice.decode()] or any(x not in texts[0] for x in ['Copyright (c) 2024 Scrollmapper','Permission is hereby granted','66 ordered books','worldwide underlying-rights clearance']):raise ValueError('Visible source/license qualification missing')
  save(OUT/'notice-gate.json',dict(status='pass',binding=stage['notice'],exact_one_terminal_lf=True))
  # The saved actual staged projection binds the exact canonical generation; verify it afresh in the canonical context with producer disabled.
  projection=read(ROOT/WORK/'integration/webster-retained-current-v1/stage-projection.json')
  if projection['receipt']['authority']['master']['sha256']!=MASTER_SHA or projection['receipt']['master_sha256']!=MASTER_SHA or len(projection['rows'])!=31102 or any(r['text']=='' for r in projection['rows']):raise ValueError('Full master/source0empty binding differs')
  src=read(ROOT/SOURCE);expected=[(b['name'],c['chapter'],v['verse'],v['text']) for b in src['books'] for c in b['chapters'] for v in c['verses']]
  if expected!=[(r['locator']['book'],r['locator']['chapter'],r['locator']['verse'],r['text']) for r in projection['rows']]:raise ValueError('Source/public full ordered tuple mismatch')
  save(OUT/'actual-master-projection.json',projection)
  argv=[sys.executable,'-m','build.tools.check_webster_saved_projection','--root',str(ROOT),'--acceptance',str(acceptance),'--projection',str(OUT/'actual-master-projection.json'),'--output',str(OUT/'independent-projection-linkage.json')]
  try:result=subprocess.run(argv,cwd=ROOT,check=True,capture_output=True,text=True,encoding='utf-8')
  except subprocess.CalledProcessError as error:save(OUT/'independent-projection-command.json',dict(argv=argv,exit_code=error.returncode,stdout=error.stdout,stderr=error.stderr));raise
  save(OUT/'independent-projection-command.json',dict(argv=argv,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr));print('Canonical saved actual-master independent producer-disabled linkage: pass',flush=True)
  release=OUT/'release';assembled=assemble_release_v2(ROOT,release,selection=selection);save(OUT/'assembly.json',assembled)
  if assembled['status']!='pass':raise ValueError(assembled)
  print('Private assembly: pass',flush=True)
  for name,action in [('independent-verification',lambda:verify_release_v2(ROOT,release,selection=selection)),('statistics',lambda:release_statistics(ROOT,release,selection)),('readers',lambda:check_reader(ROOT,release,selection))]:
   value=action();save(OUT/(name+'.json'),value)
   if value['status']!='pass':raise ValueError(value)
   print(name+': pass',flush=True)
 visible=io_path(release/'public/README.md').read_bytes()
 if notice.rstrip() not in visible:raise ValueError('Release lost visible repository license/qualification')
 save(OUT/'released-notice-check.json',dict(status='pass',full_bound_notice_embedded=True,public_readme_sha256=sha256(visible).hexdigest()))
 for mapping in (authority,frozen):
  for p,h in mapping.items():
   if digest(ROOT/p)!=h:raise ValueError('Final binding drift '+p)
 save(OUT/'authority-after.json',authority);save(OUT/'schema-implementation-after.json',frozen)
 files={p.relative_to(release).as_posix():digest(p) for p in io_glob(release,'**/*') if io_path(p).is_file()};save(OUT/'release-file-hashes.json',files)
 evidence={p.relative_to(OUT).as_posix():digest(p) for p in OUT.glob('*.json')}
 completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,scope=SCOPE,books=66,chapters=1189,rows=31102,empty_source_slots=0,text_characters=read(OUT/'statistics.json')['total']['text_characters'],accepted_master_sha256=MASTER_SHA,projection_document_sha256=projection['receipt']['master_sha256'],synthetic_projection_document_used=False,source_sha256=SOURCE_SHA,source_path=SOURCE.as_posix(),release_path=release.as_posix(),private_offline=True,publication_performed=False,authority_bindings=authority,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,source_body='Unchanged historical mapper reproduced a complete source-derived d83 baseline because the disposable historical candidate is unavailable; exact header/66label inverse restores that fresh baseline. Independent complete source oracle and coordinator comparison bound. No claim of old package byte reproduction.',guarded_installation='Journaled category-only prerequisite and shared guarded initial install; isolated after-new-live rollback proof bound.',independent_projection_producer_disabled=True,statistics_and_normal_streaming_readers='pass',visible_repository_license_and_translation_qualification=True,remaining=['Human textual/visual acceptance not recorded','Print identity/date/revision/annotation coverage not collated','Underlying translation rights/jurisdiction clearance unassessed','Public publication not authorized or performed'])
 save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion);print(json.dumps(dict(status='pass',rows=31102,text_characters=completion['text_characters'],completion_sha256=digest(ROOT/PUB/'completion.json'),authority_bindings=len(authority),schema_implementation_bindings=len(frozen))))
if __name__=='__main__':main()
