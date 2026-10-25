"""Bind complete retained JPS source and qualified current work-local metadata."""
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import jps_current_reconstruction as producer, jps_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = 'jps'
FORM_ID = 'jps-english'
EDITION_ID = 'jps-retained-electronic-witness'
ACQUISITION_ID = 'jps-retained-source'
WORK = Path('library/works/jps')
EDITION = WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION = EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE = Path('sources/bible-jps-current/jps')
SOURCE = Path('raw/bible_databases/formats/json/JPS.json')
SOURCE_SHA = 'cb698cfbf2e97843dd4357b725c96ac6e9b2f3f23c5e3e3f6a3cdb5912ca183a'
TITLE = 'Jewish Publication Society Old Testament'
LOG = Path('reports/_logs/jps-current-reconciliation-20261001-v1')
HISTORICAL = LOG/'historical-package/content.tei.xml'
DATA_NOTICE = Path('data/bible/jps/README.md')
SCOPE = 'Complete retained JPS JSON electronic witness: exact translation label, all 39 ordered books with literal source titles, 929 chapters and 23,213 verse carriers, including all 19 source-empty strings. Every literal verse text, number, book/chapter attachment and original generated identifier is preserved. Only 39 generated ordinal book div@n labels are replaced by exact source book names; original ordinal IDs and order remain. Entire retained source is accounted with no excluded members, omitted empty carriers, invented text, standard-versification reassignment, source spelling corrections or child work identities. This establishes the complete retained electronic witness, not independently verified equivalence to a particular printed JPS edition or every historical translation.'
canonical = producer.canonical
NS = '{http://www.tei-c.org/ns/1.0}'

def put(path, payload):
    target = io_path(ROOT/path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

def binding(name, path, role):
    raw = io_path(ROOT/path).read_bytes()
    return dict(name=name, path=path.as_posix(), role=role, bytes=len(raw), sha256=sha256(raw).hexdigest())

def main():
    acquired = validate_acquisition(ROOT/ACQUISITION, root=ROOT)
    raw = io_path(ROOT/SOURCE).read_bytes()
    if len(raw) != 6374024 or sha256(raw).hexdigest() != SOURCE_SHA or acquired['retained_files'][0]['sha256'] != SOURCE_SHA:
        raise ValueError('Exact acquired JPS source differs')
    historical = io_path(ROOT/HISTORICAL).read_bytes()
    if sha256(historical).hexdigest() != '0ba10803c1fd6985f23fdf0421e03f60dc1a132e0b8d14ba61958ba64b61a7cd':
        raise ValueError('Historical native identity differs')
    package = json.loads(io_path(ROOT/LOG/'historical-package/manifest.json').read_bytes())
    for row in package['members']:
        payload = io_path(ROOT/LOG/'historical-package'/row['name']).read_bytes()
        if len(payload) != row['bytes'] or sha256(payload).hexdigest() != row['sha256']:
            raise ValueError('Historical package member differs')
    source = json.loads(raw)
    header = etree.Element(NS+'teiHeader', nsmap={None:NS[1:-1]})
    fd = etree.SubElement(header, NS+'fileDesc')
    etree.SubElement(etree.SubElement(fd, NS+'titleStmt'), NS+'title').text = TITLE
    etree.SubElement(etree.SubElement(fd, NS+'publicationStmt'), NS+'p').text = 'Private nonaccepted retained electronic-witness candidate; human textual acceptance, rights clearance and publication remain separate.'
    bibl = etree.SubElement(etree.SubElement(fd, NS+'sourceDesc'), NS+'bibl')
    etree.SubElement(bibl, NS+'title', attrib={'{http://www.w3.org/XML/1998/namespace}id':'jps-source-label'}).text = source['translation']
    etree.SubElement(bibl, NS+'publisher').text = acquired['provider']+'; retained electronic source provider, not an inferred print publisher'
    etree.SubElement(bibl, NS+'ptr', target=acquired['url'])
    old = etree.fromstring(historical).find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc')
    for paragraph in old:
        etree.SubElement(bibl, NS+'note', type='historical-source-description').text = ''.join(paragraph.itertext())
    etree.SubElement(bibl, NS+'note', type='work-scope').text = SCOPE
    etree.SubElement(bibl, NS+'note', type='metadata-qualification').text = 'The source label and repository identify this retained JPS Old Testament witness. Translation date, print edition, original translator/editor, print publisher and underlying translation rights are not established by this JSON. The retained repository MIT license is reproduced for source attribution and its software permission; it does not independently establish rights in the underlying translation. Empty text strings are source slots, not inferred missing text or permission to fill verses.'
    etree.SubElement(etree.SubElement(header, NS+'encodingDesc'), NS+'p').text = 'Exact historical native body reused after full original replay. Only source-backed book routing labels are renewed; restoring those 39 attributes recovers the whole historical text bytes. A separate original independent oracle checks every retained JSON field, ordered book/chapter/verse carrier and complete external ledger. All empty ab type=verse carriers remain childless with explicit xml:space=preserve. Source-native numbering is preserved without claiming standardized versification.'
    questions = [dict(id='jps-'+kind, kind=kind, status='unresolved', detail=detail) for kind, detail in [
        ('human','No human textual acceptance or full visual review is recorded.'),
        ('edition','Specific print edition, translation date, original contributors and print equivalence remain unconfirmed.'),
        ('rights','Repository MIT software permission does not independently establish underlying translation rights; jurisdictional clearance remains separate.'),
        ('publication','No public publication authorization or action.')]]
    profile = dict(work_id=WORK_ID, source_sha256=SOURCE_SHA, scope=SCOPE, header_xml=etree.tostring(header, encoding='unicode'),
        book_label_revisions=[dict(source_pointer=f'/books/{i}/name', old_n=str(i+1), source_name=b['name'], id=f'jps-b{i+1}') for i,b in enumerate(source['books'])],
        questions=questions, historical_reuse=dict(candidate_sha256=sha256(historical).hexdigest(), disposition='Exact recovered six-member package. Historical closure bindings remain dated; current work-local wrapper independently binds actual runtime without rewriting historical manifest.'))
    put(BASE/'profile.json', canonical(profile))
    put(BASE/'validation-policy.json', canonical(dict(scope=SCOPE, rules=['complete source JSON/native TEI/ledger oracle','exact historical reconstruction replay','39 source-backed book labels with exact whole-byte restoration','all19 empty carriers retained','P5','fresh deterministic package replay','meaningful mutations'], shared_assumptions='Original independent JPS oracle reads source directly; wrapper does not import producer.')))
    license_text = io_path(ROOT/'raw/bible_databases/LICENSE').read_text(encoding='utf-8')
    notice = '# JPS retained electronic witness: source and data credit\n\nThe retained source identifies itself literally as **JPS: Jewish Publication Society Old Testament**. Source provider: [scrollmapper/bible_databases](https://github.com/scrollmapper/bible_databases). No translation year, particular print edition, translator, print publisher or public-domain status is inferred from this label.\n\n'+SCOPE+'\n\nAll 19 source-empty verses remain literal empty strings with their original numbered slots. The private/public projection uses source-native numbering; it does not fill blanks, omit carriers or claim standardized versification.\n\nThe retained repository license below concerns its software/source repository. It is reproduced visibly with the copyright and permission notice. Underlying translation rights and jurisdictional clearance remain unresolved separately. Human acceptance, print collation and public publication remain separate. Carry this notice to `'+DATA_NOTICE.as_posix()+'`.\n\n```text\n'+license_text.rstrip()+'\n```\n'
    put(BASE/'README.source.md', notice.encode())
    paths = [('retained-text',SOURCE,'primary-source'), ('profile',BASE/'profile.json','complete-source-feature-profile'),
        ('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('source-readme',BASE/'README.source.md','source-attribution'),
        ('historical-native-candidate',HISTORICAL,'checked-native-historical-candidate'),('historical-accountability',LOG/'historical-package/source-accountability.json','complete-source-ledger'),
        ('historical-manifest',LOG/'historical-package/manifest.json','historical-package-manifest'),('legacy-source-manifest',Path('sources/bible-text/jps/jps.source-manifest.json'),'readonly-historical-manifest'),
        ('legacy-mapper',Path('build/tei/jps_reconstruction.py'),'readonly-original-mapper'),('legacy-oracle',Path('build/tei/jps_oracle.py'),'readonly-independent-oracle'),
        ('canonical-acquisition',ACQUISITION,'retained-source-identity'),('repository-license',Path('raw/bible_databases/LICENSE'),'literal-repository-license'),
        ('repository-readme',Path('raw/bible_databases/README.md'),'repository-source-description'),('repository-inspection',Path('raw/bible_databases/INSPECTION_REPORT.md'),'qualified-translation-rights-evidence'),
        ('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema'),('candidate-package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')]
    manifest = dict(contract='ocd-source-manifest-v1', source_id='jps-complete-retained-current-v1', work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID, scope=SCOPE,
        authorities=[binding(*row) for row in paths], converter=dict(id=producer.CONVERTER_ID, version=producer.CONVERTER_VERSION, callable='_convert',implementation_path='build/tei/jps_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
        validator=dict(id=checker.ORACLE_ID, version=checker.ORACLE_VERSION, callable='_oracle',implementation_path='build/tei/jps_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
        package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
    put(BASE/'source-manifest.json', canonical(manifest))
    print(json.dumps(dict(status='prepared', books=39, chapters=929, verses=23213, empty=19, source_sha256=SOURCE_SHA)))

if __name__ == '__main__':
    main()
