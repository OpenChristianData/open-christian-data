"""Deterministic faithful TEI candidate for Anderson's 1864 New Testament."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, unquote

from lxml import etree

from build.tei import brenton_septuagint as base
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import compiled_schema


TEI_NS = base.TEI_NS
XML_ID = base.XML_ID
XML_LANG = base.XML_LANG
SOURCE_PREFIX = "source-usfm:anderson1864/"
CONFIG_RELATIVE = "sources/structured-text/anderson-1864-new-testament/config.json"
RAW_RELATIVE = "raw/clean-ready-acquisition-to-tei/master-3/21/anderson-1864-new-testament"
OUTPUT_PREFIX = "reports/clean-ready-acquisition-to-tei/master-3/21/anderson-1864-new-testament/"
DEFAULT_OUTPUT = OUTPUT_PREFIX + "candidate"
MEMBER_IDS = (
    "FRT", "INT", "MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO",
    "GAL", "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM",
    "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV", "GLO",
)
BOOK_IDS = MEMBER_IDS[2:-1]
PARATEXT_IDS = frozenset({"FRT", "INT", "GLO"})
LINE_MARKERS = {
    "id", "ide", "rem", "h", "toc1", "mt1", "mt3", "mt4", "periph", "pc",
    "p", "pr", "m", "mte", "c", "cl", "v", "ms", "ms2", "s1",
}
PAIRED = {"add", "it", "sc", "sig", "w"}
TOKEN = re.compile(r"\\([A-Za-z0-9]+)(\*)?")
POINTER = re.compile(r"^source-usfm:anderson1864/(?P<file>[^#]+)#line=(?P<line>[1-9][0-9]*)$")


def _q(name: str) -> str:
    return base._q(name)


def _pointer(path: Path, line_number: int) -> str:
    return f"{SOURCE_PREFIX}{quote(path.name, safe='')}#line={line_number}"


def _load_config(root: Path) -> dict[str, Any]:
    return json.loads((root / CONFIG_RELATIVE).read_bytes())


def _parse(line: str) -> tuple[str, str]:
    if not line.startswith("\\"):
        raise ValueError(f"unmarked USFM line: {line!r}")
    parts = line[1:].split(maxsplit=1)
    return parts[0], parts[1] if len(parts) == 2 else ""


def _id(path: Path) -> str:
    marker, content = _parse(path.read_text(encoding="utf-8-sig").split("\n", 1)[0])
    if marker != "id":
        raise ValueError(f"missing id in {path.name}")
    return content.split()[0]


def _files(source_root: Path) -> list[Path]:
    by_id = {_id(path): path for path in source_root.glob("*.sfm")}
    if set(by_id) != set(MEMBER_IDS):
        raise ValueError("authority member-id set mismatch")
    return [by_id[value] for value in MEMBER_IDS]


def _validate_authority_root(source_root: Path, config: dict[str, Any]) -> dict[str, object]:
    inventory, digest = base._shallow_member_inventory(source_root)
    if digest != config["authority"]["member_inventory_sha256"]:
        raise ValueError("authority member inventory digest mismatch")
    if len(inventory) != 30:
        raise ValueError("authority member count mismatch")
    line_counts: Counter[str] = Counter()
    inline: Counter[str] = Counter()
    chapters = verses = lines_total = 0
    for path in _files(source_root):
        current_chapter = ""
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        lines_total += len(lines)
        for number, line in enumerate(lines, 1):
            marker, content = _parse(line)
            if marker not in LINE_MARKERS:
                raise ValueError(f"unsupported line marker {marker} in {path.name}:{number}")
            line_counts[marker] += 1
            for token, closing in TOKEN.findall(line):
                inline[token + ("*" if closing else "")] += 1
            if marker == "c":
                chapters += 1
                current_chapter = content.split()[0]
            elif marker == "v":
                if not current_chapter:
                    raise ValueError("verse precedes chapter")
                verses += 1
    for marker in PAIRED:
        if inline[marker] != inline[marker + "*"]:
            raise ValueError(f"unbalanced inline marker {marker}")
    unknown = {key.removesuffix("*") for key in inline} - LINE_MARKERS - PAIRED
    if unknown:
        raise ValueError(f"unsupported inline markers: {sorted(unknown)}")
    return {
        "member_ids": list(MEMBER_IDS), "member_count": 30, "book_count": 27,
        "paratext_count": 3, "chapter_count": chapters, "verse_count": verses,
        "source_line_count": lines_total, "line_marker_counts": dict(sorted(line_counts.items())),
        "inline_marker_counts": dict(sorted(inline.items())), "member_inventory_sha256": digest,
    }


def _validate_acquisition(root: Path, config: dict[str, Any]) -> dict[str, object]:
    for section, label in (("authority", "authority archive"), ("sword", "SWORD archive"), ("witness", "print witness")):
        binding = config[section]
        path = binding.get("archive_path", binding.get("path"))
        base._validate_file_binding(resolve_repo_path(root, path), {"bytes": binding["archive_bytes"] if "archive_bytes" in binding else binding["bytes"], "sha256": binding["archive_sha256"] if "archive_sha256" in binding else binding["sha256"]}, label)
    raw_root = resolve_repo_path(root, RAW_RELATIVE)
    info = (raw_root / "metadata/crosswire-module-info.html").read_bytes()
    if b"1.0.1" not in info or b"Public Domain" not in info:
        raise ValueError("CrossWire identity evidence mismatch")
    commit = json.loads((raw_root / "metadata/github-commit.json").read_bytes())
    if commit.get("sha") != config["source_commit"]:
        raise ValueError("GitHub commit evidence mismatch")
    inventory, digest = base._member_inventory(raw_root)
    return {"retained_file_count": len(inventory), "retained_file_inventory_sha256": digest, "retained_files": inventory}


def _append_inline(parent: etree._Element, value: str) -> None:
    stack: list[tuple[str, etree._Element]] = [("root", parent)]
    pos = 0
    for match in TOKEN.finditer(value):
        base._append_text(stack[-1][1], value[pos:match.start()])
        marker, closing = match.group(1), bool(match.group(2))
        if closing:
            index = next((i for i in range(len(stack)-1, 0, -1) if stack[i][0] == marker), None)
            if index is None:
                raise ValueError(f"unmatched close {marker}")
            if marker == "w":
                text = stack[index][1].text or ""
                if "|" in text:
                    word, key = text.rsplit("|", 1); stack[index][1].text = word; stack[index][1].set("key", key)
            stack = stack[:index]
        elif marker in PAIRED:
            if marker == "add": child = etree.SubElement(stack[-1][1], _q("supplied"), reason="source-marked")
            elif marker in {"it", "sc"}: child = etree.SubElement(stack[-1][1], _q("hi"), rend="italic" if marker == "it" else "small-caps")
            elif marker == "sig": child = etree.SubElement(stack[-1][1], _q("seg"), type="signature")
            else: child = etree.SubElement(stack[-1][1], _q("term"), type="glossary-keyword")
            stack.append((marker, child))
        elif marker not in LINE_MARKERS:
            raise ValueError(f"unsupported inline marker {marker}")
        pos = match.end()
    base._append_text(stack[-1][1], value[pos:])
    if any(marker in PAIRED for marker, _ in stack[1:]):
        raise ValueError("unclosed inline marker")


def _render(root: Path, config: dict[str, Any]) -> tuple[bytes, dict[str, object]]:
    source_root = resolve_repo_path(root, config["source_root"])
    evidence = _validate_authority_root(source_root, config)
    tei = etree.Element(_q("TEI"), nsmap={None: TEI_NS}); tei.set(XML_ID, "anderson-1864-new-testament"); tei.set(XML_LANG, "en"); tei.set("ana", "#nonaccepted-candidate")
    header = etree.SubElement(tei, _q("teiHeader")); fd = etree.SubElement(header, _q("fileDesc")); ts = etree.SubElement(fd, _q("titleStmt")); etree.SubElement(ts, _q("title")).text=config["title"]; rs=etree.SubElement(ts,_q("respStmt"));etree.SubElement(rs,_q("resp")).text="Translation";etree.SubElement(rs,_q("name")).text=config["translator"]
    ps=etree.SubElement(fd,_q("publicationStmt"));etree.SubElement(ps,_q("publisher")).text="Nonaccepted ticket-21 candidate; not publication.";av=etree.SubElement(ps,_q("availability"),status="free");etree.SubElement(av,_q("p")).text="CrossWire and the pinned source repository identify the text as public domain."
    sd=etree.SubElement(fd,_q("sourceDesc"));b=etree.SubElement(sd,_q("bibl"));etree.SubElement(b,_q("title")).text=config["title"];etree.SubElement(b,_q("ref"),target=config["source_url"]).text="Pinned USFM authority"
    ed=etree.SubElement(header,_q("encodingDesc"));etree.SubElement(ed,_q("p")).text="Every exact USFM line is retained in a source-usfm-raw note and projected into member, chapter, verse, paratext, typography, glossary, and annotation structures."
    body=etree.SubElement(etree.SubElement(tei,_q("text")),_q("body"))
    for path in _files(source_root):
        mid=_id(path); member=None; chapter=None
        for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(),1):
            marker,content=_parse(raw);pointer=_pointer(path,number)
            if marker=="id":
                member=etree.SubElement(body,_q("div"),type="book" if mid in BOOK_IDS else "paratext",n=mid,corresp=pointer);member.set(XML_ID,f"anderson-{mid}");base._add_raw_note(member,raw);continue
            container=chapter if chapter is not None else member
            if marker=="c": chapter=etree.SubElement(member,_q("div"),type="chapter",n=content.split()[0],corresp=pointer);base._add_raw_note(chapter,raw);continue
            if marker=="v": parts=content.split(maxsplit=1);label=parts[0];text=parts[1] if len(parts)>1 else "";node=etree.SubElement(chapter,_q("ab"),type="verse",n=label,corresp=pointer)
            else: node=etree.SubElement(container,_q("ab"),type=f"usfm-{marker}",n=marker,corresp=pointer);text=content
            base._add_raw_note(node,raw);_append_inline(node,text)
    content=etree.tostring(tei,encoding="UTF-8",xml_declaration=True,pretty_print=False)
    parsed=etree.fromstring(content,parser=etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True));compiled_schema().assertValid(etree.ElementTree(parsed))
    inverse=_verify_source_files(content,source_root);return content,{**evidence,**inverse}


def _verify_source_files(content: bytes, source_root: Path) -> dict[str, object]:
    root=etree.fromstring(content,parser=etree.XMLParser(huge_tree=True));seen:dict[str,dict[int,str]]=defaultdict(dict)
    for node in root.iter():
        pointer=node.get("corresp");match=POINTER.fullmatch(pointer or "")
        if not match: continue
        notes=[c for c in node if c.tag==_q("note") and c.get("type")=="source-usfm-raw"]
        if len(notes)!=1 or notes[0].text is None: raise ValueError("missing raw note")
        seen[unquote(match.group("file"))][int(match.group("line"))]=notes[0].text
    total=0
    for path in _files(source_root):
        expected=path.read_text(encoding="utf-8-sig").splitlines();actual=seen[path.name]
        if [actual[i] for i in range(1,len(expected)+1)]!=expected: raise ValueError(f"roundtrip mismatch {path.name}")
        total+=len(expected)
    return {"source_file_roundtrip_exact":True,"source_files_verified":30,"source_lines_verified":total}


def _build_candidate(root: Path) -> dict[str, bytes]:
    root=root.resolve();config=_load_config(root);acq=_validate_acquisition(root,config);tei,e=_render(root,config)
    counts={"books":27,"paratext_members":3,"chapters":e["chapter_count"],"verse_records":e["verse_count"],"source_lines":e["source_line_count"],"supplied_spans":e["inline_marker_counts"]["add"],"glossary_keyword_spans":e["inline_marker_counts"]["w"],"italics":e["inline_marker_counts"]["it"],"small_caps":e["inline_marker_counts"]["sc"]}
    receipt={"contract":"ocd-anderson-source-receipt-v1","resource_id":config["resource_id"],"source_commit":config["source_commit"],"retrieved_at_utc":config["retrieved_at_utc"],"authority":config["authority"],"sword":config["sword"],"witness":config["witness"],"rights":"public-domain","retained_file_count":acq["retained_file_count"],"retained_file_inventory_sha256":acq["retained_file_inventory_sha256"],"retained_files":acq["retained_files"],"unresolved":["The gate-specified print witness title page says 1865 while its copyright and dedication/preface identify 1864.","Human review must decide edition-expression acceptance."]}
    accountability={"contract":"ocd-anderson-accountability-v1","source_file_roundtrip_exact":True,"source_files_verified":30,"text_counts":counts,"member_ids":list(MEMBER_IDS),"line_marker_counts":e["line_marker_counts"],"inline_marker_counts":e["inline_marker_counts"],"tei_sha256":base._sha(tei),"tei_p5_valid":True,"candidate_status":"nonaccepted","canonical_data_or_ir_changed":False,"work_catalog_changed":False,"publication_ready":False}
    boundaries={"contract":"ocd-anderson-witness-boundaries-v1","structured_authority":"pinned GitHub USFM commit","comparison_source":"CrossWire Anderson 1.0.1","sword_is_transformation_authority":False,"comparison_source_note":"The retained CrossWire module is an independent public-domain comparison source; the exact pinned USFM commit is the transformation authority.","print_witness_title_year":"1865","print_witness_copyright_year":"1864","print_preliminaries_represented_in_usfm":True,"print_terminal_glossary_represented_in_usfm":True,"bibliographic_year_discrepancy_requires_human_review":True,"candidate_status":"nonaccepted"}
    validation={"contract":"ocd-anderson-validation-v1","status":"pass","tei_p5_valid":True,"source_file_roundtrip_exact":True,"authority_binding":"pass","sword_binding":"pass","witness_binding":"pass","candidate_status":"nonaccepted"}
    unresolved={"items":receipt["unresolved"],"held":["tickets 22-27"],"candidate_status":"nonaccepted"}
    readme=b"# Anderson 1864 New Testament ticket-21 candidate\n\nDeterministic nonaccepted TEI from the pinned public-domain USFM authority. Human acceptance and publication remain pending.\n"
    outputs={"README.md":readme,"content.tei.xml":tei,"source-accountability.json":base._canonical(accountability),"source-receipt.json":base._canonical(receipt),"unresolved.json":base._canonical(unresolved),"validation.json":base._canonical(validation),"witness-boundaries.json":base._canonical(boundaries)}
    manifest={"contract":"ocd-anderson-candidate-manifest-v1","candidate_id":"anderson-1864-new-testament-ticket-21","status":"nonaccepted","source_commit":config["source_commit"],"members":[{"name":n,"bytes":len(c),"sha256":base._sha(c)} for n,c in sorted(outputs.items())],"human_review_required":True,"publication_ready":False};outputs["manifest.json"]=base._canonical(manifest);return outputs


def write_candidate(root: Path,destination: Path)->dict[str,object]:
    if destination.exists() and any(destination.iterdir()):raise FileExistsError(destination)
    destination.mkdir(parents=True,exist_ok=True);outputs=_build_candidate(root)
    for name,content in outputs.items():(destination/name).write_bytes(content)
    return {"destination":str(destination),"members":[{"name":n,"bytes":len(c),"sha256":base._sha(c)} for n,c in sorted(outputs.items())]}


def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--repository-root",type=Path,default=Path(__file__).resolve().parents[2]);p.add_argument("--output-relative",default=DEFAULT_OUTPUT);a=p.parse_args();relative=str(a.output_relative).replace("\\","/")
    if not relative.startswith(OUTPUT_PREFIX) or ".." in Path(relative).parts:raise SystemExit("unsafe output")
    print(json.dumps(write_candidate(a.repository_root.resolve(),resolve_repo_path(a.repository_root.resolve(),relative)),sort_keys=True))


if __name__=="__main__":main()
