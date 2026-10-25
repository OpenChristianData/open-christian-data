"""Source-bound Robertson 1922 DjVuXML to readable, page-structured TEI.

The retained OCR is uncorrected. Source PAGECOLUMN/REGION/PARAGRAPH/LINE/WORD
boundaries are represented without guessing cross-Gospel alignment.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping
from zipfile import ZipFile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE = "raw/internet-archive/harmony-of-the-gospels/harmonyofgospels00robeuoft"
OCR_SHA = "6756513e32994bf9823d230f37f6d1c4a8f7216e6bbc13ef0eb38af52274ad1c"
PDF_SHA = "bf6295dd1473f058c780cc57a3ecb5668ddd8b4b777e409ac49cb0b544ae49cf"
SCANDATA_NS = {"s": "http://archive.org/scribe/xml"}
SCAN_REF = "../../../../raw/internet-archive/harmony-of-the-gospels/harmonyofgospels00robeuoft/scan.pdf"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _e(parent: etree._Element, name: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attrs)


def _source(manifest: SourceManifest) -> tuple[etree._Element, list[etree._Element]]:
    manifest.verify()
    xml_path = resolve_repo_path(manifest.repository_root, f"{SOURCE}/ocr.xml")
    if manifest.authority_path("ocr-xml") != xml_path:
        raise ValueError("OCR XML authority route changed")
    xml_bytes = xml_path.read_bytes()
    if _sha(xml_bytes) != OCR_SHA:
        raise ValueError("Robertson OCR XML digest changed")
    doc = etree.fromstring(xml_bytes, etree.XMLParser(resolve_entities=False, no_network=True))
    if doc.tag != "DjVuXML" or len(doc) != 1 or doc[0].tag != "BODY":
        raise ValueError("unexpected DjVuXML envelope")
    body = doc[0]
    if len(body) != 724 or [x.tag for x in body] != ["OBJECT", "MAP"] * 362:
        raise ValueError("OCR page/map envelope changed")
    archive = manifest.authority_path("scandata")
    with ZipFile(archive) as zip_file:
        if zip_file.testzip() is not None:
            raise ValueError("scandata archive CRC failure")
        scan = etree.fromstring(zip_file.read("scandata.xml"),
                               etree.XMLParser(resolve_entities=False, no_network=True))
    pages = scan.xpath(".//s:page", namespaces=SCANDATA_NS)
    if len(pages) != 366:
        raise ValueError("scandata page inventory changed")
    accessible = [p for p in pages if p.findtext("s:addToAccessFormats", namespaces=SCANDATA_NS) == "true"]
    excluded = [p for p in pages if p.findtext("s:addToAccessFormats", namespaces=SCANDATA_NS) == "false"]
    if [int(p.get("leafNum", "0")) for p in accessible] != list(range(1, 363)):
        raise ValueError("accessible scandata leaves differ from PDF/OCR")
    if [(p.get("leafNum"), p.findtext("s:pageType", namespaces=SCANDATA_NS))
        for p in excluded] != [("364", "Color Card"), ("365", "Color Card"),
                              ("366", "White Card"), ("367", "White Card")]:
        raise ValueError("scandata trailer exclusions changed")
    metadata = json.loads(manifest.authority_path("metadata").read_bytes())
    page_numbers = json.loads(manifest.authority_path("page-numbers").read_bytes())
    if (str(metadata.get("metadata", {}).get("imagecount")) != "366" or
        [p.get("leafNum") for p in page_numbers.get("pages", [])] != list(range(1, 363))):
        raise ValueError("provider imagecount or page-number inventory changed")
    return body, pages


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    body, scan_pages = _source(manifest)
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "robertson-harmony-1922-ocr-candidate")
    header = _e(root, "teiHeader")
    desc = _e(header, "fileDesc")
    titles = _e(desc, "titleStmt")
    _e(titles, "title").text = "A Harmony of the Gospels for Students of the Life of Christ"
    _e(titles, "author").text = "A. T. Robertson"
    resp = _e(titles, "respStmt")
    _e(resp, "resp").text = "Based on the Broadus Harmony"
    _e(resp, "name").text = "John Albert Broadus"
    publication = _e(desc, "publicationStmt")
    _e(publication, "publisher").text = "Open Christian Data"
    _e(_e(publication, "availability", status="restricted"), "p").text = (
        "Nonaccepted OCR-based review candidate. Scan collation, rights, human "
        "acceptance, and publication remain separate decisions."
    )
    bibl = _e(_e(desc, "sourceDesc"), "bibl")
    _e(bibl, "title").text = "A Harmony of the Gospels for Students of the Life of Christ"
    _e(bibl, "author").text = "A. T. Robertson"
    _e(bibl, "pubPlace").text = "New York"
    _e(bibl, "publisher").text = "George H. Doran Company"
    _e(bibl, "date").text = "1922"
    _e(bibl, "idno", type="internet-archive-item").text = "harmonyofgospels00robeuoft"
    _e(bibl, "idno", type="retained-scan-sha256").text = PDF_SHA
    _e(bibl, "idno", type="retained-ocr-xml-sha256").text = OCR_SHA
    _e(_e(header, "encodingDesc"), "p").text = (
        "The 362 accessible scan leaves are represented in order. DjVuXML page, "
        "page-column, direct paragraph, region, paragraph, line and word order is retained. Word "
        "coordinates and confidence are in rendition attributes. Missing terminal "
        "word spaces are supplied only for readable display; word text remains "
        "exact. No parallel-passage alignment or OCR correction is inferred. "
        "Four nonaccess trailer cards are inventoried outside the literary text."
    )
    _e(_e(header, "revisionDesc", status="candidate"), "change", when="2026-09-25").text = (
        "Source-bound, nonaccepted OCR reconstruction for review."
    )
    sequence = _e(_e(_e(root, "text"), "body"), "div", type="accessible-scan-leaf-sequence")
    rows: list[dict[str, object]] = []
    totals: Counter[str] = Counter()
    for leaf in range(1, 363):
        obj = body[(leaf - 1) * 2]
        page_map = body[(leaf - 1) * 2 + 1]
        source_id = f"harmonyofgospels00robeuoft_{leaf:04d}.djvu"
        params = {p.get("name"): p.get("value") for p in obj.findall("PARAM")}
        if params.get("PAGE") != source_id or page_map.get("name") != source_id:
            raise ValueError(f"page/map identity mismatch at leaf {leaf}")
        hidden = obj.find("HIDDENTEXT")
        if hidden is None or any(child.tag not in {"PAGECOLUMN", "PARAGRAPH"} for child in hidden):
            raise ValueError(f"unexpected hidden text at leaf {leaf}")
        page = _e(sequence, "div", type="scan-page", n=f"{leaf:04d}")
        page.set(XML_ID, f"robe-p{leaf:04d}")
        _e(page, "pb", n=f"{leaf:04d}", facs=f"{SCAN_REF}#page={leaf}")
        counts: Counter[str] = Counter()
        if not len(hidden):
            _e(_e(page, "p"), "gap", reason="notTranscribed")
            _e(_e(page, "figure", type="map" if leaf == 10 else "scan-image"),
               "graphic", url=f"{SCAN_REF}#page={leaf}")

        def add_paragraph(parent: etree._Element, paragraph: etree._Element, number: str) -> None:
            para = _e(parent, "p", n=number)
            counts["paragraphs"] += 1
            if any(child.tag != "LINE" for child in paragraph):
                raise ValueError(f"unexpected paragraph child at leaf {leaf}")
            for line_num, line in enumerate(paragraph.findall("LINE"), 1):
                _e(para, "lb", n=str(line_num))
                counts["lines"] += 1
                words = line.findall("WORD")
                if not words or len(words) != len(line):
                    raise ValueError(f"unexpected OCR line at leaf {leaf}")
                for word_num, word in enumerate(words, 1):
                    if set(word.attrib) != {"coords", "x-confidence"} or word.text is None:
                        raise ValueError(f"unexpected OCR word at leaf {leaf}")
                    out = _e(para, "w", n=str(word_num),
                             rend=f"coords:{word.get('coords')} confidence:{word.get('x-confidence')}")
                    out.text = word.text
                    if word_num < len(words) and not word.text[-1].isspace():
                        out.tail = " "
                    counts["words"] += 1

        col_num = 0
        direct_num = 0
        for child in hidden:
            if child.tag == "PARAGRAPH":
                direct_num += 1
                counts["direct_paragraphs"] += 1
                wrapper = _e(page, "div", type="source-direct-paragraph", n=str(direct_num))
                add_paragraph(wrapper, child, "1")
                continue
            col_num += 1
            col = _e(page, "div", type="source-page-column", n=str(col_num))
            col.set(XML_ID, f"robe-p{leaf:04d}-c{col_num:02d}")
            counts["columns"] += 1
            if any(part.tag != "REGION" for part in child):
                raise ValueError(f"unexpected page-column child at leaf {leaf}")
            for reg_num, region in enumerate(child.findall("REGION"), 1):
                reg = _e(col, "div", type="source-region", n=str(reg_num))
                counts["regions"] += 1
                if any(part.tag != "PARAGRAPH" for part in region):
                    raise ValueError(f"unexpected region child at leaf {leaf}")
                for para_num, paragraph in enumerate(region.findall("PARAGRAPH"), 1):
                    add_paragraph(reg, paragraph, str(para_num))
        totals.update(counts)
        rows.append({"leaf": leaf, "source_page": source_id, "width": obj.get("width"),
                     "height": obj.get("height"), "dpi": params.get("DPI"),
                     "counts": dict(sorted(counts.items())),
                     "disposition": "OCR text represented" if len(hidden) else "no OCR text; scan leaf retained"})
    if (len(rows) != 362 or totals != Counter(
        columns=2077, regions=2077, direct_paragraphs=2684, paragraphs=10096, lines=25045, words=144689
    )):
        raise ValueError("Robertson OCR carrier inventory changed")
    accounting = {"contract": "ocd-robertson-harmony-1922-accountability-v1",
                  "source": SOURCE, "pdf_sha256": PDF_SHA, "ocr_xml_sha256": OCR_SHA,
                  "provider_imagecount": 366, "accessible_scan_leaves": 362,
                  "excluded_trailer_leaves": [
                      {"leaf": int(p.get("leafNum")), "type": p.findtext("s:pageType", namespaces=SCANDATA_NS),
                       "disposition": "nonaccess calibration card; not literary text"}
                      for p in scan_pages[362:]
                  ],
                  "counts": dict(sorted(totals.items())), "pages": rows}
    provenance = {"contract": "ocd-robertson-harmony-1922-provenance-v1",
                  "source": SOURCE, "scan_pdf_sha256": PDF_SHA, "ocr_xml_sha256": OCR_SHA,
                  "status": "nonaccepted"}
    readme = (
        "# Robertson, A Harmony of the Gospels (1922)\n\n"
        "This nonaccepted candidate maps all 362 accessible scan leaves, including "
        "front matter, harmony, appendices, and back matter, from retained IA "
        "DjVuXML to TEI in page order. It preserves every source-supplied "
        "page-column, direct paragraph, region, paragraph, line, and word; parallel Gospel alignment "
        "is not inferred. Scandata has 366 leaves: accessible leaves 1-362 and "
        "four nonaccess Color/White Card leaves 364-367, explicitly excluded from "
        "literary text. Twenty-one accessible leaves have no OCR text; their "
        "page images remain linked to the retained scan as figures, including the map on leaf 10, "
        "and remain "
        "scan-review loci. The OCR is uncorrected; print collation, CVW review, "
        "rights, human acceptance, and publication remain open.\n"
    ).encode("utf-8")
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True),
            "source-accountability.json": _json(accounting),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"",
            "README.source.md": readme}


_convert.converter_id = "ocd-robertson-harmony-1922-djvuxml-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()

