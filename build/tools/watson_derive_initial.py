"""Create Watson-local derivatives from reviewed frozen Farrar implementations."""
from pathlib import Path
from hashlib import sha256
import re,json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
WORK='expositors-bible--r-a-watson'
MEMBERS={
 'watson-ra-expositor7':('watson_ra_expositor7.xml',('i','iii'),('vi','vii')),
 'watson-ra-expositorjob':('watson_ra_expositorjob.xml',('i',),('viii','ix')),
 'watson-ra-expositornum':('watson_ra_expositornum.xml',('i',),('xxviii','xxix'))}
PINS={};SOURCES={};SPECS={}
if __name__ == '__main__':
    for member,(filename,front,back) in MEMBERS.items():
     raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();source=ET.fromstring(raw);body=source.find('ThML.body');pin=sha256(raw).hexdigest();PINS[member]=pin
     count=len(list(source.iter()));SOURCES[member]=(filename,pin,front,back,count)
     SPECS[member]=dict(path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=len(list(body.iter())),form=WORK+'--'+member+'--retained-en',edition=WORK+'--'+member+'--ccel-electronic',acquisition=WORK+'--'+member+'--acquired')
OLDPIN='685517f52f9be603117e42c1afe9d6bf2d20a95145c855b7cbb5b37971042605'
TEIPIN='94c7f5a9b7c393dca2fd53e07d5f3a21f39c995cbe0266b776b6914d8c919f75'
LEGACY='All three existing Watson members derive from an explicitly qualified replay of the historical LIB035 producer. The replayed source-accountability bytes match the dated historical pin; replayed TEI bytes differ from the dated ticket pin. Every Watson source graph field, actual old carrier and original source reading is independently reconciled before readable hierarchy repair. The 46 prior Job correction proposals remain visible as qualified annotations, not replacements of the literal retained source readings. Their external witness readings are not independently confirmed from retained witness bytes.'
def read(p):return (ROOT/p).read_text(encoding='utf-8')
def save(p,value):
 path=ROOT/p
 if path.exists():raise FileExistsError('Preserve prior Watson artifact '+str(path))
 path.write_text(value,encoding='utf-8')
def common(s):
 return s.replace('frederic-w-farrar','r-a-watson').replace('Farrar','Watson').replace('farrar','watson').replace('a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2',OLDPIN).replace('2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134',TEIPIN)
if __name__ == '__main__':
    emitter=common(read('build/tei/farrar_retained_native_emitter.py'))
    emitter=re.sub(r'KNOWN_SOURCES = \{.*?\n\}', 'KNOWN_SOURCES = '+repr(PINS),emitter,flags=re.S)
    emitter=re.sub(r'    labels = .*?\n', '    labels = ("scripCom", "pb")\n',emitter)
    emitter=emitter.replace('text = tei_el("text", {"xml:lang": "en", "{http://www.w3.org/XML/1998/namespace}space": body.get("{http://www.w3.org/XML/1998/namespace}space")})','text_attrs = {"xml:lang": "en"}\n    if body.get("{http://www.w3.org/XML/1998/namespace}space") is not None:\n        text_attrs["{http://www.w3.org/XML/1998/namespace}space"] = body.get("{http://www.w3.org/XML/1998/namespace}space")\n    text = tei_el("text", text_attrs)')
    emitter=emitter.replace('if node.get("class") and tag in REND_TAGS:', 'if node.tag == "td" and node.get("align") is not None:\n            rend.append("source-align-" + node.get("align"))\n        if node.get("class") and tag in REND_TAGS:')
    save('build/tei/watson_retained_native_emitter.py',emitter)
    prepare=common(read('build/tei/farrar_retained_native_prepare.py'))
    prepare=re.sub(r'^MEMBERS = \{.*?^SPECS = \{\}.*?^\s*form=.*?\n', 'MEMBERS = '+repr(MEMBERS)+'\nSPECS = '+repr(SPECS)+'\n',prepare,flags=re.S|re.M)
    prepare=re.sub(r'^EMITTER_SHA = .*$', 'EMITTER_SHA = '+repr(sha256(emitter.encode()).hexdigest()),prepare,flags=re.M)
    prepare=prepare.replace("if base64.b64decode(old_account['retained_source_bytes'][member_id]['base64'],validate=True)!=raw:raise ValueError('Historical Watson source bytes do not match acquired witness')", "embedded=original.xpath('//*[@xml:id=$id]/tei:note[@type=\"exact-retained-source-bytes\"]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace','tei':'http://www.tei-c.org/ns/1.0'},id=member_id)\n    if len(embedded)!=1 or base64.b64decode(embedded[0].text,validate=True)!=raw:raise ValueError('Replayed embedded Watson source bytes do not match acquired witness')")
    prepare=re.sub(r"    legacy='.*?'\n", '    legacy='+repr(LEGACY)+"\n    historical_profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib035.reconstruction-profile.json').read_bytes())\n    correction_rows=[r for r in historical_profile['text_corrections'] if r['member_id']==member_id]\n    account['historical_text_corrections']=correction_rows\n    account['historical_correction_disposition']='Literal raw source readings preserved in native body; prior proposals retained visibly and in accounting, external witness readings unconfirmed.'\n",prepare)
    prepare=prepare.replace("    permission_path=Path(","    readme+='\\n## Prior correction proposals\\n\\nOriginal source readings are preserved in the native body. These inherited proposals are not independent confirmation of an external witness; external witness readings not independently confirmed.\\n\\n'+json.dumps(correction_rows,ensure_ascii=False,sort_keys=True,indent=2)+'\\n'\n    permission_path=Path(")
    prepare=prepare.replace('Eight source preformatted genealogical/chronological carriers across this three-member work retain their exact text, inline children and xml:space semantics as ab rend="source-preformatted".', 'Source stanza and line grouping, table summaries and cell alignment retain their exact native attributes. Judges and Ruth has no source xml:space declaration; Job and Numbers preserve the literal xml:space declaration.')
    prepare=prepare.replace('chronology notes, appendices, introductions, and indexes', 'Job Prologue, Numbers Introductory, chapters, and indexes')
    save('build/tei/watson_retained_native_prepare.py',prepare)
    oracle=common(read('build/tei/farrar_retained_native_oracle.py'))
    oracle=re.sub(r'^SOURCES=\{.*?^\}', 'SOURCES='+repr(SOURCES),oracle,flags=re.S|re.M)
    oracle=oracle.replace("expected_url='https://www.ccel.org/ccel/watson/'+member_id.removeprefix('watson-')+'.html'", "expected_url='https://www.ccel.org/ccel/watson_ra/'+member_id.removeprefix('watson-ra-')+'.html'")
    oracle=oracle.replace(" expected.set(XML+'space',body.get(XML+'space'))", " if body.get(XML+'space') is not None:expected.set(XML+'space',body.get(XML+'space'))")
    oracle=oracle.replace("  if node.get('class') and tag in rend_tags:", "  if node.tag=='td' and node.get('align') is not None:rend.append('source-align-'+node.get('align'))\n  if node.get('class') and tag in rend_tags:")
    oracle=re.sub(r" legacy='.*?'\n", ' legacy='+repr(LEGACY)+'\n',oracle)
    oracle=oracle.replace(" _p5_schema().assertValid(etree.parse(str(path)))", " historical_profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib035.reconstruction-profile.json').read_bytes())\n corrections=[r for r in historical_profile['text_corrections'] if r['member_id']==member_id]\n if account.get('historical_text_corrections')!=corrections or account.get('historical_correction_disposition')!='Literal raw source readings preserved in native body; prior proposals retained visibly and in accounting, external witness readings unconfirmed.':raise ValueError('Prior correction proposal source disposition differs')\n credit=(directory/'README.source.md').read_text(encoding='utf-8')\n if json.dumps(corrections,ensure_ascii=False,sort_keys=True,indent=2) not in credit or 'external witness readings not independently confirmed' not in credit:raise ValueError('Historical correction qualification not human visible')\n _p5_schema().assertValid(etree.parse(str(path)))")
    save('build/tei/watson_retained_native_oracle.py',oracle)
    assess=common(read('build/tools/farrar_retained_assess.py'))
    assess=assess.replace("OLD=ROOT/'reports/_logs/findlay-existing-install-20261003-v1/retained-final-package'", "OLD=ROOT/'reports/_logs/dods-existing-install-20261003-v1/replayed-lib035-package'")
    assess=re.sub(r'^SOURCES=\{.*?\}\n', 'SOURCES='+repr({m:(f,PINS[m]) for m,(f,_,_) in MEMBERS.items()})+'\n',assess,flags=re.S|re.M)
    assess=assess.replace('Exact historical package recovery and complete raw witness inventory only;', 'Explicitly qualified current replay of historical LIB035 producer, not historical TEI byte recovery; exact historical accounting and complete raw witness inventory only;')
    assess=assess.replace("report=dict(status='assessed'", "report=dict(historical_tei_bytes_exact=False,historical_accounting_bytes_exact=sha(old.member_bytes('source-accountability.json'))=='33f458376acb0f0fa8c8bf6514d3ae46d2ae2dc9e26a13a269cb28abe0cbfb82',legacy_replay_receipt=json.loads((OLD.parent/'legacy-replay-receipt.json').read_bytes()),status='assessed'")
    save('build/tools/watson_retained_assess.py',assess)
    print(json.dumps(dict(status='created',specs=SPECS)))
