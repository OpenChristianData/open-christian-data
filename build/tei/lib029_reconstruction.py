"""Reconstruct the LIB-029 Creeds of Christendom Vol. I source."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-lib029-ccel-thml-cohort-to-tei"
CONVERTER_VERSION = "1"
SOURCE_SET_AUTHORITY = "retained-source-set"
PROFILE_AUTHORITY = "reconstruction-profile"
ATTRIBUTION_AUTHORITY = "source-attribution"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority_json(source_manifest: SourceManifest, name: str) -> dict[str, object]:
    return _strict_json(source_manifest.authority_path(name).read_bytes(), name)


def _retained_root(source_manifest: SourceManifest) -> Path:
    configured = os.environ.get("OCD_RETAINED_RAW_ROOT", "").strip()
    root = Path(configured) if configured else source_manifest.repository_root / "raw"
    return root.resolve(strict=True)


def _retained_members(
    source_manifest: SourceManifest,
) -> tuple[dict[str, object], ...]:
    source_set = _authority_json(source_manifest, SOURCE_SET_AUTHORITY)
    profile = _authority_json(source_manifest, PROFILE_AUTHORITY)
    if source_set.get("contract") != "ocd-retained-source-set-v1":
        raise ValueError("LIB-029 retained source-set contract drifted")
    members = source_set.get("members")
    work_order = profile.get("work_order")
    if not isinstance(members, list) or not isinstance(work_order, list):
        raise ValueError("LIB-029 source members or work order is invalid")
    if len(members) != len(work_order) or any(
        not isinstance(item, dict) for item in members
    ):
        raise ValueError("LIB-029 source member accounting is incomplete")
    root = _retained_root(source_manifest)
    result: list[dict[str, object]] = []
    for expected_work_id, raw in zip(work_order, members, strict=True):
        if (
            not isinstance(expected_work_id, str)
            or raw.get("work_id") != expected_work_id
        ):
            raise ValueError("LIB-029 source member order or identity drifted")
        logical_path = raw.get("logical_path")
        expected_bytes = raw.get("bytes")
        expected_sha = raw.get("sha256")
        if (
            not isinstance(logical_path, str)
            or not isinstance(expected_bytes, int)
            or not isinstance(expected_sha, str)
        ):
            raise ValueError("LIB-029 source member record is invalid")
        path = (root / logical_path).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("LIB-029 source member escaped retained raw root") from exc
        content = path.read_bytes()
        observed = {"bytes": len(content), "sha256": _sha(content)}
        if observed != {"bytes": expected_bytes, "sha256": expected_sha}:
            raise ValueError(f"LIB-029 retained source drifted: {logical_path}")
        result.append({**raw, "resolved_path": path})
    return tuple(result)


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", value)
    return safe or "source"


def _selector(node: etree._Element, body: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current is not body:
        parent = current.getparent()
        if parent is None:
            break
        tag = (
            _local(current)
            if isinstance(current.tag, str)
            else ("#comment" if isinstance(current, etree._Comment) else "#pi")
        )
        peers = [
            child
            for child in parent
            if (
                isinstance(child.tag, str)
                and isinstance(current.tag, str)
                and _local(child) == tag
            )
            or (
                isinstance(current, etree._Comment)
                and isinstance(child, etree._Comment)
            )
            or (
                isinstance(current, etree._ProcessingInstruction)
                and isinstance(child, etree._ProcessingInstruction)
            )
        ]
        parts.append(f"{tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _target_tag(tag: str, source: etree._Element | None = None) -> str:
    mapped = {
        "div1": "div",
        "div2": "div",
        "div3": "div",
        "div4": "div",
        "div": "quote",
        "h1": "head",
        "h2": "head",
        "h3": "head",
        "h4": "head",
        "h5": "head",
        "h6": "head",
        "title": "head",
        "p": "p",
        "i": "hi",
        "b": "hi",
        "sup": "hi",
        "sub": "hi",
        "span": "seg",
        "insertIndex": "index",
        "colgroup": "row",
        "col": "cell",
        "a": "ref",
        "scripRef": "ref",
        "note": "note",
        "pb": "pb",
        "br": "lb",
        "table": "table",
        "tr": "row",
        "td": "cell",
        "th": "cell",
        "l": "l",
        "verse": "lg",
        "ul": "list",
        "ol": "list",
        "li": "item",
        "hr": "milestone",
        "#comment": "note",
        "#pi": "note",
    }.get(tag, "seg")
    if tag == "span" and source is not None and source.get("lang"):
        return "foreign"
    return mapped


def _contextual_target_tag(source: etree._Element, parent: etree._Element) -> str:
    tag = (
        _local(source)
        if isinstance(source.tag, str)
        else ("#comment" if isinstance(source, etree._Comment) else "#pi")
    )
    target_tag = _target_tag(tag, source if isinstance(source.tag, str) else None)
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "title"}:
        parent_tag = _local(parent) if isinstance(parent.tag, str) else ""
        if parent_tag in {"div", "quote"}:
            return "p"
        if parent_tag not in {"div1", "div2", "div3", "div4"}:
            return "seg"
        if any(
            isinstance(child.tag, str)
            and _local(child) in {"head", "p", "div", "quote"}
            for child in parent
        ):
            return "p"
    return target_tag


def _target_attributes(source: etree._Element, target_tag: str) -> dict[str, str]:
    tag = _local(source)
    attrs: dict[str, str] = {}
    if source.get("type") and target_tag in {"div", "quote", "seg", "list"}:
        attrs["type"] = source.get("type", "")
    if source.get("n") and target_tag in {"div", "note", "pb", "milestone"}:
        attrs["n"] = source.get("n", "")
    if source.get("class") and target_tag == "hi":
        attrs["rend"] = source.get("class", "")
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "b":
        attrs["rend"] = "bold"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "sub":
        attrs["rend"] = "subscript"
    elif tag == "span":
        language = source.get("lang")
        if language:
            attrs["xml:lang"] = {
                "EL": "grc",
                "HE": "he",
                "LA": "la",
                "FR": "fr",
                "DE": "de",
            }.get(language, language.lower())
        else:
            attrs["type"] = "thml-span"
    elif tag == "a" and source.get("href"):
        attrs["target"] = source.get("href", "")
    elif tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("osisRef"):
            attrs["target"] = source.get("osisRef", "")
        if source.get("passage"):
            attrs["cRef"] = source.get("passage", "")
    elif tag == "note" and source.get("place"):
        attrs["place"] = source.get("place", "")
    elif tag in {"td", "th"} and source.get("colspan"):
        attrs["cols"] = source.get("colspan", "")
    elif tag == "hr":
        attrs["unit"] = "horizontal-rule"
    elif tag == "scripture":
        attrs["type"] = "scripture"
    elif tag in {"style", "selector"}:
        attrs["type"] = f"thml-{tag}"
    elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "title"} and target_tag == "seg":
        attrs["type"] = f"thml-{tag}"
    elif target_tag == "seg":
        attrs["type"] = f"thml-{tag}"
    return attrs


def _content_text(target_tag: str, value: str | None) -> str:
    text = value or ""
    if (
        target_tag in {"div", "table", "row", "list", "lg", "index"}
        and not text.strip()
    ):
        return ""
    return text


def _needs_block_wrapper(
    source: etree._Element, parent: etree._Element, target_tag: str
) -> bool:
    """Keep source-inline features valid when ThML places them in a div."""

    del source
    parent_tag = _local(parent) if isinstance(parent.tag, str) else ""
    return parent_tag in {"div", "quote"} and target_tag in {
        "ref",
        "hi",
        "seg",
        "foreign",
        "lb",
    }


def _attribute_dispositions(
    source: etree._Element,
    source_tag: str,
    target_tag: str,
    target: etree._Element,
    synthetic_title: str | None,
) -> list[dict[str, str]]:
    destinations: dict[str, tuple[str, str | None]] = {}
    if target_tag in {"div", "quote", "seg", "list"}:
        destinations["type"] = ("@type", target.get("type"))
    if target_tag in {"div", "note", "pb", "milestone"}:
        destinations["n"] = ("@n", target.get("n"))
    if target_tag == "hi":
        destinations["class"] = ("@rend", target.get("rend"))
    if source_tag == "span" and target_tag == "foreign":
        destinations["lang"] = ("@xml:lang", target.get(XML_LANG))
    if source_tag == "a" and target_tag == "ref":
        destinations["href"] = ("@target", target.get("target"))
    if source_tag == "scripRef" and target_tag == "ref":
        destinations["osisRef"] = ("@target", target.get("target"))
        destinations["passage"] = ("@cRef", target.get("cRef"))
    if source_tag == "note" and target_tag == "note":
        destinations["place"] = ("@place", target.get("place"))
    if source_tag in {"td", "th"} and target_tag == "cell":
        destinations["colspan"] = ("@cols", target.get("cols"))
    if source_tag.startswith("div") and synthetic_title is not None:
        destinations["title"] = ("child::head[1]", synthetic_title)

    dispositions: list[dict[str, str]] = []
    for key, value in source.attrib.items():
        destination, projected_value = destinations.get(
            key, ("source-accountability", None)
        )
        if key == "lang":
            expected_value = {
                "EL": "grc",
                "HE": "he",
                "LA": "la",
                "FR": "fr",
                "DE": "de",
            }.get(value, value.lower())
        else:
            expected_value = value
        if projected_value != expected_value:
            destination = "source-accountability"
        dispositions.append(
            {
                "source_attribute": key,
                "source_value": value,
                "destination": destination,
            }
        )
    return dispositions


def _append_node(
    source: etree._Element,
    parent: etree._Element,
    *,
    body: etree._Element,
    work_id: str,
    rows: list[dict[str, object]],
    counter: list[int],
    parent_id: str,
) -> None:
    counter[0] += 1
    feature_number = counter[0]
    is_comment = isinstance(source, etree._Comment)
    is_pi = isinstance(source, etree._ProcessingInstruction)
    if not isinstance(source.tag, str) and not (is_comment or is_pi):
        raise ValueError("LIB-029 source body contains an unsupported node")
    source_tag = (
        _local(source)
        if isinstance(source.tag, str)
        else ("#comment" if is_comment else "#pi")
    )
    target_tag = _contextual_target_tag(source, parent)
    target_id = f"lib029-f-{feature_number:07d}"
    attrs = {"xml:id": target_id}
    if is_comment:
        attrs["type"] = "thml-comment"
    elif is_pi:
        attrs["type"] = "thml-processing-instruction"
    else:
        attrs.update(_target_attributes(source, target_tag))
    target = tei_el(target_tag, attrs)
    target_parent = parent
    if _needs_block_wrapper(source, parent, target_tag):
        target_parent = tei_el("p")
        parent.append(target_parent)
    source_title = (
        source.get("title")
        if isinstance(source.tag, str) and source_tag.startswith("div")
        else None
    )
    has_heading_child = (
        any(
            isinstance(child.tag, str)
            and _local(child) in {"h1", "h2", "h3", "h4", "h5", "h6"}
            for child in source
        )
        if isinstance(source.tag, str)
        else False
    )
    synthetic_title = source_title if source_title and not has_heading_child else None
    if synthetic_title is not None:
        target.append(tei_el("head", text=synthetic_title))
        target[0].tail = _content_text(target_tag, source.text)
    else:
        target.text = _content_text(target_tag, source.text)
    child_ordinal = len(parent) + 1
    target_parent.append(target)
    rows.append(
        {
            "feature_id": f"lib029-feature-{feature_number:07d}",
            "work_id": work_id,
            "source_selector": _selector(source, body),
            "source_tag": source_tag,
            "source_xml_id": source.get("id"),
            "attributes": dict(source.attrib) if isinstance(source.tag, str) else {},
            "direct_text": source.text or "",
            "tail_text": source.tail or "",
            "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
            "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
            "tei_tag": target_tag,
            "tei_xml_id": target_id,
            "tei_parent_id": parent.get(XML_ID) or "",
            "tei_child_ordinal": child_ordinal,
            "tei_attributes": {
                ("xml:id" if key == XML_ID else key): value
                for key, value in target.attrib.items()
            },
            "attribute_dispositions": (
                _attribute_dispositions(
                    source, source_tag, target_tag, target, synthetic_title
                )
                if isinstance(source.tag, str)
                else []
            ),
            "disposition": "represented",
            "tei_selector": f"#{target_id}",
            "parent_feature_id": None,
            "source_title_head": synthetic_title,
        }
    )
    if rows[-1]["tei_parent_id"]:
        for previous in reversed(rows[:-1]):
            if previous["tei_xml_id"] == rows[-1]["tei_parent_id"]:
                rows[-1]["parent_feature_id"] = previous["feature_id"]
                break
    for child in source:
        _append_node(
            child,
            target,
            body=body,
            work_id=work_id,
            rows=rows,
            counter=counter,
            parent_id=target_id,
        )
        if len(target):
            target[-1].tail = _content_text(target_tag, child.tail)


def _source_document_accounting(
    roots: tuple[etree._Element, ...],
) -> dict[str, int]:
    nodes = [node for root in roots for node in root.iter()]
    return {
        "body_element_count": sum(1 for node in nodes if isinstance(node.tag, str)),
        "body_attribute_count": sum(
            len(node.attrib) for node in nodes if isinstance(node.tag, str)
        ),
        "comment_count": sum(1 for node in nodes if isinstance(node, etree._Comment)),
        "processing_instruction_count": sum(
            1 for node in nodes if isinstance(node, etree._ProcessingInstruction)
        ),
    }


def _work_metadata(profile: Mapping[str, object], work_id: str) -> dict[str, object]:
    for item in profile.get("works", []):
        if isinstance(item, dict) and item.get("work_id") == work_id:
            return item
    raise ValueError(f"LIB-029 profile has no metadata for {work_id}")


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _authority_json(source_manifest, PROFILE_AUTHORITY)
    members = _retained_members(source_manifest)
    work_order = profile.get("work_order")
    if not isinstance(work_order, list):
        raise ValueError("LIB-029 profile work order is invalid")
    root = tei_el("TEI", {"xml:id": "lib029-candidate"})
    member_records = [
        {
            "work_id": str(item["work_id"]),
            "path": str(item["logical_path"]),
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in members
    ]
    source_set_digest = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": member_records})
    )
    contributors = [
        {
            "name": "Christian Classics Ethereal Library",
            "role": "electronic source host",
        },
    ]
    root.append(
        stamp_header(
            title="LIB-029 Creeds of Christendom Vol. I faithful TEI candidate",
            author="Philip Schaff",
            contributors=contributors,
            source_url="https://www.ccel.org/ccel/schaff/creeds1.xml",
            source_sha256=source_set_digest,
            print_source="CCEL ThML edition; print-edition collation not performed",
            rights_statement=(
                "Local source configurations claim public-domain status for the underlying works. "
                "CCEL permits parsing its ThML; attribution is retained here as source evidence. "
                "Human rights, textual, edition, and publication decisions remain unresolved."
            ),
        )
    )
    text = tei_el("text")
    body_out = tei_el("body", {"xml:id": "lib029-body"})
    text.append(body_out)
    root.append(text)
    rows: list[dict[str, object]] = []
    documents: list[dict[str, object]] = []
    counter = [0]
    for member in members:
        work_id = str(member["work_id"])
        metadata = _work_metadata(profile, work_id)
        tree = _parse(member["resolved_path"])
        source_body = next(
            (
                node
                for node in tree.iter()
                if isinstance(node.tag, str) and _local(node) == "ThML.body"
            ),
            None,
        )
        if source_body is None:
            raise ValueError(
                f"LIB-029 source has no ThML.body: {member['logical_path']}"
            )
        selected_ids = profile.get("selected_div1_ids")
        if (
            not isinstance(selected_ids, list)
            or not selected_ids
            or any(not isinstance(item, str) for item in selected_ids)
        ):
            raise ValueError("LIB-029 selected div1 scope is invalid")
        selected = tuple(
            child
            for child in source_body
            if isinstance(child.tag, str)
            and _local(child) == "div1"
            and child.get("id") in selected_ids
        )
        if [child.get("id") for child in selected] != selected_ids:
            raise ValueError(
                "LIB-029 selected div1 scope is incomplete or out of order"
            )
        work_out = tei_el("div", {"xml:id": work_id, "type": "work"})
        work_out.append(tei_el("head", text=str(metadata["title"])))
        body_out.append(work_out)
        before = len(rows)
        for child in selected:
            _append_node(
                child,
                work_out,
                body=source_body,
                work_id=work_id,
                rows=rows,
                counter=counter,
                parent_id=work_id,
            )
            if len(work_out):
                work_out[-1].tail = _content_text("div", child.tail)
        documents.append(
            {
                "work_id": work_id,
                "logical_path": member["logical_path"],
                "bytes": member["bytes"],
                "sha256": member["sha256"],
                "scope_div1_ids": list(selected_ids),
                "feature_count": len(rows) - before,
                "document_accounting": _source_document_accounting(selected),
                "disposition": "selected-div1-chapters-represented-as-one-work-division",
            }
        )
    feature_counts: dict[str, int] = {}
    attribute_count = 0
    for row in rows:
        source_tag = str(row["source_tag"])
        feature_counts[source_tag] = feature_counts.get(source_tag, 0) + 1
        attribute_count += len(row["attributes"])
    accountability = {
        "contract": "ocd-lib029-source-accountability-v1",
        "schema": "lib029.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_scope": "selected ThML.body div1 chapters iii through x represented in source order",
        "source_reference_authority": {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "authority": SOURCE_SET_AUTHORITY,
            "sha256": _sha(
                source_manifest.authority_path(SOURCE_SET_AUTHORITY).read_bytes()
            ),
        },
        "source_members": member_records,
        "document_accounting": documents,
        "work_count": len(documents),
        "feature_count": len(rows),
        "attribute_count": attribute_count,
        "feature_counts": feature_counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-lib029-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_member_set_sha256": source_set_digest,
        "source_root": "durable retained raw root resolved through OCD_RETAINED_RAW_ROOT or approved raw topology",
        "works": [
            {
                **_work_metadata(profile, str(member["work_id"])),
                "source_sha256": member["sha256"],
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
            for member in members
        ],
        "rights": {
            "underlying_work_claim": "local-config-public-domain",
            "electronic_host_terms": "CCEL parsing permission retained as evidence",
            "worldwide_rights_decision": "unresolved",
        },
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "lib029-print-edition-collation",
            "scope": "selected-chapters",
            "status": "unresolved",
            "question": "Does each retained CCEL ThML witness match the intended print edition?",
            "evidence": "No print collation was performed; the candidate is bound to the retained CCEL source bytes and selected chapter scope.",
        },
        {
            "id": "lib029-human-acceptance-and-publication",
            "scope": "all-eight-chapters",
            "status": "unresolved",
            "question": "Will a maintainer accept the candidate text, rights basis, and publication status?",
            "evidence": "Technical reconstruction and validation are not human acceptance or publication authorization.",
        },
    ]
    attribution = source_manifest.authority_path(ATTRIBUTION_AUTHORITY).read_bytes()
    if b"CCEL.org" not in attribution:
        raise ValueError("LIB-029 source attribution authority is missing")
    readme = (
        "# LIB-029 faithful TEI candidate\n\n"
        "This is a nonaccepted candidate reconstructed deterministically from the retained CCEL ThML member declared by the source-set authority. "
        "The source files remain outside the repository's canonical data and are read through the durable retained raw root. "
        "Every selected source-scope node is represented in `source-accountability.json`; unsupported ThML names use an explicit `seg @type` fallback rather than silent omission.\n\n"
        "The electronic witnesses are sourced via [CCEL.org](https://www.ccel.org/). Local configs claim public-domain status for the underlying works, while CCEL parsing terms and worldwide rights remain evidence for human review. No canonical data, IR, acceptance, or publication state was written.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ("_convert",)
