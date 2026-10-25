"""Finite existing Chadwick work: one retained form, two acquired book editions."""
from pathlib import Path
import hashlib,json
from lxml import etree

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/chadwick-existing-install-20261003-v1')
WORK_ID='expositors-bible--g-a-chadwick'
OLD_PACKAGE=LOG/'immutable-prior-mark-package'
MEMBERS={
 'chadwick-mark':dict(volume=1,path='raw/ccel/expositors-bible/chadwick_mark.xml',sha256='1bbe36d072f96184a6d6c46a13d0b0b4e6c395f02efd5e769dc87e2d6fcf4bf2',bytes=912510,elements=2453,body_elements=2406,native_source_elements=2405,body_comments=10,tbody_wrappers=0,front=['i','ii'],back=['xix'],edition=WORK_ID+'-mark-retained-electronic',acquisition=WORK_ID+'-mark-acquired',source_base_url='https://www.ccel.org/ccel/chadwick/mark.html',route='bounded-existing-readable-annotation-repair'),
 'chadwick-exodus':dict(volume=2,path='raw/ccel/expositors-bible/chadwick_expositor2.xml',sha256='aa254cd88c1d64f9e5210288079a289dc57fc634410488662e0e721da8874c61',bytes=980151,elements=4251,body_elements=4184,native_source_elements=4183,body_comments=10,tbody_wrappers=0,front=['i','ii','iii'],back=['xli'],edition=WORK_ID+'-exodus-retained-electronic',acquisition=WORK_ID+'-exodus-acquired',source_base_url='https://www.ccel.org/ccel/chadwick/expositor2.html',route='existing-downloaded-companion-completion'),
}
for spec in MEMBERS.values():spec['form']='chadwick-expositors-retained-english'
OLD_TEI_SHA='09a167b7911389682950fb3d9676d315bb38a0fd8490158005ec26f2537693b6'
OLD_ACCOUNT_SHA='a1e46606dfa4ac4cab8a97be4f015a715ad7875c97ca93614d2daee2c1f387e9'
OLD_MANIFEST_SHA='51397086b9b526250c45cb223df13ef329492cee8a4a9e50be2ec22993a51554'
NS='{http://www.tei-c.org/ns/1.0}'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_comments=False,remove_pis=False,huge_tree=True))
def retained(member):
 spec=MEMBERS[member];raw=(ROOT/spec['path']).read_bytes()
 if sha(raw)!=spec['sha256'] or len(raw)!=spec['bytes']:raise ValueError('Chadwick acquired raw witness drifted '+member)
 return raw

def reconcile_mark():
 """Assess source/native fields and graph; historical status is not the proof."""
 tei_raw=(ROOT/OLD_PACKAGE/'content.tei.xml').read_bytes();account_raw=(ROOT/OLD_PACKAGE/'source-accountability.json').read_bytes();manifest_raw=(ROOT/OLD_PACKAGE/'manifest.json').read_bytes()
 if (sha(tei_raw),sha(account_raw),sha(manifest_raw))!=(OLD_TEI_SHA,OLD_ACCOUNT_SHA,OLD_MANIFEST_SHA):raise ValueError('Chadwick immutable prior Mark package drifted')
 manifest=json.loads(manifest_raw)
 for item in manifest['members']:
  raw=(ROOT/OLD_PACKAGE/item['name']).read_bytes()
  if len(raw)!=item['bytes'] or sha(raw)!=item['sha256']:raise ValueError('Chadwick prior Mark package member changed '+item['name'])
 source=parse(retained('chadwick-mark'));source_body=source.find('ThML.body')
 source_nodes=[n for n in source_body.iterdescendants() if isinstance(n.tag,str)]
 native=parse(tei_raw);account=json.loads(account_raw)
 nodes={n.get(XML_ID):n for n in native.iter() if n.get(XML_ID)}
 if len(source_nodes)!=2405 or len(account['crosswalk'])!=2405:raise ValueError('Chadwick original Mark complete body census differs')
 source_ids={n.get('id') for n in source_nodes if n.get('id')}
 generated=0;source_native={}
 for ordinal,(source_node,row) in enumerate(zip(source_nodes,account['crosswalk'],strict=True),1):
  identity=source_node.get('id') or f'mark-generated-{ordinal:05d}'
  if source_node.get('id') is None and identity in source_ids:raise ValueError('Unexpected legacy generated ID collision')
  source_native[source_node]=identity
  if row['source_tag']!=source_node.tag or row['attributes']!=dict(source_node.attrib) or row['source_xml_id']!=source_node.get('id') or row['tei_xml_id']!=identity or row['direct_text']!=(source_node.text or '') or row['tail_text']!=(source_node.tail or ''):
   raise ValueError('Chadwick prior Mark raw/account field differs at '+str(ordinal))
  node=nodes[identity]
  attrs={(XML_ID if key=='xml:id' else key):value for key,value in row['tei_attributes'].items()}
  if node.tag!=NS+row['tei_tag'] or dict(node.attrib)!=attrs or (node.text or '')!=(source_node.text or '') or (node.tail or '')!=(source_node.tail or ''):
   raise ValueError('Chadwick prior actual native Mark field differs at '+str(ordinal))
  parent=source_node.getparent();native_parent=node.getparent()
  expected_parent='mark-whole-body' if parent is source_body else source_native[parent]
  expected_siblings=[c for c in parent if isinstance(c.tag,str)]
  actual_siblings=[c for c in native_parent if c.get(XML_ID)]
  if native_parent.get(XML_ID)!=expected_parent or row['tei_parent_id']!=expected_parent or actual_siblings.index(node)!=expected_siblings.index(source_node) or row['tei_child_ordinal']!=expected_siblings.index(source_node)+1:
   raise ValueError('Chadwick prior actual native Mark relationship differs at '+str(ordinal))
  if source_node.get('title'):
   headings=node.findall(NS+'head')
   if len(headings)!=1 or headings[0].get('type')!='source-title' or headings[0].text!=source_node.get('title'):raise ValueError('Chadwick source title attachment differs')
 return tei_raw,account,dict(status='pass',original_tei_sha256=OLD_TEI_SHA,original_account_sha256=OLD_ACCOUNT_SHA,original_manifest_sha256=OLD_MANIFEST_SHA,
  all_source_and_actual_native_direct_tail_fields_equal=True,all_source_account_attrs_equal=True,all_original_native_attrs_and_relationships_equal=True,source_features=2405,
  retained_route='Existing genuinely readable native Mark body; additive source heading-level and relative-query URI context repair required; full source head/prolog/DOCTYPE disclosure renewal required',
  qualification='This reconciliation checks old raw fields and actual native graph against original account; final independent source-grounded semantic oracle does not adopt ledger attributes as correctness authority.')

def scope_report():
 work=json.loads((ROOT/'library/works'/WORK_ID/'work.json').read_bytes())
 if len(work['textual_forms'])!=1 or work['textual_forms'][0]['textual_form_id']!='chadwick-expositors-retained-english' or {x['edition_id'] for x in work['textual_forms'][0]['editions']}!={s['edition'] for s in MEMBERS.values()}:raise ValueError('Chadwick canonical one-form/two-edition scope changed')
 _,_,mark=reconcile_mark();rows=[]
 for member,spec in MEMBERS.items():
  raw=retained(member);tree=parse(raw);head=tree.find('ThML.head');body=tree.find('ThML.body')
  if len([n for n in tree.iter() if isinstance(n.tag,str)])!=spec['elements'] or len([n for n in body.iter() if isinstance(n.tag,str)])!=spec['body_elements']:raise ValueError('Chadwick complete acquired source envelope differs')
  rows.append(spec|dict(member_id=member,title=head.findtext('.//DC.Title'),print_statement=head.findtext('.//published'),outer_body=[dict(tag=n.tag,attributes=dict(n.attrib)) for n in body if isinstance(n.tag,str)],
   scope='Complete already acquired titled electronic book, including all source front/back matter; Mark and Exodus are distinct source books within the existing combined canonical work; no combined print-edition claim'))
 result=dict(status='pass',work_id=WORK_ID,included_volume_count=2,canonical_form_count=1,acquired_edition_count=2,volumes=rows,original_mark=mark,
  exodus_candidate_discovery='No corresponding retained Exodus TEI found in bounded known candidate filename inventories and named db14 integration root; not exhaustive system absence. Completion of this already downloaded companion remains authorized.',
  source_quality=['Literal Mark Strong Meat for Hungry Souls title-page heading remains in source order','Literal Exodus The Typial Bearings of the History and grouped Chapters XXXV-XL remain; no spelling repair or fabricated per-chapter mapping','Exodus has one source-broken #xxvi-Page_348 link labelled 8; no replacement target'],
  no_new_acquisition_or_download=True,human_print_rights_publication='Separate, not established by source accounting')
 (ROOT/LOG/'retained-scope-reconciliation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return result

if __name__=='__main__':print(json.dumps(scope_report(),ensure_ascii=True))
