"""Create Farrar-only implementation copies; leave frozen shared code untouched."""
from pathlib import Path
from hashlib import sha256
import re
ROOT=Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    EMITTER=ROOT/'build/tei/ccel_retained_native_emitter.py'
    assert sha256(EMITTER.read_bytes()).hexdigest()=='a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f'
    target=ROOT/'build/tei/farrar_retained_native_emitter.py'
    assert not target.exists()
    text=EMITTER.read_text()
    start=text.index('KNOWN_SOURCES = {');end=text.index('\n}\n',start)+2
    text=text[:start]+'''KNOWN_SOURCES = {
    'farrar-expositor1kings':'b5bb6a2200528b3d3573aa373eaec2f7a827c1057b462c5d473eb231e812ca8d',
    'farrar-expositor2kings':'1827452772153d95bb8f5c8c56782b4b038b51f335e6339b2ac8e241dc7267fa',
    'farrar-expositordan':'6a851a9f4c0bf941745ce28b8a0c0da9b15f3a6568c089511b66d8bc10d1a67b',
}'''+text[end:]
    text=text.replace('five existing retained witnesses','three existing Farrar witnesses')
    text=text.replace('("scripCom", "pb") if member_id.startswith("smith-") else ("scripCom", "cite", "foreign", "pb")','("scripCom", "scripRef", "pb") if member_id == "farrar-expositordan" else ("scripCom", "pb")')
    text=text.replace('"table": "table", "tr": "row", "td": "cell", "img": "figure",','"table": "table", "tr": "row", "td": "cell", "img": "figure", "pre": "ab",')
    text=text.replace('text = tei_el("text", {"xml:lang": "en"})','text = tei_el("text", {"xml:lang": "en", "xml:space": body.get("{http://www.w3.org/XML/1998/namespace}space")})')
    text=text.replace('"table", "cell", "ref", "note", "lb", "milestone", "anchor"}','"table", "cell", "ref", "note", "lb", "milestone", "anchor", "ab"}')
    text=text.replace('STYLE_TAGS = {"div", "p", "hi", "seg", "table", "cell", "milestone"}','STYLE_TAGS = {"div", "p", "hi", "seg", "table", "cell", "milestone", "ab"}')
    anchor='        if node.tag in RENDS:\n'
    text=text.replace(anchor,'''        if node.tag == "pre":
            attrs["rend"] = "source-preformatted"
            attrs["xml:space"] = node.get("{http://www.w3.org/XML/1998/namespace}space")
'''+anchor,1)
    target.write_text(text,encoding='utf-8',newline='\n')
    producer=ROOT/'build/tei/farrar_retained_native_prepare.py';assert not producer.exists()
    text=(ROOT/'build/tei/smith_retained_native_prepare.py').read_text().replace('Smith','Farrar').replace('smith','farrar').replace('george-adam-farrar','frederic-w-farrar').replace('ccel_retained_native_emitter','farrar_retained_native_emitter')
    start=text.index('OLD_PACKAGE =');end=text.index('\ndef sha(raw):',start)
    text=text[:start]+'''OLD_PACKAGE = LOG/'retained-final-package'
EMITTER_SHA = 'UNFROZEN'
MEMBERS = {
    'farrar-expositor1kings': ('farrar_expositor1kings.xml', ('i','ii'), ('vii','viii')),
    'farrar-expositor2kings': ('farrar_expositor2kings.xml', ('i','ii'), ('xliii','xliv','xlv','xlvi','xlvii')),
    'farrar-expositordan': ('farrar_expositordan.xml', ('i','ii'), ('vi','vii')),
}
SPECS = {}
for _member, _filename, _pin, _size, _elements, _body in [
 ('farrar-expositor1kings','farrar_expositor1kings.xml','b5bb6a2200528b3d3573aa373eaec2f7a827c1057b462c5d473eb231e812ca8d',1187151,7024,6940),
 ('farrar-expositor2kings','farrar_expositor2kings.xml','1827452772153d95bb8f5c8c56782b4b038b51f335e6339b2ac8e241dc7267fa',1295251,9002,8915),
 ('farrar-expositordan','farrar_expositordan.xml','6a851a9f4c0bf941745ce28b8a0c0da9b15f3a6568c089511b66d8bc10d1a67b',945183,7579,7481)]:
 SPECS[_member]=dict(path='raw/ccel/expositors-bible/'+_filename,sha256=_pin,bytes=_size,elements=_elements,body_elements=_body,
  form=WORK+'--'+_member+'--retained-en',edition=WORK+'--'+_member+'--ccel-electronic',acquisition=WORK+'--'+_member+'--acquired')
'''+text[end:]
    text=re.sub(r"    legacy=.*\n", "    legacy='All three existing Farrar members are recovered from the exact historical LIB-033 package. Their flat feature representation requires the present source-backed readable hierarchy repair; original package and raw witness bytes remain exact.'\n",text)
    producer.write_text(text,encoding='utf-8',newline='\n')
    oracle=ROOT/'build/tei/farrar_retained_native_oracle.py';assert not oracle.exists()
    text=(ROOT/'build/tei/smith_retained_native_oracle.py').read_text().replace('Smith','Farrar').replace('smith','farrar').replace('george-adam-farrar','frederic-w-farrar').replace('ccel_retained_native_emitter','farrar_retained_native_emitter')
    start=text.index('SOURCES={');end=text.index('\n}\n',start)+2
    text=text[:start]+'''SOURCES={
 'farrar-expositor1kings':('farrar_expositor1kings.xml','b5bb6a2200528b3d3573aa373eaec2f7a827c1057b462c5d473eb231e812ca8d',('i','ii'),('vii','viii'),7024),
 'farrar-expositor2kings':('farrar_expositor2kings.xml','1827452772153d95bb8f5c8c56782b4b038b51f335e6339b2ac8e241dc7267fa',('i','ii'),('xliii','xliv','xlv','xlvi','xlvii'),9002),
 'farrar-expositordan':('farrar_expositordan.xml','6a851a9f4c0bf941745ce28b8a0c0da9b15f3a6568c089511b66d8bc10d1a67b',('i','ii'),('vi','vii'),7579),
}'''+text[end:]
    text=text.replace('*,native=True','*,native=False')
    text=text.replace("regions={p:ET.SubElement(expected", "expected.set(XML+'space',body.get(XML+'space'))\n regions={p:ET.SubElement(expected",1)
    text=text.replace("'img':'figure','a':'ref'}", "'img':'figure','a':'ref','pre':'ab'}")
    text=text.replace("'milestone','anchor'}", "'milestone','anchor','ab'}")
    text=text.replace("'cell','milestone'}", "'cell','milestone','ab'}")
    anchor="  if node.tag in renders:attrs['rend']=renders[node.tag]\n"
    assert anchor in text
    text=text.replace(anchor,"  if node.tag=='pre':attrs['rend']='source-preformatted';attrs[XML+'space']=node.get(XML+'space')\n"+anchor,1)
    oracle.write_text(text,encoding='utf-8',newline='\n')
    print('Farrar-only emitter, producer and independent checker initialized; all templates unchanged')
