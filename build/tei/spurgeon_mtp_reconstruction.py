"""Complete retained Spurgeon MTP HTML corpus to one nonaccepted TEI candidate."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-spurgeon-mtp-complete-retained-html-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "spurgeon-mtp-complete-retained-corpus-v1"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_MISSING = (8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, 390)
_SUPPLEMENTAL_RIGHTS_NUMBERS = (708, 3032)
_BLOCK_TAGS = frozenset(
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
_IGNORED_TAGS = frozenset({"img", "script", "style"})

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


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_work_identity_config(
    source_manifest: SourceManifest, profile: Mapping[str, object]
) -> dict[str, object]:
    path = source_manifest.authority_path("work-identity-config")
    content = path.read_bytes()
    config = _strict_json(content, "Spurgeon work-identity config")
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


def _normalized_text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _sermon_number(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError as exc:
        raise ValueError(
            f"Spurgeon textual authority is not numeric: {path.name}"
        ) from exc


def _selected_source(path: Path, number: int) -> tuple[etree._Element, str]:
    document = html.document_fromstring(path.read_bytes())
    if path.parent.name == "html":
        articles = document.xpath(
            '//article[contains(concat(" ", normalize-space(@class), " "), " sermon ")]'
        )
        if len(articles) != 1:
            raise ValueError(
                f"Expected one sermon article in {path}, found {len(articles)}"
            )
        return articles[0], "primary-article"

    wrapper = etree.Element("section")
    if number in {708, 3032}:
        body = document.xpath(
            '//div[contains(concat(" ", normalize-space(@class), " "), " bd-ctBody ")]'
        )
        if len(body) != 1:
            raise ValueError(f"Expected one supplemental content body in {path}")
        selectors = (
            './h1[contains(concat(" ", normalize-space(@class), " "), " name ")]',
            './div[contains(concat(" ", normalize-space(@class), " "), " published-info ")]',
            './p[contains(concat(" ", normalize-space(@class), " "), " intro ")]',
            './div[contains(concat(" ", normalize-space(@class), " "), " node-body ")]',
        )
        for selector in selectors:
            matches = body[0].xpath(selector)
            if len(matches) != 1:
                raise ValueError(
                    f"Supplemental selector {selector!r} is not unique in {path}"
                )
            wrapper.append(deepcopy(matches[0]))
        return wrapper, "supplemental-aig-sermon-content"

    if number != 1698:
        raise ValueError(f"Unexpected supplemental Spurgeon number {number}")
    headings = document.xpath("//h1")
    if len(headings) != 1:
        raise ValueError("Supplemental sermon 1698 must contain exactly one h1")
    cell = next(
        (item for item in headings[0].iterancestors() if item.tag == "td"), None
    )
    if cell is None:
        raise ValueError("Supplemental sermon 1698 has no sermon-bearing table cell")
    children = [item for item in cell if isinstance(item.tag, str)]
    start = next(
        (
            index
            for index, item in enumerate(children)
            if item.tag == "center" and item.xpath(".//h1")
        ),
        None,
    )
    footer = next(
        (
            index
            for index, item in enumerate(children)
            if start is not None
            and index > start
            and item.tag == "p"
            and "Collection administered by" in _normalized_text(item)
        ),
        None,
    )
    if (
        start is None
        or footer is None
        or footer < 2
        or children[footer - 1].tag != "hr"
    ):
        raise ValueError("Supplemental sermon 1698 boundaries are no longer exact")
    for item in children[start:footer]:
        wrapper.append(deepcopy(item))
    return wrapper, "supplemental-spurgeon-archive-sermon-content"


def _supplemental_rights_evidence(path: Path, number: int) -> dict[str, object]:
    if number not in _SUPPLEMENTAL_RIGHTS_NUMBERS:
        raise ValueError(
            f"Sermon {number} has no declared supplemental rights evidence"
        )
    document = html.document_fromstring(path.read_bytes())
    outros = [
        node
        for node in document.xpath("//div")
        if node.get("id") == "ipaNodeOutro"
        and "outro" in (node.get("class") or "").split()
    ]
    if len(outros) != 1:
        raise ValueError(f"Expected one supplemental rights outro in {path}")
    headings = [
        node
        for node in outros[0]
        if isinstance(node.tag, str)
        and node.tag.lower() == "h2"
        and _normalized_text(node) == "Terms of Use"
    ]
    if len(headings) != 1:
        raise ValueError(f"Expected one Terms of Use heading in {path}")
    terms = headings[0].getnext()
    if terms is None or not isinstance(terms.tag, str) or terms.tag.lower() != "p":
        raise ValueError(f"Expected a Terms of Use paragraph in {path}")
    text = _normalized_text(terms)
    required_phrases = (
        "Modernized Edition of Spurgeon’s Sermons.",
        "Copyright © 2010, Larry and Marion Pierce, Winterbourne, Ontario, Canada.",
        "may not be reproduced or distributed by any electronic means without express written permission of the copyright owner",
        "A limited license is hereby granted for the non-commercial printing and distribution of the material in hard copy form",
        "You may not prepare, manufacture, copy, use, promote, distribute, or sell a derivative work",
    )
    if any(phrase not in text for phrase in required_phrases):
        raise ValueError(f"Supplemental rights wording drifted in {path}")
    return {
        "sermon_number": number,
        "retained_path": "/".join(path.parts[-4:]),
        "selector": "div#ipaNodeOutro.outro > h2[Terms of Use] + p",
        "source_text": text,
        "source_text_sha256": _sha(text.encode("utf-8")),
    }


def _validate_profile(profile: Mapping[str, object]) -> dict[str, object]:
    structure = profile.get("structure_policy")
    rights = profile.get("rights")
    if not isinstance(structure, Mapping) or not isinstance(rights, dict):
        raise ValueError("Spurgeon structure or rights profile is invalid")
    mapping = structure.get("tei_mapping")
    attributes = structure.get("attribute_mapping")
    if not isinstance(mapping, Mapping) or mapping.get("font") != "seg":
        raise ValueError("Spurgeon profile must map inline font to TEI seg")
    if attributes != {
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
        raise ValueError("Spurgeon supplemental witness rights profile is missing")
    if supplemental.get("scope") != {
        "sermon_numbers": [708, 3032],
        "retained_paths": [
            "raw/spurgeon_sermons/missing/708.html",
            "raw/spurgeon_sermons/missing/3032.html",
        ],
    }:
        raise ValueError("Spurgeon supplemental rights scope drifted")
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
        normalized = _normalized_text(page)
        if any(value not in normalized for value in wording):
            raise ValueError(f"Spurgeon retained attribution wording drifted in {path}")


class _Context:
    def __init__(self, number: int) -> None:
        self.number = number
        self.index = 0
        self.events: list[dict[str, object]] = []

    def identity(self, source: etree._Element, target: etree._Element) -> None:
        self.index += 1
        identifier = f"spurgeon-{self.number:04d}-source-{self.index:06d}"
        target.set("{http://www.w3.org/XML/1998/namespace}id", identifier)
        parent = source.getparent()
        parent_id = None
        while parent is not None:
            value = parent.get("_ocd_source_id")
            if value:
                parent_id = value
                break
            parent = parent.getparent()
        source.set("_ocd_source_id", identifier)
        source_tag = str(source.tag).lower()
        tei_attributes = {
            etree.QName(key).localname: str(value)
            for key, value in target.attrib.items()
            if key != "{http://www.w3.org/XML/1998/namespace}id"
        }
        self.events.append(
            {
                "id": identifier,
                "source_tag": source_tag,
                "tei_tag": etree.QName(target).localname,
                "parent_id": parent_id,
                "text_sha256": _sha(_normalized_text(source).encode("utf-8")),
                "tei_attributes": tei_attributes,
            }
        )


def _copy_tail(source: etree._Element, target: etree._Element) -> None:
    if source.tail:
        target.tail = source.tail


def _append_unwrapped_text(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _inline(source: etree._Element, context: _Context) -> etree._Element | None:
    tag = str(source.tag).lower()
    if tag in _IGNORED_TAGS:
        return None
    if tag == "br":
        target = tei_el("lb")
    elif tag in {"em", "i"}:
        target = tei_el("hi", {"rend": "italic"})
    elif tag in {"strong", "b"}:
        target = tei_el("hi", {"rend": "bold"})
    elif tag == "small":
        target = tei_el("hi", {"rend": "small"})
    elif tag == "code":
        target = tei_el("seg", {"type": "source-code"})
    elif tag == "a":
        attrs = {"type": "source-link"}
        if source.get("href") is not None:
            attrs["target"] = str(source.get("href"))
        target = tei_el("ref", attrs)
    elif tag == "span" and "reference" in (source.get("class") or "").split():
        target = tei_el("ref", {"type": "scripture"})
    elif tag in {"font", "span"}:
        attrs = {"type": f"source-{tag}"}
        if tag == "font" and source.get("size") is not None:
            attrs["rend"] = str(source.get("size"))
        target = tei_el("seg", attrs)
    else:
        target = tei_el("seg", {"type": f"source-{tag}"})
    context.identity(source, target)
    target.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            continue
        converted = _inline(child, context)
        if converted is None:
            if child.tail:
                if len(target):
                    target[-1].tail = (target[-1].tail or "") + child.tail
                else:
                    target.text = (target.text or "") + child.tail
            continue
        _copy_tail(child, converted)
        target.append(converted)
    return target


def _flow(parent: etree._Element) -> etree._Element:
    if (
        len(parent)
        and etree.QName(parent[-1]).localname == "ab"
        and parent[-1].get("type") == "source-flow"
    ):
        return parent[-1]
    value = tei_el("ab", {"type": "source-flow"})
    parent.append(value)
    return value


def _append_blocks(
    source: etree._Element, target: etree._Element, context: _Context
) -> None:
    if source.text and source.text.strip():
        _flow(target).text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            continue
        tag = str(child.tag).lower()
        if tag in _IGNORED_TAGS:
            if child.tail:
                flow = _flow(target)
                if len(flow):
                    flow[-1].tail = (flow[-1].tail or "") + child.tail
                else:
                    flow.text = (flow.text or "") + child.tail
            continue
        if tag in _BLOCK_TAGS:
            converted = _block(child, context)
            _copy_tail(child, converted)
            target.append(converted)
        else:
            flow = _flow(target)
            converted = _inline(child, context)
            if converted is not None:
                _copy_tail(child, converted)
                flow.append(converted)


def _append_container_segments(
    source: etree._Element, target: etree._Element, context: _Context
) -> None:
    """Keep mixed legacy HTML flows valid by placing each run in its own TEI div."""

    if source.text and source.text.strip():
        wrapper = tei_el("div", {"type": "source-container-segment"})
        _flow(wrapper).text = source.text
        target.append(wrapper)
    for child in source:
        if not isinstance(child.tag, str):
            continue
        tag = str(child.tag).lower()
        if tag in _IGNORED_TAGS:
            if child.tail:
                wrapper = tei_el("div", {"type": "source-container-segment"})
                _flow(wrapper).text = child.tail
                target.append(wrapper)
            continue
        wrapper = tei_el("div", {"type": "source-container-segment"})
        if tag in _BLOCK_TAGS:
            converted = _block(child, context)
            _copy_tail(child, converted)
            wrapper.append(converted)
        else:
            converted = _inline(child, context)
            if converted is not None:
                _copy_tail(child, converted)
                _flow(wrapper).append(converted)
        target.append(wrapper)


def _block(source: etree._Element, context: _Context) -> etree._Element:
    tag = str(source.tag).lower()
    if tag in {"h1", "h2"}:
        target = tei_el("head")
        context.identity(source, target)
        target.text = source.text
        for child in source:
            if isinstance(child.tag, str):
                converted = _inline(child, context)
                if converted is not None:
                    _copy_tail(child, converted)
                    target.append(converted)
                else:
                    _append_unwrapped_text(target, child.tail)
        return target
    if tag == "p":
        target = tei_el("p")
        context.identity(source, target)
        target.text = source.text
        for child in source:
            if not isinstance(child.tag, str):
                continue
            if str(child.tag).lower() in {"ol", "ul"}:
                converted = _block(child, context)
            else:
                converted = _inline(child, context)
            if converted is not None:
                _copy_tail(child, converted)
                target.append(converted)
            else:
                _append_unwrapped_text(target, child.tail)
        return target
    if tag == "blockquote":
        target = tei_el("quote")
        context.identity(source, target)
        _append_blocks(source, target, context)
        return target
    if tag in {"ol", "ul"}:
        attrs = {"type": "ordered" if tag == "ol" else "bulleted"}
        if source.get("type"):
            attrs["rend"] = str(source.get("type"))
        target = tei_el("list", attrs)
        context.identity(source, target)
        for child in source:
            if not isinstance(child.tag, str) or str(child.tag).lower() != "li":
                raise ValueError(f"Unexpected source child inside {tag}: {child.tag!r}")
            item = tei_el("item")
            context.identity(child, item)
            _append_blocks(child, item, context)
            _copy_tail(child, item)
            target.append(item)
        return target
    if tag == "hr":
        target = tei_el("milestone", {"unit": "source-horizontal-rule"})
        context.identity(source, target)
        return target
    if tag in {"center", "div", "table", "td", "tr"}:
        target = tei_el("div", {"type": f"source-{tag}"})
        context.identity(source, target)
        _append_container_segments(source, target, context)
        return target
    raise ValueError(f"Unsupported Spurgeon source block <{tag}>")


def _source_set_sha256(authorities: tuple[Mapping[str, object], ...]) -> str:
    records = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in authorities
            if item.get("role") == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": records})
    )


def _expected_source_readme(supplemental_rights: Mapping[str, object]) -> bytes:
    return (
        "# Spurgeon MTP complete retained-corpus source notice\n\n"
        "This source contract supports a deterministic, nonaccepted TEI candidate "
        "for all 3,550 retained textual HTML witnesses: 3,547 Kingdom Collective "
        "pages and supplemental retained witnesses for sermons 708, 1698, and 3032. "
        "The retained request log is accounted for as acquisition evidence and is "
        "not copied into the TEI.\n\n"
        "Thirteen sermon numbers remain localized missing-source/source-identity "
        "blockers: 8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, and 390. "
        "This source contract therefore does not claim complete resolution of all "
        "3,563 numbered slots.\n\n"
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
        "supplemental witnesses for sermons 708 and 3032 are explicitly scoped to a "
        "Modernized Edition copyright © 2010 Larry and Marion Pierce, Winterbourne, "
        "Ontario, Canada. Their retained Terms of Use prohibit electronic "
        "reproduction or distribution without the copyright owner's express written "
        "permission, allow only limited non-commercial hard-copy printing and "
        "distribution without charge while retaining the copyright notice, and "
        "prohibit derivative works without the copyright owner's express written "
        "permission. Exact retained terms: "
        f"{supplemental_rights['exact_source_text']}\n\n"
        f"Blocker owner: {supplemental_rights['blocker_owner']}. Next action: "
        f"{supplemental_rights['next_action']} Reopening condition: "
        f"{supplemental_rights['reopening_condition']}\n\n"
        "Technical validation is not human acceptance, rights clearance, or "
        "publication authorization; candidate status remains nonaccepted and "
        "publication status remains not-ready.\n"
    ).encode("utf-8")


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    if (
        source_manifest.record.get("source_id") != "spurgeon-mtp-complete-retained-html"
        or source_manifest.record.get("work_id") != "spurgeon-mtp"
    ):
        raise ValueError("Spurgeon source/work identity mismatch")
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    profile = _strict_json(profile_bytes, "Spurgeon reconstruction profile")
    if profile.get("profile_id") != _PROFILE_ID:
        raise ValueError("Spurgeon profile identity mismatch")
    work_identity_config = _validate_work_identity_config(source_manifest, profile)
    supplemental_rights = _validate_profile(profile)
    header_policy = profile["tei_header_policy"]
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Spurgeon authorities are invalid")
    textual = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    textual.sort(
        key=lambda item: _sermon_number(
            source_manifest.authority_path(str(item["name"]))
        )
    )
    if len(textual) != 3550:
        raise ValueError(
            f"Expected 3,550 retained textual witnesses, found {len(textual)}"
        )
    numbers = [
        _sermon_number(source_manifest.authority_path(str(item["name"])))
        for item in textual
    ]
    if len(set(numbers)) != 3550 or sorted(set(range(1, 3564)) - set(numbers)) != list(
        _MISSING
    ):
        raise ValueError("Spurgeon sermon-slot accounting mismatch")
    _validate_primary_attribution_evidence(source_manifest, textual)

    source_set_sha = _source_set_sha256(authorities)
    rights_evidence: dict[int, dict[str, object]] = {}
    for number in _SUPPLEMENTAL_RIGHTS_NUMBERS:
        item = next(
            value
            for value in textual
            if _sermon_number(source_manifest.authority_path(str(value["name"])))
            == number
        )
        evidence = _supplemental_rights_evidence(
            source_manifest.authority_path(str(item["name"])), number
        )
        expected = next(
            value
            for value in supplemental_rights["retained_evidence"]
            if value["sermon_number"] == number
        )
        if evidence != expected:
            raise ValueError(f"Supplemental rights profile drifted for sermon {number}")
        rights_evidence[number] = evidence
    accountability_records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="ocd-spurgeon-mtp-") as temporary:
        content_path = Path(temporary) / "content.tei.xml"
        with etree.xmlfile(str(content_path), encoding="UTF-8") as output:
            output.write_declaration()
            with output.element(f"{{{_TEI_NS}}}TEI", nsmap={None: _TEI_NS}):
                header = stamp_header(
                    title=str(header_policy["title"]),
                    author=str(header_policy["author"]),
                    contributors=list(profile["attribution"]),
                    source_url=str(header_policy["source_url"]),
                    source_sha256=source_set_sha,
                    print_source=str(header_policy["print_source"]),
                    rights_statement=(
                        "Underlying Spurgeon text is public domain; transcription, digitization, and formatting rights remain unresolved. "
                        "Retained supplemental witnesses 708 and 3032 are a Modernized Edition copyright © 2010 Larry and Marion Pierce; "
                        "electronic reproduction and derivative works require the copyright owner's express written permission, while only limited non-commercial hard-copy distribution is licensed. Publication is not authorized."
                    ),
                )
                availability = header.find(f".//{{{_TEI_NS}}}availability")
                source_bibl = header.find(
                    f".//{{{_TEI_NS}}}sourceDesc/{{{_TEI_NS}}}bibl"
                )
                if availability is None or source_bibl is None:
                    raise ValueError("Spurgeon TEI header shape drifted")
                for evidence in rights_evidence.values():
                    availability.append(
                        tei_el(
                            "p",
                            text=(
                                f"Witness {evidence['sermon_number']} ({evidence['retained_path']}): "
                                f"{evidence['source_text']}"
                            ),
                        )
                    )
                    source_bibl.append(
                        tei_el(
                            "note",
                            {
                                "type": "supplemental-witness-rights",
                                "n": str(evidence["sermon_number"]),
                            },
                            f"{evidence['retained_path']} | {evidence['selector']} | sha256:{evidence['source_text_sha256']} | {evidence['source_text']}",
                        )
                    )
                disposition = (
                    f"Rights blocker owner: {supplemental_rights['blocker_owner']}. "
                    f"Next action: {supplemental_rights['next_action']} "
                    f"Reopening condition: {supplemental_rights['reopening_condition']}"
                )
                availability.append(tei_el("p", text=disposition))
                source_bibl.append(
                    tei_el(
                        "note",
                        {"type": "supplemental-witness-rights-disposition"},
                        disposition,
                    )
                )
                output.write(header)
                with output.element(f"{{{_TEI_NS}}}text"):
                    with output.element(f"{{{_TEI_NS}}}body"):
                        for item in textual:
                            name = str(item["name"])
                            path = source_manifest.authority_path(name)
                            number = _sermon_number(path)
                            selected, selection = _selected_source(path, number)
                            context = _Context(number)
                            sermon = tei_el(
                                "div",
                                {
                                    "xml:id": f"spurgeon-mtp-{number:04d}",
                                    "type": "sermon",
                                    "n": str(number),
                                    "subtype": selection,
                                },
                            )
                            if selection == "primary-article":
                                _append_blocks(selected, sermon, context)
                            else:
                                _append_container_segments(selected, sermon, context)
                            normalized = _normalized_text(selected)
                            structure_sha = _sha(_canonical(context.events))
                            record: dict[str, object] = {
                                "number": number,
                                "logical_name": name,
                                "path": item["path"],
                                "bytes": item["bytes"],
                                "sha256": item["sha256"],
                                "role": "textual-witness",
                                "disposition": "represented",
                                "selection": selection,
                                "tei_xml_id": f"spurgeon-mtp-{number:04d}",
                                "normalized_text_sha256": _sha(
                                    normalized.encode("utf-8")
                                ),
                                "mapped_element_count": len(context.events),
                                "mapped_structure_sha256": structure_sha,
                            }
                            if number in rights_evidence:
                                record["witness_rights"] = rights_evidence[number]
                            accountability_records.append(record)
                            output.write(sermon)
        tei_bytes = content_path.read_bytes()

    request_log = next(
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("name") == "request-log"
    )
    accountability = {
        "contract": "ocd-spurgeon-mtp-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "retained_member_count": 3551,
        "retained_member_bytes": 143873038,
        "textual_witness_count": 3550,
        "primary_html_count": 3547,
        "supplemental_html_count": 3,
        "represented_textual_witness_count": len(accountability_records),
        "excluded_evidence_count": 1,
        "omitted_retained_member_count": 0,
        "duplicate_retained_member_count": 0,
        "declared_sermon_slot_count": 3563,
        "resolved_sermon_slot_count": 3550,
        "unresolved_sermon_slot_count": 13,
        "claims_complete_retained_member_coverage": True,
        "claims_complete_3563_slot_resolution": False,
        "supplemental_witness_rights": {
            "scope": supplemental_rights["scope"],
            "rights_owners": supplemental_rights["rights_owners"],
            "terms": supplemental_rights["terms"],
            "blocker_owner": supplemental_rights["blocker_owner"],
            "next_action": supplemental_rights["next_action"],
            "reopening_condition": supplemental_rights["reopening_condition"],
            "retained_evidence": list(rights_evidence.values()),
        },
        "members": accountability_records
        + [
            {
                "logical_name": "request-log",
                "path": request_log["path"],
                "bytes": request_log["bytes"],
                "sha256": request_log["sha256"],
                "role": "acquisition-evidence",
                "disposition": "excluded-from-tei",
                "reason": "Request history is retained acquisition evidence, not sermon text.",
            }
        ],
    }
    provenance = {
        "contract": "ocd-spurgeon-mtp-candidate-provenance-v1",
        "status": "nonaccepted",
        "publication_status": "not-ready",
        "publication_authorized": False,
        "source_manifest_sha256": source_manifest.sha256,
        "source_member_set_sha256": source_set_sha,
        "profile_sha256": _sha(profile_bytes),
        "work_identity": profile["work_identity"],
        "work_identity_config": work_identity_config,
        "attribution": profile["attribution"],
        "attribution_evidence": profile["attribution_evidence"],
        "rights": profile["rights"],
        "retained_source_bytes_embedded": False,
    }
    unresolved = [
        {
            "id": f"spurgeon-mtp-missing-{number}",
            "kind": "missing-source/source-identity",
            "scope": {"sermon_number": number},
            "status": "blocked",
            "evidence": "No retained primary or supplemental HTML member for this number in the exact 3,551-member inventory.",
            "routes_attempted": [
                "Kingdom Collective retained primary census",
                "retained supplemental census",
                "retained acquisition request log",
            ],
            "owner": "source-acquisition-maintainer",
            "next_action": "Acquire and identity-check a retained sermon witness for this exact number.",
            "reopening_condition": "A retained candidate witness is available with exact byte count, SHA-256, edition identity, and rights evidence.",
        }
        for number in _MISSING
    ]
    unresolved.append(deepcopy(_ATTRIBUTION_UNRESOLVED))
    unresolved.append(
        {
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
    )
    readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    if readme != _expected_source_readme(supplemental_rights):
        raise ValueError("Spurgeon durable source attribution README drifted")
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
