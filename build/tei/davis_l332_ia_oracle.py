"""Independent retained-carrier oracle for the Davis L332 OCR candidate.

The converter uses stdlib XML; this checker uses lxml, independently traverses
the retained source, and checks the actual readable TEI. Both share the same OCR
witness, so OCR-to-print fidelity remains unproven.
"""
from __future__ import annotations

import hashlib
import gzip
import json
import re
import tarfile
from pathlib import Path
from typing import Mapping

import fitz
from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BASE = "raw/internet-archive/beginners-grammar-greek-new-testament/beginnersgrammar00davi"
GROUPS = (
    ("front", "preliminaries", 1, 18),
    ("front", "contents", 19, 22),
    ("front", "part-i-divider", 23, 24),
    ("body", "part-i-lessons", 25, 220),
    ("body", "part-ii-supplement", 221, 246),
    ("back", "english-index", 247, 258),
    ("back", "vocabularies-divider", 259, 260),
    ("back", "greek-english-vocabulary", 261, 270),
    ("back", "english-greek-vocabulary", 271, 275),
    ("back", "end-material", 276, 280),
)
ZERO_OCR = [1, 3, 4, 6, 10, 16, 24, 222, 258, 260, 279]


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _parse(data: bytes) -> etree._Element:
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                   huge_tree=True))


def _need(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def _role(text: str, leaf: int, paragraph: int) -> str:
    upper = " ".join(text.strip().upper().split())
    headings = (
        "INTRODUCTION", "NOTE TO FIFTH EDITION", "PREFACE", "CONTENTS",
        "FART I: LESSONS", "PART II: SUPPLEMENT TO PART I",
        "ENGLISH INDEX", "VOCABULARIES", "GREEK-ENGLISH VOCABULARY",
        "ENGLISH-GREEK VOCABULARY",
    )
    return "head" if (upper in headings or re.fullmatch(r"LESSON [IVXLCDM]+", upper)
                      or (leaf, paragraph) in {(25, 3), (221, 2)}) else "p"


def check(root: Path, tei_bytes: bytes, account_bytes: bytes) -> dict[str, int]:
    source = lambda name: resolve_repo_path(root, f"{BASE}/{name}")
    scan = _parse(source("scandata.xml").read_bytes()).xpath("./pageData/page")
    _need(len(scan) == 284 and [p.get("leafNum") for p in scan] ==
          [str(i) for i in range(284)], "complete scandata image envelope")
    access = [p for p in scan if p.findtext("addToAccessFormats") == "true"]
    not_access = [p for p in scan if p.findtext("addToAccessFormats") != "true"]
    _need([p.get("leafNum") for p in access] == [str(i) for i in range(1, 281)],
          "280 access leaves")
    excluded = [(int(p.get("leafNum")), p.findtext("pageType")) for p in not_access]
    _need(excluded == [(0, "Delete"), (281, "Delete"),
                       (282, "Color Card"), (283, "Color Card")], "four excluded leaves")
    source_xml = _parse(source("ocr-djvu.xml").read_bytes())
    objects = source_xml.xpath("./BODY/OBJECT")
    with fitz.open(source("scan.pdf")) as pdf:
        _need(len(pdf) == 280, "280 PDF pages")
    _need(len(objects) == 280, "280 OCR objects")
    with gzip.open(source("ocr-abbyy.gz"), "rb") as stream:
        abbyy_pages = etree.parse(stream).xpath("//*[local-name()='page']")
    _need(len(abbyy_pages) == 284, "284 Abbyy original-leaf pages")
    account = json.loads(account_bytes)
    _need(account.get("contract") == "ocd-davis-l332-accountability-v1" and
          account.get("scan_leaves") == 284, "account contract/envelope")
    _need(account.get("excluded_leaves") == [
        {"leaf": n, "page_type": kind,
         "disposition": "outside PDF/OCR access sequence; original JP2 retained"}
        for n, kind in excluded], "excluded leaf accounting")
    with tarfile.open(source("original-pages.tar")) as archive:
        members = {m.name: m for m in archive if m.isfile()}
    expected_images = [
        {"leaf": n,
         "member": f"beginnersgrammar00davi_orig_jp2/beginnersgrammar00davi_orig_{n:04d}.jp2",
         "bytes": members[f"beginnersgrammar00davi_orig_jp2/beginnersgrammar00davi_orig_{n:04d}.jp2"].size}
        for n in range(284)
    ]
    _need(len(members) == 284 and account.get("original_jp2_images") == expected_images,
          "284 original JP2 carriers")
    tree = _parse(tei_bytes)
    _need(tree.tag == f"{{{TEI}}}TEI", "TEI root")
    text = tree.find(f"./{{{TEI}}}text")
    _need(text is not None and [n.tag for n in text] ==
          [f"{{{TEI}}}{s}" for s in ("front", "body", "back")], "front/body/back")
    actual_pages = []
    for section in ("front", "body", "back"):
        parent = text.find(f"{{{TEI}}}{section}")
        selected = [(group, first, last) for sec, group, first, last in GROUPS if sec == section]
        _need(parent is not None and len(parent) == len(selected), f"{section} group count")
        for idx, (group, first, last) in enumerate(selected):
            node = parent[idx]
            _need(node.tag == f"{{{TEI}}}div" and node.get("type") == group,
                  f"{section} group identity")
            pages = list(node)
            _need([p.get("n") for p in pages] == [str(i) for i in range(first, last + 1)] and
                  all(p.tag == f"{{{TEI}}}div" and p.get("type") == "scan-page"
                      for p in pages), f"{group} page order")
            actual_pages.extend((section, group, p) for p in pages)
    _need(len(actual_pages) == 280 and len(account.get("pages", [])) == 280,
          "page completeness")
    totals = {"pages": 280, "paragraphs": 0, "lines": 0, "words": 0}
    empty = []
    for ordinal, ((section, group, page), source_page, obj, row) in enumerate(
            zip(actual_pages, access, objects, account["pages"], strict=True), 1):
        marker = obj.xpath("./PARAM[@name='PAGE']")
        _need(len(marker) == 1 and marker[0].get("value") ==
              f"beginnersgrammar00davi_{ordinal:04d}.djvu", f"OCR marker {ordinal}")
        label = source_page.findtext("pageNumber") or ""
        image = expected_images[ordinal]
        _need(page.get(XML_ID) == f"leaf-{ordinal:04d}" and
              row.get("leaf") == ordinal and row.get("pdf_page") == ordinal and
              row.get("jp2_member") == image["member"] and
              row.get("printed_label") == label and
              row.get("page_type") == (source_page.findtext("pageType") or "") and
              row.get("section") == section and row.get("group") == group,
              f"page relationship {ordinal}")
        pb = page.find(f"{{{TEI}}}pb")
        _need(pb is not None and pb.get("n") == (label or str(ordinal)) and
              pb.get("facs") == f"{BASE}/scan.pdf#page={ordinal}" and
              list(page)[0] is pb, f"facsimile target {ordinal}")
        source_paras = obj.xpath(".//PARAGRAPH")
        wrappers = [node for node in list(page)[1:]
                    if node.tag == f"{{{TEI}}}div" and
                    node.get("type") in {"ocr-heading", "ocr-paragraph"}]
        source_rows = row.get("paragraphs", [])
        _need(len(source_paras) == len(wrappers) == len(source_rows),
              f"paragraph count {ordinal}")
        page_words = 0
        for pi, (para, wrapper, para_row) in enumerate(
                zip(source_paras, wrappers, source_rows, strict=True), 1):
            lines = para.xpath("./LINE")
            values = ["".join(word.text or "" for word in line.xpath("./WORD"))
                      for line in lines]
            words = sum(len(line.xpath("./WORD")) for line in lines)
            page_words += words
            role = _role(" ".join(values), ordinal, pi)
            _need(wrapper.tag == f"{{{TEI}}}div" and
                  wrapper.get("type") == ("ocr-heading" if role == "head" else "ocr-paragraph")
                  and len(wrapper) == 1, f"paragraph wrapper {ordinal}:{pi}")
            content = wrapper[0]
            _need(content.tag == f"{{{TEI}}}{role}" and
                  content.get(XML_ID) == f"leaf-{ordinal:04d}-p{pi:03d}" and
                  (content.text or "") == "", f"paragraph identity {ordinal}:{pi}")
            lbs = list(content)
            _need([(lb.tag, lb.get("n"), lb.tail or "") for lb in lbs] ==
                  [(f"{{{TEI}}}lb", str(li), value)
                   for li, value in enumerate(values, 1)],
                  f"OCR lines and wording {ordinal}:{pi}")
            _need(para_row == {"index": pi, "role": role,
                               "line_sha256": [_sha(v.encode("utf-8")) for v in values],
                               "words": words}, f"paragraph ledger {ordinal}:{pi}")
            totals["paragraphs"] += 1
            totals["lines"] += len(values)
            totals["words"] += words
        source_tables = abbyy_pages[ordinal].xpath(
            "./*[local-name()='block'][@blockType='Table']")
        alt_wrappers = [node for node in page
                        if node.tag == f"{{{TEI}}}div" and
                        node.get("type") == "alternate-ocr-layout"]
        table_ledger = row.get("abbyy_tables")
        _need(isinstance(table_ledger, list) and
              len(source_tables) == len(alt_wrappers) == len(table_ledger),
              f"Abbyy table count {ordinal}")
        for ti, (source_table, alt, ledger_rows) in enumerate(
                zip(source_tables, alt_wrappers, table_ledger, strict=True), 1):
            _need(len(alt) == 2 and alt[0].tag == f"{{{TEI}}}head" and
                  alt[0].text == "Alternate Abbyy table layout" and
                  alt[1].tag == f"{{{TEI}}}table" and
                  alt[1].get("n") == str(ti), f"alternate table identity {ordinal}:{ti}")
            source_rows = source_table.xpath("./*[local-name()='row']")
            rendered_rows = list(alt[1])
            _need(len(source_rows) == len(rendered_rows) == len(ledger_rows),
                  f"Abbyy row count {ordinal}:{ti}")
            for ri, (source_row, rendered_row, ledger_cells) in enumerate(
                    zip(source_rows, rendered_rows, ledger_rows, strict=True), 1):
                source_cells = source_row.xpath("./*[local-name()='cell']")
                rendered_cells = list(rendered_row)
                _need(rendered_row.tag == f"{{{TEI}}}row" and
                      len(source_cells) == len(rendered_cells) == len(ledger_cells),
                      f"Abbyy cells {ordinal}:{ti}:{ri}")
                for ci, (source_cell, rendered_cell, ledger_lines) in enumerate(
                        zip(source_cells, rendered_cells, ledger_cells, strict=True), 1):
                    lines = source_cell.xpath(".//*[local-name()='line']")
                    values = []
                    for line in lines:
                        chars = line.xpath(".//*[local-name()='charParams']")
                        value = "".join(
                            (" " if k and char.get("wordStart") == "true" else "")
                            + (char.text or "") for k, char in enumerate(chars))
                        values.append(value)
                    _need(rendered_cell.tag == f"{{{TEI}}}cell" and
                          [(lb.tag, lb.get("n"), lb.tail or "")
                           for lb in rendered_cell] ==
                          [(f"{{{TEI}}}lb", str(li), value)
                           for li, value in enumerate(values, 1)] and
                          ledger_lines == [_sha(v.encode("utf-8")) for v in values],
                          f"Abbyy table text {ordinal}:{ti}:{ri}:{ci}")
        gaps = [n for n in page if n.tag == f"{{{TEI}}}gap"]
        if page_words == 0:
            empty.append(ordinal)
            _need(len(gaps) == 1 and gaps[0].get("reason") == "ocr-unavailable" and
                  gaps[0].get("extent") == "unknown", f"OCR gap {ordinal}")
        else:
            _need(not gaps, f"invented OCR gap {ordinal}")
    _need(empty == ZERO_OCR, "known zero-word page set")
    _need(account.get("totals") == totals, "aggregate accounting")
    return totals


def _closure(root: Path) -> str:
    paths = ("build/tei/davis_l332_ia_oracle.py",
             "ocd_kernel/lib/storage_topology.py",
             "ocd_kernel/reconstruction/contract.py",
             "ocd_kernel/reconstruction/verifier.py")
    return _sha(_json([{"path": p, "sha256": _sha((root / p).read_bytes())}
                       for p in paths]))


def _primary_set(manifest: SourceManifest) -> str:
    members = sorted(({"name": r["name"], "path": r["path"], "bytes": r["bytes"],
                       "sha256": r["sha256"]} for r in manifest.record["authorities"]
                      if r["role"] == "primary-source"),
                     key=lambda r: (r["path"], r["name"]))
    _need(bool(members), "primary source missing")
    return members[0]["sha256"] if len(members) == 1 else _sha(_json(
        {"contract": "ocd-source-member-set-v1", "members": members}))


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    totals = check(manifest.repository_root, candidate.member_bytes("content.tei.xml"),
                   candidate.member_bytes("source-accountability.json"))
    _need(totals["pages"] == 280 and candidate.manifest.get("status") == "nonaccepted",
          "candidate status/page count")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    _need(provenance.get("status") == "nonaccepted" and
          provenance.get("source_id") == manifest.record["source_id"] and
          provenance.get("source_receipt_sha256") ==
          _sha(resolve_repo_path(manifest.repository_root,
                                 f"{BASE}/acquisition-receipt.json").read_bytes()),
          "provenance binding")
    unresolved = [json.loads(line) for line in candidate.member_bytes(
        "unresolved.jsonl").splitlines()]
    _need([r.get("id") for r in unresolved] ==
          ["davis-l332-scan-collation", "davis-l332-empty-ocr",
           "davis-l332-semantic-layout"] and
          unresolved[1].get("pages") == ZERO_OCR, "unresolved evidence")
    xsd = manifest.authority_path("tei-p5-xsd")
    validator = etree.XMLSchema(etree.parse(str(xsd)))
    parsed = etree.ElementTree(_parse(candidate.member_bytes("content.tei.xml")))
    _need(validator.validate(parsed), f"TEI P5 invalid: {validator.error_log.last_error}")
    facts = MechanicalFacts(
        _sha(Path(__file__).read_bytes()), _closure(manifest.repository_root),
        _primary_set(manifest),
        _sha(manifest.authority_path("reconstruction-profile").read_bytes()),
        _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        _sha(xsd.read_bytes()),
        _sha(manifest.authority_path("validation-policy").read_bytes()), ())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-davis-l332-independent-oracle"
_oracle.oracle_version = "1"
_oracle.implementation_path = Path(__file__).resolve()

