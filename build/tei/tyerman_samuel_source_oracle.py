"""Independent whole-object source grammar and retained-component inverse for L637.

No producer is imported. Expectations are derived from complete source objects;
the inherited carrier grammar and HTML5 recovery are explicitly qualified.
"""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile
from html.parser import HTMLParser
from collections import Counter
import base64, json, re, sys, platform
import html5lib
from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
T = 'http://www.tei-c.org/ns/1.0'; X = '{http://www.w3.org/XML/1998/namespace}'
NS = {'t': T}; WORK = 'tyerman-life-times-samuel-wesley-1866'; SOURCE_ID = 'gutenberg-67980'
HOME='sources/manifest-acquisitions/tyerman-samuel-retained-install-20261004-v1'
LOG='reports/_logs/tyerman-samuel-existing-install-20261004-v1'
OLD='sources/manifest-acquisitions/tyerman-life-times-samuel-wesley-1866'
SCOPE='The Life and Times of the Rev. Samuel Wesley, M.A.'
PRODUCER='build/tei/tyerman_samuel_retained_repair.py'
ORACLE='build/tei/tyerman_samuel_source_oracle.py'
INLINE = {'a','span','i','em','b','strong','small','sup','sub','abbr','cite','ins'}
ARCHIVE_SHA = 'a745273a2a6d5bdc0b036cb2b946dc9440b58edf74e6ff24ed8e700ee6995fc7'
PAGE = re.compile(r'(?:\[(?:Pg\s*)?|\{)([^\]}]+)(?:\]|\})')
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode()

def sha(raw): return sha256(raw).hexdigest()

def tree(node):
    return dict(tag=node.tag if isinstance(node.tag,str) else '#comment',attributes=dict(sorted(node.attrib.items())),text=node.text,tail=node.tail,children=[tree(c) for c in node])

def insist(condition, message):
    if not condition: raise ValueError(message)

class LiteralHTML(HTMLParser):
    """Separate strict lexical tree reader for this explicit, balanced HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True); self.root=etree.Element('document'); self.stack=[self.root]
    def handle_starttag(self,tag,attrs):
        n=etree.SubElement(self.stack[-1],tag,dict(attrs))
        if tag not in VOID:self.stack.append(n)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in VOID:return
        insist(len(self.stack)>1 and self.stack[-1].tag==tag,'Raw lexical HTML balance differs at '+tag)
        self.stack.pop()
    def handle_data(self,data):
        n=self.stack[-1]
        if len(n):n[-1].tail=(n[-1].tail or '')+data
        else:n.text=(n.text or '')+data
    def handle_comment(self,data):self.stack[-1].append(etree.Comment(data))

def lexical_corroboration(raw, source):
    reader=LiteralHTML();reader.feed(raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n'));reader.close()
    insist(len(reader.stack)==1,'Raw HTML unclosed element')
    lexical=reader.root.find('html'); insist(lexical is not None,'Raw html root absent')
    insist(len(lexical)==len(source)==3 and lexical[0].tag==source[0].tag=='head' and lexical[1].tag==source[1].tag=='body' and not isinstance(lexical[2].tag,str) and not isinstance(source[2].tag,str),'Exact root child order/comment differs')
    differences=[('html.text',lexical,source,'text','\n',None),('html.tail',lexical,source,'tail','\n',None),('body.tail',lexical[1],source[1],'tail','\n',None),('footer.tail',lexical[1][-1],source[1][-1],'tail',None,'\n\n\n'),('root-comment.tail',lexical[2],source[2],'tail','\n',None)]
    recovery=[]
    for pointer,a,b,field,old,new in differences:
        insist(getattr(a,field)==old and getattr(b,field)==new,'Declared document whitespace recovery differs: '+pointer)
        recovery.append(dict(pointer=pointer,lexical=old,html5=new));setattr(a,field,new)
    insist(tree(lexical)==tree(source),'Raw lexical/HTML5 complete source fields differ outside exact declared formatting recovery')
    return dict(method='Independent strict stdlib lexical HTML stack versus html5lib complete source fields',head_elements=sum(1 for n in source.find('head').iter() if isinstance(n.tag,str)),body_elements=sum(1 for n in source.find('body').iter() if isinstance(n.tag,str)),document_formatting_recovery=recovery,qualification='HTML input CRLF/CR is normalized to LF. Exactly five document formatting fields differ under HTML5 recovery; raw suffix/prolog and located root comment are visible administration. Every other whole source field is identical.')

def make(parent,tag,attrs=None,text=None):
    out=etree.SubElement(parent,'{'+T+'}'+tag,attrs or {});out.text=text;return out

def attributes(source, base, repaired):
    result=dict(base)
    if source.get('id'):result[X+'id']=source.get('id')
    if repaired:
        if 'class' in source.attrib:
            prefix=result.get('rend')
            result['rend']=(prefix+' ' if prefix else '')+source.get('class')
        if 'lang' in source.attrib:result[X+'lang']=source.get('lang')
        if 'title' in source.attrib:result['n']=source.get('title')
        if 'style' in source.attrib:result['style']=source.get('style')
    return result

def source_grammar(source, parent, repaired, images, context, inline=False):
    """Source-owned field/range grammar; every actual tree field is constrained."""
    if not isinstance(source.tag,str):
        if repaired:parent.append(etree.Comment(source.text or ''));parent[-1].tail=source.tail
        return
    kind=source.tag;classes=source.get('class','').split()
    if kind in ('div','span') and 'pagenum' in classes:
        value=''.join(source.itertext());match=PAGE.search(value)
        own=source.get('id');anchors=[n.get('id') for n in source.iter('a') if n.get('id')]
        insist(not(own and anchors),'Page marker has two conflicting identities')
        attrs={'n':match.group(1)} if match else {}
        if own or anchors:attrs[X+'id']=own or anchors[0]
        if inline:
            make(parent,'pb',attrs);make(parent,'seg',{'rend':'source-page-label'},value)
        else:
            p=make(parent,'p',{'rend':'source-page-label'});make(p,'pb',attrs);make(p,'seg',text=value)
    elif kind in ('header','footer','div','figure','figcaption','blockquote') and not inline:
        attrs={'type':'source-'+kind}
        if source.get('class'):attrs['rend']=source.get('class')
        # Class already copied on inherited container carriers.
        if source.get('id'):attrs[X+'id']=source.get('id')
        if repaired and 'lang' in source.attrib:attrs[X+'lang']=source.get('lang')
        out=make(parent,'div',attrs)
        if source.text is not None:make(out,'p',{'rend':'source-leading-text'},source.text)
        for child in source:
            slot=make(out,'div',{'type':'source-child-carrier'})
            source_grammar(child,slot,repaired,images,context)
    elif kind in ('ul','ol') and not inline:
        out=make(parent,'list',attributes(source,{'type':kind},repaired))
        if source.text and source.text.strip():make(out,'head',{'rend':'source-leading-text'},source.text)
        for child in source:source_grammar(child,out,repaired,images,context)
    elif kind=='table' and not inline:
        insist(not source.text or not source.text.strip(),'Table direct words need a native disposition')
        out=make(parent,'table',attributes(source,{},repaired))
        for child in source:source_grammar(child,out,repaired,images,context)
    elif kind in ('tbody','thead','tfoot','colgroup') and not inline:
        insist(not source.attrib,'Unexpected semantic table-section attribute')
        insist(not source.text or not source.text.strip(),'Unexpected table-section direct words')
        for child in source:source_grammar(child,parent,repaired,images,context)
    elif kind=='col' and not inline:
        attrs={'unit':'source-column'}
        if source.get('span'):attrs['n']=source.get('span')
        if not repaired and source.get('class'):attrs['rend']=source.get('class')
        make(parent,'milestone',attributes(source,attrs,repaired))
    elif kind=='tr' and not inline:
        out=make(parent,'row',attributes(source,{},False))
        for child in source:source_grammar(child,out,repaired,images,context)
    elif kind=='hr':
        attrs={'unit':'source-rule'}
        if source.get('class'):attrs['rend']=source.get('class')
        make(parent,'milestone',attributes(source,attrs,False))
    elif kind=='img':
        attrs={'url':source.get('src')}
        if source.get('alt'):attrs['n']=source.get('alt')
        if repaired:
            attrs={'url':'data:image/jpeg;base64,'+base64.b64encode(images[source.get('src')]).decode(),'corresp':'urn:ocd:retained-archive:'+ARCHIVE_SHA+':member:'+source.get('src'),'n':source.get('alt')}
        attrs=attributes(source,attrs,repaired)
        out=parent if inline else make(parent,'figure',{'type':'source-image'})
        make(out,'graphic',attrs)
    elif kind=='br':
        out=parent if inline else make(parent,'p',{'rend':'source-standalone-break'})
        make(out,'lb')
    elif kind=='a' or kind in INLINE and (inline or kind not in ('p',)):
        out=parent if inline else make(parent,'p',{'rend':'source-standalone-inline'})
        if kind=='a':
            tag='ref' if source.get('href') else 'seg'
            base={'target':source.get('href')} if source.get('href') else {'rend':'source-anchor'}
            if repaired and source.get('href') and source.get('class'):base['rend']='source-a'
            # Literal link classes replace the inherited source-anchor prefix.
            item=make(out,tag,attributes(source,base,repaired))
        else:item=make(out,'hi',attributes(source,{'rend':kind},True if repaired else False))
        if not repaired and kind!='a' and source.get('class'):item.set('rend',kind+' '+source.get('class'))
        item.text=source.text
        for child in source:source_grammar(child,item,repaired,images,context,True)
    elif kind in {'h1','h2','h3','h4','h5','h6','p','li','pre','td','th'}:
        tag='head' if kind.startswith('h') else {'p':'p','li':'item','pre':'ab','td':'cell','th':'cell'}[kind]
        base={} if kind in ('td','th') else {'rend':'source-'+kind}
        if repaired and kind in ('td','th') and source.get('class'):base['rend']='source-'+kind
        if kind=='th':base['role']='label'
        if source.get('colspan'):base['cols']=source.get('colspan')
        out=make(parent,tag,attributes(source,base,repaired))
        block_children=kind in ('td','th') and any(isinstance(n.tag,str) and n.tag not in INLINE|{'br','img','hr'} for n in source)
        if block_children:
            if source.text is not None:make(out,'p',{'rend':'source-leading-text'},source.text)
            for child in source:source_grammar(child,out,repaired,images,context)
        else:
            out.text=source.text
            for child in source:source_grammar(child,out,repaired,images,context,True)
    else:raise ValueError('Source grammar has no disposition for '+kind)
    if source.tail:
        if inline:
            parent[-1].tail=(parent[-1].tail or '')+source.tail
        elif source.tail.strip():make(parent,'p',{'rend':'source-interstitial-text'},source.tail)
        elif len(parent):parent[-1].tail=(parent[-1].tail or '')+source.tail
        elif parent.text is None:parent.text=source.tail
        else:parent.text+=source.tail

def expected_text(source, images, repaired):
    body=source.find('body');head=source.find('head')
    context=None
    insist(body.text is None and all(isinstance(n.tag,str) for n in body),'Unexpected body-leading text or body comment needs a located disposition')
    result=etree.Element('{'+T+'}text');front=make(result,'front');main=make(result,'body');back=make(result,'back')
    f=make(front,'div',{'type':'source-provider-header'});m=make(main,'div',{'type':'source-book-content'});b=make(back,'div',{'type':'source-provider-footer'})
    for element in body:
        if element.tag=='header':source_grammar(element,f,repaired,images,context)
        elif element.tag=='footer':
            if repaired:source_grammar(element,b,True,images,context)
            else:
                wrap=make(b,'div',{'type':'source-provider-license',X+'id':element.get('id')})
                make(wrap,'ab',{'type':'source-license-wrapper'},''.join(element.itertext()))
        else:source_grammar(element,make(m,'div',{'type':'source-body-carrier'}),repaired,images,context)
    return result

def expected_header(source, raw, original_header):
    header=etree.fromstring(etree.tostring(original_header))
    fd=header.find('t:fileDesc',NS);title=fd.find('t:titleStmt',NS)
    author=next(''.join(n.itertext()).strip().split(':',1)[1].strip() for n in source.find('body/header').iter('p') if ''.join(n.itertext()).strip().startswith('Author:'))
    make(title,'author',text=author)
    desc=fd.find('t:sourceDesc',NS)
    make(desc,'p',{'n':'source-boundary'},'One complete Samuel Wesley biography, including twenty chapters, appendices A-C, name index, 361 footnotes, transcriber notes, and provider wrapper. The unrelated John Wesley and Whitefield books are excluded.')
    make(desc,'p',{'n':'source-title-discrepancy'},'The literal HTML title names John and Charles Wesley; the retained book title and provider author identify L. Tyerman. The literal conflicting field is preserved below.')
    make(make(desc,'p',{'n':'source-html-prolog'}),'seg',{'type':'source-literal'},raw.decode('utf-8').split('<html',1)[0])
    make(make(desc,'p',{'n':'source-html-document-suffix'}),'seg',{'type':'source-literal'},raw.decode('utf-8').rsplit('</body>',1)[1])
    for label,n in [('root',source),('head',source.find('head')),('body',source.find('body')),('root-child-3-administration-comment',source[2])]:
        p=make(desc,'p',{'n':'source-'+label+'-fields'})
        for name,value in [('tag',n.tag if isinstance(n.tag,str) else '#comment'),('attributes',json.dumps(dict(n.attrib),ensure_ascii=False,sort_keys=True,separators=(',',':'))),('text',n.text),('tail',n.tail)]:
            make(p,'seg',{'type':'source-'+name,'n':'present' if value is not None else 'absent'},value)
    for i,n in enumerate(source.find('head'),1):
        p=make(desc,'p',{'n':'source-head-'+str(i)})
        for name,value in [('tag',n.tag),('attributes',json.dumps(dict(n.attrib),ensure_ascii=False,sort_keys=True,separators=(',',':'))),('text',n.text),('tail',n.tail)]:
            make(p,'seg',{'type':'source-'+name,'n':'present' if value is not None else 'absent'},value)
    return header

def expected_repair_ledger(old, new, images):
    """Independent comparison of raw-derived old/new native carrier families."""
    def nodes(region, name, token=None):
        return [n for area in region[:2] for n in area.iter('{'+T+'}'+name) if token is None or (n.get('rend') or '').split()[:1]==[token]]
    def anchors(region):
        return [n for area in region[:2] for n in area.iter() if n.tag=='{'+T+'}ref' or n.tag=='{'+T+'}seg' and (n.get('rend') or '').split()[:1]==['source-anchor']]
    def headings(region):
        return [n for area in region[:2] for n in area.iter('{'+T+'}head') if re.fullmatch('source-h[1-6]',(n.get('rend') or '').split()[0])]
    families=[('paragraph',nodes(old,'p','source-p'),nodes(new,'p','source-p')),('heading',headings(old),headings(new)),('anchor',anchors(old),anchors(new))]
    for label,tag in [('cell','cell'),('table','table'),('list','list'),('item','item')]:families.append((label,nodes(old,tag),nodes(new,tag)))
    families.append(('column',[n for n in nodes(old,'milestone') if n.get('unit')=='source-column'],[n for n in nodes(new,'milestone') if n.get('unit')=='source-column']))
    for tag in sorted(INLINE-{'a'}):families.append(('inline-'+tag,nodes(old,'hi',tag),nodes(new,'hi',tag)))
    families.append(('provider-header',[n for n in nodes(old,'div') if n.get('type')=='source-header'],[n for n in nodes(new,'div') if n.get('type')=='source-header']))
    result=[]
    for label,before,after in families:
        insist(len(before)==len(after),'Raw-derived repair family cardinality differs: '+label)
        for ordinal,(a,b) in enumerate(zip(before,after),1):
            if a.attrib!=b.attrib:result.append(dict(family=label,ordinal=ordinal,before=dict(a.attrib),after=dict(b.attrib)))
    for a,b in zip(nodes(old,'graphic'),nodes(new,'graphic')):
        member=a.get('url');result.append(dict(family='image',before=dict(a.attrib),after=dict(b.attrib),source_context='urn:ocd:retained-archive:'+ARCHIVE_SHA+':member:'+member,payload_sha256=sha(images[member])))
    return result

def authority_layout():
    rows=[('primary-html','raw/gutenberg/67980/html/pg67980-images.html','primary-source'),('retained-archive','raw/gutenberg/67980/pg67980-h.zip','retained-source-archive'),('acquisition-receipt','raw/gutenberg/67980/acquisition-receipt.json','retained-acquisition-receipt'),('retained-member-inventory','raw/gutenberg/67980/member-inventory.tsv','retained-member-inventory')]
    for filename in ['manifest.json','content.tei.xml','provenance.json','source-accountability.json','README.source.md','unresolved.jsonl']:
        name='original-tei' if filename=='content.tei.xml' else 'original-package-manifest' if filename=='manifest.json' else 'original-'+filename
        rows.append((name,LOG+'/retained-original-package/'+filename,'retained-original-package-member'))
    for name in ['validation','mutation-reproduction']:rows.append(('original-'+name,LOG+'/retained-original-'+name+'.json','historical-technical-proof'))
    for filename in ['source-manifest.json','profile.json','policy.json','README.source.md','REVIEW.md']:rows.append(('historical-'+filename,OLD+'/'+filename,'historical-source-authority'))
    rows.extend([('historical-producer','build/tei/tyerman_pg_html.py','historical-producer-lineage'),('historical-oracle','build/tei/tyerman_pg_html_oracle.py','historical-oracle-lineage'),('producer',PRODUCER,'bounded-repair-implementation'),('oracle',ORACLE,'independent-source-oracle-implementation'),('runtime',HOME+'/runtime.json','actual-execution-runtime-closure'),('profile',HOME+'/profile.json','complete-source-feature-profile'),('policy',HOME+'/policy.json','independent-validation-policy'),('readme',HOME+'/README.source.md','source-local-attribution-readme'),('tei-validation-schema','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),('tei-examples-schema','ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd','tei-schema-import'),('tei-xml-schema','ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd','tei-schema-import'),('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema')])
    return [dict(name=n,path=p,role=r) for n,p,r in rows]

def pinned(path):
    b=(ROOT/path).read_bytes();return dict(path=path,bytes=len(b),sha256=sha(b))

def locations(n,path='html'):
    yield path,n
    for i,c in enumerate(n,1):yield from locations(c,path+'/'+str(i)+':'+(c.tag if isinstance(c.tag,str) else '#comment'))

def expected_profile(source,raw,rows):
    nodes=list(locations(source));body=source.find('body');head=source.find('head')
    census=Counter((n.tag,k) for _,n in nodes if isinstance(n.tag,str) for k in n.attrib)
    return dict(contract='ocd-l637-whole-html-source-profile-v1',work_id=WORK,source_id=SOURCE_ID,scope=SCOPE,complete_html5_source_tree=tree(source),archive_members=rows,source_element_census=dict(sorted(Counter(n.tag for _,n in nodes if isinstance(n.tag,str)).items())),source_attribute_census=[dict(tag=k[0],attribute=k[1],count=v) for k,v in sorted(census.items())],source_direct_body_elements=len(body),source_body_elements=sum(1 for n in body.iter() if isinstance(n.tag,str)),source_head_children=len(head),source_prolog=raw.decode().split('<html',1)[0],source_document_suffix=raw.decode().rsplit('</body>',1)[1],correction_fields=[dict(pointer=p,attributes=dict(n.attrib),text=n.text,tail=n.tail) for p,n in nodes if n.tag=='ins'],language_fields=[dict(pointer=p,attributes=dict(n.attrib)) for p,n in nodes if n.tag=='span' and 'lang' in n.attrib],media_fields=[dict(pointer=p,attributes=dict(n.attrib),member=n.get('src'),payload_sha256=next(r['sha256'] for r in rows if r['path']==n.get('src')),archive_sha256=ARCHIVE_SHA) for p,n in nodes if n.tag=='img'],located_dispositions=[dict(pointer=p,source_fields=tree(n),disposition='Existing ordered native row/column flattening: wrapper attributes absent; formatting whitespace joined to actual adjacent carrier tails under declared grammar.') for p,n in nodes if n.tag in ('tbody','colgroup')]+[dict(pointer=p,source_fields=tree(n),disposition='Existing native grammar omits only this whitespace-only leading text field; all remaining fields are constrained by the complete source grammar.') for p,n in nodes if n.tag in ('table','ul') and n.text and not n.text.strip()]+[dict(pointer='html/3:#comment',source_fields=tree(source[2]),disposition='Located root administration after body; literal document suffix and comment fields visible in sourceDesc, not footer content.')],source_order=dict(primary_members=['pg67980-images.html'],front='provider header',body='Entire complete biography, including twenty chapters, appendices A-C, name index, 361 footnotes, transcriber notes, and all intervening text.',back='Structured complete provider footer',administration='Root/head/body fields, all 23 head children, literal prolog/document suffix, located root comment.'),original_package_members=[pinned(LOG+'/retained-original-package/'+n) for n in ['manifest.json','content.tei.xml','provenance.json','source-accountability.json','README.source.md','unresolved.jsonl']],authority_layout=authority_layout())

def contract_check(manifest,candidate):
    record=manifest.record
    insist(record['scope']==SCOPE and record['manifest_row']=='L637','Exact complete biography scope differs')
    insist(json.loads(encoded(dict(record['source_order'])))==dict(primary_members=['pg67980-images.html'],archive_members=['pg67980-images.html','images/cover.jpg','images/i_004.jpg']),'Ordered retained source members differ')
    actual=[dict(name=r['name'],path=r['path'],role=r['role']) for r in record['authorities']]
    insist(actual==authority_layout(),'Exact ordered authority roles or paths differ')
    insist(dict(candidate.manifest['converter'])==dict(record['converter']) and dict(candidate.manifest['package_schema'])==dict(record['package_schema']) and candidate.manifest['status']=='nonaccepted','Exact candidate producer/schema/status differs')
    insist(candidate.manifest['source_manifest']['path']==HOME+'/source-manifest.json','Exact candidate source-manifest path differs')
    producer=record['converter'];oracle=record['validator']
    insist(dict(producer)==dict(id='ocd-l637-retained-component-bounded-repair',version='1',callable='_convert',implementation_path=PRODUCER,implementation_sha256=sha(manifest.authority_path('producer').read_bytes())),'Exact composite producer identity differs')
    insist(dict(oracle)==dict(id='ocd-l637-whole-source-retained-repair-oracle',version='1',callable='_oracle',implementation_path=ORACLE,implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=sha(manifest.authority_path('runtime').read_bytes())),'Exact independent oracle identity/closure differs')
    historical=json.loads(manifest.authority_path('original-package-manifest').read_bytes())
    insist(sha(manifest.authority_path('original-package-manifest').read_bytes())=='aee7d82a4fe8d29a3ce5194e3d140c6089255187bd8d0586a3e7616993803a9d','Retained historical package manifest differs')
    insist(sha(manifest.authority_path('original-tei').read_bytes())=='662440d5db82595db3fd28b7fd42cc73dc7af27cb8a2a6775709a7ec419058d6','Retained historical TEI differs')
    for item in historical['members']:
        name='original-tei' if item['name']=='content.tei.xml' else 'original-'+item['name']
        b=manifest.authority_path(name).read_bytes();insist(len(b)==item['bytes'] and sha(b)==item['sha256'],'Historical member inventory differs: '+item['name'])

def expected_policy():
    provenance=dict(provider='Project Gutenberg',ebook_id='67980',manifest_row='L637',attribution='L. Tyerman; Project Gutenberg; KD Weeks, Brian Wilson, and the Online Distributed Proofreading Team at https://www.pgdp.net; source images credited to The Internet Archive/American Libraries.',rights='The retained source states public domain in the USA and requires local-law review outside the United States. No human rights clearance or publication authorization is implied.',source_archive_sha256=pinned('raw/gutenberg/67980/pg67980-h.zip')['sha256'],complete_work_boundary=SCOPE,modifications='Exact retained original TEI component plus bounded source-backed attribute repairs, self-contained image payloads, structured provider footer, and readable located head/prolog/root administration; source wording is preserved.',composite_producer=dict(original_package_manifest=pinned(LOG+'/retained-original-package/manifest.json'),original_tei=pinned(LOG+'/retained-original-package/content.tei.xml'),historical_converter=pinned('build/tei/tyerman_pg_html.py'),bounded_repair=pinned(PRODUCER),recipe='Use retained original content.tei.xml plus exact retained HTML/archive with build.tei.tyerman_samuel_retained_repair._convert through the maintained reconstruct_candidate CLI. The shared historical converter is lineage, not the sole current producer.'))
    policy=dict(contract='ocd-l637-whole-source-bounded-repair-policy-v1',work_id=WORK,source_id=SOURCE_ID,scope=SCOPE,provenance=provenance,repair_scope='63 literal correction title attributes; 52 span language attributes; actual source presentation classes and 25 column styles; provider header language; two exact retained JPEG payloads with archive/member URN context; full structured provider footer; all head/root/prolog/document suffix administration. No source text correction.',image_context='The source meta dcterms.source is retained metadata, not an asserted document base. Each graphic embeds exact JPEG bytes and names the exact retained archive SHA and member via corresp URN. No network xml:base is asserted.',parser_policy='HTML5 CRLF/CR normalization to LF; strict independent lexical corroboration permits exactly five known document-formatting differences. Table sections retain ordered native rows/columns and exact declared whitespace joins, with located wrapper disposition. No visual CSS/print-layout claim.',unresolved=[dict(kind='human-review',message='Technical nonaccepted candidate only; human acceptance, rights and attribution applicability remain open.'),dict(kind='visual-review',message='Print-page facsimile comparison, CSS rendering fidelity, and CVW visual review remain open.'),dict(kind='source-metadata-discrepancy',message='The literal HTML title miscredits John and Charles Wesley as authors; retained primary h1 and provider author identify the Samuel Wesley biography by L. Tyerman. Both literal fields are retained.')])
    return policy

EXPECTED_README=b'# Retained source: The Life and Times of the Rev. Samuel Wesley, M.A.\n\nOne complete authored biography by L. Tyerman, published in 1866, from the already retained Project Gutenberg eBook 67980. This successor preserves the exact original six-member v4 package and source authorities as historical lineage. It repairs the existing TEI; it does not acquire another text.\n\nCredits: KD Weeks, Brian Wilson, and the Online Distributed Proofreading Team at https://www.pgdp.net. The retained provider credits source images to The Internet Archive/American Libraries. Attribution to L. Tyerman and Project Gutenberg, the entire structured provider license footer, provider credits, transcriber notices, and all source wording remain represented. The source states public domain in the USA; people outside the United States must check applicable local laws. Technical validation is not rights clearance, human acceptance, or publication authorization.\n\nThe actual primary title and provider creator control the biography identity. The conflicting HTML title that names John and Charles Wesley is preserved as located metadata. All twenty chapters, appendices A-C, name index, 361 footnotes, and transcriber notes remain in source order.\n\nThe 63 literal correction tooltips, 52 span language attributes, actual presentation classes and column styles are preserved. Both graphic payloads are exact retained JPEGs, embedded without a network request. Each corresp URN names its retained archive SHA and member; provider dcterms.source remains separate metadata and supplies no assumed network base. Empty image alt attributes remain explicitly empty.\n\nAll 23 head children, root/head/body fields, literal prolog and document suffix, and the ppgen comment at HTML root child 3 are visible source administration. The comment is not provider footer content. An independent lexical reader corroborates the entire source tree after declared HTML newline normalization and exactly five document-formatting recovery differences. Whitespace-only table/list leading fields are explicitly located and dispositioned. Table-section wrappers are located and accounted for; the inherited native grammar flattens those formatting wrappers while preserving row/column order and exact declared whitespace joins.\n\nThe full repaired actual object is checked against the retained source. The separate byte inverse restores the verified original header/footer baseline and reverses observed carrier attributes; byte inversion alone does not establish repaired footer fidelity. Browser CSS, print-page visual fidelity, and human review remain open. This is a nonaccepted candidate; canonical installation is a separate reviewed action.\n'

def runtime_guard(manifest):
    from ocd_kernel.lib.path_io import resolve_path
    record=json.loads(manifest.authority_path('runtime').read_bytes())
    insist(record.get('contract')=='ocd-l637-actual-runtime-closure-v1','Exact runtime closure contract differs')
    executable=resolve_path(Path(sys.executable),strict=True)
    insist(record['runtime_executable']==dict(path=executable.as_posix(),bytes=executable.stat().st_size,sha256=sha(executable.read_bytes())),'Executed Python runtime differs')
    root=resolve_path(ROOT,strict=True);library=resolve_path(Path('D:/Library/Open Christian Data'),strict=True)
    local={resolve_path(ROOT/r['path'],strict=True):r['sha256'] for r in record['first_party_files']};external={resolve_path(Path(r['path']),strict=True):r['sha256'] for r in record['external_runtime_files']}
    observed=[]
    for module in sys.modules.copy().values():
        path=getattr(module,'__file__',None)
        if path:
            p=resolve_path(Path(path),strict=True);allowed=local if p.is_relative_to(root) or p.is_relative_to(library) else external
            insist(p in allowed and sha(p.read_bytes())==allowed[p],'Unexpected or changed executed oracle dependency: '+p.as_posix());observed.append(p.as_posix())
    return sorted(set(observed))

def check(manifest, candidate):
    insist(manifest.record['work_id']==WORK and manifest.record['source_id']==SOURCE_ID,'Exact work/source identity differs')
    insist(candidate.manifest['source_id']==SOURCE_ID and candidate.manifest['source_manifest']['sha256']==manifest.sha256,'Exact candidate/source contract differs')
    manifest.verify();runtime_guard(manifest)
    contract_check(manifest,candidate)
    profile=json.loads(manifest.authority_path('profile').read_bytes());policy=json.loads(manifest.authority_path('policy').read_bytes())
    insist(policy==expected_policy(),'Exact qualified composite policy/provenance/producer lineage differs')
    insist(manifest.authority_path('readme').read_bytes()==EXPECTED_README,'Exact human-visible source attribution/permission/disposition document differs')
    with ZipFile(manifest.authority_path('retained-archive')) as archive:
        insist(archive.testzip() is None,'Archive CRC differs')
        rows=[dict(path=n.filename,bytes=n.file_size,compressed_bytes=n.compress_size,crc32=f'{n.CRC:08x}',sha256=sha(archive.read(n))) for n in archive.infolist() if not n.is_dir()]
        insist(rows==profile['archive_members'],'Full archive member/order/bytes/CRC differs')
        raw=archive.read('pg67980-images.html');images={p:archive.read(p) for p in ('images/cover.jpg','images/i_004.jpg')}
    insist(sha(manifest.authority_path('retained-archive').read_bytes())==ARCHIVE_SHA,'Exact retained archive differs')
    insist(raw==manifest.authority_path('primary-html').read_bytes(),'Extracted usable primary witness differs from retained member')
    source=html5lib.parse(raw,treebuilder='etree',namespaceHTMLElements=False)
    corroboration=lexical_corroboration(raw,source)
    insist(profile==expected_profile(source,raw,rows),'Complete source profile fields, census, located dispositions, media/correction/language records, scope, or original lineage differ')
    original=manifest.authority_path('original-tei').read_bytes();old=etree.fromstring(original,etree.XMLParser(resolve_entities=False,no_network=True))
    original_expected=expected_text(source,images,False)
    insist(tree(old.find('t:text',NS))==tree(original_expected),'Original retained actual graph does not reconcile with complete source grammar')
    actual_raw=candidate.member_bytes('content.tei.xml');actual=etree.fromstring(actual_raw,etree.XMLParser(resolve_entities=False,no_network=True))
    expected=etree.Element('{'+T+'}TEI',nsmap={None:T});expected.set(X+'lang','en')
    expected.append(expected_header(source,raw,old.find('t:teiHeader',NS)));expected.append(expected_text(source,images,True))
    insist(tree(actual)==tree(expected),'Complete actual TEI envelope/header/body direct fields, attributes, order, or attachment differ')
    # Restore the independently verified original header/footer baseline, then
    # reverse observed carrier attributes. Byte inverse is conservation evidence;
    # the separate full raw-derived graph check proves repaired footer fidelity.
    inverse=etree.fromstring(actual_raw,etree.XMLParser(resolve_entities=False,no_network=True))
    def reverse(a,b,c):
        insist(a.tag==b.tag==c.tag,'Inverse carrier tag differs')
        if a.attrib!=b.attrib:
            for key in list(c.attrib):
                if key not in b.attrib:c.attrib.pop(key)
            for key,value in b.attrib.items():c.set(key,value)
        insist(a.text==c.text and a.tail==c.tail,'Inverse observed text/tail differs')
        if len(a)!=len(b):raise ValueError('Unexpected changed inverse child cardinality')
        for aa,bb,cc in zip(a,b,c):reverse(aa,bb,cc)
    new_text=inverse.find('t:text',NS);old_text=old.find('t:text',NS)
    new_text[-1].remove(new_text[-1][0]);new_text[-1].insert(0,etree.fromstring(etree.tostring(old_text[-1][0])))
    for n in list(new_text[-1])[1:]:new_text[-1].remove(n)
    repaired_expected=expected_text(source,images,True)
    for region in (0,1):reverse(repaired_expected[region],original_expected[region],new_text[region])
    inverse.remove(inverse[0]);inverse.insert(0,etree.fromstring(etree.tostring(old[0])))
    restored=etree.tostring(inverse,encoding='UTF-8',xml_declaration=True)
    insist(restored==original,'Full original TEI component byte inverse differs')
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path('tei-validation-schema'))))
    insist(schema.validate(actual),'TEI P5 source candidate differs: '+str(schema.error_log.last_error))
    ids=[n.get(X+'id') for n in actual.iter() if n.get(X+'id')];insist(len(ids)==len(set(ids)),'Global XML IDs duplicate')
    for ref in actual.iter('{'+T+'}ref'):
        target=ref.get('target','')
        if target.startswith('#'):insist(target[1:] in set(ids),'Literal local target lacks actual ID '+target)
    insist(candidate.member_bytes('README.source.md')==manifest.authority_path('readme').read_bytes(),'Full current README authority differs')
    provenance=dict(policy['provenance']);provenance['source_manifest_sha256']=manifest.sha256
    insist(json.loads(candidate.member_bytes('provenance.json'))==provenance,'Composite repair provenance differs')
    insist(candidate.member_bytes('unresolved.jsonl')==b''.join(encoded(n) for n in policy['unresolved']),'Qualified unresolved ledger differs')
    account=json.loads(candidate.member_bytes('source-accountability.json'))
    expected_account=dict(contract='ocd-l637-retained-repair-accounting-v1',work_id=WORK,source_id=SOURCE_ID,source_manifest_sha256=manifest.sha256,original_tei_sha256=sha(original),repaired_tei_sha256=sha(actual_raw),changed_attribute_families=expected_repair_ledger(original_expected,repaired_expected,images),replaced_footer_sha256=sha(etree.tostring(old.find('t:text/t:back/t:div[@type="source-provider-footer"]',NS)[0])),profile_sha256=sha(manifest.authority_path('profile').read_bytes()),policy_sha256=sha(manifest.authority_path('policy').read_bytes()),producer_sha256=sha(manifest.authority_path('producer').read_bytes()),original_package_manifest_sha256=sha(manifest.authority_path('original-package-manifest').read_bytes()))
    insist(account==expected_account,'Complete repair ledger or authority bindings differ')
    observed=runtime_guard(manifest)
    return dict(status='pass',complete_works=1,textual_members=1,archive_members=3,source_body_elements=corroboration['body_elements'],corrections=63,span_languages=52,images=2,whole_actual_tree_source_checked=True,full_original_tei_byte_inverse=True,inverse_qualification='Original header/footer baseline restored after independent full repaired graph check; byte inverse alone does not prove repaired footer fidelity.',original_tei_sha256=sha(original),actual_tei_sha256=sha(actual_raw),raw_lexical_corroboration=corroboration,actual_execution_paths=observed,independence='Oracle imports no producer or producer mapping helpers. Complete source-owned carrier grammar and lexical parser independently constrain every actual tree field. Shared HTML5 model and inherited grammar are declared, with independent balanced raw lexical corroboration. No print/visual acceptance claim.')

def _oracle(manifest,candidate):
    result=check(manifest,candidate)
    roles={a['role']:a for a in manifest.record['authorities']}
    att=dict(status='pass',oracle_id='ocd-l637-whole-source-retained-repair-oracle',oracle_version='1',implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=sha(manifest.authority_path('runtime').read_bytes()),runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,source_sha256=roles['primary-source']['sha256'],profile_sha256=roles['complete-source-feature-profile']['sha256'],policy_sha256=roles['independent-validation-policy']['sha256'],xsd_sha256=roles['tei-validation-schema']['sha256'],package_schema_sha256=roles['candidate-package-schema']['sha256'],findings=[])
    att['result_sha256']=sha(encoded(att));return att

_oracle.oracle_id='ocd-l637-whole-source-retained-repair-oracle'
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
