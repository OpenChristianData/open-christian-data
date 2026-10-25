"""L332 scan-indexed, nonaccepted OCR reconstruction of Davis's grammar."""
from __future__ import annotations

import hashlib
import gzip
import json
import re
import tarfile
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Mapping

import fitz
from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BASE = "raw/internet-archive/beginners-grammar-greek-new-testament/beginnersgrammar00davi"
SOURCE = "sources/structured-text/davis-beginners-grammar-1923"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _add(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{tag}", **attrs)


def _section(leaf: int) -> tuple[str, str]:
    if leaf <= 18:
        return "front", "preliminaries"
    if leaf <= 22:
        return "front", "contents"
    if leaf <= 24:
        return "front", "part-i-divider"
    if leaf <= 220:
        return "body", "part-i-lessons"
    if leaf <= 246:
        return "body", "part-ii-supplement"
    if leaf <= 258:
        return "back", "english-index"
    if leaf <= 260:
        return "back", "vocabularies-divider"
    if leaf <= 270:
        return "back", "greek-english-vocabulary"
    if leaf <= 275:
        return "back", "english-greek-vocabulary"
    return "back", "end-material"


def _heading(value: str) -> bool:
    v = " ".join(value.strip().upper().split())
    return bool(re.fullmatch(r"LESSON [IVXLCDM]+", v)) or v in {
        "INTRODUCTION", "NOTE TO FIFTH EDITION", "PREFACE",
        "CONTENTS", "FART I: LESSONS", "PART II: SUPPLEMENT TO PART I",
        "ENGLISH INDEX", "VOCABULARIES", "GREEK-ENGLISH VOCABULARY",
        "ENGLISH-GREEK VOCABULARY",
    }


def _source(root: Path):
    path = lambda name: resolve_repo_path(root, f"{BASE}/{name}")
    scan = ET.parse(path("scandata.xml")).getroot().findall("./pageData/page")
    if len(scan) != 284 or [p.get("leafNum") for p in scan] != [str(n) for n in range(284)]:
        raise ValueError("scandata leaf envelope changed")
    access = [p for p in scan if p.findtext("addToAccessFormats") == "true"]
    excluded = [p for p in scan if p.findtext("addToAccessFormats") != "true"]
    if [int(p.get("leafNum", "-1")) for p in access] != list(range(1, 281)):
        raise ValueError("access leaf sequence changed")
    if [(int(p.get("leafNum", "-1")), p.findtext("pageType"))
        for p in excluded] != [(0, "Delete"), (281, "Delete"),
                               (282, "Color Card"), (283, "Color Card")]:
        raise ValueError("excluded leaf sequence changed")
    objects = ET.parse(path("ocr-djvu.xml")).getroot().findall("./BODY/OBJECT")
    with fitz.open(path("scan.pdf")) as pdf:
        pdf_count = len(pdf)
    if len(objects) != pdf_count or pdf_count != 280:
        raise ValueError("OCR/PDF page count changed")
    for n, obj in enumerate(objects, 1):
        marker = obj.find("./PARAM[@name='PAGE']")
        if marker is None or marker.get("value") != f"beginnersgrammar00davi_{n:04d}.djvu":
            raise ValueError(f"OCR page marker changed at {n}")
    with tarfile.open(path("original-pages.tar")) as archive:
        images = sorted((member for member in archive if member.isfile()),
                        key=lambda m: m.name)
        names = [m.name for m in images]
        expected = [f"beginnersgrammar00davi_orig_jp2/beginnersgrammar00davi_orig_{n:04d}.jp2"
                    for n in range(284)]
        if names != expected:
            raise ValueError("original JP2 carrier envelope changed")
        image_rows = [{"leaf": n, "member": member.name, "bytes": member.size}
                      for n, member in enumerate(images)]
    with gzip.open(path("ocr-abbyy.gz"), "rb") as stream:
        abbyy_pages = ET.parse(stream).getroot().findall(".//{*}page")
    if len(abbyy_pages) != 284:
        raise ValueError("Abbyy original-leaf envelope changed")
    return scan, access, excluded, objects, image_rows, abbyy_pages


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    root_path = manifest.repository_root
    scan, access, excluded, objects, image_rows, abbyy_pages = _source(root_path)
    receipt_path = resolve_repo_path(root_path, f"{BASE}/acquisition-receipt.json")
    receipt = json.loads(receipt_path.read_bytes())
    if receipt.get("manifest_row") != "L332" or receipt.get("provider_item") != "beginnersgrammar00davi":
        raise ValueError("L332 acquisition identity changed")
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "davis-beginners-grammar-1923-review")
    header = _add(root, "teiHeader")
    desc = _add(header, "fileDesc")
    ts = _add(desc, "titleStmt")
    _add(ts, "title").text = "Beginner's Grammar of the Greek New Testament"
    _add(ts, "author").text = "William Hersey Davis"
    pub = _add(desc, "publicationStmt")
    _add(pub, "publisher").text = "Open Christian Data"
    _add(_add(pub, "availability", status="restricted"), "p").text = (
        "Nonaccepted OCR review candidate. Digitization rights and publication remain unresolved.")
    bibl = _add(_add(desc, "sourceDesc"), "bibl")
    _add(bibl, "title").text = "Beginner's Grammar of the Greek New Testament"
    _add(bibl, "author").text = "William Hersey Davis"
    _add(bibl, "date", when="1923").text = "1923"
    _add(bibl, "pubPlace").text = "New York and London"
    _add(bibl, "publisher").text = "Harper & Brothers"
    _add(bibl, "idno", type="internet-archive").text = "beginnersgrammar00davi"
    _add(_add(header, "encodingDesc"), "p").text = (
        "All 280 access-format pages are represented in scan order from uncorrected DjVuXML. "
        "Original JP2 leaf and PDF page relations are explicit. OCR errors, especially Greek, "
        "and pages with no OCR words remain unresolved; page images are authoritative.")
    _add(_add(header, "revisionDesc", status="candidate"), "change",
         when="2026-09-25").text = "Bounded L332 scan-indexed review reconstruction."
    txt = _add(root, "text")
    parts = {name: _add(txt, name) for name in ("front", "body", "back")}
    groups = {name: {} for name in parts}
    for leaf in range(1, 281):
        section, group = _section(leaf)
        if group not in groups[section]:
            groups[section][group] = _add(parts[section], "div", type=group)
    account = {
        "contract": "ocd-davis-l332-accountability-v1",
        "source_id": manifest.record["source_id"],
        "original_jp2_images": image_rows,
        "scan_leaves": 284,
        "excluded_leaves": [
            {"leaf": int(p.get("leafNum", "-1")), "page_type": p.findtext("pageType"),
             "disposition": "outside PDF/OCR access sequence; original JP2 retained"}
            for p in excluded],
        "pages": [],
    }
    total_paras = total_lines = total_words = 0
    for number, (leaf_data, obj) in enumerate(zip(access, objects, strict=True), 1):
        section, group = _section(number)
        page = _add(groups[section][group], "div", type="scan-page", n=str(number))
        page.set(XML_ID, f"leaf-{number:04d}")
        label = leaf_data.findtext("pageNumber") or ""
        _add(page, "pb", n=label or str(number),
             facs=f"{BASE}/scan.pdf#page={number}")
        paras = obj.findall(".//PARAGRAPH")
        rows = []
        for pi, para in enumerate(paras, 1):
            lines = para.findall("./LINE")
            values = ["".join(word.text or "" for word in line.findall("./WORD"))
                      for line in lines]
            count = sum(len(line.findall("./WORD")) for line in lines)
            joined = " ".join(values)
            role = "head" if _heading(joined) or (number, pi) in {(25, 3), (221, 2)} else "p"
            wrapper = _add(page, "div", type="ocr-heading" if role == "head" else "ocr-paragraph")
            paragraph = _add(wrapper, role)
            paragraph.set(XML_ID, f"leaf-{number:04d}-p{pi:03d}")
            for li, value in enumerate(values, 1):
                _add(paragraph, "lb", n=str(li)).tail = value
            rows.append({"index": pi, "role": role, "line_sha256":
                         [_sha(v.encode("utf-8")) for v in values], "words": count})
            total_lines += len(values)
            total_words += count
        table_rows = []
        for ti, block in enumerate(
                [block for block in abbyy_pages[number]
                 if block.get("blockType") == "Table"], 1):
            wrapper = _add(page, "div", type="alternate-ocr-layout")
            _add(wrapper, "head").text = "Alternate Abbyy table layout"
            table = _add(wrapper, "table", n=str(ti))
            source_rows = []
            for source_row in block.findall("./{*}row"):
                row = _add(table, "row")
                source_cells = []
                for source_cell in source_row.findall("./{*}cell"):
                    cell = _add(row, "cell")
                    values = []
                    for source_line in source_cell.findall(".//{*}line"):
                        chars = source_line.findall(".//{*}charParams")
                        value = "".join(
                            (" " if i and ch.get("wordStart") == "true" else "")
                            + (ch.text or "") for i, ch in enumerate(chars))
                        values.append(value)
                        _add(cell, "lb", n=str(len(values))).tail = value
                    source_cells.append([_sha(v.encode("utf-8")) for v in values])
                source_rows.append(source_cells)
            table_rows.append(source_rows)
        if not any(row["words"] for row in rows):
            _add(page, "gap", reason="ocr-unavailable", extent="unknown")
        account["pages"].append({
            "leaf": number, "pdf_page": number,
            "jp2_member": image_rows[number]["member"],
            "printed_label": label,
            "page_type": leaf_data.findtext("pageType") or "",
            "section": section, "group": group, "paragraphs": rows,
            "abbyy_tables": table_rows,
        })
        total_paras += len(paras)
    account["totals"] = {"pages": 280, "paragraphs": total_paras,
                         "lines": total_lines, "words": total_words}
    provenance = {"contract": "ocd-davis-l332-provenance-v1", "source_id": manifest.record["source_id"],
                  "status": "nonaccepted", "primary_source": f"{BASE}/original-pages.tar",
                  "ocr_witness": f"{BASE}/ocr-djvu.xml",
                  "source_receipt_sha256": _sha(receipt_path.read_bytes())}
    unresolved = [
        {"id": "davis-l332-scan-collation", "kind": "text-fidelity", "status": "unresolved",
         "affected_represented_pages": 280,
         "detail": "DjVuXML text is uncorrected and has severe Greek recognition errors; complete collation against JP2 scans remains open."},
        {"id": "davis-l332-empty-ocr", "kind": "coverage", "status": "unresolved",
         "pages": [n for n, row in enumerate(account["pages"], 1)
                   if not any(p["words"] for p in row["paragraphs"])],
         "detail": "These page images have no OCR word tokens; image-only text is not transcribed."},
        {"id": "davis-l332-semantic-layout", "kind": "structure", "status": "unresolved",
         "detail": "Greek paradigms, tabular alignments, vocabulary entries, and index entries retain page/paragraph/line OCR carriers pending scan-level structuring."},
    ]
    readme = (
        "# Davis, Beginner's Grammar of the Greek New Testament (1923)\n\n"
        "L332 nonaccepted scan-indexed OCR review candidate. The original JP2 tar is primary; "
        "all 284 images are inventoried, with 280 access-format PDF/OCR pages represented in "
        "TEI and four excluded leaves explicitly accounted for. OCR wording is uncorrected, "
        "including damaged Greek. Eleven pages have no OCR word tokens. The TEI retains "
        "front matter, Part I lessons, Part II supplement, English index, vocabularies, "
        "and end material in scan order, with each page related to its JP2 member and PDF page. "
        "Abbyy-detected tables are preserved as separate, explicitly labeled alternate OCR "
        "layout witnesses; their text duplicates portions of the primary DjVu reading. "
        "Complete print-level textual fidelity, tabular structure, human acceptance, "
        "digitization rights, and publication are unresolved.\n"
    ).encode("utf-8")
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True),
            "source-accountability.json": _json(account),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(row) for row in unresolved),
            "README.source.md": readme}


_convert.converter_id = "ocd-davis-l332-scan-indexed-ocr"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()

