"""Renew only work-local header/current bindings around the checked native body."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import brainerd_current_reconstruction as producer,brainerd_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='edwards-life-of-brainerd'
FORM_ID=WORK_ID+'-english'
EDITION_ID=WORK_ID+'-retained-electronic-witness'
ACQUISITION_ID=WORK_ID+'-retained-source'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/ccel-brainerd-current')/WORK_ID
SOURCE=Path('raw/ccel/edwards/brainerd.xml')
SOURCE_SHA='11722441be48a4746a03c54a31b5c73e8905a64682e2681050fe74ef178f177e'
TITLE='The Life of David Brainerd'
LOG=Path('reports/_logs/brainerd-reconciliation-20261001-v1')
HISTORICAL=LOG/'historical-package/content.tei.xml'
SCOPE="Complete retained raw/ccel/edwards/brainerd.xml ThML.body/div1 id=ix, source-titled Life and Diary of the Rev. David Brainerd with Notes and Reflections: complete preface/memoir and diary, journal in two parts, advertisement and journal preface, three appendices, remains and letters, advertisement, detached papers, E. Pemberton's ordination sermon and Edwards's reflections. All 12 major divisions, 8,545 native carriers, 105 source heading carriers, 88 notes, 146 page breaks, 246 scripture-reference carriers and their source-native hierarchy, wording, exact text/tails and mapped meaningful attributes remain in one TEI. Source navigation/title/scripture metadata and document shell remain fully accounted in the independent external ledger and unchanged raw. The source publisher explicitly distinguishes Edwards's paraphrased substance from quoted Brainerd writings; this is complete retained editorial scope, not every original unabridged diary or surviving paper. No child work identities, invented missing text, or source spelling corrections."
DATA_NOTICE=Path('data/prose')/WORK_ID/'README.md'
canonical=producer.canonical
NS='{http://www.tei-c.org/ns/1.0}'
def put(p,b):
    q=io_path(ROOT/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,p,role):
    raw=io_path(ROOT/p).read_bytes();return dict(name=name,path=p.as_posix(),role=role,bytes=len(raw),sha256=sha256(raw).hexdigest())
def main():
    acquired=validate_acquisition(ROOT/ACQUISITION,root=ROOT)
    raw=io_path(ROOT/SOURCE).read_bytes()
    if len(raw)!=1400423 or sha256(raw).hexdigest()!=SOURCE_SHA or acquired['retained_files'][0]['sha256']!=SOURCE_SHA:raise ValueError('Source/acquisition differs')
    mirror=Path('D:/Library/Open Christian Data/candidate-reviews/brainerd-ccel-native-screen-20260928-v1')
    package=json.loads((mirror/'manifest.json').read_bytes())
    if sha256((mirror/'manifest.json').read_bytes()).hexdigest()!='87542404f44c2c1180ef30c94591effc6e786223c13476f55484d006af1e2b3a':raise ValueError('Successor package identity differs')
    for row in package['members']:
        b=(mirror/row['name']).read_bytes()
        if len(b)!=row['bytes'] or sha256(b).hexdigest()!=row['sha256']:raise ValueError('Historical native package member differs')
        target=LOG/'historical-package'/row['name']
        if io_path(ROOT/target).exists() and io_path(ROOT/target).read_bytes()!=b:raise FileExistsError(target)
        put(target,b)
    put(LOG/'historical-package/manifest.json',(mirror/'manifest.json').read_bytes())
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True));selected=source.find('ThML.body/div1')
    credits=[]
    for name,role,key in [('Jonathan Edwards','preface author and memoir publisher/editor; quoted Brainerd writings retain their own voice','ix.i-p18'),('David Brainerd','diary, journal and papers as attributed and abridged in the retained editorial work','ix.i-p19'),('E. Pemberton, A. M.','embedded ordination sermon, as attributed in the native division title','ix.xi')]:
        selector='//*[@id="'+key+'"]';node=source.xpath(selector)[0]
        credits.append(dict(name=name,role=role,source_selector=selector,literal_text=''.join(node.itertext()),source_attributes=dict(node.attrib)))
    header=etree.Element(NS+'teiHeader',nsmap={None:NS[1:-1]});fd=etree.SubElement(header,NS+'fileDesc');ts=etree.SubElement(fd,NS+'titleStmt')
    etree.SubElement(ts,NS+'title').text=TITLE;etree.SubElement(ts,NS+'author').text='Jonathan Edwards'
    for credit in credits:
        rs=etree.SubElement(ts,NS+'respStmt');etree.SubElement(rs,NS+'resp').text=credit['role'];etree.SubElement(rs,NS+'name').text=credit['name']
    etree.SubElement(etree.SubElement(fd,NS+'publicationStmt'),NS+'p').text='Private nonaccepted retained electronic-witness candidate; human review, independent rights clearance and publication remain pending.'
    bibl=etree.SubElement(etree.SubElement(fd,NS+'sourceDesc'),NS+'bibl')
    etree.SubElement(bibl,NS+'title').text='THE LIFE AND DIARY OF THE REV. DAVID BRAINERD WITH NOTES AND REFLECTIONS.'
    etree.SubElement(bibl,NS+'publisher').text='Christian Classics Ethereal Library; electronic provider identified by retained acquisition'
    etree.SubElement(bibl,NS+'ptr',target=acquired['url'])
    etree.SubElement(bibl,NS+'note',type='work-scope').text=SCOPE
    etree.SubElement(bibl,NS+'note',type='metadata-qualification').text='This acquired extraction has no ThML.head, imprint, publication date or electronic contributor/rights fields. Print edition equivalence, original publication date, translator and electronic contributor roles remain unconfirmed here. The inherited config date 1749 and public-domain label are not adopted as newly verified primary-source metadata. Edwards narration, Brainerd quotations and Pemberton sermon retain distinct source-attributed roles.'
    etree.SubElement(etree.SubElement(header,NS+'encodingDesc'),NS+'p').text='Exact historical native text/body bytes retained. Original declared Brainerd mapper freshly replays source body; a separate readonly independent oracle compares all 8545 nodes, meaningful attributes, IDs, mixed text/tails and ordered parent/child relationships plus complete external source attributes ledger. Source headings remain p rendition source-heading hN. No blind review, normalization, or missing-source completion is asserted.'
    questions=[dict(id=WORK_ID+'-'+kind,status='unresolved',kind=kind,detail=detail) for kind,detail in [('human','No human textual acceptance or current complete visual comparison.'),('print','Extracted witness not collated against print; imprint/date/translator/electronic roles not independently established.'),('rights','CCEL permission retained; independent jurisdictional rights clearance unresolved.'),('publication','No public publication authorization or action.')]]
    p=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,header_xml=etree.tostring(header,encoding='unicode'),major_unit_ids=[n.get('id') for n in selected if n.tag=='div2'],credits=credits,questions=questions,historical_reuse=dict(mirror=mirror.as_posix(),package_sha256=sha256((mirror/'manifest.json').read_bytes()).hexdigest(),candidate_sha256=sha256(io_path(ROOT/HISTORICAL).read_bytes()).hexdigest(),disposition='Exact recorded successor package recovered in readable flat mirror. Original 20260912 root sandbox unreadable; no ACL change. Successor temp absent. Older manifest/closure discrepancy remains dated historical evidence; new work-local closure pinned without rewriting historical authorities.'))
    put(BASE/'profile.json',canonical(p));put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,rules=['complete independent source tree and ledger','exact historical text bytes','exact primary source credit and qualified header','P5','fresh deterministic replay','meaningful mutations'],shared_assumptions='Original mapping declaration shared; independent original oracle and stdlib source parsing reused, no producer import or blind claim.')))
    notice='# Edwards: Life and Diary of David Brainerd source and data credit\n\nSourced via [CCEL.org](https://www.ccel.org/ccel/edwards/works2.html), the retained Life and Diary with Notes and Reflections extraction. The preface is signed Jonathan Edwards. Its publisher note explicitly identifies unquoted narrative as President Edwards’s words containing the substance of Brainerd’s diary with repetitions omitted; quoted writings retain Brainerd’s voice. The embedded ordination sermon is explicitly attributed to E. Pemberton, A. M. These distinct roles and original editorial limitations remain literal.\n\nThe retained extracted source has no volume electronic header or imprint, date, contributor or rights fields. The older configuration’s original publication year and public-domain label are historical metadata, not newly confirmed source statements. No translator, print publisher or electronic contributor is inferred.\n\nCCEL permits parsing ThML/XML for text; do not sell CCEL files or derivatives of their formatting. Carry this source and permission credit visibly to `'+DATA_NOTICE.as_posix()+'`. Independent rights clearance remains separate.\n\n'+SCOPE+'\n\nHuman textual/visual acceptance, print collation, rights clearance and publication remain separate.\n'
    put(BASE/'README.source.md',notice.encode())
    paths=[('retained-text',SOURCE,'primary-source'),('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('source-readme',BASE/'README.source.md','source-attribution'),('historical-native-candidate',HISTORICAL,'checked-native-historical-candidate'),('historical-accountability',LOG/'historical-package/source-accountability.json','complete-source-native-attributes-ledger'),('historical-manifest',LOG/'historical-package/manifest.json','historical-successor-package-manifest'),('legacy-source-manifest',Path('sources/structured-text')/WORK_ID/'brainerd.source-manifest.json','readonly-prior-source-manifest'),('legacy-mapper',Path('sources/structured-text')/WORK_ID/'brainerd_converter.py','readonly-original-mapper'),('legacy-oracle',Path('sources/structured-text')/WORK_ID/'brainerd_oracle.py','readonly-independent-oracle'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),('ccel-permission',Path('docs/sources/ccel-permission.md'),'permission-evidence'),('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema'),('candidate-package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')]
    manifest=dict(contract='ocd-source-manifest-v1',source_id='brainerd-complete-retained-current-v1',work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*row) for row in paths],converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable='_convert',implementation_path='build/tei/brainerd_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable='_oracle',implementation_path='build/tei/brainerd_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json',canonical(manifest));print(json.dumps(dict(status='prepared',source_elements=8545,heads=105,major_units=12,body_unchanged=True)))
if __name__=='__main__':main()
