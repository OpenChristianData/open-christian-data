"""Independent direct retained BSB JSON/native baseline observer; no producer imports."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from lxml import etree
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'reports/_logs/bsb-coordinator-source-review-20261002-v1'
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
SOURCE=ROOT/'raw/bible_databases/formats/json/BSB.json'
BASELINE=ROOT/'reports/_logs/bsb-current-reconciliation-20261002-v1/source-derived-historical-native/content.tei.xml'
def read(p):return io_path(p).read_bytes()
def ensure(ok,label):
 if not ok:raise ValueError(label)
def attrs(node,expected,label):ensure(dict(node.attrib)==expected,label+' exact attributes')
def formatting(node,label):
 ensure(node.text is None or not node.text.strip(),label+' unexpected direct text')
 ensure(node.tail is None or not node.tail.strip(),label+' unexpected meaningful tail')
def main():
 source_bytes=read(SOURCE);baseline_bytes=read(BASELINE)
 source_sha=sha256(source_bytes).hexdigest();baseline_sha=sha256(baseline_bytes).hexdigest()
 ensure(source_sha=='73ca9ea1e36041bbbbd077738b250e266192669819117326516f871804872dac','Source preimage')
 ensure(baseline_sha=='d2382c393edf36488497e1865c2bd155a00c515103219b2fb5d4cd6491d5b511','Baseline preimage')
 source=json.loads(source_bytes);doc=etree.fromstring(baseline_bytes,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_blank_text=False))
 ensure(not doc.getroottree().docinfo.doctype,'No DOCTYPE')
 ensure(set(source)=={'translation','books'},'Exact source envelope')
 ensure(doc.tag==NS+'TEI','Native root');attrs(doc,{XML+'id':'bsb-candidate'},'Native root')
 ensure([n.tag for n in doc]==[NS+'teiHeader',NS+'text'],'Whole native root components')
 header=doc[0]
 ensure(header.findtext('.//'+NS+"title[@type='translation-marker']")==source['translation'],'Literal source translation title')
 ensure(header.findtext('.//'+NS+"note[@type='translation-marker']")==source['translation'],'Literal source translation note')
 ensure(header.findtext('.//'+NS+"idno[@type='sha256']")==source_sha,'Source header digest')
 ensure(header.findtext('.//'+NS+"num[@type='bytes']")==str(len(source_bytes)),'Source header byte count')
 text=doc[1];attrs(text,{XML+'id':'bsb-text','type':'bible'},'Native text');formatting(text,'Native text')
 ensure(len(text)==1 and text[0].tag==NS+'body','Single whole-source body')
 body=text[0];attrs(body,{XML+'id':'bsb-body'},'Native body');formatting(body,'Native body')
 ensure(len(body)==len(source['books'])==66,'Whole66 book cardinality')
 chapters=verses=characters=empty=leading=trailing=0;empty_loci=[];whitespace_loci=[];books=[];ids=set()
 def identity(key):ensure(key not in ids,'Duplicate native ID '+key);ids.add(key)
 for position,(book,sbook) in enumerate(zip(body,source['books'],strict=True),1):
  ensure(set(sbook)=={'name','chapters'},'Exact source book fields')
  key=f'bsb-book-{position:02d}';identity(key)
  ensure(book.tag==NS+'div','Book tag '+key);attrs(book,{'type':'book','n':str(position),XML+'id':key},key);formatting(book,key)
  ensure(len(book)==len(sbook['chapters'])+1,'Complete chapter cardinality '+key)
  head=book[0];ensure(head.tag==NS+'head' and not head.attrib and len(head)==0 and head.text==sbook['name'],'Literal book heading '+key)
  ensure(head.tail is None or not head.tail.strip(),'Book heading meaningful tail')
  for chapter,schapter in zip(list(book)[1:],sbook['chapters'],strict=True):
   ensure(set(schapter)=={'chapter','verses'},'Exact source chapter fields')
   ckey=key+f"-chapter-{schapter['chapter']:03d}";identity(ckey)
   ensure(chapter.tag==NS+'div','Chapter tag');attrs(chapter,{'type':'chapter','n':str(schapter['chapter']),XML+'id':ckey},ckey);formatting(chapter,ckey)
   ensure(len(chapter)==len(schapter['verses'])+1,'Complete verse/head cardinality '+ckey)
   chhead=chapter[0];ensure(chhead.tag==NS+'head' and not chhead.attrib and len(chhead)==0 and chhead.text==str(schapter['chapter']),'Literal chapter heading '+ckey)
   ensure(chhead.tail is None or not chhead.tail.strip(),'Chapter heading meaningful tail')
   chapters+=1
   for verse,sverse in zip(list(chapter)[1:],schapter['verses'],strict=True):
    ensure(set(sverse)=={'verse','text'} and isinstance(sverse['text'],str),'Exact present source verse fields')
    vkey=ckey+f"-verse-{sverse['verse']:03d}";identity(vkey)
    ensure(verse.tag==NS+'ab' and len(verse)==0,'Childless verse carrier '+vkey)
    attrs(verse,{'type':'verse','n':str(sverse['verse']),XML+'id':vkey},vkey)
    ensure((verse.text or '')==sverse['text'],'Exact literal verse string '+vkey)
    ensure(verse.tail is None or not verse.tail.strip(),'Unexpected meaningful verse tail '+vkey)
    value=sverse['text'];locus=dict(book=sbook['name'],chapter=schapter['chapter'],verse=sverse['verse'],id=vkey)
    verses+=1;characters+=len(value)
    if value=='':empty+=1;empty_loci.append(locus)
    if value!=value.lstrip():leading+=1
    if value!=value.rstrip():trailing+=1
    if value!=value.strip():whitespace_loci.append(locus|dict(source_string=value))
  books.append(dict(position=position,id=key,source_name=sbook['name'],chapters=len(sbook['chapters']),verse_carriers=sum(len(c['verses']) for c in sbook['chapters'])))
 ensure((chapters,verses,empty)==(1189,31102,16),'Expected complete BSB counts')
 ensure(read(SOURCE)==source_bytes and read(BASELINE)==baseline_bytes,'Source/baseline remained current during independent review')
 record=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),reviewer='agent:gregory-independent-direct-BSB-baseline-observer',source_path=SOURCE.relative_to(ROOT).as_posix(),source_sha256=source_sha,source_bytes=len(source_bytes),baseline_path=BASELINE.relative_to(ROOT).as_posix(),baseline_sha256=baseline_sha,baseline_bytes=len(baseline_bytes),observer_sha256=sha256(read(Path(__file__))).hexdigest(),books=66,chapters=chapters,verse_carriers=verses,text_codepoints=characters,empty_source_strings=empty,leading_whitespace_strings=leading,trailing_whitespace_strings=trailing,empty_loci=empty_loci,whitespace_loci=whitespace_loci,book_evidence=books,unique_native_book_chapter_verse_ids=len(ids),every_source_literal_string_label_order_multiplicity_parent_and_native_id_checked=True,generated_indentation_only_outside_literal_source_carriers=True,current_source_baseline_stable=True,no_producer_oracle_projection_release_imported=True,qualification='Whole retained-source baseline body proof only. Generated XML indentation outside literal source carriers is checked as whitespace-only; source leading/trailing whitespace is compared exactly without trimming. Fresh source-derived reproduction does not prove physical recovery of disposed historical packages. Current renewed header/routing/P5/acceptance/install/publication proofs and human/print/rights decisions remain with the owner/coordinator.')
 LOG.mkdir(parents=True,exist_ok=True);out=LOG/'gregory-independent-baseline-review.json';ensure(not out.exists(),'Fresh independent receipt required')
 out.write_text(json.dumps(record,ensure_ascii=True,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print(json.dumps(dict(status='pass',receipt=out.as_posix(),receipt_sha256=sha256(read(out)).hexdigest(),source_sha256=source_sha,baseline_sha256=baseline_sha,books=66,chapters=chapters,verse_carriers=verses,text_codepoints=characters,empty_source_strings=empty,leading_whitespace_strings=leading,trailing_whitespace_strings=trailing)))
if __name__=='__main__':main()
