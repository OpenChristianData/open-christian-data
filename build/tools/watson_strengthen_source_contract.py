"""Bounded Watson metadata, work-boundary and source navigation refinement."""
from pathlib import Path
from hashlib import sha256
import json,re
ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/watson-existing-install-20261003-v1')
def sha(b):return sha256(b).hexdigest()
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def once(s,a,b):
 if s.count(a)!=1:raise ValueError('Expected unique Watson preimage '+a[:60])
 return s.replace(a,b,1)
def read(p):return (ROOT/p).read_text(encoding='utf-8')
def write(p,s):(ROOT/p).write_text(s,encoding='utf-8',newline='\n')
if __name__ == '__main__':
    inputs={
     'farrar-emitter-ancestor':('build/tei/farrar_retained_native_emitter.py','5510555027c985b8c36e7851e9b39814f4e4be56f0fb1dd42dcb82a3b8789c4c'),
     'historical-lib035-producer':('build/tei/expositors_bible_lib035_reconstruction.py','8bef418725cee3a8ca8dcea90c9f8c239739b33dba98e55ca2cd6984310b95c3'),
     'historical-profile':('sources/commentaries/expositors-bible/lib035.reconstruction-profile.json','3853db08494f46184368556bebdac41d1f65c17f51935da3d1d2d3f0b934b710'),
     'historical-manifest':('sources/commentaries/expositors-bible/lib035.source-manifest.json','0febdfc83e8301ce343b9246755d2a5ad1bb26b4bf2b1ba2c8a3de5030478003'),
     'qualified-replay-recipe':('reports/_logs/dods-existing-install-20261003-v1/replay_legacy_lib035.py','cb00bfeca2bbca91e99d864dfc59c2783a7f8023501d6b2d11a9874c2a686a19'),
     'qualified-replay-receipt':('reports/_logs/dods-existing-install-20261003-v1/legacy-replay-receipt.json','91117334bc096f6fbf85f3a69576ac7f222f773a8713b0abe9fa5eaca83384b0')}
    lineage=[];folder=ROOT/LOG/'retained-producer-lineage';folder.mkdir(exist_ok=True)
    for role,(relative,pin) in inputs.items():
     original=ROOT/relative;data=original.read_bytes()
     if sha(data)!=pin:raise ValueError('Frozen lineage input drift '+role)
     target=folder/original.name
     if target.exists():raise FileExistsError('Preserve prior durable Watson lineage '+str(target))
     target.write_bytes(data);lineage.append(dict(role=role,path=target.relative_to(ROOT).as_posix(),source_path=relative,bytes=len(data),sha256=pin))
    members=[dict(path=p.relative_to(ROOT).as_posix(),name=p.name,bytes=len(p.read_bytes()),sha256=sha(p.read_bytes())) for p in sorted((ROOT/LOG/'retained-final-package').iterdir()) if p.is_file()]
    record=dict(contract='ocd-watson-retained-producer-lineage-v1',original_package_sha256='685517f52f9be603117e42c1afe9d6bf2d20a95145c855b7cbb5b37971042605',original_package_members=members,inputs=lineage,historical_accounting_bytes_exact=True,historical_tei_bytes_exact=False,qualification='Qualified current historical producer replay; dated TEI hash is not recovered, historical accounting hash is exact. Historical oracle was not rerun and its current drift remains recorded. No witness acquisition or external correction reading confirmation.')
    lineage_path=LOG/'retained-producer-lineage.json';(ROOT/lineage_path).write_bytes(canonical(record));pin=sha((ROOT/lineage_path).read_bytes())
    emitter=read('build/tei/watson_retained_native_emitter.py')
    emitter=once(emitter,'        if re.fullmatch(r"h[1-6]", node.tag):', '''        navigation = []
        for key in ("next", "prev"):
            if node.get(key) is not None:
                if node.get(key) in id_set:
                    attrs[key] = "#" + member_id + "-" + node.get(key)
                else:
                    navigation.append("urn:ccel:source-" + key + ":" + quote(node.get(key), safe="-_."))
        if navigation:
            attrs["ana"] = " ".join(navigation)
        if re.fullmatch(r"h[1-6]", node.tag):''')
    write('build/tei/watson_retained_native_emitter.py',emitter)
    prepare=read('build/tei/watson_retained_native_prepare.py')
    prepare=re.sub(r'^EMITTER_SHA = .*$', 'EMITTER_SHA = '+repr(sha((ROOT/'build/tei/watson_retained_native_emitter.py').read_bytes())),prepare,flags=re.M)
    prepare=once(prepare,'    source_sha=sha256(raw).hexdigest()', '''    source_sha=sha256(raw).hexdigest()
    lineage_path=Path('reports/_logs/watson-existing-install-20261003-v1/retained-producer-lineage.json')
    lineage_raw=(ROOT/lineage_path).read_bytes()
    if sha(lineage_raw)!='LINEAGE_PIN':raise ValueError('Watson reviewed composite producer lineage drift')
    lineage=json.loads(lineage_raw)
    account['producer_lineage']=lineage
    source_ids={n.get('id') for n in source.find('ThML.body').iter() if isinstance(n.tag,str) and n.get('id')}
    navigation_gaps=[dict(source_xpath=source.getroottree().getpath(n),source_id=n.get('id'),attribute=k,value=n.get(k)) for n in source.find('ThML.body').iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) is not None and n.get(k) not in source_ids]
    account['source_navigation_gaps']=navigation_gaps'''.replace('LINEAGE_PIN',pin))
    prepare=prepare.replace("permission_sha256=sha(permission),emitter_sha256=EMITTER_SHA", "permission_sha256=sha(permission),producer_lineage=account['producer_lineage'],emitter_sha256=EMITTER_SHA")
    prepare=prepare.replace("            'README.source.md':readme.encode('utf-8'),", "            'README.source.md':readme.encode('utf-8')+b'\\n\\n## Exact retained permission record\\n\\n'+permission,")
    prepare=prepare.replace("detail=SCOPE))}", "detail=SCOPE,source_navigation_gaps=account['source_navigation_gaps'],broken_local_links=account['broken_local_links'],historical_correction_count=len(correction_rows)))}")
    prepare=once(prepare,"    permission_path=Path(", "    readme+='\\nKnown source next/prev targets remain native links. The two absent toc targets per work remain exact typed annotations and unresolved source gaps. No generated toc target is invented. Judges and Ruth is one authored complete volume with two book parts, one title/contents sequence and shared indexes. Job and Numbers have separate authored title pages and refer to these as prior works; each remains one complete work. Shared material occurs once inside its owning work.\\n'\n    permission_path=Path(")
    write('build/tei/watson_retained_native_prepare.py',prepare)
    oracle=read('build/tei/watson_retained_native_oracle.py')
    oracle=once(oracle,"  if re.fullmatch('h[1-6]',node.tag):", "  gaps=[]\n  for key in ('next','prev'):\n   if node.get(key) is not None:\n    if node.get(key) in source_ids:attrs[key]='#'+member_id+'-'+node.get(key)\n    else:gaps.append('urn:ccel:source-'+key+':'+quote(node.get(key),safe='-_.'))\n  if gaps:attrs['ana']=' '.join(gaps)\n  if re.fullmatch('h[1-6]',node.tag):")
    oracle=oracle.replace("permission_sha256=sha256(permission).hexdigest(),emitter_sha256=", "permission_sha256=sha256(permission).hexdigest(),producer_lineage=verified_lineage(),emitter_sha256=")
    oracle=oracle.replace("detail=SCOPE):raise ValueError('Exact unresolved", "detail=SCOPE,source_navigation_gaps=account['source_navigation_gaps'],broken_local_links=account['broken_local_links'],historical_correction_count=len(account['historical_text_corrections'])):raise ValueError('Exact unresolved")
    oracle=once(oracle," _p5_schema().assertValid(etree.parse(str(path)))", " expected_gaps=[dict(source_xpath=lsource.getroottree().getpath(n),source_id=n.get('id'),attribute=k,value=n.get(k)) for n in lsource.find('ThML.body').iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) is not None and n.get(k) not in source_ids]\n if account.get('source_navigation_gaps')!=expected_gaps or account.get('producer_lineage')!=verified_lineage():raise ValueError('Source navigation gaps or composite lineage differs')\n permission=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes()\n if not (directory/'README.source.md').read_bytes().endswith(b'\\n\\n## Exact retained permission record\\n\\n'+permission):raise ValueError('Exact human-visible retained permission bytes differ')\n _p5_schema().assertValid(etree.parse(str(path)))")
    insert='''
def verified_lineage():
 path=ROOT/'reports/_logs/watson-existing-install-20261003-v1/retained-producer-lineage.json'
 raw=path.read_bytes()
 if sha256(raw).hexdigest()!='LINEAGE_PIN':raise ValueError('Reviewed producer lineage identity differs')
 record=json.loads(raw)
 for row in record['inputs']+record['original_package_members']:
  data=(ROOT/row['path']).read_bytes()
  if len(data)!=row['bytes'] or sha256(data).hexdigest()!=row['sha256']:raise ValueError('Exact composite lineage file bytes differ')
 if record['original_package_sha256']!='685517f52f9be603117e42c1afe9d6bf2d20a95145c855b7cbb5b37971042605' or record['historical_tei_bytes_exact'] is not False or record['historical_accounting_bytes_exact'] is not True:raise ValueError('Historical replay qualification differs')
 return record

def expected_profile(member,direct):
 filename,pin,front,back,count=SOURCES[member];raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();source=_parse(raw);body=source.find('ThML.body')
 form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic';acquisition=WORK+'--'+member+'--acquired'
 spec=dict(path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=sum(isinstance(n.tag,str) for n in body.iter()),form=form,edition=edition,acquisition=acquisition)
 ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 roots=[dict(source_id=n.get('id'),title=n.get('title'),region='front' if n.get('id') in front else 'back' if n.get('id') in back else 'body') for n in body if isinstance(n.tag,str)]
 navigation=[dict(source_id=n.get('id'),attribute=k,value=n.get(k)) for n in body.iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) is not None and n.get(k) not in ids]
 corrections=json.loads((ROOT/'sources/commentaries/expositors-bible/lib035.reconstruction-profile.json').read_bytes())['text_corrections'];corrections=[r for r in corrections if r['member_id']==member]
 return dict(contract='ocd-watson-existing-native-profile-v1',work_id=WORK,member_id=member,source=spec,source_census={k:direct[k] for k in ('whole_source_elements','source_body_nodes','note_count','table_count','preformatted_count','relative_nonfragment_links','relative_query_links')},original_package_sha256=verified_lineage()['original_package_sha256'],original_member_c14n_sha256=direct['original_scope']['original_member_c14n_sha256'],root_regions={p:[r['source_id'] for r in roots if r['region']==p] for p in ('front','body','back')},root_titles=roots,body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),body_source_attributes={t:sorted({k for n in body.iter(t) for k in n.attrib}) for t in sorted({n.tag for n in body.iter() if isinstance(n.tag,str)})},source_body_attributes=dict(body.attrib),source_navigation_gaps=navigation,prior_correction_proposals=corrections,producer_lineage=verified_lineage(),producer_import_closure_sha256=import_closure('build.tei.watson_retained_native_prepare'),producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',acquired_work_count=3,work_boundary=dict(classification='complete-authored-work',combined_book_parts=member=='watson-ra-expositor7',basis='Exact source title pages, contents, shared indexes and explicit authored-title references on Job and Numbers title pages; book headings and chapter sections are parts, not separate works.',shared_material='Title/front matter, printed/generated indexes and notes remain once in owning complete work; no cross-work duplication',scope='Three existing separately acquired authored works under an author/series catalog; series and author completeness not claimed'),adaptations=['Literal source wording; inherited correction proposals visible and qualified, not silently promoted','Source headings preserve source-level role/order','Literal verse/l stanza grouping and inline order','Table summary and alignment explicit; original presentation attributes exact in ledger','Exact source xml:space present or absent','Administrative comments visible in header and exact ledger; whitespace-only joins checked','Relative/query links use acquired URL per-ref xml:base','Known next/prev source IDs native; absent toc targets explicit typed gaps','Complete raw prolog including XML declaration/DTD/PIs visible; external DTD not fetched'],limitations=direct['limitations'])

def expected_policy(member,direct):
 return dict(contract='ocd-watson-independent-native-policy-v1',member_id=member,independent='Stdlib retained raw XML corroborated against libxml; all actual native fields/order/attachment and source-backed inverse checked independently of emitter and producer; exposure to reviewed source mapping and old ledger declared',required=['Complete authored-work boundary and all front/body/back ownership','Exact source literal direct/tail, hierarchy, inline order and semantic attributes','All33 notes, one table/152 cells,225 stanza groups/1329 lines and128 query links across scope','Complete source header, raw prolog, comments/CSS/rights visible and accounted','All12949 old crosswalk/actual carrier fields and46 correction source-field positions','Exact current composite producer, source identity, acquisition, package lineage, profile and policy','P5-valid feature mutants rejected','Two fresh isolated six-member byte replays per work','Strict fresh import and actual late execution closure'],patterns=['RP-01','RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],limitations=direct['limitations'])

'''.replace('LINEAGE_PIN',pin)
    oracle=once(oracle,'def _oracle(source:SourceManifest,candidate:CandidatePackage)->dict:',insert+'def _oracle(source:SourceManifest,candidate:CandidatePackage)->dict:')
    start=oracle.index(" if profile['contract']");end=oracle.index(" account=json.loads(candidate.member_bytes",start)
    oracle=oracle[:start]+" if profile!=expected_profile(member,result) or policy!=expected_policy(member,result):raise ValueError('Exact independent full profile/policy/source identity/regions/census/closure/lineage differs')\n"+oracle[end:]
    oracle=once(oracle," permission=source.authority_path('permission').read_bytes();emitter=source.authority_path('local-native-emitter').read_bytes()", " permission=source.authority_path('permission').read_bytes();emitter=source.authority_path('local-native-emitter').read_bytes()\n if permission!=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes() or source.authority_path('source-uri-acquisition').read_bytes()!=(ROOT/account['source_uri_acquisition_path']).read_bytes() or source.authority_path('composite-producer-lineage').read_bytes()!=(ROOT/'reports/_logs/watson-existing-install-20261003-v1/retained-producer-lineage.json').read_bytes():raise ValueError('Current permission/acquisition/composite lineage authority differs')")
    write('build/tei/watson_retained_native_oracle.py',oracle)
    print(json.dumps(dict(status='refined',lineage_sha256=pin,code_sha256={p:sha((ROOT/p).read_bytes()) for p in ('build/tei/watson_retained_native_emitter.py','build/tei/watson_retained_native_prepare.py','build/tei/watson_retained_native_oracle.py','build/tei/watson_original_scope.py')})))
