"""Observe the existing Douay envelope and exact supported local successor."""
from pathlib import Path
from hashlib import sha256
import json
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.projection.categories.bible import project_bible_document,verify_bible_document
from build.tei.original_douay_current_reconstruction import adapt,NS,canonical
ROOT=Path(__file__).resolve().parents[2]
WORK_ID='original-douay-rheims';FORM_ID=WORK_ID+'-retained-en';EDITION_ID=WORK_ID+'-electronic';ACQUISITION_ID=WORK_ID+'-acquired'
WORK=Path('library/works')/WORK_ID;EDITION=WORK/'forms'/FORM_ID/'editions'/EDITION_ID;SOURCE=EDITION/'source-member-set.json'
OLD=Path('reports/clean-ready-acquisition-to-tei/master-3/21')/WORK_ID/'candidate'
LOG=Path('reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1')
VERSIFICATION='source-native:original-douay-rheims-v1.0'
REVISION='original-douay-complete-electronic-v1'
def header(source_sha):
 h=etree.Element(NS+'teiHeader',nsmap={None:NS[1:-1]});f=etree.SubElement(h,NS+'fileDesc')
 t=etree.SubElement(f,NS+'titleStmt');etree.SubElement(t,NS+'title').text='The Holy Bible, Douay-Rheims Version (original translation): retained structured electronic witness v1.0'
 p=etree.SubElement(f,NS+'publicationStmt');etree.SubElement(p,NS+'p').text='Private technical preparation of the complete retained electronic witness, not independent print collation, human acceptance, rights clearance or public publication.'
 b=etree.SubElement(etree.SubElement(f,NS+'sourceDesc'),NS+'bibl')
 etree.SubElement(b,NS+'ptr',type='source',target='https://github.com/janvier-s/original-douay-rheims')
 for k,v in [('sha256',source_sha),('source_sha256',source_sha),('bible_versification',VERSIFICATION),('bible_native_chapter_policy','source-native-zero-chapter-v1')]:etree.SubElement(b,NS+'idno',type=k).text=v
 facts=[('retained-source-context','Complete651 extracted textual members of pinnedv1.0; tagged JSON,394annotation sidecars,26reference documents; raw JSON and USFM derivatives retained and accounted separately. ZIP is a package, not textual authority.73canonical+3appendix components; exact duplicate Prayer filename rendered once.'),('source-credits','Primary title documents credit the English College of Rheims and the English College of Doway. Gregory Martin and contemporary revisers/annotators are retained configuration attributions, not independently allocated roles.'),('source-date-qualification','The release README claims original1582 New Testament and1609-1610 Old Testament. Literal NT title also says fourth Edition1633; OT title also carries1635. No exact historical printed-edition identification or collation is inferred.'),('source-rights','The retained README and LICENSE declare CC0 1.0 Universal. This is provider evidence, without independent worldwide clearance or print authenticity proof.'),('reading-order','The source release tree does not declare reading order. The established candidate uses an explicitly generated historical Catholic order, then three appendix components. That inherited order is retained, not presented as literal archive order.'),('source-pointer-alias','Every generated odr-source-field XML ID is SHA256 of its exact original source-json pointer. The manifest-bound complete source field inventory and actual-TEI context companion preserve reversible pointer meaning, original labels and attachment; IDs are not asserted source-supplied identifiers.')]
 for k,v in facts:etree.SubElement(b,NS+'note',type=k).text=v
 return h
def main():
 raw=io_path(ROOT/OLD/'content.tei.xml').read_bytes();assert sha256(raw).hexdigest()=='ee7be25d78d029ae4781f58c56b8a1b5243cc60b8d12d035ba338769125ac0d8'
 source_sha=sha256(io_path(ROOT/SOURCE).read_bytes()).hexdigest();h=etree.tostring(header(source_sha),encoding='UTF-8')
 d=etree.fromstring(raw);d.replace(d[0],etree.fromstring(h));cases=[];folder=io_path(ROOT/LOG/'projection-probes');folder.mkdir(parents=True,exist_ok=True)
 context=dict(identity=dict(work_id=WORK_ID,textual_form_id=FORM_ID,edition_id=EDITION_ID),language='en',representation_revision=REVISION,edition_title='Original Douay-Rheims structured release v1.0',versification=VERSIFICATION,source_sha256=source_sha,retained_sha256=source_sha,source_url='https://github.com/janvier-s/original-douay-rheims')
 for name,b in [('header-only',etree.tostring(d,encoding='UTF-8',xml_declaration=True)),('bounded-successor',adapt(raw,h))]:
  p=folder/(name+'-v2.tei.xml');p.write_bytes(b)
  try:
   projected=project_bible_document(p,**context);errors=verify_bible_document(p,projected['rows'],projected['receipt'],**context)
  except ValueError as exc:cases.append(dict(name=name,status='rejected',reason=str(exc)));continue
  if errors:raise ValueError(errors)
  cases.append(dict(name=name,status='pass',rows=len(projected['rows']),characters=sum(len(r['text']) for r in projected['rows']),errors=errors))
  (folder/'passing-projection-v2.json').write_bytes(canonical(projected))
 io_path(ROOT/LOG/'current-route-probe-v2.json').write_bytes(canonical(dict(cases=cases,qualification='Diagnostic; full independent source/body/context proof, current package/replay/mutations and guarded installation pending.')))
 print(json.dumps(cases))
if __name__=='__main__':main()
