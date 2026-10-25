"""Independent scan-page and OCR-carrier oracle for Watson's two IA volumes.

Converter uses stdlib XML traversal; this checker uses lxml source XPath and
checks the actual readable TEI.  Both necessarily trust the same retained OCR
for wording; PDF counts and selected image inspection only corroborate alignment.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile
from typing import Mapping
import fitz
from lxml import etree
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BASE = "raw/internet-archive/theological-institutes"
VOLUMES = (
    ("theologicalinst01wats", "I", 12, 574, 586, 578, (0, 208, 209, 581, 582, 583, 584, 585)),
    ("theologicalinst02wats", "II", 8, 488, 500, 492, (0, 306, 307, 495, 496, 497, 498, 499)),
)
MEMBERS = ("scan.pdf", "ocr.txt", "ocr.xml", "scandata.xml", "metadata.json",
           "member-inventory.tsv", "acquisition-receipt.json", "page-numbers.json", "page-scans.zip")
CLOSURE = ("build/tei/watson_theological_institutes_ia_oracle.py",
           "ocd_kernel/lib/storage_topology.py",
           "ocd_kernel/reconstruction/contract.py",
           "ocd_kernel/reconstruction/verifier.py")

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")

def text_root(data: bytes) -> etree._Element:
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))

def expected_heading(value: str) -> bool:
    normalized = " ".join(value.split()).strip(" .").upper()
    return (normalized in {"ADVERTISEMENT", "CONTENTS", "PREFACE", "DEDICATION", "INDEX"}
            or bool(re.fullmatch(r"CHAPTER [IVXLCDM]+|PART (FIRST|SECOND|THIRD|FOURTH)", normalized)))

def derived_source_paragraphs(raw: str) -> list[tuple[int, list[str], int]]:
    text = raw.rstrip("\f\r\n").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block for block in re.split(r"\n[ \t]*\n+", text) if block.strip()]
    return [(index, block.split("\n"), sum(len(line.split()) for line in block.split("\n")))
            for index, block in enumerate(blocks, 1)]

def check(root: Path, tei_bytes: bytes, account_bytes: bytes) -> dict[str, int]:
    tei = text_root(tei_bytes)
    accounting = json.loads(account_bytes)
    if accounting.get("contract") != "ocd-watson-ia-accountability-v1":
        raise ValueError("source accountability contract changed")
    volumes = tei.findall(f"./{{{TEI}}}text/{{{TEI}}}group/{{{TEI}}}text")
    if len(volumes) != 2 or len(accounting.get("volumes", [])) != 2:
        raise ValueError("volume boundary/count changed")
    derived_path = root / "sources/watson-theological-institutes-ia/deleted-pages-tesseract.json"
    witness = json.loads(derived_path.read_bytes())
    if (witness.get("contract") != "ocd-watson-ia-derived-ocr-v1"
        or witness.get("engine") != "tesseract v5.5.0.20241111"
        or witness.get("command") != ["tesseract", "stdin", "stdout", "--psm", "3", "-l", "eng"]):
        raise ValueError("scan-derived OCR witness identity changed")
    derived = {int(item["leaf"]): item for item in witness["pages"]}
    if set(derived) != {306, 307} or [derived[x]["printed_page"] for x in (306, 307)] != ["298", "299"]:
        raise ValueError("scan-derived textual page identity changed")
    totals = {"pages": 0, "paragraphs": 0, "lines": 0, "explicit_ocr_heads": 0}
    for vi, (spec, volume, account) in enumerate(zip(VOLUMES, volumes, accounting["volumes"], strict=True), 1):
        name, roman, front_end, back_start, leaf_total, access_total, excluded_expected = spec
        if volume.get("n") != roman or volume.get("type") != "volume" or account.get("name") != name:
            raise ValueError(f"{name}: volume identity changed")
        base = f"{BASE}/{name}"
        members = account.get("source_members")
        if not isinstance(members, list) or [m.get("path") for m in members] != [f"{base}/{x}" for x in MEMBERS]:
            raise ValueError(f"{name}: source member inventory changed")
        for entry in members:
            physical = resolve_repo_path(root, entry["path"])
            data = physical.read_bytes()
            if entry.get("bytes") != len(data) or entry.get("sha256") != sha(data):
                raise ValueError(f"{name}: source member hash changed: {entry['path']}")
        with ZipFile(resolve_repo_path(root, f"{base}/page-scans.zip")) as archive:
            files = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
            exact_members = {f"{name}_jp2/{name}_{leaf:04d}.jp2" for leaf in range(leaf_total)}
            if len(files) != leaf_total or set(files) != exact_members:
                raise ValueError(f"{name}: page-scan member set changed")
            excluded_hashes = {leaf: sha(archive.read(f"{name}_jp2/{name}_{leaf:04d}.jp2"))
                               for leaf in excluded_expected}
        if account.get("page_scan_members") != leaf_total:
            raise ValueError(f"{name}: page-scan count changed")
        scan = text_root(resolve_repo_path(root, f"{base}/scandata.xml").read_bytes())
        leaves = scan.xpath("./pageData/page")
        if len(leaves) != leaf_total or [int(p.get("leafNum")) for p in leaves] != list(range(leaf_total)):
            raise ValueError(f"{name}: scanned leaf envelope changed")
        included = [p for p in leaves if p.findtext("addToAccessFormats") == "true"]
        excluded = [p for p in leaves if p.findtext("addToAccessFormats") != "true"]
        if [int(p.get("leafNum")) for p in excluded] != list(excluded_expected):
            raise ValueError(f"{name}: excluded leaf inventory changed")
        rescans = {208: 210, 209: 211} if vi == 1 else {}
        expected_excluded = []
        for scan_page in excluded:
            leaf = int(scan_page.get("leafNum"))
            disposition = ("unique textual scan represented by uncorrected Tesseract OCR"
                           if vi == 2 and leaf in derived else
                           f"duplicate scan of included leaf {rescans[leaf]}"
                           if leaf in rescans else
                           "nontextual cover edge" if scan_page.findtext("pageType") == "Delete" else
                           "calibration card")
            expected_excluded.append({
                "leaf": leaf, "page_type": scan_page.findtext("pageType") or "",
                "access": scan_page.findtext("addToAccessFormats") or "",
                "scan_member": f"{name}_jp2/{name}_{leaf:04d}.jp2",
                "scan_sha256": excluded_hashes[leaf], "disposition": disposition})
        if account.get("excluded_leaves") != expected_excluded:
            raise ValueError(f"{name}: excluded leaf accounting changed")
        objects = text_root(resolve_repo_path(root, f"{base}/ocr.xml").read_bytes()).xpath("./BODY/OBJECT")
        with fitz.open(resolve_repo_path(root, f"{base}/scan.pdf")) as pdf:
            pdf_count = len(pdf)
        if (len(included), len(objects), pdf_count) != (access_total, access_total, access_total):
            raise ValueError(f"{name}: access/PDF/OCR count changed")
        represented = access_total + (2 if vi == 2 else 0)
        if (account.get("leaf_count"), account.get("included_count"),
            account.get("represented_count"), account.get("ocr_object_count"),
            account.get("pdf_page_count")) != (leaf_total, access_total, represented, access_total, access_total):
            raise ValueError(f"{name}: source count accounting changed")
        rows = account.get("pages", [])
        if len(rows) != represented:
            raise ValueError(f"{name}: page accounting count changed")
        by_leaf = {}
        for pdf_index, (scan_page, obj) in enumerate(zip(included, objects, strict=True), 1):
            leaf = int(scan_page.get("leafNum"))
            param = obj.xpath("./PARAM[@name='PAGE']")
            object_name = param[0].get("value") if len(param) == 1 else None
            if object_name != f"{name}_{leaf:04d}.djvu":
                raise ValueError(f"{name}: OCR object leaf differs from scandata at {leaf}")
            by_leaf[leaf] = (obj, pdf_index, None, object_name)
        if vi == 2:
            for leaf in (306, 307):
                item = derived[leaf]
                if (item["source_member"] != f"{name}_jp2/{name}_{leaf:04d}.jp2"
                    or item["source_jp2_sha256"] != excluded_hashes[leaf]
                    or item["raw_text_sha256"] != sha(item["raw_tesseract_text"].encode("utf-8"))):
                    raise ValueError(f"scan-derived OCR source binding changed at leaf {leaf}")
                by_leaf[leaf] = (None, None, item, None)
        section_nodes = {kind: volume.find(f"{{{TEI}}}{kind}") for kind in ("front", "body", "back")}
        if any(value is None for value in section_nodes.values()) or len(volume) != 3:
            raise ValueError(f"{name}: front/body/back envelope changed")
        seen = {kind: [] for kind in section_nodes}
        represented_leaves = [page for page in leaves if int(page.get("leafNum")) in by_leaf]
        for scan_page, row in zip(represented_leaves, rows, strict=True):
            leaf = int(scan_page.get("leafNum"))
            obj, pdf_index, item, object_name = by_leaf[leaf]
            section = "front" if leaf <= front_end else "back" if leaf >= back_start else "body"
            pages = section_nodes[section].findall(f"{{{TEI}}}div")
            offset = len(seen[section])
            if offset >= len(pages):
                raise ValueError(f"{name}: missing {section} page {leaf}")
            page = pages[offset]
            seen[section].append(page)
            if (page.get(XML_ID) != f"v{vi}-leaf-{leaf:04d}" or page.get("type") != "scan-page"
                or page.get("n") != str(leaf)
                or page.get("subtype") != (scan_page.findtext("pageType") or "").lower().replace(" ", "-")):
                raise ValueError(f"{name}: page identity/role changed at leaf {leaf}")
            label = item["printed_page"] if item else (scan_page.findtext("pageNumber") or "")
            kind = "scan-derived-tesseract" if item else "ia-ocr-xml"
            expected_row = {
                "pdf_page": pdf_index, "leaf": leaf, "source_kind": kind,
                "page_type": scan_page.findtext("pageType") or "", "printed_label": label,
                "ocr_param": object_name, "section": section,
                "scan_member": f"{name}_jp2/{name}_{leaf:04d}.jp2"}
            if item:
                expected_row["scan_sha256"] = item["source_jp2_sha256"]
                expected_row["derived_text_sha256"] = item["raw_text_sha256"]
            for key, value in expected_row.items():
                if row.get(key) != value:
                    raise ValueError(f"{name}: page accounting {key} changed at {leaf}")
            pb = page.find(f"{{{TEI}}}pb")
            wanted_id = f"v{vi}-jp2-{leaf:04d}" if item else f"v{vi}-pdf-{pdf_index:04d}"
            wanted_facs = (f"zip:{base}/page-scans.zip!/{item['source_member']}"
                           if item else f"{base}/scan.pdf#page={pdf_index}")
            if pb is None or pb.get(XML_ID) != wanted_id or pb.get("n") != (label or str(leaf)) or pb.get("facs") != wanted_facs:
                raise ValueError(f"{name}: PDF/JP2 page binding changed at leaf {leaf}")
            if item:
                expected = derived_source_paragraphs(item["raw_tesseract_text"])
            else:
                expected = []
                for pi, para in enumerate(obj.xpath(".//PARAGRAPH"), 1):
                    lines = para.xpath("./LINE")
                    texts = ["".join(word.text or "" for word in line.xpath("./WORD")) for line in lines]
                    if texts and any(text.strip() for text in texts):
                        expected.append((pi, texts, sum(len(line.xpath("./WORD")) for line in lines)))
            wrappers = page.findall(f"{{{TEI}}}div")
            if len(wrappers) != len(expected) or row.get("paragraph_count") != len(expected):
                raise ValueError(f"{name}: OCR paragraph omission or duplication at leaf {leaf}")
            account_paras = row.get("paragraphs", [])
            if len(account_paras) != len(expected):
                raise ValueError(f"{name}: paragraph account count at leaf {leaf}")
            for (pi, lines, words), wrapper, para_row in zip(expected, wrappers, account_paras, strict=True):
                head = len(lines) == 1 and expected_heading(lines[0])
                role = "head" if head else "p"
                if wrapper.get("type") != ("ocr-heading" if head else "ocr-paragraph") or len(wrapper) != 1:
                    raise ValueError(f"{name}: heading/paragraph role changed at leaf {leaf} p{pi}")
                node = wrapper[0]
                identity = f"v{vi}-leaf-{leaf:04d}-p{pi:03d}"
                if node.tag != f"{{{TEI}}}{role}" or node.get(XML_ID) != identity:
                    raise ValueError(f"{name}: paragraph identity or role changed at leaf {leaf} p{pi}")
                lbs = node.findall(f"{{{TEI}}}lb")
                if len(lbs) != len(lines) or (node.text or "") != "":
                    raise ValueError(f"{name}: line omission at leaf {leaf} p{pi}")
                if [(lb.get("n"), lb.tail or "") for lb in lbs] != [(str(i), value) for i, value in enumerate(lines, 1)]:
                    raise ValueError(f"{name}: OCR wording/order changed at leaf {leaf} p{pi}")
                if (para_row.get("index"), para_row.get("id"), para_row.get("line_count"),
                    para_row.get("word_count"), para_row.get("line_sha256"), para_row.get("role")) != (
                        pi, identity, len(lines), words,
                        [sha(line.encode("utf-8")) for line in lines], role):
                    raise ValueError(f"{name}: paragraph source accounting changed at leaf {leaf} p{pi}")
                totals["paragraphs"] += 1
                totals["lines"] += len(lines)
                totals["explicit_ocr_heads"] += int(head)
            totals["pages"] += 1
        for kind, section_node in section_nodes.items():
            if len(section_node.findall(f"{{{TEI}}}div")) != len(seen[kind]):
                raise ValueError(f"{name}: invented or misplaced {kind} pages")
    if accounting.get("totals") != totals:
        raise ValueError("candidate total accounting changed")
    return totals

def closure_sha(root: Path) -> str:
    return sha(canonical([{"path": path, "sha256": sha((root / path).read_bytes())}
                          for path in CLOSURE]))

def source_set_sha(manifest: SourceManifest) -> str:
    primary = sorted(({"name": row["name"], "path": row["path"],
                       "bytes": row["bytes"], "sha256": row["sha256"]}
                      for row in manifest.record["authorities"] if row["role"] == "primary-source"),
                     key=lambda row: (row["path"], row["name"]))
    return sha(canonical({"contract": "ocd-source-member-set-v1", "members": primary}))

def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    totals = check(manifest.repository_root, candidate.member_bytes("content.tei.xml"),
                   candidate.member_bytes("source-accountability.json"))
    if totals["pages"] != 1072 or candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("Watson page total or candidate state changed")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    if [row.get("id") for row in unresolved] != [
        "watson-scan-wording-uncollated", "watson-heading-classification"]:
        raise ValueError("unresolved OCR/scan gap statement changed")
    if unresolved[0].get("affected_represented_pages") != 1072:
        raise ValueError("unresolved coverage counts changed")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("status") != "nonaccepted" or provenance.get("source_id") != manifest.record["source_id"]:
        raise ValueError("provenance/status changed")
    xsd = manifest.authority_path("tei-p5-xsd")
    validator = etree.XMLSchema(etree.parse(str(xsd)))
    document = etree.ElementTree(text_root(candidate.member_bytes("content.tei.xml")))
    if not validator.validate(document):
        raise ValueError(f"TEI P5 schema invalid: {validator.error_log.last_error}")
    facts = MechanicalFacts(
        sha(Path(__file__).read_bytes()), closure_sha(manifest.repository_root),
        source_set_sha(manifest),
        sha(manifest.authority_path("reconstruction-profile").read_bytes()),
        sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        sha(xsd.read_bytes()),
        sha(manifest.authority_path("validation-policy").read_bytes()), ())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()

_oracle.oracle_id = "ocd-watson-theological-institutes-ia-independent-oracle"
_oracle.oracle_version = "1"
_oracle.implementation_path = Path(__file__).resolve()

