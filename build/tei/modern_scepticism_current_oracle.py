"""Independent inverse check of the complete retained PG42957 handoff.

This checker does not import the converter. Actual original source fidelity is
the dated HTML5 oracle proof, not a claim that an inverse proves HTML parsing.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
import html5lib

NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
SOURCE_SHA='e8130d330cc70a9f1169ef888869dbd7b146ff78b5b1bef0e8d56cc5995206e8'
HISTORICAL_SHA='b82c494679c3d3f4e6628060e107b51f0fe72fee2105cc5da6b2b5fef798d0c3'
ORACLE_ID='ocd-modern-scepticism-complete-inverse-independent-v1'
ORACLE_VERSION='1'
BLOCK_TAGS={'ab','cell','div','head','item','l','lg','list','note','p','quote','row','table'}

def canonical(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def parse(raw):return etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))
def raw_text(n):
    pieces=[n.text or '']
    for c in n:
        pieces.append(raw_text(c));pieces.append(c.tail if c.tail is not None else (' ' if etree.QName(c).localname in BLOCK_TAGS else ''))
    return ''.join(pieces)

def inspect(source_bytes,historical_bytes,candidate_bytes):
    if sha256(source_bytes).hexdigest()!=SOURCE_SHA or sha256(historical_bytes).hexdigest()!=HISTORICAL_SHA:
        raise ValueError('Independent exact source/historical binding differs')
    old=parse(historical_bytes);new=parse(candidate_bytes)
    if old.tag!=new.tag or dict(old.attrib)!=dict(new.attrib):raise ValueError('Independent TEI envelope differs')
    a=old.find(NS+'text');b=deepcopy(new.find(NS+'text'))
    if a is None or b is None:raise ValueError('Independent complete text absent')
    aa=list(a.iter());bb=list(b.iter())
    if len(aa)!=len(bb):raise ValueError('Independent complete carrier count differs')
    changes=[];counts={'rules':0,'headings':0,'thought_breaks':0,'row_renditions':0}
    for position,(x,y) in enumerate(zip(aa,bb),1):
        if x.tag!=y.tag or x.text!=y.text or x.tail!=y.tail or len(x)!=len(y):
            raise ValueError('Independent exact tag/text/tail/hierarchy differs at '+str(position))
        expected=dict(x.attrib);kind=None
        if x.tag==NS+'milestone' and x.get('unit')=='rule':expected['unit']='horizontal-rule';kind='rules'
        elif x.tag==NS+'ab' and x.get('type') in ('h1','h2','h3'):expected['type']='source-'+x.get('type');kind='headings'
        elif x.tag==NS+'ab' and x.get('type')=='thought_break':expected.update(type='source-block',subtype='thought_break');kind='thought_breaks'
        elif x.tag==NS+'row' and x.get('rend')=='smaller':expected.pop('rend');expected['ana']='urn:ocd:pg42957:legacy-row-rend:smaller';kind='row_renditions'
        if dict(y.attrib)!=expected:raise ValueError('Independent exact carrier attributes differ at '+str(position))
        if kind:
            counts[kind]+=1;changes.append({'text_preorder_position':position,'tag':etree.QName(x).localname,'before':dict(x.attrib),'after':dict(y.attrib)})
            y.attrib.clear();y.attrib.update(x.attrib)
    if counts!={'rules':33,'headings':21,'thought_breaks':4,'row_renditions':1}:
        raise ValueError('Independent closed alias count differs')
    if etree.tostring(a)!=etree.tostring(b):raise ValueError('Independent whole text inverse bytes differ')
    # Direct source semantics for the changed carrier families. The prior
    # whole-body source proof remains separately pinned and qualified.
    html=html5lib.parse(source_bytes.decode('utf-8-sig'),namespaceHTMLElements=False);body=html.find('body')
    rules=[n for n in body.iter() if n.tag=='hr']
    thought=[n for n in body.iter('div') if 'tb' in n.get('class','').split()]
    styled_rows=[n for n in body.iter('tr') if n.get('class')=='smaller']
    if len(rules)!=33 or len(thought)!=4 or len(styled_rows)!=1:raise ValueError('Independent primary alias semantics census differs')
    source_headings=[(n.tag,' '.join(''.join(n.itertext()).split())) for n in body.iter() if n.tag in ('h1','h2','h3')]
    target_headings=[(n.get('type'),' '.join(''.join(n.itertext()).split())) for n in aa if n.tag==NS+'ab' and n.get('type') in ('h1','h2','h3')]
    if any(h not in source_headings for h in target_headings):raise ValueError('Independent literal alias heading level/text not source-backed')
    normalized=' '.join(raw_text(a).split())
    if len(normalized)!=731071 or sha256(normalized.encode()).hexdigest()!='b209892366efef6da858b515d2bd640323499b0d5496db766b0cb4755c0d354c':
        raise ValueError('Independent historical source-normalized text differs')
    return {'status':'pass','text_nodes':len(aa),'alias_counts':counts,'aliases':changes,
            'historical_candidate_sha256':HISTORICAL_SHA,'candidate_sha256':sha256(candidate_bytes).hexdigest(),
            'whole_text_inverse_byte_equal':True,'source_normalized_characters':len(normalized),
            'source_normalized_sha256':sha256(normalized.encode()).hexdigest(),
            'full_scope':'4 front units, 11 lectures + explanatory paper, 4 back units; 181 notes, 526 page labels, complete contents/printer/transcriber/provider markers',
            'source_fidelity_basis':'Dated unchanged independent HTML5 source oracle and 10 mutation results reused, corroborated by exact source/profile/historical-body pins; current checker independently checks aliases and wholetext inverse.',
            'producer_imported':False}

def closure_sha(root):
    from ocd_kernel.library._common import io_path
    names=['build/tei/modern_scepticism_current_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','build/lib/tei_xsd.py']
    return sha256(canonical([{'path':p,'sha256':sha256(io_path(root/p).read_bytes()).hexdigest()} for p in names])).hexdigest()

def check(manifest,raw):
    manifest.verify();profile=json.loads(manifest.authority_path('profile').read_bytes())
    result=inspect(manifest.authority_path('primary-source').read_bytes(),manifest.authority_path('historical-candidate').read_bytes(),raw)
    if etree.tostring(parse(raw).find(NS+'teiHeader'),encoding='unicode')!=profile['header_xml']:raise ValueError('Independent fresh qualified header differs')
    from build.lib.tei_xsd import compiled_tei_schema
    compiled_tei_schema(manifest.authority_path('tei-p5-xsd')).assertValid(etree.ElementTree(parse(raw)))
    result['p5']='pass'
    return result

def _oracle(manifest,candidate):
    from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts
    candidate.verify_integrity();profile=json.loads(manifest.authority_path('profile').read_bytes())
    if candidate.manifest['source_manifest']['sha256']!=manifest.sha256:raise ValueError('Independent current manifest binding differs')
    check(manifest,candidate.member_bytes('content.tei.xml'))
    account=json.loads(manifest.authority_path('historical-accounting').read_bytes())
    account['current_native_aliases']={'historical_candidate_sha256':HISTORICAL_SHA,'counts':profile['alias_counts'],'inverse':'Restore only the aliases on 59 declared carriers; text tree becomes exact historical text tree.'}
    if json.loads(candidate.member_bytes('source-accountability.json'))!=account:raise ValueError('Independent package accounting differs')
    if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('Independent visible credit differs')
    expected={'work_id':manifest.record['work_id'],'edition_id':manifest.record['edition_id'],'acquisition_id':manifest.record['acquisition_id'],'source_sha256':SOURCE_SHA,'status':'nonaccepted','publication':'not-authorized','historical_body_reused':True}
    if json.loads(candidate.member_bytes('provenance.json'))!=expected or candidate.member_bytes('unresolved.jsonl')!=manifest.authority_path('historical-unresolved').read_bytes():raise ValueError('Independent provenance/unresolved claims differ')
    facts=MechanicalFacts(validator_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),validator_import_closure_sha256=closure_sha(manifest.repository_root),source_sha256=SOURCE_SHA,profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
