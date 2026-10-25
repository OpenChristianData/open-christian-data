"""Bounded independent negative proof for the complete retained Hodge volume."""
from copy import deepcopy
from hashlib import sha256
import argparse
import json
from pathlib import Path
from lxml import etree
from build.tei.hodge_vol1_complete_oracle import inspect,check,parse,NS,XML,canonical
from build.tools.prepare_hodge_vol1_complete import ROOT,BASE
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','replay','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    manifest=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT)
    package=CandidatePackage.load(args.candidate/'package');replay=CandidatePackage.load(args.replay/'package')
    if package.sha256!=replay.sha256 or any(package.member_bytes(n)!=replay.member_bytes(n) for n in package.member_names):
        raise ValueError('Exact fresh-process replay differs')
    source=manifest.authority_path('primary-source').read_bytes();historical=manifest.authority_path('historical-candidate').read_bytes()
    raw=package.member_bytes('content.tei.xml');account=package.member_bytes('source-accountability.json')
    baseline=check(manifest,raw)
    cases=[]
    def run(name,mutate,ledger=False):
        tree=parse(raw);record=json.loads(account)
        mutate(record if ledger else tree.getroot())
        changed=canonical(record) if ledger else etree.tostring(tree,encoding='UTF-8',xml_declaration=True)
        if changed==(account if ledger else raw):raise ValueError('No-op negative proof: '+name)
        try:inspect(source,raw if ledger else changed,changed if ledger else account,historical)
        except ValueError as exc:reason=str(exc)
        else:raise ValueError('Independent oracle accepted mutation: '+name)
        cases.append({'name':name,'status':'rejected','reason':reason,'mutation_sha256':sha256(changed).hexdigest()})
        print(name+': rejected',flush=True)
    def body(root):return root.find(NS+'text/'+NS+'body')
    def first(root,tag,predicate=lambda n:True):return next(n for n in body(root).iter(NS+tag) if predicate(n))
    def remove(root,tag,predicate=lambda n:True):
        node=first(root,tag,predicate);node.getparent().remove(node)
    run('omit-title-root',lambda r:body(r).remove(body(r)[0]))
    run('omit-prefatory-root',lambda r:body(r).remove(body(r)[1]))
    run('omit-index-root',lambda r:body(r).remove(body(r)[4]))
    run('reorder-root',lambda r:body(r).insert(0,body(r)[4]))
    def duplicate(r):
        node=deepcopy(body(r)[4]);
        for n in node.iter():
            if n.get(XML+'id'):n.set(XML+'id',n.get(XML+'id')+'-duplicated')
        body(r).append(node)
    run('duplicate-index-root',duplicate)
    run('alter-title-wording',lambda r:setattr(first(r,'p'), 'text',(first(r,'p').text or '')+' ALTERED'))
    run('omit-contents-row',lambda r:remove(r,'row'))
    run('alter-header-role',lambda r:first(r,'cell',lambda n:n.get('role')=='label').attrib.pop('role'))
    run('alter-cell-wording',lambda r:setattr(first(r,'cell'),'text',(first(r,'cell').text or '')+' ALTERED'))
    run('omit-rowspan',lambda r:first(r,'cell',lambda n:n.get('rows')).attrib.pop('rows'))
    run('alter-rowspan',lambda r:first(r,'cell',lambda n:n.get('rows')).set('rows','99'))
    run('omit-colspan',lambda r:first(r,'cell',lambda n:n.get('cols')).attrib.pop('cols'))
    run('omit-column-layout',lambda r:remove(r,'head',lambda n:n.get('type')=='source-column-layout'))
    run('omit-note',lambda r:remove(r,'note'))
    run('omit-page',lambda r:remove(r,'pb'))
    run('alter-language',lambda r:next(n for n in body(r).iter() if n.get(XML+'lang')).set(XML+'lang','xx'))
    run('omit-source-cell-annotation',lambda r:first(r,'cell').attrib.pop('ana'))
    run('alter-target-link',lambda r:first(r,'ref',lambda n:n.get('type')=='source-link').set('target','#invented-target'))
    run('alter-source-href-annotation',lambda r:first(r,'ref',lambda n:n.get('type')=='source-link').set('ana','urn:changed'))
    run('omit-source-index-marker',lambda r:remove(r,'anchor'))
    run('alter-generated-wrapper-role',lambda r:first(r,'div',lambda n:n.get('type')=='source-order-wrapper').set('type','invented'))
    run('alter-legacy-title',lambda r:setattr(first(r,'head',lambda n:not n.attrib),'text','ALTERED TITLE'))
    def reparent(r):
        n=first(r,'note');n.getparent().remove(n);body(r)[4].append(n)
    run('reparent-note',reparent)
    run('alter-ledger-attribute',lambda a:a['rows'][0]['source_attributes'].append(['invented','value']),True)
    run('reorder-ledger',lambda a:a['rows'].reverse(),True)
    run('omit-ledger-record',lambda a:a['rows'].pop(),True)
    run('alter-source-prolog',lambda a:a['document_prolog']['before'][0].update(text='changed'),True)
    run('alter-source-header',lambda a:a.update(retained_header_xml='changed'),True)
    run('alter-link-crosswalk',lambda a:a['index_link_crosswalk'][0].update(literal_href='changed'),True)
    def erase_year(r):
        for n in r.find(NS+'teiHeader').iter():
            if n.text:n.text=n.text.replace('1940','UNRECORDED')
            if n.tail:n.tail=n.tail.replace('1940','UNRECORDED')
    run('erase-primary-header-year',erase_year)
    result={'status':'pass','candidate_sha256':package.sha256,'replay_sha256':replay.sha256,'baseline':baseline,'cases':cases,'source_sha256':sha256(source).hexdigest()}
    (args.output/'result.json').write_bytes(canonical(result));print(json.dumps({'status':'pass','cases':len(cases)}))


if __name__=='__main__':main()
