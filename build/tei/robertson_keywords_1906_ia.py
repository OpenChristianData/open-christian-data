"""Scan-indexed, nonaccepted OCR candidate for Robertson's 1906 Keywords."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Mapping

import fitz
from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest
from build.lib.reviewed_json_fields import verify_reviewed_fields

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE = "raw/internet-archive/keywords-in-the-teaching-of-jesus/keywordsinteachi01robe"
MEMBERS = ("ocr.xml", "ocr.txt", "abbyy.xml.gz", "scan.pdf", "scandata.xml",
           "metadata.json", "member-inventory.tsv", "acquisition-receipt.json")
CHAPTERS = ((15, "I"), (29, "II"), (45, "III"), (60, "IV"),
            (82, "V"), (97, "VI"), (113, "VII"))
BACK = ((126, "scripture-index"), (129, "topical-index"),
        (131, "bibliography"), (133, "appended-material"))
EXPLICIT_HEADINGS = {(11, 1), (13, 1), (15, 3), (29, 1), (45, 1),
                     (60, 1), (82, 1), (97, 1), (113, 1),
                     (126, 1), (129, 1), (131, 1)}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _el(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{tag}", **attrs)


def _group(leaf: int) -> tuple[str, str]:
    if leaf < 15:
        return "front", "preliminaries"
    if leaf < 126:
        return "body", next(roman for start, roman in reversed(CHAPTERS)
                            if leaf >= start)
    return "back", next(name for start, name in reversed(BACK) if leaf >= start)


def _source(root: Path):
    paths = {name: resolve_repo_path(root, f"{SOURCE}/{name}") for name in MEMBERS}
    files = [{"path": f"{SOURCE}/{name}", "bytes": paths[name].stat().st_size,
              "sha256": _sha(paths[name].read_bytes()),
              "role": "OCR text handoff" if name == "ocr.xml" else
                      "scan witness" if name == "scan.pdf" else
                      "alternate OCR witness" if name in {"ocr.txt", "abbyy.xml.gz"} else
                      "source support"} for name in MEMBERS]
    leaves = ET.parse(paths["scandata.xml"]).getroot().findall("./pageData/page")
    if len(leaves) != 138 or [p.get("leafNum") for p in leaves] != [
        str(i) for i in range(138)]:
        raise ValueError("scandata leaf envelope changed")
    included = [p for p in leaves if p.findtext("addToAccessFormats") == "true"]
    excluded = [p for p in leaves if p.findtext("addToAccessFormats") != "true"]
    if ([int(p.get("leafNum", "-1")) for p in included] != list(range(1, 137))
            or [int(p.get("leafNum", "-1")) for p in excluded] != [0, 137]
            or any(p.findtext("pageType") != "Color Card" for p in excluded)):
        raise ValueError("access-format leaf selection changed")
    objects = ET.parse(paths["ocr.xml"]).getroot().findall("./BODY/OBJECT")
    with fitz.open(paths["scan.pdf"]) as pdf:
        pdf_count = len(pdf)
    if len(objects) != 136 or pdf_count != 136:
        raise ValueError("PDF/OCR page count changed")
    for number, obj in enumerate(objects, 1):
        marker = obj.find("./PARAM[@name='PAGE']")
        if marker is None or marker.get("value") != f"keywordsinteachi01robe_{number:04d}.djvu":
            raise ValueError(f"OCR/scan alignment changed at page {number}")
    return files, included, excluded, objects


def _scan_map(manifest: SourceManifest, objects: list[ET.Element]):
    path = manifest.authority_path("scan-grounded-correction-map")
    content = path.read_bytes()
    record = json.loads(content)
    if (record.get("contract") != "ocd-robertson-keywords-scan-correction-map-v1"
            or record.get("source_id") != manifest.record.get("source_id")
            or record.get("work_id") != manifest.record.get("work_id")):
        raise ValueError("scan correction map identity binding changed")
    has_review = any(row['name'] == 'reviewed-authored-text-fields' for row in manifest.record['authorities'])
    if has_review or "text_review" in record:
        if record.get('text_review') != {'authority': 'reviewed-authored-text-fields'}:
            raise ValueError('Bound reviewed authored fields require their explicit map binding')
        review = json.loads(manifest.authority_path(record["text_review"]["authority"]).read_bytes())
        verify_reviewed_fields(record, review, record["scan_authority"]["sha256"])
    replacements = {}
    removed = {}
    toc_slots = set()

    def source_word(leaf: int, paragraph: int, line: int, word: int):
        try:
            return (objects[leaf - 1].findall(".//PARAGRAPH")[paragraph - 1]
                    .findall("./LINE")[line - 1].findall("./WORD")[word - 1])
        except IndexError as exc:
            raise ValueError(
                f"scan-map carrier outside OCR at {leaf}:{paragraph}:{line}:{word}") from exc

    def suppress(leaf: int, selector: Mapping[str, int], label: str,
                 target: set | None = None):
        for wi in range(selector["first_word"], selector["last_word"] + 1):
            source_word(leaf, selector["paragraph"], selector["line"], wi)
            key = (leaf, selector["paragraph"], selector["line"], wi)
            removed.setdefault(key, set()).add(label)
            if target is not None:
                target.add(key)

    for item in record.get("replacements", []):
        key = (item["page_ordinal"], item["paragraph"], item["line"], item["word"])
        word = source_word(*key)
        if (word.text or "") != item["ocr_form"]:
            raise ValueError(f"scan-map source form changed: {item['id']}")
        if key in replacements:
            raise ValueError(f"duplicate scan-map replacement: {item['id']}")
        replacements[key] = item["scan_reading"]
    for item in record.get("marginal_headings", []):
        for selector in item.get("carriers", []):
            suppress(item["page_ordinal"], selector, f"heading:{item['id']}")
    for item in record.get("tables_of_contents", []):
        for carrier in item.get("header_carriers", []):
            suppress(item["page_ordinal"], carrier["selector"],
                     f"toc:{item['id']}", toc_slots)
        for row in item.get("rows", []):
            for name in ("chapter_carrier", "entry_carrier", "page_carrier"):
                suppress(item["page_ordinal"], row[name], f"toc:{item['id']}", toc_slots)
    for item in record.get("carrier_gaps", []):
        for selector in item.get("carriers", []):
            suppress(item["page_ordinal"], selector, f"gap:{item['id']}")
    for item in record.get("paratext", []):
        for selector in item.get("source_carriers", []):
            suppress(item["page_ordinal"], selector, f"paratext:{item['id']}")
    return record, _sha(content), replacements, removed, toc_slots


def _carrier_words(objects: list[ET.Element], leaf: int,
                   selector: Mapping[str, int]) -> list[dict[str, object]]:
    records = []
    for wi in range(selector["first_word"], selector["last_word"] + 1):
        word = (objects[leaf - 1].findall(".//PARAGRAPH")[selector["paragraph"] - 1]
                .findall("./LINE")[selector["line"] - 1].findall("./WORD")[wi - 1])
        records.append({"paragraph": selector["paragraph"], "line": selector["line"],
                        "word": wi, "text": word.text or "", "coords": word.get("coords")})
    return records


def _collation_evidence(record: Mapping[str, object], map_sha: str,
                        objects: list[ET.Element], map_path: str) -> dict[str, object]:
    replacements = []
    for item in record.get("replacements", []):
        selector = {"paragraph": item["paragraph"], "line": item["line"],
                    "first_word": item["word"], "last_word": item["word"]}
        replacements.append({**item, "selector": selector,
                             "source_carriers": _carrier_words(objects, item["page_ordinal"], selector)})
    headings = []
    for item in record.get("marginal_headings", []):
        headings.append({**item, "source_carriers": [
            {"selector": selector, "words": _carrier_words(objects, item["page_ordinal"], selector)}
            for selector in item.get("carriers", [])]})
    contents = []
    for item in record.get("tables_of_contents", []):
        rows = []
        for row in item.get("rows", []):
            evidence = {"chapter": row["chapter"], "title": row["title"], "page": row["page"]}
            for name in ("chapter_carrier", "entry_carrier", "page_carrier"):
                selector = row[name]
                evidence[name] = {"selector": selector,
                                  "words": _carrier_words(objects, item["page_ordinal"], selector)}
            rows.append(evidence)
        contents.append({**item, "source_rows": rows,
                         "header_evidence": [
                             {"selector": header["selector"], "scan_reading": header["scan_reading"],
                              "words": _carrier_words(objects, item["page_ordinal"], header["selector"])}
                             for header in item.get("header_carriers", [])]})
    gaps = [{**item, "source_carriers": [
        {"selector": selector, "words": _carrier_words(objects, item["page_ordinal"], selector)}
        for selector in item.get("carriers", [])]} for item in record.get("carrier_gaps", [])]
    paratext = [{**item, "source_carriers": [
        {"selector": selector, "words": _carrier_words(objects, item["page_ordinal"], selector)}
        for selector in item.get("source_carriers", [])]} for item in record.get("paratext", [])]
    return {"contract": "ocd-robertson-keywords-scan-collation-v1",
            "map_path": map_path,
            "map_sha256": map_sha, "method": record["method"],
            "replacements": replacements, "marginal_headings": headings,
            "tables_of_contents": contents, "carrier_gaps": gaps,
            "explicit_gaps": record.get("explicit_gaps", []),
            "column_layout_pages": record.get("column_layout_pages", []),
            "paratext": paratext,
            "visual_review": record.get("visual_review", {})}


def _coords(word: ET.Element) -> tuple[int, int, int, int]:
    raw = word.get("coords", "")
    try:
        values = tuple(int(value) for value in raw.split(","))
    except ValueError as exc:
        raise ValueError(f"invalid OCR coordinates: {raw!r}") from exc
    if len(values) != 4:
        raise ValueError(f"OCR word has no complete coordinates: {raw!r}")
    return values


def _plain(paragraph: ET.Element) -> str:
    return "".join(word.text or "" for line in paragraph.findall("./LINE")
                   for word in line.findall("./WORD"))


def _layout_header(paragraph: ET.Element) -> bool:
    normalized = " ".join(_plain(paragraph).split()).upper()
    return normalized in {"INDEX OF SCRIPTURE REFERENCES", "TOPICAL INDEX",
                          "BIBLIOGRAPHY", "PAGE"} or (
        normalized.isdigit() and len(normalized) <= 4)


def _column_split(paragraphs: list[ET.Element]) -> tuple[float, tuple[int, int]]:
    centers = []
    min_x = max_x = None
    for paragraph in paragraphs:
        if _layout_header(paragraph):
            continue
        for word in paragraph.findall("./LINE/WORD"):
            x0, _y1, x1, _y0 = _coords(word)
            centers.append((x0 + x1) / 2)
            min_x = x0 if min_x is None else min(min_x, x0)
            max_x = x1 if max_x is None else max(max_x, x1)
    if len(centers) < 4 or min_x is None or max_x is None or max_x <= min_x:
        raise ValueError("two-column page has insufficient OCR geometry")
    ordered = sorted(set(centers))
    mid, span = (min_x + max_x) / 2, max_x - min_x
    candidates = [(right - left, (left + right) / 2)
                  for left, right in zip(ordered, ordered[1:])
                  if right - left >= span * .04
                  and abs((left + right) / 2 - mid) <= span * .08]
    if not candidates:
        candidates = [(right - left, (left + right) / 2)
                      for left, right in zip(ordered, ordered[1:])]
    if not candidates:
        raise ValueError("two-column page has no OCR-coordinate separation")
    _gap, split = max(candidates, key=lambda row: (row[0], -abs(row[1] - mid)))
    return split, (min_x, max_x)


def _line_text(leaf: int, pi: int, li: int, line: ET.Element,
               replacements: Mapping[tuple[int, int, int, int], str],
               removed: Mapping[tuple[int, int, int, int], set[str]],
               column: int | None = None, split: float | None = None) -> tuple[str, int]:
    chunks, omitted = [], 0
    for wi, word in enumerate(line.findall("./WORD"), 1):
        slot = (leaf, pi, li, wi)
        if column is not None:
            if split is None:
                raise ValueError("column split is missing")
            x0, _y1, x1, _y0 = _coords(word)
            if (1 if (x0 + x1) / 2 <= split else 2) != column:
                continue
        if slot in removed:
            omitted += 1
        else:
            chunks.append(replacements.get(slot, word.text or ""))
    return "".join(chunks), omitted


def _append_paragraph(parent: etree._Element, leaf: int, pi: int,
                      paragraph: ET.Element, role: str, suffix: str,
                      replacements: Mapping[tuple[int, int, int, int], str],
                      removed: Mapping[tuple[int, int, int, int], set[str]],
                      column: int | None = None, split: float | None = None) -> list[str]:
    wrapper = _el(parent, "div", type="ocr-heading" if role == "head" else "ocr-paragraph")
    p = _el(wrapper, role)
    p.set(XML_ID, f"leaf-{leaf:04d}-p{pi:03d}{suffix}")
    hashes = []
    for li, line in enumerate(paragraph.findall("./LINE"), 1):
        value, _omitted = _line_text(leaf, pi, li, line, replacements, removed, column, split)
        hashes.append(_sha(value.encode("utf-8")))
        lb = _el(p, "lb", n=str(li))
        if value:
            lb.tail = value
    return hashes


def _contents_table(parent: etree._Element, item: Mapping[str, object]) -> None:
    wrapper = _el(parent, "div", type="contents-table")
    wrapper.set(XML_ID, item["id"])
    table = _el(wrapper, "list", type="contents")
    _el(table, "head").text = "PAGE"
    for data in item["rows"]:
        row = _el(table, "item")
        _el(row, "label").text = f"CHAPTER {data['chapter']}"
        _el(row, "seg", type="title").text = data["title"]
        _el(row, "seg", type="page").text = data["page"]


def _gap_note(parent: etree._Element, item_id: str, description: str,
              disposition: str | None = None) -> None:
    if disposition == "nonliterary-exclusion":
        note = _el(parent, "note", type="source-disposition", n=item_id)
        note.text = description
        return
    note = _el(parent, "note", type="source-gap", n=item_id)
    gap = _el(note, "gap", reason="unreadable-or-absent", extent="unknown")
    gap.tail = " " + description


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    files, leaves, excluded, objects = _source(manifest.repository_root)
    correction_map, map_sha, replacements, removed, toc_slots = _scan_map(manifest, objects)
    by_path = {row["path"]: row["sha256"] for row in files}
    if correction_map["scan_authority"]["sha256"] != by_path[f"{SOURCE}/scan.pdf"]:
        raise ValueError("scan correction map binds a different PDF")
    if correction_map["ocr_authority"]["sha256"] != by_path[f"{SOURCE}/ocr.xml"]:
        raise ValueError("scan correction map binds a different OCR witness")
    margin_by_page: dict[int, list[Mapping[str, object]]] = {}
    for item in correction_map["marginal_headings"]:
        margin_by_page.setdefault(item["page_ordinal"], []).append(item)
    toc_by_page = {item["page_ordinal"]: item for item in correction_map["tables_of_contents"]}
    columns = {item["page_ordinal"]: item for item in correction_map["column_layout_pages"]}
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "robertson-keywords-1906-ia-review")
    header = _el(root, "teiHeader")
    desc = _el(_el(header, "fileDesc"), "titleStmt")
    _el(desc, "title").text = "Keywords in the Teaching of Jesus"
    _el(desc, "author").text = "A. T. Robertson"
    file_desc = header.find(f".//{{{TEI}}}titleStmt/..")
    publication = _el(file_desc, "publicationStmt")
    _el(publication, "publisher").text = "Open Christian Data"
    _el(_el(publication, "availability", status="restricted"), "p").text = (
        "Nonaccepted OCR review candidate; rights and publication remain open.")
    source_desc = _el(file_desc, "sourceDesc")
    bibl = _el(source_desc, "bibl")
    _el(bibl, "title").text = "Keywords in the Teaching of Jesus"
    _el(bibl, "author").text = "A. T. Robertson"
    _el(bibl, "date", when="1906").text = "1906"
    _el(bibl, "idno", type="internet-archive").text = "keywordsinteachi01robe"
    _el(_el(header, "encodingDesc"), "p").text = (
        "All 136 access-format pages are represented from the retained DjVuXML. "
        "A scan-bound correction map records verified readings, marginal headings, "
        "the contents table, two-column back matter, paratext, and uncertain gaps. "
        "Original OCR remains immutable; alternate OCR is not used as reading text.")
    _el(_el(header, "revisionDesc", status="candidate"), "change",
        when="2026-10-02").text = "Scan-grounded single-title TEI reconstruction for technical review."
    text = _el(root, "text")
    sections = {name: _el(text, name) for name in ("front", "body", "back")}
    groups = {"front": {}, "body": {}, "back": {}}
    for leaf in range(1, 137):
        section, key = _group(leaf)
        if key not in groups[section]:
            groups[section][key] = _el(sections[section], "div",
                type="chapter" if section == "body" else key,
                **({"n": key} if section == "body" else {}))
    account = {"contract": "ocd-robertson-keywords-ia-accountability-v1",
        "source_id": manifest.record["source_id"],
        "work_id": manifest.record["work_id"],
        "textual_form_id": manifest.record["textual_form_id"],
        "edition_id": manifest.record["edition_id"],
        "acquisition_id": manifest.record["acquisition_id"],
        "source_members": files,
        "leaf_count": 138,
        "excluded_leaves": [{"leaf": int(p.get("leafNum", "-1")),
            "page_type": p.findtext("pageType"), "disposition": "nontextual color calibration card"}
            for p in excluded],
        "scan_collation": _collation_evidence(correction_map, map_sha, objects,
            manifest.authority_path("scan-grounded-correction-map").relative_to(manifest.repository_root).as_posix()), "pages": []}
    totals = {"pages": 0, "paragraphs": 0, "lines": 0}
    for number, (leaf_data, obj) in enumerate(zip(leaves, objects, strict=True), 1):
        leaf = int(leaf_data.get("leafNum", "-1"))
        section, key = _group(leaf)
        page = _el(groups[section][key], "div", type="scan-page", n=str(leaf))
        page.set(XML_ID, f"leaf-{leaf:04d}")
        label = leaf_data.findtext("pageNumber") or ""
        _el(page, "pb", n=label or str(leaf), facs=f"{SOURCE}/scan.pdf#page={number}")
        paragraphs = obj.findall(".//PARAGRAPH")
        for gap in correction_map.get("carrier_gaps", []):
            if gap["page_ordinal"] == leaf:
                _gap_note(page, gap["id"], gap["description"])
        carrier_gap_pages = {gap["page_ordinal"]
                             for gap in correction_map.get("carrier_gaps", [])}
        for gap in correction_map.get("explicit_gaps", []):
            if gap.get("page_ordinal") == leaf or leaf in gap.get("page_ordinals", []):
                if leaf not in carrier_gap_pages and not any(
                        node.get("n") == gap["id"] for node in page.findall(f"{{{TEI}}}note")):
                    _gap_note(page, gap["id"], gap["description"], gap.get("disposition"))
        for record in correction_map.get("paratext", []):
            if record["page_ordinal"] == leaf:
                note = _el(page, "note", type="printed-paratext", n=record["id"])
                note.text = record.get("scan_reading") or (
                    f"{record['label']} [barcode {record['barcode']}]")
        page_account = {"pdf_page": number, "leaf": leaf,
            "page_type": leaf_data.findtext("pageType") or "", "printed_label": label,
            "section": section, "group": key,
            "ocr_param": f"keywordsinteachi01robe_{leaf:04d}.djvu", "paragraphs": []}
        totals["pages"] += 1
        layout = columns.get(leaf)
        split, bounds = _column_split(paragraphs) if layout else (None, None)
        left = _el(page, "div", type="source-column", n="1") if layout else None
        right = _el(page, "div", type="source-column", n="2") if layout else None
        toc = toc_by_page.get(leaf)
        toc_done = False
        headings = sorted(margin_by_page.get(leaf, []), key=lambda item: (
            item["target_paragraph"], item["carriers"][0]["line"],
            item["carriers"][0]["first_word"], item["id"]))
        for pi, paragraph in enumerate(paragraphs, 1):
            role = "head" if (leaf, pi) in EXPLICIT_HEADINGS else (
                "head" if layout and " ".join(_plain(paragraph).split()).upper() in {
                    "INDEX OF SCRIPTURE REFERENCES", "TOPICAL INDEX", "BIBLIOGRAPHY"} else "p")
            for heading in headings:
                if heading["target_paragraph"] == pi:
                    note = _el(page, "note", place="margin", type="heading", n=heading["id"])
                    note.set("corresp", f"#leaf-{leaf:04d}-p{pi:03d}")
                    note.text = heading["scan_reading"]
            source_lines = ["".join(word.text or "" for word in line.findall("./WORD"))
                            for line in paragraph.findall("./LINE")]
            source_hashes = [_sha(value.encode("utf-8")) for value in source_lines]
            source_count = sum(len(line.findall("./WORD")) for line in paragraph.findall("./LINE"))
            all_toc = bool(source_count) and all(
                (leaf, pi, li, wi) in toc_slots
                for li, line in enumerate(paragraph.findall("./LINE"), 1)
                for wi, _word in enumerate(line.findall("./WORD"), 1))
            if all_toc:
                if not toc_done:
                    _contents_table(page, toc)
                    toc_done = True
                output_hashes = [_sha(b"") for _ in source_lines]
                placement = "contents-table"
                output_count = 0
                column_hashes = None
            elif layout and role == "p" and not _layout_header(paragraph):
                left_hashes = _append_paragraph(left, leaf, pi, paragraph, "p", "-col1",
                    replacements, removed, 1, split)
                right_hashes = _append_paragraph(right, leaf, pi, paragraph, "p", "-col2",
                    replacements, removed, 2, split)
                # A paragraph can occupy one or both physical columns; discard empty side wrappers.
                left_wrapper, right_wrapper = left[-1], right[-1]
                left_words = sum(1 for line in paragraph.findall("./LINE")
                    for word in line.findall("./WORD")
                    if (_coords(word)[0] + _coords(word)[2]) / 2 <= split)
                right_words = source_count - left_words
                if not left_words:
                    left.remove(left_wrapper)
                if not right_words:
                    right.remove(right_wrapper)
                output_hashes = [left_hashes, right_hashes]
                placement, column_hashes = "columns", {"1": left_hashes, "2": right_hashes}
                output_count = sum(1 for li, line in enumerate(paragraph.findall("./LINE"), 1)
                    for wi, _word in enumerate(line.findall("./WORD"), 1)
                    if (leaf, pi, li, wi) not in removed)
            else:
                output_hashes = _append_paragraph(page, leaf, pi, paragraph, role, "",
                                                   replacements, removed)
                placement = "page"
                column_hashes = None
                output_count = sum(1 for li, line in enumerate(paragraph.findall("./LINE"), 1)
                    for wi, _word in enumerate(line.findall("./WORD"), 1)
                    if (leaf, pi, li, wi) not in removed)
            page_account["paragraphs"].append({"index": pi, "role": role,
                "lines": len(source_lines), "line_sha256": source_hashes,
                "output_line_sha256": output_hashes, "source_word_count": source_count,
                "output_word_count": output_count, "placement": placement,
                **({"column_line_sha256": column_hashes} if column_hashes is not None else {})})
            totals["paragraphs"] += 1
            totals["lines"] += len(source_lines)
        if toc and not toc_done:
            _contents_table(page, toc)
        if layout:
            page_account["column_layout"] = {"kind": layout["kind"], "columns": 2,
                "split_x": split, "coordinate_bounds": list(bounds),
                "algorithm": "largest WORD-center gap near the center of retained OCR text extents"}
            page.remove(left)
            page.remove(right)
            page.append(left)
            page.append(right)
        account["pages"].append(page_account)
    account["totals"] = totals
    provenance = {"contract": "ocd-robertson-keywords-ia-provenance-v1",
        "source_id": manifest.record["source_id"], "work_id": manifest.record["work_id"],
        "textual_form_id": manifest.record["textual_form_id"],
        "edition_id": manifest.record["edition_id"],
        "acquisition_id": manifest.record["acquisition_id"],
        "status": "nonaccepted", "primary_witness": f"{SOURCE}/scan.pdf",
        "text_witness": f"{SOURCE}/ocr.xml",
        "scan_correction_map": {"path": account["scan_collation"]["map_path"],
                                "sha256": account["scan_collation"]["map_sha256"]},
        "qualification": "Technical reconstruction does not establish human acceptance, rights clearance, or publication authorization."}
    unresolved = [
        {"id": "robertson-keywords-zero-word-pages", "kind": "text-gap", "status": "unresolved",
         "affected_pages": [3, 4, 6, 10, 14, 133],
         "detail": "The retained DjVuXML has no WORD carriers on these pages; page markers and gaps are preserved and image-only text is not inferred."},
        {"id": "robertson-keywords-handwritten-marks", "kind": "paratext-gap", "status": "unresolved",
         "affected_pages": [7, 8, 9, 135],
         "detail": "Handwritten marks are unreadable or ambiguous in the retained scan and remain explicit gaps."},
        {"id": "robertson-keywords-barcode-graphic", "kind": "graphic-gap", "status": "unresolved",
         "affected_pages": [136],
         "detail": "The printed library label and number are represented from the scan; the barcode graphic itself has no textual transcription."}]
    readme = ("# Robertson, Keywords in the Teaching of Jesus (1906)\\n\\n"
        "Nonaccepted scan-grounded technical candidate for one complete titled work. "
        "All 136 access-format pages, seven chapters, two indexes, bibliography, and "
        "appended matter are represented. The scan-bound correction map records "
        "verified text, marginal headings, the contents table, two-column layout, "
        "paratext, and genuine gaps. Original OCR remains unchanged. Human acceptance, "
        "rights clearance, and publication are separate open decisions.\\n").encode("utf-8")
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True),
            "source-accountability.json": _json(account), "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(row) for row in unresolved),
            "README.source.md": readme}


_convert.converter_id = "ocd-robertson-keywords-1906-ia-scan-indexed-ocr"
_convert.converter_version = "2"
_convert.implementation_path = Path(__file__).resolve()
