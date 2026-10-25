"""One Stokes Acts work, preserving two installed complete volume envelopes."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage,reconstruct
from ocd_kernel.tei.writer import tei_el

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--g-t-stokes'
MEMBERS=('stokes-expositoracts1','stokes-expositoracts2')
TITLE="The Expositor's Bible: The Acts of the Apostles"
STATUS='Nonaccepted complete authored Acts commentary containing both already acquired Stokes volumes in source order. Legacy accepted volumes remain unchanged. Human review, print collation, rights and publication remain separate.'
SOURCE=Path('sources/commentaries/expositors-bible/stokes-acts-complete-20261003-v2')
LOG=Path('reports/_logs/stokes-acts-complete-20261003-v2')

def canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf8')
def sha(raw):return sha256(raw).hexdigest()
def parser():return etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_comments=False,remove_pis=False,huge_tree=True)

def metadata(raw,legacy_header):
 source=etree.fromstring(raw,parser());head=source.find('ThML.head');notes=[]
 notes.append(dict(type='source-document-prefix',n='1',text=raw[:raw.index(b'<ThML')].decode('utf8')))
 notes.append(dict(type='source-document-root',n='1',text=json.dumps(dict(tag=source.tag,attributes=dict(source.attrib),text=source.text,tail=source.tail),ensure_ascii=False,sort_keys=True)))
 for ordinal,node in enumerate(head.iter(),1):
  value=dict(xpath=source.getroottree().getpath(node),kind='element' if isinstance(node.tag,str) else 'comment' if node.tag is etree.Comment else 'pi',tag=node.tag if isinstance(node.tag,str) else None,attributes=dict(node.attrib),text=node.text,tail=node.tail)
  notes.append(dict(type='complete-source-head-field',n=str(ordinal),text=json.dumps(value,ensure_ascii=False,sort_keys=True)))
 notes.append(dict(type='legacy-installed-volume-header',n='1',text=etree.tostring(legacy_header,encoding='unicode')))
 return notes

def convert(source):
 source.verify();profile=json.loads(source.authority_path('complete-profile').read_bytes())
 if profile['ordered_members']!=list(MEMBERS) or profile['complete_works']!=1:raise ValueError('Stokes complete work/member boundary differs')
 root=tei_el('TEI',{'xml:id':'stokes-acts-complete-work'});header=tei_el('teiHeader');fd=tei_el('fileDesc');ts=tei_el('titleStmt');ts.append(tei_el('title',text=TITLE))
 roots=[];packages=[];sources=[];acquisitions=[]
 for member in MEMBERS:
  package=CandidatePackage.load(source.authority_path(member+'-manifest').parent);package.verify_integrity();packages.append(package)
  legacy=etree.fromstring(source.authority_path(member+'-master').read_bytes(),parser());roots.append(legacy)
  raw=source.authority_path(member+'-raw').read_bytes();sources.append(raw)
  acquisition=json.loads(source.authority_path(member+'-acquisition').read_bytes());acquisitions.append(acquisition)
  candidate=etree.fromstring(package.member_bytes('content.tei.xml'),parser())
  if etree.tostring(legacy.find(NS+'text'),method='c14n')!=etree.tostring(candidate.find(NS+'text'),method='c14n'):raise ValueError('Installed Stokes native source text drifted from package')
 for role in ('author','editor'):
  values=[etree.fromstring(raw,parser()).findtext('.//DC.Creator[@sub="'+role.title()+'"][@scheme="short-form"]') for raw in sources]
  if not values[0] or len(set(values))!=1:raise ValueError('Common primary Stokes authorship differs')
  ts.append(tei_el(role,text=values[0]))
 fd.append(ts);pub=tei_el('publicationStmt');pub.append(tei_el('p',text=STATUS));fd.append(pub);desc=tei_el('sourceDesc');listing=tei_el('listBibl')
 outer=tei_el('bibl');outer.append(tei_el('note',{'type':'complete-work-boundary'},text=profile['boundary']));listing.append(outer)
 text=tei_el('text',{'xml:lang':'en'});group=tei_el('group',{'xml:id':'stokes-acts-source-volumes'});base_repairs=[]
 for member,legacy,package,raw,acq in zip(MEMBERS,roots,packages,sources,acquisitions,strict=True):
  src=etree.fromstring(raw,parser());bibl=tei_el('bibl',{'xml:id':member+'-source-records','type':'retained-source-volume'})
  bibl.append(tei_el('title',text=src.findtext('.//DC.Title')))
  for note in metadata(raw,legacy.find(NS+'teiHeader')):bibl.append(tei_el('note',{'type':note['type'],'n':note['n']},text=note['text']))
  listing.append(bibl);volume=deepcopy(legacy.find(NS+'text'))
  volume.set(XML+'id',member+'-volume');byid={n.get(XML+'id'):n for n in volume.iter() if n.get(XML+'id')};account=json.loads(package.member_bytes('source-accountability.json'))
  for feature in account['features']:
   href=feature['source_attributes'].get('href')
   if feature['source_tag']=='a' and href and not href.startswith('#') and not urlsplit(href).scheme:
    node=byid[feature['tei_id']]
    if node.tag!=NS+'ref' or node.get('target')!=href or node.get(XML+'base') is not None:raise ValueError('Unexpected legacy Stokes relative reference')
    node.set(XML+'base',acq['url']);base_repairs.append(dict(member_id=member,source_path=feature['source_path'],tei_id=feature['tei_id'],target=href,base=acq['url']))
  group.append(volume)
 desc.append(listing);fd.append(desc);header.append(fd);root.extend([header,text]);text.append(group)
 account=dict(contract='ocd-stokes-acts-complete-accounting-v1',complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),profile=profile,volume_accounting=[json.loads(p.member_bytes('source-accountability.json')) for p in packages],uri_base_repairs=base_repairs,
  grouping='Each entire legacy volume text occurs once, I then II, including its own front/body/back matter. Only synthetic volume XML ID and exact source-backed relative-link XML base are added. No chapter regrouping or cross-volume targets are invented.')
 provenance=dict(status='nonaccepted',work_id=WORK,complete_work=TITLE,profile=profile,converter=dict(source.record['converter']),source_manifest_sha256=source.sha256,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
 return {'content.tei.xml':etree.tostring(root,encoding='UTF-8',xml_declaration=True),'source-accountability.json':canonical(account),'provenance.json':canonical(provenance),'README.source.md':source.authority_path('complete-readme').read_bytes(),'unresolved.jsonl':canonical(dict(id='stokes-acts-complete-human-rights-print',status='unresolved',detail=STATUS))}

convert.converter_id='ocd-stokes-acts-complete-group';convert.converter_version='1';convert.implementation_path=Path(__file__).resolve()
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);p.add_argument('--source-manifest',type=Path,required=True);args=p.parse_args();print(reconstruct(SourceManifest.load(args.source_manifest,repository_root=ROOT),args.destination,convert).sha256)
