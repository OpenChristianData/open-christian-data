"""Group both full installed Isaiah volume envelopes without re-emitting them."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage,SourceManifest
from ocd_kernel.tei.writer import tei_el

ROOT=Path(__file__).resolve().parents[2]
WORK='expositors-bible--george-adam-smith'
KEY='smith-ga-isaiah-complete'
MEMBERS=('smith-ga-expositorisa1','smith-ga-expositorisa2')
TITLE="The Expositor's Bible: The Book of Isaiah"
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
STATUS='Nonaccepted complete electronic Book of Isaiah from two already acquired source volumes. Distinct London1910 and London1890 print witnesses remain separate. Human acceptance, print collation, rights and publication remain unresolved.'

def sha(raw):return sha256(raw).hexdigest()
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')

def convert(source:SourceManifest):
    source.verify();scope=json.loads(source.authority_path('scope-assessment').read_bytes())
    if scope['ordered_members']!=list(MEMBERS) or scope['source_volumes']!=2 or scope['complete_works']!=1:raise ValueError('Complete Isaiah source denominator differs')
    packages=[];roots=[]
    for member in MEMBERS:
        p=CandidatePackage.load(source.authority_path(member+'-manifest').parent);p.verify_integrity();packages.append(p);roots.append(etree.fromstring(p.member_bytes('content.tei.xml')))
    root=tei_el('TEI',{'xml:id':KEY});header=tei_el('teiHeader');fd=tei_el('fileDesc');ts=tei_el('titleStmt');ts.append(tei_el('title',text=TITLE))
    for role in ('author','editor'):
        values=[r.findtext(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+role) for r in roots]
        if not values[0] or len(set(values))!=1:raise ValueError('Common primary author/editor differs')
        ts.append(tei_el(role,text=values[0]))
    fd.append(ts);pub=tei_el('publicationStmt');pub.append(tei_el('p',text=STATUS));fd.append(pub)
    desc=tei_el('sourceDesc');qual=tei_el('bibl');qual.append(tei_el('note',{'type':'complete-work-scope'},text=scope['boundary']));qual.append(tei_el('note',{'type':'shared-material-disposition'},text=scope['shared_material']));qual.append(tei_el('note',{'type':'excluded-partial-work'},text=scope['excluded']));desc.append(qual)
    text=tei_el('text',{'xml:lang':'en'});group=tei_el('group',{'xml:id':KEY+'-volumes'})
    for member,component,package,row in zip(MEMBERS,roots,packages,scope['volumes'],strict=True):
        original=component.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc');bibls=original.findall(NS+'bibl')
        if len(bibls)!=2:raise ValueError('Complete source-volume metadata expected')
        bibl=deepcopy(bibls[1]);bibl.set(XML+'id',member+'-source');bibl.set('type','retained-source-volume');bibl.insert(0,deepcopy(bibls[0][0]))
        bibl.append(tei_el('note',{'type':'retained-source-document-prefix'},text=row['document_prefix']))
        bibl.append(tei_el('note',{'type':'retained-source-uri-context'},text=row['source_url']))
        desc.append(bibl)
        volume=deepcopy(component.find(NS+'text'))
        if volume.attrib!={XML+'lang':'en'}:raise ValueError('Unexpected preexisting native text attributes')
        volume.set(XML+'id',member+'-volume');volume.set(XML+'base',row['source_url']);group.append(volume)
    fd.append(desc);header.append(fd);root.extend([header,text]);text.append(group)
    profile=json.loads(source.authority_path('complete-profile').read_bytes())
    account=dict(contract='ocd-smith-isaiah-complete-accounting-v1',work_id=WORK,complete_work_id=KEY,complete_works=1,source_volumes=2,ordered_members=list(MEMBERS),profile=profile,volume_accounting=[json.loads(p.member_bytes('source-accountability.json')) for p in packages],native_changes='Only two synthetic volume text IDs and two acquired-URL xml:base attributes. All preexisting text fields, attributes, children, attachment and volume front/body/back are preserved exactly; independent raw inverses prove all source readings. Original full document prefixes are human-visible and accounted.',historical_package_provenance=[json.loads(p.member_bytes('provenance.json')) for p in packages])
    provenance=dict(contract='ocd-smith-isaiah-composite-provenance-v1',status='nonaccepted',work_id=WORK,complete_work_id=KEY,title=TITLE,ordered_members=list(MEMBERS),source_manifest_sha256=source.sha256,converter=dict(source.record['converter']),producer_recipe_sha256=sha(Path(__file__).read_bytes()),oracle_sha256=sha(source.authority_path('independent-oracle').read_bytes()),source_profile=profile,historical_packages='Immutable already installed source-volume packages are ingredients, not the sole current producer. Complete-work recipe groups both serialized text envelopes and binds each original acquired URI context.',human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
    unresolved=b''
    for m,p in zip(MEMBERS,packages,strict=True):
        for line in p.member_bytes('unresolved.jsonl').splitlines():
            row=json.loads(line);row['source_member_id']=m;unresolved+=canonical(row)
    unresolved+=canonical(dict(id=KEY+'-identity-print-rights',status='unresolved',detail=STATUS))
    for row in profile['volumes']:
        for i,gap in enumerate(row['source_navigation_gaps'],1):unresolved+=canonical(dict(id=row['member_id']+'-source-navigation-gap-'+str(i),status='unresolved',kind='missing-source-navigation-target',source_member_id=row['member_id'],source_id=gap['id'],source_attribute=gap['attribute'],literal_target=gap['target'],detail='Target is absent from the complete acquired source ID set; no destination is invented.'))
    return {'content.tei.xml':etree.tostring(root,encoding='UTF-8',xml_declaration=True),'source-accountability.json':canonical(account),'provenance.json':canonical(provenance),'README.source.md':source.authority_path('complete-readme').read_bytes(),'unresolved.jsonl':unresolved}

convert.converter_id='ocd-smith-isaiah-complete-existing-volume-group'
convert.converter_version='1'
convert.implementation_path=Path(__file__).resolve()
