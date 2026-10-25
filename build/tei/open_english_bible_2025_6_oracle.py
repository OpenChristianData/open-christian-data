"""Independent archive-to-TEI oracle for retained Open English Bible 2025.6."""
from __future__ import annotations
from collections import Counter
import hashlib, json, platform, re, sys
from pathlib import Path, PurePosixPath
from typing import Mapping
from zipfile import ZipFile
from urllib.parse import quote
from lxml import etree
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

TEI="http://www.tei-c.org/ns/1.0"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"
XML_LANG="{http://www.w3.org/XML/1998/namespace}lang"
NS={"tei":TEI}
ORACLE_ID="ocd-open-english-bible-2025-6-independent-source-oracle"
SOURCE_BASE="raw/ebible/open-english-bible-2025.6"
OT={"GEN","JOS","RUT","EST","PSA","HOS","JOL","AMO","OBA","JON","MIC","NAM","HAB","ZEP","HAG","ZEC","MAL"}
NT={"MAT","MRK","LUK","JHN","ACT","ROM","1CO","2CO","GAL","EPH","PHP","COL","1TH","2TH","1TI","2TI","TIT","PHM","HEB","JAS","1PE","2PE","1JN","2JN","3JN","JUD","REV"}
LINE=re.compile(r"^\\([A-Za-z][A-Za-z0-9]*)(?:[ \t](.*))?$")
LINE_MARKERS={"b","c","d","h","id","ide","m","ms","mt","mt1","mt2","mt3","nb","p","periph","pi","q","q1","q2","q3","rem","s","s2","toc1","toc2","toc3","v"}
SECTION_HEADS={"s","s2","ms","d"}

def _sha(data: bytes)->str: return hashlib.sha256(data).hexdigest()
def _json(value: object)->bytes: return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
def closure_digest()->str:
    p=Path(__file__).resolve(); return _sha(_json([{"path":p.name,"sha256":_sha(p.read_bytes())}]))
def _resolve(root:Path, logical:str)->Path: return resolve_repo_path(root,logical).resolve(strict=True)
def _lines(data:bytes,label:str)->list[str]:
    if b"\r" in data or data.startswith(b"\xef\xbb\xbf"): raise ValueError(f"unsupported UTF-8 boundary at {label}")
    result=data.decode("utf-8",errors="strict").split("\n")
    if result and result[-1]=="": result.pop()
    return result

def _inline(value:str)->list[tuple[str,str]]:
    """Character scanner; independent of the converter's regular-expression tokenizer."""
    result=[]; text=[]; i=0
    while i<len(value):
        if value[i]!="\\": text.append(value[i]); i+=1; continue
        j=i+1
        if j<len(value) and value[j]=="+": j+=1
        start=j
        while j<len(value) and value[j].isascii() and value[j].isalnum(): j+=1
        if j==start: text.append(value[i]); i+=1; continue
        if j<len(value) and value[j]=="*": j+=1
        marker=value[i+1:j]
        if text: result.append(("text","".join(text))); text=[]
        result.append(("marker",marker)); i=j
    if text: result.append(("text","".join(text)))
    return result

def _expected_line(marker,payload,pointer,chapter,verse,variant,filename,number):
    if marker is None:
        kind="blank" if payload=="" else "continuation"
        return {"kind":kind,"marker":None,"payload":payload,"events":[] if not payload else _inline(payload),"pointer":pointer,"chapter":chapter,"verse":verse,"variant":variant},chapter,verse
    if marker=="c":
        if not payload.isdecimal(): raise ValueError(f"bad chapter number at {pointer}")
        return {"kind":"chapter","marker":marker,"payload":payload,"events":[],"pointer":pointer,"chapter":payload,"verse":None,"variant":variant},payload,None
    if marker=="v":
        num,sep,body=payload.partition(" ")
        if not sep or not num or chapter is None: raise ValueError(f"bad verse at {pointer}")
        return {"kind":"verse","marker":marker,"payload":body,"events":_inline(body),"pointer":pointer,"chapter":chapter,"verse":num,"variant":variant},chapter,num
    if marker=="periph":
        return {"kind":"periph","marker":marker,"payload":payload,"events":[],"pointer":pointer,"chapter":None,"verse":None,"variant":variant},None,None
    if marker in {"id","ide","h","toc1","toc2","toc3","mt","mt1","mt2","mt3","s","s2","ms","d"}: kind="head"
    elif marker in {"p","m","q","q1","q2","q3","pi"}: kind="block"
    elif marker=="rem": kind="rem"
    elif marker in {"b","nb"}: kind="break"
    else: raise ValueError(f"unprofiled line marker {marker!r} at {pointer}")
    new_verse=None if kind in {"head","block","rem","break"} else verse
    return {"kind":kind,"marker":marker,"payload":payload,"events":_inline(payload),"pointer":pointer,"chapter":chapter,"verse":verse,"variant":variant},chapter,new_verse

def _source_index(manifest:SourceManifest,profile:Mapping[str,object]):
    problems=[]; expected={}; summaries={}
    authorities={str(x["name"]):x for x in manifest.record["authorities"]}
    members={str(x["name"]):x for x in manifest.record.get("source_members",())}
    for vs in profile["variants"]:
        variant=vs["variant"]
        archive_path=manifest.authority_path(vs["archive"]["authority_name"])
        receipt_path=manifest.authority_path(vs["receipt"]["authority_name"])
        inventory_path=manifest.authority_path(vs["inventory"]["authority_name"])
        ab=archive_path.read_bytes(); rb=receipt_path.read_bytes(); ib=inventory_path.read_bytes()
        receipt=json.loads(rb.decode("utf-8")); normalized=ib.replace(b"\r\n",b"\n")
        if _sha(ab)!=vs["archive"]["sha256"] or len(ab)!=vs["archive"]["bytes"]: problems.append(f"{variant} archive hash differs")
        if _sha(rb)!=vs["receipt"]["sha256"] or len(rb)!=vs["receipt"]["bytes"]: problems.append(f"{variant} receipt digest differs")
        if b"\r" in normalized or not normalized.endswith(b"\n") or _sha(normalized)!=vs["inventory"]["canonical_lf_sha256"]: problems.append(f"{variant} inventory canonical digest differs")
        if receipt.get("manifest_row")!="L605" or receipt.get("variant")!=variant or receipt.get("release")!=profile["release"]: problems.append(f"{variant} receipt identity differs")
        inv=[line.split("\t") for line in normalized.decode("utf-8").splitlines()]
        source_files=[]; extracted_names=set(); selected=[]; observed=[]
        with ZipFile(archive_path) as z:
            if z.testzip() is not None: problems.append(f"{variant} ZIP CRC failure")
            infos=z.infolist()
            if len(infos)!=len(inv) or len(infos)!=vs["archive_member_count"]: problems.append(f"{variant} archive entry count differs")
            for pos,info in enumerate(infos,1):
                data=z.read(info); digest=_sha(data); row=inv[pos-1] if pos<=len(inv) else []
                if len(row)!=4: problems.append(f"{variant} inventory row absent at {pos}"); continue
                rn,rs,rc,rh=row; is_dir=info.is_dir()
                if (rn,int(rs),rc.casefold())!=(info.filename,info.file_size,f"{info.CRC:08x}"): problems.append(f"{variant} archive/inventory row mismatch at {pos}")
                if rh!=("<directory>" if is_dir else digest): problems.append(f"{variant} archive member hash mismatch at {pos}")
                pure=PurePosixPath(info.filename)
                if pure.is_absolute() or ".." in pure.parts or "\\" in info.filename: problems.append(f"{variant} unsafe archive path {info.filename!r}")
                logical=f"{SOURCE_BASE}/{variant}/usfm/{info.filename.rstrip('/')}"
                pe=vs["archive_entries"][pos-1] if pos<=len(vs["archive_entries"]) else {}
                auth_name=pe.get("authority_name")
                if pe.get("name")!=info.filename or pe.get("index")!=pos or pe.get("extraction_path")!=logical: problems.append(f"{variant} profile member identity mismatch at {pos}")
                extracted=_resolve(manifest.repository_root,logical)
                if is_dir:
                    if not extracted.is_dir(): problems.append(f"{variant} extracted directory missing: {info.filename}")
                    stored=None
                else:
                    extracted_names.add(info.filename)
                    if not extracted.is_file() or extracted.read_bytes()!=data: problems.append(f"{variant} extracted bytes mismatch: {info.filename}")
                    auth=authorities.get(str(auth_name)); sm=members.get(str(auth_name))
                    if auth is None or sm is None or auth.get("role")!="extracted-source-member": problems.append(f"{variant} extracted authority missing: {info.filename}")
                    elif any(auth.get(k)!=sm.get(k) for k in ("path","bytes","sha256")) or sm.get("logical_name")!=info.filename or sm.get("bytes")!=len(data) or sm.get("sha256")!=digest: problems.append(f"{variant} extraction manifest binding differs: {info.filename}")
                    stored=digest
                    if info.filename.startswith("usfm/") and info.filename.endswith(".usfm"): selected.append((info.filename,data))
                observed.append({"index":pos,"name":info.filename,"is_directory":is_dir,"bytes":info.file_size,"compressed_bytes":info.compress_size,"crc32":f"{info.CRC:08x}","sha256":stored,"extraction_path":logical,"authority_name":auth_name})
        if observed!=vs["archive_entries"]: problems.append(f"{variant} full archive inventory differs from profile")
        eroot=_resolve(manifest.repository_root,f"{SOURCE_BASE}/{variant}/usfm")
        disk={p.relative_to(eroot).as_posix() for p in eroot.rglob("*") if p.is_file()}
        if disk!=extracted_names: problems.append(f"{variant} extracted tree has missing or extra files")
        if [n for n,_ in selected]!=vs["book_member_order"] or len(selected)!=45 or len(selected)!=len(vs["usfm_files"]): problems.append(f"{variant} USFM order or count differs")
        variant_summaries=[]; seen_ids=[]
        for ix,(member,data) in enumerate(selected):
            fp=vs["usfm_files"][ix]; filename=member.split("/",1)[1]
            if fp.get("member")!=member or fp.get("bytes")!=len(data) or fp.get("sha256")!=_sha(data): problems.append(f"{variant}/{member} source profile mismatch")
            lines=_lines(data,f"{variant}/{member}")
            ident=next((LINE.fullmatch(line) for line in lines if LINE.fullmatch(line) and LINE.fullmatch(line).group(1)=="id"),None)
            if ident is None: problems.append(f"{variant}/{member} source ID absent"); continue
            book_id=(ident.group(2) or "").split(maxsplit=1)[0]; seen_ids.append(book_id)
            if book_id!=fp.get("book_id"): problems.append(f"{variant}/{member} source ID differs")
            chapter=verse=None; active_verse_id=None; line_counts=Counter(); inline_counts=Counter(); chapters=verses=blanks=continuations=0
            member_pointer=f"source-usfm:{variant}/{quote(filename,safe="")}"
            for number,raw in enumerate(lines,1):
                pointer=f"{member_pointer}#line={number}"; match=LINE.fullmatch(raw)
                if raw=="":
                    record,chapter,verse=_expected_line(None,"",pointer,chapter,verse,variant,filename,number)
                    record["target_verse_id"]=active_verse_id; blanks+=1
                elif match is None or match.group(1) not in LINE_MARKERS:
                    record,chapter,verse=_expected_line(None,raw,pointer,chapter,verse,variant,filename,number)
                    record["target_verse_id"]=active_verse_id; continuations+=1
                else:
                    marker=match.group(1); payload=match.group(2) or ""; line_counts[marker]+=1
                    chapters+=marker=="c"; verses+=marker=="v"
                    if marker in {"c","periph"}: active_verse_id=None
                    record,chapter,verse=_expected_line(marker,payload,pointer,chapter,verse,variant,filename,number)
                    if marker=="v":
                        active_verse_id=f"{variant}-{book_id}-line-{number}"
                        record["verse_xml_id"]=active_verse_id
                for kind,value in record["events"]:
                    if kind=="marker": inline_counts[value]+=1
                expected[pointer]=record
            if (len(lines),chapters,verses,blanks,continuations)!=(fp.get("line_count"),fp.get("chapter_count"),fp.get("verse_count"),fp.get("blank_line_count"),fp.get("continuation_line_count")): problems.append(f"{variant}/{member} line/chapter/verse totals differ")
            if dict(sorted(line_counts.items()))!=fp.get("line_marker_counts"): problems.append(f"{variant}/{member} line marker census differs")
            all_tokens=Counter(fp.get("marker_token_counts",{}))
            for key,count in line_counts.items(): all_tokens[key]-=count
            wanted={k:v for k,v in all_tokens.items() if v}
            if dict(sorted(inline_counts.items()))!=dict(sorted(wanted.items())): problems.append(f"{variant}/{member} inline marker census differs")
            variant_summaries.append({"member":member,"book_id":book_id,"line_count":len(lines),"chapter_count":chapters,"verse_count":verses,"line_marker_counts":dict(sorted(line_counts.items())),"inline_marker_counts":dict(sorted(inline_counts.items())),"blank_line_count":blanks,"continuation_line_count":continuations})
        biblical={x for x in seen_ids if x!="FRT"}
        if len(biblical)!=44 or biblical!=(OT|NT) or seen_ids.count("FRT")!=1: problems.append(f"{variant} retained book scope differs")
        if (sum(x["chapter_count"] for x in variant_summaries),sum(x["verse_count"] for x in variant_summaries))!=(565,13914): problems.append(f"{variant} chapter or verse total differs")
        summaries[variant]=variant_summaries
    return expected,summaries,problems

def _source_description(profile:Mapping[str,object])->str:
    archives={x["variant"]:x["archive"] for x in profile["variants"]}
    return (f"Open English Bible {profile['release']} USFM release retained from {profile['source_url']}; "
            f"US package SHA-256 {archives['US']['sha256']}; Cth package SHA-256 {archives['Cth']['sha256']}. "
            f"Declared contents: {profile['scope']['description']}")

def _events_from_tei(node:etree._Element,pointer:str):
    events=[]; pointers=[]; problems=[]
    def add_text(value):
        if value: events.append(("text",value))
    def walk(element,root=False):
        tag=etree.QName(element).localname; kind=element.get("type"); marker=""
        if not root:
            if tag=="note" and kind=="usfm-footnote": marker="f"
            elif tag=="label" and kind=="usfm-fr": marker="fr"
            elif tag=="seg" and kind=="usfm-ft": marker="ft"
            elif tag=="milestone" and element.get("unit")=="usfm-marker": marker=element.get("n") or ""
            elif tag in {"hi","name","q"}: problems.append(f"inline wrapper hides marker events at {pointer}")
            if marker:
                events.append(("marker",marker)); found=element.get("corresp")
                if found is None: problems.append(f"inline marker has no source pointer at {pointer}")
                else: pointers.append(found)
        add_text(element.text)
        for child in element:
            p=child.get("corresp") or ""
            if "#line=" in p and "&token=" not in p:
                add_text(child.tail); continue
            walk(child); add_text(child.tail)
    walk(node,True)
    if pointers!=[f"{pointer}&token={i}" for i in range(1,len(pointers)+1)]:
        problems.append(f"inline marker positions differ at {pointer}")
    return events,problems

def _shape(node:etree._Element,record:Mapping[str,object])->list[str]:
    p=record["pointer"]; kind=record["kind"]; marker=record["marker"]
    if kind=="blank":
        ok=etree.QName(node).localname=="milestone" and node.get("unit")=="source-line" and node.get("n")=="blank" and node.get("target") is None
    elif kind=="continuation":
        wanted=f"#{record['target_verse_id']}" if record.get("target_verse_id") else None
        links=node.xpath("./tei:ptr[@type='preceding-verse']/@target",namespaces=NS)
        ok=etree.QName(node).localname=="ab" and node.get("type")=="source-continuation" and links==[wanted]
    elif kind=="chapter": ok=etree.QName(node).localname=="div" and node.get("type")=="chapter" and node.get("ana")=="#usfm-c" and node.get("n")==record["payload"]
    elif kind=="verse": ok=etree.QName(node).localname=="ab" and node.get("type")=="verse" and node.get("ana")=="#usfm-v" and node.get("n")==record["verse"] and node.get(XML_ID)==record.get("verse_xml_id")
    elif kind=="periph": ok=etree.QName(node).localname=="div" and node.get("type")=="periph" and node.get("ana")=="#usfm-periph" and node.get("n")==record["payload"]
    elif kind=="head":
        if marker in SECTION_HEADS:
            parent=node.getparent()
            ok=etree.QName(node).localname=="head" and node.get("type")==f"usfm-{marker}" and node.get("ana")==f"#usfm-{marker}" and parent is not None and etree.QName(parent).localname=="div" and parent.get("type")=="usfm-section"
        else:
            ok=etree.QName(node).localname=="ab" and node.get("type")==f"usfm-{marker}" and node.get("ana")==f"#usfm-{marker}"
    elif kind=="block": ok=etree.QName(node).localname=="ab" and node.get("type")==f"usfm-{marker}" and node.get("ana")==f"#usfm-{marker}"
    elif kind=="rem": ok=etree.QName(node).localname=="note" and node.get("type")=="usfm-rem" and node.get("ana")=="#usfm-rem"
    elif kind=="break": ok=etree.QName(node).localname=="milestone" and node.get("unit")=="usfm-line-marker" and node.get("n")==marker
    else: ok=False
    return [] if ok else [f"wrong TEI line node kind or owner at {p}"]

def _account_variants(summaries):
    result=[]
    for variant,books in summaries.items():
        line=Counter(); inline=Counter()
        for book in books:
            line.update(book["line_marker_counts"]); inline.update(book["inline_marker_counts"])
        result.append({"variant":variant,"source_line_count":sum(x["line_count"] for x in books),"chapter_count":sum(x["chapter_count"] for x in books),"verse_count":sum(x["verse_count"] for x in books),"blank_source_line_count":sum(x["blank_line_count"] for x in books),"continuation_line_count":sum(x["continuation_line_count"] for x in books),"line_marker_counts":dict(sorted(line.items())),"inline_marker_counts":dict(sorted(inline.items())),"books":books})
    return result

def _archive_accounting(profile):
    return [{"variant":v["variant"],"archive_sha256":v["archive"]["sha256"],"receipt_sha256":v["receipt"]["sha256"],"raw_inventory_sha256":v["inventory"]["sha256"],"canonical_inventory_sha256":v["inventory"]["canonical_lf_sha256"],"archive_member_count":v["archive_member_count"],"archive_file_count":v["archive_file_count"],"extracted_file_count":v["archive_file_count"],"archive_entries":[{"index":e["index"],"member":e["name"],"is_directory":e["is_directory"],"bytes":e["bytes"],"crc32":e["crc32"],"sha256":e["sha256"],"extraction_path":e["extraction_path"]} for e in v["archive_entries"]]} for v in profile["variants"]]

def check_xml(manifest:SourceManifest,content:bytes)->list[str]:
    try: tree=etree.fromstring(content,parser=etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    except etree.XMLSyntaxError as exc: return [f"TEI XML parse failure: {exc}"]
    profile=json.loads(manifest.authority_path("profile").read_bytes())
    policy=json.loads(manifest.authority_path("policy").read_bytes())
    problems=[]
    if tree.tag!=f"{{{TEI}}}TEI" or tree.xpath(".//tei:TEI",namespaces=NS):
        return ["candidate must have exactly one document-level TEI root"]
    if tree.get(XML_ID)!="open-english-bible-2025-6-L605" or tree.get(XML_LANG)!="en" or tree.get("ana")!="#nonaccepted-candidate": problems.append("TEI root identity or nonaccepted status differs")
    titles=tree.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title/text()",namespaces=NS)
    if titles!=[profile["title"]]: problems.append("TEI title differs from profile")
    pub=tree.xpath("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:p/text()",namespaces=NS)
    if pub!=["Nonaccepted technical reconstruction candidate; human acceptance, rights review, and publication are separate decisions."]: problems.append("TEI nonaccepted status statement differs")
    source=tree.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:p/text()",namespaces=NS)
    if source!=[_source_description(profile)]: problems.append("TEI source description or archive identity differs")
    desc=tree.xpath("./tei:teiHeader/tei:encodingDesc/tei:p/text()",namespaces=NS)
    if desc!=[policy["mapping"],policy["scope"]]: problems.append("TEI mapping policy or partial scope differs")
    groups=tree.xpath("./tei:text/tei:group",namespaces=NS)
    if len(groups)!=1: return problems+["candidate must contain one text/group for its witness branches"]
    branches=groups[0].xpath("./tei:text",namespaces=NS)
    if [x.get("n") for x in branches]!=profile["variant_order"] or [x.get("type") for x in branches]!=["witness","witness"]: problems.append("US/Cth variant labels or order differ")
    if len(branches)!=2: return problems+["candidate must contain the two retained variants separately"]
    expected,summaries,source_problems=_source_index(manifest,profile); problems.extend(source_problems)
    for variant,branch in zip(profile["variant_order"],branches):
        variant=str(variant)
        if branch.get(XML_ID)!=f"oeb-2025-6-{variant.lower()}": problems.append(f"{variant} witness xml:id differs")
        body=branch.find(f"{{{TEI}}}body")
        if body is None: problems.append(f"{variant} witness body absent"); continue
        spec=next(x for x in profile["variants"] if x["variant"]==variant)
        members=[x for x in body if etree.QName(x).localname=="div" and x.get("type") in {"front-matter","book"}]
        if len(members)!=len(spec["usfm_files"]): problems.append(f"{variant} source member count differs")
        if [x.get("n") for x in members]!=[x["book_id"] for x in spec["usfm_files"]]: problems.append(f"{variant} source member order or IDs differ")
        for node,file in zip(members,spec["usfm_files"]):
            wanted_type="front-matter" if file["is_front_page"] else "book"
            if node.get("type")!=wanted_type or node.get("n")!=file["book_id"]: problems.append(f"{variant}/{file['member']} member type/identity differs")
            wanted_pointer=f"source-usfm:{variant}/{quote(file['filename'],safe="")}"
            if node.get("corresp")!=wanted_pointer: problems.append(f"{variant}/{file['member']} member pointer differs")
            if wanted_type=="book" and node.get(XML_ID)!=f"{variant}-{file['book_id']}": problems.append(f"{variant}/{file['member']} book xml:id differs")
        branch_expected={p:r for p,r in expected.items() if r["variant"]==variant}
        observed={}
        for element in body.iter():
            pointer=element.get("corresp") or ""
            if "#line=" in pointer and "&token=" not in pointer: observed.setdefault(pointer,[]).append(element)
        if set(observed)!=set(branch_expected): problems.append(f"{variant} TEI source lines are missing or invented")
        for pointer,record in branch_expected.items():
            nodes=observed.get(pointer,[])
            if len(nodes)!=1: problems.append(f"{variant} source line pointer missing/duplicated: {pointer}"); continue
            node=nodes[0]; problems.extend(_shape(node,record))
            actual,inline_problems=_events_from_tei(node,pointer); problems.extend(inline_problems)
            if actual!=record["events"]: problems.append(f"source wording or inline marker order differs at {pointer}")
            if record["kind"]=="continuation":
                link=node.xpath("./tei:ptr[@type='preceding-verse']/@target",namespaces=NS)
                chapter=node.xpath("ancestor::tei:div[@type='chapter'][1]",namespaces=NS)
                if record.get("target_verse_id") is None or link!=[f"#{record['target_verse_id']}"] or not chapter or chapter[0].get("n")!=record["chapter"]: problems.append(f"continuation target or source-order owner differs at {pointer}")
            elif record["kind"]=="verse":
                chapter=node.xpath("ancestor::tei:div[@type='chapter'][1]",namespaces=NS)
                if not chapter or chapter[0].get("n")!=record["chapter"]: problems.append(f"verse attached to the wrong chapter at {pointer}")
            elif record["kind"]=="chapter":
                parent=node.getparent()
                if parent is None or etree.QName(parent).localname!="div" or parent.get("type") not in {"book","front-matter"}: problems.append(f"chapter attached to the wrong source member at {pointer}")
            if len(problems)>100: break
    schema=etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-validation-schema"))))
    if not schema.validate(etree.ElementTree(tree)): problems.append(f"TEI P5 XSD failure: {schema.error_log.last_error}")
    return problems

def _primary_sha(manifest:SourceManifest)->str:
    values=sorted(({"name":x["name"],"path":x["path"],"bytes":x["bytes"],"sha256":x["sha256"]} for x in manifest.record["authorities"] if x.get("role")=="primary-source"),key=lambda x:(str(x["path"]),str(x["name"])))
    return _sha(_json({"contract":"ocd-source-member-set-v1","members":values}))

def _oracle(manifest:SourceManifest,candidate:CandidatePackage)->Mapping[str,object]:
    xml=candidate.member_bytes("content.tei.xml"); problems=check_xml(manifest,xml)
    profile=json.loads(manifest.authority_path("profile").read_bytes()); policy=json.loads(manifest.authority_path("policy").read_bytes())
    account=json.loads(candidate.member_bytes("source-accountability.json"))
    expected,summaries,source_problems=_source_index(manifest,profile); problems.extend(source_problems)
    variants=_account_variants(summaries)
    if account.get("contract")!="ocd-open-english-bible-2025-6-accountability-v1" or account.get("source_id")!=profile["source_id"] or account.get("source_manifest_sha256")!=manifest.sha256 or account.get("profile_sha256")!=next(x["sha256"] for x in manifest.record["authorities"] if x.get("name")=="profile") or account.get("tei_sha256")!=_sha(xml) or account.get("tei_root_count")!=1 or account.get("variant_order")!=profile["variant_order"] or account.get("scope")!=profile["scope"] or account.get("variants")!=variants or account.get("archive_accounting")!=_archive_accounting(profile): problems.append("source-accountability differs from independent archive and line accounting")
    if candidate.member_bytes("README.source.md")!=manifest.authority_path("readme").read_bytes(): problems.append("candidate README differs from bound source description")
    if json.loads(candidate.member_bytes("provenance.json"))!=policy["provenance"]: problems.append("candidate provenance differs from policy")
    if candidate.member_bytes("unresolved.jsonl")!=b"".join(_json(x) for x in policy["unresolved"]): problems.append("candidate unresolved ledger differs from policy")
    roles={str(x["role"]):x for x in manifest.record["authorities"] if x.get("role")!="primary-source"}
    result={"status":"pass" if not problems else "fail","oracle_id":ORACLE_ID,"oracle_version":"1","implementation_sha256":_sha(Path(__file__).read_bytes()),"import_closure_sha256":closure_digest(),"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})","source_manifest_sha256":manifest.sha256,"candidate_sha256":candidate.sha256,"source_sha256":_primary_sha(manifest),"profile_sha256":roles["complete-source-feature-profile"]["sha256"],"package_schema_sha256":roles["candidate-package-schema"]["sha256"],"xsd_sha256":roles["tei-validation-schema"]["sha256"],"policy_sha256":roles["independent-validation-policy"]["sha256"],"findings":problems}
    result["result_sha256"]=_sha(_json(result)); return result

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version="1"
_oracle.implementation_path=Path(__file__).resolve()
