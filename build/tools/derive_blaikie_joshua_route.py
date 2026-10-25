"""Create Joshua-local derivatives; preserve every reviewed ancestor byte."""
from pathlib import Path
from hashlib import sha256
import json,re

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/blaikie-joshua-existing-install-20261003-v1')
SOURCE=Path('sources/commentaries/expositors-bible/blaikie-joshua-retained-install-20261003-v1')
MEMBER='blaikie-expositorjosh'
WORK='expositors-bible--william-g-blaikie'
PIN='7a2be4c01ca4ed8ecf37aa6905a161c126ac8cc4752e00448126ae363d2139b3'
BASE='https://www.ccel.org/ccel/blaikie/expositorjosh.html'
SCOPE='Complete authored Book of Joshua from its one already acquired CCEL electronic witness: title page, all Chapters I through XXXIII including authored introduction, generated indexes, notes and verse. Samuel and author/series completeness are excluded. Human review, print collation, rights clearance and publication remain separate; no new acquisition.'
BOUNDARY='One complete authored Book of Joshua: independent title, author and imprint; Chapters I through XXXIII including authored introduction, then indexes. The Expositors Bible and inherited author catalog are containers; First and Second Samuel are separately assigned and excluded.'

def put(path,raw):
 p=ROOT/path
 if p.exists():raise FileExistsError('Preserve prior Joshua artifact '+str(path))
 p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)

def main():
 report=json.loads((ROOT/LOG/'source-inventory-read-only-preflight.json').read_bytes())
 if report['status']!='source-preflight-pass' or report['source']['sha256']!=PIN:raise ValueError('Joshua exact preflight required')
 old=Path(report['qualified_replay']['package_path'])
 for row in report['qualified_replay']['members']:
  raw=(ROOT/old/row['name']).read_bytes()
  if sha256(raw).hexdigest()!=row['sha256'] or len(raw)!=row['bytes']:raise ValueError('Frozen replay source drift')
  put(LOG/'qualified-current-lib036-replay'/row['name'],raw)
 receipt=ROOT/report['qualified_replay']['receipt_path'];put(LOG/'qualified-current-lib036-replay-receipt.json',receipt.read_bytes())
 put(SOURCE/'qualified-lib036-replay.source-manifest.json',(ROOT/'sources/commentaries/expositors-bible/bennett-retained-install-20261003-v1/qualified-lib036-replay.source-manifest.json').read_bytes())
 ancestor_paths=['build/tei/bennett_retained_scope.py','build/tei/bennett_retained_native_emitter.py','build/tei/bennett_retained_native_prepare.py','build/tei/bennett_retained_native_oracle.py','build/tools/prepare_bennett_retained_candidates.py','reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/reconcile_legacy.py']
 ancestors={}
 for path in ancestor_paths:
  raw=(ROOT/path).read_bytes();put(LOG/'reviewed-ancestors'/Path(path).name,raw);ancestors[path]=sha256(raw).hexdigest()
 put(LOG/'derivation-ancestors.json',(json.dumps(ancestors,sort_keys=True,indent=2)+'\n').encode())
 scope=(ROOT/ancestor_paths[0]).read_text(encoding='utf-8').replace('Bennett','Joshua').replace('bennett','blaikie_joshua')
 scope=scope.replace("WORK_ID='expositors-bible--w-h-blaikie_joshua'",f"WORK_ID='{WORK}'")
 scope=scope.replace('reports/_logs/blaikie_joshua-existing-install-20261003-v1',LOG.as_posix())
 spec=dict(volume=1,path='raw/ccel/expositors-bible/blaikie_expositorjosh.xml',sha256=PIN,bytes=823168,elements=2352,body_elements=2286,body_comments=22,tbody_wrappers=0,colgroup_wrappers=0,native_source_elements=2285,front=['i'],back=['xxxv'],source_base_url=BASE)
 scope=re.sub(r'MEMBERS=\{.*?\n\}',"MEMBERS={"+repr(MEMBER)+':'+repr(spec)+'\n}',scope,count=1,flags=re.S)
 scope=scope[:scope.index('def scope_report():')]
 # Producer uses only exact retained bytes/constants; actual legacy graph
 # reconciliation is performed by a separately derived stdlib checker.
 scope=scope[:scope.index('def reconcile(member):')]
 put(Path('build/tei/blaikie_joshua_retained_scope.py'),scope.encode())
 legacy=(ROOT/ancestor_paths[-1]).read_text(encoding='utf-8')
 legacy=legacy.replace('First Samuel','Joshua').replace('FirstSamuel','Joshua').replace('blaikie-first-samuel-existing-install-20261003-v1',LOG.name).replace('blaikie-expositor8',MEMBER)
 legacy=legacy[:legacy.index('preflight=json.loads')]
 legacy=legacy.replace("ROOT=Path.cwd().resolve(strict=True)","ROOT=Path(__file__).resolve().parents[2]")
 legacy=legacy.replace('Historical Dods correction','Historical Joshua correction')
 start=legacy.index("account=json.loads")
 imports=legacy[:start];body=legacy[start:]
 body='\n'.join(' '+line for line in body.splitlines())
 legacy=imports+'\ndef reconcile():\n'+body+'\n return dict(status="pass",work_id=WORK,legacy_members=results,legacy_correction_count=len(seen_corrections),qualification="Current-authority converter-only replay, inaccessible September11 package not recovered; no historical bytes or oracle pass claimed")\n'
 legacy+='\nif __name__=="__main__":\n result=reconcile();path=LOG/"retained-scope-reconciliation.json"\n if path.exists():raise FileExistsError("Preserve Joshua scope proof")\n path.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\\n",encoding="utf-8");print(json.dumps(result,sort_keys=True))\n'
 put(Path('build/tei/blaikie_joshua_legacy_oracle.py'),legacy.encode())
 emitter=(ROOT/ancestor_paths[1]).read_text(encoding='utf-8')
 emitter=emitter.replace('Bennett-only','Joshua-only').replace('Bennett witnesses','Joshua witness')
 emitter=re.sub(r'KNOWN_SOURCES = \{.*?\n\}',f'KNOWN_SOURCES = {{{MEMBER!r}:{PIN!r}}}',emitter,count=1,flags=re.S)
 emitter=re.sub(r'SOURCE_BASES=\{.*?\n\}',f'SOURCE_BASES={{{MEMBER!r}:{BASE!r}}}',emitter,count=1,flags=re.S)
 emitter=emitter.replace('labels = ("scripCom", "pb") if member_id == "bennett-expositorjer2" else ("scripRef", "foreign", "foreign", "pb")','labels = ("scripCom", "scripRef", "foreign", "foreign", "pb")')
 emitter=emitter.replace('the two existing retained','the one existing retained')
 # Joshua has no colgroup or Hebrew mixed wrapper; other-source exceptions
 # remain unreachable behind the exact one-source hash fence and are removed.
 emitter=re.sub(r'                if member_id == "bennett-expositor10".*?                    tag = "div"\n','',emitter,count=1,flags=re.S)
 a=emitter.index('        if node.tag == "colgroup":');b=emitter.index('        if node.tag == "th":',a)
 emitter=emitter[:a]+'        if node.tag == "colgroup":\n            raise ValueError("No Joshua column group exists")\n'+emitter[b:]
 emitter=emitter.replace('Bennett-only changes bind both raw witnesses, duplicate comment classes, source\nlanguages/attributes, the empty column group, and the Hebrew index wrapper.','Joshua-only changes bind its one exact raw witness, five generated index comment classes, original query URI context, and all original source attributes.')
 put(Path('build/tei/blaikie_joshua_retained_native_emitter.py'),emitter.encode())
 for filename in ('bennett_retained_native_prepare.py','bennett_retained_native_oracle.py'):
  text=(ROOT/'build/tei'/filename).read_text(encoding='utf-8').replace('bennett_retained','blaikie_joshua_retained').replace('ocd-bennett','ocd-blaikie-joshua').replace('ccel-bennett','ccel-blaikie-joshua').replace('bennett-retained-install-20261003-v1',SOURCE.name).replace('bennett-existing-install-20261003-v1',LOG.name).replace('expositors-bible--w-h-bennett',WORK)
  text=re.sub(r"SCOPE\s*=\s*\(.*?\)\n",'SCOPE = '+repr(SCOPE)+'\n',text,count=1,flags=re.S)
  text=text.replace('Unknown existing Bennett witness','Unknown existing Joshua witness')
  text=text.replace('Two distinct complete authored works: Bennett Jeremiah Chapters XXI-LII supplement to C.J. Ball, and Books of Chronicles; no whole biblical Jeremiah or series completeness claim',BOUNDARY)
  if filename.endswith('_oracle.py'):
   text=re.sub(r'SOURCES=\{.*?\n\}',f'SOURCES={{{MEMBER!r}:('+repr('blaikie_expositorjosh.xml')+','+repr(PIN)+",('i',),('xxxv',),2352)\n}",text,count=1,flags=re.S)
   text=text.replace("'https://www.ccel.org/ccel/bennett/'+('expositorjer2.html' if member.endswith('jer2') else 'expositor10.html')",repr(BASE)).replace("'https://www.ccel.org/ccel/bennett/'+('expositorjer2.html' if member_id.endswith('jer2') else 'expositor10.html')",repr(BASE))
   text=text.replace("volume=1 if member.endswith('jer2') else 2","volume=1").replace("profile['acquired_work_volumes']!=2","profile['acquired_work_volumes']!=1")
   text=re.sub(r"    if member_id=='bennett-expositor10'.*?\n",'',text)
   a=text.index("  if node.tag=='colgroup':");b=text.index("  if node.tag=='th':",a)
   text=text[:a]+"  if node.tag=='colgroup':raise ValueError('No Joshua column group exists')\n"+text[b:]
  put(Path('build/tei')/filename.replace('bennett_retained','blaikie_joshua_retained'),text.encode())
 print(json.dumps(dict(status='draft-derived',complete_authored_works=1,source_member=MEMBER,ancestor_pins=ancestors),sort_keys=True))

if __name__=='__main__':main()
