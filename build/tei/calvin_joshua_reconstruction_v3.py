"""Build the first title-specific Calvin candidate from the sealed aggregate source route."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei import calvin_commentaries_oracle as aggregate_oracle
from build.tei import calvin_commentaries_reconstruction as aggregate
from build.tei.calvin_series_selection import validate_title_selection_profile
from ocd_kernel.reconstruction import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
CONVERTER_ID = "ocd-calvin-joshua-title-selection"
CONVERTER_VERSION = "3"
PROFILE = "calvin-title-selection-profile"
PARENT = "collection-source-manifest"
POLICY = "title-validation-policy"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, label: str) -> dict:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source_path(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{etree.QName(node).localname}[1]"
    elements = [child for child in parent if isinstance(child.tag, str)]
    return f"{_source_path(parent)}/{etree.QName(node).localname}[{elements.index(node) + 1}]"


def _catalogue_title_binding(source_manifest: SourceManifest, target_element: etree._Element) -> tuple[str, dict[str, object]]:
    catalogue_path = source_manifest.authority_path("commentaries.xml")
    catalogue_bytes = catalogue_path.read_bytes()
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    catalogue = etree.fromstring(catalogue_bytes, parser)
    main_titles = [
        node for node in catalogue.iter()
        if isinstance(node.tag, str) and node.tag == "DC.Title" and node.get("sub") == "Main"
    ]
    descriptions = catalogue.xpath("/ThML/ThML.head/generalInfo/description")
    if len(main_titles) != 1 or len(descriptions) != 1:
        raise ValueError("retained catalogue requires one DC.Title Main and one separate description")
    title_node = main_titles[0]
    title = "".join(title_node.itertext())
    title_bytes = title.encode("utf-8")
    title_offsets = [index for index in range(len(catalogue_bytes)) if catalogue_bytes.startswith(title_bytes, index)]
    if not title or title != title.strip() or "\ufffd" in title or len(title_offsets) != 1:
        raise ValueError("retained catalogue main title is not one exact strict UTF-8 source value")
    description_text = "".join(descriptions[0].itertext())
    description_offset = catalogue_bytes.find(description_text.encode("utf-8"))
    if not description_text or description_text == title or description_offset < 0:
        raise ValueError("retained catalogue description is missing or conflated with its main title")
    authority = next(
        item for item in source_manifest.record["authorities"]
        if item.get("name") == "commentaries.xml"
    )
    return title, {
        "member": "commentaries.xml",
        "source_path": authority["path"],
        "source_sha256": authority["sha256"],
        "source_selector": _source_path(title_node),
        "source_title": title,
        "source_title_sha256": _sha(title_bytes),
        "source_title_byte_offset": title_offsets[0],
        "target_selector": _source_path(target_element),
        "target_text_sha256": _sha(title_bytes),
        "selector_convention": "all-element-child-position; not same-tag XPath indexing",
        "separate_description_selector": _source_path(descriptions[0]),
        "separate_description_text_sha256": _sha(description_text.encode("utf-8")),
    }


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile_bytes = source_manifest.authority_path(PROFILE).read_bytes()
    profile = _json(profile_bytes, "Calvin title-selection profile")
    validated = validate_title_selection_profile(profile)
    title = profile["selected_unit"]["title"]
    selected = profile["selected_unit"]["members"]
    if title != "Commentary on Joshua" or selected != ["calcom07.xml"]:
        raise ValueError("first-unit profile must remain Joshua → calcom07.xml")

    derivation = profile.get("derivation_authority")
    if not isinstance(derivation, dict):
        raise ValueError("aggregate derivation authority is missing")
    if source_manifest.authority_path(PARENT).read_bytes() != (
        source_manifest.repository_root / derivation["source_manifest_path"]
    ).read_bytes():
        raise ValueError("nested aggregate source manifest differs from title profile")
    parent_manifest = SourceManifest.load(
        source_manifest.authority_path(PARENT),
        repository_root=source_manifest.repository_root,
    )
    if parent_manifest.sha256 != derivation.get("source_manifest_sha256"):
        raise ValueError("aggregate source-manifest digest differs from title profile")
    parent_converter = parent_manifest.record["converter"]
    if parent_manifest.record.get("producer_import_closure_sha256") != aggregate_oracle._closure_digest(
        source_manifest.repository_root,
        source_manifest.repository_root / parent_converter["implementation_path"],
    ):
        raise ValueError("aggregate producer import closure differs from reviewed binding")

    # Reuse the already-reviewed complete converter; the exact aggregate TEI
    # digest is pinned in the title profile before selecting its wrappers.
    aggregate_payloads = aggregate._convert(parent_manifest)
    aggregate_tei = aggregate_payloads["content.tei.xml"]
    if _sha(aggregate_tei) != derivation.get("aggregate_tei_sha256"):
        raise ValueError("reconstructed collection TEI differs from reviewed aggregate")
    root = etree.fromstring(aggregate_tei, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    front = root.find(f"{{{TEI}}}text/{{{TEI}}}front")
    body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if front is None or body is None:
        raise ValueError("aggregate TEI lacks front/body")
    catalogues = front.findall(f"{{{TEI}}}div[@type='source-member']")
    wrappers = body.findall(f"{{{TEI}}}div[@type='source-member']")
    if len(catalogues) != 1 or catalogues[0].get("n") != "commentaries.xml":
        raise ValueError("aggregate catalogue wrapper changed")
    by_name = {node.get("n"): node for node in wrappers}
    if len(by_name) != 45 or set(by_name) != {row["member"] for row in validated["component_rows"]}:
        raise ValueError("aggregate component wrapper set differs from title profile")
    if [node.get("n") for node in wrappers if node.get("n") in selected] != selected:
        raise ValueError("selected title members are not in source order")
    expected_wrapper_hashes = profile.get("retained_wrapper_sha256")
    if not isinstance(expected_wrapper_hashes, dict):
        raise ValueError("reviewed aggregate wrapper hashes are missing")
    actual_wrapper_hashes = {
        "catalogue": _sha(etree.tostring(catalogues[0], encoding="UTF-8")),
        "calcom07.xml": _sha(etree.tostring(by_name["calcom07.xml"], encoding="UTF-8")),
    }
    if actual_wrapper_hashes != expected_wrapper_hashes:
        raise ValueError("selected source wrappers differ from the previously reviewed aggregate")
    for node in list(body):
        body.remove(node)
    chosen = [by_name[name] for name in selected]
    for node in chosen:
        body.append(node)

    root.set(f"{{{XML}}}id", "calvin-joshua-candidate")
    titles = root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces={"tei": TEI})
    if len(titles) != 1:
        raise ValueError("aggregate TEI title header changed")
    titles[0].text = title
    notes = root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:notesStmt", namespaces={"tei": TEI})
    if len(notes) != 1:
        raise ValueError("aggregate TEI notes structure changed")
    for note in list(notes[0]):
        if note.get("type") in {"source-member-set-sha256", "source-boundary", "series-selection", "shared-catalogue-ownership"}:
            notes[0].remove(note)
    for kind, value in (
        ("selected-primary-source", "calcom07.xml"),
        ("shared-catalogue-ownership", "commentaries.xml is shared collection-level front matter; sibling CCEL hrefs remain external."),
        ("historical-container-context", "calvin-commentaries is retained as historical collection identity; this package is scoped to the source-attested Joshua title."),
    ):
        etree.SubElement(notes[0], f"{{{TEI}}}note", type=kind).text = value

    source_desc = root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces={"tei": TEI})
    if len(source_desc) != 1:
        raise ValueError("aggregate TEI sourceDesc structure changed")
    keep = {"commentaries.xml", *selected}
    for bibl in list(source_desc[0]):
        name = bibl.findtext(f"{{{TEI}}}idno[@type='filename']")
        if name not in keep:
            source_desc[0].remove(bibl)
    observed_source_names = [node.findtext(f"{{{TEI}}}idno[@type='filename']") for node in source_desc[0]]
    if observed_source_names != ["commentaries.xml", *selected]:
        raise ValueError("title sourceDesc does not identify exactly shared catalogue and selected primary source")
    header = root.find(f"{{{TEI}}}teiHeader")
    if header is None or _sha(etree.tostring(header, encoding="UTF-8")) != profile.get("retained_tei_header_sha256"):
        raise ValueError("Joshua TEI header differs from the reviewed title-scope profile")

    catalogue_bibliographies = [
        node for node in source_desc[0]
        if node.findtext(f"{{{TEI}}}idno[@type='filename']") == "commentaries.xml"
    ]
    if len(catalogue_bibliographies) != 1:
        raise ValueError("Joshua sourceDesc must contain one catalogue bibliography record")
    catalogue_titles = catalogue_bibliographies[0].findall(f"{{{TEI}}}title")
    if len(catalogue_titles) != 1:
        raise ValueError("Joshua catalogue bibliography must contain one title")
    catalogue_title, catalogue_title_binding = _catalogue_title_binding(source_manifest, catalogue_titles[0])
    catalogue_titles[0].text = catalogue_title
    if "\ufffd" in (catalogue_titles[0].text or ""):
        raise ValueError("source-derived catalogue title still contains a replacement character")

    schema_path = parent_manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    tei_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    parsed = etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if not schema.validate(parsed):
        raise ValueError(f"Joshua title TEI fails P5: {schema.error_log.last_error}")

    member_rows = {row["member"]: row for row in validated["component_rows"]}
    included = []
    for name, role, wrapper in (("commentaries.xml", "shared-catalogue-front-matter", catalogues[0]), ("calcom07.xml", "primary-commentary-source", chosen[0])):
        authority = next(item for item in parent_manifest.record["authorities"] if item["name"] == name)
        included.append({
            "member": name,
            "path": authority["path"],
            "role": role,
            "bytes": authority["bytes"],
            "sha256": authority["sha256"],
            "wrapper_sha256": _sha(etree.tostring(wrapper, encoding="UTF-8")),
            "mapped_selector_count": sum(1 for node in wrapper.iter() if isinstance(node.tag, str) and node.get("corresp")),
        })
    siblings = [
        {"member": name, "group": group["title"], "disposition": "sibling-title-excluded-from-this-TEI"}
        for group in validated["groups"] for name in group["members"] if name not in selected
    ]
    accounting = {
        "contract": "ocd-calvin-series-accountability-v2",
        "profile_sha256": _sha(profile_bytes),
        "crosswalk_sha256": profile["crosswalk_sha256"],
        "historical_container_id": "calvin-commentaries",
        "title": title,
        "selected_members": selected,
        "included": included,
        "sibling_exclusions": siblings,
        "group_count": len(validated["groups"]),
        "component_count": len(validated["component_rows"]),
        "catalogue_title_binding": catalogue_title_binding,
    }
    policy = _json(source_manifest.authority_path(POLICY).read_bytes(), "Joshua policy")
    return {
        "README.source.md": source_manifest.authority_path("title-source-readme").read_bytes(),
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accounting),
        "provenance.json": _canonical(policy["provenance"]),
        "unresolved.jsonl": b"".join(_canonical(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
