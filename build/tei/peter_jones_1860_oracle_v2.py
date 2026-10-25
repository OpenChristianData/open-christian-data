"""Independent retained-Wikisource checks for the Peter Jones 1860 candidate."""

from __future__ import annotations

from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, _validation_authority_bindings
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


TEI = "http://www.tei-c.org/ns/1.0"
EXPORT = "http://www.mediawiki.org/xml/export-0.11/"
SOURCE = "raw/wikisource/peter-jones-life-and-journals-1860"
ORACLE_ID = "ocd-peter-jones-1860-independent-wikisource-oracle-v2"
ORACLE_VERSION = "2"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure(root: Path) -> str:
    paths = (
        "build/tei/peter_jones_1860_oracle_v2.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
        "ocd_kernel/lib/storage_topology.py",
    )
    return _sha(_json([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in paths]))


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", unescape(text), flags=re.UNICODE)


def _source_words(wikitext: str) -> list[str]:
    """Project visible lexical text independently of the TEI converter."""
    text = re.sub(r"<noinclude>.*?</noinclude>", "", wikitext, flags=re.I | re.S)
    if "<noinclude" in text.lower():
        raise ValueError("source noinclude balance failure")
    template = re.compile(r"\{\{([^{}]*)\}\}", re.S)

    def expand(match: re.Match[str]) -> str:
        fields = match.group(1).split("|")
        name = fields[0].strip().casefold()
        values = fields[1:]
        if name in {"hyphenated word start", "hyphenated word end", "dropinitial"}:
            return values[0] if values else ""
        if name in {"font-size", "fsx-block"}:
            return values[-1] if values else ""
        if name in {"small-caps", "center", "c", "cquote", "smaller", "smaller block", "xx-larger", "block center", "right", "left", "float right"}:
            return next((value for value in reversed(values) if "=" not in value.split("\n", 1)[0]), "")
        if name in {"rule", "upe", "gap", "rh", "smallrefs", "-"}:
            return ""
        raise ValueError(f"unaccounted source template: {name}")

    while "{{" in text:
        replaced = template.sub(expand, text)
        if replaced == text:
            raise ValueError("unaccounted nested source template")
        text = replaced
    text = re.sub(r"\[\[(?:Image|File):[^]]+\]\]", " ", text, flags=re.I)
    text = re.sub(r"\[\[([^]]+)\]\]", lambda match: match.group(1).split("|")[-1], text)
    text = re.sub(r"<[^>]*>", " ", text)
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("{|", "|}", "|-")):
            continue
        if stripped.startswith("|"):
            cells = []
            for item in stripped[1:].split("||"):
                cells.append(item.split("|", 1)[-1])
            line = " ".join(cells)
        lines.append(line.replace("''", ""))
    return _words(" ".join(lines))


def _tei_pages(div: etree._Element) -> dict[int, list[str]]:
    pages: dict[int, list[str]] = {}
    current: int | None = None

    def add(text: str | None) -> None:
        if current is not None and text:
            pages[current].extend(_words(text))

    def walk(node: etree._Element) -> None:
        nonlocal current
        if node.tag == f"{{{TEI}}}pb":
            number = node.get("n")
            if number is None or not number.isdecimal() or int(number) in pages:
                raise ValueError("candidate page milestone identity or duplicate failure")
            current = int(number)
            pages[current] = []
        else:
            add(node.text)
            for child in node:
                walk(child)
                add(child.tail)

    for child in div:
        if child.tag != f"{{{TEI}}}head":
            walk(child)
            add(child.tail)
    return pages


def _source_census(chunks: list[str]) -> dict[str, object]:
    totals = {"source_tables": 0, "source_rows": 0, "source_cells": 0, "notes": 0, "media_references": 0, "links": 0}
    media_names: list[str] = []
    links: list[tuple[str, str]] = []
    in_table = False
    row_open = False
    for chunk in chunks:
        body = re.sub(r"<noinclude>.*?</noinclude>", "", chunk, flags=re.I | re.S)
        totals["notes"] += len(re.findall(r"<ref\b", body, flags=re.I))
        names = re.findall(r"\[\[(?:Image|File):([^]|]+)(?:\|[^]]*)?\]\]", body, flags=re.I)
        media_names.extend(names)
        totals["media_references"] += len(names)
        for raw_link in re.findall(r"\[\[([^]]+)\]\]", body):
            parts = raw_link.split("|")
            if not parts[0].casefold().startswith(("image:", "file:")):
                links.append((parts[0], parts[-1] if len(parts) > 1 else parts[0]))
                totals["links"] += 1
        for line in body.splitlines():
            marker = line.strip()
            if marker.startswith("{|"):
                if in_table:
                    raise ValueError("source nested table in census")
                in_table, row_open = True, False
                totals["source_tables"] += 1
            elif marker.startswith("|}"):
                if not in_table:
                    raise ValueError("source unmatched table end in census")
                in_table, row_open = False, False
            elif in_table and marker.startswith("|-"):
                row_open = True
                totals["source_rows"] += 1
            elif in_table and marker.startswith("|"):
                if not row_open:
                    row_open = True
                    totals["source_rows"] += 1
                totals["source_cells"] += len(marker[1:].split("||"))
    if in_table:
        raise ValueError("source unclosed table in census")
    return {**totals, "media_names": media_names, "link_records": links}


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    root = source_manifest.repository_root
    authority = source_manifest.authority_path
    profile_bytes = authority("profile").read_bytes()
    profile = json.loads(profile_bytes)
    policy_bytes = authority("policy").read_bytes()
    policy = json.loads(policy_bytes)
    root_xml = etree.fromstring(authority("root-export").read_bytes(), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    exported: dict[str, tuple[str, str]] = {}
    for page in root_xml.findall(f"{{{EXPORT}}}page"):
        title = page.findtext(f"{{{EXPORT}}}title")
        revision = page.find(f"{{{EXPORT}}}revision")
        if title is None or revision is None or title in exported:
            raise ValueError("source export page inventory failure")
        exported[title] = (revision.findtext(f"{{{EXPORT}}}id") or "", revision.findtext(f"{{{EXPORT}}}text") or "")
    if len(exported) != 68 or exported[profile["root_title"]][0] != str(profile["root_revision"]) or exported[profile["index_title"]][0] != str(profile["index_revision"]):
        raise ValueError("source export fixed revision failure")
    index = exported[profile["index_title"]][1]
    if not all(value in index for value in ("|Publisher=Anson Green", "|Address=Toronto", "|Year=1860", "20=-", "21=1", "445to450=-")):
        raise ValueError("source edition/index boundary failure")
    root_receipt = json.loads(authority("root-receipt").read_bytes())
    linked_receipt = json.loads(authority("linked-receipt").read_bytes())
    leaf_receipt = json.loads(authority("leaf-receipt").read_bytes())
    query = json.loads(authority("revision-query").read_bytes())
    outer = json.loads(authority("outer-disposition").read_bytes())
    if root_receipt["member"]["sha256"] != _sha(authority("root-export").read_bytes()) or root_receipt["verification"]["member_inventory_sha256"] != _sha(authority("root-inventory").read_bytes()):
        raise ValueError("source root receipt binding failure")
    if linked_receipt["inventory"]["sha256"] != _sha(authority("linked-inventory").read_bytes()) or linked_receipt["query"]["sha256"] != _sha(authority("revision-query").read_bytes()):
        raise ValueError("source linked receipt binding failure")
    if leaf_receipt["page_inventory"]["sha256"] != _sha(authority("leaf-inventory").read_bytes()) or leaf_receipt["outer_disposition"]["sha256"] != _sha(authority("outer-disposition").read_bytes()):
        raise ValueError("source leaf receipt binding failure")
    if outer["index"]["parent_export_sha256"] != _sha(authority("root-export").read_bytes()):
        raise ValueError("source outer disposition binding failure")
    if len(linked_receipt["pages"]) != 15 or len(leaf_receipt["members"]) != 425:
        raise ValueError("source child or Page leaf count failure")
    api = {page["title"]: page for page in query["query"]["pages"].values()}
    leaf_text: dict[int, str] = {}
    for number, item in enumerate(leaf_receipt["members"], 20):
        if item["page_number"] != number or item["quality_status"] != ("Without text" if number == 20 else "Validated"):
            raise ValueError("source Page leaf order/quality failure")
        path = resolve_repo_path(root, f"{SOURCE}/page-leaves-20260925/{item['path']}")
        raw = path.read_bytes()
        if _sha(raw) != item["sha256"] or len(raw) != item["bytes"]:
            raise ValueError("source Page leaf hash failure")
        leaf_text[number] = raw.decode("utf-8", "strict")
    if _source_words(leaf_text[20]):
        raise ValueError("source blank Page has body text")
    source_children: list[dict[str, object]] = []
    for ordinal, item in enumerate(linked_receipt["pages"], 1):
        path = resolve_repo_path(root, f"{SOURCE}/linked-work-pages-20260925/{item['path']}")
        raw = path.read_bytes()
        if item["ordinal"] != ordinal or _sha(raw) != item["sha256"] or len(raw) != item["bytes"]:
            raise ValueError("source linked child hash/order failure")
        fixed = api[item["title"]]["revisions"][0]
        if fixed["revid"] != item["revision_id"] or fixed["slots"]["main"]["*"].encode("utf-8") != raw:
            raise ValueError("source linked child revision failure")
        selector = re.search(r'<pages\s+index="([^"]+)"\s+from=(\d+)\s+to=(\d+)\s*/>', raw.decode("utf-8"))
        if selector is None or selector.group(1) != profile["scan_index_name"] or (int(selector.group(2)), int(selector.group(3))) != (item["transclusion"]["from_page"], item["transclusion"]["to_page"]):
            raise ValueError("source child transclusion boundary failure")
        source_children.append({"ordinal": ordinal, "title": item["title"], "revision": item["revision_id"], "path": item["path"], "sha256": item["sha256"], "start": int(selector.group(2)), "end": int(selector.group(3)), "heading": re.search(r"\|\s*section\s*=\s*(.+)", raw.decode("utf-8")).group(1).strip()})
    if source_children != profile["children"] or source_children[0]["start"] != 20 or source_children[-1]["end"] != 444 or any(a["end"] + 1 != b["start"] for a, b in zip(source_children, source_children[1:])):
        raise ValueError("source child partition/profile failure")
    xml = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    schema = compiled_schema()
    if not schema.validate(tree):
        raise ValueError("candidate is not valid TEI P5: " + str(schema.error_log[:1]))
    if tree.tag != f"{{{TEI}}}TEI" or tree.get("{http://www.w3.org/XML/1998/namespace}id") != "peter-jones-1860-wikisource-edited-selection":
        raise ValueError("candidate volume identity failure")
    title = tree.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
    source_desc = tree.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc/{{{TEI}}}p")
    if title is None or title.text != "Life and Journals of Kah-ke-wa-quo-nā-by" or source_desc is None or "Toronto: Anson Green, 1860" not in (source_desc.text or "") or _sha(authority("root-export").read_bytes()) not in (source_desc.text or ""):
        raise ValueError("candidate source-bound edition metadata failure")
    front = tree.find(f"{{{TEI}}}text/{{{TEI}}}front/{{{TEI}}}div")
    body = tree.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if front is None or body is None or len(body) != 15 or front.get("type") != "source-paratext":
        raise ValueError("candidate front/child partition failure")
    front_pages = _tei_pages(front)
    if list(front_pages) != list(range(8, 20)):
        raise ValueError("candidate front Page milestone coverage failure")
    for number, tokens in front_pages.items():
        title = f"Page:Life and journals of Kah-ke-wa-quo-na-by.djvu/{number}"
        if tokens != _source_words(exported[title][1]):
            raise ValueError(f"candidate front Page text mismatch: {number}")
    expected_account_children = []
    for div, child in zip(body, source_children, strict=True):
        ordinal = child["ordinal"]
        if div.tag != f"{{{TEI}}}div" or div.get("n") != str(ordinal) or div.get("type") != "source-component" or div.get("corresp") != child["title"]:
            raise ValueError("candidate child identity/order failure")
        head = div.find(f"{{{TEI}}}head")
        if head is None or head.text != child["heading"]:
            raise ValueError("candidate child heading mismatch")
        pages = _tei_pages(div)
        if list(pages) != list(range(child["start"], child["end"] + 1)):
            raise ValueError("candidate child Page coverage/order failure")
        for number, tokens in pages.items():
            if tokens != _source_words(leaf_text[number]):
                raise ValueError(f"candidate Page text mismatch: {number}")
        expected_account_children.append(child)
    chunks = [exported[f"Page:Life and journals of Kah-ke-wa-quo-na-by.djvu/{n}"][1] for n in range(8, 20)] + [leaf_text[n] for n in range(20, 445)]
    census = _source_census(chunks)
    actual = {
        "source_tables": len(list(tree.iter(f"{{{TEI}}}table"))),
        "source_rows": len(list(tree.iter(f"{{{TEI}}}row"))),
        "source_cells": len(list(tree.iter(f"{{{TEI}}}cell"))),
        "notes": len(list(tree.iter(f"{{{TEI}}}note"))),
        "media_references": len([node for node in tree.iter(f"{{{TEI}}}milestone") if node.get("unit") == "unretained-media-reference"]),
        "links": len(list(tree.iter(f"{{{TEI}}}ref"))),
    }
    if actual != {key: census[key] for key in actual}:
        raise ValueError("candidate source markup census mismatch")
    if [node.get("n") for node in tree.iter(f"{{{TEI}}}milestone") if node.get("unit") == "unretained-media-reference"] != census["media_names"]:
        raise ValueError("candidate source media reference/order mismatch")
    target_ids = {child["title"]: "#peter-jones-1860-component-" + str(child["ordinal"]) for child in source_children}
    expected_refs = [(target, target_ids[target], label) for target, label in census["link_records"]]
    observed_refs = [(node.get("n"), node.get("target"), "".join(node.itertext())) for node in tree.iter(f"{{{TEI}}}ref")]
    if observed_refs != expected_refs:
        raise ValueError("candidate source link target/order mismatch")
    gaps = list(tree.iter(f"{{{TEI}}}gap"))
    if len(gaps) != 1 or gaps[0].get("reason") != "blank" or gaps[0].get("unit") != "page" or gaps[0].get("extent") != "1":
        raise ValueError("candidate blank Page status failure")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if account["contract"] != "ocd-peter-jones-1860-source-accounting-v2" or account["root_export_sha256"] != _sha(authority("root-export").read_bytes()) or account["root_paratext_pages"] != 12 or account["linked_child_count"] != 15 or account["page_leaf_count"] != 425 or account["blank_page"] != 20 or account["outer_disposition_sha256"] != _sha(authority("outer-disposition").read_bytes()) or account["tei_sha256"] != _sha(xml):
        raise ValueError("candidate source-accounting envelope mismatch")
    accounted = {key: sum(unit[key] for unit in [account["front"], *account["children"]]) for key in actual}
    if accounted != actual:
        raise ValueError("candidate source accounting markup census mismatch")
    source_page_hashes = {str(n): _sha(re.sub(r"<noinclude>.*?</noinclude>", "", chunk, flags=re.I | re.S).encode("utf-8")) for n, chunk in zip(range(8, 445), chunks, strict=True)}
    account_page_hashes = {**account["front"]["page_body_sha256"]}
    for unit in account["children"]:
        account_page_hashes.update(unit["page_body_sha256"])
    if account_page_hashes != source_page_hashes:
        raise ValueError("candidate source accounting Page body digests mismatch")
    if len(account["children"]) != 15 or any({key: item[key] for key in ("ordinal", "revision_id", "path", "sha256", "start", "end")} != {"ordinal": child["ordinal"], "revision_id": child["revision"], "path": child["path"], "sha256": child["sha256"], "start": child["start"], "end": child["end"]} for item, child in zip(account["children"], expected_account_children, strict=True)):
        raise ValueError("candidate child accounting mismatch")
    if candidate.member_bytes("README.source.md") != authority("readme").read_bytes() or json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"] or candidate.member_bytes("unresolved.jsonl") != b"".join(_json(item) for item in policy["unresolved"]):
        raise ValueError("candidate attribution, provenance, or unresolved mismatch")
    closure = _closure(root)
    if closure != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=_validation_authority_bindings(source_manifest)["source_sha256"],
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(authority("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(authority("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
