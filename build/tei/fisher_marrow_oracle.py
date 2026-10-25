"""Producer-independent oracle for the retained Fisher Marrow OCR candidate."""

from __future__ import annotations

import ast
import hashlib
import json
import platform
from pathlib import Path
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-fisher-marrow-source-to-tei-oracle"
ORACLE_VERSION = "1"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_PAGE = re.compile(r"^(?:\d+|[IVXLCDM]+)$", re.IGNORECASE)
_HEADING = re.compile(
    r"^(?:INTRODUCTION\.?|APPENDIX\.?|RECOMMENDATIONS[.,]?|PREFACE[.,]?|"
    r"DEDICATION[.,]?|TO THE READER[.,]?|PART\s+SECOND[,.]?|"
    r"(?:CHAP|CHAPTER)\.?\s+[A-Z]+\.?|COMMANDMENT\s+[A-Z]+[,.\-]?|"
    r"SECT(?:ION)?[*.,\-]?\s*[A-Za-z0-9IVXLCDM-]*.*)$",
    re.IGNORECASE,
)
_SPEAKER = re.compile(
    r"^(?P<prefix>\s*(?:Evan|Nom|Nam|Ant|Neo|Norn|AnL|Anl|iVeo|jVeo|JVeo|"
    r"JVbm|jVbm|iVbm|JVom|jVom|iVom|Mvan|Etfan|Eran|Euan|Ecan|Eean|E\^an|"
    r"&an|£van|N\^om|No7n|Nmn|n&Qt|N\^eo|\^eo|N\^o|iVffo|iV\^o|JV\^o)"
    r"[.,;:!?*^>\-»~']*\s+)(?P<rest>.*)$"
)
_EXPECTED_SPEAKER_LINES_SHA256 = "9501f7ce4ee3eab50cbcb0e405122b3423201120a0d93a079a72a63c64763f30"
_EXPECTED_SPEAKER_OBSERVATIONS_SHA256 = "840356b52312d38a5e67338d366ad657dc3a55fa568d56c68e30008881077ccb"
_EXPECTED_REJECTED_SPEAKER_LIKE = (2899, 3080, 6290, 9115, 15083, 15957, 16997, 19112, 19687)
_EXPECTED_FALSE_HEADERS = (1656, 3155, 4579, 7146, 7602, 13507, 14521, 15798, 17422, 17645, 17725, 18094, 18676, 19162, 21145, 21276)
_EXPECTED_FALSE_HEADER_LINES_SHA256 = "7b1251913aef9078d48bbd7323e586f8861a0fee1d5bdbd11b3e69f7225074dd"
_EXPECTED_FALSE_HEADER_OBSERVATIONS_SHA256 = "ff18efcd50a730de4fe2513e91f699f32785e79747871772b5e196164c83556d"
_RETAINED_IDENTITY_LINES = {
    80: ("BY EDWARD FISHER, A.M. ", "7aa95a4d7d2d433eeed69901e959a4f580b07fa2cf536a37fdae0fae97de6ea2"),
    83: ("BY THE REV. THOMAS BOSTON, ", "d34cb9213499ab59714f868c91aacb1b6d4d4095bc6dea100e27de16d9a2a1a6"),
    87: ("A NBW EDITION. ", "eeff10105d51aecc399d3c19ec4bd079e2fecd03014dc383699949da6ca1ed85"),
    88: ("LONDON: ", "99fbe9de0e2b1838fcaab016715678920e6ca93b3d515fdff7c668ee64ca376c"),
    90: ("tINTED FOR THOMAS TE66 AND SON, 73, CHEAPSIDE; ", "8a0d1fe61b06af1b326b277b456ed593c023d589b7b10e5cdc9626bd373579f1"),
    94: ("1837. ", "99db84e2329035d41f42c205d45f11b0965290746fdd77f56fab0e9d4a59df3d"),
}
_RETAINED_ATTRIBUTION_LINES = {
    30: ('+ Maintain attribution The Google "watermark" you see on each file is essential for informing people about this project and helping them find ', "fac44e9d457d1e4157485cdfe97e72fc453349c104e5f5923ff92170ffa2ffdf"),
    31: ("additional materials through Google Book Search. Please do not remove it. ", "fcb1859562efbe7be3eadc0ce03543904a18b982f5c56bcc88ffa942a7410dd3"),
}
_EXPECTED_MEMBER_CENSUS_INCLUDED = {
    "logical_name": "retained-fisher-ocr",
    "path": "raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt",
    "role": "primary-source",
    "bytes": 1087403,
    "sha256": "14b46f1a400f8e2c8ec7612019a7769dac46daf31e10f7d6b68212351ff46dd3",
    "disposition": "included",
    "reason": "Complete retained OCR witness; every decoded line and source byte range is accounted for without treating the legacy projection as authority.",
}
_EXPECTED_MEMBER_CENSUS_EXCLUDED = (
    {
        "logical_name": "canonical-json-projection",
        "path": "data/structured-text/fisher-marrow-of-modern-divinity.json",
        "disposition": "excluded",
        "reason": "Existing canonical JSON is a comparator and downstream projection, not retained-source authority for faithful TEI reconstruction.",
    },
    {
        "logical_name": "legacy-census",
        "path": "ir/census/fisher-marrow-of-modern-divinity.ia-ocr.census.json",
        "disposition": "excluded",
        "reason": "Legacy census is a defect comparator and shares the incumbent route's interpretation; it cannot establish complete retained-member coverage.",
    },
    {
        "logical_name": "legacy-tei",
        "path": "ir/fisher/fisher-marrow-of-modern-divinity.ia-ocr.tei.xml",
        "disposition": "excluded",
        "reason": "Legacy TEI is frozen comparator output with known omissions and misattachments, not reconstruction authority.",
    },
    {
        "logical_name": "legacy-viewer-render",
        "path": "ir/fisher/fisher-marrow-of-modern-divinity.ia-ocr.viewer-dialogue.png",
        "disposition": "excluded",
        "reason": "Legacy viewer render is presentation evidence only and is not a retained source member or TEI authority.",
    },
    {
        "logical_name": "legacy-hf-projection",
        "path": "ir/fisher/hf/fisher-marrow-of-modern-divinity.ia-ocr.jsonl",
        "disposition": "excluded",
        "reason": "Legacy JSONL is a downstream projection and cannot replace the retained OCR witness or establish TEI fidelity.",
    },
    {
        "logical_name": "legacy-loss-receipt",
        "path": "ir/fisher/hf/fisher-marrow-of-modern-divinity.ia-ocr.jsonl.loss.json",
        "disposition": "excluded",
        "reason": "Legacy projection loss receipt describes the incumbent output and is retained only as comparator evidence.",
    },
    {
        "logical_name": "witness-inventory-scaffold",
        "path": "sources/fisher-marrow-of-modern-divinity/witnesses.json",
        "disposition": "excluded",
        "reason": "Empty scaffold records no retained alternate witness and is not source text for this work.",
    },
    {
        "logical_name": "source-config",
        "path": "sources/structured-text/fisher-marrow-of-modern-divinity/config.json",
        "disposition": "excluded",
        "reason": "Current metadata is a diagnostic comparator and carries the stale Edinburgh 1828 claim; retained title-page evidence governs candidate identity.",
    },
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _independent_member_census(source_manifest: SourceManifest) -> dict[str, object]:
    """Re-read the reviewed member scope without importing converter helpers."""

    record = source_manifest.record
    if (
        record.get("source_id") != "internet-archive-fisher-marrow-1837-retained-ocr"
        or record.get("work_id") != "fisher-marrow-of-modern-divinity"
    ):
        raise ValueError("Fisher retained-member identity mutation")
    members = record.get("source_members")
    exclusions = record.get("excluded_members")
    if not isinstance(members, tuple) or not isinstance(exclusions, tuple) or len(members) != 1:
        raise ValueError("Fisher retained-member census shape mutation")
    member = members[0]
    if not isinstance(member, Mapping):
        raise ValueError("Fisher retained source member is not an object")
    included = {
        "logical_name": member.get("logical_name"),
        "path": member.get("path"),
        "role": member.get("role"),
        "bytes": member.get("bytes"),
        "sha256": member.get("sha256"),
        "disposition": "included",
        "reason": member.get("reason"),
    }
    if included != _EXPECTED_MEMBER_CENSUS_INCLUDED:
        raise ValueError("Fisher retained-member inclusion authority mutation")
    authorities = record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Fisher source authority inventory mutation")
    primary = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    if len(primary) != 1 or any(
        primary[0].get(field) != member.get(source_field)
        for field, source_field in (
            ("name", "logical_name"),
            ("path", "path"),
            ("bytes", "bytes"),
            ("sha256", "sha256"),
        )
    ):
        raise ValueError("Fisher retained-member primary authority mutation")
    source_path = source_manifest.authority_path("retained-fisher-ocr")
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != member.get("bytes") or _sha(source_bytes) != member.get("sha256"):
        raise ValueError("Fisher retained-member bytes mutation")
    excluded: list[dict[str, object]] = []
    for item in exclusions:
        if not isinstance(item, Mapping):
            raise ValueError("Fisher excluded source member is not an object")
        excluded.append(
            {
                "logical_name": item.get("logical_name"),
                "path": item.get("path"),
                "disposition": "excluded",
                "reason": item.get("reason"),
            }
        )
    excluded.sort(key=lambda item: str(item.get("path")))
    if tuple(excluded) != _EXPECTED_MEMBER_CENSUS_EXCLUDED:
        raise ValueError("Fisher retained-member exclusion authority mutation")
    return {
        "contract": "ocd-fisher-marrow-member-census-v1",
        "source_id": "internet-archive-fisher-marrow-1837-retained-ocr",
        "work_id": "fisher-marrow-of-modern-divinity",
        "included": [included],
        "excluded": excluded,
        "counts": {"included": 1, "excluded": len(excluded), "total": 1 + len(excluded)},
    }


def _independent_lines(source: bytes) -> list[dict[str, object]]:
    parts = source.split(b"\n")
    result: list[dict[str, object]] = []
    cursor = 0
    for number, payload in enumerate(parts, start=1):
        has_lf = number != len(parts)
        record = payload + (b"\n" if has_lf else b"")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"retained Fisher line {number} is not UTF-8") from exc
        result.append(
            {
                "line": number,
                "byte_start": cursor,
                "byte_end": cursor + len(record),
                "has_lf": has_lf,
                "text": text,
                "text_sha256": _sha(payload),
                "record_sha256": _sha(record),
            }
        )
        cursor += len(record)
    if cursor != len(source):
        raise ValueError("independent Fisher byte accounting failed")
    return result


def _independent_regions(profile: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    source = profile.get("regions")
    if not isinstance(source, list):
        raise ValueError("Fisher regions are missing")
    regions = tuple(dict(item) for item in source if isinstance(item, dict))
    if len(regions) != 11:
        raise ValueError("Fisher region count mismatch")
    cursor = 1
    for item in regions:
        if item.get("start_line") != cursor or not isinstance(item.get("end_line"), int):
            raise ValueError("Fisher regions are not contiguous")
        cursor = int(item["end_line"]) + 1
    if cursor != 22947:
        raise ValueError("Fisher regions do not cover the retained witness")
    return regions


def _region(line: int, regions: tuple[dict[str, object], ...]) -> str:
    matches = [
        str(item["id"])
        for item in regions
        if int(item["start_line"]) <= line <= int(item["end_line"])
    ]
    if len(matches) != 1:
        raise ValueError(f"Fisher line {line} region cardinality mismatch")
    return matches[0]


def _strict_line_inventory(value: object, *, label: str, count: int) -> list[int]:
    if not isinstance(value, list) or any(type(item) is not int for item in value):
        raise ValueError(f"Fisher {label} must contain exact integers")
    if len(value) != count or len(set(value)) != count:
        raise ValueError(f"Fisher {label} must contain {count} unique lines")
    if any(item < 1 or item > 22946 for item in value):
        raise ValueError(f"Fisher {label} contains an out-of-scope line")
    return value


def _speaker_observation_records(
    lines: list[dict[str, object]], speakers: Mapping[int, Mapping[str, str]]
) -> list[dict[str, object]]:
    return [
        {
            "line": number,
            "raw_line_sha256": _sha(str(lines[number - 1]["text"]).encode("utf-8")),
            "section_prefix_sha256": _sha(str(parts["section_prefix"]).encode("utf-8")),
            "speaker_prefix_sha256": _sha(str(parts["speaker_prefix"]).encode("utf-8")),
            "body_sha256": _sha(str(parts["body"]).encode("utf-8")),
        }
        for number, parts in speakers.items()
    ]


def _speaker_observations_from_authority(
    lines: list[dict[str, object]], profile: Mapping[str, object]
) -> tuple[dict[int, dict[str, str]], tuple[int, ...]]:
    authority = profile.get("speaker_observation_authority")
    if not isinstance(authority, dict):
        raise ValueError("Fisher exact speaker-observation authority is missing")
    accepted = _strict_line_inventory(authority.get("ordered_line_numbers"), label="accepted speaker inventory", count=455)
    sections = _strict_line_inventory(authority.get("section_boundary_line_numbers"), label="section-boundary speaker inventory", count=24)
    rejected = _strict_line_inventory(
        authority.get("rejected_paragraph_continuation_line_numbers"),
        label="rejected speaker-lookalike inventory",
        count=9,
    )
    if not set(sections) <= set(accepted) or set(accepted) & set(rejected):
        raise ValueError("Fisher speaker observation inventories overlap or disagree")
    if tuple(rejected) != _EXPECTED_REJECTED_SPEAKER_LIKE:
        raise ValueError("Fisher rejected speaker-lookalike inventory differs from reviewed authority")
    line_digest = _sha(json.dumps(accepted, separators=(",", ":")).encode("utf-8"))
    if authority.get("count") != 455 or line_digest != _EXPECTED_SPEAKER_LINES_SHA256 or authority.get("ordered_line_numbers_sha256") != line_digest:
        raise ValueError("Fisher accepted speaker line authority digest mismatch")

    section_set = set(sections)
    observations: dict[int, dict[str, str]] = {}
    for number in accepted:
        text = str(lines[number - 1]["text"])
        section_prefix = ""
        candidate = text
        if number in section_set:
            split = next(
                (index for index in range(1, len(text)) if text[:index].strip().upper().startswith("SECT") and _SPEAKER.fullmatch(text[index:].lstrip()) is not None),
                None,
            )
            if split is None:
                raise ValueError(f"Fisher section-boundary speaker line {number} cannot be split from retained bytes")
            section_prefix, candidate = text[:split], text[split:]
        without_leading = candidate.lstrip()
        match = _SPEAKER.fullmatch(without_leading)
        if match is None:
            raise ValueError(f"Fisher accepted speaker line {number} lacks retained speaker evidence")
        observations[number] = {
            "section_prefix": section_prefix,
            "speaker_prefix": candidate[: len(candidate) - len(without_leading)] + match.group("prefix"),
            "body": match.group("rest"),
        }
    for number in rejected:
        if _SPEAKER.fullmatch(str(lines[number - 1]["text"]).lstrip()) is None:
            raise ValueError(f"Fisher rejected speaker-lookalike line {number} lacks retained lookalike evidence")
    observation_digest = _sha(_canonical(_speaker_observation_records(lines, observations)))
    if observation_digest != _EXPECTED_SPEAKER_OBSERVATIONS_SHA256 or authority.get("ordered_observations_sha256") != observation_digest:
        raise ValueError("Fisher exact speaker observation digest mismatch")
    return observations, tuple(rejected)


def _exact_false_header_authority(landmarks: Mapping[str, object], lines: list[dict[str, object]]) -> frozenset[int]:
    values = _strict_line_inventory(landmarks.get("false_running_header_lines"), label="false-running-header inventory", count=16)
    if tuple(values) != _EXPECTED_FALSE_HEADERS:
        raise ValueError("Fisher false-running-header inventory differs from reviewed authority")
    line_digest = _sha(json.dumps(values, separators=(",", ":")).encode("utf-8"))
    observations = [
        {"line": number, "raw_line_sha256": _sha(str(lines[number - 1]["text"]).encode("utf-8"))}
        for number in values
    ]
    observation_digest = _sha(_canonical(observations))
    if (
        line_digest != _EXPECTED_FALSE_HEADER_LINES_SHA256
        or landmarks.get("false_running_header_line_numbers_sha256") != line_digest
        or observation_digest != _EXPECTED_FALSE_HEADER_OBSERVATIONS_SHA256
        or landmarks.get("false_running_header_observations_sha256") != observation_digest
    ):
        raise ValueError("Fisher false-running-header retained evidence digest mismatch")
    return frozenset(values)


def _direct_title_page_identity(source: bytes, profile: Mapping[str, object], policy: Mapping[str, object]) -> dict[str, str]:
    lines = source.split(b"\n")
    evidence_rows = []
    for number, (expected_text, expected_sha) in _RETAINED_IDENTITY_LINES.items():
        payload = lines[number - 1]
        if payload.decode("utf-8") != expected_text or _sha(payload) != expected_sha:
            raise ValueError(f"retained Fisher title-page line {number} does not match its exact evidence")
        evidence_rows.append({"line": number, "text": expected_text, "sha256": expected_sha})
    evidence = profile.get("title_page_evidence")
    if not isinstance(evidence, dict) or evidence.get("lines") != evidence_rows:
        raise ValueError("Fisher title-page evidence binding mutation")
    rule = str(evidence.get("normalization_rule"))
    if (
        "For line 87 only, replace the exact OCR form NBW with NEW" not in rule
        or "For line 90 only, replace the exact OCR forms tINTED with PRINTED and TE66 with TEGG" not in rule
        or "No other OCR repair" not in rule
    ):
        raise ValueError("Fisher title-page normalization rule mutation")
    attribution_rows = []
    for number, (expected_text, expected_sha) in _RETAINED_ATTRIBUTION_LINES.items():
        payload = lines[number - 1]
        if payload.decode("utf-8") != expected_text or _sha(payload) != expected_sha:
            raise ValueError(f"retained Fisher Google attribution line {number} does not match its exact evidence")
        attribution_rows.append({"line": number, "text": expected_text, "sha256": expected_sha})
    attribution = profile.get("google_attribution_evidence")
    if (
        not isinstance(attribution, dict)
        or attribution.get("lines") != attribution_rows
        or "do not remove" not in str(attribution.get("obligation", "")).lower()
    ):
        raise ValueError("Fisher Google attribution evidence or obligation mutation")
    imprint = lines[89].decode().strip()
    normalized_imprint = imprint.replace("tINTED", "PRINTED").replace("TE66", "TEGG")
    publisher_match = re.fullmatch(r"PRINTED FOR ([^,]+),.*", normalized_imprint)
    if publisher_match is None:
        raise ValueError("Fisher retained publisher imprint is not interpretable by the declared rule")
    derived = {
        "title": " ".join(lines[index - 1].decode().strip() for index in (63, 65, 67, 69)).rstrip(":").title().replace(" Of ", " of "),
        "author": lines[79].decode().strip().removeprefix("BY ").title(),
        "contributor": lines[82].decode().strip().removeprefix("BY ").rstrip(",").title() + " (notes)",
        "edition": lines[86].decode().strip().replace("NBW", "NEW").rstrip(".").title(),
        "place": lines[87].decode().strip().rstrip(":").title(),
        "publisher": publisher_match.group(1).title().replace(" And ", " and "),
        "year": lines[93].decode().strip().rstrip("."),
    }
    profile_identity = profile.get("witness_identity")
    header_identity = policy.get("tei_header")
    if not isinstance(profile_identity, dict) or not isinstance(header_identity, dict):
        raise ValueError("Fisher profile or policy identity is invalid")
    for name, derived_value in derived.items():
        profile_name = "edition_statement" if name == "edition" else name
        if profile_identity.get(profile_name) != derived_value or header_identity.get(name) != derived_value:
            raise ValueError(f"Fisher {name} was invented independently of retained title-page bytes")
    return derived


def _independent_kind(line: int, text: str, false_headers: frozenset[int], speakers: Mapping[int, Mapping[str, str]]) -> str:
    stripped = text.strip()
    if line in false_headers:
        return "false-running-header-content"
    if line >= 1285 and _PAGE.fullmatch(stripped):
        return "page-marker-candidate"
    if line in speakers:
        return "section-boundary-dialogue-line" if speakers[line]["section_prefix"] else "dialogue-line"
    if _HEADING.fullmatch(stripped):
        return "heading-line"
    if any(mark in text for mark in ("*", "§", "†", "‡")):
        return "inline-uncertainty-line"
    return "blank-line" if not text else "text-line"


def _line_text(node: etree._Element, extraction: str) -> str:
    if extraction == "element-text":
        return node.text or ""
    if extraction == "speaker-plus-paragraph":
        children = [item for item in node if isinstance(item.tag, str)]
        if [etree.QName(item).localname for item in children] != ["speaker", "p"]:
            raise ValueError("Fisher dialogue structure mutation")
        return (children[0].text or "") + (children[1].text or "")
    if extraction == "section-heading-plus-speaker-paragraph":
        children = [item for item in node if isinstance(item.tag, str)]
        if [etree.QName(item).localname for item in children[:2]] != ["head", "sp"]:
            raise ValueError("Fisher section-boundary dialogue structure mutation")
        speech = [item for item in children[1] if isinstance(item.tag, str)]
        if [etree.QName(item).localname for item in speech] != ["speaker", "p"]:
            raise ValueError("Fisher section-boundary speaker structure mutation")
        return (children[0].text or "") + (speech[0].text or "") + (speech[1].text or "")
    raise ValueError("Fisher extraction mode mutation")


def _verify_dialogue_components(
    node: etree._Element, extraction: str, expected: Mapping[str, str]
) -> None:
    if extraction == "speaker-plus-paragraph":
        speaker, paragraph = node[0], node[1]
        observed = {
            "section_prefix": "",
            "speaker_prefix": speaker.text or "",
            "body": paragraph.text or "",
        }
    elif extraction == "section-heading-plus-speaker-paragraph":
        heading, speech = node[0], node[1]
        observed = {
            "section_prefix": heading.text or "",
            "speaker_prefix": speech[0].text or "",
            "body": speech[1].text or "",
        }
    else:
        return
    if observed != dict(expected):
        raise ValueError("Fisher TEI dialogue component boundary mutation")


def _verify_header(tei: etree._Element, policy: Mapping[str, object], source_sha: str, identity: Mapping[str, str]) -> None:
    values = policy.get("tei_header")
    if not isinstance(values, dict):
        raise ValueError("Fisher header policy is invalid")
    ns = {"tei": _TEI_NS}
    def one(path: str) -> etree._Element:
        matches = tei.xpath(path, namespaces=ns)
        if len(matches) != 1:
            raise ValueError(f"Fisher TEI header cardinality mutation at {path}")
        return matches[0]

    expected_text = {
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title": identity["title"],
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author": identity["author"],
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name": identity["contributor"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:title": identity["title"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:author": identity["author"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:editor": identity["contributor"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:edition": identity["edition"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:pubPlace": identity["place"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:publisher": identity["publisher"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:date": identity["year"],
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno": source_sha,
    }
    for path, expected in expected_text.items():
        if (one(path).text or "") != expected:
            raise ValueError(f"Fisher 1837 title-page identity mutation at {path}")
    availability = one("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability")
    if availability.get("status") != values["availability_status"] or (
        one("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p").text or ""
    ) != values["rights_statement"]:
        raise ValueError("Fisher rights-status mutation")
    ptr = one("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr")
    date = one("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:date")
    if ptr.get("target") != values["source_url"] or date.get("when") != identity["year"]:
        raise ValueError("Fisher source URL or edition date mutation")
    header = one("./tei:teiHeader")
    if any(token in etree.tostring(header, encoding="unicode") for token in ("J. and D. Collie", "Edinburgh 1828", "1828")):
        raise ValueError("stale Fisher 1828 authority leaked into candidate TEI")


def _verify_candidate(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    source: bytes,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
    accountability: Mapping[str, object],
) -> None:
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "Fisher accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"Fisher accountability schema failure: {errors[0].message}")
    source_lines = _independent_lines(source)
    identity = _direct_title_page_identity(source, profile, policy)
    regions = _independent_regions(profile)
    landmarks = profile.get("landmarks")
    if not isinstance(landmarks, dict) or not isinstance(landmarks.get("false_running_header_lines"), list):
        raise ValueError("Fisher landmark policy mutation")
    false_headers = _exact_false_header_authority(landmarks, source_lines)
    speakers, rejected_speaker_like = _speaker_observations_from_authority(source_lines, profile)
    section_speaker_count = sum(bool(item["section_prefix"]) for item in speakers.values())
    if (
        len(speakers) != 455
        or section_speaker_count != 24
        or len(rejected_speaker_like) != 9
        or tuple(landmarks.get("paragraph_continuation_speaker_like_lines", ())) != rejected_speaker_like
        or policy.get("required_high_confidence_speaker_count") != 455
        or policy.get("required_section_boundary_speaker_count") != 24
        or policy.get("required_rejected_paragraph_continuation_speaker_like_count") != 9
    ):
        raise ValueError("Fisher independent paragraph-aware speaker census mutation")
    observed_crosswalk = accountability.get("crosswalk")
    if not isinstance(observed_crosswalk, list) or len(observed_crosswalk) != len(source_lines):
        raise ValueError("Fisher complete line crosswalk count mutation")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Fisher candidate TEI is not parseable") from exc
    if etree.QName(tei).text != f"{{{_TEI_NS}}}TEI":
        raise ValueError("Fisher candidate is not TEI")
    _verify_header(tei, policy, _sha(source), identity)
    if not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError(f"Fisher TEI P5 validation failure: {compiled_schema().error_log.last_error}")

    ns = {"tei": _TEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"}
    ordered_ids = [
        value
        for value in tei.xpath("//tei:text//@xml:id", namespaces=ns)
        if str(value).startswith("fisher-line-")
    ]
    expected_ids = [f"fisher-line-{index:05d}" for index in range(1, 22947)]
    if ordered_ids != expected_ids:
        raise ValueError("Fisher TEI line omission, duplication, or reorder")
    line_nodes = {
        str(node.get(_XML_ID)): node
        for node in tei.xpath("//tei:text//*[@xml:id]", namespaces=ns)
        if str(node.get(_XML_ID)).startswith("fisher-line-")
    }
    if set(line_nodes) != set(expected_ids):
        raise ValueError("Fisher TEI line target inventory mutation")
    if len(tei.xpath("//tei:text//tei:sp", namespaces=ns)) != 455 or len(
        tei.xpath("//tei:text//tei:sp[contains(@ana, 'section-boundary-speaker')]", namespaces=ns)
    ) != 24:
        raise ValueError("Fisher TEI speaker occurrence census mutation")

    expected_crosswalk: list[dict[str, object]] = []
    page_lines: list[int] = []
    false_count = 0
    for raw in source_lines:
        number = int(raw["line"])
        text = str(raw["text"])
        kind = _independent_kind(number, text, false_headers, speakers)
        region_id = _region(number, regions)
        identifier = f"fisher-line-{number:05d}"
        extraction = (
            "section-heading-plus-speaker-paragraph"
            if kind == "section-boundary-dialogue-line"
            else ("speaker-plus-paragraph" if kind == "dialogue-line" else "element-text")
        )
        tag = "div" if kind == "section-boundary-dialogue-line" else ("sp" if kind == "dialogue-line" else ("head" if kind == "heading-line" else "ab"))
        expected_crosswalk.append(
            {
                "feature_id": identifier,
                **raw,
                "region": region_id,
                "kind": kind,
                "disposition": "represented",
                "tei_tag": tag,
                "tei_xml_id": identifier,
                "tei_selector": f"#{identifier}",
                "extraction": extraction,
            }
        )
        node = line_nodes[identifier]
        if etree.QName(node).localname != tag:
            raise ValueError(f"Fisher line {number} target cardinality or kind mutation")
        if _line_text(node, extraction) != text:
            raise ValueError(f"Fisher line {number} text or uncertainty mutation")
        if kind in {"dialogue-line", "section-boundary-dialogue-line"}:
            _verify_dialogue_components(node, extraction, speakers[number])
        region_matches = node.xpath("ancestor::tei:div[starts-with(@xml:id, 'fisher-region-')]", namespaces=ns)
        if len(region_matches) != 1 or region_matches[0].get(_XML_ID) != f"fisher-region-{region_id}":
            raise ValueError(f"Fisher line {number} structural misattachment")
        semantic_value = node.get("ana") if kind == "dialogue-line" else node.get("type")
        expected_semantic = (
            "#source-dialogue-line"
            if kind == "dialogue-line"
            else ("source-section" if kind == "section-boundary-dialogue-line" else ("source-heading" if kind == "heading-line" else kind))
        )
        if semantic_value != expected_semantic:
            raise ValueError(f"Fisher line {number} semantic kind mutation")
        if kind == "page-marker-candidate":
            page_lines.append(number)
            if node.get("ana") != "#page-marker-candidate":
                raise ValueError("Fisher page-marker candidate certainty mutation")
        if kind == "inline-uncertainty-line" and node.get("ana") != "#uncorrected-ocr #inline-mark":
            raise ValueError("Fisher inline uncertainty annotation lost")
        if kind == "false-running-header-content":
            false_count += 1
            if node.get("ana") != "#substantive-content #not-a-running-header":
                raise ValueError("Fisher substantive false header was not retained as content")
    if observed_crosswalk != expected_crosswalk:
        raise ValueError("Fisher accountability was weakened or invented")
    if (
        len(page_lines) != policy.get("required_page_marker_candidate_count")
        or false_count != policy.get("required_false_running_header_content_count")
        or accountability.get("high_confidence_speaker_count") != 455
        or accountability.get("section_boundary_speaker_count") != 24
        or accountability.get("rejected_paragraph_continuation_speaker_like_count") != 9
    ):
        raise ValueError("Fisher page-marker or false-header census mutation")
    page_digest = _sha(json.dumps(page_lines, separators=(",", ":")).encode("utf-8"))
    if page_digest != landmarks.get("page_marker_candidate_line_numbers_sha256"):
        raise ValueError("Fisher page-marker candidate order mutation")

    structural = {
        "recommendations": (242, 538, "front"),
        "part-two-front": (16577, 16775, "body"),
        "appendix": (21186, 22946, "back"),
    }
    for region_id, (start, end, part) in structural.items():
        region_nodes = tei.xpath(
            f"./tei:text/tei:{part}/tei:div[@xml:id=$identifier]",
            identifier=f"fisher-region-{region_id}",
            namespaces=ns,
        )
        if len(region_nodes) != 1:
            raise ValueError(f"Fisher {region_id} region placement mutation")
        ids = [
            value
            for value in region_nodes[0].xpath(".//@xml:id", namespaces=ns)
            if str(value).startswith("fisher-line-")
        ]
        if ids != [f"fisher-line-{number:05d}" for number in range(start, end + 1)]:
            raise ValueError(f"Fisher {region_id} source coverage mutation")


def _local_module_path(root: Path, module: str) -> Path | None:
    if not module or any(part in {"", ".", ".."} for part in module.split(".")):
        return None
    stem = root.joinpath(*module.split("."))
    candidates = (stem.with_suffix(".py"), stem / "__init__.py")
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("oracle import closure escaped repository root") from exc
        if resolved.is_file():
            return resolved
    return None


def _resolved_import_names(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        relative = path.relative_to(root)
        package = list(relative.parts[:-1])
        ascend = node.level - 1
        if ascend > len(package):
            raise ValueError("oracle relative import escaped repository package")
        prefix = package[: len(package) - ascend]
        suffix = node.module.split(".") if node.module else []
        base = ".".join([*prefix, *suffix])
    names = [base] if base else []
    for alias in node.names:
        if alias.name != "*":
            names.append(f"{base}.{alias.name}" if base else alias.name)
    return tuple(names)


def _package_initializers(root: Path, path: Path) -> tuple[Path, ...]:
    relative = path.relative_to(root)
    initializers: list[Path] = []
    for depth in range(1, len(relative.parts)):
        candidate = root.joinpath(*relative.parts[:depth], "__init__.py")
        if candidate.is_file():
            initializers.append(candidate.resolve(strict=True))
    return tuple(initializers)


def _repository_import_closure(root: Path, entry: Path, forbidden: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    entry = entry.resolve(strict=True)
    try:
        entry.relative_to(root)
    except ValueError as exc:
        raise ValueError("oracle closure entry is outside repository root") from exc
    pending = [entry, *_package_initializers(root, entry)]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec"}:
                raise ValueError("Fisher oracle closure contains dynamic import or execution")
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = _resolved_import_names(path, root, node)
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"Fisher oracle closure contains forbidden import {name}")
                dependency = _local_module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
                    pending.extend(_package_initializers(root, dependency))
    return tuple(
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    return _sha(_canonical(_repository_import_closure(root, Path(__file__), forbidden)))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    expected_source_manifest = source_manifest.path.relative_to(root).as_posix()
    manifest = candidate.manifest
    if (
        manifest.get("status") != "nonaccepted"
        or manifest.get("source_manifest") != {"path": expected_source_manifest, "sha256": source_manifest.sha256}
        or manifest.get("converter") != source_manifest.record["converter"]
        or manifest.get("package_schema") != source_manifest.record["package_schema"]
    ):
        raise ValueError("Fisher candidate authority binding mutation")
    source = source_manifest.authority_path("retained-fisher-ocr").read_bytes()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "Fisher reconstruction profile")
    policy = _strict_json(policy_bytes, "Fisher validation policy")
    retained_identity = _direct_title_page_identity(source, profile, policy)
    member_census = _independent_member_census(source_manifest)
    accountability = _strict_json(candidate.member_bytes("source-accountability.json"), "Fisher source accountability")
    _verify_candidate(source_manifest, candidate, source, profile, policy, accountability)

    provenance = _strict_json(candidate.member_bytes("provenance.json"), "Fisher provenance")
    expected_authorities = {
        str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")}
        for item in source_manifest.record["authorities"]
    }
    identity = provenance.get("witness_identity")
    rights = provenance.get("rights")
    if (
        provenance.get("contract") != "ocd-fisher-marrow-candidate-provenance-v1"
        or provenance.get("status") != "nonaccepted"
        or provenance.get("authorities") != expected_authorities
        or provenance.get("retained_member_census") != member_census
        or provenance.get("retained_member_census_sha256") != _sha(_canonical(member_census))
        or identity != profile.get("witness_identity")
        or provenance.get("retained_title_page_identity") != retained_identity
        or not isinstance(identity, dict)
        or identity.get("place") != "London"
        or identity.get("publisher") != "Thomas Tegg and Son"
        or identity.get("year") != "1837"
        or identity.get("legacy_edinburgh_1828_claim_is_current_authority") is not False
        or rights != {"publication_authorized": False, "status": "unresolved-human-review-required"}
        or provenance.get("source_bytes_embedded_in_candidate") is not False
    ):
        raise ValueError("Fisher provenance, identity, or rights mutation")
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
        if line.strip()
    ]
    if {item.get("id") for item in unresolved} != set(policy.get("required_unresolved_ids", [])):
        raise ValueError("Fisher unresolved ledger mutation")
    readme = candidate.member_bytes("README.source.md")
    for phrase in (
        b"London, Thomas Tegg and Son, 1837",
        b"22,946-line",
        b"not human acceptance",
        b"retain the Google watermark and Google Book Search attribution",
        b"do not remove it",
    ):
        if phrase not in readme:
            raise ValueError("Fisher candidate README mutation")

    xsd = source_manifest.authority_path("tei-p5-xsd").read_bytes()
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(xsd),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
