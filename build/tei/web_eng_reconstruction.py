"""Source-bound reconstruction of the retained eBible eng-web edition."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from zipfile import ZipFile

from lxml import etree
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.lib.storage_topology import resolve_repo_path

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
CONVERTER_ID = "ocd-ebible-eng-web-usfm-to-tei"
LINE_RE = re.compile(r"^\\(?P<marker>[A-Za-z0-9]+)(?: (?P<content>.*))?$", re.DOTALL)
INLINE_RE = re.compile(r"\\([+A-Za-z0-9]+)(\*)?")
WORD_ATTR = re.compile(r'^(?P<word>.*?)\|strong="(?P<strong>[^"]+)"$', re.DOTALL)
SOURCE_PREFIX = "source-usfm:eng-web/"
BOOK_RE = re.compile(r"^[0-9]{2,3}-(?P<id>[A-Z0-9]{3})eng-web\.usfm$")
PAIRED = {"w", "+w", "+wh", "wj", "f", "x", "k", "bk", "+bk", "qs", "fl"}
INTERNAL = {"fr", "ft", "fqa", "fq", "xo", "xt"}

def _sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def _json(x: object) -> bytes: return (json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
def _q(name: str) -> str: return f"{{{TEI}}}{name}"

def _members(manifest: SourceManifest, profile: dict) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes]]]:
    roots=[]
    for label, archive_auth, inventory_auth, root_rel, expected in (
        ("usfm", "usfm-archive", "usfm-inventory", "raw/ebible/eng-web/usfm/members", profile["usfm"]),
        ("usfx", "usfx-archive", "usfx-inventory", "raw/ebible/eng-web/usfx/members", profile["usfx"]),
    ):
        archive_path=manifest.authority_path(archive_auth); inv_path=manifest.authority_path(inventory_auth)
        raw=archive_path.read_bytes()
        if len(raw)!=expected["archive_bytes"] or _sha(raw)!=expected["archive_sha256"]: raise ValueError(f"{label} archive binding mismatch")
        extracted=resolve_repo_path(manifest.repository_root,root_rel)
        records=[]; selected=[]
        with ZipFile(archive_path) as z:
            if z.testzip() is not None: raise ValueError(f"{label} archive CRC failure")
            for i,info in enumerate(z.infolist(),1):
                content=z.read(info); name=info.filename
                records.append({"index":i,"name":name,"is_directory":info.is_dir(),"bytes":len(content),"compressed_bytes":info.compress_size,"crc32":f"{info.CRC:08x}","sha256":_sha(content)})
                path=extracted / Path(*name.replace("\\","/").split("/"))
                if not info.is_dir():
                    if not path.is_file() or path.read_bytes()!=content: raise ValueError(f"{label} extracted member mismatch: {name}")
                if label=="usfm" and BOOK_RE.fullmatch(name): selected.append((name,content))
        if _sha(inv_path.read_bytes())!=expected["inventory_file_sha256"]: raise ValueError(f"{label} retained inventory file binding mismatch")
        if records!=expected["entries"] or len(records)!=expected["member_count"]: raise ValueError(f"{label} full envelope inventory mismatch")
        roots.append((label,selected if label=="usfm" else records))
    usfm=roots[0][1]; usfx=roots[1][1]
    if [n for n,_ in usfm]!=profile["usfm"]["book_member_order"]: raise ValueError("USFM source order mismatch")
    if not isinstance(usfx,list): raise ValueError("USFX inventory malformed")
    return usfm, []

def _append_text(parent, value):
    if not value:return
    if len(parent): parent[-1].tail=(parent[-1].tail or "")+value
    else: parent.text=(parent.text or "")+value

def _inline(parent, text):
    stack=[("root",parent)]; pos=0
    for match in INLINE_RE.finditer(text):
        _append_text(stack[-1][1],text[pos:match.start()]); marker=match.group(1); close=bool(match.group(2))
        if close:
            ix=next((i for i in range(len(stack)-1,0,-1) if stack[i][0]==marker),None)
            if ix is None: raise ValueError(f"unmatched inline close {marker}")
            node=stack[ix][1]
            if marker in {"w","+w"}:
                payload=node.text or ""; found=WORD_ATTR.fullmatch(payload)
                if found is None: raise ValueError(f"invalid word payload: {payload[:60]!r}")
                node.text=found.group("word"); node.set("n",found.group("strong"))
            stack=stack[:ix]
        elif marker in PAIRED:
            if marker in {"f","x"}: node=etree.SubElement(stack[-1][1],_q("note"),type="footnote" if marker=="f" else "cross-reference")
            elif marker in {"w","+w"}: node=etree.SubElement(stack[-1][1],_q("w"),type=marker)
            elif marker=="+wh": node=etree.SubElement(stack[-1][1],_q("seg"),type="usfm-+wh")
            elif marker=="wj": node=etree.SubElement(stack[-1][1],_q("seg"),type="words-of-Jesus")
            elif marker in {"k"}: node=etree.SubElement(stack[-1][1],_q("term"))
            elif marker in {"bk","+bk"}: node=etree.SubElement(stack[-1][1],_q("title"),type="book-name")
            elif marker=="fl": node=etree.SubElement(stack[-1][1],_q("foreign"))
            else: node=etree.SubElement(stack[-1][1],_q("seg"),type="usfm-qs")
            stack.append((marker,node))
        elif marker in INTERNAL:
            index=next((i for i in range(len(stack)-1,0,-1) if stack[i][0] in {"f","x"}),None)
            if index is None: raise ValueError(f"note marker {marker} outside note")
            stack=stack[:index+1]; node=etree.SubElement(stack[-1][1],_q("seg"),type="usfm-"+marker); stack.append((marker,node))
        else: raise ValueError(f"unsupported inline marker {marker}")
        pos=match.end()
    _append_text(stack[-1][1],text[pos:])
    open_paired=[name for name,_ in stack[1:] if name in PAIRED]
    if open_paired: raise ValueError(f"unclosed inline markers: {open_paired}")

def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    profile=json.loads(manifest.authority_path("profile").read_bytes()); policy=json.loads(manifest.authority_path("policy").read_bytes())
    usfm,_=_members(manifest,profile)
    root=etree.Element(_q("TEI"),nsmap={None:TEI}); root.set(XML_ID,"world-english-bible-classic-eng-web"); root.set(XML_LANG,"en"); root.set("ana","#nonaccepted-candidate")
    header=etree.SubElement(root,_q("teiHeader")); fd=etree.SubElement(header,_q("fileDesc")); ts=etree.SubElement(fd,_q("titleStmt")); etree.SubElement(ts,_q("title")).text=profile["title"]
    for name in ("World English Bible Committee",):
        rs=etree.SubElement(ts,_q("respStmt")); etree.SubElement(rs,_q("resp")).text="Revision"; etree.SubElement(rs,_q("name")).text=name
    ps=etree.SubElement(fd,_q("publicationStmt")); etree.SubElement(ps,_q("p")).text="Nonaccepted source-to-TEI candidate; human acceptance, rights review, and publication remain open."
    source_desc=etree.SubElement(fd,_q("sourceDesc")); etree.SubElement(source_desc,_q("bibl")).text=profile["edition"]
    enc=etree.SubElement(header,_q("encodingDesc")); etree.SubElement(enc,_q("p")).text="Every source line is preserved verbatim in a direct source-usfm-raw note and mapped to a source-pointed TEI carrier. Source labels, front matter, glossary, heading, poetry, verse, supplied formatting, footnotes, cross-references, and inline markers stay in source order; whitespace in the witness is never normalized."
    etree.SubElement(enc,_q("p")).text="The source provider states that the text is public domain and that the World English Bible name must not be used for altered text. This candidate preserves the actual source wording; no title or text edits were made."
    etree.SubElement(etree.SubElement(header,_q("profileDesc")),_q("langUsage")).append(etree.Element(_q("language"),ident="en"))
    body=etree.SubElement(etree.SubElement(root,_q("text")),_q("body")); line_counts=Counter(); inline_counts=Counter(); verses=chapters=0; retained=[]
    for filename,raw in usfm:
        book_id=BOOK_RE.fullmatch(filename).group("id"); book=etree.SubElement(body,_q("div"),type="paratext" if book_id in {"FRT","GLO"} else "book",n=book_id,corresp=SOURCE_PREFIX+filename); book.set(XML_ID,"web-"+book_id)
        chapter=None; current_verse=None
        for lineno,line in enumerate(raw.decode("utf-8").split("\n"),1):
            parsed=LINE_RE.fullmatch(line)
            if parsed is None:
                pointer=f"{SOURCE_PREFIX}{filename}#line={lineno}"
                blank=etree.SubElement(chapter if chapter is not None else book,_q("ab"),type="usfm-blank-line",corresp=pointer)
                etree.SubElement(blank,_q("note"),type="source-usfm-raw").text=line
                retained.append((filename,lineno,line))
                continue
            marker=parsed.group("marker"); value=parsed.group("content") or ""; line_counts[marker]+=1; inline_counts.update(m.group(1)+("*" if m.group(2) else "") for m in INLINE_RE.finditer(value)); pointer=f"{SOURCE_PREFIX}{filename}#line={lineno}"
            if marker=="c":
                n=value.split()[0]; chapter=etree.SubElement(book,_q("div"),type="chapter",n=n); chapter.set(XML_ID,f"web-{book_id}-{n}"); chapters+=1; current_verse=None; node=etree.SubElement(chapter,_q("ab"),type="source-chapter-label",corresp=pointer)
            elif marker=="v":
                if chapter is None: raise ValueError(f"verse precedes chapter {filename}:{lineno}")
                parts=value.split(maxsplit=1); n=parts[0]; current_verse=etree.SubElement(chapter,_q("ab"),type="verse",n=n,corresp=pointer); current_verse.set(XML_ID,f"web-{book_id}-{chapter.get('n')}-{n}"); node=current_verse; verses+=1
                value=parts[1] if len(parts)>1 else ""
            else:
                container=chapter if chapter is not None else book
                if marker in {"id","h","toc1","toc2","toc3","cl","cp","mt1","mt2","mt3","ms1","s1","is1","d"}: tag="ab"; attrs={"type":"usfm-"+marker}
                elif marker=="sp": tag="ab"; attrs={"type":"usfm-sp"}
                elif marker=="b": tag="ab"; attrs={"type":"usfm-b"}; value=""
                elif marker in {"q1","q2","q3","p","m","mi","nb","li1","pi1","ili","pc"}: tag="ab"; attrs={"type":"usfm-"+marker}
                else: tag="ab"; attrs={"type":"usfm-"+marker}
                node=etree.SubElement(container,_q(tag),corresp=pointer,**attrs)
            etree.SubElement(node,_q("note"),type="source-usfm-raw").text=line
            _inline(node,value)
            retained.append((filename,lineno,line))
    tei=etree.tostring(root,encoding="UTF-8",xml_declaration=True,pretty_print=False)
    accountability={"contract":"ocd-ebible-eng-web-accountability-v1","source_manifest_sha256":manifest.sha256,"usfm_archive_sha256":profile["usfm"]["archive_sha256"],"usfx_archive_sha256":profile["usfx"]["archive_sha256"],"usfm_members":profile["usfm"]["member_count"],"usfx_members":profile["usfx"]["member_count"],"source_book_members":len(usfm),"source_lines":len(retained),"chapters":chapters,"verses":verses,"line_marker_counts":dict(sorted(line_counts.items())),"inline_marker_counts":dict(sorted(inline_counts.items())),"usfx_alignment":profile["cross_encoding_alignment"],"tei_sha256":_sha(tei),"rights_and_title_use":profile["rights_and_title_use"]}
    return {"README.source.md":manifest.authority_path("readme").read_bytes(),"content.tei.xml":tei,"source-accountability.json":_json(accountability),"provenance.json":_json(policy["provenance"]),"unresolved.jsonl":b"".join(_json(x) for x in policy["unresolved"])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version="1"
_convert.implementation_path=Path(__file__).resolve()
