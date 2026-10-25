"""Producer-independent oracle for the four LIB-014 IA candidates."""

from __future__ import annotations

import ast
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib014-puritan-ia-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}

SPECS = {
    "brooks-precious-remedies": (
        "brooks_precious_remedies.txt",
        360_630,
        "dd9e5a0bd0b875939b3dc2bd5f848b84988a99c53ce8451f3222c34c58547cdb",
        8_526,
        "Precious Remedies Against Satan's Devices",
        "Thomas Brooks",
        "https://archive.org/download/preciousremedies00broo/preciousremedies00broo_djvu.txt",
        "Retained title page states First American Edition, New Haven, Nathan Whiting, 1832.",
        "Retained title page states abridged by W. Smelle and edited by Staunton Stevens Burdott.",
        0,
    ),
    "burroughs-rare-jewel-contentment": (
        "burroughs_rare_jewel.txt",
        454_509,
        "fed949f533923e8d4291df1b7eb04644fbe59f743cb732e67dbc8768f26c59d6",
        8_212,
        "The Rare Jewel of Christian Contentment",
        "Jeremiah Burroughs",
        "https://archive.org/download/JerimiahBurroughsTheRareJewelOfChristianContentment/Jerimiah%20Burroughs%20The%20Rare%20Jewel%20of%20Christian%20Contentment_djvu.txt",
        "The retained text identifies the work and creator but does not establish a scan edition date.",
        "No contributor role is asserted as accepted metadata.",
        0,
    ),
    "gurnall-complete-armour": (
        "gurnall_complete_armour.txt",
        4_672_135,
        "aa145a5411d1f87b35cde03407e9c4db4cc0a003a550821c3a9c73d54be2c4fa",
        57_974,
        "The Christian in Complete Armour",
        "William Gurnall",
        "https://archive.org/download/christianincom00gurn/christianincom00gurn_djvu.txt",
        "Retained title page states London, Thomas Tegg, MDCCCXLV (1845).",
        "Retained title page states carefully revised and corrected by Rev. John Campbell, D.D.",
        0,
    ),
    "sibbes-bruised-reed": (
        "sibbes_bruised_reed.txt",
        251_397,
        "b98f1e3819cfa3ee8c5c9e34fe24d5c9b3960ff94b5e4539cb0f9c06221ab52e",
        7_171,
        "The Bruised Reed and Smoking Flax",
        "Richard Sibbes",
        "https://archive.org/download/bruisedreedands00sibbgoog/bruisedreedands00sibbgoog_djvu.txt",
        "Retained title page states Edinburgh, Maclaren & Macniven, 1878.",
        "Retained title page states an introductory essay by Alexander Beith, D.D.",
        48,
    ),
}

SOURCE_IDS = {
    "brooks-precious-remedies": "lib014-brooks-precious-remedies-retained",
    "burroughs-rare-jewel-contentment": "lib014-burroughs-rare-jewel-contentment-retained",
    "gurnall-complete-armour": "lib014-gurnall-complete-armour-retained",
    "sibbes-bruised-reed": "lib014-sibbes-bruised-reed-retained",
}

# Filled with immutable source-local authority digests after the packet files are complete.
LOCAL_AUTHORITY_SHA256: dict[str, dict[str, str]] = {
    "brooks-precious-remedies": {
        "source-readme": "8fb7689a9f002917ff0f26daf3f34a0d068d51a1773f23b4708e3cb86e5bedcd",
        "complete-source-feature-profile": "26686d38e1e3bf0d054f0cbcd894f12ccdf50d714615a643c5bdc7229d2f84d8",
        "independent-validation-policy": "b3aa2bc09f8aa8492beb5b600d42c312bc74d43c969e24154d7b114d9afa0f42",
        "source-accountability-schema": "64bcdebb89686bf29dbe0340a4106feada40a9953d9ebcd2e0bd8b35b9384bc6",
    },
    "burroughs-rare-jewel-contentment": {
        "source-readme": "718e65b471efd3353214c15bfc503810078380680b1669a009adf334ff95b83f",
        "complete-source-feature-profile": "06fb2f5962bc95bb4726d9bd69d4c6556b62110f91a07901fe739be1eab38cf1",
        "independent-validation-policy": "5c7fdbfd1df8ccc537daf87574d15ccc501fe249dcd1916ea928ff7684b67bda",
        "source-accountability-schema": "43c77090111a84f25ebc0ec132dfeac80e680367c5423961e004124699f3247b",
    },
    "gurnall-complete-armour": {
        "source-readme": "041d8ab9b0da3680eeabfada4ed4c7fc30b27945bc39af1988efb17f0555ab74",
        "complete-source-feature-profile": "f24161f402c3ad69abc92d8a47f272342cf20a3cf54114805d85bb748ca67d5f",
        "independent-validation-policy": "1118bfff271a26035981ed75cc2f4e4e87d4a5bc808650a2cad3068500cd3745",
        "source-accountability-schema": "7ccf6e487bac1159004e4a697b8ba9d89ea47a618a94ebc2a335f50431249a6b",
    },
    "sibbes-bruised-reed": {
        "source-readme": "88bd823a1237ce3f8069e8f755c288c0854d123e23816ecb190fcf962dc06a0c",
        "complete-source-feature-profile": "8907db5554c69ede41ec88e7f742a3469af79ea9f4d5ea890e8b8f61b9bcf3e9",
        "independent-validation-policy": "93ceef1c7091b4820bef40a97d69968924fafc2251a5ca7e53be58af5de1164f",
        "source-accountability-schema": "9a7871e5fa7e35a5d59fd6c49fb3e3a6a8548230b5aa42190e8904c879736889",
    },
}

SHARED_AUTHORITY_RECORDS: dict[str, dict[str, object]] = {
    "candidate-package-schema": {
        "name": "candidate-package-schema",
        "path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
        "role": "candidate-package-schema",
        "bytes": 2_173,
        "sha256": "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3",
    },
    "tei-p5-xsd": {
        "name": "tei-p5-xsd",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
        "role": "tei-validation-schema",
        "bytes": 1_108_622,
        "sha256": "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f",
    },
    "tei-p5-xsd-teix": {
        "name": "tei-p5-xsd-teix",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
        "role": "tei-validation-schema-dependency",
        "bytes": 2_202,
        "sha256": "51ab8c0071f2abc375090829acadf7cb57c707fe17a993cdb2213e84932a6fac",
    },
    "tei-p5-xsd-xml": {
        "name": "tei-p5-xsd-xml",
        "path": "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
        "role": "tei-validation-schema-dependency",
        "bytes": 2_359,
        "sha256": "4f3a8348802f3bc968cbdd2a9d54a38a0549e5e4e7bc8d4338404f85f89568ba",
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


_SHARED_CONTRACT_PATH = "ocd_kernel/reconstruction/contract.py"
_SHARED_CONTRACT_SHA256 = (
    "2caac35bbbfcff7036c343c0408bbb87e6a1dbdbce818001fb26a153202201af"
)
_DYNAMIC_IMPORT_CALLS = {
    "__import__",
    "eval",
    "exec",
    "import_module",
    "module_from_spec",
    "spec_from_file_location",
    "exec_module",
}


def _local_module(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path.resolve(strict=True)
    return None


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.resolve(strict=True).relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_names(root: Path, path: Path, node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    if node.level:
        package = _module_name(root, path).split(".")
        if path.name != "__init__.py":
            package.pop()
        if node.level > len(package):
            raise ValueError("LIB-014 oracle import closure escapes repository")
        base = ".".join(package[: len(package) - node.level + 1])
        if node.module:
            base = f"{base}.{node.module}" if base else node.module
    else:
        base = node.module or ""
    if not base:
        return ()
    return (base, *(f"{base}.{alias.name}" for alias in node.names))


def _closure(root: Path, route: Path) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [route.resolve(strict=True)]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "LIB-014 oracle import closure escapes repository"
            ) from exc
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name)
                and node.func.id in _DYNAMIC_IMPORT_CALLS
                or isinstance(node.func, ast.Attribute)
                and node.func.attr in _DYNAMIC_IMPORT_CALLS
            ):
                raise ValueError(
                    "LIB-014 oracle import closure contains dynamic execution"
                )
            for name in _import_names(root, path, node):
                dependency = _local_module(root, name)
                if dependency is not None and dependency not in seen:
                    pending.append(dependency)
                parts = name.split(".")
                for index in range(1, len(parts)):
                    package = _local_module(root, ".".join(parts[:index]))
                    if package is not None and package not in seen:
                        pending.append(package)
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix())
    )


def _closure_digest(root: Path, route: Path) -> str:
    return _sha(_canonical(_closure(root, route)))


def _verify_contract_binding(closure: tuple[dict[str, str], ...]) -> None:
    matches = [item for item in closure if item["path"] == _SHARED_CONTRACT_PATH]
    if len(matches) != 1:
        raise ValueError("LIB-014 oracle import closure omitted shared contract")
    if matches[0]["sha256"] != _SHARED_CONTRACT_SHA256:
        raise ValueError("LIB-014 oracle shared contract closure drifted")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority(source_manifest: object, name: str) -> tuple[Mapping[str, object], Path]:
    authorities = getattr(source_manifest, "record")["authorities"]
    matches = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"authority inventory mismatch for {name}")
    return matches[0], getattr(source_manifest, "authority_path")(name)


def _category(wrapper_end: int, line_number: int) -> str:
    return (
        "digitization-wrapper"
        if wrapper_end and line_number <= wrapper_end
        else "retained-ocr-line"
    )


def _source(source_manifest: object) -> tuple[str, bytes, tuple[bytes, ...]]:
    work_id = str(getattr(source_manifest, "record")["work_id"])
    if work_id not in SPECS:
        raise ValueError("source manifest work is outside LIB-014")
    if (
        set(SOURCE_IDS) != set(SPECS)
        or getattr(source_manifest, "record").get("source_id") != SOURCE_IDS[work_id]
    ):
        raise ValueError("source manifest source_id drift")
    filename, byte_count, digest, line_count, *_ = SPECS[work_id]
    source_record, source_path = _authority(source_manifest, "retained-source")
    expected_path = f"raw/ia/{filename}"
    if dict(source_record) != {
        "name": "retained-source",
        "path": expected_path,
        "role": "primary-source",
        "bytes": byte_count,
        "sha256": digest,
    }:
        raise ValueError("retained-source authority record drift")
    content = source_path.read_bytes()
    content.decode("utf-8", errors="strict")
    records = tuple(content.splitlines(keepends=True))
    if (
        len(content),
        _sha(content),
        len(records),
        content.count(b"\n"),
        content.count(b"\r"),
        content.endswith(b"\n"),
    ) != (byte_count, digest, line_count, line_count, 0, True):
        raise ValueError("retained source bytes or LF framing drift")
    return work_id, content, records


def _verify_local_authorities(source_manifest: object, work_id: str) -> None:
    expected = LOCAL_AUTHORITY_SHA256[work_id]
    required = {
        "source-readme",
        "complete-source-feature-profile",
        "independent-validation-policy",
        "source-accountability-schema",
    }
    if set(expected) != required:
        raise ValueError("oracle local authority closure is incomplete")
    source_dir = f"sources/{work_id}"
    paths = {
        "source-readme": f"{source_dir}/LIB-014.README.source.md",
        "complete-source-feature-profile": f"{source_dir}/LIB-014.source-profile.json",
        "independent-validation-policy": f"{source_dir}/LIB-014.validation-policy.json",
        "source-accountability-schema": f"{source_dir}/LIB-014.source-accountability.schema.json",
    }
    roles = {
        "source-readme": "source-attribution-readme",
        "complete-source-feature-profile": "complete-source-feature-profile",
        "independent-validation-policy": "independent-validation-policy",
        "source-accountability-schema": "source-accountability-schema",
    }
    for name in sorted(required):
        record, path = _authority(source_manifest, name)
        content = path.read_bytes()
        if (
            dict(record)
            != {
                "name": name,
                "path": paths[name],
                "role": roles[name],
                "bytes": len(content),
                "sha256": expected[name],
            }
            or _sha(content) != expected[name]
        ):
            raise ValueError(f"{name} exact authority binding drift")
    for name, expected_record in SHARED_AUTHORITY_RECORDS.items():
        record, path = _authority(source_manifest, name)
        content = path.read_bytes()
        if (
            dict(record) != expected_record
            or len(content) != expected_record["bytes"]
            or _sha(content) != expected_record["sha256"]
        ):
            raise ValueError(f"{name} exact authority binding drift")
    authority_names = {
        str(item["name"]) for item in getattr(source_manifest, "record")["authorities"]
    }
    expected_names = required | {"retained-source"} | set(SHARED_AUTHORITY_RECORDS)
    if authority_names != expected_names:
        raise ValueError("source manifest authority inventory drift")


def _verify_closures(
    source_manifest: object,
    converter: Mapping[str, object],
    validator: Mapping[str, object],
) -> tuple[str, str]:
    root = getattr(source_manifest, "repository_root")
    producer_path = root / str(converter.get("implementation_path"))
    producer_records = _closure(root, producer_path)
    _verify_contract_binding(producer_records)
    producer_digest = _sha(_canonical(producer_records))
    if producer_digest != getattr(source_manifest, "record").get(
        "producer_import_closure_sha256"
    ):
        raise ValueError("LIB-014 producer import closure drifted")

    oracle_path = root / str(validator.get("implementation_path"))
    oracle_records = _closure(root, oracle_path)
    _verify_contract_binding(oracle_records)
    oracle_digest = _sha(_canonical(oracle_records))
    if oracle_digest != validator.get("import_closure_sha256"):
        raise ValueError("LIB-014 oracle import closure drifted")
    return producer_digest, oracle_digest


def _crosswalk(work_id: str, records: tuple[bytes, ...]) -> list[dict[str, object]]:
    wrapper_end = SPECS[work_id][-1]
    result: list[dict[str, object]] = []
    offset = 0
    for number, record in enumerate(records, 1):
        end = offset + len(record)
        text = record[:-1].decode("utf-8", errors="strict")
        line_id = f"{work_id}-line-{number:05d}"
        result.append(
            {
                "id": line_id,
                "line": number,
                "byte_start": offset,
                "byte_end": end,
                "record_sha256": _sha(record),
                "text_sha256": _sha(text.encode("utf-8")),
                "category": _category(wrapper_end, number),
                "disposition": "represented",
                "target": f"#{line_id}",
            }
        )
        offset = end
    return result


@lru_cache(maxsize=4)
def _compiled_schema(path: Path) -> etree.XMLSchema:
    # All three XSD hashes are checked before every oracle validation.
    return etree.XMLSchema(etree.parse(str(path)))


def _validate_tei(
    source_manifest: object, candidate: object, work_id: str, records: tuple[bytes, ...]
) -> None:
    (
        _,
        byte_count,
        digest,
        line_count,
        title,
        creator,
        source_url,
        edition,
        contributor,
        wrapper_end,
    ) = SPECS[work_id]
    content = getattr(candidate, "member_bytes")("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(content, parser)
    xsd_path = _authority(source_manifest, "tei-p5-xsd")[1]
    _compiled_schema(xsd_path).assertValid(etree.ElementTree(root))
    if root.tag != f"{{{TEI_NS}}}TEI" or root.attrib != {
        f"{{{XML_NS}}}id": f"{work_id}-candidate"
    }:
        raise ValueError("TEI root metadata drift")
    exact_text = {
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title": f"{title}: faithful retained-source candidate",
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author": creator,
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:resp": "Exact physical-line transcription",
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name": "Open Christian Data",
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:title": title,
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:author": creator,
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='edition-evidence']": edition,
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='contributor-evidence']": contributor,
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='URI']": source_url,
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='SHA-256']": digest,
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:extent": f"{byte_count} bytes; {line_count} UTF-8 LF physical lines",
    }
    for xpath, expected in exact_text.items():
        nodes = root.xpath(xpath, namespaces=NS)
        if len(nodes) != 1 or nodes[0].text != expected:
            raise ValueError(f"TEI header drift at {xpath}")
    division = root.xpath("./tei:text/tei:body/tei:div", namespaces=NS)
    if len(division) != 1 or division[0].attrib != {
        f"{{{XML_NS}}}id": f"{work_id}-retained-lines",
        "type": "treatise",
        "subtype": "ia-ocr-source-transcription",
    }:
        raise ValueError("TEI work scope drift")
    nodes = division[0].xpath("./tei:ab", namespaces=NS)
    if len(nodes) != line_count:
        raise ValueError("TEI line omission, duplication, or invention")
    reconstructed: list[bytes] = []
    for number, (node, record) in enumerate(zip(nodes, records, strict=True), 1):
        text = record[:-1].decode("utf-8", errors="strict")
        expected_attrs = {
            f"{{{XML_NS}}}id": f"{work_id}-line-{number:05d}",
            "n": str(number),
            "ana": f"#source-line #{_category(wrapper_end, number)}",
        }
        if (
            node.tag != f"{{{TEI_NS}}}ab"
            or node.attrib != expected_attrs
            or len(node)
            or node.tail is not None
            or (node.text or "") != text
        ):
            raise ValueError(
                f"TEI order, text, or source classification drift at line {number}"
            )
        reconstructed.append(text.encode("utf-8") + b"\n")
    if (
        b"".join(reconstructed)
        != _authority(source_manifest, "retained-source")[1].read_bytes()
    ):
        raise ValueError("TEI does not losslessly reconstruct retained bytes")


def _validate_members(
    source_manifest: object, candidate: object, work_id: str, records: tuple[bytes, ...]
) -> None:
    (
        filename,
        byte_count,
        digest,
        line_count,
        title,
        creator,
        source_url,
        edition,
        contributor,
        _,
    ) = SPECS[work_id]
    package = _strict_json(
        getattr(candidate, "member_bytes")("manifest.json"), "candidate manifest"
    )
    Draft202012Validator(
        _strict_json(
            _authority(source_manifest, "candidate-package-schema")[1].read_bytes(),
            "candidate package schema",
        )
    ).validate(package)
    record = getattr(source_manifest, "record")
    expected_manifest = {
        "path": getattr(source_manifest, "path")
        .relative_to(getattr(source_manifest, "repository_root"))
        .as_posix(),
        "sha256": getattr(source_manifest, "sha256"),
    }
    if (
        package.get("status") != "nonaccepted"
        or package.get("source_id") != SOURCE_IDS[work_id]
        or package.get("source_manifest") != expected_manifest
        or package.get("converter") != dict(record["converter"])
        or package.get("package_schema") != dict(record["package_schema"])
    ):
        raise ValueError("candidate manifest binding drift")
    crosswalk = _crosswalk(work_id, records)
    expected_accountability = {
        "contract": "ocd-lib014-source-accountability-v1",
        "work_id": work_id,
        "source_sha256": digest,
        "source_bytes": byte_count,
        "physical_lines": line_count,
        "represented_lines": line_count,
        "omitted_lines": 0,
        "duplicated_lines": 0,
        "member_census": [
            {
                "path": f"raw/ia/{filename}",
                "bytes": byte_count,
                "sha256": digest,
                "included": True,
                "reason": "The frozen LIB-014 source map assigns this sole exact retained direct-file member to this work.",
            }
        ],
        "excluded_members": [],
        "crosswalk_sha256": _sha(_canonical(crosswalk)),
        "crosswalk": crosswalk,
    }
    accountability = _strict_json(
        getattr(candidate, "member_bytes")("source-accountability.json"),
        "accountability",
    )
    Draft202012Validator(
        _strict_json(
            _authority(source_manifest, "source-accountability-schema")[1].read_bytes(),
            "accountability schema",
        )
    ).validate(accountability)
    if accountability != expected_accountability:
        raise ValueError("source accountability drift")
    profile = _strict_json(
        _authority(source_manifest, "complete-source-feature-profile")[1].read_bytes(),
        "source profile",
    )
    expected_provenance = {
        "contract": "ocd-lib014-provenance-v1",
        "work_id": work_id,
        "title": title,
        "creator": creator,
        "source_format": "Internet Archive retained UTF-8 OCR/plain-text export with LF framing",
        "source_url": source_url,
        "source_sha256": digest,
        "edition_evidence": edition,
        "contributor_evidence": contributor,
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "technical_validation_is_human_acceptance": False,
        "rights": profile["rights"],
    }
    if (
        _strict_json(
            getattr(candidate, "member_bytes")("provenance.json"), "provenance"
        )
        != expected_provenance
    ):
        raise ValueError("candidate provenance drift")
    unresolved = [
        _strict_json(line + b"\n", "unresolved record")
        for line in getattr(candidate, "member_bytes")("unresolved.jsonl").splitlines()
    ]
    expected_unresolved = [
        {
            "id": f"{work_id}-identity-edition",
            "kind": "identity-edition-witness",
            "status": "human-review-required",
            "scope": "whole retained witness and title-page assertions",
            "detail": "Title, creator, contributor roles, edition identity, and witness fitness remain unaccepted.",
        },
        {
            "id": f"{work_id}-ocr",
            "kind": "ocr-substantive-reading-editorial",
            "status": "human-review-required",
            "scope": f"all {line_count} retained physical lines",
            "detail": "OCR artifacts, replacement characters, marginalia, lineation, and substantive readings are preserved without silent correction.",
        },
        {
            "id": f"{work_id}-rights",
            "kind": "rights-attribution",
            "status": "human-review-required",
            "scope": "retained scan/export, jurisdiction, reuse terms, and attribution",
            "detail": profile["rights_unresolved_detail"],
        },
        {
            "id": f"{work_id}-acceptance",
            "kind": "acceptance-publication",
            "status": "human-review-required",
            "scope": "whole candidate",
            "detail": "Technical validation is not human acceptance or publication authorization.",
        },
    ]
    if unresolved != expected_unresolved:
        raise ValueError("unresolved human boundary drift")
    if (
        getattr(candidate, "member_bytes")("README.source.md")
        != _authority(source_manifest, "source-readme")[1].read_bytes()
    ):
        raise ValueError("candidate README attribution drift")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    getattr(source_manifest, "verify")()
    getattr(candidate, "verify_integrity")()
    record = getattr(source_manifest, "record")
    converter = record.get("converter")
    validator = record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("LIB-014 converter or validator binding is invalid")
    _, oracle_closure = _verify_closures(source_manifest, converter, validator)
    work_id, content, records = _source(source_manifest)
    _verify_local_authorities(source_manifest, work_id)
    _validate_tei(source_manifest, candidate, work_id, records)
    _validate_members(source_manifest, candidate, work_id, records)
    implementation_sha256 = _sha(Path(__file__).read_bytes())
    if validator.get("implementation_sha256") != implementation_sha256:
        raise ValueError("oracle implementation authority drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha256,
        "import_closure_sha256": oracle_closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": getattr(source_manifest, "sha256"),
        "candidate_sha256": getattr(candidate, "sha256"),
        "profile_sha256": _authority(
            source_manifest, "complete-source-feature-profile"
        )[0]["sha256"],
        "package_schema_sha256": _authority(
            source_manifest, "candidate-package-schema"
        )[0]["sha256"],
        "source_sha256": _sha(content),
        "xsd_sha256": _authority(source_manifest, "tei-p5-xsd")[0]["sha256"],
        "policy_sha256": _authority(source_manifest, "independent-validation-policy")[
            0
        ]["sha256"],
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
