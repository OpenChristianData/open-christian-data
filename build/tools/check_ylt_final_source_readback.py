"""Read current binding maps and compare installed YLT directly to retained JSON.

This observer imports neither source producer/oracle nor public projection/release.
"""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from lxml import etree
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'reports/_logs/ylt-offline-release-20261002-v1'
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
def raw(p):return io_path(p).read_bytes()
def digest(p):return sha256(raw(p)).hexdigest()
def ensure(condition,label):
 if not condition:raise ValueError(label)
def attrs(node,expected,label):ensure(dict(node.attrib)==expected,label+' attributes')
def main():
 audit=LOG/'current-delivery-audit.json';audit_bytes=raw(audit);record=json.loads(audit_bytes)
 ensure(record['status']=='pass','Current delivery status')
 counts={};checks=[]
 for kind in ['authority','schemas','release','evidence']:
  base=Path(record['map_bases'][kind]);counts[kind]=len(record[kind])
  for p,h in record[kind].items():
   actual=digest(base/p);ensure(actual==h,'Current '+kind+' binding '+p)
   checks.append(dict(kind=kind,path=p,sha256=actual))
 ensure(sum(counts.values())==158,'Exact158 bindings')
 source_path=ROOT/'raw/bible_databases/formats/json/YLT.json';source_bytes=raw(source_path);source=json.loads(source_bytes)
 ensure(sha256(source_bytes).hexdigest()=='d55ef42dae715c4fc5d00049011b818a42a99e0ff419f5f08bc37cea0b4f12e3','Retained source hash')
 master_path=ROOT/'library/works/ylt/forms/ylt-english/editions/ylt-retained-electronic-witness/master.tei.xml';master_bytes=raw(master_path)
 ensure(sha256(master_bytes).hexdigest()==record['completed']['accepted_master_sha256'],'Installed master hash')
 tree=etree.fromstring(master_bytes,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_blank_text=False))
 ensure(not tree.getroottree().docinfo.doctype,'No DOCTYPE')
 ensure(set(source)=={'translation','books'},'Source envelope fields')
 header=tree.find(NS+'teiHeader');bibl=header.find('.//'+NS+'bibl')
 ensure(bibl.text==source['translation'],'Literal translation label')
 text=tree.find(NS+'text');ensure(len(text)==1 and text[0].tag==NS+'body','Complete native text envelope')
 body=text[0];books=list(body);ensure(len(books)==len(source['books'])==66,'Whole66 books')
 chapters=verses=characters=empty=0;book_evidence=[]
 for ordinal,(book,sbook) in enumerate(zip(books,source['books'],strict=True),1):
  key=f'ylt-book-{ordinal:03d}'
  ensure(set(sbook)=={'name','chapters'},'Source book fields')
  ensure(book.tag==NS+'div','Native book tag')
  attrs(book,{'type':'book','n':sbook['name'],XML+'id':key},key)
  ensure(book.text is None and book.tail is None,'Book direct text/tail '+key)
  ensure(len(book)==len(sbook['chapters'])+1,'Book chapter/head cardinality '+key)
  head=book[0];ensure(head.tag==NS+'head' and len(head)==0 and head.text==sbook['name'] and head.tail is None,'Literal source book head '+key)
  attrs(head,{XML+'id':key+'-title'},key+' head')
  for chposition,(chapter,schapter) in enumerate(zip(list(book)[1:],sbook['chapters'],strict=True),1):
   ensure(set(schapter)=={'chapter','verses'},'Source chapter fields')
   ckey=key+f'-chapter-{chposition:03d}'
   ensure(chapter.tag==NS+'div','Native chapter tag')
   attrs(chapter,{'type':'chapter','n':str(schapter['chapter']),XML+'id':ckey},ckey)
   ensure(chapter.text is None and chapter.tail is None,'Chapter direct text/tail '+ckey)
   ensure(len(chapter)==len(schapter['verses']),'Chapter verse multiplicity '+ckey)
   chapters+=1
   for vposition,(verse,sverse) in enumerate(zip(chapter,schapter['verses'],strict=True),1):
    ensure(set(sverse)=={'verse','text'} and isinstance(sverse['text'],str),'Present literal source verse fields')
    vkey=ckey+f'-verse-{vposition:03d}'
    ensure(verse.tag==NS+'ab' and len(verse)==0,'Native childless verse '+vkey)
    attrs(verse,{'type':'verse','n':str(sverse['verse']),XML+'id':vkey,XML+'space':'preserve'},vkey)
    ensure((verse.text or '')==sverse['text'] and verse.tail is None,'Exact source verse text/tail '+vkey)
    verses+=1;characters+=len(sverse['text']);empty+=not bool(sverse['text'])
  book_evidence.append(dict(position=ordinal,source_name=sbook['name'],id=key,chapters=len(sbook['chapters']),verse_carriers=sum(len(c['verses']) for c in sbook['chapters'])))
 ensure((chapters,verses,characters,empty)==(1189,31102,4101874,0),'Complete source counts')
 terminal=ROOT/'reports/_logs/ylt-current-reconciliation-20261002-v1/private-release-terminal.json'
 ensure(json.loads(raw(terminal))['exit_code']==0,'Authoritative private terminal')
 proof=dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),current_delivery_audit_sha256=sha256(audit_bytes).hexdigest(),map_counts=counts,binding_checks=checks,installed_master_sha256=sha256(master_bytes).hexdigest(),retained_source_sha256=sha256(source_bytes).hexdigest(),private_release_terminal_sha256=digest(terminal),private_release_exit_code=0,observer_sha256=digest(Path(__file__)),books=66,chapters=chapters,verse_carriers=verses,text_codepoints=characters,empty_source_text_values=empty,book_evidence=book_evidence,all_source_strings_labels_order_multiplicity_and_parent_attachment=True,all_native_ids_and_attributes_checked=True,producer_oracle_projection_release_not_imported=True,qualification='Direct installed-master versus real retained JSON comparison and current hash readback only; no projection/release/test rerun, physical old-package recovery, human acceptance, print/translator/rights/publication claim.')
 out=LOG/'independent-final-source-and-binding-readback.json'
 ensure(not out.exists(),'Fresh readback receipt required');out.write_text(json.dumps(proof,ensure_ascii=True,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print(json.dumps(dict(status='pass',path=out.as_posix(),sha256=digest(out),counts=counts,books=66,chapters=chapters,verse_carriers=verses,text_codepoints=characters)))
if __name__=='__main__':main()
