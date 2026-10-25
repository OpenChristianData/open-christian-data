"""Account for Blaikie's one already acquired complete Joshua witness."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage

ROOT = Path(__file__).resolve().parents[2]
LOG = Path('reports/_logs/blaikie-joshua-existing-install-20261003-v1')
MEMBER = 'blaikie-expositorjosh'
WORK = 'expositors-bible--william-g-blaikie'
RAW = Path('raw/ccel/expositors-bible/blaikie_expositorjosh.xml')
PIN = '7a2be4c01ca4ed8ecf37aa6905a161c126ac8cc4752e00448126ae363d2139b3'
URL = 'https://www.ccel.org/ccel/blaikie/expositorjosh.html'
REPLAY = Path('reports/_logs/bennett-existing-install-20261003-v1/qualified-current-lib036-replay')
RECEIPT = REPLAY.parent/'qualified-current-lib036-replay-receipt.json'
PINS = {'manifest.json':'08ca804efd6b7ed9160f9d2b202c465e83d125e7bc26dc021904b3181de0ca03',
 'content.tei.xml':'d0535bfffe51dfcdd0eb31ecaba7da3b386fe641aa85b17ee4050e543aa79d1b',
 'source-accountability.json':'fd5e9c342283c827b5d8fce1c95e3713d755ac3b8048de19874bdc4b983f2257'}

def digest(raw): return sha256(raw).hexdigest()

def assess():
 raw=(ROOT/RAW).read_bytes()
 if len(raw)!=823168 or digest(raw)!=PIN: raise ValueError('Exact acquired Joshua witness differs')
 parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True))
 primary=ET.fromstring(raw,parser=parser)
 corroborating=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,remove_comments=False,remove_pis=False))
 fields=lambda root:[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text,n.tail,len(n)) for n in root.iter()]
 if fields(primary)!=fields(corroborating): raise ValueError('Two independent XML parser fields differ')
 head=primary.find('ThML.head');body=primary.find('ThML.body')
 form=WORK+'--'+MEMBER+'--retained-en';edition=WORK+'--'+MEMBER+'--ccel-electronic';acquisition=WORK+'--'+MEMBER+'--acquired'
 acq_path=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(acquisition+'.json')
 acq=json.loads((ROOT/acq_path).read_bytes())
 if (acq['source_path'],acq['source_sha256'],acq['source_bytes'],acq['url'])!=(RAW.as_posix(),PIN,len(raw),URL): raise ValueError('Joshua retained acquisition binding differs')
 if len(acq['retained_files'])!=1 or acq['retained_files'][0]['sha256']!=PIN or acq['retained_files'][0]['path']!=RAW.as_posix(): raise ValueError('Joshua acquired member set differs')
 elements=[n for n in primary.iter() if isinstance(n.tag,str)]
 if len(elements)!=2352: raise ValueError('Whole Joshua source census differs')
 title=head.findtext('.//DC.Title');title_page=''.join(body.find("div1[@id='i']").itertext())
 roots=[n for n in body if isinstance(n.tag,str)]
 if title!="The Expositor's Bible: The Book of Joshua" or 'THE BOOK OF JOSHUA' not in title_page or 'WILLIAM GARDEN BLAIKIE' not in title_page or len(roots)!=35 or roots[1].get('title')!='Chapter I. Introductory: The Book of Joshua.' or roots[-2].get('title')!="Chapter XXXIII. Joshua's Work for Israel." or roots[-1].get('title')!='Indexes': raise ValueError('Complete authored Joshua work boundary differs')
 ids=[n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')]
 if len(ids)!=len(set(ids)): raise ValueError('Duplicate raw source IDs')
 relative=[dict(position=i,id=n.get('id'),href=n.get('href'),source_base=URL) for i,n in enumerate(body.iter(),1) if n.tag=='a' and n.get('href') and not n.get('href').startswith('#') and not urlsplit(n.get('href')).scheme]
 missing=[dict(source_id=n.get('id'),attribute=k,target=n.get(k)) for n in body.iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) and n.get(k) not in ids]
 package=CandidatePackage.load(ROOT/REPLAY)
 for name,pin in PINS.items():
  if digest(package.member_bytes(name))!=pin: raise ValueError('Frozen qualified LIB036 replay differs')
 if digest((ROOT/RECEIPT).read_bytes())!='a7a06e42f01ce713b43364540485074efdfc6ca2c2480f6d681031e29ec6880f': raise ValueError('Qualified replay receipt differs')
 historical=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
 corrections=[r for r in historical['text_corrections'] if r['member_id']==MEMBER]
 return dict(status='source-preflight-pass',work_id=WORK,member_id=MEMBER,complete_authored_works=1,acquired_sources=1,
  source=dict(path=RAW.as_posix(),bytes=len(raw),sha256=PIN,whole_elements=len(elements),body_elements=sum(isinstance(n.tag,str) for n in body.iter()),body_comments=sum(n.tag is ET.Comment for n in body.iter()),body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str)))),
  acquisition=dict(path=acq_path.as_posix(),sha256=digest((ROOT/acq_path).read_bytes()),url=URL),
  primary_title=title,primary_title_page=title_page,primary_print_statement=head.findtext('.//published'),
  source_root_divisions=[dict(attributes=dict(n.attrib)) for n in roots],
  complete_work_boundary='One complete authored Book of Joshua: independent title/author/imprint, Chapters I through XXXIII including the authored introductory Chapter I, then generated indexes. The Expositors Bible is the series container; First and Second Samuel are separate assigned works and excluded.',
  region_policy=dict(front=['i'],body=[n.get('id') for n in roots[1:-1]],back=['xxxv']),
  shared_material='This witness title page, series/editor credit, stylesheet/header/prolog and all generated indexes belong to Joshua and remain in this reconstruction; no material is taken from Samuel.',
  relative_links=relative,missing_next_prev=missing,historical_correction_alternatives=corrections,
  parser_corroboration='All actual source fields, attributes, child counts, text/tail and order agree between stdlib ElementTree and lxml without recovery',
  qualified_replay=dict(package_path=REPLAY.as_posix(),package_sha256=package.sha256,members=[dict(name=name,sha256=digest(package.member_bytes(name)),bytes=len(package.member_bytes(name))) for name in package.member_names],receipt_path=RECEIPT.as_posix(),qualification='Current-authority converter-only aggregate replay; exact September11 package inaccessible and not recovered, not proven absent. No historical TEI byte equality or old oracle pass claimed. Actual Joshua graph reconciliation still pending.'),
  no_download=True,canonical_mutation=False)

if __name__=='__main__':
 target=ROOT/LOG/'source-inventory-read-only-preflight.json'
 if target.exists(): raise FileExistsError('Preserve Joshua source preflight')
 target.parent.mkdir(parents=True,exist_ok=True)
 result=assess();target.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(dict(status=result['status'],complete_authored_works=1,source=result['source'],relative_links=len(result['relative_links']),missing_next_prev=result['missing_next_prev'],proof_sha256=digest(target.read_bytes())),sort_keys=True))
