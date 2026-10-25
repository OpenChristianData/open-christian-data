"""Extract the two existing readable Findlay members without reconstructing them."""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage, reconstruct

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/findlay-existing-install-20261003-v1')
SOURCE_DIR=Path('sources/commentaries/expositors-bible/findlay-retained-install-20261003-v3')
OLD_PACKAGE=LOG/'retained-final-package'
WORK_ID='expositors-bible--g-g-findlay'
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
MEMBERS={
 'findlay-expositoreph':dict(file='findlay_expositoreph.xml',sha256='697b5713691c402b9d127296cf7d68c2e5aacae66fc6e8a052d6ac9206b3f771',bytes=1023989,elements=5744,body_elements=5644,comments=14),
 'findlay-expositorgal':dict(file='findlay_expositorgal.xml',sha256='9fcb5bc51a36d49f68a94d1852a57ffcefd8896d7e7f8ae7036aae1da4a8fc6d',bytes=1003429,elements=4504,body_elements=4435,comments=22)}
for member,spec in MEMBERS.items():
 spec.update(path='raw/ccel/expositors-bible/'+spec['file'],form=WORK_ID+'--'+member+'--retained-en',edition=WORK_ID+'--'+member+'--ccel-electronic',acquisition=WORK_ID+'--'+member+'--acquired')
SCOPE='Complete existing retained CCEL electronic epistle witness; two acquired editions in the existing author catalog record, not complete author or series. No new acquisition, editorial correction, human acceptance, print collation, rights clearance or publication. Existing source-layout and wrapper-topology limits remain explicit.'

def sha(raw):return sha256(raw).hexdigest()
def canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
def el(tag,attrs=None,text=None):
 node=etree.Element(NS+tag,attrs or {});node.text=text;return node

@lru_cache(maxsize=1)
def retained():
 old=CandidatePackage.load(ROOT/OLD_PACKAGE)
 if old.sha256!='a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2':raise ValueError('Findlay final retained package changed')
 tei=(old.path/'content.tei.xml').read_bytes();account=(old.path/'source-accountability.json').read_bytes()
 if sha(tei)!='2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134' or sha(account)!='3f5893aa82b9e9f564e3d1eeec64c69fcc56165b717104f3bb79a989f2c99644':raise ValueError('Findlay actual retained payload changed')
 return old.sha256,parse(tei),json.loads(account)

def convert(member):
 spec=MEMBERS[member];raw=(ROOT/spec['path']).read_bytes()
 if sha(raw)!=spec['sha256']:raise ValueError('Findlay source binding changed')
 old_sha,old_tree,old_account=retained()
 source=parse(raw);head=source.find('ThML.head');body=source.find('ThML.body')
 native=deepcopy(old_tree.xpath('//*[@xml:id="'+member+'"]')[0])
 original_c14n=etree.tostring(native,method='c14n',with_comments=True)
 summary_changes=[]
 source_elements=[n for n in source.iter() if isinstance(n.tag,str)]
 for ordinal,n in enumerate(source_elements,1):
  if n.tag=='table' and n.get('summary') is not None:
   identity=member+f'-feature-{ordinal:05d}';target=native.xpath('//*[@xml:id="'+identity+'"]')[0]
   if target.get('n') is not None:raise ValueError('Unexpected original table label')
   target.set('n',n.get('summary'));summary_changes.append(dict(tei_id=identity,attribute='n',before=None,after=n.get('summary'),source_xpath=source.getroottree().getpath(n)))
 acquisition_path=Path('library/works')/WORK_ID/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
 acquisition=json.loads((ROOT/acquisition_path).read_bytes())
 if acquisition['source_path']!=spec['path'] or acquisition['source_sha256']!=spec['sha256']:raise ValueError('Findlay source URI authority differs')
 bases=[]
 for ordinal,n in enumerate(source_elements,1):
  href=n.get('href')
  if href is not None and not href.startswith('#') and not urlsplit(href).scheme:
   identity=member+f'-feature-{ordinal:05d}';target=native.xpath('//*[@xml:id="'+identity+'"]')[0]
   if target.get(XML+'base') is not None or target.get('target')!=href:raise ValueError('Unexpected existing relative URI mapping')
   target.set(XML+'base',acquisition['url']);bases.append(dict(tei_id=identity,attribute=XML+'base',before=None,after=acquisition['url'],source_href=href,source_xpath=source.getroottree().getpath(n)))
 inverse=deepcopy(native)
 for row in summary_changes+bases:del inverse.xpath('//*[@xml:id="'+row['tei_id']+'"]')[0].attrib[row['attribute']]
 if etree.tostring(inverse,method='c14n',with_comments=True)!=original_c14n:raise ValueError('Bounded table summary inverse changed original native member')
 tei=etree.Element(NS+'TEI',{XML+'id':member+'--candidate'},nsmap={'ns0':NS[1:-1]})
 header=el('teiHeader');fd=el('fileDesc');ts=el('titleStmt')
 title=head.findtext('.//DC.Title');author=head.findtext('.//DC.Creator[@sub="Author"][@scheme="short-form"]');editor=head.findtext('.//DC.Creator[@sub="Editor"][@scheme="short-form"]')
 for tag,value in [('title',title),('author',author),('editor',editor)]:ts.append(el(tag,text=value))
 fd.append(ts);pub=el('publicationStmt');pub.append(el('p',text='Existing readable retained witness candidate. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'));fd.append(pub)
 desc=el('sourceDesc');bibl=el('bibl');bibl.append(el('note',{'type':'source-limitations'},SCOPE));records=[]
 for ordinal,n in enumerate(head.iter(),1):
  path=source.getroottree().getpath(n)
  row=dict(ordinal=ordinal,kind='element' if isinstance(n.tag,str) else 'comment',source_xpath=path,tag=n.tag if isinstance(n.tag,str) else '#comment',attributes=dict(n.attrib),text=n.text,tail=n.tail)
  if not isinstance(n.tag,str):value='Retained source head comment: '+(n.text or '')
  elif (n.text or '').strip() or n.attrib:value='Source field '+path+': '+json.dumps(dict(attributes=dict(n.attrib),text=n.text),ensure_ascii=False,sort_keys=True)
  else:value=None
  if value is not None:bibl.append(el('note',{'type':'retained-source-head-field','n':str(ordinal)},value));row['visible_note']=value
  records.append(row)
 prolog=[dict(node_kind='comment' if n.tag is etree.Comment else 'pi',target=n.target if n.tag is etree.PI else None,text=n.text,tail=n.tail) for n in reversed(list(source.itersiblings(preceding=True)))]
 for ordinal,row in enumerate(prolog,1):bibl.append(el('note',{'type':'retained-source-prolog','n':str(ordinal)},'Retained source prolog '+str(ordinal)+': '+json.dumps(row,ensure_ascii=False,sort_keys=True)))
 desc.append(bibl);fd.append(desc);header.append(fd);tei.append(header);text=el('text',{XML+'lang':'en'});container=el('body');container.append(native);text.append(container);tei.append(text)
 tei_bytes=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
 serialized_native=parse(tei_bytes).xpath('//*[@xml:id="'+member+'"]')[0]
 if etree.tostring(serialized_native,method='c14n',with_comments=True)!=etree.tostring(native,method='c14n',with_comments=True):raise ValueError('Serialized native namespace conservation failed')
 serialized_inverse=deepcopy(serialized_native)
 for row in summary_changes+bases:del serialized_inverse.xpath('//*[@xml:id="'+row['tei_id']+'"]')[0].attrib[row['attribute']]
 if etree.tostring(serialized_inverse,method='c14n',with_comments=True)!=original_c14n:raise ValueError('Serialized original native member inverse failed')
 comments=[];counter=0
 for n in body.iter():
  if not isinstance(n.tag,str):
   counter+=1;comments.append(dict(ordinal=counter,kind='comment' if n.tag is etree.Comment else 'pi',text=n.text,tail=n.tail,source_xpath=source.getroottree().getpath(n),anchor_id=member+f'-comment-{counter:05d}'))
 account=dict(contract='ocd-findlay-existing-readable-account-v1',work_id=WORK_ID,member_id=member,source_sha256=spec['sha256'],source_bytes=len(raw),source_path=spec['path'],source_root_attributes=dict(source.attrib),source_head_records=records,source_prolog=prolog,
  crosswalk=[r for r in old_account['crosswalk'] if r['member_id']==member],body_auxiliaries=comments,source_body_c14n_sha256=sha(etree.tostring(body,method='c14n',with_comments=True)),original_native_member_c14n_sha256=sha(original_c14n),summary_changes=summary_changes,relative_uri_bases=bases,source_uri_acquisition_path=acquisition_path.as_posix(),source_uri_acquisition_sha256=sha((ROOT/acquisition_path).read_bytes()),
  limitations=['Existing transparent compatibility wrappers do not assert exact wrapper topology','Source-title projection is declared limited, not universal typography','Presentation-only attributes retained in source accounting and visible original CSS; no pixel comparison','Human/print/rights/publication remain unassessed'])
 readme=(ROOT/'data/commentaries/expositors-bible/README.md').read_bytes()+('\n\n'+title+'\n\n'+SCOPE+'\n\nExact raw source: '+spec['path']+'; SHA-256 '+spec['sha256']+'.\n\nExisting final native member retained; only Ephesians table summary gains source-derived n="Contents", with exact inverse. All source comments retain exact payload/position in accounting and their original native digest anchors. Source replacement characters remain literal. Metadata and CSS remain human-visible in the TEI header; typography is not universally reproduced.\n').encode()
 readme+=('\nNonfragment relative source hrefs retain literal targets and receive per-ref xml:base from the exact retained acquisition URL: '+acquisition['url']+'. '+str(len(bases))+' bounded attributes; exact original-native inverse removes only those bases and the declared table summary. Bare local fragments remain remapped local links.\n').encode()
 return {'content.tei.xml':tei_bytes,'source-accountability.json':canonical(account),'README.source.md':readme,
  'provenance.json':canonical(dict(status='nonaccepted',work_id=WORK_ID,member_id=member,source_path=spec['path'],source_sha256=spec['sha256'],source_bytes=len(raw),scope=SCOPE,original_package_sha256=old_sha)),
  'unresolved.jsonl':canonical(dict(id=member+'-retained-source-quality',status='unresolved',detail=SCOPE))}

def _convert(manifest):
 manifest.verify();member=manifest.record['scope']['member_id'];result=convert(member)
 if result['README.source.md']!=manifest.authority_path('source-local-attribution-readme').read_bytes():raise ValueError('Findlay visible source credit differs')
 return result
_convert.converter_id='ocd-findlay-existing-readable-member-extraction';_convert.converter_version='1';_convert.implementation_path=Path(__file__).resolve()

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);p.add_argument('--source-manifest',type=Path,required=True);args=p.parse_args()
 print(reconstruct(SourceManifest.load(args.source_manifest,repository_root=ROOT),args.destination,_convert).sha256)
