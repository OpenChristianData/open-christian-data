"""Independent validation oracle for the two City of God successor witnesses."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-city-of-god-independent-source-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
STANDARD_ROOT = "raw/standard_ebooks/augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith"
CCEL_PATH = "raw/ccel/npnf1/npnf102.xml"
PRINT_MANIFEST = "sources/city-of-god/print-acquisitions.json"
XML_SUFFIXES = {".opf", ".svg", ".xhtml", ".xml"}
CHUNK = 65_536


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _strict(data: bytes, label: str) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, value in pairs:
            if key in out: raise ValueError(f"{label} duplicate key")
            out[key] = value
        return out
    value = json.loads(data.decode(), object_pairs_hook=hook)
    if not isinstance(value, dict): raise ValueError(f"{label} is not an object")
    return value


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _address(node: etree._Element) -> str:
    segments = []
    while node is not None:
        name = _local(node)
        index = 1
        sibling = node.getprevious()
        while sibling is not None:
            if isinstance(sibling.tag, str) and _local(sibling) == name: index += 1
            sibling = sibling.getprevious()
        segments.insert(0, f"{name}[{index}]")
        node = node.getparent()
    return "/" + "/".join(segments)


def _atoms(prefix: str, logical: str, data: bytes) -> list[dict[str, object]]:
    document = etree.fromstring(data, etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False))
    result = []
    for node in document.iter():
        if not isinstance(node.tag, str):
            continue
        address = f"{prefix}:{logical}:{_address(node)}"
        result.append({"binding":address,"kind":"element","name":_local(node),"value":""})
        attrs = []
        for raw, value in node.attrib.items():
            q = etree.QName(raw)
            label = "xml:" + q.localname if q.namespace == "http://www.w3.org/XML/1998/namespace" else q.localname
            attrs.append((label, value))
        for label, value in sorted(attrs):
            result.append({"binding":address + "/@" + label,"kind":"attribute","name":label,"value":value})
        if node.text is not None: result.append({"binding":address+"/text()","kind":"text","name":"#text","value":node.text})
        if node.tail is not None: result.append({"binding":address+"/tail()","kind":"tail","name":"#tail","value":node.tail})
    return result


def _recount(repo: Path, profile: Mapping[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    root = (repo / STANDARD_ROOT).resolve(strict=True)
    scope = profile["standard_scope"]
    safe = f"safe.directory={root.as_posix()}"
    def git(*args: str) -> bytes:
        return subprocess.run(["git","-c",safe,"-C",str(root),*args],check=True,capture_output=True).stdout
    if git("rev-parse","--verify","HEAD").decode().strip() != scope["commit"] or git("rev-parse","--verify","HEAD^{tree}").decode().strip() != scope["tree"]:
        raise ValueError("retained Standard revision drifted")
    if git("status","--porcelain=v1","--untracked-files=all","-z"): raise ValueError("retained Standard checkout dirty")
    names = git("ls-files","-z").decode().rstrip("\0").split("\0")
    if names == [""]: names = []
    member_rows = []
    observations = []
    for name in names:
        data = (root / name).read_bytes()
        member_rows.append({"path":name,"bytes":len(data),"sha256":_sha(data)})
        observations.append({"binding":f"standard:{name}","kind":"file","name":name,"value":_sha(data),"disposition":"evidence-only"})
        if Path(name).suffix in XML_SUFFIXES:
            for atom in _atoms("standard", name, data):
                atom["disposition"] = "represented" if name.startswith("src/epub/text/book-") or name.endswith("preface.xhtml") else "evidence-only"
                observations.append(atom)
    if len(names) != 46 or sum(x["bytes"] for x in member_rows) != 10_910_503 or _sha(_canonical(member_rows)) != scope["member_set_sha256"] or len(observations) != 58_815:
        raise ValueError("Standard complete inventory mismatch")
    ccel_data = (repo / CCEL_PATH).read_bytes()
    ccel = [{"binding":f"ccel:{CCEL_PATH}","kind":"file","name":CCEL_PATH,"value":_sha(ccel_data),"disposition":"evidence-only"}]
    prefixes = ("/ThML[1]/ThML.body[1]/div1[4]", "/ThML[1]/ThML.body[1]/div1[3]")
    for atom in _atoms("ccel", CCEL_PATH, ccel_data):
        loc = str(atom["binding"]).split(f"ccel:{CCEL_PATH}:",1)[1]
        atom["disposition"] = "represented" if loc.startswith(prefixes) else "outside-city-evidence-only"
        ccel.append(atom)
    if len(ccel) != 88_276: raise ValueError("CCEL complete inventory mismatch")
    observations.extend(ccel)
    print_record = _strict((repo / PRINT_MANIFEST).read_bytes(), "print manifest")
    members=[]; chunks=[]
    for acq in print_record["acquisitions"]:
        for item in acq["members"]:
            data=(repo/item["path"]).read_bytes()
            if len(data)!=item["bytes"] or _sha(data)!=item["sha256"]: raise ValueError("print source drift")
            members.append({"path":item["path"],"bytes":len(data),"sha256":_sha(data)})
            offset=0
            while offset < len(data):
                piece=data[offset:offset+CHUNK]
                chunks.append({"path":item["path"],"offset":offset,"bytes":len(piece),"sha256":_sha(piece),"disposition":"evidence-only"})
                offset += len(piece)
    if len(members)!=15 or sum(x["bytes"] for x in members)!=237_821_801: raise ValueError("print inventory mismatch")
    return observations,{"standard_observation_count":58815,"ccel_observation_count":88276,"print_member_count":15,"print_bytes":237821801,"print_chunk_size":CHUNK,"print_chunk_count":len(chunks),"print_chunks_sha256":_sha(_canonical(chunks)),"print_members":members,"print_chunks":chunks}


def _header_projection(root: etree._Element) -> list[object]:
    header=root.find(f"{{{TEI}}}teiHeader")
    if header is None: raise ValueError("TEI header missing")
    return [{"tag":_local(n),"attrs":sorted((etree.QName(k).localname,v) for k,v in n.attrib.items()),"text":n.text or "","tail":n.tail or ""} for n in header.iter()]


def _expected_header_element(edition: str, profile: Mapping[str, object]) -> etree._Element:
    meta=profile["editions"][edition]
    h=etree.Element(f"{{{TEI}}}teiHeader")
    fd=etree.SubElement(h,f"{{{TEI}}}fileDesc"); ts=etree.SubElement(fd,f"{{{TEI}}}titleStmt")
    etree.SubElement(ts,f"{{{TEI}}}title").text=meta["title"]; etree.SubElement(ts,f"{{{TEI}}}author").text="Augustine of Hippo"
    for person in meta["contributors"]:
        rs=etree.SubElement(ts,f"{{{TEI}}}respStmt"); etree.SubElement(rs,f"{{{TEI}}}resp").text=person["role"]; etree.SubElement(rs,f"{{{TEI}}}name").text=person["name"]
    ps=etree.SubElement(fd,f"{{{TEI}}}publicationStmt"); etree.SubElement(ps,f"{{{TEI}}}publisher").text="Open Christian Data — nonaccepted candidate, not canonical or authorized for publication"
    av=etree.SubElement(ps,f"{{{TEI}}}availability",status="restricted")
    for p in profile["availability"]: etree.SubElement(av,f"{{{TEI}}}p").text=p
    sd=etree.SubElement(fd,f"{{{TEI}}}sourceDesc")
    for p in meta["source_description"]: etree.SubElement(sd,f"{{{TEI}}}p").text=p
    enc=etree.SubElement(h,f"{{{TEI}}}encodingDesc"); etree.SubElement(enc,f"{{{TEI}}}p").text="Direct deterministic projection retaining separate edition identity; print controls remain evidence, not silent master text."
    rev=etree.SubElement(h,f"{{{TEI}}}revisionDesc",status="candidate"); etree.SubElement(rev,f"{{{TEI}}}change",when="2026-08-25").text="Generated as a nonaccepted review candidate."
    return h


def _expected_header(edition: str, profile: Mapping[str, object]) -> list[object]:
    h = _expected_header_element(edition, profile)
    return [{"tag":_local(n),"attrs":sorted((etree.QName(k).localname,v) for k,v in n.attrib.items()),"text":n.text or "","tail":n.tail or ""} for n in h.iter()]


def _append_source_text(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _oracle_carrier(source: etree._Element, target: etree._Element) -> None:
    semantic = [v for v in (source.get("class") or "").split() if v in {"continued", "eoc"}]
    if semantic:
        target.set("rend", " ".join(([target.get("rend")] if target.get("rend") else []) + semantic))
    language = source.get(XML_LANG) or source.get("lang")
    if language:
        target.set(XML_LANG, language)


def _oracle_copy(source: etree._Element, target: etree._Element, notes: Mapping[str, etree._Element]) -> None:
    _append_source_text(target, source.text)
    for child in source:
        name = _local(child)
        output: etree._Element | None = None
        if name in {"header", "title"}:
            _oracle_copy(child, target, notes)
        elif name in {"h1", "h2", "h3", "h4", "h5", "h6", "head"}:
            output = etree.SubElement(target, f"{{{TEI}}}head")
        elif name in {"p", "argument"}:
            output = etree.SubElement(target, f"{{{TEI}}}p"); _oracle_carrier(child, output)
        elif name in {"blockquote", "quote"}:
            output = etree.SubElement(target, f"{{{TEI}}}quote")
        elif name in {"ul", "ol", "list"}:
            output = etree.SubElement(target, f"{{{TEI}}}list")
        elif name in {"li", "item"}:
            output = etree.SubElement(target, f"{{{TEI}}}item")
        elif name == "note" or (name == "a" and "noteref" in child.get(EPUB_TYPE, "")):
            output = etree.SubElement(target, f"{{{TEI}}}note", place="end")
            label = (child.get("n") or "") if name == "note" else "".join(child.itertext()).strip()
            if label: output.set("n", label)
            if name == "note":
                _oracle_copy(child, output, notes)
            else:
                target_id = (child.get("href") or "").rsplit("#", 1)[-1]
                if target_id not in notes: raise ValueError("oracle unresolved Standard note target")
                _oracle_copy(notes[target_id], output, notes)
        elif name == "pb":
            output = etree.SubElement(target, f"{{{TEI}}}pb")
            if child.get("n"): output.set("n", child.get("n"))
            if child.get("id"): output.set(XML_ID, child.get("id"))
        elif name == "br":
            etree.SubElement(target, f"{{{TEI}}}lb")
        elif name in {"i", "em", "b", "strong"}:
            output = etree.SubElement(target, f"{{{TEI}}}hi", rend="italic" if name in {"i", "em"} else "bold"); _oracle_carrier(child, output)
        elif name in {"a", "scripRef"}:
            output = etree.SubElement(target, f"{{{TEI}}}ref")
            ref = child.get("href") or child.get("passage") or child.get("target")
            if ref: output.set("target", ref)
        elif name in {"span", "time", "abbr", "foreign"}:
            output = etree.SubElement(target, f"{{{TEI}}}seg"); _oracle_carrier(child, output)
        else:
            _oracle_copy(child, target, notes)
        if output is not None and name not in {"note", "pb", "br"} and not (name == "a" and "noteref" in child.get(EPUB_TYPE, "")):
            _oracle_copy(child, output, notes)
        _append_source_text(target, child.tail)


def _oracle_standard_body(repo: Path) -> etree._Element:
    source_root = repo / STANDARD_ROOT / "src/epub/text"
    endnotes = etree.parse(str(source_root / "endnotes.xhtml"))
    notes = {n.get("id"): n for n in endnotes.xpath("//*[local-name()='li' and @id]")}
    if len(notes) != 1691: raise ValueError("oracle Standard endnote inventory drift")
    body = etree.Element(f"{{{TEI}}}body")
    front = etree.SubElement(body, f"{{{TEI}}}div", type="preface", n="editor")
    preface = etree.parse(str(source_root / "preface.xhtml"))
    _oracle_copy(preface.xpath("//*[local-name()='body']")[0], front, notes)
    parts = {i: etree.SubElement(body, f"{{{TEI}}}div", type="part", n=str(i)) for i in (1, 2)}
    chapter_count = preface_count = unit_count = 0
    for book_number in range(1, 23):
        parent = parts[1 if book_number <= 10 else 2]
        if book_number in {1, 14}:
            etree.SubElement(parent, f"{{{TEI}}}milestone", unit="physical-volume", n="1" if book_number == 1 else "2")
        tree = etree.parse(str(source_root / f"book-{book_number}.xhtml"))
        section = tree.xpath("//*[local-name()='body']/*[local-name()='section']")[0]
        book = etree.SubElement(parent, f"{{{TEI}}}div", type="book", n=str(book_number)); book.set(XML_ID, f"dods-book-{book_number}")
        header = section.find("{*}header")
        if header is not None: _oracle_copy(header, book, notes)
        for source_unit in section.findall("{*}section"):
            source_unit = etree.fromstring(etree.tostring(source_unit))
            role = "preface" if "preface" in source_unit.get(EPUB_TYPE, "") else "chapter"
            if role == "preface": preface_count += 1; number = preface_count
            else: chapter_count += 1; number = chapter_count
            unit_count += 1
            unit = etree.SubElement(book, f"{{{TEI}}}div", type=role, n=str(number))
            if source_unit.get("id"): unit.set(XML_ID, "dods-" + source_unit.get("id"))
            _oracle_copy(source_unit, unit, notes)
    if (unit_count, chapter_count, preface_count) != (665, 661, 4): raise ValueError("oracle Standard unit drift")
    return body


def _oracle_ccel_body(repo: Path) -> etree._Element:
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    tree = etree.parse(str(repo / CCEL_PATH), parser); notes: dict[str, etree._Element] = {}
    body = etree.Element(f"{{{TEI}}}body")
    editor = tree.xpath("//*[local-name()='div1' and @id='iii']")[0]
    front = etree.SubElement(body, f"{{{TEI}}}div", type="preface", n="series-editor"); _oracle_copy(editor, front, notes)
    city = tree.xpath("//*[local-name()='div1' and @id='iv']")[0]
    titlepage = etree.SubElement(body, f"{{{TEI}}}div", type="titlepage", n="city-source-front")
    for child in city:
        if _local(child) != "div2":
            wrapper = etree.Element("wrapper"); wrapper.append(etree.fromstring(etree.tostring(child))); _oracle_copy(wrapper, titlepage, notes)
    translator = city.xpath("./*[local-name()='div2' and @id='iv.i']")[0]
    trans = etree.SubElement(body, f"{{{TEI}}}div", type="preface", n="translator"); _oracle_copy(translator, trans, notes)
    etree.SubElement(body, f"{{{TEI}}}milestone", unit="physical-volume", n="2")
    parts = {i: etree.SubElement(body, f"{{{TEI}}}div", type="part", n=str(i)) for i in (1, 2)}
    chapters = prefaces = 0
    books = city.xpath("./*[local-name()='div2' and @type='Book']")
    for book_number, source_book in enumerate(books, 1):
        book = etree.SubElement(parts[1 if book_number <= 10 else 2], f"{{{TEI}}}div", type="book", n=str(book_number)); book.set(XML_ID, f"npnf-book-{book_number}")
        if source_book.get("title"): etree.SubElement(book, f"{{{TEI}}}head").text = source_book.get("title").strip()
        for child in source_book:
            if _local(child) != "div3":
                wrapper = etree.Element("wrapper"); wrapper.append(etree.fromstring(etree.tostring(child))); _oracle_copy(wrapper, book, notes)
        for index, source_unit in enumerate(source_book.xpath("./*[local-name()='div3']"), 1):
            source_unit = etree.fromstring(etree.tostring(source_unit))
            role = "preface" if index == 1 and " ".join((source_unit.get("title") or "").split()).lower().startswith("preface") else "chapter"
            if role == "preface": prefaces += 1
            else: chapters += 1
            unit = etree.SubElement(book, f"{{{TEI}}}div", type=role, n=str(index))
            if source_unit.get("id"): unit.set(XML_ID, "npnf-" + source_unit.get("id").replace(".", "-"))
            _oracle_copy(source_unit, unit, notes)
    if (len(books), chapters, prefaces) != (22, 661, 4): raise ValueError("oracle CCEL unit drift")
    return body


def _expected_tei(repo: Path, edition: str, profile: Mapping[str, object]) -> etree._Element:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI}); root.set(XML_ID, "city-of-god-" + edition)
    root.append(_expected_header_element(edition, profile))
    text = etree.SubElement(root, f"{{{TEI}}}text"); text.set(XML_LANG, "en")
    text.append(_oracle_standard_body(repo) if edition == "dods-1871" else _oracle_ccel_body(repo))
    return root


def _recursive_projection(root: etree._Element) -> list[dict[str, object]]:
    projection: list[dict[str, object]] = []
    def visit(node: etree._Element, path: tuple[int, ...]) -> None:
        projection.append({"path": list(path), "qname": node.tag, "attributes": sorted(node.attrib.items()), "text": node.text, "tail": node.tail, "child_count": len(node)})
        for index, child in enumerate(node): visit(child, path + (index,))
    visit(root, ())
    return projection


def _body_checks(root: etree._Element, edition: str, repo: Path) -> None:
    body=root.find(f".//{{{TEI}}}body")
    if body is None: raise ValueError("TEI body missing")
    books=body.xpath(".//tei:div[@type='book']",namespaces={"tei":TEI})
    chapters=body.xpath(".//tei:div[@type='chapter']",namespaces={"tei":TEI})
    prefaces=body.xpath(".//tei:div[@type='preface']",namespaces={"tei":TEI})
    parts=body.xpath("./tei:div[@type='part']",namespaces={"tei":TEI})
    milestones=body.xpath(".//tei:milestone[@unit='physical-volume']",namespaces={"tei":TEI})
    expected_prefaces=5 if edition=="dods-1871" else 6
    if (len(books),len(chapters),len(prefaces),len(parts))!=(22,661,expected_prefaces,2): raise ValueError("book/chapter/preface/part hierarchy drifted")
    if [b.get("n") for b in books] != [str(i) for i in range(1,23)]: raise ValueError("book identity/order drifted")
    if [p.get("n") for p in parts] != ["1","2"]: raise ValueError("conceptual part identity drifted")
    if [m.get("n") for m in milestones] != (["1","2"] if edition=="dods-1871" else ["2"]): raise ValueError("physical volume identity drifted")
    if edition=="dods-1871":
        if milestones[0].getparent() is not parts[0] or milestones[0].getnext() is not books[0]: raise ValueError("volume I attachment drifted")
        if milestones[1].getparent() is not parts[1] or milestones[1].getnext() is not books[13]: raise ValueError("volume II attachment drifted")
        text=" ".join("".join(body.itertext()).split())
        chapter=body.xpath(".//tei:div[@xml:id='dods-chapter-17-16']",namespaces={"tei":TEI,"xml":"http://www.w3.org/XML/1998/namespace"})
        chapter_text=" ".join("".join(chapter[0].itertext()).split()) if len(chapter)==1 else ""
        source_chapter = etree.parse(str(repo / STANDARD_ROOT / "src/epub/text/book-17.xhtml")).xpath("//*[@id='chapter-17-16']")[0]
        source_text = " ".join("".join(source_chapter.itertext()).split())
        if source_text.count("Zion") != 2 or "Sion" in source_text: raise ValueError("Dods electronic source reading drifted")
        if chapter_text.count("Zion") != 2 or "Sion" in chapter_text: raise ValueError("Dods electronic reading was changed")
        if len(body.xpath(".//*[@rend and contains(concat(' ',normalize-space(@rend),' '),' continued ')]")) != 16: raise ValueError("continued carrier attachment drifted")
        if len(body.xpath(".//*[@rend and contains(concat(' ',normalize-space(@rend),' '),' eoc ')]")) != 32: raise ValueError("projected eoc carrier attachment drifted")
        expected_continued=[]
        for filename in ["preface.xhtml", *[f"book-{i}.xhtml" for i in range(1,23)]]:
            tree=etree.parse(str(repo/STANDARD_ROOT/"src/epub/text"/filename))
            for carrier in tree.xpath("//*[contains(concat(' ',normalize-space(@class),' '),' continued ')]"):
                section=carrier.xpath("ancestor::*[local-name()='section' and @id][1]")[0]
                peers=section.xpath(".//*[local-name()='p']")
                expected_continued.append(("dods-"+section.get("id"),_local(carrier),peers.index(carrier)))
        observed_continued=[]
        for carrier in body.xpath(".//*[@rend and contains(concat(' ',normalize-space(@rend),' '),' continued ')]"):
            if carrier.xpath("ancestor::tei:note",namespaces={"tei":TEI}):
                continue
            divisions=carrier.xpath("ancestor::tei:div[@xml:id][1]",namespaces={"tei":TEI,"xml":"http://www.w3.org/XML/1998/namespace"})
            if len(divisions)!=1: raise ValueError("continued carrier escaped its source division")
            division=divisions[0]
            peers=division.xpath(".//tei:p[not(ancestor::tei:note)]",namespaces={"tei":TEI})
            observed_continued.append((division.get(XML_ID),_local(carrier),peers.index(carrier)))
        if observed_continued != expected_continued: raise ValueError("continued carrier exact attachment drifted")
        if "Philip Schaff" in text: raise ValueError("Schaff preface leaked into Dods edition")
    else:
        if milestones[0].getparent() is not body: raise ValueError("NPNF physical-volume attachment drifted")
        series=body.xpath("./tei:div[@type='preface' and @n='series-editor']",namespaces={"tei":TEI})
        if len(series)!=1 or not "".join(series[0].itertext()).strip(): raise ValueError("Schaff series-editor preface lost or merged")
        source = etree.parse(str(repo / CCEL_PATH), etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False))
        source_chapter = source.xpath("//*[local-name()='div1' and @id='iv']//*[local-name()='div2' and @type='Book'][10]//*[local-name()='div3'][2]")[0]
        chapter = body.xpath(".//tei:div[@xml:id='npnf-iv-X-2']", namespaces={"tei": TEI, "xml": "http://www.w3.org/XML/1998/namespace"})
        source_text = " ".join("".join(source_chapter.itertext()).split())
        chapter_text = " ".join("".join(chapter[0].itertext()).split()) if len(chapter) == 1 else ""
        phrase = "their blessed life, and the light of truth"
        if source_text.count(phrase) != 2: raise ValueError("CCEL X.2 electronic source reading drifted")
        if chapter_text.count(phrase) != 2: raise ValueError("CCEL X.2 duplicated electronic reading was changed")
    allowed={"body","div","milestone","head","p","quote","list","item","note","pb","lb","hi","ref","seg"}
    if any(_local(n) not in allowed for n in body.iter()): raise ValueError("invented body carrier")
    if any(n.get("type") not in {"preface","titlepage","part","book","chapter"} for n in body.iter(f"{{{TEI}}}div")): raise ValueError("invented or cross-edition division")
    candidate_notes=[n.get("n") for n in body.iter(f"{{{TEI}}}note")]
    candidate_pages=[n.get("n") for n in body.iter(f"{{{TEI}}}pb")]
    if edition=="dods-1871":
        source_root=repo/STANDARD_ROOT/"src/epub/text"
        expected_notes=[]
        for filename in ["preface.xhtml", *[f"book-{i}.xhtml" for i in range(1,23)]]:
            tree=etree.parse(str(source_root/filename))
            expected_notes.extend("".join(a.itertext()).strip() for a in tree.xpath("//*[local-name()='a' and contains(@*[local-name()='type'],'noteref')]") )
        if candidate_notes != expected_notes or candidate_pages: raise ValueError("Dods note/page occurrence attachment drifted")
    else:
        source=etree.parse(str(repo/CCEL_PATH),etree.XMLParser(load_dtd=False,no_network=True,resolve_entities=False))
        editor=source.xpath("//*[local-name()='div1' and @id='iii']")[0]; city=source.xpath("//*[local-name()='div1' and @id='iv']")[0]
        expected_notes=[n.get("n") for scope in (editor,city) for n in scope.iter("note")]
        expected_pages=[n.get("n") for scope in (editor,city) for n in scope.iter("pb")]
        if candidate_notes != expected_notes or candidate_pages != expected_pages: raise ValueError("NPNF note/page occurrence attachment drifted")


def _module_target(repo: Path, name: str) -> Path | None:
    stem = repo.joinpath(*name.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file(): return candidate.resolve(strict=True)
    return None


def _reject_dynamic_execution(tree: ast.AST) -> None:
    """Reject dynamic-code mechanisms that have no place in this fixed oracle graph."""

    direct = {"__import__", "compile", "eval", "exec"}
    attributes = {"exec_module", "import_module", "load_module"}
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "importlib":
                aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "import_module")
            elif node.module == "builtins":
                aliases.update(alias.asname or alias.name for alias in node.names if alias.name in direct)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id in direct | aliases:
            raise ValueError(f"dynamic execution is forbidden in oracle closure: {function.id}")
        if isinstance(function, ast.Attribute) and function.attr in direct | attributes:
            category = "execution" if function.attr in direct else "import"
            raise ValueError(
                f"dynamic {category} is forbidden in oracle closure: {function.attr}"
            )
        if (
            isinstance(function, ast.Call)
            and isinstance(function.func, ast.Name)
            and function.func.id == "getattr"
            and len(function.args) >= 2
            and isinstance(function.args[1], ast.Constant)
            and function.args[1].value in direct | attributes
        ):
            raise ValueError("dynamic getattr execution is forbidden in oracle closure")


def _static_closure(repo: Path, entry: Path, forbidden: tuple[str, ...]) -> tuple[str,list[dict[str,object]]]:
    pending=[entry.resolve(strict=True)]; seen:set[Path]=set()
    while pending:
        path=pending.pop(0)
        if path in seen: continue
        path.relative_to(repo); seen.add(path)
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        _reject_dynamic_execution(tree)
        for node in ast.walk(tree):
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else ([node.module] if isinstance(node,ast.ImportFrom) and node.level==0 and node.module else [])
            for name in names:
                if any(name==prefix or name.startswith(prefix+".") for prefix in forbidden): raise ValueError(f"forbidden runtime import {name}")
                target=_module_target(repo,name)
                if target is not None and target not in seen: pending.append(target)
    rows=[{"path":p.relative_to(repo).as_posix(),"bytes":p.stat().st_size,"sha256":_sha(p.read_bytes())} for p in sorted(seen,key=lambda p:p.relative_to(repo).as_posix())]
    return _sha(_canonical(rows)),rows


def _closure(repo: Path, forbidden: tuple[str, ...]) -> tuple[str,list[dict[str,object]]]:
    here=Path(__file__).resolve(strict=True); expected=(repo/"build/tei/city_of_god_oracle_electronic_v2.py").resolve(strict=True)
    contract=(repo/"ocd_kernel/reconstruction/contract.py").resolve(strict=True)
    loaded_manifest=Path(inspect.getsourcefile(SourceManifest) or "").resolve(strict=True)
    loaded_candidate=Path(inspect.getsourcefile(CandidatePackage) or "").resolve(strict=True)
    callable_source=Path(inspect.getsourcefile(_oracle) or "").resolve(strict=True)
    if not here.samefile(expected) or not callable_source.samefile(here) or not loaded_manifest.samefile(contract) or not loaded_candidate.samefile(contract): raise ValueError("runtime editable or site-package shadow")
    for name,module in tuple(sys.modules.items()):
        if name in {"build.tei.city_of_god_oracle_electronic_v2","ocd_kernel.reconstruction.contract"} and getattr(module,"__file__",None):
            target=_module_target(repo,name)
            if target is None or not Path(module.__file__).resolve(strict=True).samefile(target): raise ValueError(f"runtime module shadow: {name}")
    return _static_closure(repo,here,forbidden)


def _enforce_forbidden_claims(candidate: CandidatePackage, claims: tuple[str, ...]) -> None:
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), etree.XMLParser(load_dtd=False,no_network=True,resolve_entities=False))
    header = tei.find(f"{{{TEI}}}teiHeader")
    if header is None: raise ValueError("TEI header missing for claim policy")
    surfaces = b"\n".join((etree.tostring(header),candidate.member_bytes("README.source.md"))).decode("utf-8").casefold()
    for claim in claims:
        needle=claim.casefold()
        if needle=="accepted":
            if re.search(r"(?<!non)\baccepted\b",surfaces): raise ValueError("forbidden accepted claim")
        elif needle=="canonical":
            if re.search(r"(?<!not )\bcanonical\b",surfaces): raise ValueError("forbidden canonical claim")
        elif needle in surfaces:
            raise ValueError(f"forbidden candidate claim: {claim}")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    repo=source_manifest.repository_root; edition=str(source_manifest.record["edition"])
    profile_bytes=source_manifest.authority_path("reconstruction-profile").read_bytes(); profile=_strict(profile_bytes,"profile")
    policy_bytes=source_manifest.authority_path("validation-policy").read_bytes(); policy=_strict(policy_bytes,"policy")
    forbidden_imports=tuple(str(v) for v in policy["forbidden_runtime_import_prefixes"])
    forbidden_claims=tuple(str(v) for v in policy["forbidden_claims"])
    _enforce_forbidden_claims(candidate,forbidden_claims)
    account=_strict(candidate.member_bytes("source-accountability.json"),"accountability")
    observations, print_inventory=_recount(repo,profile)
    expected={"contract":"ocd-city-of-god-source-accountability-v1","edition":edition,"standard_observation_count":58815,"ccel_observation_count":88276,"observations_sha256":_sha(_canonical(observations)),"observations":observations,"print_inventory":print_inventory,"semantic_units":{"books":22,"chapters":661,"prefaces":4,"aligned_units":665},"variants":{"lexical":1533,"orthographic":2390},"print_decisions":profile["print_decisions"],"crop_evidence":profile["crop_evidence"],"semantic_defects":profile["semantic_defects"],"omitted_count":0}
    if account != expected: raise ValueError("source accountability, disposition, or print inventory drifted")
    schema=_strict(source_manifest.authority_path("source-accountability-schema").read_bytes(),"accountability schema")
    errors=list(Draft202012Validator(schema).iter_errors(account))
    if errors: raise ValueError("source accountability schema failure: "+errors[0].message)
    parser=etree.XMLParser(load_dtd=False,no_network=True,resolve_entities=False); root=etree.fromstring(candidate.member_bytes("content.tei.xml"),parser)
    xsd_path=source_manifest.authority_path("tei-p5-xsd"); xsd=etree.XMLSchema(etree.parse(str(xsd_path),parser))
    if not xsd.validate(root): raise ValueError("TEI P5 XSD failure: "+str(xsd.error_log.last_error))
    if root.get(XML_ID)!="city-of-god-"+edition or _header_projection(root)!=_expected_header(edition,profile): raise ValueError("complete TEI identity/header/availability drifted")
    expected_root = _expected_tei(repo, edition, profile)
    if _recursive_projection(root) != _recursive_projection(expected_root):
        raise ValueError("complete recursive TEI projection drifted")
    _body_checks(root,edition,repo)
    unresolved=b"".join(_canonical(item) for item in profile["unresolved"])
    if candidate.member_bytes("unresolved.jsonl")!=unresolved: raise ValueError("unresolved claim inventory drifted")
    readme=str(profile["readme"]).replace("{EDITION}",edition).encode()
    if candidate.member_bytes("README.source.md")!=readme: raise ValueError("complete README drifted")
    prov=_strict(candidate.member_bytes("provenance.json"),"provenance")
    closure_sha,_=_closure(repo,forbidden_imports)
    converter=source_manifest.record["converter"]
    producer_path=(repo/str(converter["implementation_path"])).resolve(strict=True)
    producer_closure_sha,producer_closure=_static_closure(repo,producer_path,forbidden_imports)
    expected_provenance={"contract":"ocd-city-of-god-provenance-v1","status":"nonaccepted","edition":edition,"source_manifest_sha256":source_manifest.sha256,"producer_closure_sha256":producer_closure_sha,"producer_closure":producer_closure,"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})","authority":{"profile_sha256":_sha(_canonical(profile)),"policy_sha256":_sha(_canonical(policy))}}
    if prov != expected_provenance: raise ValueError("complete provenance, closure, or nonacceptance drifted")
    source_records=sorted(({"name":x["name"],"path":x["path"],"bytes":x["bytes"],"sha256":x["sha256"]} for x in source_manifest.record["authorities"] if x["role"]=="primary-source"),key=lambda x:(str(x["path"]),str(x["name"])))
    source_sha=source_records[0]["sha256"] if len(source_records)==1 else _sha(_canonical({"contract":"ocd-source-member-set-v1","members":source_records}))
    result={"status":"pass","oracle_id":ORACLE_ID,"oracle_version":ORACLE_VERSION,"implementation_sha256":_sha(Path(__file__).read_bytes()),"import_closure_sha256":closure_sha,"runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})","source_manifest_sha256":source_manifest.sha256,"candidate_sha256":candidate.sha256,"profile_sha256":_sha(profile_bytes),"package_schema_sha256":_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),"source_sha256":source_sha,"xsd_sha256":_sha(xsd_path.read_bytes()),"policy_sha256":_sha(policy_bytes),"findings":[]}
    result["result_sha256"]=_sha(_canonical(result)); return result


_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()

__all__: tuple[str,...]=()
