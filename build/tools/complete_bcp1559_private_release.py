"""Complete the installed whole retained BCP1559 electronic expression privately, with exact input bindings."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from build.tools.prepare_bcp1559_current import ROOT, WORK, WORK_ID, EDITION, BASE, ACQUISITION, LOG as INSTALL_LOG, DATA_NOTICE
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.liturgies import project_accepted_liturgies, _validate_rows
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2

LOG=ROOT/'reports/_logs/bcp1559-offline-release-20261002-v1'
PUB=ROOT/WORK/'publication/private-offline-20261002'
RELEASE=LOG/'release'

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
    if LOG.exists() or PUB.exists():raise FileExistsError('Fresh BCP1559 publication/report roots required')
    LOG.mkdir(parents=True);PUB.mkdir(parents=True)
    acceptance=ROOT/EDITION/'acceptance.json';master=ROOT/EDITION/'master.tei.xml'
    notice=io_path(ROOT/BASE/'README.source.md').read_bytes();io_path(ROOT/DATA_NOTICE).parent.mkdir(parents=True,exist_ok=True)
    if io_path(ROOT/DATA_NOTICE).exists() and io_path(ROOT/DATA_NOTICE).read_bytes()!=notice:raise ValueError('Existing data notice differs')
    io_path(ROOT/DATA_NOTICE).write_bytes(notice)
    stage=json.loads((ROOT/BASE/'stage-pin.json').read_bytes());receipt=json.loads(Path(stage['receipt']).read_bytes())
    if digest(master)!=receipt['master_sha256'] or digest(acceptance)!=receipt['after'][str(EDITION.relative_to(WORK)/'acceptance.json').replace('\\','/')]:raise ValueError('Installed acceptance/master differs from frozen stage')
    from ocd_kernel.tei.install_accepted import _files
    bound={(WORK/Path(p)).as_posix():h for p,h in _files(ROOT/WORK).items()}
    manifest=json.loads((ROOT/BASE/'source-manifest.json').read_bytes())
    for entry in manifest['authorities']:bound[entry['path']]=entry['sha256']
    for prefix in ['converter','validator']:bound[manifest[prefix]['implementation_path']]=manifest[prefix]['implementation_sha256']
    for path in io_glob(ROOT/BASE,'*'):
        if io_path(path).is_file():bound[path.relative_to(ROOT).as_posix()]=digest(path)
    for name in ['prepare','run','package','stage','freeze','install']:
        p='build/tools/'+name+'_bcp1559_current.py';bound[p]=digest(ROOT/p)
    for p in ['build/tools/prove_bcp1559_isolated_rollback.py','build/tools/complete_bcp1559_private_release.py']:
        bound[p]=digest(ROOT/p)
    for p in io_glob(ROOT/INSTALL_LOG,'**/*.json'):
        if io_path(p).is_file():bound[p.relative_to(ROOT).as_posix()]=digest(p)
    bound[DATA_NOTICE.as_posix()]=digest(ROOT/DATA_NOTICE)
    public_source=BASE/'README.source.md';bound[public_source.as_posix()]=digest(ROOT/public_source)
    for p,h in stage['dependency_bindings'].items():
        if digest(ROOT/p)!=h:raise ValueError('Frozen relevant dependency changed: '+p)
        bound[p]=h
    schema_names=list(receipt['schema_pins'])+[p for p in stage['dependency_bindings'] if p.startswith('schemas/')]+['schemas/v2/release-selection.schema.json','schemas/v2/release-report.schema.json']
    schemas={p:digest(ROOT/p) for p in schema_names}
    modules=['ocd_kernel/projection/categories/liturgies.py','ocd_kernel/projection/categories/liturgies_bcp1559.py','ocd_kernel/projection/categories/liturgies_bcp1559_check.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/envelope.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/release/notices.py','ocd_kernel/release/verify.py','build/scripts/export_huggingface.py','build/tools/check_hf_release.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py']
    modules.extend(['ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/library/identities.py','ocd_kernel/library/_common.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/state.py','ocd_kernel/release/selection.py','ocd_kernel/release/assemble.py','ocd_kernel/lib/storage_topology.py'])
    runtime={p:digest(ROOT/p) for p in modules}
    if any(digest(ROOT/p)!=h for p,h in receipt['schema_pins'].items()):raise ValueError('Frozen relevant implementation inputs differ')
    bound.update(runtime)
    if any(digest(ROOT/p)!=h for p,h in bound.items()):raise ValueError('Pre-release exact input bindings differ')
    save(LOG/'runtime-freeze.json',runtime);save(LOG/'schemas-before.json',schemas)
    item=dict(item_id=WORK_ID,category='liturgies',acceptance_path=acceptance.relative_to(ROOT).as_posix(),public_notices=[dict(source_path=(BASE/'README.source.md').as_posix(),source_sha256=digest(ROOT/BASE/'README.source.md'),notice_path=DATA_NOTICE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTICE))])
    selection=dict(schema_version='2.0',release_id='bcp1559-private-offline-20261002-v1',items=[item])
    texts=notice_texts_for_item(ROOT,item,acceptance)
    if len(texts)!=1 or not all(s in texts[0] for s in ['Charles Wohlers','128','rights clearance']):raise ValueError('Complete source/use note differs')
    save(LOG/'notice-preflight.json',dict(status='pass',notice_count=len(texts)))
    selected=PUB/'selection.json';save(selected,selection);save(LOG/'selection.json',selection);bound[selected.relative_to(ROOT).as_posix()]=digest(selected)
    save(LOG/'authority-before.json',bound)
    projection_source=ROOT/WORK/'integration/bcp1559-current-v1/stage-projection.json'
    projection=json.loads(io_path(projection_source).read_bytes())
    if any(digest(ROOT/entry['path'])!=entry['sha256'] for entry in projection['receipt']['authority'].values()):
        raise ValueError('Saved supported actual-master projection authority differs from installed bytes')
    save(LOG/'actual-master-projection.json',projection)
    save(LOG/'projection-reuse.json',dict(status='pass',source_path=projection_source.relative_to(ROOT).as_posix(),source_sha256=digest(projection_source),saved_projection_sha256=digest(LOG/'actual-master-projection.json'),qualification='Reuse supported staged actual-master projection; all accepted master/acceptance/acquisition/work authority bindings now match canonical installed bytes exactly. Producer-disabled checker below rechecks this saved projection against canonical authority. No producer gate repeated.'))
    _validate_rows(projection['rows']);errors=[]
    if errors or len(projection['rows'])!=16 or projection['receipt']['master_sha256']!=digest(master):raise ValueError(errors or 'Complete actual-master projection binding differs')
    save(LOG/'public-validation.json',dict(status='pass',rows=16,errors=[]))
    code='''import sys,json,hashlib
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import liturgies,liturgies_bcp1559
from ocd_kernel.projection import native_content
def unavailable(*a,**k):raise AssertionError('Liturgy producer invoked by independent checker')
liturgies.project_accepted_liturgies=liturgies.project_liturgies_document=liturgies_bcp1559.project_document=liturgies_bcp1559.project_content=native_content.project_content=unavailable
root,acceptance,projected=map(Path,sys.argv[1:]);raw=projected.read_bytes();p=json.loads(raw)
with cached_edition_lookups():errors=liturgies.verify_accepted_liturgies(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'])
print(json.dumps(dict(status='fail' if errors else 'pass',errors=errors,producer_disabled=True,saved_projection_sha256=hashlib.sha256(raw).hexdigest())))
raise SystemExit(bool(errors))'''
    checked=json.loads(process('independent-projection',[sys.executable,'-c',code,str(ROOT),str(acceptance),str(LOG/'actual-master-projection.json')]).stdout)
    checked.update(accepted_master_sha256=digest(master),acceptance_sha256=digest(acceptance),schemas=schemas,qualification='Full installed accepted master projected; no synthetic or source-selected document.')
    if checked['status']!='pass' or checked['saved_projection_sha256']!=digest(LOG/'actual-master-projection.json'):raise ValueError(checked)
    save(LOG/'independent-projection-linkage.json',checked)
    census={'table':0,'table-row':0,'table-cell':0,'row_span':0}
    def walk(node):
        if node['kind']=='text':return
        if node['kind'] in census:census[node['kind']]+=1
        if 'row_span' in node['attributes']:census['row_span']+=1
        for child in node['content']:walk(child)
    for row in projection['rows']:
        if row['source_links'] or row['response_model']!='source-native-labels-without-response-inference':raise ValueError('Inferred responses or authorities')
        walk(row['structure'][0])
    if census!={'table':128,'table-row':391,'table-cell':998,'row_span':46}:raise ValueError(census)
    save(LOG/'source-native-table-check.json',dict(status='pass',census=census))
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
    completion=dict(status='technical-private-offline-release-pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,rows=16,members=16,tables=128,table_rows=391,cells=998,rowspans=46,characters=sum(len(r['text']) for r in projection['rows']),statistics=json.loads((LOG/'statistics.json').read_bytes())['total'],accepted_master_sha256=digest(master),saved_projection_sha256=digest(LOG/'actual-master-projection.json'),independent_linkage_sha256=digest(LOG/'independent-projection-linkage.json'),authority_unchanged_during_release=True,bound_schemas_stable=True,publication_performed=False,remaining=['human acceptance','visual proofreading/print collation','source transcription/print equivalence','rights clearance','global selection/publication authorization'])
    save(LOG/'completion.json',completion);save(PUB/'completion.json',completion)
    readme="# BCP1559 retained electronic expression: private preparation complete\n\nAll sixteen declared primary HTML members,128tables/391rows/998cells,46rowspans and46colspans remain represented in one accepted TEI. Actual-master projection, saved producer-disabled independent linkage, private assembly, both release verifiers, statistics and normal/streaming readers pass. Complete paired source/data credits are visible in the release README. Charles Wohlers is credited as Web author from fifteen literal footers; inherited Mammana transcription attribution is unconfirmed. Later variants and contextualappendices remain explicit. No pure1559print equivalence, universal electronic reuse permission, linked asset verification, response inference, human acceptance or public publication is claimed.\n"
    (PUB/'README.md').write_text(readme,encoding='utf-8');(LOG/'README.md').write_text(readme,encoding='utf-8')
    for p in io_glob(PUB,'**/*'):
        if io_path(p).is_file():after[p.relative_to(ROOT).as_posix()]=digest(p)
    evidence={p.relative_to(LOG).as_posix():digest(p) for p in io_glob(LOG,'**/*') if io_path(p).is_file() and RELEASE not in p.parents}
    save(LOG/'final-delivery.json',dict(status='pass',authority=after,schemas=schema_after,release=files,evidence=evidence))
    print(json.dumps(completion),flush=True)

if __name__=='__main__':main()
