"""Independent Robertson 1922 source-to-TEI oracle; no converter import."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from typing import Mapping

import fitz
from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SCAN_NS = "{http://archive.org/scribe/xml}"
SOURCE = "raw/internet-archive/harmony-of-the-gospels/harmonyofgospels00robeuoft"
SCAN_REF = "../../../../raw/internet-archive/harmony-of-the-gospels/harmonyofgospels00robeuoft/scan.pdf"
CLOSURE = (
    "build/tei/robertson_harmony_1922_oracle.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def import_closure_sha256(root: Path) -> str:
    return _sha(_json([{"path": path, "sha256": _sha((root / path).read_bytes())}
                      for path in CLOSURE]))


def check(manifest: SourceManifest, tei_bytes: bytes, account_bytes: bytes) -> dict[str, object]:
    """Compare stdlib source traversal with actual TEI hierarchy and tokens."""
    source_path = resolve_repo_path(manifest.repository_root, f"{SOURCE}/ocr.xml")
    source = ET.parse(source_path).getroot()
    if source.tag != "DjVuXML" or len(source) != 1 or source[0].tag != "BODY":
        raise ValueError("oracle: unexpected source XML envelope")
    body = source[0]
    if [item.tag for item in body] != ["OBJECT", "MAP"] * 362:
        raise ValueError("oracle: source page/map order differs")
    tei = etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True))
    if tei.tag != NS + "TEI":
        raise ValueError("oracle: candidate is not TEI")
    content = tei.find(f"{NS}text/{NS}body/{NS}div")
    if content is None or content.get("type") != "accessible-scan-leaf-sequence":
        raise ValueError("oracle: missing accessible leaf sequence")
    target_pages = list(content)
    if len(target_pages) != 362:
        raise ValueError("oracle: candidate page count differs")
    account = json.loads(account_bytes)
    if (account.get("contract") != "ocd-robertson-harmony-1922-accountability-v1" or
        len(account.get("pages", [])) != 362):
        raise ValueError("oracle: accountability envelope differs")
    totals: Counter[str] = Counter()
    no_ocr: list[int] = []

    def check_para(source_para: ET.Element, target_para: etree._Element,
                   number: str, counts: Counter[str], leaf: int) -> None:
        if target_para.tag != NS + "p" or target_para.get("n") != number:
            raise ValueError(f"oracle: paragraph identity differs on leaf {leaf}")
        counts["paragraphs"] += 1
        lines = list(source_para)
        if any(line.tag != "LINE" for line in lines):
            raise ValueError(f"oracle: unexpected source paragraph child on leaf {leaf}")
        target_children = list(target_para)
        cursor = 0
        for line_number, source_line in enumerate(lines, 1):
            if (cursor >= len(target_children) or
                target_children[cursor].tag != NS + "lb" or
                target_children[cursor].get("n") != str(line_number)):
                raise ValueError(f"oracle: line boundary/order differs on leaf {leaf}")
            cursor += 1
            counts["lines"] += 1
            words = list(source_line)
            if not words or any(word.tag != "WORD" for word in words):
                raise ValueError(f"oracle: unexpected source line/word on leaf {leaf}")
            for word_number, word in enumerate(words, 1):
                if cursor >= len(target_children):
                    raise ValueError(f"oracle: omitted word on leaf {leaf}")
                target_word = target_children[cursor]
                cursor += 1
                tail = " " if (word_number < len(words) and word.text and
                               not word.text[-1].isspace()) else None
                if (target_word.tag != NS + "w" or
                    target_word.get("n") != str(word_number) or
                    target_word.get("rend") !=
                        f"coords:{word.get('coords')} confidence:{word.get('x-confidence')}" or
                    target_word.text != word.text or target_word.tail != tail):
                    raise ValueError(f"oracle: word text/position/order differs on leaf {leaf}")
                counts["words"] += 1
        if cursor != len(target_children):
            raise ValueError(f"oracle: invented paragraph content on leaf {leaf}")

    for leaf in range(1, 363):
        obj = body[(leaf - 1) * 2]
        source_map = body[(leaf - 1) * 2 + 1]
        source_id = f"harmonyofgospels00robeuoft_{leaf:04d}.djvu"
        param = {part.get("name"): part.get("value") for part in obj.findall("PARAM")}
        if (param.get("PAGE") != source_id or source_map.get("name") != source_id or
            param.get("DPI") is None or obj.get("width") is None or obj.get("height") is None):
            raise ValueError(f"oracle: source scan identity differs on leaf {leaf}")
        hidden = obj.find("HIDDENTEXT")
        if hidden is None:
            raise ValueError(f"oracle: missing hidden-text envelope on leaf {leaf}")
        source_children = list(hidden)
        if any(c.tag not in {"PAGECOLUMN", "PARAGRAPH"} for c in source_children):
            raise ValueError(f"oracle: unexpected source page child on leaf {leaf}")
        page = target_pages[leaf - 1]
        if (page.tag != NS + "div" or page.get("type") != "scan-page" or
            page.get("n") != f"{leaf:04d}" or page.get(XML_ID) != f"robe-p{leaf:04d}"):
            raise ValueError(f"oracle: page identity/order differs at leaf {leaf}")
        page_children = list(page)
        if (not page_children or page_children[0].tag != NS + "pb" or
            page_children[0].get("n") != f"{leaf:04d}" or
            page_children[0].get("facs") != f"{SCAN_REF}#page={leaf}"):
            raise ValueError(f"oracle: page facsimile milestone differs at leaf {leaf}")
        target_children = page_children[1:]
        if not source_children:
            no_ocr.append(leaf)
            if (len(target_children) != 2 or target_children[0].tag != NS + "p" or
                len(target_children[0]) != 1 or target_children[0][0].tag != NS + "gap" or
                target_children[0][0].get("reason") != "notTranscribed" or
                target_children[1].tag != NS + "figure" or
                target_children[1].get("type") != ("map" if leaf == 10 else "scan-image") or
                len(target_children[1]) != 1 or
                target_children[1][0].tag != NS + "graphic" or
                target_children[1][0].get("url") != f"{SCAN_REF}#page={leaf}"):
                raise ValueError(f"oracle: no-OCR leaf image/gap disposition differs at leaf {leaf}")
        elif len(target_children) != len(source_children):
            raise ValueError(f"oracle: source-child count/order differs at leaf {leaf}")
        counts: Counter[str] = Counter()
        col_number = 0
        direct_number = 0
        for source_child, target_child in zip(source_children, target_children):
            if source_child.tag == "PARAGRAPH":
                direct_number += 1
                counts["direct_paragraphs"] += 1
                if (target_child.tag != NS + "div" or
                    target_child.get("type") != "source-direct-paragraph" or
                    target_child.get("n") != str(direct_number) or len(target_child) != 1):
                    raise ValueError(f"oracle: direct paragraph attachment differs on leaf {leaf}")
                check_para(source_child, target_child[0], "1", counts, leaf)
                continue
            col_number += 1
            if (target_child.tag != NS + "div" or
                target_child.get("type") != "source-page-column" or
                target_child.get("n") != str(col_number) or
                target_child.get(XML_ID) != f"robe-p{leaf:04d}-c{col_number:02d}"):
                raise ValueError(f"oracle: column order/identity differs on leaf {leaf}")
            counts["columns"] += 1
            regions = list(source_child)
            if any(r.tag != "REGION" for r in regions) or len(target_child) != len(regions):
                raise ValueError(f"oracle: region grouping differs on leaf {leaf}")
            for region_number, (source_region, target_region) in enumerate(zip(regions, target_child), 1):
                if (target_region.tag != NS + "div" or
                    target_region.get("type") != "source-region" or
                    target_region.get("n") != str(region_number)):
                    raise ValueError(f"oracle: region identity differs on leaf {leaf}")
                counts["regions"] += 1
                paragraphs = list(source_region)
                if (any(p.tag != "PARAGRAPH" for p in paragraphs) or
                    len(target_region) != len(paragraphs)):
                    raise ValueError(f"oracle: paragraph grouping differs on leaf {leaf}")
                for para_number, (source_para, target_para) in enumerate(zip(paragraphs, target_region), 1):
                    check_para(source_para, target_para, str(para_number), counts, leaf)
        totals.update(counts)
        expected_row = {"leaf": leaf, "source_page": source_id,
                        "width": obj.get("width"), "height": obj.get("height"),
                        "dpi": param.get("DPI"), "counts": dict(sorted(counts.items())),
                        "disposition": "OCR text represented" if source_children else
                                       "no OCR text; scan leaf retained"}
        if account["pages"][leaf - 1] != expected_row:
            raise ValueError(f"oracle: page accountability differs on leaf {leaf}")
    expected = {"columns": 2077, "regions": 2077, "direct_paragraphs": 2684,
                "paragraphs": 10096, "lines": 25045, "words": 144689}
    if dict(totals) != expected or account.get("counts") != expected:
        raise ValueError("oracle: complete OCR carrier counts differ")
    if (account.get("accessible_scan_leaves") != 362 or
        account.get("provider_imagecount") != 366 or
        account.get("excluded_trailer_leaves") != [
            {"leaf": n, "type": kind, "disposition": "nonaccess calibration card; not literary text"}
            for n, kind in ((364, "Color Card"), (365, "Color Card"),
                            (366, "White Card"), (367, "White Card"))
        ]):
        raise ValueError("oracle: scandata exclusion accounting differs")
    if len(no_ocr) != 21:
        raise ValueError("oracle: no-OCR leaf census differs")
    return {"pages": 362, "no_ocr_leaves": no_ocr, "counts": expected}


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    tei_bytes = candidate.member_bytes("content.tei.xml")
    account_bytes = candidate.member_bytes("source-accountability.json")
    result = check(manifest, tei_bytes, account_bytes)
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_id") != manifest.record.get("source_id"):
        raise ValueError("oracle: candidate status/source differs")
    if candidate.member_bytes("unresolved.jsonl") != b"":
        raise ValueError("oracle: unexpected unresolved exclusion")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("status") != "nonaccepted" or provenance.get("ocr_xml_sha256") != "6756513e32994bf9823d230f37f6d1c4a8f7216e6bbc13ef0eb38af52274ad1c":
        raise ValueError("oracle: provenance differs")
    pdf_path = manifest.authority_path("scan-pdf")
    if not (candidate.path / SCAN_REF).resolve(strict=True).samefile(pdf_path):
        raise ValueError("oracle: TEI facsimile route does not resolve to retained scan")
    if len(fitz.open(pdf_path)) != 362:
        raise ValueError("oracle: scan PDF page count differs")
    with ZipFile(manifest.authority_path("scandata")) as z:
        if z.testzip() is not None:
            raise ValueError("oracle: scandata archive CRC failure")
        scan_members = [{"name": item.filename, "bytes": item.file_size,
                         "crc32": f"{item.CRC:08x}"} for item in z.infolist()]
        scan = ET.fromstring(z.read("scandata.xml"))
    pages = scan.findall(f".//{SCAN_NS}page")
    if (len(pages) != 366 or
        [int(p.get("leafNum", "0")) for p in pages if p.findtext(f"{SCAN_NS}addToAccessFormats") == "true"] != list(range(1, 363)) or
        [(int(p.get("leafNum", "0")), p.findtext(f"{SCAN_NS}pageType"))
         for p in pages if p.findtext(f"{SCAN_NS}addToAccessFormats") == "false"] !=
        [(364, "Color Card"), (365, "Color Card"), (366, "White Card"), (367, "White Card")]):
        raise ValueError("oracle: independent scandata inclusion/exclusion differs")
    number_map = json.loads(manifest.authority_path("page-numbers").read_bytes())
    if [p.get("leafNum") for p in number_map.get("pages", [])] != list(range(1, 363)):
        raise ValueError("oracle: page-number map differs")
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    if (profile.get("contract") != "ocd-robertson-harmony-1922-profile-v1" or
        profile.get("expected_counts") != result["counts"] or
        profile.get("no_ocr_leaves") != result["no_ocr_leaves"] or
        [{key: row[key] for key in ("name", "bytes", "crc32")}
         for row in profile.get("scandata_archive_members", [])] != scan_members):
        raise ValueError("oracle: source profile differs")
    xsd_path = manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not schema.validate(etree.ElementTree(etree.fromstring(tei_bytes))):
        raise ValueError(f"oracle: TEI P5 schema failure: {schema.error_log.last_error}")
    facts = MechanicalFacts(
        _sha(Path(__file__).read_bytes()),
        import_closure_sha256(manifest.repository_root),
        _sha(_json({"contract": "ocd-source-member-set-v1", "members": sorted(
            [{"name": a["name"], "path": a["path"], "bytes": a["bytes"], "sha256": a["sha256"]}
             for a in manifest.record["authorities"] if a["role"] == "primary-source"],
            key=lambda item: (str(item["path"]), str(item["name"]))
        )})),
        _sha(manifest.authority_path("reconstruction-profile").read_bytes()),
        _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        _sha(xsd_path.read_bytes()),
        _sha(manifest.authority_path("validation-policy").read_bytes()),
        (),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-robertson-harmony-1922-independent-layout-oracle"
_oracle.oracle_version = "1"
_oracle.implementation_path = Path(__file__).resolve()

