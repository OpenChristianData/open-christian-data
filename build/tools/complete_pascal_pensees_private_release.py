"""Reuse the complete accepted Pascal electronic witness for private preparation."""
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
WORK=Path('library/works/pascal-pensees');PUB=WORK/'publication'
PRE=Path('reports/_logs/pascal-pensees-downstream-preflight-20261001')
OUT=Path('D:/Library/Open Christian Data/reports/_logs/pascal-pensees-private-release-20261001-v1')
SOURCE=Path('raw/ccel/pascal/pensees.xml')
SOURCE_NOTE=Path('sources/private-ccel-pascal/pascal-pensees/README.source.md')
DATA_NOTE=Path('data/prose/pascal-pensees/README.md')
SCOPE='Complete retained CCEL English Trotter electronic witness of Pensées: title division,14numberedsections including SectionXIV Appendix:PolemicalFragments, and Indexes, in16ordered source divisions; no verified print-edition collation.'
MASTER='add09c83ea5f8a2ccbc2d092e46ba67bcea9797068b0febb267a3ed4d6cf7410'
NOTICE='''# Pensées: source and data credit

By Blaise Pascal, translated by W. F. Trotter, sourced via CCEL.org. The complete retained English electronic witness includes its title division, all fourteen numbered sections including Section XIV Appendix: Polemical Fragments, and Indexes. The source title division literally displays 1660; this retained statement is not verified as a print publication or translation date. No independent print-edition collation is claimed.

The electronic header credits Jon Van Hofwegen for Markup. Tim Perrine is credited as CCEL Staff Writer for the electronic description, without assigning those roles to the authored thoughts, translation or printed edition. The electronic publisher is Christian Classics Ethereal Library, Grand Rapids, MI. The electronic record's Created date is 2002-07-10 and electronic version is 1.0. Its print published and electronic transcriber fields are blank. The catalog classification B1901 .P4 1944 is retained as a classification, not asserted as a verified edition date.

The source DC.Rights says Public Domain. This is a provider claim about the retained witness, without independent worldwide rights clearance for the translation or electronic formatting.

CCEL source: https://www.ccel.org/ccel/pascal/pensees.html

CCEL permission recorded by this project permits parsing ThML/XML for text. CCEL's copyright applies to its files and formatting, rather than underlying public-domain texts. Restriction: do not sell CCEL files or derivatives of their formatting. CCEL attribution is appreciated. This provider statement does not independently clear this particular edition or translation.

CCEL policy: https://ccel.org/about/copyright.html

This is private offline technical preparation. Human acceptance, exhaustive proofreading, print collation, rights clearance and public publication remain separate.
'''

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
    audit_path=ROOT/'reports/_logs/downstream-reconciliation-review-20261001-v1/audit.json';entry=next(e for e in read(audit_path)['ranked_candidates'] if e['work_id']==WORK.name)
    local=[p.relative_to(ROOT).as_posix() for p in io_glob(ROOT/PUB,'**/*') if io_path(p).is_file()]
    if entry['dated_report_search_matches'] or entry['current_local_publication_receipts'] or local:raise ValueError('Prior proof needs reconciliation')
    src=etree.fromstring(io_path(ROOT/SOURCE).read_bytes(),etree.XMLParser(load_dtd=False,no_network=True));body=src.find('ThML.body')
    units=[dict(tag=n.tag,id=n.get('id'),title=n.get('title'),attributes=dict(n.attrib)) for n in body if isinstance(n.tag,str)]
    comments=[dict(body_child_index=body.index(n),text=n.text,tail=n.tail) for n in body if isinstance(n,etree._Comment)]
    if len(units)!=16 or sum(u['title'].startswith('SECTION ') for u in units)!=14:raise ValueError('Complete16-division source scope differs')
    authority={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/WORK,'**/*') if io_path(p).is_file() and 'publication' not in p.relative_to(ROOT/WORK).parts}
    for p in [ROOT/SOURCE,audit_path,ROOT/'reports/_logs/downstream-reconciliation-review-20261001-v1/receipt-search.json',ROOT/'docs/sources/ccel-permission.md',Path(__file__)]:authority[p.relative_to(ROOT).as_posix()]=digest(p)
    result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,acceptance_path=paths[0].relative_to(ROOT).as_posix(),accepted_master_sha256=MASTER,source_path=SOURCE.as_posix(),source_sha256=digest(ROOT/SOURCE),scope=SCOPE,source_units=units,source_dc_fields=[dict(tag=n.tag,attributes=dict(n.attrib),text=''.join(n.itertext())) for n in src.findall('.//DC/*')],source_description=''.join(src.find('.//generalInfo/description').itertext()),literal_credit_evidence=[dict(id=id,text=''.join(src.xpath('//*[@id=$id]',id=id)[0].itertext())) for id in ['i-p0.1','i-p0.2','i-p0.3','i-p0.4','xv-p0.1','xvi-p0.1']],prior_search=dict(exact_work_matches=[],canonical_publication_files=local,bounded_dated_search_reused=True,qualification='No completion located by dated bounded report/group receipt search, not universal absence proof'),patterns=['RP-13 recovered historical proof','RP-14 electronic credit and disclosure roles','RP-03 complete retained appendices and shared matter'],authority_bindings=authority,schema_implementation_bindings=runtime())
    result['source_body_comment_carriers']=comments
    result['initial_caller_census_failure_preserved']='initial-census-failure.json'
    for name in ['initial-census-failure.json','helper-before-comment-census-fix.py']:authority[(PRE/name).as_posix()]=digest(ROOT/PRE/name)
    save(ROOT/PRE/'preflight.json',result)
    print(json.dumps(dict(status='pass',source_divisions=len(units),sections=14,authority=len(authority),runtime_schema=len(result['schema_implementation_bindings']))),flush=True)
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
    if rows!=16:raise ValueError('Full16-unit route differs')
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
    selection=dict(schema_version='2.0',release_id='pascal-pensees-private-offline-20261001-v1',items=[dict(item_id=WORK.name,category='prose',acceptance_path=pre['acceptance_path'],public_notices=[dict(source_path=SOURCE_NOTE.as_posix(),source_sha256=digest(ROOT/SOURCE_NOTE),notice_path=DATA_NOTE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTE))])])
    save(ROOT/PUB/'selection.json',selection);save(OUT/'selection.json',selection)
    with cached_edition_lookups():
        texts=notice_texts_for_item(ROOT,selection['items'][0],ROOT/pre['acceptance_path'])
        if len(texts)!=1 or any(t not in texts[0] for t in ['W. F. Trotter','Jon Van Hofwegen','Tim Perrine','do not sell CCEL files','Public Domain','1660']):raise ValueError('Own required notice missing')
        save(OUT/'notice-gate.json',dict(status='pass',own_translator_markup_staff_credits_permission_and_date_qualification=True,exact_one_terminal_lf=True))
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
    done=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,scope=SCOPE,rows=rows,text_characters=chars,accepted_master_sha256=MASTER,projection_document_sha256=projected['receipt']['master_sha256'],synthetic_projection_document_used=False,source_sha256=pre['source_sha256'],source_path=SOURCE.as_posix(),canonical_authority_unchanged=True,reconstruction_performed=False,private_offline=True,publication_performed=False,release_path=release_path.as_posix(),evidence_path=OUT.as_posix(),authority_bindings=authority,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,independent_projection_producer_disabled=True,statistics_and_normal_streaming_readers='pass',remaining=['Human textual/visual review not newly performed','Independent print collation not performed;1660 source title statement not verified as edition date','Rights clearance not established by source declarations','Public publication not authorized or performed'])
    save(ROOT/PUB/'completion.json',done);save(OUT/'completion.json',done)
    print(json.dumps(dict(status='pass',rows=rows,text_characters=chars,completion_sha256=digest(ROOT/PUB/'completion.json'),authority_pins=len(authority),runtime_schema_pins=len(frozen))),flush=True)
if __name__=='__main__':
    if len(sys.argv)==1:preflight()
    elif sys.argv[1]=='project':project()
    elif sys.argv[1]=='release':release()
    else:raise ValueError('Unknown action')
