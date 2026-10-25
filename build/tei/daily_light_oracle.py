"""Independent validation oracle for the LIB-006 Daily Light candidate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-daily-light-sword-independent-oracle"
ORACLE_VERSION = "1"
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
_MEMBER_BYTES = {_MEMBERS[0]: 1_034_668, _MEMBERS[1]: 2_202, _MEMBERS[2]: 603}
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
_TAG_COUNTS = {"b": 1, "br": 20346, "center": 1, "i": 732, "scripRef": 1218}
_MORNING_MARKER = b"<i>Morning</i>:<br />\n"
_EVENING_MARKER = b"<i>Evening</i>:<br />\n"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _source_sha(manifest: SourceManifest) -> str:
    authorities = [
        item
        for item in manifest.record.get("authorities", ())
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    members = sorted(
        [
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in authorities
        ],
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    for item in manifest.record.get("authorities", ()):
        if isinstance(item, Mapping) and item.get("name") == name:
            return item
    raise ValueError(f"Daily Light authority {name!r} is missing")


def _u16(content: bytes, offset: int) -> int:
    field = content[offset : offset + 2]
    if len(field) != 2:
        raise ValueError("Daily Light truncated two-byte field")
    return int.from_bytes(field, "little")


def _u32(content: bytes, offset: int) -> int:
    field = content[offset : offset + 4]
    if len(field) != 4:
        raise ValueError("Daily Light truncated four-byte field")
    return int.from_bytes(field, "little")


class _TokenInventory(HTMLParser):
    """Inventory the restricted source fragments without an XML/HTML tree."""

    _ALIASES = {name.casefold(): name for name in _TAG_COUNTS}

    def __init__(self, scope: str) -> None:
        super().__init__(convert_charrefs=True)
        self.scope = scope
        self.observations: list[dict[str, object]] = []
        self.text: list[str] = []
        self.stack: list[str] = []
        self.counts = {name: 0 for name in _TAG_COUNTS}

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, closed: bool) -> None:
        canonical = self._ALIASES.get(tag.casefold())
        if canonical is None:
            raise ValueError(f"Daily Light unexpected source token {tag!r}")
        if canonical == "br" and not closed:
            closed = True
        if canonical != "br" and closed:
            raise ValueError(f"Daily Light nonvoid source token {tag!r} is self-closing")
        if len({name for name, _ in attrs}) != len(attrs):
            raise ValueError("Daily Light duplicate source attribute")
        attributes: dict[str, str] = {}
        for name, value in attrs:
            if value is None:
                raise ValueError("Daily Light valueless source attribute")
            attributes[name] = value
        self.counts[canonical] += 1
        ordinal = len(self.observations) + 1
        ident = f"daily:{self.scope}:source-element-{ordinal:05d}"
        self.observations.append(
            {
                "id": ident,
                "scope": self.scope,
                "ordinal": ordinal,
                "source_tag": canonical,
                "source_attributes": attributes,
                "target": f"#daily-{self.scope}-element-{ordinal:05d}",
                "disposition": "represented",
            }
        )
        if not closed:
            self.stack.append(canonical)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=True)

    def handle_endtag(self, tag: str) -> None:
        canonical = self._ALIASES.get(tag.casefold())
        if canonical is None or canonical == "br" or not self.stack or self.stack.pop() != canonical:
            raise ValueError(f"Daily Light source end-token topology drift for {tag!r}")

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def handle_comment(self, data: str) -> None:
        raise ValueError("Daily Light source comment is unsupported")

    def handle_decl(self, decl: str) -> None:
        raise ValueError("Daily Light source declaration is unsupported")

    def handle_pi(self, data: str) -> None:
        raise ValueError("Daily Light source processing instruction is unsupported")

    def finish(self) -> None:
        self.close()
        if self.stack:
            raise ValueError("Daily Light unclosed source token")


@dataclass(frozen=True)
class _Day:
    ordinal: int
    key: str
    month: int
    day: int
    offset: int
    bytes: int
    raw_sha256: str
    index_slot_sha256: str
    morning: str
    evening: str


@dataclass(frozen=True)
class _Source:
    members: list[dict[str, object]]
    payloads: dict[str, bytes]
    header: bytes
    index: bytes
    days: list[_Day]
    carriers: list[dict[str, object]]


def _source(manifest: SourceManifest) -> _Source:
    members: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    extracted_root: Path | None = None
    for name in _MEMBERS:
        authority_name = _MEMBER_AUTHORITIES[name]
        authority = _authority(manifest, authority_name)
        if authority.get("role") != _MEMBER_AUTHORITY_ROLES[name]:
            raise ValueError(f"Daily Light authority role drifted for {authority_name}")
        member_path = manifest.authority_path(authority_name)
        if extracted_root is None:
            extracted_root = member_path.parents[5]
        payload = member_path.read_bytes()
        if len(payload) != _MEMBER_BYTES[name] or _sha(payload) != _MEMBER_DIGESTS[name]:
            raise ValueError(f"Daily Light extracted member {name} drifted")
        payloads[name] = payload
        members.append({"name": name, "role": _MEMBER_ROLES[name], "bytes": len(payload), "sha256": _sha(payload)})
    assert extracted_root is not None
    observed = tuple(
        path.relative_to(extracted_root).as_posix()
        for path in sorted(extracted_root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    )
    if observed != tuple(sorted(_MEMBERS)):
        raise ValueError("Daily Light extracted member set drifted")
    dat, idx = payloads[_MEMBERS[0]], payloads[_MEMBERS[1]]
    payloads[_MEMBERS[2]].decode("utf-8", "strict")
    if len(idx) != 2202 or len(idx) // 6 != 367:
        raise ValueError("Daily Light index census drift")
    if idx[:6] != b"\x00" * 6 or _sha(idx[:6]) != _SENTINEL_SHA256:
        raise ValueError("Daily Light zero index sentinel drift")
    first_offset, first_size = _u32(idx, 6), _u16(idx, 10)
    if first_offset != _HEADER_BYTES or first_size <= 0:
        raise ValueError("Daily Light first index slot drift")
    header = dat[:first_offset]
    header.decode("utf-8", "strict")
    if len(header) != _HEADER_BYTES or _sha(header) != _HEADER_SHA256:
        raise ValueError("Daily Light source header bytes drift")
    month_days = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    expected = [(month, day) for month, count in enumerate(month_days, 1) for day in range(1, count + 1)]
    days: list[_Day] = []
    carriers: list[dict[str, object]] = [
        {"id": "daily.dat:header", "member": _MEMBERS[0], "kind": "header", "offset": 0, "bytes": len(header), "sha256": _sha(header), "disposition": "represented", "target": "#daily-light-source-header-content"},
        {"id": "daily.idx:slot-000", "member": _MEMBERS[1], "kind": "index-sentinel", "offset": 0, "bytes": 6, "sha256": _sha(idx[:6]), "disposition": "structural-support", "reason": "The exact zero slot is the rawLD index sentinel and has no textual TEI projection."},
    ]
    slots = [(_u32(idx, ordinal * 6), _u16(idx, ordinal * 6 + 4)) for ordinal in range(367)]
    for ordinal, (month, day) in enumerate(expected, 1):
        offset, size = slots[ordinal]
        if size <= 0 or (
            ordinal > 1
            and offset < slots[ordinal - 1][0] + slots[ordinal - 1][1]
        ):
            raise ValueError(f"Daily Light invalid or reordered index slot at {ordinal}")
        raw = dat[offset : offset + size]
        key_bytes, separator, body_bytes = raw.partition(_DELIMITER)
        key = key_bytes.decode("utf-8", "strict")
        if not separator or key != f"{month:02d}.{day:02d}" or len(raw) != size:
            raise ValueError(f"Daily Light key/index drift at {ordinal}")
        body_bytes.decode("utf-8", "strict")
        if not body_bytes.startswith(_MORNING_MARKER):
            raise ValueError(f"Daily Light morning boundary missing for {key}")
        evening_at = body_bytes.find(_EVENING_MARKER)
        if evening_at < 0 or body_bytes.find(_EVENING_MARKER, evening_at + 1) >= 0:
            raise ValueError(f"Daily Light evening boundary missing for {key}")
        morning = body_bytes[:evening_at].decode("utf-8", "strict").strip()
        evening_body = body_bytes[evening_at:].decode("utf-8", "strict").strip()
        slot = idx[ordinal * 6 : ordinal * 6 + 6]
        days.append(_Day(ordinal, key, month, day, offset, size, _sha(raw), _sha(slot), morning, evening_body))
        carriers.append({"id": f"daily.dat:day-{ordinal:03d}", "member": _MEMBERS[0], "kind": "day-record", "offset": offset, "bytes": size, "sha256": _sha(raw), "index_slot_offset": ordinal * 6, "index_slot_bytes": 6, "index_slot_sha256": _sha(slot), "disposition": "represented", "target": f"#daily-light-day-{key}"})
        next_offset = slots[ordinal + 1][0] if ordinal < 366 else len(dat)
        delimiter_offset = offset + size
        delimiter = dat[delimiter_offset:next_offset]
        if delimiter != _DELIMITER:
            raise ValueError(f"Daily Light exact record delimiter drift at {key}")
        carriers.append({"id": f"daily.dat:delimiter-{ordinal:03d}", "member": _MEMBERS[0], "kind": "record-delimiter", "offset": delimiter_offset, "bytes": len(delimiter), "sha256": _sha(delimiter), "terminal": ordinal == 366, "disposition": "structural-separator", "reason": "The exact CRLF separates indexed rawLD records and has no textual TEI projection."})
    carriers.append({"id": "daily.conf:member", "member": _MEMBERS[2], "kind": "module-metadata-and-rights-evidence", "offset": 0, "bytes": len(payloads[_MEMBERS[2]]), "sha256": _sha(payloads[_MEMBERS[2]]), "disposition": "support-evidence", "reason": "Module metadata and rights claims remain bound as evidence rather than projected as work text."})
    if sum(int(item["bytes"]) for item in carriers if item["member"] == _MEMBERS[0]) != len(dat):
        raise ValueError("Daily Light data carrier coverage drift")
    if 6 + sum(int(item["index_slot_bytes"]) for item in carriers if item["kind"] == "day-record") != len(idx):
        raise ValueError("Daily Light index carrier coverage drift")
    return _Source(members, payloads, header, idx, days, carriers)


def _tag_counts(content: str) -> dict[str, int]:
    inventory = _TokenInventory("census")
    inventory.feed(content)
    inventory.finish()
    return inventory.counts


def _period_rows(days: list[_Day]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for day in days:
        for period, content in (("morning", day.morning), ("evening", day.evening)):
            tags = _tag_counts(content)
            encoded = content.encode("utf-8")
            rows.append(
                {
                    "key": day.key,
                    "period": period,
                    "offset": day.offset,
                    "day_record_bytes": day.bytes,
                    "period_utf8_bytes": len(encoded),
                    "period_sha256": _sha(encoded),
                    "tag_counts": tags,
                    "source_elements": sum(tags.values()),
                    "disposition": "represented",
                }
            )
    return rows


def _expected_accountability(
    manifest: SourceManifest,
    source: _Source,
) -> dict[str, object]:
    observations: list[dict[str, object]] = []

    def observed(scope: str, content: str) -> list[dict[str, object]]:
        inventory = _TokenInventory(scope)
        inventory.feed(content)
        inventory.finish()
        return inventory.observations

    observations.extend(observed("header", source.header.decode("utf-8", "strict")))
    for day in source.days:
        observations.extend(observed(f"{day.key}-morning", day.morning))
        observations.extend(observed(f"{day.key}-evening", day.evening))
    period_rows = _period_rows(source.days)
    entries: list[dict[str, object]] = []
    cursor = 0
    for day in source.days:
        periods = period_rows[cursor : cursor + 2]
        cursor += 2
        entries.append(
            {
                "ordinal": day.ordinal,
                "key": day.key,
                "month": day.month,
                "day": day.day,
                "offset": day.offset,
                "day_record_bytes": day.bytes,
                "raw_sha256": day.raw_sha256,
                "index_slot_offset": day.ordinal * 6,
                "index_slot_bytes": 6,
                "index_slot_sha256": day.index_slot_sha256,
                "periods": periods,
                "disposition": "represented",
            }
        )
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
        "day_span_bytes": sum(day.bytes for day in source.days),
        "record_delimiter_count": 366,
        "record_delimiter_bytes": 732,
        "record_delimiter_sha256": _DELIMITER_SHA256,
        "terminal_delimiter_count": 1,
        "terminal_tail_bytes": 2,
        "gap_count": 367,
        "gap_bytes": 2282,
        "unexplained_gap_count": 0,
        "period_count": len(period_rows),
        "source_element_count": len(observations),
        "tag_counts": _TAG_COUNTS,
        "omitted_count": 0,
        "duplicate_count": 0,
        "unresolved_count": 0,
        "carriers": source.carriers,
        "entries": entries,
        "source_element_observations": observations,
    }


def _visible_source(content: str) -> str:
    inventory = _TokenInventory("visible")
    inventory.feed(content)
    inventory.finish()
    return "".join(inventory.text)


def _verify_tei(
    manifest: SourceManifest,
    candidate: CandidatePackage,
    days: list[_Day],
    expected_accountability: Mapping[str, object],
    profile: Mapping[str, object],
) -> None:
    try:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    except etree.XMLSyntaxError as exc:
        raise ValueError("Daily Light TEI XML is not well-formed") from exc
    xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(root):
        raise ValueError(f"Daily Light TEI schema failure: {xsd.error_log}")
    if root.get(_XML_ID) != "daily-light-candidate":
        raise ValueError("Daily Light TEI root identity drift")
    titles = root.xpath(
        "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces={"t": _TEI}
    )
    authors = root.xpath(
        "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:author", namespaces={"t": _TEI}
    )
    identity = profile.get("identity")
    if (
        not isinstance(identity, Mapping)
        or len(titles) != 1
        or titles[0].text != identity.get("title")
        or len(authors) != 1
        or authors[0].text != identity.get("author")
    ):
        raise ValueError("Daily Light TEI header identity drift")
    days_nodes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='day']", namespaces={"t": _TEI})
    if len(days_nodes) != 366:
        raise ValueError("Daily Light day omission or duplication")
    for source, node in zip(days, days_nodes):
        if (
            node.get("n") != source.key
            or node.get(_XML_ID) != f"daily-light-day-{source.key}"
            or set(node.attrib) != {"type", "n", _XML_ID}
        ):
            raise ValueError("Daily Light day order or identity drift")
        periods = node.xpath("./t:div[@type='period']", namespaces={"t": _TEI})
        if [period.get("n") for period in periods] != ["morning", "evening"]:
            raise ValueError("Daily Light period order drift")
        if any(set(period.attrib) != {"type", "n", _XML_ID} for period in periods):
            raise ValueError("Daily Light period identity drift")
        for period, expected in zip(periods, (source.morning, source.evening)):
            paragraphs = period.xpath("./t:p", namespaces={"t": _TEI})
            if len(paragraphs) != 1 or _visible_source(expected) != "".join(period.itertext()):
                raise ValueError("Daily Light source payload drift")
    mapped = root.xpath("//*[@corresp]")
    observations = expected_accountability.get("source_element_observations")
    if not isinstance(observations, list) or len(mapped) != len(observations):
        raise ValueError("Daily Light source element omission or duplication")
    for node, observation in zip(mapped, observations):
        if not isinstance(observation, Mapping):
            raise ValueError("Daily Light source observation shape drift")
        source_tag = observation.get("source_tag")
        source_attributes = observation.get("source_attributes")
        target = observation.get("target")
        if (
            not isinstance(source_tag, str)
            or not isinstance(source_attributes, Mapping)
            or not isinstance(target, str)
            or not target.startswith("#")
            or node.get("corresp") != observation.get("id")
            or node.get(_XML_ID) != target[1:]
        ):
            raise ValueError("Daily Light source observation identity drift")
        expected_attributes: dict[str, str] = {
            "corresp": str(observation["id"]),
            _XML_ID: target[1:],
        }
        expected_tag: str
        if source_tag == "br":
            expected_tag = "lb"
        elif source_tag == "i":
            expected_tag = "hi"
            expected_attributes["rend"] = "italic"
        elif source_tag == "b":
            expected_tag = "hi"
            expected_attributes["rend"] = "bold"
        elif source_tag == "center":
            expected_tag = "hi"
            expected_attributes["rend"] = "center"
        elif source_tag == "scripRef":
            expected_tag = "ref"
            expected_attributes["type"] = "scripture"
            if set(source_attributes) != {"passage"}:
                raise ValueError("Daily Light scripture source attributes drift")
            expected_attributes["cRef"] = str(source_attributes["passage"])
        else:
            raise ValueError("Daily Light source tag drift")
        if source_tag != "scripRef" and source_attributes:
            raise ValueError("Daily Light source attributes drift")
        if node.tag != f"{{{_TEI}}}{expected_tag}" or dict(node.attrib) != expected_attributes:
            raise ValueError("Daily Light mapped target semantics drift")


def _closure(root: Path) -> str:
    paths = {
        Path(__file__).resolve(strict=True),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    }
    records = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())]
    return _sha(_canonical(records))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if source_manifest.record.get("ticket_id") != "LIB-006" or source_manifest.record.get("work_id") != "daily-light":
        raise ValueError("Daily Light source identity drift")
    validator = source_manifest.record.get("validator")
    converter = source_manifest.record.get("converter")
    if not isinstance(validator, Mapping) or not isinstance(converter, Mapping):
        raise ValueError("Daily Light callable binding drift")
    expected_manifest = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_manifest") != {"path": expected_manifest, "sha256": source_manifest.sha256}:
        raise ValueError("Daily Light candidate binding drift")
    if candidate.manifest.get("converter") != dict(converter) or candidate.manifest.get("package_schema") != dict(source_manifest.record["package_schema"]):
        raise ValueError("Daily Light candidate authority drift")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Daily Light profile")
    policy = _strict(policy_bytes, "Daily Light policy")
    if profile.get("profile_id") != "daily-light-sword-rawld-v1" or policy.get("policy_id") != "daily-light-sword-rawld-policy-v1" or policy.get("oracle_id") != ORACLE_ID:
        raise ValueError("Daily Light profile or policy drift")
    source = _source(source_manifest)
    retained_census = source_manifest.record.get("retained_member_census")
    expected_census_members = tuple(
        {
            "name": item["name"],
            "role": item["role"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in source.members
    )
    if not isinstance(retained_census, Mapping) or (
        retained_census.get("extracted_dir_bytes") != sum(item["bytes"] for item in source.members)
        or retained_census.get("members") != expected_census_members
    ):
        raise ValueError("Daily Light retained member census drifted")
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
        or source_scope.get("tag_counts") != _TAG_COUNTS
    ):
        raise ValueError("Daily Light profile source scope drifted")
    if profile.get("feature_dispositions") != {
        "br": "one TEI lb with source corresp",
        "i": "one TEI hi rend=italic with source corresp",
        "b": "one TEI hi rend=bold with source corresp",
        "center": "one TEI hi rend=center with source corresp",
        "scripRef": "one TEI ref type=scripture with source corresp",
    }:
        raise ValueError("Daily Light feature disposition drifted")
    accountability = _strict(candidate.member_bytes("source-accountability.json"), "Daily Light accountability")
    expected_accountability = _expected_accountability(source_manifest, source)
    if accountability != expected_accountability or candidate.member_bytes("source-accountability.json") != _canonical(expected_accountability):
        raise ValueError("Daily Light exact source accountability drift")
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "Daily Light accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"Daily Light accountability schema failure: {errors[0].message}")
    if policy.get("required_counts") != {"index_records": 367, "index_sentinels": 1, "headers": 1, "header_bytes": 1550, "days": 366, "day_span_bytes": 1032386, "record_delimiters": 366, "record_delimiter_bytes": 732, "terminal_delimiters": 1, "terminal_tail_bytes": 2, "gaps": 367, "gap_bytes": 2282, "unexplained_gaps": 0, "periods": 732, "source_elements": 22298, "tag_counts": _TAG_COUNTS, "omitted": 0, "duplicate": 0, "unresolved": 0}:
        raise ValueError("Daily Light required census drift")
    if (
        policy.get("required_members") != list(_MEMBERS)
        or policy.get("required_member_roles") != _MEMBER_ROLES
    ):
        raise ValueError("Daily Light required member role drift")
    _verify_tei(source_manifest, candidate, source.days, expected_accountability, profile)
    provenance = _strict(candidate.member_bytes("provenance.json"), "Daily Light provenance")
    if provenance.get("contract") != "ocd-daily-light-candidate-provenance-v1" or provenance.get("status") != "nonaccepted" or provenance.get("ticket_id") != "LIB-006" or provenance.get("work_id") != "daily-light" or provenance.get("source_id") != source_manifest.record.get("source_id") or provenance.get("source_manifest_sha256") != source_manifest.sha256 or provenance.get("identity") != profile.get("identity") or provenance.get("rights") != profile.get("rights") or provenance.get("candidate_boundary") != {"acceptance_status": "nonaccepted", "publication_status": "not-authorized", "canonical_data_or_ir_written": False}:
        raise ValueError("Daily Light provenance or metadata drift")
    required_unresolved = ("daily-light-rights-review", "daily-light-human-acceptance")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines() if line.strip()]
    if [item.get("id") for item in unresolved] != list(required_unresolved) or any(item.get("status") != "unresolved" for item in unresolved):
        raise ValueError("Daily Light unresolved ledger drift")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("Daily Light attribution evidence drift")
    closure = _closure(source_manifest.repository_root)
    if closure != validator.get("import_closure_sha256"):
        raise ValueError("Daily Light oracle import closure drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _source_sha(source_manifest),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
