"""Exact fresh replay and meaningful independent source/structure mutations."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from lxml import etree
from pathlib import Path
from build.tools.prepare_brainerd_current import ROOT,BASE,canonical
from build.tei.brainerd_current_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
def challenge(manifest,raw):
    baseline=check(manifest,raw);cases=[]
    for name in ('wording','omission','duplication','order','attachment','heading-level','source-class','italic-id','note-number','scripture-target','root-tail','header-credit','editorial-qualification','sermon-attribution','flattening'):
        d=etree.fromstring(raw);s=d.find(NS+'text/'+NS+'body')[0];p=next(n for n in s.iter(NS+'p') if (n.text or '').strip());parts=list(s.iter(NS+'div'))
        if name=='wording':p.text='Invented opening'
        elif name=='omission':p.getparent().remove(p)
        elif name=='duplication':p.addnext(deepcopy(p))
        elif name=='order':
            moved=s[2];s.remove(moved);s.insert(1,moved)
        elif name=='attachment':parts[2].append(p)
        elif name=='heading-level':p.set('rend','source-heading h1')
        elif name=='source-class':next(n for n in s.iter(NS+'p') if n.get('rend')=='Body').set('rend','normalized')
        elif name=='italic-id':next(s.iter(NS+'hi')).set(XML+'id','invented')
        elif name=='note-number':next(s.iter(NS+'note')).set('n','999')
        elif name=='scripture-target':next(s.iter(NS+'ref')).set('target','Bible:Gen.99.99')
        elif name=='root-tail':s.tail='invented'
        elif name=='header-credit':d.find('.//'+NS+'name').text='Invented editor'
        elif name=='editorial-qualification':next(n for n in s.iter(NS+'p') if n.get(XML+'id')=='ix.i-p19').text='Every original diary is complete and unabridged.'
        elif name=='sermon-attribution':next(n for n in s.iter(NS+'p') if n.get(XML+'id','').startswith('ix.xi-p') and n.text).text='Jonathan Edwards preached this sermon.'
        elif name=='flattening':parts[1].tag=NS+'p'
        b=etree.tostring(d,encoding='UTF-8',xml_declaration=True)
        if b==raw:raise ValueError('Mutation did not change candidate')
        try:check(manifest,b)
        except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as error:cases.append(dict(name=name,status='rejected',reason=str(error),mutated_sha256=sha256(b).hexdigest()))
        else:raise ValueError('Oracle accepted mutation '+name)
    return dict(status='pass',baseline=baseline,cases=cases)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--candidate',type=Path,required=True);parser.add_argument('--replay',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    c=CandidatePackage.load(a.candidate/'package');r=CandidatePackage.load(a.replay/'package')
    if c.sha256!=r.sha256 or any(c.member_bytes(n)!=r.member_bytes(n) for n in c.member_names):raise ValueError('Fresh six-member replay differs')
    if (a.candidate/'validation.json').read_bytes()!=(a.replay/'validation.json').read_bytes():raise ValueError('Fresh validation bytes differ')
    m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);proof=challenge(m,c.member_bytes('content.tei.xml'));proof.update(candidate_sha256=c.sha256,replay_sha256=r.sha256,validation_equal=True,candidate_root=a.candidate.as_posix(),replay_root=a.replay.as_posix())
    a.output.mkdir(parents=True,exist_ok=False);(a.output/'result.json').write_bytes(canonical(proof));print(json.dumps(dict(status='pass',cases=len(proof['cases']),candidate_sha256=c.sha256)))
if __name__=='__main__':main()
