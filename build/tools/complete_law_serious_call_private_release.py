"""Reuse the complete accepted Law electronic witness for private preparation."""
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
WORK=Path('library/works/law-serious-call');PUB=WORK/'publication'
PRE=Path('reports/_logs/law-serious-call-downstream-preflight-20261001')
OUT=Path('D:/Library/Open Christian Data/reports/_logs/law-serious-call-private-release-20261001-v1')
SOURCE=Path('raw/ccel/law/serious_call.xml')
SOURCE_NOTE=Path('sources/private-ccel-law/law-serious-call/README.source.md')
DATA_NOTE=Path('data/prose/law-serious-call/README.md')
SCOPE='Complete retained CCEL electronic witness: Title Page, 24 chapters, Appendices A–C, Indexes and Acknowledgements, in 30 ordered source divisions; no verified print-edition collation.'
MASTER='bddab41de3c3604871caf1be6a98c85610d286b67f90ae9c6cdb8ebc6941757d'
NOTICE='''# A Serious Call to a Devout and Holy Life: source and data credit

By William Law, sourced via CCEL.org. The complete retained electronic witness includes its Title Page, 24 chapters, Appendices A–C, Indexes and Acknowledgements. The source title page states London, printed for William Innys, MDCCXXIX. Appendix A also states 1729; Appendix B states 1728. These differing source claims remain unresolved; this is not an independently collated print edition.

Appendix A is explicitly from the Introduction to the Methuen edition by C. Bigg, DD, with its November 1899 publication statement qualified to that edition. Appendix B is from the Introduction to the Dent Everyman edition. Appendix C is signed John Harris, dated 24th January 1994, Bristol, England. Harris reports scanning the Dent Everyman text and following its omission of the original italics. He labels this release 1.0 and requests all distributed copies bear the name WLSCHL10.xxx. These statements and source editorial choices are retained without restoring omitted italics or claiming verified print identity. Historical contact details in that appendix remain in the accepted private text; future public disclosure is a separate decision.

Tim Perrine is credited as CCEL Staff Writer for the electronic description, without assigning that role to the authored book or appendices. The electronic publisher is Grand Rapids, MI: Christian Classics Ethereal Library. The electronic record's Created date is 2000-07-09, not a print date. Its print published, DC.Rights, electronic transcriber and markup fields are blank. Its Proofed subject is a provider-supplied claim, not newly performed exhaustive proofreading.

Appendix C calls the electronic edition Public Domain and reports advice that the two introductions are free of copyright restriction. These remain source claims, without independent rights clearance. The Acknowledgements separately states that the cover art is a derivative of a linked Flickr work available under Creative Commons Attribution Share-Alike 3.0; that statement concerns the cover art, not a blanket license for all text. No cover image is acquired or distributed here.

CCEL source: https://www.ccel.org/ccel/law/serious_call.html

CCEL permission recorded by this project permits parsing ThML/XML for text. CCEL's copyright applies to its files and formatting, rather than underlying public-domain texts. Restriction: do not sell CCEL files or derivatives of their formatting. CCEL attribution is appreciated. This provider statement does not independently clear the particular edition or its editorial apparatus.

CCEL policy: https://ccel.org/about/copyright.html

This is private offline technical preparation. Human acceptance, exhaustive proofreading, print collation, rights clearance, source distribution-name requirements, historical-contact disclosure and public publication remain separate.
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
    units=[dict(tag=n.tag,id=n.get('id'),title=n.get('title'),attributes=dict(n.attrib)) for n in body]
    if len(units)!=30 or sum(u['title'].startswith('Chapter ') for u in units)!=24:raise ValueError('Complete30-division source scope differs')
    authority={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/WORK,'**/*') if io_path(p).is_file() and 'publication' not in p.relative_to(ROOT/WORK).parts}
    for p in [ROOT/SOURCE,audit_path,ROOT/'reports/_logs/downstream-reconciliation-review-20261001-v1/receipt-search.json',ROOT/'docs/sources/ccel-permission.md',Path(__file__)]:authority[p.relative_to(ROOT).as_posix()]=digest(p)
    result=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,acceptance_path=paths[0].relative_to(ROOT).as_posix(),accepted_master_sha256=MASTER,source_path=SOURCE.as_posix(),source_sha256=digest(ROOT/SOURCE),scope=SCOPE,source_units=units,source_dc_fields=[dict(tag=n.tag,attributes=dict(n.attrib),text=''.join(n.itertext())) for n in src.findall('.//DC/*')],source_description=''.join(src.find('.//generalInfo/description').itertext()),literal_credit_evidence=[dict(id=id,text=''.join(src.xpath('//*[@id=$id]',id=id)[0].itertext())) for id in ['i-p22','i-p25','xxvi-p2','xxvi-p3','xxvi-p5','xxvii-p8','xxviii-p9','xxviii-p10','xxviii-p12','xxviii-p14','xxviii-p18']],prior_search=dict(exact_work_matches=[],canonical_publication_files=local,bounded_dated_search_reused=True,qualification='No completion located by dated bounded report/group receipt search, not universal absence proof'),patterns=['RP-13 recovered historical proof','RP-14 electronic credit and disclosure roles','RP-03 complete retained appendices and shared matter'],authority_bindings=authority,schema_implementation_bindings=runtime())
    save(ROOT/PRE/'preflight.json',result)
    print(json.dumps(dict(status='pass',source_divisions=len(units),chapters=24,authority=len(authority),runtime_schema=len(result['schema_implementation_bindings']))),flush=True)
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
    if rows!=30:raise ValueError('Full30-unit route differs')
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
    selection=dict(schema_version='2.0',release_id='law-serious-call-private-offline-20261001-v1',items=[dict(item_id=WORK.name,category='prose',acceptance_path=pre['acceptance_path'],public_notices=[dict(source_path=SOURCE_NOTE.as_posix(),source_sha256=digest(ROOT/SOURCE_NOTE),notice_path=DATA_NOTE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTE))])])
    save(ROOT/PUB/'selection.json',selection);save(OUT/'selection.json',selection)
    with cached_edition_lookups():
        texts=notice_texts_for_item(ROOT,selection['items'][0],ROOT/pre['acceptance_path'])
        if len(texts)!=1 or any(t not in texts[0] for t in ['John Harris','Tim Perrine','WLSCHL10.xxx','do not sell CCEL files','cover art','1728']):raise ValueError('Own required notice missing')
        save(OUT/'notice-gate.json',dict(status='pass',own_credits_permission_distribution_name_and_cover_qualification=True,exact_one_terminal_lf=True))
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
    done=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,scope=SCOPE,rows=rows,text_characters=chars,accepted_master_sha256=MASTER,projection_document_sha256=projected['receipt']['master_sha256'],synthetic_projection_document_used=False,source_sha256=pre['source_sha256'],source_path=SOURCE.as_posix(),canonical_authority_unchanged=True,reconstruction_performed=False,private_offline=True,publication_performed=False,release_path=release_path.as_posix(),evidence_path=OUT.as_posix(),authority_bindings=authority,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,independent_projection_producer_disabled=True,statistics_and_normal_streaming_readers='pass',remaining=['Human textual/visual review not newly performed','Independent print collation not performed;1729/1728 source claims unresolved','Rights clearance not established by source declarations','Historical contact disclosure and distribution-name requirement need separate publication decision','Public publication not authorized or performed'])
    save(ROOT/PUB/'completion.json',done);save(OUT/'completion.json',done)
    print(json.dumps(dict(status='pass',rows=rows,text_characters=chars,completion_sha256=digest(ROOT/PUB/'completion.json'),authority_pins=len(authority),runtime_schema_pins=len(frozen))),flush=True)
if __name__=='__main__':
    if len(sys.argv)==1:preflight()
    elif sys.argv[1]=='project':project()
    elif sys.argv[1]=='release':release()
    else:raise ValueError('Unknown action')
