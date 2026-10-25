"""Independent lxml/native-content observations for the complete L594 public rows."""
from hashlib import sha256
import json
from pathlib import Path
import re
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.projection.categories.liturgies_bcp1549_check import _paths

PROFILE='ocd-liturgies-chrysostom-1866-retained-members-v1'
IDENTITY={'work_id':'chrysostom-divine-and-sacred-liturgy','textual_form_id':'chrysostom-divine-and-sacred-liturgy-wikisource-retained','edition_id':'chrysostom-divine-and-sacred-liturgy-wikisource-electronic'}
NS='{http://www.tei-c.org/ns/1.0}'
ROOT=Path(__file__).resolve().parents[3]
SCHEMA=ROOT/'schemas/v2/categories/liturgies.schema.json';COMMON=ROOT/'schemas/v2/public-row.schema.json';NATIVE=ROOT/'schemas/v2/native-content.schema.json'

def _hash(raw):return sha256(raw).hexdigest()
def _json(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def verify_document(tei_path,rows,receipt=None,*,identity,language,representation_revision,edition_title,projection_profile,source_url=None,source_sha256=None,retained_sha256=None):
    try:
        if projection_profile!=PROFILE or dict(identity)!=IDENTITY or language!='en':raise PipelineError('Chrysostom exact identity/profile/language required')
        raw=Path(tei_path).read_bytes()
        if any(t in raw.upper() for t in (b'<!DOCTYPE',b'<!ENTITY',b'<!--')) or re.search(rb'<\?(?!xml(?:\s|\?>))',raw,re.I):raise PipelineError('Chrysostom declarations/comments/instructions unsupported')
        doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
        if doc.tag!=NS+'TEI' or [n.tag for n in doc]!=[NS+'teiHeader',NS+'text'] or [n.tag for n in doc[1]]!=[NS+'body']:raise PipelineError('Chrysostom envelope differs')
        body=doc[1][0]
        if len(body)!=2 or [n.tag for n in body]!=[NS+'div']*2 or [n.get('type') for n in body]!=['complete-validated-transcription','printer-imprint']:raise PipelineError('Chrysostom complete text/imprint boundary differs')
        for n in [doc,doc[1],body]:
            if (n.text or '').strip() or any((c.tail or '').strip() for c in n):raise PipelineError('Chrysostom unassigned envelope text')
        from ocd_kernel.projection.categories.liturgies import _source_binding_lxml,_validator
        binding=_source_binding_lxml(doc,source_url=source_url,source_sha256=source_sha256,retained_sha256=retained_sha256)
        expected=[];anchors=[]
        for i,unit in enumerate(body,1):
            content,text=observe_content(etree.tostring(unit,with_tail=False));structure=[content];token=_hash(f'/TEI/text/body/div[{i}]'.encode())[:20]
            row=dict(IDENTITY,record_id=f'{IDENTITY["edition_id"]}:liturgy-member:{token}',sequence=i,category='liturgies',language=language,text=text,representation_revision=representation_revision,provenance={'edition_title':edition_title},notes=[],references=[],row_profile=PROFILE,member_id=token,member_number=i,member_title='Complete validated 1866 liturgy and order' if i==1 else 'Printer imprint',member_kind='source-member',response_model='source-native-labels-without-response-inference',content_format='ocd-native-content-v1',structure=structure,source_links=[],locator={'kind':'liturgy-member','text_part':'body','member':i,'member_kind':'source-member'})
            expected.append(row);anchors.append(dict(record_id=row['record_id'],tei_path=f'/TEI/text/body/div[{i}]',text_sha256=_hash(text.encode()),structure_sha256=_hash(_json(structure)),source_links_sha256=_hash(_json([]))))
        warnings=['Provider-validated electronic witness; full print equivalence not independently established.','Native rubric typography, tables and exact original graphic URLs retained; no response/person relationships inferred.']
        proof=dict(mapping_version=PROFILE,assembler_version='ocd-liturgies-assembler-provisional-v1',projection_profile=PROFILE,master_sha256=_hash(raw),source_binding=binding,policy_sha256=_hash(SCHEMA.read_bytes()),common_schema_sha256=_hash(COMMON.read_bytes()),native_schema_sha256=_hash(NATIVE.read_bytes()),output_sha256=_hash(_json(expected)),row_count=2,anchors=anchors,inventory=_paths(doc),warnings=warnings,exclusions=[{'tei_path':'/TEI/teiHeader','reason':'private-bibliographic-header'}],unsupported=[],independent_check={'status':'pending'})
        errors=[]
        if rows!=expected:errors.append('Chrysostom complete native text/structure/order differs')
        if receipt is None or dict(receipt)!=proof:errors.append('Chrysostom complete projection receipt differs')
        validator=_validator()
        for row in rows:errors.extend(e.message for e in validator.iter_errors(row))
        return errors
    except (OSError,ValueError,TypeError,KeyError,PipelineError,etree.XMLSyntaxError) as exc:return [str(exc)]
