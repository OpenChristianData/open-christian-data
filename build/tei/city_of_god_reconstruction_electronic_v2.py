"""Direct City of God retained witnesses to separately identified TEI candidates."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
CONVERTER_ID = "ocd-city-of-god-direct-witness-to-tei"
CONVERTER_VERSION = "1"
STANDARD_ROOT = "raw/standard_ebooks/augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith"
CCEL_PATH = "raw/ccel/npnf1/npnf102.xml"
PRINT_MANIFEST = "sources/city-of-god/print-acquisitions.json"
XML_SUFFIXES = {".opf", ".svg", ".xhtml", ".xml"}
CHUNK = 65_536
_NOTE_TARGETS: dict[str, etree._Element] = {}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not an object")
    return value


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), *args],
        check=True, capture_output=True,
    ).stdout


def _standard_members(repo: Path, profile: Mapping[str, object]) -> list[tuple[str, Path, bytes]]:
    root = (repo / STANDARD_ROOT).resolve(strict=True)
    scope = profile["standard_scope"]
    assert isinstance(scope, dict)
    if _git(root, "rev-parse", "--verify", "HEAD").decode().strip() != scope["commit"]:
        raise ValueError("Standard Ebooks retained commit drifted")
    if _git(root, "rev-parse", "--verify", "HEAD^{tree}").decode().strip() != scope["tree"]:
        raise ValueError("Standard Ebooks retained tree drifted")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z"):
        raise ValueError("Standard Ebooks retained checkout is not clean")
    raw = _git(root, "ls-files", "-z").decode().rstrip("\0")
    names = raw.split("\0") if raw else []
    rows = [(name, root / name, (root / name).read_bytes()) for name in names]
    member_set = [{"path": n, "bytes": len(b), "sha256": _sha(b)} for n, _, b in rows]
    if len(rows) != 46 or sum(len(b) for _, _, b in rows) != 10_910_503:
        raise ValueError("Standard Ebooks retained member count or bytes drifted")
    if _sha(_canonical(member_set)) != scope["member_set_sha256"]:
        raise ValueError("Standard Ebooks retained member set drifted")
    return rows


def _node_address(node: etree._Element) -> str:
    pieces: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        name = _local(current)
        prior = sum(1 for sib in current.itersiblings(preceding=True) if isinstance(sib.tag, str) and _local(sib) == name)
        pieces.append(f"{name}[{prior + 1}]")
        current = current.getparent()
    return "/" + "/".join(reversed(pieces))


def _xml_observations(prefix: str, logical: str, data: bytes) -> list[dict[str, object]]:
    root = etree.fromstring(data, etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False))
    out: list[dict[str, object]] = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        address = f"{prefix}:{logical}:{_node_address(node)}"
        out.append({"binding": address, "kind": "element", "name": _local(node), "value": ""})
        attributes = []
        for key, value in node.attrib.items():
            q = etree.QName(key)
            name = ("xml:" + q.localname) if q.namespace == "http://www.w3.org/XML/1998/namespace" else q.localname
            attributes.append((name, value))
        for name, value in sorted(attributes):
            out.append({"binding": address + "/@" + name, "kind": "attribute", "name": name, "value": value})
        if node.text is not None:
            out.append({"binding": address + "/text()", "kind": "text", "name": "#text", "value": node.text})
        if node.tail is not None:
            out.append({"binding": address + "/tail()", "kind": "tail", "name": "#tail", "value": node.tail})
    return out


def _source_inventory(repo: Path, profile: Mapping[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    standard = _standard_members(repo, profile)
    observations: list[dict[str, object]] = []
    for logical, _, data in standard:
        observations.append({"binding": f"standard:{logical}", "kind": "file", "name": logical, "value": _sha(data), "disposition": "evidence-only"})
        if Path(logical).suffix in XML_SUFFIXES:
            for atom in _xml_observations("standard", logical, data):
                atom["disposition"] = "represented" if logical.startswith("src/epub/text/book-") or logical.endswith("preface.xhtml") else "evidence-only"
                observations.append(atom)
    if len(observations) != 58_815:
        raise ValueError(f"Standard observation drift: {len(observations)}")

    ccel_data = (repo / CCEL_PATH).read_bytes()
    ccel = [{"binding": f"ccel:{CCEL_PATH}", "kind": "file", "name": CCEL_PATH, "value": _sha(ccel_data), "disposition": "evidence-only"}]
    city_prefixes = ("/ThML[1]/ThML.body[1]/div1[4]", "/ThML[1]/ThML.body[1]/div1[3]")
    for atom in _xml_observations("ccel", CCEL_PATH, ccel_data):
        location = str(atom["binding"]).split(f"ccel:{CCEL_PATH}:", 1)[1]
        atom["disposition"] = "represented" if location.startswith(city_prefixes) else "outside-city-evidence-only"
        ccel.append(atom)
    if len(ccel) != 88_276:
        raise ValueError(f"CCEL observation drift: {len(ccel)}")
    observations.extend(ccel)

    print_manifest = _load(repo / PRINT_MANIFEST)
    print_members: list[dict[str, object]] = []
    chunk_records: list[dict[str, object]] = []
    for acquisition in print_manifest["acquisitions"]:
        for member in acquisition["members"]:
            path = repo / member["path"]
            data = path.read_bytes()
            if len(data) != member["bytes"] or _sha(data) != member["sha256"]:
                raise ValueError(f"print authority drifted: {member['path']}")
            print_members.append({"path": member["path"], "bytes": len(data), "sha256": _sha(data)})
            for offset in range(0, len(data), CHUNK):
                part = data[offset:offset + CHUNK]
                chunk_records.append({"path": member["path"], "offset": offset, "bytes": len(part), "sha256": _sha(part), "disposition": "evidence-only"})
    if len(print_members) != 15 or sum(x["bytes"] for x in print_members) != 237_821_801:
        raise ValueError("print member inventory drifted")
    summary = {
        "standard_observation_count": 58_815,
        "ccel_observation_count": 88_276,
        "print_member_count": 15,
        "print_bytes": 237_821_801,
        "print_chunk_size": CHUNK,
        "print_chunk_count": len(chunk_records),
        "print_chunks_sha256": _sha(_canonical(chunk_records)),
        "observations_sha256": _sha(_canonical(observations)),
        "print_members": print_members,
        "print_chunks": chunk_records,
    }
    return observations, summary


def _set_text(target: etree._Element, text: str | None) -> None:
    if text:
        target.text = text


def _append_text(parent: etree._Element, text: str | None) -> None:
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _carrier(source: etree._Element, target: etree._Element) -> None:
    classes = (source.get("class") or "").split()
    semantic = [value for value in classes if value in {"continued", "eoc"}]
    if semantic:
        target.set("rend", " ".join(([target.get("rend")] if target.get("rend") else []) + semantic))
    lang = source.get(XML_LANG) or source.get("lang")
    if lang:
        target.set(XML_LANG, lang)


def _copy_content(source: etree._Element, target: etree._Element) -> None:
    _append_text(target, source.text)
    for child in source:
        name = _local(child)
        if name in {"header", "title"}:
            _copy_content(child, target)
        elif name in {"h1", "h2", "h3", "h4", "h5", "h6", "head"}:
            out = etree.SubElement(target, f"{{{TEI}}}head")
            _copy_content(child, out)
        elif name in {"p", "argument"}:
            out = etree.SubElement(target, f"{{{TEI}}}p")
            _carrier(child, out)
            _copy_content(child, out)
        elif name in {"blockquote", "quote"}:
            out = etree.SubElement(target, f"{{{TEI}}}quote")
            _copy_content(child, out)
        elif name in {"ul", "ol", "list"}:
            out = etree.SubElement(target, f"{{{TEI}}}list")
            _copy_content(child, out)
        elif name in {"li", "item"}:
            out = etree.SubElement(target, f"{{{TEI}}}item")
            _copy_content(child, out)
        elif name in {"note"} or (name == "a" and "noteref" in child.get(EPUB_TYPE, "")):
            out = etree.SubElement(target, f"{{{TEI}}}note", place="end")
            label = (child.get("n") or "") if name == "note" else "".join(child.itertext()).strip()
            if label:
                out.set("n", label)
            if name == "note":
                _copy_content(child, out)
            else:
                href = child.get("href") or ""
                target_id = href.rsplit("#", 1)[-1]
                source_note = _NOTE_TARGETS.get(target_id)
                if source_note is None:
                    raise ValueError(f"unresolved Standard note target {target_id}")
                _copy_content(source_note, out)
        elif name == "pb":
            out = etree.SubElement(target, f"{{{TEI}}}pb")
            for key in ("n", "id"):
                if child.get(key): out.set("n" if key == "n" else XML_ID, child.get(key))
        elif name == "br":
            etree.SubElement(target, f"{{{TEI}}}lb")
        elif name in {"i", "em", "b", "strong"}:
            out = etree.SubElement(target, f"{{{TEI}}}hi", rend="italic" if name in {"i", "em"} else "bold")
            _carrier(child, out)
            _copy_content(child, out)
        elif name in {"a", "scripRef"}:
            out = etree.SubElement(target, f"{{{TEI}}}ref")
            href = child.get("href") or child.get("passage") or child.get("target")
            if href: out.set("target", href)
            _copy_content(child, out)
        elif name in {"span", "time", "abbr", "foreign"}:
            out = etree.SubElement(target, f"{{{TEI}}}seg")
            _carrier(child, out)
            _copy_content(child, out)
        else:
            _copy_content(child, target)
        _append_text(target, child.tail)


def _header(edition: str, profile: Mapping[str, object]) -> etree._Element:
    meta = profile["editions"][edition]
    header = etree.Element(f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = str(meta["title"])
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Augustine of Hippo"
    for person in meta["contributors"]:
        node = etree.SubElement(title_stmt, f"{{{TEI}}}respStmt")
        etree.SubElement(node, f"{{{TEI}}}resp").text = person["role"]
        etree.SubElement(node, f"{{{TEI}}}name").text = person["name"]
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}publisher").text = "Open Christian Data — nonaccepted candidate, not canonical or authorized for publication"
    availability = etree.SubElement(publication, f"{{{TEI}}}availability", status="restricted")
    for paragraph in profile["availability"]:
        etree.SubElement(availability, f"{{{TEI}}}p").text = paragraph
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    for paragraph in meta["source_description"]:
        etree.SubElement(source_desc, f"{{{TEI}}}p").text = paragraph
    encoding = etree.SubElement(header, f"{{{TEI}}}encodingDesc")
    etree.SubElement(encoding, f"{{{TEI}}}p").text = "Direct deterministic projection retaining separate edition identity; print controls remain evidence, not silent master text."
    revision = etree.SubElement(header, f"{{{TEI}}}revisionDesc", status="candidate")
    etree.SubElement(revision, f"{{{TEI}}}change", when="2026-08-25").text = "Generated as a nonaccepted review candidate."
    return header


def _standard_body(repo: Path, profile: Mapping[str, object]) -> etree._Element:
    root = repo / STANDARD_ROOT / "src/epub/text"
    endnotes = etree.parse(str(root / "endnotes.xhtml"))
    _NOTE_TARGETS.clear()
    _NOTE_TARGETS.update({node.get("id"): node for node in endnotes.xpath("//*[local-name()='li' and @id]")})
    if len(_NOTE_TARGETS) != 1691:
        raise ValueError("Standard endnote target inventory drifted")
    body = etree.Element(f"{{{TEI}}}body")
    front = etree.SubElement(body, f"{{{TEI}}}div", type="preface", n="editor")
    preface = etree.parse(str(root / "preface.xhtml")).getroot()
    _copy_content(preface.xpath("//*[local-name()='body']")[0], front)
    parts = {1: etree.SubElement(body, f"{{{TEI}}}div", type="part", n="1"), 2: etree.SubElement(body, f"{{{TEI}}}div", type="part", n="2")}
    units = 0
    chapters = 0
    prefaces = 0
    for book_no in range(1, 23):
        parent = parts[1 if book_no <= 10 else 2]
        if book_no in {1, 14}:
            etree.SubElement(parent, f"{{{TEI}}}milestone", unit="physical-volume", n="1" if book_no == 1 else "2")
        source = etree.parse(str(root / f"book-{book_no}.xhtml")).getroot()
        section = source.xpath("//*[local-name()='body']/*[local-name()='section']")[0]
        book = etree.SubElement(parent, f"{{{TEI}}}div", type="book", n=str(book_no))
        book.set(XML_ID, f"dods-book-{book_no}")
        header = section.find("{*}header")
        if header is not None: _copy_content(header, book)
        for unit in section.findall("{*}section"):
            typ = "preface" if "preface" in unit.get(EPUB_TYPE, "") else "chapter"
            if typ == "preface": prefaces += 1
            else: chapters += 1
            units += 1
            unit = etree.fromstring(etree.tostring(unit))
            div = etree.SubElement(book, f"{{{TEI}}}div", type=typ, n=str(prefaces if typ == "preface" else chapters))
            source_id = unit.get("id")
            if source_id: div.set(XML_ID, "dods-" + source_id)
            _copy_content(unit, div)
    if (units, chapters, prefaces) != (665, 661, 4):
        raise ValueError(f"Standard semantic unit drift: {(units, chapters, prefaces)}")
    return body


def _ccel_body(repo: Path) -> etree._Element:
    source = etree.parse(str(repo / CCEL_PATH), etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False))
    body = etree.Element(f"{{{TEI}}}body")
    editor = source.xpath("//*[local-name()='div1' and @id='iii']")[0]
    front = etree.SubElement(body, f"{{{TEI}}}div", type="preface", n="series-editor")
    _copy_content(editor, front)
    city = source.xpath("//*[local-name()='div1' and @id='iv']")[0]
    titlepage = etree.SubElement(body, f"{{{TEI}}}div", type="titlepage", n="city-source-front")
    for child in city:
        if _local(child) != "div2":
            wrapper = etree.Element("wrapper")
            wrapper.append(etree.fromstring(etree.tostring(child)))
            _copy_content(wrapper, titlepage)
    translator = city.xpath("./*[local-name()='div2' and @id='iv.i']")[0]
    trans = etree.SubElement(body, f"{{{TEI}}}div", type="preface", n="translator")
    _copy_content(translator, trans)
    etree.SubElement(body, f"{{{TEI}}}milestone", unit="physical-volume", n="2")
    parts = {1: etree.SubElement(body, f"{{{TEI}}}div", type="part", n="1"), 2: etree.SubElement(body, f"{{{TEI}}}div", type="part", n="2")}
    books = city.xpath("./*[local-name()='div2' and @type='Book']")
    chapters = prefaces = 0
    for book_no, source_book in enumerate(books, 1):
        book = etree.SubElement(parts[1 if book_no <= 10 else 2], f"{{{TEI}}}div", type="book", n=str(book_no))
        book.set(XML_ID, f"npnf-book-{book_no}")
        if source_book.get("title"):
            etree.SubElement(book, f"{{{TEI}}}head").text = source_book.get("title").strip()
        for child in source_book:
            if _local(child) != "div3":
                wrapper = etree.Element("wrapper")
                wrapper.append(etree.fromstring(etree.tostring(child)))
                _copy_content(wrapper, book)
        for index, unit in enumerate(source_book.xpath("./*[local-name()='div3']"), 1):
            unit = etree.fromstring(etree.tostring(unit))
            raw_title = " ".join((unit.get("title") or "").split()).lower()
            typ = "preface" if index == 1 and raw_title.startswith("preface") else "chapter"
            if typ == "preface": prefaces += 1
            else: chapters += 1
            div = etree.SubElement(book, f"{{{TEI}}}div", type=typ, n=str(index))
            if unit.get("id"): div.set(XML_ID, "npnf-" + unit.get("id").replace(".", "-"))
            _copy_content(unit, div)
    if (len(books), chapters, prefaces) != (22, 661, 4):
        raise ValueError(f"CCEL semantic unit drift: {(len(books), chapters, prefaces)}")
    return body


def _tei(repo: Path, edition: str, profile: Mapping[str, object]) -> bytes:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "city-of-god-" + edition)
    root.append(_header(edition, profile))
    text = etree.SubElement(root, f"{{{TEI}}}text")
    text.set(XML_LANG, "en")
    text.append(_standard_body(repo, profile) if edition == "dods-1871" else _ccel_body(repo))
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _module_target(repo: Path, name: str) -> Path | None:
    stem = repo.joinpath(*name.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file(): return candidate.resolve(strict=True)
    return None


def _reject_dynamic_execution(tree: ast.AST) -> None:
    """Reject the small set of dynamic-code mechanisms forbidden in this fixed producer."""

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
            raise ValueError(f"dynamic execution is forbidden in producer closure: {function.id}")
        if isinstance(function, ast.Attribute) and function.attr in direct | attributes:
            category = "execution" if function.attr in direct else "import"
            raise ValueError(
                f"dynamic {category} is forbidden in producer closure: {function.attr}"
            )
        if (
            isinstance(function, ast.Call)
            and isinstance(function.func, ast.Name)
            and function.func.id == "getattr"
            and len(function.args) >= 2
            and isinstance(function.args[1], ast.Constant)
            and function.args[1].value in direct | attributes
        ):
            raise ValueError("dynamic getattr execution is forbidden in producer closure")


def _closure(repo: Path, forbidden: tuple[str, ...]) -> tuple[str, list[dict[str, object]]]:
    entry = Path(__file__).resolve(strict=True)
    contract = (repo / "ocd_kernel/reconstruction/contract.py").resolve(strict=True)
    loaded_contract = Path(inspect.getsourcefile(SourceManifest) or "").resolve(strict=True)
    callable_source = Path(inspect.getsourcefile(_convert) or "").resolve(strict=True)
    if (
        not entry.samefile(repo / "build/tei/city_of_god_reconstruction_electronic_v2.py")
        or not callable_source.samefile(entry)
        or not loaded_contract.samefile(contract)
    ):
        raise ValueError("runtime module shadow detected")
    for name, module in tuple(sys.modules.items()):
        if name in {"build.tei.city_of_god_reconstruction_electronic_v2", "ocd_kernel.reconstruction.contract"} and getattr(module, "__file__", None):
            target = _module_target(repo, name)
            if target is None or not Path(module.__file__).resolve(strict=True).samefile(target):
                raise ValueError(f"runtime module shadow: {name}")
    pending = [entry]; seen: set[Path] = set()
    while pending:
        path = pending.pop(0)
        if path in seen: continue
        path.relative_to(repo); seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _reject_dynamic_execution(tree)
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"forbidden runtime import {name}")
                target = _module_target(repo, name)
                if target is not None and target not in seen: pending.append(target)
    rows = []
    for path in sorted(seen, key=lambda p: p.relative_to(repo).as_posix()):
        data = path.read_bytes(); rows.append({"path":path.relative_to(repo).as_posix(),"bytes":len(data),"sha256":_sha(data)})
    return _sha(_canonical(rows)), rows


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    repo = source_manifest.repository_root
    profile = _load(source_manifest.authority_path("reconstruction-profile"))
    policy = _load(source_manifest.authority_path("validation-policy"))
    edition = str(source_manifest.record["edition"])
    observations, summary = _source_inventory(repo, profile)
    tei = _tei(repo, edition, profile)
    forbidden_imports = tuple(str(value) for value in policy["forbidden_runtime_import_prefixes"])
    closure_sha, closure = _closure(repo, forbidden_imports)
    accountability = {
        "contract": "ocd-city-of-god-source-accountability-v1",
        "edition": edition,
        "standard_observation_count": 58_815,
        "ccel_observation_count": 88_276,
        "observations_sha256": summary["observations_sha256"],
        "observations": observations,
        "print_inventory": {key: value for key, value in summary.items() if key not in {"observations_sha256"}},
        "semantic_units": {"books": 22, "chapters": 661, "prefaces": 4, "aligned_units": 665},
        "variants": {"lexical": 1533, "orthographic": 2390},
        "print_decisions": profile["print_decisions"],
        "crop_evidence": profile["crop_evidence"],
        "semantic_defects": profile["semantic_defects"],
        "omitted_count": 0,
    }
    provenance = {
        "contract": "ocd-city-of-god-provenance-v1", "status": "nonaccepted", "edition": edition,
        "source_manifest_sha256": source_manifest.sha256, "producer_closure_sha256": closure_sha,
        "producer_closure": closure, "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "authority": {"profile_sha256": _sha(_canonical(profile)), "policy_sha256": _sha(_canonical(policy))},
    }
    unresolved = b"".join(_canonical(item) for item in profile["unresolved"])
    readme = str(profile["readme"]).replace("{EDITION}", edition).encode()
    return {"content.tei.xml": tei, "source-accountability.json": _canonical(accountability), "provenance.json": _canonical(provenance), "unresolved.jsonl": unresolved, "README.source.md": readme}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
