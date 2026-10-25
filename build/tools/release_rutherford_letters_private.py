"""Bind an unchanged full accepted Rutherford master to one private release."""
from build.tools.complete_rutherford_letters_private_release import ROOT,WORK,PUB,PRE,OUT,SOURCE,SOURCE_NOTE,DATA_NOTE,SCOPE,digest,read,save,runtime
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from build.tools.report_release_stats import release_statistics
from build.tools.check_release_reader import check_reader

NOTICE = '''# A Selection from his Letters: source and data credit

Letters by Samuel Rutherford, sourced via CCEL.org. The retained electronic title is A Selection from his Letters. This release contains the complete retained electronic selection: Title Page, Contents, Foreword, Letters, Glossary and Indexes. Its 71 letter divisions do not constitute all surviving Rutherford correspondence or necessarily complete historical letters.

The Foreword is signed HUGH MARTIN. Its author describes selecting representative letters, omitting passages to avoid repetition and historical argumentation, arranging letters chronologically where dates are ascertainable, and providing a glossary. These stated abridgments remain part of this witness; this release does not restore omitted text. Emmalon Davis is credited as CCEL Staff Writer for the electronic description, without assigning that role to the letters or Foreword.

The electronic publisher is Grand Rapids, MI: Christian Classics Ethereal Library. The electronic record's Created date is 2000-07-09; it is not a print publication date. The retained print published field, source edition fields and DC.Rights are blank. No verified print edition, print date or complete textual review is asserted.

CCEL source: https://www.ccel.org/ccel/rutherford/letters.html

CCEL permission recorded by this project permits parsing ThML/XML for text. CCEL's copyright applies to its files and formatting, rather than underlying public-domain texts. Restriction: do not sell CCEL files or derivatives of their formatting. CCEL attribution is appreciated. This provider statement does not establish independent rights clearance for this particular selection, Foreword, glossary or editorial apparatus.

CCEL policy: https://ccel.org/about/copyright.html

This is private offline technical preparation. Human acceptance, exhaustive proofreading, print collation, rights clearance and public publication remain separate.
'''

def native_text(n):
    if n['kind']=='text':return n['text']
    return ''.join(native_text(c) for c in n.get('content',[]))
def native_nodes(n):
    yield n
    for child in n.get('content',[]):yield from native_nodes(child)
def table_check(projection, master):
    raw=etree.fromstring(io_path(ROOT/SOURCE).read_bytes(),etree.XMLParser(load_dtd=False,no_network=True))
    original=raw.findall('.//tr');tei=etree.fromstring(io_path(master).read_bytes())
    mapped=tei.findall('.//{http://www.tei-c.org/ns/1.0}row')
    public=[n for row in projection['rows'] for node in row['structure'] for n in native_nodes(node) if n['kind']=='table-row']
    if len(original)!=74 or len(mapped)!=74 or len(public)!=74:raise ValueError('Table row loss')
    cells=0;heads=0
    for src,mt,out in zip(original,mapped,public):
        source_cells=[n for n in src if n.tag in ('td','th')]
        master_cells=[n for n in mt if n.tag=='{http://www.tei-c.org/ns/1.0}cell']
        output_cells=[n for n in out['content'] if n['kind']=='table-cell']
        if not len(source_cells)==len(master_cells)==len(output_cells):raise ValueError('Cell attachment loss')
        for sc,mc,pc in zip(source_cells,master_cells,output_cells):
            value=''.join(sc.itertext())
            if value!=''.join(mc.itertext()) or value!=native_text(pc):raise ValueError('Table cell text/order loss')
            expected={}
            if sc.get('colspan'):expected['columns']=sc.get('colspan')
            if sc.tag=='th':expected['source_role']='label';heads+=1
            if pc['attributes']!=expected:raise ValueError('Table cell span/role differs')
            cells+=1
    if cells!=218 or heads!=1:raise ValueError('Cell census mismatch')
    return dict(status='pass',source_rows=74,master_rows=74,public_rows=74,source_td=217,source_th=1,master_public_cells=cells,ordered_cell_texts_and_row_attachments_equal=True,colspan_and_header_role_preserved=True,qualification='Focused direct retained-source table comparison, not new whole-work reconstruction proof')

def main():
    if OUT.exists() or io_path(ROOT/PUB/'completion.json').exists():raise FileExistsError('Reconcile existing completion')
    pre=read(ROOT/PRE/'preflight-v2.json');authority=dict(pre['current_authority_bindings']);frozen=runtime()
    if frozen!=pre['runtime_bindings']:raise ValueError('Reviewed runtime drift')
    for p,h in authority.items():
        if digest(ROOT/p)!=h:raise ValueError('Preflight authority drift '+p)
    authority['build/tools/release_rutherford_letters_private.py']=digest(Path(__file__))
    for p in ('preflight.json','preflight-v2.json','actual-master-projection.json'):authority[(PRE/p).as_posix()]=digest(ROOT/PRE/p)
    OUT.mkdir(parents=True);save(OUT/'authority-before.json',authority);save(OUT/'schema-implementation-before.json',frozen)
    projected=read(ROOT/PRE/'actual-master-projection.json');acceptance=ROOT/pre['acceptance_path'];a=read(acceptance);master=ROOT/a['promotion']['master']['path']
    if len(projected['rows'])!=6 or sum(len(r['text']) for r in projected['rows'])!=230086 or projected['receipt']['master_sha256']!=digest(master) or projected['receipt']['authority']['master']['sha256']!=digest(master):raise ValueError('Full master binding/count differs')
    save(OUT/'actual-master-projection.json',projected);save(ROOT/PUB/'actual-master-projection.json',projected)
    independent='''import sys,json,os,hashlib
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import verify_accepted_prose
import ocd_kernel.projection.native_content as producer
def unavailable(*args,**kwargs):raise AssertionError('producer or renderer invoked by checker')
producer.project_content=unavailable
producer.readable_content=unavailable
root,acceptance,projected=map(Path,sys.argv[1:]);raw=projected.read_bytes();p=json.loads(raw)
with cached_edition_lookups():errors=verify_accepted_prose(root,acceptance_path=acceptance,rows=p['rows'],receipt=p['receipt'])
print(json.dumps(dict(status='fail' if errors else 'pass',errors=errors,pid=os.getpid(),producer_disabled=True,projection_sha256=hashlib.sha256(raw).hexdigest())))
raise SystemExit(bool(errors))
'''
    argv=[sys.executable,'-c',independent,str(ROOT),str(acceptance),str(OUT/'actual-master-projection.json')]
    try:result=subprocess.run(argv,cwd=ROOT,check=True,capture_output=True,text=True,encoding='utf-8')
    except subprocess.CalledProcessError as exc:
        save(OUT/'independent-projection-command.json',dict(argv=argv,exit_code=exc.returncode,stdout=exc.stdout,stderr=exc.stderr));raise
    checked=json.loads(result.stdout)
    if checked['status']!='pass' or checked['projection_sha256']!=digest(OUT/'actual-master-projection.json'):raise ValueError('Independent linkage differs')
    save(OUT/'independent-projection-command.json',dict(argv=argv,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    save(OUT/'independent-projection-linkage.json',checked)
    save(OUT/'source-master-public-table-check.json',table_check(projected,master))
    print('Full master producer-disabled independent linkage and direct74row/218cell proof: pass',flush=True)
    for p,text in [(DATA_NOTE,NOTICE),(SOURCE_NOTE,NOTICE+'\nThe human-visible data attribution is maintained at `'+DATA_NOTE.as_posix()+'`.\n')]:
        payload=(text.rstrip('\n')+'\n').encode();q=io_path(ROOT/p)
        if q.exists() and q.read_bytes()!=payload:raise FileExistsError('Existing notice differs '+str(p))
        q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(payload);authority[p.as_posix()]=digest(q)
    selection=dict(schema_version='2.0',release_id='rutherford-letters-private-offline-20261001-v1',items=[dict(item_id=WORK.name,category='prose',acceptance_path=pre['acceptance_path'],public_notices=[dict(source_path=SOURCE_NOTE.as_posix(),source_sha256=digest(ROOT/SOURCE_NOTE),notice_path=DATA_NOTE.as_posix(),notice_sha256=digest(ROOT/DATA_NOTE))])])
    save(ROOT/PUB/'selection.json',selection);save(OUT/'selection.json',selection)
    with cached_edition_lookups():
        texts=notice_texts_for_item(ROOT,selection['items'][0],acceptance)
        if len(texts)!=1 or any(t not in texts[0] for t in ['HUGH MARTIN','Emmalon Davis','do not sell CCEL files','DC.Rights are blank','71 letter divisions']):raise ValueError('Own credit/permission notice missing')
        save(OUT/'notice-gate.json',dict(status='pass',own_credits_permission_and_selection_qualification_visible=True,exact_one_terminal_lf=True))
        release=OUT/'release';assembled=assemble_release_v2(ROOT,release,selection=selection);save(OUT/'assembly.json',assembled)
        if assembled['status']!='pass':raise ValueError(assembled)
        print('Private assembly: pass',flush=True)
        for name,op in [('independent-verification',lambda:verify_release_v2(ROOT,release,selection=selection)),('statistics',lambda:release_statistics(ROOT,release,selection)),('readers',lambda:check_reader(ROOT,release,selection))]:
            value=op();save(OUT/(name+'.json'),value)
            if value['status']!='pass':raise ValueError(value)
            print(name+': pass',flush=True)
    visible=io_path(release/'public/README.md').read_bytes()
    if io_path(ROOT/DATA_NOTE).read_bytes().rstrip() not in visible:raise ValueError('Released notice missing')
    save(OUT/'released-notice-check.json',dict(status='pass',exact_own_notice_embedded=True,public_readme_sha256=sha256(visible).hexdigest()))
    if runtime()!=frozen:raise ValueError('Final runtime drift')
    for p,h in authority.items():
        if digest(ROOT/p)!=h:raise ValueError('Final authority drift '+p)
    save(OUT/'authority-after.json',authority);save(OUT/'schema-implementation-after.json',frozen)
    files={p.relative_to(release).as_posix():digest(p) for p in release.rglob('*') if p.is_file()};save(OUT/'release-file-hashes.json',files)
    evidence={p.relative_to(OUT).as_posix():digest(p) for p in OUT.glob('*.json')}
    completion=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,scope=SCOPE,rows=6,text_characters=230086,letters=71,table_rows=74,table_cells=218,accepted_master_sha256=digest(master),projection_document_sha256=projected['receipt']['master_sha256'],synthetic_projection_document_used=False,source_sha256=digest(ROOT/SOURCE),source_path=SOURCE.as_posix(),reconstruction_performed=False,canonical_authority_unchanged=True,private_offline=True,publication_performed=False,release_path=release.as_posix(),evidence_path=OUT.as_posix(),authority_bindings=authority,schema_implementation_bindings=frozen,release_file_bindings=files,release_evidence_bindings=evidence,independent_projection_producer_disabled=True,source_table_direct_check='pass',statistics_and_normal_streaming_readers='pass',remaining=['Human textual/visual review not newly performed','Independent print collation not performed','Historical letters are abridged in this source selection','Print identity and rights clearance unresolved','Public publication not authorized or performed'])
    save(OUT/'completion.json',completion);save(ROOT/PUB/'completion.json',completion)
    print(json.dumps(dict(status='pass',rows=6,text_characters=230086,completion_sha256=digest(ROOT/PUB/'completion.json'),authority_pins=len(authority),runtime_schema_pins=len(frozen))))
if __name__=='__main__':main()
