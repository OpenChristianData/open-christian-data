"""Exact two-volume Whitefield biography reader admission; no acceptance creation."""
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
FULL_FIELDS_SHA='cc19da89f27695aad41002bab2bb9f3a4fdd7d3ba75b467493a135c13873283e'
GRAPHICS={'v44280-img_images_frontispiece.jpg': {'attributes': {'corresp': 'urn:ocd:retained:pg44280:images/frontispiece.jpg', 'n': 'Whitefield', 'width': '450px', 'height': '473px', 'ana': 'urn:ocd:l635:source:%7B%22attributes%22%3A%7B%22alt%22%3A%22Whitefield%22%2C%22height%22%3A%22473%22%2C%22id%22%3A%22img_images_frontispiece.jpg%22%2C%22src%22%3A%22images%2Ffrontispiece.jpg%22%2C%22width%22%3A%22450%22%7D%2C%22tag%22%3A%22img%22%7D', '{http://www.w3.org/XML/1998/namespace}id': 'v44280-img_images_frontispiece.jpg'}, 'url_sha256': '45335e879c59f7fb562e6b62d9087785e58a6edff5f0b77c4617f43e2947d812', 'alias': 'retained-embedded-image:pg44280:images/frontispiece.jpg'}, 'v62023-img_images_coverpage.jpg': {'attributes': {'corresp': 'urn:ocd:retained:pg62023:images/coverpage.jpg', 'n': 'Book Cover', 'ana': 'urn:ocd:l635:source:%7B%22attributes%22%3A%7B%22alt%22%3A%22Book%20Cover%22%2C%22class%22%3A%22image_057%22%2C%22id%22%3A%22img_images_coverpage.jpg%22%2C%22src%22%3A%22images%2Fcoverpage.jpg%22%7D%2C%22tag%22%3A%22img%22%7D', '{http://www.w3.org/XML/1998/namespace}id': 'v62023-img_images_coverpage.jpg'}, 'url_sha256': '48bc22488f205ccd0be84856c70ad6038ae309ca3a2b87edf4a87c41728f6e31', 'alias': 'retained-embedded-image:pg62023:images/coverpage.jpg'}, 'v62023-img_images_i_frontis.jpg': {'attributes': {'corresp': 'urn:ocd:retained:pg62023:images/i_frontis.jpg', 'n': '', 'ana': 'urn:ocd:l635:source:%7B%22attributes%22%3A%7B%22alt%22%3A%22%22%2C%22class%22%3A%22image_095%22%2C%22id%22%3A%22img_images_i_frontis.jpg%22%2C%22src%22%3A%22images%2Fi_frontis.jpg%22%7D%2C%22tag%22%3A%22img%22%7D', '{http://www.w3.org/XML/1998/namespace}id': 'v62023-img_images_i_frontis.jpg'}, 'url_sha256': 'cf5debba827a9e7b2b0f6e89770d8b728c3806d3fe725d5dfec641a4f152d5e9', 'alias': 'retained-embedded-image:pg62023:images/i_frontis.jpg'}, 'v62023-img_images_brace_lt.png': {'attributes': {'corresp': 'urn:ocd:retained:pg62023:images/brace_lt.png', 'n': '', 'height': '2em', 'ana': 'urn:ocd:l635:source:%7B%22attributes%22%3A%7B%22alt%22%3A%22%22%2C%22class%22%3A%22inline%20vert_m%22%2C%22id%22%3A%22img_images_brace_lt.png%22%2C%22src%22%3A%22images%2Fbrace_lt.png%22%2C%22style%22%3A%22height%3A%202em%3B%22%7D%2C%22tag%22%3A%22img%22%7D', '{http://www.w3.org/XML/1998/namespace}id': 'v62023-img_images_brace_lt.png', 'style': 'height: 2em;'}, 'url_sha256': '4a028627d2fc284397d740fc8c41702260898ba51998ade05afaaa7e26f2ecb5', 'alias': 'retained-embedded-image:pg62023:images/brace_lt.png'}, 'v62023-img_images_brace_lt.png_1': {'attributes': {'corresp': 'urn:ocd:retained:pg62023:images/brace_lt.png', 'n': '', 'height': '2em', 'ana': 'urn:ocd:l635:source:%7B%22attributes%22%3A%7B%22alt%22%3A%22%22%2C%22class%22%3A%22inline%20vert_m%22%2C%22id%22%3A%22img_images_brace_lt.png_1%22%2C%22src%22%3A%22images%2Fbrace_lt.png%22%2C%22style%22%3A%22height%3A%202em%3B%22%7D%2C%22tag%22%3A%22img%22%7D', '{http://www.w3.org/XML/1998/namespace}id': 'v62023-img_images_brace_lt.png_1', 'style': 'height: 2em;'}, 'url_sha256': '4a028627d2fc284397d740fc8c41702260898ba51998ade05afaaa7e26f2ecb5', 'alias': 'retained-embedded-image:pg62023:images/brace_lt.png'}}
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
