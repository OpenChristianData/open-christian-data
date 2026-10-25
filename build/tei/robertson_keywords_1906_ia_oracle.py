"""Independent scan-aware source-carrier check for Robertson's IA candidate."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

import fitz
from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BASE = "raw/internet-archive/keywords-in-the-teaching-of-jesus/keywordsinteachi01robe"
LAYOUT_HEADERS = {"INDEX OF SCRIPTURE REFERENCES", "TOPICAL INDEX", "BIBLIOGRAPHY"}
SOURCE_NAMES = {"ocr.xml", "ocr.txt", "abbyy.xml.gz", "scan.pdf", "scandata.xml",
                "metadata.json", "member-inventory.tsv", "acquisition-receipt.json"}
HEADING_POSITIONS = {(11, 1), (13, 1), (15, 3), (29, 1), (45, 1),
                     (60, 1), (82, 1), (97, 1), (113, 1),
                     (126, 1), (129, 1), (131, 1)}
GROUPS = (("front", "preliminaries", 1, 14),
          ("body", "I", 15, 28), ("body", "II", 29, 44),
          ("body", "III", 45, 59), ("body", "IV", 60, 81),
          ("body", "V", 82, 96), ("body", "VI", 97, 112),
          ("body", "VII", 113, 125),
          ("back", "scripture-index", 126, 128),
          ("back", "topical-index", 129, 130),
          ("back", "bibliography", 131, 132),
          ("back", "appended-material", 133, 136))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _parse(data: bytes) -> etree._Element:
    return etree.fromstring(
        data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def check(root: Path, tei_bytes: bytes, account_bytes: bytes) -> dict[str, int]:
    tree = _parse(tei_bytes)
    account = json.loads(account_bytes)
    _require(account.get("contract") == "ocd-robertson-keywords-ia-accountability-v1",
             "accountability contract")
    _require(tree.tag == f"{{{TEI}}}TEI", "TEI root")
    files = account.get("source_members", [])
    _require(len(files) == 8 and {Path(row.get("path", "")).name for row in files} == SOURCE_NAMES,
             "source member inventory")
    for row in files:
        path = row["path"]
        _require(path.startswith(BASE + "/"), "source member path")
        data = resolve_repo_path(root, path).read_bytes()
        _require(row["bytes"] == len(data) and row["sha256"] == _sha(data),
                 f"source member digest {path}")
    scan = _parse(resolve_repo_path(root, f"{BASE}/scandata.xml").read_bytes())
    scan_pages = scan.xpath("./pageData/page")
    _require(len(scan_pages) == 138 and
             [p.get("leafNum") for p in scan_pages] == [str(i) for i in range(138)],
             "scan leaf envelope")
    excluded = [p for p in scan_pages if p.findtext("addToAccessFormats") != "true"]
    _require([p.get("leafNum") for p in excluded] == ["0", "137"] and
             all(p.findtext("pageType") == "Color Card" for p in excluded),
             "excluded color leaves")
    _require(account.get("leaf_count") == 138 and
             account.get("excluded_leaves") == [
                 {"leaf": int(p.get("leafNum")), "page_type": p.findtext("pageType"),
                  "disposition": "nontextual color calibration card"}
                 for p in excluded], "excluded leaf accounting")
    access = [p for p in scan_pages if p.findtext("addToAccessFormats") == "true"]
    ocr = _parse(resolve_repo_path(root, f"{BASE}/ocr.xml").read_bytes())
    objects = ocr.xpath("./BODY/OBJECT")
    with fitz.open(resolve_repo_path(root, f"{BASE}/scan.pdf")) as pdf:
        pdf_count = len(pdf)
    _require(len(access) == len(objects) == pdf_count == 136 and
             [p.get("leafNum") for p in access] == [str(i) for i in range(1, 137)],
             "PDF/OCR/access page alignment")
    # Boundary expectations were read from the retained OCR before grouping pages.
    for leaf, ordinal, expected_label in (
            (15, 3, "CHAPTER I"), (29, 1, "CHAPTER II"),
            (45, 1, "CHAPTER III"), (60, 1, "CHAPTER IV"),
            (82, 1, "CHAPTER V"), (97, 1, "CHAPTER VI"),
            (113, 1, "CHAPTER VII"), (11, 1, "PREFACE"),
            (13, 1, "TABLE OF CONTENTS"), (126, 1, "INDEX OF SCRIPTURE REFERENCES"),
            (129, 1, "TOPICAL INDEX"), (131, 1, "BIBLIOGRAPHY")):
        paragraphs = objects[leaf - 1].xpath(".//PARAGRAPH")
        _require(len(paragraphs) >= ordinal, f"source heading carrier at {leaf}")
        actual_label = " ".join(
            "".join(word.text or "" for word in paragraph.xpath("./WORD"))
            for paragraph in paragraphs[ordinal - 1].xpath("./LINE"))
        _require(" ".join(actual_label.split()).upper() == expected_label,
                 f"source heading at {leaf}")
    text = tree.find(f"./{{{TEI}}}text")
    _require(text is not None and len(text) == 3, "TEI text sections")
    section_nodes = {n.tag.removeprefix(f"{{{TEI}}}"): n for n in text}
    _require(list(section_nodes) == ["front", "body", "back"], "front/body/back order")
    actual_pages = []
    for section, group, first, last in GROUPS:
        parent = section_nodes[section]
        idx = sum(1 for row in GROUPS if row[0] == section and row[2] < first)
        node = parent[idx]
        _require(node.tag == f"{{{TEI}}}div" and
                 node.get("type") == ("chapter" if section == "body" else group) and
                 (node.get("n") == group if section == "body" else node.get("n") is None),
                 f"{section} grouping {group}")
        pages = node.findall(f"{{{TEI}}}div")
        _require([p.get("n") for p in pages] == [str(n) for n in range(first, last + 1)],
                 f"{group} page order")
        actual_pages.extend((section, group, p) for p in pages)
    _require([len(section_nodes[s]) for s in ("front", "body", "back")] == [1, 7, 4] and
             len(actual_pages) == 136, "section/group completeness")
    rows = account.get("pages", [])
    _require(len(rows) == 136, "account page count")
    totals = {"pages": 0, "paragraphs": 0, "lines": 0}
    for pdf_page, (source_page, obj, page_tuple, row) in enumerate(
            zip(access, objects, actual_pages, rows, strict=True), 1):
        leaf = int(source_page.get("leafNum", "-1"))
        section, group, page = page_tuple
        marker = obj.xpath("./PARAM[@name='PAGE']")
        expected_marker = f"keywordsinteachi01robe_{leaf:04d}.djvu"
        _require(len(marker) == 1 and marker[0].get("value") == expected_marker,
                 f"OCR page marker at {leaf}")
        label = source_page.findtext("pageNumber") or ""
        _require(row.get("pdf_page") == pdf_page and row.get("leaf") == leaf and
                 row.get("page_type") == (source_page.findtext("pageType") or "") and
                 row.get("printed_label") == label and row.get("section") == section and
                 row.get("group") == group and row.get("ocr_param") == expected_marker,
                 f"page accounting at {leaf}")
        _require(page.get(XML_ID) == f"leaf-{leaf:04d}" and page.get("type") == "scan-page",
                 f"page identity at {leaf}")
        pb = page.find(f"{{{TEI}}}pb")
        _require(pb is not None and pb.get("n") == (label or str(leaf)) and
                 pb.get("facs") == f"{BASE}/scan.pdf#page={pdf_page}",
                 f"PDF page binding at {leaf}")
        expected = []
        for pi, paragraph in enumerate(obj.xpath(".//PARAGRAPH"), 1):
            lines = ["".join(word.text or "" for word in line.xpath("./WORD"))
                     for line in paragraph.xpath("./LINE")]
            expected.append((pi, lines))
        wrappers = page.findall(f"{{{TEI}}}div")
        _require(len(wrappers) == len(expected) == len(row.get("paragraphs", [])),
                 f"paragraph omission or duplication at {leaf}")
        _require(len(page) == 1 + len(wrappers), f"page extra content at {leaf}")
        for (pi, lines), wrapper, para_row in zip(expected, wrappers, row["paragraphs"],
                                                  strict=True):
            role = "head" if (leaf, pi) in HEADING_POSITIONS else "p"
            _require(wrapper.get("type") == ("ocr-heading" if role == "head" else "ocr-paragraph") and len(wrapper) == 1,
                     f"paragraph role at {leaf}:{pi}")
            p = wrapper[0]
            _require(p.tag == f"{{{TEI}}}{role}" and p.get(XML_ID) == f"leaf-{leaf:04d}-p{pi:03d}",
                     f"paragraph identity at {leaf}:{pi}")
            lbs = p.findall(f"{{{TEI}}}lb")
            _require(len(p) == len(lbs) == len(lines) and not (p.text or ""),
                     f"line omission at {leaf}:{pi}")
            _require([(lb.get("n"), lb.tail or "") for lb in lbs] ==
                     [(str(n), line) for n, line in enumerate(lines, 1)],
                     f"OCR wording/order at {leaf}:{pi}")
            _require(para_row == {"index": pi, "role": role, "lines": len(lines),
                                  "line_sha256": [_sha(line.encode("utf-8")) for line in lines]},
                     f"paragraph accounting at {leaf}:{pi}")
            totals["paragraphs"] += 1
            totals["lines"] += len(lines)
        totals["pages"] += 1
    _require(account.get("totals") == totals, "total accounting")
    return totals


def _closure(root: Path) -> str:
    paths = ("build/tei/robertson_keywords_1906_ia_oracle.py",
             "ocd_kernel/lib/storage_topology.py",
             "ocd_kernel/reconstruction/contract.py",
             "ocd_kernel/reconstruction/verifier.py")
    return _sha(_canonical([{"path": p, "sha256": _sha((root / p).read_bytes())}
                            for p in paths]))


def _source_set(manifest: SourceManifest) -> str:
    members = sorted(({"name": row["name"], "path": row["path"],
                       "bytes": row["bytes"], "sha256": row["sha256"]}
                      for row in manifest.record["authorities"]
                      if row["role"] == "primary-source"),
                     key=lambda row: (row["path"], row["name"]))
    _require(bool(members), "primary-source authority missing")
    if len(members) == 1:
        return members[0]["sha256"]
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    totals = check(manifest.repository_root, candidate.member_bytes("content.tei.xml"),
                   candidate.member_bytes("source-accountability.json"), source_manifest=manifest.record)
    _require(totals["pages"] == 136 and candidate.manifest.get("status") == "nonaccepted",
             "page count or candidate state")
    unresolved = [json.loads(line) for line in candidate.member_bytes(
        "unresolved.jsonl").splitlines()]
    _require([row.get("id") for row in unresolved] == [
        "robertson-keywords-zero-word-pages", "robertson-keywords-handwritten-marks",
        "robertson-keywords-barcode-graphic"] and
        all(row.get("status") == "unresolved" for row in unresolved) and
        unresolved[0].get("affected_pages") == [3, 4, 6, 10, 14, 133] and
        unresolved[1].get("affected_pages") == [7, 8, 9, 135] and
        unresolved[2].get("affected_pages") == [136],
        "unresolved gap statement")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    _require(provenance.get("status") == "nonaccepted" and
             provenance.get("source_id") == manifest.record["source_id"] and
             provenance.get("work_id") == manifest.record["work_id"] and
             all(provenance.get(key) == manifest.record.get(key)
                 for key in ("textual_form_id", "edition_id", "acquisition_id")) and
             provenance.get("scan_correction_map") == {
                 "path": manifest.authority_path("scan-grounded-correction-map").relative_to(manifest.repository_root).as_posix(),
                 "sha256": json.loads(candidate.member_bytes(
                     "source-accountability.json"))["scan_collation"]["map_sha256"]},
             "provenance binding")
    xsd = manifest.authority_path("tei-p5-xsd")
    validator = etree.XMLSchema(etree.parse(str(xsd)))
    document = etree.ElementTree(_parse(candidate.member_bytes("content.tei.xml")))
    _require(validator.validate(document),
             f"TEI schema invalid: {validator.error_log.last_error}")
    facts = MechanicalFacts(
        _sha(Path(__file__).read_bytes()), _closure(manifest.repository_root),
        _source_set(manifest),
        _sha(manifest.authority_path("reconstruction-profile").read_bytes()),
        _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        _sha(xsd.read_bytes()),
        _sha(manifest.authority_path("validation-policy").read_bytes()), ())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-robertson-keywords-1906-ia-independent-oracle"
_oracle.oracle_version = "2"
_oracle.implementation_path = Path(__file__).resolve()


def check(root: Path, tei_bytes: bytes, account_bytes: bytes, *, source_manifest=None) -> dict[str, int]:
    """Independently reconcile transformed TEI, source carriers, map and accounting."""
    account = json.loads(account_bytes)
    _require(account.get("contract") == "ocd-robertson-keywords-ia-accountability-v1",
             "accountability contract")
    manifest_path = root / "sources/structured-text/robertson-keywords-1906/source-manifest.json"
    manifest = source_manifest if source_manifest is not None else json.loads(manifest_path.read_bytes())
    authorities = {row["name"]: row for row in manifest["authorities"]}

    def bound_record(name):
        authority = authorities.get(name)
        _require(authority is not None, f"{name} identity authority")
        content = resolve_repo_path(root, authority["path"]).read_bytes()
        _require(authority.get("bytes") == len(content)
                 and authority.get("sha256") == _sha(content),
                 f"{name} identity digest")
        return json.loads(content)

    work = bound_record("canonical-work-identity")
    member_set = bound_record("retained-source-member-set")
    acquisition = bound_record("canonical-acquisition")
    identity = {key: manifest.get(key) for key in
                ("work_id", "textual_form_id", "edition_id", "acquisition_id")}
    form = next((row for row in work.get("textual_forms", [])
                 if row.get("textual_form_id") == identity["textual_form_id"]), None)
    edition = next((row for row in form.get("editions", [])
                    if row.get("edition_id") == identity["edition_id"]), None) if form else None
    member_authority = authorities["retained-source-member-set"]
    expected_member_set = (json.dumps({
        "contract": "ocd-retained-source-member-set-v1",
        "acquisition_id": identity["acquisition_id"],
        "edition_id": identity["edition_id"],
        "scope": acquisition.get("source_scope"),
        "members": [dict(row, position=index)
                    for index, row in enumerate(acquisition.get("retained_files", []), 1)],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    _require(work.get("work_id") == identity["work_id"]
             and form is not None and edition is not None
             and identity["acquisition_id"] in edition.get("acquisition_ids", [])
             and acquisition.get("acquisition_id") == identity["acquisition_id"]
             and acquisition.get("edition_id") == identity["edition_id"]
             and acquisition.get("source_path") == member_authority["path"]
             and acquisition.get("source_bytes") == len(expected_member_set)
             and acquisition.get("source_sha256") == _sha(expected_member_set)
             and member_set.get("contract") == "ocd-retained-source-member-set-v1"
             and member_set.get("edition_id") == identity["edition_id"]
             and member_set.get("acquisition_id") == identity["acquisition_id"]
             and member_set.get("members") == json.loads(expected_member_set)["members"],
             "canonical work/edition/acquisition linkage")
    _require(all(account.get(key) == value for key, value in identity.items())
             and account.get("source_id") == manifest.get("source_id"),
             "source accountability identity")
    map_authority = next((row for row in manifest["authorities"]
                          if row.get("name") == "scan-grounded-correction-map"), None)
    _require(map_authority is not None, "scan correction map authority")
    map_path = resolve_repo_path(root, map_authority["path"])
    map_bytes = map_path.read_bytes()
    scan_map = json.loads(map_bytes)
    map_sha = _sha(map_bytes)
    _require(scan_map.get("contract") == "ocd-robertson-keywords-scan-correction-map-v1"
             and scan_map.get("source_id") == manifest.get("source_id")
             and scan_map.get("work_id") == manifest.get("work_id"),
             "scan correction map identity")
    _require(map_authority.get("bytes") == len(map_bytes)
             and map_authority.get("sha256") == map_sha,
             "scan correction map manifest binding")
    scan_authority = next(row for row in manifest["authorities"]
                          if row.get("name") == "scan-pdf")
    _require(scan_map["scan_authority"]["sha256"] == scan_authority["sha256"],
             "scan correction map PDF binding")
    if "reviewed-authored-text-fields" in authorities or "text_review" in scan_map:
        _require(scan_map.get("text_review") == {"authority": "reviewed-authored-text-fields"},
                 "bound reviewed authored fields require their explicit map binding")
        review = bound_record(scan_map["text_review"]["authority"])
        _require(review.get("contract") == "ocd-reviewed-json-text-fields-v1"
                 and review.get("source_sha256") == scan_authority["sha256"]
                 and bool(review.get("fields")), "reviewed authored fields source binding")
        pointers = set()
        for field in review["fields"]:
            pointer = field["pointer"]
            _require(isinstance(pointer, str) and pointer.startswith("/")
                     and not re.search(r"~(?![01])", pointer), "invalid reviewed authored field pointer")
            _require(pointer not in pointers, "duplicate reviewed authored field")
            pointers.add(pointer)
            value = scan_map
            for component in pointer.lstrip("/").split("/"):
                key = component.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    _require(re.fullmatch(r"0|[1-9][0-9]*", key) is not None,
                             "invalid reviewed authored field list index")
                value = value[int(key)] if isinstance(value, list) else value[key]
            _require(value == field["reading"], "independently reviewed authored field " + pointer)
    visual_review = scan_map.get("visual_review", {})
    reviewed_pages = [page for item in visual_review.get("coverage", [])
                      for page in range(item["pdf_pages"][0], item["pdf_pages"][1] + 1)]
    _require(visual_review.get("contract") == "ocd-robertson-keywords-visual-page-review-v1"
             and visual_review.get("source_pdf_sha256") == scan_authority["sha256"]
             and sorted(reviewed_pages) == list(range(1, 137))
             and len(reviewed_pages) == len(set(reviewed_pages)),
             "complete scan-page review coverage")

    tree = _parse(tei_bytes)
    _require(tree.tag == f"{{{TEI}}}TEI"
             and len(tree.xpath("//tei:TEI", namespaces={"tei": TEI})) == 1,
             "single TEI root")
    _require(tree.xpath("string(./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)",
                        namespaces={"tei": TEI}) == "Keywords in the Teaching of Jesus"
             and tree.xpath("string(./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author)",
                            namespaces={"tei": TEI}) == "A. T. Robertson"
             and len(tree.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title",
                                namespaces={"tei": TEI})) == 1,
             "one complete titled work")
    text = tree.find(f"./{{{TEI}}}text")
    _require(text is not None and [node.tag for node in text] ==
             [f"{{{TEI}}}front", f"{{{TEI}}}body", f"{{{TEI}}}back"],
             "TEI front/body/back sections")

    source_rows = account.get("source_members", [])
    _require(len(source_rows) == 8
             and {Path(row.get("path", "")).name for row in source_rows} == SOURCE_NAMES,
             "retained source member inventory")
    for row in source_rows:
        _require(row["path"].startswith(BASE + "/"), "source member path")
        content = resolve_repo_path(root, row["path"]).read_bytes()
        _require(row["bytes"] == len(content) and row["sha256"] == _sha(content),
                 f"source member digest {row['path']}")
    scan = _parse(resolve_repo_path(root, f"{BASE}/scandata.xml").read_bytes())
    scan_pages = scan.xpath("./pageData/page")
    _require(len(scan_pages) == 138
             and [page.get("leafNum") for page in scan_pages] == [str(i) for i in range(138)],
             "scan leaf envelope")
    excluded = [page for page in scan_pages if page.findtext("addToAccessFormats") != "true"]
    _require([page.get("leafNum") for page in excluded] == ["0", "137"]
             and all(page.findtext("pageType") == "Color Card" for page in excluded),
             "excluded calibration leaves")
    _require(account.get("leaf_count") == 138 and account.get("excluded_leaves") == [
        {"leaf": int(page.get("leafNum")), "page_type": page.findtext("pageType"),
         "disposition": "nontextual color calibration card"} for page in excluded],
        "excluded leaf accounting")
    access = [page for page in scan_pages if page.findtext("addToAccessFormats") == "true"]
    objects = _parse(resolve_repo_path(root, f"{BASE}/ocr.xml").read_bytes()).xpath("./BODY/OBJECT")
    with fitz.open(resolve_repo_path(root, f"{BASE}/scan.pdf")) as pdf:
        pdf_count = len(pdf)
    _require(len(access) == len(objects) == pdf_count == 136
             and [page.get("leafNum") for page in access] == [str(i) for i in range(1, 137)],
             "PDF/OCR/access page alignment")
    _require(scan_map["scan_authority"]["sha256"] == _sha(
        resolve_repo_path(root, f"{BASE}/scan.pdf").read_bytes())
        and scan_map["ocr_authority"]["sha256"] == _sha(
            resolve_repo_path(root, f"{BASE}/ocr.xml").read_bytes()),
        "scan correction map source hashes")

    replacements = {}
    removed = {}
    toc_slots = set()

    def source_word(leaf: int, paragraph: int, line: int, word: int):
        try:
            return objects[leaf - 1].xpath(".//PARAGRAPH")[paragraph - 1].xpath("./LINE")[line - 1].xpath("./WORD")[word - 1]
        except IndexError as exc:
            raise ValueError(f"scan-map carrier outside OCR at {leaf}:{paragraph}:{line}:{word}") from exc

    def suppress(leaf: int, selector: Mapping[str, int], label: str, target: set | None = None):
        for wi in range(selector["first_word"], selector["last_word"] + 1):
            source_word(leaf, selector["paragraph"], selector["line"], wi)
            slot = (leaf, selector["paragraph"], selector["line"], wi)
            removed.setdefault(slot, set()).add(label)
            if target is not None:
                target.add(slot)

    for item in scan_map.get("replacements", []):
        slot = (item["page_ordinal"], item["paragraph"], item["line"], item["word"])
        _require((source_word(*slot).text or "") == item["ocr_form"],
                 f"scan-map original OCR form {item['id']}")
        _require(slot not in replacements, f"duplicate scan-map replacement {item['id']}")
        replacements[slot] = item["scan_reading"]
    for item in scan_map.get("marginal_headings", []):
        for selector in item.get("carriers", []):
            suppress(item["page_ordinal"], selector, f"heading:{item['id']}")
    for item in scan_map.get("tables_of_contents", []):
        for header in item.get("header_carriers", []):
            suppress(item["page_ordinal"], header["selector"], f"toc:{item['id']}", toc_slots)
        for row in item.get("rows", []):
            for name in ("chapter_carrier", "entry_carrier", "page_carrier"):
                suppress(item["page_ordinal"], row[name], f"toc:{item['id']}", toc_slots)
    for item in scan_map.get("carrier_gaps", []):
        for selector in item.get("carriers", []):
            suppress(item["page_ordinal"], selector, f"gap:{item['id']}")
    for item in scan_map.get("paratext", []):
        for selector in item.get("source_carriers", []):
            suppress(item["page_ordinal"], selector, f"paratext:{item['id']}")

    def expand(leaf: int, selector: Mapping[str, int]):
        result = []
        for wi in range(selector["first_word"], selector["last_word"] + 1):
            word = source_word(leaf, selector["paragraph"], selector["line"], wi)
            result.append({"paragraph": selector["paragraph"], "line": selector["line"],
                           "word": wi, "text": word.text or "", "coords": word.get("coords")})
        return result

    expected_collation = {"contract": "ocd-robertson-keywords-scan-collation-v1",
        "map_path": map_authority["path"], "map_sha256": map_sha, "method": scan_map["method"],
        "replacements": [], "marginal_headings": [], "tables_of_contents": [],
        "carrier_gaps": [], "explicit_gaps": scan_map.get("explicit_gaps", []),
        "column_layout_pages": scan_map.get("column_layout_pages", []), "paratext": [],
        "visual_review": visual_review}
    for item in scan_map.get("replacements", []):
        selector = {"paragraph": item["paragraph"], "line": item["line"],
                    "first_word": item["word"], "last_word": item["word"]}
        expected_collation["replacements"].append({**item, "selector": selector,
            "source_carriers": expand(item["page_ordinal"], selector)})
    for item in scan_map.get("marginal_headings", []):
        expected_collation["marginal_headings"].append({**item, "source_carriers": [
            {"selector": selector, "words": expand(item["page_ordinal"], selector)}
            for selector in item.get("carriers", [])]})
    for item in scan_map.get("tables_of_contents", []):
        rows = []
        for row in item["rows"]:
            evidence = {"chapter": row["chapter"], "title": row["title"], "page": row["page"]}
            for name in ("chapter_carrier", "entry_carrier", "page_carrier"):
                evidence[name] = {"selector": row[name],
                                  "words": expand(item["page_ordinal"], row[name])}
            rows.append(evidence)
        expected_collation["tables_of_contents"].append({**item, "source_rows": rows,
            "header_evidence": [{"selector": header["selector"],
                "scan_reading": header["scan_reading"],
                "words": expand(item["page_ordinal"], header["selector"])}
                for header in item.get("header_carriers", [])]})
    for item in scan_map.get("carrier_gaps", []):
        expected_collation["carrier_gaps"].append({**item, "source_carriers": [
            {"selector": selector, "words": expand(item["page_ordinal"], selector)}
            for selector in item.get("carriers", [])]})
    for item in scan_map.get("paratext", []):
        expected_collation["paratext"].append({**item, "source_carriers": [
            {"selector": selector, "words": expand(item["page_ordinal"], selector)}
            for selector in item.get("source_carriers", [])]})
    _require(account.get("scan_collation") == expected_collation,
             "scan map and exact OCR carrier accounting")

    def coords(word):
        values = tuple(int(value) for value in (word.get("coords") or "").split(","))
        _require(len(values) == 4, "two-column word coordinates")
        return values

    def plain(paragraph):
        return "".join(word.text or "" for line in paragraph.xpath("./LINE")
                       for word in line.xpath("./WORD"))

    def layout_header(paragraph):
        value = " ".join(plain(paragraph).split()).upper()
        return value in {"INDEX OF SCRIPTURE REFERENCES", "TOPICAL INDEX",
                         "BIBLIOGRAPHY", "PAGE"} or (value.isdigit() and len(value) <= 4)

    def split_columns(paragraphs):
        centers, min_x, max_x = [], None, None
        for paragraph in paragraphs:
            if layout_header(paragraph):
                continue
            for word in paragraph.xpath("./LINE/WORD"):
                x0, _y1, x1, _y0 = coords(word)
                centers.append((x0 + x1) / 2)
                min_x = x0 if min_x is None else min(min_x, x0)
                max_x = x1 if max_x is None else max(max_x, x1)
        _require(len(centers) >= 4 and min_x is not None and max_x is not None and max_x > min_x,
                 "two-column geometry")
        ordered = sorted(set(centers))
        mid, span = (min_x + max_x) / 2, max_x - min_x
        candidates = [(right - left, (left + right) / 2)
            for left, right in zip(ordered, ordered[1:])
            if right - left >= span * .04 and abs((left + right) / 2 - mid) <= span * .08]
        if not candidates:
            candidates = [(right - left, (left + right) / 2)
                          for left, right in zip(ordered, ordered[1:])]
        _require(bool(candidates), "two-column split candidate")
        _gap, split = max(candidates, key=lambda row: (row[0], -abs(row[1] - mid)))
        return split, [min_x, max_x]

    def rendered_line(leaf, pi, li, line, column=None, split=None):
        chunks, omitted = [], 0
        for wi, word in enumerate(line.xpath("./WORD"), 1):
            slot = (leaf, pi, li, wi)
            if column is not None:
                x0, _y1, x1, _y0 = coords(word)
                if (1 if (x0 + x1) / 2 <= split else 2) != column:
                    continue
            if slot in removed:
                omitted += 1
            else:
                chunks.append(replacements.get(slot, word.text or ""))
        return "".join(chunks), omitted

    group_ranges = [("front", "preliminaries", 1, 14),
        ("body", "I", 15, 28), ("body", "II", 29, 44), ("body", "III", 45, 59),
        ("body", "IV", 60, 81), ("body", "V", 82, 96), ("body", "VI", 97, 112),
        ("body", "VII", 113, 125), ("back", "scripture-index", 126, 128),
        ("back", "topical-index", 129, 130), ("back", "bibliography", 131, 132),
        ("back", "appended-material", 133, 136)]
    sections = {name: tree.find(f"./{{{TEI}}}text/{{{TEI}}}{name}")
                for name in ("front", "body", "back")}
    _require(list(sections) == ["front", "body", "back"], "front/body/back order")
    expected_groups = [row for row in group_ranges]
    actual_groups = []
    for section in ("front", "body", "back"):
        for group in sections[section]:
            actual_groups.append((section, group.get("type"), group.get("n")))
    _require(actual_groups == [("front", "preliminaries", None)]
             + [("body", "chapter", name) for name in ("I", "II", "III", "IV", "V", "VI", "VII")]
             + [("back", name, None) for name in ("scripture-index", "topical-index",
                                                  "bibliography", "appended-material")],
             "section groups")
    for section_name, group_name, first, last in group_ranges:
        group_node = next(node for node in sections[section_name]
                          if (node.get("n") == group_name if section_name == "body"
                              else node.get("type") == group_name))
        group_pages = group_node.xpath("./tei:div[@type='scan-page']",
                                       namespaces={"tei": TEI})
        _require([page.get("n") for page in group_pages]
                 == [str(leaf) for leaf in range(first, last + 1)],
                 f"{group_name} page order")
    account_pages = account.get("pages", [])
    _require(len(account_pages) == 136, "account page count")
    totals = {"pages": 0, "paragraphs": 0, "lines": 0}
    layout_by_page = {item["page_ordinal"]: item for item in scan_map.get("column_layout_pages", [])}
    toc_by_page = {item["page_ordinal"]: item for item in scan_map.get("tables_of_contents", [])}
    margin_by_page = {}
    for item in scan_map.get("marginal_headings", []):
        margin_by_page.setdefault(item["page_ordinal"], []).append(item)
    for ordinal, (source_page, obj, page_row) in enumerate(
            zip(access, objects, account_pages, strict=True), 1):
        leaf = int(source_page.get("leafNum"))
        section_name, group_name = next((section, group) for section, group, first, last in group_ranges
                                        if first <= leaf <= last)
        group_node = next(node for node in sections[section_name]
                          if (node.get("n") == group_name if section_name == "body"
                              else node.get("type") == group_name))
        page_nodes = group_node.xpath("./tei:div[@type='scan-page' and @n=$leaf]",
                                      namespaces={"tei": TEI}, leaf=str(leaf))
        _require(page_row.get("pdf_page") == ordinal and page_row.get("leaf") == leaf
                 and page_row.get("page_type") == (source_page.findtext("pageType") or "")
                 and page_row.get("printed_label") == (source_page.findtext("pageNumber") or "")
                 and page_row.get("section") == section_name and page_row.get("group") == group_name,
                 f"page accounting at {leaf}")
        _require(len(page_nodes) == 1, f"TEI page uniqueness at {leaf}")
        page = page_nodes[0]
        _require(page.get(XML_ID) == f"leaf-{leaf:04d}" and page.get("n") == str(leaf),
                 f"TEI page identity at {leaf}")
        pb = page.find(f"{{{TEI}}}pb")
        _require(pb is not None and pb.get("n") == (source_page.findtext("pageNumber") or str(leaf))
                 and pb.get("facs") == f"{BASE}/scan.pdf#page={ordinal}",
                 f"scan page binding at {leaf}")
        marker = obj.xpath("./PARAM[@name='PAGE']")
        _require(len(marker) == 1 and marker[0].get("value") ==
                 f"keywordsinteachi01robe_{leaf:04d}.djvu", f"OCR page marker at {leaf}")
        paragraphs = obj.xpath(".//PARAGRAPH")
        rows = page_row.get("paragraphs", [])
        _require(len(rows) == len(paragraphs), f"source paragraph accounting at {leaf}")
        layout = layout_by_page.get(leaf)
        split, bounds = split_columns(paragraphs) if layout else (None, None)
        if layout:
            col_nodes = page.xpath("./tei:div[@type='source-column']", namespaces={"tei": TEI})
            _require(len(col_nodes) == 2 and [node.get("n") for node in col_nodes] == ["1", "2"],
                     f"two-column structure at {leaf}")
            _require(page_row.get("column_layout") == {"kind": layout["kind"], "columns": 2,
                "split_x": split, "coordinate_bounds": bounds,
                "algorithm": "largest WORD-center gap near the center of retained OCR text extents"},
                f"column boundary accounting at {leaf}")
        else:
            _require(not page.xpath("./tei:div[@type='source-column']", namespaces={"tei": TEI}),
                     f"unexpected columns at {leaf}")
        for pi, (paragraph, row) in enumerate(zip(paragraphs, rows, strict=True), 1):
            lines = paragraph.xpath("./LINE")
            raw_lines = ["".join(word.text or "" for word in line.xpath("./WORD")) for line in lines]
            source_hashes = [_sha(value.encode("utf-8")) for value in raw_lines]
            source_count = sum(len(line.xpath("./WORD")) for line in lines)
            text_label = " ".join(plain(paragraph).split()).upper()
            role = "head" if (leaf, pi) in HEADING_POSITIONS or (
                layout and text_label in LAYOUT_HEADERS) else "p"
            _require(row.get("index") == pi and row.get("role") == role
                     and row.get("lines") == len(lines) and row.get("line_sha256") == source_hashes
                     and row.get("source_word_count") == source_count,
                     f"source paragraph row at {leaf}:{pi}")
            toc = toc_by_page.get(leaf)
            toc_covered = bool(source_count) and all(
                (leaf, pi, li, wi) in toc_slots
                for li, line in enumerate(lines, 1) for wi, _word in enumerate(line.xpath("./WORD"), 1))
            if toc_covered:
                expected_lines = [_sha(b"") for _line in lines]
                _require(row.get("placement") == "contents-table"
                         and row.get("output_line_sha256") == expected_lines
                         and row.get("output_word_count") == 0,
                         f"contents source carrier disposition at {leaf}:{pi}")
                _require(not page.xpath(f".//*[@xml:id='leaf-{leaf:04d}-p{pi:03d}']",
                                         namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}),
                         f"contents OCR duplicate at {leaf}:{pi}")
            elif layout and role == "p" and not layout_header(paragraph):
                left_lines = [rendered_line(leaf, pi, li, line, 1, split)[0]
                              for li, line in enumerate(lines, 1)]
                right_lines = [rendered_line(leaf, pi, li, line, 2, split)[0]
                               for li, line in enumerate(lines, 1)]
                left_hashes = [_sha(value.encode("utf-8")) for value in left_lines]
                right_hashes = [_sha(value.encode("utf-8")) for value in right_lines]
                expected_hashes = {"1": left_hashes, "2": right_hashes}
                _require(row.get("placement") == "columns"
                         and row.get("column_line_sha256") == expected_hashes
                         and row.get("output_line_sha256") == [left_hashes, right_hashes],
                         f"column text accounting at {leaf}:{pi}")
                for col, expected_lines in ((1, left_lines), (2, right_lines)):
                    has_source = any(
                        (coords(word)[0] + coords(word)[2]) / 2 <= split if col == 1
                        else (coords(word)[0] + coords(word)[2]) / 2 > split
                        for line in lines for word in line.xpath("./WORD"))
                    node_id = f"leaf-{leaf:04d}-p{pi:03d}-col{col}"
                    found = page.xpath(f".//*[@xml:id='{node_id}']",
                                       namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})
                    _require(len(found) == (1 if has_source else 0),
                             f"column paragraph identity at {leaf}:{pi}:{col}")
                    if found:
                        _require(found[0].tag == f"{{{TEI}}}p",
                                 f"column paragraph role at {leaf}:{pi}:{col}")
                        lbs = found[0].xpath("./tei:lb", namespaces={"tei": TEI})
                        _require(len(lbs) == len(expected_lines)
                                 and [(lb.get("n"), lb.tail or "") for lb in lbs] ==
                                 [(str(i), value) for i, value in enumerate(expected_lines, 1)],
                                 f"column OCR transformation at {leaf}:{pi}:{col}")
                output_count = sum(1 for li, line in enumerate(lines, 1)
                    for wi, _word in enumerate(line.xpath("./WORD"), 1)
                    if (leaf, pi, li, wi) not in removed)
                _require(row.get("output_word_count") == output_count,
                         f"column word accounting at {leaf}:{pi}")
            else:
                values = [rendered_line(leaf, pi, li, line)[0]
                          for li, line in enumerate(lines, 1)]
                hashes = [_sha(value.encode("utf-8")) for value in values]
                _require(row.get("placement") == "page"
                         and row.get("output_line_sha256") == hashes,
                         f"transformed line accounting at {leaf}:{pi}")
                found = page.xpath(f".//*[@xml:id='leaf-{leaf:04d}-p{pi:03d}']",
                                   namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})
                _require(len(found) == 1, f"paragraph identity at {leaf}:{pi}")
                _require(found[0].tag == f"{{{TEI}}}{role}",
                         f"paragraph role at {leaf}:{pi}")
                lbs = found[0].xpath("./tei:lb", namespaces={"tei": TEI})
                _require(len(lbs) == len(values)
                         and [(lb.get("n"), lb.tail or "") for lb in lbs] ==
                         [(str(i), value) for i, value in enumerate(values, 1)],
                         f"scan-grounded OCR transformation at {leaf}:{pi}")
                output_count = sum(1 for li, line in enumerate(lines, 1)
                    for wi, _word in enumerate(line.xpath("./WORD"), 1)
                    if (leaf, pi, li, wi) not in removed)
                _require(row.get("output_word_count") == output_count,
                         f"output word accounting at {leaf}:{pi}")
            totals["paragraphs"] += 1
            totals["lines"] += len(lines)
        for heading in margin_by_page.get(leaf, []):
            notes = page.xpath(f"./tei:note[@n='{heading['id']}']", namespaces={"tei": TEI})
            _require(len(notes) == 1 and notes[0].get("place") == "margin"
                     and notes[0].get("type") == "heading"
                     and "".join(notes[0].itertext()) == heading["scan_reading"]
                     and notes[0].get("corresp") ==
                     f"#leaf-{leaf:04d}-p{heading['target_paragraph']:03d}",
                     f"scan-grounded marginal heading at {leaf}:{heading['id']}")
        for gap in scan_map.get("explicit_gaps", []):
            if gap.get("page_ordinal") == leaf and gap.get("disposition") == "nonliterary-exclusion":
                notes = page.xpath(f"./tei:note[@n='{gap['id']}']", namespaces={"tei": TEI})
                _require(len(notes) == 1 and notes[0].get("type") == "source-disposition"
                         and "".join(notes[0].itertext()) == gap["description"],
                         f"nonliterary source disposition at {leaf}:{gap['id']}")
        if toc := toc_by_page.get(leaf):
            lists = page.xpath("./tei:div[@type='contents-table']/tei:list[@type='contents']",
                               namespaces={"tei": TEI})
            _require(len(lists) == 1
                     and len(lists[0].xpath("./tei:item", namespaces={"tei": TEI})) == len(toc["rows"]),
                     "contents table structure")
            items = lists[0].xpath("./tei:item", namespaces={"tei": TEI})
            for item, expected in zip(items, toc["rows"], strict=True):
                _require(item.xpath("string(./tei:label)", namespaces={"tei": TEI}) ==
                         f"CHAPTER {expected['chapter']}"
                         and item.xpath("string(./tei:seg[@type='title'])", namespaces={"tei": TEI}) ==
                         expected["title"]
                         and item.xpath("string(./tei:seg[@type='page'])", namespaces={"tei": TEI}) ==
                         expected["page"], "contents row reading")
        for paratext in scan_map.get("paratext", []):
            if paratext["page_ordinal"] == leaf:
                notes = page.xpath(f"./tei:note[@n='{paratext['id']}']", namespaces={"tei": TEI})
                expected_reading = paratext.get("scan_reading")
                if expected_reading is None:
                    expected_reading = f"{paratext['label']} [barcode {paratext['barcode']}]"
                _require(len(notes) == 1 and "".join(notes[0].itertext()) ==
                         expected_reading,
                         f"printed paratext at {leaf}")
        totals["pages"] += 1
    _require(account.get("totals") == totals, "source totals")
    return totals






