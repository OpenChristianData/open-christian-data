"""Independently verify all literal source nodes, mapped attributes and complete scope."""
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from typing import Any, Mapping
from build.tei.npnf2_lib048_oracle import _verify_node, _projection, _selector
from build.tei.npnf2_lib048_oracle import _normalized_attrs, _sha
from ocd_kernel.tei.validate import validate_file

ORACLE_ID='ocd-hilary-select-works-complete-collection-source-oracle'
ORACLE_VERSION='1'
NS='{http://www.tei-c.org/ns/1.0}'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def _expected_hilary_rows(
    selected: list[tuple[str, etree._Element, str]],
    policy: Mapping[str, Any],
    reference_exceptions: Mapping[tuple[str, str, str], str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(
        key: str,
        node: etree._Element,
        parent_feature_id: str | None,
        work_id: str | None = None,
        source_root_id: str | None = None,
    ) -> None:
        if not isinstance(node.tag, str):
            raise ValueError("assigned source contains non-element")
        ordinal = 19031 + len(rows) + 1
        feature_id = f"lib048-feature-{ordinal:06d}"
        if source_root_id is None:
            raise ValueError("reference classification context is required")
        neutral_reference = (
            key,
            source_root_id,
            node.get("id") or "",
        ) in reference_exceptions
        tag, attrs, wrapper = _projection(
            policy,
            node,
            key,
            ordinal,
            work_id,
            source_root_id,
            reference_exceptions,
        )
        dispositions = []
        for name, value in node.attrib.items():
            destination, method = (
                "source-accountability",
                "preserved-exactly-in-accountability",
            )
            rule = policy["projection"]["attribute_rules"].get(name)
            if name == "id":
                destination, method = (
                    "@xml:id-and-source-accountability",
                    "deterministic-member-and-ordinal-prefix",
                )
            elif (
                rule
                and str(node.tag) in rule.get("source_tags", [])
                and not (rule.get("except_work_root") and work_id)
                and not (
                    str(node.tag) == "scripRef"
                    and name in {"passage", "osisRef"}
                    and neutral_reference
                )
            ):
                destination, method = (
                    rule.get("disposition", "source-accountability"),
                    rule.get("method", method),
                )
            dispositions.append(
                {
                    "source_attribute": name,
                    "source_value": value,
                    "destination": destination,
                    "method": method,
                }
            )
        row = {
            "feature_id": feature_id,
            "parent_feature_id": parent_feature_id,
            "source_member": key,
            "source_selector": _selector(node),
            "source_tag": node.tag,
            "source_xml_id": node.get("id"),
            "source_attributes": dict(node.attrib),
            "direct_text_length": len(node.text or ""),
            "direct_text_sha256": _sha((node.text or "").encode()),
            "tail_text_length": len(node.tail or ""),
            "tail_text_sha256": _sha((node.tail or "").encode()),
            "source_title_head": node.get("title")
            if str(node.tag).startswith("div")
            else None,
            "tei_tag": tag,
            "tei_xml_id": attrs["xml:id"],
            "tei_attributes": attrs,
            "tei_wrapper_id": wrapper,
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            **({"work_id": work_id} if work_id else {}),
        }
        rows.append(row)
        for child in node:
            visit(key, child, feature_id, source_root_id=source_root_id)

    for key, root, work_id in selected:
        visit(key, root, None, work_id, root.get("id"))
    return rows


def _oracle(manifest,candidate):
    profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
    policy=json.loads(manifest.authority_path('validation-policy').read_bytes())
    raw=manifest.authority_path('retained-thml').read_bytes();findings=[]
    try:
        lx=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,remove_comments=False))
        matches=lx.xpath('/ThML/ThML.body/div1[@id="ii"]')
        if len(matches)!=1:raise ValueError('complete source collection absent or repeated')
        selected=matches[0]
        if len(selected)!=7 or len(list(selected.iter()))!=8156 or [n.get('id') for n in selected]!=['ii-Page_III','ii.i','ii.ii','ii.iii','ii.iv','ii.v','ii.vi']:raise ValueError('source collection cardinality/boundary differs')
        legacy_policy=json.loads(manifest.authority_path('legacy-policy').read_bytes())
        if any(e['source_member']=='npnf209' for e in legacy_policy['projection']['reference_classification']['neutral_non_scripture_exceptions']):raise ValueError('unexpected Hilary neutral reference exception')
        doc=etree.fromstring(candidate.member_bytes('content.tei.xml'))
        body=doc.find(NS+'text/'+NS+'body')
        if body is None or len(body)!=1 or body[0].get('{http://www.w3.org/XML/1998/namespace}id')!='lib048-npnf209-019032-ii':raise ValueError('candidate must retain exactly one complete Hilary Select Works collection')
        original=etree.fromstring(manifest.authority_path('historical-content').read_bytes())
        oldrows=json.loads(manifest.authority_path('historical-accounting').read_bytes())['crosswalk']
        matches=[i for i,r in enumerate(oldrows) if r.get('work_id')==profile['work_id']]
        if matches!=[19031] or profile['original_global_ordinal_offset']!=19031:raise ValueError('original historical global ordinal offset differs')
        count=[19031];_verify_node(selected,body[0],'npnf209',legacy_policy,count,work_id=profile['work_id'],source_root_id='ii',reference_exceptions={})
        source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
        nodes=[n for n in source.find('ThML.body') if n.get('id')=='ii'];ledger=[]
        def walk(n,parent):
            ledger.append(dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',parent=parent,children=[c.get('id') for c in n]))
            for c in n:walk(c,n.get('id'))
        walk(nodes[0],None)
        accounting=json.loads(candidate.member_bytes('source-accountability.json'))
        if ledger!=accounting['literal_source_nodes'] or accounting['elements']!=8156 or accounting['scope']!=profile['scope']:raise ValueError('literal source/accounting scope mismatch')
        for id,literal in profile['context_literals'].items():
            found=[n for n in source.iter() if n.get('id')==id]
            if len(found)!=1 or ''.join(found[0].itertext())!=literal:raise ValueError('literal primary credit/context mismatch: '+id)
        expected_rows=_expected_hilary_rows([('npnf209',selected,profile['work_id'])],legacy_policy,{})
        if expected_rows!=accounting['crosswalk']:raise ValueError('full original attribute disposition/crosswalk mismatch')
        envelope=[dict(position=i,id=n.get('id'),tag=n.tag,title=n.get('title'),elements=sum(isinstance(c.tag,str) for c in n.iter()),c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='complete-selected-collection' if n.get('id')=='ii' else 'shared-volume-context-or-index-excluded') for i,n in enumerate(lx.find('ThML.body'),1) if isinstance(n.tag,str)]
        shell=[dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest(),disposition='retained-outside-readable-work-body; header and source-evidence context') for n in lx if isinstance(n.tag,str) and n.tag!='ThML.body']
        if accounting['source_envelope']!=envelope or accounting['source_shell']!=shell:raise ValueError('source envelope/shell exclusions mismatch')
        if accounting['source_sha256']!=sha256(raw).hexdigest() or accounting['source_bytes']!=len(raw):raise ValueError('source byte accounting mismatch')
        historic=etree.fromstring(manifest.authority_path('historical-content').read_bytes()).xpath('//*[@xml:id="lib048-npnf209-019032-ii"]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'})[0]
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
    report=dict(status='pass' if not findings else 'fail',oracle_id=ORACLE_ID,oracle_version='1',implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure,runtime=dict(python=platform.python_version(),implementation=platform.python_implementation(),lxml=etree.LXML_VERSION),source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=sha256(manifest.authority_path('reconstruction-profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],source_sha256=sha256(raw).hexdigest(),xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),policy_sha256=sha256(manifest.authority_path('validation-policy').read_bytes()).hexdigest(),findings=findings,source_elements=8156,native_constituent_divisions=6,shared_assumptions=['Original source boundary and historical candidate previously exposed; lxml parser shared. Independent imported LIB048 checker does not import mapper; second stdlib traversal independently compares original literal node ledger. Header values use bound profile and exact original context literals.'],independent_corroboration='Complete original recursive source-to-candidate attrs/text/tails/hierarchy plus stdlib literal source/accounting ledger and whole source envelope dispositions.')
    for field in ('source_elements','native_constituent_divisions','shared_assumptions','independent_corroboration'):
        report.pop(field)
    report['runtime']=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})'
    report['result_sha256']=sha256(canonical(report)).hexdigest();return report
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
