"""Fresh scoped bindings for the complete retained KJVA electronic witness."""
from pathlib import Path
from hashlib import sha256
import json
from xml.etree import ElementTree as ET
from build.tei import kjva_current_reconstruction as producer,kjva_current_oracle as checker
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='kjva';FORM_ID='kjva-english';EDITION_ID='kjva-retained-electronic-witness';ACQUISITION_ID='kjva-retained-source'
WORK=Path('library/works')/WORK_ID;EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID;ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/bible-kjva-current/kjva');SOURCE=Path('raw/bible_databases/formats/json/KJVA.json');SOURCE_SHA='b927f4a0601de39b1636ebb71162ab1bf8ddbad66a55f50603011697e46060d5';TITLE='King James Version with Apocrypha'
LOG=Path('reports/_logs/kjva-current-reconciliation-20261001-v1');HISTORICAL=LOG/'historical-package'
SCOPE='Complete retained scrollmapper/bible_databases KJVA JSON electronic witness: all80ordered books including14Apocrypha books,1371chapters and36819nonempty present verse carriers in one existing work/TEI. Exact source strings, whitespace, order, integer labels, parent attachment and generated IDs conserved. Only80generated book n ordinals replaced by their literal source book names. Source label1769/Strongs Numbers/Morphology/CatchWords/without glosses remains electronic metadata, not verified print edition, annotations, revision, standard versification or collation. Human acceptance, rights clearance and publication remain separate.'
DATA_NOTICE=Path('data/bible/kjva/README.md');canonical=producer.canonical
def put(p,b):
 q=io_path(ROOT/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,p,role):
 b=io_path(ROOT/p).read_bytes();return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
 source=io_path(ROOT/SOURCE).read_bytes();record=json.loads(source)
 label='KJVA: King James Version (1769) with Strongs Numbers and Morphology and CatchWords, including Apocrypha (without glosses)'
 if sha256(source).hexdigest()!=SOURCE_SHA or record['translation']!=label:raise ValueError('Retained KJVA source differs')
 questions=[dict(id='kjva-'+k,status='unassessed',kind=k,detail=v) for k,v in [('human','Fresh visual proofreading and human acceptance not recorded.'),('print','1769 and annotation labels are retained electronic metadata; no print or revision collation.'),('credits','JSON establishes no named editor, translator, transcriber or print publisher.'),('rights','Repository MIT software license does not independently clear underlying translation rights in every jurisdiction.'),('publication','Private technical preparation; no publication authorization.')]]
 ns='{http://www.tei-c.org/ns/1.0}';ET.register_namespace('',ns[1:-1]);h=ET.Element(ns+'teiHeader');f=ET.SubElement(h,ns+'fileDesc');t=ET.SubElement(f,ns+'titleStmt');ET.SubElement(t,ns+'title').text=TITLE
 pub=ET.SubElement(f,ns+'publicationStmt');ET.SubElement(pub,ns+'p').text='Retained electronic witness prepared privately; human acceptance, print identity, underlying rights and publication remain separate.'
 desc=ET.SubElement(f,ns+'sourceDesc');b=ET.SubElement(desc,ns+'bibl',{'type':'retained-translation-label','{http://www.w3.org/XML/1998/namespace}id':'kjva-translation-label'});ET.SubElement(b,ns+'title').text=label
 ET.SubElement(b,ns+'idno',{'type':'sha256'}).text=SOURCE_SHA
 ET.SubElement(b,ns+'note',{'type':'source-label-limitation'}).text='The source-supplied1769 and Strongs Numbers/Morphology/CatchWords/without glosses label is not independent print, revision or annotation evidence. No named contributor or print imprint is inferred.'
 ET.SubElement(b,ns+'note',{'type':'retained-source-scope'}).text=SCOPE
 ET.SubElement(b,ns+'note',{'type':'rights-qualification'}).text='Retained repository software MIT license: copyright2024Scrollmapper. The inherited Public Domain statement is historical support, not fresh worldwide underlying-translation rights clearance.'
 header=ET.tostring(h,encoding='utf-8').decode()
 profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,questions=questions,header_xml=header,book_label_revisions=[dict(source_pointer=f'/books/{i-1}/name',old_n=str(i),source_name=v['name'],id=f'kjva-book-{i:03d}') for i,v in enumerate(record['books'],1)])
 put(BASE/'header.xml',header.encode());put(BASE/'profile.json',canonical(profile));put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,body_changes='Exactly80generated book n labels to literal source names; no other body changes.',checks=['full independent JSON fields/order/states ledger','inverse header/book labels restores complete historical TEI bytes','unchanged independent original recursive source tree checks','exact qualified header and namespace','P5/current validation closure','fresh process byte replay'])))
 license_text=io_path(ROOT/'raw/bible_databases/LICENSE').read_text(encoding='utf-8').strip()
 notice=f'''# KJVA: complete retained electronic witness

Provider: scrollmapper/bible_databases. Its literal translation label is **{label}**. This existing work preserves all 80 ordered books, including 14 Apocrypha books, 1,371 chapters and 36,819 present nonempty verse strings. No complete historical print edition, universal versification, digital annotation coverage, or human proofreading is asserted. Only generated book-label ordinals are replaced by their corresponding literal source names; original identities, verse wording, Unicode, whitespace, numbers, order and attachment remain unchanged.

The JSON contains no named translator, transcriber, editor, publisher, copyright or license fields beyond its translation label. No such contributor, imprint or production date is invented. The source's 1769 and Strongs Numbers/Morphology/CatchWords/without glosses statements remain source metadata. Historical config public-domain/1611/1769 claims do not establish new print collation or worldwide rights clearance. Underlying King James translation rights and jurisdictional applicability remain distinct from the repository's software license and unassessed here.

Maintain this source/data credit and the retained repository permission notice with any permitted copies. The software repository license is retained verbatim below; it is not a new blanket license for underlying Bible translations. Private technical acceptance does not establish human acceptance, rights clearance or public publication authorization.

```text
{license_text}
```

For data at `data/bible/kjva`, retain this notice at `data/bible/kjva/README.md` and in the release README containing these rows.
'''
 put(BASE/'README.source.md',notice.encode());put(DATA_NOTICE,notice.encode())
 old=json.loads((ROOT/'sources/bible-text/kjva/kjva.source-manifest.json').read_bytes())
 authorities=[binding(a['name'],a['path'],'historical-'+a['role'] if a['name'] in ('kjva-profile','kjva-policy') else a['role']) for a in old['authorities']]
 extra=[('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('source-readme',BASE/'README.source.md','source-attribution'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),('historical-native-candidate',HISTORICAL/'content.tei.xml','complete-historical-native-candidate'),('historical-accountability',HISTORICAL/'source-accountability.json','complete-historical-source-ledger'),('historical-manifest','sources/bible-text/kjva/kjva.source-manifest.json','unaltered-historical-binding'),('prior-producer','build/tei/kjva_reconstruction.py','unchanged-source-producer'),('prior-checker','build/tei/kjva_oracle.py','unchanged-independent-source-checker'),('provider-license','raw/bible_databases/LICENSE','retained-software-permission-notice'),('provider-readme','raw/bible_databases/README.md','retained-provider-label'),('coordinator-source-review','reports/_logs/kjva-coordinator-source-review-20261001-v1/review.json','independent-full-source-body-corroboration')]
 authorities += [binding(*a) for a in extra]
 m=dict(contract='ocd-source-manifest-v1',source_id='kjva-retained-current-v1',work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=authorities,converter=dict(id=producer.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/kjva_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/kjva_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path=old['package_schema']['path'],sha256=sha256((ROOT/old['package_schema']['path']).read_bytes()).hexdigest()))
 put(BASE/'source-manifest.json',canonical(m));print(json.dumps(dict(status='prepared',books=80,chapters=1371,verses=36819)))
if __name__=='__main__':main()
