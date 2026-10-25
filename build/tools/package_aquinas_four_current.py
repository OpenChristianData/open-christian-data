"""Challenge the conserved source body, current header and complete HTML ledger."""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
import argparse,json
from lxml import etree
from build.tools.prepare_aquinas_four_current import ROOT,BASE,canonical
from build.tei.aquinas_four_current_oracle import check
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
NS='{http://www.tei-c.org/ns/1.0}'; XML='{http://www.w3.org/XML/1998/namespace}'
def main():
    parser=argparse.ArgumentParser()
    for name in ('candidate','replay','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--resume',type=Path)
    args=parser.parse_args();a=CandidatePackage.load(args.candidate/'package');b=CandidatePackage.load(args.replay/'package')
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (args.candidate/'validation.json').read_bytes()!=(args.replay/'validation.json').read_bytes():raise ValueError('Exact fresh process package/validation replay differs')
    args.output.mkdir(exist_ok=False);m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);raw=a.member_bytes('content.tei.xml');account=a.member_bytes('source-accountability.json');baseline=check(m,raw,account)
    names=['wording','unit-omission','unit-duplication','unit-order','component-order','component-omission','heading-tag','heading-rendition','italic-loss','italic-change','break-omission','break-attachment','question-attachment','article-attachment','question-number','article-number','source-unit-id','source-corresp','analysis-loss','literal-Q811-correction','editorial-insertion-omission','recovered-question-boundary','header-translator','header-bibl-id','header-analysis-label','header-analysis-id','ledger-omission','ledger-order','ledger-attributes','ledger-text','ledger-tail','ledger-parent','ledger-disposition']
    cases=[]
    if args.resume:
        previous=json.loads(args.resume.read_bytes())
        if previous['candidate_sha256']!=a.sha256 or previous['replay_sha256']!=b.sha256 or [c['name'] for c in previous['cases']]!=names[:len(previous['cases'])] or any(c['status']!='rejected' for c in previous['cases']):raise ValueError('Exact passed prefix differs')
        cases=previous['cases']
    for name in names:
        if name in {c['name'] for c in cases}:continue
        doc=etree.fromstring(raw);body=doc.find(NS+'text/'+NS+'body');nodes=list(body.iter());unit=next(n for n in nodes if n.get('corresp','').endswith('#id00050'));head=next(n for n in nodes if n.tag==NS+'head');hi=next(n for n in nodes if n.tag==NS+'hi');lb=next(n for n in nodes if n.tag==NS+'lb');question=next(n for n in nodes if n.tag==NS+'div' and n.get('type')=='question');article=next(n for n in nodes if n.tag==NS+'div' and n.get('type')=='article');ledger=json.loads(account);recipe=dict(case=name)
        if name=='wording':unit.text='Invented wording'
        elif name=='unit-omission':unit.getparent().remove(unit)
        elif name=='unit-duplication':unit.addnext(deepcopy(unit))
        elif name=='unit-order':nextunit=unit.getnext();unit.getparent().remove(unit);nextunit.addnext(unit)
        elif name=='component-order':body.insert(0,body[1])
        elif name=='component-omission':body.remove(body[-1])
        elif name=='heading-tag':head.tag=NS+'p'
        elif name=='heading-rendition':next(n for n in nodes if n.get('rend','').startswith('source-h')).set('rend','source-h9')
        elif name=='italic-loss':hi.attrib.pop('rend')
        elif name=='italic-change':hi.set('rend','bold')
        elif name=='break-omission':lb.getparent().remove(lb)
        elif name=='break-attachment':lb.getparent().remove(lb);unit.append(lb)
        elif name=='question-attachment':unit.getparent().remove(unit);question.append(unit)
        elif name=='article-attachment':unit.getparent().remove(unit);article.append(unit)
        elif name=='question-number':question.set('n','999')
        elif name=='article-number':article.set('n','999')
        elif name=='source-unit-id':unit.set(XML+'id','invented-unit')
        elif name=='source-corresp':unit.set('corresp','https://example.invalid/#invented')
        elif name=='analysis-loss':next(n for n in nodes if n.get('ana')).attrib.pop('ana')
        elif name=='literal-Q811-correction':next(n for n in nodes if n.get(XML+'id')=='pg18755-id11244').text='Corrected Q.81'
        elif name=='editorial-insertion-omission':n=next(n for n in nodes if n.get('type')=='editorial-insertion');n.getparent().remove(n)
        elif name=='recovered-question-boundary':next(n for n in nodes if n.get('type')=='question' and '#source-question-heading-omitted' in n.get('ana','')).set('n','999')
        elif name=='header-translator':doc.find('.//'+NS+'name').text='Invented translator'
        elif name=='header-bibl-id':doc.find('.//'+NS+'bibl').set(XML+'id','invented-bibl')
        elif name=='header-analysis-label':doc.find('.//'+NS+'item').text='Invented analysis'
        elif name=='header-analysis-id':doc.find('.//'+NS+'item').set(XML+'id','invented-analysis')
        elif name=='ledger-omission':ledger['nodes'].pop()
        elif name=='ledger-order':ledger['nodes'][0],ledger['nodes'][1]=ledger['nodes'][1],ledger['nodes'][0]
        elif name=='ledger-attributes':ledger['nodes'][100]['attributes'].append(['invented','true'])
        elif name=='ledger-text':ledger['nodes'][100]['text']='Invented source wording'
        elif name=='ledger-tail':ledger['nodes'][100]['tail']='Invented tail'
        elif name=='ledger-parent':ledger['nodes'][100]['parent']=999
        elif name=='ledger-disposition':ledger['nodes'][100]['disposition']='unexplained-exclusion'
        altered=raw if name.startswith('ledger-') else etree.tostring(doc,encoding='UTF-8',xml_declaration=True,pretty_print=False)
        changed=canonical(ledger)
        if name.startswith('ledger-') and changed==account:raise ValueError('Inert ledger challenge')
        if not name.startswith('ledger-') and etree.tostring(doc)==etree.tostring(etree.fromstring(raw)):raise ValueError('Inert TEI challenge')
        try:check(m,altered,changed)
        except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as error:cases.append(dict(name=name,status='rejected',reason=str(error),mutated_tei_sha256=sha256(altered).hexdigest(),mutated_accountability_sha256=sha256(changed).hexdigest(),reproducible_recipe=recipe));print('Rejected '+name,flush=True)
        else:raise ValueError('Mutation escaped '+name)
        (args.output/'partial-result.json').write_bytes(canonical(dict(candidate_sha256=a.sha256,replay_sha256=b.sha256,cases=cases)))
    (args.output/'result.json').write_bytes(canonical(dict(status='pass',baseline=baseline,cases=cases,candidate_sha256=a.sha256,replay_sha256=b.sha256,validation_equal=True,qualification='Each compact mutation recipe/digest is reproducible from the frozen baseline using this pinned script; large repeated mutant payloads are not duplicated.')))
if __name__=='__main__':main()
