"""Prove bounded semantic rejection by the unchanged independent source oracle."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from lxml import etree
from build.tools.prepare_matthew_collection import ROOT,BASE,canonical
from build.tei.matthew_collection_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage,SourceManifest

NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
    original=CandidatePackage.load(a.candidate/'package')
    cases=[]
    def mutate(label,operation,expected):
        destination=a.output/label/'package';shutil.copytree(original.path,destination)
        doc=etree.fromstring(original.member_bytes('content.tei.xml'));body=doc.find(NS+'text/'+NS+'body');root=body[0]
        operation(doc,body,root)
        payload=etree.tostring(doc,encoding='UTF-8',xml_declaration=True)
        (destination/'content.tei.xml').write_bytes(payload)
        record=json.loads((destination/'manifest.json').read_bytes())
        item=next(i for i in record['members'] if i['name']=='content.tei.xml');item.update(bytes=len(payload),sha256=sha256(payload).hexdigest())
        (destination/'manifest.json').write_bytes(canonical(record))
        altered=CandidatePackage.load(destination);result=_oracle(manifest,altered)
        if result['status']!='fail' or not any(expected in finding for finding in result['findings']):raise ValueError('Mutation did not reject for intended source comparison: '+label+' '+str(result))
        (destination.parent/'oracle-result.json').write_bytes(canonical(result))
        cases.append(dict(case=label,status='rejected',payload_sha256=sha256(payload).hexdigest(),candidate_sha256=altered.sha256,expected_finding=expected,findings=result['findings'],oracle_result_sha256=result['result_sha256']))
        print(label+': rejected',flush=True)
    def omitlast(d,b,r):r.remove(r[-1])
    def reorder(d,b,r):
        left=r[4];r.remove(left);r.insert(5,left)
    def omitpreface(d,b,r):r.remove(r[2])
    def inventtext(d,b,r):
        n=next(n for n in r.iter(NS+'p') if len(n.text or '')>100);n.text+=' Invented sentence.'
    def movenote(d,b,r):
        n=next(r.iter(NS+'note'));n.getparent().remove(n);r[-1].append(n)
    def changeattr(tag,name,value):
        def f(d,b,r):
            n=next(n for n in r.iter(NS+tag) if name in n.attrib);n.set(name,value)
        return f
    def heading(d,b,r):r[-1].find(NS+'head').text='Homily corrected to LXXXVI.'
    def index(d,b,r):
        raw=etree.fromstring(manifest.authority_path('retained-thml').read_bytes(),etree.XMLParser(resolve_entities=False,no_network=True));n=raw.xpath('/ThML/ThML.body/div1[@id="iv"]')[0]
        extra=etree.SubElement(b,NS+'div',{XML+'id':'npnf110-iv'});etree.SubElement(extra,NS+'head').text=n.get('title')
    def header(d,b,r):d.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+'title').text='Single homily only'
    mutate('omit-final-native-homily',omitlast,'omission duplication')
    mutate('reorder-native-homilies',reorder,'tag or attribute drift')
    mutate('omit-oxford-preface',omitpreface,'omission duplication')
    mutate('invent-ordinary-source-text',inventtext,'direct text or tail drift')
    mutate('detach-original-note-attachment',movenote,'omission duplication')
    mutate('alter-source-passage',changeattr('ref','cRef','Matt. 99. 99'),'tag or attribute drift')
    mutate('alter-native-page-target',changeattr('pb','facs','/ccel/schaff/npnf110/Page_wrong.html'),'tag or attribute drift')
    mutate('alter-original-language',changeattr('foreign',XML+'lang','en'),'tag or attribute drift')
    mutate('alter-native-inline-style',changeattr('hi','rend','bold'),'tag or attribute drift')
    mutate('normalize-source-numbering',heading,'division title drift')
    mutate('neighbor-index-contamination',index,'exactly one complete Matthew collection')
    mutate('invent-work-header-scope',header,'supported title/author differs')
    result=dict(status='pass',candidate_sha256=original.sha256,source_manifest_sha256=manifest.sha256,cases=cases,limits='Mutations reseal only payload integrity; rejection must come from intended original source fidelity, boundary or header check, not stale package SHA.')
    (a.output/'result.json').write_bytes(canonical(result));print(json.dumps(dict(status='pass',cases=len(cases))))
if __name__=='__main__':main()
