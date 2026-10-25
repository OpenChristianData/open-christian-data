"""Reconstruct John Wesley's LIB-032 retained CCEL ThML witness."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-lib032-wesley-plain-account-to-tei"
CONVERTER_VERSION = "1"
SOURCE_SET_AUTHORITY = "retained-source-set"
PROFILE_AUTHORITY = "reconstruction-profile"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"


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


def _retained_member_path(source_manifest: SourceManifest, logical_path: str) -> Path:
    relative = PurePosixPath(logical_path)
    if (
        not logical_path
        or "\\" in logical_path
        or relative.is_absolute()
        or relative.as_posix() != logical_path
        or any(part in {".", ".."} for part in relative.parts)
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise ValueError("LIB-032 source logical path is invalid")

    configured = os.environ.get("OCD_RETAINED_RAW_ROOT", "").strip()
    if configured:
        root = Path(configured).resolve(strict=True)
        path = (root / Path(*relative.parts)).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("LIB-032 source member escaped retained raw root") from exc
        return path

    try:
        path = resolve_repo_path(source_manifest.repository_root, f"raw/{logical_path}")
    except StorageTopologyError as exc:
        raise ValueError("LIB-032 source member escaped retained raw root") from exc
    if not path.is_file():
        raise ValueError(f"LIB-032 retained source is unavailable: {logical_path}")
    return path


def _retained_members(
    source_manifest: SourceManifest,
) -> tuple[dict[str, object], ...]:
    source_set = _authority_json(source_manifest, SOURCE_SET_AUTHORITY)
    profile = _authority_json(source_manifest, PROFILE_AUTHORITY)
    if (
        set(source_set) != {"contract", "storage", "census", "members"}
        or source_set.get("contract") != "ocd-retained-source-set-v1"
    ):
        raise ValueError("LIB-032 retained source-set contract drifted")
    census = source_set.get("census")
    if not isinstance(census, dict) or census != {
        "included": 1,
        "excluded": 0,
        "basis": "the sole ticket-assigned CCEL ThML witness is present, byte-pinned, and suitable for complete ThML.body reconstruction",
    }:
        raise ValueError("LIB-032 retained source census drifted")
    members = source_set.get("members")
    work_order = profile.get("work_order")
    if not isinstance(members, list) or not isinstance(work_order, list):
        raise ValueError("LIB-032 source members or work order is invalid")
    if len(members) != len(work_order) or any(
        not isinstance(item, dict) for item in members
    ):
        raise ValueError("LIB-032 source member accounting is incomplete")
    result: list[dict[str, object]] = []
    for expected_work_id, raw in zip(work_order, members, strict=True):
        if (
            not isinstance(expected_work_id, str)
            or raw.get("work_id") != expected_work_id
        ):
            raise ValueError("LIB-032 source member order or identity drifted")
        logical_path = raw.get("logical_path")
        expected_bytes = raw.get("bytes")
        expected_sha = raw.get("sha256")
        if (
            not isinstance(logical_path, str)
            or type(expected_bytes) is not int
            or not isinstance(expected_sha, str)
            or set(raw)
            != {"work_id", "logical_path", "bytes", "sha256", "disposition", "reason"}
            or raw.get("disposition") != "include"
            or raw.get("reason")
            != "ticket-assigned complete retained CCEL ThML witness"
        ):
            raise ValueError("LIB-032 source member record is invalid")
        path = _retained_member_path(source_manifest, logical_path)
        content = path.read_bytes()
        observed = {"bytes": len(content), "sha256": _sha(content)}
        if observed != {"bytes": expected_bytes, "sha256": expected_sha}:
            raise ValueError(f"LIB-032 retained source drifted: {logical_path}")
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
    text = value if value is not None else ""
    if target_tag in {"div", "table", "row", "list", "lg", "index"} and text.strip():
        raise ValueError(
            f"LIB-032 cannot place non-whitespace source text directly in TEI {target_tag}"
        )
    return text


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
        raise ValueError("LIB-032 source body contains an unsupported node")
    source_tag = (
        _local(source)
        if isinstance(source.tag, str)
        else ("#comment" if is_comment else "#pi")
    )
    target_tag = _contextual_target_tag(source, parent)
    target_id = f"lib032-f-{feature_number:07d}"
    attrs = {"xml:id": target_id}
    if is_comment:
        attrs["type"] = "thml-comment"
    elif is_pi:
        attrs["type"] = "thml-processing-instruction"
    else:
        attrs.update(_target_attributes(source, target_tag))
    target = tei_el(target_tag, attrs)
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
    if source_title and not has_heading_child:
        target.append(tei_el("head", text=source_title))
        target[0].tail = _content_text(target_tag, source.text)
    else:
        target.text = _content_text(target_tag, source.text)
    child_ordinal = len(parent) + 1
    parent.append(target)
    rows.append(
        {
            "feature_id": f"lib032-feature-{feature_number:07d}",
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
                (
                    "xml:id"
                    if key == XML_ID
                    else "xml:lang"
                    if key == f"{{{XML_NS}}}lang"
                    else key
                ): value
                for key, value in target.attrib.items()
            },
            "attribute_dispositions": (
                [
                    {
                        "source_attribute": key,
                        "source_value": value,
                        "destination": (
                            "@xml:id"
                            if key == "id"
                            else "projected-TEI-attribute"
                            if key
                            in {
                                "type",
                                "n",
                                "class",
                                "lang",
                                "href",
                                "osisRef",
                                "passage",
                                "place",
                                "colspan",
                            }
                            else "source-accountability"
                        ),
                    }
                    for key, value in source.attrib.items()
                ]
                if isinstance(source.tag, str)
                else []
            ),
            "disposition": "represented",
            "tei_selector": f"#{target_id}",
            "parent_feature_id": None,
            "source_title_head": source_title,
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
    tree: etree._ElementTree, body: etree._Element
) -> dict[str, int]:
    comments = sum(1 for node in tree.iter() if isinstance(node, etree._Comment))
    processing_instructions = sum(
        1 for node in tree.iter() if isinstance(node, etree._ProcessingInstruction)
    )
    return {
        "body_element_count": sum(
            1 for node in body.iter() if isinstance(node.tag, str)
        )
        - 1,
        "body_attribute_count": sum(
            len(node.attrib) for node in body.iter() if isinstance(node.tag, str)
        ),
        "comment_count": comments,
        "processing_instruction_count": processing_instructions,
    }


def _work_metadata(profile: Mapping[str, object], work_id: str) -> dict[str, object]:
    for item in profile.get("works", []):
        if isinstance(item, dict) and item.get("work_id") == work_id:
            return item
    raise ValueError(f"LIB-032 profile has no metadata for {work_id}")


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _authority_json(source_manifest, PROFILE_AUTHORITY)
    members = _retained_members(source_manifest)
    work_order = profile.get("work_order")
    if not isinstance(work_order, list):
        raise ValueError("LIB-032 profile work order is invalid")
    root = tei_el("TEI", {"xml:id": "lib032-candidate"})
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
            title="LIB-032 Wesley faithful TEI candidate",
            author="John Wesley",
            contributors=contributors,
            source_url="https://www.ccel.org/",
            source_sha256=source_set_digest,
            print_source="CCEL ThML witness; print-edition collation not performed",
            rights_statement=(
                "The local source configuration claims public-domain status for the underlying work. "
                "CCEL permits parsing its ThML; attribution is retained here as source evidence. "
                "Human rights, textual, edition, and publication decisions remain unresolved."
            ),
        )
    )
    text = tei_el("text")
    body_out = tei_el("body", {"xml:id": "lib032-body"})
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
                f"LIB-032 source has no ThML.body: {member['logical_path']}"
            )
        work_out = tei_el("div", {"xml:id": work_id, "type": "work"})
        work_out.append(tei_el("head", text=str(metadata["title"])))
        work_out[0].tail = _content_text("div", source_body.text)
        body_out.append(work_out)
        before = len(rows)
        for child in source_body:
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
                "feature_count": len(rows) - before,
                "body_direct_text": source_body.text or "",
                "body_direct_text_sha256": _sha(
                    (source_body.text or "").encode("utf-8")
                ),
                "document_accounting": _source_document_accounting(tree, source_body),
                "disposition": "represented-as-one-work-division",
            }
        )
    feature_counts: dict[str, int] = {}
    attribute_count = 0
    for row in rows:
        source_tag = str(row["source_tag"])
        feature_counts[source_tag] = feature_counts.get(source_tag, 0) + 1
        attribute_count += len(row["attributes"])
    accountability = {
        "contract": "ocd-lib032-source-accountability-v1",
        "schema": "lib032.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_scope": "each retained ThML.body represented in declared work order",
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
        "contract": "ocd-lib032-provenance-v1",
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
            "id": "lib032-print-edition-collation",
            "scope": "wesley-plain-account",
            "status": "unresolved",
            "question": "Does the retained CCEL ThML witness match the intended print edition?",
            "evidence": "No print collation was performed; the candidate is bound to the retained source bytes.",
        },
        {
            "id": "lib032-human-acceptance-and-publication",
            "scope": "wesley-plain-account",
            "status": "unresolved",
            "question": "Will a maintainer accept the candidate text, rights basis, and publication status?",
            "evidence": "Technical reconstruction and validation are not human acceptance or publication authorization.",
        },
    ]
    readme = (
        "# LIB-032 faithful TEI candidate\n\n"
        "This is a nonaccepted candidate reconstructed deterministically from the sole retained CCEL ThML member declared by the source-set authority. "
        "The source file remains outside the repository's canonical data and is read through the durable retained raw root. "
        "Every source-body element is represented in `source-accountability.json`; unsupported ThML names use an explicit `seg @type` fallback rather than silent omission.\n\n"
        "The electronic witness is sourced via [CCEL.org](https://www.ccel.org/). The local config claims public-domain status for the underlying work, while CCEL parsing terms and worldwide rights remain evidence for human review. No canonical data, IR, acceptance, or publication state was written.\n"
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
