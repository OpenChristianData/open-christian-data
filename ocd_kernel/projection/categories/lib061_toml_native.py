"""Exact retained LIB-061 TOML-member rows, with a separate lxml observer.

Source fields retain their names, order, TOML types, and literal values. A row
is a source member, including its ordered records; metadata members are rows
too. Paths and source assertions are never promoted into historical identity,
canonical verse targets, or permission to navigate a source URL.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from xml.etree import ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories import commentary as core
from ocd_kernel.projection import native_content

FAMILY = 'ocd-commentary-lib061-retained-toml-members-v1'
IDENTITY = {
    'work_id': 'church-fathers-quotations',
    'textual_form_id': 'church-fathers-quotations-retained-en',
    'edition_id': 'church-fathers-quotations-retained-electronic',
    'acquisition_id': 'church-fathers-quotations-acquired-member-set',
}
REVISION = 'church-fathers-quotations-retained-accepted-20261004-v1'
SOURCE_SHA = 'f38c1dd6cf88ea1bf8c75626225327a0f473af5f9723eda5bb5b7d9e89f0096f'
BODY_SHA = '70535d7ec3e9aa7c41ae2aed10a1d1aa991bf7a26f3a663128ba95909242caa5'
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
ORIGINAL_HEADER = b'''<teiHeader><fileDesc><titleStmt><title>Church Fathers verse-reference quotations</title></titleStmt><publicationStmt><p>Nonaccepted reconstruction candidate; publication not ready</p></publicationStmt><sourceDesc><p>Commentaries-Database.tar; SHA-256 5a4ba3ef4bfd168cdaf4cd6bcc4e8cc655c90da97bfe5abf3e6fe9338d86fbe6</p></sourceDesc></fileDesc><encodingDesc><classDecl><taxonomy xml:id="toml-types"><category xml:id="toml-string"><catDesc>TOML string</catDesc></category><category xml:id="toml-integer"><catDesc>TOML integer</catDesc></category></taxonomy></classDecl></encodingDesc></teiHeader>'''
PUBLICATION_TEXT = 'Technical reconstruction of the exact retained electronic collection; human acceptance, rights review, and publication remain open.'
WARNING = 'source-member-and-record-order-preserved;metadata-and-source-claims-not-historical-identity;copyrighted-translation-caveat-retained'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def route(metadata):
    if metadata['acceptance']['identity'].get('work_id') != IDENTITY['work_id']:
        return None
    accepted = metadata['acceptance']
    if (accepted['identity'] != IDENTITY or metadata['language'] != 'en'
            or accepted['representation_revision']['id'] != REVISION
            or accepted['source'].get('source_kind') != 'retained-member-set'
            or accepted['source']['source_sha256'] != SOURCE_SHA
            or metadata['acquisition']['source_sha256'] != SOURCE_SHA):
        raise PipelineError('LIB-061 route requires its exact retained collection and technical revision')
    return FAMILY


def _header_facts(metadata):
    accepted = metadata['acceptance']
    acquisition = metadata['acquisition']
    revision = accepted['representation_revision']
    return IDENTITY | {
        'source_sha256': SOURCE_SHA,
        'source_bytes': str(acquisition['source_bytes']),
        'representation_revision': REVISION,
        'source_kind': 'retained-member-set',
        'sha256': SOURCE_SHA,
    }, revision, acquisition


def _check_header_et(root, metadata):
    expected = ET.fromstring(b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'+ORIGINAL_HEADER+b'</TEI>')[0]
    fd = expected.find(NS+'fileDesc')
    fd.find(NS+'publicationStmt/'+NS+'p').text = PUBLICATION_TEXT
    sd = fd.find(NS+'sourceDesc'); sd[0].tag = NS+'bibl'
    facts, revision, acquisition = _header_facts(metadata)
    binding = ET.SubElement(sd, NS+'bibl', {'type':'ocd-acceptance-binding'})
    ET.SubElement(binding, NS+'ptr', {'target':acquisition['url']})
    for key, value in facts.items():
        ET.SubElement(binding, NS+'idno', {'type':key}).text = value
    for key, value in [('source-location', acquisition['source_path']), ('source-scope', metadata['acceptance']['scope']['declared'])]:
        ET.SubElement(binding, NS+'note', {'type':key}).text = value
    ET.SubElement(ET.SubElement(expected, NS+'revisionDesc'), NS+'change', {XML+'id':REVISION,'when':revision['date']}).text = revision['note']
    def equal(a,b):
        if b is None or a.tag != b.tag or dict(a.attrib) != dict(b.attrib) or a.text != b.text or a.tail != b.tail or len(a) != len(b):
            raise PipelineError('LIB-061 complete accepted header differs')
        for x,y in zip(a,b,strict=True):equal(x,y)
    equal(expected, root.find(NS+'teiHeader'))


def _observe_header(doc, metadata):
    observed = copy.deepcopy(doc.find(NS+'teiHeader'))
    revision = metadata['acceptance']['representation_revision']
    rd = observed.find(NS+'revisionDesc')
    if rd is None or len(rd)!=1 or rd[0].tag!=NS+'change' or dict(rd[0].attrib)!={XML+'id':REVISION,'when':revision['date']} or rd[0].text!=revision['note'] or len(rd[0]) or rd[0].tail is not None:
        raise ValueError('observed LIB-061 revision differs')
    observed.remove(rd)
    sd = observed.find(NS+'fileDesc/'+NS+'sourceDesc')
    if sd is None or len(sd)!=2 or sd[0].tag!=NS+'bibl' or sd[0].attrib or sd[1].tag!=NS+'bibl' or dict(sd[1].attrib)!={'type':'ocd-acceptance-binding'}:
        raise ValueError('observed LIB-061 complete source descriptions differ')
    binding = sd[1]; sd.remove(binding)
    acquisition = metadata['acquisition']
    wanted = [('ptr', {'target':acquisition['url']}, None)]
    facts = IDENTITY | {'source_sha256':SOURCE_SHA,'source_bytes':str(acquisition['source_bytes']),'representation_revision':REVISION,'source_kind':'retained-member-set','sha256':SOURCE_SHA}
    wanted += [('idno',{'type':key},value) for key,value in facts.items()]
    wanted += [('note',{'type':'source-location'},acquisition['source_path']),('note',{'type':'source-scope'},metadata['acceptance']['scope']['declared'])]
    if binding.text is not None or binding.tail is not None or len(binding)!=len(wanted):
        raise ValueError('observed LIB-061 binding shape differs')
    for actual,(tag,attrs,text) in zip(binding,wanted,strict=True):
        if actual.tag!=NS+tag or dict(actual.attrib)!=attrs or actual.text!=text or actual.tail is not None or len(actual):
            raise ValueError('observed LIB-061 bound source fact differs')
    publication = observed.find(NS+'fileDesc/'+NS+'publicationStmt/'+NS+'p')
    if publication is None or publication.text != PUBLICATION_TEXT:
        raise ValueError('observed LIB-061 publication qualifier differs')
    publication.text = 'Nonaccepted reconstruction candidate; publication not ready'
    sd[0].tag = NS+'p'
    original = etree.fromstring(b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'+ORIGINAL_HEADER+b'</TEI>')[0]
    # Independent structural records include every header slot, attribute, text,
    # tail, and child count, so extra author/metadata carriers cannot pass.
    def slots(node):
        return [(x.tag,sorted(x.attrib.items()),x.text,x.tail,len(x)) for x in node.iter()]
    if slots(observed) != slots(original):
        raise ValueError('observed LIB-061 historical header differs')


def _raw(metadata):
    if route(metadata)!=FAMILY:raise PipelineError('LIB-061 profile was not selected')
    raw = io_path(metadata['master_path']).read_bytes()
    if any(x in raw.lower() for x in (b'<!doctype',b'<!entity',b'<!--')) or raw.count(b'</teiHeader>')!=1:
        raise PipelineError('LIB-061 declaration or complete header boundary differs')
    if _sha(raw.split(b'</teiHeader>',1)[1]) != BODY_SHA:
        raise PipelineError('LIB-061 complete source-verified collection body differs')
    return raw


def _field_et(node):
    key=node.get('n');typ=node.get('ana');label,value=list(node)
    if node.tag!=NS+'item' or dict(node.attrib)!={'n':key,'ana':typ} or label.tag!=NS+'label' or label.text!=key or label.attrib or len(label) or label.tail is not None:
        raise PipelineError('LIB-061 source field label differs')
    if typ=='#toml-string' and value.tag==NS+'seg' and dict(value.attrib)=={XML+'space':'preserve'}:
        attrs={'whitespace':'preserve'}; text=value.text or ''
    elif typ=='#toml-integer' and value.tag==NS+'num' and dict(value.attrib)=={'type':'integer'}:
        text=value.text or '';assert str(int(text))==text;attrs={'type':'integer'}
    else:raise PipelineError('LIB-061 source field type differs')
    if len(value) or value.tail is not None or node.text is not None or node.tail is not None:raise PipelineError('LIB-061 source field mixed content differs')
    children=[{'kind':'label','attributes':{},'content':[{'kind':'text','text':key}]}]
    children.append({'kind':'segment','attributes':attrs,'content':[{'kind':'text','text':text}] if text else []})
    return {'kind':'list-item','attributes':{'number':key,'source_annotations':typ},'content':children},key+': '+text


def _unit_et(unit):
    contents=[]; lines=[]
    for child in unit:
        if child.tag in (NS+'head',NS+'ab'):
            kind='heading' if child.tag==NS+'head' else 'paragraph'; attrs={} if kind=='heading' else {'type':child.get('type')}
            contents.append({'kind':kind,'attributes':attrs,'content':[{'kind':'text','text':child.text}]});lines.append(child.text)
        else:
            objects=[child] if child.tag==NS+'list' else list(child)
            grouped=[]
            for obj in objects:
                fields=[]
                for item in obj:
                    field,line=_field_et(item);fields.append(field);lines.append(line)
                grouped.append({'kind':'list','attributes':{'type':'toml-object'},'content':fields})
            if child.tag==NS+'div':
                contents.append({'kind':'division','attributes':{'type':'commentary-record','number':child.get('n')},'content':grouped})
            else:contents.extend(grouped)
    return {'kind':'division','attributes':{'type':'source-member','subtype':unit.get('subtype'),'number':unit.get('n')},'content':contents},'\n'.join(lines)


def _unit_observe(member):
    nodes=[]; output=[]
    for node in member:
        name=etree.QName(node).localname
        if name=='head' or name=='ab':
            nodes.append({'kind':'heading' if name=='head' else 'paragraph','attributes':{} if name=='head' else {'type':node.attrib['type']},'content':[{'kind':'text','text':node.text}]});output.append(node.text);continue
        records=[node] if name=='list' else list(node)
        lists=[]
        for record in records:
            items=[]
            for field in record:
                label,value=field;key=label.text;marker=field.attrib['ana']
                if key!=field.attrib['n'] or marker not in ('#toml-string','#toml-integer') or len(value):raise ValueError('observed LIB-061 field differs')
                literal=value.text or ''
                if marker=='#toml-integer':
                    if value.tag!=NS+'num' or str(int(literal))!=literal:raise ValueError('observed LIB-061 integer differs')
                    properties={'type':'integer'}
                else:
                    if value.tag!=NS+'seg' or dict(value.attrib)!={XML+'space':'preserve'}:raise ValueError('observed LIB-061 string differs')
                    properties={'whitespace':'preserve'}
                slots=[{'kind':'label','attributes':{},'content':[{'kind':'text','text':key}]},{'kind':'segment','attributes':properties,'content':[{'kind':'text','text':literal}] if literal else []}]
                items.append({'kind':'list-item','attributes':{'number':key,'source_annotations':marker},'content':slots});output.append(key+': '+literal)
            lists.append({'kind':'list','attributes':{'type':'toml-object'},'content':items})
        if name=='div':nodes.append({'kind':'division','attributes':{'type':'commentary-record','number':node.attrib['n']},'content':lists})
        else:nodes.extend(lists)
    return {'kind':'division','attributes':{'type':'source-member','subtype':member.attrib['subtype'],'number':member.attrib['n']},'content':nodes},'\n'.join(output)


def _observe_readable(member):
    policy = json.loads(native_content.SCHEMA.read_bytes())['x-ocd-native-content']
    kinds = {'div':'division','head':'heading','ab':'paragraph','list':'list','item':'list-item','label':'label','seg':'segment','num':'segment'}
    def visit(node):
        kind = kinds[etree.QName(node).localname]
        value = re.sub(r'\s+', ' ', node.text or '')
        for child in node:
            value += visit(child) + re.sub(r'\s+', ' ', child.tail or '')
        if kind in policy['block_boundaries']:
            return '\n\n' + value.strip() + '\n\n'
        return value
    return re.sub(r'\n{3,}', '\n\n', re.sub(r' *\n *', '\n', visit(member))).strip()


def _assemble(metadata,raw,root,units,observer):
    rows=[];anchors=[];inventory=[];records=metadata_count=0
    for ordinal,unit in enumerate(units,1):
        structure,text=_unit_observe(unit) if observer else _unit_et(unit)
        text = _observe_readable(unit) if observer else native_content.readable_content(structure)
        row={key:IDENTITY[key] for key in core._IDENTITY_KEYS}
        row.update(record_id=f"{IDENTITY['edition_id']}:toml-member-{ordinal:06d}",sequence=ordinal,category='commentary',language='en',text=text,representation_revision=REVISION,provenance={'edition_title':metadata['edition'].title},content_format='ocd-native-content-v1',structure=[structure],locator={'kind':'native-unit','text_part':'body','unit':ordinal})
        rows.append(row)
        path=f'/TEI[1]/text[1]/body[1]/div[{ordinal}]'
        anchors.append({'sequence':ordinal,'tei_path':path})
        memberslots=[(x.tag,sorted(x.attrib.items()),x.text,x.tail,len(x)) for x in unit.iter()]
        inventory.append({'tei_path':path,'disposition':'source-member-row','archive_index':unit.get('n'),'archive_path':unit[0].text,'subtype':unit.get('subtype'),'node_count':len(memberslots),'complete_slots_sha256':_sha(json.dumps(memberslots,ensure_ascii=False,separators=(',',':')).encode())})
        records+=sum(x.tag==NS+'div' and x.get('type')=='commentary-record' for x in unit)
        metadata_count+=unit.get('subtype')=='metadata'
    if (len(rows),records,metadata_count)!=(58675,70194,335):raise PipelineError('LIB-061 source member/record/metadata census differs')
    header=core._checker_header(root,{}) if observer else core._header(root)
    core._validate_accepted_header(header,metadata)
    result={'rows':rows,'anchors':anchors,'inventory':inventory,'references':[],'warnings':[{'reason':WARNING}],'exclusions':[],'unsupported':[],'master_sha256':_sha(raw),'scope_id':None,'mapping_version':FAMILY,'assembler_version':core.ASSEMBLER_VERSION,'source_binding':{'source_url':header['source_url'],'source_sha256':SOURCE_SHA,'retained_sha256':SOURCE_SHA},'authority':metadata['authority']}
    if not observer:core._validate_rows(rows)
    result['receipt']=core.build_commentary_receipt(result,identity={k:IDENTITY[k] for k in core._IDENTITY_KEYS})
    return result


def project(metadata):
    raw=_raw(metadata);root=ET.fromstring(raw)
    if root.tag!=NS+'TEI' or dict(root.attrib)!={XML+'id':'lib061-church-fathers-quotations'}:raise PipelineError('LIB-061 root differs')
    _check_header_et(root,metadata)
    return _assemble(metadata,raw,root,list(root.find(NS+'text/'+NS+'body')),False)


def observe(metadata):
    raw=_raw(metadata)
    doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=True,remove_comments=False))
    if doc.tag!=NS+'TEI' or dict(doc.attrib)!={XML+'id':'lib061-church-fathers-quotations'}:raise ValueError('observed LIB-061 root differs')
    _observe_header(doc,metadata)
    return _assemble(metadata,raw,doc,list(doc.find(NS+'text/'+NS+'body')),True)


def verify(metadata,rows,receipt):
    try:
        expected=observe(metadata)
        from ocd_kernel.projection.categories.commentary_source_native import _compare
        return _compare(expected,rows,receipt)
    except (PipelineError,OSError,ValueError,KeyError,TypeError,etree.XMLSyntaxError) as exc:
        return [str(exc)]
