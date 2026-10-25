"""Source-grounded complete authored-work boundary review for current Watson inputs."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'reports/_logs/watson-existing-install-20261003-v1'
FILES=('watson_ra_expositor7.xml','watson_ra_expositorjob.xml','watson_ra_expositornum.xml')
PINS=('9d235aa2fd1d93d33c3a1bb8ea462c28c30ea01f711cc44c091d337dd792ad47','9e8fab9fe169699cad7ab72c0cc5cc77732c6b1045379b3693d351b804180bc0','ea84347fe36b4380749c077dc41bf4a8431f0a7bf7157668579833bb72dc602f')
def review():
 rows=[]
 for filename,pin in zip(FILES,PINS,strict=True):
  raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();assert sha256(raw).hexdigest()==pin
  source=ET.fromstring(raw);body=source.find('ThML.body');title=''.join(body[0].itertext());member=filename.removesuffix('.xml').replace('watson_ra_','watson-ra-')
  assert body[0].get('id')=='i' and body[0].get('title')=='Title Page'
  rows.append(dict(member_id=member,source_sha256=pin,source_bytes=len(raw),head_title=source.findtext('.//DC.Title'),author=source.findtext('.//DC.Creator[@sub="Author"][@scheme="short-form"]'),title_page_selector='/ThML[1]/ThML.body[1]/div1[1]',exact_title_page_text=title,root_regions=[dict(selector='/ThML[1]/ThML.body[1]/div1['+str(i)+']',id=n.get('id'),title=n.get('title')) for i,n in enumerate(body,1)],classification='one-complete-authored-work'))
 assert 'JUDGES AND RUTH.' in rows[0]['exact_title_page_text']
 assert 'THE BOOK OF JOB.' in rows[1]['exact_title_page_text'] and 'AUTHOR OF "JUDGES AND RUTH,"' in rows[1]['exact_title_page_text']
 assert 'THE BOOK OF NUMBERS' in rows[2]['exact_title_page_text'] and '"JUDGES AND RUTH,"' in rows[2]['exact_title_page_text'] and '"THE BOOK OF JOB,"' in rows[2]['exact_title_page_text']
 combined=ET.fromstring((ROOT/'raw/ccel/expositors-bible'/FILES[0]).read_bytes()).find('ThML.body');contents=''.join(combined[1].itertext())
 assert combined[1].get('id')=='iii' and combined[1].get('title')=='Contents'
 assert 'THE BOOK OF JUDGES.' in contents and 'THE BOOK OF RUTH.' in contents and 'Index421' in contents
 assert 'PROBLEMS OF SETTLEMENT AND WAR3' in contents and 'THE MARRIAGE AT THE GATE408' in contents
 rows[0].update(contents_selector='/ThML[1]/ThML.body[1]/div1[2]',exact_contents_text=contents,part_ids=['iv','v'],part_titles=['The Book of Judges','The Book of Ruth'],shared_index_ids=['vi','vii'],boundary_basis='One combined authored printed title page, one contents sequence, continuous printed-page sequence from Judges page3 to Ruth page408 and shared Index421. Job and Numbers separately name Judges and Ruth as a prior authored title. Biblical book headings remain two parts of that authored work; they do not establish separate complete authored works here.')
 rows[1]['boundary_basis']='Separate Book of Job authored title page explicitly names Judges and Ruth as a prior authored title; Prologue and all colloquies are source parts of Job.'
 rows[2]['boundary_basis']='Separate Book of Numbers authored title page explicitly names Judges and Ruth and The Book of Job as prior authored titles; Introductory through chapterXXVI are source parts of Numbers.'
 report=dict(status='pass',source_work_count=3,acquired_source_count=3,complete_authored_work_count=3,container='Existing Watson author grouping within The Expositors Bible series; does not itself produce another TEI',outputs=rows,shared_material_disposition='Title/front matter, single contents where present, scholarly introduction/Prologue, notes and printed/generated indexes stay once within their owning complete authored work; no cross-work duplication or inherited series title extraction',limits='Electronic retained source boundary review, not print collation or author/series completeness. No source downloaded or source selection expanded.',prior_exposure='Source-to-TEI skill and independently assessed raw/old-ledger scope known before this explicit boundary review.')
 return report
if __name__=='__main__':
 (LOG/'complete-work-boundary-review.json').write_text(json.dumps(review(),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
 print('Watson: three source-grounded complete authored works')
