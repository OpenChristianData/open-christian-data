"""Bind the complete retained BCP1549 electronic envelope without acquisition."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import bcp1549_current_reconstruction as producer,bcp1549_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
BASE=Path('sources/liturgies-bcp1549-current/bcp-1549')
LOG=Path('reports/_logs/bcp1549-current-reconciliation-20261002-v1')
FORM='bcp-1549-retained-electronic';EDITION='bcp-1549-retained-electronic-witness'
ACQ=Path('library/works/bcp-1549/forms')/FORM/'editions'/EDITION/'acquisitions/bcp-1549-retained-source-set.json'
WORK_ID='bcp-1549';FORM_ID=FORM;EDITION_ID=EDITION;ACQUISITION_ID='bcp-1549-retained-source-set'
WORK=Path('library/works/bcp-1549');EDITION_PATH=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
TITLE='The Book of Common Prayer (1549)'
SOURCE_SHA='f22ff0f58dcd14bb7e5c9e89042e477674cea1e551c20a56b12278af202b4aa1'
DATA_NOTICE=Path('data/liturgies/bcp-1549/README.md')
OLD=Path('sources/structured-text/bcp-1549/bcp-1549.source-manifest.json')
canonical=producer.canonical
NS='{http://www.tei-c.org/ns/1.0}'
SCOPE='Complete34member retained BCP1549 electronic expression,1,560,188 primary bytes,19,975 source HTML body elements including236tables/874rows/2009cells/65rowspans/218colspans. Source-owned overview/shared1549-1552introduction/shared1549-1552-1559readings/1550ordinal and comparative1549/1552-1559columns are preserved as explicit context. This is not a pure1549print witness. Two additional retained directory/PDF-technical HTML files are support outside the unchanged34textual-member acquisition. Missing linked PDFs/images are qualified; no source deletion, new work identities, acquisitions or restored print wording.'

def put(path,raw):
    target=io_path(ROOT/path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
def binding(name,path,role):
    raw=io_path(ROOT/path).read_bytes()
    return dict(name=name,path=path.as_posix(),role=role,bytes=len(raw),sha256=sha256(raw).hexdigest())

def main():
    acquired=validate_acquisition(ROOT/ACQ,root=ROOT)
    if acquired['source_sha256']!='f22ff0f58dcd14bb7e5c9e89042e477674cea1e551c20a56b12278af202b4aa1':raise ValueError('Original acquisition aggregate differs')
    original=json.loads(io_path(ROOT/OLD).read_bytes())
    if {(m['path'],m['sha256'],m['bytes']) for m in acquired['retained_files']}!={(m['path'],m['sha256'],m['bytes']) for m in original['source_members']}:raise ValueError('Original34member scope differs')
    support=[]
    for name,disposition in [('_index.html','Retained Apache directory listing:inventory support,not liturgical text.'),('PDF_Notes.htm','Retained PDF-technical support:actualbody Notes on the PDF files; misleading copied HTMLtitle is not the content identity. SeparatePDFpresentation,not a1549service.')]:
        p=Path('raw/bcp-full-text/bcp-1549')/name;r=binding('support-'+name,p,'retained-support')
        support.append(dict(path=p.as_posix(),bytes=r['bytes'],sha256=r['sha256'],disposition=disposition))
    files={p.name for p in io_path(ROOT/'raw/bcp-full-text/bcp-1549').iterdir() if p.is_file()}
    if files!=set(producer.READING_ORDER)|{'_index.html','PDF_Notes.htm'}:raise ValueError('Retained36file envelope differs')
    h=producer.header();b=h.find(NS+'fileDesc/'+NS+'sourceDesc/'+NS+'bibl')
    etree.SubElement(b,NS+'note',type='source-native-representation').text='All retained body tables, cell spans, inline emphasis, literal label spelling, image URIs/alternatives, original ordered HTML attributes and text/tails are conserved. HTML recovered hierarchy is explicit, not a print or browser visual collation. Sole Baptism paragraph directly under source ul has a declared generated TEI grammar wrapper, not an invented source li. No inferred response edges or person authority.'
    etree.SubElement(b,NS+'note',type='source-character-decoding').text='198literal numeric references &#149; and1literal &#151; represent HTML-visible bulletU2022/em dashU2014. Their original bytes, exact lexemes and offsets remain in the reversible decoder ledger. No source spelling/whitespace corrections are applied.'
    etree.SubElement(b,NS+'note',type='source-link-resolution').text='Literal href/anchor attributes and source-member URLs remain in the external crosswalk. TEIref targets resolve relative HTMLhref against each original primary-source member URL, including same-pagefragments; these are original-source hyperlinks, not resolving generatedTEI authority fragments. Remote availability and unretained linked assets remain unassessed.'
    etree.SubElement(b,NS+'note',type='rights-qualification').text='No explicit retained electronic permission notice was identified. The inherited source-config public-domain/Mammana transcription assertions are historical and are not corroborated as electronic rights/contributor authority. Print edition claims, human textual acceptance, visual collation, electronic transcription rights and public publication remain separate.'
    questions=[dict(id='bcp1549-'+kind,kind=kind,status='unresolved',detail=detail) for kind,detail in [('print','Complete declared electronic envelope contains shared/comparative material; not a pure1549print witness.'),('contributor','LiteralWebauthorCharlesWohlers and introductionauthorEdwardC.S.Gibson roles retained; inheritedMammana transcriber claim uncorroborated.'),('assets','Linked PDFs/images are not physically retained; literal reference/alt and support context conserved.'),('parser','Explicit recoveredHTML hierarchy and source-visible numeric reference decoding; browser/print visual collation not performed.'),('rights','No explicit retained electronic permission identified; inheritedpublicdomain is not clearance.'),('human','No human textual acceptance.'),('publication','No public publication action or authorization.')]]
    profile=dict(work_id='bcp-1549',textual_form_id=FORM,edition_id=EDITION,projection_profile='ocd-liturgies-bcp1549-retained-members-v1',source_sha256=acquired['source_sha256'],scope=SCOPE,header_xml=etree.tostring(h,encoding='unicode'),reading_order=list(producer.READING_ORDER),source_members=original['source_members'],acquired_member_order=[Path(m['path']).name for m in acquired['retained_files']],retained_support=support,questions=questions,historical_metadata_disposition='Old sourceconfig/profile/flattenedTEI preserved as historicalregression evidence, not current source-fidelity authority. Current source-specific profile supersedes unsupported contributor/rights assertions.')
    put(BASE/'profile.json',canonical(profile))
    put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,rules=['Complete34nativeHTML bodies exact inverse including hierarchy/text/tails/orderedattrs/IDs','Original198bullet+1em dash lexical/byte-offset decoder ledger','All236tables/65rowspans/218colspans including native usable row_span','Exact34member source-owned readingorder with acquiredorder crosswalk','Sole explicit generated grammar wrapper inverse','Exact original-source href resolution independentcrosswalk','All36retained files disposition','P5','Fresh deterministic package replay and meaningful negative mutations'],qualification='Separate producer/inverse oracle share declared libxml HTML recovery; numeric visible reference decoding is independently derived by Python HTML decoder. Technical conservation is not print/browser visual collation, human acceptance or rights clearance.')))
    notice='# BCP1549 retained electronic edition: source and data credit\n\nRetained primary location: [Justus Anglican BCP1549](http://justus.anglican.org/resources/bcp/1549/).\n\n'+SCOPE+'\n\nLiteral primary footers credit **Charles Wohlers as Web author**. The shared introduction is attributed to **Edward C. S. Gibson, Bishop of Gloucester**. These roles are retained as stated; Web author is not silently rewritten as transcriber. The inherited Mammana transcription assertion is uncorroborated by these retained pages.\n\nThe overview describes a1910Everyman reprint, source modernizations/variants, and qualified probable original-print claims. The PDFtechnical notes describe a different facsimile presentation. Shared readings,1550ordinal/comparative columns and electronic editorial context remain explicit. All34sourcebody members and236tables are preserved, including source-owned site context. All65rowspans/218colspans and original inline labels/emphasis remain structured. No inferred persons/response links or corrected spelling.\n\nAll36physical retained files are accounted. `_index.html` is directory inventory support; `PDF_Notes.htm` is PDF-technical support despite its copied HTMLtitle. Both remain outside the unchanged34textual-member acquisition. No PDFs/images were downloaded;105image references, literal alternate text and all source attributes remain preserved. Literal original hrefs and their original-source URL resolution remain qualified hyperlinks, not generated TEIauthority links.\n\nThe199numeric reference lexemes/byteoffsets remain private evidence; readable glyphs follow source-defined HTML decoding (198bullets and1em dash). Recovered HTML hierarchy is explicit; no print/browser visual collation is claimed.\n\nNo explicit retained electronic permission notice was found. The inherited public-domain claim does not establish electronic transcription rights or publication clearance. Human acceptance, print identity, rights clearance and public publication remain separate. Carry this visible notice to `data/liturgies/bcp-1549/README.md`.\n'
    put(BASE/'README.source.md',notice.encode())
    authorities=[binding('profile',BASE/'profile.json','complete-source-feature-profile'),binding('validation-policy-current',BASE/'validation-policy.json','independent-validation-policy'),binding('source-readme',BASE/'README.source.md','visible-source-credit'),binding('canonical-acquisition',ACQ,'current-retained-member-set'),binding('original-source-manifest',OLD,'readonly-historical-source-manifest')]
    for a in original['authorities']:
        if a['role'] in ('primary-source','candidate-package-schema','tei-validation-schema'):
            authorities.append(binding(a['name'],Path(a['path']),a['role']))
    for s in support:authorities.append(binding('support-'+Path(s['path']).name,Path(s['path']),'retained-support'))
    manifest=dict(contract='ocd-source-manifest-v1',ticket_id='37c-073',source_id='bcp1549-complete-retained-native-current-v1',work_id='bcp-1549',textual_form_id=FORM,edition_id=EDITION,acquisition_id='bcp-1549-retained-source-set',scope=SCOPE,source_bundle=original['source_bundle'],source_members=original['source_members'],authorities=authorities,converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable='_convert',implementation_path='build/tei/bcp1549_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable='_oracle',implementation_path='build/tei/bcp1549_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=original['package_schema'])
    put(BASE/'source-manifest.json',canonical(manifest))
    scope=dict(status='prepared-not-accepted',created_utc=datetime.now(timezone.utc).isoformat(),source_manifest_sha256=sha256(canonical(manifest)).hexdigest(),scope=SCOPE,source_members=original['source_members'],retained_support=support,physical_file_count=36,reading_order=list(producer.READING_ORDER),acquired_order=profile['acquired_member_order'],immutable_work_sha256=sha256(io_path(ROOT/'library/works/bcp-1549/work.json').read_bytes()).hexdigest())
    put(LOG/'current-source-scope.json',canonical(scope))
    print(json.dumps(dict(status='prepared',members=34,retained_support=2,source_sha256=acquired['source_sha256'],source_manifest= str(BASE/'source-manifest.json'))))

if __name__=='__main__':main()
