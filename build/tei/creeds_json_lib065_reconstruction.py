"""Faithfully reconstruct one LIB-065 Creeds.json member as TEI.

The seven ticket members are deliberately packaged separately.  Each package is
therefore bound to one literal retained JSON byte stream and can participate in
the WorkCatalog through an exact, work-local legacy-claim lineage.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-creeds-json-lib065-retained-member-to-tei"
CONVERTER_VERSION = "1"
ASSIGNED: tuple[tuple[str, str], ...] = (
    ("ten-theses-of-berne", "ten_theses_of_berne"),
    ("tertullians-rule-of-faith", "tertullians_rule_of_faith"),
    ("tetrapolitan-confession", "tetrapolitan_confession"),
    ("waldensian-confession", "waldensian_confession"),
    ("westminster-confession-of-faith", "westminster_confession_of_faith"),
    ("zwinglis-67-articles", "zwinglis_67_articles"),
    ("zwinglis-fidei-ratio", "zwinglis_fidei_ratio"),
)
WORK_TO_STEM = dict(ASSIGNED)
STEM_TO_WORK = {stem: work_id for work_id, stem in ASSIGNED}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"retained JSON has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        loaded = json.loads(
            content.decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "retained Creeds.json member is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError("retained Creeds.json document root must be an object")
    return loaded


def _manifest_context(
    source_manifest: SourceManifest,
) -> tuple[str, Path, bytes, dict[str, object], dict[str, object]]:
    record = source_manifest.record
    work_id = record.get("work_id")
    if not isinstance(work_id, str) or work_id not in WORK_TO_STEM:
        raise ValueError("LIB-065 source manifest work identity drifted")
    authorities = record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("LIB-065 source authorities are invalid")
    primary = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    if len(primary) != 1:
        raise ValueError("LIB-065 package requires exactly one primary source")
    authority = primary[0]
    expected_path = f"raw/Creeds.json/creeds/{WORK_TO_STEM[work_id]}.json"
    if authority.get("path") != expected_path:
        raise ValueError("LIB-065 work-to-retained-member binding drifted")
    source_path = source_manifest.authority_path(str(authority["name"]))
    source_bytes = source_path.read_bytes()
    document = _strict_json(source_bytes)
    metadata = document.get("Metadata")
    if not isinstance(metadata, dict) or set(document) != {"Metadata", "Data"}:
        raise ValueError("retained Creeds.json top-level shape or order drifted")
    return work_id, source_path, source_bytes, document, metadata


def _scalar_text(value: object) -> tuple[str, str]:
    if value is None:
        return "json-null", ""
    if isinstance(value, bool):
        return "json-boolean", "true" if value else "false"
    if isinstance(value, (int, float)):
        return "json-number", json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, str):
        return "json-string", value
    raise TypeError(f"unsupported JSON scalar {type(value).__name__}")


def _append_json_value(
    parent: etree._Element,
    value: object,
    *,
    work_id: str,
    path: str,
    state: dict[str, object],
) -> None:
    ordinal = int(state["next_ordinal"])
    state["next_ordinal"] = ordinal + 1
    node_id = f"lib065-{work_id}-node-{ordinal:05d}"
    if isinstance(value, dict):
        kind = "json-object"
    elif isinstance(value, list):
        kind = "json-array"
    else:
        kind, _ = _scalar_text(value)
    node = tei_el("div", {"xml:id": node_id, "type": kind})
    parent.append(node)
    row: dict[str, object] = {
        "ordinal": ordinal,
        "json_path": path,
        "kind": kind.removeprefix("json-"),
        "tei_xml_id": node_id,
    }
    if isinstance(value, dict):
        row["member_count"] = len(value)
        state["objects"] = int(state["objects"]) + 1
        for member_ordinal, (key, child) in enumerate(value.items(), start=1):
            wrapper_ordinal = int(state["next_ordinal"])
            state["next_ordinal"] = wrapper_ordinal + 1
            wrapper_id = f"lib065-{work_id}-node-{wrapper_ordinal:05d}"
            wrapper = tei_el(
                "div",
                {"xml:id": wrapper_id, "type": "json-member", "n": str(member_ordinal)},
            )
            wrapper.append(tei_el("head", {"type": "json-key"}, key))
            node.append(wrapper)
            state["members"] = int(state["members"]) + 1
            state["crosswalk"].append(
                {
                    "ordinal": wrapper_ordinal,
                    "json_path": f"{path}/{key}",
                    "kind": "member",
                    "key": key,
                    "member_ordinal": member_ordinal,
                    "tei_xml_id": wrapper_id,
                }
            )
            _append_json_value(
                wrapper,
                child,
                work_id=work_id,
                path=f"{path}/{key}",
                state=state,
            )
    elif isinstance(value, list):
        row["item_count"] = len(value)
        state["arrays"] = int(state["arrays"]) + 1
        for index, child in enumerate(value):
            wrapper_ordinal = int(state["next_ordinal"])
            state["next_ordinal"] = wrapper_ordinal + 1
            wrapper_id = f"lib065-{work_id}-node-{wrapper_ordinal:05d}"
            wrapper = tei_el(
                "div",
                {"xml:id": wrapper_id, "type": "json-item", "n": str(index)},
            )
            node.append(wrapper)
            state["items"] = int(state["items"]) + 1
            state["crosswalk"].append(
                {
                    "ordinal": wrapper_ordinal,
                    "json_path": f"{path}/{index}",
                    "kind": "item",
                    "item_index": index,
                    "tei_xml_id": wrapper_id,
                }
            )
            _append_json_value(
                wrapper,
                child,
                work_id=work_id,
                path=f"{path}/{index}",
                state=state,
            )
    else:
        _kind, scalar = _scalar_text(value)
        state[_kind.removeprefix("json-") + "s"] = (
            int(state[_kind.removeprefix("json-") + "s"]) + 1
        )
        node.append(tei_el("ab", {"type": "json-scalar"}, scalar))
        row["value_sha256"] = _sha(scalar.encode("utf-8"))
        row["value_characters"] = len(scalar)
    state["crosswalk"].append(row)


def _family_census(source_manifest: SourceManifest) -> list[dict[str, object]]:
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_text(
            encoding="utf-8"
        )
    )
    census = profile.get("family_census")
    if not isinstance(census, list) or len(census) != 43:
        raise ValueError("LIB-065 retained-family census is incomplete")
    return census


def _readme(work_id: str, title: str, source_path: str, source_sha: str) -> bytes:
    rights = (
        "The bound repository README states that this member is covered by "
        "the Unlicense because it is not one of the eight named exceptions. "
        "That repository-level statement is retained as rights evidence; edition, "
        "translation, authorship, and worldwide publication conclusions still "
        "require human review. No attribution request is stated for this member."
    )
    return (
        f"# {title}: retained Creeds.json witness\n\n"
        f"Work ID: `{work_id}`  \n"
        f"Retained source: `{source_path}`  \n"
        f"Literal-byte SHA-256: `{source_sha}`\n\n"
        f"{rights}\n\n"
        "This candidate preserves the literal retained JSON bytes in base64 and "
        "also projects every JSON object, member key, array item, scalar value, "
        "and their order into TEI. It is technically verified evidence only: "
        "human review is required, accepted IR is not accepted, and publication "
        "is not ready.\n"
    ).encode("utf-8")


def _unresolved(work_id: str, source_path: str, source_sha: str) -> bytes:
    rows = (
        {
            "id": f"{work_id}-identity-edition-and-translation",
            "scope": work_id,
            "kind": "identity",
            "question": "Which historical edition and English translation does the retained JSON witness represent?",
            "evidence": {"path": source_path, "sha256": source_sha},
            "disposition": "human-review-required",
        },
        {
            "id": f"{work_id}-metadata-claims",
            "scope": work_id,
            "kind": "editorial",
            "question": "Which retained metadata claims are independently supported by a primary witness?",
            "evidence": {"path": source_path, "sha256": source_sha},
            "disposition": "human-review-required",
        },
        {
            "id": f"{work_id}-rights-and-publication",
            "scope": work_id,
            "kind": "rights",
            "question": "Does the repository-level Unlicense evidence suffice for the retained edition and translation in every intended jurisdiction?",
            "evidence": {
                "path": "raw/Creeds.json/README.md",
                "member_path": source_path,
                "member_sha256": source_sha,
            },
            "disposition": "human-review-required-publication-not-ready",
        },
    )
    return b"".join(_canonical(row) for row in rows)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    work_id, source_path, source_bytes, document, metadata = _manifest_context(
        source_manifest
    )
    source_record = next(
        item
        for item in source_manifest.record["authorities"]
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    )
    source_logical = str(source_record["path"])
    source_sha = _sha(source_bytes)
    title = metadata.get("Title")
    if not isinstance(title, str) or not title:
        raise ValueError("retained Creeds.json Title is missing")
    authors = metadata.get("Authors")
    author = (
        "; ".join(str(item) for item in authors)
        if isinstance(authors, list) and authors
        else "Authorship not stated in retained source"
    )
    attribution = metadata.get("SourceAttribution")
    contributors = (
        [str(attribution)] if isinstance(attribution, str) and attribution else []
    )
    source_url = metadata.get("SourceUrl")
    if not isinstance(source_url, str) or not source_url:
        source_url = "https://github.com/NonlinearFruit/Creeds.json"

    root = tei_el(
        "TEI",
        {"xml:id": f"lib065-{work_id}", "xml:lang": "en"},
    )
    root.append(
        stamp_header(
            title=f"{title} — retained Creeds.json witness",
            author=author,
            contributors=contributors,
            source_url=source_url,
            source_sha256=source_sha,
            print_source=(
                "Retained Creeds.json JSON witness; edition and translation "
                "identity are not independently established."
            ),
            rights_statement=(
                "The retained Creeds.json README places this member under the "
                "Unlicense, subject to human confirmation of edition and translation rights."
            ),
        )
    )
    text = tei_el("text")
    body = tei_el("body")
    text.append(body)
    root.append(text)
    document_div = tei_el(
        "div",
        {
            "xml:id": f"lib065-{work_id}-document",
            "type": "retained-json-document",
            "n": work_id,
            "corresp": source_logical,
        },
    )
    document_div.append(tei_el("head", text=title))
    byte_div = tei_el(
        "div",
        {"xml:id": f"lib065-{work_id}-literal-bytes", "type": "retained-byte-stream"},
    )
    byte_div.append(
        tei_el(
            "ab",
            {"type": "base64-application-json"},
            base64.b64encode(source_bytes).decode("ascii"),
        )
    )
    document_div.append(byte_div)
    semantic = tei_el(
        "div",
        {"xml:id": f"lib065-{work_id}-semantic-json", "type": "json-semantic-tree"},
    )
    document_div.append(semantic)
    body.append(document_div)
    state: dict[str, object] = {
        "next_ordinal": 1,
        "objects": 0,
        "arrays": 0,
        "members": 0,
        "items": 0,
        "strings": 0,
        "numbers": 0,
        "booleans": 0,
        "nulls": 0,
        "crosswalk": [],
    }
    _append_json_value(
        semantic,
        document,
        work_id=work_id,
        path="$",
        state=state,
    )
    tei_bytes = etree.tostring(
        etree.ElementTree(root),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    normalized_sha = _sha(source_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    lineage = source_manifest.record.get("catalog_claim_lineage")
    if (
        not isinstance(lineage, Mapping)
        or lineage.get("work_id") != work_id
        or lineage.get("retained_source_sha256") != source_sha
        or lineage.get("claim_count") != 1
        or lineage.get("claims")
        != (
            {
                "source_path": f"doctrinal-documents/{work_id}.json",
                "legacy_source_sha256": normalized_sha,
            },
        )
    ):
        raise ValueError("LIB-065 catalog claim lineage drifted")
    census = _family_census(source_manifest)
    accountability = {
        "contract": "ocd-creeds-json-lib065-source-accountability-v1",
        "work_id": work_id,
        "source_path": source_logical,
        "source_bytes": len(source_bytes),
        "source_sha256": source_sha,
        "universal_newline_normalized_utf8_sha256": normalized_sha,
        "legacy_claim_semantics": "universal-newline-normalized UTF-8 retained JSON",
        "family_member_count": 43,
        "family_included_count": 7,
        "family_excluded_count": 36,
        "family_census": census,
        "json_counts": {
            key: int(state[key])
            for key in (
                "objects",
                "arrays",
                "members",
                "items",
                "strings",
                "numbers",
                "booleans",
                "nulls",
            )
        },
        "crosswalk": sorted(state["crosswalk"], key=lambda row: int(row["ordinal"])),
        "omitted_json_node_count": 0,
        "invented_json_node_count": 0,
    }
    provenance = {
        "contract": "ocd-creeds-json-lib065-provenance-v1",
        "work_id": work_id,
        "retained_source": {
            "path": source_logical,
            "bytes": len(source_bytes),
            "sha256": source_sha,
        },
        "retained_metadata": metadata,
        "rights": {
            "evidence_path": "raw/Creeds.json/README.md",
            "repository_statement": "Unlicense except eight named members; this assigned member is not named",
            "human_review": "required",
        },
        "status": {
            "candidate": "nonaccepted",
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        },
        "authority_boundary": (
            "Retained JSON bytes are authority. Legacy parser output and data JSON "
            "are diagnostics only and were not read by the converter."
        ),
    }
    return {
        "README.source.md": _readme(work_id, title, source_logical, source_sha),
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": _unresolved(work_id, source_logical, source_sha),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


__all__ = ("ASSIGNED", "CONVERTER_ID", "CONVERTER_VERSION", "_convert")
