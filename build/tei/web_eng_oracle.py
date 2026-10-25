"""Independent source-envelope and TEI oracle for eBible eng-web."""
from __future__ import annotations
import hashlib, json, platform, re, sys
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.lib.storage_topology import resolve_repo_path

TEI="http://www.tei-c.org/ns/1.0"; XML="http://www.w3.org/XML/1998/namespace"
ORACLE_ID="ocd-ebible-eng-web-independent-oracle"; VERSION="1"
TOKEN=re.compile(r"\\([+A-Za-z0-9]+)(\*)?")
BOOK=re.compile(r"^[0-9]{2,3}-(?P<id>[A-Z0-9]{3})eng-web\.usfm$")
CONT={"q1","q2","q3","q4","q5","q6","pi1","pi2","pi3","pi4","li1","li2","li3","li4","m","mi","nb","p","pc","pr","cls"}

def sha(b): return hashlib.sha256(b).hexdigest()
def canon(x): return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _source_members(manifest):
    rows=manifest.record["authorities"]
    return {str(x["name"]):x for x in rows}
def _load(manifest):
    profile=json.loads(manifest.authority_path("profile").read_bytes()); policy=json.loads(manifest.authority_path("policy").read_bytes())
    if manifest.record.get("work_id")!="world-english-bible-classic" or manifest.record.get("source_id")!="ebible-eng-web-2020-stable": raise ValueError("L596 work/source identity mismatch")
    if profile.get("contract")!="ocd-ebible-eng-web-source-profile-v1" or profile.get("usfm",{}).get("archive_sha256")!="cc5d6cc5c4cef69efa1bd52aee1459211104c945bd685a5bcb247209fc30c792" or profile.get("usfx",{}).get("archive_sha256")!="4a06b3f09e2770a3b6f946151ed061840106eb1e866f9b3c579b01405d472d22": raise ValueError("L596 source profile binding mismatch")
    return profile,policy

def _archive(manifest,profile,which):
    cfg=profile[which]; root=manifest.repository_root
    archive=manifest.authority_path(which+"-archive"); extracted=manifest.repository_root
    # Extracted roots are fixed, logical raw routes. Use the source-profile's path fields.
    import ocd_kernel.lib.storage_topology as st
    root=st.resolve_repo_path(manifest.repository_root,cfg["extracted_root"])
    records=[]; selected=[]
    with ZipFile(archive) as z:
        if z.testzip() is not None: raise ValueError(which+" CRC failure")
        for i,info in enumerate(z.infolist(),1):
            data=z.read(info); row={"index":i,"name":info.filename,"is_directory":info.is_dir(),"bytes":len(data),"compressed_bytes":info.compress_size,"crc32":f"{info.CRC:08x}","sha256":sha(data)}; records.append(row)
            if not info.is_dir():
                path=root/Path(*info.filename.replace("\\","/").split("/"))
                if not path.is_file() or path.read_bytes()!=data: raise ValueError(f"{which} extracted member mismatch: {info.filename}")
            if which=="usfm" and BOOK.fullmatch(info.filename): selected.append((info.filename,data))
    if len(records)!=cfg["member_count"] or records!=cfg["entries"]: raise ValueError(which+" full archive envelope differs")
    inventory=manifest.authority_path(which+"-inventory")
    if sha(inventory.read_bytes())!=cfg["inventory_file_sha256"]: raise ValueError(which+" inventory file hash mismatch")
    if sha(archive.read_bytes())!=cfg["archive_sha256"]: raise ValueError(which+" archive hash mismatch")
    return selected,records

def _line_rows(usfm_members):
    result=[]; counts={}; book_order=[]; current_book=""; chapter=""; verses=chapters=0; d=sp=0
    for name,data in usfm_members:
        book=BOOK.fullmatch(name).group("id"); book_order.append(book); chapter=""
        for no,line in enumerate(data.decode("utf-8").split("\n"),1):
            m=re.fullmatch(r"\\(?P<marker>[A-Za-z0-9]+)(?: (?P<content>.*))?",line,re.DOTALL)
            if not m: raise ValueError(f"invalid USFM physical line {name}:{no}")
            marker=m.group("marker"); value=m.group("content") or ""; counts[marker]=counts.get(marker,0)+1
            if marker=="c": chapter=value.split()[0]; chapters+=1
            elif marker=="v": verses+=1
            elif marker=="d": d+=1
            elif marker=="sp": sp+=1
            result.append((name,no,line,book,chapter,marker,value))
    return result,counts,book_order,chapters,verses,d,sp

def _inline_text(value,exclude_notes=False):
    out=[]; pos=0; stack=[]
    for match in TOKEN.finditer(value):
        if not (exclude_notes and any(m in {"f","x"} for m in stack)): out.append(value[pos:match.start()])
        marker=match.group(1); closing=bool(match.group(2))
        if closing:
            index=next((i for i in range(len(stack)-1,-1,-1) if stack[i]==marker),None)
            if index is not None: stack=stack[:index]
        else: stack.append(marker)
        pos=match.end()
    if not (exclude_notes and any(m in {"f","x"} for m in stack)): out.append(value[pos:])
    return re.sub(r'\|strong="[^"]*"','',"".join(out))

def _usfm_verse_text(rows):
    out={}; key=None; occurrences=[]
    for _,_,_,book,ch,marker,value in rows:
        if marker=="c": key=None
        elif marker=="v":
            bits=value.split(maxsplit=1); key=(book,ch,bits[0]); occurrences.append(key); out[key]=_inline_text(bits[1] if len(bits)>1 else "",True)
        elif key and marker in CONT: out[key]+=" "+_inline_text(value,True)
    return {k:re.sub(r"\s+"," ",v).strip() for k,v in out.items()},occurrences

def _usfx_verse_text(path):
    root=ET.parse(path).getroot(); out={}; occurrences=[]
    for book_node in root.findall("book"):
        state={"chapter":"","key":None}
        def walk(node,excluded=False):
            if node.tag=="c": state["chapter"]=node.get("id","")
            if node.tag=="v": state["key"]=(book_node.get("id"),state["chapter"],node.get("id","")); occurrences.append(state["key"]); out[state["key"]]=""
            if node.tag=="ve": state["key"]=None; return
            excluded=excluded or node.tag in {"f","x","d"} or (node.tag=="p" and node.get("sfm") in {"sp","d"})
            if state["key"] and not excluded and node.text: out[state["key"]]+=node.text
            for child in node:
                walk(child,excluded)
                if state["key"] and not excluded and child.tail: out[state["key"]]+=child.tail
        for child in book_node: walk(child)
    return {k:re.sub(r"\s+"," ",v).strip() for k,v in out.items()},root,occurrences

def _node_text(node):
    vals=[node.text or ""]
    for child in node:
        if child.tag==f"{{{TEI}}}note" and child.get("type")=="source-usfm-raw":
            vals.append(child.tail or ""); continue
        vals.append(_node_text(child)); vals.append(child.tail or "")
    return "".join(vals)

def _check(manifest,candidate,profile,policy,usfm_members,usfx_archive):
    problems=[]; xml=candidate.member_bytes("content.tei.xml")
    parser=etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,huge_tree=True)
    try: tree=etree.fromstring(xml,parser)
    except etree.XMLSyntaxError as exc: raise ValueError("candidate malformed XML") from exc
    xsd=manifest.authority_path("tei-p5-xsd")
    schema=etree.XMLSchema(etree.parse(str(xsd)))
    if not schema.validate(etree.ElementTree(tree)): problems.append("P5:"+str(schema.error_log.last_error))
    rows,markers,book_order,chapters,verses,d_count,sp_count=_line_rows(usfm_members)
    nodes={}
    for node in tree.iter():
        pointer=node.get("corresp")
        if pointer and "#line=" in pointer:
            if pointer in nodes: problems.append("duplicate line pointer:"+pointer)
            nodes[pointer]=node
    if len(nodes)!=len(rows): problems.append(f"TEI line-pointer count {len(nodes)} != source line count {len(rows)}")
    actual_d=actual_sp=0; expected_pointer_order=[]; actual_pointer_order=[n.get("corresp") for n in tree.iter() if n.get("corresp") and "#line=" in n.get("corresp")]
    psalm119_d=0; song_sp=0
    for name,no,line,book,ch,marker,value in rows:
        pointer=f"source-usfm:eng-web/{name}#line={no}"; expected_pointer_order.append(pointer); node=nodes.get(pointer)
        if node is None: problems.append("missing line:"+pointer); continue
        raw=[c for c in node if c.tag==f"{{{TEI}}}note" and c.get("type")=="source-usfm-raw"]
        if len(raw)!=1 or raw[0].text!=line: problems.append("raw-line mismatch:"+pointer)
        if marker=="d":
            actual_d+=1
            if book=="PSA" and ch=="119": psalm119_d+=1
            valid=node.tag==f"{{{TEI}}}ab" and node.get("type")=="usfm-d"
        elif marker=="sp":
            actual_sp+=1
            if book=="SNG": song_sp+=1
            valid=node.tag==f"{{{TEI}}}ab" and node.get("type")=="usfm-sp"
        elif marker=="v": valid=node.tag==f"{{{TEI}}}ab" and node.get("type")=="verse" and node.get("n")==value.split()[0]
        elif marker=="c": valid=node.tag==f"{{{TEI}}}ab" and node.get("type")=="source-chapter-label"
        else: valid=True
        if not valid: problems.append("marker role mismatch:"+pointer)
        source_value=value
        if marker=="b": source_value=""
        if marker=="v":
            bits=value.split(maxsplit=1); source_value=bits[1] if len(bits)>1 else ""
        expected=_inline_text(source_value,False)
        actual=_node_text(node)
        if expected!=actual: problems.append(f"readable carrier text mismatch:{pointer}")
    if actual_d!=d_count or actual_sp!=sp_count: problems.append(f"heading/speaker preservation mismatch d={actual_d}/{d_count} sp={actual_sp}/{sp_count}")
    if psalm119_d!=22 or song_sp!=33: problems.append(f"source-bound structure census mismatch PSA119-d={psalm119_d}/22 SNG-sp={song_sp}/33")
    if actual_pointer_order!=expected_pointer_order: problems.append("source line carrier order differs from USFM source order")
    if chapters!=profile["usfm"]["chapter_count"] or verses!=profile["usfm"]["verse_count"] or book_order!=profile["usfm"]["book_ids"]: problems.append("USFM source scope census mismatch")
    # Independent cross-encoding text and address comparison.
    u1,usfm_occurrences=_usfm_verse_text(rows)
    usfx_path=resolve_repo_path(manifest.repository_root,profile["usfx"]["xml_member_path"])
    u2,usfx_root,usfx_occurrences=_usfx_verse_text(usfx_path)
    usfm_counts=Counter(usfm_occurrences); usfx_counts=Counter(usfx_occurrences)
    usfm_duplicates=sorted((key,count) for key,count in usfm_counts.items() if count>1)
    usfx_duplicates=sorted((key,count) for key,count in usfx_counts.items() if count>1)
    if len(usfm_occurrences)!=profile["cross_encoding_alignment"].get("usfm_verse_occurrence_count") or usfm_duplicates!=[] or len(usfm_duplicates)!=profile["cross_encoding_alignment"].get("usfm_duplicate_key_count"):
        problems.append(f"USFM occurrence/duplicate census mismatch occurrences={len(usfm_occurrences)} duplicate_keys={len(usfm_duplicates)}")
    if len(usfx_occurrences)!=profile["cross_encoding_alignment"].get("usfx_verse_occurrence_count") or usfx_duplicates!=[] or len(usfx_duplicates)!=profile["cross_encoding_alignment"].get("usfx_duplicate_key_count"):
        problems.append(f"USFX occurrence/duplicate census mismatch occurrences={len(usfx_occurrences)} duplicate_keys={len(usfx_duplicates)}")
    if usfm_counts!=usfx_counts: problems.append("USFM/USFX verse-key multiplicity differs")
    if set(u1)!=set(u2): problems.append(f"USFM/USFX address mismatch missing={len(set(u1)-set(u2))} extra={len(set(u2)-set(u1))}")
    else:
        substantive=[]; collapsed=spaces_only=0
        for key,left in u1.items():
            right=u2[key]
            if re.sub(r"\s+"," ",left).strip()==re.sub(r"\s+"," ",right).strip():
                collapsed+=1
            elif re.sub(r"\s+","",left)==re.sub(r"\s+","",right):
                spaces_only+=1
            else:
                substantive.append(key)
        if substantive: problems.append(f"substantive USFM/USFX verse differences:{len(substantive)} {substantive[:6]}")
        if len(u1)!=profile["cross_encoding_alignment"]["verse_key_count"] or collapsed!=profile["cross_encoding_alignment"]["text_equal_after_whitespace_collapse"] or spaces_only!=profile["cross_encoding_alignment"]["additional_equal_after_removing_whitespace"]: problems.append("USFM/USFX alignment census differs from profile")
    usfx_ids=[x.get("id") for x in usfx_root.findall("book")]
    if len(usfx_ids)!=profile["usfx"]["book_count"] or usfx_ids!=profile["usfx"]["member_order"]: problems.append("USFX book order/profile census mismatch")
    account=json.loads(candidate.member_bytes("source-accountability.json"))
    if account.get("tei_sha256")!=sha(xml) or account.get("source_lines")!=len(rows) or account.get("chapters")!=chapters or account.get("verses")!=verses: problems.append("source accountability receipt mismatch")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("readme").read_bytes(): problems.append("README differs from bound source note")
    if json.loads(candidate.member_bytes("provenance.json"))!=policy["provenance"]: problems.append("provenance differs")
    expected_unresolved=b"".join(canon(item) for item in policy["unresolved"])
    if candidate.member_bytes("unresolved.jsonl")!=expected_unresolved: problems.append("unresolved ledger differs")
    return problems

def _oracle(manifest:SourceManifest,candidate:CandidatePackage)->dict[str,object]:
    profile,policy=_load(manifest); usfm,_=_archive(manifest,profile,"usfm"); _,usfx_entries=_archive(manifest,profile,"usfx")
    problems=_check(manifest,candidate,profile,policy,usfm,usfx_entries)
    auth=_source_members(manifest); primary=sorted(({"name":x["name"],"path":x["path"],"bytes":x["bytes"],"sha256":x["sha256"]} for x in auth.values() if x.get("role")=="primary-source"),key=lambda x:(x["path"],x["name"]))
    source_sha=primary[0]["sha256"] if len(primary)==1 else sha(canon({"contract":"ocd-source-member-set-v1","members":primary}))
    vals={"status":"pass" if not problems else "fail","oracle_id":ORACLE_ID,"oracle_version":VERSION,"implementation_sha256":sha(Path(__file__).read_bytes()),"import_closure_sha256":sha(Path(__file__).read_bytes()),"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})","source_manifest_sha256":manifest.sha256,"candidate_sha256":candidate.sha256,"profile_sha256":sha(manifest.authority_path("profile").read_bytes()),"package_schema_sha256":sha(manifest.authority_path("candidate-package-schema").read_bytes()),"source_sha256":source_sha,"xsd_sha256":sha(manifest.authority_path("tei-p5-xsd").read_bytes()),"policy_sha256":sha(manifest.authority_path("policy").read_bytes()),"findings":problems}
    vals["result_sha256"]=sha(canon(vals)); return vals

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=VERSION
_oracle.implementation_path=Path(__file__).resolve()
