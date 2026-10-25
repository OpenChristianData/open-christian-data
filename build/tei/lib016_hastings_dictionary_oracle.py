"""Producer-independent LIB-016 Hastings faithful-TEI validator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree


ORACLE_ID = "ocd-lib016-hastings-independent-oracle"
ORACLE_VERSION = "1"
AGGREGATE_SHA256 = "1cd0f245927973e5f84db7bad42c71aa1dfb259e5aad026a40dd5f0d6238f7a7"
AGGREGATE_BYTES = 44_374_718
MEMBER_SET_SHA256 = "997d3b2ee21ce47e747811c826e05456964cac318f4846bc346b3b790d6e57c8"
WORK_ID = "hastings-dictionary-of-the-bible"
WORK_CONFIG_PATH = "sources/reference/hastings-dictionary-of-the-bible/config.json"
CATALOG_SOURCE_PATH = "reference/hastings-dictionary-of-the-bible.json"
CANONICAL_TEI_SHA256 = (
    "5e053e358eac3a61831d9b0fc6a3b834214b0451be11583e9ec08de826013db0"
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
MEMBERS = (
    (
        "b24749163_0005_djvu.txt",
        11_778_287,
        "b99bc2dc36d90eb7c1bd8ae3f4d630230013e57b6fa4c910b2e12fc3fd8c4b08",
        217_888,
        0,
        4_057_175,
    ),
    (
        "DictionaryOfTheBibleV1_djvu.txt",
        7_786_046,
        "7a7bf16bf9a32891e62ab6dce4948ba9cee16bdfa4633fa7111a6e24b0ec8403",
        166_219,
        4_896_652,
        0,
    ),
    (
        "DictionaryOfTheBibleV2_djvu.txt",
        7_917_100,
        "0a814cb444e7c03c1f9818a3847aab2f62fd4fd8a753cff500709f400599740e",
        166_344,
        4_985_366,
        0,
    ),
    (
        "DictionaryOfTheBibleV3_djvu.txt",
        7_718_997,
        "1269c783b46a54143722e27d41b8b23d8b6221e93cb8f6c78f3e0aa364b5711f",
        162_721,
        4_885_733,
        0,
    ),
    (
        "DictionaryOfTheBibleV4_djvu.txt",
        9_174_288,
        "958a011508170ddfc59f110e3087f2fd5bee9dda25c2216974778a974202997a",
        189_821,
        5_801_976,
        0,
    ),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
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
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _latin_count(text: str) -> int:
    return sum(("A" <= char <= "Z") or ("a" <= char <= "z") for char in text)


def _authority(source_manifest: object, name: str) -> tuple[Mapping[str, object], Path]:
    authorities = getattr(source_manifest, "record").get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("name") == name:
            return authority, getattr(source_manifest, "authority_path")(name)
    raise ValueError(f"missing authority: {name}")


def _source_truth(
    source_manifest: object,
) -> tuple[tuple[bytes, ...], list[dict[str, object]]]:
    contents: list[bytes] = []
    records: list[dict[str, object]] = []
    aggregate = hashlib.sha256()
    offset = 0
    for order, (
        name,
        expected_bytes,
        expected_sha,
        expected_lines,
        expected_latin,
        expected_greek,
    ) in enumerate(MEMBERS, start=1):
        authority, path = _authority(source_manifest, f"retained-member-{order:02d}")
        if authority.get("filename") != name or authority.get("order") != order:
            raise ValueError("source member scope or order drift")
        content = path.read_bytes()
        text = content.decode("utf-8", errors="strict")
        if (
            len(content) != expected_bytes
            or _sha(content) != expected_sha
            or content.count(b"\n") != expected_lines
            or not content.endswith(b"\n")
            or b"\r" in content
            or _latin_count(text) != expected_latin
        ):
            raise ValueError(f"retained source identity drift: {name}")
        end = offset + len(content)
        records.append(
            {
                "name": name,
                "order": order,
                "byte_start": offset,
                "byte_end": end,
                "bytes": len(content),
                "sha256": expected_sha,
                "physical_lines": expected_lines,
                "terminal_lf": True,
                "latin_letters": expected_latin,
                "greek_classified_characters": expected_greek,
                "represented_bytes": len(content),
                "represented_lines": expected_lines,
                "status": "represented",
                "target": f"#lib016-member-{order:02d}-text",
            }
        )
        aggregate.update(content)
        offset = end
        contents.append(content)
    if offset != AGGREGATE_BYTES or aggregate.hexdigest() != AGGREGATE_SHA256:
        raise ValueError("independent aggregate order, separator, or identity drift")
    return tuple(contents), records


def _verify_authorities(source_manifest: object) -> None:
    record = getattr(source_manifest, "record")
    if set(record) != {
        "contract",
        "source_id",
        "catalog_claim_lineage",
        "authorities",
        "converter",
        "validator",
        "package_schema",
        "lineage",
    }:
        raise ValueError("source manifest top-level fields drifted")
    if (
        record.get("contract") != "ocd-source-manifest-v1"
        or record.get("source_id") != WORK_ID
    ):
        raise ValueError("source manifest identity drift")
    authorities = record.get("authorities")
    if not isinstance(authorities, tuple) or len(authorities) != 14:
        raise ValueError("source manifest authority inventory drift")
    expected_names = tuple(
        [f"retained-member-{number:02d}" for number in range(1, 6)]
        + [
            "work-identity-config",
            "source-readme",
            "reconstruction-profile",
            "source-accountability-schema",
            "validation-policy",
            "tei-p5-xsd",
            "tei-p5-xsd-teix",
            "tei-p5-xsd-xml",
            "candidate-package-schema",
        ]
    )
    names = tuple(item.get("name") for item in authorities if isinstance(item, Mapping))
    if names != expected_names:
        raise ValueError("source manifest authority order or scope drift")
    for order, expected in enumerate(MEMBERS, start=1):
        name, size, digest, lines, _, _ = expected
        item = authorities[order - 1]
        if not isinstance(item, Mapping) or dict(item) != {
            "name": f"retained-member-{order:02d}",
            "path": f"raw/ia/hastings-dictionary/{name}",
            "durable_path": f"D:/Library/Open Christian Data/raw/ia/hastings-dictionary/{name}",
            "filename": name,
            "role": "primary-source",
            "order": order,
            "bytes": size,
            "sha256": digest,
            "physical_lines": lines,
        }:
            raise ValueError(f"retained member authority record drift: {name}")
    expected_local = {
        "work-identity-config": (
            WORK_CONFIG_PATH,
            "work-identity-config",
            1905,
            "72fa2720f5ab5599ad446aed096d3b5118b42d5a1beb45e92a4b7fdd85fd61d0",
        ),
        "source-readme": (
            "sources/hastings-dictionary-of-the-bible/LIB-016/README.source.md",
            "local-source-readme",
            1414,
            "ed022b160f930c5c5e1a9071f54d3592c2e07226faa9f6523884e2ebb26a793b",
        ),
        "reconstruction-profile": (
            "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.reconstruction-profile.json",
            "complete-source-feature-profile",
            1421,
            "7944df495284171c244560859cb40d2c111a428eee72b414bd13798b90a2564b",
        ),
        "source-accountability-schema": (
            "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.source-accountability.schema.json",
            "complete-source-accountability-schema",
            1930,
            "0f1f404cceb5cc2c380d116f2e38f4f6995bcd85dfbd34ad7440129d319e20f9",
        ),
        "validation-policy": (
            "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.validation-policy.json",
            "independent-validation-policy",
            1144,
            "34b820f3adb59cbfae3ef503351be3211421253218eeeedfef4d19998aad30c8",
        ),
        "tei-p5-xsd": (
            "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
            "tei-validation-schema",
            1108622,
            "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f",
        ),
        "tei-p5-xsd-teix": (
            "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
            "tei-validation-schema-dependency",
            2202,
            "51ab8c0071f2abc375090829acadf7cb57c707fe17a993cdb2213e84932a6fac",
        ),
        "tei-p5-xsd-xml": (
            "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
            "tei-validation-schema-dependency",
            2359,
            "4f3a8348802f3bc968cbdd2a9d54a38a0549e5e4e7bc8d4338404f85f89568ba",
        ),
        "candidate-package-schema": (
            "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
            "candidate-package-schema",
            2173,
            "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3",
        ),
    }
    for item in authorities[5:]:
        assert isinstance(item, Mapping)
        path, role, size, digest = expected_local[str(item["name"])]
        if dict(item) != {
            "name": item["name"],
            "path": path,
            "role": role,
            "bytes": size,
            "sha256": digest,
        }:
            raise ValueError(f"authority record drift: {item['name']}")
        content = getattr(source_manifest, "authority_path")(item["name"]).read_bytes()
        if len(content) != size or _sha(content) != digest:
            raise ValueError(f"authority bytes drift: {item['name']}")
    config = _strict_json(
        getattr(source_manifest, "authority_path")("work-identity-config").read_bytes(),
        "work identity config",
    )
    if {config.get("dictionary_id"), config.get("resource_id")} != {WORK_ID}:
        raise ValueError("work identity config semantics drift")
    expected_catalog_claim_lineage = {
        "contract": "ocd-catalog-claim-lineage-v1",
        "work_id": WORK_ID,
        "retained_source_sha256": MEMBER_SET_SHA256,
        "claim_count": 1,
        "claims": (
            {
                "source_path": CATALOG_SOURCE_PATH,
                "legacy_source_sha256": AGGREGATE_SHA256,
            },
        ),
    }
    catalog_claim_lineage = record.get("catalog_claim_lineage")
    if (
        not isinstance(catalog_claim_lineage, Mapping)
        or dict(catalog_claim_lineage) != expected_catalog_claim_lineage
    ):
        raise ValueError("catalog claim lineage drift")
    converter = record.get("converter")
    validator = record.get("validator")
    package_schema = record.get("package_schema")
    if (
        not isinstance(converter, Mapping)
        or converter.get("id") != "ocd-lib016-hastings-dictionary-lossless-ocr-to-tei"
        or converter.get("version") != "1"
        or converter.get("callable") != "_convert"
        or converter.get("implementation_path")
        != "build/tei/lib016_hastings_dictionary_reconstruction.py"
    ):
        raise ValueError("converter binding drift")
    if (
        not isinstance(validator, Mapping)
        or validator.get("id") != ORACLE_ID
        or validator.get("version") != ORACLE_VERSION
        or validator.get("callable") != "_oracle"
        or validator.get("implementation_path")
        != "build/tei/lib016_hastings_dictionary_oracle.py"
    ):
        raise ValueError("validator binding drift")
    if not isinstance(package_schema, Mapping) or dict(package_schema) != {
        "path": expected_local["candidate-package-schema"][0],
        "sha256": expected_local["candidate-package-schema"][3],
    }:
        raise ValueError("package schema binding drift")
    expected_lineage = {
        "initial_sealed_hashes": {
            "build/tei/lib016_hastings_dictionary_oracle.py": "73bd5e9fb3bcacc85a6d132c187cd537f85c4cc032b32c747863afe3225feefb",
            "build/tei/lib016_hastings_dictionary_reconstruction.py": "7d919f56f3819c5a8bdf4f484d8296ae484f13cb9a90b76ccc5a8e4e2c4a3d55",
            "sources/hastings-dictionary-of-the-bible/LIB-016/README.source.md": "ed022b160f930c5c5e1a9071f54d3592c2e07226faa9f6523884e2ebb26a793b",
            "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.reconstruction-profile.json": "7944df495284171c244560859cb40d2c111a428eee72b414bd13798b90a2564b",
            "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.source-accountability.schema.json": "0f1f404cceb5cc2c380d116f2e38f4f6995bcd85dfbd34ad7440129d319e20f9",
            "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.source-manifest.json": "74b9a36d1bc4d61a8e40a815caf5b438bd309e3870ea19d461782f19dea805b5",
            "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.validation-policy.json": "34b820f3adb59cbfae3ef503351be3211421253218eeeedfef4d19998aad30c8",
            "tests/test_lib016_hastings_dictionary_reconstruction_contract.py": "6c2ea17c81e4071829464bad98bcd6afaae95d4d3063f02b583b1c17b1706fc9",
        },
        "schema_rebase": {
            "from": {
                "bytes": 2244,
                "sha256": "eab839cd9f2cbce22fb86f5e8928488b8c91a41f5f83820bb9430dc81fa5c421",
            },
            "to": {
                "bytes": 2173,
                "sha256": "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3",
            },
        },
    }
    if (
        not isinstance(record.get("lineage"), Mapping)
        or dict(record["lineage"]) != expected_lineage
    ):
        raise ValueError("source manifest lineage drift")


def _validate_tei(
    source_manifest: object, candidate: object, contents: tuple[bytes, ...]
) -> None:
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_blank_text=False, huge_tree=True
    )
    content = getattr(candidate, "member_bytes")("content.tei.xml")
    if _sha(content) != CANONICAL_TEI_SHA256:
        raise ValueError("TEI canonical bytes drifted")
    root = etree.fromstring(content, parser)
    _, xsd_path = _authority(source_manifest, "tei-p5-xsd")
    etree.XMLSchema(etree.parse(str(xsd_path))).assertValid(etree.ElementTree(root))
    if (
        root.get("{http://www.w3.org/XML/1998/namespace}id")
        != "lib016-hastings-dictionary-candidate"
    ):
        raise ValueError("TEI root identity drift")
    expected_text = {
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title": "Dictionary of the Bible: faithful retained-OCR transcription candidate",
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:editor": "James Hastings",
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:resp": "Exact five-member retained-OCR transcription",
        "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name": "Open Christian Data",
        "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher": "Open Christian Data",
        "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p": "Nonaccepted candidate; publication is not authorized; human textual, edition, identity, and rights review is required.",
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:title": "Dictionary of the Bible",
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:editor": "James Hastings",
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:edition": "Volumes I-IV: Scribner/T. & T. Clark 1911 reprint; Extra Volume: 1909",
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno": AGGREGATE_SHA256,
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:extent": "44374718 bytes; five UTF-8 DjVuTXT OCR members concatenated in lexicographic filename order without separators",
        "./tei:teiHeader/tei:encodingDesc/tei:projectDesc/tei:p[1]": "Every member and every literal LF-delimited source line is represented once, verbatim, and in frozen aggregate order.",
        "./tei:teiHeader/tei:encodingDesc/tei:projectDesc/tei:p[2]": "No article segmentation, OCR correction, Unicode normalization, or inferred separator is applied.",
        "./tei:teiHeader/tei:revisionDesc/tei:change": "Deterministic nonaccepted candidate generated from the exact retained cohort.",
    }
    for xpath, expected in expected_text.items():
        nodes = root.xpath(xpath, namespaces=NS)
        if len(nodes) != 1 or nodes[0].text != expected:
            raise ValueError(f"TEI metadata drift: {xpath}")
    availability = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
        namespaces=NS,
    )[0]
    change = root.xpath("./tei:teiHeader/tei:revisionDesc/tei:change", namespaces=NS)[0]
    if availability.get("status") != "restricted" or change.get("status") != "draft":
        raise ValueError("TEI status attribute drift")
    notes = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note", namespaces=NS
    )
    if [(node.get("type"), node.text) for node in notes] != [
        (
            "source-format",
            "Internet Archive DjVuTXT OCR; UTF-8; LF; no normalization or OCR cleanup",
        ),
        (
            "ocr-defect",
            "The retained Extra Volume OCR has zero Latin letters and 4057175 Greek-classified alphabetic characters; its text is preserved verbatim and unresolved.",
        ),
    ]:
        raise ValueError("TEI source note drift")
    texts = root.xpath("./tei:text/tei:group/tei:text", namespaces=NS)
    if len(texts) != 5:
        raise ValueError("TEI member omission or duplication")
    labels = ("Extra Volume", "Volume I", "Volume II", "Volume III", "Volume IV")
    for order, (text_node, label, source) in enumerate(
        zip(texts, labels, contents, strict=True), start=1
    ):
        if text_node.get(
            "{http://www.w3.org/XML/1998/namespace}id"
        ) != f"lib016-member-{order:02d}" or text_node.get("n") != str(order):
            raise ValueError("TEI member identity or order drift")
        divisions = text_node.xpath("./tei:body/tei:div", namespaces=NS)
        abs_ = text_node.xpath("./tei:body/tei:div/tei:ab", namespaces=NS)
        if (
            len(divisions) != 1
            or len(abs_) != 1
            or divisions[0].attrib
            != {"type": "volume", "subtype": "verbatim-ocr", "n": label}
        ):
            raise ValueError("TEI member scope drift")
        ab = abs_[0]
        if (
            ab.get("{http://www.w3.org/XML/1998/namespace}id")
            != f"lib016-member-{order:02d}-text"
            or ab.get("ana") != "#retained-ocr-verbatim"
            or len(ab)
            or (ab.text or "").encode("utf-8") != source
        ):
            raise ValueError("TEI member text or boundary drift")


def _expected_accountability(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "contract": "ocd-lib016-hastings-source-accountability-v1",
        "profile_id": "lib016-hastings-five-member-whole-work-v1",
        "aggregate_bytes": AGGREGATE_BYTES,
        "aggregate_sha256": AGGREGATE_SHA256,
        "member_count": 5,
        "omitted_members": 0,
        "duplicated_members": 0,
        "invented_separator_bytes": 0,
        "members": records,
    }


def _validate_json(
    source_manifest: object, candidate: object, records: list[dict[str, object]]
) -> None:
    accountability = _strict_json(
        getattr(candidate, "member_bytes")("source-accountability.json"),
        "source accountability",
    )
    _, schema_path = _authority(source_manifest, "source-accountability-schema")
    schema = _strict_json(schema_path.read_bytes(), "accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors or accountability != _expected_accountability(records):
        raise ValueError("source accountability drift")
    provenance = _strict_json(
        getattr(candidate, "member_bytes")("provenance.json"), "provenance"
    )
    expected_provenance = {
        "contract": "ocd-lib016-hastings-provenance-v1",
        "work_id": "hastings-dictionary-of-the-bible",
        "title": "Dictionary of the Bible",
        "editor": "James Hastings",
        "source_editions": "Volumes I-IV: Charles Scribner's Sons / T. & T. Clark, 1911 reprint; Extra Volume, 1909",
        "source_format": "five Internet Archive DjVuTXT OCR files",
        "aggregate_definition": "member UTF-8 bytes concatenated in lexicographic filename order with no separator",
        "aggregate_bytes": AGGREGATE_BYTES,
        "aggregate_sha256": AGGREGATE_SHA256,
        "derived_json_authority": "partial diagnostic only",
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "rights": {
            "underlying_publications": "public-domain claim requires human confirmation",
            "worldwide": "unresolved",
            "scan_and_ocr_layer_terms": "unresolved",
        },
    }
    if provenance != expected_provenance:
        raise ValueError("provenance drift")
    expected_unresolved = [
        {
            "id": "lib016-extra-volume-greek-ocr",
            "kind": "substantive-reading",
            "status": "source-bound-re-ocr-required",
            "scope": "b24749163_0005_djvu.txt; all 217888 physical lines",
            "detail": "Retained OCR has zero Latin letters and 4057175 Greek-classified alphabetic characters due an OCR-generation error; bytes are preserved verbatim and require exact scan-bound EzraOCR handling.",
        },
        {
            "id": "lib016-ocr-readings",
            "kind": "substantive-reading",
            "status": "human-review-required",
            "scope": "all five retained OCR members",
            "detail": "No OCR cleanup, Unicode normalization, article segmentation, or silent correction was performed.",
        },
        {
            "id": "lib016-edition-identity",
            "kind": "edition-witness",
            "status": "human-review-required",
            "scope": "five-member cohort",
            "detail": "Bibliographic identity is recorded but not human accepted as a critical or authorial edition.",
        },
        {
            "id": "lib016-rights",
            "kind": "rights",
            "status": "human-review-required",
            "scope": "worldwide and scan/OCR-layer terms",
            "detail": "Publication remains unauthorized pending human rights review.",
        },
        {
            "id": "lib016-acceptance",
            "kind": "acceptance-publication",
            "status": "human-review-required",
            "scope": "whole candidate",
            "detail": "Technical validation is not textual acceptance or publication authorization.",
        },
    ]
    unresolved = [
        _strict_json(line + b"\n", "unresolved record")
        for line in getattr(candidate, "member_bytes")("unresolved.jsonl").splitlines()
    ]
    if unresolved != expected_unresolved:
        raise ValueError("unresolved evidence drift")
    _, readme_path = _authority(source_manifest, "source-readme")
    if (
        getattr(candidate, "member_bytes")("README.source.md")
        != readme_path.read_bytes()
    ):
        raise ValueError("README drift")
    package = _strict_json(
        getattr(candidate, "member_bytes")("manifest.json"), "candidate manifest"
    )
    expected_members = []
    for name in (
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    ):
        content = getattr(candidate, "member_bytes")(name)
        expected_members.append(
            {"name": name, "bytes": len(content), "sha256": _sha(content)}
        )
    record = getattr(source_manifest, "record")
    expected_package = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": "hastings-dictionary-of-the-bible",
        "source_manifest": {
            "path": "sources/hastings-dictionary-of-the-bible/LIB-016/lib016-hastings.source-manifest.json",
            "sha256": getattr(source_manifest, "sha256"),
        },
        "converter": dict(record["converter"]),
        "package_schema": dict(record["package_schema"]),
        "members": expected_members,
    }
    if package != expected_package:
        raise ValueError("candidate manifest semantic drift")


def _source_member_set_sha(source_manifest: object) -> str:
    items = []
    for number in range(1, 6):
        authority, _ = _authority(source_manifest, f"retained-member-{number:02d}")
        items.append(
            {
                "name": authority.get("name"),
                "path": authority.get("path"),
                "bytes": authority.get("bytes"),
                "sha256": authority.get("sha256"),
            }
        )
    digest = _sha(
        _canonical(
            {
                "contract": "ocd-source-member-set-v1",
                "members": sorted(
                    items, key=lambda item: (str(item["path"]), str(item["name"]))
                ),
            }
        )
    )
    if digest != MEMBER_SET_SHA256:
        raise ValueError("retained source member-set identity drift")
    return digest


def _oracle(source_manifest: object, candidate: object) -> dict[str, object]:
    getattr(source_manifest, "verify")()
    _verify_authorities(source_manifest)
    getattr(candidate, "verify_integrity")()
    contents, records = _source_truth(source_manifest)
    _validate_tei(source_manifest, candidate, contents)
    _validate_json(source_manifest, candidate, records)
    implementation_sha256 = _sha(Path(__file__).read_bytes())
    validator = getattr(source_manifest, "record")["validator"]
    if (
        validator.get("implementation_sha256") != implementation_sha256
        or validator.get("import_closure_sha256") != implementation_sha256
    ):
        raise ValueError("oracle implementation or closure drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha256,
        "import_closure_sha256": implementation_sha256,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": getattr(source_manifest, "sha256"),
        "candidate_sha256": getattr(candidate, "sha256"),
        "profile_sha256": _authority(source_manifest, "reconstruction-profile")[0][
            "sha256"
        ],
        "package_schema_sha256": _authority(
            source_manifest, "candidate-package-schema"
        )[0]["sha256"],
        "source_sha256": _source_member_set_sha(source_manifest),
        "xsd_sha256": _authority(source_manifest, "tei-p5-xsd")[0]["sha256"],
        "policy_sha256": _authority(source_manifest, "validation-policy")[0]["sha256"],
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
