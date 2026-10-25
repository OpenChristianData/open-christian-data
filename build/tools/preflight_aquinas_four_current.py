"""Read-only reconciliation of the retained four-part Aquinas handoff."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
from lxml import etree, html
from ocd_kernel.library._common import io_path
ROOT=Path(__file__).resolve().parents[2]
WORK='aquinas-summa-theologica-four-parts'
LOG=ROOT/'reports/_logs/aquinas-four-current-reconciliation-20261002-v1'
EDITION=Path('library/works')/WORK/'forms'/(WORK+'-gutenberg-retained-en')/'editions'/(WORK+'-gutenberg-electronic')
CANDIDATE=Path('reports/clean-ready-acquisition-to-tei/master-1/09')/WORK/'candidate.tei.xml'
NS={'t':'http://www.tei-c.org/ns/1.0'}
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
def digest(path): return sha256(io_path(path).read_bytes()).hexdigest()
def put(name,value):
    LOG.mkdir(parents=True,exist_ok=True); path=LOG/name
    if path.exists(): raise FileExistsError(path)
    path.write_bytes((json.dumps(value,ensure_ascii=True,indent=2,sort_keys=True)+'\n').encode())
def inline(source,target):
    if source.text!=target.text: raise ValueError('Direct text differs '+str(source.get('id')))
    if len(source)!=len(target): raise ValueError('Inline arity differs')
    for left,right in zip(source,target,strict=True):
        if (left.tag,etree.QName(right).localname) not in [('i','hi'),('br','lb')]: raise ValueError('Inline carrier differs')
        expected={'rend':'italic'} if left.tag=='i' else {}
        if dict(right.attrib)!=expected or left.attrib: raise ValueError('Inline attrs differ')
        inline(left,right)
        if left.tail!=right.tail: raise ValueError('Inline tail differs')
def main():
    if digest(ROOT/CANDIDATE)!='29b5a5542140557f91ae2b990e90cfb9022ffc32be074daa36b388a99fdda1d5': raise ValueError('Historical handoff changed')
    tree=etree.fromstring(io_path(ROOT/CANDIDATE).read_bytes()); bodies=tree.xpath('/t:TEI/t:text/t:body/t:div',namespaces=NS)
    members=json.loads(io_path(ROOT/EDITION/'source-member-set.json').read_bytes())['members']; reports=[]; total=0
    if len(members)!=4 or len(bodies)!=4: raise ValueError('Four component scope differs')
    for member,component in zip(members,bodies,strict=True):
        path=ROOT/member['path']; raw=io_path(path).read_bytes()
        if sha256(raw).hexdigest()!=member['sha256'] or len(raw)!=member['bytes']: raise ValueError('Acquired source differs')
        source=html.fromstring(raw); body=source.xpath('//body')[0]; units=[n for n in body if isinstance(n.tag,str) and n.tag not in ('header','footer')]
        pgid=Path(member['path']).name.split('-')[0][2:]; prefix='pg'+pgid+'-'
        target=component.xpath('.//*[@corresp and contains(@corresp,"#id")]')
        if len(units)!=len(target): raise ValueError('Full unit accounting differs')
        for left,right in zip(units,target,strict=True):
            if right.get(XML_ID)!=prefix+left.get('id') or not right.get('corresp').endswith('#'+left.get('id')): raise ValueError('Unit identity/order differs')
            if left.tag=='p' and etree.QName(right).localname not in ('p','head'): raise ValueError('Source paragraph carrier differs')
            if left.tag.startswith('h') and etree.QName(right).localname!='head' and not (etree.QName(right).localname=='p' and right.get('rend')=='source-'+left.tag): raise ValueError('Source heading carrier/rend differs '+pgid+'/'+left.get('id'))
            inline(left,right)
        credits=[' '.join(n.itertext()) for n in body.xpath('./header')]
        attrs=Counter((n.tag,k,v) for n in units for k,v in n.attrib.items() if k!='id')
        reports.append(dict(source=member,component_attributes=dict(component.attrib),source_units=len(units),source_tags=dict(Counter(n.tag for n in units)),inline_tags=dict(Counter(n.tag for u in units for n in u.iterdescendants() if isinstance(n.tag,str))),source_extra_attributes=[dict(tag=t,attribute=k,value=v,count=count) for (t,k,v),count in attrs.items()],wrapper_header_text=credits,first_text=''.join(units[0].itertext()),terminal_text=''.join(units[-1].itertext()),source_outer_whitespace_tails=sum(bool(n.tail) for n in units),qualification='Exact source payload/inline text and tails conserved; source-unit outer whitespace tails are HTML layout framing, not appended to the semantic TEI carrier. Gutenberg header/footer remain retained source context, not TEI book text.'))
        total+=len(units)
    authority=[CANDIDATE, CANDIDATE.with_name('accounting.json'),Path('library/works')/WORK/'work.json',Path('library/works')/WORK/'state.json',EDITION/'source-member-set.json',EDITION/'acquisitions'/(WORK+'-gutenberg-acquired.json')]
    before={p.as_posix():digest(ROOT/p) for p in authority}
    put('preflight.json',dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK,candidate_sha256=digest(ROOT/CANDIDATE),source_units=total,components=reports,authority=before,canonical_master_exists=io_path(ROOT/EDITION/'master.tei.xml').exists(),producer_or_oracle_imported=False,scope='One existing partial English Summa witness: four complete retained components I/I-II/II-II/III, dedication/electronic edition notes/contents/prologues/questions/articles and own closing retained; traditional Supplement absent. Provider wrappers explicitly separate retained context. Header/current source-bound acceptance and publication proof remain pending.'))
    print(json.dumps(dict(status='pass',source_units=total,components=4,candidate_sha256=digest(ROOT/CANDIDATE),preflight=str(LOG/'preflight.json'))))
if __name__=='__main__': main()
