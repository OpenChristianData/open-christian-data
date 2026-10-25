"""Independent Joshua only reconciliation of replayed historical flat TEI evidence."""
from pathlib import Path
from hashlib import sha256
from urllib.parse import quote
import base64,json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'reports/_logs/blaikie-joshua-existing-install-20261003-v1'
OLD=LOG/'qualified-current-lib036-replay'
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--william-g-blaikie'

def reconcile():
 account=json.loads((OLD/'source-accountability.json').read_bytes())
 if sha256((OLD/'source-accountability.json').read_bytes()).hexdigest()!='fd5e9c342283c827b5d8fce1c95e3713d755ac3b8048de19874bdc4b983f2257':raise ValueError('Historical exact accounting pin differs')
 profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
 candidate=ET.fromstring((OLD/'content.tei.xml').read_bytes())
 tei=next(n for n in candidate if n.tag==NS+'TEI' and n.get(XML+'id')==WORK)
 members=tei.find(NS+'text/'+NS+'body')
 if members is None or not any(n.get(XML+'id')=='blaikie-expositorjosh' for n in members):raise ValueError('Selected existing Joshua graph absent')
 results=[];seen_corrections=[]
 for division in [n for n in members if n.get(XML+'id')=='blaikie-expositorjosh']:
  member=division.get(XML+'id');configured=next(r for r in profile['included_members'] if r['member_id']==member)
  path=next(r['path'] for r in json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.source-manifest.json').read_bytes())['authorities'] if r['name']==configured['authority_name'])
  raw=(ROOT/path).read_bytes()
  note=division.find(NS+'note');decoded=base64.b64decode(note.text,validate=True)
  if decoded!=raw or note.attrib!={'type':'exact-retained-source-bytes','subtype':'base64','n':sha256(raw).hexdigest()}:raise ValueError('Actual embedded historical source differs')
  source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)));elements=[n for n in source.iter() if isinstance(n.tag,str)];ordinals={id(n):i for i,n in enumerate(elements,1)};parents={id(c):n for n in elements for c in n}
  def selector(n):
   parent=parents.get(id(n))
   if parent is None:return '/'+n.tag+'[1]'
   peers=[c for c in parent if c.tag==n.tag]
   return selector(parent)+'/'+n.tag+'['+str(peers.index(n)+1)+']'
  rows=[r for r in account['crosswalk'] if r['member_id']==member]
  blocks=list(division.find(NS+'div'))
  if len(rows)!=len(elements) or len(blocks)!=len(elements):raise ValueError('Actual historical feature denominator differs')
  for ordinal,(node,row,block) in enumerate(zip(elements,rows,blocks),1):
   parent=parents.get(id(node));siblings=[n for n in parent if isinstance(n.tag,str)] if parent is not None else [node]
   identity=member+'-feature-'+str(ordinal).zfill(5);sel=selector(node)
   expected=dict(feature_id=identity,source_selector=sel,source_tag=node.tag,source_attributes=dict(sorted(node.attrib.items())),source_direct_text=node.text or '',source_tail_text=node.tail or '',source_direct_text_sha256=sha256((node.text or '').encode()).hexdigest(),source_tail_text_sha256=sha256((node.tail or '').encode()).hexdigest(),source_parent_ordinal=ordinals[id(parent)] if parent is not None else None,source_child_ordinal=siblings.index(node)+1,tei_xml_id=identity,member_id=member,work_id=WORK,disposition='represented',tei_selector='#'+identity)
   if row!=expected:raise ValueError('Independently read source/full accounting fields differ '+identity+' '+repr({k:(row.get(k),v) for k,v in expected.items() if row.get(k)!=v}))
   if block.tag!=NS+'ab' or block.attrib!={XML+'id':identity,'type':'source-xml-element','subtype':node.tag,'n':str(siblings.index(node)+1),'corresp':'urn:source-xpath:'+quote(sel,safe='')} or len(block)!=2 or (block.text or '') or (block.tail or ''):raise ValueError('Actual historical graph node differs '+identity)
   for segment,field,label in zip(block,('text','tail'),('direct-text','tail-text')):
    value=getattr(node,field) or ''
    if segment.tag!=NS+'seg' or segment.attrib!={'type':label} or (segment.tail or ''):raise ValueError('Historical text segment envelope differs')
    restored=segment.text or '';cursor=len(restored)
    for choice in segment:
     rows_here=[r for r in profile['text_corrections'] if r['member_id']==member and r['source_selector']==sel and r['source_field']==field and r['start']==cursor]
     if len(rows_here)!=1:raise ValueError('Actual historical choice source placement differs')
     r=rows_here[0];fields=('member_id','source_selector','source_field','source_value_sha256','start','end','sic','corr','witness_url')
     correction_id=sha256('\\0'.join(str(r[f]) for f in fields).encode()).hexdigest()
     if choice.tag!=NS+'choice' or choice.attrib!={'corresp':'urn:ocd:source-text-correction:'+correction_id,'resp':r['witness_url']} or (choice.text or '') or len(choice)!=2:raise ValueError('Historical correction annotation differs')
     sic,corr=choice
     if (sic.tag,sic.attrib,sic.text or '',sic.tail or '',len(sic))!=(NS+'sic',{},r['sic'],'',0) or (corr.tag,corr.attrib,corr.text or '',corr.tail or '',len(corr))!=(NS+'corr',{},r['corr'],'',0):raise ValueError('Historical choice readings differ')
     if sha256(value.encode()).hexdigest()!=r['source_value_sha256'] or value[r['start']:r['end']]!=r['sic'] or r['end']-r['start']!=len(r['sic']):raise ValueError('Historical sic span not exact source')
     restored+=r['sic']+(choice.tail or '');cursor=len(restored);seen_corrections.append(r)
    if restored!=value:raise ValueError('Actual historical graph original source reading differs')
  results.append(dict(member_id=member,features=len(elements),source_sha256=sha256(raw).hexdigest(),embedded_bytes_equal=True,all_actual_feature_fields_source_equal=True,original_sic_reading_inverse_equal=True,body_kind='flat parsed XML feature graph; not a readable native commentary'))
 expected_corrections=[r for r in profile['text_corrections'] if r['member_id']=='blaikie-expositorjosh']
 if sorted(json.dumps(r,sort_keys=True) for r in seen_corrections)!=sorted(json.dumps(r,sort_keys=True) for r in expected_corrections):raise ValueError('Historical Joshua correction complete ledger differs')
 return dict(status="pass",work_id=WORK,legacy_members=results,legacy_correction_count=len(seen_corrections),qualification="Current-authority converter-only replay, inaccessible September11 package not recovered; no historical bytes or oracle pass claimed")

if __name__=="__main__":
 result=reconcile();path=LOG/"retained-scope-reconciliation.json"
 if path.exists():raise FileExistsError("Preserve Joshua scope proof")
 path.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8");print(json.dumps(result,sort_keys=True))
