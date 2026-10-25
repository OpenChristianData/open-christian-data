"""Stage one standalone Bounds TEI from the validated LIB-031 family candidate.

This pilot leaves the frozen family producer and canonical library sidecars alone.
It does not assert acceptance, visual review, print collation, or rights clearance.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.lib031_bounds_necessity_standalone_oracle import verify
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.lib.storage_topology import resolve_repo_path

WORK_ID = "bounds-necessity-of-prayer"
SOURCE = Path("raw/ccel/bounds/necessity.xml")
MANIFEST = Path("sources/structured-text/bounds-essentials-of-prayer/lib031.source-manifest.json")
ACQUISITION = Path("library/works/bounds-necessity-of-prayer/forms/bounds-necessity-of-prayer-english/editions/bounds-necessity-of-prayer-ccel-thml-electronic/acquisitions/bounds-necessity-of-prayer-ccel-retained-xml.json")
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(content: bytes) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _tag(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _child(parent: etree._Element, name: str, text: str | None = None, **attrs: str) -> etree._Element:
    result = etree.SubElement(parent, _tag(name), attrs)
    result.text = text
    return result


def stage(root: Path, family_package: Path, destination: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    if destination.exists():
        raise FileExistsError(f"refusing to replace candidate stage: {destination}")
    source = resolve_repo_path(root, SOURCE.as_posix()).read_bytes()
    manifest_bytes = (root / MANIFEST).read_bytes()
    acquisition = _json(_io_path(root / ACQUISITION).read_bytes())
    matches = [item for item in acquisition["retained_files"] if item.get("path") == SOURCE.as_posix()]
    if len(matches) != 1 or matches[0]["sha256"] != _sha(source) or matches[0]["bytes"] != len(source):
        raise ValueError("canonical acquisition does not bind exact retained XML")

    family_manifest_bytes = (family_package / "manifest.json").read_bytes()
    family_manifest = _json(family_manifest_bytes)
    family_validation_bytes = (family_package.parent / "validation.json").read_bytes()
    family_validation = _json(family_validation_bytes)
    if (
        family_manifest.get("status") != "nonaccepted"
        or family_validation.get("status") != "pass"
        or family_manifest["source_manifest"]["sha256"] != _sha(manifest_bytes)
        or family_validation.get("source_manifest_sha256") != _sha(manifest_bytes)
        or family_validation.get("candidate_sha256") != _sha(family_manifest_bytes)
    ):
        raise ValueError("parent family package or validation is stale")
    declared = {member["name"]: member for member in family_manifest["members"]}
    source_member = (family_package / "content.tei.xml").read_bytes()
    family_accounting_bytes = (family_package / "source-accountability.json").read_bytes()
    for name, content in (("content.tei.xml", source_member), ("source-accountability.json", family_accounting_bytes)):
        if name not in declared or declared[name]["sha256"] != _sha(content) or declared[name]["bytes"] != len(content):
            raise ValueError(f"parent family member changed: {name}")
    family_accounting = _json(family_accounting_bytes)
    rows = [copy.deepcopy(row) for row in family_accounting["crosswalk"] if row.get("work_id") == WORK_ID]
    source_tree = etree.fromstring(source, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    source_head = source_tree.find("ThML.head")
    if source_head is None:
        raise ValueError("source ThML head missing")
    source_body = source_tree.find("ThML.body")
    if source_tree.tag != "ThML" or source_body is None:
        raise ValueError("expected complete retained ThML document")
    if (source_body.text or "").strip() or (source_body.tail or "").strip():
        raise ValueError("nonwhitespace source body boundary text requires mapping")
    header_rows = [
        {"tag": node.tag if isinstance(node.tag, str) else "#comment", "attributes": dict(node.attrib), "text": node.text or "", "tail": node.tail or ""}
        for node in source_head.iter()
    ]
    family = etree.fromstring(source_member, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    ns = {"tei": TEI_NS}
    divisions = family.xpath("./tei:text/tei:body/tei:div", namespaces=ns)
    profile = _json((root / "sources/structured-text/bounds-essentials-of-prayer/lib031.reconstruction-profile.json").read_bytes())
    if [node.get(XML_ID) for node in divisions] != profile["work_order"]:
        raise ValueError("parent family work order changed")
    selected = [node for node in divisions if node.get(XML_ID) == WORK_ID]
    if len(selected) != 1 or not rows:
        raise ValueError("unique Bounds child or source crosswalk missing")

    tei = etree.Element(_tag("TEI"), nsmap={None: TEI_NS})
    header = _child(tei, "teiHeader")
    desc = _child(header, "fileDesc")
    title_stmt = _child(desc, "titleStmt")
    _child(title_stmt, "title", "The Necessity of Prayer")
    _child(title_stmt, "author", "Edward M. Bounds")
    publication = _child(desc, "publicationStmt")
    _child(publication, "publisher", "Open Christian Data")
    availability = _child(publication, "availability", status="restricted")
    _child(availability, "p", "Nonaccepted standalone technical candidate; rights and publication have not been decided.")
    source_desc = _child(desc, "sourceDesc")
    bibl = _child(source_desc, "bibl", type="retained-electronic-witness")
    _child(bibl, "title", "The Necessity of Prayer")
    _child(bibl, "author", "Edward M. Bounds")
    _child(bibl, "ref", SOURCE.as_posix(), target="https://www.ccel.org/ccel/bounds/necessity.xml")
    _child(bibl, "idno", _sha(source), type="sha256")
    text = _child(tei, "text")
    body = _child(text, "body")
    work_div = copy.deepcopy(selected[0])
    wrapper_head = work_div[0]
    if wrapper_head.tag != _tag("head") or wrapper_head.text != "The Necessity of Prayer" or len(wrapper_head):
        raise ValueError("parent work wrapper title changed")
    work_div.remove(wrapper_head)
    mapped = {node.get(XML_ID): node for node in work_div.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
    source_nodes = list(source_body.iter())[1:]
    if len(source_nodes) != len(rows):
        raise ValueError("source and parent crosswalk count differ")
    headed_divisions = 0
    for source_node, row in zip(source_nodes, rows, strict=True):
        if row["tei_parent_id"] == WORK_ID:
            row["tei_child_ordinal"] -= 1
        parent = source_node.getparent()
        if (source_node.tag in {"h1", "h2"} and parent is not None
                and parent.tag in {"div1", "div2"} and parent.index(source_node) == 0):
            target = mapped.get(row["tei_selector"][1:])
            if target is None or target.tag != _tag("p"):
                raise ValueError("parent heading carrier changed")
            target.tag = _tag("head")
            row["tei_tag"] = "head"
            headed_divisions += 1
    division_count = sum(node.tag in {"div1", "div2"} for node in source_nodes)
    if headed_divisions != division_count:
        raise ValueError("source division heading coverage incomplete")
    source_ids = {}
    for source_node, row in zip(source_nodes, rows, strict=True):
        source_id = source_node.get("id")
        if source_id:
            if source_id in source_ids:
                raise ValueError(f"duplicate source XML ID: {source_id}")
            source_ids[source_id] = row["tei_selector"][1:]
    localized_links = 0
    for source_node, row in zip(source_nodes, rows, strict=True):
        if source_node.tag != "a":
            continue
        href = source_node.get("href", "")
        before, separator, fragment = href.partition("#")
        if not separator or not before.startswith("?") or not fragment or fragment not in source_ids:
            raise ValueError(f"unresolved retained index link: {href}")
        target = mapped[row["tei_selector"][1:]]
        if target.tag != _tag("ref") or target.get("target") != href:
            raise ValueError("parent index link carrier changed")
        target.set("target", "#" + source_ids[fragment])
        row["tei_attributes"]["target"] = target.get("target")
        localized_links += 1
    body.append(work_div)
    tei_bytes = etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n"
    accounting = {
        "contract": "ocd-lib031-bounds-standalone-accounting-v1",
        "work_id": WORK_ID,
        "source_path": SOURCE.as_posix(),
        "source_sha256": _sha(source),
        "source_header": header_rows,
        "source_body_boundary": {"text": source_body.text or "", "tail": source_body.tail or "", "disposition": "excluded formatting whitespace"},
        "body_crosswalk": rows,
        "source_division_headings": headed_divisions,
        "source_index_links_localized": localized_links,
        "parent_accounting_sha256": _sha(family_accounting_bytes),
    }
    accounting_bytes = _canonical(accounting)
    result = verify(source, tei_bytes, accounting)
    readme = (
        "# The Necessity of Prayer: standalone technical candidate\n\n"
        "This nonaccepted TEI is one work from the verified LIB-031 ten-work candidate. "
        "The retained textual source is extracted `raw/ccel/bounds/necessity.xml`; "
        "the family candidate and source ledger are bound in `manifest.json`. "
        "The complete ThML body is mapped to the standalone TEI, with source division headings retained as TEI heads, six index links targeting local TEI IDs, and no duplicated wrapper title; the exact "
        "ThML header is inventoried in `source-accountability.json`. "
        "Visual review, source-header metadata adoption, human review, rights, and acceptance remain open.\n"
    ).encode("utf-8")
    members = {"README.source.md": readme, "content.tei.xml": tei_bytes, "source-accountability.json": accounting_bytes}
    package_manifest = {
        "contract": "ocd-lib031-standalone-pilot-v1",
        "status": "nonaccepted",
        "work_id": WORK_ID,
        "source": {"path": SOURCE.as_posix(), "sha256": _sha(source), "bytes": len(source)},
        "canonical_acquisition": {"path": ACQUISITION.as_posix(), "sha256": _sha(_io_path(root / ACQUISITION).read_bytes())},
        "builder": {"path": "build/tei/lib031_bounds_necessity_standalone.py", "sha256": _sha((root / "build/tei/lib031_bounds_necessity_standalone.py").read_bytes())},
        "oracle": {"path": "build/tei/lib031_bounds_necessity_standalone_oracle.py", "sha256": _sha((root / "build/tei/lib031_bounds_necessity_standalone_oracle.py").read_bytes())},
        "schema": {"path": "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "sha256": _sha((root / "ocd_kernel/tei/vendor/xsd/tei_all.xsd").read_bytes())},
        "family_source_manifest": {"path": MANIFEST.as_posix(), "sha256": _sha(manifest_bytes)},
        "parent_candidate": {"package_manifest": str(family_package / "manifest.json"), "sha256": _sha(family_manifest_bytes), "validation_sha256": _sha(family_validation_bytes)},
        "members": [{"name": name, "bytes": len(content), "sha256": _sha(content)} for name, content in sorted(members.items())],
    }
    validation = {"contract": "ocd-lib031-standalone-pilot-validation-v1", "status": "pass", "work_id": WORK_ID, "package_manifest_sha256": _sha(_canonical(package_manifest)), "checks": result}
    package = destination / "package"
    package.mkdir(parents=True, exist_ok=False)
    for name, content in members.items():
        (package / name).write_bytes(content)
    (package / "manifest.json").write_bytes(_canonical(package_manifest))
    (destination / "validation.json").write_bytes(_canonical(validation))
    return {"destination": str(destination), "source_sha256": _sha(source), "tei_sha256": _sha(tei_bytes), "package_manifest_sha256": _sha(_canonical(package_manifest)), **result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--family-package", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.root, args.family_package, args.destination), sort_keys=True))


if __name__ == "__main__":
    main()
