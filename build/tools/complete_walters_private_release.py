"""Reuse the complete accepted Walters DocSouth electronic witness for private preparation."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
import subprocess
import sys
from lxml import etree
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader

ROOT=Path(__file__).resolve().parents[2]
WORK=Path('library/works/alexander-walters-my-life-and-work');PUB=WORK/'publication'
PRE=Path('reports/_logs/alexander-walters-my-life-and-work-downstream-preflight-20261002')
OUT=Path('D:/Library/Open Christian Data/reports/_logs/alexander-walters-my-life-and-work-private-release-20261002-v1')
SOURCE=Path('raw/docsouth/l762-walters/walters.xml')
SOURCE_NOTE=Path('sources/private-docsouth-walters/alexander-walters-my-life-and-work/README.source.md')
DATA_NOTE=Path('data/prose/alexander-walters-my-life-and-work/README.md')
SCOPE='Complete retained DocSouth electronic witness My Life and Work: complete front/body,28 quoted nested texts at up to two levels,11 source figure bindings and264 page markers; no independent print collation.'
MASTER='5019f1a428ac667a97521272f11422e425879c0d26ead62cbca6dae055d7c710'
NOTICE='# My Life and Work: source and data credit\n\nBy Alexander Walters. This private preparation uses the complete retained electronic witness from Documenting the American South, University of North Carolina at Chapel Hill. It includes the front/body, all 28 quoted nested texts at up to two levels, eleven source figure bindings, and 264 page markers. Public rows preserve the nested reading structure and figure source locators; the retained JPEGs remain source support, without a claim of visual comparison or independent print collation.\n\nThe electronic header credits Thomas Horan and Sarah Reuning for text scanning (OCR) and image scanning, and Lee Ann Morawski and Natalia Smith for text encoding. Funding from the National Endowment for the Humanities supported the electronic publication of this title. The electronic publisher is Academic Affairs Library, UNC-CH, and the electronic edition and publication statements give 1999. These are electronic-source roles and dates, not newly performed OCR or inferred print contributions.\n\nThe retained source description names My Life and Work, Alexander Walters, A.M., D.D., Fleming H. Revell Company, New York, Chicago, Toronto, c1917, and 272 pages with illustrations. These are retained bibliographic statements, without independently verified print-exemplar equivalence.\n\nDocSouth source: https://docsouth.unc.edu/church/walters/walters.html\n\nThe retained source availability status is unknown. Its rights label is No Copyright - United States. The exact source wording below joins that linked label to the following sentence without a separator; line-breaking whitespace is normalized for presentation:\n\nNo Copyright - United StatesThe organization that has made the Item available believes that the Item is in the Public Domain under the laws of the United States, but a determination was not made as to its copyright status under the copyright laws of other countries. The Item may not be in the Public Domain under the laws of other countries. Please refer to the organization that has made the Item available for more information.\n\nRights statement: http://rightsstatements.org/vocab/NoC-US/1.0/\n\nThe source editorial declaration says line-break hyphens were joined, indentation and running titles were not preserved. This is faithful preparation of that retained electronic witness, not restoration of features the provider omitted.\n\nHuman textual and visual acceptance, independent print collation, worldwide rights clearance, and public publication remain separate. No new source acquisition, OCR, or source reconstruction was performed for this downstream preparation.\n'

def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def read(p):return json.loads(io_path(p).read_bytes())
def save(p,v):
    q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode())
def runtime():
    names=['ocd_kernel/projection/categories/prose.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/release/assemble.py','ocd_kernel/release/verify.py','ocd_kernel/release/notices.py','build/tools/report_release_stats.py','build/tools/check_release_reader.py','ocd_kernel/tei/acceptance.py','ocd_kernel/library/state.py','ocd_kernel/reconstruction/contract.py']
    return {p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/'schemas/v2','**/*.json')}|{p:digest(ROOT/p) for p in names}
def assert_pins(pre):
    for p,h in pre['authority_bindings'].items():
        if digest(ROOT/p)!=h:raise ValueError('Authority drift '+p)
    if runtime()!=pre['schema_implementation_bindings']:raise ValueError('Prose runtime/schema drift')
def preflight():
    if io_path(ROOT/PRE/'preflight.json').exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile existing proof')
    paths=list(io_glob(ROOT/WORK,'**/acceptance.json'))
    if len(paths)!=1:raise ValueError('One accepted edition required')
    a=read(paths[0]);master=ROOT/a['promotion']['master']['path']
    if digest(master)!=MASTER or digest(ROOT/SOURCE)!=a['source']['source_sha256']:raise ValueError('Accepted source/master binding differs')
    prior=[];scanned=0
    for directory in [ROOT/'reports/_logs',ROOT/'exports']:
        for d in io_glob(directory,'*'):
            for pat in ['completion.json','closeout.json','*/completion.json','*/closeout.json','report.json','release-report.json']:
                for p in io_glob(d,pat):
                    raw=io_path(p).read_bytes();scanned+=1
                    if WORK.name.encode() in raw:prior.append(p.relative_to(ROOT).as_posix())
    if prior:raise ValueError('Prior proof needs reconciliation '+str(prior))
    src=etree.fromstring(io_path(ROOT/SOURCE).read_bytes(),etree.XMLParser(load_dtd=False,no_network=True,resolve_entities=False))
    m=etree.fromstring(io_path(master).read_bytes());ns={'t':'http://www.tei-c.org/ns/1.0'}
    counts=dict(source_nested_texts=len(src.findall('.//q/text')),source_figures=len(src.findall('.//figure')),source_pages=len(src.findall('.//pb')),master_floating_texts=len(m.findall('.//t:floatingText',ns)),master_figures=len(m.findall('.//t:figure',ns)),master_pages=len(m.findall('.//t:pb',ns)))
    if counts!=dict(source_nested_texts=28,source_figures=11,source_pages=264,master_floating_texts=28,master_figures=11,master_pages=264):raise ValueError('Retained envelope differs '+str(counts))
    authority={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/WORK,'**/*') if io_path(p).is_file() and 'publication' not in p.relative_to(ROOT/WORK).parts}
    for p in io_glob(ROOT/SOURCE.parent,'*'):
        if io_path(p).is_file():authority[p.relative_to(ROOT).as_posix()]=digest(p)
    plan=ROOT/'plans/2026-09-22-source-preflight/docsouth-illustrated-walters-stage-20260927.md'
    for p in [plan,Path(__file__)]:authority[p.relative_to(ROOT).as_posix()]=digest(p)
    header=src.find('teiHeader');rights=' '.join(''.join(header.find('.//availability').itertext()).split())
    if rights not in NOTICE:raise ValueError('Exact provider rights wording missing')
    result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,acceptance_path=paths[0].relative_to(ROOT).as_posix(),accepted_master_sha256=MASTER,source_path=SOURCE.as_posix(),source_sha256=digest(ROOT/SOURCE),scope=SCOPE,counts=counts,source_header=etree.tostring(header,encoding='unicode'),prior_search=dict(scanned_documented_names=scanned,matches=prior,qualification='Bounded dated log/export completion,closeout and report names depth two, not universal absence. Sept25 selection contains Walters in excluded works, not a released item; Sept26 selected35 has no Walters.'),authority_bindings=authority,schema_implementation_bindings=runtime())
    save(ROOT/PRE/'preflight.json',result)
    print(json.dumps(dict(status='pass',counts=counts,authority=len(authority),runtime_schema=len(result['schema_implementation_bindings']))),flush=True)
    project()

def project():
    pre=read(ROOT/PRE/'preflight.json');assert_pins(pre)
    if io_path(ROOT/PRE/'actual-master-projection.json').exists():raise FileExistsError('Preserve projection')
    with cached_edition_lookups():
        acceptance=ROOT/pre['acceptance_path'];validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
        projected=project_accepted_prose(ROOT,acceptance_path=acceptance);save(ROOT/PRE/'actual-master-projection.json',projected)
    print(json.dumps(dict(status='projected',rows=len(projected['rows']),characters=sum(len(r['text']) for r in projected['rows']),accepted_master_sha256=MASTER,projection_document_sha256=projected['receipt']['master_sha256'],authority_master_sha256=projected['receipt']['authority']['master']['sha256'])),flush=True)
def release():
    if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile prior release')
    pre=read(ROOT/PRE/'preflight.json');assert_pins(pre);authority=dict(pre['authority_bindings']);frozen=runtime();projected=read(ROOT/PRE/'actual-master-projection.json')
    if projected['receipt']['master_sha256']!=MASTER or projected['receipt']['authority']['master']['sha256']!=MASTER:raise ValueError('Full accepted master binding differs')
    rows=len(projected['rows']);chars=sum(len(r['text']) for r in projected['rows'])
    if rows!=37:raise ValueError('Complete37-unit native route differs')
    for name in ['preflight.json','actual-master-projection.json']:authority[(PRE/name).as_posix()]=digest(ROOT/PRE/name)
    OUT.mkdir(parents=True);save(OUT/'authority-before.json',authority);save(OUT/'schema-implementation-before.json',frozen);save(OUT/'actual-master-projection.json',projected);save(ROOT/PUB/'actual-master-projection.json',projected)
    independent='''import sys,json,os,hashlib
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import verify_accepted_prose
import ocd_kernel.projection.native_content as producer
def unavailable(*args,**kwargs):raise AssertionError('producer or renderer invoked by checker')
producer.project_content=unavailable;producer.readable_content=unavailable
root,acceptance,projected=map(Path,sys.argv[1:]);raw=projected.read_bytes();p=json.loads(raw)
with cached_edition_lookups():errors=verify_accepted_prose(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'])
print(json.dumps(dict(status='fail' if errors else 'pass',errors=errors,pid=os.getpid(),producer_disabled=True,projection_sha256=hashlib.sha256(raw).hexdigest())))
raise SystemExit(bool(errors))
'''
    argv=[sys.executable,'-c',independent,str(ROOT),str(ROOT/pre['acceptance_path']),str(OUT/'actual-master-projection.json')]
    try:result=subprocess.run(argv,cwd=ROOT,check=True,capture_output=True,text=True,encoding='utf-8')
    except subprocess.CalledProcessError as exc:
        save(OUT/'independent-projection-command.json',dict(argv=argv,exit_code=exc.returncode,stdout=exc.stdout,stderr=exc.stderr));raise
    checked=json.loads(result.stdout)
    if checked['status']!='pass' or checked['projection_sha256']!=digest(OUT/'actual-master-projection.json'):raise ValueError('Independent saved linkage differs')
    save(OUT/'independent-projection-command.json',dict(argv=argv,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr));save(OUT/'independent-projection-linkage.json',checked)
    print('Producer-disabled full-master independent linkage: pass',flush=True)
    for p,text in [(DATA_NOTE,NOTICE),(SOURCE_NOTE,NOTICE+'\nThe human-visible data attribution is maintained at `'+DATA_NOTE.as_posix()+'`.\n')]:
        q=io_path(ROOT/p);payload=(text.rstrip('\n')+'\n').encode()
        if q.exists() and q.read_bytes()!=payload:raise FileExistsError('Existing notice differs '+str(p))
        q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(payload);authority[p.as_posix()]=digest(q)
    selection=dict(schema_version='2.0',release_id='alexander-walters-my-life-and-work-private-offline-20261002-v1',items=[dict(item_id=WORK.name,category='prose',acceptance_path=pre['acceptance_path'],public_notices=[dict(source_path=SOURCE_NOTE.as_posix(),source_sha256=digest(ROOT/SOURCE_NOTE),notice_path=DATA_NOTE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTE))])])
    save(ROOT/PUB/'selection.json',selection);save(OUT/'selection.json',selection)
    with cached_edition_lookups():
        texts=notice_texts_for_item(ROOT,selection['items'][0],ROOT/pre['acceptance_path'])
        if len(texts)!=1 or any(t not in texts[0] for t in ['Thomas Horan and Sarah Reuning','Lee Ann Morawski and Natalia Smith','National Endowment for the Humanities','other countries','c1917','Documenting the American South']):raise ValueError('Own required notice missing')
        save(OUT/'notice-gate.json',dict(status='pass',own_source_roles_funding_rights_and_bibliographic_qualification=True,exact_one_terminal_lf=True))
        release_path=OUT/'release';assembled=assemble_release_v2(ROOT,release_path,selection=selection);save(OUT/'assembly.json',assembled)
        if assembled['status']!='pass':raise ValueError(assembled)
        print('Private assembly: pass',flush=True)
        for name,op in [('independent-verification',lambda:verify_release_v2(ROOT,release_path,selection=selection)),('statistics',lambda:release_statistics(ROOT,release_path,selection)),('readers',lambda:check_reader(ROOT,release_path,selection))]:
            value=op();save(OUT/(name+'.json'),value)
            if value['status']!='pass':raise ValueError(value)
            print(name+': pass',flush=True)
    visible=io_path(release_path/'public/README.md').read_bytes()
    if io_path(ROOT/DATA_NOTE).read_bytes().rstrip() not in visible:raise ValueError('Actual released notice missing')
    save(OUT/'released-notice-check.json',dict(status='pass',exact_own_notice_embedded=True,public_readme_sha256=sha256(visible).hexdigest()))
    if runtime()!=frozen:raise ValueError('Final schema/runtime drift')
    for p,h in authority.items():
        if digest(ROOT/p)!=h:raise ValueError('Final authority drift '+p)
    save(OUT/'authority-after.json',authority);save(OUT/'schema-implementation-after.json',frozen)
    files={p.relative_to(release_path).as_posix():digest(p) for p in release_path.rglob('*') if p.is_file()};save(OUT/'release-file-hashes.json',files)
    evidence={p.relative_to(OUT).as_posix():digest(p) for p in OUT.glob('*.json')}
    done=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,scope=SCOPE,rows=rows,text_characters=chars,accepted_master_sha256=MASTER,projection_document_sha256=projected['receipt']['master_sha256'],synthetic_projection_document_used=False,source_sha256=pre['source_sha256'],source_path=SOURCE.as_posix(),canonical_authority_unchanged=True,reconstruction_performed=False,private_offline=True,publication_performed=False,release_path=release_path.as_posix(),evidence_path=OUT.as_posix(),authority_bindings=authority,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,independent_projection_producer_disabled=True,statistics_and_normal_streaming_readers='pass',remaining=['Human textual/visual review not newly performed','Independent print collation and visual comparison not performed; source c1917 description qualified','Rights clearance not established by source declarations','Public publication not authorized or performed'])
    save(ROOT/PUB/'completion.json',done);save(OUT/'completion.json',done)
    print(json.dumps(dict(status='pass',rows=rows,text_characters=chars,completion_sha256=digest(ROOT/PUB/'completion.json'),authority_pins=len(authority),runtime_schema_pins=len(frozen))),flush=True)
if __name__=='__main__':
    if len(sys.argv)==1:preflight()
    elif sys.argv[1]=='project':project()
    elif sys.argv[1]=='release':release()
    else:raise ValueError('Unknown action')
