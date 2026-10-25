"""Manifest-bound TEI candidates for the three retained L225 eBible USFM editions."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile
from lxml import etree

TEI="http://www.tei-c.org/ns/1.0"; XML="{http://www.w3.org/XML/1998/namespace}id"
LINE=re.compile(r"^\\(?P<marker>[A-Za-z0-9]+)(?: (?P<content>.*))?$",re.DOTALL)
BOOK=re.compile(r"(?P<position>\d{2,3})-(?P<code>[A-Z0-9]{3})[A-Za-z0-9-]*\.usfm\Z")
HEADINGS={"h","toc1","toc2","toc3","mt1","mt2","mt3","s1","s2","s3","is1","is2","ms1","ms2"}
EDITION={
 "engwebpb":{"slug":"engwebpb","resource":"engwebpb","source_id":"engwebpb-usfm","title":"World English Bible British Edition","archive":"raw/ebible/engwebpb/usfm/engwebpb_usfm.zip","receipt":"raw/ebible/engwebpb/usfm/acquisition-receipt.json","inventory":"raw/ebible/engwebpb/usfm/member-inventory.tsv","folder":"raw/ebible/engwebpb/usfm/members/"},
 "eng-web-c":{"slug":"eng-web-c","resource":"eng-web-c","source_id":"eng-web-c-usfm","title":"World English Bible (Catholic)","archive":"raw/ebible/eng-web-c/usfm/eng-web-c_usfm.zip","receipt":"raw/ebible/eng-web-c/usfm/acquisition-receipt.json","inventory":"raw/ebible/eng-web-c/usfm/member-inventory.tsv","folder":"raw/ebible/eng-web-c/usfm/members/"},
 "engwmb":{"slug":"engwmb","resource":"engwmb","source_id":"engwmb-usfm","title":"World Messianic Bible","archive":"raw/ebible/engwmb/usfm/engwmb_usfm.zip","receipt":"raw/ebible/engwmb/usfm/acquisition-receipt.json","inventory":"raw/ebible/engwmb/usfm/member-inventory.tsv","folder":"raw/ebible/engwmb/usfm/members/"}}

def _sha(b): return hashlib.sha256(b).hexdigest()
def _json(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _source_line(raw:str):
 if raw=="": return "", ""
 m=LINE.fullmatch(raw)
 if not m: raise ValueError(f"unparsed USFM source line: {raw[:120]!r}")
 return m.group("marker"),m.group("content") or ""

def convert(manifest):
 manifest.verify(); work=str(manifest.record.get("work_id")); cfg=EDITION.get(work)
 if cfg is None or manifest.record.get("source_id")!=cfg["source_id"]: raise ValueError("L225 source manifest identity mismatch")
 profile=json.loads(manifest.authority_path("edition-profile").read_bytes()); policy=json.loads(manifest.authority_path("edition-policy").read_bytes())
 archive_path=manifest.authority_path("source-archive"); receipt=json.loads(manifest.authority_path("acquisition-receipt").read_bytes()); inventory=manifest.authority_path("member-inventory").read_text(encoding="utf-8").splitlines()
 if receipt.get("source_id")!=cfg["source_id"] or _sha(archive_path.read_bytes())!=receipt["package"]["sha256"] or profile["archive_sha256"]!=receipt["package"]["sha256"]: raise ValueError("retained L225 archive hash or identity mismatch")
 tsv=[]
 for line in inventory:
  name,size,crc,digest=line.split("\t"); tsv.append({"name":name,"bytes":int(size),"crc32":crc,"sha256":digest})
 if _sha(_json(tsv))!=profile["member_inventory_json_sha256"]: raise ValueError("L225 member inventory binding mismatch")
 ET=etree; root=ET.Element(f"{{{TEI}}}TEI",nsmap={None:TEI}); root.set(XML,cfg["slug"]); root.set("ana","#nonaccepted-candidate")
 header=ET.SubElement(root,f"{{{TEI}}}teiHeader"); fd=ET.SubElement(header,f"{{{TEI}}}fileDesc"); ts=ET.SubElement(fd,f"{{{TEI}}}titleStmt"); ET.SubElement(ts,f"{{{TEI}}}title").text=cfg["title"]
 pub=ET.SubElement(fd,f"{{{TEI}}}publicationStmt"); ET.SubElement(pub,f"{{{TEI}}}p").text="Nonaccepted source-to-TEI candidate; human acceptance, rights review, and publication remain open."
 sd=ET.SubElement(fd,f"{{{TEI}}}sourceDesc"); ET.SubElement(sd,f"{{{TEI}}}p").text=f"Exact retained eBible USFM package {cfg['archive']} (sha256:{receipt['package']['sha256']}); source edition label from acquisition receipt: {receipt['edition']}."
 body=ET.SubElement(ET.SubElement(root,f"{{{TEI}}}text"),f"{{{TEI}}}body")
 line_rows=[]; markers={}; counts={"books":0,"chapters":0,"verses":0,"source_lines":0}; mapped=[]; archive_entries=[]
 with ZipFile(archive_path) as z:
  if z.testzip() is not None: raise ValueError("L225 archive CRC failure")
  zfiles=[i for i in z.infolist() if not i.is_dir()]
  if len(zfiles)!=receipt["verification"]["member_count"]: raise ValueError("L225 archive member count mismatch")
  if len(zfiles)!=len(tsv): raise ValueError("L225 inventory row count mismatch")
  for i,(info,inv) in enumerate(zip(zfiles,tsv,strict=True),1):
   data=z.read(info); digest=_sha(data)
   if (info.filename,info.file_size,f"{info.CRC:08x}",digest)!=(inv["name"],inv["bytes"],inv["crc32"],inv["sha256"]): raise ValueError(f"L225 member inventory mismatch: {info.filename}")
   archive_entries.append({"position":i,"name":info.filename,"bytes":len(data),"crc32":f"{info.CRC:08x}","sha256":digest})
   match=BOOK.fullmatch(info.filename)
   if not match:
    mapped.append({"member":info.filename,"disposition":"retained-support-member","sha256":digest,"bytes":len(data)}); continue
   code=match.group("code"); pos=int(match.group("position")); special=code in {"FRT","GLO"}
   node=ET.SubElement(body,f"{{{TEI}}}div",type="front" if code=="FRT" else "back" if code=="GLO" else "book",n=code); node.set(XML,f"{work}-{code}"); counts["books"]+=0 if special else 1
   chapter=None
   for ln,raw in enumerate(data.decode("utf-8",errors="strict").splitlines(),1):
    marker,content=_source_line(raw); markers[marker]=markers.get(marker,0)+1; counts["source_lines"]+=1
    pointer=f"source-usfm:{work}/{quote(info.filename,safe='')}#line={ln}"
    kind="source-blank-line" if not marker else f"usfm-{marker}"
    target=None
    if not marker:
     holder=chapter if chapter is not None and not special else ET.SubElement(node,f"{{{TEI}}}div",type="usfm-line",n=str(ln))
     target=ET.SubElement(holder,f"{{{TEI}}}milestone",unit="source-blank-line",corresp=pointer)
    elif marker=="c" and not special:
     number,sep,chapter_extra=content.partition(" ");
     if not number.isdecimal(): raise ValueError(f"invalid chapter marker {info.filename}:{ln}")
     chapter=ET.SubElement(node,f"{{{TEI}}}div",type="chapter",n=number,corresp=pointer)
     if sep:
      para=ET.SubElement(chapter,f"{{{TEI}}}p"); ET.SubElement(para,f"{{{TEI}}}seg",type="usfm-c-content").text=chapter_extra
     counts["chapters"]+=1; target=f"{code}-{number}"
    elif marker=="v" and not special:
     if chapter is None: raise ValueError(f"verse before chapter {info.filename}:{ln}")
     number,sep,text=content.partition(" ")
     if not number or not sep: raise ValueError(f"invalid verse marker {info.filename}:{ln}")
     target=ET.SubElement(chapter,f"{{{TEI}}}ab",type="verse",n=number,corresp=pointer); target.set("{http://www.w3.org/XML/1998/namespace}space","preserve"); target.text=text; counts["verses"]+=1
    elif marker=="p" and not content:
     holder=chapter if chapter is not None and not special else ET.SubElement(node,f"{{{TEI}}}div",type="usfm-line",n=str(ln))
     target=ET.SubElement(holder,f"{{{TEI}}}milestone",unit="paragraph",corresp=pointer)
    elif marker in HEADINGS:
     section=ET.SubElement(node,f"{{{TEI}}}div",type="usfm-heading",n=f"{marker}-{ln}"); target=ET.SubElement(section,f"{{{TEI}}}head",type=f"usfm-{marker}",corresp=pointer); target.text=content
    else:
     holder=chapter if chapter is not None and not special else ET.SubElement(node,f"{{{TEI}}}div",type="usfm-line",n=str(ln))
     para=ET.SubElement(holder,f"{{{TEI}}}p"); target=ET.SubElement(para,f"{{{TEI}}}seg",type=kind,corresp=pointer); target.text=content
    line_rows.append({"member":info.filename,"line":ln,"marker":marker,"raw_line_sha256":_sha(raw.encode("utf-8")),"content_sha256":_sha(content.encode("utf-8")),"target":pointer})
   mapped.append({"member":info.filename,"disposition":"mapped-to-tei-source-lines","sha256":digest,"bytes":len(data),"line_count":sum(x["member"]==info.filename for x in line_rows)})
 if len(archive_entries)!=len(tsv) or archive_entries!=profile["archive_entries"]: raise ValueError("unaccounted or changed archive member")
 if [x["member"] for x in mapped if x["disposition"]=="mapped-to-tei-source-lines"]!=profile["usfm_member_order"]: raise ValueError("USFM archive member order differs from profile")
 expected={"books":profile["counts"]["books"],"chapters":profile["counts"]["chapters"],"verses":profile["counts"]["verses"],"source_lines":profile["counts"]["source_lines"]}
 if counts!=expected: raise ValueError(f"L225 source count mismatch: {counts} != {expected}")
 if dict(sorted(markers.items()))!=profile["marker_counts"]: raise ValueError("L225 marker inventory differs from profile")
 account={"contract":"ocd-l225-usfm-accountability-v1","work_id":work,"source_id":cfg["source_id"],"archive_sha256":receipt["package"]["sha256"],"member_inventory_sha256":receipt["verification"]["member_inventory_sha256"],"archive_member_count":len(archive_entries),"archive_members":archive_entries,"member_dispositions":mapped,"counts":counts,"marker_counts":dict(sorted(markers.items())),"source_lines":line_rows}
 xml=ET.tostring(root,encoding="UTF-8",xml_declaration=True,pretty_print=False)
 readme=(f"# {cfg['title']} retained source notes\n\nSource archive: `{cfg['archive']}`; SHA-256 `{receipt['package']['sha256']}`.\n\nThe candidate preserves the retained edition's ordered USFM source lines. Explicit `\\id`, `\\c`, and `\\v` markers provide book, chapter, and verse boundaries; heading markers map to source-labeled TEI blocks with their exact USFM marker, paragraph markers to milestones, and remaining markers to source-labeled blocks. FRT and GLO are included as front/back matter divisions when present. The non-USFM archive members are accounted as retained support members. Rights, trademark, human acceptance, and publication decisions remain separate.\n\nRetained acquisition receipt wording: {receipt['rights']}\n").encode()
 prov={"source_id":cfg["source_id"],"source_sha256":receipt["package"]["sha256"],"manifest_sha256":manifest.sha256,"scope":"complete retained ZIP member inventory; every USFM source line mapped once; support members accounted separately"}
 unresolved=[{"question_id":"edition-and-rights-review","status":"unresolved","observation":receipt["rights"],"question":"This technical reconstruction does not decide rights applicability, trademark use, human acceptance, or publication authorization."}]
 return {"README.source.md":readme,"content.tei.xml":xml,"source-accountability.json":_json(account),"provenance.json":_json(prov),"unresolved.jsonl":b"".join(_json(x) for x in unresolved)}
convert.converter_id="ocd-l225-ebible-usfm-to-tei"; convert.converter_version="1"
