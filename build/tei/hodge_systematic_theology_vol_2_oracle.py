"""Independent source-to-TEI oracle for Hodge, Systematic Theology, Volume II."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-37c204-hodge-systematic-theology-vol-2-oracle"
ORACLE_VERSION = "2"
PROFILE_ID = "hodge-systematic-theology-vol-2-ccel-content-roots-v1"
SOURCE_KEY = "hodge-vol-2"
SOURCE_PATH = "raw/ccel/hodge/theology2.xml"
SOURCE_BYTES = 2_601_781
SOURCE_SHA256 = "52a43581dcb7b75a6903c89c8e2496b8d754bdbcd6fa751ecaa4f065e933d942"
WORK_ID = "hodge-systematic-theology-vol-2"
SOURCE_ID = "ocd-37c204-hodge-systematic-theology-vol-2-ccel-theology2"
ASSIGNED_ROOTS = ((SOURCE_KEY, "iii", WORK_ID), (SOURCE_KEY, "iv", WORK_ID))
TOP_LEVEL_IDS = ("i", "ii", "iii", "iv", "v")
ROOT_LABELS = (
    "Title",
    "Prefatory",
    "Part II. Anthropology",
    "Part III. Soteriology.",
    "Indexes",
)
SPECIAL_TAG_PROJECTIONS = {"hr": "milestone", "verse": "lg", "l": "l"}
SPECIAL_TAG_COUNTS = {"hr": 2, "verse": 7, "l": 28}
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _census(nodes: list[etree._Element]) -> dict[str, Any]:
    """Independently summarize source carriers for profile and accountability checks."""
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in elements]
    return {
        "attribute_counts": dict(
            sorted(Counter(key for node in elements for key in node.attrib).items())
        ),
        "attributes": sum(len(node.attrib) for node in elements),
        "characters": sum(map(len, strings)),
        "direct_text_bytes": sum(
            len((node.text or "").encode("utf-8")) for node in elements
        ),
        "elements": len(elements),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in value) for value in strings
        ),
        "notes": sum(node.tag == "note" for node in elements),
        "page_breaks": sum(node.tag == "pb" for node in elements),
        "scripture_refs": sum(node.tag == "scripRef" for node in elements),
        "tag_counts": dict(sorted(Counter(node.tag for node in elements).items())),
        "tail_text_bytes": sum(
            len((node.tail or "").encode("utf-8")) for node in elements
        ),
        "tail_nodes": sum(bool(node.tail) for node in elements),
        "text_nodes": sum(bool(node.text) for node in elements),
    }


def _subtract(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in left.items():
        if key in {"tag_counts", "attribute_counts"}:
            result[key] = {
                name: count - right.get(key, {}).get(name, 0)
                for name, count in value.items()
                if count - right.get(key, {}).get(name, 0)
            }
        else:
            result[key] = value - right.get(key, 0)
    return result


def _json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict) or _canonical(value) != data:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _source_tree(data: bytes) -> etree._ElementTree:
    try:
        return etree.parse(
            io.BytesIO(data),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Volume II ThML is not well formed") from exc


def _source_document_record(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()

    def adjacent_nodes(
        node: etree._Element | None, *, previous: bool
    ) -> list[dict[str, str]]:
        records = []
        while node is not None:
            records.append(
                {
                    "kind": "comment"
                    if node.tag is etree.Comment
                    else "processing-instruction",
                    "text": node.text or "",
                    "tail": node.tail or "",
                }
            )
            node = node.getprevious() if previous else node.getnext()
        if previous:
            records.reverse()
        return records

    return {
        "doctype": tree.docinfo.doctype,
        "encoding": tree.docinfo.encoding,
        "post_root_nodes": adjacent_nodes(root.getnext(), previous=False),
        "pre_root_nodes": adjacent_nodes(root.getprevious(), previous=True),
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": {
            "" if prefix is None else prefix: uri for prefix, uri in root.nsmap.items()
        },
        "root_tag": root.tag,
        "standalone": tree.docinfo.standalone,
        "xml_version": tree.docinfo.xml_version,
    }


def _source_metadata_record(tree: etree._ElementTree) -> dict[str, Any]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained Volume II source has no ThML.head")
    electronic = head.find("electronicEdInfo")
    if electronic is None:
        raise ValueError("retained Volume II source has no electronicEdInfo")
    dc = electronic.find("DC")
    print_info = head.find("printSourceInfo")

    def entries(nodes: list[etree._Element]) -> list[dict[str, Any]]:
        return [
            {
                "attributes": dict(node.attrib),
                "tag": node.tag,
                "tail": node.tail or "",
                "text": node.text or "",
            }
            for node in nodes
        ]

    return {
        "dc_entries": entries(list(dc) if dc is not None else []),
        "electronic_ed_info_entries": entries(
            [node for node in electronic if node.tag != "DC"]
        ),
        "head_c14n_sha256": _sha(
            etree.tostring(head, method="c14n", with_comments=True)
        ),
        "print_source_entries": entries(
            list(print_info) if print_info is not None else []
        ),
    }


def _tei_tree(data: bytes) -> etree._ElementTree:
    try:
        root = etree.fromstring(
            data,
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
            ),
        )
        return etree.ElementTree(root)
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is not well formed") from exc


def _authority(source: SourceManifest, name: str) -> bytes:
    return source.authority_path(name).read_bytes()


def _policy(source: SourceManifest) -> dict[str, Any]:
    policy = json.loads(_authority(source, "validation-policy"))
    if not isinstance(policy, dict) or policy.get("policy_id") != PROFILE_ID:
        raise ValueError("Volume II validation policy/profile binding drift")
    validator = source.record.get("validator")
    if not isinstance(validator, Mapping) or (
        validator.get("id") != ORACLE_ID
        or validator.get("version") != ORACLE_VERSION
        or validator.get("implementation_path")
        != "build/tei/hodge_systematic_theology_vol_2_oracle.py"
    ):
        raise ValueError("Volume II oracle identity is not bound by SourceManifest")
    return policy


def _profile(source: SourceManifest) -> dict[str, Any]:
    profile = json.loads(_authority(source, "reconstruction-profile"))
    if not isinstance(profile, dict) or profile.get("profile_id") != PROFILE_ID:
        raise ValueError("Volume II reconstruction profile binding drift")
    return profile


def _source_inventory(
    tree: etree._ElementTree, source: SourceManifest
) -> tuple[list[etree._Element], list[etree._Element]]:
    root = tree.getroot()
    body = root.find("ThML.body")
    if root.tag != "ThML" or body is None:
        raise ValueError("retained source envelope lacks ThML.body")
    top = [node for node in body if isinstance(node.tag, str)]
    if tuple(node.get("id") for node in top) != TOP_LEVEL_IDS:
        raise ValueError("retained Volume II top-level root inventory drift")
    if tuple(node.get("title", "") for node in top) != ROOT_LABELS:
        raise ValueError("retained Volume II root labels/order drift")
    scope = source.record.get("scope")
    expected_scope = {
        "assigned_roots_in_source_order": [list(item) for item in ASSIGNED_ROOTS],
        "excluded_top_level_roots": ["i", "ii", "v"],
        "kind": "complete-source-subtrees",
        "source_member": "retained-hodge-vol-2",
    }
    try:
        observed_scope = {
            "assigned_roots_in_source_order": [
                list(item) for item in scope["assigned_roots_in_source_order"]
            ],
            "excluded_top_level_roots": list(scope["excluded_top_level_roots"]),
            "kind": scope["kind"],
            "source_member": scope["source_member"],
        }
    except (KeyError, TypeError):
        raise ValueError("Volume II manifest scope is incomplete") from None
    if observed_scope != expected_scope or source.record.get("source_id") != SOURCE_ID:
        raise ValueError("Volume II manifest scope or source identity drift")
    return top, [top[2], top[3]]


def _first_party_path(root: Path, module: str) -> Path | None:
    direct = root.joinpath(*module.split(".")).with_suffix(".py")
    package = root.joinpath(*module.split("."), "__init__.py")
    return direct if direct.is_file() else package if package.is_file() else None


def _relative_module(module: str, path: Path, imported: str | None, level: int) -> str:
    if level == 0:
        return imported or ""
    parts = module.split(".")
    base = parts if path.name == "__init__.py" else parts[:-1]
    base = base[: len(base) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _local_closure(root: Path, policy: Mapping[str, Any]) -> str:
    forbidden = policy.get("forbidden_oracle_imports", [])
    if not isinstance(forbidden, list) or any(
        not isinstance(x, str) for x in forbidden
    ):
        raise ValueError("policy forbidden_oracle_imports is invalid")
    entry = Path(__file__).resolve()
    entry_module = "build.tei.hodge_systematic_theology_vol_2_oracle"
    pending = [entry_module]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_path(root, module)
        if path is None:
            continue
        modules[module] = path
        package_parts = (
            module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
        )
        pending.extend(
            ".".join(package_parts[:index])
            for index in range(1, len(package_parts) + 1)
        )
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                name = _relative_module(module, path, node.module, node.level)
                if name:
                    imports.add(name)
                    imports.update(
                        f"{name}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec", "import_module"}
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            ):
                raise ValueError("oracle closure contains dynamic import or execution")
        for name in imports:
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in forbidden
            ):
                raise ValueError(
                    f"oracle closure contains policy-forbidden import: {name}"
                )
            if (
                name == "build.tei.hodge_systematic_theology_vol_2_reconstruction"
                or name.startswith(
                    "build.tei.hodge_systematic_theology_vol_2_reconstruction."
                )
            ):
                raise ValueError("oracle closure imports Volume II producer")
            if _first_party_path(root, name) is not None:
                pending.append(name)
    if modules.get(entry_module) != entry:
        raise ValueError("oracle import-closure entry path mismatch")
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(set(modules.values()), key=lambda item: item.as_posix())
    ]
    return _sha(_canonical(records))


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id"
        if key == f"{{{XML_NS}}}id"
        else "xml:lang"
        if key == f"{{{XML_NS}}}lang"
        else key: value
        for key, value in node.attrib.items()
    }


def _expected_attribute_dispositions(
    source: etree._Element, policy: Mapping[str, Any]
) -> list[dict[str, str]]:
    rules = policy.get("attribute_rules", {})
    source_only = {"next", "parsed", "prev", "progress", "title", "version"}
    dispositions = []
    for name, value in source.attrib.items():
        rule = rules.get(name)
        if not isinstance(rule, Mapping) or source.tag not in rule.get(
            "source_tags", ()
        ):
            raise ValueError(f"policy does not account for {source.tag}@{name}")
        if name == "id":
            destination = "@xml:id-and-source-accountability"
            method = "deterministic-global-feature-id"
        elif name in source_only:
            destination = "source-accountability-only"
            method = "preserved-exactly-in-accountability"
        elif name in {"class", "style", "border"}:
            destination = "@rend"
            method = f"exact-source-{name}-token-in-rend"
        else:
            destination = str(rule.get("disposition", "source-accountability-only"))
            method = "declared-attribute-map"
        dispositions.append(
            {
                "destination": destination,
                "method": method,
                "source_attribute": name,
                "source_value": value,
            }
        )
    return dispositions


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            raise ValueError("Volume II source selector escaped ThML.body")
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _assert_projection(
    source: etree._Element,
    target: etree._Element,
    policy: Mapping[str, Any],
    counter: list[int],
) -> None:
    """Walk source and candidate in lockstep without producer traversal code."""
    projection = policy.get("projection")
    if not isinstance(projection, Mapping):
        raise ValueError("Volume II policy has no projection map")
    counter[0] += 1
    feature_id = f"hodge-systematic-theology-vol-2-feature-{counter[0]:06d}"
    source_tag = str(source.tag)
    tag_map = projection.get("tag_map", {})
    target_name = (
        projection.get("language_span_tag")
        if source_tag == "span" and source.get("lang")
        else tag_map.get(source_tag)
    )
    if source_tag in SPECIAL_TAG_PROJECTIONS:
        expected_name = SPECIAL_TAG_PROJECTIONS[source_tag]
        if target_name != expected_name:
            raise ValueError(
                f"Volume II policy must explicitly map {source_tag} to TEI {expected_name}"
            )
    if not isinstance(target_name, str) or target.tag != f"{{{TEI_NS}}}{target_name}":
        raise ValueError(f"candidate structure/tag drift at source {source_tag}")
    attrs = _normalized_attrs(target)
    expected_attrs = {"xml:id": feature_id}
    derived = projection.get("derived_attributes", {})
    if source_tag in {"div", "div1", "div2", "div3"}:
        expected_attrs["type"] = str(derived["div_type_template"]).format(
            source_tag=source_tag
        )
    elif source_tag == "hr":
        unit = derived.get("milestone_unit")
        if unit != "separator" or len(source) or set(source.attrib) != {"style"}:
            raise ValueError(
                "horizontal rule must be an explicitly accounted separator"
            )
        expected_attrs["unit"] = str(unit)
    elif source_tag == "verse":
        if (
            set(source.attrib) != {"id"}
            or not len(source)
            or any(child.tag != "l" for child in source)
        ):
            raise ValueError("ThML verse group contains an unexpected source form")
        expected_attrs["type"] = "source-verse"
    elif source_tag == "span" and not source.get("lang"):
        expected_attrs["type"] = str(derived["plain_span_type"])
    elif source_tag == "scripRef":
        expected_attrs["type"] = "scripture"

    rend = []
    source_rend = derived.get("source_tag_rend", {}).get(source_tag)
    if source_rend:
        rend.append(str(source_rend))
    rules = policy.get("attribute_rules", {})
    source_only = {"next", "parsed", "prev", "progress", "version"}
    for name, value in source.attrib.items():
        rule = rules.get(name)
        if not isinstance(rule, Mapping) or source_tag not in rule.get(
            "source_tags", ()
        ):
            raise ValueError(f"policy does not account for {source_tag}@{name}")
        if name in {"id", "title"} or name in source_only:
            continue
        if name == "lang":
            value_map = rule.get("value_map", {})
            if not isinstance(value_map, Mapping) or value not in value_map:
                raise ValueError(f"policy does not map source language {value!r}")
            expected_attrs["xml:lang"] = str(value_map[value])
        elif name == "n":
            expected_attrs["n"] = value
        elif name == "href":
            expected_attrs["facs"] = value
        elif name == "passage":
            expected_attrs["cRef"] = value
        elif name == "osisRef":
            expected_attrs["target"] = value
        elif name in {"class", "style", "border"}:
            rend.append(f"{name}={value}")
        else:
            raise ValueError(f"oracle has no independent map for {source_tag}@{name}")
    if rend:
        expected_attrs["rend"] = "; ".join(rend)
    if attrs != expected_attrs:
        raise ValueError(f"candidate attributes drift at source {source_tag}")
    if source_tag == "l" and (
        source.getparent() is None
        or source.getparent().tag != "verse"
        or source.get("class") not in {"t1", "t2"}
    ):
        raise ValueError(
            "ThML line is detached from or misclassified in its source verse group"
        )
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError("candidate source text or tail drift")
    children = list(target)
    source_children = list(source)
    if len(children) != len(source_children):
        raise ValueError("candidate omits, duplicates, or invents source structure")
    for left, right in zip(source_children, children, strict=True):
        if not isinstance(left.tag, str):
            raise ValueError("assigned source contains non-element content")
        _assert_projection(left, right, policy, counter)


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    policy = _policy(source_manifest)
    profile = _profile(source_manifest)
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("Volume II candidate package inventory/status drift")
    expected_source = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("source_manifest") != expected_source
        or candidate.manifest.get("package_schema")
        != source_manifest.record.get("package_schema")
        or candidate.manifest.get("converter")
        != source_manifest.record.get("converter")
    ):
        raise ValueError("Volume II candidate source/converter authority drift")
    content = _authority(source_manifest, "retained-hodge-vol-2")
    if len(content) != SOURCE_BYTES or _sha(content) != SOURCE_SHA256:
        raise ValueError("retained Volume II source bytes/hash drift")
    tree = _source_tree(content)
    top, assigned = _source_inventory(tree, source_manifest)
    observed_special_counts = {
        name: sum(
            1 for root_node in assigned for node in root_node.iter() if node.tag == name
        )
        for name in SPECIAL_TAG_COUNTS
    }
    if observed_special_counts != SPECIAL_TAG_COUNTS:
        raise ValueError("Volume II special-tag source census drift")
    # Independently inventory source nodes; never use the producer's traversal.
    assigned_nodes = [node for source_root in assigned for node in source_root.iter()]
    assigned_census = _census(assigned_nodes)
    complete_census = _census(list(tree.getroot().iter()))
    root_counts = {
        node.get("id"): sum(1 for child in node.iter() if isinstance(child.tag, str))
        for node in assigned
    }
    if (
        profile.get("assigned_root_counts") != root_counts
        or profile.get("assigned_census") != assigned_census
    ):
        raise ValueError("Volume II assigned-root source census drift")
    total = assigned_census["elements"]
    tei = _tei_tree(candidate.member_bytes("content.tei.xml"))
    document = tei.getroot()
    if document.tag != f"{{{TEI_NS}}}TEI" or _normalized_attrs(document) != {
        "xml:id": "hodge-systematic-theology-vol-2-candidate"
    }:
        raise ValueError("Volume II TEI document identity drift")
    if [etree.QName(node).localname for node in document] != ["teiHeader", "text"]:
        raise ValueError("Volume II TEI envelope drift")
    header_text = " ".join(" ".join(document[0].itertext()).split())
    for required in (
        "Systematic Theology",
        "Volume II",
        "1940",
        "1871",
        "Eerdmans",
        "Scribner",
        "Sourced via CCEL.org",
    ):
        if required not in header_text:
            raise ValueError(
                f"Volume II TEI provenance omits required distinction: {required}"
            )
    ns = {"tei": TEI_NS}
    bibls = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl", namespaces=ns
    )
    if len(bibls) != 1:
        raise ValueError(
            "Volume II source-description bibliography is missing or duplicated"
        )
    bibl = bibls[0]
    print_dates = bibl.xpath("./tei:date", namespaces=ns)
    if (
        len(print_dates) != 1
        or print_dates[0].get("when") != "1940"
        or " ".join(print_dates[0].itertext()).strip() != "1940"
    ):
        raise ValueError("Volume II retained 1940 imprint date drift")
    if bibl.xpath(".//tei:date[@when='1872' or @when='1873']", namespaces=ns):
        raise ValueError("unproven local-edition year adopted as an imprint date")
    claim_notes = bibl.xpath(
        "./tei:note[@type='unverified-local-edition-claim'][@source='work-config']",
        namespaces=ns,
    )
    claim_text = " ".join(claim_notes[0].itertext()) if len(claim_notes) == 1 else ""
    if (
        len(claim_notes) != 1
        or "1872-1873" not in claim_text
        or "not adopted" not in claim_text
    ):
        raise ValueError(
            "unverified local-edition claim is not preserved as unresolved"
        )
    other_bibl_text = " ".join(
        " ".join(node.itertext()) for node in bibl if node is not claim_notes[0]
    )
    if "1872-1873" in other_bibl_text:
        raise ValueError(
            "unproven local-edition claim appears outside its unresolved note"
        )
    header_nodes = list(document[0].iter())
    imprint = [
        node
        for node in header_nodes
        if "Eerdmans" in " ".join(node.itertext())
        and "1940" in " ".join(node.itertext())
    ]
    copyright = [
        node
        for node in header_nodes
        if "Scribner" in " ".join(node.itertext())
        and "1871" in " ".join(node.itertext())
    ]
    if (
        not imprint
        or not copyright
        or all(left is right for left in imprint for right in copyright)
    ):
        raise ValueError(
            "Volume II title-page imprint and copyright notice are not separately represented"
        )
    availability = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
        namespaces=ns,
    )
    if (
        len(availability) != 1
        or availability[0].get("status") != "unknown"
        or "not a rights decision" not in " ".join(availability[0].itertext()).lower()
    ):
        raise ValueError("Volume II rights status is not explicitly unresolved")
    text = document[1]
    if len(text) != 1 or etree.QName(text[0]).localname != "body":
        raise ValueError("Volume II TEI text/body topology drift")
    body = text[0]
    if _normalized_attrs(body).get("xml:id") != "hodge-systematic-theology-vol-2-body":
        raise ValueError("Volume II TEI body identity drift")
    targets = list(body)
    if len(targets) != 2:
        raise ValueError("Volume II candidate must represent roots iii then iv only")
    counter = [0]
    for source_root, target_root in zip(assigned, targets, strict=True):
        _assert_projection(source_root, target_root, policy, counter)
    if counter[0] != total:
        raise ValueError("Volume II candidate projection is incomplete")
    accountability = _json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    accounting_keys = {
        "assigned_census",
        "assigned_root_count",
        "assigned_work_count",
        "attribute_count",
        "complete_source_envelope",
        "contract",
        "crosswalk",
        "duplicate_feature_count",
        "feature_count",
        "member_accounting",
        "omitted_feature_count",
        "profile_id",
        "root_accounting",
        "root_bindings",
        "schema",
        "source_member_count",
        "unresolved_feature_count",
        "work_bindings",
    }
    if set(accountability) != accounting_keys:
        raise ValueError("Volume II source accountability fields drift")
    expected_accounting_values = {
        "assigned_census": assigned_census,
        "assigned_root_count": len(assigned),
        "assigned_work_count": 1,
        "attribute_count": assigned_census["attributes"],
        "contract": "ocd-37c204-source-accountability-v1",
        "duplicate_feature_count": 0,
        "feature_count": total,
        "omitted_feature_count": 0,
        "profile_id": PROFILE_ID,
        "schema": "inline-entry-structural-contract-v1",
        "source_member_count": 1,
        "unresolved_feature_count": 0,
    }
    if any(
        accountability.get(key) != value
        for key, value in expected_accounting_values.items()
    ):
        raise ValueError("Volume II source accountability census drift")
    roots = accountability.get("root_accounting")
    if not isinstance(roots, list) or len(roots) != len(top):
        raise ValueError("Volume II source accounting omits/reorders source roots")
    expected_envelope = {
        "assigned_root_ids_in_source_order": ["iii", "iv"],
        "excluded_root_ids": ["i", "ii", "v"],
        "top_level_root_ids_in_source_order": list(TOP_LEVEL_IDS),
        "top_level_root_count": 5,
    }
    if accountability.get("complete_source_envelope") != expected_envelope:
        raise ValueError("Volume II complete source envelope accounting drift")
    expected_roots = []
    for index, node in enumerate(top, 1):
        root_census = _census(list(node.iter()))
        assigned_root = node.get("id") in {"iii", "iv"}
        expected_roots.append(
            {
                "census": root_census,
                "disposition": "assigned-work-root-represented"
                if assigned_root
                else "source-evidence-outside-work-projection",
                "feature_count": root_census["elements"],
                "id": node.get("id"),
                "ordinal": index,
                "reason": "complete source-native subtree represented in retained order"
                if assigned_root
                else "title, prefatory, or index material outside the assigned work projection",
                "selector": _selector(node),
                "tag": node.tag,
                "title": node.get("title", ""),
            }
        )
    if roots != expected_roots:
        raise ValueError("Volume II top-level source-root accounting drift")
    members = accountability.get("member_accounting")
    if not isinstance(members, list) or len(members) != 1:
        raise ValueError("Volume II source member accounting is incomplete")
    expected_member = {
        "assigned_scope_census": assigned_census,
        "bytes": SOURCE_BYTES,
        "complete_document_census": complete_census,
        "document_accounting": _source_document_record(tree),
        "excluded_scope_census": _subtract(complete_census, assigned_census),
        "key": SOURCE_KEY,
        "path": SOURCE_PATH,
        "sha256": SOURCE_SHA256,
        "disposition": "retained primary source; assigned content roots represented and all excluded top-level roots explicitly accounted",
    }
    if members != [expected_member]:
        raise ValueError("Volume II retained-source/member accounting drift")
    expected_root_bindings = []
    for order, node in enumerate(assigned, 1):
        root_census = _census(list(node.iter()))
        expected_root_bindings.append(
            {
                "feature_count": root_census["elements"],
                "root_census": root_census,
                "source_key": SOURCE_KEY,
                "source_member": SOURCE_PATH,
                "source_root_id": node.get("id"),
                "source_root_selector": _selector(node),
                "source_root_title": node.get("title", ""),
                "source_order": order,
                "work_id": WORK_ID,
            }
        )
    if accountability.get("root_bindings") != expected_root_bindings:
        raise ValueError("Volume II source root bindings drift")
    expected_work_bindings = [
        {
            "root_ids": ["iii", "iv"],
            "source_key": SOURCE_KEY,
            "source_member": SOURCE_PATH,
            "work_id": WORK_ID,
        }
    ]
    if accountability.get("work_bindings") != expected_work_bindings:
        raise ValueError("Volume II source work bindings drift")
    crosswalk = accountability.get("crosswalk")
    if not isinstance(crosswalk, list) or len(crosswalk) != total:
        raise ValueError("Volume II source crosswalk completeness drift")
    expected_nodes = [
        node
        for source_root in assigned
        for node in source_root.iter()
        if isinstance(node.tag, str)
    ]
    target_nodes = [
        node
        for target_root in targets
        for node in target_root.iter()
        if isinstance(node.tag, str)
        and _normalized_attrs(node)
        .get("xml:id", "")
        .startswith("hodge-systematic-theology-vol-2-feature-")
    ]
    if len(target_nodes) != total:
        raise ValueError("Volume II TEI feature inventory is incomplete")
    source_root_by_node = {
        id(node): source_root
        for source_root in assigned
        for node in source_root.iter()
        if isinstance(node.tag, str)
    }
    feature_id_by_node = {
        id(node): f"hodge-systematic-theology-vol-2-feature-{index:06d}"
        for index, node in enumerate(expected_nodes, 1)
    }
    for index, (row, node, target_node) in enumerate(
        zip(crosswalk, expected_nodes, target_nodes, strict=True), 1
    ):
        source_root = source_root_by_node[id(node)]
        parent = node.getparent()
        child_ordinal = (
            TOP_LEVEL_IDS.index(source_root.get("id")) + 1
            if node is source_root
            else list(parent).index(node) + 1
        )
        source_text = (node.text or "").encode("utf-8")
        source_tail = (node.tail or "").encode("utf-8")
        expected_row = {
            "attribute_dispositions": _expected_attribute_dispositions(node, policy),
            "child_ordinal": child_ordinal,
            "direct_text_length": len(source_text),
            "direct_text_sha256": _sha(source_text),
            "disposition": "represented",
            "feature_id": f"hodge-systematic-theology-vol-2-feature-{index:06d}",
            "parent_feature_id": feature_id_by_node.get(id(parent)),
            "source_attributes": dict(node.attrib),
            "source_member": SOURCE_KEY,
            "source_root_id": source_root.get("id"),
            "source_selector": _selector(node),
            "source_tag": node.tag,
            "source_xml_id": node.get("id"),
            "tail_text_length": len(source_tail),
            "tail_text_sha256": _sha(source_tail),
            "tei_attributes": _normalized_attrs(target_node),
            "tei_tag": etree.QName(target_node).localname,
            "tei_xml_id": _normalized_attrs(target_node).get("xml:id"),
            "work_id": WORK_ID,
        }
        if row.get("attribute_dispositions") != expected_row["attribute_dispositions"]:
            raise ValueError(
                f"Volume II source attribute disposition drift at feature {index}"
            )
        if row != expected_row:
            raise ValueError(f"Volume II source crosswalk drift at feature {index}")
    provenance = _json(candidate.member_bytes("provenance.json"), "provenance")
    if (
        set(provenance)
        != {
            "canonical_data_written",
            "canonical_ir_written",
            "contract",
            "publication_state",
            "source_id",
            "source_scope",
            "sources",
            "works",
        }
        or provenance.get("contract") != "ocd-37c204-provenance-v1"
        or provenance.get("source_id") != SOURCE_ID
        or provenance.get("canonical_data_written") is not False
        or provenance.get("canonical_ir_written") is not False
        or provenance.get("publication_state") != "not_ready"
    ):
        raise ValueError("Volume II provenance identity/state drift")
    expected_source_scope = {
        "assigned_roots": [list(item) for item in ASSIGNED_ROOTS],
        "excluded_top_level_roots": [
            root_id for root_id in TOP_LEVEL_IDS if root_id not in {"iii", "iv"}
        ],
        "kind": "complete-source-subtrees",
    }
    if provenance.get("source_scope") != expected_source_scope:
        raise ValueError("Volume II source scope provenance drift")
    expected_work_provenance = {
        "accepted_ir": "not_accepted",
        "human_review": "required",
        "publication": "not_ready",
        "root_ids": ["iii", "iv"],
        "source_key": SOURCE_KEY,
        "source_member": SOURCE_PATH,
        "textual_form": "retained English CCEL electronic ThML witness; translation or revision allocation not established",
        "translation_credit": {
            "credited_to": [],
            "status": "not-established-in-retained-source",
            "work_specific_allocation": None,
        },
        "work_id": WORK_ID,
    }
    if provenance.get("works") != [expected_work_provenance]:
        raise ValueError("Volume II work provenance drift")
    serialized_provenance = json.dumps(provenance, ensure_ascii=False, sort_keys=True)
    sources = provenance.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != {SOURCE_KEY}:
        raise ValueError("Volume II source provenance inventory drift")
    source_provenance = sources.get(SOURCE_KEY)
    if not isinstance(source_provenance, Mapping):
        raise ValueError("Volume II source provenance record is missing")
    if set(source_provenance) != {
        "bytes",
        "config_claims",
        "metadata",
        "path",
        "permission_evidence",
        "sha256",
        "witness_inventory",
    }:
        raise ValueError("Volume II source provenance fields drift")
    if (
        source_provenance.get("path") != SOURCE_PATH
        or source_provenance.get("bytes") != SOURCE_BYTES
        or source_provenance.get("sha256") != SOURCE_SHA256
        or "2005-06-20" not in serialized_provenance
        or "Christian Classics Ethereal Library" not in serialized_provenance
    ):
        raise ValueError("Volume II electronic-source provenance drift")
    permission_bytes = _authority(source_manifest, "ccel-permission-evidence")
    expected_permission_evidence = {
        "bytes": len(permission_bytes),
        "path": source_manifest.authority_path("ccel-permission-evidence")
        .relative_to(root)
        .as_posix(),
        "sha256": _sha(permission_bytes),
    }
    if source_provenance.get("permission_evidence") != expected_permission_evidence:
        raise ValueError("Volume II permission provenance drift")
    witness_bytes = _authority(source_manifest, "witness-inventory")
    expected_witness_inventory = json.loads(witness_bytes.decode("utf-8"))
    if source_provenance.get("witness_inventory") != expected_witness_inventory:
        raise ValueError("Volume II witness provenance drift")
    head = tree.getroot().find("ThML.head")
    metadata = source_provenance.get("metadata")
    if head is None or metadata != _source_metadata_record(tree):
        raise ValueError("Volume II electronic-header evidence binding drift")
    created_dates = [
        row.get("text")
        for row in metadata.get("dc_entries", [])
        if row.get("tag") == "DC.Date"
        and row.get("attributes", {}).get("sub") == "Created"
    ]
    if created_dates != ["2005-06-20"]:
        raise ValueError("Volume II CCEL electronic-creation date is not source-bound")
    config_claims = source_provenance.get("config_claims")
    expected_claims = json.loads(
        _authority(source_manifest, "work-config").decode("utf-8")
    )
    if config_claims != {
        "authority": "work-config",
        "claims": expected_claims,
        "status": "unresolved-not-adopted",
    }:
        raise ValueError(
            "Volume II work-config claims are not preserved as unresolved evidence"
        )
    unresolved = candidate.member_bytes("unresolved.jsonl").splitlines()
    if not unresolved:
        raise ValueError("Volume II unresolved rights/edition questions were dropped")
    unresolved_records = [json.loads(line.decode("utf-8")) for line in unresolved]
    unresolved_by_id = {row.get("id"): row for row in unresolved_records}
    expected_unresolved_ids = {
        f"{WORK_ID}-print-edition-claim",
        f"{WORK_ID}-textual-form-and-contributors",
        f"{WORK_ID}-rights-and-acceptance",
        f"{WORK_ID}-visual-review-and-admission",
    }
    if set(unresolved_by_id) != expected_unresolved_ids or any(
        row.get("status") != "unresolved" for row in unresolved_records
    ):
        raise ValueError("Volume II rights and edition unknowns must remain explicit")
    edition_evidence = unresolved_by_id[f"{WORK_ID}-print-edition-claim"].get(
        "evidence", ""
    )
    rights_evidence = unresolved_by_id[f"{WORK_ID}-rights-and-acceptance"].get(
        "evidence", ""
    )
    if (
        not all(phrase in edition_evidence for phrase in ("1940", "1871", "1872-1873"))
        or "not a rights decision" not in rights_evidence
    ):
        raise ValueError("Volume II unresolved edition/rights evidence is incomplete")
    readme_bytes = candidate.member_bytes("README.source.md")
    if readme_bytes != _authority(source_manifest, "attribution-readme"):
        raise ValueError(
            "Volume II source README differs from its bound attribution authority"
        )
    readme = readme_bytes.decode("utf-8").casefold()
    if "sourced via ccel.org" not in readme:
        raise ValueError("Volume II attribution is missing from source README")
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    try:
        schema.assertValid(tei)
    except etree.DocumentInvalid as exc:
        raise ValueError("Volume II candidate fails TEI P5 schema") from exc
    result: dict[str, object] = {
        "candidate_sha256": candidate.sha256,
        "findings": [],
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _local_closure(root, policy),
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "package_schema_sha256": _sha(
            _authority(source_manifest, "candidate-package-schema")
        ),
        "policy_sha256": _sha(_authority(source_manifest, "validation-policy")),
        "profile_sha256": _sha(_authority(source_manifest, "reconstruction-profile")),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "source_sha256": SOURCE_SHA256,
        "status": "pass",
        "xsd_sha256": _sha(_authority(source_manifest, "tei-p5-xsd")),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__ = ("_oracle",)
