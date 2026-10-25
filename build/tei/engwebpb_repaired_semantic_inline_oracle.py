"""Independent archive-led oracle for L225 eBible USFM TEI candidates."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from ocd_kernel.reconstruction.verifier import MechanicalFacts,verify_mechanical_facts

TEI="http://www.tei-c.org/ns/1.0"; XML="{http://www.w3.org/XML/1998/namespace}id"; XMLSPACE="{http://www.w3.org/XML/1998/namespace}space"
BOOK=re.compile(r"(?P<position>\d{2,3})-(?P<code>[A-Z0-9]{3})[A-Za-z0-9-]*\.usfm\Z"); LINE=re.compile(r"^\\(?P<marker>[A-Za-z0-9]+)(?: (?P<content>.*))?$",re.DOTALL)
HEADINGS={"h","toc1","toc2","toc3","mt1","mt2","mt3","s1","s2","s3","is1","is2","ms1","ms2"}
INLINE=re.compile(r"\\(?P<tag>\+?[A-Za-z][A-Za-z0-9]*)(?P<close>\*)?")
WORD=re.compile(r"\\(?P<tag>\+?w) (?P<body>.*?)\\(?P=tag)\*",re.DOTALL)
STRONG=re.compile(r'\|strong="([^"]+)"')
OPEN_TO_TEI={"w":("w",None),"+w":("w","usfm-plus-w"),"wj":("q","words-of-Jesus"),"+wh":("foreign",None),"qs":("seg","selah"),"bk":("title","biblical-book"),"k":("term",None),"f":("note","footnote"),"x":("note","cross-reference")}
FIELD_TO_TEI={"fr":("ref","source-label"),"xo":("ref","source-origin"),"ft":("seg","footnote-text"),"xt":("ref","source-target"),"fqa":("seg","alternate-reading"),"fq":("seg","quoted-reading")}

def _inline_check(node, source_text, pointer, counts):
    expected=STRONG.sub("",INLINE.sub("",source_text))
    actual="".join(node.itertext())
    if actual!=expected: raise ValueError(f"L225 readable inline text/order mismatch {pointer}: {actual!r} != {expected!r}")
    if any("\\" in (part or "") for descendant in node.iter() for part in (descendant.text,descendant.tail)):
        raise ValueError(f"L225 opaque inline USFM remains at {pointer}")
    words=[]
    for match in WORD.finditer(source_text):
        body=match.group("body"); strong=STRONG.search(body)
        words.append((STRONG.sub("",body).lstrip(),strong.group(1) if strong else None))
    actual_words=node.xpath(".//tei:w",namespaces={"tei":TEI})
    if len(actual_words)!=len(words): raise ValueError(f"L225 lexical word mapping count at {pointer}")
    for actual_word,(text,strong) in zip(actual_words,words,strict=True):
        if ("".join(actual_word.itertext()),actual_word.get("n"))!=(text,strong): raise ValueError(f"L225 lexical word/Strong's mapping at {pointer}")
    tokens=list(INLINE.finditer(source_text)); expected_counts={}
    for token in tokens:
        tag=token.group("tag")+("*" if token.group("close") else "")
        expected_counts[tag]=expected_counts.get(tag,0)+1
        counts[tag]=counts.get(tag,0)+1
    scope_stack=[]; expected_spans=[]
    for index,token in enumerate(tokens):
        tag=token.group("tag"); closing=bool(token.group("close"))
        if tag not in set(OPEN_TO_TEI)|set(FIELD_TO_TEI): raise ValueError(f"L225 unsupported source inline marker {tag}")
        if closing:
            if not scope_stack or scope_stack[-1][0]!=tag: raise ValueError(f"L225 source inline scope mismatch {tag}*")
            _,start=scope_stack.pop(); expected_spans.append(f"{pointer}&span={start}:{token.end()}")
            continue
        if tag in FIELD_TO_TEI:
            end=tokens[index+1].start() if index+1<len(tokens) else len(source_text)
            expected_spans.append(f"{pointer}&span={token.start()}:{end}")
        else:
            scope_stack.append((tag,token.start()))
    if scope_stack: raise ValueError(f"L225 unclosed source inline scopes: {[x[0] for x in scope_stack]}")
    for tag,count in expected_counts.items():
        if tag.endswith("*"):
            if expected_counts.get(tag[:-1],0)!=count: raise ValueError(f"L225 unpaired source inline close {tag}")
            continue
        if tag in OPEN_TO_TEI:
            name,typ=OPEN_TO_TEI[tag]; xpath=f".//tei:{name}"+(f"[@type='{typ}']" if typ else ("[not(@type='usfm-plus-w')]" if tag=="w" else ""))
            if len(node.xpath(xpath,namespaces={"tei":TEI})) != count: raise ValueError(f"L225 inline structure count drift {tag}")
        elif tag in FIELD_TO_TEI:
            name,typ=FIELD_TO_TEI[tag]
            if len(node.xpath(f".//tei:{name}[@type='{typ}']",namespaces={"tei":TEI})) != count: raise ValueError(f"L225 inline field count drift {tag}")
    actual_spans=[]
    for child in node.iterdescendants():
        span=child.get("corresp")
        if span is not None:
            if not re.fullmatch(re.escape(pointer)+r"&span=\d+:\d+",span): raise ValueError(f"L225 invalid inline source span {span}")
            actual_spans.append(span)
    if sorted(actual_spans)!=sorted(expected_spans): raise ValueError(f"L225 inline source-span coverage mismatch at {pointer}")

def _sha(b): return hashlib.sha256(b).hexdigest()
def _json(b):
 def pairs(items):
  d={}
  for k,v in items:
   if k in d: raise ValueError(f"duplicate JSON key {k}")
   d[k]=v
  return d
 return json.loads(b.decode("utf-8"),object_pairs_hook=pairs)
def _canon(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _import_closure_sha256(repository_root):
 return _closure()

def _closure():
 r=Path(__file__).resolve().parents[2]; names=("ocd_kernel/__init__.py","ocd_kernel/reconstruction/__init__.py","ocd_kernel/reconstruction/contract.py","ocd_kernel/reconstruction/verifier.py")
 return _sha(_canon({n:_sha((r/n).read_bytes()) for n in names}))
def _source_line(raw):
 if raw=="": return "",""
 m=LINE.fullmatch(raw)
 if not m: raise ValueError(f"unparsed source line {raw[:80]!r}")
 return m.group("marker"),m.group("content") or ""

def oracle(manifest,candidate):
 manifest.verify(); candidate.verify_integrity(); rec=manifest.record; work=str(rec["work_id"])
 profile=_json(manifest.authority_path("edition-profile").read_bytes()); policy=_json(manifest.authority_path("edition-policy").read_bytes()); receipt=_json(manifest.authority_path("acquisition-receipt").read_bytes()); archive=manifest.authority_path("source-archive"); tsv=manifest.authority_path("member-inventory").read_text(encoding="utf-8").splitlines()
 if receipt["source_id"]!=rec["source_id"] or _sha(archive.read_bytes())!=receipt["package"]["sha256"] or receipt["package"]["sha256"]!=profile["archive_sha256"]: raise ValueError("L225 archive identity/hash mismatch")
 inv=[]
 for line in tsv:
  name,size,crc,digest=line.split("\t"); inv.append({"name":name,"bytes":int(size),"crc32":crc,"sha256":digest})
 if _sha(_canon(inv))!=profile["member_inventory_json_sha256"]: raise ValueError("L225 inventory/profile mismatch")
 root=etree.fromstring(candidate.member_bytes("content.tei.xml"),etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False)); q=lambda n:f"{{{TEI}}}{n}"
 if root.tag!=q("TEI") or root.get(XML)!=work or len(root)!=2 or root[1].tag!=q("text") or len(root[1])!=1 or root[1][0].tag!=q("body"): raise ValueError("L225 direct-root TEI shape")
 title=root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title",namespaces={"tei":TEI})
 if len(title)!=1 or title[0].text!=profile["title"]: raise ValueError("L225 title drift")
 body=root[1][0]; source_lines=[]; expected_files=[]; archive_entries=[]; support=[]; marker_counts={}; inline_marker_counts={}; source_data={}; source_text_lines={}; counts={"books":0,"chapters":0,"verses":0,"source_lines":0}
 corresp_nodes={}
 for element in root.iter():
  pointer=element.get("corresp")
  if pointer:
   if pointer in corresp_nodes: raise ValueError(f"duplicate L225 source pointer {pointer}")
   corresp_nodes[pointer]=element
 with ZipFile(archive) as z:
  if z.testzip() is not None: raise ValueError("L225 archive CRC failure")
  files=[i for i in z.infolist() if not i.is_dir()]
  if len(files)!=receipt["verification"]["member_count"] or len(files)!=len(inv): raise ValueError("L225 archive member count")
  for i,(info,row) in enumerate(zip(files,inv,strict=True),1):
   data=z.read(info); digest=_sha(data)
   if (info.filename,len(data),f"{info.CRC:08x}",digest)!=(row["name"],row["bytes"],row["crc32"],row["sha256"]): raise ValueError("L225 archive member tuple mismatch")
   archive_entries.append({"position":i,"name":info.filename,"bytes":len(data),"crc32":f"{info.CRC:08x}","sha256":digest})
   m=BOOK.fullmatch(info.filename)
   if not m:
    support.append({"member":info.filename,"disposition":"retained-support-member","sha256":digest,"bytes":len(data)}); continue
   code=m.group("code"); pos=int(m.group("position")); special=code in {"FRT","GLO"}; expected_files.append((info.filename,code,pos,special)); source_data[info.filename]=data
   source_text_lines[info.filename]=data.decode("utf-8",errors="strict").splitlines()
   for ln,raw in enumerate(source_text_lines[info.filename],1):
    marker,payload=_source_line(raw); marker_counts[marker]=marker_counts.get(marker,0)+1; counts["source_lines"]+=1
    pointer=f"source-usfm:{work}/{info.filename}#line={ln}"; source_lines.append({"member":info.filename,"line":ln,"marker":marker,"raw_line_sha256":_sha(raw.encode("utf-8")),"content_sha256":_sha(payload.encode("utf-8")),"target":pointer})
 counts["books"]=sum(not special for _,_,_,special in expected_files)
 counts["chapters"]=sum(x["marker"]=="c" and not next(f[3] for f in expected_files if f[0]==x["member"]) for x in source_lines)
 counts["verses"]=sum(x["marker"]=="v" and not next(f[3] for f in expected_files if f[0]==x["member"]) for x in source_lines)
 if archive_entries!=profile["archive_entries"]: raise ValueError("L225 archive entry profile mismatch")
 if [f[0] for f in expected_files]!=profile["usfm_member_order"]: raise ValueError("L225 USFM member order profile mismatch")
 if counts!={k:profile["counts"][k] for k in counts}: raise ValueError(f"L225 count profile mismatch: {counts} != {profile['counts']}")
 if dict(sorted(marker_counts.items()))!=profile["marker_counts"]: raise ValueError("L225 marker profile mismatch")
 booknodes=list(body)
 if len(booknodes)!=len(expected_files): raise ValueError("L225 FRT/GLO/book member omission or invention")
 observed=[]
 for (fname,code,pos,special),book in zip(expected_files,booknodes,strict=True):
  typ="front" if code=="FRT" else "back" if code=="GLO" else "book"
  if book.tag!=q("div") or book.get("type")!=typ or book.get("n")!=code or book.get(XML)!=f"{work}-{code}": raise ValueError(f"L225 source member order/identity {fname}")
  # Every source line points to exactly one TEI carrier whose type and text encode that marker.
  lines=[x for x in source_lines if x["member"]==fname]
  for row in lines:
   marker=row["marker"]
   n=corresp_nodes.get(row["target"])
   if n is None: raise ValueError(f"L225 line carrier missing {fname}:{row['line']}")
   # Re-read the authoritative line; its marker and payload are checked against the mapped node.
   raw=source_text_lines[fname][row["line"]-1]
   mk,value=_source_line(raw)
   if not mk:
    if n.tag!=q("milestone") or n.get("unit")!="source-blank-line": raise ValueError("L225 blank line mapping")
   elif mk=="c" and not special:
    if n.tag!=q("div") or n.get("type")!="chapter" or n.get("n")!=value.split(" ",1)[0]: raise ValueError("L225 chapter marker mapping")
    extra=value.partition(" ")
    if extra[1]:
     suffix=n[1] if fname=="20-PSAengwebpb.usfm" and n.get("n") in {"1","42","73","90","107"} else n[0]
     if suffix.tag!=q("p") or len(suffix)!=1 or suffix[0].tag!=q("seg") or suffix[0].get("type")!="usfm-c-content" or suffix[0].text!=extra[2]: raise ValueError("L225 chapter marker suffix drift")
   elif mk=="v" and not special:
    number,sep,text=value.partition(" ")
    if n.tag!=q("ab") or n.get("type")!="verse" or n.get("n")!=number or n.get(XMLSPACE)!="preserve" or not sep: raise ValueError("L225 verse source number drift")
    _inline_check(n,text,row["target"],inline_marker_counts)
   elif mk=="p" and not value:
    if n.tag!=q("milestone") or n.get("unit")!="paragraph": raise ValueError("L225 paragraph marker mapping")
   elif mk in HEADINGS:
    repaired=fname=="20-PSAengwebpb.usfm" and mk=="ms1" and row["line"] in {10,2137,3775,4960,6025}
    if n.tag!=q("head") or n.get("type")!=f"usfm-{mk}" or n.getparent().tag!=q("div") or n.getparent().get("type")!=("chapter" if repaired else "usfm-heading"): raise ValueError("L225 heading marker mapping")
    if repaired and (n.getparent()[0] is not n or n.getparent().get("n")!={10:"1",2137:"42",3775:"73",4960:"90",6025:"107"}[row["line"]]):raise ValueError("L225 repaired heading source chapter/order")
    _inline_check(n,value,row["target"],inline_marker_counts)
   else:
    if n.tag!=q("seg") or n.get("type")!=f"usfm-{mk}" or n.getparent().tag!=q("p"): raise ValueError(f"L225 marker preservation drift {mk}")
    _inline_check(n,value,row["target"],inline_marker_counts)
   observed.append(row["target"])
 if len(observed)!=len(set(observed)) or len(observed)!=len(source_lines): raise ValueError("L225 source lines not mapped exactly once")
 marker_dict=dict(sorted(marker_counts.items()))
 if dict(sorted(inline_marker_counts.items()))!=profile.get("inline_marker_counts"): raise ValueError("L225 inline marker profile mismatch")
 expected_account={"contract":"ocd-l225-usfm-accountability-v1","work_id":work,"source_id":rec["source_id"],"archive_sha256":receipt["package"]["sha256"],"member_inventory_sha256":receipt["verification"]["member_inventory_sha256"],"archive_member_count":len(archive_entries),"archive_members":archive_entries,"member_dispositions":[{"member":f[0],"disposition":"mapped-to-tei-source-lines","sha256":next(x["sha256"] for x in archive_entries if x["name"]==f[0]),"bytes":next(x["bytes"] for x in archive_entries if x["name"]==f[0]),"line_count":sum(x["member"]==f[0] for x in source_lines)} for f in expected_files]+support,"counts":counts,"marker_counts":marker_dict,"source_lines":source_lines,"inline_marker_counts":dict(sorted(inline_marker_counts.items()))}
 account=_json(candidate.member_bytes("source-accountability.json"))
 # Producer archive dispositions follow archive order; canonical comparison preserves that order.
 expected_account["member_dispositions"]=[]
 for entry in archive_entries:
  f=next((x for x in expected_files if x[0]==entry["name"]),None)
  if f: expected_account["member_dispositions"].append({"member":entry["name"],"disposition":"mapped-to-tei-source-lines","sha256":entry["sha256"],"bytes":entry["bytes"],"line_count":sum(x["member"]==entry["name"] for x in source_lines)})
  else: expected_account["member_dispositions"].append({"member":entry["name"],"disposition":"retained-support-member","sha256":entry["sha256"],"bytes":entry["bytes"]})
 if account!=expected_account: raise ValueError("L225 complete source-accountability mismatch")
 schema=etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))); schema.assertValid(root)
 # Source support artifacts are human-visible and bound to the retained receipt.
 if receipt["rights"].encode() not in candidate.member_bytes("README.source.md"): raise ValueError("L225 README omitted retained rights/trademark receipt wording")
 authorities={x["name"]:x["sha256"] for x in rec["authorities"]}
 facts=MechanicalFacts(validator_implementation_sha256=_sha(Path(__file__).read_bytes()),validator_import_closure_sha256=_closure(),source_sha256=authorities["source-archive"],profile_sha256=authorities["edition-profile"],package_schema_sha256=authorities["candidate-package-schema"],xsd_sha256=authorities["tei-p5-xsd"],policy_sha256=authorities["edition-policy"],findings=())
 return verify_mechanical_facts(manifest,candidate,facts).as_record()
oracle.oracle_id="ocd-engwebpb-repaired-semantic-inline-oracle"; oracle.oracle_version="3"
