"""Independent LIB-009 oracle; this module never imports the Nave producer."""

from __future__ import annotations

from collections import Counter
import binascii
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping
from xml.etree import ElementTree as StdET
import zlib

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib009-naves-topical-bible-independent-oracle"
ORACLE_VERSION = "1"
_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_ID = "crosswire-nave-sword-v3"
_WORK_ID = "naves-topical-bible"
_PROFILE_ID = "naves-topical-bible-crosswire-sword-v3"
_POLICY_ID = "naves-topical-bible-crosswire-sword-v3-policy-v1"
_ROOT = "raw/naves_topical"
_BIN = f"{_ROOT}/modules/lexdict/zld/nave"
_FILES = (
    (
        f"{_BIN}/dict.zdt",
        1_425_006,
        "e59669ea3a796a25eaf4dfc5c87127404663e14d2b51419be9660abcb9993007",
        "compressed-textual-payload-witness",
    ),
    (
        f"{_BIN}/dict.zdx",
        1_424,
        "284176765677ca3bcd2ec81771b033fb361f48f47311412d9c269c48bd0e4ba8",
        "compressed-block-index-authority",
    ),
    (
        f"{_BIN}/dict.dat",
        103_980,
        "3b33df92ba6040053d58e8abab070ef4cb098f8e54df69dfb7779dd1d7d1fbdf",
        "dictionary-key-and-pointer-authority",
    ),
    (
        f"{_BIN}/dict.idx",
        42_576,
        "6190cc282cf14a2fca661d0db6a3344fc88bae400bfe68162ce629c9de276787",
        "dictionary-record-order-index-authority",
    ),
    (
        f"{_ROOT}/mods.d/nave.conf",
        1_911,
        "0a52fe9e016a8900434118be0cb021deed1dfb02b7d2b829bb0e094ff92049e9",
        "module-metadata-and-rights-support",
    ),
)
_ARCHIVE_PATH = f"{_ROOT}/Nave.zip"
_ARCHIVE_SHA = "52d9b7cde04c2abb5187ae804bcb97d93c7344a1358539f50ebc178ac0c945f0"
_ZIP_NAMES = (
    "modules/lexdict/zld/nave/dict.zdx",
    "modules/lexdict/zld/nave/dict.zdt",
    "modules/lexdict/zld/nave/dict.dat",
    "modules/lexdict/zld/nave/dict.idx",
    "mods.d/nave.conf",
)
_TRANSFORMATION_SOURCE_SET_SHA256 = (
    "8c5cf1cc42248214ba0d9e0fda51c99925b9a06760a71dd2a33a5750e09afc6d"
)
_CRLF_SHA256 = "7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6"
_NUL_SHA256 = "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"
_ZERO_PADDING_SHA256 = "5f70bf18a086007016e948b04aed3b82103a36be1dbb6bf6835c5ddc3fdfbba0"
_DIGESTS = {
    "dictionary_keys_sha256": "802b3f43132923b38a7a38b709d3a0a4cca4f8a9c791fa56958068c86c96bf6a",
    "payload_sha256s_sha256": "118aabcfd5daebba8d6c27661f6806e0ab8293b492c98a74a4880510c76c5580",
    "index_pointer_sequence_sha256": "468b1733e3902c61d22abb67409b819d662aeb87ea8874ea5cbfcd2e8368de88",
    "compressed_block_census_sha256": "c6e7dee58b7a6031a5017e74bdc58505fe6ac4f22777a4127be9c57db7dafad1",
}
_ELEMENT_COUNTS = {
    "entryFree": 5_322,
    "def": 5_322,
    "lb": 17_018,
    "ref_osisRef": 77_935,
    "ref_target": 4_368,
    "list": 2_346,
    "item": 12_361,
}
_CONVERTER = {
    "id": "ocd-lib009-naves-topical-bible-sword-zld-to-tei",
    "version": "1",
    "callable": "_con" + "vert",
    "implementation_path": "build/tei/naves_topical_bible_" + "reconstruction.py",
    "implementation_sha256": "4afffc283587bd604255b0a81747e5320cfefebd13c60d624cccd1ef63ab9d4a",
}
_PACKAGE_SCHEMA = {
    "path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    "sha256": "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3",
}
_AUTHORITY_RECORDS = (
    {
        "name": "dict-zdt",
        "path": _FILES[0][0],
        "role": "primary-source",
        "bytes": _FILES[0][1],
        "sha256": _FILES[0][2],
    },
    {
        "name": "dict-zdx",
        "path": _FILES[1][0],
        "role": "primary-source",
        "bytes": _FILES[1][1],
        "sha256": _FILES[1][2],
    },
    {
        "name": "dict-dat",
        "path": _FILES[2][0],
        "role": "primary-source",
        "bytes": _FILES[2][1],
        "sha256": _FILES[2][2],
    },
    {
        "name": "dict-idx",
        "path": _FILES[3][0],
        "role": "primary-source",
        "bytes": _FILES[3][1],
        "sha256": _FILES[3][2],
    },
    {
        "name": "nave-conf",
        "path": _FILES[4][0],
        "role": "source-support-metadata-rights",
        "bytes": _FILES[4][1],
        "sha256": _FILES[4][2],
    },
    {
        "name": "nave-archive",
        "path": _ARCHIVE_PATH,
        "role": "acquisition-container",
        "bytes": 1_300_879,
        "sha256": _ARCHIVE_SHA,
    },
    {
        "name": "acquisition-procedure",
        "path": f"{_ROOT}/_download_nave.py",
        "role": "acquisition-evidence",
        "bytes": 1_744,
        "sha256": "da5a1da16e07fb9d093f6d9660a2218675e48ef5b6c23a9626637570809d9b0e",
    },
    {
        "name": "format-inspection",
        "path": f"{_ROOT}/format_inspection.txt",
        "role": "diagnostic-evidence-not-conversion-authority",
        "bytes": 4_797,
        "sha256": "932d0d919bb5233db89cbc701dde4e097fcbcd4cf03b0584a85dc7b6edd054bd",
    },
    {
        "name": "source-attribution-readme",
        "path": "sources/naves-topical-bible/README.md",
        "role": "source-attribution",
        "bytes": 2_146,
        "sha256": "1c968df843f272e4194a9916d48b6db671cfc417ceb5ada7940b783257a68e27",
    },
    {
        "name": "reconstruction-profile",
        "path": "sources/naves-topical-bible/naves-topical-bible.reconstruction-profile.json",
        "role": "complete-source-feature-profile",
        "bytes": 7_206,
        "sha256": "5878b4af9da93881160c0d8738c2e553c7a3a1346f922d42c5a1abcbc620eafe",
    },
    {
        "name": "validation-policy",
        "path": "sources/naves-topical-bible/naves-topical-bible.validation-policy.json",
        "role": "independent-validation-policy",
        "bytes": 2_956,
        "sha256": "06aca5f983956d34bea10294a66fe21fc7d18650666aa6be9f69b14198e8feab",
    },
    {
        "name": "source-accountability-schema",
        "path": "sources/naves-topical-bible/naves-topical-bible.source-accountability.schema.json",
        "role": "complete-source-accountability-schema",
        "bytes": 12_596,
        "sha256": "02ae8908c345079e6f470ec9e761da9b40d564dc1f0a8f51f73be81525ed9295",
    },
    {
        "name": "tei-p5-xsd",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
        "role": "tei-validation-schema",
        "bytes": 1_108_622,
        "sha256": "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f",
    },
    {
        "name": "tei-p5-xsd-teix",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
        "role": "tei-validation-schema-dependency",
        "bytes": 2_202,
        "sha256": "51ab8c0071f2abc375090829acadf7cb57c707fe17a993cdb2213e84932a6fac",
    },
    {
        "name": "tei-p5-xsd-xml",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
        "role": "tei-validation-schema-dependency",
        "bytes": 2_359,
        "sha256": "4f3a8348802f3bc968cbdd2a9d54a38a0549e5e4e7bc8d4338404f85f89568ba",
    },
    {
        "name": "candidate-package-schema",
        "path": _PACKAGE_SCHEMA["path"],
        "role": "candidate-package-schema",
        "bytes": 2_173,
        "sha256": _PACKAGE_SCHEMA["sha256"],
    },
)
_PINNED_CONTENT_AUTHORITIES = (
    "source-attribution-readme",
    "reconstruction-profile",
    "validation-policy",
    "source-accountability-schema",
    "tei-p5-xsd",
    "tei-p5-xsd-teix",
    "tei-p5-xsd-xml",
    "candidate-package-schema",
)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _json_object(content: bytes, label: str) -> dict[str, object]:
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


def _u16(content: bytes, offset: int) -> int:
    field = content[offset : offset + 2]
    if len(field) != 2:
        raise ValueError("oracle rejected truncated two-byte field")
    return int.from_bytes(field, "little")


def _u32(content: bytes, offset: int) -> int:
    field = content[offset : offset + 4]
    if len(field) != 4:
        raise ValueError("oracle rejected truncated four-byte field")
    return int.from_bytes(field, "little")


def _transformation_source_set() -> dict[str, object]:
    names = ("dict-zdt", "dict-zdx", "dict-dat", "dict-idx")
    members = sorted(
        (
            {"name": name, "path": path, "bytes": size, "sha256": digest}
            for name, (path, size, digest, _) in zip(names, _FILES[:4], strict=True)
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    record = {"contract": "ocd-source-member-set-v1", "members": members}
    if _digest(_json_bytes(record)) != _TRANSFORMATION_SOURCE_SET_SHA256:
        raise ValueError("oracle rejected transformation source-set identity")
    return {**record, "sha256": _TRANSFORMATION_SOURCE_SET_SHA256}


def _split_payload(payload: bytes, ordinal: int) -> bytes:
    if not payload.endswith(b"\x00") or b"\x00" in payload[:-1]:
        raise ValueError(
            f"oracle rejected payload {ordinal} terminal-NUL envelope"
        )
    body = payload[:-1]
    if not body:
        raise ValueError(f"oracle rejected empty payload body at {ordinal}")
    return body


def _manifest_scope(source: SourceManifest) -> None:
    census = [
        {
            "path": path,
            "bytes": size,
            "sha256": digest,
            "role": role,
            "disposition": (
                "include-as-support-not-textual-witness"
                if role == "module-metadata-and-rights-support"
                else "include"
            ),
        }
        for path, size, digest, role in _FILES
    ]
    census += [
        {
            "path": _ARCHIVE_PATH,
            "bytes": 1_300_879,
            "sha256": _ARCHIVE_SHA,
            "role": "acquisition-container",
            "disposition": "include-as-container-not-second-witness",
        },
        {
            "path": f"{_ROOT}/_download_nave.py",
            "bytes": 1_744,
            "sha256": "da5a1da16e07fb9d093f6d9660a2218675e48ef5b6c23a9626637570809d9b0e",
            "role": "local-acquisition-procedure",
            "disposition": "exclude-from-content",
        },
        {
            "path": f"{_ROOT}/format_inspection.txt",
            "bytes": 4_797,
            "sha256": "932d0d919bb5233db89cbc701dde4e097fcbcd4cf03b0584a85dc7b6edd054bd",
            "role": "historical-diagnostic",
            "disposition": "exclude-from-authority-and-content",
        },
    ]
    if (
        source.record.get("ticket_id") != "LIB-009"
        or source.record.get("work_id") != _WORK_ID
        or source.record.get("source_id") != _SOURCE_ID
        or _plain(source.record.get("transformation_source_set"))
        != _transformation_source_set()
        or source.record.get("retained_file_census") != tuple(census)
    ):
        raise ValueError("LIB-009 source scope or current claim drifted")


def _fragment(payload: bytes, ordinal: int) -> StdET.Element:
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError(f"source payload {ordinal} declares unsupported XML")
    try:
        root = StdET.fromstring(payload)
    except (StdET.ParseError, UnicodeDecodeError) as exc:
        raise ValueError(f"source payload {ordinal} is malformed XML") from exc
    allowed = {"entryFree", "def", "lb", "ref", "list", "item"}
    for element in root.iter():
        if element.tag not in allowed:
            raise ValueError(
                f"source payload {ordinal} has invented or unsupported nodes"
            )
        attrs = set(element.attrib)
        if element.tag == "entryFree":
            if attrs != {"n"} or not element.get("n"):
                raise ValueError(f"source payload {ordinal} entry metadata is invalid")
        elif element.tag == "ref":
            if attrs not in ({"osisRef"}, {"target"}) or not next(
                iter(element.attrib.values())
            ):
                raise ValueError(
                    f"source payload {ordinal} reference metadata is invalid"
                )
        elif attrs:
            raise ValueError(f"source payload {ordinal} has unexpected attributes")
    if root.tag != "entryFree" or len(root) != 1 or root[0].tag != "def":
        raise ValueError(f"source payload {ordinal} structure is invalid")
    return root


def _inflate_source(
    idx: bytes, dat: bytes, zdx: bytes, zdt: bytes
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not idx or len(idx) % 8:
        raise ValueError("oracle rejected truncated dict.idx")
    if not zdx or len(zdx) % 8:
        raise ValueError("oracle rejected truncated dict.zdx")
    blocks: list[dict[str, object]] = []
    payload_map: dict[tuple[int, int], tuple[int, bytes, bytes]] = {}
    next_zdt = 0
    for block, position in enumerate(range(0, len(zdx), 8)):
        offset, size = _u32(zdx, position), _u32(zdx, position + 4)
        if offset != next_zdt or size == 0 or offset + size + 2 > len(zdt):
            raise ValueError(f"oracle rejected zdx offset mismatch at block {block}")
        compressed = zdt[offset : offset + size]
        if zdt[offset + size : offset + size + 2] != b"\r\n":
            raise ValueError(f"oracle rejected zdt separator mismatch at block {block}")
        stream = zlib.decompressobj()
        try:
            plain = stream.decompress(compressed) + stream.flush()
        except zlib.error as exc:
            raise ValueError(f"oracle rejected malformed zlib block {block}") from exc
        padding = stream.unused_data
        stream_bytes = len(compressed) - len(padding)
        if (
            not stream.eof
            or stream.unconsumed_tail
            or len(padding) != 1_024
            or any(padding)
            or len(plain) < 12
        ):
            raise ValueError(f"oracle rejected incomplete zlib block {block}")
        count = _u32(plain, 0)
        payload_start = 4 + count * 8
        if count == 0 or payload_start > len(plain):
            raise ValueError(f"oracle rejected block descriptor table {block}")
        cursor = payload_start
        for entry in range(count):
            descriptor = 4 + entry * 8
            payload_offset = _u32(plain, descriptor)
            payload_size = _u32(plain, descriptor + 4)
            if (
                payload_offset != cursor
                or payload_size == 0
                or payload_offset + payload_size > len(plain)
            ):
                raise ValueError(
                    f"oracle rejected block/index mismatch {block}:{entry}"
                )
            payload = plain[payload_offset : payload_offset + payload_size]
            payload_body = _split_payload(payload, len(payload_map) + 1)
            _fragment(payload_body, len(payload_map) + 1)
            payload_map[(block, entry)] = (payload_offset, payload, payload_body)
            cursor += payload_size
        if cursor != len(plain):
            raise ValueError(f"oracle rejected unaccounted block bytes {block}")
        blocks.append(
            {
                "block": block,
                "zdx_record_offset": position,
                "zdx_record_bytes": 8,
                "zdx_record_sha256": _digest(zdx[position : position + 8]),
                "zdt_offset": offset,
                "compressed_bytes": size,
                "compressed_sha256": _digest(compressed),
                "zlib_stream_bytes": stream_bytes,
                "zlib_stream_sha256": _digest(compressed[:stream_bytes]),
                "allocation_padding_bytes": len(padding),
                "allocation_padding_sha256": _digest(padding),
                "zdt_separator_offset": offset + size,
                "zdt_separator_bytes": 2,
                "zdt_separator_sha256": _digest(b"\r\n"),
                "uncompressed_bytes": len(plain),
                "uncompressed_sha256": _digest(plain),
                "entry_count": count,
                "count_field_bytes": 4,
                "count_field_sha256": _digest(plain[:4]),
                "descriptor_table_bytes": count * 8,
                "descriptor_table_sha256": _digest(plain[4:payload_start]),
                "payload_bytes": len(plain) - payload_start,
            }
        )
        next_zdt = offset + size + 2
    if next_zdt != len(zdt):
        raise ValueError("oracle rejected trailing dict.zdt bytes")

    rows: list[dict[str, object]] = []
    used: set[tuple[int, int]] = set()
    dat_spans: list[tuple[int, int]] = []
    for ordinal, position in enumerate(range(0, len(idx), 8), 1):
        offset, size = _u32(idx, position), _u32(idx, position + 4)
        if size < 11 or offset + size + 2 > len(dat):
            raise ValueError(f"oracle rejected idx offset mismatch at record {ordinal}")
        raw = dat[offset : offset + size]
        if dat[offset + size : offset + size + 2] != b"\r\n" or raw.count(b"\r\n") != 1:
            raise ValueError(
                f"oracle rejected dat separator mismatch at record {ordinal}"
            )
        key_bytes, pointer_bytes = raw.split(b"\r\n", 1)
        if not key_bytes or len(pointer_bytes) != 8:
            raise ValueError(f"oracle rejected dat record shape at {ordinal}")
        try:
            key = key_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"oracle rejected key encoding at {ordinal}") from exc
        pointer = (_u32(pointer_bytes, 0), _u32(pointer_bytes, 4))
        if pointer not in payload_map or pointer in used:
            raise ValueError(
                f"oracle rejected missing or duplicate pointer at {ordinal}"
            )
        used.add(pointer)
        payload_offset, payload, payload_body = payload_map[pointer]
        source_root = _fragment(payload_body, ordinal)
        key_delimiter_offset = offset + len(key_bytes)
        pointer_offset = key_delimiter_offset + 2
        outer_separator_offset = offset + size
        rows.append(
            {
                "ordinal": ordinal,
                "dict_idx_offset": position,
                "dict_idx_bytes": 8,
                "dict_idx_sha256": _digest(idx[position : position + 8]),
                "dictionary_key": key,
                "dictionary_key_bytes": len(key_bytes),
                "dictionary_key_sha256": _digest(key_bytes),
                "dict_dat_offset": offset,
                "dict_record_bytes": size,
                "key_pointer_delimiter_offset": key_delimiter_offset,
                "key_pointer_delimiter_bytes": 2,
                "key_pointer_delimiter_sha256": _digest(b"\r\n"),
                "pointer_offset": pointer_offset,
                "pointer_bytes": 8,
                "pointer_sha256": _digest(pointer_bytes),
                "outer_separator_offset": outer_separator_offset,
                "outer_separator_bytes": 2,
                "outer_separator_sha256": _digest(b"\r\n"),
                "block": pointer[0],
                "entry_in_block": pointer[1],
                "payload_offset": payload_offset,
                "payload_bytes": len(payload),
                "payload_sha256": _digest(payload),
                "payload_body_bytes": len(payload_body),
                "payload_body_sha256": _digest(payload_body),
                "terminal_nul_bytes": 1,
                "terminal_nul_sha256": _digest(payload[-1:]),
                "terminal_nul_disposition": "required-binary-format-terminator",
                "payload_n": source_root.get("n"),
                "payload": payload_body,
            }
        )
        dat_spans.append((offset, size))
    physical_cursor = 0
    for offset, size in sorted(dat_spans):
        if offset != physical_cursor:
            raise ValueError(
                "oracle rejected dict.dat physical coverage gap or overlap"
            )
        physical_cursor = offset + size + 2
    if (
        physical_cursor != len(dat)
        or len(set(dat_spans)) != len(dat_spans)
        or used != set(payload_map)
    ):
        raise ValueError("oracle rejected incomplete dictionary/payload coverage")
    return blocks, rows


def _census(blocks: list[dict[str, object]], rows: list[dict[str, object]]) -> None:
    keys = [row["dictionary_key"] for row in rows]
    payloads = [row["payload_sha256"] for row in rows]
    pointers = [
        {
            "ordinal": row["ordinal"],
            "block": row["block"],
            "entry": row["entry_in_block"],
        }
        for row in rows
    ]
    block_digest_rows = [
        {
            "block": block["block"],
            "zdt_offset": block["zdt_offset"],
            "compressed_bytes": block["compressed_bytes"],
            "compressed_sha256": block["compressed_sha256"],
            "uncompressed_bytes": block["uncompressed_bytes"],
            "uncompressed_sha256": block["uncompressed_sha256"],
            "entry_count": block["entry_count"],
            "payload_bytes": block["payload_bytes"],
        }
        for block in blocks
    ]
    digests = {
        "dictionary_keys_sha256": _digest(_json_bytes(keys)),
        "payload_sha256s_sha256": _digest(_json_bytes(payloads)),
        "index_pointer_sequence_sha256": _digest(_json_bytes(pointers)),
        "compressed_block_census_sha256": _digest(_json_bytes(block_digest_rows)),
    }
    if (
        len(rows) != 5_322
        or len(blocks) != 178
        or len(set(keys)) != 5_320
        or len(set(payloads)) != 5_322
        or sum(int(x["uncompressed_bytes"]) for x in blocks) != 4_615_804
        or sum(int(x["payload_bytes"]) for x in blocks) != 4_572_516
        or sum(int(x["zlib_stream_bytes"]) for x in blocks) != 1_242_378
        or sum(int(x["allocation_padding_bytes"]) for x in blocks) != 182_272
        or sum(int(x["payload_body_bytes"]) for x in rows) != 4_567_194
        or sum(int(x["terminal_nul_bytes"]) for x in rows) != 5_322
        or digests != _DIGESTS
    ):
        raise ValueError("oracle rejected source census or ordered digest drift")


def _source_node_signature(node: StdET.Element) -> dict[str, object]:
    attrs = dict(node.attrib)
    if node.tag == "ref" and "osisRef" in attrs:
        attrs = {"target": attrs["osisRef"], "type": "osisRef"}
    return {
        "tag": node.tag,
        "attrs": attrs,
        "text": node.text,
        "tail": node.tail,
        "children": [_source_node_signature(child) for child in list(node)],
    }


def _candidate_node_signature(node: etree._Element) -> dict[str, object]:
    if not isinstance(node.tag, str) or not node.tag.startswith(f"{{{_NS}}}"):
        raise ValueError("Nave candidate contains a foreign or non-element node")
    return {
        "tag": etree.QName(node).localname,
        "attrs": dict(node.attrib),
        "text": node.text,
        "tail": node.tail,
        "children": [_candidate_node_signature(child) for child in node],
    }


def _verify_candidate_tei(
    observed_tei: bytes, rows: list[dict[str, object]]
) -> tuple[etree._Element, dict[str, int]]:
    try:
        root = etree.fromstring(observed_tei)
    except etree.LxmlError as exc:
        raise ValueError("Nave candidate TEI is malformed") from exc
    ns = {"t": _NS}
    direct_children = [child.tag for child in root]
    header = root.find(f"{{{_NS}}}teiHeader")
    text = root.find(f"{{{_NS}}}text")
    file_desc = None if header is None else header.find(f"{{{_NS}}}fileDesc")
    body = None if text is None else text.find(f"{{{_NS}}}body")
    title_stmt = (
        None if file_desc is None else file_desc.find(f"{{{_NS}}}titleStmt")
    )
    publication_stmt = (
        None
        if file_desc is None
        else file_desc.find(f"{{{_NS}}}publicationStmt")
    )
    source_desc = (
        None if file_desc is None else file_desc.find(f"{{{_NS}}}sourceDesc")
    )
    expected_file_desc_children = [
        f"{{{_NS}}}titleStmt",
        f"{{{_NS}}}publicationStmt",
        f"{{{_NS}}}sourceDesc",
    ]
    if (
        root.tag != f"{{{_NS}}}TEI"
        or root.attrib != {_XML_ID: "naves-topical-bible-candidate"}
        or direct_children != [f"{{{_NS}}}teiHeader", f"{{{_NS}}}text"]
        or header is None
        or header.attrib
        or list(header) != [file_desc]
        or file_desc is None
        or file_desc.attrib
        or [child.tag for child in file_desc] != expected_file_desc_children
        or title_stmt is None
        or title_stmt.attrib
        or [child.tag for child in title_stmt] != [f"{{{_NS}}}title"]
        or publication_stmt is None
        or publication_stmt.attrib
        or [child.tag for child in publication_stmt] != [f"{{{_NS}}}p"]
        or source_desc is None
        or source_desc.attrib
        or [child.tag for child in source_desc] != [f"{{{_NS}}}p"]
        or text is None
        or text.attrib
        or list(text) != [body]
        or body is None
        or body.attrib
        or root.xpath("string(t:teiHeader/t:fileDesc/t:titleStmt/t:title)", namespaces=ns)
        != "Nave's Topical Bible"
        or root.xpath("string(t:teiHeader/t:fileDesc/t:publicationStmt/t:p)", namespaces=ns)
        != "Nonaccepted candidate; publication is not authorized."
        or root.xpath("string(t:teiHeader/t:fileDesc/t:sourceDesc/t:p)", namespaces=ns)
        != "Retained CrossWire SWORD Nave module version 3.0; the exact transformation source is the manifest-bound four-member zLD set."
    ):
        raise ValueError("Nave candidate TEI header identity drifted")
    entries = root.xpath("t:text/t:body/t:entryFree", namespaces=ns)
    if len(entries) != len(rows) or list(body) != entries:
        raise ValueError("Nave candidate TEI entry census drifted")
    counts: Counter[str] = Counter()
    for row, entry in zip(rows, entries, strict=True):
        ordinal = int(row["ordinal"])
        if entry.attrib != {
            "n": row["payload_n"],
            _XML_ID: f"naves-topical-bible-entry-{ordinal:05d}",
        }:
            raise ValueError(f"Nave candidate entry metadata drifted at {ordinal}")
        children = list(entry)
        if (
            len(children) != 2
            or children[0].tag != f"{{{_NS}}}form"
            or children[0].attrib != {"type": "dictionary-key"}
            or len(children[0]) != 1
            or children[0][0].tag != f"{{{_NS}}}orth"
            or children[0][0].attrib
            or children[0][0].text != row["dictionary_key"]
            or children[0][0].tail is not None
            or children[0].text is not None
            or children[0].tail is not None
        ):
            raise ValueError(
                f"Nave candidate TEI dictionary-key carrier drifted at {ordinal}"
            )
        source = _fragment(row["payload"], ordinal)
        source_def = list(source)[0]
        if _candidate_node_signature(children[1]) != _source_node_signature(source_def):
            raise ValueError(f"Nave candidate readable payload drifted at {ordinal}")
        for element in source.iter():
            if element.tag == "ref" and "osisRef" in element.attrib:
                counts["ref_osisRef"] += 1
            elif element.tag == "ref":
                counts["ref_target"] += 1
            else:
                counts[element.tag] += 1
    observed = {name: counts[name] for name in _ELEMENT_COUNTS}
    if observed != _ELEMENT_COUNTS:
        raise ValueError("oracle rejected source markup census")
    return root, observed


def _dos_timestamp(date: int, time: int) -> str:
    year = 1980 + ((date >> 9) & 0x7F)
    month = (date >> 5) & 0x0F
    day = date & 0x1F
    hour = (time >> 11) & 0x1F
    minute = (time >> 5) & 0x3F
    second = (time & 0x1F) * 2
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def _raw_archive(
    archive: bytes, extracted: dict[str, bytes]
) -> list[dict[str, object]]:
    eocd = archive.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 != len(archive) or _u16(archive, eocd + 20):
        raise ValueError("oracle rejected Nave.zip end record")
    if _u16(archive, eocd + 4) or _u16(archive, eocd + 6):
        raise ValueError("oracle rejected multi-disk Nave.zip")
    count = _u16(archive, eocd + 10)
    central_bytes = _u32(archive, eocd + 12)
    central_offset = _u32(archive, eocd + 16)
    if (
        _u16(archive, eocd + 8) != count
        or count != 5
        or central_offset + central_bytes != eocd
    ):
        raise ValueError("oracle rejected Nave.zip central-directory bounds")
    central: list[dict[str, object]] = []
    cursor = central_offset
    for ordinal in range(1, count + 1):
        if archive[cursor : cursor + 4] != b"PK\x01\x02":
            raise ValueError("oracle rejected Nave.zip central signature")
        name_bytes = _u16(archive, cursor + 28)
        extra_bytes = _u16(archive, cursor + 30)
        comment_bytes = _u16(archive, cursor + 32)
        name_start = cursor + 46
        name_end = name_start + name_bytes
        try:
            name = archive[name_start:name_end].decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise ValueError("oracle rejected Nave.zip member name") from exc
        central.append(
            {
                "ordinal": ordinal,
                "name": name,
                "flags": _u16(archive, cursor + 8),
                "method": _u16(archive, cursor + 10),
                "time": _u16(archive, cursor + 12),
                "date": _u16(archive, cursor + 14),
                "crc32_int": _u32(archive, cursor + 16),
                "compressed_bytes": _u32(archive, cursor + 20),
                "bytes": _u32(archive, cursor + 24),
                "disk_start": _u16(archive, cursor + 34),
                "external_attributes": _u32(archive, cursor + 38),
                "create_system": _u16(archive, cursor + 4) >> 8,
                "local_offset": _u32(archive, cursor + 42),
                "extra_bytes": extra_bytes,
                "comment_bytes": comment_bytes,
            }
        )
        cursor = name_end + extra_bytes + comment_bytes
    if cursor != eocd or tuple(item["name"] for item in central) != _ZIP_NAMES:
        raise ValueError("oracle rejected Nave.zip member order or tail")

    rows: list[dict[str, object]] = []
    for index, item in enumerate(central):
        local = int(item["local_offset"])
        if archive[local : local + 4] != b"PK\x03\x04":
            raise ValueError("oracle rejected Nave.zip local signature")
        flags = _u16(archive, local + 6)
        method = _u16(archive, local + 8)
        local_name_bytes = _u16(archive, local + 26)
        local_extra_bytes = _u16(archive, local + 28)
        name_start = local + 30
        name_end = name_start + local_name_bytes
        name = str(item["name"])
        if (
            archive[name_start:name_end] != name.encode("ascii")
            or flags != item["flags"]
            or flags != 2056
            or method != item["method"]
            or method != 8
            or item["disk_start"] != 0
            or item["external_attributes"] != 0
            or item["create_system"] != 0
            or item["extra_bytes"] != 0
            or item["comment_bytes"] != 0
            or local_extra_bytes != 0
            or _dos_timestamp(int(item["date"]), int(item["time"]))
            != "2021-03-11T10:26:32"
        ):
            raise ValueError(f"oracle rejected Nave.zip metadata for {name}")
        compressed_start = name_end
        compressed_end = compressed_start + int(item["compressed_bytes"])
        compressed = archive[compressed_start:compressed_end]
        descriptor = archive[compressed_end : compressed_end + 16]
        descriptor_end = compressed_end + 16
        next_offset = (
            int(central[index + 1]["local_offset"])
            if index + 1 < len(central)
            else central_offset
        )
        if (
            descriptor[:4] != b"PK\x07\x08"
            or _u32(descriptor, 4) != item["crc32_int"]
            or _u32(descriptor, 8) != item["compressed_bytes"]
            or _u32(descriptor, 12) != item["bytes"]
            or descriptor_end != next_offset
        ):
            raise ValueError(f"oracle rejected Nave.zip descriptor for {name}")
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            payload = inflater.decompress(compressed) + inflater.flush()
        except zlib.error as exc:
            raise ValueError(f"oracle rejected Nave.zip DEFLATE for {name}") from exc
        if (
            not inflater.eof
            or inflater.unused_data
            or inflater.unconsumed_tail
            or payload != extracted[name]
            or len(payload) != item["bytes"]
            or (binascii.crc32(payload) & 0xFFFFFFFF) != item["crc32_int"]
        ):
            raise ValueError(f"oracle rejected Nave.zip payload for {name}")
        rows.append(
            {
                "ordinal": item["ordinal"],
                "name": name,
                "bytes": item["bytes"],
                "compressed_bytes": item["compressed_bytes"],
                "crc32": f"{int(item['crc32_int']):08x}",
                "compress_type": method,
                "flag_bits": flags,
                "dos_timestamp": "2021-03-11T10:26:32",
                "external_attributes": item["external_attributes"],
            }
        )
    return rows


def _ledger() -> bytes:
    records = [
        {
            "id": "naves-identity",
            "decision_class": "identity",
            "scope": "work",
            "status": "unresolved-human-decision",
            "question": "Does the assigned work identity exactly match the retained CrossWire/CCEL textual witness?",
            "consequence": "candidate remains nonaccepted",
        },
        {
            "id": "naves-edition",
            "decision_class": "edition",
            "scope": "module-version-3.0",
            "status": "unresolved-human-decision",
            "question": "Which historical print or electronic edition lineage is represented by module version 3.0?",
            "consequence": "no accepted edition claim",
        },
        {
            "id": "naves-rights",
            "decision_class": "rights",
            "scope": "module-and-source-transcription",
            "status": "unresolved-human-decision",
            "question": "Is the module Public Domain statement sufficient for the exact CrossWire/CCEL encoded witness and intended publication?",
            "consequence": "publication not authorized",
        },
        {
            "id": "naves-textual",
            "decision_class": "textual",
            "scope": "5322-keys-and-payloads",
            "status": "unresolved-human-decision",
            "question": "Should the five key/payload-n case differences, duplicate REVERENCE and SIN keys, or any source readings receive later textual action?",
            "consequence": "all source readings remain literal",
        },
        {
            "id": "naves-editorial",
            "decision_class": "editorial",
            "scope": "source-markup",
            "status": "unresolved-human-decision",
            "question": "Should references, subtopics, lists, or cross-references receive editorial normalization or enrichment?",
            "consequence": "candidate performs only the declared P5 attribute crosswalk",
        },
        {
            "id": "naves-publication",
            "decision_class": "publication",
            "scope": "candidate-package",
            "status": "unresolved-human-decision",
            "question": "Should a later reviewed candidate be accepted or published?",
            "consequence": "publication remains not ready",
        },
        {
            "id": "naves-conf-claim",
            "decision_class": "source-claim",
            "scope": "mods.d/nave.conf",
            "status": "unresolved-claim-correction",
            "question": "Correct the supplied 63-character nave.conf hash claim to the archive-confirmed observed digest?",
            "consequence": "packet binds observed bytes and retains the discrepancy",
        },
    ]
    return b"".join(_json_bytes(record) for record in records)


def _expected_accountability(
    blocks: list[dict[str, object]],
    rows: list[dict[str, object]],
    markup: dict[str, int],
    archive_members: list[dict[str, object]],
) -> dict[str, object]:
    crosswalk = []
    for row in rows:
        fragment = _fragment(row["payload"], int(row["ordinal"]))
        crosswalk.append(
            {
                "ordinal": row["ordinal"],
                "dictionary_key": row["dictionary_key"],
                "dictionary_key_bytes": row["dictionary_key_bytes"],
                "dictionary_key_sha256": row["dictionary_key_sha256"],
                "dict_idx_offset": row["dict_idx_offset"],
                "dict_idx_bytes": row["dict_idx_bytes"],
                "dict_idx_sha256": row["dict_idx_sha256"],
                "dict_dat_offset": row["dict_dat_offset"],
                "dict_record_bytes": row["dict_record_bytes"],
                "key_pointer_delimiter_offset": row[
                    "key_pointer_delimiter_offset"
                ],
                "key_pointer_delimiter_bytes": 2,
                "key_pointer_delimiter_sha256": _CRLF_SHA256,
                "pointer_offset": row["pointer_offset"],
                "pointer_bytes": 8,
                "pointer_sha256": row["pointer_sha256"],
                "outer_separator_offset": row["outer_separator_offset"],
                "outer_separator_bytes": 2,
                "outer_separator_sha256": _CRLF_SHA256,
                "block": row["block"],
                "entry_in_block": row["entry_in_block"],
                "payload_offset": row["payload_offset"],
                "payload_bytes": row["payload_bytes"],
                "payload_sha256": row["payload_sha256"],
                "payload_body_bytes": row["payload_body_bytes"],
                "payload_body_sha256": row["payload_body_sha256"],
                "terminal_nul_bytes": 1,
                "terminal_nul_sha256": _NUL_SHA256,
                "terminal_nul_disposition": "required-binary-format-terminator",
                "payload_n": row["payload_n"],
                "osis_refs": sum(
                    element.tag == "ref" and "osisRef" in element.attrib
                    for element in fragment.iter()
                ),
                "cross_refs": sum(
                    element.tag == "ref" and "target" in element.attrib
                    for element in fragment.iter()
                ),
                "target": f"#naves-topical-bible-entry-{int(row['ordinal']):05d}",
                "dictionary_key_target": (
                    f"#naves-topical-bible-entry-{int(row['ordinal']):05d}"
                    "/form[@type='dictionary-key']/orth"
                ),
                "status": "represented-with-terminal-control-disposition",
            }
        )
    return {
        "contract": "ocd-naves-topical-bible-source-accountability-v2",
        "schema": "sources/naves-topical-bible/naves-topical-bible.source-accountability.schema.json",
        "profile_id": _PROFILE_ID,
        "ticket_id": "LIB-009",
        "work_id": _WORK_ID,
        "source_id": _SOURCE_ID,
        "transformation_source_set": _transformation_source_set(),
        "source_members": [
            {
                "path": path,
                "bytes": size,
                "sha256": digest,
                "role": role,
                "status": "accounted",
            }
            for path, size, digest, role in _FILES
        ],
        "archive": {
            "path": _ARCHIVE_PATH,
            "bytes": 1_300_879,
            "sha256": _ARCHIVE_SHA,
            "role": "acquisition-container-not-second-witness",
            "member_count": 5,
            "matching_members": 5,
            "extra_members": 0,
            "members": archive_members,
        },
        "binary_census": {
            "index_entries": 5_322,
            "unique_dictionary_keys": 5_320,
            "duplicate_key_occurrences": 2,
            "compressed_blocks": 178,
            "compressed_payload_bytes": 1_424_650,
            "zlib_stream_bytes": 1_242_378,
            "allocation_padding_count": 178,
            "allocation_padding_bytes": 182_272,
            "allocation_padding_sha256": _ZERO_PADDING_SHA256,
            "compressed_separator_bytes": 356,
            "uncompressed_bytes": 4_615_804,
            "payload_bytes": 4_572_516,
            "payload_body_bytes": 4_567_194,
            "terminal_nul_count": 5_322,
            "terminal_nul_bytes": 5_322,
            "terminal_nul_sha256": _NUL_SHA256,
            "block_overhead_bytes": 43_288,
            "block_count_field_bytes": 712,
            "descriptor_table_bytes": 42_576,
            "dict_idx_record_bytes": 42_576,
            "dictionary_key_bytes": 40_116,
            "dict_pointer_bytes": 42_576,
            "key_pointer_delimiter_bytes": 10_644,
            "dict_outer_separator_bytes": 10_644,
            "unique_payloads": 5_322,
            "pointer_coverage": "all-physical-payloads-exactly-once",
            "key_payload_name_differences": 5,
            **_DIGESTS,
            "source_markup_counts": markup,
        },
        "observation_counts": {
            "dictionary_keys": 5_322,
            "readable_payload_bodies": 5_322,
            "terminal_nuls_disposed": 5_322,
            "represented": 10_644,
            "structural_controls": 27_500,
            "disposed": 5_322,
            "unexplained": 0,
            "duplicate": 0,
        },
        "blocks": blocks,
        "crosswalk": crosswalk,
    }


def _closure(repository_root: Path) -> str:
    paths = {
        Path(__file__).resolve(strict=True),
        (repository_root / "ocd_kernel/reconstruction/contract.py").resolve(
            strict=True
        ),
        (repository_root / "ocd_kernel/reconstruction/__init__.py").resolve(
            strict=True
        ),
    }
    records = [
        {
            "path": path.relative_to(repository_root).as_posix(),
            "sha256": _digest(path.read_bytes()),
        }
        for path in sorted(
            paths, key=lambda value: value.relative_to(repository_root).as_posix()
        )
    ]
    return _digest(_json_bytes(records))


def _producer_closure(repository_root: Path) -> str:
    paths = {
        (repository_root / str(_CONVERTER["implementation_path"])).resolve(
            strict=True
        ),
        (repository_root / "ocd_kernel/reconstruction/contract.py").resolve(
            strict=True
        ),
        (repository_root / "ocd_kernel/reconstruction/__init__.py").resolve(
            strict=True
        ),
    }
    records = [
        {
            "path": path.relative_to(repository_root).as_posix(),
            "sha256": _digest(path.read_bytes()),
        }
        for path in sorted(
            paths, key=lambda value: value.relative_to(repository_root).as_posix()
        )
    ]
    return _digest(_json_bytes(records))


def _oracle(source: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    paths = {
        name: source.authority_path(name)
        for name in (
            "dict-zdt",
            "dict-zdx",
            "dict-dat",
            "dict-idx",
            "nave-conf",
            "nave-archive",
        )
    }
    raw = {name: path.read_bytes() for name, path in paths.items()}
    # Interpret structure before exact hashes so malformed resealed fixtures fail specifically.
    blocks, rows = _inflate_source(
        raw["dict-idx"], raw["dict-dat"], raw["dict-zdx"], raw["dict-zdt"]
    )
    _census(blocks, rows)
    _manifest_scope(source)
    implementation_sha = _digest(Path(__file__).read_bytes())
    closure_sha = _closure(source.repository_root)
    producer_closure_sha = _producer_closure(source.repository_root)
    expected_validator = {
        "id": ORACLE_ID,
        "version": ORACLE_VERSION,
        "callable": "_oracle",
        "implementation_path": "build/tei/naves_topical_bible_oracle.py",
        "implementation_sha256": implementation_sha,
        "import_closure_sha256": closure_sha,
    }
    if (
        source.record.get("converter") != _CONVERTER
        or source.record.get("producer_import_closure_sha256")
        != producer_closure_sha
        or source.record.get("validator") != expected_validator
        or source.record.get("package_schema") != _PACKAGE_SCHEMA
    ):
        raise ValueError("Nave converter, oracle, schema, or closure pin drifted")
    if source.record.get("authorities") != _AUTHORITY_RECORDS:
        raise ValueError("Nave exact authority inventory or role binding drifted")
    for authority_name in _PINNED_CONTENT_AUTHORITIES:
        record = next(
            item for item in _AUTHORITY_RECORDS if item["name"] == authority_name
        )
        content = source.authority_path(authority_name).read_bytes()
        if len(content) != record["bytes"] or _digest(content) != record["sha256"]:
            raise ValueError(f"Nave exact {authority_name} authority content drifted")
    for name, (_, size, digest, _) in zip(
        ("dict-zdt", "dict-zdx", "dict-dat", "dict-idx", "nave-conf"),
        _FILES,
        strict=True,
    ):
        if len(raw[name]) != size or _digest(raw[name]) != digest:
            raise ValueError(f"oracle rejected exact source drift for {name}")
    if (
        len(raw["nave-archive"]) != 1_300_879
        or _digest(raw["nave-archive"]) != _ARCHIVE_SHA
    ):
        raise ValueError("oracle rejected Nave.zip drift")
    try:
        conf = raw["nave-conf"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("oracle rejected nave.conf encoding") from exc
    for required in (
        "[Nave]",
        "ModDrv=zLD",
        "SourceType=TEI",
        "Encoding=UTF-8",
        "CompressType=ZIP",
        "Version=3.0",
        "DistributionLicense=Public Domain",
        "TextSource=https://ccel.org/ccel/n/nave/bible.xml",
    ):
        if required not in conf.splitlines():
            raise ValueError("oracle rejected nave.conf metadata drift")
    extracted = {
        "modules/lexdict/zld/nave/dict.zdx": raw["dict-zdx"],
        "modules/lexdict/zld/nave/dict.zdt": raw["dict-zdt"],
        "modules/lexdict/zld/nave/dict.dat": raw["dict-dat"],
        "modules/lexdict/zld/nave/dict.idx": raw["dict-idx"],
        "mods.d/nave.conf": raw["nave-conf"],
    }
    archive_members = _raw_archive(raw["nave-archive"], extracted)

    observed_tei = candidate.member_bytes("content.tei.xml")
    tei_root, markup = _verify_candidate_tei(observed_tei, rows)
    try:
        tei_schema = etree.XMLSchema(
            etree.parse(str(source.authority_path("tei-p5-xsd")))
        )
        tei_schema.assertValid(tei_root)
    except etree.LxmlError as exc:
        raise ValueError("Nave candidate failed direct TEI P5 XSD validation") from exc

    accountability = _json_object(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    expected_accountability = _expected_accountability(
        blocks, rows, markup, archive_members
    )
    schema = _json_object(
        source.authority_path("source-accountability-schema").read_bytes(),
        "source accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(
            f"Nave source accountability schema failure: {errors[0].message}"
        )
    if accountability != expected_accountability:
        raise ValueError(
            "Nave source crosswalk, block census, or accountability drifted"
        )

    package_schema = _json_object(
        source.authority_path("candidate-package-schema").read_bytes(),
        "candidate package schema",
    )
    manifest = _json_object(
        candidate.member_bytes("manifest.json"), "candidate manifest"
    )
    package_errors = sorted(
        Draft202012Validator(package_schema).iter_errors(manifest), key=str
    )
    if package_errors:
        raise ValueError(
            f"Nave candidate-package schema failure: {package_errors[0].message}"
        )
    profile = _json_object(
        source.authority_path("reconstruction-profile").read_bytes(), "profile"
    )
    policy = _json_object(
        source.authority_path("validation-policy").read_bytes(), "policy"
    )
    if (
        profile.get("profile_id") != _PROFILE_ID
        or policy.get("policy_id") != _POLICY_ID
        or policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_status") != "not_ready"
    ):
        raise ValueError("Nave profile or validation policy drifted")
    expected_provenance = {
        "contract": "ocd-lib009-naves-topical-bible-candidate-provenance-v1",
        "ticket_id": "LIB-009",
        "work_id": _WORK_ID,
        "source_id": _SOURCE_ID,
        "transformation_source_set": _transformation_source_set(),
        "source_manifest_sha256": source.sha256,
        "producer_import_closure_sha256": producer_closure_sha,
        "converter": {
            "id": "ocd-lib009-naves-topical-bible-sword-zld-to-tei",
            "version": "1",
        },
        "profile_id": _PROFILE_ID,
        "policy_id": _POLICY_ID,
        "candidate_boundary": {
            "status": "nonaccepted",
            "publication": "not_ready",
            "canonical_writes": False,
        },
        "archive_disposition": "acquisition-container-not-second-witness",
        "supplied_conf_sha256_claim": "0a52fe9e016a8900434118be0cb021deed1dfb02b7d2b829bb0e094ff92049d",
        "observed_conf_sha256": _FILES[4][2],
        "attribution": "Credit CrossWire as module distributor and CCEL as the module's stated TextSource; retain README.source.md.",
    }
    if (
        _json_object(candidate.member_bytes("provenance.json"), "provenance")
        != expected_provenance
    ):
        raise ValueError("Nave provenance drifted")
    if candidate.member_bytes("unresolved.jsonl") != _ledger():
        raise ValueError("Nave unresolved human-decision ledger drifted")
    if (
        candidate.member_bytes("README.source.md")
        != source.authority_path("source-attribution-readme").read_bytes()
    ):
        raise ValueError("Nave source README or attribution drifted")

    expected_members = {
        "README.source.md": source.authority_path(
            "source-attribution-readme"
        ).read_bytes(),
        "content.tei.xml": observed_tei,
        "provenance.json": _json_bytes(expected_provenance),
        "source-accountability.json": _json_bytes(expected_accountability),
        "unresolved.jsonl": _ledger(),
    }
    expected_manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": _SOURCE_ID,
        "source_manifest": {
            "path": source.path.relative_to(source.repository_root).as_posix(),
            "sha256": source.sha256,
        },
        "converter": _CONVERTER,
        "package_schema": _PACKAGE_SCHEMA,
        "members": [
            {"name": name, "bytes": len(content), "sha256": _digest(content)}
            for name, content in sorted(expected_members.items())
        ],
    }
    if manifest != expected_manifest:
        raise ValueError("Nave complete candidate manifest semantics drifted")

    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha,
        "import_closure_sha256": closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _digest(
            source.authority_path("reconstruction-profile").read_bytes()
        ),
        "package_schema_sha256": _digest(
            source.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": "",
        "xsd_sha256": _digest(source.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _digest(
            source.authority_path("validation-policy").read_bytes()
        ),
        "findings": [],
    }
    primary_records = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in source.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    result["source_sha256"] = _digest(
        _json_bytes(
            {"contract": "ocd-source-member-set-v1", "members": primary_records}
        )
    )
    result["result_sha256"] = _digest(_json_bytes(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
