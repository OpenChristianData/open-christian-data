"""Freeze work-local whole retained BCP1559 source, credit, and mapping bindings."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei import bcp1559_current_reconstruction as producer,bcp1559_current_oracle as checker
from ocd_kernel.library._common import io_path
from ocd_kernel.library.acquisitions import validate_acquisition

ROOT=Path(__file__).resolve().parents[2]
WORK_ID='bcp-1559'; FORM_ID='bcp-1559-retained-electronic'
EDITION_ID='bcp-1559-retained-electronic-witness'; ACQUISITION_ID='bcp-1559-retained-source-set'
WORK=Path('library/works')/WORK_ID
EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID
ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/liturgies-bcp1559-current/bcp-1559')
LOG=Path('reports/_logs/bcp1559-current-reconciliation-20261002-v1')
DATA_NOTICE=Path('data/liturgies/bcp-1559/README.md')
TITLE='The Book of Common Prayer (1559)'
NS='{http://www.tei-c.org/ns/1.0}'
canonical=producer.canonical


def put(path,raw):
 p=io_path(ROOT/path);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)


def binding(name,path,role):
 raw=io_path(ROOT/path).read_bytes()
 return dict(name=name,path=path.as_posix(),role=role,bytes=len(raw),sha256=sha256(raw).hexdigest())


def main():
 acquired=validate_acquisition(ROOT/ACQUISITION,root=ROOT)
 old_path=Path('sources/structured-text/bcp-1559/bcp-1559.source-manifest.json')
 old=json.loads(io_path(ROOT/old_path).read_bytes())
 pre=json.loads(io_path(ROOT/LOG/'preflight.json').read_bytes())
 members=old['source_members']
 if [(m['path'],m['sha256'],m['bytes']) for m in members]!=[(m['path'],m['sha256'],m['bytes']) for m in acquired['retained_files']]:
  raise ValueError('Immutable retained sixteen-member acquisition scope differs')
 current={p:sha256(io_path(ROOT/p).read_bytes()).hexdigest() for p in pre['bindings'] if p.startswith('library/')}
 if any(current[p]!=pre['bindings'][p] for p in current):raise ValueError('Canonical acquired authority changed')
 scope=pre['proposed_scope']
 credits=('Fifteen retained HTML footers explicitly credit Charles Wohlers as Web author; the standalone Commination member does not carry that footer. '
          'The inherited Richard J. Mammana transcription claim remains unconfirmed and is not asserted as current attribution. '
          'The provider Notes on the Text state that these HTML pages were transcribed from The Prayer Book of Queen Elizabeth 1559, '
          'published in 1890 by Griffith Farran Okeden and Welsh (Griffiths 1890/7), which in turn appears to use Richard Grafton\'s London 1559 book. '
          'The provider identifies an original 1634 edition for the 1604 changes and consulted John Booty (1976), William Keeling (1851), '
          'and Frank Streatfeild (1950) for specified contexts. These are retained provider statements, not independent print collation.')
 rights=('No explicit universal permission for reuse of this electronic transcription was identified. '
         'Underlying historical text, modern transcription, editorial material, images, and linked editions have separate rights questions. '
         'Inherited configuration public-domain claims are not rights clearance. Human textual acceptance, full visual or print collation, rights clearance, '
         'external contact disclosure, and public publication remain separate and unestablished.')
 representation=('All 16 declared member bodies retain their exact decoded text/tails, ordered hierarchy, and original HTML attributes in reversible source annotations. '
                 'All 128 HTML tables (391 rows and 998 cells) are represented, including web-navigation, title-banner, layout, and content relationships; '
                 'this does not classify every HTML table as a liturgical data table. The calendar alone contains 35 tables. '
                 'Five source blocks under inline font/b wrappers use closed inline carriers without flattening or changing their source hierarchy. '
                 'Source font/class/color/size/align attributes remain explicit annotations, not inferred speaker identities, rubric classifications, or response links. '
                 'The HTML numeric-reference decoding rule renders 90 literal &#149; references as bullets and two &#134; references as daggers; '
                 'their original byte locations and lexemes remain accounted. The two dagger occurrences form the Confirmation prayer/footnote marker pair. '
                 'Source head/prolog/comment material and exact outside-html whitespace are accounted separately. HTML recovery assumptions are disclosed; no browser or print collation is claimed.')
 assets=('All 53 literal image occurrences, alt attributes, and original link targets remain represented as source-context references. '
         'Their pixel, PDF, and other linked-edition payloads are outside the immutable primary 16-member source selection and are unverified. '
         'No payloads were fetched. The retained _index.html and PDF1623.htm files are outside that selection and remain supplementary evidence, not added primary members. '
         'Source web-author mailto links remain source context in this private preparation; no public contact-disclosure decision or external message is authorized.')
 h=etree.Element(NS+'teiHeader',nsmap={None:NS[1:-1]});fd=etree.SubElement(h,NS+'fileDesc')
 etree.SubElement(etree.SubElement(fd,NS+'titleStmt'),NS+'title').text=TITLE+': complete declared retained electronic expression'
 etree.SubElement(etree.SubElement(fd,NS+'publicationStmt'),NS+'p').text='Private technical candidate. '+rights
 b=etree.SubElement(etree.SubElement(fd,NS+'sourceDesc'),NS+'bibl')
 etree.SubElement(b,NS+'title').text=TITLE+' retained sixteen-member electronic witness'
 etree.SubElement(b,NS+'ptr',target=acquired['url'])
 etree.SubElement(b,NS+'idno',type='sha256').text=acquired['source_sha256']
 for kind,text in [('work-scope',scope),('source-credit',credits),('source-representation',representation),('source-assets',assets),('rights-qualification',rights)]:
  etree.SubElement(b,NS+'note',type=kind).text=text
 questions=[dict(id='bcp1559-'+kind,kind=kind,status='unresolved',detail=detail) for kind,detail in [
  ('print','Complete retained electronic expression, including disclosed later and supplementary contexts; not a single collated 1559 print edition.'),
  ('rights',rights),('assets',assets),('human','Human textual acceptance and browser/print visual collation are not established.'),
  ('publication','No public publication or external contact-disclosure authorization.')]]
 source_digest=sha256(canonical({'contract':'ocd-source-member-set-v1','members':sorted(members,key=lambda q:(q['path'],q['name']))})).hexdigest()
 profile=dict(work_id=WORK_ID,source_sha256=source_digest,retained_source_sha256=acquired['source_sha256'],
              scope=scope,source_members=members,header_xml=etree.tostring(h,encoding='unicode'),questions=questions)
 put(BASE/'profile.json',canonical(profile))
 put(BASE/'validation-policy.json',canonical(dict(scope=scope,rules=['every retained body carrier and ordered original attribute','exact source text/tail attachment and hierarchy','independent lexical full-document decoding','all table spans','P5','fresh deterministic replay','meaningful omission/order/attachment/attribute and header mutations'],shared_assumptions='Both hierarchy readers use lxml HTML recovery; the independent CPython HTMLParser lexical check corroborates full decoded wording and accounts exact outside-html whitespace. Visual/print collation remains unassessed.')))
 notice='# BCP1559 retained electronic expression: source and data credit\n\nRetained source location: [Justus Anglican BCP1559](http://justus.anglican.org/resources/bcp/1559/).\n\n'+scope+'\n\n'+credits+'\n\n'+representation+'\n\n'+assets+'\n\n'+rights+'\n\nCarry this complete visible source and data notice to `'+DATA_NOTICE.as_posix()+'`.\n'
 put(BASE/'README.source.md',notice.encode())
 paths=[(m['name'],Path(m['path']),'primary-source') for m in members]
 paths.extend([('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy-current',BASE/'validation-policy.json','independent-validation-policy'),
 ('source-readme',BASE/'README.source.md','visible-source-credit'),('canonical-acquisition',ACQUISITION,'current-retained-member-set'),
 ('original-source-manifest',old_path,'historical-source-authority'),('original-config',Path('sources/structured-text/bcp-1559/config.json'),'historical-unconfirmed-metadata'),
 ('legacy-escaped-tei',Path('ir/bcp/book-of-common-prayer.bcp-1559.tei.xml'),'historical-incomplete-native-reconstruction'),
 ('tei-p5-xsd',Path('ocd_kernel/tei/vendor/xsd/tei_all.xsd'),'tei-validation-schema'),
 ('candidate-package-schema',Path('ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json'),'candidate-package-schema')])
 authorities=[binding(*p) for p in paths];package_schema=next(q for q in authorities if q['name']=='candidate-package-schema')
 manifest=dict(contract='ocd-source-manifest-v1',source_id='bcp1559-complete-retained-native-current-v1',work_id=WORK_ID,
 textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=scope,source_bundle=old['source_bundle'],
 source_members=members,authorities=authorities,
 converter=dict(id=producer.CONVERTER_ID,version=producer.CONVERTER_VERSION,callable='_convert',implementation_path='build/tei/bcp1559_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),
 validator=dict(id=checker.ORACLE_ID,version=checker.ORACLE_VERSION,callable='_oracle',implementation_path='build/tei/bcp1559_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),
 package_schema={k:package_schema[k] for k in ('path','sha256')})
 put(BASE/'source-manifest.json',canonical(manifest))
 put(LOG/'current-source-scope.json',canonical(dict(status='pass',created_utc=datetime.now(timezone.utc).isoformat(),source_manifest_sha256=sha256(canonical(manifest)).hexdigest(),
 scope=scope,source_members=members,extra_source_dispositions=pre['all_retained_root_extra_files'],canonical_authority_unchanged=current)))
 print(json.dumps(dict(status='prepared',source_sha256=source_digest,retained_source_sha256=acquired['source_sha256'],members=16)))


if __name__=='__main__':main()
