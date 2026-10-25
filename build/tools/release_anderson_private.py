"""Finish the complete installed Anderson witness and all source context privately."""
import json,subprocess,sys
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from build.tools.prepare_anderson_current import ROOT,WORK_ID,WORK,EDITION,BASE,SOURCE,SOURCE_SHA,LOG,DATA_NOTICE,SCOPE,canonical
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
PUB=WORK/'publication';OUT=Path('D:/Library/Open Christian Data/reports/_logs/anderson-private-release-20261002-v1');INSTALL=Path('reports/_logs/anderson-install-20261002-v1/canonical')
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
 for directory in (ROOT/BASE,ROOT/LOG,ROOT/INSTALL,ROOT/'reports/_logs/anderson-current-reconciliation-20261002-v1'):
  for path in io_glob(directory,'**/*'):
   if io_path(path).is_file():authority[path.relative_to(ROOT).as_posix()]=digest(path)
 manifest=read(ROOT/BASE/'source-manifest.json');profile=read(ROOT/BASE/'profile.json')
 for item in manifest['authorities']:
  path=Path(item['path'])
  if item['name']=='work-identity':
   previous=ROOT/INSTALL/'original-generation'/path
   if digest(previous)!=item['sha256']:raise ValueError('Exact acquired work identity preimage missing')
   authority[previous.relative_to(ROOT).as_posix()]=digest(previous)
  else:
   if digest(ROOT/path)!=item['sha256']:raise ValueError('Retained manifest authority drift '+str(path))
   authority[path.as_posix()]=digest(ROOT/path)
 supplement=read(ROOT/LOG/'note-presentation-binding.json')
 for field in ('source_path','notice_path'):authority[supplement[field]]=digest(ROOT/supplement[field])
 for item in profile['context_bindings']:
  for field in ('source_path','notice_path'):authority[item[field]]=digest(ROOT/item[field])
 names=['build/tools/probe_anderson_current_route.py','build/tei/anderson_1864_new_testament.py','build/tei/brenton_septuagint.py','build/tei/anderson_current_reconstruction.py','build/tei/anderson_current_oracle.py','build/tools/prepare_anderson_current.py','build/tools/run_anderson_current.py','build/tools/package_anderson_current.py','build/tools/stage_anderson_current.py','build/tools/install_anderson_current.py','build/tools/replay_anderson_accepted.py','build/tools/anderson_context_annex.py','build/tools/check_anderson_saved_projection.py','build/tools/release_anderson_private.py','ocd_kernel/projection/categories/bible.py','ocd_kernel/projection/envelope.py','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/notices.py','ocd_kernel/release/typed_rows.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py','ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/reconstruction/contract.py']
 frozen=dict(stage['schema_pins'])|{p:digest(ROOT/p) for p in names}
 extra_schemas=['release-selection.schema.json','release-report.schema.json','source-metadata.schema.json']
 frozen.update({('schemas/v2/'+p):digest(ROOT/'schemas/v2'/p) for p in extra_schemas})
 for p in ['ocd_kernel/release/selection.py','ocd_kernel/release/features.py','ocd_kernel/release/work_metadata.py','ocd_kernel/release/public_allowlist.py','ocd_kernel/release/public_rows.py','build/lib/source_metadata.py']:
  frozen[p]=digest(ROOT/p)
 OUT.mkdir(parents=True);save(OUT/'authority-before.json',authority);save(OUT/'schema-implementation-before.json',frozen)
 acceptance=ROOT/EDITION/'acceptance.json';notice=io_path(ROOT/BASE/'README.source.md').read_bytes()
 if io_path(ROOT/DATA_NOTICE).read_bytes()!=notice or not notice.endswith(b'\n') or notice.endswith(b'\n\n'):raise ValueError('Paired notice/one-LF differs')
 selection=dict(schema_version='2.0',release_id='anderson-private-offline-20261002-v1',items=[dict(item_id=WORK_ID,category='bible',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[*stage['notices'],supplement])]);save(OUT/'selection.json',selection);save(ROOT/PUB/'selection.json',selection)
 with cached_edition_lookups():
  validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
  texts=notice_texts_for_item(ROOT,selection['items'][0],acceptance)
  expected_texts=[io_path(ROOT/b['notice_path']).read_text(encoding='utf-8') for b in selection['items'][0]['public_notices']]
  if texts!=expected_texts or len(texts)!=26 or any(x not in texts[0] for x in ['John Augustus Williams','English dress','Public Domain','1865','not authored footnotes','All2489nonverse']):raise ValueError('Visible exact source qualification/context missing')
  from build.tools.anderson_context_annex import parts
  from build.tei.anderson_current_oracle import context_check
  from types import SimpleNamespace
  actual=io_path(ROOT/EDITION/'master.tei.xml').read_bytes()
  generated=parts(actual)
  if len(generated)!=24 or generated!=[text.encode() for text in texts[1:25]]:raise ValueError('Complete companion is not exact actual accepted TEI generation')
  # Context observer needs only repository_root. Historical manifest authorities
  # were checked above, including exact pre-category work preimage.
  m=SimpleNamespace(repository_root=ROOT)
  context_facts=context_check(m,profile,actual)
  save(OUT/'notice-gate.json',dict(status='pass',bindings=selection['items'][0]['public_notices'],exact_one_terminal_lf=True,actual_accepted_tei_companion_generation='pass',independent_context_check=context_facts))
  # The saved actual staged projection binds the exact canonical generation; verify it afresh in the canonical context with producer disabled.
  projection=read(ROOT/WORK/'integration/anderson-retained-current-v1/stage-projection.json')
  if projection['receipt']['authority']['master']['sha256']!=MASTER_SHA or projection['receipt']['master_sha256']!=MASTER_SHA or len(projection['rows'])!=7946 or sum(len(r['text']) for r in projection['rows'])!=938720 or sum(r['text']=='' for r in projection['rows'])!=0:raise ValueError('Exact full master/literal verse binding differs')
  if sum(n['label'].startswith('Generated annotation: ') for r in projection['rows'] for n in r['notes'])!=121 or any(not any(n['label'].startswith('Generated source accounting (not an authored footnote): ') for n in r['notes']) for r in projection['rows']):raise ValueError('Explicit generated source annotations/accounting lost')
  save(OUT/'actual-master-projection.json',projection)
  argv=[sys.executable,'-m','build.tools.check_anderson_saved_projection','--root',str(ROOT),'--acceptance',str(acceptance),'--projection',str(OUT/'actual-master-projection.json'),'--output',str(OUT/'independent-projection-linkage.json')]
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
 position=0
 for text in texts:
  payload=text.rstrip().encode();found=visible.find(payload,position)
  if found<0:raise ValueError('Release lost/reordered complete visible source/context companion')
  position=found+len(payload)
 save(OUT/'released-notice-check.json',dict(status='pass',all26bound_notices_embedded_in_order=True,complete2489context_carriers=True,public_readme_sha256=sha256(visible).hexdigest()))
 for mapping in (authority,frozen):
  for p,h in mapping.items():
   if digest(ROOT/p)!=h:raise ValueError('Final binding drift '+p)
 save(OUT/'authority-after.json',authority);save(OUT/'schema-implementation-after.json',frozen)
 files={p.relative_to(release).as_posix():digest(p) for p in io_glob(release,'**/*') if io_path(p).is_file()};save(OUT/'release-file-hashes.json',files)
 evidence={p.relative_to(OUT).as_posix():digest(p) for p in OUT.glob('*.json')}
 completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,scope=SCOPE,books=27,textual_members=30,chapters=260,rows=7946,empty_source_slots=0,context_carriers=2489,context_parts=24,generated_source_annotations=121,public_notice_pairs=26,generated_note_prose_whitespace_normalized=True,exact_key_annotation_texts=23,normalized_supplied_note_explanations=98,text_characters=read(OUT/'statistics.json')['total']['text_characters'],accepted_master_sha256=MASTER_SHA,projection_document_sha256=projection['receipt']['master_sha256'],synthetic_projection_document_used=False,source_sha256=SOURCE_SHA,source_path=SOURCE.as_posix(),release_path=release.as_posix(),private_offline=True,publication_performed=False,authority_bindings=authority,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,source_body='Existing established producer TEI3e939 reused; independently source-checked all10435lines and semantic attachments. Reversible scaffold aliases preserve complete body byte inverse, 7946literal-whitespace verses and121explicit derived annotations. All2489nonverse carriers publicly embedded through24deterministic independently verified actual-accepted-TEI companion parts. Historical source manifest acquired work identity remains bound to exact guarded preimage; category-only prerequisite separately verified.',guarded_installation='Journaled category-only prerequisite and shared guarded initial install; isolated after-new-live rollback proof bound.',independent_projection_producer_disabled=True,statistics_and_normal_streaming_readers='pass',visible_repository_license_and_translation_qualification=True,remaining=['Human textual/visual acceptance not recorded','Print identity/date/revision/annotation coverage not collated','Underlying translation rights/jurisdiction clearance unassessed','Public publication not authorized or performed'])
 save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion);print(json.dumps(dict(status='pass',rows=7946,text_characters=completion['text_characters'],completion_sha256=digest(ROOT/PUB/'completion.json'),authority_bindings=len(authority),schema_implementation_bindings=len(frozen))))
if __name__=='__main__':main()
