"""Bind a fresh reproduction of the complete retained YLT electronic witness."""
from pathlib import Path
from hashlib import sha256
import json
from xml.etree import ElementTree as ET
from build.tei import ylt_current_reconstruction as producer, ylt_current_oracle as checker
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='ylt';FORM_ID='ylt-english';EDITION_ID='ylt-retained-electronic-witness';ACQUISITION_ID='ylt-retained-source'
WORK=Path('library/works')/WORK_ID;EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID;ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/bible-ylt-current')/WORK_ID;SOURCE=Path('raw/bible_databases/formats/json/YLT.json');SOURCE_SHA='d55ef42dae715c4fc5d00049011b818a42a99e0ff419f5f08bc37cea0b4f12e3';TITLE="Young's Literal Translation"
LOG=Path('reports/_logs/ylt-current-reconciliation-20261002-v1')
SCOPE='Complete retained scrollmapper/bible_databases YLT JSON electronic witness: literal translation label, all66ordered books,1189chapters and31102nonempty verse carriers. Exact source strings, Unicode, array order, integer labels and parent attachment preserved. Fresh original-mapper reproduction matches recorded historical02521f hash; disposed historical package not physically recovered. Only66generated book div@n ordinal labels become literal source names; original XML IDs/headings/chapter/verse subtree unchanged. Source label1898 is uncollated metadata, not verified print date/edition/translator/revision/lineage. No external versification, rights clearance, human acceptance or publication claim.'
DATA_NOTICE=Path('data/bible/ylt/README.md')
canonical=producer.canonical
def put(p,b):
 q=io_path(ROOT/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,p,role):
 b=io_path(ROOT/p).read_bytes();return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
 source=io_path(ROOT/SOURCE).read_bytes();record=json.loads(source)
 if sha256(source).hexdigest()!=SOURCE_SHA or record['translation']!="YLT: Young's Literal Translation (1898)":raise ValueError('Exact source differs')
 questions=[dict(id=WORK_ID+'-'+k,status='unassessed',kind=k,detail=v) for k,v in [('human','No fresh human visual/proofreading review.'),('print','Source label1898 is not collated print/edition/lineage evidence.'),('translator','JSON label does not establish translator/revision attribution.'),('rights','Legacy config rights claims are historical support, not independent clearance.'),('publication','Private technical preparation only; publication unperformed/unapproved.')]]
 baseline=LOG/'regenerated-original-native.tei.xml';account=LOG/'regenerated-original-accountability.json'
 profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,questions=questions,regenerated_tei_sha256=sha256(io_path(ROOT/baseline).read_bytes()).hexdigest(),regenerated_accountability_sha256=sha256(io_path(ROOT/account).read_bytes()).hexdigest(),book_label_transitions=[dict(position=i,id=f'ylt-book-{i:03d}',old=str(i),new=b['name']) for i,b in enumerate(record['books'],1)])
 put(BASE/'profile.json',canonical(profile));put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,rules=['independent complete source ledger and original independent whole tree checker','normalize only reviewed header and66n labels to exact freshly reproduced native bytes','P5 and current mechanical attestation','exact fresh-process replay'],permitted_body_changes='exact66source-backedbooklabels only')))
 ns='{http://www.tei-c.org/ns/1.0}';ET.register_namespace('',ns[1:-1]);h=ET.Element(ns+'teiHeader');f=ET.SubElement(h,ns+'fileDesc');t=ET.SubElement(f,ns+'titleStmt');ET.SubElement(t,ns+'title').text=TITLE
 pub=ET.SubElement(f,ns+'publicationStmt');ET.SubElement(pub,ns+'p').text='Technical retained-electronic-witness preparation only; human review, print identity, rights clearance and publication remain separate.'
 desc=ET.SubElement(f,ns+'sourceDesc');b=ET.SubElement(desc,ns+'bibl',{'type':'retained-translation-label','{http://www.w3.org/XML/1998/namespace}id':'ylt-translation-label'});b.text=record['translation'];ET.SubElement(b,ns+'idno',{'type':'sha256'}).text=SOURCE_SHA
 ET.SubElement(b,ns+'note',{'type':'source-label-limitation'}).text="The literal YLT: Young's Literal Translation (1898) label is source-supplied metadata; it does not independently establish print date, edition, translator, revision, rights or lineage."
 ET.SubElement(b,ns+'note',{'type':'retained-source-scope'}).text='Complete66books/1189chapters/31102nonempty verse carriers. Fresh original-mapper reproduction matches recorded historical native hash; old package was not physically recovered. Only66generated book labels change to source names; IDs and whole verse body conserved. No external versification inference.'
 put(BASE/'header.xml',ET.tostring(h,encoding='utf-8'))
 notice="""# Young's Literal Translation: retained electronic witness and use notice

Credit the retained provider scrollmapper/bible_databases and its literal label **YLT: Young's Literal Translation (1898)**. The label is electronic source metadata. Its year is not independently verified print publication, edition, translation revision or lineage evidence. This retained JSON has no independent translator, editor, transcriber, publisher, imprint, copyright or license fields. Legacy configuration claims about Robert Young and Public Domain are preserved as historical support, not adopted as new primary-source confirmation or independent rights clearance.

The whole existing work remains one TEI: 66 ordered books, 1,189 chapters and 31,102 nonempty verse carriers, with 4,101,874 source text codepoints. Source wording, Unicode, integer labels, order and parent attachment remain exact. Each book label is its literal source name, while original mapper XML IDs are conserved. The source-native numbering is not asserted to match external versification or normalized OSIS book identities. No wording is borrowed or supplied.

The historical candidate package was not physically recovered from its declared locations. A fresh reproduction using the retained source and unchanged original mapper matches the previously recorded native TEI SHA256 02521fdd8772431c1063aa679b34fc1569750f7fef56b6122924c7a9b635403a. This byte match is not a physical package lineage claim. Fresh source accounting, an independent source checker and coordinator review support the renewed candidate.

Independent rights clearance, database/formatting terms and jurisdictional applicability remain unassessed. Technical acceptance and private offline verification do not establish human proofreading, print equivalence or permission for public publication.

For data at `data/bible/ylt`, maintain this complete notice in `data/bible/ylt/README.md` and any release README containing these rows.
"""
 put(BASE/'README.source.md',notice.encode('utf-8'));put(DATA_NOTICE,notice.encode('utf-8'))
 authorities=[('primary-source',SOURCE,'primary-source'),('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('header',BASE/'header.xml','qualified-current-header'),('source-readme',BASE/'README.source.md','source-attribution'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),('regenerated-tei',baseline,'fresh-original-mapper-reproduction'),('regenerated-accountability',account,'fresh-complete-source-ledger'),('regenerated-profile','sources/bible-text/ylt/ylt.reconstruction-profile.json','original-source-profile'),('regenerated-policy','sources/bible-text/ylt/ylt.validation-policy.json','original-independent-policy'),('original-mapper','build/tei/ylt_reconstruction.py','unchanged-original-mapper'),('prior-checker','build/tei/ylt_oracle.py','current-independent-checker'),('historical-current-manifest','sources/bible-text/ylt/ylt.source-manifest.json','historical-binding-preserved-not-resealed'),('regeneration-proof',LOG/'retained-source-regeneration-proof.json','fresh-regeneration-and-search-evidence'),('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),('contract','ocd_kernel/reconstruction/contract.py','current-contract'),('coordinator-source-review','reports/_logs/ylt-coordinator-source-review-20261002-v1/review.json','independent-direct-source-baseline-corroboration')]
 m=dict(contract='ocd-source-manifest-v1',source_id='ylt-retained-current-v1',work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=[binding(*a) for a in authorities],converter=dict(id=producer.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/ylt_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/ylt_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest()))
 put(BASE/'source-manifest.json',canonical(m));print(json.dumps(dict(status='prepared',fresh_reproduction=True,only66booklabels_change=True)))
if __name__=='__main__':main()
