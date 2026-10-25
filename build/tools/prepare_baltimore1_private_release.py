"""Reconcile unchanged accepted catechism/source and prepare visible own-source credits."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.tei.acceptance import validate_acceptance

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='baltimore-catechism-no-1';WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms/baltimore-catechism-no-1-retained-english/editions/baltimore-catechism-no-1-gutenberg-electronic-witness'
ACQUISITION=EDITION/'acquisitions/baltimore-catechism-no-1-gutenberg-retained.json'
SOURCE=Path('raw/gutenberg/pg14551.txt');SOURCE_SHA='d4b49653b457cc11f39df004896d072892b534e49899def16cdd75761c80993e'
LOG=Path('reports/_logs/baltimore-catechism-no-1-downstream-preflight-20261002-v1')
BASE=Path('sources/publication/baltimore-catechism-no-1-pg14551')
DATA_NOTICE=Path('data/catechisms/baltimore-catechism-no-1/README.md')
NS={'t':'http://www.tei-c.org/ns/1.0'}

def digest(p):return sha256(io_path(ROOT/p).read_bytes()).hexdigest()
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def main():
    if (ROOT/LOG).exists() or (ROOT/BASE).exists():raise FileExistsError('Fresh own preflight/notice evidence required')
    (ROOT/LOG).mkdir(parents=True);(ROOT/BASE).mkdir(parents=True)
    accepted_raw=io_path(ROOT/EDITION/'master.tei.xml').read_bytes();source_raw=io_path(ROOT/SOURCE).read_bytes()
    if sha256(accepted_raw).hexdigest()!='0167bf6b53410ede7fcc20737634b61090d538ab6aa1c946bc3111df5f522cdd' or sha256(source_raw).hexdigest()!=SOURCE_SHA:raise ValueError('Expected accepted master/source differs')
    with cached_edition_lookups():accepted=validate_acceptance(ROOT/EDITION/'acceptance.json',root=ROOT)
    doc=etree.fromstring(accepted_raw)
    lines=doc.xpath('./t:text/t:body//t:div[@type="source-line"]',namespaces=NS)
    physical=source_raw.decode('utf-8-sig').splitlines(keepends=True)
    payloads=[line[:-2] if line.endswith('\r\n') else line[:-1] if line.endswith('\n') or line.endswith('\r') else line for line in physical]
    if len(lines)!=len(payloads) or len(lines)!=2620:raise ValueError('Complete source physical-line census differs')
    for n,(line,payload) in enumerate(zip(lines,payloads),1):
        if len(line)!=1 or len(line[0]) or line[0].get('n')!=str(n) or (line[0].text or '')!=payload:
            raise ValueError('Literal retained source line differs: '+str(n))
    question_count=len(doc.xpath('./t:text/t:body//t:div[@type="question-answer"]',namespaces=NS))
    source_check=dict(status='pass',source_sha256=SOURCE_SHA,master_sha256=sha256(accepted_raw).hexdigest(),physical_lines=2620,question_answer_groups=question_count,
        method='Direct retained UTF-8/BOM and CRLF physical-line payload comparison in source order against every indexed accepted source-line carrier. No producer/oracle imported.',
        qualifications=['Transport BOM and physical line terminators are framing; all line payloads and blank slots compared literally.','Existing detailed source accounting and visual review remain dated evidence; no renewed print collation claimed.'])
    (ROOT/LOG/'direct-installed-source-line-corroboration.json').write_bytes(canonical(source_check))
    old=[]
    for path in ['plans/2026-09-22-source-preflight/whole-library-offline-rehearsal-20260925-r2/selection.json','plans/2026-09-22-source-preflight/whole-library-offline-rehearsal-20260926-selection/selection.json','plans/2026-09-22-source-preflight/whole-library-offline-rehearsal-20260926-35-evidence/release-report.precheck.json']:
        p=ROOT/path
        if p.exists():
            record=json.loads(p.read_bytes());item=[x for x in record.get('items',[]) if WORK_ID in x.get('item_id','')]
            old.append(dict(path=path,sha256=digest(Path(path)),report_status=record.get('status'),selected_items=item))
    source_text=source_raw.decode('utf-8-sig').replace('\r\n','\n')
    license_text=source_text[source_text.index('START: FULL LICENSE'):]
    note="""# Baltimore Catechism No. 1: retained electronic source and use notice

This complete retained Project Gutenberg eBook 14551 is the electronic witness of *A catechism of Christian doctrine, no. 1: for first communion classes*, with prayers and hymns. Its 2,620 physical source lines remain in one accepted TEI and one complete structured source-transcription record; the question/answer index supplements that entire text rather than replacing it. Provider header, title, approvals, composite-transcription note, prayers, all lessons/questions/answers, hymns, end markers and full retained license remain included.

The retained provider header literally lists J. De Concilio and Saint Roberto Francesco Romolo Bellarmino as authors, Catholic Church. Plenary Council of Baltimore as creator, John Lancaster Spalding as editor, and "Produced by Dennis McCarthy" as electronic credit. The work title says prepared and enjoined by order of the Third Plenary Council of Baltimore. An older end marker calls it "Baltimore Catechism No. 1 (of 4), by Anonymous"; this remains source context and does not override the provider's distinct contributor statements. No inferred translator or print publisher is asserted.

The source lists electronic release January 1, 2005 and most recent update October 28, 2024. Its approvals are dated April 6, 1885 in New York and Baltimore; those are literal approval dates, not proof of this electronic witness's exact print exemplar. The transcriber's note says it substantially uses files from catholic.net with missing material added, and preserves numbering gaps/out-of-order questions and minor differences from No. 2. The Holy Communion answer includes its literal note about a 1977 revision. This is a composite electronic witness, not an independently collated 1885 printed edition. Human acceptance, exhaustive proofreading, print identity, rights clearance and public publication remain separate.

The retained wrapper permits copying/reuse under its included or online Project Gutenberg License, and directs users outside the United States to check their local laws. Preserve this credit and the complete retained license when distributing Gutenberg-branded material. The license includes the original-format availability requirement for alternate-format distribution; the retained original text remains evidence, and this private package does not claim public-distribution compliance or independent rights clearance. No downloads or external contact were performed. The full license below is reproduced from this own retained member; it is not transferred from another work or fetched online.

Source reference: https://www.gutenberg.org/ebooks/14551 . The full source/use notice is provided at `data/catechisms/baltimore-catechism-no-1/README.md` and must accompany generated data for this edition. Underlying text, modern electronic contribution, Project Gutenberg trademark and country-specific rights questions remain distinct. Repository software licensing does not clear them.

## Full retained Project Gutenberg license and closing provider information

"""+license_text
    for p in [ROOT/BASE/'README.source.md',ROOT/DATA_NOTICE]:
        io_path(p).parent.mkdir(parents=True,exist_ok=True)
        if io_path(p).exists():raise FileExistsError(p)
        io_path(p).write_text(note,encoding='utf-8',newline='\n')
    authority={p.relative_to(ROOT).as_posix():digest(p.relative_to(ROOT)) for p in io_glob(ROOT/WORK,'**/*') if io_path(p).is_file()}
    authority[SOURCE.as_posix()]=SOURCE_SHA
    dependencies=['ocd_kernel/projection/categories/catechisms.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','schemas/v2/native-content.schema.json','schemas/v2/categories/catechisms.schema.json','schemas/v2/public-row.schema.json','ocd_kernel/reconstruction/contract.py','ocd_kernel/tei/acceptance.py','ocd_kernel/library/identities.py','ocd_kernel/release/notices.py']
    preflight=dict(status='accepted-master-reconciled-downstream-required',utc=datetime.now(timezone.utc).isoformat(),work_id=WORK_ID,
        source=source_check,accepted_scope=accepted['scope'],accepted_master_sha256=digest(EDITION/'master.tei.xml'),acceptance_sha256=digest(EDITION/'acceptance.json'),
        authority=authority,dependencies={p:digest(Path(p)) for p in dependencies},
        existing_handoffs='Canonical complete native master and work-local single-source-agent-handoff/package/accounting/visual proof physically retained; unchanged accepted master reused.',
        receipt_search=dict(search='Explicit ignored reports/_logs, exports and dated source-preflight selection/release/verification/completion formats, plus work-local canonical publication paths.',
            existing=old,qualification='Located dated whole-library rehearsal selection/precheck evidence, not an independently completed own-work private package. No direct/nested canonical completion; no bound independent closeout discovered. Earlier source/acceptance proofs remain dated and unchanged.'),
        next='Unchanged actual accepted-master catechism projection and saved producer-disabled independent linkage; normal private assembly/verifiers/statistics/readers, paired complete source license/credits and canonical completion/selection accounting.',
        notice=dict(source_path=(BASE/'README.source.md').as_posix(),source_sha256=digest(BASE/'README.source.md'),notice_path=DATA_NOTICE.as_posix(),notice_sha256=digest(DATA_NOTICE)),
        unchanged_authorities='No source, work, state, acquisition, acceptance, master, shared runtime or schema edits.')
    (ROOT/LOG/'preflight.json').write_bytes(canonical(preflight));print(json.dumps(dict(status=preflight['status'],master_sha256=preflight['accepted_master_sha256'],source_sha256=SOURCE_SHA,lines=2620,question_answer_groups=question_count,prior_release_items=old)))

if __name__=='__main__':main()
