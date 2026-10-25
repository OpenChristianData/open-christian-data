"""Independent one-work boundary and complete per-volume retained-source observer."""
from pathlib import Path
from hashlib import sha256
import copy,json,xml.etree.ElementTree as ET
from lxml import etree
from build.tei.newman_parochial_pg_oracle import enumerate_source,_header,signature,check_document
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema
T='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
ENCODING='One source-attested work; retained non-OCR volumes VII and VIII in source order. Each volume wrapper conserves its full source front matter, eighteen sermons and back label, including literal notes, emphasis, coordinates and whitespace. The verified member source-location assertion is renamed retained-source-location without changing its value. Six IA OCR volumes I–VI are excluded; no complete eight-volume or uniform 1868 print edition is claimed. Complete provider notices and credits are delivered in README.source.md.'
PATHS=('build/tei/newman_parochial_pg_work_oracle.py','build/tei/newman_parochial_pg_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/lib/path_io.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/tei/validate.py')
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def digest(v):return sha256(v).hexdigest()
def closure(root):return digest(canonical([dict(path=p,sha256=digest((root/p).read_bytes())) for p in PATHS]))
def check(manifest,content):
    assert (manifest.record['work_id'],manifest.record['ticket_id'],manifest.record['source_id'])==('newman-parochial-sermons','LIB-018','newman-retained-pg-vii-viii-one-work')
    root=ET.fromstring(content);assert root.tag==T+'TEI' and not root.attrib and root.text is None and root.tail is None and len(root)==2
    profile=json.loads(manifest.authority_path('profile').read_bytes());assert len(manifest.record['source_members'])==len(profile['members'])==2
    header=ET.Element(T+'teiHeader');fd=ET.SubElement(header,T+'fileDesc');ts=ET.SubElement(fd,T+'titleStmt')
    ET.SubElement(ts,T+'title').text='Parochial and Plain Sermons; retained volumes VII–VIII';ET.SubElement(ts,T+'author').text='JOHN HENRY NEWMAN, B.D.'
    ET.SubElement(ET.SubElement(fd,T+'publicationStmt'),T+'p').text='Nonaccepted one-work reconstruction of the exact retained non-OCR PG volumes VII–VIII; human, print, rights and publication decisions remain open.'
    desc=ET.SubElement(fd,T+'sourceDesc');ET.SubElement(ET.SubElement(header,T+'encodingDesc'),T+'p').text=ENCODING
    text=root[1];assert text.tag==T+'text' and text.attrib=={X+'lang':'en'} and text.text is None and text.tail is None and len(text)==1
    body=text[0];assert body.tag==T+'body' and not body.attrib and body.text is None and body.tail is None and len(body)==2
    facts=[]
    for i,(logical,volume,slug) in enumerate([('raw/gutenberg/sermons/newman/pg24256.txt','VII','pg24256'),('raw/gutenberg/sermons/newman/pg24284.txt','VIII','pg24284')],1):
        raw=manifest.authority_path('retained-source-'+str(i)).read_bytes();source=enumerate_source(raw,logical);entry=profile['members'][i-1];member=manifest.record['source_members'][i-1]
        assert member['path']==logical and member['bytes']==len(raw) and member['sha256']==digest(raw) and dict(member)==entry['source_member'] and entry['volume']==volume and entry['slug']==slug
        assert digest(manifest.authority_path('verified-volume-'+str(i)).read_bytes())==entry['verified_tei_sha256']
        authority=next(a for a in manifest.record['authorities'] if a['name']=='retained-source-'+str(i));assert authority['path']==logical and authority['role']=='primary-source'
        wrapper=body[i-1];assert wrapper.tag==T+'div' and wrapper.attrib=={'type':'source-div1','n':volume,X+'id':slug+'-volume'} and wrapper.text is None and wrapper.tail is None and len(wrapper)==20
        assert wrapper[0].get('type')=='source-front' and wrapper[-1].get('type')=='source-back' and all(u.get('type')=='source-div1' for u in list(wrapper)[1:-1])
        original_header=_header(source);bibl=copy.deepcopy(original_header.find(T+'fileDesc/'+T+'sourceDesc/'+T+'bibl'));bibl.find(T+'note').set('type','retained-source-location');desc.append(bibl)
        restored=ET.Element(T+'TEI');restored.append(original_header);restored_text=ET.SubElement(restored,T+'text',{X+'lang':'en'})
        front=ET.SubElement(restored_text,T+'front');front.append(copy.deepcopy(wrapper[0]));sermons=ET.SubElement(restored_text,T+'body')
        for unit in list(wrapper)[1:-1]:sermons.append(copy.deepcopy(unit))
        back=ET.SubElement(restored_text,T+'back');back.append(copy.deepcopy(wrapper[-1]))
        check_document(raw,logical,ET.tostring(restored,encoding='UTF-8',xml_declaration=True))
        facts.append(dict(volume=volume,source_path=logical,source_sha256=digest(raw),carriers=len(source['carriers']),note_definitions=source['note_definitions'],exceptions=source['exceptions']))
    assert signature(root[0])==signature(header),'complete one-work source header differs'
    assert compiled_schema().validate(etree.fromstring(content))
    return facts
def complete_check(manifest,candidate):
    content=candidate.member_bytes('content.tei.xml');facts=check(manifest,content)
    profile=json.loads(manifest.authority_path('profile').read_bytes());policy=json.loads(manifest.authority_path('policy').read_bytes());account=json.loads(candidate.member_bytes('source-accountability.json'))
    assert profile['excluded_ocr_editions']==['newman-parochial-sermons-ia-'+str(i).zfill(2)+'-retained-electronic' for i in range(1,7)]
    accounts=[]
    for i,fact in enumerate(facts,1):
        raw=manifest.authority_path('retained-source-'+str(i)).read_bytes();source=enumerate_source(raw,fact['source_path'])
        volume_account={k:source[k] for k in ('source_path','source_sha256','source_bytes','volume','book_start','book_stop','note_definitions','exceptions')}
        volume_account.update(contract='ocd-newman-parochial-pg-accountability-v1',content_sha256=digest(manifest.authority_path('verified-volume-'+str(i)).read_bytes()),carriers=source['carriers'],encoding_dispositions={'utf8_bom':raw.startswith(b'\xef\xbb\xbf'),'crlf_to_lf':raw.count(b'\r\n')},sermons=18,contents_sermons=18,complete_eight_volume_claim=False,provider_administration_disposition='Complete literal opening/start marker and end marker/footer are delivered in README.source.md; excluded from book projection.')
        assert volume_account==json.loads(manifest.authority_path('verified-account-'+str(i)).read_bytes())
        accounts.append(volume_account)
    expected=dict(contract='ocd-newman-parochial-one-work-accountability-v1',content_sha256=digest(content),one_work=True,volume_order=['VII','VIII'],source_members=accounts,excluded_ocr_editions=profile['excluded_ocr_editions'],complete_eight_volume_claim=False,member_header_disposition='Exact original source bibliographies conserved; shared author asserted once; original volume title/front matter conserved inside each volume wrapper; repeated source-location note role renamed retained-source-location without changing its value.')
    assert account==expected and candidate.member_bytes('source-accountability.json')==canonical(expected)
    expected_provenance=dict(contract='ocd-newman-parochial-pg-one-work-provenance-v1',work_id='newman-parochial-sermons',textual_form_id='newman-parochial-gutenberg-english',edition_id='newman-parochial-sermons-pg-vii-viii-retained-electronic',source_order=['VII','VIII'],candidate_status='nonaccepted',supported_scope='One work containing the two complete retained non-OCR PG electronic volumes VII–VIII only; six IA OCR volumes I–VI excluded; no full eight-volume or collated print claim.',human_review='not-recorded',rights='not-assessed-for-publication')
    assert policy['provenance']==expected_provenance and candidate.member_bytes('provenance.json')==canonical(expected_provenance)
    expected_unresolved=[]
    for fact in facts:
        expected_unresolved.extend(dict(id=Path(fact['source_path']).stem+'-source-exception-'+str(i+1),status='literal-source-exception-preserved',scope=exception) for i,exception in enumerate(fact['exceptions']))
    expected_unresolved.append(dict(id='newman-one-work-scope-boundaries',status='unassessed-stronger-claims',items=['Six IA OCR volumes I–VI excluded; complete eight-volume print title is not reconstructed.','One retained non-OCR scoped work in one TEI; VII/VIII remain source-native volumes, not independent works.','Literal 1891 title-page assertions; no uniform 1868 edition, print collation, human acceptance, rights clearance or publication.']))
    assert policy['unresolved']==expected_unresolved and candidate.member_bytes('unresolved.jsonl')==b''.join(canonical(x) for x in expected_unresolved)
    readme=candidate.member_bytes('README.source.md');assert readme==manifest.authority_path('source-readme').read_bytes()
    for i,member in enumerate(manifest.record['source_members'],1):
        source=enumerate_source(manifest.authority_path('retained-source-'+str(i)).read_bytes(),member['path'])
        assert source['text'][:source['book_start']].encode() in readme and source['text'][source['book_stop']:].encode() in readme
    return facts
def _oracle(manifest,candidate):
    complete_check(manifest,candidate);bound=closure(manifest.repository_root);assert bound==manifest.record['validator']['import_closure_sha256']
    members=sorted([{k:a[k] for k in ('name','path','bytes','sha256')} for a in manifest.record['authorities'] if a['role']=='primary-source'],key=lambda a:(a['path'],a['name']))
    facts=MechanicalFacts(validator_implementation_sha256=digest(Path(__file__).read_bytes()),validator_import_closure_sha256=bound,source_sha256=digest(canonical(dict(contract='ocd-source-member-set-v1',members=members))),profile_sha256=digest(manifest.authority_path('profile').read_bytes()),package_schema_sha256=digest(manifest.authority_path('candidate-package-schema').read_bytes()),xsd_sha256=digest(manifest.authority_path('tei-p5-xsd').read_bytes()),policy_sha256=digest(manifest.authority_path('policy').read_bytes()),findings=())
    return verify_mechanical_facts(manifest,candidate,facts).as_record()
_oracle.oracle_id='ocd-newman-parochial-pg-one-work-oracle-v1'
_oracle.oracle_version='1'
_oracle.implementation_path=Path(__file__).resolve()
