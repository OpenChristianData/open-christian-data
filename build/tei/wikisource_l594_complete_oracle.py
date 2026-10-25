"""Independent observed-carrier checks for the complete L594 witness."""
from __future__ import annotations
import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from lxml import etree, html

ORACLE_ID='ocd-l594-complete-source-carrier-oracle'
ORACLE_VERSION='1'
T='{http://www.tei-c.org/ns/1.0}'
M='{http://www.mediawiki.org/xml/export-0.11/}'

def encoded(v): return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(v): return hashlib.sha256(v).hexdigest()
def norm(v): return ' '.join((v or '').split())
def closure(root): return sha(encoded([{'path':p,'sha256':sha((root/p).read_bytes())} for p in ['build/tei/wikisource_l594_complete_oracle.py','ocd_kernel/reconstruction/contract.py']]))

def findings(manifest, raw):
    problems=[]
    xml=ET.fromstring(manifest.authority_path('official-source-member').read_bytes())
    pages=xml.findall(M+'page')
    if len(pages)!=122: problems.append('complete 122-record XML inventory differs')
    q=[re.search(r'pagequality level="(\d+)"',p.findtext(M+'revision/'+M+'text') or '').group(1) for p in pages[4:]]
    if q.count('4')!=109 or q.count('0')!=9: problems.append('validated/blank page census differs')
    rendered=json.loads(manifest.authority_path('rendered-text').read_bytes())
    doc=html.fromstring(rendered['parse']['text'])
    source=doc.xpath('.//div[@class="prp-pages-output"]')[0]
    for n in source.xpath('.//style|.//link|.//*[contains(concat(" ",normalize-space(@class)," ")," ws-noexport ")]|.//*[contains(concat(" ",normalize-space(@class)," ")," wst-dhr ")]|.//*[contains(concat(" ",normalize-space(@class)," ")," __nop ")]'):
        if n.getparent() is not None: n.drop_tree()
    actual=etree.fromstring(raw)
    content=actual.find('.//'+T+'body/'+T+'div')
    if norm(''.join(source.itertext()))!=norm(''.join(content.itertext())): problems.append('complete readable wording/order differs')
    # Compare carriers and their full mixed content, rather than just whole-text equality.
    for h,t in [('p','p'),('table','table'),('tr','row'),('td','cell'),('figure','figure'),('i','hi')]:
        expected=[norm(''.join(n.itertext())) for n in source.iter(h)]
        observed=[norm(''.join(n.itertext())) for n in content.iter(T+t) if h!='i' or n.get('rend','').split(' ',1)[0]=='i']
        if expected!=observed: problems.append(h+' carrier order/content/attachment differs')
    expected=[n.get('data-page-index') for n in source.xpath('.//*[@data-page-index]')]
    if expected!=[n.get('n') for n in content.iter(T+'pb')]: problems.append('page positions/order differ')
    for h,t in [('div','div'),('span','hi')]:
        expected=[norm(''.join(n.itertext())) for n in source.iter(h) if n is not source and not n.get('data-page-index')]
        observed=[norm(''.join(n.itertext())) for n in content.iter(T+t) if n is not content and (h!='div' or n.get('type')=='source-layout') and (h!='span' or n.get('rend','').split(' ',1)[0] not in {'i','b'})]
        # Page-marker wrappers become empty hi; include them in the source too.
        if expected!=observed: problems.append(h+' nested grouping differs')
    reds=[norm(''.join(n.itertext())) for n in source.xpath('.//span[contains(@style,"color:#8B0000")]')]
    if reds!=[norm(''.join(n.itertext())) for n in content.iter(T+'hi') if 'color:#8B0000' in n.get('rend','')]: problems.append('rubric color/content attachment differs')
    graphics=list(content.iter(T+'graphic'))
    if len(graphics)!=2 or not graphics[0].get('url','').endswith('Liturgy_of_John_Chrysostom_diagram.png') or not graphics[1].get('url','').endswith('IC_XC_NI_KA_-_Liturgy_of_John_Chrysostom.png'): problems.append('graphic identities/order differ')
    if actual.findtext('.//'+T+'div[@type="printer-imprint"]/'+T+'p')!='J. MASTERS AND SON, PRINTERS, ALDERSGATE ST., LONDON.': problems.append('final printer imprint differs')
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path('p5-schema'))))
    if not schema.validate(actual): problems.append('P5: '+str(schema.error_log.last_error))
    return problems

def _oracle(manifest,candidate):
    problems=findings(manifest,candidate.member_bytes('content.tei.xml'))
    att={'status':'fail' if problems else 'pass','oracle_id':ORACLE_ID,'oracle_version':ORACLE_VERSION,
         'implementation_sha256':sha(Path(__file__).read_bytes()),'import_closure_sha256':closure(manifest.repository_root),
         'runtime':f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',
         'source_manifest_sha256':manifest.sha256,'candidate_sha256':candidate.sha256,
         'profile_sha256':sha(manifest.authority_path('profile').read_bytes()),'package_schema_sha256':manifest.record['package_schema']['sha256'],
         'source_sha256':sha(manifest.authority_path('rendered-text').read_bytes()),'xsd_sha256':sha(manifest.authority_path('p5-schema').read_bytes()),
         'policy_sha256':sha(manifest.authority_path('policy').read_bytes()),'findings':problems}
    att['result_sha256']=sha(encoded(att));return att

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
