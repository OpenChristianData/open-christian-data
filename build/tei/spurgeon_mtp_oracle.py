"""Producer-independent oracle for the complete retained Spurgeon MTP candidate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform
import subprocess
import sys
from types import MappingProxyType
from typing import Mapping, Sequence
from xml.parsers import expat

from jsonschema import Draft202012Validator
from lxml import etree, html

from build.lib.tei_xsd import compiled_tei_schema
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-spurgeon-mtp-complete-retained-source-oracle"
ORACLE_VERSION = "1"
_PROFILE_ID = "spurgeon-mtp-complete-retained-corpus-v1"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_MISSING = (8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, 390)
_SUPPLEMENTAL_RIGHTS_NUMBERS = (708, 3032)
_FIRST_PARTY_IMPORT_PATHS = (
    "build/__init__.py",
    "build/lib/__init__.py",
    "build/lib/tei_xsd.py",
    "build/tei/spurgeon_mtp_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
)
_SKIP = frozenset({"img", "script", "style"})
_BLOCK = frozenset(
    {
        "blockquote",
        "center",
        "div",
        "h1",
        "h2",
        "hr",
        "ol",
        "p",
        "table",
        "td",
        "tr",
        "ul",
    }
)
_TAG_MAP = {
    "a": "ref",
    "article": "div",
    "b": "hi",
    "blockquote": "quote",
    "br": "lb",
    "center": "div",
    "code": "seg",
    "div": "div",
    "em": "hi",
    "font": "seg",
    "h1": "head",
    "h2": "head",
    "hr": "milestone",
    "i": "hi",
    "li": "item",
    "ol": "list",
    "p": "p",
    "small": "hi",
    "span": "ref-or-seg",
    "strong": "hi",
    "table": "div",
    "td": "div",
    "tr": "div",
    "ul": "list",
}
_TEI_ATTRIBUTE_POLICY = {
    "a": {"type": "source-link", "source_attribute_map": {"href": "target"}},
    "b": {"rend": "bold"},
    "center": {"type": "source-center"},
    "code": {"type": "source-code"},
    "div": {"type": "source-div"},
    "em": {"rend": "italic"},
    "font": {"type": "source-font", "source_attribute_map": {"size": "rend"}},
    "hr": {"unit": "source-horizontal-rule"},
    "i": {"rend": "italic"},
    "ol": {"type": "ordered", "source_attribute_map": {"type": "rend"}},
    "small": {"rend": "small"},
    "span.other": {"type": "source-span"},
    "span.reference": {"type": "scripture"},
    "strong": {"rend": "bold"},
    "table": {"type": "source-table"},
    "td": {"type": "source-td"},
    "tr": {"type": "source-tr"},
    "ul": {"type": "bulleted", "source_attribute_map": {"type": "rend"}},
}
_GENERATED_ATTRIBUTE_POLICY = {
    "source-container-segment": {"element": "div", "type": "source-container-segment"},
    "source-flow": {"element": "ab", "type": "source-flow"},
}
_SERMON_ATTRIBUTE_POLICY = {
    "type": "sermon",
    "n": "source-sermon-number",
    "subtype": "source-selection",
    "xml:id": "spurgeon-mtp-{number:04d}",
}
_TEI_HEADER_POLICY = {
    "title": "Metropolitan Tabernacle Pulpit — complete retained HTML corpus candidate",
    "author": "C. H. Spurgeon",
    "contributors": [
        {"resp": "manuscript editor", "name": "Emmett O'Donnell"},
        {"resp": "designer", "name": "Benry Yip"},
    ],
    "publisher": "Open Christian Data",
    "availability_status": "restricted",
    "source_url": "https://thekingdomcollective.com/spurgeon/",
    "source_sha256_type": "sha256",
    "print_source": "3,547 retained Kingdom Collective sermon pages plus three explicitly identified supplemental retained sermon pages.",
}
_ATTRIBUTION_EVIDENCE = {
    "primary_html_count": 3547,
    "retained_wording": [
        {
            "name": "Emmett O'Donnell",
            "wording": "transcribed from manuscripts edited by Emmett O'Donnell",
            "supported_responsibility": "manuscript editor",
        },
        {
            "name": "Benry Yip",
            "wording": "Designed by Benry Yip",
            "supported_responsibility": "designer",
        },
    ],
    "unresolved_responsibilities": [
        "The retained primary wording does not identify the transcriber.",
        "The retained primary wording does not identify the digitizer.",
    ],
}
_ATTRIBUTION = [
    {
        "name": "Emmett O'Donnell",
        "role": "manuscript editor",
        "source_wording": "transcribed from manuscripts edited by Emmett O'Donnell",
        "affiliation": "SpurgeonGems (spurgeongems.org)",
        "url": "http://www.spurgeongems.org/",
    },
    {
        "name": "Benry Yip",
        "role": "designer",
        "source_wording": "Designed by Benry Yip",
        "affiliation": "The Kingdom Collective",
        "url": "https://thekingdomcollective.com/spurgeon/",
    },
]
_ATTRIBUTION_UNRESOLVED = {
    "id": "spurgeon-mtp-contributor-responsibility",
    "kind": "metadata/source-responsibility",
    "scope": {"primary_html_count": 3547},
    "status": "localized-unresolved",
    "evidence": _ATTRIBUTION_EVIDENCE["retained_wording"],
    "unresolved_responsibilities": _ATTRIBUTION_EVIDENCE["unresolved_responsibilities"],
    "owner": "source-evidence-maintainer",
    "next_action": (
        "Do not assign transcriber or digitizer contributor roles without retained "
        "primary evidence."
    ),
    "reopening_condition": (
        "Retained primary evidence identifies who performed transcription or "
        "digitization."
    ),
}
_WORK_IDENTITY_CONTRIBUTORS = [
    {
        "name": "Emmett O'Donnell",
        "role": "manuscript editor",
        "affiliation": "SpurgeonGems (spurgeongems.org)",
        "url": "http://www.spurgeongems.org/",
    },
    {
        "name": "Benry Yip",
        "role": "designer",
        "affiliation": "The Kingdom Collective",
        "url": "https://thekingdomcollective.com/spurgeon/",
    },
]
_WORK_IDENTITY_SOURCE_EDITION = "Retained Kingdom Collective HTML sermon pages."
_LEGACY_JSON_BOUNDARY = (
    "Legacy canonical JSON is an aid outside this campaign, not candidate authority, "
    "and remains untouched under the protected-path rule."
)
_WORK_IDENTITY_NOTES = (
    "Spurgeon died in 1892; the underlying sermons are public domain. Retained "
    'primary wording says the collection was "transcribed from manuscripts edited '
    'by Emmett O\'Donnell" and states "Designed by Benry Yip." It does not identify '
    "the transcriber or digitizer; those responsibilities remain unresolved. "
    f"{_LEGACY_JSON_BOUNDARY} Output is split into per-chunk files "
    "(sermons-<start>-<end>.json, 100 sermons per file) to stay under GitHub's "
    "100 MB file-size limit."
)


@dataclass(frozen=True, slots=True)
class _SermonFact:
    number: int
    authority: Mapping[str, object]
    selection: str
    source_tree_sha256: str
    source_event_tags: tuple[str, ...]
    source_events_sha256: str
    normalized_text_sha256: str
    expected_accountability: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _SourceFacts:
    source_manifest_sha256: str
    oracle_implementation_sha256: str
    import_closure_sha256: str
    authorities: tuple[Mapping[str, object], ...]
    profile: Mapping[str, object]
    profile_sha256: str
    package_schema_sha256: str
    xsd_sha256: str
    policy_sha256: str
    source_set_sha256: str
    work_identity_config: Mapping[str, object]
    supplemental_rights: Mapping[str, object]
    rights_evidence: Mapping[int, Mapping[str, object]]
    source_readme: bytes
    request_log: Mapping[str, object]
    sermon_facts: tuple[_SermonFact, ...]
    facts_sha256: str


@dataclass(frozen=True, slots=True)
class _CandidateSnapshot:
    candidate_sha256: str
    manifest: Mapping[str, object]
    members: Mapping[str, bytes]

    def member_bytes(self, name: str) -> bytes:
        try:
            return self.members[name]
        except KeyError as exc:
            raise ValueError(f"unknown candidate member {name!r}") from exc


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"{label} has duplicate key {key!r}")
            value[key] = item
        return value

    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result


def _deep_freeze(value: object) -> object:
    """Copy JSON-like values into a deeply immutable object graph."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    raise TypeError(f"unsupported source-fact value {type(value).__name__}")


def _deep_thaw(value: object) -> object:
    """Return an independent JSON-compatible view of frozen source facts."""

    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _snapshot_candidate(candidate: CandidatePackage) -> _CandidateSnapshot:
    """Capture one integrity-checked package view for the complete validation run."""

    candidate.verify_integrity()
    members = {
        name: (candidate.path / name).read_bytes() for name in candidate.member_names
    }
    manifest_bytes = members["manifest.json"]
    if _sha(manifest_bytes) != candidate.sha256:
        raise ValueError("Spurgeon candidate manifest bytes drifted during snapshot")
    manifest = _json(manifest_bytes, "Spurgeon candidate manifest")
    records = manifest.get("members")
    if not isinstance(records, list):
        raise ValueError("Spurgeon candidate member inventory drifted")
    expected = {
        item.get("name"): (item.get("bytes"), item.get("sha256"))
        for item in records
        if isinstance(item, dict)
    }
    for name, content in members.items():
        if name == "manifest.json":
            continue
        if expected.get(name) != (len(content), _sha(content)):
            raise ValueError(f"Spurgeon candidate snapshot drifted for {name}")
    return _CandidateSnapshot(candidate.sha256, manifest, members)


def _validate_work_identity_config(
    source_manifest: SourceManifest, profile: Mapping[str, object]
) -> dict[str, object]:
    path = source_manifest.authority_path("work-identity-config")
    content = path.read_bytes()
    config = _json(content, "Spurgeon work-identity config")
    if config.get("contributors") != _WORK_IDENTITY_CONTRIBUTORS:
        raise ValueError(
            "Spurgeon work-identity config contributors contradict retained wording"
        )
    if config.get("source_edition") != _WORK_IDENTITY_SOURCE_EDITION:
        raise ValueError(
            "Spurgeon work-identity config source_edition asserts unsupported lineage"
        )
    if config.get("notes") != _WORK_IDENTITY_NOTES:
        raise ValueError(
            "Spurgeon work-identity config notes contradict the protected legacy boundary"
        )
    if (
        config.get("resource_id") != "spurgeon-mtp"
        or config.get("title") != "Metropolitan Tabernacle Pulpit"
        or config.get("author") != "C. H. Spurgeon"
    ):
        raise ValueError("Spurgeon work-identity config identity drifted")
    expected_binding = {
        "path": "sources/sermons/spurgeon-mtp/config.json",
        "bytes": len(content),
        "sha256": _sha(content),
        "candidate_authority": False,
        "legacy_json_boundary": _LEGACY_JSON_BOUNDARY,
    }
    if profile.get("work_identity_config") != expected_binding:
        raise ValueError("Spurgeon work-identity config profile binding drifted")
    return expected_binding


def _text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _number(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError as exc:
        raise ValueError(f"Non-numeric Spurgeon authority {path.name}") from exc


def _evidence_region(path: Path, number: int) -> tuple[etree._Element, str]:
    page = html.document_fromstring(path.read_bytes())
    if path.parent.name == "html":
        candidates = [
            node
            for node in page.xpath("//article")
            if "sermon" in (node.get("class") or "").split()
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"Primary retained page {path} lost its unique sermon article"
            )
        return candidates[0], "primary-article"

    region = etree.Element("section")
    if number in (708, 3032):
        bodies = [
            node
            for node in page.xpath("//div")
            if "bd-ctBody" in (node.get("class") or "").split()
        ]
        if len(bodies) != 1:
            raise ValueError(
                f"Supplemental retained page {path} lost its unique content body"
            )
        wanted = (
            ("h1", "name"),
            ("div", "published-info"),
            ("p", "intro"),
            ("div", "node-body"),
        )
        for tag, token in wanted:
            matches = [
                node
                for node in bodies[0]
                if isinstance(node.tag, str)
                and node.tag.lower() == tag
                and token in (node.get("class") or "").split()
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Supplemental evidence region {tag}.{token} is not unique"
                )
            region.append(deepcopy(matches[0]))
        return region, "supplemental-aig-sermon-content"

    if number != 1698:
        raise ValueError(f"Unexpected supplemental retained number {number}")
    h1 = page.xpath("//h1")
    if len(h1) != 1:
        raise ValueError("Supplemental retained page 1698 lost its unique heading")
    cell = next((node for node in h1[0].iterancestors() if node.tag == "td"), None)
    if cell is None:
        raise ValueError("Supplemental retained page 1698 lost its sermon table cell")
    children = [node for node in cell if isinstance(node.tag, str)]
    starts = [
        i
        for i, node in enumerate(children)
        if node.tag == "center" and node.xpath(".//h1")
    ]
    footers = [
        i
        for i, node in enumerate(children)
        if node.tag == "p" and "Collection administered by" in _text(node)
    ]
    if (
        len(starts) != 1
        or len(footers) != 1
        or footers[0] < 2
        or children[footers[0] - 1].tag != "hr"
    ):
        raise ValueError("Supplemental retained page 1698 boundaries drifted")
    for node in children[starts[0] : footers[0]]:
        region.append(deepcopy(node))
    return region, "supplemental-spurgeon-archive-sermon-content"


def _retained_rights_evidence(path: Path, number: int) -> dict[str, object]:
    if number not in _SUPPLEMENTAL_RIGHTS_NUMBERS:
        raise ValueError(f"Sermon {number} is outside the supplemental rights scope")
    page = html.document_fromstring(path.read_bytes())
    outros = [
        node
        for node in page.iter("div")
        if node.get("id") == "ipaNodeOutro"
        and "outro" in (node.get("class") or "").split()
    ]
    if len(outros) != 1:
        raise ValueError(f"Supplemental rights node omission or scope drift in {path}")
    children = [node for node in outros[0] if isinstance(node.tag, str)]
    headings = [
        (index, node)
        for index, node in enumerate(children)
        if node.tag.lower() == "h2" and _text(node) == "Terms of Use"
    ]
    if len(headings) != 1 or headings[0][0] + 1 >= len(children):
        raise ValueError(f"Supplemental Terms of Use omission in {path}")
    terms_node = children[headings[0][0] + 1]
    if terms_node.tag.lower() != "p":
        raise ValueError(f"Supplemental Terms of Use paragraph drift in {path}")
    text = _text(terms_node)
    exact_clauses = (
        "Modernized Edition of Spurgeon’s Sermons.",
        "Copyright © 2010, Larry and Marion Pierce, Winterbourne, Ontario, Canada.",
        "The modernized edition of the material published in these sermons may not be reproduced or distributed by any electronic means without express written permission of the copyright owner.",
        "A limited license is hereby granted for the non-commercial printing and distribution of the material in hard copy form, provided this is done without charge to the recipient and the copyright information remains intact.",
        "Any charge or cost for distribution of the material is expressly forbidden under the terms of this limited license and automatically voids such permission.",
        "You may not prepare, manufacture, copy, use, promote, distribute, or sell a derivative work of the copyrighted work without the express written permission of the copyright owner.",
    )
    if any(clause not in text for clause in exact_clauses):
        raise ValueError(f"Supplemental rights owner or term drift in {path}")
    return {
        "sermon_number": number,
        "retained_path": "/".join(path.parts[-4:]),
        "selector": "div#ipaNodeOutro.outro > h2[Terms of Use] + p",
        "source_text": text,
        "source_text_sha256": _sha(text.encode("utf-8")),
    }


def _validate_profile_policy(
    profile: Mapping[str, object], rights_evidence: Mapping[int, dict[str, object]]
) -> dict[str, object]:
    structure = profile.get("structure_policy")
    rights = profile.get("rights")
    if not isinstance(structure, Mapping) or not isinstance(rights, Mapping):
        raise ValueError("Spurgeon profile structure or rights contract is missing")
    mapping = structure.get("tei_mapping")
    if not isinstance(mapping, Mapping) or mapping.get("font") != "seg":
        raise ValueError("Spurgeon font policy must preserve inline font as TEI seg")
    if structure.get("attribute_mapping") != {
        "a.href": "ref.target",
        "font.size": "seg.rend",
        "ol.type": "list.rend",
        "ul.type": "list.rend",
    }:
        raise ValueError("Spurgeon source-attribute policy drifted")
    if (
        structure.get("tei_attribute_policy") != _TEI_ATTRIBUTE_POLICY
        or structure.get("generated_tei_attribute_policy")
        != _GENERATED_ATTRIBUTE_POLICY
        or structure.get("sermon_attribute_policy") != _SERMON_ATTRIBUTE_POLICY
        or profile.get("tei_header_policy") != _TEI_HEADER_POLICY
    ):
        raise ValueError("Spurgeon TEI attribute or header policy drifted")
    attribution = profile.get("attribution")
    if (
        attribution != _ATTRIBUTION
        or profile.get("attribution_evidence") != _ATTRIBUTION_EVIDENCE
        or not isinstance(attribution, list)
        or [
            {"resp": item.get("role"), "name": item.get("name")}
            for item in attribution
            if isinstance(item, Mapping)
        ]
        != _TEI_HEADER_POLICY["contributors"]
    ):
        raise ValueError("Spurgeon TEI contributor policy drifted")
    supplemental = rights.get("supplemental_witness_terms")
    if not isinstance(supplemental, dict):
        raise ValueError("Spurgeon supplemental rights contract is missing")
    expected_scope = {
        "sermon_numbers": [708, 3032],
        "retained_paths": [
            "raw/spurgeon_sermons/missing/708.html",
            "raw/spurgeon_sermons/missing/3032.html",
        ],
    }
    expected_terms = {
        "electronic_reproduction": "The modernized edition of the material published in these sermons may not be reproduced or distributed by any electronic means without express written permission of the copyright owner.",
        "hard_copy_license": "A limited license is hereby granted for the non-commercial printing and distribution of the material in hard copy form, provided this is done without charge to the recipient and the copyright information remains intact. Any charge or cost for distribution of the material is expressly forbidden under the terms of this limited license and automatically voids such permission.",
        "derivative_works": "You may not prepare, manufacture, copy, use, promote, distribute, or sell a derivative work of the copyrighted work without the express written permission of the copyright owner.",
    }
    evidence = [rights_evidence[number] for number in _SUPPLEMENTAL_RIGHTS_NUMBERS]
    if (
        supplemental.get("edition") != "Modernized Edition of Spurgeon’s Sermons"
        or supplemental.get("copyright")
        != "Copyright © 2010, Larry and Marion Pierce, Winterbourne, Ontario, Canada"
        or supplemental.get("rights_owners") != ["Larry Pierce", "Marion Pierce"]
        or supplemental.get("scope") != expected_scope
        or supplemental.get("terms") != expected_terms
        or supplemental.get("exact_source_text") != evidence[0]["source_text"]
        or evidence[0]["source_text"] != evidence[1]["source_text"]
        or supplemental.get("retained_evidence") != evidence
        or supplemental.get("blocker_owner") != "project-maintainer"
        or not supplemental.get("next_action")
        or not supplemental.get("reopening_condition")
    ):
        raise ValueError(
            "Spurgeon supplemental rights owner, terms, scope, or evidence drifted"
        )
    return supplemental


def _validate_primary_attribution_evidence(
    source_manifest: SourceManifest,
    textual: list[Mapping[str, object]],
) -> None:
    primary = [
        item
        for item in textual
        if str(item.get("path", "")).startswith("raw/spurgeon_sermons/html/")
    ]
    if len(primary) != _ATTRIBUTION_EVIDENCE["primary_html_count"]:
        raise ValueError("Spurgeon primary attribution witness count drifted")
    wording = [
        str(item["wording"]) for item in _ATTRIBUTION_EVIDENCE["retained_wording"]
    ]
    for item in primary:
        path = source_manifest.authority_path(str(item["name"]))
        page = html.parse(str(path)).getroot()
        normalized = _text(page)
        if any(value not in normalized for value in wording):
            raise ValueError(f"Spurgeon retained attribution wording drifted in {path}")


def _expected_tei_attributes(node: etree._Element) -> dict[str, str]:
    source_tag = node.tag.lower()
    if source_tag in {"em", "i"}:
        return {"rend": "italic"}
    if source_tag in {"strong", "b"}:
        return {"rend": "bold"}
    if source_tag == "small":
        return {"rend": "small"}
    if source_tag == "code":
        return {"type": "source-code"}
    if source_tag == "a":
        attributes = {"type": "source-link"}
        if node.get("href") is not None:
            attributes["target"] = str(node.get("href"))
        return attributes
    if source_tag == "span":
        return {
            "type": (
                "scripture"
                if "reference" in (node.get("class") or "").split()
                else "source-span"
            )
        }
    if source_tag == "font":
        attributes = {"type": "source-font"}
        if node.get("size") is not None:
            attributes["rend"] = str(node.get("size"))
        return attributes
    if source_tag in {"ol", "ul"}:
        attributes = {"type": "ordered" if source_tag == "ol" else "bulleted"}
        if node.get("type"):
            attributes["rend"] = str(node.get("type"))
        return attributes
    if source_tag == "hr":
        return {"unit": "source-horizontal-rule"}
    if source_tag in {"center", "div", "table", "td", "tr"}:
        return {"type": f"source-{source_tag}"}
    return {}


def _tei_element(
    localname: str, attributes: Mapping[str, str] | None = None
) -> etree._Element:
    return etree.Element(
        f"{{{_TEI_NS}}}{localname}",
        {} if attributes is None else dict(attributes),
    )


class _ExpectedTreeContext:
    def __init__(self, number: int) -> None:
        self.number = number
        self.index = 0

    def identify(self, target: etree._Element) -> None:
        self.index += 1
        target.set(_XML_ID, f"spurgeon-{self.number:04d}-source-{self.index:06d}")


def _copy_source_tail(source: etree._Element, target: etree._Element) -> None:
    if source.tail:
        target.tail = source.tail


def _append_expected_text(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _expected_inline(
    source: etree._Element, context: _ExpectedTreeContext
) -> etree._Element | None:
    tag = str(source.tag).lower()
    if tag in _SKIP:
        return None
    expected_tag = _TAG_MAP.get(tag)
    if expected_tag is None:
        raise ValueError(
            f"Unaccounted retained HTML inline tag <{tag}> in sermon {context.number}"
        )
    if tag == "span":
        expected_tag = (
            "ref" if "reference" in (source.get("class") or "").split() else "seg"
        )
    target = _tei_element(expected_tag, _expected_tei_attributes(source))
    context.identify(target)
    target.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            continue
        converted = _expected_inline(child, context)
        if converted is None:
            _append_expected_text(target, child.tail)
            continue
        _copy_source_tail(child, converted)
        target.append(converted)
    return target


def _expected_flow(parent: etree._Element) -> etree._Element:
    if (
        len(parent)
        and isinstance(parent[-1].tag, str)
        and etree.QName(parent[-1]).localname == "ab"
        and parent[-1].get("type") == "source-flow"
    ):
        return parent[-1]
    flow = _tei_element("ab", {"type": "source-flow"})
    parent.append(flow)
    return flow


def _append_expected_blocks(
    source: etree._Element,
    target: etree._Element,
    context: _ExpectedTreeContext,
) -> None:
    if source.text and source.text.strip():
        _expected_flow(target).text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            continue
        tag = str(child.tag).lower()
        if tag in _SKIP:
            if child.tail:
                _append_expected_text(_expected_flow(target), child.tail)
            continue
        if tag in _BLOCK:
            converted = _expected_block(child, context)
            _copy_source_tail(child, converted)
            target.append(converted)
            continue
        converted = _expected_inline(child, context)
        if converted is not None:
            _copy_source_tail(child, converted)
            _expected_flow(target).append(converted)


def _append_expected_container_segments(
    source: etree._Element,
    target: etree._Element,
    context: _ExpectedTreeContext,
) -> None:
    if source.text and source.text.strip():
        wrapper = _tei_element("div", {"type": "source-container-segment"})
        _expected_flow(wrapper).text = source.text
        target.append(wrapper)
    for child in source:
        if not isinstance(child.tag, str):
            continue
        tag = str(child.tag).lower()
        if tag in _SKIP:
            if child.tail:
                wrapper = _tei_element("div", {"type": "source-container-segment"})
                _expected_flow(wrapper).text = child.tail
                target.append(wrapper)
            continue
        wrapper = _tei_element("div", {"type": "source-container-segment"})
        if tag in _BLOCK:
            converted = _expected_block(child, context)
            _copy_source_tail(child, converted)
            wrapper.append(converted)
        else:
            converted = _expected_inline(child, context)
            if converted is not None:
                _copy_source_tail(child, converted)
                _expected_flow(wrapper).append(converted)
        target.append(wrapper)


def _expected_block(
    source: etree._Element, context: _ExpectedTreeContext
) -> etree._Element:
    tag = str(source.tag).lower()
    expected_tag = _TAG_MAP.get(tag)
    if expected_tag is None:
        raise ValueError(
            f"Unaccounted retained HTML block tag <{tag}> in sermon {context.number}"
        )
    target = _tei_element(expected_tag, _expected_tei_attributes(source))
    context.identify(target)
    if tag in {"h1", "h2", "p"}:
        target.text = source.text
        for child in source:
            if not isinstance(child.tag, str):
                continue
            child_tag = str(child.tag).lower()
            converted = (
                _expected_block(child, context)
                if tag == "p" and child_tag in {"ol", "ul"}
                else _expected_inline(child, context)
            )
            if converted is None:
                _append_expected_text(target, child.tail)
                continue
            _copy_source_tail(child, converted)
            target.append(converted)
        return target
    if tag == "blockquote":
        _append_expected_blocks(source, target, context)
        return target
    if tag in {"ol", "ul"}:
        for child in source:
            if not isinstance(child.tag, str) or str(child.tag).lower() != "li":
                raise ValueError(
                    f"Unexpected retained child inside {tag}: {child.tag!r}"
                )
            item = _tei_element("item")
            context.identify(item)
            _append_expected_blocks(child, item, context)
            _copy_source_tail(child, item)
            target.append(item)
        return target
    if tag == "hr":
        return target
    if tag in {"center", "div", "table", "td", "tr"}:
        _append_expected_container_segments(source, target, context)
        return target
    raise ValueError(
        f"Unsupported retained HTML block <{tag}> in sermon {context.number}"
    )


def _strict_tree_signature(node: etree._Element) -> tuple[object, ...]:
    if not isinstance(node.tag, str):
        raise ValueError("Spurgeon candidate contains an unaccounted comment or PI")
    return (
        node.tag,
        tuple(sorted((str(key), str(value)) for key, value in node.attrib.items())),
        node.text,
        node.tail,
        tuple(_strict_tree_signature(child) for child in node),
    )


def _validate_namespace_declarations(content: bytes) -> None:
    element_ordinal = 0

    def start_element(name: str, attributes: dict[str, str]) -> None:
        nonlocal element_ordinal
        element_ordinal += 1
        observed = {
            key: value
            for key, value in attributes.items()
            if key == "xmlns" or key.startswith("xmlns:")
        }
        if element_ordinal == 1:
            expected = {"xmlns": _TEI_NS}
        elif element_ordinal == 2:
            expected = {"xmlns:ns0": _TEI_NS}
        elif name.rsplit(":", 1)[-1] == "div" and attributes.get("type") == "sermon":
            expected = {"xmlns:ns0": _TEI_NS}
        else:
            expected = {}
        if observed != expected:
            raise ValueError(
                "Spurgeon TEI namespace declarations drifted at "
                f"element {element_ordinal}"
            )

    parser = expat.ParserCreate()
    parser.StartElementHandler = start_element
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(content, True)
    except expat.ExpatError as exc:
        raise ValueError("Spurgeon candidate is not safe well-formed XML") from exc


def _validate_xml_declaration(content: bytes) -> None:
    declaration = b"<?xml version='1.0' encoding='UTF-8'?>"
    if not content.startswith(declaration):
        raise ValueError("Spurgeon XML declaration drifted")
    if not content.startswith(declaration + b"\n<TEI") or not content.endswith(b"</TEI>"):
        raise ValueError("Spurgeon TEI lexical shell drifted")


def _expected_sermon_tree(
    source: etree._Element, selection: str, number: int
) -> etree._Element:
    sermon = _tei_element(
        "div",
        {
            "type": "sermon",
            "n": str(number),
            "subtype": selection,
            _XML_ID: f"spurgeon-mtp-{number:04d}",
        },
    )
    context = _ExpectedTreeContext(number)
    if selection == "primary-article":
        _append_expected_blocks(source, sermon, context)
    else:
        _append_expected_container_segments(source, sermon, context)
    return sermon


def _validate_complete_sermon_tree(
    source: etree._Element,
    selection: str,
    candidate: etree._Element,
    number: int,
) -> None:
    expected = _expected_sermon_tree(source, selection, number)
    if _strict_tree_signature(candidate) != _strict_tree_signature(expected):
        raise ValueError(
            f"Spurgeon {number} complete mapped/generated carrier structure drift"
        )


def _validate_document_shell(
    document: etree._ElementTree,
) -> tuple[etree._Element, list[etree._Element]]:
    root = document.getroot()
    if document.docinfo.doctype:
        raise ValueError("Spurgeon TEI document contains an unaccounted doctype")
    if root.getprevious() is not None or root.getnext() is not None:
        raise ValueError("Spurgeon TEI document shell contains an unaccounted node")
    children = list(root)
    if (
        root.tag != f"{{{_TEI_NS}}}TEI"
        or root.attrib
        or root.text is not None
        or root.tail is not None
        or len(children) != 2
        or not all(isinstance(child.tag, str) for child in children)
        or [child.tag for child in children]
        != [f"{{{_TEI_NS}}}teiHeader", f"{{{_TEI_NS}}}text"]
    ):
        raise ValueError("Spurgeon TEI document shell or child order drifted")
    text = children[1]
    text_children = list(text)
    if (
        text.attrib
        or text.text is not None
        or text.tail is not None
        or len(text_children) != 1
        or not isinstance(text_children[0].tag, str)
        or text_children[0].tag != f"{{{_TEI_NS}}}body"
    ):
        raise ValueError("Spurgeon TEI text shell or child order drifted")
    body = text_children[0]
    body_children = list(body)
    if (
        body.attrib
        or body.text is not None
        or body.tail is not None
        or any(
            not isinstance(child.tag, str)
            or child.tag != f"{{{_TEI_NS}}}div"
            or child.get("type") != "sermon"
            for child in body_children
        )
    ):
        raise ValueError("Spurgeon TEI body contains an unaccounted carrier or node")
    return body, body_children


def _source_events(region: etree._Element, number: int) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    identifiers: dict[etree._Element, str] = {}
    index = 0
    for node in region.iterdescendants():
        if not isinstance(node.tag, str):
            continue
        source_tag = node.tag.lower()
        if source_tag in _SKIP:
            continue
        index += 1
        identifier = f"spurgeon-{number:04d}-source-{index:06d}"
        identifiers[node] = identifier
        parent = node.getparent()
        parent_identifier = None
        while parent is not None and parent is not region:
            parent_identifier = identifiers.get(parent)
            if parent_identifier is not None:
                break
            parent = parent.getparent()
        expected_tag = _TAG_MAP.get(source_tag)
        if expected_tag is None:
            raise ValueError(
                f"Unaccounted retained HTML tag <{source_tag}> in sermon {number}"
            )
        if source_tag == "span":
            expected_tag = (
                "ref" if "reference" in (node.get("class") or "").split() else "seg"
            )
        events.append(
            {
                "id": identifier,
                "source_tag": source_tag,
                "tei_tag": expected_tag,
                "parent_id": parent_identifier,
                "text_sha256": _sha(_text(node).encode("utf-8")),
                "tei_attributes": _expected_tei_attributes(node),
            }
        )
    return events


def _candidate_events(sermon: etree._Element, number: int) -> list[dict[str, object]]:
    prefix = f"spurgeon-{number:04d}-source-"
    events: list[dict[str, object]] = []
    for node in sermon.iterdescendants():
        identifier = node.get(_XML_ID)
        if not identifier or not identifier.startswith(prefix):
            continue
        parent = node.getparent()
        parent_identifier = None
        while parent is not None and parent is not sermon:
            value = parent.get(_XML_ID)
            if value and value.startswith(prefix):
                parent_identifier = value
                break
            parent = parent.getparent()
        localname = etree.QName(node).localname
        tei_attributes = {
            etree.QName(key).localname: str(value)
            for key, value in node.attrib.items()
            if key != _XML_ID
        }
        events.append(
            {
                "id": identifier,
                "source_tag": None,
                "tei_tag": localname,
                "parent_id": parent_identifier,
                "text_sha256": _sha(_text(node).encode("utf-8")),
                "tei_attributes": tei_attributes,
            }
        )
    return events


def _validate_generated_candidate_structure(sermon: etree._Element) -> None:
    expected = {
        "div": {"type": "source-container-segment"},
        "ab": {"type": "source-flow"},
    }
    for node in sermon.iterdescendants():
        if node.get(_XML_ID):
            continue
        localname = etree.QName(node).localname
        attributes = {
            etree.QName(key).localname: str(value) for key, value in node.attrib.items()
        }
        if expected.get(localname) != attributes:
            raise ValueError(
                "Spurgeon generated container structure or attribute drift"
            )


def _expected_tei_header(
    policy: Mapping[str, object],
    source_set_sha: str,
    supplemental_rights: Mapping[str, object],
    rights_evidence: Mapping[int, dict[str, object]],
) -> etree._Element:
    header = _tei_element("teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI_NS}}}title").text = str(policy["title"])
    etree.SubElement(title_stmt, f"{{{_TEI_NS}}}author").text = str(policy["author"])
    contributors = policy["contributors"]
    if not isinstance(contributors, list):
        raise ValueError("Spurgeon TEI contributor policy is invalid")
    for contributor in contributors:
        if not isinstance(contributor, Mapping):
            raise ValueError("Spurgeon TEI contributor policy is invalid")
        statement = etree.SubElement(title_stmt, f"{{{_TEI_NS}}}respStmt")
        etree.SubElement(statement, f"{{{_TEI_NS}}}resp").text = str(
            contributor["resp"]
        )
        etree.SubElement(statement, f"{{{_TEI_NS}}}name").text = str(
            contributor["name"]
        )

    publication = etree.SubElement(file_desc, f"{{{_TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI_NS}}}publisher").text = str(
        policy["publisher"]
    )
    availability = etree.SubElement(
        publication,
        f"{{{_TEI_NS}}}availability",
        {"status": str(policy["availability_status"])},
    )
    availability_lines = [
        "Underlying Spurgeon text is public domain; transcription, digitization, and formatting rights remain unresolved. Retained supplemental witnesses 708 and 3032 are a Modernized Edition copyright © 2010 Larry and Marion Pierce; electronic reproduction and derivative works require the copyright owner's express written permission, while only limited non-commercial hard-copy distribution is licensed. Publication is not authorized.",
        *[
            f"Witness {record['sermon_number']} ({record['retained_path']}): {record['source_text']}"
            for record in rights_evidence.values()
        ],
        (
            f"Rights blocker owner: {supplemental_rights['blocker_owner']}. "
            f"Next action: {supplemental_rights['next_action']} "
            f"Reopening condition: {supplemental_rights['reopening_condition']}"
        ),
    ]
    for line in availability_lines:
        etree.SubElement(availability, f"{{{_TEI_NS}}}p").text = str(line)

    source_desc = etree.SubElement(file_desc, f"{{{_TEI_NS}}}sourceDesc")
    bibliography = etree.SubElement(source_desc, f"{{{_TEI_NS}}}bibl")
    etree.SubElement(
        bibliography,
        f"{{{_TEI_NS}}}ptr",
        {"target": str(policy["source_url"])},
    )
    identifier = etree.SubElement(
        bibliography,
        f"{{{_TEI_NS}}}idno",
        {"type": str(policy["source_sha256_type"])},
    )
    identifier.text = source_set_sha
    print_source = etree.SubElement(
        bibliography,
        f"{{{_TEI_NS}}}note",
        {"type": "print-source"},
    )
    print_source.text = str(policy["print_source"])
    for record in rights_evidence.values():
        note = etree.SubElement(
            bibliography,
            f"{{{_TEI_NS}}}note",
            {
                "type": "supplemental-witness-rights",
                "n": str(record["sermon_number"]),
            },
        )
        note.text = (
            f"{record['retained_path']} | {record['selector']} | "
            f"sha256:{record['source_text_sha256']} | {record['source_text']}"
        )
    disposition = etree.SubElement(
        bibliography,
        f"{{{_TEI_NS}}}note",
        {"type": "supplemental-witness-rights-disposition"},
    )
    disposition.text = availability_lines[-1]
    return header


def _validate_tei_header(
    document: etree._ElementTree,
    policy: Mapping[str, object],
    source_set_sha: str,
    supplemental_rights: Mapping[str, object],
    rights_evidence: Mapping[int, dict[str, object]],
) -> None:
    namespace = {"tei": _TEI_NS}
    titles = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title",
        namespaces=namespace,
    )
    authors = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author",
        namespaces=namespace,
    )
    resp_statements = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt",
        namespaces=namespace,
    )
    contributors: list[dict[str, str]] = []
    for statement in resp_statements:
        children = [child for child in statement if isinstance(child.tag, str)]
        if [etree.QName(child).localname for child in children] != ["resp", "name"]:
            raise ValueError("Spurgeon TEI contributor header structure drifted")
        contributors.append({"resp": _text(children[0]), "name": _text(children[1])})
    publishers = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher",
        namespaces=namespace,
    )
    availability = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
        namespaces=namespace,
    )
    pointers = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr",
        namespaces=namespace,
    )
    identifiers = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno",
        namespaces=namespace,
    )
    print_sources = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='print-source']",
        namespaces=namespace,
    )
    observed = {
        "title": [_text(node) for node in titles],
        "author": [_text(node) for node in authors],
        "contributors": contributors,
        "publisher": [_text(node) for node in publishers],
        "availability_status": [node.get("status") for node in availability],
        "source": [
            {"target": node.get("target"), "attributes": dict(node.attrib)}
            for node in pointers
        ],
        "source_sha256": [
            {
                "type": node.get("type"),
                "text": _text(node),
                "attributes": dict(node.attrib),
            }
            for node in identifiers
        ],
        "print_source": [
            {
                "type": node.get("type"),
                "text": _text(node),
                "attributes": dict(node.attrib),
            }
            for node in print_sources
        ],
    }
    expected = {
        "title": [policy["title"]],
        "author": [policy["author"]],
        "contributors": policy["contributors"],
        "publisher": [policy["publisher"]],
        "availability_status": [policy["availability_status"]],
        "source": [
            {
                "target": policy["source_url"],
                "attributes": {"target": policy["source_url"]},
            }
        ],
        "source_sha256": [
            {
                "type": policy["source_sha256_type"],
                "text": source_set_sha,
                "attributes": {"type": policy["source_sha256_type"]},
            }
        ],
        "print_source": [
            {
                "type": "print-source",
                "text": policy["print_source"],
                "attributes": {"type": "print-source"},
            }
        ],
    }
    if observed != expected:
        raise ValueError("Spurgeon TEI core header metadata or source drifted")
    headers = document.xpath("/tei:TEI/tei:teiHeader", namespaces=namespace)
    if len(headers) != 1:
        raise ValueError("Spurgeon TEI complete header structure drifted")
    complete_expected = _expected_tei_header(
        policy, source_set_sha, supplemental_rights, rights_evidence
    )
    if _strict_tree_signature(headers[0]) != _strict_tree_signature(complete_expected):
        raise ValueError("Spurgeon TEI complete header structure drifted")


def _source_set_sha(authorities: tuple[Mapping[str, object], ...]) -> str:
    members = sorted(
        (
            {key: item[key] for key in ("name", "path", "bytes", "sha256")}
            for item in authorities
            if item.get("role") == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": members})
    )


def _fresh_first_party_import_paths(root: Path) -> tuple[str, ...]:
    script = """
import importlib.util
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve(strict=True)
oracle_path = root / "build/tei/spurgeon_mtp_oracle.py"
sys.path.insert(0, str(root))
before = set(sys.modules)
spec = importlib.util.spec_from_file_location("_lib084_oracle_closure_probe", oracle_path)
if spec is None or spec.loader is None:
    raise RuntimeError("oracle closure probe cannot create a module spec")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
paths = set()
for name in set(sys.modules) - before:
    module_path = getattr(sys.modules[name], "__file__", None)
    if module_path is None:
        continue
    path = Path(module_path).resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError:
        continue
    paths.add(relative.as_posix())
print(json.dumps(sorted(paths)))
"""
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(root)],
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(result.stdout)
    except (json.JSONDecodeError, OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Spurgeon first-party import closure probe failed") from exc
    if not isinstance(observed, list) or not all(
        isinstance(value, str) for value in observed
    ):
        raise ValueError("Spurgeon first-party import closure probe drifted")
    return tuple(observed)


def _import_closure(root: Path) -> str:
    resolved_root = root.resolve(strict=True)
    records = []
    for relative in _FIRST_PARTY_IMPORT_PATHS:
        try:
            path = (resolved_root / relative).resolve(strict=True)
            observed_relative = path.relative_to(resolved_root).as_posix()
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Spurgeon first-party import closure member missing or escaped"
            ) from exc
        if observed_relative != relative:
            raise ValueError("Spurgeon first-party import closure path drifted")
        records.append({"path": relative, "sha256": _sha(path.read_bytes())})
    observed = _fresh_first_party_import_paths(resolved_root)
    if observed != _FIRST_PARTY_IMPORT_PATHS:
        raise ValueError(
            "Spurgeon first-party import closure drifted: "
            f"expected {_FIRST_PARTY_IMPORT_PATHS!r}, observed {observed!r}"
        )
    return _sha(_canonical(records))


def _validate_tei_schema(path: Path, schema_path: Path) -> None:
    schema = compiled_tei_schema(schema_path)
    try:
        iterator = etree.iterparse(
            str(path), events=("end",), schema=schema, huge_tree=True
        )
        for _, node in iterator:
            node.clear()
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Spurgeon TEI P5 validation failed: {exc}") from exc


def _validate_tei_schema_document(
    document: etree._ElementTree, schema_path: Path
) -> None:
    schema = compiled_tei_schema(schema_path)
    if not schema.validate(document):
        raise ValueError(
            f"Spurgeon TEI P5 validation failed: {schema.error_log.last_error}"
        )


def _expected_missing_source_blockers() -> list[dict[str, object]]:
    return [
        {
            "id": f"spurgeon-mtp-missing-{number}",
            "kind": "missing-source/source-identity",
            "scope": {"sermon_number": number},
            "status": "blocked",
            "evidence": (
                "No retained primary or supplemental HTML member for this number "
                "in the exact 3,551-member inventory."
            ),
            "routes_attempted": [
                "Kingdom Collective retained primary census",
                "retained supplemental census",
                "retained acquisition request log",
            ],
            "owner": "source-acquisition-maintainer",
            "next_action": (
                "Acquire and identity-check a retained sermon witness for this exact "
                "number."
            ),
            "reopening_condition": (
                "A retained candidate witness is available with exact byte count, "
                "SHA-256, edition identity, and rights evidence."
            ),
        }
        for number in _MISSING
    ]


def _english_list(values: list[str]) -> str:
    if not values:
        raise ValueError("Spurgeon README authority list is empty")
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _expected_readme(
    profile: Mapping[str, object], supplemental_rights: Mapping[str, object]
) -> bytes:
    inventory = profile.get("inventory")
    slots = profile.get("slot_accounting")
    attribution = profile.get("attribution")
    rights = profile.get("rights")
    if (
        not isinstance(inventory, Mapping)
        or not isinstance(slots, Mapping)
        or not isinstance(attribution, list)
        or not attribution
        or not all(isinstance(item, Mapping) for item in attribution)
        or not isinstance(rights, Mapping)
    ):
        raise ValueError("Spurgeon README authorities are invalid")
    supplemental_numbers = slots.get("supplemental_resolutions")
    missing_numbers = slots.get("unresolved_sermon_numbers")
    declared_range = slots.get("declared_range")
    rights_scope = supplemental_rights.get("scope")
    if (
        not isinstance(supplemental_numbers, list)
        or not all(isinstance(value, int) for value in supplemental_numbers)
        or not isinstance(missing_numbers, list)
        or not all(isinstance(value, int) for value in missing_numbers)
        or not isinstance(declared_range, list)
        or len(declared_range) != 2
        or not all(isinstance(value, int) for value in declared_range)
        or not isinstance(rights_scope, Mapping)
    ):
        raise ValueError("Spurgeon README slot or rights scope drifted")
    rights_numbers = rights_scope.get("sermon_numbers")
    if not isinstance(rights_numbers, list) or not all(
        isinstance(value, int) for value in rights_numbers
    ):
        raise ValueError("Spurgeon README rights witness scope drifted")
    edition_label = str(supplemental_rights["edition"]).split(" of ", 1)[0]
    copyright_summary = str(supplemental_rights["copyright"]).replace(
        "Copyright", "copyright", 1
    )
    copyright_summary = copyright_summary.replace(", ", " ", 1)
    resolved = int(slots["resolved_textual_witness_count"])
    primary = int(inventory["primary_html_count"])
    declared_count = declared_range[1] - declared_range[0] + 1
    supplemental_text = _english_list([str(value) for value in supplemental_numbers])
    missing_text = _english_list([str(value) for value in missing_numbers])
    rights_numbers_text = _english_list([str(value) for value in rights_numbers])
    readme = (
        "# Spurgeon MTP complete retained-corpus source notice\n\n"
        "This source contract supports a deterministic, nonaccepted TEI candidate "
        f"for all {resolved:,} retained textual HTML witnesses: {primary:,} Kingdom "
        f"Collective pages and supplemental retained witnesses for sermons "
        f"{supplemental_text}. The retained request log is accounted for as "
        "acquisition evidence and is not copied into the TEI.\n\n"
        f"Thirteen sermon numbers remain localized missing-source/source-identity "
        f"blockers: {missing_text}. This source contract therefore does not claim "
        f"complete resolution of all {declared_count:,} numbered slots.\n\n"
        'Retained primary source wording says the collection was "transcribed from '
        'manuscripts edited by Emmett O\'Donnell" and states "Designed by Benry '
        "Yip.\" OCD therefore records Emmett O'Donnell only as manuscript editor, "
        "with the retained SpurgeonGems link (http://www.spurgeongems.org/), and "
        "Benry Yip only as designer, with the retained Kingdom Collective link "
        "(https://thekingdomcollective.com/spurgeon/). The retained wording does not "
        "identify who performed transcription or digitization; those contributor "
        "roles remain unresolved and are not asserted.\n\n"
        "The underlying Spurgeon text is public domain. Separate transcription, "
        "digitization, and formatting rights remain unresolved. The retained "
        f"supplemental witnesses for sermons {rights_numbers_text} are explicitly "
        f"scoped to a {edition_label} {copyright_summary}. Their retained Terms of "
        "Use prohibit electronic reproduction or distribution without the copyright "
        "owner's express written permission, allow only limited non-commercial "
        "hard-copy printing and distribution without charge while retaining the "
        "copyright notice, and prohibit derivative works without the copyright "
        "owner's express written permission. Exact retained terms: "
        f"{supplemental_rights['exact_source_text']}\n\n"
        f"Blocker owner: {supplemental_rights['blocker_owner']}. Next action: "
        f"{supplemental_rights['next_action']} Reopening condition: "
        f"{supplemental_rights['reopening_condition']}\n\n"
        "Technical validation is not human acceptance, rights clearance, or "
        "publication authorization; candidate status remains nonaccepted and "
        "publication status remains "
        f"{rights['publication_status']}.\n"
    )
    return readme.encode("utf-8")


def _source_facts_digest(
    *,
    source_manifest_sha256: str,
    oracle_implementation_sha256: str,
    import_closure_sha256: str,
    profile_sha256: str,
    package_schema_sha256: str,
    xsd_sha256: str,
    policy_sha256: str,
    source_set_sha256: str,
    authorities: Sequence[Mapping[str, object]],
    profile: Mapping[str, object],
    work_identity_config: Mapping[str, object],
    supplemental_rights: Mapping[str, object],
    rights_evidence: Mapping[int, Mapping[str, object]],
    source_readme: bytes,
    request_log: Mapping[str, object],
    sermon_facts: Sequence[_SermonFact],
) -> str:
    return _sha(
        _canonical(
            {
                "source_manifest_sha256": source_manifest_sha256,
                "oracle_implementation_sha256": oracle_implementation_sha256,
                "import_closure_sha256": import_closure_sha256,
                "profile_sha256": profile_sha256,
                "package_schema_sha256": package_schema_sha256,
                "xsd_sha256": xsd_sha256,
                "policy_sha256": policy_sha256,
                "source_set_sha256": source_set_sha256,
                "authorities": _deep_thaw(authorities),
                "profile": _deep_thaw(profile),
                "work_identity_config": _deep_thaw(work_identity_config),
                "supplemental_rights": _deep_thaw(supplemental_rights),
                "rights_evidence": _deep_thaw(rights_evidence),
                "source_readme": {
                    "bytes": len(source_readme),
                    "sha256": _sha(source_readme),
                },
                "request_log": _deep_thaw(request_log),
                "sermons": [
                    {
                        "number": fact.number,
                        "authority": _deep_thaw(fact.authority),
                        "selection": fact.selection,
                        "source_tree_sha256": fact.source_tree_sha256,
                        "source_event_tags": fact.source_event_tags,
                        "source_events_sha256": fact.source_events_sha256,
                        "normalized_text_sha256": fact.normalized_text_sha256,
                        "expected_accountability": _deep_thaw(
                            fact.expected_accountability
                        ),
                    }
                    for fact in sermon_facts
                ],
            }
        )
    )


def _derive_source_facts(source_manifest: SourceManifest) -> _SourceFacts:
    """Read the complete retained boundary once into immutable source expectations."""

    source_manifest.verify()
    root = source_manifest.repository_root
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Spurgeon manifest authorities are invalid")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = _json(profile_bytes, "Spurgeon profile")
    work_identity_config = _validate_work_identity_config(source_manifest, profile)
    inventory_bytes = source_manifest.authority_path("retained-member-inventory").read_bytes()
    inventory = profile.get("inventory")
    if not isinstance(inventory, dict) or (
        inventory.get("bytes") != len(inventory_bytes)
        or inventory.get("sha256") != _sha(inventory_bytes)
        or inventory.get("member_count") != 3551
        or inventory.get("total_bytes") != 143873038
    ):
        raise ValueError("Spurgeon retained inventory binding drifted")
    lines = inventory_bytes.decode("utf-8").splitlines()
    if not lines or lines[0] != "logical_path\tbyte_count\tsha256" or len(lines) != 3552:
        raise ValueError("Spurgeon retained inventory shape drifted")
    inventory_rows = [line.split("\t") for line in lines[1:]]
    if any(len(row) != 3 for row in inventory_rows):
        raise ValueError("Spurgeon retained inventory row drifted")
    inventory_map = {row[0]: (int(row[1]), row[2]) for row in inventory_rows}
    if len(inventory_map) != 3551 or sum(value[0] for value in inventory_map.values()) != 143873038:
        raise ValueError("Spurgeon retained inventory coverage drifted")

    textual = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    textual.sort(key=lambda item: _number(source_manifest.authority_path(str(item["name"]))))
    numbers = [_number(source_manifest.authority_path(str(item["name"]))) for item in textual]
    if len(textual) != 3550 or len(set(numbers)) != 3550 or sorted(set(range(1, 3564)) - set(numbers)) != list(_MISSING):
        raise ValueError("Spurgeon textual witness or missing-slot accounting drifted")
    rights_evidence = {
        number: _retained_rights_evidence(
            source_manifest.authority_path(f"sermon-{number:04d}"), number
        )
        for number in _SUPPLEMENTAL_RIGHTS_NUMBERS
    }
    supplemental_rights = _validate_profile_policy(profile, rights_evidence)
    _validate_primary_attribution_evidence(source_manifest, textual)
    source_readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    if source_readme != _expected_readme(profile, supplemental_rights):
        raise ValueError("Spurgeon durable source attribution README drifted")
    for item in textual:
        path = str(item["path"])
        if inventory_map.get(path) != (item["bytes"], item["sha256"]):
            raise ValueError(f"Spurgeon inventory/manifest mismatch for {path}")
    request_log = next(
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("name") == "request-log"
    )
    if inventory_map.get(str(request_log["path"])) != (request_log["bytes"], request_log["sha256"]):
        raise ValueError("Spurgeon request-log accounting drifted")

    sermon_facts: list[_SermonFact] = []
    for item, number in zip(textual, numbers, strict=True):
        region, selection = _evidence_region(
            source_manifest.authority_path(str(item["name"])), number
        )
        source_events = _source_events(region, number)
        normalized = _text(region)
        expected_record: dict[str, object] = {
            "number": number,
            "logical_name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "role": "textual-witness",
            "disposition": "represented",
            "selection": selection,
            "tei_xml_id": f"spurgeon-mtp-{number:04d}",
            "normalized_text_sha256": _sha(normalized.encode("utf-8")),
            "mapped_element_count": len(source_events),
            "mapped_structure_sha256": _sha(_canonical(source_events)),
        }
        if number in rights_evidence:
            expected_record["witness_rights"] = rights_evidence[number]
        expected_tree = _expected_sermon_tree(region, selection, number)
        sermon_facts.append(
            _SermonFact(
                number=number,
                authority=_deep_freeze(item),
                selection=selection,
                source_tree_sha256=_sha(_canonical(_strict_tree_signature(expected_tree))),
                source_event_tags=tuple(str(record["source_tag"]) for record in source_events),
                source_events_sha256=_sha(_canonical(source_events)),
                normalized_text_sha256=_sha(normalized.encode("utf-8")),
                expected_accountability=_deep_freeze(expected_record),
            )
        )

    frozen_authorities = tuple(_deep_freeze(item) for item in authorities)
    frozen_profile = _deep_freeze(profile)
    frozen_work_identity_config = _deep_freeze(work_identity_config)
    frozen_supplemental_rights = _deep_freeze(supplemental_rights)
    frozen_rights_evidence = _deep_freeze(rights_evidence)
    frozen_request_log = _deep_freeze(request_log)
    if not all(
        isinstance(value, Mapping)
        for value in (
            frozen_profile,
            frozen_work_identity_config,
            frozen_supplemental_rights,
            frozen_rights_evidence,
            frozen_request_log,
        )
    ) or not all(isinstance(item, Mapping) for item in frozen_authorities):
        raise TypeError("Spurgeon source facts did not freeze as mappings")
    profile_sha = _sha(profile_bytes)
    package_schema_sha = _sha(source_manifest.authority_path("candidate-package-schema").read_bytes())
    xsd_sha = _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes())
    implementation_sha = _sha(Path(__file__).read_bytes())
    closure_sha = _import_closure(root)
    source_set_sha = _source_set_sha(authorities)
    facts_digest = _source_facts_digest(
        source_manifest_sha256=source_manifest.sha256,
        oracle_implementation_sha256=implementation_sha,
        import_closure_sha256=closure_sha,
        profile_sha256=profile_sha,
        package_schema_sha256=package_schema_sha,
        xsd_sha256=xsd_sha,
        policy_sha256=profile_sha,
        source_set_sha256=source_set_sha,
        authorities=frozen_authorities,
        profile=frozen_profile,
        work_identity_config=frozen_work_identity_config,
        supplemental_rights=frozen_supplemental_rights,
        rights_evidence=frozen_rights_evidence,
        source_readme=source_readme,
        request_log=frozen_request_log,
        sermon_facts=sermon_facts,
    )
    return _SourceFacts(
        source_manifest_sha256=source_manifest.sha256,
        oracle_implementation_sha256=implementation_sha,
        import_closure_sha256=closure_sha,
        authorities=frozen_authorities,
        profile=frozen_profile,
        profile_sha256=profile_sha,
        package_schema_sha256=package_schema_sha,
        xsd_sha256=xsd_sha,
        policy_sha256=profile_sha,
        source_set_sha256=source_set_sha,
        work_identity_config=frozen_work_identity_config,
        supplemental_rights=frozen_supplemental_rights,
        rights_evidence=frozen_rights_evidence,
        source_readme=source_readme,
        request_log=frozen_request_log,
        sermon_facts=tuple(sermon_facts),
        facts_sha256=facts_digest,
    )


def _require_current_source_facts(
    source_manifest: SourceManifest, facts: _SourceFacts
) -> None:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Spurgeon manifest authorities are invalid")
    observed_digest = _source_facts_digest(
        source_manifest_sha256=facts.source_manifest_sha256,
        oracle_implementation_sha256=facts.oracle_implementation_sha256,
        import_closure_sha256=facts.import_closure_sha256,
        profile_sha256=facts.profile_sha256,
        package_schema_sha256=facts.package_schema_sha256,
        xsd_sha256=facts.xsd_sha256,
        policy_sha256=facts.policy_sha256,
        source_set_sha256=facts.source_set_sha256,
        authorities=facts.authorities,
        profile=facts.profile,
        work_identity_config=facts.work_identity_config,
        supplemental_rights=facts.supplemental_rights,
        rights_evidence=facts.rights_evidence,
        source_readme=facts.source_readme,
        request_log=facts.request_log,
        sermon_facts=facts.sermon_facts,
    )
    if (
        facts.facts_sha256 != observed_digest
        or facts.source_manifest_sha256 != source_manifest.sha256
        or _deep_thaw(facts.authorities) != _deep_thaw(authorities)
        or facts.oracle_implementation_sha256 != _sha(Path(__file__).read_bytes())
        or facts.import_closure_sha256 != _import_closure(source_manifest.repository_root)
        or facts.source_set_sha256 != _source_set_sha(authorities)
        or len(facts.sermon_facts) != 3550
        or tuple(fact.number for fact in facts.sermon_facts)
        != tuple(number for number in range(1, 3564) if number not in _MISSING)
    ):
        raise ValueError("Spurgeon source facts are stale or internally inconsistent")


def _validate_candidate_envelope(
    source_manifest: SourceManifest,
    facts: _SourceFacts,
    snapshot: _CandidateSnapshot,
) -> None:
    root = source_manifest.repository_root
    expected_manifest_path = source_manifest.path.relative_to(root).as_posix()
    manifest = snapshot.manifest
    if (
        manifest.get("status") != "nonaccepted"
        or manifest.get("source_manifest")
        != {"path": expected_manifest_path, "sha256": source_manifest.sha256}
        or manifest.get("converter") != source_manifest.record.get("converter")
        or manifest.get("package_schema") != source_manifest.record.get("package_schema")
    ):
        raise ValueError("Spurgeon candidate authority binding drifted")
    package_schema_bytes = source_manifest.authority_path("candidate-package-schema").read_bytes()
    if _sha(package_schema_bytes) != facts.package_schema_sha256:
        raise ValueError("Spurgeon candidate package schema facts drifted")
    errors = sorted(
        Draft202012Validator(_json(package_schema_bytes, "candidate package schema")).iter_errors(manifest),
        key=str,
    )
    if errors:
        raise ValueError(f"Spurgeon candidate package schema failed: {errors[0].message}")


def _parse_candidate_document(
    source_manifest: SourceManifest,
    facts: _SourceFacts,
    snapshot: _CandidateSnapshot,
) -> tuple[etree._ElementTree, list[etree._Element]]:
    content = snapshot.member_bytes("content.tei.xml")
    _validate_xml_declaration(content)
    _validate_namespace_declarations(content)
    try:
        document = etree.parse(
            BytesIO(content),
            etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("Spurgeon candidate is not safe well-formed XML") from exc
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    if _sha(xsd_path.read_bytes()) != facts.xsd_sha256:
        raise ValueError("Spurgeon TEI schema facts drifted")
    _validate_tei_schema_document(document, xsd_path)
    _, sermons = _validate_document_shell(document)
    return document, sermons


def _validate_candidate_header(
    facts: _SourceFacts, document: etree._ElementTree
) -> None:
    profile = _deep_thaw(facts.profile)
    supplemental_rights = _deep_thaw(facts.supplemental_rights)
    rights_evidence = _deep_thaw(facts.rights_evidence)
    if not all(
        isinstance(value, dict)
        for value in (profile, supplemental_rights, rights_evidence)
    ):
        raise ValueError("Spurgeon frozen header facts are invalid")
    header_policy = profile.get("tei_header_policy")
    if not isinstance(header_policy, Mapping):
        raise ValueError("Spurgeon TEI header policy is missing")
    _validate_tei_header(
        document,
        header_policy,
        facts.source_set_sha256,
        supplemental_rights,
        rights_evidence,
    )
    namespace = {"tei": _TEI_NS}
    expected_availability = [
        "Underlying Spurgeon text is public domain; transcription, digitization, and formatting rights remain unresolved. Retained supplemental witnesses 708 and 3032 are a Modernized Edition copyright © 2010 Larry and Marion Pierce; electronic reproduction and derivative works require the copyright owner's express written permission, while only limited non-commercial hard-copy distribution is licensed. Publication is not authorized.",
        *[
            f"Witness {record['sermon_number']} ({record['retained_path']}): {record['source_text']}"
            for record in rights_evidence.values()
        ],
        (
            f"Rights blocker owner: {supplemental_rights['blocker_owner']}. "
            f"Next action: {supplemental_rights['next_action']} "
            f"Reopening condition: {supplemental_rights['reopening_condition']}"
        ),
    ]
    availability = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p",
        namespaces=namespace,
    )
    if [_text(node) for node in availability] != expected_availability:
        raise ValueError("Spurgeon TEI availability rights drifted")
    source_notes = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='supplemental-witness-rights']",
        namespaces=namespace,
    )
    expected_notes = [
        (
            str(record["sermon_number"]),
            f"{record['retained_path']} | {record['selector']} | sha256:{record['source_text_sha256']} | {record['source_text']}",
        )
        for record in rights_evidence.values()
    ]
    if [(node.get("n"), _text(node)) for node in source_notes] != expected_notes:
        raise ValueError("Spurgeon TEI source-description rights drifted")
    disposition_notes = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='supplemental-witness-rights-disposition']",
        namespaces=namespace,
    )
    if len(disposition_notes) != 1 or _text(disposition_notes[0]) != expected_availability[-1]:
        raise ValueError("Spurgeon TEI rights disposition drifted")


def _validate_candidate_auxiliary(
    source_manifest: SourceManifest,
    facts: _SourceFacts,
    snapshot: _CandidateSnapshot,
) -> None:
    profile = _deep_thaw(facts.profile)
    work_identity_config = _deep_thaw(facts.work_identity_config)
    supplemental_rights = _deep_thaw(facts.supplemental_rights)
    rights_evidence = _deep_thaw(facts.rights_evidence)
    request_log = _deep_thaw(facts.request_log)
    if not all(
        isinstance(value, dict)
        for value in (
            profile,
            work_identity_config,
            supplemental_rights,
            rights_evidence,
            request_log,
        )
    ):
        raise ValueError("Spurgeon frozen auxiliary facts are invalid")
    accountability = _json(snapshot.member_bytes("source-accountability.json"), "Spurgeon accountability")
    observed_members = accountability.get("members")
    if not isinstance(observed_members, list) or len(observed_members) != 3551:
        raise ValueError("Spurgeon accountability member count drifted")
    observed_by_number = {
        item.get("number"): item
        for item in observed_members
        if isinstance(item, dict) and isinstance(item.get("number"), int)
    }
    expected_by_number = {
        fact.number: _deep_thaw(fact.expected_accountability)
        for fact in facts.sermon_facts
    }
    if observed_by_number != expected_by_number:
        raise ValueError("Spurgeon textual accountability identities or facts drifted")
    excluded = [
        item
        for item in observed_members
        if isinstance(item, dict) and item.get("disposition") == "excluded-from-tei"
    ]
    expected_excluded = {
        "logical_name": "request-log",
        "path": request_log["path"],
        "bytes": request_log["bytes"],
        "sha256": request_log["sha256"],
        "role": "acquisition-evidence",
        "disposition": "excluded-from-tei",
        "reason": "Request history is retained acquisition evidence, not sermon text.",
    }
    summary_keys = (
        "contract", "profile_id", "retained_member_count", "retained_member_bytes",
        "textual_witness_count", "primary_html_count", "supplemental_html_count",
        "represented_textual_witness_count", "excluded_evidence_count",
        "omitted_retained_member_count", "duplicate_retained_member_count",
        "declared_sermon_slot_count", "resolved_sermon_slot_count",
        "unresolved_sermon_slot_count", "claims_complete_retained_member_coverage",
        "claims_complete_3563_slot_resolution",
    )
    expected_summary = {
        "contract": "ocd-spurgeon-mtp-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "retained_member_count": 3551,
        "retained_member_bytes": 143873038,
        "textual_witness_count": 3550,
        "primary_html_count": 3547,
        "supplemental_html_count": 3,
        "represented_textual_witness_count": 3550,
        "excluded_evidence_count": 1,
        "omitted_retained_member_count": 0,
        "duplicate_retained_member_count": 0,
        "declared_sermon_slot_count": 3563,
        "resolved_sermon_slot_count": 3550,
        "unresolved_sermon_slot_count": 13,
        "claims_complete_retained_member_coverage": True,
        "claims_complete_3563_slot_resolution": False,
    }
    if {key: accountability.get(key) for key in summary_keys} != expected_summary or excluded != [expected_excluded]:
        raise ValueError("Spurgeon complete retained-member accounting drifted")
    expected_rights_accountability = {
        "scope": supplemental_rights["scope"],
        "rights_owners": supplemental_rights["rights_owners"],
        "terms": supplemental_rights["terms"],
        "blocker_owner": supplemental_rights["blocker_owner"],
        "next_action": supplemental_rights["next_action"],
        "reopening_condition": supplemental_rights["reopening_condition"],
        "retained_evidence": list(rights_evidence.values()),
    }
    if accountability.get("supplemental_witness_rights") != expected_rights_accountability:
        raise ValueError("Spurgeon supplemental rights accountability drifted")

    provenance = _json(snapshot.member_bytes("provenance.json"), "Spurgeon provenance")
    expected_provenance = {
        "contract": "ocd-spurgeon-mtp-candidate-provenance-v1",
        "status": "nonaccepted",
        "publication_status": "not-ready",
        "publication_authorized": False,
        "source_manifest_sha256": source_manifest.sha256,
        "source_member_set_sha256": facts.source_set_sha256,
        "profile_sha256": facts.profile_sha256,
        "work_identity": profile["work_identity"],
        "work_identity_config": work_identity_config,
        "attribution": profile["attribution"],
        "attribution_evidence": profile["attribution_evidence"],
        "rights": profile["rights"],
        "retained_source_bytes_embedded": False,
    }
    if provenance != expected_provenance:
        raise ValueError("Spurgeon metadata, rights, source, or status provenance drifted")
    unresolved = [
        _json(line, f"Spurgeon unresolved record {index}")
        for index, line in enumerate(snapshot.member_bytes("unresolved.jsonl").splitlines(), start=1)
        if line
    ]
    if unresolved[:13] != _expected_missing_source_blockers():
        raise ValueError("Spurgeon missing-source unresolved evidence drifted")
    if len(unresolved) < 14 or unresolved[13] != _ATTRIBUTION_UNRESOLVED:
        raise ValueError("Spurgeon contributor responsibility evidence drifted")
    expected_rights_unresolved = {
        "id": "spurgeon-mtp-rights",
        "kind": "rights",
        "scope": supplemental_rights["scope"],
        "status": "human-decision-required",
        "rights_owners": supplemental_rights["rights_owners"],
        "terms": supplemental_rights["terms"],
        "retained_evidence": list(rights_evidence.values()),
        "evidence": supplemental_rights["exact_source_text"],
        "owner": supplemental_rights["blocker_owner"],
        "next_action": supplemental_rights["next_action"],
        "reopening_condition": supplemental_rights["reopening_condition"],
    }
    if len(unresolved) != 15 or unresolved[-1] != expected_rights_unresolved:
        raise ValueError("Spurgeon rights question or unresolved evidence drifted")
    if snapshot.member_bytes("README.source.md") != facts.source_readme:
        raise ValueError("Spurgeon source attribution or review README drifted")


def _validate_candidate_sermons(
    facts: _SourceFacts, sermons: Sequence[etree._Element]
) -> None:
    if len(sermons) != len(facts.sermon_facts):
        raise ValueError("Spurgeon candidate sermon omission or duplication")
    for sermon, fact in zip(sermons, facts.sermon_facts, strict=True):
        try:
            number = int(str(sermon.get("n")))
        except ValueError as exc:
            raise ValueError("Spurgeon candidate sermon number is invalid") from exc
        if number != fact.number:
            raise ValueError("Spurgeon candidate sermon omission, duplication, or reorder")
        expected_attributes = {
            _XML_ID: f"spurgeon-mtp-{number:04d}",
            "type": "sermon",
            "n": str(number),
            "subtype": fact.selection,
        }
        if sermon.attrib != expected_attributes:
            raise ValueError(f"Spurgeon candidate sermon attribute drifted for {number}")
        _validate_generated_candidate_structure(sermon)
        if _sha(_canonical(_strict_tree_signature(sermon))) != fact.source_tree_sha256:
            raise ValueError(f"Spurgeon {number} complete mapped/generated carrier structure drift")
        candidate_events = _candidate_events(sermon, number)
        if len(candidate_events) != len(fact.source_event_tags):
            raise ValueError(f"Spurgeon {number} structure, nesting, inline carrier, or text drift")
        projection = [
            {**record, "source_tag": fact.source_event_tags[index]}
            for index, record in enumerate(candidate_events)
        ]
        if _sha(_canonical(projection)) != fact.source_events_sha256:
            raise ValueError(f"Spurgeon {number} structure, nesting, inline carrier, or text drift")
        if _sha(_text(sermon).encode("utf-8")) != fact.normalized_text_sha256:
            raise ValueError(f"Spurgeon {number} wording or order drift")


def _build_attestation(
    source_manifest: SourceManifest,
    facts: _SourceFacts,
    snapshot: _CandidateSnapshot,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": facts.oracle_implementation_sha256,
        "import_closure_sha256": facts.import_closure_sha256,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": snapshot.candidate_sha256,
        "profile_sha256": facts.profile_sha256,
        "package_schema_sha256": facts.package_schema_sha256,
        "source_sha256": facts.source_set_sha256,
        "xsd_sha256": facts.xsd_sha256,
        "policy_sha256": facts.policy_sha256,
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


def _validate_with_source_facts(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    facts: _SourceFacts,
) -> dict[str, object]:
    _require_current_source_facts(source_manifest, facts)
    snapshot = _snapshot_candidate(candidate)
    _validate_candidate_envelope(source_manifest, facts, snapshot)
    document, sermons = _parse_candidate_document(source_manifest, facts, snapshot)
    _validate_candidate_header(facts, document)
    _validate_candidate_auxiliary(source_manifest, facts, snapshot)
    _validate_candidate_sermons(facts, sermons)
    return _build_attestation(source_manifest, facts, snapshot)


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    facts = _derive_source_facts(source_manifest)
    return _validate_with_source_facts(source_manifest, candidate, facts)


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
