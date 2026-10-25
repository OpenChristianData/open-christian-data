"""Deterministic Daily Light SWORD extracted module to TEI candidate conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-daily-light-sword-rawld-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_EXTRACTED_DIR = "raw/sword_modules/Daily"
_MEMBERS = (
    "modules/lexdict/rawld/devotionals/daily/daily.dat",
    "modules/lexdict/rawld/devotionals/daily/daily.idx",
    "mods.d/daily.conf",
)
_MEMBER_AUTHORITIES = {
    _MEMBERS[0]: "retained-daily-dat",
    _MEMBERS[1]: "retained-daily-idx",
    _MEMBERS[2]: "retained-daily-conf",
}
_MEMBER_AUTHORITY_ROLES = {
    _MEMBERS[0]: "primary-source",
    _MEMBERS[1]: "primary-source",
    _MEMBERS[2]: "source-support-metadata-rights",
}
_MEMBER_DIGESTS = {
    _MEMBERS[0]: "a7b7a9a4207836d152365e465ca3ba219de3df01d5516e2bfcf7ed6201f8e543",
    _MEMBERS[1]: "76bdcf08e75da1bcb98b46fbc7a0b97183c055756cef9b4e4b7318e439083899",
    _MEMBERS[2]: "4c5afc29317b58ad7c110affbac23ffc534a9e04d1d4f86c05efd4cb584689fb",
}
_MEMBER_BYTES = {
    _MEMBERS[0]: 1_034_668,
    _MEMBERS[1]: 2_202,
    _MEMBERS[2]: 603,
}
_MEMBER_ROLES = {
    _MEMBERS[0]: "textual-witness",
    _MEMBERS[1]: "binary-order-index-authority",
    _MEMBERS[2]: "module-metadata-and-rights-evidence",
}
_HEADER_BYTES = 1550
_HEADER_SHA256 = "c60281a7c2ceae138bb8d38d76d72108d0970c78b7cfb47706a51c728803e9b8"
_SENTINEL_SHA256 = "b0f66adc83641586656866813fd9dd0b8ebb63796075661ba45d1aa8089e1d44"
_DELIMITER = b"\r\n"
_DELIMITER_SHA256 = "7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6"
_TAG_NAMES = ("b", "br", "center", "i", "scripRef")
_EXPECTED_TAG_COUNTS = {"b": 1, "br": 20346, "center": 1, "i": 732, "scripRef": 1218}
_OPEN_TAG_RE = re.compile(r"<\s*(?!/)([A-Za-z][A-Za-z0-9]*)\b[^>]*>")
_EVENING_RE = re.compile(r"<i>\s*Evening\s*</i>\s*:\s*", re.IGNORECASE)
_MORNING_RE = re.compile(r"<i>\s*Morning\s*</i>\s*:\s*", re.IGNORECASE)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def load_manifest(path: str | Path, *, repository_root: str | Path) -> SourceManifest:
    """Load a source manifest through the shared exact-binding contract."""

    return SourceManifest.load(path, repository_root=repository_root)


def _authority(manifest: SourceManifest, name: str) -> Path:
    return manifest.authority_path(name)


def _member_authority(manifest: SourceManifest, rel_path: str) -> Path:
    authority_name = _MEMBER_AUTHORITIES[rel_path]
    authority = next(
        (
            item
            for item in manifest.record.get("authorities", ())
            if isinstance(item, Mapping) and item.get("name") == authority_name
        ),
        None,
    )
    if authority is None or authority.get("role") != _MEMBER_AUTHORITY_ROLES[rel_path]:
        raise ValueError(f"Daily Light authority role drifted for {authority_name}")
    return manifest.authority_path(authority_name)


def _strict(path: Path, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _tag_counts(content: str) -> dict[str, int]:
    counts = {name: 0 for name in _TAG_NAMES}
    for match in _OPEN_TAG_RE.finditer(content):
        name = match.group(1)
        canonical = {value.casefold(): value for value in _TAG_NAMES}.get(name.casefold())
        if canonical is not None:
            counts[canonical] += 1
    return counts


@dataclass
class _Source:
    members: list[dict[str, object]]
    payloads: dict[str, bytes]
    header: bytes
    days: list[dict[str, object]]
    carriers: list[dict[str, object]]


def _source(manifest: SourceManifest) -> _Source:
    members: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    extracted_root: Path | None = None
    for rel_path in _MEMBERS:
        member_path = _member_authority(manifest, rel_path)
        if extracted_root is None:
            extracted_root = member_path.parents[5]
        payload = member_path.read_bytes()
        payloads[rel_path] = payload
        if len(payload) != _MEMBER_BYTES[rel_path] or _sha(payload) != _MEMBER_DIGESTS[rel_path]:
            raise ValueError(f"Daily Light extracted member {rel_path} drifted")
        members.append(
            {
                "name": rel_path,
                "role": _MEMBER_ROLES[rel_path],
                "bytes": len(payload),
                "sha256": _sha(payload),
                }
            )
    assert extracted_root is not None
    observed = tuple(
        path.relative_to(extracted_root).as_posix()
        for path in sorted(extracted_root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    )
    if observed != tuple(sorted(_MEMBERS)):
        raise ValueError("Daily Light extracted member set drifted")
    retained_census = manifest.record.get("retained_member_census")
    expected_census_members = tuple(
        {
            "name": item["name"],
            "role": item["role"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in members
    )
    if not isinstance(retained_census, Mapping) or (
        retained_census.get("extracted_dir_bytes") != sum(item["bytes"] for item in members)
        or retained_census.get("members") != expected_census_members
    ):
        raise ValueError("Daily Light retained member census drifted")
    dat = payloads[_MEMBERS[0]]
    idx = payloads[_MEMBERS[1]]
    payloads[_MEMBERS[2]].decode("utf-8", "strict")
    if len(idx) % 6 or len(idx) // 6 != 367:
        raise ValueError("Daily Light index record count drifted")
    if idx[:6] != b"\x00" * 6 or _sha(idx[:6]) != _SENTINEL_SHA256:
        raise ValueError("Daily Light zero index sentinel drifted")
    first_offset, first_size = struct.unpack_from("<IH", idx, 6)
    if first_size == 0 or first_offset != _HEADER_BYTES:
        raise ValueError("Daily Light first index record is invalid")
    header = dat[:first_offset]
    header.decode("utf-8", "strict")
    if len(header) != _HEADER_BYTES or _sha(header) != _HEADER_SHA256:
        raise ValueError("Daily Light source header bytes drifted")
    days: list[dict[str, object]] = []
    expected_days = []
    month_days = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    for month, count in enumerate(month_days, 1):
        expected_days.extend((month, day) for day in range(1, count + 1))
    carriers: list[dict[str, object]] = [
        {
            "id": "daily.dat:header",
            "member": _MEMBERS[0],
            "kind": "header",
            "offset": 0,
            "bytes": len(header),
            "sha256": _sha(header),
            "disposition": "represented",
            "target": "#daily-light-source-header-content",
        },
        {
            "id": "daily.idx:slot-000",
            "member": _MEMBERS[1],
            "kind": "index-sentinel",
            "offset": 0,
            "bytes": 6,
            "sha256": _sha(idx[:6]),
            "disposition": "structural-support",
            "reason": "The exact zero slot is the rawLD index sentinel and has no textual TEI projection.",
        },
    ]
    slots: list[tuple[int, int]] = []
    for ordinal in range(367):
        slots.append(struct.unpack_from("<IH", idx, ordinal * 6))
    for ordinal, (month, day) in enumerate(expected_days, 1):
        offset, size = slots[ordinal]
        if size <= 0 or (
            ordinal > 1
            and offset < slots[ordinal - 1][0] + slots[ordinal - 1][1]
        ):
            raise ValueError(f"Daily Light invalid or reordered index slot at {ordinal}")
        raw = dat[offset : offset + size]
        key_line, separator, body = raw.partition(_DELIMITER)
        key = key_line.decode("utf-8", "strict")
        if not separator or key != f"{month:02d}.{day:02d}" or len(raw) != size:
            raise ValueError(f"Daily Light source key/index drift at {ordinal}")
        text = body.decode("utf-8", "strict")
        evening = _EVENING_RE.search(text)
        if evening is None:
            raise ValueError(f"Daily Light evening boundary missing for {key}")
        morning_match = _MORNING_RE.search(text[: evening.start()])
        if morning_match is None:
            raise ValueError(f"Daily Light morning boundary missing for {key}")
        # Keep the two section labels as source markup.  They are source
        # elements, not converter-owned headings, and therefore belong in the
        # element-level accounting and TEI candidate.
        morning = text[: evening.start()].strip()
        evening_text = text[evening.start() :].strip()
        days.append(
            {
                "ordinal": ordinal,
                "key": key,
                "month": month,
                "day": day,
                "offset": offset,
                "bytes": size,
                "raw_sha256": _sha(raw),
                "index_slot_offset": ordinal * 6,
                "index_slot_sha256": _sha(idx[ordinal * 6 : ordinal * 6 + 6]),
                "periods": {"morning": morning, "evening": evening_text},
            }
        )
        carriers.append(
            {
                "id": f"daily.dat:day-{ordinal:03d}",
                "member": _MEMBERS[0],
                "kind": "day-record",
                "offset": offset,
                "bytes": size,
                "sha256": _sha(raw),
                "index_slot_offset": ordinal * 6,
                "index_slot_bytes": 6,
                "index_slot_sha256": _sha(idx[ordinal * 6 : ordinal * 6 + 6]),
                "disposition": "represented",
                "target": f"#daily-light-day-{key}",
            }
        )
        next_offset = slots[ordinal + 1][0] if ordinal < 366 else len(dat)
        delimiter_offset = offset + size
        delimiter = dat[delimiter_offset:next_offset]
        if delimiter != _DELIMITER:
            boundary = "terminal" if ordinal == 366 else "inter-record"
            raise ValueError(f"Daily Light {boundary} record delimiter drift at {key}")
        carriers.append(
            {
                "id": f"daily.dat:delimiter-{ordinal:03d}",
                "member": _MEMBERS[0],
                "kind": "record-delimiter",
                "offset": delimiter_offset,
                "bytes": len(delimiter),
                "sha256": _sha(delimiter),
                "terminal": ordinal == 366,
                "disposition": "structural-separator",
                "reason": "The exact CRLF separates indexed rawLD records and has no textual TEI projection.",
            }
        )
    carriers.append(
        {
            "id": "daily.conf:member",
            "member": _MEMBERS[2],
            "kind": "module-metadata-and-rights-evidence",
            "offset": 0,
            "bytes": len(payloads[_MEMBERS[2]]),
            "sha256": _sha(payloads[_MEMBERS[2]]),
            "disposition": "support-evidence",
            "reason": "Module metadata and rights claims remain bound as evidence rather than projected as work text.",
        }
    )
    if sum(int(item["bytes"]) for item in carriers if item["member"] == _MEMBERS[0]) != len(dat):
        raise ValueError("Daily Light data carrier coverage drifted")
    if 6 + sum(int(item["index_slot_bytes"]) for item in carriers if item["kind"] == "day-record") != len(idx):
        raise ValueError("Daily Light index carrier coverage drifted")
    return _Source(
        members=members,
        payloads=payloads,
        header=header,
        days=days,
        carriers=carriers,
    )


@dataclass
class _Markup:
    scope: str
    ordinal: int = 0
    tags: dict[str, int] = field(default_factory=lambda: {name: 0 for name in _TAG_NAMES})
    observations: list[dict[str, object]] = field(default_factory=list)

    def mapped(self, source_tag: str, target: etree._Element, *, attributes: Mapping[str, str] | None = None) -> None:
        self.ordinal += 1
        canonical = {value.casefold(): value for value in _TAG_NAMES}[source_tag.casefold()]
        self.tags[canonical] += 1
        corresp = f"daily:{self.scope}:source-element-{self.ordinal:05d}"
        target.set("corresp", corresp)
        self.observations.append(
            {
                "id": corresp,
                "scope": self.scope,
                "ordinal": self.ordinal,
                "source_tag": canonical,
                "source_attributes": dict(attributes or {}),
                "target": f"#{target.get(_XML_ID)}" if target.get(_XML_ID) else None,
                "disposition": "represented",
            }
        )


def _append_text(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _copy_fragment(raw: str, parent: etree._Element, markup: _Markup) -> None:
    wrapper = html.fragment_fromstring(raw, create_parent="span")

    def visit(source: etree._Element, target_parent: etree._Element) -> None:
        tag = str(source.tag).casefold()
        if tag == "br":
            target = etree.SubElement(target_parent, f"{{{_TEI}}}lb")
        elif tag == "i":
            target = etree.SubElement(target_parent, f"{{{_TEI}}}hi", rend="italic")
        elif tag == "b":
            target = etree.SubElement(target_parent, f"{{{_TEI}}}hi", rend="bold")
        elif tag == "center":
            target = etree.SubElement(target_parent, f"{{{_TEI}}}hi", rend="center")
        elif tag == "scripref":
            target = etree.SubElement(target_parent, f"{{{_TEI}}}ref", type="scripture")
            passage = source.get("passage")
            if passage:
                target.set("cRef", passage)
        else:
            raise ValueError(f"Daily Light unexpected source element {source.tag!r}")
        target.set(_XML_ID, f"daily-{markup.scope}-element-{markup.ordinal + 1:05d}")
        markup.mapped(tag, target, attributes=source.attrib)
        _append_text(target, source.text)
        for child in source:
            visit(child, target)
            _append_text(target, child.tail)

    _append_text(parent, wrapper.text)
    for child in wrapper:
        visit(child, parent)
        _append_text(parent, child.tail)


def _header(source: _Source, root: etree._Element, markup: _Markup) -> None:
    front = etree.SubElement(root, f"{{{_TEI}}}text")
    front.set(_XML_ID, "daily-light-text")
    header_div = etree.SubElement(front, f"{{{_TEI}}}front", {"type": "module-header"})
    header_div.set(_XML_ID, "daily-light-module-header")
    header_p = etree.SubElement(header_div, f"{{{_TEI}}}p")
    _copy_fragment(source.header.decode("utf-8", "strict"), header_p, markup)


def _tei(source: _Source, profile: Mapping[str, object]) -> tuple[bytes, list[dict[str, object]], dict[str, int]]:
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "daily-light-candidate")
    tei_header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(tei_header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(profile["identity"]["title"])
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = "Jonathan Bagster"
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{_TEI}}}availability", status="restricted")
    etree.SubElement(availability, f"{{{_TEI}}}p").text = "Nonaccepted candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    etree.SubElement(source_desc, f"{{{_TEI}}}p").text = "Daily Light on the Daily Path, retained as an extracted CrossWire SWORD rawLD module."
    encoding = etree.SubElement(tei_header, f"{{{_TEI}}}encodingDesc")
    etree.SubElement(encoding, f"{{{_TEI}}}p").text = "Every retained module member, index record, day, period, and source markup element is accounted for."
    revision = etree.SubElement(tei_header, f"{{{_TEI}}}revisionDesc", status="candidate")
    etree.SubElement(revision, f"{{{_TEI}}}change", when="2026-08-30").text = "Generated as a nonaccepted review candidate."
    text = etree.SubElement(root, f"{{{_TEI}}}text")
    text.set(_XML_ID, "daily-light-body-text")
    markup = _Markup("header")
    front = etree.SubElement(text, f"{{{_TEI}}}front")
    front.set(_XML_ID, "daily-light-source-header")
    header_div = etree.SubElement(front, f"{{{_TEI}}}div", type="source-header")
    header_div.set(_XML_ID, "daily-light-source-header-content")
    header_p = etree.SubElement(header_div, f"{{{_TEI}}}p")
    _copy_fragment(source.header.decode("utf-8", "strict"), header_p, markup)
    body = etree.SubElement(text, f"{{{_TEI}}}body")
    body.set(_XML_ID, "daily-light-body")
    observations: list[dict[str, object]] = list(markup.observations)
    total_tags = markup.tags.copy()
    for day in source.days:
        day_node = etree.SubElement(body, f"{{{_TEI}}}div", type="day", n=str(day["key"]))
        day_node.set(_XML_ID, f"daily-light-day-{day['key']}")
        for period_name in ("morning", "evening"):
            period_node = etree.SubElement(day_node, f"{{{_TEI}}}div", type="period", n=period_name)
            period_node.set(_XML_ID, f"daily-light-{day['key']}-{period_name}")
            period_markup = _Markup(f"{day['key']}-{period_name}")
            period_p = etree.SubElement(period_node, f"{{{_TEI}}}p")
            _copy_fragment(str(day["periods"][period_name]), period_p, period_markup)
            observations.extend(period_markup.observations)
            for key, value in period_markup.tags.items():
                total_tags[key] += value
    if total_tags != _EXPECTED_TAG_COUNTS or len(observations) != 22298:
        raise ValueError(f"Daily Light source element census drifted: {total_tags}, {len(observations)}")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False), observations, total_tags


def _accountability(source: _Source, observations: list[dict[str, object]], tags: dict[str, int], manifest: SourceManifest) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for day in source.days:
        periods: list[dict[str, object]] = []
        for period_name in ("morning", "evening"):
            raw = str(day["periods"][period_name]).encode("utf-8")
            period_tags = _tag_counts(str(day["periods"][period_name]))
            periods.append(
                {
                    "key": day["key"],
                    "period": period_name,
                    "offset": day["offset"],
                    "day_record_bytes": day["bytes"],
                    "period_utf8_bytes": len(raw),
                    "period_sha256": _sha(raw),
                    "tag_counts": period_tags,
                    "source_elements": sum(period_tags.values()),
                    "disposition": "represented",
                }
            )
        entries.append(
            {
                "ordinal": day["ordinal"],
                "key": day["key"],
                "month": day["month"],
                "day": day["day"],
                "offset": day["offset"],
                "day_record_bytes": day["bytes"],
                "raw_sha256": day["raw_sha256"],
                "index_slot_offset": day["index_slot_offset"],
                "index_slot_bytes": 6,
                "index_slot_sha256": day["index_slot_sha256"],
                "periods": periods,
                "disposition": "represented",
            }
        )
    delimiters = [item for item in source.carriers if item["kind"] == "record-delimiter"]
    day_carriers = [item for item in source.carriers if item["kind"] == "day-record"]
    return {
        "contract": "ocd-daily-light-source-accountability-v2",
        "schema": "sources/devotionals/daily-light/daily-light.source-accountability.schema.json",
        "profile_id": "daily-light-sword-rawld-v1",
        "work_id": "daily-light",
        "source_id": manifest.record["source_id"],
        "member_count": len(source.members),
        "members": source.members,
        "member_bytes": {str(item["name"]): item["bytes"] for item in source.members},
        "member_sha256": {str(item["name"]): item["sha256"] for item in source.members},
        "member_roles": _MEMBER_ROLES,
        "index_record_count": 367,
        "index_sentinel_count": 1,
        "index_sentinel_bytes": 6,
        "index_sentinel_sha256": _SENTINEL_SHA256,
        "header_count": 1,
        "header_bytes": len(source.header),
        "header_sha256": _sha(source.header),
        "day_count": len(source.days),
        "day_span_bytes": sum(int(item["bytes"]) for item in day_carriers),
        "record_delimiter_count": len(delimiters),
        "record_delimiter_bytes": sum(int(item["bytes"]) for item in delimiters),
        "record_delimiter_sha256": _DELIMITER_SHA256,
        "terminal_delimiter_count": sum(bool(item["terminal"]) for item in delimiters),
        "terminal_tail_bytes": int(delimiters[-1]["bytes"]),
        "gap_count": 1 + len(delimiters),
        "gap_bytes": len(source.header) + sum(int(item["bytes"]) for item in delimiters),
        "unexplained_gap_count": 0,
        "period_count": sum(len(entry["periods"]) for entry in entries),
        "source_element_count": len(observations),
        "tag_counts": tags,
        "omitted_count": 0,
        "duplicate_count": 0,
        "unresolved_count": 0,
        "carriers": source.carriers,
        "entries": entries,
        "source_element_observations": observations,
    }


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict(_authority(source_manifest, "reconstruction-profile"), "Daily Light profile")
    policy = _strict(_authority(source_manifest, "validation-policy"), "Daily Light policy")
    if profile.get("profile_id") != "daily-light-sword-rawld-v1" or policy.get("policy_id") != "daily-light-sword-rawld-policy-v1":
        raise ValueError("Daily Light profile or policy identity drifted")
    if profile.get("feature_dispositions") != {
        "br": "one TEI lb with source corresp",
        "i": "one TEI hi rend=italic with source corresp",
        "b": "one TEI hi rend=bold with source corresp",
        "center": "one TEI hi rend=center with source corresp",
        "scripRef": "one TEI ref type=scripture with source corresp",
    }:
        raise ValueError("Daily Light feature disposition drifted")
    source_scope = profile.get("source_scope")
    if not isinstance(source_scope, Mapping) or (
        source_scope.get("extracted_root") != _EXTRACTED_DIR
        or source_scope.get("member_paths") != list(_MEMBERS)
        or source_scope.get("member_bytes") != _MEMBER_BYTES
        or source_scope.get("member_sha256") != _MEMBER_DIGESTS
        or source_scope.get("index_record_count") != 367
        or source_scope.get("index_sentinel_count") != 1
        or source_scope.get("header_bytes") != _HEADER_BYTES
        or source_scope.get("record_delimiter_count") != 366
        or source_scope.get("record_delimiter_bytes") != 732
        or source_scope.get("terminal_tail_bytes") != 2
        or source_scope.get("gap_count") != 367
        or source_scope.get("gap_bytes") != 2282
        or source_scope.get("member_roles") != _MEMBER_ROLES
        or source_scope.get("day_count") != 366
        or source_scope.get("period_count") != 732
        or source_scope.get("source_element_count") != 22298
        or source_scope.get("tag_counts") != _EXPECTED_TAG_COUNTS
    ):
        raise ValueError("Daily Light profile source scope drifted")
    source = _source(source_manifest)
    tei, observations, tags = _tei(source, profile)
    accountability = _accountability(source, observations, tags, source_manifest)
    if policy.get("required_counts") != {
        "index_records": 367,
        "index_sentinels": 1,
        "headers": 1,
        "header_bytes": 1550,
        "days": 366,
        "day_span_bytes": 1032386,
        "record_delimiters": 366,
        "record_delimiter_bytes": 732,
        "terminal_delimiters": 1,
        "terminal_tail_bytes": 2,
        "gaps": 367,
        "gap_bytes": 2282,
        "unexplained_gaps": 0,
        "periods": 732,
        "source_elements": 22298,
        "tag_counts": _EXPECTED_TAG_COUNTS,
        "omitted": 0,
        "duplicate": 0,
        "unresolved": 0,
    }:
        raise ValueError("Daily Light policy census drifted")
    if (
        policy.get("required_members") != list(_MEMBERS)
        or policy.get("required_member_roles") != _MEMBER_ROLES
    ):
        raise ValueError("Daily Light policy member role drifted")
    authority_bindings = {
        str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")}
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-daily-light-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": "LIB-006",
        "work_id": "daily-light",
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "identity": profile["identity"],
        "source": {
            "extracted_root": _EXTRACTED_DIR,
            "members": source.members,
            "module": "Daily",
        },
        "authorities": authority_bindings,
        "rights": profile["rights"],
        "candidate_boundary": {
            "acceptance_status": "nonaccepted",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
    }
    unresolved = (
        {"id": "daily-light-rights-review", "status": "unresolved", "kind": "rights", "detail": "Human review is required before acceptance or publication."},
        {"id": "daily-light-human-acceptance", "status": "unresolved", "kind": "acceptance", "detail": "This deterministic candidate has not received human textual acceptance."},
    )
    readme = _authority(source_manifest, "source-attribution-readme").read_bytes()
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(row) for row in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
