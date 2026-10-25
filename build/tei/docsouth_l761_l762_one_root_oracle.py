"""Independent Expat source oracle for the six DocSouth TEI candidates."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
T = "{" + TEI + "}"
X = "{" + XML + "}"
ORACLE_ID = "ocd-docsouth-l761-l762-one-root-independent-source-oracle"
ORACLE_VERSION = "1"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _local(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _primary(node: ET.Element) -> str:
    parts: list[str] = []

    def visit(current: ET.Element) -> None:
        if current.text:
            parts.append(current.text)
        children = list(current)
        if current.tag == T + "choice":
            children = children[:1]
        for child in children:
            visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return "".join(parts)


def _tokens(value: str) -> str:
    return " ".join(value.split())


def _source_features(raw: bytes) -> dict:
    source = ET.fromstring(raw)
    if source.tag != "TEI.2":
        raise ValueError("source root is not TEI.2")
    images = dict(re.findall(rb'<!ENTITY\s+([A-Za-z0-9_-]+)\s+SYSTEM\s+"([^"]+\.jpg)"\s+NDATA\s+jpeg>', raw))
    figures = [node.get("entity") for node in source.iter("figure") if node.get("entity")]
    if any(entity.encode("ascii") not in images for entity in figures):
        raise ValueError("source figure refers to undeclared image entity")
    text = source.find("text")
    if text is None:
        raise ValueError("source text envelope is missing")
    sections = {}
    carriers = []
    for section in ("front", "body", "back"):
        part = text.find(section)
        if part is None:
            continue
        sections[section] = _sha(_tokens("".join(part.itertext())).encode("utf-8"))
        for ordinal, node in enumerate(part):
            head = next((h for h in node.iter() if h.tag == "head"), None)
            carriers.append({
                "section": section,
                "ordinal": ordinal,
                "tag": node.tag,
                "type": node.get("type"),
                "id": node.get("id"),
                "heading": _tokens("".join(head.itertext())) if head is not None else "",
                "text_sha256": _sha(_tokens("".join(node.itertext())).encode("utf-8")),
            })
    return {
        "element_counts": {tag: sum(_local(n) == tag for n in source.iter()) for tag in
                           ("div1", "div2", "div3", "div4", "pb", "figure", "ref", "note", "head", "lg", "l", "sic", "corr", "q")},
        "image_entities": {name.decode("ascii"): filename.decode("ascii") for name, filename in images.items()},
        "figure_entities_ordered": figures,
        "page_markers": [[n.get("id"), n.get("n"), n.get("rend")] for n in source.iter("pb")],
        "sections": sections,
        "carriers": carriers,
        "source_ids": [n.get("id") for n in source.iter() if n.get("id") and n.tag != "language"],
        "headings": [_tokens("".join(n.itertext())) for n in source.iter("head")],
        "notes": [_tokens("".join(n.itertext())) for n in source.iter("note")],
        "availability": [_tokens("".join(n.itertext())) for n in source.iter("availability")],
    }



def _constituents(raw: bytes, source_id: str) -> list[dict]:
    """Source-native selectors and exact reading scopes, independent of conversion."""
    source = ET.fromstring(raw)
    text = source.find("text")
    if text is None or text.find("body") is None:
        raise ValueError("source body is missing")
    body = text.find("body")
    front = text.find("front")
    result = []

    def add(identity: str, selector: str, title: str, role: str, nodes: list[ET.Element],
            *, author: str = "", front_nodes: list[ET.Element] | None = None) -> None:
        reading = _tokens("".join("".join(node.itertext()) for node in nodes))
        pages = [n.get("id") for node in nodes for n in node.iter("pb")]
        front_reading = _tokens("".join("".join(node.itertext()) for node in (front_nodes or [])))
        result.append({
            "tei_xml_id": identity,
            "source_selector": selector,
            "title": title,
            "role": role,
            "author": author,
            "body_text_sha256": _sha(reading.encode("utf-8")),
            "body_page_ids": pages,
            "front_text_sha256": _sha(front_reading.encode("utf-8")),
        })

    if source_id == "docsouth-holsey":
        top = body.findall("div1")
        if len(top) != 3 or front is None:
            raise ValueError("Holsey source top-level boundaries differ")
        add("holsey-volume-front", "/TEI.2/text/front", "Shared volume front matter",
            "shared-front", [], front_nodes=[front])
        add("holsey-autobiography", "/TEI.2/text/body/div1[1]", "Autobiography of Bishop L. H. Holsey",
            "work", [top[0]], author="L. H. Holsey")
        sermon_prefix = [n for n in top[1] if n.tag != "div2"]
        add("holsey-sermons-group", "/TEI.2/text/body/div1[2]/head-and-opening-pb", "Sermons group",
            "shared-group", sermon_prefix)
        for index, unit in enumerate(top[1].findall("div2"), 1):
            head = unit.find("head")
            title = _tokens("".join(head.itertext())) if head is not None else ""
            add(f"holsey-sermon-{index:02d}", f"/TEI.2/text/body/div1[2]/div2[{index}]",
                title, "work", [unit], author="L. H. Holsey")
        later_prefix = [n for n in top[2] if n.tag != "div2"]
        add("holsey-later-group", "/TEI.2/text/body/div1[3]/opening-pb", "Later works group",
            "shared-group", later_prefix)
        for index, unit in enumerate(top[2].findall("div2"), 1):
            head = unit.find("head")
            title = _tokens("".join(head.itertext())) if head is not None else ""
            add(f"holsey-later-work-{index:02d}", f"/TEI.2/text/body/div1[3]/div2[{index}]",
                title, "work", [unit], author="L. H. Holsey")
    elif source_id == "docsouth-heard":
        chapters = body.findall("div1")
        if len(chapters) != 10 or front is None:
            raise ValueError("Heard source ten-chapter boundary differs")
        add("heard-autobiography", "/TEI.2/text/body/div1[1..9]",
            "From Slavery to the Bishopric in the A.M.E. Church: An Autobiography",
            "work", chapters[:9], author="William H. Heard", front_nodes=[front])
        poem = chapters[9]
        author = poem.find("docAuthor")
        if author is None or "EPHRAIM D. TYLER" not in _tokens("".join(author.itertext())):
            raise ValueError("Heard Tyler poem authorship differs")
        add("heard-tyler-poem", "/TEI.2/text/body/div1[10]",
            "The Life of William H. Heard: An Original Poem", "work", [poem],
            author="Ephraim D. Tyler")
    else:
        add("parent-edition", "/TEI.2/text/body", "Complete retained edition", "work",
            [body], front_nodes=[front] if front is not None else [])
    return result

def _candidate_section(root: ET.Element, section: str) -> list[ET.Element]:
    if root.tag == T + "TEI":
        part = root.find(T + "text/" + T + section)
        return [part] if part is not None else []
    if root.tag != T + "teiCorpus":
        return []
    result = []
    for child in root.findall(T + "TEI"):
        part = child.find(T + "text/" + T + section)
        if part is not None:
            result.append(part)
    return result


def _check_content(manifest: SourceManifest, content: bytes, *, schema: bool = True) -> list[str]:
    problems: list[str] = []
    raw = manifest.authority_path("official-source-member").read_bytes()
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    try:
        source = ET.fromstring(raw)
        candidate = ET.fromstring(content)
    except ET.ParseError as exc:
        return [f"Expat XML parsing failed: {exc}"]
    expected = _source_features(raw)
    if expected != profile["source_features"]:
        problems.append("source-derived carrier and media profile differs from retained XML")
    expected_constituents = _constituents(raw, manifest.record["source_id"])
    if expected_constituents != profile["constituent_units"]:
        problems.append("source-attested constituent selectors or ownership differ")
    if candidate.tag == T + "TEI":
        body = candidate.find(T + "text/" + T + "body")
        groups = [n for n in body.findall(T + "div") if n.get("type") == "source-constituent"] if body is not None else []
        body_units = [unit for unit in expected_constituents if unit["role"] != "shared-front"]
        if len(groups) != len(body_units):
            problems.append("one-root constituent division count differs")
        for group, unit in zip(groups, body_units):
            if group.get("n") != unit["tei_xml_id"]:
                problems.append("one-root constituent ID/order differs")
                continue
            if _sha(_tokens(_primary(group)).encode("utf-8")) != unit["body_text_sha256"]:
                problems.append(f"constituent body scope differs: {unit['tei_xml_id']}")
            if [n.get(X + "id") for n in group.iter(T + "pb")] != unit["body_page_ids"]:
                problems.append(f"constituent page ownership differs: {unit['tei_xml_id']}")
    text_root = source.find("text")
    if text_root is None:
        problems.append("source text envelope is absent")
    else:
        observed_scopes = {}
        for section in ("front", "body", "back"):
            part = text_root.find(section)
            if part is None:
                continue
            labels = [page.get("n") for page in part.iter("pb")]
            observed_scopes[section] = {
                "pb_nodes": len(labels),
                "distinct_labels": len(set(labels)),
                "duplicate_labels": sorted(label for label in set(labels) if labels.count(label) > 1),
            }
        if observed_scopes != profile["page_marker_scopes"]:
            problems.append("scoped source page marker and duplicate counts differ")
        body = text_root.find("body")
        if body is not None:
            numeric = [int(page.get("n")) for page in body.iter("pb") if (page.get("n") or "").isdigit()]
            jumps = [n for n in range(min(numeric), max(numeric) + 1) if n not in set(numeric)]
            if (len(numeric), jumps) != (profile["body_page_marker_count"], profile["unmarked_page_numbers"]):
                problems.append("source body page marker count or unmarked numbers differ")
    if len(expected["page_markers"]) != profile["total_page_markers"] or len({n[1] for n in expected["page_markers"]}) != profile["total_distinct_page_labels"]:
        problems.append("full-envelope page marker total or distinct-label count differs")
    if candidate.tag != T + "TEI":
        problems.append("one top-level titled work must have exactly one TEI root")
    if manifest.record["source_id"] == "docsouth-heard":
        body = candidate.find(T + "text/" + T + "body")
        groups = [n for n in body.findall(T + "div") if n.get("type") == "source-constituent"] if body is not None else []
        ids = [n.get("n") for n in groups]
        if ids != ["heard-autobiography", "heard-tyler-poem"]:
            problems.append("Heard autobiography and Tyler poem boundary/order differs")
        title_stmt = candidate.find(T + "teiHeader/" + T + "fileDesc/" + T + "titleStmt")
        attributions = title_stmt.findall(T + "respStmt") if title_stmt is not None else []
        attribution = next((node for node in attributions if _tokens(_primary(node.find(T + "resp"))) == "author of the Tyler poem component"), None)
        if attribution is None or _tokens(_primary(attribution.find(T + "name"))) != "Ephraim D. Tyler":
            problems.append("Tyler poem's source-attested component-author attribution differs")
    source_text = source.find("text")
    for section in ("front", "body", "back"):
        original = source_text.find(section) if source_text is not None else None
        actual = _candidate_section(candidate, section)
        if original is None:
            if actual:
                problems.append(f"unexpected {section} section")
            continue
        if not actual:
            problems.append(f"missing {section} section")
            continue
        observed = _tokens("".join(_primary(node) for node in actual))
        wanted = _tokens("".join(original.itertext()))
        if observed != wanted:
            problems.append(f"ordered {section} text differs")
    source_heads = [_tokens("".join(n.itertext())) for n in source.iter("text") if False]
    source_heads = [_tokens("".join(n.itertext())) for n in source.find("text").iter("head")]
    candidate_heads = [_tokens(_primary(n)) for node in _candidate_section(candidate, "front") + _candidate_section(candidate, "body") + _candidate_section(candidate, "back") for n in node.iter(T + "head")]
    if source_heads != candidate_heads:
        problems.append("source heading text or order differs")
    source_pages = [(n.get("id"), n.get("n")) for n in source.iter("pb")]
    candidate_pages = [(n.get(X + "id"), n.get("n")) for n in candidate.iter(T + "pb")]
    if source_pages != candidate_pages:
        problems.append("page marker identity, number, or order differs")
    source_notes = [_tokens("".join(n.itertext())) for n in source.iter("note")]
    candidate_notes = [_tokens(_primary(n)) for n in candidate.iter(T + "note")]
    if source_notes != candidate_notes:
        problems.append("source notes or note order differ")
    source_edges = []
    for node in source.iter():
        if node.tag == "a":
            source_edges.append(node.get("href"))
        elif node.tag == "ref":
            target = node.get("target")
            source_edges.append(
                " ".join(part if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", part) else "#" + part.lstrip("#")
                         for part in target.split()) if target else None
            )
    candidate_edges = [node.get("target") for node in candidate.iter(T + "ref")]
    if source_edges != candidate_edges:
        problems.append("source ref/href targets or edge order differ")
    source_corrections = [
        [(node.tag, "".join(node.itertext())),
         ("corr" if node.tag == "sic" else "sic", node.get("corr") if node.tag == "sic" else node.get("sic"))]
        for node in source.iter() if node.tag in ("sic", "corr") and (node.get("corr") or node.get("sic"))
    ]
    candidate_corrections = [
        [(_local(child), "".join(child.itertext())) for child in node]
        for node in candidate.iter(T + "choice")
    ]
    if source_corrections != candidate_corrections:
        problems.append("source correction alternatives or order differ")
    for tag in ("lg", "l", "byline", "docAuthor"):
        source_units = [_tokens("".join(node.itertext())) for node in source.iter(tag)]
        candidate_units = [_tokens(_primary(node)) for node in candidate.iter(T + tag)]
        if source_units != candidate_units:
            problems.append(f"source {tag} text, grouping, or order differs")
    source_header = source.find("teiHeader")
    candidate_header = candidate.find(T + "teiHeader")
    if source_header is None or candidate_header is None:
        problems.append("source or candidate primary header is absent")
    else:
        for role in ("author", "editor", "titlePage"):
            original_roles = [_tokens("".join(n.itertext())) for n in source_header.iter(role)]
            migrated_roles = [_tokens(_primary(n)) for n in candidate_header.iter(T + role)]
            if role == "titlePage":
                migrated_roles = [_tokens(_primary(n)) for n in candidate.iter(T + role)]
                original_roles = [_tokens("".join(n.itertext())) for n in source.iter(role)]
            if original_roles != migrated_roles:
                problems.append(f"source {role} role text/order differs")
    source_divs = {level: [n for n in source.iter(f"div{level}")] for level in range(1, 5)}
    candidate_divs = {level: [n for n in candidate.iter(T + "div") if n.get("type") == f"source-div-{level}"] for level in range(1, 5)}
    for level in range(1, 5):
        if len(source_divs[level]) != len(candidate_divs[level]):
            problems.append(f"source division level {level} count differs")
        if level > 1 or manifest.record["source_id"] != "docsouth-holsey":
            for old, new in zip(source_divs[level], candidate_divs[level]):
                if _tokens("".join(old.itertext())) != _tokens(_primary(new)):
                    problems.append(f"source division level {level} text/attachment differs")
                    break
    source_figures = [n.get("entity") for n in source.iter("figure") if n.get("entity")]
    candidate_graphics = [(n.get("n"), n.get("url")) for n in candidate.iter(T + "graphic")]
    source_url = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))["source_url"]
    target_base = source_url.rsplit("/", 1)[0] + "/"
    expected_graphics = [(entity, target_base + expected["image_entities"][entity]) for entity in source_figures]
    if candidate_graphics != expected_graphics:
        problems.append("figure entity or external JPEG target/order differs")
    source_rights = [_tokens("".join(n.itertext())) for n in source.iter("availability")]
    candidate_rights = [_tokens(_primary(n)) for n in candidate.iter(T + "availability")]
    if source_rights != candidate_rights:
        problems.append("actual source rights statement differs")
    source_ids = [n.get("id") for n in source.iter() if n.get("id") and n.tag != "language"]
    candidate_ids = [n.get(X + "id") for n in candidate.iter() if n.get(X + "id") and n.tag not in (T + "TEI", T + "teiCorpus")]
    if source_ids != candidate_ids:
        problems.append("source XML IDs or order differ")
    if len(candidate_ids) != len(set(candidate_ids)):
        problems.append("duplicate candidate XML IDs")
    for n in candidate.iter():
        for attr in ("target", "ana"):
            value = n.get(attr)
            if not value:
                continue
            for target in value.split():
                if target.startswith("#") and target[1:] not in candidate_ids:
                    problems.append(f"unclosed local {attr} target {target}")
    if schema:
        schema_doc = etree.XMLSchema(etree.parse(str(manifest.authority_path("p5-schema")), etree.XMLParser(resolve_entities=False, no_network=True)))
        parsed = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
        if not schema_doc.validate(parsed):
            problems.append(f"TEI P5 XSD validation failed: {schema_doc.error_log.last_error}")
        if candidate.tag == T + "teiCorpus":
            for child in parsed.findall(T + "TEI"):
                if not schema_doc.validate(child):
                    problems.append(f"constituent TEI fails standalone P5 validation: {child.get(X + 'id')}")
    return problems


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    content = candidate.member_bytes("content.tei.xml")
    problems = _check_content(manifest, content)
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    policy = json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    if account.get("tei_sha256") != _sha(content) or account.get("tei_bytes") != len(content):
        problems.append("source accountability does not bind candidate bytes")
    if account.get("source_sha256") != receipt["member"]["sha256"]:
        problems.append("source accountability does not bind retained XML")
    if account.get("source_features") != profile["source_features"]:
        problems.append("source accountability does not bind source profile")
    if account.get("constituent_units") != profile["constituent_units"]:
        problems.append("source accountability does not bind constituent work selectors")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("readme").read_bytes():
        problems.append("attribution README differs from source authority")
    if json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]:
        problems.append("provenance differs from declared mapping policy")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(item) for item in policy["unresolved"]):
        problems.append("unresolved ledger differs from declared gaps")
    result = {
        "status": "pass" if not problems else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _sha(Path(__file__).read_bytes()),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
        "package_schema_sha256": manifest.record["package_schema"]["sha256"],
        "source_sha256": receipt["member"]["sha256"],
        "xsd_sha256": _sha(manifest.authority_path("p5-schema").read_bytes()),
        "policy_sha256": _sha(manifest.authority_path("policy").read_bytes()),
        "findings": problems,
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()