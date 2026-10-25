"""Complete scan-indexed OCR review candidate for Watson's two IA volumes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from typing import Mapping
import fitz
from lxml import etree
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BASE = "raw/internet-archive/theological-institutes"
VOLUMES = (
    ("theologicalinst01wats", "I", "1825", 12, 574, 586, 578),
    ("theologicalinst02wats", "II", "1826", 8, 488, 500, 492),
)
MEMBERS = ("scan.pdf", "ocr.txt", "ocr.xml", "scandata.xml", "metadata.json",
           "member-inventory.tsv", "acquisition-receipt.json", "page-numbers.json", "page-scans.zip")

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")

def el(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{tag}", **attrs)

def section_for(leaf: int, front_end: int, back_start: int) -> str:
    return "front" if leaf <= front_end else "back" if leaf >= back_start else "body"

def heading(value: str) -> bool:
    line = " ".join(value.split()).strip(" .")
    return bool(re.fullmatch(
        r"(?:CHAPTER\s+[IVXLCDM]+|PART\s+(?:FIRST|SECOND|THIRD|FOURTH)|"
        r"ADVERTISEMENT|CONTENTS|PREFACE|DEDICATION|INDEX)",
        line, flags=re.IGNORECASE))

def derived_paragraphs(raw: str) -> list[list[str]]:
    """Keep Tesseract line strings and blank-line paragraph boundaries."""
    result: list[list[str]] = []
    current: list[str] = []
    for line in raw.rstrip("\f\r\n").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            if current:
                result.append(current)
                current = []
        else:
            current.append(line)
    if current:
        result.append(current)
    return result

def read_volume(root: Path, name: str, expected_leaves: int, expected_pdf: int):
    base = f"{BASE}/{name}"
    paths = {member: resolve_repo_path(root, f"{base}/{member}") for member in MEMBERS}
    members = [{"path": f"{base}/{member}", "bytes": paths[member].stat().st_size,
                "sha256": sha(paths[member].read_bytes()),
                "role": "scan witness" if member in {"scan.pdf", "page-scans.zip"} else
                        "OCR handoff" if member in {"ocr.xml", "ocr.txt"} else "support"}
               for member in MEMBERS]
    with ZipFile(paths["page-scans.zip"]) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        expected_names = [f"{name}_jp2/{name}_{leaf:04d}.jp2" for leaf in range(expected_leaves)]
        if len(names) != expected_leaves or set(names) != set(expected_names):
            raise ValueError(f"{name}: page scan member set changed")
        excluded_ids = ([0, 208, 209, 581, 582, 583, 584, 585] if name.endswith("01wats")
                        else [0, 306, 307, 495, 496, 497, 498, 499])
        excluded_hashes = {leaf: sha(archive.read(f"{name}_jp2/{name}_{leaf:04d}.jp2"))
                           for leaf in excluded_ids}
    scan = ET.parse(paths["scandata.xml"]).getroot()
    leaves = scan.findall("./pageData/page")
    if len(leaves) != expected_leaves or [int(p.get("leafNum", "-1")) for p in leaves] != list(range(expected_leaves)):
        raise ValueError(f"{name}: scan leaf envelope changed")
    included = [p for p in leaves if p.findtext("addToAccessFormats") == "true"]
    excluded = [p for p in leaves if p.findtext("addToAccessFormats") != "true"]
    objects = ET.parse(paths["ocr.xml"]).getroot().findall("./BODY/OBJECT")
    with fitz.open(paths["scan.pdf"]) as pdf:
        pdf_count = len(pdf)
    if len(included) != expected_pdf or len(objects) != expected_pdf or pdf_count != expected_pdf:
        raise ValueError(f"{name}: included/PDF/OCR count changed")
    derived = {}
    if name.endswith("02wats"):
        witness_path = root / "sources/watson-theological-institutes-ia/deleted-pages-tesseract.json"
        witness = json.loads(witness_path.read_bytes())
        if witness.get("contract") != "ocd-watson-ia-derived-ocr-v1":
            raise ValueError("scan-only derived witness contract changed")
        derived = {int(row["leaf"]): row for row in witness["pages"]}
        if set(derived) != {306, 307}:
            raise ValueError("scan-only derived leaf set changed")
        for leaf, row in derived.items():
            if (row["source_member"] != f"{name}_jp2/{name}_{leaf:04d}.jp2"
                or row["source_jp2_sha256"] != excluded_hashes[leaf]
                or sha(row["raw_tesseract_text"].encode("utf-8")) != row["raw_text_sha256"]):
                raise ValueError(f"derived OCR source/text binding changed at {leaf}")
    by_leaf = {}
    for pdf_index, (page, obj) in enumerate(zip(included, objects, strict=True), 1):
        leaf = int(page.get("leafNum", "-1"))
        param = obj.find("./PARAM[@name='PAGE']")
        actual = param.get("value", "") if param is not None else ""
        if actual != f"{name}_{leaf:04d}.djvu":
            raise ValueError(f"{name}: OCR/PDF leaf mapping differs at page {pdf_index}")
        row = {"pdf_page": pdf_index, "leaf": leaf, "source_kind": "ia-ocr-xml",
               "page_type": page.findtext("pageType") or "",
               "printed_label": page.findtext("pageNumber") or "",
               "ocr_param": actual, "scan_member": f"{name}_jp2/{name}_{leaf:04d}.jp2"}
        by_leaf[leaf] = ((obj, None), row)
    for leaf, witness in derived.items():
        page = leaves[leaf]
        if page.findtext("addToAccessFormats") != "false" or page.findtext("pageType") != "Delete":
            raise ValueError(f"derived leaf {leaf} is no longer excluded")
        by_leaf[leaf] = ((None, witness), {
            "pdf_page": None, "leaf": leaf, "source_kind": "scan-derived-tesseract",
            "page_type": "Delete", "printed_label": witness["printed_page"],
            "ocr_param": None, "scan_member": witness["source_member"],
            "scan_sha256": witness["source_jp2_sha256"],
            "derived_text_sha256": witness["raw_text_sha256"]})
    duplicate_map = {208: 210, 209: 211} if name.endswith("01wats") else {}
    aligned = []
    rows = []
    for page in leaves:
        leaf = int(page.get("leafNum"))
        if leaf in by_leaf:
            item, row = by_leaf[leaf]
            aligned.append(item)
            rows.append(row)
    def disposition(page: ET.Element) -> str:
        leaf = int(page.get("leafNum"))
        if leaf in derived:
            return "unique textual scan represented by uncorrected Tesseract OCR"
        if leaf in duplicate_map:
            return f"duplicate scan of included leaf {duplicate_map[leaf]}"
        return "nontextual cover edge" if page.findtext("pageType") == "Delete" else "calibration card"
    facts = {"name": name, "source_members": members, "page_scan_members": expected_leaves,
             "leaf_count": len(leaves), "included_count": len(included),
             "represented_count": len(rows),
             "ocr_object_count": len(objects), "pdf_page_count": pdf_count,
             "excluded_leaves": [{"leaf": int(p.get("leafNum", "-1")),
                                  "page_type": p.findtext("pageType") or "",
                                  "access": p.findtext("addToAccessFormats") or "",
                                  "scan_member": f"{name}_jp2/{name}_{int(p.get('leafNum', '-1')):04d}.jp2",
                                  "scan_sha256": excluded_hashes[int(p.get("leafNum", "-1"))],
                                  "disposition": disposition(p)} for p in excluded]}
    return aligned, rows, facts

def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "watson-theological-institutes-1825-1826-ia-review")
    header = el(root, "teiHeader")
    desc = el(header, "fileDesc")
    title = el(desc, "titleStmt")
    el(title, "title").text = "Theological Institutes"
    el(title, "author").text = "Richard Watson"
    pub = el(desc, "publicationStmt")
    el(pub, "publisher").text = "Open Christian Data"
    el(el(pub, "availability", status="restricted"), "p").text = (
        "Nonaccepted OCR review candidate. Scan collation, rights, human acceptance, and publication remain open.")
    src = el(desc, "sourceDesc")
    for name, roman, year, _, _, _, _ in VOLUMES:
        bibl = el(src, "bibl")
        el(bibl, "title").text = "Theological Institutes"
        el(bibl, "author").text = "Richard Watson"
        el(bibl, "biblScope", unit="volume").text = roman
        el(bibl, "date", when=year).text = year
        el(bibl, "idno", type="internet-archive").text = name
    el(el(header, "encodingDesc"), "p").text = (
        "Every access-format scan leaf and two additional unique scan-only text pages are in source order. "
        "Wording is uncorrected Internet Archive or local Tesseract OCR, not a scan-collated transcription. "
        "Duplicate, cover-edge, and calibration leaves are separately accounted.")
    el(el(header, "revisionDesc", status="candidate"), "change", when="2026-09-25").text = (
        "Two-volume scan-indexed OCR handoff for review; no textual acceptance.")
    group = el(el(root, "text"), "group")
    account = {"contract": "ocd-watson-ia-accountability-v1",
               "mapping": "PDF page (1-based) equals the ordinal of access-format leaves; OCR OBJECT PAGE names its scandata leaf. Scan-only leaves 306/307 in volume II use JP2 and a separately bound Tesseract witness.",
               "volumes": []}
    totals = {"pages": 0, "paragraphs": 0, "lines": 0, "explicit_ocr_heads": 0}
    for vi, (name, roman, year, front_end, back_start, leaves, pdfs) in enumerate(VOLUMES, 1):
        aligned, page_rows, facts = read_volume(manifest.repository_root, name, leaves, pdfs)
        volume = el(group, "text", n=roman, type="volume")
        sections = {kind: el(volume, kind) for kind in ("front", "body", "back")}
        volume_account = {**facts, "year": year, "front_last_leaf": front_end,
                          "back_first_leaf": back_start, "pages": []}
        for (obj, derived_witness), row in zip(aligned, page_rows, strict=True):
            leaf = row["leaf"]
            section = section_for(leaf, front_end, back_start)
            page = el(sections[section], "div", type="scan-page", n=str(leaf),
                      subtype=row["page_type"].lower().replace(" ", "-"))
            page.set(XML_ID, f"v{vi}-leaf-{leaf:04d}")
            if derived_witness is None:
                facs = f"{BASE}/{name}/scan.pdf#page={row['pdf_page']}"
                pb_id = f"v{vi}-pdf-{row['pdf_page']:04d}"
                source_paragraphs = [
                    (pi, ["".join(word.text or "" for word in line.findall("./WORD"))
                          for line in para.findall("./LINE")],
                     sum(len(line.findall("./WORD")) for line in para.findall("./LINE")))
                    for pi, para in enumerate(obj.findall(".//PARAGRAPH"), 1)]
            else:
                facs = f"zip:{BASE}/{name}/page-scans.zip!/{row['scan_member']}"
                pb_id = f"v{vi}-jp2-{leaf:04d}"
                source_paragraphs = [(pi, lines, sum(len(line.split()) for line in lines))
                                     for pi, lines in enumerate(derived_paragraphs(
                                         derived_witness["raw_tesseract_text"]), 1)]
            pb = el(page, "pb", n=row["printed_label"] or str(leaf), facs=facs)
            pb.set(XML_ID, pb_id)
            para_rows = []
            for pi, line_texts, word_count in source_paragraphs:
                if not line_texts or not any(line.strip() for line in line_texts):
                    continue
                value = " ".join(" ".join(line_texts).split())
                is_head = len(line_texts) == 1 and heading(value)
                wrapper = el(page, "div", type="ocr-heading" if is_head else "ocr-paragraph")
                node = el(wrapper, "head" if is_head else "p")
                node.set(XML_ID, f"v{vi}-leaf-{leaf:04d}-p{pi:03d}")
                for li, line_text in enumerate(line_texts, 1):
                    el(node, "lb", n=str(li)).tail = line_text
                totals["paragraphs"] += 1
                totals["lines"] += len(line_texts)
                totals["explicit_ocr_heads"] += int(is_head)
                para_rows.append({"index": pi, "id": node.get(XML_ID),
                                  "line_count": len(line_texts),
                                  "word_count": word_count,
                                  "line_sha256": [sha(line.encode("utf-8")) for line in line_texts],
                                  "role": "head" if is_head else "p"})
            volume_account["pages"].append({**row, "section": section,
                                             "paragraph_count": len(para_rows),
                                             "paragraphs": para_rows})
            totals["pages"] += 1
        account["volumes"].append(volume_account)
    account["totals"] = totals
    provenance = {"contract": "ocd-watson-ia-provenance-v1", "status": "nonaccepted",
                  "primary_witness": "Retained 1825 and 1826 scanned PDFs",
                  "text_handoff": "Retained Internet Archive DjVu OCR XML plus local Tesseract for volume II leaves 306/307; uncorrected",
                  "source_id": manifest.record["source_id"],
                  "mapping_profile": "sources/watson-theological-institutes-ia/reconstruction-profile.json"}
    unresolved = [
        {"id": "watson-scan-wording-uncollated", "kind": "text-fidelity", "status": "unresolved",
         "affected_represented_pages": 1072,
         "detail": "OCR wording has not been fully collated against page images. Visible title-page errors mean this cannot be an accepted scan-faithful transcription."},
        {"id": "watson-heading-classification", "kind": "structure", "status": "unresolved",
         "detail": "Explicit chapter/part labels receive head elements; other headings and page-spanning paragraphs require human scan review."},
    ]
    readme = ("# Watson, Theological Institutes (1825/1826)\n\n"
              "Complete two-volume, nonaccepted OCR review candidate. The retained PDF scans are "
              "textual authority. TEI represents every included scan leaf and two unique scan-only "
              "volume II leaves in order, with PDF or JP2 source IDs, "
              "front/body/back placement, and uncorrected OCR paragraph and line text. The source "
               "accounting records every retained file, included page, and excluded scandata leaf. "
              "All source JP2 leaf images are retained and hash-bound. Volume I's two mid-volume "
              "Delete leaves visually duplicate included rescans. Volume II's two mid-volume Delete "
              "leaves are unique printed pages 298-299 and are represented by uncorrected, hash-bound "
              "local Tesseract OCR. End leaves show cover edges or calibration cards. "
              "None of the 1072 represented pages is fully text-collated. "
              "No textual fidelity, acceptance, rights, or publication claim follows.\n").encode("utf-8")
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True),
            "source-accountability.json": canonical(account),
            "provenance.json": canonical(provenance),
            "unresolved.jsonl": b"".join(canonical(row) for row in unresolved),
            "README.source.md": readme}

_convert.converter_id = "ocd-watson-theological-institutes-ia-scan-indexed-ocr"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()

