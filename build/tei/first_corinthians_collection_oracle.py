"""Independently verify all literal source nodes, mapped attributes and complete scope."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei.npnf_chrysostom_oracle import _verify_node, _expected_attributes, _target_tag, _selector
from ocd_kernel.tei.validate import validate_file

ORACLE_ID='ocd-first-corinthians-complete-collection-source-oracle'
ORACLE_VERSION='1'
NS='{http://www.tei-c.org/ns/1.0}'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def _oracle(manifest,candidate):
    profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
    policy=json.loads(manifest.authority_path('validation-policy').read_bytes())
    raw=manifest.authority_path('retained-thml').read_bytes();findings=[]
    try:
        lx=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False))
        matches=lx.xpath('/ThML/ThML.body/div1[@id="iv"]')
        if len(matches)!=1:raise ValueError('complete source collection absent or repeated')
        selected=matches[0]
        if len(selected)!=45 or len(list(selected.iter()))!=5008 or selected[0].get('id')!='iv.i' or selected[-1].get('id')!='iv.xlv' or sum(n.get('type')=='Homily' for n in selected)!=44:raise ValueError('source collection cardinality/boundary differs')
        doc=etree.fromstring(candidate.member_bytes('content.tei.xml'))
        body=doc.find(NS+'text/'+NS+'body')
        if body is None or len(body)!=1 or body[0].get('{http://www.w3.org/XML/1998/namespace}id')!='npnf112-iv':raise ValueError('candidate must retain exactly one complete First Corinthians collection')
        original=etree.fromstring(manifest.authority_path('historical-content').read_bytes())
        historical_roots=original.find(NS+'text/'+NS+'body')
        offset=0
        for oldroot in historical_roots:
            if oldroot.get('{http://www.w3.org/XML/1998/namespace}id')=='npnf112-iv':break
            offset+=sum(n.tag!=NS+'head' for n in oldroot.iter())
        if offset!=32042 or profile['original_global_ordinal_offset']!=offset:raise ValueError('original historical global ordinal offset differs')
        count=[offset];_verify_node(selected,body[0],member='npnf112',work_id=profile['work_id'],number=count,is_work_root=True)
        source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
        nodes=[n for n in source.find('ThML.body') if n.get('id')=='iv'];ledger=[]
        def walk(n,parent):
            ledger.append(dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',parent=parent,children=[c.get('id') for c in n]))
            for c in n:walk(c,n.get('id'))
        walk(nodes[0],None)
        accounting=json.loads(candidate.member_bytes('source-accountability.json'))
        if ledger!=accounting['literal_source_nodes'] or accounting['elements']!=5008 or accounting['scope']!=profile['scope']:raise ValueError('literal source/accounting scope mismatch')
        for id,literal in profile['context_literals'].items():
            found=[n for n in source.iter() if n.get('id')==id]
            if len(found)!=1 or ''.join(found[0].itertext())!=literal:raise ValueError('literal primary credit/context mismatch: '+id)
        expected_rows=[];by_node={}
        def cross(n,parent_feature,parent_id,position,isroot):
            ordinal=profile['original_global_ordinal_offset']+len(expected_rows)+1;fid=f'npnf-chrysostom-feature-{ordinal:05d}'
            attrs,dispositions=_expected_attributes(n,'npnf112',ordinal,profile['work_id'],is_work_root=isroot)
            expected_rows.append(dict(ordinal=ordinal,feature_id=fid,member='npnf112',work_id=profile['work_id'],source_selector=_selector(n),source_tag=n.tag,source_xml_id=n.get('id'),source_attributes=dict(n.attrib),text_present=n.text is not None,text_sha256=sha256((n.text or '').encode()).hexdigest(),tail_present=n.tail is not None,tail_sha256=sha256((n.tail or '').encode()).hexdigest(),tei_tag=_target_tag(n),tei_xml_id=attrs['xml:id'],tei_parent_id=parent_id,tei_child_ordinal=position,tei_attributes=attrs,attribute_dispositions=dispositions,tei_selector='#'+attrs['xml:id'],parent_feature_id=parent_feature,source_title_head=n.get('title') if str(n.tag).startswith('div') else None,disposition='represented'))
            for i,c in enumerate(n,1):cross(c,fid,attrs['xml:id'],i+(1 if n.get('title') is not None else 0),False)
        cross(selected,None,'npnf-chrysostom-assigned-body',1,True)
        if expected_rows!=accounting['crosswalk']:raise ValueError('full original attribute disposition/crosswalk mismatch')
        envelope=[dict(position=i,id=n.get('id'),tag=n.tag,title=n.get('title'),elements=sum(isinstance(c.tag,str) for c in n.iter()),c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='complete-selected-collection' if n.get('id')=='iv' else 'shared-volume-context-or-index-excluded') for i,n in enumerate(lx.find('ThML.body'),1) if isinstance(n.tag,str)]
        shell=[dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='retained-outside-readable-work-body; header and source-evidence context') for n in lx if isinstance(n.tag,str) and n.tag!='ThML.body']
        if accounting['source_envelope']!=envelope or accounting['source_shell']!=shell:raise ValueError('source envelope/shell exclusions mismatch')
        if accounting['source_sha256']!=sha256(raw).hexdigest() or accounting['source_bytes']!=len(raw):raise ValueError('source byte accounting mismatch')
        historic=etree.fromstring(manifest.authority_path('historical-content').read_bytes()).xpath('//*[@xml:id="npnf112-iv"]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'})[0]
        if etree.tostring(body[0],method='c14n')!=etree.tostring(historic,method='c14n'):raise ValueError('full historical body changed')
        if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('credit note differs')
        header=doc.find(NS+'teiHeader/'+NS+'fileDesc')
        ts=header.find(NS+'titleStmt')
        if ts.find(NS+'title').text!=profile['title'] or ts.find(NS+'author').text!=profile['author']:raise ValueError('supported title/author differs')
        contributors=[dict(role=n.find(NS+'resp').text,name=n.find(NS+'name').text) for n in ts.findall(NS+'respStmt')]
        if contributors!=profile['contributors']:raise ValueError('source contributor roles differ')
        if header.find(NS+'publicationStmt/'+NS+'p').text!=profile['rights_statement']:raise ValueError('provider rights header differs')
        bibl=header.find(NS+'sourceDesc/'+NS+'bibl')
        if [c.text for c in bibl]!=[profile['volume_title'],profile['source_url'],profile['source_sha256'],profile['print_source'],profile['scope']]:raise ValueError('source bibliography/scope differs')
        if errors:=validate_file(candidate.path/'content.tei.xml'):raise ValueError('TEI P5 failure: '+str(errors))
    except (ValueError,KeyError,IndexError,TypeError,etree.XMLSyntaxError,ET.ParseError,AttributeError) as exc:findings.append(str(exc))
    closure=sha256(canonical([dict(path=p,sha256=sha256((manifest.repository_root/p).read_bytes()).hexdigest()) for p in policy['closure_inputs']])).hexdigest()
    report=dict(status='pass' if not findings else 'fail',oracle_id=ORACLE_ID,oracle_version='1',implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure,runtime=dict(python=platform.python_version(),implementation=platform.python_implementation(),lxml=etree.LXML_VERSION),source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=sha256(manifest.authority_path('reconstruction-profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],source_sha256=sha256(raw).hexdigest(),xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=findings,source_elements=5008,native_homily_divisions=44,shared_assumptions=['Original source boundary and historical candidate previously exposed; lxml parser shared. Independent imported Chrysostom checker does not import mapper; second stdlib traversal independently compares original literal node ledger. Header values use bound profile and exact original context literals.'],independent_corroboration='Complete original recursive source-to-candidate attrs/text/tails/hierarchy plus stdlib literal source/accounting ledger and whole source envelope dispositions.')
    for field in ('source_elements','native_homily_divisions','shared_assumptions','independent_corroboration'):
        report.pop(field)
    report['runtime']=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})'
    report['result_sha256']=sha256(canonical(report)).hexdigest();return report
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
