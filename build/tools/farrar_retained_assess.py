"""Assess the three acquired Farrar witnesses and exact existing LIB033 package."""
from pathlib import Path
from collections import Counter
from hashlib import sha256
from datetime import datetime,timezone
import json,sys,shutil
import xml.etree.ElementTree as ET
from lxml import etree

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from ocd_kernel.reconstruction.contract import CandidatePackage
LOG=ROOT/'reports/_logs/farrar-existing-install-20261003-v1'
OLD=ROOT/'reports/_logs/findlay-existing-install-20261003-v1/retained-final-package'
WORK=ROOT/'library/works/expositors-bible--frederic-w-farrar'
SOURCES={
 'farrar-expositor1kings':('farrar_expositor1kings.xml','b5bb6a2200528b3d3573aa373eaec2f7a827c1057b462c5d473eb231e812ca8d'),
 'farrar-expositor2kings':('farrar_expositor2kings.xml','1827452772153d95bb8f5c8c56782b4b038b51f335e6339b2ac8e241dc7267fa'),
 'farrar-expositordan':('farrar_expositordan.xml','6a851a9f4c0bf941745ce28b8a0c0da9b15f3a6568c089511b66d8bc10d1a67b')}
def sha(raw):return sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def kind(node):return node.tag if isinstance(node.tag,str) else '#comment' if node.tag in (ET.Comment,etree.Comment) else '#pi'
def main():
 LOG.mkdir(parents=True,exist_ok=True)
 old=CandidatePackage.load(OLD)
 assert old.sha256=='a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2'
 assert sha(old.member_bytes('content.tei.xml'))=='2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134'
 durable=LOG/'retained-final-package'
 if not durable.exists():shutil.copytree(OLD,durable)
 copied=CandidatePackage.load(durable)
 assert copied.sha256==old.sha256 and all(copied.member_bytes(n)==old.member_bytes(n) for n in old.member_names)
 oldtree=etree.fromstring(old.member_bytes('content.tei.xml'))
 account=json.loads(old.member_bytes('source-accountability.json'))
 before={p.relative_to(WORK).as_posix():sha(p.read_bytes()) for p in WORK.rglob('*') if p.is_file()}
 assert not any(p.endswith(('master.tei.xml','acceptance.json')) for p in before)
 members=[]
 for member,(filename,pin) in SOURCES.items():
  path=ROOT/'raw/ccel/expositors-bible'/filename;raw=path.read_bytes();assert sha(raw)==pin
  source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
  alternative=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False,remove_pis=False))
  standard=[(kind(n),dict(n.attrib),n.text,n.tail,len(n)) for n in source.iter()]
  libxml=[(kind(n),dict(n.attrib),n.text,n.tail,len(n)) for n in alternative.iter()]
  assert standard==libxml,'Independent strict XML parser source field discrepancy'
  body=source.find('ThML.body');head=source.find('ThML.head');assert body is not None and head is not None
  acquisitions=list(WORK.glob('forms/*/editions/*/acquisitions/*'+member+'--acquired.json'));assert len(acquisitions)==1
  acquisition=json.loads(acquisitions[0].read_bytes());assert acquisition['source_sha256']==pin and acquisition['source_path']==path.relative_to(ROOT).as_posix()
  original=oldtree.xpath('//*[@xml:id=$id]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'},id=member);assert len(original)==1
  source_ids=[n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id') is not None]
  hrefs=[dict(source_id=n.get('id'),href=n.get('href')) for n in body.iter() if isinstance(n.tag,str) and n.get('href') is not None]
  member_account=[r for r in account['crosswalk'] if r['member_id']==member]
  census=Counter(n.tag for n in body.iter() if isinstance(n.tag,str))
  regions=[dict(tag=n.tag,id=n.get('id'),title=n.get('title'),text_prefix=''.join(n.itertext())[:180]) for n in body if isinstance(n.tag,str)]
  row=dict(member_id=member,source_path=path.relative_to(ROOT).as_posix(),source_sha256=pin,source_bytes=len(raw),title=head.findtext('.//DC.Title'),author=head.findtext('.//DC.Creator[@sub="Author"][@scheme="short-form"]'),editor=head.findtext('.//DC.Creator[@sub="Editor"][@scheme="short-form"]'),elements=sum(isinstance(n.tag,str) for n in source.iter()),body_elements=sum(census.values()),body_tags=dict(census),comments=sum(kind(n)=='#comment' for n in body.iter()),body_pis=sum(kind(n)=='#pi' for n in body.iter()),prolog=raw[:raw.index(b'<ThML>')].decode(),root_attributes=dict(source.attrib),body_attributes=dict(body.attrib),head_fields=[dict(kind=kind(n),attributes=dict(n.attrib),text=n.text,tail=n.tail) for n in head.iter()],regions=regions,body_text_chars=len(''.join(body.itertext())),replacement_characters=raw.decode().count('\ufffd'),duplicate_source_ids=sorted(i for i,c in Counter(source_ids).items() if c>1),source_hrefs=hrefs,acquisition_path=acquisitions[0].relative_to(ROOT).as_posix(),acquisition_sha256=sha(acquisitions[0].read_bytes()),acquisition_url=acquisition['url'],original_member_c14n_sha256=sha(etree.tostring(original[0],method='c14n',with_comments=True)),original_member_tags=dict(Counter(etree.QName(n).localname for n in original[0].iter() if isinstance(n.tag,str))),original_crosswalk_records=len(member_account),strict_xml_parser_corroboration=True)
  members.append(row)
 report=dict(status='assessed',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,finite_denominator=3,source_bytes=sum(m['source_bytes'] for m in members),historical_package_sha256=old.sha256,historical_tei_sha256=sha(old.member_bytes('content.tei.xml')),historical_package_source=OLD.relative_to(ROOT).as_posix(),historical_package_durable_copy=durable.relative_to(ROOT).as_posix(),historical_package_members=[dict(name=n,bytes=len(copied.member_bytes(n)),sha256=sha(copied.member_bytes(n))) for n in copied.member_names],work_before=before,members=members,review_patterns=['RP-01','RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],prior_exposure='Source-to-TEI skill, frozen CCEL emitter, and Findlay producer/oracle read before assessment; no blind discovery claim.',claim='Exact historical package recovery and complete raw witness inventory only; readable Farrar native fidelity and installation remain pending.')
 (LOG/'existing-scope-assessment.json').write_bytes(encoded(report))
 print(json.dumps(dict(status=report['status'],members=[{k:m[k] for k in ('member_id','elements','body_elements','comments','source_bytes','original_member_tags','duplicate_source_ids')} for m in members],source_bytes=report['source_bytes']),sort_keys=True),flush=True)
if __name__=='__main__':main()
