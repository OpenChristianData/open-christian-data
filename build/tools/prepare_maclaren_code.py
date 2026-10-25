"""Create work-local Maclaren derivatives; never edits installed shared code."""
from pathlib import Path
from hashlib import sha256
import json
ROOT=Path.cwd();LOG=Path('reports/_logs/maclaren-existing-install-20261003-v1');inventory=json.loads((ROOT/LOG/'source-inventory.json').read_bytes());rows=inventory['included_members']
def replace(text,old,new):
 if old not in text:raise ValueError('Maclaren derivative basis differs '+old[:90])
 return text.replace(old,new)
regions={'maclaren-expositorpsalms1':(('i','ii'),('xli',)),'maclaren-expositorpsalms2':(('i',),('lii',)),'maclaren-expositorpsalms3':(('i',),('lxiii',)),'maclaren-expositorcolphm':(('i','ii'),('v',))}
emitter=(ROOT/'build/tei/ccel_retained_native_emitter.py').read_text(encoding='utf-8')
if sha256((ROOT/'build/tei/ccel_retained_native_emitter.py').read_bytes()).hexdigest()!='a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f':raise ValueError('Frozen shared emitter changed')
emitter=replace(emitter,'from urllib.parse import quote','from urllib.parse import quote, urlsplit')
start=emitter.index('KNOWN_SOURCES = {');end=emitter.index('\n\n\ndef emit_text',start)
emitter=emitter[:start]+'KNOWN_SOURCES = '+repr({r['member_id']:r['sha256'] for r in rows})+emitter[end:]
emitter=replace(emitter,'back_ids: tuple[str, ...])','back_ids: tuple[str, ...], source_url: str)')
emitter=replace(emitter,'the five existing retained witnesses','the four existing acquired Maclaren witnesses')
emitter=replace(emitter,'labels = ("scripCom", "pb") if member_id.startswith("smith-") else ("scripCom", "cite", "foreign", "pb")','labels = ("scripCom", "pb")')
emitter=replace(emitter,'"td": "cell", "img": "figure",','"td": "cell", "th": "cell", "img": "figure",')
emitter=replace(emitter,'if node.tag == "td":','if node.tag in {"td", "th"}:')
emitter=replace(emitter,'        if node.tag == "table":','        if node.tag == "th":\n            attrs["role"] = "label"\n        if node.tag == "table":')
emitter=replace(emitter,'                attrs["target"] = href','                attrs["target"] = href\n                if not urlsplit(href).scheme:\n                    attrs["{http://www.w3.org/XML/1998/namespace}base"] = source_url')
emitter=replace(emitter,'        out = tei_el(tag, attrs)', '''        if node.get('valign') and tag == 'cell':
            attrs['rend'] = (attrs.get('rend','')+' source-valign-'+node.get('valign')).strip()
        for key in ('next','prev'):
            if node.get(key) is not None:
                target=node.get(key)
                if target in id_set:attrs[key]='#'+member_id+'-'+target
                else:
                    attrs['ana']=(attrs.get('ana','')+' urn:ccel:source-navigation:'+key+':'+quote(target,safe='-_.')).strip()
        out = tei_el(tag, attrs)''')
target=ROOT/'build/tei/maclaren_retained_native_emitter.py'
if target.exists():raise FileExistsError('Preserve Maclaren derivative')
target.write_text(emitter,encoding='utf-8');emitter_sha=sha256(target.read_bytes()).hexdigest()
prepare=(ROOT/'build/tei/smith_retained_native_prepare.py').read_text(encoding='utf-8').replace('Smith','Maclaren').replace('smith','maclaren').replace('george-adam-maclaren','alexander-maclaren')
prepare=replace(prepare,'from build.tei.ccel_retained_native_emitter import emit_text','from build.tei.maclaren_retained_native_emitter import emit_text')
prepare=replace(prepare,"OLD_PACKAGE = Path('reports/_logs/stokes-existing-install-20261003-v1/immutable-lib034-package')","OLD_PACKAGE = LOG / 'retained-lib033-package'")
prepare=replace(prepare,"SOURCE_DIR = Path('sources/commentaries/expositors-bible/maclaren-existing-retained-20261003-v2')","SOURCE_DIR = Path('sources/commentaries/expositors-bible/maclaren-retained-install-20261003-v1')")
prepare=replace(prepare,"EMITTER_SHA = 'a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f'","EMITTER_SHA = "+repr(emitter_sha))
start=prepare.index('MEMBERS = {');end=prepare.index('\ndef sha(raw):',start)
specs={r['member_id']:dict(path=r['path'],sha256=r['sha256'],bytes=r['bytes'],elements=r['elements'],body_elements=r['body_elements'],comments=10,form=inventory['work_id']+'--'+r['member_id']+'--retained-en',edition=inventory['work_id']+'--'+r['member_id']+'--ccel-electronic',acquisition=inventory['work_id']+'--'+r['member_id']+'--acquired') for r in rows}
prepare=prepare[:start]+'MEMBERS = '+repr({r['member_id']:(r['file'],*regions[r['member_id']]) for r in rows})+'\nSPECS = '+repr(specs)+'\n'+prepare[end:]
prepare=prepare.replace("'build/tei/ccel_retained_native_emitter.py'","'build/tei/maclaren_retained_native_emitter.py'")
prepare=replace(prepare,'    text,account=emit_text(raw,member_id=member_id,front_ids=front,back_ids=back)', '''    spec=SPECS[member_id]
    acquisition_path=Path('library/works')/WORK/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
    acquisition=json.loads((ROOT/acquisition_path).read_bytes())
    if acquisition['source_path']!=source_path or acquisition['source_sha256']!=spec['sha256'] or acquisition['source_bytes']!=len(raw):raise ValueError('Exact Maclaren acquired source URI authority differs')
    text,account=emit_text(raw,member_id=member_id,front_ids=front,back_ids=back,source_url=acquisition['url'])
    account['source_uri_acquisition_path']=acquisition_path.as_posix();account['source_uri_acquisition_sha256']=sha((ROOT/acquisition_path).read_bytes())''')
start=prepare.index('    legacy=');end=prepare.index('    readme=',start)
prepare=prepare[:start]+"    legacy='All four original LIB033 flat feature-ledger members and exact encoded witnesses independently reconciled against current raw sources before readable hierarchy repair.'\n"+prepare[end:]
prepare=prepare.replace('LIB-034','LIB-033').replace('Map and Arabic-word image references, when present, preserve literal URLs, alt/title, source dimensions and inline context. Their unretained pixels and Arabic glyph content have not been reconstructed or visually reviewed.','These four XML sources contain no images. Table summaries/spans and th header roles retained; relative hrefs carry exact acquired-source per-ref xml:base, without changing literal targets; navigation next/prev resolves only known source IDs, missing source targets remain explicit annotations. Psalms I/II/III cover1–38/39–89/90–150, source PsalmsI–II often represent verse lines with spans/br and these literal source carriers remain unchanged. No invented stanza grouping or typographic equivalence is claimed.')
target=ROOT/'build/tei/maclaren_retained_native_prepare.py';target.write_text(prepare,encoding='utf-8')
oracle=(ROOT/'build/tei/smith_retained_native_oracle.py').read_text(encoding='utf-8').replace('Smith','Maclaren').replace('smith','maclaren').replace('george-adam-maclaren','alexander-maclaren')
oracle=replace(oracle,'from urllib.parse import quote','from urllib.parse import quote, urlsplit, urljoin')
start=oracle.index('SOURCES={');end=oracle.index('\n\n# Exact observed',start)
oracle=oracle[:start]+'SOURCES='+repr({r['member_id']:(r['file'],r['sha256'],*regions[r['member_id']],r['elements']) for r in rows})+oracle[end:]
oracle=oracle.replace('build/tei/ccel_retained_native_emitter.py','build/tei/maclaren_retained_native_emitter.py')
oracle=replace(oracle,"if actual is None or candidate.get(XML+'id')!=member_id:raise ValueError('Actual candidate identity/envelope differs')", "if actual is None or candidate.get(XML+'id')!=member_id or candidate.attrib!={XML+'id':member_id} or [n.tag for n in candidate]!=[NS+'teiHeader',NS+'text'] or (candidate.text or '') or (candidate.tail or ''):raise ValueError('Actual candidate identity/envelope differs')")
oracle=replace(oracle,"'tr':'row','td':'cell','img':'figure'","'tr':'row','td':'cell','th':'cell','img':'figure'")
oracle=replace(oracle,"  if node.tag=='td':","  if node.tag in {'td','th'}:")
oracle=replace(oracle,"  if node.tag=='table':","  if node.tag=='th':attrs['role']='label'\n  if node.tag=='table':")
oracle=replace(oracle," expected=ET.Element(NS+'text',{XML+'lang':'en'})",''' acquisition_path=Path('library/works')/WORK/'forms'/(WORK+'--'+member_id+'--retained-en')/'editions'/(WORK+'--'+member_id+'--ccel-electronic')/'acquisitions'/(WORK+'--'+member_id+'--acquired.json')
 acquisition=json.loads((ROOT/acquisition_path).read_bytes())
 if acquisition['source_path']!='raw/ccel/expositors-bible/'+filename or acquisition['source_sha256']!=pin or acquisition['source_bytes']!=len(raw):raise ValueError('Independent acquired URI authority differs')
 expected=ET.Element(NS+'text',{XML+'lang':'en'})''')
oracle=replace(oracle,"   else:attrs['target']=href","   else:\n    attrs['target']=href\n    if not urlsplit(href).scheme:attrs[XML+'base']=acquisition['url']")
oracle=replace(oracle,"  out=ET.SubElement(parent,NS+tag,attrs)",'''  if node.get('valign') and tag=='cell':attrs['rend']=(attrs.get('rend','')+' source-valign-'+node.get('valign')).strip()
  for key in ('next','prev'):
   if node.get(key) is not None:
    target=node.get(key)
    if target in source_ids:attrs[key]='#'+member_id+'-'+target
    else:attrs['ana']=(attrs.get('ana','')+' urn:ccel:source-navigation:'+key+':'+quote(target,safe='-_.')).strip()
  out=ET.SubElement(parent,NS+tag,attrs)''')
oracle=replace(oracle," root_ids=[n.get('id')", " if account['source_uri_acquisition_path']!=acquisition_path.as_posix() or account['source_uri_acquisition_sha256']!=sha256((ROOT/acquisition_path).read_bytes()).hexdigest():raise ValueError('Acquired URI accounting differs')\n root_ids=[n.get('id')")
target=ROOT/'build/tei/maclaren_retained_native_oracle.py';target.write_text(oracle,encoding='utf-8')
print(json.dumps(dict(status='created',work_id=inventory['work_id'],members=4,emitter_sha256=emitter_sha),sort_keys=True))
