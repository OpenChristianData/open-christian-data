"""Direct retained Fisher OCR to immutable nonaccepted TEI candidate conversion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-fisher-marrow-retained-ocr-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "fisher-marrow-complete-line-accountability-v1"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_PAGE_RE = re.compile(r"^(?:\d+|[IVXLCDM]+)$", re.IGNORECASE)
_HEADING_RE = re.compile(
    r"^(?:INTRODUCTION\.?|APPENDIX\.?|RECOMMENDATIONS[.,]?|PREFACE[.,]?|"
    r"DEDICATION[.,]?|TO THE READER[.,]?|PART\s+SECOND[,.]?|"
    r"(?:CHAP|CHAPTER)\.?\s+[A-Z]+\.?|COMMANDMENT\s+[A-Z]+[,.\-]?|"
    r"SECT(?:ION)?[*.,\-]?\s*[A-Za-z0-9IVXLCDM-]*.*)$",
    re.IGNORECASE,
)
_SPEAKER_TOKEN = (
    r"Evan|Nom|Nam|Ant|Neo|Norn|AnL|Anl|iVeo|jVeo|JVeo|JVbm|jVbm|iVbm|"
    r"JVom|jVom|iVom|Mvan|Etfan|Eran|Euan|Ecan|Eean|E\^an|&an|£van|"
    r"N\^om|No7n|Nmn|n&Qt|N\^eo|\^eo|N\^o|iVffo|iV\^o|JV\^o"
)
_SPEAKER_RE = re.compile(
    rf"^(?P<prefix>\s*(?:{_SPEAKER_TOKEN})[.,;:!?*^>\-»~']*\s+)(?P<rest>.*)$"
)
_SECTION_PREFIX_RE = re.compile(
    r"^(?P<prefix>SECT(?:ION)?[*.,\-]?\s*)"
    r"(?P<num>[A-Za-z0-9iIvVxXlLmM-]+)?(?P<rest>.*)$",
    re.IGNORECASE,
)
_TITLE_EVIDENCE = {
    80: ("BY EDWARD FISHER, A.M. ", "7aa95a4d7d2d433eeed69901e959a4f580b07fa2cf536a37fdae0fae97de6ea2"),
    83: ("BY THE REV. THOMAS BOSTON, ", "d34cb9213499ab59714f868c91aacb1b6d4d4095bc6dea100e27de16d9a2a1a6"),
    87: ("A NBW EDITION. ", "eeff10105d51aecc399d3c19ec4bd079e2fecd03014dc383699949da6ca1ed85"),
    88: ("LONDON: ", "99fbe9de0e2b1838fcaab016715678920e6ca93b3d515fdff7c668ee64ca376c"),
    90: ("tINTED FOR THOMAS TE66 AND SON, 73, CHEAPSIDE; ", "8a0d1fe61b06af1b326b277b456ed593c023d589b7b10e5cdc9626bd373579f1"),
    94: ("1837. ", "99db84e2329035d41f42c205d45f11b0965290746fdd77f56fab0e9d4a59df3d"),
}
_ATTRIBUTION_EVIDENCE = {
    30: ('+ Maintain attribution The Google "watermark" you see on each file is essential for informing people about this project and helping them find ', "fac44e9d457d1e4157485cdfe97e72fc453349c104e5f5923ff92170ffa2ffdf"),
    31: ("additional materials through Google Book Search. Please do not remove it. ", "fcb1859562efbe7be3eadc0ce03543904a18b982f5c56bcc88ffa942a7410dd3"),
}
_EXPECTED_SPEAKER_LINES_SHA256 = "9501f7ce4ee3eab50cbcb0e405122b3423201120a0d93a079a72a63c64763f30"
_EXPECTED_SPEAKER_OBSERVATIONS_SHA256 = "840356b52312d38a5e67338d366ad657dc3a55fa568d56c68e30008881077ccb"
_EXPECTED_FALSE_HEADERS = (1656, 3155, 4579, 7146, 7602, 13507, 14521, 15798, 17422, 17645, 17725, 18094, 18676, 19162, 21145, 21276)
_EXPECTED_FALSE_HEADER_LINES_SHA256 = "7b1251913aef9078d48bbd7323e586f8861a0fee1d5bdbd11b3e69f7225074dd"
_EXPECTED_FALSE_HEADER_OBSERVATIONS_SHA256 = "ff18efcd50a730de4fe2513e91f699f32785e79747871772b5e196164c83556d"
_EXPECTED_MEMBER_CENSUS_EXCLUDED_PATHS = (
    "data/structured-text/fisher-marrow-of-modern-divinity.json",
    "ir/census/fisher-marrow-of-modern-divinity.ia-ocr.census.json",
    "ir/fisher/fisher-marrow-of-modern-divinity.ia-ocr.tei.xml",
    "ir/fisher/fisher-marrow-of-modern-divinity.ia-ocr.viewer-dialogue.png",
    "ir/fisher/hf/fisher-marrow-of-modern-divinity.ia-ocr.jsonl",
    "ir/fisher/hf/fisher-marrow-of-modern-divinity.ia-ocr.jsonl.loss.json",
    "sources/fisher-marrow-of-modern-divinity/witnesses.json",
    "sources/structured-text/fisher-marrow-of-modern-divinity/config.json",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _member_census(source_manifest: SourceManifest) -> dict[str, object]:
    """Keep the retained-member boundary inside the pinned converter."""

    source_manifest.verify()
    record = source_manifest.record
    if (
        record.get("source_id") != "internet-archive-fisher-marrow-1837-retained-ocr"
        or record.get("work_id") != "fisher-marrow-of-modern-divinity"
    ):
        raise ValueError("Fisher retained-member identity mismatch")
    source_members = record.get("source_members")
    excluded_members = record.get("excluded_members")
    authorities = record.get("authorities")
    if (
        not isinstance(source_members, tuple)
        or not isinstance(excluded_members, tuple)
        or not isinstance(authorities, tuple)
        or len(source_members) != 1
    ):
        raise ValueError("Fisher retained-member census shape mismatch")
    member = source_members[0]
    if not isinstance(member, Mapping):
        raise ValueError("Fisher retained source member is invalid")
    primary = [
        authority
        for authority in authorities
        if isinstance(authority, Mapping) and authority.get("role") == "primary-source"
    ]
    if len(primary) != 1:
        raise ValueError("Fisher retained-member primary authority is ambiguous")
    included = {
        "logical_name": member.get("logical_name"),
        "path": member.get("path"),
        "role": member.get("role"),
        "bytes": member.get("bytes"),
        "sha256": member.get("sha256"),
        "disposition": "included",
        "reason": member.get("reason"),
    }
    if (
        included["logical_name"] != primary[0].get("name")
        or included["path"] != primary[0].get("path")
        or included["role"] != "primary-source"
        or included["bytes"] != primary[0].get("bytes")
        or included["sha256"] != primary[0].get("sha256")
        or not isinstance(included["reason"], str)
        or not included["reason"].strip()
    ):
        raise ValueError("Fisher retained-member authority mismatch")
    source_path = source_manifest.authority_path("retained-fisher-ocr")
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != included["bytes"] or _sha(source_bytes) != included["sha256"]:
        raise ValueError("Fisher retained-member bytes drifted")
    excluded = []
    names: set[str] = {str(included["logical_name"])}
    paths: set[str] = {str(included["path"])}
    for item in excluded_members:
        if not isinstance(item, Mapping):
            raise ValueError("Fisher excluded source member is invalid")
        name = item.get("logical_name")
        path = item.get("path")
        reason = item.get("reason")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(path, str)
            or not path.strip()
            or not isinstance(reason, str)
            or not reason.strip()
            or name in names
            or path in paths
        ):
            raise ValueError("Fisher excluded-member census is invalid")
        names.add(name)
        paths.add(path)
        excluded.append(
            {
                "logical_name": name,
                "path": path,
                "disposition": "excluded",
                "reason": reason,
            }
        )
    excluded.sort(key=lambda item: str(item["path"]))
    if tuple(str(item["path"]) for item in excluded) != _EXPECTED_MEMBER_CENSUS_EXCLUDED_PATHS:
        raise ValueError("Fisher excluded-member census differs from reviewed scope")
    return {
        "contract": "ocd-fisher-marrow-member-census-v1",
        "source_id": "internet-archive-fisher-marrow-1837-retained-ocr",
        "work_id": "fisher-marrow-of-modern-divinity",
        "included": [included],
        "excluded": excluded,
        "counts": {"included": 1, "excluded": len(excluded), "total": 1 + len(excluded)},
    }


def _tei(name: str, attributes: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    node = etree.Element(f"{{{_TEI_NS}}}{name}")
    for key, value in (attributes or {}).items():
        node.set(_XML_ID if key == "xml:id" else key, value)
    node.text = text
    return node


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    value = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if (
        not isinstance(value, dict)
        or value.get("contract") != "ocd-fisher-marrow-reconstruction-profile-v1"
        or value.get("profile_id") != _PROFILE_ID
        or value.get("version") != 1
    ):
        raise ValueError("Fisher reconstruction profile identity mismatch")
    return value


def _source_lines(source: bytes) -> list[dict[str, object]]:
    parts = source.split(b"\n")
    records: list[dict[str, object]] = []
    offset = 0
    for index, payload in enumerate(parts, start=1):
        has_lf = index < len(parts)
        record = payload + (b"\n" if has_lf else b"")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Fisher retained OCR line {index} is not UTF-8") from exc
        records.append(
            {
                "line": index,
                "byte_start": offset,
                "byte_end": offset + len(record),
                "has_lf": has_lf,
                "text": text,
                "text_sha256": _sha(payload),
                "record_sha256": _sha(record),
            }
        )
        offset += len(record)
    if offset != len(source):
        raise ValueError("Fisher retained OCR byte accounting is not contiguous")
    return records


def _regions(profile: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    regions = profile.get("regions")
    if not isinstance(regions, list) or len(regions) != 11:
        raise ValueError("Fisher profile region inventory mismatch")
    normalized = tuple(dict(item) for item in regions if isinstance(item, dict))
    if len(normalized) != len(regions):
        raise ValueError("Fisher profile region is invalid")
    expected = 1
    for region in normalized:
        if region.get("start_line") != expected or not isinstance(region.get("end_line"), int):
            raise ValueError("Fisher profile regions are not contiguous")
        expected = int(region["end_line"]) + 1
    if expected != 22947:
        raise ValueError("Fisher profile regions do not cover the complete witness")
    return normalized


def _region_for(line: int, regions: tuple[dict[str, object], ...]) -> dict[str, object]:
    for region in regions:
        if int(region["start_line"]) <= line <= int(region["end_line"]):
            return region
    raise ValueError(f"Fisher line {line} has no region")


def _running_header(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    upper = stripped.upper()
    if re.match(r"^(?:CHAP|CHAPTER)\.?\s+", stripped, re.IGNORECASE):
        return not bool(re.fullmatch(r"(?:CHAP|CHAPTER)\.?\s+[A-Z]+\.?", stripped))
    if re.match(r"^PAR[TI]\b", stripped, re.IGNORECASE):
        return not bool(re.fullmatch(r"PART\s+SECOND[,.]?", stripped, re.IGNORECASE))
    return (
        ("MARROW OF MODERN DIVINITY" in upper and len(stripped) < 70)
        or upper.startswith("THE MARROW OF")
        or upper.startswith("MODERN DIVINITY")
        or upper in {"THE MARROW", "MARROW", "OF MODERN DIVINITY", "MARROW OF", "MARROW OF MODERN"}
    )


def _section_parts(text: str) -> tuple[str, str, str] | None:
    value = text.strip()
    match = _SECTION_PREFIX_RE.fullmatch(value)
    if match is None:
        return None
    number = match.group("num")
    rest = match.group("rest")
    if value.upper().startswith("SECTION") and number:
        return "heading", text, ""
    if number and rest.count("—") + rest.count("–") >= 2:
        return "synopsis", "", text
    if number and not re.match(r"^[*.,\-\s]*[—–-]", rest):
        if re.search(r"[—–-]\s*\d", rest) or rest.count("—") + rest.count("–") >= 2:
            return "synopsis", "", text
    separator = re.search(r"[—–]", rest)
    if separator:
        absolute_end = value.find(rest) + separator.end()
        after = value[absolute_end:]
        if re.match(r"\s*(?:Of|Or)\b", after, re.IGNORECASE):
            return "heading", text, ""
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()):]
        core = text.strip()
        return "boundary", leading + core[:absolute_end], core[absolute_end:] + trailing
    if number and re.match(r"\s*(?:But|And|Ant|Evan|Nom|Nam|Neo|Norn|AnL|iVeo|JVbm)\b", rest, re.IGNORECASE):
        prefix_end = value.find(rest)
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()):]
        core = text.strip()
        return "boundary", leading + core[:prefix_end], core[prefix_end:] + trailing
    return "synopsis", "", text


def _speaker_semantics(lines: list[dict[str, object]]) -> tuple[dict[int, dict[str, str]], tuple[int, ...]]:
    speakers: dict[int, dict[str, str]] = {}
    rejected: list[int] = []
    in_paragraph = False
    for line in lines[1284:]:
        number = int(line["line"])
        text = str(line["text"])
        stripped = text.strip()
        if not stripped:
            in_paragraph = False
            continue
        if _PAGE_RE.fullmatch(stripped) or _running_header(text):
            continue
        section = _section_parts(text)
        if section and section[0] == "synopsis":
            continue
        candidate = section[2] if section and section[0] == "boundary" else text
        candidate_lstripped = candidate.lstrip()
        match = _SPEAKER_RE.fullmatch(candidate_lstripped)
        accepted = match is not None and (not in_paragraph or section is not None)
        if accepted and match is not None:
            speakers[number] = {
                "section_prefix": section[1] if section and section[0] == "boundary" else "",
                "speaker_prefix": candidate[: len(candidate) - len(candidate_lstripped)] + match.group("prefix"),
                "body": match.group("rest"),
            }
        elif match is not None and in_paragraph and section is None:
            rejected.append(number)
        in_paragraph = True
    return speakers, tuple(rejected)


def _source_identity(source: bytes, profile: Mapping[str, object], policy: Mapping[str, object]) -> dict[str, str]:
    parts = source.split(b"\n")
    observed = []
    for line, (text, digest) in _TITLE_EVIDENCE.items():
        payload = parts[line - 1]
        if payload.decode("utf-8") != text or _sha(payload) != digest:
            raise ValueError(f"Fisher title-page evidence line {line} drifted")
        observed.append({"line": line, "text": text, "sha256": digest})
    evidence = profile.get("title_page_evidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("lines") != observed
        or "For line 87 only, replace the exact OCR form NBW with NEW" not in str(evidence.get("normalization_rule"))
        or "For line 90 only, replace the exact OCR forms tINTED with PRINTED and TE66 with TEGG" not in str(evidence.get("normalization_rule"))
        or "No other OCR repair is authorized" not in str(evidence.get("normalization_rule"))
    ):
        raise ValueError("Fisher title-page evidence or normalization rule drifted")
    attribution_rows = []
    for line, (text, digest) in _ATTRIBUTION_EVIDENCE.items():
        payload = parts[line - 1]
        if payload.decode("utf-8") != text or _sha(payload) != digest:
            raise ValueError(f"Fisher Google attribution evidence line {line} drifted")
        attribution_rows.append({"line": line, "text": text, "sha256": digest})
    attribution = profile.get("google_attribution_evidence")
    if (
        not isinstance(attribution, dict)
        or attribution.get("lines") != attribution_rows
        or "do not remove" not in str(attribution.get("obligation", "")).lower()
    ):
        raise ValueError("Fisher Google attribution authority drifted")
    title = " ".join(parts[line - 1].decode().strip() for line in (63, 65, 67, 69)).rstrip(":").title().replace(" Of ", " of ")
    author = parts[79].decode().strip().removeprefix("BY ").title()
    contributor = parts[82].decode().strip().removeprefix("BY ").rstrip(",").title() + " (notes)"
    place = parts[87].decode().strip().rstrip(":").title()
    imprint = parts[89].decode().strip().replace("tINTED", "PRINTED").replace("TE66", "TEGG")
    imprint_match = re.fullmatch(r"PRINTED FOR (?P<publisher>[^,]+),.*", imprint)
    if imprint_match is None:
        raise ValueError("Fisher OCR-damaged publisher imprint cannot be interpreted by the bound rule")
    publisher = imprint_match.group("publisher").title().replace(" And ", " and ")
    year = parts[93].decode().strip().rstrip(".")
    edition = parts[86].decode().strip().replace("NBW", "NEW").rstrip(".").title()
    identity = {
        "title": title,
        "author": author,
        "contributor": contributor,
        "edition": edition,
        "place": place,
        "publisher": publisher,
        "year": year,
    }
    profile_identity = profile.get("witness_identity")
    header = policy.get("tei_header")
    if not isinstance(profile_identity, dict) or not isinstance(header, dict):
        raise ValueError("Fisher identity authorities are invalid")
    for key, value in identity.items():
        profile_key = "edition_statement" if key == "edition" else key
        if profile_identity.get(profile_key) != value or header.get(key) != value:
            raise ValueError(f"Fisher {key} authority contradicts retained title-page evidence")
    return identity


def _false_header_authority(
    landmarks: Mapping[str, object], lines: list[dict[str, object]] | None = None
) -> frozenset[int]:
    values = landmarks.get("false_running_header_lines")
    if not isinstance(values, list):
        raise ValueError("Fisher false-running-header profile must be a list")
    if any(type(item) is not int for item in values):
        raise ValueError("Fisher false-running-header lines must be exact integers")
    if any(item < 1 or item > 22946 for item in values):
        raise ValueError("Fisher false-running-header line is outside retained scope")
    result = frozenset(values)
    if len(values) != 16 or len(result) != 16:
        raise ValueError("Fisher false-running-header profile must contain 16 unique lines")
    if tuple(values) != _EXPECTED_FALSE_HEADERS:
        raise ValueError("Fisher false-running-header inventory differs from reviewed authority")
    line_digest = _sha(json.dumps(values, separators=(",", ":")).encode("utf-8"))
    if (
        line_digest != _EXPECTED_FALSE_HEADER_LINES_SHA256
        or landmarks.get("false_running_header_line_numbers_sha256") != line_digest
    ):
        raise ValueError("Fisher false-running-header line inventory digest mismatch")
    if lines is not None:
        observations = [
            {"line": number, "raw_line_sha256": _sha(str(lines[number - 1]["text"]).encode("utf-8"))}
            for number in values
        ]
        observation_digest = _sha(_canonical(observations))
        if (
            observation_digest != _EXPECTED_FALSE_HEADER_OBSERVATIONS_SHA256
            or landmarks.get("false_running_header_observations_sha256") != observation_digest
        ):
            raise ValueError("Fisher false-running-header retained-line evidence mismatch")
    return result


def _speaker_observation_records(
    lines: list[dict[str, object]], speakers: Mapping[int, Mapping[str, str]]
) -> list[dict[str, object]]:
    return [
        {
            "line": number,
            "raw_line_sha256": _sha(str(lines[number - 1]["text"]).encode("utf-8")),
            "section_prefix_sha256": _sha(str(value["section_prefix"]).encode("utf-8")),
            "speaker_prefix_sha256": _sha(str(value["speaker_prefix"]).encode("utf-8")),
            "body_sha256": _sha(str(value["body"]).encode("utf-8")),
        }
        for number, value in speakers.items()
    ]


def _verify_speaker_authority(
    profile: Mapping[str, object],
    lines: list[dict[str, object]],
    speakers: Mapping[int, Mapping[str, str]],
    rejected: tuple[int, ...],
) -> None:
    authority = profile.get("speaker_observation_authority")
    if not isinstance(authority, dict):
        raise ValueError("Fisher exact speaker-observation authority is missing")
    accepted_lines = authority.get("ordered_line_numbers")
    section_lines = authority.get("section_boundary_line_numbers")
    rejected_lines = authority.get("rejected_paragraph_continuation_line_numbers")
    if (
        not isinstance(accepted_lines, list)
        or any(type(item) is not int for item in accepted_lines)
        or accepted_lines != list(speakers)
        or section_lines != [number for number, value in speakers.items() if value["section_prefix"]]
        or rejected_lines != list(rejected)
    ):
        raise ValueError("Fisher classified speakers differ from exact reviewed observation inventory")
    line_digest = _sha(json.dumps(accepted_lines, separators=(",", ":")).encode("utf-8"))
    observation_digest = _sha(_canonical(_speaker_observation_records(lines, speakers)))
    if (
        authority.get("count") != 455
        or line_digest != _EXPECTED_SPEAKER_LINES_SHA256
        or authority.get("ordered_line_numbers_sha256") != line_digest
        or observation_digest != _EXPECTED_SPEAKER_OBSERVATIONS_SHA256
        or authority.get("ordered_observations_sha256") != observation_digest
    ):
        raise ValueError("Fisher exact speaker-observation authority digest mismatch")


def _kind(line: int, text: str, *, false_headers: frozenset[int], speakers: Mapping[int, Mapping[str, str]]) -> str:
    stripped = text.strip()
    if line in false_headers:
        return "false-running-header-content"
    if line >= 1285 and _PAGE_RE.fullmatch(stripped):
        return "page-marker-candidate"
    if line in speakers:
        return "section-boundary-dialogue-line" if speakers[line]["section_prefix"] else "dialogue-line"
    if _HEADING_RE.fullmatch(stripped):
        return "heading-line"
    if "*" in text or "§" in text or "†" in text or "‡" in text:
        return "inline-uncertainty-line"
    if not text:
        return "blank-line"
    return "text-line"


def _header(policy: Mapping[str, object], source_sha256: str) -> etree._Element:
    values = policy.get("tei_header")
    if not isinstance(values, dict):
        raise ValueError("Fisher TEI header policy is invalid")
    header = _tei("teiHeader")
    file_desc = _tei("fileDesc")
    title_stmt = _tei("titleStmt")
    title_stmt.append(_tei("title", text=str(values["title"])))
    title_stmt.append(_tei("author", text=str(values["author"])))
    resp = _tei("respStmt")
    resp.append(_tei("resp", text="Notes"))
    resp.append(_tei("name", text=str(values["contributor"])))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = _tei("publicationStmt")
    publication.append(_tei("publisher", text="Open Christian Data"))
    availability = _tei("availability", {"status": str(values["availability_status"])})
    availability.append(_tei("p", text=str(values["rights_statement"])))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _tei("sourceDesc")
    bibl = _tei("bibl")
    bibl.append(_tei("title", text=str(values["title"])))
    bibl.append(_tei("author", text=str(values["author"])))
    bibl.append(_tei("editor", {"role": "annotator"}, str(values["contributor"])))
    bibl.append(_tei("edition", text=str(values["edition"])))
    bibl.append(_tei("pubPlace", text=str(values["place"])))
    bibl.append(_tei("publisher", text=str(values["publisher"])))
    bibl.append(_tei("date", {"when": str(values["year"])}, str(values["year"])))
    bibl.append(_tei("ptr", {"target": str(values["source_url"])}))
    bibl.append(_tei("idno", {"type": "sha256"}, source_sha256))
    bibl.append(_tei("note", {"type": "source-quality"}, "Uncorrected retained ABBYY OCR; damaged text and uncertain inline marks are preserved without invented repairs or note boundaries."))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    source = source_manifest.authority_path("retained-fisher-ocr").read_bytes()
    member_census = _member_census(source_manifest)
    profile = _profile(source_manifest)
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    scope = profile["source_scope"]
    if not isinstance(scope, dict) or (
        len(source) != scope.get("bytes")
        or _sha(source) != scope.get("sha256")
        or source.count(b"\n") != scope.get("newline_count")
    ):
        raise ValueError("Fisher retained source scope or digest mismatch")
    lines = _source_lines(source)
    if len(lines) != scope.get("line_count"):
        raise ValueError("Fisher retained source line count mismatch")
    identity = _source_identity(source, profile, policy)
    regions = _regions(profile)
    landmarks = profile.get("landmarks")
    if not isinstance(landmarks, dict):
        raise ValueError("Fisher landmark policy is invalid")
    false_headers = _false_header_authority(landmarks, lines)
    speakers, rejected_speaker_like = _speaker_semantics(lines)
    _verify_speaker_authority(profile, lines, speakers, rejected_speaker_like)
    section_speakers = sum(bool(item["section_prefix"]) for item in speakers.values())
    if (
        len(speakers) != 455
        or section_speakers != 24
        or len(rejected_speaker_like) != 9
        or tuple(landmarks.get("paragraph_continuation_speaker_like_lines", ())) != rejected_speaker_like
    ):
        raise ValueError("Fisher paragraph-aware speaker census mismatch")

    root = _tei("TEI", {"xml:id": "fisher-marrow-1837-retained-ocr-candidate"})
    root.append(_header(policy, _sha(source)))
    text_root = _tei("text")
    part_nodes = {name: _tei(name) for name in ("front", "body", "back")}
    text_root.extend((part_nodes["front"], part_nodes["body"], part_nodes["back"]))
    root.append(text_root)

    region_nodes: dict[str, etree._Element] = {}
    current_segments: dict[str, etree._Element] = {}
    for region in regions:
        attrs = {"xml:id": f"fisher-region-{region['id']}", "type": str(region["type"])}
        if "n" in region:
            attrs["n"] = str(region["n"])
        region_node = _tei("div", attrs)
        segment = _tei("div", {"xml:id": f"fisher-segment-{region['id']}-0001", "type": "source-segment"})
        region_node.append(segment)
        part_nodes[str(region["tei_part"])].append(region_node)
        region_nodes[str(region["id"])] = region_node
        current_segments[str(region["id"])] = segment

    crosswalk: list[dict[str, object]] = []
    page_lines: list[int] = []
    false_header_count = 0
    segment_counts = {str(region["id"]): 1 for region in regions}
    for source_line in lines:
        number = int(source_line["line"])
        content = str(source_line["text"])
        region = _region_for(number, regions)
        region_id = str(region["id"])
        kind = _kind(number, content, false_headers=false_headers, speakers=speakers)
        identifier = f"fisher-line-{number:05d}"
        extraction = "element-text"
        if kind == "heading-line":
            segment_counts[region_id] += 1
            segment = _tei(
                "div",
                {
                    "xml:id": f"fisher-segment-{region_id}-{segment_counts[region_id]:04d}",
                    "type": "source-section",
                },
            )
            node = _tei("head", {"xml:id": identifier, "type": "source-heading"}, content)
            segment.append(node)
            region_nodes[region_id].append(segment)
            current_segments[region_id] = segment
            tag = "head"
        elif kind == "section-boundary-dialogue-line":
            semantic = speakers[number]
            node = _tei("div", {"xml:id": identifier, "type": "source-section"})
            node.append(_tei("head", {"type": "source-heading"}, semantic["section_prefix"]))
            speech = _tei("sp", {"ana": "#source-dialogue-line #section-boundary-speaker"})
            speech.append(_tei("speaker", text=semantic["speaker_prefix"]))
            speech.append(_tei("p", text=semantic["body"]))
            node.append(speech)
            region_nodes[region_id].append(node)
            current_segments[region_id] = node
            extraction = "section-heading-plus-speaker-paragraph"
            tag = "div"
        elif kind == "dialogue-line":
            semantic = speakers[number]
            node = _tei("sp", {"xml:id": identifier, "ana": "#source-dialogue-line"})
            node.append(_tei("speaker", text=semantic["speaker_prefix"]))
            node.append(_tei("p", text=semantic["body"]))
            current_segments[region_id].append(node)
            extraction = "speaker-plus-paragraph"
            tag = "sp"
        else:
            node = _tei("ab", {"xml:id": identifier, "type": kind}, content)
            if kind == "page-marker-candidate":
                node.set("ana", "#page-marker-candidate")
                page_lines.append(number)
            if kind == "inline-uncertainty-line":
                node.set("ana", "#uncorrected-ocr #inline-mark")
            if kind == "false-running-header-content":
                node.set("ana", "#substantive-content #not-a-running-header")
                false_header_count += 1
            current_segments[region_id].append(node)
            tag = "ab"
        crosswalk.append(
            {
                "feature_id": identifier,
                **source_line,
                "region": region_id,
                "kind": kind,
                "disposition": "represented",
                "tei_tag": tag,
                "tei_xml_id": identifier,
                "tei_selector": f"#{identifier}",
                "extraction": extraction,
            }
        )

    page_digest = _sha(_canonical(page_lines).rstrip(b"\n"))
    if (
        len(page_lines) != landmarks.get("page_marker_candidate_count")
        or page_digest != landmarks.get("page_marker_candidate_line_numbers_sha256")
        or false_header_count != len(false_headers)
        or len(false_headers) != 16
    ):
        raise ValueError("Fisher page-marker or false-header census mismatch")

    tei_bytes = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    accountability = {
        "contract": "ocd-fisher-marrow-source-accountability-v1",
        "schema": "fisher-marrow.source-accountability.schema.json",
        "profile_id": _PROFILE_ID,
        "source_scope": "complete retained 1087403-byte OCR witness",
        "source_sha256": _sha(source),
        "source_bytes": len(source),
        "line_count": len(lines),
        "newline_count": source.count(b"\n"),
        "represented_count": len(crosswalk),
        "evidence_only_count": 0,
        "excluded_count": 0,
        "omitted_count": 0,
        "duplicate_count": 0,
        "page_marker_candidate_count": len(page_lines),
        "false_running_header_content_count": false_header_count,
        "high_confidence_speaker_count": len(speakers),
        "section_boundary_speaker_count": section_speakers,
        "rejected_paragraph_continuation_speaker_like_count": len(rejected_speaker_like),
        "crosswalk": crosswalk,
    }
    authorities = {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-fisher-marrow-candidate-provenance-v1",
        "status": "nonaccepted",
        "authorities": authorities,
        "retained_member_census": member_census,
        "retained_member_census_sha256": _sha(_canonical(member_census)),
        "witness_identity": profile["witness_identity"],
        "retained_title_page_identity": identity,
        "rights": {
            "status": "unresolved-human-review-required",
            "publication_authorized": False,
        },
        "source_bytes_embedded_in_candidate": False,
    }
    unresolved = [
        {"id": "fisher-ocr-note-boundaries", "status": "unresolved", "reason": "Asterisks and section signs survive, but the retained OCR does not reliably delimit Boston note bodies."},
        {"id": "fisher-rights-review", "status": "unresolved", "reason": "Candidate validation does not decide publication rights."},
        {"id": "fisher-human-acceptance", "status": "unresolved", "reason": "This candidate has not been accepted by a human."},
    ]
    readme = (
        "# Fisher Marrow retained-source candidate\n\n"
        "This six-member package is a nonaccepted reconstruction candidate of the exact retained "
        "1,087,403-byte, 22,946-line Internet Archive OCR witness. The retained title page identifies "
        "London, Thomas Tegg and Son, 1837, and identifies Thomas Boston as the contributor of notes.\n\n"
        "Every retained line is represented exactly once. OCR damage, asterisks, section signs, page-marker "
        "candidates, the 297-line Recommendations, separate Part II front matter, and the Appendix remain "
        "visible. No OCR correction or uncertain note boundary has been invented.\n\n"
        "Attribution obligation: retain the Google watermark and Google Book Search attribution from "
        "source lines 30-31; do not remove it from any redistributed source-derived package.\n\n"
        "Validation is not human acceptance, rights clearance, publication readiness, or downstream migration.\n"
    ).encode("utf-8")
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
