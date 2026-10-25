"""Bind full retained Webster JSON using the unchanged source-native mapper."""
import json,os
from pathlib import Path
from hashlib import sha256
from xml.etree import ElementTree as ET
from lxml import etree
from jsonschema import Draft202012Validator
from build.tei import webster_current_reconstruction as producer,webster_current_oracle as checker
from build.tei.webster_reconstruction import _account_source,_tei_bytes
from build.tei.webster_oracle import _derive_source_accountability,_check_tree
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='webster';FORM_ID='webster-english';EDITION_ID='webster-retained-electronic-witness';ACQUISITION_ID='webster-retained-source'
WORK=Path('library/works')/WORK_ID;EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID;ACQUISITION=EDITION/'acquisitions'/(ACQUISITION_ID+'.json')
BASE=Path('sources/bible-webster-current/webster');SOURCE=Path('raw/bible_databases/formats/json/Webster.json');SOURCE_SHA='12b70533fcc01b5bad9d704af348617208a525f4ed2fbaf869736e83ef352f6a';TITLE='Webster Bible'
LOG=Path('reports/_logs/webster-current-reconciliation-20261002-v1');BASELINE=LOG/'rederived-baseline';DATA_NOTICE=Path('data/bible/webster/README.md')
SCOPE='Complete retained scrollmapper/bible_databases Webster JSON electronic witness: all 66 ordered books, 1,189 chapters and 31,102 nonempty verse strings, in one existing work and one TEI. Exact source labels, Unicode, whitespace, numbers, order, parent attachment and generated IDs are preserved. Only 66 generated book n ordinals are replaced by the corresponding literal source book names. Original historical native mapper/checker are reused, with fresh source-derived baseline because its disposable candidate is no longer located. Source label Webster: Webster Bible does not establish a particular print edition, date, translator, textual revision or standard versification. Human acceptance, rights clearance and publication remain separate.'
canonical=producer.canonical
def put(p,b):
 q=io_path(ROOT/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def binding(name,p,role):
 b=io_path(ROOT/p).read_bytes();return dict(name=name,path=Path(p).as_posix(),role=role,bytes=len(b),sha256=sha256(b).hexdigest())
def main():
 raw=io_path(ROOT/SOURCE).read_bytes();s=json.loads(raw)
 if sha256(raw).hexdigest()!=SOURCE_SHA or s['translation']!='Webster: Webster Bible':raise ValueError('Exact retained Webster source differs')
 legacy_profile=json.loads((ROOT/'sources/bible-text/webster/webster.reconstruction-profile.json').read_bytes());legacy_policy=json.loads((ROOT/'sources/bible-text/webster/webster.validation-policy.json').read_bytes())
 baseline_path=io_path(ROOT/BASELINE)
 if not baseline_path.exists():
  native_source,ledger,books=_account_source(raw,legacy_profile);baseline=_tei_bytes(native_source,books,legacy_profile,legacy_policy)
  independent_source,independent_ledger=_derive_source_accountability(raw,legacy_profile)
  if canonical(ledger)!=canonical(independent_ledger):raise ValueError('Independent full source field ledger differs')
  _check_tree(independent_source,baseline,legacy_policy)
  Draft202012Validator(json.loads((ROOT/'sources/bible-text/webster/webster.source-accountability.schema.json').read_bytes())).validate(independent_ledger)
  etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd'))).assertValid(etree.fromstring(baseline))
  put(BASELINE/'content.tei.xml',baseline);put(BASELINE/'source-accountability.json',canonical(ledger))
  put(BASELINE/'validation.json',canonical(dict(status='pass',pid=os.getpid(),exit_code=0,source_sha256=SOURCE_SHA,tei_sha256=sha256(baseline).hexdigest(),accountability_sha256=sha256(canonical(ledger)).hexdigest(),independent_source_counts=ledger['counts'],p5='pass',accountability_schema='pass',source_fidelity='Full unchanged independent JSON ledger and recursive TEI checker; no prior disposed package-byte claim.',historical_profile_example='Incorrect opening example preserved but unused; actual complete source and profile expected field-state/whitespace counts independently checked.')))
 questions=[dict(id='webster-'+k,status='unassessed',kind=k,detail=v) for k,v in [('human','Human textual/visual acceptance not recorded.'),('print','Specific print edition, date and revision not established by JSON label.'),('credits','No named contributor fields; Noah Webster/1833 config statements remain historical support, not new primary attribution.'),('rights','Retained MIT repository software license is separate from underlying translation rights.'),('publication','Private technical preparation only; no public publication authorization.')]]
 ns='{http://www.tei-c.org/ns/1.0}';ET.register_namespace('',ns[1:-1]);h=ET.Element(ns+'teiHeader');f=ET.SubElement(h,ns+'fileDesc');t=ET.SubElement(f,ns+'titleStmt');ET.SubElement(t,ns+'title').text=TITLE
 pub=ET.SubElement(f,ns+'publicationStmt');ET.SubElement(pub,ns+'p').text='Retained electronic witness prepared privately; human acceptance, print identity, underlying rights and publication remain separate.'
 desc=ET.SubElement(f,ns+'sourceDesc');b=ET.SubElement(desc,ns+'bibl',{'type':'retained-translation-label','{http://www.w3.org/XML/1998/namespace}id':'webster-translation-label'});ET.SubElement(b,ns+'title').text=s['translation'];ET.SubElement(b,ns+'idno',{'type':'sha256'}).text=SOURCE_SHA
 ET.SubElement(b,ns+'note',{'type':'source-label-limitation'}).text='The literal Webster: Webster Bible label is electronic metadata only. Legacy config Noah Webster/1833/Public Domain claims are historical support, not newly verified print identity or translator attribution. No named contributor or imprint is inferred from the JSON.'
 ET.SubElement(b,ns+'note',{'type':'retained-source-scope'}).text=SCOPE
 ET.SubElement(b,ns+'note',{'type':'rights-qualification'}).text='Repository software MIT permission: copyright 2024 Scrollmapper. This is not fresh worldwide underlying-translation rights clearance.'
 header=ET.tostring(h,encoding='utf-8').decode();put(BASE/'header.xml',header.encode())
 profile=dict(work_id=WORK_ID,source_sha256=SOURCE_SHA,scope=SCOPE,questions=questions,header_xml=header,book_label_revisions=[dict(source_pointer=f'/books/{i-1}/name',old_n=str(i),source_name=v['name'],id=f'webster-book-{i:03d}') for i,v in enumerate(s['books'],1)],historical_profile_example_not_adopted=True)
 put(BASE/'profile.json',canonical(profile));put(BASE/'validation-policy.json',canonical(dict(scope=SCOPE,body_changes='Only66source-literalbooklabels; all other text/IDs/order/attrs conserved.',checks=['full independent strict JSON keys/order/states and all31102verse values','exact inverse header/66labels recovers fresh unchanged historical-mapper baseline','independent original source-tree and accountability schema checks','qualified current header/namespace and P5','fresh complete package/current attestation replay'])))
 license_text=io_path(ROOT/'raw/bible_databases/LICENSE').read_text(encoding='utf-8').strip()
 notice=f'''# Webster Bible: complete retained electronic witness

Provider: scrollmapper/bible_databases. The literal translation field reads **Webster: Webster Bible**. This existing work preserves the complete retained electronic JSON: 66 ordered books, 1,189 chapters and 31,102 present nonempty verse strings, from Genesis through Revelation of John. Exact source names, wording, Unicode, whitespace, numeric labels, order and edition-local identities remain intact. Only generated book-label ordinals are replaced by corresponding literal source names. No external versification or normalized OSIS identity is inferred.

The JSON has no individual translator, editor, transcriber, publisher, print date, copyright or license fields beyond that label. The historical config's Noah Webster, 1833 and Public Domain statements remain historical support, not newly confirmed identity, date, translation revision or worldwide underlying-rights clearance. No contributor or print imprint is invented. The historical profile's sample opening text is incorrect for this witness; it was not adopted. The actual source opening is “In the beginning God created the heaven and the earth.” and the ending is “The grace of our Lord Jesus Christ [be] with you all. Amen.”

Maintain this source/data credit and full retained repository permission notice with any permitted copies. The software repository license below does not automatically establish rights clearance for underlying Bible translations. Human acceptance, print collation, independent translation rights and public publication remain separate from private technical preparation.

```text
{license_text}
```

For data at `data/bible/webster`, maintain this notice at `data/bible/webster/README.md` and in the release README containing these rows.
'''
 put(BASE/'README.source.md',notice.encode());put(DATA_NOTICE,notice.encode())
 old=json.loads((ROOT/'sources/bible-text/webster/webster.source-manifest.json').read_bytes());authorities=[binding(a['name'],a['path'],'historical-'+a['role'] if a['name'] in ('webster-profile','webster-policy') else a['role']) for a in old['authorities']]
 extra=[('profile',BASE/'profile.json','complete-source-feature-profile'),('validation-policy',BASE/'validation-policy.json','independent-validation-policy'),('source-readme',BASE/'README.source.md','source-attribution'),('canonical-acquisition',ACQUISITION,'retained-source-identity'),('rederived-native-baseline',BASELINE/'content.tei.xml','fresh-rederived-complete-native-baseline'),('rederived-accountability',BASELINE/'source-accountability.json','fresh-independent-source-ledger'),('baseline-validation',BASELINE/'validation.json','fresh-independent-source-baseline-proof'),('historical-manifest','sources/bible-text/webster/webster.source-manifest.json','unaltered-historical-binding'),('prior-producer','build/tei/webster_reconstruction.py','unchanged-source-producer'),('prior-checker','build/tei/webster_oracle.py','unchanged-independent-source-checker'),('provider-license','raw/bible_databases/LICENSE','retained-software-permission-notice'),('reconciliation-preflight',LOG/'preflight.json','retained-candidate-and-source-reconciliation')]
 authorities += [binding(*a) for a in extra]
 m=dict(contract='ocd-source-manifest-v1',source_id='webster-retained-json',source_selection=old['source_selection'],work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID,acquisition_id=ACQUISITION_ID,scope=SCOPE,authorities=authorities,converter=dict(id=producer.CONVERTER_ID,version='1',callable='_convert',implementation_path='build/tei/webster_current_reconstruction.py',implementation_sha256=sha256(Path(producer.__file__).read_bytes()).hexdigest()),validator=dict(id=checker.ORACLE_ID,version='1',callable='_oracle',implementation_path='build/tei/webster_current_oracle.py',implementation_sha256=sha256(Path(checker.__file__).read_bytes()).hexdigest(),import_closure_sha256=checker.closure_sha(ROOT)),package_schema=dict(path=old['package_schema']['path'],sha256=sha256((ROOT/old['package_schema']['path']).read_bytes()).hexdigest()))
 put(BASE/'source-manifest.json',canonical(m));print(json.dumps(dict(status='prepared',books=66,chapters=1189,verses=31102,baseline_sha256=sha256(io_path(ROOT/BASELINE/'content.tei.xml').read_bytes()).hexdigest())))
if __name__=='__main__':main()
