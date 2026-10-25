"""Challenge only source-present Murray whole collection and complete private accounting."""
import argparse,json
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from build.tools.prepare_murray_absolute_surrender_current import ROOT,BASE,canonical
from build.tei.murray_absolute_surrender_current_oracle import check
NS='{http://www.tei-c.org/ns/1.0}'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('candidate','replay','output'):p.add_argument('--'+n,type=Path,required=True)
    args=p.parse_args();a=CandidatePackage.load(args.candidate/'package');b=CandidatePackage.load(args.replay/'package')
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (args.candidate/'validation.json').read_bytes()!=(args.replay/'validation.json').read_bytes():raise ValueError('exact fresh replay differs')
    args.output.mkdir(exist_ok=False);m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);raw=a.member_bytes('content.tei.xml');account=a.member_bytes('source-accountability.json');baseline=check(m,raw,account);cases=[]
    names=['wording','address-omission','address-order','index-omission','duplication','literal-head','heading-level','italic-style','paragraph-class','verse-type','verse-line','verse-order','scripture-label','scripture-cRef','hyperlink-target','hyperlink-attachment','header-credit','header-editorial-qualification','ledger-omission','ledger-order','ledger-attribute','ledger-parent','ledger-ordinal','ledger-target','ledger-non-element-event']
    for name in names:
        doc=etree.fromstring(raw);text=doc.find(NS+'text');body=text.find(NS+'body');account_obj=json.loads(account)
        first=body[0];ps=list(first.iter(NS+'p'));v=next(n for n in ps if n.text and n.text.strip());lg=next(text.iter(NS+'lg'));ref=next(n for n in text.iter(NS+'ref') if n.get('cRef'));link=next(n for n in text.iter(NS+'ref') if n.get('target'))
        if name=='wording':v.text='Invented words'
        elif name=='address-omission':body.remove(body[0])
        elif name=='address-order':body.insert(0,body[1])
        elif name=='index-omission':text.remove(text.find(NS+'back'))
        elif name=='duplication':v.addnext(deepcopy(v))
        elif name=='literal-head':next(text.iter(NS+'head')).text='Normalized title'
        elif name=='heading-level':next(text.iter(NS+'head')).set('type','ThML-h9')
        elif name=='italic-style':next(text.iter(NS+'hi')).set('rend','bold')
        elif name=='paragraph-class':next(n for n in text.iter(NS+'p') if n.get('rend')).attrib.pop('rend')
        elif name=='verse-type':lg.attrib.pop('type')
        elif name=='verse-line':lg[0].text='Invented verse'
        elif name=='verse-order':lg.insert(0,lg[1])
        elif name=='scripture-label':ref.set('n','Invented passage')
        elif name=='scripture-cRef':ref.set('cRef','Invented.1')
        elif name=='hyperlink-target':link.set('target','#invented')
        elif name=='hyperlink-attachment':link.getparent().remove(link);body[-1].append(link)
        elif name=='header-credit':doc.find('.//'+NS+'name').text='Invented transcriber'
        elif name=='header-editorial-qualification':doc.find('.//'+NS+"note[@type='source-editorial-comment']").text='Unedited print copy'
        elif name=='ledger-omission':account_obj['crosswalk'].pop()
        elif name=='ledger-order':account_obj['crosswalk'][0],account_obj['crosswalk'][1]=account_obj['crosswalk'][1],account_obj['crosswalk'][0]
        elif name=='ledger-attribute':account_obj['crosswalk'][100]['source_attributes'][0]['value']='invented'
        elif name=='ledger-parent':account_obj['crosswalk'][100]['source_parent_ordinal']=999
        elif name=='ledger-ordinal':account_obj['crosswalk'][100]['source_ordinal']=999
        elif name=='ledger-target':account_obj['crosswalk'][100]['target_xml_id']='invented'
        elif name=='ledger-non-element-event':account_obj['non_element_events'].pop()
        altered=etree.tostring(doc,encoding='UTF-8',xml_declaration=True,pretty_print=False);changed_account=canonical(account_obj)
        if name.startswith('ledger-'):
            altered=raw
            if changed_account==account:raise ValueError('inert ledger mutation '+name)
        elif altered==raw:raise ValueError('inert TEI mutation '+name)
        (args.output/(name+'.tei.xml')).write_bytes(altered);(args.output/(name+'.source-accountability.json')).write_bytes(changed_account)
        try:check(m,altered,changed_account)
        except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as error:cases.append(dict(name=name,status='rejected',reason=str(error),mutated_sha256=sha256(altered).hexdigest(),mutated_accountability_sha256=sha256(changed_account).hexdigest()));print('Rejected '+name,flush=True)
        else:raise ValueError('accepted mutation '+name)
        (args.output/'partial-result.json').write_bytes(canonical(dict(candidate_sha256=a.sha256,replay_sha256=b.sha256,cases=cases)))
    (args.output/'result.json').write_bytes(canonical(dict(status='pass',baseline=baseline,cases=cases,candidate_sha256=a.sha256,replay_sha256=b.sha256,validation_equal=True)))
if __name__=='__main__':main()
