"""Challenge only the renewed aliases/header; reuse dated source negatives."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from build.tei.modern_scepticism_current_oracle import inspect,check,parse,NS,canonical
from build.tools.prepare_modern_scepticism_current import ROOT,BASE
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','replay','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
    package=CandidatePackage.load(args.candidate/'package');replay=CandidatePackage.load(args.replay/'package')
    if package.sha256!=replay.sha256 or any(package.member_bytes(n)!=replay.member_bytes(n) for n in package.member_names):raise ValueError('New alias/header package replay differs')
    if (args.candidate/'validation.json').read_bytes()!=(args.replay/'validation.json').read_bytes():raise ValueError('Current validation replay differs')
    source=manifest.authority_path('primary-source').read_bytes();historical=manifest.authority_path('historical-candidate').read_bytes()
    raw=package.member_bytes('content.tei.xml');baseline=check(manifest,raw);cases=[]
    def first(root,tag,predicate=lambda n:True):return next(n for n in root.find(NS+'text').iter(NS+tag) if predicate(n))
    def run(name,mutate,header=False):
        root=parse(raw);mutate(root);changed=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
        if changed==raw:raise ValueError('No-op mutation: '+name)
        try:
            if header:check(manifest,changed)
            else:inspect(source,historical,changed)
        except ValueError as exc:reason=str(exc)
        else:raise ValueError('Independent checker accepted mutation: '+name)
        cases.append({'name':name,'status':'rejected','reason':reason,'mutation_sha256':sha256(changed).hexdigest()});print(name+': rejected',flush=True)
    run('revert-rule-alias',lambda r:first(r,'milestone').set('unit','rule'))
    run('alter-rule-role',lambda r:first(r,'milestone').set('unit','page'))
    run('alter-literal-heading-level',lambda r:first(r,'ab',lambda n:n.get('type','').startswith('source-h')).set('type','source-h9'))
    run('omit-thought-break-origin',lambda r:first(r,'ab',lambda n:n.get('subtype')=='thought_break').attrib.pop('subtype'))
    run('alter-thought-break-rend',lambda r:first(r,'ab',lambda n:n.get('subtype')=='thought_break').set('rend','invented'))
    run('omit-source-row-style',lambda r:first(r,'row',lambda n:n.get('ana')).attrib.pop('ana'))
    run('alter-source-row-style',lambda r:first(r,'row',lambda n:n.get('ana')).set('ana','urn:changed'))
    run('alter-renewed-credit',lambda r:setattr(r.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt')[-1][-1],'text','Invented electronic producer'),True)
    result={'status':'pass','candidate_sha256':package.sha256,'replay_sha256':replay.sha256,'baseline':baseline,'cases':cases,'historical_source_negatives_reused':10,'source_sha256':sha256(source).hexdigest()}
    (args.output/'result.json').write_bytes(canonical(result));print(json.dumps({'status':'pass','new_cases':len(cases),'dated_source_cases_reused':10}))

if __name__=='__main__':main()
