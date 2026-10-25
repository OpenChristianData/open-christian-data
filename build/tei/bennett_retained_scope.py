"""Bennett's two complete authored works and qualified existing LIB036 replay."""
from pathlib import Path
import hashlib,json,base64
from lxml import etree

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/bennett-existing-install-20261003-v1')
OLD_PACKAGE=LOG/'qualified-current-lib036-replay'
WORK_ID='expositors-bible--w-h-bennett'
NS='{http://www.tei-c.org/ns/1.0}'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
MEMBERS={
 'bennett-expositorjer2':dict(volume=1,path='raw/ccel/expositors-bible/bennett_expositorjer2.xml',sha256='6d06ef71aedbb8d960aa229f69c4286b700261c1a23bfa33bc1e16886bd18293',bytes=914224,elements=6267,body_elements=6175,body_comments=10,tbody_wrappers=4,colgroup_wrappers=0,native_source_elements=6170,front=['i','ii','iii','iv','v'],back=['x'],source_base_url='https://www.ccel.org/ccel/bennett/expositorjer2.html'),
 'bennett-expositor10':dict(volume=2,path='raw/ccel/expositors-bible/bennett_expositor10.xml',sha256='b09acd5c4cbbe1f811e092f27e23d6ec7d9c7b7f1aeda485b6957f7f77aa61e4',bytes=1183464,elements=4985,body_elements=4940,body_comments=18,tbody_wrappers=1,colgroup_wrappers=1,native_source_elements=4938,front=['i','ii'],back=['vii'],source_base_url='https://www.ccel.org/ccel/bennett/expositor10.html'),
}
for member,spec in MEMBERS.items():spec.update(form=WORK_ID+'--'+member+'--retained-en',edition=WORK_ID+'--'+member+'--ccel-electronic',acquisition=WORK_ID+'--'+member+'--acquired')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_comments=False,huge_tree=True))
def correction_rows(member):
 profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
 return [r for r in profile['text_corrections'] if r['member_id']==member]
def retained(member):
 spec=MEMBERS[member];raw=(ROOT/spec['path']).read_bytes()
 if len(raw)!=spec['bytes'] or sha(raw)!=spec['sha256']:raise ValueError('Bennett acquired witness drifted')
 return raw
def reconcile(member):
 from ocd_kernel.reconstruction import CandidatePackage
 package=CandidatePackage.load(ROOT/OLD_PACKAGE);account=json.loads(package.member_bytes('source-accountability.json'));tei=parse(package.member_bytes('content.tei.xml'))
 divisions=tei.xpath('//*[@xml:id=$id]',id=member)
 if len(divisions)!=1:raise ValueError('Bennett replay member cardinality differs')
 div=divisions[0];notes=div.findall(NS+'note')
 if len(notes)!=1 or base64.b64decode(notes[0].text,validate=True)!=retained(member):raise ValueError('Bennett replay encoded source differs')
 elements=[n for n in parse(retained(member)).iter() if isinstance(n.tag,str)];rows=[r for r in account['crosswalk'] if r['member_id']==member];ledger=div.findall('.//'+NS+'ab')
 if len(elements)!=len(rows) or len(ledger)!=len(elements):raise ValueError('Bennett replay feature cardinality differs')
 positions={n:i for i,n in enumerate(elements,1)};choices=0
 expected=correction_rows(member)
 correction_fields=('member_id','source_selector','source_field','source_value_sha256','start','end','sic','corr','witness_url')
 proposals={'urn:ocd:source-text-correction:'+sha('\\0'.join(str(r[k]) for k in correction_fields).encode()):r for r in expected}
 used=set()
 def sic_text(segment,row,field):
  nonlocal choices
  result=segment.text or ''
  for child in segment:
   if child.tag!=NS+'choice' or [n.tag for n in child]!=[NS+'sic',NS+'corr']:raise ValueError('Bennett historical choice envelope differs')
   identity=child.get('corresp');proposal=proposals.get(identity)
   value=row['source_direct_text' if field=='text' else 'source_tail_text']
   if proposal is None or identity in used or child.attrib!={'corresp':identity,'resp':proposal['witness_url']} or child[0].attrib or child[1].attrib or len(child[0]) or len(child[1]) or child[0].text!=proposal['sic'] or child[1].text!=proposal['corr'] or proposal['source_selector']!=row['source_selector'] or proposal['source_field']!=field or proposal['source_value_sha256']!=sha(value.encode()) or value[proposal['start']:proposal['end']]!=proposal['sic']:raise ValueError('Bennett exact historical sic/corr authority or source span differs')
   used.add(identity)
   choices+=1;result+=(child[0].text or '')+(child.tail or '')
  return result
 for i,(n,row,block) in enumerate(zip(elements,rows,ledger,strict=True),1):
  parent=n.getparent();siblings=[c for c in parent if isinstance(c.tag,str)] if parent is not None else [n]
  if row['source_tag']!=n.tag or row['source_attributes']!=dict(n.attrib) or row['source_parent_ordinal']!=positions.get(parent) or row['source_child_ordinal']!=siblings.index(n)+1 or row['source_direct_text']!=(n.text or '') or row['source_tail_text']!=(n.tail or '') or row['tei_xml_id']!=block.get(XML_ID) or block.get('subtype')!=n.tag:raise ValueError('Bennett replay raw feature graph differs '+str(i))
  segs=block.findall(NS+'seg')
  if len(segs)!=2 or [s.get('type') for s in segs]!=['direct-text','tail-text'] or sic_text(segs[0],row,'text')!=(n.text or '') or sic_text(segs[1],row,'tail')!=(n.tail or ''):raise ValueError('Bennett replay actual original-reading payload differs '+str(i))
 if choices!=len(expected) or used!=set(proposals):raise ValueError('Historical correction count differs')
 return dict(status='pass',qualification='Current converter-only aggregate replay, not recovered September11 candidate; no historical oracle pass claimed',package_sha256=package.sha256,feature_count=len(rows),all_source_graph_and_actual_sic_fields_equal=True,historical_choices=choices,corrections_adopted=0)
def scope_report():
 rows=[]
 for member,spec in MEMBERS.items():
  raw=retained(member);source=parse(raw);body=source.find('ThML.body');head=source.find('ThML.head')
  if sum(isinstance(n.tag,str) for n in source.iter())!=spec['elements']:raise ValueError('Bennett complete source census differs')
  rows.append(dict(member_id=member,**spec,title=head.findtext('.//DC.Title'),title_page=''.join(body.find("div1[@id='i']").itertext()),preface=''.join(body.find("div1[@id='ii']").itertext()),root_divisions=[dict(id=n.get('id'),title=n.get('title')) for n in body if isinstance(n.tag,str)],lineage=reconcile(member)))
 return dict(status='pass',work_id=WORK_ID,complete_authored_works=2,acquired_sources=2,
  work_boundaries='Jeremiah title page names The Book of Jeremiah Chapters XXI-LII by W.H. Bennett. Its Preface expressly names this present work as a supplement to a separate volume by C.J. Ball; its own commentary chapters run I-XXXV. CCEL Volume II is biblical-book series coverage, not a missing Bennett authored volume. Chronicles has its own complete title, author, preface and internal Books I-IV. Exactly one TEI per distinct complete authored work; canonical author-cohort identity retained.',
  collection='Both belong to The Expositors Bible, edited by W. Robertson Nicoll. Ball, other authors, complete biblical Jeremiah coverage and series completeness excluded; no new acquisition.',
  correction_policy='All 85 Jeremiah legacy sic/corr rows retained unchanged as historical alternatives. No retained cited Gutenberg41893 witness located in bounded raw filename search; one unrelated Watson subtree ACL-denied. Raw reading preserved; no correction promoted.',members=rows)
if __name__=='__main__':
 result=scope_report();path=ROOT/LOG/'retained-scope-reconciliation.json';path.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf8');print(sha(path.read_bytes()))
