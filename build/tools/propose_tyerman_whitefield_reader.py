"""Generate an isolated, Whitefield-only maintained-reader patch proposal."""
from pathlib import Path
import difflib,hashlib,json
import xml.etree.ElementTree as ET
from lxml import etree

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.tmp_audit/tyerman_whitefield_native_v7'
MASTER=ROOT/'sources/manifest-acquisitions/tyerman-life-george-whitefield-accepted-header-draft-20261004-v1/candidate.tei.xml'
N='{http://www.tei-c.org/ns/1.0}'
X='{http://www.w3.org/XML/1998/namespace}'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def signature(node):return [node.tag,sorted(node.attrib.items()),node.text,node.tail,[signature(c) for c in node]]
def replace(text,old,new,count=1):
 if text.count(old)!=count:raise ValueError('Bounded patch preimage count differs '+repr(old[:90]))
 return text.replace(old,new)

def propose():
 if OUT.exists():raise FileExistsError('Preserve Whitefield reader draft')
 raw=MASTER.read_bytes()
 if sha(raw)!='24637ca4083c82f8c07eb8f375540a723cc35982e4cd5a9cdf37547f57778857':raise ValueError('Approved master differs')
 root=ET.fromstring(raw);observed=etree.fromstring(raw)
 if signature(root)!=signature(observed):raise ValueError('Independent full field signatures differ')
 graphics={}
 for node in root.iter(N+'graphic'):
  attrs=dict(node.attrib);url=attrs.pop('url');graphics[node.get(X+'id')]=dict(attributes=attrs,url_sha256=sha(url.encode()),alias='retained-embedded-image:'+node.get('corresp').removeprefix('urn:ocd:retained:'))
 profile='''"""Exact two-volume Whitefield biography reader admission; no acceptance creation."""
from pathlib import Path
import hashlib,json
from urllib.parse import unquote,quote
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.library._common import io_path
N='{http://www.tei-c.org/ns/1.0}'
X='{http://www.w3.org/XML/1998/namespace}'
PROFILE='ocd-prose-tyerman-whitefield-pg44280-62023-source-native-v1'
IDENTITY={'work_id':'tyerman-life-george-whitefield','textual_form_id':'tyerman-life-george-whitefield--retained-en','edition_id':'tyerman-life-george-whitefield--pg44280-62023-1876-1877'}
ACQUISITION='tyerman-life-george-whitefield--pg44280-62023-retained-member-set'
MASTER_SHA='24637ca4083c82f8c07eb8f375540a723cc35982e4cd5a9cdf37547f57778857'
FULL_FIELDS_SHA=FULL_SIGNATURE_PLACEHOLDER
GRAPHICS=GRAPHICS_PLACEHOLDER
ANCHORS={'v62023-p154a':'PgL635'+b'v62023-p154a'.hex()}
def anchor(value):
 if value not in ANCHORS:raise ValueError('Whitefield choice anchor differs')
 return ANCHORS[value]
SOURCE={'source_kind':'retained-member-set','source_path':'sources/manifest-acquisitions/tyerman-life-george-whitefield-identity-proposal-20261004-v1/source-member-set.json','source_bytes':2732,'source_sha256':'37df107ae0a87088c8d6c34c8ae085c9564fe333ea0aef902d49d47fd44993b4'}
RAW={'raw/gutenberg/44280/html/pg44280-images.html':(1782292,'8b1f346c952efe26f71c259fd08ebcbe38097a03eeeeae41d8f3c0cf556e0aca'),'raw/gutenberg/62023/html/pg62023-images.html':(2297996,'24a3a6825397c9e4c9fb061bdbb865bb5cc6be455501ccc2c784a21efd0febfa')}
def digest(raw):return hashlib.sha256(raw).hexdigest()
def route(identity,raw,*,language,category,collection,projection_profile,allow_acceptance_metadata,source_base):
 if identity.get('work_id')!=IDENTITY['work_id']:return False
 if identity!=IDENTITY or digest(raw)!=MASTER_SHA or language!='en' or category!='prose' or collection or projection_profile is not None or not allow_acceptance_metadata or source_base is not None:raise ValueError('Whitefield exact accepted master/identity/context differs')
 return True
def fields_et(node):return [node.tag,sorted(node.attrib.items()),node.text,node.tail,[fields_et(c) for c in node]]
def fields_lxml(node):return [str(node.tag),sorted((str(k),str(v)) for k,v in node.attrib.items()),node.text,node.tail,[fields_lxml(c) for c in node]]
def check_et(root):
 text=root.find(N+'text');group=text.find(N+'group') if text is not None else None
 if root.tag!=N+'TEI' or dict(root.attrib)!={X+'lang':'en'} or [c.tag for c in root]!=[N+'teiHeader',N+'text'] or text.attrib or [c.tag for c in text]!=[N+'group'] or group.attrib or len(group)!=2 or [c.get(X+'id') for c in group]!=['volume-44280','volume-62023'] or [c.get('n') for c in group]!=['I','II'] or any([p.tag for p in c]!=[N+'front',N+'body',N+'back'] for c in group):raise ValueError('Whitefield exact two-volume envelope/ownership differs')
 if digest(json.dumps(fields_et(root),ensure_ascii=False,separators=(',',':')).encode())!=FULL_FIELDS_SHA:raise ValueError('Whitefield complete actual fields/header/order/source body differ')
 return True
def check_lxml(root):
 nodes=root.xpath('./t:text/t:group/t:text',namespaces={'t':N[1:-1]})
 if len(nodes)!=2 or [n.get(X+'id') for n in nodes]!=['volume-44280','volume-62023'] or [n.get('n') for n in nodes]!=['I','II'] or any([etree.QName(p).localname for p in n]!=['front','body','back'] for n in nodes):raise ValueError('Observed Whitefield volume order/parts differ')
 if digest(json.dumps(fields_lxml(root),ensure_ascii=False,separators=(',',':')).encode())!=FULL_FIELDS_SHA:raise ValueError('Observed Whitefield entire actual tree fields differ')
 return True
def annotation(value):
 prefix='urn:ocd:l635:source:'
 if not value.startswith(prefix):raise ValueError('Whitefield source annotation identity differs')
 def unique(pairs):
  result={}
  for key,value in pairs:
   if key in result:raise ValueError('Duplicate Whitefield source key')
   result[key]=value
  return result
 result=json.loads(unquote(value[len(prefix):],errors='strict'),object_pairs_hook=unique)
 if quote(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')),safe='')!=value[len(prefix):] or not isinstance(result.get('attributes'),dict):raise ValueError('Whitefield canonical annotation differs')
 return result
def choice_et(node):
 a=annotation(node.get('ana',''))
 if a['tag']!='abbr' or set(node.attrib)-{'ana',X+'id'} or [c.tag for c in node]!=[N+'abbr',N+'expan'] or len(node[1]) or node[1].attrib or node[1].text!=a['attributes'].get('title'):raise ValueError('Whitefield abbreviation source/expansion differs')
def choice_lxml(node):
 source=annotation(node.get('ana',''));alternatives=list(node)
 if source.get('tag')!='abbr' or set(dict(node.attrib)) - {'ana',X+'id'} or [etree.QName(c).localname for c in alternatives]!=['abbr','expan'] or len(alternatives[1]) or dict(alternatives[1].attrib) or alternatives[1].text!=source['attributes'].get('title'):raise ValueError('Observed Whitefield abbreviation alternatives differ')
def graphic_et(node):
 attrs=dict(node.attrib);url=attrs.pop('url',None);expected=GRAPHICS.get(node.get(X+'id'))
 if expected is None or attrs!=expected['attributes'] or url is None or digest(url.encode())!=expected['url_sha256']:raise ValueError('Whitefield exact retained graphic/pixels/dimensions differ')
 css=' '.join([key+': '+node.get(key)+';' for key in ['width','height'] if node.get(key)]+([node.get('style')] if node.get('style') else []))
 return expected['alias'],css
def graphic_lxml(node):
 key=node.get(X+'id');expected=GRAPHICS.get(key)
 if expected is None or {str(k):str(v) for k,v in node.attrib.items() if k!='url'}!=expected['attributes'] or digest(node.get('url','').encode())!=expected['url_sha256']:raise ValueError('Observed Whitefield source graphic fields differ')
 declarations=[f'{key}: {node.get(key)};' for key in ('width','height') if node.get(key)]
 if node.get('style'):declarations.append(node.get('style'))
 return expected['alias'],' '.join(declarations)
def select(root,context,declared_profile):
 if context['identity'].get('work_id')!=IDENTITY['work_id']:return False
 from ocd_kernel.library.acquisitions import acquisition_for_edition,source_member_set_bytes
 accepted=context['accepted'];source=accepted.get('source',{})
 if context['identity']!=IDENTITY or accepted.get('identity')!={**IDENTITY,'acquisition_id':ACQUISITION} or context['language']!='en' or declared_profile is not None or context['authority']['master']['sha256']!=MASTER_SHA or {k:source.get(k) for k in SOURCE}!=SOURCE or source.get('missing_members')!=[] or source.get('unknown_members')!=[]:raise ValueError('Whitefield validated accepted identity/source/profile differs')
 acquisition_path,a=acquisition_for_edition(root,IDENTITY['work_id'],IDENTITY['edition_id'],acquisition_id=ACQUISITION)
 descriptor=io_path(root/SOURCE['source_path']).read_bytes()
 if a.get('acquisition_id')!=ACQUISITION or a.get('edition_id')!=IDENTITY['edition_id'] or a.get('url')!='https://www.gutenberg.org/ebooks/44280' or {k:a.get(k) for k in SOURCE}!=SOURCE or descriptor!=source_member_set_bytes(a) or len(descriptor)!=SOURCE['source_bytes'] or digest(descriptor)!=SOURCE['source_sha256'] or digest(io_path(acquisition_path).read_bytes())!=context['authority']['acquisition']['sha256']:raise ValueError('Whitefield exact retained acquisition/descriptor differs')
 for path,(length,pinned) in RAW.items():
  raw=io_path(root/path).read_bytes()
  if len(raw)!=length or digest(raw)!=pinned:raise ValueError('Whitefield retained primary HTML differs '+path)
 raw=io_path(context['edition'].path).read_bytes()
 if digest(raw)!=MASTER_SHA:raise ValueError('Whitefield accepted master drift')
 check_lxml(etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True)))
 return True
'''
 profile=profile.replace('FULL_SIGNATURE_PLACEHOLDER',repr(sha(json.dumps(signature(root),ensure_ascii=False,separators=(',',':')).encode()))).replace('GRAPHICS_PLACEHOLDER',repr(graphics))
 OUT.mkdir(parents=True);leaf=OUT/'tyerman_whitefield_source_profile.py';leaf.write_text(profile,encoding='utf-8')
 packet={}
 for role,relative in [('native_content','ocd_kernel/projection/native_content.py'),('native_content_check','ocd_kernel/projection/native_content_check.py'),('native_documents','ocd_kernel/projection/categories/native_documents.py'),('prose','ocd_kernel/projection/categories/prose.py')]:
  baseline=(ROOT/relative).read_text(encoding='utf-8');text=baseline
  if role in ['native_content','native_content_check']:
   text=replace(text,"GUYON_PROFILE = 'ocd-prose-guyon-pg24989-v16-source-native-v1'", "GUYON_PROFILE = 'ocd-prose-guyon-pg24989-v16-source-native-v1'\nfrom ocd_kernel.projection.categories import tyerman_whitefield_source_profile as whitefield_source\nWHITEFIELD_PROFILE = whitefield_source.PROFILE")
   text=replace(text,'GUYON_PROFILE):','GUYON_PROFILE, WHITEFIELD_PROFILE):')
   text=replace(text,"and node.get('unit') != 'source-horizontal-rule'","and node.get('unit') != 'source-horizontal-rule' and not (source_profile == WHITEFIELD_PROFILE and node.get('unit') == 'source-hr')")
   text=replace(text,"else 'horizontal-rule' if node.get('unit') == 'source-horizontal-rule'","else 'horizontal-rule' if node.get('unit') == 'source-horizontal-rule' or source_profile == WHITEFIELD_PROFILE and node.get('unit') == 'source-hr'",count=1 if role=='native_content' else 2)
   text=replace(text,'source_profile not in (None, ELMSLIE_CHOICE_PROFILE)','source_profile not in (None, ELMSLIE_CHOICE_PROFILE, WHITEFIELD_PROFILE)')
   text=replace(text,'source_profile in (None, ELMSLIE_CHOICE_PROFILE)','source_profile in (None, ELMSLIE_CHOICE_PROFILE, WHITEFIELD_PROFILE)')
   if role=='native_content':
    text=replace(text,"if tag == 'choice':\n", "if tag == 'choice':\n            if source_profile == WHITEFIELD_PROFILE:\n                whitefield_source.choice_et(node)\n")
    text=replace(text,'WHITEFIELD_PROFILE) or node.attrib','WHITEFIELD_PROFILE) or (node.attrib and source_profile != WHITEFIELD_PROFILE)')
    text=replace(text,'attributes = {}\n','attributes = {}\n        whitefield_graphic = whitefield_source.graphic_et(node) if source_profile == WHITEFIELD_PROFILE and tag == \'graphic\' else None\n        if whitefield_graphic and whitefield_graphic[1]:\n            attributes[\'css_style\'] = whitefield_graphic[1]\n')
    text=replace(text,"name = 'xml:' + key[len(XML):] if key.startswith(XML) else key\n", "name = 'xml:' + key[len(XML):] if key.startswith(XML) else key\n            if source_profile == WHITEFIELD_PROFILE and name == 'ana':\n                whitefield_source.annotation(value)\n                continue  # Exact literal remains private source inventory, not public administration.\n            if source_profile == WHITEFIELD_PROFILE and tag == 'choice' and name == 'xml:id':\n                attributes['source_anchor'] = whitefield_source.anchor(value)\n                continue\n            if source_profile == WHITEFIELD_PROFILE and tag == 'ref' and name == 'target' and value.startswith('#') and value[1:] in whitefield_source.ANCHORS:\n                attributes['source_target'] = '#'+whitefield_source.anchor(value[1:])\n                continue\n            if whitefield_graphic and name in {'url', 'width', 'height', 'style'}:\n                if name == 'url':attributes['source_target'] = whitefield_graphic[0]\n                continue\n")
   else:
    text=replace(text,"if name.localname == 'choice':\n", "if name.localname == 'choice':\n            if source_profile == WHITEFIELD_PROFILE:\n                whitefield_source.choice_lxml(node)\n")
    text=replace(text,'WHITEFIELD_PROFILE) or dict(node.attrib)','WHITEFIELD_PROFILE) or (dict(node.attrib) and source_profile != WHITEFIELD_PROFILE)')
    text=replace(text,"properties = {}\n", "properties = {}\n        whitefield_graphic = whitefield_source.graphic_lxml(node) if source_profile == WHITEFIELD_PROFILE and name.localname == 'graphic' else None\n        if whitefield_graphic and whitefield_graphic[1]:\n            properties['css_style'] = whitefield_graphic[1]\n")
    text=replace(text,"spelling = 'xml:' + key.localname if key.namespace == XML else attribute\n", "spelling = 'xml:' + key.localname if key.namespace == XML else attribute\n            if source_profile == WHITEFIELD_PROFILE and spelling == 'ana':\n                whitefield_source.annotation(value)\n                continue  # Literal remains in independent private inventory.\n            if source_profile == WHITEFIELD_PROFILE and name.localname == 'choice' and spelling == 'xml:id':\n                properties['source_anchor'] = whitefield_source.anchor(value)\n                continue\n            if source_profile == WHITEFIELD_PROFILE and name.localname == 'ref' and spelling == 'target' and value.startswith('#') and value[1:] in whitefield_source.ANCHORS:\n                properties['source_target'] = '#'+whitefield_source.anchor(value[1:])\n                continue\n            if whitefield_graphic and spelling in {'url', 'width', 'height', 'style'}:\n                if spelling == 'url':properties['source_target'] = whitefield_graphic[0]\n                continue\n")
  elif role=='native_documents':
   text=replace(text,'from ocd_kernel.projection.categories import commentary_group_policy, guyon_source_profile','from ocd_kernel.projection.categories import commentary_group_policy, guyon_source_profile, tyerman_whitefield_source_profile as whitefield_source')
   text=replace(text,"\n    virgin_mary_note = _virgin_mary_note_route(identity, raw, category=category,", "\n    whitefield = whitefield_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)\n    if whitefield:whitefield_source.check_et(root)\n    virgin_mary_note = _virgin_mary_note_route(identity, raw, category=category,")
   text=replace(text,"\n        virgin_mary_note = _virgin_mary_note_route(identity, raw, category=category,", "\n        whitefield = whitefield_source.route(identity, raw, language=language, category=category, collection=collection, projection_profile=projection_profile, allow_acceptance_metadata=_allow_acceptance_metadata, source_base=source_base)\n        if whitefield:whitefield_source.check_lxml(doc)\n        virgin_mary_note = _virgin_mary_note_route(identity, raw, category=category,")
   text=replace(text,'\n        elif wilberforce_group or carey:',"\n        elif whitefield:\n            outer=text;group=outer[0];source_texts=list(group)\n            envelopes.extend([(outer,set()),(group,set())])\n        elif wilberforce_group or carey:")
   text=replace(text,'\n        elif wilberforce_group or carey:',"elif wilberforce_group or carey:",count=2) if False else text
   # Checker uses a different source variable; its branch has one extra indentation level.
   text=replace(text,'\n            elif wilberforce_group or carey:',"\n            elif whitefield:\n                outer=source_text;group=outer[0];source_texts=list(group)\n                envelopes.extend([(outer,set()),(group,set())])\n            elif wilberforce_group or carey:")
   text=replace(text,"\n            text_allowed = {XML+'id', XML+'lang'}", "\n            text_allowed = ({XML+'id', XML+'lang', XML+'base','ana','n'} if whitefield else {XML+'id', XML+'lang'})")
   text=replace(text,"\n                text_allowed = {XML+'id', XML+'lang'}", "\n                text_allowed = ({XML+'id', XML+'lang', XML+'base','ana','n'} if whitefield else {XML+'id', XML+'lang'})")
   text=replace(text,'def _prose_references(unit, book_codes):','def _prose_references(unit, book_codes, source_profile=None):')
   text=replace(text,'native_content.project_content(node)), **','native_content.project_content(node,source_profile=source_profile)), **')
   text=replace(text,'def _observe_prose_references(unit, book_codes):','def _observe_prose_references(unit, book_codes, source_profile=None):')
   text=replace(text,'observe_content(etree.tostring(node, with_tail=False))[1], **','observe_content(etree.tostring(node, with_tail=False),source_profile=source_profile)[1], **')
   text=replace(text,'_prose_references(unit, book_codes)','_prose_references(unit, book_codes, whitefield_source.PROFILE if whitefield else None)')
   text=replace(text,'_observe_prose_references(source, book_codes)','_observe_prose_references(source, book_codes, whitefield_source.PROFILE if whitefield else None)')
   text=replace(text,'if header and node not in source_projection_nodes and node not in guyon_header_nodes:', 'if header and not whitefield and node not in source_projection_nodes and node not in guyon_header_nodes:',count=2)
   text=replace(text,'source_profile=MTP_PROFILE if mtp else','source_profile=whitefield_source.PROFILE if whitefield else MTP_PROFILE if mtp else',count=2)
   text=replace(text,"f'/TEI/text/group/text[{volume}]' if group_profile is not None else", "f'/TEI/text/group/text[{volume}]' if whitefield or group_profile is not None else",count=2)
   text=replace(text,'if corpus or group_profile is not None:', 'if corpus or whitefield or group_profile is not None:',count=2)
   text=replace(text,"'mapping_version': MTP_PROFILE if mtp else", "'mapping_version': whitefield_source.PROFILE if whitefield else MTP_PROFILE if mtp else",count=2)
  else:
   text=replace(text,"\n    guyon_profile = _guyon_accepted_profile(root, context)", "\n    from ocd_kernel.projection.categories import tyerman_whitefield_source_profile as whitefield_source\n    if whitefield_source.select(root,context,_accepted_projection_profile(root,context)):\n        from ocd_kernel.projection.categories.native_documents import project_accepted_document\n        return project_accepted_document(root,acceptance_path=acceptance_path,category='prose')\n    guyon_profile = _guyon_accepted_profile(root, context)")
   text=replace(text,"\n        guyon_profile = _guyon_accepted_profile(root, context)", "\n        from ocd_kernel.projection.categories import tyerman_whitefield_source_profile as whitefield_source\n        if whitefield_source.select(root,context,_accepted_projection_profile(root,context)):\n            from ocd_kernel.projection.categories.native_documents import verify_accepted_document\n            return verify_accepted_document(root,acceptance_path=acceptance_path,rows=rows,receipt=receipt,category='prose')\n        guyon_profile = _guyon_accepted_profile(root, context)")
  destination=OUT/(role+'_candidate.py');destination.write_text(text,encoding='utf-8')
  diff=''.join(difflib.unified_diff(baseline.splitlines(True),text.splitlines(True),fromfile=relative,tofile=relative));(OUT/(role+'.diff')).write_text(diff,encoding='utf-8')
  packet[role]=dict(canonical_path=relative,baseline_sha256=sha((ROOT/relative).read_bytes()),candidate=destination.relative_to(ROOT).as_posix(),candidate_sha256=sha(destination.read_bytes()),bounded_diff=(OUT/(role+'.diff')).relative_to(ROOT).as_posix(),diff_sha256=sha(diff.encode()))
 (OUT/'packet.json').write_bytes(enc(dict(status='isolated unexecuted proposal',master_sha256=sha(raw),source_candidate_sha256='fd2e1d4b5b51bb16175f269093b97686cede9d54b45c4549181271acdcb1b8a9',leaf=dict(path=leaf.relative_to(ROOT).as_posix(),sha256=sha(leaf.read_bytes()),proposed_target='ocd_kernel/projection/categories/tyerman_whitefield_source_profile.py'),files=packet,schema_unchanged_sha256=sha((ROOT/'schemas/v2/native-content.schema.json').read_bytes()),qualification='No canonical reader, source, package, schema, stage or installation writes. Full actual root/header/text fields bound independently via ElementTree and lxml. Public image aliases preserve occurrence order; literal graphics/annotations/header administration remain private inventory. Derived dimension declarations precede retained inline style. Actual accepted validation remains a later gate.')))
 print(json.dumps({'packet':str(OUT/'packet.json'),'sha256':sha((OUT/'packet.json').read_bytes())}))
if __name__=='__main__':propose()
