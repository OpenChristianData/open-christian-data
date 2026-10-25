"""Complete the installed whole Darby electronic witness privately, with exact input bindings."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from build.tools.prepare_darby_current import ROOT, WORK, WORK_ID, EDITION, BASE, SOURCE, SOURCE_SHA, LOG as INSTALL_LOG, DATA_NOTICE
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.bible import project_accepted_bible, _validator
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2

LOG=ROOT/'reports/_logs/darby-offline-release-20261002-v1'
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
    if not LOG.exists() or not PUB.exists() or RELEASE.exists() or (LOG/'completion.json').exists():raise ValueError('Resume only before assembly from preserved projection')
    acceptance=ROOT/EDITION/'acceptance.json';master=ROOT/EDITION/'master.tei.xml'
    stage=json.loads((ROOT/BASE/'stage-pin.json').read_bytes());receipt=json.loads(Path(stage['receipt']).read_bytes())
    if digest(master)!=receipt['master_sha256'] or digest(acceptance)!=receipt['after'][str(EDITION.relative_to(WORK)/'acceptance.json').replace('\\','/')]:raise ValueError('Installed acceptance/master differs from frozen stage')
    bound=json.loads((LOG/'authority-before.json').read_bytes())
    if any(digest(ROOT/p)!=h for p,h in bound.items()):raise ValueError('Preserved original authority/runtime input changed')
    bound['build/tools/complete_darby_private_release_resume.py']=digest(ROOT/'build/tools/complete_darby_private_release_resume.py')
    coordinator=ROOT/INSTALL_LOG/'canonical-install/coordinator-installed-hash-audit.json'
    if coordinator.exists():bound[coordinator.relative_to(ROOT).as_posix()]=digest(coordinator)
    schemas={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/'schemas/v2','**/*.json') if io_path(p).is_file()}
    modules=['ocd_kernel/projection/categories/bible.py','ocd_kernel/projection/envelope.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/release/notices.py','ocd_kernel/release/verify.py','build/scripts/export_huggingface.py','build/tools/check_hf_release.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py']
    modules.extend(['ocd_kernel/tei/acceptance.py','ocd_kernel/tei/install_accepted.py','ocd_kernel/library/identities.py','ocd_kernel/library/_common.py','ocd_kernel/library/acquisitions.py','ocd_kernel/library/state.py','ocd_kernel/release/selection.py','ocd_kernel/release/assemble.py','ocd_kernel/lib/storage_topology.py'])
    runtime={p:digest(ROOT/p) for p in modules}
    if runtime['ocd_kernel/projection/categories/bible.py']!='9f4e6cd7b0238379eb2d6de70a35eda9ab02226b8beba51a32710bfc667f8c7b' or digest(ROOT/SOURCE)!=SOURCE_SHA:raise ValueError('Frozen Bible/source inputs differ')
    bound.update(runtime);save(LOG/'runtime-freeze.json',runtime);save(LOG/'schemas-before.json',schemas)
    item=dict(item_id=WORK_ID,category='bible',acceptance_path=acceptance.relative_to(ROOT).as_posix(),public_notices=[dict(source_path=(BASE/'README.source.md').as_posix(),source_sha256=digest(ROOT/BASE/'README.source.md'),notice_path=DATA_NOTICE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTICE))])
    selection=dict(schema_version='2.0',release_id='darby-private-offline-20261002-v1',items=[item])
    texts=notice_texts_for_item(ROOT,item,acceptance)
    if len(texts)!=1 or not all(s in texts[0] for s in ['Darby: Darby Bible (1889)','31,102','Matthew 23:14','Acts 8:37','Acts 15:34','rights clearance']):raise ValueError('Complete source/use note differs')
    save(LOG/'notice-preflight.json',dict(status='pass',notice_count=len(texts)))
    selected=PUB/'selection.json';save(selected,selection);save(LOG/'selection.json',selection);bound[selected.relative_to(ROOT).as_posix()]=digest(selected)
    save(LOG/'authority-before-resume.json',bound)
    projection=json.loads((LOG/'actual-master-projection.json').read_bytes())
    save(LOG/'actual-master-projection.json',projection)
    validator=_validator()
    errors=[str(e) for r in projection['rows'] for e in validator.iter_errors(r)]
    if errors or len(projection['rows'])!=31102 or projection['receipt']['master_sha256']!=digest(master):raise ValueError(errors or 'Complete actual-master projection binding differs')
    save(LOG/'public-validation.json',dict(status='pass',rows=31102,errors=[]))
    code='''import sys,json,hashlib
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
import ocd_kernel.projection.categories.bible as bible
def unavailable(*a,**k):raise AssertionError('Bible producer invoked by independent checker')
bible.project_accepted_bible=bible.project_bible_document=bible._projection=bible._render=unavailable
root,acceptance,projected=map(Path,sys.argv[1:]);raw=projected.read_bytes();p=json.loads(raw)
with cached_edition_lookups():errors=bible.verify_accepted_bible(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'])
print(json.dumps(dict(status='fail' if errors else 'pass',errors=errors,producer_disabled=True,saved_projection_sha256=hashlib.sha256(raw).hexdigest())))
raise SystemExit(bool(errors))'''
    checked=json.loads(process('independent-projection',[sys.executable,'-c',code,str(ROOT),str(acceptance),str(LOG/'actual-master-projection.json')]).stdout)
    checked.update(accepted_master_sha256=digest(master),acceptance_sha256=digest(acceptance),schemas=schemas,qualification='Full installed accepted master projected; no synthetic or source-selected document.')
    if checked['status']!='pass' or checked['saved_projection_sha256']!=digest(LOG/'actual-master-projection.json'):raise ValueError(checked)
    save(LOG/'independent-projection-linkage.json',checked)
    empties=[r['locator'] for r in projection['rows'] if r['text']==''];save(LOG/'source-empty-slot-check.json',dict(status='pass',empty_count=len(empties),loci=empties))
    if len(empties)!=3:raise ValueError('Source-empty slot count differs')
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
    completion=dict(status='technical-private-offline-release-pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,rows=31102,books=66,chapters=1189,source_empty_slots=3,characters=sum(len(r['text']) for r in projection['rows']),statistics=json.loads((LOG/'statistics.json').read_bytes())['total'],accepted_master_sha256=digest(master),saved_projection_sha256=digest(LOG/'actual-master-projection.json'),independent_linkage_sha256=digest(LOG/'independent-projection-linkage.json'),authority_unchanged_during_release=True,bound_schemas_stable=True,publication_performed=False,remaining=['human acceptance','visual proofreading/print collation','translator/print identity','rights clearance','global selection/publication authorization'])
    save(LOG/'completion.json',completion);save(PUB/'completion.json',completion)
    readme='# Darby Bible: private preparation complete\n\nAll 66 source books, 1,189 chapters and 31,102 verse carriers remain present, including three empty source slots. Actual accepted-master projection, saved producer-disabled linkage, both private release verifiers, statistics and normal/streaming readers pass. Complete paired provider/source use notice appears in the release README. Source-native numbering and edition-local IDs are qualified; 1889 is an uncollated source label. Human review, rights and publication remain separate.\n'
    (PUB/'README.md').write_text(readme,encoding='utf-8');(LOG/'README.md').write_text(readme,encoding='utf-8')
    for p in io_glob(PUB,'**/*'):
        if io_path(p).is_file():after[p.relative_to(ROOT).as_posix()]=digest(p)
    evidence={p.relative_to(LOG).as_posix():digest(p) for p in io_glob(LOG,'**/*') if io_path(p).is_file() and RELEASE not in p.parents}
    save(LOG/'final-delivery.json',dict(status='pass',authority=after,schemas=schema_after,release=files,evidence=evidence))
    print(json.dumps(completion),flush=True)

if __name__=='__main__':main()
