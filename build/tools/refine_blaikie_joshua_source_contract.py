"""Finish the Joshua-only source contract before any candidate is frozen."""
from pathlib import Path
from hashlib import sha256
import json

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/blaikie-joshua-existing-install-20261003-v1')

def main():
 preserved=ROOT/LOG/'aborted-initial-native-draft'
 if preserved.exists():raise FileExistsError('Preserve Joshua initial draft')
 preserved.mkdir()
 for name in ('blaikie_joshua_retained_native_prepare.py','blaikie_joshua_retained_native_oracle.py','blaikie_joshua_retained_native_emitter.py','blaikie_joshua_retained_scope.py'):
  (preserved/name).write_bytes((ROOT/'build/tei'/name).read_bytes())
 (preserved/'failure.json').write_text(json.dumps(dict(status='aborted-before-packaging',reason='Retained administrative comment/PI census differs',cause='Independent raw census has cite, not scripRef, as the third generated index class',source_bytes_changed=False,canonical_mutation=False),sort_keys=True,indent=2)+'\n',encoding='utf-8')
 emitter=ROOT/'build/tei/blaikie_joshua_retained_native_emitter.py'
 text=emitter.read_text(encoding='utf-8').replace('labels = ("scripCom", "scripRef", "foreign", "foreign", "pb")','labels = ("scripCom", "cite", "foreign", "foreign", "pb")')
 emitter.write_text(text,encoding='utf-8')
 scope=ROOT/'build/tei/blaikie_joshua_retained_scope.py';text=scope.read_text(encoding='utf-8').replace("Joshua's two complete authored works", "Joshua's one complete authored work");scope.write_text(text,encoding='utf-8')
 prepare=ROOT/'build/tei/blaikie_joshua_retained_native_prepare.py'
 text=prepare.read_text(encoding='utf-8')
 start=text.index('    readme=(');end=text.index("    return {'content.tei.xml'",start)
 readme="""    readme=(f'# Retained source: {title}\\n\\nSourced via CCEL.org.\\n\\n'
        f'Retained authority: {source_path}; SHA-256 {source_sha}; {len(raw)} bytes.\\n\\n'
        f'Primary source author: {author}. Series editor: {editor}.\\n\\n'
        f'Literal source printed-edition statement: {head.findtext(".//published")}.\\n\\n'
        f'Literal DC.Rights: {head.findtext(".//DC.Rights") or "[empty in retained source]"}. This source field is not rights clearance.\\n\\n'
        f'{legacy}\\n\\n{SCOPE}\\n\\n'
        'Chapter I is substantive authored introduction and remains in the body; only title page i is front, and index xxxv is back. All source readable content remains in original order. Source h1 through h6 preserve exact heading level as source-level paragraphs. Notes, verse lines, page numbers, lists, inline styles and every literal source attribute retain fields, order and attachment. The 22 administrative comments retain exact source fields/positions; their whitespace-only tails join adjacent actual TEI carriers reversibly.\\n\\n'
        'All 40 relative query links retain literal href readings and the exact primary acquired CCEL HTML URL as per-ref xml:base. Two absent source next/prev toc destinations remain explicit typed unresolved gaps; no destination is invented. The complete Joshua source contains no table or image elements and no historical text-correction proposals; no raw reading is replaced. Literal source header fields, CSS, XML declaration and stylesheet processing instructions remain visible and accounted.\\n\\n'
        'Bennett mapping and checker implementations were inspected and used as separately maintained ancestors; independence is not blind. The current checker independently derives all readable fields and hierarchy from stdlib raw XML, corroborates all raw fields with strict lxml, and inverses the whole raw body from the actual TEI. No browser/CSS visual equivalence or print collation is claimed.\\n\\n'
        '## Retained CCEL permission evidence\\n\\n'+(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_text(encoding='utf-8'))
    unresolved=canonical(dict(id=member_id+'-human-rights-print-assets',status='unresolved',detail=SCOPE))
    ids={n.get('id') for n in source.find('ThML.body').iter() if isinstance(n.tag,str) and n.get('id')}
    gaps=[dict(source_id=n.get('id'),attribute=k,target=n.get(k)) for n in source.find('ThML.body').iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) and n.get(k) not in ids]
    for ordinal,gap in enumerate(gaps,1):
        unresolved+=canonical(dict(id=member_id+'-missing-source-directive-'+str(ordinal),status='unresolved',kind='source-next-prev-gap',**gap))
"""
 text=text[:start]+readme+text[end:]
 import re
 text=re.sub(r"'unresolved.jsonl':canonical\(dict\(id=member_id\+'-[^']+',status='unresolved',detail=SCOPE\)\)","'unresolved.jsonl':unresolved",text)
 text=text.replace('Raw retained reading; cited witness not recovered, no historical correction adopted','No historical Joshua correction proposals; exact raw retained readings')
 prepare.write_text(text,encoding='utf-8')
 oracle=ROOT/'build/tei/blaikie_joshua_retained_native_oracle.py';text=oracle.read_text(encoding='utf-8').replace('quote, urlsplit','quote, urlsplit, urljoin')
 text=text.replace('Raw retained reading; cited witness not recovered, no historical correction adopted','No historical Joshua correction proposals; exact raw retained readings')
 start=text.index(' unresolved=');end=text.index('\n\n\n@lru_cache',start)
 independent_readme=readme[readme.index('    readme=('):readme.index('    unresolved=')]
 independent_readme=independent_readme.replace('source_path','\'raw/ccel/expositors-bible/\'+filename').replace('source_sha','pin').replace('{author}',"{next(n.text for n in primary_head.findall('.//DC.Creator') if n.get('sub')=='Author' and n.get('scheme')=='short-form')}").replace('{editor}',"{next(n.text for n in primary_head.findall('.//DC.Creator') if n.get('sub')=='Editor' and n.get('scheme')=='short-form')}").replace('{title}',"{primary_head.findtext('.//DC.Title')}").replace('head.findtext','primary_head.findtext').replace('{legacy}','{LEGACY}')
 independent_readme=independent_readme.replace('primary_primary_head','primary_head')
 independent_readme='\n'.join(line[3:] for line in independent_readme.splitlines())
 replacement=""" primary=_parse(raw);primary_head=primary.find('ThML.head');body=primary.find('ThML.body')
 unresolved=(json.dumps(dict(id=member+'-human-rights-print-assets',status='unresolved',detail=SCOPE),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\\n').encode()
 ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 gaps=[dict(source_id=n.get('id'),attribute=k,target=n.get(k)) for n in body.iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) and n.get(k) not in ids]
 for ordinal,gap in enumerate(gaps,1):
  unresolved+=(json.dumps(dict(id=member+'-missing-source-directive-'+str(ordinal),status='unresolved',kind='source-next-prev-gap',**gap),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\\n').encode()
 if (directory/'unresolved.jsonl').read_bytes()!=unresolved:raise ValueError('Exact source gaps and qualification differ')
"""+independent_readme+"\n if (directory/'README.source.md').read_bytes()!=readme.encode('utf-8'):raise ValueError('Exact visible current source credit, scope and permission differ')\n"
 text=text[:start]+replacement+text[end:]
 text=text.replace("if acquisition['url']!=source_base or acquisition['source_sha256']!=pin or acquisition['source_path']!='raw/ccel/expositors-bible/'+filename", "if acquisition['url']!=source_base or acquisition['source_sha256']!=pin or acquisition['source_path']!='raw/ccel/expositors-bible/'+filename or acquisition['source_bytes']!=len(raw) or len(acquisition['retained_files'])!=1 or acquisition['retained_files'][0]['sha256']!=pin or acquisition['retained_files'][0]['bytes']!=len(raw) or acquisition['retained_files'][0]['path']!='raw/ccel/expositors-bible/'+filename")
 text=text.replace(" # Secondary parser corroborates", " # Secondary parser corroborates")
 needle=" if native:raise ValueError('Actual commentary projection is a separate installation-stage probe')"
 extra=""" actual_relative=[]
 for source_path,out in source_to_tei.items():
  original=body
  for index in source_path:original=original[index]
  href=original.get('href') if original.tag=='a' else None
  if href and not href.startswith('#') and not urlsplit(href).scheme:
   if out.get('target')!=href or out.get(XML+'base')!=source_base or urljoin(source_base,href)!=urljoin(out.get(XML+'base'),out.get('target')):raise ValueError('Actual relative URI source context differs')
   actual_relative.append(dict(source_path=list(source_path),tei_id=out.get(XML+'id'),href=href,base=source_base,resolved=urljoin(source_base,href)))
 if len(actual_relative)!=40:raise ValueError('Complete Joshua relative link denominator differs')
 result['relative_uri_contexts']=actual_relative
 from build.tei.blaikie_joshua_legacy_oracle import reconcile
 result['qualified_original_scope']=reconcile()
"""
 assert needle in text;text=text.replace(needle,extra+needle)
 oracle.write_text(text,encoding='utf-8')
 print(json.dumps(dict(status='source-code-refined',pins={p.name:sha256(p.read_bytes()).hexdigest() for p in (prepare,oracle,emitter,scope)}),sort_keys=True))

if __name__=='__main__':main()
