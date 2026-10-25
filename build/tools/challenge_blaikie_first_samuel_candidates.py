"""P5-valid semantic challenges to the one complete First Samuel source gate."""
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import json
from lxml import etree as E
from build.tei.blaikie_first_samuel_retained_native_prepare import ROOT,LOG,canonical,sha
from build.tei.blaikie_first_samuel_retained_native_oracle import check,_p5_schema
from build.tools.prepare_blaikie_first_samuel_candidates import CANDIDATES,MEMBER

NS={'t':'http://www.tei-c.org/ns/1.0'};Q='{'+NS['t']+'}';XML='{http://www.w3.org/XML/1998/namespace}'

def challenge():
 package=CANDIDATES/'package';raw=(package/'content.tei.xml').read_bytes();original=E.fromstring(raw)
 def select(tree,xpath):
  nodes=tree.xpath(xpath,namespaces=NS)
  if not nodes:raise ValueError('Observed source challenge selector absent '+xpath)
  return nodes[0]
 cases=[]
 def attr(name,xpath,key,value):
  cases.append((name,lambda t:select(t,xpath).set(key,value)))
 def text(name,xpath,field='text'):
  def edit(t):
   n=select(t,xpath);setattr(n,field,(getattr(n,field) or '')+(' ' if field=='tail' else ' CHALLENGE'))
  cases.append((name,edit))
 text('source-word','t:text/t:body//t:p')
 text('source-tail','t:text/t:body//t:p','tail')
 attr('heading-role','t:text//*[@rend="source-h2"]','rend','source-h3')
 attr('page-label','t:text//t:pb','n','9999')
 attr('source-linebreak','t:text//t:lb','type','source-other-break')
 attr('note-place','t:text//t:note','place','inline')
 attr('source-division-role','t:text/t:body/t:div','type','source-div2')
 attr('navigation-next','t:text//*[@next]','next','#blaikie-expositor8-xl')
 attr('missing-navigation','t:text//*[@ana]','ana','urn:ccel:source-navigation:prev:other-toc')
 attr('local-link-target','t:text//t:ref[starts-with(@target,"#")]','target','#blaikie-expositor8-i')
 attr('relative-uri-base','t:text//t:ref[@xml:base]',XML+'base','https://www.ccel.org/ccel/other/expositor8.html')
 attr('relative-uri-target','t:text//t:ref[@xml:base]','target','?scrBook=1Sam&scrCh=999#i')
 attr('scripture-marker-role','t:text//t:milestone[@unit="scripCom"]','unit','scripRef')
 attr('scripture-marker-reading','t:text//t:milestone[@unit="scripCom"]','corresp','1Sam.99')
 attr('scripture-ref-reading','t:text//t:ref[not(starts-with(@target,"#")) and not(@xml:base)]','target','1Sam.99')
 attr('span-class','t:text//t:seg[@type="thml-span"]','rend','source-class-other')
 attr('index-role','t:text//t:div[@type="source-index"]','type','source-other-index')
 text('primary-header-title','t:teiHeader/t:fileDesc/t:titleStmt/t:title')
 text('literal-document-prefix','t:teiHeader//t:note[@type="retained-source-document-prefix"]')
 text('visible-source-field','t:teiHeader//t:note[@type="retained-source-head-field"]')
 def move_note(t):
  n=select(t,'t:text//t:note');n.getparent().remove(n);select(t,'t:text/t:body//t:p').append(n)
 cases.append(('same-note-wrong-attachment',move_note))
 def swap_chapters(t):
  b=select(t,'t:text/t:body');a,c=list(b)[:2];b.remove(c);b.insert(0,c)
 cases.append(('same-chapters-wrong-order',swap_chapters))
 def payload(t):E.SubElement(E.SubElement(select(t,'t:text/t:body'),Q+'div',{'type':'invented-payload'}),Q+'p').text='Invented readable payload'
 cases.append(('outer-body-extra-payload',payload))
 def extra_header(t):E.SubElement(select(t,'t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl'),Q+'note').text='Invented metadata'
 cases.append(('outer-header-extra-payload',extra_header))
 results=[]
 with TemporaryDirectory(prefix='blaikie-first-samuel-semantic-') as scratch:
  scratch=Path(scratch)
  for name,edit in cases:
   tree=deepcopy(original);edit(tree);content=E.tostring(tree,encoding='UTF-8',xml_declaration=True)
   try:_p5_schema().assertValid(E.fromstring(content))
   except E.DocumentInvalid as error:raise ValueError('Semantic challenge must be P5-valid: '+name) from error
   out=scratch/name;out.mkdir()
   for p in package.iterdir():
    if p.is_file():(out/p.name).write_bytes(content if p.name=='content.tei.xml' else p.read_bytes())
   try:check(MEMBER,out)
   except ValueError as error:reason=str(error)
   else:raise ValueError('First Samuel semantic mutant admitted '+name)
   results.append(dict(name=name,schema_valid=True,rejected=True,reason=reason))
 # Source ledger and literal authority/accounting challenges keep TEI unchanged.
  for name,edit in [('administrative-comment',lambda a:a['features'][0].update(source_text=' changed administrative comment ')),('source-attribute-ledger',lambda a:a['features'][1]['source_attributes'].update(title='Changed source title')),('zero-correction-ledger',lambda a:a.update(historical_text_corrections=[{'sic':'invented'}])),('missing-navigation-ledger',lambda a:a.update(missing_source_navigation=[])),('source-head-xml',lambda a:a.update(source_head_xml='<invented/>'))]:
   out=scratch/name;out.mkdir()
   for p in package.iterdir():
    if p.is_file():(out/p.name).write_bytes(p.read_bytes())
   account=json.loads((out/'source-accountability.json').read_bytes());edit(account);(out/'source-accountability.json').write_bytes(canonical(account))
   try:check(MEMBER,out)
   except ValueError as error:reason=str(error)
   else:raise ValueError('First Samuel accounting mutant admitted '+name)
   results.append(dict(name=name,schema_valid=True,rejected=True,reason=reason))
 from ocd_kernel.reconstruction import CandidatePackage
 receipt=dict(status='pass',work_id='expositors-bible--william-g-blaikie',complete_work_count=1,source_member_count=1,expected_challenges=len(results),members=[dict(complete_work_id=MEMBER,package_sha256=CandidatePackage.load(package).sha256,expected_challenges=len(results),challenges=results)],implementation_sha256=sha(Path(__file__).read_bytes()))
 (ROOT/LOG/'complete-semantic-challenges-v3.json').write_bytes(canonical(receipt))
 print(json.dumps(dict(status='pass',schema_valid_rejected_challenges=len(results))))
 return receipt

if __name__=='__main__':challenge()
