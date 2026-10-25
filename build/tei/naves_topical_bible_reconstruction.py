"""LIB-009 producer for the retained CrossWire Nave SWORD zLD module."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
from typing import Mapping
import zipfile
import zlib

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib009-naves-topical-bible-sword-zld-to-tei"
CONVERTER_VERSION = "1"
_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_WORK_ID = "naves-topical-bible"
_SOURCE_ID = "crosswire-nave-sword-v3"
_PROFILE_ID = "naves-topical-bible-crosswire-sword-v3"
_POLICY_ID = "naves-topical-bible-crosswire-sword-v3-policy-v1"
_SOURCE_ROOT = "raw/naves_topical"
_ZLD_ROOT = f"{_SOURCE_ROOT}/modules/lexdict/zld/nave"

_MEMBERS = (
    (
        f"{_ZLD_ROOT}/dict.zdt",
        1_425_006,
        "e59669ea3a796a25eaf4dfc5c87127404663e14d2b51419be9660abcb9993007",
        "compressed-textual-payload-witness",
    ),
    (
        f"{_ZLD_ROOT}/dict.zdx",
        1_424,
        "284176765677ca3bcd2ec81771b033fb361f48f47311412d9c269c48bd0e4ba8",
        "compressed-block-index-authority",
    ),
    (
        f"{_ZLD_ROOT}/dict.dat",
        103_980,
        "3b33df92ba6040053d58e8abab070ef4cb098f8e54df69dfb7779dd1d7d1fbdf",
        "dictionary-key-and-pointer-authority",
    ),
    (
        f"{_ZLD_ROOT}/dict.idx",
        42_576,
        "6190cc282cf14a2fca661d0db6a3344fc88bae400bfe68162ce629c9de276787",
        "dictionary-record-order-index-authority",
    ),
    (
        f"{_SOURCE_ROOT}/mods.d/nave.conf",
        1_911,
        "0a52fe9e016a8900434118be0cb021deed1dfb02b7d2b829bb0e094ff92049e9",
        "module-metadata-and-rights-support",
    ),
)
_ARCHIVE = (
    f"{_SOURCE_ROOT}/Nave.zip",
    1_300_879,
    "52d9b7cde04c2abb5187ae804bcb97d93c7344a1358539f50ebc178ac0c945f0",
)
_ARCHIVE_NAMES = (
    "modules/lexdict/zld/nave/dict.zdx",
    "modules/lexdict/zld/nave/dict.zdt",
    "modules/lexdict/zld/nave/dict.dat",
    "modules/lexdict/zld/nave/dict.idx",
    "mods.d/nave.conf",
)
_MEMBER_AUTHORITY_NAMES = ("dict-zdt", "dict-zdx", "dict-dat", "dict-idx")
_TRANSFORMATION_SOURCE_SET_SHA256 = (
    "8c5cf1cc42248214ba0d9e0fda51c99925b9a06760a71dd2a33a5750e09afc6d"
)
_CRLF_SHA256 = "7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6"
_NUL_SHA256 = "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"
_ZERO_PADDING_SHA256 = "5f70bf18a086007016e948b04aed3b82103a36be1dbb6bf6835c5ddc3fdfbba0"
_ORDERED_DIGESTS = {
    "dictionary_keys_sha256": "802b3f43132923b38a7a38b709d3a0a4cca4f8a9c791fa56958068c86c96bf6a",
    "payload_sha256s_sha256": "118aabcfd5daebba8d6c27661f6806e0ab8293b492c98a74a4880510c76c5580",
    "index_pointer_sequence_sha256": "468b1733e3902c61d22abb67409b819d662aeb87ea8874ea5cbfcd2e8368de88",
    "compressed_block_census_sha256": "c6e7dee58b7a6031a5017e74bdc58505fe6ac4f22777a4127be9c57db7dafad1",
}
_MARKUP_COUNTS = {
    "entryFree": 5_322,
    "def": 5_322,
    "lb": 17_018,
    "ref_osisRef": 77_935,
    "ref_target": 4_368,
    "list": 2_346,
    "item": 12_361,
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
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


def _transformation_source_set() -> dict[str, object]:
    members = sorted(
        (
            {"name": name, "path": path, "bytes": size, "sha256": digest}
            for name, (path, size, digest, _) in zip(
                _MEMBER_AUTHORITY_NAMES, _MEMBERS[:4], strict=True
            )
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    record = {"contract": "ocd-source-member-set-v1", "members": members}
    if _sha(_canonical(record)) != _TRANSFORMATION_SOURCE_SET_SHA256:
        raise ValueError("LIB-009 transformation source-set identity drifted")
    return {**record, "sha256": _TRANSFORMATION_SOURCE_SET_SHA256}


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
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(
            paths, key=lambda value: value.relative_to(repository_root).as_posix()
        )
    ]
    return _sha(_canonical(records))


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


def _source_paths(source: SourceManifest) -> dict[str, Path]:
    names = {
        "dict-zdt": f"{_ZLD_ROOT}/dict.zdt",
        "dict-zdx": f"{_ZLD_ROOT}/dict.zdx",
        "dict-dat": f"{_ZLD_ROOT}/dict.dat",
        "dict-idx": f"{_ZLD_ROOT}/dict.idx",
        "nave-conf": f"{_SOURCE_ROOT}/mods.d/nave.conf",
        "nave-archive": f"{_SOURCE_ROOT}/Nave.zip",
    }
    result = {name: source.authority_path(name) for name in names}
    for name, expected in names.items():
        actual = next(
            (
                record.get("path")
                for record in source.record["authorities"]
                if record.get("name") == name
            ),
            None,
        )
        if actual != expected:
            raise ValueError(f"LIB-009 authority path drifted for {name}")
    return result


def _verify_scope(source: SourceManifest) -> None:
    expected_census = [
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
        for path, size, digest, role in _MEMBERS
    ]
    expected_census.extend(
        [
            {
                "path": f"{_SOURCE_ROOT}/Nave.zip",
                "bytes": 1_300_879,
                "sha256": _ARCHIVE[2],
                "role": "acquisition-container",
                "disposition": "include-as-container-not-second-witness",
            },
            {
                "path": f"{_SOURCE_ROOT}/_download_nave.py",
                "bytes": 1_744,
                "sha256": "da5a1da16e07fb9d093f6d9660a2218675e48ef5b6c23a9626637570809d9b0e",
                "role": "local-acquisition-procedure",
                "disposition": "exclude-from-content",
            },
            {
                "path": f"{_SOURCE_ROOT}/format_inspection.txt",
                "bytes": 4_797,
                "sha256": "932d0d919bb5233db89cbc701dde4e097fcbcd4cf03b0584a85dc7b6edd054bd",
                "role": "historical-diagnostic",
                "disposition": "exclude-from-authority-and-content",
            },
        ]
    )
    if (
        source.record.get("ticket_id") != "LIB-009"
        or source.record.get("work_id") != _WORK_ID
        or source.record.get("source_id") != _SOURCE_ID
        or _plain(source.record.get("transformation_source_set"))
        != _transformation_source_set()
        or source.record.get("retained_file_census")
        != tuple({key: value for key, value in row.items()} for row in expected_census)
    ):
        raise ValueError("LIB-009 retained source scope drifted")


def _strict_conf(content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("nave.conf is not strict UTF-8") from exc
    required = {
        "[Nave]",
        "DataPath=./modules/lexdict/zld/nave/dict",
        "ModDrv=zLD",
        "SourceType=TEI",
        "Encoding=UTF-8",
        "CompressType=ZIP",
        "Version=3.0",
        "History_3.0=(2021-02-28) New source from ccel.org. Solves MOD-390",
        "DistributionLicense=Public Domain",
        "TextSource=https://ccel.org/ccel/n/nave/bible.xml",
        "InstallSize=1572986",
    }
    lines = set(text.splitlines())
    missing = sorted(required - lines)
    if missing:
        raise ValueError(f"nave.conf required metadata drifted: {missing[0]}")


def _archive_members(
    archive_path: Path, extracted: Mapping[str, bytes]
) -> list[dict[str, object]]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or tuple(names) != _ARCHIVE_NAMES:
                raise ValueError("Nave.zip member scope or order drifted")
            rows: list[dict[str, object]] = []
            for info in infos:
                name = info.filename
                if archive.read(name) != extracted[name]:
                    raise ValueError(
                        f"Nave.zip member bytes differ from extracted {name}"
                    )
                if (
                    info.compress_type != zipfile.ZIP_DEFLATED
                    or info.date_time != (2021, 3, 11, 10, 26, 32)
                    or info.external_attr != 0
                    or info.flag_bits != 2056
                    or info.create_system != 0
                    or info.extra
                    or info.comment
                ):
                    raise ValueError(f"Nave.zip member metadata drifted for {name}")
                rows.append(
                    {
                        "ordinal": len(rows) + 1,
                        "name": name,
                        "bytes": info.file_size,
                        "compressed_bytes": info.compress_size,
                        "crc32": f"{info.CRC:08x}",
                        "compress_type": info.compress_type,
                        "flag_bits": info.flag_bits,
                        "dos_timestamp": "2021-03-11T10:26:32",
                        "external_attributes": info.external_attr,
                    }
                )
            return rows
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("Nave.zip is unreadable or malformed") from exc


def _split_payload(payload: bytes, ordinal: int) -> bytes:
    if not payload.endswith(b"\x00") or payload[:-1].find(b"\x00") >= 0:
        raise ValueError(
            f"payload {ordinal} must contain exactly one terminal NUL byte"
        )
    body = payload[:-1]
    if not body:
        raise ValueError(f"payload {ordinal} has an empty readable XML body")
    return body


def _source_fragment(payload: bytes, ordinal: int) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        root = etree.fromstring(payload, parser=parser)
    except etree.LxmlError as exc:
        raise ValueError(f"payload {ordinal} is not strict XML") from exc
    allowed = {"entryFree", "def", "lb", "ref", "list", "item"}
    for node in root.iter():
        if not isinstance(node.tag, str) or node.tag not in allowed:
            raise ValueError(f"payload {ordinal} has unsupported XML node")
        attrs = set(node.attrib)
        if node.tag == "entryFree":
            if attrs != {"n"} or not node.get("n"):
                raise ValueError(f"payload {ordinal} entryFree attributes drifted")
        elif node.tag == "ref":
            if attrs not in ({"osisRef"}, {"target"}) or not next(
                iter(node.attrib.values())
            ):
                raise ValueError(f"payload {ordinal} ref attributes drifted")
        elif attrs:
            raise ValueError(f"payload {ordinal} element attributes drifted")
    if root.tag != "entryFree" or len(root) != 1 or root[0].tag != "def":
        raise ValueError(f"payload {ordinal} root structure drifted")
    return root


def _decode(idx: bytes, dat: bytes, zdx: bytes, zdt: bytes) -> dict[str, object]:
    if not idx or len(idx) % 8:
        raise ValueError("dict.idx is truncated or misaligned")
    if not zdx or len(zdx) % 8:
        raise ValueError("dict.zdx is truncated or misaligned")

    blocks: list[dict[str, object]] = []
    physical_payloads: dict[tuple[int, int], tuple[int, bytes, bytes]] = {}
    zdt_cursor = 0
    for block_number, position in enumerate(range(0, len(zdx), 8)):
        offset, compressed_size = struct.unpack_from("<II", zdx, position)
        if (
            offset != zdt_cursor
            or compressed_size == 0
            or offset + compressed_size + 2 > len(zdt)
        ):
            raise ValueError(f"dict.zdx block {block_number} offset or size mismatch")
        compressed = zdt[offset : offset + compressed_size]
        if zdt[offset + compressed_size : offset + compressed_size + 2] != b"\r\n":
            raise ValueError(f"dict.zdt block {block_number} separator mismatch")
        inflater = zlib.decompressobj()
        try:
            plain = inflater.decompress(compressed) + inflater.flush()
        except zlib.error as exc:
            raise ValueError(
                f"dict.zdt block {block_number} decompression failed"
            ) from exc
        # SWORD's indexed block allocation includes an exact zero-filled
        # allocation tail after the complete zlib stream. Keep both carriers.
        padding = inflater.unused_data
        stream_bytes = len(compressed) - len(padding)
        if (
            not inflater.eof
            or inflater.unconsumed_tail
            or len(padding) != 1_024
            or any(padding)
        ):
            raise ValueError(
                f"dict.zdt block {block_number} compressed stream is incomplete"
            )
        if len(plain) < 12:
            raise ValueError(f"block {block_number} is truncated")
        entry_count = struct.unpack_from("<I", plain, 0)[0]
        data_start = 4 + entry_count * 8
        if entry_count == 0 or data_start > len(plain):
            raise ValueError(f"block {block_number} descriptor table is invalid")
        payload_cursor = data_start
        for entry_number in range(entry_count):
            payload_offset, payload_size = struct.unpack_from(
                "<II", plain, 4 + entry_number * 8
            )
            if (
                payload_offset != payload_cursor
                or payload_size == 0
                or payload_offset + payload_size > len(plain)
            ):
                raise ValueError(
                    f"block {block_number} entry {entry_number} descriptor mismatch"
                )
            payload = plain[payload_offset : payload_offset + payload_size]
            payload_body = _split_payload(payload, len(physical_payloads) + 1)
            _source_fragment(payload_body, len(physical_payloads) + 1)
            physical_payloads[(block_number, entry_number)] = (
                payload_offset,
                payload,
                payload_body,
            )
            payload_cursor += payload_size
        if payload_cursor != len(plain):
            raise ValueError(f"block {block_number} has unaccounted bytes")
        blocks.append(
            {
                "block": block_number,
                "zdx_record_offset": position,
                "zdx_record_bytes": 8,
                "zdx_record_sha256": _sha(zdx[position : position + 8]),
                "zdt_offset": offset,
                "compressed_bytes": compressed_size,
                "compressed_sha256": _sha(compressed),
                "zlib_stream_bytes": stream_bytes,
                "zlib_stream_sha256": _sha(compressed[:stream_bytes]),
                "allocation_padding_bytes": len(padding),
                "allocation_padding_sha256": _sha(padding),
                "zdt_separator_offset": offset + compressed_size,
                "zdt_separator_bytes": 2,
                "zdt_separator_sha256": _sha(b"\r\n"),
                "uncompressed_bytes": len(plain),
                "uncompressed_sha256": _sha(plain),
                "entry_count": entry_count,
                "count_field_bytes": 4,
                "count_field_sha256": _sha(plain[:4]),
                "descriptor_table_bytes": entry_count * 8,
                "descriptor_table_sha256": _sha(plain[4:data_start]),
                "payload_bytes": len(plain) - data_start,
            }
        )
        zdt_cursor = offset + compressed_size + 2
    if zdt_cursor != len(zdt):
        raise ValueError("dict.zdt has trailing or unindexed bytes")

    records: list[dict[str, object]] = []
    seen_pointers: set[tuple[int, int]] = set()
    dat_spans: list[tuple[int, int]] = []
    for ordinal, position in enumerate(range(0, len(idx), 8), 1):
        offset, record_size = struct.unpack_from("<II", idx, position)
        if record_size < 11 or offset + record_size + 2 > len(dat):
            raise ValueError(f"dict.idx record {ordinal} offset or size mismatch")
        raw_record = dat[offset : offset + record_size]
        if dat[offset + record_size : offset + record_size + 2] != b"\r\n":
            raise ValueError(f"dict.dat record {ordinal} separator mismatch")
        if raw_record.count(b"\r\n") != 1:
            raise ValueError(f"dict.dat record {ordinal} key delimiter mismatch")
        key_bytes, pointer_bytes = raw_record.split(b"\r\n", 1)
        if not key_bytes or len(pointer_bytes) != 8:
            raise ValueError(f"dict.dat record {ordinal} shape mismatch")
        try:
            key = key_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"dict.dat record {ordinal} key is not UTF-8") from exc
        block_number, entry_number = struct.unpack("<II", pointer_bytes)
        pointer = (block_number, entry_number)
        if pointer not in physical_payloads:
            raise ValueError(f"dict.dat record {ordinal} pointer is out of range")
        if pointer in seen_pointers:
            raise ValueError(f"dict.dat record {ordinal} duplicates a payload pointer")
        seen_pointers.add(pointer)
        payload_offset, payload, payload_body = physical_payloads[pointer]
        fragment = _source_fragment(payload_body, ordinal)
        idx_record = idx[position : position + 8]
        key_delimiter_offset = offset + len(key_bytes)
        pointer_offset = key_delimiter_offset + 2
        outer_separator_offset = offset + record_size
        records.append(
            {
                "ordinal": ordinal,
                "dict_idx_offset": position,
                "dict_idx_bytes": 8,
                "dict_idx_sha256": _sha(idx_record),
                "dictionary_key": key,
                "dictionary_key_bytes": len(key_bytes),
                "dictionary_key_sha256": _sha(key_bytes),
                "dict_dat_offset": offset,
                "dict_record_bytes": record_size,
                "key_pointer_delimiter_offset": key_delimiter_offset,
                "key_pointer_delimiter_bytes": 2,
                "key_pointer_delimiter_sha256": _sha(b"\r\n"),
                "pointer_offset": pointer_offset,
                "pointer_bytes": 8,
                "pointer_sha256": _sha(pointer_bytes),
                "outer_separator_offset": outer_separator_offset,
                "outer_separator_bytes": 2,
                "outer_separator_sha256": _sha(b"\r\n"),
                "block": block_number,
                "entry_in_block": entry_number,
                "payload_offset": payload_offset,
                "payload_bytes": len(payload),
                "payload_sha256": _sha(payload),
                "payload_body_bytes": len(payload_body),
                "payload_body_sha256": _sha(payload_body),
                "terminal_nul_bytes": 1,
                "terminal_nul_sha256": _sha(payload[-1:]),
                "terminal_nul_disposition": "required-binary-format-terminator",
                "payload_n": fragment.get("n"),
                "payload": payload_body,
            }
        )
        dat_spans.append((offset, record_size))
    physical_cursor = 0
    for offset, record_size in sorted(dat_spans):
        if offset != physical_cursor:
            raise ValueError("dict.dat physical record coverage has a gap or overlap")
        physical_cursor = offset + record_size + 2
    if physical_cursor != len(dat) or len(set(dat_spans)) != len(dat_spans):
        raise ValueError("dict.dat has trailing, duplicate, or unindexed record bytes")
    if seen_pointers != set(physical_payloads):
        raise ValueError(
            "dictionary index does not address every physical payload exactly once"
        )
    return {"blocks": blocks, "records": records}


def _verify_census(decoded: Mapping[str, object]) -> None:
    blocks = decoded["blocks"]
    records = decoded["records"]
    assert isinstance(blocks, list) and isinstance(records, list)
    keys = [record["dictionary_key"] for record in records]
    payload_hashes = [record["payload_sha256"] for record in records]
    pointers = [
        {
            "ordinal": record["ordinal"],
            "block": record["block"],
            "entry": record["entry_in_block"],
        }
        for record in records
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
    observed = {
        "dictionary_keys_sha256": _sha(_canonical(keys)),
        "payload_sha256s_sha256": _sha(_canonical(payload_hashes)),
        "index_pointer_sequence_sha256": _sha(_canonical(pointers)),
        "compressed_block_census_sha256": _sha(_canonical(block_digest_rows)),
    }
    if (
        len(records) != 5_322
        or len(blocks) != 178
        or len(set(keys)) != 5_320
        or len(set(payload_hashes)) != 5_322
        or sum(int(block["uncompressed_bytes"]) for block in blocks) != 4_615_804
        or sum(int(block["payload_bytes"]) for block in blocks) != 4_572_516
        or sum(int(block["zlib_stream_bytes"]) for block in blocks) != 1_242_378
        or sum(int(block["allocation_padding_bytes"]) for block in blocks)
        != 182_272
        or sum(int(record["payload_body_bytes"]) for record in records)
        != 4_567_194
        or sum(int(record["terminal_nul_bytes"]) for record in records) != 5_322
        or observed != _ORDERED_DIGESTS
    ):
        raise ValueError("Nave binary census or ordered digests drifted")


def _tei(records: list[dict[str, object]]) -> tuple[bytes, dict[str, int]]:
    root = etree.Element(f"{{{_NS}}}TEI", nsmap={None: _NS})
    root.set(_XML_ID, "naves-topical-bible-candidate")
    header = etree.SubElement(root, f"{{{_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_NS}}}title").text = "Nave's Topical Bible"
    publication = etree.SubElement(file_desc, f"{{{_NS}}}publicationStmt")
    etree.SubElement(
        publication, f"{{{_NS}}}p"
    ).text = "Nonaccepted candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{_NS}}}sourceDesc")
    etree.SubElement(
        source_desc, f"{{{_NS}}}p"
    ).text = "Retained CrossWire SWORD Nave module version 3.0; the exact transformation source is the manifest-bound four-member zLD set."
    text = etree.SubElement(root, f"{{{_NS}}}text")
    body = etree.SubElement(text, f"{{{_NS}}}body")
    markup: Counter[str] = Counter()
    for record in records:
        ordinal = int(record["ordinal"])
        fragment = _source_fragment(record["payload"], ordinal)
        for node in fragment.iter():
            original = node.tag
            node.tag = f"{{{_NS}}}{original}"
            if original == "ref" and "osisRef" in node.attrib:
                node.set("target", node.attrib.pop("osisRef"))
                node.set("type", "osisRef")
                markup["ref_osisRef"] += 1
            elif original == "ref":
                markup["ref_target"] += 1
            else:
                markup[original] += 1
        form = etree.Element(f"{{{_NS}}}form", type="dictionary-key")
        etree.SubElement(form, f"{{{_NS}}}orth").text = str(
            record["dictionary_key"]
        )
        fragment.insert(0, form)
        fragment.set(_XML_ID, f"naves-topical-bible-entry-{ordinal:05d}")
        body.append(fragment)
    observed = {name: markup[name] for name in _MARKUP_COUNTS}
    if observed != _MARKUP_COUNTS:
        raise ValueError("Nave source markup census drifted")
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    ), observed


def _unresolved() -> bytes:
    rows = [
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
    return b"".join(_canonical(row) for row in rows)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    if source_manifest.record.get(
        "producer_import_closure_sha256"
    ) != _closure(source_manifest.repository_root):
        raise ValueError("Nave producer import closure drifted")
    paths = _source_paths(source_manifest)
    contents = {name: path.read_bytes() for name, path in paths.items()}
    # Parse first so malformed/truncated same-scope test inputs fail at the binary seam.
    decoded = _decode(
        contents["dict-idx"],
        contents["dict-dat"],
        contents["dict-zdx"],
        contents["dict-zdt"],
    )
    _strict_conf(contents["nave-conf"])
    archive_extracted = {
        "modules/lexdict/zld/nave/dict.zdx": contents["dict-zdx"],
        "modules/lexdict/zld/nave/dict.zdt": contents["dict-zdt"],
        "modules/lexdict/zld/nave/dict.dat": contents["dict-dat"],
        "modules/lexdict/zld/nave/dict.idx": contents["dict-idx"],
        "mods.d/nave.conf": contents["nave-conf"],
    }
    archive_members = _archive_members(paths["nave-archive"], archive_extracted)
    _verify_scope(source_manifest)
    _verify_census(decoded)
    for authority_name, (_, size, digest, _) in zip(
        ("dict-zdt", "dict-zdx", "dict-dat", "dict-idx", "nave-conf"),
        _MEMBERS,
        strict=True,
    ):
        if (
            len(contents[authority_name]) != size
            or _sha(contents[authority_name]) != digest
        ):
            raise ValueError(f"{authority_name} exact source binding drifted")
    if (
        len(contents["nave-archive"]) != _ARCHIVE[1]
        or _sha(contents["nave-archive"]) != _ARCHIVE[2]
    ):
        raise ValueError("Nave.zip exact source binding drifted")

    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(), "profile"
    )
    policy = _strict_json(
        source_manifest.authority_path("validation-policy").read_bytes(), "policy"
    )
    if (
        profile.get("profile_id") != _PROFILE_ID
        or policy.get("policy_id") != _POLICY_ID
    ):
        raise ValueError("Nave profile or policy identity drifted")
    records = decoded["records"]
    blocks = decoded["blocks"]
    assert isinstance(records, list) and isinstance(blocks, list)
    tei, markup = _tei(records)
    crosswalk = []
    for record in records:
        fragment = _source_fragment(record["payload"], int(record["ordinal"]))
        crosswalk.append(
            {
                "ordinal": record["ordinal"],
                "dictionary_key": record["dictionary_key"],
                "dictionary_key_bytes": record["dictionary_key_bytes"],
                "dictionary_key_sha256": record["dictionary_key_sha256"],
                "dict_idx_offset": record["dict_idx_offset"],
                "dict_idx_bytes": record["dict_idx_bytes"],
                "dict_idx_sha256": record["dict_idx_sha256"],
                "dict_dat_offset": record["dict_dat_offset"],
                "dict_record_bytes": record["dict_record_bytes"],
                "key_pointer_delimiter_offset": record[
                    "key_pointer_delimiter_offset"
                ],
                "key_pointer_delimiter_bytes": 2,
                "key_pointer_delimiter_sha256": _CRLF_SHA256,
                "pointer_offset": record["pointer_offset"],
                "pointer_bytes": 8,
                "pointer_sha256": record["pointer_sha256"],
                "outer_separator_offset": record["outer_separator_offset"],
                "outer_separator_bytes": 2,
                "outer_separator_sha256": _CRLF_SHA256,
                "block": record["block"],
                "entry_in_block": record["entry_in_block"],
                "payload_offset": record["payload_offset"],
                "payload_bytes": record["payload_bytes"],
                "payload_sha256": record["payload_sha256"],
                "payload_body_bytes": record["payload_body_bytes"],
                "payload_body_sha256": record["payload_body_sha256"],
                "terminal_nul_bytes": 1,
                "terminal_nul_sha256": _NUL_SHA256,
                "terminal_nul_disposition": "required-binary-format-terminator",
                "payload_n": record["payload_n"],
                "osis_refs": len(fragment.xpath(".//ref[@osisRef]")),
                "cross_refs": len(fragment.xpath(".//ref[@target]")),
                "target": f"#naves-topical-bible-entry-{int(record['ordinal']):05d}",
                "dictionary_key_target": (
                    f"#naves-topical-bible-entry-{int(record['ordinal']):05d}"
                    "/form[@type='dictionary-key']/orth"
                ),
                "status": "represented-with-terminal-control-disposition",
            }
        )
    accountability = {
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
            for path, size, digest, role in _MEMBERS
        ],
        "archive": {
            "path": _ARCHIVE[0],
            "bytes": _ARCHIVE[1],
            "sha256": _ARCHIVE[2],
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
            **_ORDERED_DIGESTS,
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
    provenance = {
        "contract": "ocd-lib009-naves-topical-bible-candidate-provenance-v1",
        "ticket_id": "LIB-009",
        "work_id": _WORK_ID,
        "source_id": _SOURCE_ID,
        "transformation_source_set": _transformation_source_set(),
        "source_manifest_sha256": source_manifest.sha256,
        "producer_import_closure_sha256": _closure(
            source_manifest.repository_root
        ),
        "converter": {"id": CONVERTER_ID, "version": CONVERTER_VERSION},
        "profile_id": _PROFILE_ID,
        "policy_id": _POLICY_ID,
        "candidate_boundary": {
            "status": "nonaccepted",
            "publication": "not_ready",
            "canonical_writes": False,
        },
        "archive_disposition": "acquisition-container-not-second-witness",
        "supplied_conf_sha256_claim": "0a52fe9e016a8900434118be0cb021deed1dfb02b7d2b829bb0e094ff92049d",
        "observed_conf_sha256": _MEMBERS[4][2],
        "attribution": "Credit CrossWire as module distributor and CCEL as the module's stated TextSource; retain README.source.md.",
    }
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": _unresolved(),
        "README.source.md": source_manifest.authority_path(
            "source-attribution-readme"
        ).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
