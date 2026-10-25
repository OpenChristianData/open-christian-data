"""Exact complete 1866 Chrysostom electronic witness, retaining native content."""
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content import project_content, readable_content
from ocd_kernel.projection.categories.liturgies_bcp1549 import _walk

PROFILE='ocd-liturgies-chrysostom-1866-retained-members-v1'
IDENTITY={'work_id':'chrysostom-divine-and-sacred-liturgy','textual_form_id':'chrysostom-divine-and-sacred-liturgy-wikisource-retained','edition_id':'chrysostom-divine-and-sacred-liturgy-wikisource-electronic'}
NS='{http://www.tei-c.org/ns/1.0}'
ROOT=Path(__file__).resolve().parents[3]
SCHEMA=ROOT/'schemas/v2/categories/liturgies.schema.json'
COMMON=ROOT/'schemas/v2/public-row.schema.json'
NATIVE=ROOT/'schemas/v2/native-content.schema.json'
TITLES=('Complete validated 1866 liturgy and order','Printer imprint')

def _hash(raw):return sha256(raw).hexdigest()
def _json(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def accepted_source_member(base, identity, acquisition, source, included):
    """Bind the primary render and its exact revision/image support set."""
    from ocd_kernel.lib.storage_topology import resolve_repo_path
    expected=('complete-export-20261007.xml','complete-render-all-20261007.json','liturgy-diagram.png','liturgy-seal.png')
    retained=acquisition.get('retained_files',[])
    if ({key:identity.get(key) for key in IDENTITY}!=IDENTITY or
            acquisition.get('acquisition_id')!='chrysostom-divine-and-sacred-liturgy-wikisource-complete-20261007' or
            not isinstance(included,list) or len(included)!=4 or len(retained)!=4 or
            [item.get('path') for item in retained]!=['raw/wikisource/chrysostom-divine-liturgy-1866/'+name for name in expected] or
            any(not isinstance(item,dict) or not isinstance(item.get('position'),int) for item in included)):
        raise PipelineError('Chrysostom complete render/support membership differs')
    for position,(selected,item) in enumerate(zip(sorted(included,key=lambda item:item['position']),retained),1):
        if selected.get('position')!=position or any(selected.get(k)!=item.get(k) for k in ('path','sha256','bytes')):
            raise PipelineError('Chrysostom accepted support membership/order differs')
        raw=resolve_repo_path(base,item['path']).read_bytes()
        if len(raw)!=item['bytes'] or _hash(raw)!=item['sha256']:
            raise PipelineError('Chrysostom retained render/support bytes differ')
    if any(source.get('source_'+k)!=acquisition.get('source_'+k) for k in ('path','sha256','bytes')) or source.get('source_path')!=retained[1]['path']:
        raise PipelineError('Chrysostom primary rendered witness binding differs')
    return {'path':source['source_path'],'sha256':source['source_sha256'],'bytes':source['source_bytes']}

def project_document(tei_path,*,identity,language,representation_revision,edition_title,projection_profile,source_url=None,source_sha256=None,retained_sha256=None):
    if projection_profile!=PROFILE or dict(identity)!=IDENTITY or language!='en':raise PipelineError('Chrysostom exact identity/profile/language required')
    path=Path(tei_path);raw=path.read_bytes()
    if any(t in raw.upper() for t in (b'<!DOCTYPE',b'<!ENTITY',b'<!--')) or re.search(rb'<\?(?!xml(?:\s|\?>))',raw,re.I):raise PipelineError('Chrysostom declarations/comments/instructions unsupported')
    doc=ET.fromstring(raw)
    if doc.tag!=NS+'TEI' or [c.tag for c in doc]!=[NS+'teiHeader',NS+'text'] or [c.tag for c in doc[1]]!=[NS+'body']:raise PipelineError('Chrysostom envelope differs')
    body=doc[1][0]
    if len(body)!=2 or [n.tag for n in body]!=[NS+'div']*2 or [n.get('type') for n in body]!=['complete-validated-transcription','printer-imprint']:raise PipelineError('Chrysostom complete text/imprint boundary differs')
    for n in [doc,doc[1],body]:
        if (n.text or '').strip() or any((c.tail or '').strip() for c in n):raise PipelineError('Chrysostom unassigned envelope text')
    from ocd_kernel.projection.categories.liturgies import _source_binding_et,_validate_rows
    binding=_source_binding_et(doc,source_url=source_url,source_sha256=source_sha256,retained_sha256=retained_sha256)
    rows=[];anchors=[]
    for i,unit in enumerate(body,1):
        structure=[project_content(unit)];text=readable_content(structure[0]);token=_hash(f'/TEI/text/body/div[{i}]'.encode())[:20]
        row=dict(IDENTITY,record_id=f'{IDENTITY["edition_id"]}:liturgy-member:{token}',sequence=i,category='liturgies',language=language,text=text,representation_revision=representation_revision,provenance={'edition_title':edition_title},notes=[],references=[],row_profile=PROFILE,member_id=token,member_number=i,member_title=TITLES[i-1],member_kind='source-member',response_model='source-native-labels-without-response-inference',content_format='ocd-native-content-v1',structure=structure,source_links=[],locator={'kind':'liturgy-member','text_part':'body','member':i,'member_kind':'source-member'})
        rows.append(row);anchors.append(dict(record_id=row['record_id'],tei_path=f'/TEI/text/body/div[{i}]',text_sha256=_hash(text.encode()),structure_sha256=_hash(_json(structure)),source_links_sha256=_hash(_json([]))))
    _validate_rows(rows)
    warnings=['Provider-validated electronic witness; full print equivalence not independently established.','Native rubric typography, tables and exact original graphic URLs retained; no response/person relationships inferred.']
    receipt=dict(mapping_version=PROFILE,assembler_version='ocd-liturgies-assembler-provisional-v1',projection_profile=PROFILE,master_sha256=_hash(raw),source_binding=binding,policy_sha256=_hash(SCHEMA.read_bytes()),common_schema_sha256=_hash(COMMON.read_bytes()),native_schema_sha256=_hash(NATIVE.read_bytes()),output_sha256=_hash(_json(rows)),row_count=2,anchors=anchors,inventory=_walk(doc),warnings=warnings,exclusions=[{'tei_path':'/TEI/teiHeader','reason':'private-bibliographic-header'}],unsupported=[],independent_check={'status':'pending'})
    return dict(rows=rows,receipt=receipt,mapping_version=PROFILE,assembler_version=receipt['assembler_version'],master_sha256=receipt['master_sha256'],source_binding=binding,anchors=anchors,inventory=receipt['inventory'],warnings=warnings,exclusions=receipt['exclusions'],unsupported=[],independent_check=receipt['independent_check'])
