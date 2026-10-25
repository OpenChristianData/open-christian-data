"""Create a bounded First Samuel derivative from frozen reviewed Dods recipes.

This is a work-local development recipe, not an acquisition or installation tool.
It preserves the qualified LIB036 replay as lineage and never edits its source.
"""
from pathlib import Path
from hashlib import sha256
import json
import re
import shutil
from collections import Counter
from urllib.parse import urlsplit
from lxml import etree

ROOT=Path.cwd().resolve(strict=True)
LOG=ROOT/'reports/_logs/blaikie-first-samuel-existing-install-20261003-v1'
SOURCE=ROOT/'sources/commentaries/expositors-bible/blaikie-first-samuel-existing-20261003-v1'
LOG.mkdir(parents=True,exist_ok=True);SOURCE.mkdir(parents=True,exist_ok=True)
MEMBER='blaikie-expositor8';WORK='expositors-bible--william-g-blaikie'
RAW=ROOT/'raw/ccel/expositors-bible/blaikie_expositor8.xml'
PIN='b46bd6cb856df0819dedc06b23a657f7763b49501248db63ce762585d67603d4'
if sha256(RAW.read_bytes()).hexdigest()!=PIN:raise ValueError('Selected acquired source pin differs')
raw=RAW.read_bytes();tree=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True));body=tree.find('ThML.body')
spec=dict(path='raw/ccel/expositors-bible/blaikie_expositor8.xml',sha256=PIN,bytes=len(raw),elements=sum(isinstance(n.tag,str) for n in tree.iter()),body_elements=sum(isinstance(n.tag,str) for n in body.iter()),comments=sum(n.tag is etree.Comment for n in body.iter()),form=WORK+'--'+MEMBER+'--retained-en',edition=WORK+'--'+MEMBER+'--ccel-electronic',acquisition=WORK+'--'+MEMBER+'--acquired')
uri_count=sum(n.tag=='a' and n.get('href') is not None and not n.get('href').startswith('#') and not urlsplit(n.get('href')).scheme for n in body.iter())
old=ROOT/'reports/_logs/bennett-existing-install-20261003-v1/qualified-current-lib036-replay'
dest=LOG/'qualified-current-lib036-replay';dest.mkdir(exist_ok=True)
expected={'content.tei.xml':'d0535bfffe51dfcdd0eb31ecaba7da3b386fe641aa85b17ee4050e543aa79d1b','source-accountability.json':'fd5e9c342283c827b5d8fce1c95e3713d755ac3b8048de19874bdc4b983f2257','README.source.md':'529a6131558abb5bb80689f048a4f664f7fa84c0c0e1ce7c1429918864325759','provenance.json':'3fdd8f5751e18f2a6f7d4f2fb81aae84d88933570e7fd6adeecb3306a78f90ce','unresolved.jsonl':'151157b270a5e48209f0610287d8fd2c654b11b80835cb07b2c6ae051bf5334d','manifest.json':'08ca804efd6b7ed9160f9d2b202c465e83d125e7bc26dc021904b3181de0ca03'}
for name,pin in expected.items():
 content=(old/name).read_bytes()
 if sha256(content).hexdigest()!=pin:raise ValueError('Frozen qualified replay member differs: '+name)
 (dest/name).write_bytes(content)
receipt=ROOT/'reports/_logs/bennett-existing-install-20261003-v1/qualified-current-lib036-replay-receipt.json'
if sha256(receipt.read_bytes()).hexdigest()!='a7a06e42f01ce713b43364540485074efdfc6ca2c2480f6d681031e29ec6880f':raise ValueError('Frozen replay qualification differs')
(LOG/'legacy-replay-receipt.json').write_bytes(receipt.read_bytes())
inventory=dict(work_id=WORK,selected_complete_work=MEMBER,source=spec,primary_title='THE FIRST BOOK OF SAMUEL.',primary_imprint='TORONTO: WILLARD TRACT DEPOSITORY AND BIBLE DEPOT, 1888.',scope='One complete separately titled First Samuel commentary; Second Samuel and Joshua excluded.',root_titles=[dict(n.attrib) for n in body if isinstance(n.tag,str)],body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),relative_uri_count=uri_count,acquisition_url='https://www.ccel.org/ccel/blaikie/expositor8.html')
(LOG/'source-inventory-read-only-preflight.json').write_text(json.dumps(inventory,sort_keys=True,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

# Derive the independent flat-graph reconciler; its selected raw expectations
# come from stdlib XML, not either reconstruction implementation.
s=(ROOT/'reports/_logs/dods-existing-install-20261003-v1/reconcile_legacy.py').read_text(encoding='utf-8')
s=s.replace('Dods-only','First Samuel only').replace('dods-existing-install-20261003-v1','blaikie-first-samuel-existing-install-20261003-v1').replace('replayed-lib035-package','qualified-current-lib036-replay').replace('expositors-bible--marcus-dods',WORK).replace('lib035','lib036')
s=s.replace("'33f458376acb0f0fa8c8bf6514d3ae46d2ae2dc9e26a13a269cb28abe0cbfb82'","'fd5e9c342283c827b5d8fce1c95e3713d755ac3b8048de19874bdc4b983f2257'")
s=re.sub(r"if members is None or \[n.get\(XML\+'id'\) for n in members\]!=\[.*?\]:raise ValueError\('Historical Dods three-member graph scope differs'\)","if members is None or not any(n.get(XML+'id')=='blaikie-expositor8' for n in members):raise ValueError('Selected existing First Samuel graph absent')",s)
s=s.replace('for division in members:',"for division in [n for n in members if n.get(XML+'id')=='blaikie-expositor8']:")
s=s.replace("r['member_id'].startswith('dods-')","r['member_id']=='blaikie-expositor8'")
s=s.replace("historical_accounting_bytes_exact=True,historical_tei_bytes_exact=False","historical_accounting_bytes_exact=False,historical_tei_bytes_exact=False")
s=s.replace("new_current_companion='dods-expositorjohn2 already acquired; outside this three-member historical cohort; complete under current four-acquisition authority'","historical_qualification='Current-authority converter replay; inaccessible September11 package was not recovered; historic TEI/accounting equality and historic oracle pass are not claimed'")
s=s.replace('historical_accounting_exact=True','historical_accounting_exact=False')
(LOG/'reconcile_legacy.py').write_text(s,encoding='utf-8')

scope='Complete retained CCEL electronic XML witness for the separately titled First Book of Samuel commentary, Toronto 1888. One complete authored work; Second Samuel and Joshua excluded; not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. This XML witness contains no image elements. Source layout is not a print or universal typography claim.'
legacy='The selected First Samuel member of a frozen qualified current-authority LIB036 converter replay is independently reconciled against its complete current raw source. The inaccessible September 11 package was not recovered, and historical TEI/accounting byte equality or historical oracle pass is not claimed. The historical profile has no First Samuel correction rows. All original raw readings remain in the readable body.'
prefix='blaikie_first_samuel'
for kind in ('emitter','prepare','oracle'):
 s=(ROOT/f'build/tei/dods_retained_native_{kind}.py').read_text(encoding='utf-8')
 s=s.replace('dods_retained_native',prefix+'_retained_native').replace('expositors-bible--marcus-dods',WORK).replace('dods-existing-install-20261003-v1','blaikie-first-samuel-existing-install-20261003-v1').replace('dods-retained-install-20261003-v1','blaikie-first-samuel-existing-20261003-v1').replace('replayed-lib035-package','qualified-current-lib036-replay').replace('lib035','lib036').replace('ccel-dods-retained-native-','ccel-blaikie-first-samuel-retained-native-').replace('ocd-dods-','ocd-blaikie-first-samuel-')
 s=s.replace("historical_accounting_pin_exact=True","historical_accounting_pin_exact=False").replace('acquired_work_units=4','acquired_work_units=1').replace("['acquired_work_member_count']!=4","['acquired_work_member_count']!=1")
 if kind=='emitter':
  s=re.sub(r'^KNOWN_SOURCES = .*$',"KNOWN_SOURCES = "+repr({MEMBER:PIN}),s,flags=re.M)
  s=re.sub(r'^    labels = .*$',"    labels = ('scripRef', 'scripCom', 'pb')",s,flags=re.M)
  s=s.replace('the four existing acquired Dods witnesses','the one existing acquired First Samuel witness')
  start=s.index('            elif any(child.tag == "div"')
  end=s.index('            else:',start)
  s=s[:start]+s[end:]
 elif kind=='prepare':
  s=re.sub(r'^MEMBERS = .*$',"MEMBERS = "+repr({MEMBER:('blaikie_expositor8.xml',('i',),('xl',))}),s,flags=re.M)
  s=re.sub(r'^SPECS = .*$',"SPECS = "+repr({MEMBER:spec}),s,flags=re.M)
  s=re.sub(r'SCOPE = \(.*?\)\n',"SCOPE = "+repr(scope)+'\n',s,count=1,flags=re.S)
  s=re.sub(r"    legacy=.*?\n",'    legacy='+repr(legacy)+'\n',s,count=1)
  s=s.replace("('legacy-replay-receipt.json','source-inventory.json','replay_legacy_lib035.py','reconcile_legacy.py')","('legacy-replay-receipt.json','source-inventory.json','reconcile_legacy.py')")
  s=s.replace("tei_el('TEI',{'xml:id':member_id})","tei_el('TEI',{'xml:id':member_id+'--candidate'})")
  s=s.replace("'build/tei/maclaren_retained_native_", "'build/tei/dods_retained_native_")
  s=s.replace("'These four XML sources contain no images. Source paragraph, list, note, verse, page, citation and emphasis roles retained; relative hrefs carry exact acquired-source per-ref xml:base, without changing literal targets; navigation next/prev resolves only known source IDs, missing source targets remain explicit annotations. Genesis retains its complete Project Gutenberg Information section. John I and John II retain distinct literal New York 1891 and London 1892 printed-edition statements, without asserting a single print edition. Literal source verse and index carriers remain unchanged. No invented stanza grouping or typographic equivalence is claimed.\\n'","'This First Samuel XML contains no images or tables. Source paragraph, note, page, scripture, anchor and emphasis roles remain readable; relative hrefs carry the exact acquired-source per-ref xml:base, without changing literal targets. Known navigation resolves only source IDs; missing source targets remain explicit annotations. Chapter XXIII retains its author note about paragraphs reproduced from David, King of Israel. The primary title page states Toronto 1888; electronic print metadata literally spells Williard, which remains unchanged. No typographic equivalence is claimed.\\n'")
  s=re.sub(r"    readme\+='\\nJohn II Greek index wrapper.*?\n",'',s)
 else:
  s=re.sub(r'^SOURCES=.*$',"SOURCES="+repr({MEMBER:('blaikie_expositor8.xml',PIN,('i',),('xl',),spec['elements'])}),s,flags=re.M)
  s=re.sub(r'SCOPE=\(.*?\)\n',"SCOPE="+repr(scope)+'\n',s,count=1,flags=re.S)
  s=re.sub(r'LEGACY=\(.*?\)\n',"LEGACY="+repr(legacy)+'\n',s,count=1,flags=re.S)
  s=s.replace("candidate.get(XML+'id')!=member_id or candidate.attrib!={XML+'id':member_id}","candidate.get(XML+'id')!=member_id+'--candidate' or candidate.attrib!={XML+'id':member_id+'--candidate'}")
  start=s.index("   elif any(c.tag=='div' and c.get('class')=='Index'")
  end=s.index('   else:',start);s=s[:start]+s[end:]
  s=re.sub(r"if len\(uri_rows\)!=\{.*?\}\[member_id\]",'if len(uri_rows)!='+str(uri_count),s)
  s=s.replace("('legacy-replay-receipt.json','source-inventory.json','replay_legacy_lib036.py','reconcile_legacy.py')","('legacy-replay-receipt.json','source-inventory.json','reconcile_legacy.py')")
  s=s.replace("'build/tei/maclaren_retained_native_", "'build/tei/dods_retained_native_")
  s=re.sub(r'index_container=\[dict\(source_path=\[28,2,1\].*?else \[\],lineage_bindings=lineage', 'index_container=[],lineage_bindings=lineage',s)
  s=s.replace('four Dods witnesses','one First Samuel witness').replace('Current four acquired work scope differs','Current one complete First Samuel scope differs')
 (ROOT/f'build/tei/{prefix}_retained_native_{kind}.py').write_text(s,encoding='utf-8')
emitter=ROOT/f'build/tei/{prefix}_retained_native_emitter.py'
prepare=ROOT/f'build/tei/{prefix}_retained_native_prepare.py'
s=prepare.read_text(encoding='utf-8');s=re.sub(r"^EMITTER_SHA = .*?$","EMITTER_SHA = "+repr(sha256(emitter.read_bytes()).hexdigest()),s,flags=re.M);prepare.write_text(s,encoding='utf-8')
print(json.dumps({'status':'draft-created','source':spec,'relative_uris':uri_count,'selected_work':MEMBER}))
