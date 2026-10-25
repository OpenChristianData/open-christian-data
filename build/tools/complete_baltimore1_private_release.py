"""Complete the installed unchanged whole Baltimore Catechism No.1 electronic witness privately, with exact input bindings."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from build.tools.prepare_baltimore1_private_release import ROOT, WORK, WORK_ID, EDITION, BASE, ACQUISITION, LOG as INSTALL_LOG, DATA_NOTICE
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.catechisms import project_accepted_catechisms, _validate_rows
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2

LOG=ROOT/'reports/_logs/baltimore-catechism-no-1-offline-release-20261002-v2'
PUB=ROOT/WORK/'publication'
RELEASE=LOG/'release'
ORIGINAL_BASE=BASE
BASE=Path('sources/publication-pg14551/baltimore-catechism-no-1')

def digest(p): return sha256(io_path(p).read_bytes()).hexdigest()
def save(p,v):
    q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(v,ensure_ascii=True,indent=2,sort_keys=True)+'\n').encode()
    if q.exists():
        if json.loads(q.read_bytes())!=v:raise ValueError('Preserved receipt differs: '+str(q))
        return
    q.write_bytes(raw)
def process(name,argv):
    try: r=subprocess.run(argv,cwd=ROOT,check=True,capture_output=True,text=True,encoding='utf-8')
    except subprocess.CalledProcessError as e:
        save(LOG/(name+'.command.json'),dict(argv=argv,exit_code=e.returncode,stdout=e.stdout,stderr=e.stderr));raise
    save(LOG/(name+'.command.json'),dict(argv=argv,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr));return r
def command(name,module,args):
    code='import sys;sys.dont_write_bytecode=True\nfrom ocd_kernel.library.identities import cached_edition_lookups\nfrom '+module+' import main\nwith cached_edition_lookups():\n raise SystemExit(main())'
    r=process(name,[sys.executable,'-c',code,*args])
    if name!='assembly':
        v=json.loads(r.stdout);save(LOG/(name+'.json'),v)
        if v['status']!='pass':raise ValueError(v)

def main():
    if LOG.exists() or (PUB.exists() and any(io_glob(PUB,'**/*'))):raise FileExistsError('Fresh Baltimore1 report root and empty work-local publication required')
    LOG.mkdir(parents=True);PUB.mkdir(parents=True,exist_ok=True)
    acceptance=ROOT/EDITION/'acceptance.json';master=ROOT/EDITION/'master.tei.xml'
    notice=io_path(ROOT/ORIGINAL_BASE/'README.source.md').read_bytes()
    io_path(ROOT/BASE).mkdir(parents=True,exist_ok=True)
    if io_path(ROOT/BASE/'README.source.md').exists():raise FileExistsError('Fresh supported source notice path required')
    io_path(ROOT/BASE/'README.source.md').write_bytes(notice)
    io_path(ROOT/DATA_NOTICE).parent.mkdir(parents=True,exist_ok=True)
    if io_path(ROOT/DATA_NOTICE).exists() and io_path(ROOT/DATA_NOTICE).read_bytes()!=notice:raise ValueError('Existing data notice differs')
    io_path(ROOT/DATA_NOTICE).write_bytes(notice)
    preflight=json.loads((ROOT/INSTALL_LOG/'preflight.json').read_bytes())
    if digest(master)!=preflight['accepted_master_sha256'] or digest(acceptance)!=preflight['acceptance_sha256']:raise ValueError('Reconciled accepted master changed')
    bound=dict(preflight['authority'])
    bound.update(preflight['dependencies'])
    for p in ['build/tools/prepare_baltimore1_private_release.py','build/tools/complete_baltimore1_private_release.py']:
        bound[p]=digest(ROOT/p)
    for p in io_glob(ROOT/INSTALL_LOG,'**/*.json'):
        if io_path(p).is_file():bound[p.relative_to(ROOT).as_posix()]=digest(p)
    bound[DATA_NOTICE.as_posix()]=digest(ROOT/DATA_NOTICE)
    bound[(BASE/'README.source.md').as_posix()]=digest(ROOT/BASE/'README.source.md')
    schema_names=['schemas/v2/native-content.schema.json','schemas/v2/categories/catechisms.schema.json','schemas/v2/public-row.schema.json','schemas/v2/projection-receipt.schema.json','schemas/v2/acceptance.schema.json','schemas/v2/work.schema.json','schemas/v2/state.schema.json','schemas/v2/acquisition.schema.json','schemas/v2/release-selection.schema.json','schemas/v2/release-report.schema.json']
    schemas={p:digest(ROOT/p) for p in schema_names}
    modules=['ocd_kernel/projection/categories/catechisms.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/envelope.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/release/notices.py','ocd_kernel/release/verify.py','build/scripts/export_huggingface.py','build/tools/check_hf_release.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py','ocd_kernel/tei/acceptance.py','ocd_kernel/library/identities.py','ocd_kernel/library/_common.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/state.py','ocd_kernel/release/selection.py','ocd_kernel/release/assemble.py','ocd_kernel/release/typed_rows.py','ocd_kernel/lib/storage_topology.py']
    runtime={p:digest(ROOT/p) for p in modules}
    bound.update(runtime)
    if any(digest(ROOT/p)!=h for p,h in bound.items()):raise ValueError('Pre-release exact input bindings differ')
    save(LOG/'runtime-freeze.json',runtime);save(LOG/'schemas-before.json',schemas)
    item=dict(item_id=WORK_ID,category='catechisms',acceptance_path=acceptance.relative_to(ROOT).as_posix(),public_notices=[dict(source_path=(BASE/'README.source.md').as_posix(),source_sha256=digest(ROOT/BASE/'README.source.md'),notice_path=DATA_NOTICE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTICE))])
    selection=dict(schema_version='2.0',release_id='baltimore1-private-offline-20261002-v1',items=[item])
    texts=notice_texts_for_item(ROOT,item,acceptance)
    if len(texts)!=1 or not all(s in texts[0] for s in ['Dennis McCarthy','John Lancaster Spalding','1977','START: FULL LICENSE','rights clearance']):raise ValueError('Complete source/use note differs')
    save(LOG/'notice-preflight.json',dict(status='pass',notice_count=len(texts)))
    selected=PUB/'selection.json';save(selected,selection);save(LOG/'selection.json',selection);bound[selected.relative_to(ROOT).as_posix()]=digest(selected)
    save(LOG/'authority-before.json',bound)
    with cached_edition_lookups():projection=project_accepted_catechisms(ROOT,acceptance_path=acceptance)
    save(LOG/'actual-master-projection.json',projection)
    _validate_rows(projection['rows']);errors=[]
    if errors or len(projection['rows'])!=1 or projection['receipt']['master_sha256']!=digest(master):raise ValueError(errors or 'Complete actual-master projection binding differs')
    save(LOG/'public-validation.json',dict(status='pass',rows=1,errors=[]))
    code='''import sys,json,hashlib
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import catechisms
from ocd_kernel.projection import native_content
def unavailable(*a,**k):raise AssertionError('Catechism producer invoked by independent checker')
catechisms.project_accepted_catechisms=catechisms.project_catechism_document=catechisms._project_native_accepted_catechism=native_content.project_content=native_content.readable_content=unavailable
root,acceptance,projected=map(Path,sys.argv[1:]);raw=projected.read_bytes();p=json.loads(raw)
with cached_edition_lookups():errors=catechisms.verify_accepted_catechisms(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'])
print(json.dumps(dict(status='fail' if errors else 'pass',errors=errors,producer_disabled=True,saved_projection_sha256=hashlib.sha256(raw).hexdigest())))
raise SystemExit(bool(errors))'''
    checked=json.loads(process('independent-projection',[sys.executable,'-c',code,str(ROOT),str(acceptance),str(LOG/'actual-master-projection.json')]).stdout)
    checked.update(accepted_master_sha256=digest(master),acceptance_sha256=digest(acceptance),schemas=schemas,qualification='Full installed accepted master projected; no synthetic or source-selected document.')
    if checked['status']!='pass' or checked['saved_projection_sha256']!=digest(LOG/'actual-master-projection.json'):raise ValueError(checked)
    save(LOG/'independent-projection-linkage.json',checked)
    row=projection['rows'][0]
    if row['source_line_count']!=2620 or len(row['question_answers'])!=206:raise ValueError('Whole source or Q/A census differs')
    save(LOG/'source-transcription-scope-check.json',dict(status='pass',source_lines=2620,question_answers=206,whole_structured_record=True,header_prayers_hymns_editorial_notes_endmarkers_license_included=True))
    print('Actual installed master projection and producer-disabled linkage passed; assembling private release',flush=True)
    common=['--root',str(ROOT),'--selection',str(selected)]
    command('assembly','build.scripts.export_huggingface',[*common,'--output',str(RELEASE)])
    save(LOG/'assembly.json',json.loads((RELEASE/'internal/release-report.json').read_bytes()))
    with cached_edition_lookups():verified=verify_release_v2(ROOT,RELEASE,selection=selection)
    save(LOG/'independent-verification.json',verified)
    if verified['status']!='pass':raise ValueError(verified)
    args=[*common,'--release',str(RELEASE)]
    command('separate-process-verification','build.tools.check_hf_release',args)
    command('statistics','build.tools.report_release_stats',args)
    command('readers','build.tools.check_release_reader',[*args,'--output',str(LOG/'readers.json')])
    if io_path(ROOT/DATA_NOTICE).read_bytes().rstrip() not in (RELEASE/'public/README.md').read_bytes():raise ValueError('Release omits full visible note')
    save(LOG/'released-notice-check.json',dict(status='pass',complete_notice_embedded=True,notice_sha256=digest(ROOT/DATA_NOTICE)))
    after={p:digest(ROOT/p) for p in bound};schema_after={p:digest(ROOT/p) for p in schemas}
    if after!=bound or schema_after!=schemas:raise ValueError('Authority/runtime/schema drift')
    save(LOG/'authority-after.json',after);save(LOG/'schema-stability.json',dict(status='pass',before=schemas,after=schema_after))
    files={p.relative_to(RELEASE).as_posix():digest(p) for p in io_glob(RELEASE,'**/*') if io_path(p).is_file()};save(LOG/'release-file-hashes.json',files)
    completion=dict(status='technical-private-offline-release-pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,rows=1,source_lines=2620,question_answer_groups=206,characters=sum(len(r['text']) for r in projection['rows']),statistics=json.loads((LOG/'statistics.json').read_bytes())['total'],accepted_master_sha256=digest(master),saved_projection_sha256=digest(LOG/'actual-master-projection.json'),independent_linkage_sha256=digest(LOG/'independent-projection-linkage.json'),authority_unchanged_during_release=True,bound_schemas_stable=True,publication_performed=False,remaining=['human acceptance','visual proofreading/print collation','source transcription/print equivalence','rights clearance','global selection/publication authorization'])
    save(LOG/'completion.json',completion);save(PUB/'completion.json',completion)
    readme="# Baltimore Catechism No.1: private publication readiness\n\nThe unchanged accepted complete Gutenberg electronic witness is privately verified: one structured source-transcription record, all2,620 physical source lines and206 question/answer groups. Provider header, prayers, catechism, hymns, composite-transcription/1977 revision notes, end markers and full retained license remain included. Actual-master projection, saved producer-disabled independent linkage, private assembly, both release verifiers, statistics and normal/streaming readers pass. Own primary contributor credits and full Gutenberg license are visible in paired source/data notices and the private release README.1885approval dates remain distinct from electronic release/update dates; no print equivalence, human acceptance, independent rights clearance or public publication is claimed.\n"
    (PUB/'README.md').write_text(readme,encoding='utf-8');(LOG/'README.md').write_text(readme,encoding='utf-8')
    for p in io_glob(PUB,'**/*'):
        if io_path(p).is_file():after[p.relative_to(ROOT).as_posix()]=digest(p)
    evidence={p.relative_to(LOG).as_posix():digest(p) for p in io_glob(LOG,'**/*') if io_path(p).is_file() and RELEASE not in p.parents}
    save(LOG/'final-delivery.json',dict(status='pass',authority=after,schemas=schema_after,release=files,evidence=evidence))
    print(json.dumps(completion),flush=True)

if __name__=='__main__':main()
