"""Independent raw-body inverse for one complete three-volume Wesley biography.

No producer/emitter helpers are imported. The original mapper was inspected;
source HTML parsing shares html5lib's declared recovery model. Actual serialized
TEI is read independently with stdlib XML and its complete source geometry,
attributes, text/tails, hierarchy, media and retained-component inverse checked.
"""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
from copy import deepcopy
from urllib.parse import unquote,quote
import base64,json,sys,subprocess,importlib
import xml.etree.ElementTree as ET
import html5lib
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage
from ocd_kernel.reconstruction.contract import _validation_authority_bindings,_runtime_binding

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/tyerman-john-wesley-existing-install-20261004-v1')
WORK='tyerman-life-times-john-wesley'
TITLE='The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists.'
PAGES=(69582,71130,76882)
N='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
PREFIX='urn:ocd:tyerman-wesley:source-fields:'
ORACLE_ID='ocd-tyerman-wesley-independent-complete-body-inverse'
SOURCE=ROOT/'sources/manifest-acquisitions/tyerman-life-times-john-wesley-complete-20261004-v2'
ORIGINAL_MANIFEST_PINS=('39efc17caa95bcf03c232f1a268f39881f7b7c714619fd2e71af0b46adb2ddaa','d99f4941d0ed0d12ff6533c071c7bb5b4e5fa964070980c857518f2069c6b185','fc070bfe0b347f43aff77d63d21ed64b028efdba344145d7c7d39a205acabdbd')
RECOVERY_PIN='485cc1f9f2f1b99891becd37df81be8247110834161a25f759bf0b6635e06112'
IMPORT_COMMON=('build/__init__.py','build/tei/__init__.py','ocd_kernel/__init__.py','ocd_kernel/lib/__init__.py','ocd_kernel/lib/path_io.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/reconstruction/__init__.py','ocd_kernel/reconstruction/contract.py')
IMPORT_PATHS={
 'build.tei.tyerman_john_wesley_oracle':sorted((*IMPORT_COMMON,'build/tei/tyerman_john_wesley_oracle.py')),
 'build.tei.tyerman_john_wesley_prepare':sorted((*IMPORT_COMMON,'build/tei/tyerman_john_wesley_prepare.py','build/tei/tyerman_john_wesley_emitter.py'))}

def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def sha(b):return sha256(b).hexdigest()
def fail(message):raise ValueError(message)
def strict(b):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:fail('Duplicate source JSON key: '+k)
            result[k]=v
        return result
    return json.loads(b.decode('utf-8'),object_pairs_hook=pairs)
def native_fields(tree):return [(n.tag,dict(n.attrib),n.text,n.tail,len(n)) for n in tree.iter()]
def source_fields(tree):return [dict(tag=n.tag if isinstance(n.tag,str) else '!comment',attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for n in tree.iter()]

def geometry(body):
    output=[];offset=0
    def scan(n,path,parent,pos):
        nonlocal offset
        iscomment=not isinstance(n.tag,str)
        r=dict(path=path,parent=parent,position=pos,tag='!comment' if iscomment else n.tag,attributes=dict(n.attrib),text_range=None,tail_range=None,comment=n.text if iscomment else None)
        output.append(r)
        if not iscomment and n.text is not None:r['text_range']=[offset,len(n.text)];offset+=len(n.text)
        for i,c in enumerate(n):scan(c,path+'/'+str(i),path,i)
        if n.tail is not None:r['tail_range']=[offset,len(n.tail)];offset+=len(n.tail)
    scan(body,'body',None,0)
    return output,offset

def default_reading(n):
    if n.tag==N+'choice':
        if n.attrib or n.text or len(n)!=2 or n[0].tag!=N+'abbr' or n[1].tag!=N+'expan' or n[1].attrib or len(n[1]) or n[1].tail:fail('Source abbreviation choice envelope differs')
        return default_reading(n[0])
    return (n.text or '')+''.join(default_reading(c)+(c.tail or '') for c in n)

def inverse_source(volume,source_body):
    expected,size=geometry(source_body);wanted={r['path']:r for r in expected}
    observed={};owners={};parent_native={c:n for n in volume.iter() for c in n}
    firstpaths=[]
    for n in volume.iter():
        value=n.get('ana','')
        if not value:continue
        if not value.startswith(PREFIX):fail('Unknown actual body annotation')
        rows=strict(unquote(value[len(PREFIX):]).encode('utf-8'))
        if not isinstance(rows,list) or not rows:fail('Empty source field annotation')
        for r in rows:
            if r.get('path') in observed or r.get('path') not in wanted or r!=wanted[r['path']]:fail('Actual source field geometry/attributes/comment differs')
            observed[r['path']]=r;owners[r['path']]=n
        firstpaths.append(rows[0]['path'])
    if observed!=wanted:fail('Complete source field denominator differs')
    if firstpaths!=sorted(firstpaths,key=lambda p:[-1 if x=='body' else int(x) for x in p.split('/')]):fail('Actual source carrier attachment/order differs')
    source_by_path={r['path']:n for r,n in zip(expected,source_body.iter(),strict=True)}
    owner_primary={owners[p]:p for p in reversed(firstpaths)}
    for p in firstpaths:
        n=owners[p];r=wanted[p];source=source_by_path[p];attrs=r['attributes'];tag=r['tag']
        allowed={'body':{'text'},'header':{'div'},'footer':{'div'},'div':{'div','milestone','pb'},'figure':{'div'},'figcaption':{'div'},'blockquote':{'div'},'p':{'p'},'pre':{'ab'},'ul':{'list'},'ol':{'list'},'li':{'item'},'table':{'table'},'tr':{'row'},'td':{'cell'},'th':{'cell'},'img':{'graphic'},'a':{'ref','seg'},'br':{'lb'},'hr':{'milestone'},'span':{'hi','pb'},'abbr':{'abbr'},'i':{'hi'},'em':{'hi'},'b':{'hi'},'strong':{'hi'},'small':{'hi'},'sup':{'hi'},'sub':{'hi'},'cite':{'hi'},'ins':{'hi'}}
        if tag.startswith('h') and tag[1:] in ['1','2','3','4','5','6']:permitted={'head'}
        else:permitted=allowed.get(tag,set())
        if n.tag.removeprefix(N) not in permitted:fail('Native source role differs: '+p)
        if tag.startswith('h') and tag[1:] in ['1','2','3','4','5','6'] and 'title' in attrs and n.get('n')!=attrs['title']:fail('Source heading navigation title differs')
        def source_reading(node):
            return (node.text or '' if isinstance(node.tag,str) else '')+''.join(source_reading(c)+(c.tail or '') for c in node)
        # Slot ownership is independently local, not merely a global stream.
        # This rejects moving a word from a paragraph into its neighbor's tail
        # while leaving the whole visible stream unchanged.
        if n.tag not in [N+'milestone',N+'pb'] and default_reading(n)!=source_reading(source):fail('Native source unit text ownership differs: '+p)
        if n.tag in [N+'p',N+'head',N+'ab',N+'hi',N+'abbr',N+'ref',N+'seg']:
            unit=parent_native[n] if n.tag==N+'abbr' or parent_native[n].get('rend')=='source-standalone-inline' else n
            if parent_native.get(unit) is not None and parent_native[unit].get('rend')=='source-standalone-inline':unit=parent_native[unit]
            native_tail=unit.tail
            parent_unit=parent_native.get(unit)
            if parent_unit is not None:
                siblings=list(parent_unit);index=siblings.index(unit)
                if index+1<len(siblings) and siblings[index+1].get('rend')=='source-interstitial-text':native_tail=siblings[index+1].text
            if (native_tail or '').strip()!=(source.tail or '').strip():fail('Native source tail ownership differs: '+p)
        if attrs.get('lang') and n.get(X+'lang')!=attrs['lang']:fail('Source native language differs')
        if tag in ['td','th']:
            if n.get('cols')!=attrs.get('colspan') or n.get('rows')!=attrs.get('rowspan') or (n.get('role')=='label')!=(tag=='th'):fail('Source cell role/span differs')
        if tag=='abbr':
            parent=parent_native[n]
            if parent.tag!=N+'choice' or parent[0] is not n or parent[1].text!=attrs.get('title'):fail('Source abbreviation expansion differs')
        if tag=='a' and attrs.get('href'):
            volume_number=int(volume.get(X+'id').rsplit('-',1)[1]);href=attrs['href'];target='#v'+str(volume_number)+'--'+href[1:] if href.startswith('#') else href
            if n.get('target')!=target:fail('Source link target or volume context differs')
        if tag=='img':
            if n.get('n')!=attrs.get('alt',''):fail('Source image alternative label differs')
        # Every represented native owner is attached to the nearest represented
        # source ancestor. Declared section and page-label/layout folds are skipped.
        raw_parent=r['parent']
        while raw_parent is not None:
            candidate=owners[raw_parent]
            if candidate is not n and candidate.tag not in [N+'milestone',N+'pb']:break
            raw_parent=wanted[raw_parent]['parent']
        physical=parent_native.get(n)
        while physical is not None and physical not in owner_primary:physical=parent_native.get(physical)
        if raw_parent is not None and physical is not owners[raw_parent]:fail('Actual source parent attachment differs: '+p)
        if tag in ['header','footer','div','figure','figcaption','blockquote'] and n.tag==N+'div':
            carriers=[c for c in n if c.tag==N+'div' and c.get('type')=='source-child-carrier']
            if len(carriers)!=len(source):fail('Source container child cardinality differs')
        if tag=='table':
            rawrows=[q for q in source.iter('tr')]
            actualrows=list(n.iter(N+'row'))
            if len(rawrows)!=len(actualrows):fail('Source table row cardinality differs')
    visible=default_reading(volume)
    if len(visible)!=size:fail('Actual source direct text/tail character denominator differs')
    recovered={}
    for p,r in observed.items():
        n=ET.Element(r['tag'],r['attributes']) if r['tag']!='!comment' else ET.Comment(r['comment'] or '')
        for key in ['text','tail']:
            span=r[key+'_range']
            if key=='text' and r['tag']=='!comment':continue
            setattr(n,key,None if span is None else visible[span[0]:span[0]+span[1]])
        recovered[p]=n
    for r in expected:
        if r['parent'] is not None:recovered[r['parent']].append(recovered[r['path']])
    if source_fields(recovered['body'])!=source_fields(source_body):fail('Full actual body inverse differs in source tags/attributes/text/tails/order')
    return dict(source_nodes=len(expected),source_comments=sum(r['tag']=='!comment' for r in expected),source_attributes=sum(len(r['attributes']) for r in expected),source_text_characters=size,actual_body_inverse='pass',represented_native_owners=len(firstpaths))

def undo_patches(volume,patches,original):
    tree=deepcopy(volume)
    def locate(path):
        n=tree
        for index in path:n=n[index]
        return n
    for row in reversed(patches):
        n=locate(row['path']);kind=row['kind']
        before=original
        for index in row['path']:before=before[index]
        if kind=='subtree':
            if sha(enc(native_fields(n)))!=row['after_sha256']:fail('Declared repaired subtree differs')
            old=deepcopy(before)
            if not row['path']:tree=old
            else:
                parent=locate(row['path'][:-1]);index=row['path'][-1];parent.remove(n);parent.insert(index,old)
        elif kind=='attributes':
            if sha(enc(n.attrib))!=row['after_sha256']:fail('Declared repaired attributes differ')
            n.attrib.clear();n.attrib.update(before.attrib)
        elif kind in ['text','tail']:
            if sha(enc(getattr(n,kind)))!=row['after_sha256']:fail('Declared repaired scalar field differs')
            setattr(n,kind,getattr(before,kind))
        else:fail('Unknown repair inverse operation')
    return tree

def import_probe(module):
    script="""import importlib,json,sys
from pathlib import Path
r=Path(sys.argv[1]).resolve();sys.path.insert(0,str(r));importlib.import_module(sys.argv[2])
print(json.dumps(sorted({Path(m.__file__).resolve().relative_to(r).as_posix() for m in sys.modules.copy().values() if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(r)})))"""
    paths=json.loads(subprocess.run([sys.executable,'-I','-B','-c',script,str(ROOT),module],check=True,capture_output=True,text=True).stdout)
    allowed=IMPORT_PATHS
    if allowed and paths!=allowed[module]:fail('Unexpected or missing fresh first-party import')
    return [dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in paths]
def closure_digest():
    closure=strict((SOURCE/'code-closure.json').read_bytes())
    if set(closure)!={'contract','imports'} or closure['contract']!='ocd-tyerman-wesley-fresh-imports-v1' or set(closure['imports'])!=set(IMPORT_PATHS):fail('Closed producer/oracle import declaration differs')
    for module in IMPORT_PATHS:
        observed=import_probe(module)
        if observed!=closure['imports'][module]:fail('Fresh transitive code pins drifted: '+module)
    return sha(enc(closure['imports']['build.tei.tyerman_john_wesley_oracle']))

def authority_plan():
    plan={}
    def add(name,path,role):
        if name in plan:fail('Duplicate expected source authority')
        plan[name]=(str(path).replace('\\','/'),role)
    for number,pg,pin in zip([1,2,3],PAGES,ORIGINAL_MANIFEST_PINS,strict=True):
        original=f'sources/manifest-acquisitions/tyerman-life-times-john-wesley-vol-{number}-1872/source-manifest.json'
        raw=(ROOT/original).read_bytes()
        if sha(raw)!=pin:fail('Original historical source manifest drifted')
        add('original-manifest-'+str(number),original,'historical-component-source-manifest')
        for row in strict(raw)['authorities']:add('original-'+str(number)+'-'+row['name'],row['path'],row['role'] if row['role']=='primary-source' else 'historical-component-authority')
        base=LOG/'retained-v4'/str(pg)
        for member in ['README.source.md','content.tei.xml','provenance.json','source-accountability.json','unresolved.jsonl','manifest.json']:add('legacy-'+str(number)+'-'+member,base/'package'/member,'historical-component-package')
        for member in ['validation.json','mutation-reproduction.json']:add('legacy-'+str(number)+'-'+member,base/member,'historical-component-proof')
    if sha((ROOT/LOG/'retained-recovery-receipt.json').read_bytes())!=RECOVERY_PIN:fail('Exact scoped recovery receipt drifted')
    add('recovery-receipt',LOG/'retained-recovery-receipt.json','historical-component-recovery')
    for name,filename,role in [('profile','profile.json','complete-source-feature-profile'),('policy','policy.json','independent-validation-policy'),('readme','README.source.md','source-local-attribution-readme'),('code-closure','code-closure.json','fresh-code-import-closure'),('execution-runtime','runtime-bindings.json','actual-execution-runtime-bindings')]:add(name,SOURCE.relative_to(ROOT)/filename,role)
    add('tei-validation-schema','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema')
    add('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')
    for name in ['tei_all_teix.xsd','tei_all_xml.xsd']:add(name,'ocd_kernel/tei/vendor/xsd/'+name,'tei-schema-import')
    for i,path in enumerate(sorted(set(p for paths in IMPORT_PATHS.values() for p in paths)|{'build/tools/reconstruct_candidate.py','ocd_kernel/reconstruction/destination_policy.py','build/tei/tyerman_pg_html.py','build/tei/tyerman_pg_html_oracle.py'})):add('code-'+str(i),path,'source-execution-code')
    return plan

def assert_authorities(manifest):
    actual={a['name']:(a['path'],a['role']) for a in manifest.record['authorities']}
    if len(actual)!=len(manifest.record['authorities']) or actual!=authority_plan():fail('Exact source authority paths/roles differ')
    for a in manifest.record['authorities']:
        if set(a)!={'name','path','role','bytes','sha256'}:fail('Source authority field shape differs')
    for field,path,identifier in [('converter','build/tei/tyerman_john_wesley_prepare.py','ocd-tyerman-wesley-retained-three-volume-repair'),('validator','build/tei/tyerman_john_wesley_oracle.py',ORACLE_ID)]:
        record=manifest.record[field]
        expected={'callable':'_convert' if field=='converter' else '_oracle','id':identifier,'implementation_path':path,'implementation_sha256':sha((ROOT/path).read_bytes()),'version':'1'}
        if field=='validator':expected['import_closure_sha256']=sha(enc(strict((SOURCE/'code-closure.json').read_bytes())['imports']['build.tei.tyerman_john_wesley_oracle']))
        if dict(record)!=expected:fail('Exact current callable declaration differs: '+field)

def runtime_files():
    found={}
    for module in sys.modules.copy().values():
        f=getattr(module,'__file__',None)
        if not f:continue
        p=Path(f).resolve(strict=True)
        key=p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix()
        found[key]=sha(p.read_bytes())
    found[Path(sys.executable).resolve(strict=True).as_posix()]=sha(Path(sys.executable).read_bytes())
    return found

def assert_runtime():
    declared=strict((SOURCE/'runtime-bindings.json').read_bytes())
    if declared.get('status')!='sealed':fail('Runtime execution closure remains draft')
    if set(declared)!={'contract','status','files'} or declared['contract']!='ocd-tyerman-wesley-runtime-files-v1':fail('Closed runtime declaration differs')
    observed=runtime_files()
    unknown={p:h for p,h in observed.items() if declared['files'].get(p)!=h}
    if unknown:fail('Unexpected or changed actual execution dependency: '+repr(unknown))
    for p,h in declared['files'].items():
        path=Path(p) if Path(p).is_absolute() else ROOT/p
        if sha(path.read_bytes())!=h:fail('Bound current runtime code drifted: '+p)
    return observed

def expected_metadata(profile,policy,manifest=None):
    expected_policy=dict(contract='ocd-tyerman-wesley-complete-policy-v1',work_id=WORK,scope='Complete retained three-volume John Wesley biography; Volume III appendix by Abel Stevens and index included.',provenance={'provider':'Project Gutenberg','modifications':profile['component_route'],'historical_scope_qualification':'The old separate-volume complete-work claims are preserved as dated component evidence and superseded by primary three-volume title evidence.','human_verification':'not_recorded','rights':'unresolved','publication':'not_ready'},unresolved=[{'kind':'human-review','message':'No human textual acceptance, rendered comparison or printed-witness collation is claimed.'},{'kind':'rights','message':'Project Gutenberg notices and contributors are retained; applicable jurisdiction and reuse rights remain unresolved.'}])
    if policy!=expected_policy:fail('Complete policy contents differ')
    if profile['primary_boundary']!='All three primary title pages explicitly say IN THREE VOLUMES; distinct numbered source volumes share the complete biography title and 1872 New York imprint.' or profile['component_route']!='Existing three TEI text trees are checked against their unchanged declared mapping and patched in place; original packages remain byte-identical. Only located source-backed field, whitespace, footer hierarchy, ID/ref and media repairs are applied.':fail('Complete boundary/repair disposition differs')
    expected_dispositions={'body_comments':'Exact administrative payload, parent and position retained in source annotations; comment text is not invented as visible prose. All comment tail joins are retained.','table_sections':'tbody/thead/tfoot/colgroup are declared layout folds at their table owner; exact fields and child relations remain in annotations; row/cell roles and all spans are native.','page_labels':'Exact source page subtree fields remain at the native page marker; original label text remains adjacent.','source_head':'Complete head fields, style and prefix are literal human-visible header/source README support context.','source_attributes':'Every attribute remains literal at the source-bound native owner; language, rowspans, abbreviation expansion alternatives and graphics also have native semantic representations.'}
    if profile['field_dispositions']!=expected_dispositions:fail('Complete source field disposition differs')
    header=ET.Element(N+'teiHeader');fd=ET.SubElement(header,N+'fileDesc');ts=ET.SubElement(fd,N+'titleStmt');ET.SubElement(ts,N+'title').text=TITLE;ET.SubElement(ts,N+'author').text='L. Tyerman';resp=ET.SubElement(ts,N+'respStmt');ET.SubElement(resp,N+'resp').text='Appendix in Volume III';ET.SubElement(resp,N+'name').text='Abel Stevens'
    pub=ET.SubElement(fd,N+'publicationStmt');ET.SubElement(pub,N+'p').text='Nonaccepted retained electronic reconstruction of the complete three-volume work. Human verification, print collation, rights and publication remain separate.'
    desc=ET.SubElement(fd,N+'sourceDesc')
    readme=['# '+TITLE,'','One complete authored work in three ordered source volumes. The original volume packages and their historical separate-work claims are preserved as component evidence, not adopted as the current work boundary. No new source was acquired.','','Source abbreviation titles are represented as choice/abbr/expan alternatives; the retained abbreviation is the default source reading. Classes, styles, administrative comments and folded table section fields remain literal, located source annotations. Source display metadata does not invent new prose.','','Human verification, rendered comparison, printed-witness collation and applicable rights remain unresolved. Project Gutenberg notices and credited contributors remain visible in every volume.','']
    for number,pg,u in zip([1,2,3],PAGES,profile['units'],strict=True):
        base=ROOT/LOG/'retained-v4'/str(pg)/'package';old=etree.fromstring((base/'content.tei.xml').read_bytes());old_header=old.find(N+'teiHeader');old_title=old_header.findtext(N+'fileDesc/'+N+'titleStmt/'+N+'title');receipt=strict((ROOT/f'raw/gutenberg/{pg}/acquisition-receipt.json').read_bytes())
        with ZipFile(ROOT/f'raw/gutenberg/{pg}/pg{pg}-h.zip') as z:raw=z.read(f'pg{pg}-images.html')
        src=html5lib.parse(raw,treebuilder='etree',namespaceHTMLElements=False);head=src.find('head');body=src.find('body');prefix=raw[:raw.lower().index(b'<html')].decode('utf-8');suffix=raw[raw.lower().rfind(b'</body>')+len(b'</body>'):].decode('utf-8')
        envelope=dict(root_tag=src.tag,root_attributes=dict(src.attrib),root_text=src.text,root_tail=src.tail,root_child_tags=[n.tag if isinstance(n.tag,str) else '!comment' for n in src],head_tail=head.tail,body_text=body.text,body_tail=body.tail,raw_suffix_after_body=suffix,parser_line_endings='HTML5 CRLF and CR normalization to LF; original bytes remain unchanged in the retained archive.')
        if u['source_envelope']!=envelope:fail('Complete root/head/body/suffix disposition differs')
        head_literal=ET.tostring(head,encoding='unicode');b=ET.SubElement(desc,N+'bibl',{'type':'retained-source-volume',X+'id':'wesley-source-'+str(number)})
        for name,value in [('title',old_title),('author','L. Tyerman'),('pubPlace','New York'),('publisher','Harper & Brothers, Publishers'),('date','1872')]:ET.SubElement(b,N+name).text=value
        ET.SubElement(b,N+'ref',{'target':receipt['source_url']}).text=receipt['source_url']
        notes=[('volume-scope','Primary title page: IN THREE VOLUMES; VOL. '+('I','II','III')[number-1]+'. Source Gutenberg electronic release, update, contributor and license statements remain literal in its complete volume envelope.'),('historical-component-header',etree.tostring(old_header,encoding='unicode')),('source-document-prefix',prefix),('source-head-literal',head_literal),('source-envelope-fields',enc(envelope).decode('utf-8'))]
        for kind,value in notes:ET.SubElement(b,N+'note',{'type':kind}).text=value
        readme.extend(['## Volume '+str(number)+' — Gutenberg '+str(pg),'','Primary title page: IN THREE VOLUMES; VOL. '+('I','II','III')[number-1]+'. New York: Harper & Brothers, Publishers, Franklin Square, 1872.','',('Volume III explicitly includes the appendix by Abel Stevens and the index.' if number==3 else 'The complete source front, book body and provider footer are retained.'),'','Source: '+receipt['source_url'],'','### Original source document prefix','```xml',prefix,'```','','### Literal source head, including styles and support context','```xml',head_literal,'```','','### Original retained source notice',(base/'README.source.md').read_text(encoding='utf-8'),'','### Exact source envelope fields, suffix and parser disposition','```json',enc(envelope).decode('utf-8'),'```',''])
    provenance=dict(contract='ocd-tyerman-wesley-composite-provenance-v1',status='nonaccepted',work_id=WORK,source_volumes=[{k:u[k] for k in ('volume','ebook_id','source_path','source_sha256','source_bytes','source_url','downloaded_utc','source_manifest_path','source_manifest_sha256','legacy_package_path','legacy_manifest_sha256','legacy_tei_sha256')} for u in profile['units']],producer_recipe_sha256=sha((ROOT/'build/tei/tyerman_john_wesley_prepare.py').read_bytes()),emitter_sha256=sha((ROOT/'build/tei/tyerman_john_wesley_emitter.py').read_bytes()),oracle_sha256=sha(Path(__file__).read_bytes()),ancestor_pins=[dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in ('build/tei/tyerman_pg_html.py','build/tei/tyerman_pg_html_oracle.py')],human_verification='not_recorded',rights='unresolved',publication='not_ready')
    if manifest is not None:provenance.update(source_manifest_sha256=manifest.sha256,converter=dict(manifest.record['converter']),oracle=dict(manifest.record['validator']),code_closure_sha256=sha((SOURCE/'code-closure.json').read_bytes()),execution_runtime_sha256=sha((SOURCE/'runtime-bindings.json').read_bytes()))
    return header,('\n'.join(readme)+'\n').encode('utf-8'),provenance

def check(manifest,candidate):
    manifest.verify();candidate.verify_integrity();profile=strict(manifest.authority_path('profile').read_bytes());policy=strict(manifest.authority_path('policy').read_bytes())
    assert_authorities(manifest)
    if set(profile)!={'contract','work_id','complete_work_count','source_volume_count','volume_order','primary_boundary','units','media','component_route','field_dispositions'} or profile['work_id']!=WORK or profile['complete_work_count']!=1 or profile['source_volume_count']!=3 or profile['volume_order']!=list(map(str,PAGES)):fail('Complete source profile scope/shape differs')
    if policy['work_id']!=WORK or policy['scope']!=manifest.record['scope'] or policy['contract']!='ocd-tyerman-wesley-complete-policy-v1':fail('Complete policy identity/scope differs')
    if set(manifest.record)!={'contract','manifest_row','work_id','source_id','scope','converter','validator','package_schema','authorities'} or manifest.record['work_id']!=WORK or manifest.record['manifest_row']!='L634' or manifest.record['source_id']!='gutenberg-69582-71130-76882-complete':fail('Complete source manifest identity/shape differs')
    header,readme,provenance=expected_metadata(profile,policy,manifest)
    raw=candidate.member_bytes('content.tei.xml');actual=ET.fromstring(raw)
    if actual.tag!=N+'TEI' or actual.attrib!={X+'id':WORK+'--candidate',X+'lang':'en'} or actual.text or actual.tail or [n.tag for n in actual]!=[N+'teiHeader',N+'text']:fail('Whole TEI outer envelope differs')
    if native_fields(actual[0])!=native_fields(header):fail('Complete source/aggregate header fields differ')
    if candidate.member_bytes('README.source.md')!=readme or manifest.authority_path('readme').read_bytes()!=readme:fail('Complete literal source README differs')
    if strict(candidate.member_bytes('provenance.json'))!=provenance:fail('Complete current composite provenance differs')
    text=actual[1]
    if text.attrib or text.text or text.tail or len(text)!=1 or text[0].tag!=N+'group':fail('Whole text/group envelope differs')
    group=text[0]
    if group.attrib!={X+'id':WORK+'--volumes'} or group.text or group.tail or len(group)!=3:fail('Three volume group identity/order differs')
    ids=[n.get(X+'id') for n in actual.iter() if n.get(X+'id')]
    if len(ids)!=len(set(ids)):fail('Duplicate global source IDs')
    for n in actual.iter():
        if n.tag==N+'ref' and n.get('target','').startswith('#') and n.get('target')[1:] not in ids:fail('Unresolved grouped fragment')
    outcomes=[];expected_media=[]
    for volume,pg,unit in zip(group,PAGES,profile['units'],strict=True):
        if set(unit)!={'volume','ebook_id','source_path','source_bytes','source_sha256','html_member','html_sha256','source_url','downloaded_utc','source_manifest_path','source_manifest_sha256','legacy_package_path','legacy_manifest_sha256','legacy_tei_sha256','source_root_attributes','source_envelope','source_head','document_prefix','source_body_records','native_patch','native_fields_sha256','original_visible_text_sha256','original_visible_text_characters'}:fail('Complete volume profile field shape differs')
        number=PAGES.index(pg)+1
        if volume.tag!=N+'text' or volume.get(X+'id')!='wesley-volume-'+str(number) or volume.get(X+'lang')!='en' or volume.tail or [n.tag for n in volume]!=[N+'front',N+'body',N+'back']:fail('Complete volume envelope differs')
        source_path=f'raw/gutenberg/{pg}/pg{pg}-h.zip';source=(ROOT/source_path).read_bytes();receipt=strict((ROOT/f'raw/gutenberg/{pg}/acquisition-receipt.json').read_bytes());oldbase=ROOT/LOG/'retained-v4'/str(pg)/'package';old=ET.fromstring((oldbase/'content.tei.xml').read_bytes())
        if unit['volume']!=number or unit['ebook_id']!=str(pg) or unit['source_path']!=source_path or unit['source_bytes']!=len(source) or unit['source_sha256']!=sha(source) or unit['source_url']!=receipt['source_url'] or unit['downloaded_utc']!=receipt['downloaded_utc']:fail('Original source acquisition lineage differs')
        if unit['legacy_manifest_sha256']!=sha((oldbase/'manifest.json').read_bytes()) or unit['legacy_tei_sha256']!=sha((oldbase/'content.tei.xml').read_bytes()):fail('Legacy component binding differs')
        expected_original_manifest=f'sources/manifest-acquisitions/tyerman-life-times-john-wesley-vol-{number}-1872/source-manifest.json'
        if unit['source_manifest_path']!=expected_original_manifest or unit['source_manifest_sha256']!=sha((ROOT/expected_original_manifest).read_bytes()) or unit['legacy_package_path']!=(LOG/'retained-v4'/str(pg)/'package').as_posix():fail('Original component authority paths/pins differ')
        for patch in unit['native_patch']:
            if set(patch)!={'path','kind','after_sha256'} or not all(isinstance(i,int) and i>=0 for i in patch['path']) or patch['kind'] not in ['subtree','attributes','text','tail']:fail('Repair inverse ledger shape differs')
        if len({(tuple(p['path']),p['kind']) for p in unit['native_patch']})!=len(unit['native_patch']):fail('Duplicate repair inverse slot')
        with ZipFile(ROOT/source_path) as archive:
            if archive.testzip() is not None:fail('Source ZIP CRC failed')
            htmlraw=archive.read(f'pg{pg}-images.html');src=html5lib.parse(htmlraw,treebuilder='etree',namespaceHTMLElements=False);body=src.find('body');head=src.find('head')
            if unit['html_member']!=f'pg{pg}-images.html' or unit['html_sha256']!=sha(htmlraw) or unit['source_root_attributes']!=dict(src.attrib) or unit['source_head']!=source_fields(head) or unit['document_prefix']!=htmlraw[:htmlraw.lower().index(b'<html')].decode('utf-8'):fail('Complete source head/prefix/profile fields differ')
            if unit['source_body_records']!=geometry(body)[0]:fail('Source body profile differs')
            # Primary title boundary is observed directly, not inferred from IDs.
            primary=' '.join(''.join(body.itertext()).split())
            if 'IN THREE VOLUMES' not in primary.upper() or 'HARPER & BROTHERS' not in primary.upper() or '1872' not in primary:fail('Primary three-volume/imprint boundary missing')
            if pg==76882 and not all(s in primary.upper() for s in ['ABEL STEVENS','APPENDIX','INDEX']):fail('Volume III appendix/index source scope missing')
            outcome=inverse_source(volume,body)
            for member in archive.namelist():
                if member.endswith('/') or member.endswith('.html'):continue
                data=archive.read(member);path=f'raw/gutenberg/{pg}/html/{member}'
                if (ROOT/path).read_bytes()!=data:fail('Existing extracted media differs')
                expected_media.append(dict(volume=number,ebook_id=str(pg),archive_member=member,path=path,bytes=len(data),sha256=sha(data),media_type='image/jpeg'))
            images=list(body.iter('img'));graphics=list(volume.iter(N+'graphic'))
            if len(images)!=len(graphics):fail('Source graphic occurrence denominator differs')
            for source_image,graphic in zip(images,graphics,strict=True):
                member=source_image.get('src');data=archive.read(member)
                if graphic.get('corresp')!='urn:ocd:retained-archive-member:sha256:'+sha(source)+':'+quote(member,safe='') or graphic.get('url')!='data:image/jpeg;base64,'+base64.b64encode(data).decode('ascii'):fail('Source graphic attachment/pixels/context differs')
        if native_fields(undo_patches(volume,unit['native_patch'],old.find(N+'text')))!=native_fields(old.find(N+'text')):fail('Exact retained component inverse differs')
        if unit['native_fields_sha256']!=sha(enc(native_fields(volume))):fail('Complete actual native fields differ from exercised repair ledger')
        if unit['original_visible_text_sha256']!=sha(default_reading(volume).encode('utf-8')) or unit['original_visible_text_characters']!=len(default_reading(volume)):fail('Complete source reading binding differs')
        carriers=volume.find(N+'body/'+N+'div')
        if carriers is None or len(carriers)!=sum(isinstance(n.tag,str) and n.tag not in ['header','footer'] for n in body):fail('Source direct body carrier denominator differs')
        outcomes.append(outcome|dict(volume=number,ebook_id=str(pg),retained_component_inverse='pass',graphic_occurrences=len(graphics)))
    if profile['media']!=expected_media:fail('Complete media/profile fields differ')
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path('tei-validation-schema'))))
    if not schema.validate(etree.fromstring(raw)):fail('P5 schema failure: '+str(schema.error_log.last_error))
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('readme').read_bytes():fail('Human-visible credit/readme authority differs')
    if candidate.member_bytes('unresolved.jsonl')!=b''.join(enc(r) for r in policy['unresolved']):fail('Complete unresolved disposition differs')
    account=strict(candidate.member_bytes('source-accountability.json'))
    if account!=dict(contract='ocd-tyerman-wesley-complete-accounting-v1',work_id=WORK,complete_work_count=1,source_volume_count=3,volume_order=list(map(str,PAGES)),source_tei_sha256=sha(raw),profile_sha256=sha(manifest.authority_path('profile').read_bytes()),media=expected_media,historical_recovery_receipt_sha256=sha((ROOT/LOG/'retained-recovery-receipt.json').read_bytes()),source_reading_rule='For a source-attested abbreviation choice, read abbr; expan is an explicitly separate source title alternative.'):fail('Complete source accounting differs')
    return dict(status='pass',complete_work_count=1,source_volume_count=3,volumes=outcomes,graphics=sum(r['graphic_occurrences'] for r in outcomes),retained_assets=len(expected_media),full_actual_source_inverse=True,whole_retained_component_inverse=True)

def _oracle(manifest:SourceManifest,candidate:CandidatePackage):
    assert_runtime()
    check(manifest,candidate)
    assert_runtime()
    bindings=_validation_authority_bindings(manifest)
    result=dict(status='pass',oracle_id=ORACLE_ID,oracle_version='1',implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=closure_digest(),runtime=_runtime_binding(),source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,findings=[],**bindings)
    assert_runtime()
    result['result_sha256']=sha(enc(result));return result
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
