"""Producer-independent retained-source oracle for the Bunyan TEI candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.lib.storage_topology import resolve_repo_path


ORACLE_ID = "ocd-pilgrims-progress-source-to-tei-oracle"
ORACLE_VERSION = "1"
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
TEI = "http://www.tei-c.org/ns/1.0"
EPUB_TYPE = f"{{{EPUB}}}type"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _strict(content: bytes, label: str) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        out = {}
        for key, value in values:
            if key in out:
                raise ValueError(f"{label} duplicate key {key!r}")
            out[key] = value
        return out
    value = json.loads(content.decode(), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _members(manifest: SourceManifest) -> list[tuple[str, Path, bytes]]:
    result = []
    for authority in manifest.record["authorities"]:
        if authority.get("role") == "primary-source":
            path = manifest.authority_path(str(authority["name"]))
            logical = str(authority["path"]).split("john-bunyan_the-pilgrims-progress/", 1)[1]
            result.append((logical, path, path.read_bytes()))
    return sorted(result)


def _git_evidence(checkout: Path) -> dict[str, object]:
    resolved = checkout.resolve(strict=True)
    command = ["git", "-c", f"safe.directory={resolved}", "-C", str(resolved)]
    def query(*args: str) -> str:
        completed = subprocess.run(command + list(args), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        return completed.stdout
    return {"commit": query("rev-parse", "--verify", "HEAD").strip(), "tree": query("rev-parse", "--verify", "HEAD^{tree}").strip(), "clean": not bool(query("status", "--porcelain=v1", "--untracked-files=all")), "tracked_members": sorted(query("ls-files").splitlines())}


def _runtime_paths(repo: Path) -> dict[str, str]:
    import ocd_kernel.reconstruction.contract as contract_module
    observed = {"oracle": str(Path(__file__).resolve(strict=True)), "contract": str(Path(contract_module.__file__).resolve(strict=True))}
    expected = {"oracle": str((repo / "build/tei/pilgrims_progress_oracle.py").resolve(strict=True)), "contract": str((repo / "ocd_kernel/reconstruction/contract.py").resolve(strict=True))}
    if any(not Path(observed[key]).samefile(Path(expected[key])) for key in expected):
        raise ValueError(f"runtime import shadow detected: {observed!r}")
    return expected


def _observations(logical: str, root: etree._ElementTree) -> list[dict[str, object]]:
    records = []
    represented_nodes = {
        node
        for body in root.xpath(
            "//*[local-name()='body' and namespace-uri()=$namespace]",
            namespace=XHTML,
        )
        for node in body.iter()
    }
    for element in root.iter():
        disposition = "represented" if element in represented_nodes else "evidence-only"
        path = root.getpath(element)
        records.append({"member": logical, "kind": "element", "path": path, "name": etree.QName(element).localname, "value_sha256": _sha(etree.QName(element).text.encode()), "disposition": disposition})
        for name, value in sorted(element.attrib.items()):
            records.append({"member": logical, "kind": "attribute", "path": path, "name": etree.QName(name).text, "value_sha256": _sha(value.encode()), "disposition": disposition})
        if element.text and element.text.strip():
            records.append({"member": logical, "kind": "text", "path": path + "/text()", "name": "text", "value_sha256": _sha(element.text.encode()), "disposition": disposition})
        if element.tail and element.tail.strip():
            records.append({"member": logical, "kind": "text", "path": path + "/following-sibling-text()", "name": "tail", "value_sha256": _sha(element.tail.encode()), "disposition": disposition})
    for index, record in enumerate(records, 1):
        record["observation_id"] = f"{logical}#{index:05d}"
    return records


def _types(node: etree._Element) -> set[str]:
    return set(node.get(EPUB_TYPE, "").split())


def _source_features(roots: Mapping[str, etree._ElementTree], spine: list[str]) -> tuple[dict[str, object], list[dict[str, object]]]:
    ns = {"x": XHTML, "epub": EPUB, "xml": "http://www.w3.org/XML/1998/namespace"}
    sections = []
    spine_roots = []
    for href in spine:
        logical = "src/epub/" + href
        tree = roots[logical]
        spine_roots.append((href, tree))
        body = tree.find(".//x:body", ns)
        if body is None:
            raise ValueError("spine member missing body")
        matter = next((item.removesuffix("matter") for item in _types(body) if item in {"frontmatter", "bodymatter", "backmatter"}), None)
        source_sections = body.findall("x:section", ns)
        if len(source_sections) != 1:
            raise ValueError("spine member section count drifted")
        section = source_sections[0]
        heading = next(("".join(node.itertext()) for node in section if etree.QName(node).localname.startswith("h")), "")
        sections.append({"member": logical, "matter": matter, "id": section.get("id"), "heading_sha256": _sha(heading.encode())})

    typed = [(href, node) for href, tree in spine_roots for node in tree.xpath("//*[@epub:type]", namespaces=ns)]
    groups = [(href, node) for href, node in typed if _types(node) & {"z3998:poem", "z3998:verse", "z3998:song"}]
    noterefs = [node for _, node in typed if "noteref" in _types(node)]
    backlinks = [node for _, node in typed if "backlink" in _types(node)]
    endnotes = roots["src/epub/text/endnotes.xhtml"].xpath("//x:li[@epub:type='endnote']", namespaces=ns)
    expected_ids = [str(i) for i in range(1, 1011)]
    if [node.get("id", "").removeprefix("noteref-") for node in noterefs] != expected_ids:
        raise ValueError("source note-reference order or identity drifted")
    if [node.get("id", "").removeprefix("note-") for node in endnotes] != expected_ids:
        raise ValueError("source endnote order or identity drifted")
    if [node.get("href", "").rsplit("#noteref-", 1)[-1] for node in backlinks] != expected_ids:
        raise ValueError("source note-backlink order or identity drifted")
    if ["".join(node.itertext()).strip() for node in noterefs] != expected_ids:
        raise ValueError("source visible note labels drifted")
    lists = [node for _, tree in spine_roots for node in tree.xpath("//x:ol|//x:ul", namespaces=ns)]
    cites = [node for _, tree in spine_roots for node in tree.xpath("//x:cite", namespaces=ns)]
    attributed = sum(bool(note.xpath(".//x:cite", namespaces=ns)) for note in endnotes)
    inline = {tag: sum(len(tree.xpath("//x:" + tag, namespaces=ns)) for _, tree in spine_roots) for tag in ("a","abbr","b","i","em","cite","span","time","br","img")}
    cite_strings = [" ".join("".join(node.itertext()).split()) for node in cites]
    if _sha(_canonical(cite_strings)) != "3e513537add025175f1d1c8687800798fd4db8c518cf7d2f0094fa7d2abfbf1b":
        raise ValueError("ordered cite-string evidence drifted")
    features = {
        "note_references": len(noterefs), "note_bodies": len(endnotes), "note_backlinks": len(backlinks), "visible_note_labels": len(noterefs),
        "lists": len(lists), "list_items": sum(len(node.xpath("./x:li", namespaces=ns)) for node in lists),
        "attributed_notes": attributed, "unattributed_notes": len(endnotes) - attributed, "cites": len(cites),
        "distinct_cite_strings": len(set(cite_strings)),
        "ordered_cite_strings_sha256": "3e513537add025175f1d1c8687800798fd4db8c518cf7d2f0094fa7d2abfbf1b",
        "verse_groups": len(groups), "poems": sum("z3998:poem" in _types(node) for _, node in groups),
        "verses": sum("z3998:verse" in _types(node) for _, node in groups), "songs": sum("z3998:song" in _types(node) for _, node in groups),
        "stanzas": sum(len(node.xpath("./x:p", namespaces=ns)) for _, node in groups),
        "verse_lines": sum(sum(1 + len(p.xpath(".//x:br", namespaces=ns)) for p in node.xpath("./x:p", namespaces=ns)) for _, node in groups),
        "indentation_spans": sum(1 for _, tree in spine_roots for node in tree.xpath("//x:span[@class]", namespaces=ns) if (node.get("class") or "").startswith("i")),
        "abbr_eoc_renditions": sum(len(tree.xpath("//x:abbr[@class='eoc']", namespaces=ns)) for _, tree in spine_roots),
        "body_verse_groups": sum(href in {"text/part-1.xhtml", "text/part-2.xhtml"} for href, _ in groups),
        "front_verse_groups": sum(href in {"text/preface-1.xhtml", "text/preface-2.xhtml"} for href, _ in groups),
        "back_verse_groups": sum(href == "text/uncopyright.xhtml" for href, _ in groups),
        "note_verse_groups": sum(href == "text/endnotes.xhtml" for href, _ in groups),
        "language_spans": sum(1 for _, tree in spine_roots for node in tree.xpath("//*[@xml:lang]", namespaces=ns) if etree.QName(node).localname != "html"),
        "image_borne_strings": sum(1 for logical, tree in roots.items() if logical.endswith(".svg") for node in tree.iter() for value in (node.text, node.tail) if value and value.strip()) + sum(len(tree.xpath("//x:img[@alt]", namespaces=ns)) for _, tree in spine_roots),
        "image_alternatives": sum(len(tree.xpath("//x:img[@alt]", namespaces=ns)) for _, tree in spine_roots),
        "inline_carriers": inline,
    }
    return features, sections


def _norm(node: etree._Element) -> str:
    return " ".join(piece for piece in "".join(node.itertext()).split())


def _marker(member: object, path: object, suffix: str = "") -> str:
    return "#bunyan-source-" + _sha((str(member) + "|" + str(path) + suffix).encode())


def _expected_availability(claims: Mapping[str, object]) -> str:
    return "Retained OPF rights statement: " + str(claims["retained_opf_text"]) + " This reconstruction candidate is nonaccepted; generation and validation do not grant worldwide publication clearance."


def _expected_readme(claims: Mapping[str, object]) -> bytes:
    return (
        "# Source and rights\n\nStatus: nonaccepted.\n\nRetained OPF rights statement:\n\n"
        + str(claims["retained_opf_text"])
        + "\n\nThis reconstruction candidate is nonaccepted. Generation and validation do not establish worldwide publication clearance or replace human acceptance.\n\n"
        "Metadata review: config language en versus OPF en-GB; config contributors [] versus named OPF contributors; original 1678 versus digital 2020-05-07 dates; the retained extended title; and both Gutenberg and Internet Archive OPF source witnesses.\n"
    ).encode()


def _line_hashes(paragraph: etree._Element) -> list[str]:
    buckets = [paragraph.text or ""]
    for child in paragraph:
        if etree.QName(child).localname == "br":
            buckets.append(child.tail or "")
        else:
            buckets[-1] += "".join(child.itertext()) + (child.tail or "")
    return [_sha(" ".join(value.split()).encode()) for value in buckets]


def _independent_bindings(roots: Mapping[str, etree._ElementTree], spine: list[str], config: Mapping[str, object]) -> dict[str, object]:
    ns = {"x": XHTML, "epub": EPUB, "opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/", "xml": "http://www.w3.org/XML/1998/namespace"}
    ordered = [("src/epub/" + href, roots["src/epub/" + href]) for href in spine]
    references: dict[str, dict[str, object]] = {}
    inline: list[dict[str, object]] = []
    verse: list[dict[str, object]] = []
    cites: list[dict[str, object]] = []
    carriers = {"a", "abbr", "b", "strong", "i", "em", "cite", "span", "small", "sub", "sup", "q", "time", "br", "img"}
    for logical, tree in ordered:
        body = tree.xpath("//x:body", namespaces=ns)[0]
        placement = ({"frontmatter", "bodymatter", "backmatter"} & set(body.get(EPUB_TYPE, "").split())).pop().replace("matter", "")
        for element in body.iter():
            tag = etree.QName(element).localname
            path = tree.getpath(element)
            tokens = set(element.get(EPUB_TYPE, "").split())
            if tag == "a" and "noteref" in tokens:
                row = {"member": logical, "path": path, "id": element.get("id"), "target": element.get("href"), "label": _norm(element)}
                references[str(element.get("href")).rsplit("#", 1)[-1]] = row
            if tag in carriers:
                semantic_attributes = {name: value for name, value in (("id", element.get("id")), ("href", element.get("href")), ("src", element.get("src")), ("alt", element.get("alt")), ("datetime", element.get("datetime")), ("class", element.get("class")), ("xml:lang", element.get("{http://www.w3.org/XML/1998/namespace}lang")), ("epub:type", element.get(EPUB_TYPE))) if value is not None}
                inline.append({"member": logical, "path": path, "carrier": tag, "class": element.get("class"), "language": element.get("{http://www.w3.org/XML/1998/namespace}lang"), "epub_type": element.get(EPUB_TYPE), "semantic_attributes": semantic_attributes, "value_sha256": _sha(_norm(element).encode())})
            if tag == "cite":
                cites.append({"member": logical, "path": path, "value": _norm(element)})
            kinds = tokens & {"z3998:poem", "z3998:verse", "z3998:song"}
            if kinds:
                stanza_rows = []
                for paragraph in element.xpath("./x:p", namespaces=ns):
                    hashes = _line_hashes(paragraph)
                    stanza_rows.append({"path": tree.getpath(paragraph), "line_count": len(hashes), "line_sha256": hashes})
                verse.append({"member": logical, "path": path, "genre": next(iter(kinds)).split(":")[-1], "placement": placement, "stanzas": stanza_rows})
    end_tree = roots["src/epub/text/endnotes.xhtml"]
    notes = []
    for body in end_tree.xpath("//x:li[@epub:type='endnote']", namespaces=ns):
        body_id = body.get("id")
        back = body.xpath(".//x:a[contains(concat(' ',normalize-space(@epub:type),' '),' backlink ')]", namespaces=ns)
        if body_id not in references or len(back) != 1:
            raise ValueError("independent source note graph is not bijective")
        link = back[0]
        notes.append({"body_id": body_id, "body_path": end_tree.getpath(body), "body_text_sha256": _sha(_norm(body).encode()), "reference": references[str(body_id)], "backlink_path": end_tree.getpath(link), "backlink_target": link.get("href"), "backlink_label": _norm(link)})
    toc_tree = roots["src/epub/toc.xhtml"]
    toc = []
    for index, link in enumerate(toc_tree.xpath("//*[local-name()='nav']//*[local-name()='a']"), 1):
        nav = link.xpath("ancestor::*[local-name()='nav'][1]")[0]
        toc.append({"order": index, "nav_type": nav.get(EPUB_TYPE), "depth": len(link.xpath("ancestor::*[local-name()='li']")), "path": toc_tree.getpath(link), "target": link.get("href"), "label": _norm(link), "link_type": link.get(EPUB_TYPE)})
    image_strings = []
    for logical in sorted(name for name in roots if name.endswith(".svg")):
        tree = roots[logical]
        for node in tree.iter():
            base = tree.getpath(node)
            if node.text and node.text.strip(): image_strings.append({"member": logical, "path": base + "/text()", "kind": "svg-text", "value": node.text})
            if node.tail and node.tail.strip(): image_strings.append({"member": logical, "path": base + "/tail()", "kind": "svg-tail", "value": node.tail})
    for logical, tree in ordered:
        for image in tree.xpath("//x:img[@alt]", namespaces=ns):
            image_strings.append({"member": logical, "path": tree.getpath(image) + "/@alt", "kind": "xhtml-alt", "value": image.get("alt")})
    opf = roots["src/epub/content.opf"]
    metadata = {"config": {key: config.get(key) for key in ("title", "author", "contributors", "original_publication_year", "language", "original_language", "source_url", "source_edition")}, "opf": {
        "titles": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:title", namespaces=ns)],
        "language": [_norm(node) for node in opf.xpath("//opf:metadata/dc:language", namespaces=ns)],
        "dates": [{"property": node.get("property"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:date|//opf:metadata/opf:meta[@property='dcterms:modified']", namespaces=ns)],
        "sources": [_norm(node) for node in opf.xpath("//opf:metadata/dc:source", namespaces=ns)],
        "creators": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:creator", namespaces=ns)],
        "contributors": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:contributor", namespaces=ns)],
        "rights": [_norm(node) for node in opf.xpath("//opf:metadata/dc:rights", namespaces=ns)],
        "long_description": [_norm(node) for node in opf.xpath("//opf:metadata/opf:meta[@property='se:long-description']", namespaces=ns)],
        "production_notes": [_norm(node) for node in opf.xpath("//opf:metadata/opf:meta[@property='se:production-notes']", namespaces=ns)],
    }}
    rights_nodes = opf.xpath("//opf:metadata/dc:rights", namespaces=ns)
    if len(rights_nodes) != 1:
        raise ValueError("retained OPF rights statement cardinality drifted")
    rights_text = _norm(rights_nodes[0])
    rights_claims = {"candidate_status": "nonaccepted", "source_member": "src/epub/content.opf", "source_path": opf.getpath(rights_nodes[0]), "retained_opf_text": rights_text, "underlying_scope": "believed-US-public-domain-worldwide-uncertain", "contributor_scope": "CC0-1.0-dedication", "worldwide_clearance": False}
    return {"notes": notes, "verse": verse, "inline": inline, "toc": toc, "image_strings": image_strings, "cite_occurrences": cites, "distinct_cite_strings": sorted({row["value"] for row in cites}), "metadata_claims": metadata, "rights_claims": rights_claims}


def _local_imports(path: Path, repo: Path, seen: set[Path]) -> None:
    path = path.resolve(strict=True)
    if path in seen:
        return
    seen.add(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            parts = name.split(".")
            candidate = repo.joinpath(*parts).with_suffix(".py")
            package = repo.joinpath(*parts, "__init__.py")
            target = candidate if candidate.is_file() else package if package.is_file() else None
            if target:
                for depth in range(1, len(parts)):
                    init = repo.joinpath(*parts[:depth], "__init__.py")
                    if init.is_file():
                        _local_imports(init, repo, seen)
                _local_imports(target, repo, seen)


def _closure(repo: Path, start: Path | None = None) -> tuple[str, list[dict[str, object]]]:
    seen: set[Path] = set()
    _local_imports(start or Path(__file__), repo, seen)
    records = [{"path": path.relative_to(repo).as_posix(), "bytes": len(data := path.read_bytes()), "sha256": _sha(data)} for path in sorted(seen)]
    return _sha(_canonical({"contract": "ocd-python-import-closure-v1", "members": records})), records


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    runtime_paths = _runtime_paths(source_manifest.repository_root)
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "profile")
    policy = _strict(policy_bytes, "policy")
    members = _members(source_manifest)
    observed_set = [{"path": logical, "bytes": len(content), "sha256": _sha(content)} for logical, _, content in members]
    if observed_set != profile["source_scope"]["members"] or sum(item["bytes"] for item in observed_set) != 6028743:
        raise ValueError("retained source member set drifted")
    git_evidence = _git_evidence(
        resolve_repo_path(
            source_manifest.repository_root,
            "raw/standard_ebooks/john-bunyan_the-pilgrims-progress",
        )
    )
    expected_git = {"commit": profile["source_scope"]["commit"], "tree": profile["source_scope"]["tree"], "clean": True, "tracked_members": [row["path"] for row in observed_set]}
    if git_evidence != expected_git:
        raise ValueError("actual retained Git checkout authority drifted")
    roots = {}
    observations = []
    non_xml = []
    for logical, path, content in members:
        try:
            root = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))
        except etree.XMLSyntaxError:
            non_xml.append({"member": logical, "bytes": len(content), "sha256": _sha(content), "disposition": profile["non_xml_dispositions"][logical]})
            continue
        roots[logical] = root
        observations.extend(_observations(logical, root))
    opf = roots["src/epub/content.opf"]
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    hrefs = {node.get("id"): node.get("href") for node in opf.xpath("//opf:manifest/opf:item", namespaces=ns)}
    spine = [hrefs[node.get("idref")] for node in opf.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    if spine != profile["spine"]:
        raise ValueError("OPF spine drifted")
    features, sections = _source_features(roots, spine)
    if features != profile["feature_inventory"] or sections != profile["sections"]:
        raise ValueError("source-derived semantic inventory drifted")
    config_claims = _strict(source_manifest.authority_path("local-source-config").read_bytes(), "local source config")
    bindings = _independent_bindings(roots, spine, config_claims)
    if len(bindings["cite_occurrences"]) != 771 or len(bindings["distinct_cite_strings"]) != 156:
        raise ValueError("exact source cite occurrence/distinct inventory drifted")
    toc_rows = bindings["toc"]
    if [row["nav_type"] for row in toc_rows] != ["toc"] * 11 + ["landmarks"] * 2 or [row["link_type"] for row in toc_rows[-2:]] != ["bodymatter", "backmatter endnotes"] or len(bindings["image_strings"]) != 18:
        raise ValueError("retained TOC/landmark or image-string inventory drifted")

    accountability = _strict(candidate.member_bytes("source-accountability.json"), "accountability")
    schema_bytes = source_manifest.authority_path("source-accountability-schema").read_bytes()
    schema = _strict(schema_bytes, "accountability schema")
    errors = list(Draft202012Validator(schema).iter_errors(accountability))
    if errors:
        raise ValueError(f"source accountability schema failed: {errors[0].message}")
    if accountability["source_members"] != observed_set or accountability["observations"] != observations or accountability["non_xml_dispositions"] != non_xml or accountability["sections"] != sections or accountability["feature_inventory"] != features or accountability["semantic_bindings"] != bindings:
        raise ValueError("candidate source accountability differs from independent retained-source census")
    dispositions = [item["disposition"] for item in observations]
    observed_scope = {"total":len(observations), "represented":dispositions.count("represented"), "evidence_only":dispositions.count("evidence-only"), "ordered_dispositions_sha256":_sha(_canonical(dispositions))}
    if observed_scope != profile["observation_accounting"] or accountability["represented_count"] != observed_scope["represented"] or accountability["evidence_only_count"] != observed_scope["evidence_only"] or accountability["ordered_dispositions_sha256"] != observed_scope["ordered_dispositions_sha256"]:
        raise ValueError("candidate body/evidence disposition scope collapsed or drifted")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    tei = etree.fromstring(tei_bytes)
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(tei):
        raise ValueError(f"TEI P5 XSD failure: {xsd.error_log.last_error}")
    tns = {"t": TEI}
    correlated_nodes = tei.xpath("//*[@corresp]")
    by_corresp = {node.get("corresp"): node for node in correlated_nodes}
    if len(by_corresp) != len(correlated_nodes):
        raise ValueError("duplicate TEI source attachment marker")
    divs = tei.xpath("/t:TEI/t:text/t:body/t:div", namespaces=tns)
    observed_sections = [{"member": node.get("source"), "matter": (node.get("ana") or "").removeprefix("#").removesuffix("matter"), "id": node.get("{http://www.w3.org/XML/1998/namespace}id")} for node in divs]
    if observed_sections != [{key: row[key] for key in ("member", "matter", "id")} for row in sections]:
        raise ValueError("TEI spine order or matter classification drifted")
    source_sections = []
    for href in spine:
        section = roots["src/epub/" + href].find(f".//{{{XHTML}}}body/{{{XHTML}}}section")
        assert section is not None
        source_sections.append(section)
    for source_section, tei_div in zip(source_sections, divs, strict=True):
        tei_copy = etree.fromstring(etree.tostring(tei_div))
        for description in tei_copy.xpath(".//t:figDesc", namespaces=tns):
            description.getparent().remove(description)
        source_text = " ".join("".join(source_section.itertext()).split())
        candidate_text = " ".join("".join(tei_copy.itertext()).split())
        if source_text != candidate_text:
            raise ValueError("TEI section text omission, invention, reorder, or misattachment detected")
        source_lists = [" ".join("".join(node.itertext()).split()) for node in source_section.xpath(".//x:ol|.//x:ul", namespaces={"x": XHTML})]
        tei_lists = [" ".join("".join(node.itertext()).split()) for node in tei_div.xpath(".//t:list", namespaces=tns)]
        if source_lists != tei_lists:
            raise ValueError("TEI list/list-item order or content drifted")
        source_groups = [" ".join("".join(text for paragraph in node.xpath("./x:p", namespaces={"x": XHTML}) for text in paragraph.itertext()).split()) for node in source_section.xpath(".//*[@epub:type]", namespaces={"epub": EPUB}) if _types(node) & {"z3998:poem", "z3998:verse", "z3998:song"}]
        tei_groups = [" ".join("".join(node.itertext()).split()) for node in tei_div.xpath(".//t:lg[@type='poem']|.//t:lg[@type='verse']|.//t:lg[@type='song']", namespaces=tns)]
        if source_groups != tei_groups:
            raise ValueError("TEI poetry genre, placement, or text drifted")
    refs = tei.xpath("//t:ref[@type='note']", namespaces=tns)
    backs = tei.xpath("//t:ref[@type='backlink']", namespaces=tns)
    if len(refs) != 1010 or len(backs) != 1010 or [node.get("target") for node in refs] != [f"#note-{i}" for i in range(1, 1011)] or [node.get("target") for node in backs] != [f"#noteref-{i}" for i in range(1, 1011)]:
        raise ValueError("TEI note graph is not the exact source bijection")
    for row in bindings["notes"]:
        reference = row["reference"]
        found_ref = [by_corresp.get(_marker(reference["member"], reference["path"]))]
        found_body = tei.xpath("//t:item[@xml:id=$value]", namespaces={**tns, "xml":"http://www.w3.org/XML/1998/namespace"}, value=row["body_id"])
        found_back = [by_corresp.get(_marker("src/epub/text/endnotes.xhtml", row["backlink_path"]))]
        body_marker = _marker("src/epub/text/endnotes.xhtml", row["body_path"])
        if found_ref[0] is None or len(found_body) != 1 or found_back[0] is None or found_body[0].get("corresp") != body_marker or found_back[0] not in found_body[0].iterdescendants() or found_ref[0].get("target") != "#" + str(row["body_id"]) or _norm(found_ref[0]) != reference["label"] or found_back[0].get("target") != "#" + str(reference["id"]) or _norm(found_back[0]) != row["backlink_label"] or _sha(_norm(found_body[0]).encode()) != row["body_text_sha256"]:
            raise ValueError("TEI note body/reference/backlink attachment drifted")
    if len(tei.xpath("//t:list", namespaces=tns)) != 2 or len(tei.xpath("//t:item", namespaces=tns)) != 1026:
        raise ValueError("TEI list structure drifted")
    if len(tei.xpath("//t:lg[@type='stanza']", namespaces=tns)) != 171 or len(tei.xpath("//t:l", namespaces=tns)) != 1045:
        raise ValueError("TEI verse stanza/line structure drifted")
    if len(tei.xpath("//t:lg[@type='poem']|//t:lg[@type='verse']|//t:lg[@type='song']", namespaces=tns)) != 95:
        raise ValueError("TEI poetry genre inventory drifted")
    for group in bindings["verse"]:
        marker = _marker(group["member"], group["path"])
        match = by_corresp.get(marker)
        if match is None or etree.QName(match).localname != "lg" or match.get("type") != group["genre"]:
            raise ValueError("TEI verse source location/genre attachment drifted")
        section_ancestor = match.xpath("ancestor::t:div[@source][1]", namespaces=tns)
        if len(section_ancestor) != 1 or section_ancestor[0].get("source") != group["member"] or section_ancestor[0].get("ana") != "#" + str(group["placement"]) + "matter":
            raise ValueError("TEI verse front/body/back source placement drifted")
        stanzas = match.xpath("./t:lg[@type='stanza']", namespaces=tns)
        if len(stanzas) != len(group["stanzas"]):
            raise ValueError("TEI stanza attachment drifted")
        for source_stanza, stanza in zip(group["stanzas"], stanzas, strict=True):
            if stanza.get("corresp") != _marker(group["member"], source_stanza["path"]):
                raise ValueError("TEI stanza source location drifted")
            lines = stanza.xpath("./t:l", namespaces=tns)
            hashes = [_sha(_norm(line).encode()) for line in lines]
            expected_markers = [_marker(group["member"], source_stanza["path"], f"|line:{i}") for i in range(1, len(lines) + 1)]
            if hashes != source_stanza["line_sha256"] or [line.get("corresp") for line in lines] != expected_markers:
                raise ValueError("TEI verse line/stanza placement drifted")
    expected_inline = {"a":"ref", "abbr":"abbr", "b":"hi", "strong":"hi", "i":"hi", "em":"emph", "cite":"title", "span":"seg", "small":"hi", "sub":"hi", "sup":"hi", "q":"q", "time":"date", "br":"lb", "img":"figure"}
    expected_inline_markers = [_marker(item["member"], item["path"]) for item in bindings["inline"]]
    expected_inline_marker_set = set(expected_inline_markers)
    if [node.get("corresp") for node in correlated_nodes if node.get("corresp") in expected_inline_marker_set] != expected_inline_markers:
        raise ValueError("TEI inline source-occurrence order/attachment drifted")
    for item in bindings["inline"]:
        marker = _marker(item["member"], item["path"])
        node = by_corresp.get(marker)
        if node is None:
            raise ValueError("TEI inline carrier occurrence attachment drifted")
        actual_name = etree.QName(node).localname
        if item["carrier"] == "cite" and actual_name == "bibl":
            pass
        elif actual_name != expected_inline[item["carrier"]]:
            raise ValueError("TEI inline carrier type swap detected")
        if item["carrier"] in {"i", "b", "strong", "span", "abbr"}:
            expected_rend = "italic" if item["carrier"] == "i" else "bold" if item["carrier"] in {"b", "strong"} else item["class"]
            if node.get("rend") != expected_rend:
                raise ValueError("TEI exact inline rendition/indentation attachment drifted")
        if node.get("{http://www.w3.org/XML/1998/namespace}lang") != item["language"]:
            raise ValueError("TEI language carrier attachment drifted")
        if item["carrier"] != "img" and _sha(_norm(node).encode()) != item["value_sha256"]:
            raise ValueError("TEI inline occurrence text attachment drifted")
        source_attrs = item["semantic_attributes"]
        expected_ana = " ".join("epub:" + token for token in str(source_attrs.get("epub:type", "")).split()) or None
        if node.get("ana") != expected_ana:
            raise ValueError("TEI inline EPUB semantic mapping drifted")
        if source_attrs.get("id") is not None and node.get("{http://www.w3.org/XML/1998/namespace}id") != source_attrs["id"]:
            raise ValueError("TEI inline source identity mapping drifted")
        if item["carrier"] == "a":
            href = str(source_attrs["href"])
            tokens = str(source_attrs.get("epub:type", "")).split()
            expected_target = "#" + href.rsplit("#", 1)[-1] if "noteref" in tokens or "backlink" in tokens else href
            expected_type = "note" if "noteref" in tokens else "backlink" if "backlink" in tokens else None
            if node.get("target") != expected_target or node.get("type") != expected_type:
                raise ValueError("TEI exact anchor target/type mapping drifted")
        elif item["carrier"] == "img":
            graphics = node.xpath("./t:graphic", namespaces=tns)
            descriptions = node.xpath("./t:figDesc", namespaces=tns)
            if len(graphics) != 1 or graphics[0].get("url") != source_attrs["src"] or len(descriptions) != 1 or _norm(descriptions[0]) != str(source_attrs.get("alt", "")):
                raise ValueError("TEI exact image URL/alternative mapping drifted")
        elif item["carrier"] == "time" and node.get("when") != source_attrs.get("datetime"):
            raise ValueError("TEI exact time datetime mapping drifted")
    carrier_counts = {
        "a": len(tei.xpath("//t:ref", namespaces=tns)),
        "abbr": len(tei.xpath("//t:abbr", namespaces=tns)),
        "b": len(tei.xpath("//t:hi[@rend='bold']", namespaces=tns)),
        "i": len(tei.xpath("//t:hi[@rend='italic']", namespaces=tns)),
        "em": len(tei.xpath("//t:emph", namespaces=tns)),
        "span": len(tei.xpath("//t:seg", namespaces=tns)),
        "time": len(tei.xpath("//t:date", namespaces=tns)),
        "img": len(tei.xpath("//t:figure", namespaces=tns)),
    }
    for name, count in carrier_counts.items():
        if count != features["inline_carriers"][name]:
            raise ValueError(f"TEI inline carrier {name} count drifted")
    if len(tei.xpath("//*[@xml:lang='la']", namespaces={"xml":"http://www.w3.org/XML/1998/namespace"})) != 3:
        raise ValueError("TEI language carrier inventory drifted")
    if len(tei.xpath("//t:seg[starts-with(@rend,'i')]", namespaces=tns)) != 21:
        raise ValueError("TEI verse indentation carrier inventory drifted")
    alternatives = [row["value"] for row in bindings["image_strings"] if row["kind"] == "xhtml-alt"]
    if ["".join(node.itertext()) for node in tei.xpath("//t:figDesc", namespaces=tns)] != alternatives or len(bindings["image_strings"]) != 18:
        raise ValueError("TEI image alternatives drifted")
    if ["".join(node.itertext()) for node in tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=tns)] != [profile["metadata"]["title"]] or ["".join(node.itertext()) for node in tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:author", namespaces=tns)] != [profile["metadata"]["author"]]:
        raise ValueError("TEI source-derived title or author drifted")
    availability = tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:availability", namespaces=tns)
    rights_claims = bindings["rights_claims"]
    if len(availability) != 1 or availability[0].get("status") != "unknown" or _norm(availability[0]) != _expected_availability(rights_claims):
        raise ValueError("TEI rights categories are missing or conflated")
    readme = candidate.member_bytes("README.source.md")
    if readme != _expected_readme(rights_claims):
        raise ValueError("candidate source/rights handoff is incomplete")
    unresolved = [_strict(line + b"\n", "unresolved") for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    if [item["id"] for item in unresolved] != policy["required_unresolved_ids"]:
        raise ValueError("unresolved human/rights/metadata boundaries drifted")

    closure_sha, closure_members = _closure(source_manifest.repository_root)
    producer_closure_sha, _ = _closure(source_manifest.repository_root, source_manifest.repository_root / "build/tei/pilgrims_progress_reconstruction.py")
    if producer_closure_sha != profile["producer_import_closure_sha256"]:
        raise ValueError("producer recursive import closure drifted")
    forbidden = tuple(policy["forbidden_import_prefixes"])
    imported = []
    for row in closure_members:
        imported.append(str(row["path"]).removesuffix(".py").replace("/", "."))
    if any(name.startswith(forbidden) for name in imported):
        raise ValueError("oracle import closure reaches forbidden producer or campaign machinery")
    validator = source_manifest.record["validator"]
    if closure_sha != validator["import_closure_sha256"]:
        raise ValueError("oracle recursive import closure drifted")
    provenance = _strict(candidate.member_bytes("provenance.json"), "provenance")
    expected_provenance = {
        "contract":"ocd-pilgrims-progress-provenance-v1", "status":"nonaccepted",
        "retained_commit":profile["source_scope"]["commit"], "retained_tree":profile["source_scope"]["tree"],
        "source_member_set_sha256":_sha(_canonical({"contract":"ocd-source-member-set-v1","members":observed_set})),
        "spine":spine, "metadata_conflicts":profile["metadata_conflicts"], "rights":profile["rights"],
        "producer_import_closure_sha256":producer_closure_sha,
        "metadata_claims":bindings["metadata_claims"],
    }
    if provenance != expected_provenance:
        raise ValueError("candidate provenance, revision, metadata conflicts, or rights drifted")
    implementation_sha = _sha(Path(__file__).read_bytes())
    source_records = sorted(({"name": a["name"], "path": a["path"], "bytes": a["bytes"], "sha256": a["sha256"]} for a in source_manifest.record["authorities"] if a["role"] == "primary-source"), key=lambda row: (str(row["path"]), str(row["name"])))
    source_sha = _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": source_records}))
    result = {
        "status":"pass", "oracle_id":ORACLE_ID, "oracle_version":ORACLE_VERSION,
        "implementation_sha256":implementation_sha, "import_closure_sha256":closure_sha,
        "runtime":f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256":source_manifest.sha256, "candidate_sha256":candidate.sha256,
        "profile_sha256":_sha(profile_bytes), "package_schema_sha256":str(source_manifest.record["package_schema"]["sha256"]),
        "source_sha256":source_sha, "xsd_sha256":_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256":_sha(policy_bytes),
        "findings":[],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
