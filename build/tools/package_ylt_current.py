"""Challenge only source-present YLT retained witness and complete private accounting."""
import argparse,json
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from build.tools.prepare_ylt_current import ROOT,BASE,canonical
from build.tei.ylt_current_oracle import check
NS='{http://www.tei-c.org/ns/1.0}'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('candidate','replay','output'):p.add_argument('--'+n,type=Path,required=True)
    args=p.parse_args();a=CandidatePackage.load(args.candidate/'package');b=CandidatePackage.load(args.replay/'package')
    if a.sha256!=b.sha256 or any(a.member_bytes(n)!=b.member_bytes(n) for n in a.member_names) or (args.candidate/'validation.json').read_bytes()!=(args.replay/'validation.json').read_bytes():raise ValueError('exact fresh replay differs')
    args.output.mkdir(exist_ok=False);m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);raw=a.member_bytes('content.tei.xml');account=a.member_bytes('source-accountability.json');baseline=check(m,raw,account);cases=[]
    names=['wording','space-insertion','verse-omission','verse-order','verse-label','chapter-label','book-order','book-label','unexpected-book-attribute','book-heading','translation-label','header-scope','ledger-omission','ledger-text-digest','ledger-parent']
    for name in names:
        doc=etree.fromstring(raw);text=doc.find(NS+'text');body=text.find(NS+'body');account_obj=json.loads(account)
        first=body[0];chapter=first[1];v=chapter[0]
        if name=='wording':v.text='Invented words'
        elif name=='space-insertion':v.text=v.text+' '
        elif name=='verse-omission':chapter.remove(v)
        elif name=='verse-order':chapter.insert(0,chapter[1])
        elif name=='verse-label':v.set('n','2')
        elif name=='chapter-label':chapter.set('n','2')
        elif name=='book-order':body.insert(0,body[1])
        elif name=='book-label':first.set('n','1')
        elif name=='unexpected-book-attribute':first.set('book_name','Genesis')
        elif name=='book-heading':first[0].text='Normalized book'
        elif name=='translation-label':doc.find('.//'+NS+"bibl[@type='retained-translation-label']").text='YLT print1898 verified'
        elif name=='header-scope':doc.find('.//'+NS+"note[@type='source-label-limitation']").text='Collated complete print copy'
        elif name=='ledger-omission':account_obj['verse_carriers'].pop()
        elif name=='ledger-text-digest':account_obj['verse_carriers'][0]['text_value_sha256']='0'*64
        elif name=='ledger-parent':account_obj['verse_carriers'][0]['identity']['chapter']=2
        altered=etree.tostring(doc,encoding='UTF-8',xml_declaration=True,pretty_print=False);changed_account=canonical(account_obj)
        if name.startswith('ledger-'):
            altered=raw
            if changed_account==account:raise ValueError('inert ledger mutation '+name)
        elif altered==raw:raise ValueError('inert TEI mutation '+name)
        # Original baseline, exact mutation selector and changed artifact hashes retained; avoid18duplicatedfullledgers.
        if name in ('book-label','space-insertion'): (args.output/(name+'.tei.xml')).write_bytes(altered)
        try:check(m,altered,changed_account)
        except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as error:cases.append(dict(name=name,status='rejected',reason=str(error),mutated_sha256=sha256(altered).hexdigest(),mutated_accountability_sha256=sha256(changed_account).hexdigest()));print('Rejected '+name,flush=True)
        else:raise ValueError('accepted mutation '+name)
        (args.output/'partial-result.json').write_bytes(canonical(dict(candidate_sha256=a.sha256,replay_sha256=b.sha256,cases=cases)))
    (args.output/'result.json').write_bytes(canonical(dict(status='pass',baseline=baseline,cases=cases,candidate_sha256=a.sha256,replay_sha256=b.sha256,validation_equal=True)))
if __name__=='__main__':main()
