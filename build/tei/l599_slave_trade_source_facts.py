"""Independent retained-source facts for L599 packaging; no producer imports."""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "raw/wikisource/slave-trade-east-africa-1869/wikisource-export.xml"
RECEIPT = "raw/wikisource/slave-trade-east-africa-1869/acquisition-receipt.json"
INVENTORY = "raw/wikisource/slave-trade-east-africa-1869/member-inventory.tsv"
OLD = "reports/_logs/l599-slave-trade-existing-20261004-v1/retained-v3/package"
RECOVERED = "reports/_logs/l599-slave-trade-existing-20261004-v1/recovered-archive"
ORIGINAL = "reports/_logs/l599-slave-trade-existing-20261004-v1/original-authorities"
HOME = "sources/manifest-acquisitions/l599-slave-trade-retained-v4"
WORK = "slave-trade-of-east-africa"
IDENTITY = {"work_id": WORK, "textual_form_id": WORK + "-wikisource-retained",
            "edition_id": WORK + "-wikisource-electronic", "acquisition_id": WORK + "-wikisource-acquired"}
SCOPE = ("One source-titled retained Wikisource electronic witness of The slave trade of east Africa "
         "(Church Missionary Society, 1869): one exact 92-record XML export, its root/Index context, "
         "23 scan-page wikitext records 5 through 27, 67 retained support records and all XML metadata. "
         "Root main-transclusion reading excludes noinclude, uses retained template-defined fullword "
         "endings, and conserves notes, links and cross-page quotation context. Appendix/Notes A-C, "
         "Index dash positions and absent Page records stay qualified; no complete print-witness claim.")
M = "{http://www.mediawiki.org/xml/export-0.11/}"
PRIMARY_PIN = "54b15f460245becab46674cc364a05129d5b03ea4cb431df58704973c539b0a5"
OLD_TEI_PIN = "f100a1bcc5de3d5fa9563329360bfbdecedd992642e46287fbf89981678ff9de"
REPAIRED_TEI_PIN = "2c0dceeef36d7af7f125af81738125683778f908bd9de7b952985a7e94bef10b"
SOURCE_URL = "https://en.wikisource.org/wiki/Special:Export/The_slave_trade_of_east_Africa?templates=1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def enc(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def primary() -> tuple[bytes, ET.Element]:
    data = (ROOT / SOURCE).read_bytes()
    if sha(data) != PRIMARY_PIN:
        raise ValueError("L599 primary bytes differ")
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    root = ET.fromstring(data, parser=parser)
    if root.tag != M + "mediawiki" or any(not isinstance(e.tag, str) for e in root.iter()):
        raise ValueError("L599 source XML namespace/comment/PI scope differs")
    if not data.startswith(b"<mediawiki ") or b"<!DOCTYPE" in data or b"<?" in data or b"<!--" in data:
        raise ValueError("L599 source lexical document-envelope scope differs")
    return data, root


def graph(root: ET.Element) -> list[dict[str, object]]:
    rows = []
    def visit(node: ET.Element, path: str, parent: str | None, ordinal: int) -> None:
        rows.append({"path": path, "parent": parent, "ordinal": ordinal, "tag": node.tag,
                     "attributes": [[k, v] for k, v in node.attrib.items()], "direct_text": node.text,
                     "tail_text": node.tail, "child_count": len(node),
                     "disposition": "retained-export-administration-and-support-fields"})
        for i, child in enumerate(node):
            visit(child, path + "/" + str(i), path, i)
    visit(root, "0", None, 0)
    return rows


def inverse_graph(rows: list[dict[str, object]]) -> ET.Element:
    """Read the actual private object, enforcing every field and relationship."""
    made: dict[str, ET.Element] = {}
    allowed = {"path", "parent", "ordinal", "tag", "attributes", "direct_text", "tail_text", "child_count", "disposition"}
    counts = {}
    for row in rows:
        if set(row) != allowed or row["disposition"] != "retained-export-administration-and-support-fields":
            raise ValueError("L599 private inverse row fields/disposition differ")
        path, parent, ordinal = row["path"], row["parent"], row["ordinal"]
        if not isinstance(path, str) or path in made or not isinstance(ordinal, int):
            raise ValueError("L599 private inverse identity/ordinal differs")
        if not isinstance(row["tag"], str) or not isinstance(row["attributes"], list):
            raise ValueError("L599 private inverse tag/attributes differ")
        attrs = dict(row["attributes"])
        if len(attrs) != len(row["attributes"]):
            raise ValueError("L599 private inverse duplicate attributes")
        node = ET.Element(row["tag"], attrs)
        node.text, node.tail = row["direct_text"], row["tail_text"]
        if parent is None:
            if made or path != "0" or ordinal != 0:
                raise ValueError("L599 private inverse root envelope differs")
        else:
            if parent not in made or path != parent + "/" + str(ordinal) or ordinal != len(made[parent]):
                raise ValueError("L599 private inverse parent/order differs")
            made[parent].append(node)
        made[path] = node
        counts[path] = row["child_count"]
    if not made or any(len(node) != counts[path] for path, node in made.items()):
        raise ValueError("L599 private inverse child cardinality differs")
    return made["0"]


def record_rows(root: ET.Element) -> list[dict[str, object]]:
    result = []
    for p in root.findall(M + "page"):
        title = p.findtext(M + "title")
        rev = p.find(M + "revision")
        text = rev.findtext(M + "text") or ""
        role = "work" if title == "The slave trade of east Africa" else "index" if title.startswith("Index:") else "page-transcription" if title.startswith("Page:") else "support"
        result.append({"title": title, "role": role, "page_id": p.findtext(M + "id"),
                       "revision_id": rev.findtext(M + "id"), "timestamp": rev.findtext(M + "timestamp"),
                       "contributor": rev.findtext(M + "contributor/" + M + "username"),
                       "contributor_id": rev.findtext(M + "contributor/" + M + "id"),
                       "text_bytes": len(text.encode()), "text_sha256": sha(text.encode())})
    return result


def original_identity() -> dict[str, object]:
    """Bind whole preserved catalog records and their explicit source relationship.

    The historical acquired state is lineage, not the future accepted state.
    No missing author, timestamp, or rights value is inferred.
    """
    base = "library/works/" + WORK
    acquisition = base + "/forms/" + IDENTITY["textual_form_id"] + "/editions/" + IDENTITY["edition_id"] + "/acquisitions/" + IDENTITY["acquisition_id"] + ".json"
    pins = [(base + "/work.json", "cb501683e769bf343667bed466fab75a720748cbfd8f8213d3393d36c4577888"),
            (base + "/state.json", "7ea62438dfdc347f7f1bb0bbd8f569e180e5891494de4e5134f01371c1ffef3f"),
            (acquisition, "19641fe9fcac4f66259977d8c54c2bda4e4aecb708eac24b6837559a8840249d")]
    rows = []
    for path, digest in pins:
        data = (ROOT / ORIGINAL / path).read_bytes()
        if sha(data) != digest:
            raise ValueError("L599 preserved identity bytes differ: " + path)
        rows.append({"path": path, "snapshot": ORIGINAL + "/" + path, "bytes": len(data), "sha256": digest, "record": json.loads(data)})
    work, acquisition_record = rows[0]["record"], rows[2]["record"]
    if (work["work_id"] != WORK or work["textual_forms"][0]["textual_form_id"] != IDENTITY["textual_form_id"]
            or work["textual_forms"][0]["editions"][0]["edition_id"] != IDENTITY["edition_id"]
            or work["textual_forms"][0]["editions"][0]["acquisition_ids"] != [IDENTITY["acquisition_id"]]
            or acquisition_record["acquisition_id"] != IDENTITY["acquisition_id"]
            or acquisition_record["edition_id"] != IDENTITY["edition_id"]
            or acquisition_record["source_path"] != SOURCE or acquisition_record["source_sha256"] != PRIMARY_PIN
            or acquisition_record["source_bytes"] != 275988 or acquisition_record["url"] != SOURCE_URL):
        raise ValueError("L599 preserved identity/acquisition relationship differs")
    return {"identity": IDENTITY, "records": rows,
            "meaning": "Exact historical acquired catalog preimage; future acceptance changes state only through a separate reviewed installation."}


def expected_profile() -> dict[str, object]:
    data, root = primary()
    rows = record_rows(root)
    counts = {role: sum(r["role"] == role for r in rows) for role in ["work", "index", "page-transcription", "support"]}
    if counts != {"work": 1, "index": 1, "page-transcription": 23, "support": 67}:
        raise ValueError("L599 full retained record roles differ")
    wiki = {p.findtext(M + "title"): p.findtext(M + "revision/" + M + "text") or "" for p in root.findall(M + "page")}
    source_page_order = ["Page:The slave trade of east Africa.djvu/" + str(n) for n in range(5, 28)]
    support = [r for r in rows if r["role"] == "support"]
    site = root.find(M + "siteinfo")
    dispositions = []
    for i, row in enumerate(rows, 1):
        title = row["title"]
        carrier = None
        if row["role"] == "work":
            carrier = "teiHeader/fileDesc/sourceDesc/bibl[@type='retained-source-administration']/note[@type='root-page-wikitext']/p"
        elif row["role"] == "index":
            carrier = "teiHeader/fileDesc/sourceDesc/bibl[@type='retained-source-administration']/note[@type='index-page-wikitext']/p"
        elif row["role"] == "page-transcription":
            carrier = "teiHeader/fileDesc/sourceDesc/bibl[@type='retained-source-administration']/note[@type='page-wikitext']/p[@n=" + json.dumps(title) + "]"
        dispositions.append({"record": title, "role": row["role"], "raw_xml_graph_prefix": "0/" + str(i),
                             "exact_wikitext_native_carrier": carrier,
                             "other_fields": "Exact private XML field graph; original retained XML remains source authority.",
                             "meaning": "Root/Index/page text is preserved as native source administration and separately interpreted for the declared reading only." if carrier else "Retained template/module/style/configuration support; no remote execution or authored-text claim."})
    return {"contract": "ocd-l599-retained-full-source-profile-v4", "identity": IDENTITY,
            "original_catalog_lineage": original_identity(),
            "scope": SCOPE, "source": {"path": SOURCE, "bytes": len(data), "sha256": sha(data)},
            "document_envelope": {"xml_declaration": None, "doctype": None, "comments": 0, "processing_instructions": 0,
                                  "namespace_bindings": [["", M[1:-1]], ["xsi", "http://www.w3.org/2001/XMLSchema-instance"]],
                                  "source_fields": len(graph(root))},
            "record_rows": rows, "record_roles": counts, "source_record_order": [r["title"] for r in rows],
            "transclusion_order": source_page_order, "root_selectors": re.findall(r"<pages\b.*?(?:/>|</pages>)", wiki["The slave trade of east Africa"], re.S),
            "index_pagelist": re.search(r"<pagelist.*?/>", wiki["Index:The slave trade of east Africa.djvu"], re.S).group(0),
            "provider_context": {k: site.findtext(M + k) for k in ["sitename", "dbname", "base", "case", "generator"]},
            "support_definition_rows": support, "reading_context": "root-main-transclusion-outside-Page",
            "record_dispositions": dispositions,
            "source_quality": {"replacement_characters": sum(t.count("\ufffd") for t in wiki.values()),
                               "interpretation": "Source wording and typographical surprises retained; no scan comparison."},
            "original_component": {"path": OLD + "/content.tei.xml", "sha256": OLD_TEI_PIN},
            "reviewed_repaired_tei_sha256": REPAIRED_TEI_PIN,
            "source_gaps": {"index_dash_positions": [1, 2, 3, 4, 41, 42, 43, 44], "absent_scan_positions": list(range(28, 41)),
                            "Appendix": "not-retained-extent-unknown", "Notes": ["A", "B", "C"], "print_images_retained": False}}


def expected_policy() -> dict[str, object]:
    profile = expected_profile()
    rights = json.loads((ROOT / RECEIPT).read_bytes())["rights"]
    return {"contract": "ocd-l599-retained-full-source-policy-v4",
            "provenance": {**IDENTITY, "source_id": "wikisource-slave-trade-east-africa-1869", "source_path": SOURCE,
                           "source_sha256": PRIMARY_PIN, "source_url": "https://en.wikisource.org/wiki/Special:Export/The_slave_trade_of_east_Africa?templates=1",
                           "scope": SCOPE, "candidate_status": "nonaccepted", "author_attribution": "Church Missionary Society",
                           "date_as_stated": "1869", "original_package_manifest_sha256": "d183c98cd4481243fbb9540ec9ddda22bdcad295ddef48bf34e6770ccceaebb3",
                           "representation": "Source-backed readable repair of the existing technical TEI; original package and authorities conserved. No whole-body additive inverse is claimed.",
                           "rights_notice": rights, "source_quality": profile["source_quality"]},
            "unresolved": [
                {"id": "appendix-and-notes-not-retained", "status": "unresolved", "effect": "Appendix and Notes A-C remain an explicit gap with unknown extent."},
                {"id": "index-and-print-collation", "status": "unresolved", "effect": "Index dash positions and absent records remain source facts; no print images or page collation."},
                {"id": "contributor-rights-and-history", "status": "unresolved", "effect": "Attribution identifies retained revision contributors and proofreader labels, not complete contribution history or rights clearance."},
                {"id": "source-wording-and-presentation", "status": "unresolved", "effect": "Source wording/typos retained. Finite retained template semantics, not remote Lua/template execution or visual equivalence."},
                {"id": "human-review-and-publication", "status": "unresolved", "effect": "Technical source evidence does not establish human visual review, rights clearance or publication authorization."},
            ]}


def expected_readme() -> bytes:
    _, root = primary()
    rights = json.loads((ROOT / RECEIPT).read_bytes())["rights"]
    lines = ["# The Slave Trade of East Africa: retained source and credit", "",
             "The title page attributes publication to Church Missionary Society, London, 1869. It says REPRINTED FROM THE CHRISTIAN OBSERVER and WITH AN APPENDIX. The retained root/Index attribution is Church Missionary Society; no personal author is inferred.", "",
             "Source: https://en.wikisource.org/wiki/The_slave_trade_of_east_Africa?oldid=13901313", "",
             "Retained export: " + SOURCE, "SHA-256: " + PRIMARY_PIN, "", rights, "",
             "The exact 92-record export retains one current revision per record. The credit table below identifies these retained revision contributors, including support records. It is not a complete authorship/contribution history; earlier contributor history and page-specific licensing remain unreviewed. Proofreader usernames are separately retained from the Page wikitext quality markers. Technical reconstruction does not authorize publication.", "",
             "The source supplies 23 scan-page records, positions 5 through 27. The Index places a dash at 1 through 4 and 41 through 44; 28 through 40 have no retained Page records. The linked Appendix and Notes A-C are absent, with unknown extent. No print images or complete print-witness/visual-collation claim is made.", "",
             "The repaired reading uses the root main-transclusion context. Four word-end templates explicitly supply their full-word second argument; two hws starts are suppressed by the retained template definition. Scan-page wikitext and its noinclude headers/footers remain exact source administration. Attached footnotes, links, emphasis, source styling and quotation continuations retain source ownership and order. All XML/revision/support fields remain located in private accounting; no support code was executed remotely.", "",
             "The original v3 candidate and dated proof claims remain preserved. Its U+FFFD preservation warning is withdrawn in this successor: the complete retained record texts contain zero replacement characters. Its flattened readable markup and page-context hyphenation are repaired; no whole-body additive inverse is claimed.", "",
             "## Retained revision contributors", "", "| Source record | Role | Revision | Retained contributor |", "| --- | --- | --- | --- |"]
    for row in record_rows(root):
        url = "https://en.wikisource.org/wiki/" + quote(row["title"].replace(" ", "_"), safe=":/") + "?oldid=" + row["revision_id"]
        lines.append("| [" + row["title"] + "](" + url + ") | " + row["role"] + " | " + row["revision_id"] + " | " + row["contributor"] + " |")
    labels = []
    for p in root.findall(M + "page"):
        if p.findtext(M + "title").startswith("Page:"):
            labels.extend(re.findall(r'<pagequality level="4" user="([^"]+)"', p.findtext(M + "revision/" + M + "text") or ""))
    lines.extend(["", "## Retained Page quality labels", "", ", ".join(dict.fromkeys(labels)) + ".", "",
                  "These are literal retained level-4 user labels, not an OCD human review or print-collation attestation.", ""])
    return "\n".join(lines).encode()
