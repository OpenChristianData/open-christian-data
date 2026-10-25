"""Independent Expat fidelity oracle for the exact retained Gaines source with title-statement binding."""
from __future__ import annotations
import hashlib, json, platform, sys, re
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"; XML = "http://www.w3.org/XML/1998/namespace"
T = "{" + TEI + "}"; X = "{" + XML + "}"
ORACLE_ID = "ocd-docsouth-gaines-exact-v5-expat-oracle"; ORACLE_VERSION = "5"
def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _json(value: object) -> bytes: return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
def _closure(root: Path) -> str:
    paths = ("build/tei/docsouth_gaines_exact_v5_oracle.py", "ocd_kernel/reconstruction/contract.py")
    return _sha(_json([{"path": p, "sha256": _sha((root / p).read_bytes())} for p in paths]))
def _norm(value: str) -> str: return " ".join(value.split())
def _text(node: ET.Element) -> str: return _norm("".join(node.itertext()))
def _primary(node: ET.Element) -> str:
    parts: list[str] = []
    def visit(current: ET.Element) -> None:
        if current.text: parts.append(current.text)
        children = list(current)
        if current.tag in {"choice", T + "choice"}: children = children[:1]
        for child in children:
            visit(child)
            if child.tail: parts.append(child.tail)
    visit(node)
    return _norm("".join(parts))

def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    problems: list[str] = []
    raw = manifest.authority_path("official-source-member").read_bytes()
    content = candidate.member_bytes("content.tei.xml")
    source = ET.fromstring(raw); result = ET.fromstring(content)
    if source.tag != "TEI.2" or result.tag != T + "TEI": problems.append("expected one source TEI.2 and exactly one P5 TEI")
    source_text = source.find("text"); result_text = result.find(T + "text")
    if source_text is None or result_text is None: problems.append("source/candidate text envelope absent")
    else:
        for section in ("front", "body", "back"):
            s = source_text.find(section); c = result_text.find(T + section)
            if (s is None) != (c is None): problems.append(f"{section} envelope presence differs")
            elif s is not None and c is not None and _primary(s) != _primary(c): problems.append(f"{section} text/order differs")
    # Independently derive rendition and attachment from Expat source nodes.
    def rendition_units(text_node, prefix):
        # Text offsets survive P4-to-P5 schema wrapper normalization while
        # binding each rendition to its exact source-attested text span.
        units = []
        offset = 0
        def advance(text):
            nonlocal offset
            offset += sum(not c.isspace() for c in (text or ""))
        def visit(node):
            start = offset
            advance(node.text)
            children = list(node)
            if node.tag in {"choice", T + "choice"}: children = children[:1]
            for child in children:
                visit(child)
                advance(child.tail)
            if node.tag == prefix + "hi":
                units.append((start, offset, node.get("rend"), _primary(node)))
        if text_node is not None: visit(text_node)
        return units
    if rendition_units(source_text, "") != rendition_units(result_text, T):
        problems.append("source inline rendition, text, or attachment differs")
    source_heads = [_primary(n) for n in source_text.iter("head")]
    candidate_heads = [_primary(n) for n in result_text.iter(T + "head")]
    if source_heads != candidate_heads: problems.append("source heading wording/order differs")
    source_divs = [(n.tag[3:], n.get("id")) for n in source_text.iter() if n.tag.startswith("div") and n.tag[3:].isdigit()]
    candidate_divs = [(n.get("type")[11:], n.get(X + "id")) for n in result_text.iter(T + "div") if (n.get("type") or "").startswith("source-div-")]
    if source_divs != candidate_divs: problems.append("source division level/identity/order differs")
    def source_links():
        links = []
        for node in source.iter():
            target = node.get("href") if node.tag == "a" else node.get("target")
            if target:
                if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                    target = " ".join("#" + part.lstrip("#") for part in target.split())
                links.append((target, _primary(node)))
        return links
    candidate_links = [(node.get("target"), _primary(node)) for node in result.iter() if node.get("target")]
    if source_links() != candidate_links: problems.append("source link target, order, or label differs")
    id_set = {node.get(X + "id") for node in result.iter() if node.get(X + "id")}
    for target, _ in candidate_links:
        if any(value.startswith("#") and value[1:] not in id_set for value in target.split()):
            problems.append("unresolved local source link target")
    source_pages = [(p.get("id"), p.get("n")) for p in source.iter("pb")]
    candidate_pages = [(p.get(X + "id"), p.get("n")) for p in result.iter(T + "pb")]
    if source_pages != candidate_pages: problems.append("page marker identity, label, or order differs")
    source_ids = [(n.get("id"), n.tag) for n in source.iter() if n.get("id") and n.tag != "language"]
    candidate_ids = [(n.get(X + "id"), n.tag) for n in result.iter() if n.get(X + "id")]
    if [i for i, _ in source_ids] != [i for i, _ in candidate_ids]: problems.append("source xml:id inventory or order differs")
    source_languages = [n.get("id") for n in source.iter("language") if n.get("id")]
    candidate_languages = [n.get("ident") for n in result.iter(T + "language") if n.get("ident")]
    if source_languages != candidate_languages: problems.append("source language identifiers differ")
    sfig = [n.get("entity") for n in source.iter("figure") if n.get("entity")]
    cgraphics = [(n.get("n"), n.get("url")) for n in result.iter(T + "graphic")]
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_bytes())
    base = receipt["source_url"].rsplit("/", 1)[0] + "/"
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    expected_graphics = [(e, base + profile["image_entities"][e]) for e in sfig]
    if cgraphics != expected_graphics: problems.append("figure/entity/image URL inventory differs")
    if len([n for n in result.iter() if n.tag == T + "TEI"]) != 1: problems.append("candidate must contain exactly one top-level titled work")
    source_title_statements = source.findall(".//titleStmt")
    candidate_title_statements = result.findall(".//" + T + "titleStmt")
    source_title_values = [[_text(node) for node in statement.findall("./title")] for statement in source_title_statements]
    candidate_title_values = [[_text(node) for node in statement.findall(T + "title")] for statement in candidate_title_statements]
    if not source_title_statements or source_title_values != candidate_title_values:
        problems.append("source/candidate title statement wording, order, or cardinality differs")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    if account.get("source_sha256") != _sha(raw) or account.get("tei_sha256") != _sha(content) or account.get("tei_bytes") != len(content): problems.append("source accountability does not bind exact bytes")
    if account.get("source_envelope") != profile["envelope"] or account.get("page_markers") != profile["page_markers"] or account.get("image_entities") != profile["image_entities"]: problems.append("source envelope ledger differs from profile")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("readme").read_bytes(): problems.append("source README differs")
    if json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]: problems.append("provenance differs")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(x) for x in policy["unresolved"]): problems.append("unresolved ledger differs")
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("p5-schema")), etree.XMLParser(resolve_entities=False, no_network=True)))
    if not schema.validate(etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))): problems.append("P5 schema invalid: " + str(schema.error_log.last_error))
    att = {"status": "pass" if not problems else "fail", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
           "implementation_sha256": _sha(Path(__file__).read_bytes()), "import_closure_sha256": _closure(manifest.repository_root),
           "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
           "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
           "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
           "package_schema_sha256": manifest.record["package_schema"]["sha256"], "source_sha256": _sha(raw),
           "xsd_sha256": _sha(manifest.authority_path("p5-schema").read_bytes()),
           "policy_sha256": _sha(manifest.authority_path("policy").read_bytes()), "findings": problems}
    att["result_sha256"] = _sha(_json(att)); return att

_oracle.oracle_id = ORACLE_ID; _oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
