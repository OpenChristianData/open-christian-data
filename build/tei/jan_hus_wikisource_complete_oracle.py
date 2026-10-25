"""Independent source-carrier and page-ledger checks for Jan Hus's Wikisource witness."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest

ORACLE_ID = "ocd-jan-hus-wikisource-source-carrier-oracle"
ORACLE_VERSION = "1"
T = "{http://www.tei-c.org/ns/1.0}"
MW = "{http://www.mediawiki.org/xml/export-0.11/}"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _classes(node) -> set[str]:
    return set((node.get("class") or "").split())


def _page_rows(manifest: SourceManifest) -> tuple[dict[str, tuple[str, int, str]], dict[int, int]]:
    root = ET.fromstring(manifest.authority_path("page-records-export").read_bytes())
    rows = {}
    counts: dict[int, int] = {}
    for page in root.findall(MW + "page"):
        title = page.findtext(MW + "title") or ""
        rev = page.find(MW + "revision")
        if rev is None:
            raise ValueError("page record has no revision: " + title)
        revision = rev.findtext(MW + "id") or ""
        text = rev.findtext(MW + "text") or ""
        match = re.search(r"pagequality\s+level=[\"']([0-4])[\"']", text, re.IGNORECASE)
        if not match:
            match = re.search(r"\{\{\s*pagequality\s*\|\s*([0-4])", text, re.IGNORECASE)
        if not match or title in rows:
            raise ValueError("page quality missing or title duplicated: " + title)
        quality = int(match.group(1))
        rows[title] = (revision, quality, _sha(text.encode("utf-8")))
        counts[quality] = counts.get(quality, 0) + 1
    return rows, counts


def _strip_ignored(clone) -> None:
    remove = clone.xpath(
        './/style|.//link|.//meta|.//script|.//*[@data-page-index]|'
        './/*[contains(concat(" ",normalize-space(@class)," ")," __nop ")]|'
        './/*[contains(concat(" ",normalize-space(@class)," ")," mw-cite-backlink ")]|'
        './/*[contains(concat(" ",normalize-space(@class)," ")," mw-empty-elt ")]|'
        './/*[contains(concat(" ",normalize-space(@class)," ")," ws-noexport ")]|'
        './/*[contains(concat(" ",normalize-space(@class)," ")," wst-dhr ")]|'
        './/*[contains(concat(" ",normalize-space(@class)," ")," wst-header-back-arrow ")]|'
        './/*[contains(concat(" ",normalize-space(@class)," ")," wst-header-forward-arrow ")]'
    )
    for node in reversed(remove):
        if node.getparent() is not None:
            node.drop_tree()


def _main_carriers(record: dict[str, object]):
    document = html.fromstring(record["render_html"])
    if record["kind"] == "section":
        wrappers = document.xpath(
            './/div[contains(concat(" ",normalize-space(@class)," ")," prp-pages-output ")]'
        )
        mains = [wrapper for wrapper in wrappers if not wrapper.xpath(
            './/ol[contains(concat(" ",normalize-space(@class)," ")," mw-references ")]'
        )]
    else:
        mains = document.xpath(
            './/div[contains(concat(" ",normalize-space(@class)," ")," pagetext ")]'
        )
    if not mains:
        raise ValueError("source render has no main text carrier: " + record["title"])
    return document, mains


def _source_text(record: dict[str, object]) -> str:
    document, mains = _main_carriers(record)
    parts = []
    for main in mains:
        clone = deepcopy(main)
        _strip_ignored(clone)
        parts.append("".join(clone.itertext()))
    notes = document.xpath('.//li[starts-with(@id,"cite_note-")]')
    for note in notes:
        clone = deepcopy(note)
        _strip_ignored(clone)
        reference_text = clone.xpath(
            './/span[contains(concat(" ",normalize-space(@class)," ")," mw-reference-text ")]'
        )
        if len(reference_text) != 1:
            raise ValueError("source note has no unique body carrier: " + (note.get("id") or ""))
        parts.append("".join(reference_text[0].itertext()))
    return "".join(parts)


def _source_italics(record: dict[str, object]) -> list[str]:
    document, mains = _main_carriers(record)
    result = []
    for main in mains:
        clone = deepcopy(main)
        _strip_ignored(clone)
        result.extend(_norm("".join(node.itertext())) for node in clone.iter("i"))
    for note in document.xpath('.//li[starts-with(@id,"cite_note-")]'):
        clone = deepcopy(note)
        _strip_ignored(clone)
        carriers = clone.xpath(
            './/span[contains(concat(" ",normalize-space(@class)," ")," mw-reference-text ")]'
        )
        if len(carriers) == 1:
            result.extend(_norm("".join(node.itertext())) for node in carriers[0].iter("i"))
    return result


def _note_id(section_id: str, source_id: str) -> str:
    suffix = source_id.removeprefix("cite_note-")
    suffix = re.sub(r"[^A-Za-z0-9.-]+", "-", suffix).strip("-")
    return f"{section_id}-note-{suffix}"


def _section_id(title: str) -> str:
    if title == "De Ecclesia. The Church/Front matter":
        return "jan-hus-front-matter"
    if title == "De Ecclesia. The Church/Introduction":
        return "jan-hus-introduction"
    if title == "De Ecclesia. The Church":
        return "jan-hus-table-of-contents"
    chapter = re.fullmatch(r"De Ecclesia\. The Church/Chapter ([1-9][0-9]*)", title)
    if chapter:
        return f"jan-hus-chapter-{chapter.group(1)}"
    page = re.fullmatch(r"Page:The Church, by John Huss\.pdf/([0-9]+)", title)
    if page and page.group(1) == "51":
        return "jan-hus-title-page"
    if page and int(page.group(1)) in range(353, 357):
        return f"jan-hus-index-page-{page.group(1)}"
    raise ValueError("unexpected rendered source identity: " + title)


def findings(manifest: SourceManifest, raw: bytes) -> list[str]:
    problems: list[str] = []
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    capture = json.loads(manifest.authority_path("rendered-text").read_bytes())
    if capture.get("contract") != "ocd-wikisource-expanded-render-capture-v1":
        problems.append("render capture contract differs")
    if len(capture.get("records", [])) != profile["expected_render_record_count"]:
        problems.append("render record count differs")
    if capture.get("section_count") != profile["expected_section_record_count"]:
        problems.append("expanded section-record count differs")
    by_title = {record["title"]: record for record in capture["records"]}
    if len(by_title) != len(capture["records"]) or set(by_title) != set(profile["record_order"]):
        problems.append("render source identities differ")
    pages, quality_counts = _page_rows(manifest)
    if len(pages) != profile["expected_page_count"]:
        problems.append("complete scan-page record count differs")
    quality_summary = {str(key): value for key, value in quality_counts.items()}
    if quality_summary != profile["expected_page_quality_counts"]:
        problems.append("quality-level census differs")
    captured_ledger = {row["title"]: row for row in capture["page_record_ledger"]}
    if len(captured_ledger) != len(capture["page_record_ledger"]) or set(captured_ledger) != set(pages):
        problems.append("captured page ledger identities differ")
    else:
        for title, (revision, quality, text_sha) in pages.items():
            row = captured_ledger[title]
            if row["revision"] != revision or int(row["quality"]) != quality or row["wikitext_sha256"] != text_sha:
                problems.append("captured page revision/quality/hash differs: " + title)
                break
    untranscribed = sorted(int(title.rsplit("/", 1)[1]) for title, row in pages.items() if row[1] == 0)
    if untranscribed != profile["untranscribed_scan_positions"]:
        problems.append("quality-0 position set differs")
    classification = profile["untranscribed_page_classification"]
    expected_page_revisions = {
        str(number): pages[f"Page:The Church, by John Huss.pdf/{number}"][0]
        for number in untranscribed
    }
    if classification.get("status") != "without-text" or classification.get("page_revision_ids") != expected_page_revisions:
        problems.append("quality-0 no-text classifications do not bind exact source revisions")
    transcribed = sorted(int(title.rsplit("/", 1)[1]) for title, row in pages.items() if row[1] in {3, 4})
    for title, record in by_title.items():
        encoded = record["render_html"].encode("utf-8")
        if _sha(encoded) != record["render_sha256"] or len(encoded) != record["render_bytes"]:
            problems.append("render HTML hash/size differs: " + title)
    try:
        actual = etree.fromstring(raw)
    except etree.XMLSyntaxError as exc:
        return problems + ["candidate XML is invalid: " + str(exc)]
    ns = {"t": T[1:-1]}
    body = actual.find(".//" + T + "text/" + T + "body")
    if body is None:
        return problems + ["candidate has no TEI body"]
    expected_section_ids = [_section_id(title) for title in profile["record_order"]]
    observed_section_ids = [
        node.get("{http://www.w3.org/XML/1998/namespace}id")
        for node in body.iter(T + "div")
        if node.get("{http://www.w3.org/XML/1998/namespace}id")
    ]
    if observed_section_ids != expected_section_ids:
        problems.append("TEI section identities or order differ")
    expected_text = "".join(_source_text(by_title[title]) for title in profile["record_order"] if title in by_title)
    observed_text = "".join(body.itertext())
    if _norm(expected_text) != _norm(observed_text):
        problems.append("source-visible wording/order differs")

    expected_pages: list[int] = []
    for title in profile["record_order"]:
        record = by_title.get(title)
        if record is None:
            continue
        if record["kind"] == "page":
            expected_pages.append(int(title.rsplit("/", 1)[1]))
        else:
            source_doc = html.fromstring(record["render_html"])
            wrappers = source_doc.xpath(
                './/div[contains(concat(" ",normalize-space(@class)," ")," prp-pages-output ")]'
            )
            main = [wrapper for wrapper in wrappers if not wrapper.xpath(
                './/ol[contains(concat(" ",normalize-space(@class)," ")," mw-references ")]'
            )]
            expected_pages.extend(
                int(node.get("data-page-index")) for wrapper in main for node in wrapper.iter()
                if node.get("data-page-index")
            )
    observed_pages = [int(node.get("n")) for node in body.iter(T + "pb") if (node.get("n") or "").isdigit()]
    if observed_pages != expected_pages or len(set(observed_pages)) != len(observed_pages):
        problems.append("page-break sequence differs from source render")
    if sorted(observed_pages) != transcribed or len(observed_pages) != profile["expected_transcribed_page_count"]:
        problems.append("candidate does not cover every quality-3/4 scan page once")

    expected_italics = [
        text
        for title in profile["record_order"] if title in by_title
        for text in _source_italics(by_title[title])
    ]
    observed_italics = [
        _norm("".join(node.itertext())) for node in body.iter(T + "hi")
        if (node.get("rend") or "").split(" ", 1)[0] == "italic"
    ]
    if expected_italics != observed_italics:
        problems.append("italic carrier sequence differs")

    expected_notes = {}
    expected_markers = 0
    for title in profile["record_order"]:
        record = by_title.get(title)
        if record is None:
            continue
        section_id = _section_id(title)
        source_doc = html.fromstring(record["render_html"])
        expected_markers += len(source_doc.xpath(
            './/sup[contains(concat(" ",normalize-space(@class)," ")," mw-ref ")]'
        ))
        for note in source_doc.xpath('.//li[starts-with(@id,"cite_note-")]'):
            note_clone = deepcopy(note)
            _strip_ignored(note_clone)
            text_nodes = note_clone.xpath(
                './/span[contains(concat(" ",normalize-space(@class)," ")," mw-reference-text ")]'
            )
            if len(text_nodes) != 1:
                problems.append("source note body carrier differs: " + str(note.get("id")))
                continue
            expected_notes[_note_id(section_id, note.get("id") or "")] = _norm("".join(text_nodes[0].itertext()))
    observed_notes = {
        node.get("{http://www.w3.org/XML/1998/namespace}id"): _norm("".join(node.itertext()))
        for node in body.iter(T + "note")
    }
    if observed_notes != expected_notes:
        problems.append("footnote identities or wording differ")
    note_ids = set(observed_notes)
    markers = [node for node in body.iter(T + "ref") if node.get("type") == "footnote-marker"]
    if len(markers) != expected_markers or any((node.get("target") or "")[1:] not in note_ids for node in markers):
        problems.append("footnote markers do not bind exact retained notes")

    expected_tables = sum(
        sum(1 for main in _main_carriers(by_title[title])[1] for _ in main.iter("table"))
        for title in profile["record_order"] if title in by_title
    )
    if len(list(body.iter(T + "table"))) != expected_tables:
        problems.append("table carrier count differs")
    graphics = list(body.iter(T + "graphic"))
    if len(graphics) != 1 or not graphics[0].get("url", "").endswith("Charles_Scribner%27s_Sons_logo.png"):
        problems.append("retained printer-mark identity differs")
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("p5-schema"))))
    if not schema.validate(actual):
        problems.append("P5: " + str(schema.error_log.last_error))
    return problems


def _closure(root: Path) -> str:
    paths = ["build/tei/jan_hus_wikisource_complete_oracle.py", "ocd_kernel/reconstruction/contract.py"]
    return _sha(_json([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in paths]))


def _oracle(manifest: SourceManifest, candidate) -> dict[str, object]:
    problems = findings(manifest, candidate.member_bytes("content.tei.xml"))
    att: dict[str, object] = {
        "status": "fail" if problems else "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure(manifest.repository_root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
        "package_schema_sha256": manifest.record["package_schema"]["sha256"],
        "source_sha256": _sha(manifest.authority_path("rendered-text").read_bytes()),
        "xsd_sha256": _sha(manifest.authority_path("p5-schema").read_bytes()),
        "policy_sha256": _sha(manifest.authority_path("policy").read_bytes()),
        "findings": problems,
    }
    att["result_sha256"] = _sha(_json(att))
    return att


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
