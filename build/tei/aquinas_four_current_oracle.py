"""Independent literal HTML/unit reader with explicit historical hierarchy reuse."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json,re
from lxml import etree,html
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts
ORACLE_ID='ocd-aquinas-four-current-independent-v1'; ORACLE_VERSION='1'
NS='{http://www.tei-c.org/ns/1.0}'; XML='{http://www.w3.org/XML/1998/namespace}'
def canonical(v):return (json.dumps(v,ensure_ascii=False,separators=(',',':'),sort_keys=True)+'\n').encode()
def closure_sha(root):
    names=['build/tei/aquinas_four_current_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','build/lib/tei_xsd.py']
    return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in names])).hexdigest()
def _observe_inline(source,target):
    if source.text!=target.text or len(source)!=len(target):raise ValueError('Literal source wording/inline arity differs')
    for a,b in zip(source,target,strict=True):
        wanted='hi' if a.tag=='i' else 'lb' if a.tag=='br' else None
        if wanted is None or b.tag!=NS+wanted or a.attrib or dict(b.attrib)!=({'rend':'italic'} if a.tag=='i' else {}):raise ValueError('Literal source inline carrier/attributes differ')
        _observe_inline(a,b)
        if a.tail!=b.tail:raise ValueError('Literal source inline tail differs')
def semantic_ownership(units,projected,part,pg):
    """Derive question/article intervals from literal labels and closed omissions."""
    text=[' '.join(''.join(n.itertext()).split()) for n in units]
    question_starts={i:int(m.group(1)) for i,value in enumerate(text) if (m:=re.fullmatch(r'QUESTION (\d+)',value))}
    # This duplicate source QUESTION23 is explicitly an article in Q23, not Q24.
    for i,n in enumerate(units):
        if pg==17897 and n.get('id')=='id01743':question_starts.pop(i,None)
    missing={17611:[116],17897:[1],18755:[183],19950:[]}[pg]
    for number in missing:
        first=next(i for i,value in enumerate(text) if 'ARTICLE [' in value and re.search(r'\bQ[.,]?\s*'+str(number)+r'\b',value,re.I))
        title=next(i for i in range(first-1,-1,-1) if re.search(r'\([Ii]n [A-Za-z-]+ Articles?\)$',text[i].rstrip(' _')))
        question_starts[title]=number
    # Two source one-article sections lack their own article headings.
    implicit={17611:{'id04760','id04775'},17897:{'id01743'},18755:set(),19950:set()}[pg]
    article_starts={i for i,value in enumerate(text) if (not value.startswith('>') and 'ARTICLE [' in value and value.endswith(']')) or re.fullmatch(r'[A-Z-]+ ARTICLE',value) or units[i].get('id') in implicit}
    q=None; article=None; ordinal=0; relationships=[]
    for i,(source,target) in enumerate(zip(units,projected,strict=True)):
        if text[i].startswith('TREATISE ON ') and '(QQ.' in text[i]:q=None;article=None;ordinal=0
        if pg==19950 and source.get('id')=='id01912':q=None;article=None;ordinal=0
        if i in question_starts:q=question_starts[i];article=None;ordinal=0
        if i in article_starts:
            if q is None:raise ValueError('Source-derived article has no question')
            ordinal+=1;article=ordinal
        ancestors=list(target.iterancestors()); actualq=next((n.get('n') for n in ancestors if n.tag==NS+'div' and n.get('type')=='question'),None); actuala=next((n.get('n') for n in ancestors if n.tag==NS+'div' and n.get('type')=='article'),None)
        if (actualq,actuala)!=(str(q) if q is not None else None,str(article) if article is not None else None):raise ValueError('Source question/article attachment differs pg'+str(pg)+'/'+source.get('id')+' expected '+str((q,article))+' observed '+str((actualq,actuala)))
        relationships.append(dict(source_id=source.get('id'),question=q,article=article))
    return relationships
def check(manifest,raw,accountability=None):
    manifest.verify();profile=json.loads(manifest.authority_path('profile').read_bytes())
    old=manifest.authority_path('historical-candidate').read_bytes()
    if sha256(old).hexdigest()!=profile['historical_candidate_sha256']:raise ValueError('Historical handoff changed')
    if raw.split(b'</teiHeader>',1)[1]!=old.split(b'</teiHeader>',1)[1]:raise ValueError('Source-proven whole historical text tree/bytes changed')
    a=raw.index(b'<teiHeader');b=raw.index(b'</teiHeader>')+len(b'</teiHeader>')
    if raw[a:b]!=manifest.authority_path('fresh-header').read_bytes():raise ValueError('Explicit header renewal differs')
    target=etree.fromstring(raw); parts=target.findall(NS+'text/'+NS+'body/'+NS+'div')
    if len(parts)!=4 or [n.get('subtype') for n in parts]!=[n['code'] for n in profile['components']]:raise ValueError('Four-part scope/order differs')
    ledger=[]; counts=[]
    for spec,part in zip(profile['components'],parts,strict=True):
        source=manifest.authority_path('source-html-'+str(spec['position'])).read_bytes()
        if sha256(source).hexdigest()!=spec['source_sha256']:raise ValueError('Exact primary HTML changed')
        doc=html.fromstring(source);body=doc.xpath('//body')[0]
        units=[n for n in body if isinstance(n.tag,str) and n.tag not in ('header','footer')]
        projected=[n for n in part.iter() if n.get('corresp','').split('#')[-1].startswith('id') and '#id' in n.get('corresp','')]
        if len(units)!=spec['units'] or len(units)!=len(projected):raise ValueError('Source-unit count differs')
        for position,(left,right) in enumerate(zip(units,projected,strict=True)):
            if right.get(XML+'id')!='pg'+str(spec['pg_id'])+'-'+left.get('id') or right.get('corresp')!='https://www.gutenberg.org/cache/epub/'+str(spec['pg_id'])+'/pg'+str(spec['pg_id'])+'-images.html#'+left.get('id'):raise ValueError('Literal source-unit identity/order differs')
            kind=right.tag.removeprefix(NS)
            if kind not in ('head','p') or (left.tag.startswith('h') and kind=='p' and right.get('rend')!='source-'+left.tag):raise ValueError('Source heading carrier/rend differs')
            _observe_inline(left,right)
        elements=[n for n in doc.iter() if isinstance(n.tag,str)]; positions={n:i+1 for i,n in enumerate(elements)}
        for node in elements:
            ancestor=node
            while ancestor.getparent() is not None and ancestor.getparent().tag!='body':ancestor=ancestor.getparent()
            selected=ancestor.getparent() is not None and ancestor.getparent().tag=='body' and ancestor.tag not in ('header','footer')
            ledger.append(dict(component=spec['code'],ordinal=positions[node],parent=positions.get(node.getparent()),tag=node.tag,attributes=list(node.attrib.items()),text=node.text,tail=node.tail,disposition='book-content' if selected else 'retained-provider-or-document-context',source_unit_id=ancestor.get('id') if selected else None,target_unit_id='pg'+str(spec['pg_id'])+'-'+ancestor.get('id') if selected else None))
        ownership=semantic_ownership(units,projected,part,spec['pg_id'])
        counts.append(dict(pg_id=spec['pg_id'],source_units=len(units),italic_spans=sum(len(n.findall('.//i')) for n in units),line_breaks=sum(len(n.findall('.//br')) for n in units),questions=len(part.findall('.//'+NS+'div[@type="question"]')),articles=len(part.findall('.//'+NS+'div[@type="article"]')),independent_source_ownership_sha256=sha256(canonical(ownership)).hexdigest()))
    header=target.find(NS+'teiHeader'); bibl=header.findall(NS+'fileDesc/'+NS+'sourceDesc/'+NS+'bibl')
    if [etree.tostring(n,with_tail=False).decode() for n in bibl[:4]]!=profile['bibliographic_payloads']:raise ValueError('Original bibliographic payloads/IDs changed')
    taxonomy=header.find('.//'+NS+'list')
    if taxonomy is None or taxonomy.get(XML+'id')!=profile['taxonomy_id'] or [dict(id=n.get(XML+'id'),label=n.text) for n in taxonomy]!=profile['taxonomy_labels']:raise ValueError('Original generated analysis labels/IDs changed')
    allids={n.get(XML+'id') for n in target.iter() if n.get(XML+'id')}
    if any(value[1:] not in allids for n in target.iter() for value in n.get('ana','').split() if value.startswith('#')):raise ValueError('Body analysis link unresolved')
    if accountability is not None:
        actual=json.loads(accountability)
        original_account=json.loads(manifest.authority_path('historical-accounting').read_bytes())
        for key in ('validation','tei_relaxng_sha256','candidate_bytes','candidate_sha256'):original_account.pop(key,None)
        if canonical(actual.get('nodes'))!=canonical(ledger):raise ValueError('Whole source ledger differs')
        if actual.get('historical_semantic_accounting')!=original_account:raise ValueError('Historical semantic accounting differs '+str([k for k in set(original_account)|set(actual.get('historical_semantic_accounting',{})) if original_account.get(k)!=actual.get('historical_semantic_accounting',{}).get(k)]))
    from build.lib.tei_xsd import compiled_tei_schema
    compiled_tei_schema(manifest.authority_path('tei-p5-xsd')).assertValid(target)
    return dict(status='pass',source_elements=len(ledger),source_units=sum(c['source_units'] for c in counts),components=counts,whole_historical_text_bytes_conserved=True,literal_selected_source_payloads_and_inline_checked=True,complete_html_context_ledger_checked=True,p5='pass',qualification='No producer import. Historical semantic hierarchy is reused unchanged and separately coordinator-reviewed; literal HTML wording/inline/order/IDs independently checked here. Source-unit outer layout tails/style and wrappers retained in full ledger, not rendered as authored book text. Same lxml HTML parser assumptions disclosed; root independent source corroboration required before installation.')
def _oracle(manifest,candidate):
    candidate.verify_integrity();profile=json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256:raise ValueError('Current source manifest binding differs')
    check(manifest,candidate.member_bytes('content.tei.xml'),candidate.member_bytes('source-accountability.json'))
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('Source-directed notice changed')
    if [json.loads(row) for row in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:raise ValueError('Unassessed claims changed')
    expected=dict(work_id=profile['work_id'],source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted',historical_body_reproduced_unchanged=True,header_only_renewal=True)
    if json.loads(candidate.member_bytes('provenance.json'))!=expected:raise ValueError('Provenance changed')
    members=sorted([dict(name=a['name'],path=a['path'],bytes=a['bytes'],sha256=a['sha256']) for a in manifest.record['authorities'] if a['role']=='primary-source'],key=lambda a:(a['path'],a['name']))
    source_digest=sha256(canonical(dict(contract='ocd-source-member-set-v1',members=members))).hexdigest()
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=source_digest,profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
