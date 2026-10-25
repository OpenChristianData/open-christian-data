"""Faithful deterministic HTML-to-TEI conversion for Lightfoot's essays."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
EXPECTED_SOURCE_SHA256 = "a3fdcb0d069bad8a6ee5855dfb25ccec9a5536668cf2af7c23675d3e0c9855b6"
EXPECTED_SOURCE_TEXT_SHA256 = "267d9e684e13c4dde33690e59ff3d426b0449caa4b61f1bc728129fe2a59fa81"
SOURCE_RELATIVE_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    "lightfoot-essays-supernatural-religion-1893/pg18191-images.html"
)
PACKAGE_HASHES = {
    "18191-8.txt": "445679673dbe4b67b518e4dfe79678fa6243b0d9a1b5f8fc353204107db860f0",
    "18191-8.zip": "9a22d7b93927a4c801be12bb401f728a9459decbe268ade307a2658b72d2abf1",
    "18191.txt": "1ed59682fd843a17eefb60a69c810b475c6ab884461109b3a9711d9271476c12",
    "18191.zip": "07a16f96381a6f1bbe6320d5b7221464073c6f3ffa7988ee43f9ff2c6d697ae1",
    "files-index.html": "ea0fef5f8ae0052b4fd4e1232466020dc426012591b7ede94c0e363361af17e7",
    "landing.html": "43308e60f54e9c96abec1c46797eca441d1ab0420cb85ddbe503f1d123f3ddaa",
    "pg18191-h.zip": "0ac44cd475db3a395a6152e42568be7f620cda2a3e057ea90c7a7df5f0d921ac",
    "pg18191-images.html": EXPECTED_SOURCE_SHA256,
    "pg18191.txt": "a8f866bd7ebfcf7d406420150c8626946451b73f55b79fc1c883e9776d7e23f6",
}
COVER_SHA256 = "02399ab360764c798a299b549950ca32a935fcaf0db91a7d6742bd639ec43fbc"
SECTION_HEADS = [
    "SUPERNATURAL RELIGION.",
    "II. THE SILENCE OF EUSEBIUS.",
    "III. THE IGNATIAN EPISTLES.",
    "IV. POLYCARP OF SMYRNA.",
    "V. PAPIAS OF HIERAPOLIS.",
    "VI. PAPIAS OF HIERAPOLIS.",
    "VII. THE LATER SCHOOL OF ST JOHN.",
    "VIII. THE CHURCHES OF GAUL.",
    "IX. TATIAN'S DIATESSARON [272:1].",
    "DISCOVERIES ILLUSTRATING THE ACTS OF THE APOSTLES.",
]


class SourceMismatchError(ValueError):
    """The retained source/package is not the gate-released witness."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source_path(repository_root: Path) -> Path:
    return resolve_repo_path(repository_root, SOURCE_RELATIVE_PATH)


def _parse_source(path: Path) -> html.HtmlElement:
    return html.fromstring(path.read_text(encoding="utf-8"))


def _body(document: html.HtmlElement) -> html.HtmlElement:
    bodies = document.xpath("//body")
    if len(bodies) != 1:
        raise SourceMismatchError(f"expected one HTML body, found {len(bodies)}")
    return bodies[0]


def _normalized_text(element: etree._Element) -> str:
    return " ".join(element.text_content().split())


def _positions(body: html.HtmlElement) -> list[int]:
    starts: list[int] = []
    cursor = 0
    for expected in SECTION_HEADS:
        found = next(
            (i for i in range(cursor, len(body)) if _normalized_text(body[i]) == expected),
            None,
        )
        if found is None:
            raise SourceMismatchError(f"missing section boundary: {expected}")
        starts.append(found)
        cursor = found + 1
    return starts


def _package_audit(raw_root: Path) -> dict[str, Any]:
    actual = {path.name for path in raw_root.iterdir() if path.is_file()}
    if actual != set(PACKAGE_HASHES):
        raise SourceMismatchError(
            f"retained package differs: missing={sorted(set(PACKAGE_HASHES)-actual)}, "
            f"unexpected={sorted(actual-set(PACKAGE_HASHES))}"
        )
    hashes = {name: sha256_file(raw_root / name) for name in sorted(PACKAGE_HASHES)}
    wrong = {name: value for name, value in hashes.items() if value != PACKAGE_HASHES[name]}
    if wrong:
        raise SourceMismatchError(f"retained package SHA-256 mismatch: {wrong}")
    comparisons: list[dict[str, Any]] = []
    archives: dict[str, list[str]] = {}
    for archive_name, member_name, direct_name in (
        ("pg18191-h.zip", "pg18191-images.html", "pg18191-images.html"),
        ("18191.zip", "18191.txt", "18191.txt"),
        ("18191-8.zip", "18191-8.txt", "18191-8.txt"),
    ):
        with zipfile.ZipFile(raw_root / archive_name) as archive:
            archives[archive_name] = sorted(i.filename for i in archive.infolist() if not i.is_dir())
            member_hash = hashlib.sha256(archive.read(member_name)).hexdigest()
        direct_hash = hashes[direct_name]
        comparisons.append({
            "archive": archive_name,
            "member": member_name,
            "direct": direct_name,
            "member_sha256": member_hash,
            "direct_sha256": direct_hash,
            "match": member_hash == direct_hash,
        })
    with zipfile.ZipFile(raw_root / "pg18191-h.zip") as archive:
        cover_hash = hashlib.sha256(archive.read("18191-cover.png")).hexdigest()
    if not all(item["match"] for item in comparisons) or cover_hash != COVER_SHA256:
        raise SourceMismatchError("ZIP member/container comparison failed")
    return {"package_hashes": hashes, "container_comparisons": comparisons,
            "archive_members": archives, "cover_sha256": cover_hash}


def audit_source(source: Path, *, repository_root: Path) -> dict[str, Any]:
    source_hash = sha256_file(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SourceMismatchError(f"source SHA-256 {source_hash} does not match {EXPECTED_SOURCE_SHA256}")
    package = _package_audit(source.parent)
    document = _parse_source(source)
    body = _body(document)
    source_text = _normalized_text(body)
    text_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if text_hash != EXPECTED_SOURCE_TEXT_SHA256:
        raise SourceMismatchError("source normalized-text SHA-256 mismatch")
    elements = [e for e in body.iter() if isinstance(e.tag, str)]
    counts = Counter(e.tag for e in elements)
    ids = [e.get("id") for e in elements if e.get("id")]
    if len(ids) != 1880 or len(ids) != len(set(ids)):
        raise SourceMismatchError("source identifier census differs")
    starts = _positions(body)
    expected_positions = [21, 77, 174, 248, 372, 448, 542, 609, 647, 693]
    if starts != expected_positions:
        raise SourceMismatchError(f"section positions differ: {starts}")
    if counts != Counter({"p":1841,"i":1337,"br":893,"div":50,"h2":17,"h5":14,
                         "strong":6,"a":5,"li":4,"span":3,"h4":3,"h1":3,"body":1,
                         "header":1,"footer":1,"blockquote":1,"ul":1}):
        raise SourceMismatchError(f"source element census differs: {counts}")
    transcriber = _normalized_text(body[3])
    if "Footnotes have been relocated" not in transcriber or "Inconsistent hyphenations" not in transcriber:
        raise SourceMismatchError("transcriber's intervention notice differs")
    return {
        **package,
        "source_sha256": source_hash,
        "source_bytes": source.stat().st_size,
        "source_text_characters": len(source_text),
        "source_text_sha256": text_hash,
        "tag_counts": dict(sorted(counts.items())),
        "source_ids": len(ids),
        "ids_unique": True,
        "section_heads": SECTION_HEADS,
        "section_positions": starts,
        "relocated_footnote_paragraphs": 708,
        "subject_index_paragraphs": 384,
        "passage_index_paragraphs": 65,
        "transcribers_note": transcriber,
        "project_gutenberg_start_marker": _normalized_text(body[0]),
        "project_gutenberg_end_and_license": _normalized_text(body[-1]),
    }


def _tei(name: str) -> etree._Element:
    return etree.Element(f"{{{TEI_NS}}}{name}")


def _copy_attributes(source: etree._Element, target: etree._Element) -> None:
    if source.get("id"):
        target.set(f"{{{XML_NS}}}id", source.get("id"))
    if source.get("class"):
        target.set("rend", " ".join(source.get("class").split()))


def _clone(source: etree._Element, *, footnote: bool = False) -> etree._Element:
    tag = source.tag.lower()
    if footnote and tag == "p":
        target = _tei("note")
        target.set("place", "end")
    elif tag == "p": target = _tei("p")
    elif tag in {"i", "span"}:
        target = _tei("hi")
        if tag == "i": target.set("rend", "italic")
    elif tag == "strong":
        target = _tei("hi"); target.set("rend", "bold")
    elif tag == "br": target = _tei("lb")
    elif tag == "a":
        target = _tei("ref")
        if source.get("href"): target.set("target", source.get("href"))
    elif tag in {"h1", "h2", "h4", "h5"} and source.xpath("ancestor::header | ancestor::footer"):
        target = _tei("ab"); target.set("type", f"source_{tag}")
    elif tag in {"h1", "h2", "h4", "h5"}:
        target = _tei("head"); target.set("type", tag)
    elif tag == "ul": target = _tei("list")
    elif tag == "li": target = _tei("item")
    elif tag == "blockquote": target = _tei("quote")
    elif tag in {"header", "footer"}:
        target = _tei("div"); target.set("type", f"project_gutenberg_{tag}")
    elif tag == "div" and source.xpath("./p"):
        target = _tei("quote"); target.set("type", "xhtml_div")
    elif tag == "div": target = _tei("ab")
    else: raise SourceMismatchError(f"unmapped HTML element: {tag}")
    _copy_attributes(source, target)
    target.text = source.text
    for child in source:
        cloned = _clone(child, footnote=footnote)
        cloned.tail = child.tail
        target.append(cloned)
    return target


def _append_group(parent: etree._Element, kind: str, nodes: Iterable[etree._Element], *, footnotes: bool = False) -> etree._Element:
    division = etree.SubElement(parent, f"{{{TEI_NS}}}div", type=kind)
    for node in nodes:
        cloned = _clone(node, footnote=footnotes)
        if etree.QName(cloned).localname == "head" and len(division):
            cloned.tag = f"{{{TEI_NS}}}ab"; cloned.set("type", f"source_{node.tag.lower()}")
        cloned.tail = node.tail
        division.append(cloned)
    return division


def _header() -> etree._Element:
    header = _tei("teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = "Essays on the Work Entitled Supernatural Religion"
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = "Joseph Barber Lightfoot"
    edition_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}editionStmt")
    etree.SubElement(edition_stmt, f"{{{TEI_NS}}}edition").text = "Second edition, 1893; first edition, 1889"
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = "Project Gutenberg"
    date = etree.SubElement(publication, f"{{{TEI_NS}}}date", when="2006-04-17"); date.text = "April 17, 2006"
    idno = etree.SubElement(publication, f"{{{TEI_NS}}}idno", type="Project-Gutenberg"); idno.text = "18191"
    availability = etree.SubElement(publication, f"{{{TEI_NS}}}availability", status="free")
    etree.SubElement(availability, f"{{{TEI_NS}}}p").text = "Public domain in the United States according to Project Gutenberg."
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI_NS}}}bibl")
    etree.SubElement(bibl, f"{{{TEI_NS}}}title").text = "Essays on the Work Entitled Supernatural Religion"
    etree.SubElement(bibl, f"{{{TEI_NS}}}date", when="1893").text = "1893"
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc").append(etree.Element(f"{{{TEI_NS}}}p"))
    encoding.find(f"{{{TEI_NS}}}projectDesc/{{{TEI_NS}}}p").text = (
        "Faithful deterministic projection of exact retained Project Gutenberg HTML; "
        "source footnote relocation and inconsistent hyphenation are retained."
    )
    profile = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    usage = etree.SubElement(profile, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(usage, f"{{{TEI_NS}}}language", ident="en").text = "English with source-defined transliterated Greek"
    revision = etree.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
    etree.SubElement(revision, f"{{{TEI_NS}}}change", when="2026-08-31").text = "Generated as a nonaccepted Open Christian Data candidate."
    return header


def _transform(document: html.HtmlElement) -> etree._ElementTree:
    source = _body(document); starts = _positions(source)
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS}); root.set(f"{{{XML_NS}}}lang", "en")
    root.append(_header()); text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    front = etree.SubElement(text, f"{{{TEI_NS}}}front")
    _append_group(front, "project_gutenberg_header", source[0:1])
    _append_group(front, "production_and_transcribers_note", source[1:4])
    _append_group(front, "title_page", source[4:10])
    _append_group(front, "preface", source[10:18])
    _append_group(front, "contents", source[18:21])
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else 708
        if index == 8: end = 691
        if index == 9: start = 691
        _append_group(body, "essay" if index < 9 else "appendix", source[start:end])
    back = etree.SubElement(text, f"{{{TEI_NS}}}back")
    _append_group(back, "relocated_footnotes", source[708:1417], footnotes=True)
    _append_group(back, "indices", source[1417:1871])
    _append_group(back, "project_gutenberg_footer", source[1871:])
    return etree.ElementTree(root)


@lru_cache(maxsize=1)
def _relaxng(path: Path) -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(path)))


def _project_raw(element: etree._Element) -> str:
    pieces = [element.text or ""]
    for child in element:
        pieces.append(_project_raw(child))
        if child.tail is not None: pieces.append(child.tail)
        elif etree.QName(child).localname in {"ab","div","head","item","list","note","p","quote"}: pieces.append(" ")
    return "".join(pieces)


def _project(element: etree._Element) -> str:
    return " ".join(_project_raw(element).split())


def _validate(source_document: html.HtmlElement, candidate: etree._ElementTree, repository_root: Path) -> dict[str, Any]:
    schema = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    validator = _relaxng(schema)
    if not validator.validate(candidate):
        raise SourceMismatchError(f"TEI P5 Relax NG validation failed: {validator.error_log.last_error}")
    source_text = _normalized_text(_body(source_document)); text = candidate.find("tei:text", NS)
    if text is None: raise SourceMismatchError("candidate text missing")
    candidate_text = _project(text)
    if source_text != candidate_text: raise SourceMismatchError("source and candidate ordered text differ")
    counts = Counter(etree.QName(e).localname for e in text.iter() if isinstance(e.tag, str))
    ids = {str(x) for x in candidate.xpath("//@xml:id", namespaces={"xml":XML_NS})}
    targets = [str(x)[1:] for x in candidate.xpath("//tei:ref/@target", namespaces=NS) if str(x).startswith("#")]
    unresolved = sorted(set(targets)-ids)
    if unresolved: raise SourceMismatchError(f"unresolved candidate targets: {unresolved}")
    return {"tei_p5_relaxng_valid":True,"source_candidate_text_match":True,
            "source_text_sha256":hashlib.sha256(source_text.encode()).hexdigest(),
            "candidate_text_sha256":hashlib.sha256(candidate_text.encode()).hexdigest(),
            "source_text_characters":len(source_text),"candidate_text_characters":len(candidate_text),
            "candidate_tag_counts":dict(sorted(counts.items())),"section_divisions":10,
            "candidate_ids":len(ids),"internal_targets":len(targets),"unresolved_internal_targets":unresolved}


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); stage = path.with_name(path.name + ".tmp")
    if stage.exists(): raise FileExistsError(stage)
    stage.write_text(json.dumps(record,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n"); stage.replace(path)


def build_candidate(source: Path, candidate: Path, report: Path, *, repository_root: Path, replace: bool=False) -> dict[str, Any]:
    audit = audit_source(source, repository_root=repository_root)
    if not replace and (candidate.exists() or report.exists()): raise FileExistsError("candidate or validation report already exists")
    source_document = _parse_source(source); candidate_document = _transform(source_document)
    validation = _validate(source_document, candidate_document, repository_root)
    candidate_bytes = etree.tostring(candidate_document,encoding="UTF-8",xml_declaration=True,pretty_print=False)
    result = {**validation,"source_sha256":audit["source_sha256"],"candidate_sha256":hashlib.sha256(candidate_bytes).hexdigest(),
              "relocated_footnote_paragraphs":708,"transcribers_note_retained":True,
              "electronic_interventions":"Source-stated footnote relocation and inconsistent hyphenation are retained verbatim; no further corrections or modernization applied.",
              "canonical_write":False,"acceptance_status":"nonaccepted","publication_status":"not-authorized"}
    candidate.parent.mkdir(parents=True,exist_ok=True); report.parent.mkdir(parents=True,exist_ok=True)
    cs=candidate.with_name(candidate.name+".tmp"); rs=report.with_name(report.name+".tmp")
    if cs.exists() or rs.exists(): raise FileExistsError("staged output exists")
    cs.write_bytes(candidate_bytes); rs.write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n"); cs.replace(candidate); rs.replace(report)
    return result


def write_determinism_report(a: Path, av: Path, b: Path, bv: Path, output: Path, *, repository_root: Path) -> dict[str, Any]:
    result={"candidate_bytes_equal":a.read_bytes()==b.read_bytes(),"candidate_sha256":sha256_file(a),
            "validation_bytes_equal":av.read_bytes()==bv.read_bytes(),"validation_sha256":sha256_file(av),
            "different_working_directory":Path.cwd().resolve()!=repository_root.resolve(),
            "run_a_working_directory":str(repository_root.resolve()),"run_b_working_directory":str(Path.cwd().resolve())}
    if not all(result[k] for k in ("candidate_bytes_equal","validation_bytes_equal","different_working_directory")): raise SourceMismatchError("fresh-CWD determinism contract failed")
    _write_json(output,result); return result


def write_offline_visual_contact_sheet(source: Path, candidate: Path, output_dir: Path) -> dict[str, Any]:
    body=_body(_parse_source(source)); doc=etree.parse(str(candidate)); checks=[]
    selections=[("opening-title-edition",body[4:10],doc.xpath("/tei:TEI/tei:text/tei:front/tei:div[@type='title_page']",namespaces=NS),"full"),
                ("middle-papias",body[448:542],doc.xpath("/tei:TEI/tei:text/tei:body/tei:div[6]",namespaces=NS),"prefix"),
                ("unusual-relocated-footnote",body[709:712],doc.xpath("/tei:TEI/tei:text/tei:back/tei:div[@type='relocated_footnotes']/tei:note[position()<=3]",namespaces=NS),"full"),
                ("unusual-greek-and-typography",body[647:651],doc.xpath("/tei:TEI/tei:text/tei:body/tei:div[9]/*[position()<=4]",namespaces=NS),"full"),
                ("ending-index-and-footer",body[1804:],doc.xpath("/tei:TEI/tei:text/tei:back/tei:div[@type='indices']/*[position()>=388] | /tei:TEI/tei:text/tei:back/tei:div[@type='project_gutenberg_footer']",namespaces=NS),"suffix")]
    for label,snodes,cnodes,mode in selections:
        st=" ".join(filter(None,(_normalized_text(n) for n in snodes))); ct=" ".join(filter(None,(_project(n) for n in cnodes)))
        if st!=ct: raise SourceMismatchError(f"offline contact selection differs: {label}")
        excerpt=st[:1200] if mode=="prefix" else st[-1600:] if mode=="suffix" else st
        checks.append({"label":label,"selection":mode,"full_text_characters":len(st),"full_text_sha256":hashlib.sha256(st.encode()).hexdigest(),"source_candidate_full_text_match":True,"exact_excerpt":excerpt,"exact_excerpt_characters":len(excerpt),"exact_excerpt_sha256":hashlib.sha256(excerpt.encode()).hexdigest(),"result":"pass"})
    result={"method":"offline exact-excerpt contact sheet from pinned HTML and TEI","checks":checks,"all_exact_text_checks_passed":True,
            "acceptance_scope":"machine-verifiable lightweight fidelity evidence only; human acceptance remains separate"}
    output_dir.mkdir(parents=True,exist_ok=True); _write_json(output_dir/"offline_contact_sheet.json",result)
    lines=["# Lightfoot offline exact-excerpt contact sheet","","Aligned exact excerpts from the pinned HTML and generated TEI.",""]
    for c in checks: lines += [f"## {c['label']}","",c["exact_excerpt"],""]
    (output_dir/"offline_contact_sheet.md").write_text("\n".join(lines),encoding="utf-8",newline="\n"); return result


def write_evidence_bundle(
    source: Path,
    candidate: Path,
    validation: Path,
    determinism: Path,
    evidence_root: Path,
    *,
    repository_root: Path,
) -> dict[str, Path]:
    audit = audit_source(source, repository_root=repository_root)
    validation_record = json.loads(validation.read_text(encoding="utf-8"))
    urls = {
        "18191-8.txt":"https://www.gutenberg.org/files/18191/18191-8.txt",
        "18191-8.zip":"https://www.gutenberg.org/files/18191/18191-8.zip",
        "18191.txt":"https://www.gutenberg.org/files/18191/18191.txt",
        "18191.zip":"https://www.gutenberg.org/files/18191/18191.zip",
        "files-index.html":"https://www.gutenberg.org/files/18191/",
        "landing.html":"https://www.gutenberg.org/ebooks/18191",
        "pg18191-h.zip":"https://www.gutenberg.org/cache/epub/18191/pg18191-h.zip",
        "pg18191-images.html":"https://www.gutenberg.org/cache/epub/18191/pg18191-images.html",
        "pg18191.txt":"https://www.gutenberg.org/cache/epub/18191/pg18191.txt",
    }
    acquisition = evidence_root.parent / "acquisition"
    members=[]
    for name in sorted(PACKAGE_HASHES):
        path=source.parent/name; headers=acquisition/f"{name}.headers.txt"
        members.append({"name":name,"bytes":path.stat().st_size,"sha256":sha256_file(path),"url":urls[name],"download_headers_sha256":sha256_file(headers)})
    receipt={"ticket":28,"master":4,"slug":"lightfoot-essays-supernatural-religion-1893",
             "identity":{"title":"Essays on the Work Entitled Supernatural Religion","author":"Joseph Barber Lightfoot","edition":"Second edition, London: Macmillan and Co., and New York, 1893; first edition 1889","project_gutenberg_id":"18191","workcatalog":"provisional net-new candidate; no canonical write"},
             "retained_members":members,"container_comparisons":audit["container_comparisons"],"archive_members":audit["archive_members"],"cover_member_sha256":audit["cover_sha256"],
             "rights":{"status":"Public domain in the United States per Project Gutenberg record","license_url":"https://www.gutenberg.org/policy/license.html","production_credit":"Project Gutenberg Distributed Proofreaders"},
             "source_authority":"pg18191-images.html is the structural and textual authority; retained current/legacy text pairs, ZIP containers and cover, landing page, and official file index are hash-bound corroborating witnesses",
             "completeness":{"source_text_characters":audit["source_text_characters"],"source_text_sha256":audit["source_text_sha256"],"section_heads":audit["section_heads"],"relocated_footnote_paragraphs":708,"subject_index_paragraphs":384,"passage_index_paragraphs":65,"source_ids":audit["source_ids"],"project_gutenberg_start_marker":audit["project_gutenberg_start_marker"],"project_gutenberg_end_and_license_sha256":hashlib.sha256(audit["project_gutenberg_end_and_license"].encode()).hexdigest()},
             "acceptance_status":"nonaccepted","publication_status":"not-authorized"}
    accountability={"source_sha256":audit["source_sha256"],"candidate_sha256":sha256_file(candidate),"validation_sha256":sha256_file(validation),"determinism_sha256":sha256_file(determinism),
                    "schema":{"path":"ocd_kernel/tei/vendor/relaxng/tei_all.rng","sha256":sha256_file(repository_root/"ocd_kernel/tei/vendor/relaxng/tei_all.rng")},
                    "converter":{"path":"build/tei/lightfoot_essays_supernatural_religion_1893.py","sha256":sha256_file(repository_root/"build/tei/lightfoot_essays_supernatural_religion_1893.py")},
                    "source_config":{"path":"sources/structured-text/lightfoot-essays-supernatural-religion-1893/config.json","sha256":sha256_file(repository_root/"sources/structured-text/lightfoot-essays-supernatural-religion-1893/config.json")},
                    "attribution_readme":{"path":"sources/structured-text/lightfoot-essays-supernatural-religion-1893/README.md","sha256":sha256_file(repository_root/"sources/structured-text/lightfoot-essays-supernatural-religion-1893/README.md")},
                    "contract_tests":{"path":"tests/test_lightfoot_essays_supernatural_religion_1893.py","sha256":sha256_file(repository_root/"tests/test_lightfoot_essays_supernatural_religion_1893.py"),"result":"5 passed"},
                    "package_hashes":audit["package_hashes"],"container_comparisons":audit["container_comparisons"],
                    "tei_p5_relaxng_valid":validation_record["tei_p5_relaxng_valid"],"source_candidate_text_match":validation_record["source_candidate_text_match"],
                    "source_text_sha256":validation_record["source_text_sha256"],"candidate_text_sha256":validation_record["candidate_text_sha256"],
                    "candidate_tag_counts":validation_record["candidate_tag_counts"],"unresolved_internal_targets":validation_record["unresolved_internal_targets"],
                    "electronic_interventions":validation_record["electronic_interventions"],"wording_modernized":False,"canonical_write":False,"acceptance_status":"nonaccepted","publication_status":"not-authorized"}
    unresolved={"textual_acceptance":"pending human review","identity_and_edition_acceptance":"pending human review","rights_acceptance":"pending human review","editorial_acceptance":"pending human review","visual_acceptance":"offline exact-excerpt checks pass; human visual acceptance remains pending","canonical_integration":"not authorized","publication":"not authorized"}
    paths={"receipt":evidence_root/"source_receipt.json","accountability":evidence_root/"accountability.json","unresolved":evidence_root/"unresolved_items.json"}
    _write_json(paths["receipt"],receipt); _write_json(paths["accountability"],accountability); _write_json(paths["unresolved"],unresolved); return paths


def write_path_hash_manifest(raw_root: Path, report_root: Path, output: Path, *, repository_root: Path) -> dict[str, Any]:
    entries=[]
    for scope,root in (("raw",raw_root),("report",report_root)):
        for path in sorted(p for p in root.rglob("*") if p.is_file() and p.resolve()!=output.resolve()):
            entries.append({"scope":scope,"path":path.relative_to(root).as_posix(),"bytes":path.stat().st_size,"sha256":sha256_file(path)})
    for relative in ("sources/structured-text/lightfoot-essays-supernatural-religion-1893/config.json","sources/structured-text/lightfoot-essays-supernatural-religion-1893/README.md","build/tei/lightfoot_essays_supernatural_religion_1893.py","tests/test_lightfoot_essays_supernatural_religion_1893.py"):
        path=repository_root/relative; entries.append({"scope":"worktree","path":relative,"bytes":path.stat().st_size,"sha256":sha256_file(path)})
    result={"ticket":28,"master":4,"slug":"lightfoot-essays-supernatural-religion-1893","files":entries,"file_count_excluding_manifest":len(entries),"canonical_write":False,"acceptance_status":"nonaccepted","publication_status":"not-authorized"}
    _write_json(output,result); return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--repository-root",type=Path,required=True); parser.add_argument("--source",type=Path); parser.add_argument("--candidate",type=Path,required=True); parser.add_argument("--validation",type=Path,required=True); parser.add_argument("--replace",action="store_true"); args=parser.parse_args()
    root=args.repository_root.resolve(); source=(args.source or resolve_source_path(root)).resolve()
    build_candidate(source,args.candidate.resolve(),args.validation.resolve(),repository_root=root,replace=args.replace); return 0


if __name__ == "__main__": raise SystemExit(main())
