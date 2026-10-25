"""Reuse Anderson's existing complete TEI with reversible local scaffolds."""
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote
from lxml import etree
from build.tei import anderson_1864_new_testament as historical

NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
CONVERTER_ID='ocd-anderson-existing-native-current-v1';CONVERTER_VERSION='1'
ACCOUNT_LABEL='Generated source accounting (not an authored footnote): '

def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

def visible(n):
 return (n.text or '')+''.join((visible(c) if c.tag!=NS+'note' else '')+(c.tail or '') for c in n)

def adapt(original,header_xml):
 d=etree.fromstring(original);d.replace(d[0],etree.fromstring(header_xml));d.attrib.pop(XML+'lang');d.attrib.pop('ana')
 for n in list(d.find(NS+'text').iter()):
  if n.tag==NS+'ab':
   pointer=n.attrib.pop('corresp');n[0].set('n',ACCOUNT_LABEL+pointer)
   if n.get('type')!='verse':n.attrib.pop('n')
   else:n.set(XML+'space','preserve')
  elif n.tag==NS+'supplied':
   text=visible(n);n.tag=NS+'hi';n.attrib.clear();n.set('rend','source-supplied:source-marked')
   a=etree.SubElement(n,NS+'note',type='source-feature-annotation',n='Generated annotation: source-supplied span (not an authored footnote)');a.text='Source USFM \\add marks this exact span as supplied: '+text
  elif n.tag==NS+'term':
   key=n.get('key');n.tag=NS+'seg';n.attrib.clear();n.set('type','source-glossary-keyword'+(':'+quote(key,safe='') if key is not None else ''))
   a=etree.SubElement(n,NS+'note',type='source-feature-annotation',n='Generated annotation: source glossary keyword (not an authored footnote)');a.text='Source USFM \\w glossary key: '+(key if key is not None else '(no key supplied)')
 return etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)

def _convert(manifest):
 manifest.verify();profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes());baseline=manifest.authority_path('historical-native-baseline').read_bytes()
 # Fresh replay of the established producer only; this does not create a new textual witness.
 outputs=historical._build_candidate(manifest.repository_root)
 if outputs['content.tei.xml']!=baseline:raise ValueError('Existing historical complete-source TEI replay differs')
 current=adapt(baseline,profile['header_xml'].encode())
 return {'content.tei.xml':current,'source-accountability.json':manifest.authority_path('historical-accountability').read_bytes(),'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions']),'provenance.json':canonical(dict(work_id=profile['work_id'],scope=profile['scope'],source_manifest_sha256=manifest.sha256,historical_native_sha256=sha256(baseline).hexdigest(),scaffold_policy=profile['scaffold_policy'],status='nonaccepted'))}

_convert.converter_id=CONVERTER_ID;_convert.converter_version=CONVERTER_VERSION;_convert.implementation_path=Path(__file__).resolve()
