"""One scoped Newman work TEI, conserving the verified retained PG volume units."""
from pathlib import Path
from hashlib import sha256
import copy,json
from lxml import etree
T='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
ID='ocd-newman-parochial-pg-one-work-v1'
ENCODING='One source-attested work; retained non-OCR volumes VII and VIII in source order. Each volume wrapper conserves its full source front matter, eighteen sermons and back label, including literal notes, emphasis, coordinates and whitespace. The verified member source-location assertion is renamed retained-source-location without changing its value. Six IA OCR volumes I–VI are excluded; no complete eight-volume or uniform 1868 print edition is claimed. Complete provider notices and credits are delivered in README.source.md.'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def _convert(manifest):
    if (manifest.record['work_id'],manifest.record['ticket_id'],manifest.record['source_id'])!=('newman-parochial-sermons','LIB-018','newman-retained-pg-vii-viii-one-work'):
        raise ValueError('Newman work/member identity differs')
    profile=json.loads(manifest.authority_path('profile').read_bytes());policy=json.loads(manifest.authority_path('policy').read_bytes())
    members=manifest.record['source_members'];assert len(members)==len(profile['members'])==2
    root=etree.Element(T+'TEI',nsmap={None:T[1:-1]});header=etree.SubElement(root,T+'teiHeader');fd=etree.SubElement(header,T+'fileDesc')
    ts=etree.SubElement(fd,T+'titleStmt');etree.SubElement(ts,T+'title').text='Parochial and Plain Sermons; retained volumes VII–VIII'
    etree.SubElement(ts,T+'author').text='JOHN HENRY NEWMAN, B.D.'
    etree.SubElement(etree.SubElement(fd,T+'publicationStmt'),T+'p').text='Nonaccepted one-work reconstruction of the exact retained non-OCR PG volumes VII–VIII; human, print, rights and publication decisions remain open.'
    desc=etree.SubElement(fd,T+'sourceDesc');etree.SubElement(etree.SubElement(header,T+'encodingDesc'),T+'p').text=ENCODING
    body=etree.SubElement(etree.SubElement(root,T+'text',{X+'lang':'en'}),T+'body');accounts=[]
    for i,(declared,entry) in enumerate(zip(members,profile['members'],strict=True),1):
        raw=manifest.authority_path('retained-source-'+str(i)).read_bytes()
        if dict(declared)!=entry['source_member'] or declared['bytes']!=len(raw) or declared['sha256']!=sha256(raw).hexdigest():raise ValueError('Newman work declared source bytes differ')
        authority=next(a for a in manifest.record['authorities'] if a['name']=='retained-source-'+str(i))
        if authority['path']!=declared['path'] or authority['role']!='primary-source':raise ValueError('Newman primary member differs')
        fragment=manifest.authority_path('verified-volume-'+str(i)).read_bytes();assert sha256(fragment).hexdigest()==entry['verified_tei_sha256']
        volume=etree.fromstring(fragment);bibl=copy.deepcopy(volume.find(T+'teiHeader/'+T+'fileDesc/'+T+'sourceDesc/'+T+'bibl'))
        bibl.find(T+'note').set('type','retained-source-location');desc.append(bibl)
        wrapper=etree.SubElement(body,T+'div',{'type':'source-div1','n':entry['volume'],X+'id':entry['slug']+'-volume'})
        for part in volume.find(T+'text'):
            for unit in part:wrapper.append(copy.deepcopy(unit))
        account=json.loads(manifest.authority_path('verified-account-'+str(i)).read_bytes());assert account['source_path']==declared['path'] and account['source_sha256']==declared['sha256']
        accounts.append(account)
    content=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
    account=dict(contract='ocd-newman-parochial-one-work-accountability-v1',content_sha256=sha256(content).hexdigest(),one_work=True,volume_order=['VII','VIII'],source_members=accounts,excluded_ocr_editions=profile['excluded_ocr_editions'],complete_eight_volume_claim=False,member_header_disposition='Exact original source bibliographies conserved; shared author asserted once; original volume title/front matter conserved inside each volume wrapper; repeated source-location note role renamed retained-source-location without changing its value.')
    return {'content.tei.xml':content,'source-accountability.json':canonical(account),'README.source.md':manifest.authority_path('source-readme').read_bytes(),'provenance.json':canonical(policy['provenance']),'unresolved.jsonl':b''.join(canonical(x) for x in policy['unresolved'])}
_convert.converter_id=ID
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()
