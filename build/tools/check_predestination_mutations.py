"""Reseal ten meaningful semantic mutations and require source-oracle rejection."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
from lxml import etree
from build.tei.predestination_oracle import _oracle
from build.tools.prepare_predestination import ROOT, BASE, canonical
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage
T='{http://www.tei-c.org/ns/1.0}'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);c=CandidatePackage.load(a.candidate/'package');baseline=_oracle(m,c)
    a.output.mkdir(parents=True,exist_ok=False);results=[]
    cases=['omit-book-two','book-order','omit-paragraph','invent-text','note-attachment','scripture-attribute','page-target','book-two-title','source-comment','neighbor-contamination']
    for name in cases:
        target=a.output/name;shutil.copytree(c.path,target);r=etree.fromstring(c.member_bytes('content.tei.xml'));work=r.find(T+'text/'+T+'body')[0]
        if name=='omit-book-two':work.remove(work[-1])
        elif name=='book-order':
            node=work[-1];work.remove(node);work.insert(1,node)
        elif name=='omit-paragraph':
            node=work.find('.//'+T+'p');node.getparent().remove(node)
        elif name=='invent-text':work.find('.//'+T+'p').text='INVENTED SOURCE WORDS'
        elif name=='note-attachment':
            node=work.find('.//'+T+'note');node.getparent().remove(node);work.append(node)
        elif name=='scripture-attribute':work.find('.//'+T+'ref').set('target','Gen.1.1')
        elif name=='page-target':work.find('.//'+T+'pb').set('facs','https://invalid.example/page')
        elif name=='book-two-title':work[-1][0].text='A Different Independent Work'
        elif name=='source-comment':work.xpath('.//comment()')[0].text='changed native comment'
        else:
            from build.tei import npnf105_reconstruction as mapper
            native=etree.fromstring(m.authority_path('retained-thml').read_bytes()).find('ThML.body')
            neighbor=next(n for n in native if n.get('id')=='xx')
            mapper._append_source_node(neighbor,work,[],None)
        raw=etree.tostring(r,encoding='UTF-8',xml_declaration=True)
        if raw==c.member_bytes('content.tei.xml'):raise ValueError('unchanged mutation: '+name)
        (target/'content.tei.xml').write_bytes(raw);record=json.loads((target/'manifest.json').read_bytes());next(v for v in record['members'] if v['name']=='content.tei.xml').update(bytes=len(raw),sha256=sha256(raw).hexdigest());(target/'manifest.json').write_bytes(canonical(record))
        try:_oracle(m,CandidatePackage.load(target))
        except ValueError as error:
            finding=str(error)
            if not any(v in finding for v in ['TEI child count differs','TEI attributes differ','TEI direct or tail text differs','division heading differs','source comment differs','TEI tag differs']):raise ValueError('unexpected rejection: '+name+': '+finding) from error
        else:raise ValueError('mutation accepted: '+name)
        results.append(dict(mutation=name,status='rejected',candidate_sha256=sha256(raw).hexdigest(),findings=[finding]));print(name+': rejected',flush=True)
    (a.output/'result.json').write_bytes(canonical(dict(status='pass',baseline=baseline,cases=results)))
if __name__=='__main__':main()
