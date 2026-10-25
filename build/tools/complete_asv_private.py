"""Complete unchanged accepted ASV using its recovered exact release projection."""
import json,subprocess,sys
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='asv';WORK=Path('library/works/asv');EDITION=WORK/'forms/english-asv/editions/retained-json'
BASE=Path('sources/asv-retained-release/asv');SOURCE=Path('raw/bible_databases/formats/json/ASV.json');SOURCE_SHA='0851e73ac46ae7ccaf1a8bb44beb359295df5eca04a578ea4d448eb7a641f9ae'
LOG=Path('reports/_logs/asv-existing-release-reconciliation-20261002-v1');DATA_NOTICE=Path('data/bible/asv/README.md')
SCOPE='Complete retained ASV JSON electronic witness: all66books/1189chapters/31102verses/4143242literalcharacters,0trueempty and16nonempty whitespace-only slots; unchanged accepted master, original native ordinal labels and IDs. Full literal source book names map to those keys in maintained visible context. Physical1901print, contributor allocation, human/rights/publication remain qualified.'
def canonical(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
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
PUB=WORK/'publication';OUT=Path('D:/Library/Open Christian Data/reports/_logs/asv-private-release-20261002-v1')
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def read(p):return json.loads(io_path(p).read_bytes())
def save(p,v):
 q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(canonical(v))
def main():
 if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile existing completion')
 MASTER_SHA='403c43be7281b1272ea7b50e4de6dff964294544de7c1eac75d140ec8519b0ca'
 installed={p:h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
 if digest(ROOT/EDITION/'master.tei.xml')!=MASTER_SHA or digest(ROOT/SOURCE)!=SOURCE_SHA:raise ValueError('Accepted authority differs')
 stage=dict(schema_pins={})
 schema_paths=[Path('schemas/v2')/n for n in ('work.schema.json','state.schema.json','acquisition.schema.json','acceptance.schema.json','public-row.schema.json','projection-receipt.schema.json','native-content.schema.json','categories/bible.schema.json')]
 schema_paths+=sorted(p.relative_to(ROOT) for p in (ROOT/'ocd_kernel/tei/vendor/xsd').rglob('*.xsd'))
 stage['schema_pins']={p.as_posix():digest(ROOT/p) for p in schema_paths}
 authority={(WORK/Path(p)).as_posix():h for p,h in installed.items()}
 for directory in (ROOT/BASE,ROOT/LOG,ROOT/'sources/bible-text/asv',ROOT/'reports/_logs/asv-coordinator-source-review-20261002-v1'):
  for path in io_glob(directory,'**/*'):
   if io_path(path).is_file():authority[path.relative_to(ROOT).as_posix()]=digest(path)
 for p in [SOURCE,DATA_NOTICE,Path('raw/bible_databases/LICENSE'),Path('raw/bible_databases/README.md')]:authority[p.as_posix()]=digest(ROOT/p)
 names=['build/tools/complete_asv_private.py','build/tools/check_asv_saved_projection.py','build/tei/asv_reconstruction.py','build/tei/asv_oracle.py','ocd_kernel/projection/categories/bible.py','ocd_kernel/projection/envelope.py','ocd_kernel/projection/scripture_authority.py','ocd_kernel/projection/scripture_targets.py','ocd_kernel/projection/scripture_targets_check.py','build/bible_data/osis_book_codes.json','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/notices.py','ocd_kernel/release/typed_rows.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py','ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/tei/reviewed_integration.py','ocd_kernel/tei/validate.py','ocd_kernel/library/identities.py','ocd_kernel/library/state.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/_common.py','ocd_kernel/lib/atomic_io.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/reconstruction/contract.py']
 frozen=dict(stage['schema_pins'])|{p:digest(ROOT/p) for p in names}
 extra_schemas=['release-selection.schema.json','release-report.schema.json','source-metadata.schema.json']
 frozen.update({('schemas/v2/'+p):digest(ROOT/'schemas/v2'/p) for p in extra_schemas})
 for p in ['ocd_kernel/release/selection.py','ocd_kernel/release/features.py','ocd_kernel/release/work_metadata.py','ocd_kernel/release/public_allowlist.py','ocd_kernel/release/public_rows.py','build/lib/source_metadata.py']:
  frozen[p]=digest(ROOT/p)
 OUT.mkdir(parents=True);save(OUT/'authority-before.json',authority);save(OUT/'schema-implementation-before.json',frozen)
 acceptance=ROOT/EDITION/'acceptance.json';notice=io_path(ROOT/BASE/'README.source.md').read_bytes()
 if io_path(ROOT/DATA_NOTICE).read_bytes()!=notice or not notice.endswith(b'\n') or notice.endswith(b'\n\n'):raise ValueError('Paired notice/one-LF differs')
 binding=dict(source_path=(BASE/'README.source.md').as_posix(),source_sha256=digest(ROOT/BASE/'README.source.md'),notice_path=DATA_NOTICE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTICE))
 selection=dict(schema_version='2.0',release_id='asv-private-offline-20261002-v1',items=[dict(item_id=WORK_ID,category='bible',acceptance_path=(EDITION/'acceptance.json').as_posix(),public_notices=[binding])]);save(OUT/'selection.json',selection);save(ROOT/PUB/'selection.json',selection)
 with cached_edition_lookups():
  validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
  texts=notice_texts_for_item(ROOT,selection['items'][0],acceptance)
  if texts!=[notice.decode()] or any(x not in texts[0] for x in ['Copyright (c) 2024 Scrollmapper','Permission is hereby granted','no true-empty source strings','16 nonempty whitespace-only','Literal source book name','configuration claims']):raise ValueError('Visible source/license qualification missing')
  save(OUT/'notice-gate.json',dict(status='pass',binding=binding,exact_one_terminal_lf=True,complete66literal_head_to_native_key_context=True))
  # Exact ASV rows and receipt reused from retained historical group outputs.
  projection=read(ROOT/LOG/'reused-actual-master-projection.json')
  if projection['receipt']['authority']['master']['sha256']!=MASTER_SHA or projection['receipt']['master_sha256']!=MASTER_SHA or len(projection['rows'])!=31102 or sum(r['text']=='' for r in projection['rows'])!=0 or sum(r['text']!='' and not r['text'].strip() for r in projection['rows'])!=16:raise ValueError('Exact full master/source blank distinctions differ')
  src=read(ROOT/SOURCE);expected=[(str(i),c['chapter'],v['verse'],v['text']) for i,b in enumerate(src['books'],1) for c in b['chapters'] for v in c['verses']]
  if expected!=[(r['locator']['book'],r['locator']['chapter'],r['locator']['verse'],r['text']) for r in projection['rows']]:raise ValueError('Complete public literal source tuple differs')
  linkage=read(ROOT/LOG/'current-producer-disabled-linkage.json')
  if linkage['status']!='pass' or not linkage['producer_disabled'] or len(linkage['cases'])!=6 or linkage['projection_sha256']!=digest(ROOT/LOG/'reused-actual-master-projection.json'):raise ValueError('Reused current independent projection proof differs')
  save(OUT/'independent-projection-linkage.json',linkage)
  save(OUT/'actual-master-projection.json',projection)
  print('Recovered actual-master projection/current producer-disabled linkage reused: pass',flush=True)
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
 completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,scope=SCOPE,books=66,chapters=1189,rows=31102,empty_source_slots=0,nonempty_whitespace_only_slots=16,text_characters=read(OUT/'statistics.json')['total']['text_characters'],accepted_master_sha256=MASTER_SHA,projection_document_sha256=projection['receipt']['master_sha256'],synthetic_projection_document_used=False,source_sha256=SOURCE_SHA,source_path=SOURCE.as_posix(),release_path=release.as_posix(),private_offline=True,publication_performed=False,authority_bindings=authority,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,source_body='Unchanged accepted ASV master403c reused. Exact recovered r2 ASV rows/receipt bind the current canonical source/master/acceptance/work. Historical group remains failed; this new one-work release closes maintained visible attribution, private verification/readers and canonical accounting. Current direct coordinator source proof is separately bound; native book keys1through66 preserve existing routing with all literal source headings mapped in visible context. No source reconstruction, master/header/metadata rewrite or acquisition.',authority_installation='Existing accepted installation remains unchanged; no new apply or staged replacement was performed',independent_projection_producer_disabled=True,statistics_and_normal_streaming_readers='pass',visible_repository_license_and_translation_qualification=True,remaining=['Human textual/visual acceptance not recorded','Print identity/date/revision/annotation coverage not collated','Underlying translation rights/jurisdiction clearance unassessed','Public publication not authorized or performed'])
 save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion);print(json.dumps(dict(status='pass',rows=31102,text_characters=completion['text_characters'],completion_sha256=digest(ROOT/PUB/'completion.json'),authority_bindings=len(authority),schema_implementation_bindings=len(frozen))))
if __name__=='__main__':main()
