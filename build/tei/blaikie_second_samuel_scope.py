"""Blaikie's complete Second Samuel work and qualified existing LIB036 replay."""
from pathlib import Path
import hashlib,json,base64
from lxml import etree

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/blaikie-second-samuel-existing-20261003-v4')
REPLAY_LOG=Path('reports/_logs/bennett-existing-install-20261003-v1')
OLD_PACKAGE=REPLAY_LOG/'qualified-current-lib036-replay'
WORK_ID='expositors-bible--william-g-blaikie'
NS='{http://www.tei-c.org/ns/1.0}'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
MEMBERS={'blaikie-expositor2sam':dict(volume=1,path='raw/ccel/expositors-bible/blaikie_expositor2sam.xml',sha256='e3397acdd20cbc7ea8ef6c81eb10407263fe1276b40973c07cd908cf4902c379',bytes=758940,elements=1908,body_elements=1845,body_comments=10,tbody_wrappers=0,colgroup_wrappers=0,native_source_elements=1844,front=['i'],back=['xxxv'],source_base_url='https://www.ccel.org/ccel/blaikie/expositor2sam.html')}
BOUNDARY='One complete authored commentary on The Second Book of Samuel by W.G. Blaikie, within The Expositors Bible series edited by W. Robertson Nicoll. Its own titled New York A.C. Armstrong and Son 1898 title page, chapters I-XXXIII, concluding chapter and final generated indexes define this complete book. First Samuel and Joshua are distinct titled works outside this candidate; author-catalog and series completeness are not claimed.'
for member,spec in MEMBERS.items():spec.update(form=WORK_ID+'--'+member+'--retained-en',edition=WORK_ID+'--'+member+'--ccel-electronic',acquisition=WORK_ID+'--'+member+'--acquired')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_comments=False,huge_tree=True))
def correction_rows(member):
 profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
 return [r for r in profile['text_corrections'] if r['member_id']==member]
def retained(member):
 spec=MEMBERS[member];raw=(ROOT/spec['path']).read_bytes()
 if len(raw)!=spec['bytes'] or sha(raw)!=spec['sha256']:raise ValueError('Blaikie Second Samuel acquired witness drifted')
 return raw
def reconcile(member, *, package_path=None):
 from ocd_kernel.reconstruction import CandidatePackage
 package=CandidatePackage.load(ROOT/OLD_PACKAGE if package_path is None else package_path);account=json.loads(package.member_bytes('source-accountability.json'));tei=parse(package.member_bytes('content.tei.xml'))
 divisions=tei.xpath('//*[@xml:id=$id]',id=member)
 if len(divisions)!=1:raise ValueError('Blaikie Second Samuel replay member cardinality differs')
 div=divisions[0];notes=div.findall(NS+'note')
 if len(notes)!=1 or base64.b64decode(notes[0].text,validate=True)!=retained(member):raise ValueError('Blaikie Second Samuel replay encoded source differs')
 elements=[n for n in parse(retained(member)).iter() if isinstance(n.tag,str)];rows=[r for r in account['crosswalk'] if r['member_id']==member];ledger=div.findall('.//'+NS+'ab')
 if len(elements)!=len(rows) or len(ledger)!=len(elements):raise ValueError('Blaikie Second Samuel replay feature cardinality differs')
 positions={n:i for i,n in enumerate(elements,1)};choices=0
 expected=correction_rows(member)
 correction_fields=('member_id','source_selector','source_field','source_value_sha256','start','end','sic','corr','witness_url')
 proposals={'urn:ocd:source-text-correction:'+sha('\\0'.join(str(r[k]) for k in correction_fields).encode()):r for r in expected}
 used=set()
 def sic_text(segment,row,field):
  nonlocal choices
  result=segment.text or ''
  for child in segment:
   if child.tag!=NS+'choice' or [n.tag for n in child]!=[NS+'sic',NS+'corr']:raise ValueError('Blaikie Second Samuel historical choice envelope differs')
   identity=child.get('corresp');proposal=proposals.get(identity)
   value=row['source_direct_text' if field=='text' else 'source_tail_text']
   if proposal is None or identity in used or child.attrib!={'corresp':identity,'resp':proposal['witness_url']} or child[0].attrib or child[1].attrib or len(child[0]) or len(child[1]) or child[0].text!=proposal['sic'] or child[1].text!=proposal['corr'] or proposal['source_selector']!=row['source_selector'] or proposal['source_field']!=field or proposal['source_value_sha256']!=sha(value.encode()) or value[proposal['start']:proposal['end']]!=proposal['sic']:raise ValueError('Blaikie Second Samuel exact historical sic/corr authority or source span differs')
   used.add(identity)
   choices+=1;result+=(child[0].text or '')+(child.tail or '')
  return result
 for i,(n,row,block) in enumerate(zip(elements,rows,ledger,strict=True),1):
  parent=n.getparent();siblings=[c for c in parent if isinstance(c.tag,str)] if parent is not None else [n]
  path=[];cursor=n
  while cursor is not None:
   owner=cursor.getparent();same=[c for c in owner if isinstance(c.tag,str) and c.tag==cursor.tag] if owner is not None else [cursor]
   path.append(cursor.tag+'['+str(same.index(cursor)+1)+']');cursor=owner
  selector='/'+'/'.join(reversed(path));feature_id=member+'-feature-'+format(i,'05d')
  expected_row=dict(disposition='represented',feature_id=feature_id,member_id=member,work_id=WORK_ID,
   source_attributes=dict(n.attrib),source_child_ordinal=siblings.index(n)+1,source_parent_ordinal=positions.get(parent),
   source_selector=selector,source_tag=n.tag,source_direct_text=n.text or '',source_tail_text=n.tail or '',
   source_direct_text_sha256=sha((n.text or '').encode('utf8')),source_tail_text_sha256=sha((n.tail or '').encode('utf8')),
   tei_selector='#'+feature_id,tei_xml_id=feature_id)
  if row!=expected_row or block.get(XML_ID)!=feature_id or block.get('subtype')!=n.tag:
   raise ValueError('Second Samuel complete15-field raw-derived retained crosswalk differs '+str(i))
  segs=block.findall(NS+'seg')
  if len(segs)!=2 or [s.get('type') for s in segs]!=['direct-text','tail-text'] or sic_text(segs[0],row,'text')!=(n.text or '') or sic_text(segs[1],row,'tail')!=(n.tail or ''):raise ValueError('Blaikie Second Samuel replay actual original-reading payload differs '+str(i))
 if choices!=len(expected) or used!=set(proposals):raise ValueError('Historical correction count differs')
 return dict(status='pass',qualification='Current converter-only aggregate replay, not recovered September11 candidate; no historical oracle pass claimed',package_sha256=package.sha256,feature_count=len(rows),all_source_graph_and_actual_sic_fields_equal=True, all_declared_crosswalk_fields_raw_derived=True, checked_crosswalk_fields=sorted(expected_row), feature_identity_ordinal_xpath_and_text_hashes_equal=True,historical_choices=choices,corrections_adopted=0)
def scope_report():
 member='blaikie-expositor2sam';spec=MEMBERS[member];raw=retained(member);source=parse(raw);body=source.find('ThML.body');head=source.find('ThML.head')
 title=head.findtext('.//DC.Title');page=''.join(body.find("div1[@id='i']").itertext());roots=[n for n in body if isinstance(n.tag,str)]
 if title!="The Expositor's Bible: The Second Book of Samuel" or 'THE SECOND BOOK' not in page or 'BLAIKIE' not in page or '1898.' not in page or 'ARMSTRONG AND SON' not in page or len(roots)!=35 or roots[1].get('id')!='ii' or roots[-2].get('id')!='xxxiv' or roots[-1].get('id')!='xxxv':raise ValueError('Primary complete-work boundary differs')
 if sum(isinstance(n.tag,str) for n in source.iter())!=spec['elements']:raise ValueError('Whole source census differs')
 return dict(status='pass',work_id=WORK_ID,complete_authored_works=1,retained_sources=1,source_boundary=BOUNDARY,member=dict(member_id=member,**spec,title=title,title_page=page,root_divisions=[dict(id=n.get('id'),title=n.get('title')) for n in roots],lineage=reconcile(member)),excluded_works=['First Samuel','Joshua'],historical_corrections=correction_rows(member),historical_correction_policy='No Second Samuel correction rows exist in the retained profile; raw readings preserved',patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'])
if __name__=='__main__':
 result=scope_report();path=ROOT/LOG/'retained-scope-reconciliation.json'
 if path.exists():raise FileExistsError('Preserve prior Second Samuel source reconciliation')
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf8');print(sha(path.read_bytes()))
