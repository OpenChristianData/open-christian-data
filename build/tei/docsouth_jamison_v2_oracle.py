
"""Independent source fidelity oracle for a versioned DocSouth route with exact retained figures."""
from __future__ import annotations
import hashlib, json, platform, sys
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
T = "{" + TEI + "}"
X = "{" + XML + "}"
ORACLE_ID = "ocd-docsouth-l763-jamison-independent-expat-oracle-retained-images"
ORACLE_VERSION = "3"
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
def _closure(root: Path) -> str:
    paths = ("build/tei/docsouth_jamison_v2_oracle.py", "ocd_kernel/reconstruction/contract.py")
    return _sha(_json([{"path": p, "sha256": _sha((root / p).read_bytes())} for p in paths]))
def _norm(value: str) -> str:
    return " ".join(value.split())
def _primary(node: ET.Element) -> str:
    parts: list[str] = []
    def visit(current: ET.Element) -> None:
        if current.text:
            parts.append(current.text)
        children = list(current)
        if current.tag in {"choice", T + "choice"}:
            children = children[:1]
        for child in children:
            visit(child)
            if child.tail:
                parts.append(child.tail)
    visit(node)
    return _norm("".join(parts))

def _title_statement(node: ET.Element, *, source_document: bool) -> tuple[str, ...] | None:
    if source_document:
        statement = node.find("teiHeader/fileDesc/titleStmt")
        title_tag = "title"
    else:
        statement = node.find(f"{T}teiHeader/{T}fileDesc/{T}titleStmt")
        title_tag = T + "title"
    if statement is None:
        return None
    return tuple(_primary(title) for title in statement if title.tag == title_tag)
def _image_checks(manifest: SourceManifest, receipt: dict, profile: dict, inventory: bytes) -> list[str]:
    problems: list[str] = []
    sequence = profile.get("figure_entity_sequence")
    image_entities = profile.get("image_entities")
    assets = profile.get("retained_image_assets")
    rows = receipt.get("image_members")
    if not isinstance(sequence, list) or not isinstance(image_entities, dict) or not isinstance(assets, list) or not isinstance(rows, list):
        return ["retained image inventory is incomplete"]
    by_entity = {row.get("entity"): row for row in rows if isinstance(row, dict)}
    asset_by_entity = {row.get("entity"): row for row in assets if isinstance(row, dict)}
    if len(by_entity) != len(rows) or len(asset_by_entity) != len(assets):
        problems.append("retained image entity inventory contains duplicates")
    if len(sequence) != len(set(sequence)) or set(sequence) != set(by_entity) or set(sequence) != set(asset_by_entity) or set(sequence) != set(image_entities):
        problems.append("retained image entities differ from source profile or receipt")
    authority_records = {item.get("name"): item for item in manifest.record.get("authorities", ())}
    inventory_rows = {}
    try:
        lines = inventory.decode("utf-8").splitlines()
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                problems.append("member inventory row is malformed")
                continue
            inventory_rows[parts[0]] = {"bytes": int(parts[1]), "sha256": parts[2]}
    except (UnicodeDecodeError, ValueError):
        problems.append("member inventory is not valid UTF-8 TSV")
    base = receipt.get("source_url", "").rsplit("/", 1)[0] + "/"
    for entity in sequence:
        if entity not in by_entity or entity not in asset_by_entity:
            continue
        source = by_entity[entity]
        asset = asset_by_entity[entity]
        expected_url = base + image_entities[entity]
        expected = {
            "entity": entity,
            "path": source.get("path"),
            "source_url": source.get("source_url"),
            "media_type": source.get("media_type"),
            "http_status": source.get("http_status"),
            "bytes": source.get("bytes"),
            "sha256": source.get("sha256"),
            "figure_c14n_sha256": source.get("figure_c14n_sha256"),
        }
        if asset != expected:
            problems.append(f"profile image authority differs from acquisition receipt for {entity}")
        if source.get("source_url") != expected_url or source.get("http_status") != 200:
            problems.append(f"exact provider URL/status differs for image {entity}")
        if source.get("media_type") != "image/jpeg":
            problems.append(f"retained image media type differs for {entity}")
        name = "retained-image-" + entity
        authority = authority_records.get(name)
        if not isinstance(authority, Mapping) or authority.get("path") != source.get("path"):
            problems.append(f"source manifest does not bind exact logical path for image {entity}")
            continue
        try:
            raw = manifest.authority_path(name).read_bytes()
        except (OSError, ValueError):
            problems.append(f"retained image cannot be resolved through storage topology for {entity}")
            continue
        if len(raw) != source.get("bytes") or _sha(raw) != source.get("sha256"):
            problems.append(f"retained image bytes/hash differ for {entity}")
        if not raw.startswith(b"\xff\xd8\xff"):
            problems.append(f"retained image bytes do not have JPEG signature for {entity}")
        inv = inventory_rows.get(Path(source.get("path", "")).name)
        if inv != {"bytes": source.get("bytes"), "sha256": source.get("sha256")}:
            problems.append(f"member inventory differs for image {entity}")
    return problems

def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    problems: list[str] = []
    raw = manifest.authority_path("official-source-member").read_bytes()
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_bytes())
    inventory = manifest.authority_path("member-inventory").read_bytes()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    content = candidate.member_bytes("content.tei.xml")
    source = ET.fromstring(raw)
    result = ET.fromstring(content)
    if source.tag != "TEI.2" or result.tag != T + "TEI":
        problems.append("expected one source TEI.2 and exactly one P5 TEI")
    source_titles = _title_statement(source, source_document=True)
    candidate_titles = _title_statement(result, source_document=False)
    if source_titles is None or candidate_titles is None:
        problems.append("source/candidate title statement absent")
    elif source_titles != candidate_titles:
        problems.append("title statement text differs from retained source")
    source_text = source.find("text")
    result_text = result.find(T + "text")
    if source_text is None or result_text is None:
        problems.append("source/candidate text envelope absent")
    else:
        for section in ("front", "body", "back"):
            s = source_text.find(section)
            c = result_text.find(T + section)
            if (s is None) != (c is None):
                problems.append(f"{section} envelope presence differs")
            elif s is not None and c is not None and _primary(s) != _primary(c):
                problems.append(f"{section} text/order differs")
    source_pages = [(p.get("id"), p.get("n")) for p in source.iter("pb")]
    candidate_pages = [(p.get(X + "id"), p.get("n")) for p in result.iter(T + "pb")]
    if source_pages != candidate_pages:
        problems.append("page marker identity, label, or order differs")
    expected_count = 193
    if len(source_pages) != expected_count:
        problems.append(f"source page-marker count differs from exact route expectation ({expected_count})")
    source_ids = [(n.get("id"), n.tag) for n in source.iter() if n.get("id") and n.tag != "language"]
    candidate_ids = [(n.get(X + "id"), n.tag) for n in result.iter() if n.get(X + "id")]
    if [i for i, _ in source_ids] != [i for i, _ in candidate_ids]:
        problems.append("source xml:id inventory or order differs")
    source_languages = [n.get("id") for n in source.iter("language") if n.get("id")]
    candidate_languages = [n.get("ident") for n in result.iter(T + "language") if n.get("ident")]
    if source_languages != candidate_languages:
        problems.append("source language identifiers differ")
    source_figures = [n.get("entity") for n in source.iter("figure") if n.get("entity")]
    candidate_graphics = [(n.get("n"), n.get("url")) for n in result.iter(T + "graphic")]
    expected_graphics = [(entity, receipt["source_url"].rsplit("/", 1)[0] + "/" + profile["image_entities"].get(entity, "")) for entity in source_figures]
    if source_figures != profile.get("figure_entity_sequence"):
        problems.append("source figure entity sequence differs from bound profile")
    if candidate_graphics != expected_graphics:
        problems.append("figure/entity/source URL inventory differs")
    if len([n for n in result.iter() if n.tag == T + "TEI"]) != 1:
        problems.append("candidate must contain exactly one top-level titled work")
    problems.extend(_image_checks(manifest, receipt, profile, inventory))
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if account.get("source_id") != receipt["source_id"] or account.get("work_id") != manifest.record["work_id"]:
        problems.append("source/work identity differs")
    if account.get("source_sha256") != _sha(raw) or account.get("tei_sha256") != _sha(content) or account.get("tei_bytes") != len(content):
        problems.append("source accountability does not bind exact bytes")
    if account.get("source_envelope") != profile.get("envelope") or account.get("page_markers") != profile.get("page_markers") or account.get("image_entities") != profile.get("image_entities"):
        problems.append("source envelope ledger differs from profile")
    if account.get("retained_image_assets") != profile.get("retained_image_assets"):
        problems.append("candidate accountability does not bind exact retained images")
    if "external-images" in {row.get("id") for row in policy.get("unresolved", []) if isinstance(row, dict)}:
        problems.append("policy still marks retained image bytes unresolved")
    if policy.get("resolved_resources", {}).get("figure_assets") != profile.get("retained_image_assets"):
        problems.append("policy resolved image inventory differs")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("readme").read_bytes():
        problems.append("source README differs")
    if json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]:
        problems.append("provenance differs")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_json(x) for x in policy["unresolved"]):
        problems.append("unresolved ledger differs")
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("p5-schema")), etree.XMLParser(resolve_entities=False, no_network=True)))
    if not schema.validate(etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))):
        problems.append("P5 schema invalid: " + str(schema.error_log.last_error))
    att = {
        "status": "pass" if not problems else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure(manifest.repository_root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
        "package_schema_sha256": manifest.record["package_schema"]["sha256"],
        "source_sha256": _sha(raw),
        "xsd_sha256": _sha(manifest.authority_path("p5-schema").read_bytes()),
        "policy_sha256": _sha(manifest.authority_path("policy").read_bytes()),
        "findings": problems,
    }
    att["result_sha256"] = _sha(_json(att))
    return att
_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
