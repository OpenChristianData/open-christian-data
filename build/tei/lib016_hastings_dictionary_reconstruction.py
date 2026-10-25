"""Lossless LIB-016 Hastings *Dictionary of the Bible* TEI candidate writer."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, reconstruct


CONVERTER_ID = "ocd-lib016-hastings-dictionary-lossless-ocr-to-tei"
CONVERTER_VERSION = "1"
AGGREGATE_SHA256 = "1cd0f245927973e5f84db7bad42c71aa1dfb259e5aad026a40dd5f0d6238f7a7"
AGGREGATE_BYTES = 44_374_718
MEMBER_SET_SHA256 = "997d3b2ee21ce47e747811c826e05456964cac318f4846bc346b3b790d6e57c8"
WORK_ID = "hastings-dictionary-of-the-bible"
WORK_CONFIG_PATH = "sources/reference/hastings-dictionary-of-the-bible/config.json"
CATALOG_SOURCE_PATH = "reference/hastings-dictionary-of-the-bible.json"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
DEFAULT_SOURCE_ROOT = Path("D:/Library/Open Christian Data/raw/ia/hastings-dictionary")
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


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _latin_count(text: str) -> int:
    return sum(("A" <= char <= "Z") or ("a" <= char <= "z") for char in text)


def _source_member_set_sha(authorities: tuple[object, ...]) -> str:
    members = []
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("role") == "primary-source":
            members.append(
                {
                    "name": authority.get("name"),
                    "path": authority.get("path"),
                    "bytes": authority.get("bytes"),
                    "sha256": authority.get("sha256"),
                }
            )
    return _sha(
        _canonical(
            {
                "contract": "ocd-source-member-set-v1",
                "members": sorted(
                    members,
                    key=lambda item: (str(item["path"]), str(item["name"])),
                ),
            }
        )
    )


def _expected_catalog_claim_lineage() -> dict[str, object]:
    return {
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


@dataclass(frozen=True, slots=True)
class WitnessMember:
    name: str
    content: bytes
    sha256: str
    physical_lines: int
    latin_letters: int
    greek_classified_characters: int

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="strict")


def inspect_source_root(path: str | Path) -> tuple[WitnessMember, ...]:
    root = Path(path).resolve(strict=True)
    inspected: list[WitnessMember] = []
    aggregate = hashlib.sha256()
    aggregate_bytes = 0
    for (
        name,
        expected_bytes,
        expected_sha,
        expected_lines,
        expected_latin,
        expected_greek,
    ) in MEMBERS:
        content = (root / name).read_bytes()
        text = content.decode("utf-8", errors="strict")
        actual = (len(content), _sha(content), content.count(b"\n"), _latin_count(text))
        expected = (expected_bytes, expected_sha, expected_lines, expected_latin)
        if actual != expected or not content.endswith(b"\n") or b"\r" in content:
            raise ValueError(f"LIB-016 retained member identity drift: {name}")
        aggregate.update(content)
        aggregate_bytes += len(content)
        inspected.append(
            WitnessMember(
                name,
                content,
                expected_sha,
                expected_lines,
                expected_latin,
                expected_greek,
            )
        )
    if aggregate_bytes != AGGREGATE_BYTES or aggregate.hexdigest() != AGGREGATE_SHA256:
        raise ValueError("LIB-016 aggregate order, separator, or identity drift")
    return tuple(inspected)


@dataclass(frozen=True, slots=True)
class HastingsSourceManifest:
    path: Path
    repository_root: Path
    source_root: Path
    sha256: str
    _record: Mapping[str, object]

    @property
    def record(self) -> Mapping[str, object]:
        return self._record

    def authority_path(self, name: str) -> Path:
        authorities = self._record.get("authorities")
        if not isinstance(authorities, tuple):
            raise ValueError("source manifest authorities are invalid")
        for authority in authorities:
            if isinstance(authority, Mapping) and authority.get("name") == name:
                if authority.get("role") == "primary-source":
                    return (self.source_root / str(authority["filename"])).resolve(
                        strict=True
                    )
                logical = authority.get("path")
                if not isinstance(logical, str) or Path(logical).is_absolute():
                    raise ValueError(f"invalid authority path: {name}")
                return (self.repository_root / logical).resolve(strict=True)
        raise ValueError(f"missing authority: {name}")

    def verify(self) -> None:
        if _sha(self.path.read_bytes()) != self.sha256:
            raise ValueError("source manifest bytes drifted")
        if (
            self._record.get("contract") != "ocd-source-manifest-v1"
            or self._record.get("source_id") != WORK_ID
        ):
            raise ValueError("source manifest identity drift")
        inspect_source_root(self.source_root)
        authorities = self._record.get("authorities")
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
        if (
            tuple(
                authority.get("name")
                for authority in authorities
                if isinstance(authority, Mapping)
            )
            != expected_names
        ):
            raise ValueError("source manifest authority order or scope drift")
        for authority in authorities:
            if not isinstance(authority, Mapping):
                raise ValueError("invalid authority record")
            content = self.authority_path(str(authority.get("name"))).read_bytes()
            if authority.get("bytes") != len(content) or authority.get(
                "sha256"
            ) != _sha(content):
                raise ValueError(f"authority bytes drift: {authority.get('name')}")
        work_config = authorities[5]
        if not isinstance(work_config, Mapping) or dict(work_config) != {
            "name": "work-identity-config",
            "path": WORK_CONFIG_PATH,
            "role": "work-identity-config",
            "bytes": 1905,
            "sha256": "72fa2720f5ab5599ad446aed096d3b5118b42d5a1beb45e92a4b7fdd85fd61d0",
        }:
            raise ValueError("work identity config authority drift")
        config = json.loads(self.authority_path("work-identity-config").read_bytes())
        if not isinstance(config, dict) or {
            config.get("dictionary_id"),
            config.get("resource_id"),
        } != {WORK_ID}:
            raise ValueError("work identity config semantics drift")
        if _source_member_set_sha(authorities) != MEMBER_SET_SHA256:
            raise ValueError("retained source member-set identity drift")
        lineage = self._record.get("catalog_claim_lineage")
        if not isinstance(lineage, Mapping) or dict(lineage) != (
            _expected_catalog_claim_lineage()
        ):
            raise ValueError("catalog claim lineage drift")
        for key in ("converter", "validator"):
            binding = self._record.get(key)
            if not isinstance(binding, Mapping):
                raise ValueError(f"missing {key} binding")
            implementation = (
                self.repository_root / str(binding.get("implementation_path"))
            ).resolve(strict=True)
            if binding.get("implementation_sha256") != _sha(
                implementation.read_bytes()
            ):
                raise ValueError(f"{key} implementation drift")
        package = self._record.get("package_schema")
        if not isinstance(package, Mapping):
            raise ValueError("missing package schema binding")
        package_path = (self.repository_root / str(package.get("path"))).resolve(
            strict=True
        )
        if package.get("sha256") != _sha(package_path.read_bytes()):
            raise ValueError("package schema drift")


def load_source_manifest(
    path: str | Path,
    *,
    repository_root: str | Path,
    source_root: str | Path | None = None,
) -> HastingsSourceManifest:
    root = Path(repository_root).resolve(strict=True)
    manifest_path = Path(path).resolve(strict=True)
    manifest_path.relative_to(root)
    content = manifest_path.read_bytes()

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"source manifest has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        record = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("source manifest is not strict UTF-8 JSON") from exc
    if not isinstance(record, dict):
        raise ValueError("source manifest must be an object")
    expected_fields = {
        "contract",
        "source_id",
        "catalog_claim_lineage",
        "authorities",
        "converter",
        "validator",
        "package_schema",
        "lineage",
    }
    if set(record) != expected_fields:
        raise ValueError("source manifest top-level fields drifted")
    manifest = HastingsSourceManifest(
        manifest_path,
        root,
        Path(source_root or DEFAULT_SOURCE_ROOT).resolve(strict=True),
        _sha(content),
        _freeze(record),
    )  # type: ignore[arg-type]
    manifest.verify()
    return manifest


def _node(
    parent: etree._Element,
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    child = etree.SubElement(parent, f"{{{TEI_NS}}}{name}", **dict(attributes or {}))
    child.text = text
    return child


def _build_tei(members: tuple[WitnessMember, ...]) -> bytes:
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", "lib016-hastings-dictionary-candidate")
    header = _node(root, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(
        title_stmt,
        "title",
        text="Dictionary of the Bible: faithful retained-OCR transcription candidate",
    )
    _node(title_stmt, "editor", text="James Hastings")
    resp = _node(title_stmt, "respStmt")
    _node(resp, "resp", text="Exact five-member retained-OCR transcription")
    _node(resp, "name", text="Open Christian Data")
    publication = _node(file_desc, "publicationStmt")
    _node(publication, "publisher", text="Open Christian Data")
    availability = _node(publication, "availability", {"status": "restricted"})
    _node(
        availability,
        "p",
        text="Nonaccepted candidate; publication is not authorized; human textual, edition, identity, and rights review is required.",
    )
    source_desc = _node(file_desc, "sourceDesc")
    bibl = _node(source_desc, "bibl", {f"{{{XML_NS}}}id": "lib016-retained-cohort"})
    _node(bibl, "title", text="Dictionary of the Bible")
    _node(bibl, "editor", text="James Hastings")
    _node(
        bibl,
        "edition",
        text="Volumes I-IV: Scribner/T. & T. Clark 1911 reprint; Extra Volume: 1909",
    )
    _node(bibl, "idno", {"type": "SHA-256"}, AGGREGATE_SHA256)
    _node(
        bibl,
        "extent",
        text="44374718 bytes; five UTF-8 DjVuTXT OCR members concatenated in lexicographic filename order without separators",
    )
    _node(
        bibl,
        "note",
        {"type": "source-format"},
        "Internet Archive DjVuTXT OCR; UTF-8; LF; no normalization or OCR cleanup",
    )
    _node(
        bibl,
        "note",
        {"type": "ocr-defect"},
        "The retained Extra Volume OCR has zero Latin letters and 4057175 Greek-classified alphabetic characters; its text is preserved verbatim and unresolved.",
    )
    encoding = _node(header, "encodingDesc")
    project = _node(encoding, "projectDesc")
    _node(
        project,
        "p",
        text="Every member and every literal LF-delimited source line is represented once, verbatim, and in frozen aggregate order.",
    )
    _node(
        project,
        "p",
        text="No article segmentation, OCR correction, Unicode normalization, or inferred separator is applied.",
    )
    revision = _node(header, "revisionDesc")
    _node(
        revision,
        "change",
        {"status": "draft"},
        "Deterministic nonaccepted candidate generated from the exact retained cohort.",
    )
    text = _node(root, "text")
    group = _node(text, "group")
    labels = ("Extra Volume", "Volume I", "Volume II", "Volume III", "Volume IV")
    for order, (member, label) in enumerate(zip(members, labels, strict=True), start=1):
        volume_text = _node(
            group,
            "text",
            {f"{{{XML_NS}}}id": f"lib016-member-{order:02d}", "n": str(order)},
        )
        body = _node(volume_text, "body")
        division = _node(
            body, "div", {"type": "volume", "subtype": "verbatim-ocr", "n": label}
        )
        _node(
            division,
            "ab",
            {
                f"{{{XML_NS}}}id": f"lib016-member-{order:02d}-text",
                "ana": "#retained-ocr-verbatim",
            },
            member.text,
        )
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _accountability(members: tuple[WitnessMember, ...]) -> dict[str, object]:
    records = []
    offset = 0
    for order, member in enumerate(members, start=1):
        end = offset + len(member.content)
        records.append(
            {
                "name": member.name,
                "order": order,
                "byte_start": offset,
                "byte_end": end,
                "bytes": len(member.content),
                "sha256": member.sha256,
                "physical_lines": member.physical_lines,
                "terminal_lf": True,
                "latin_letters": member.latin_letters,
                "greek_classified_characters": member.greek_classified_characters,
                "represented_bytes": len(member.content),
                "represented_lines": member.physical_lines,
                "status": "represented",
                "target": f"#lib016-member-{order:02d}-text",
            }
        )
        offset = end
    return {
        "contract": "ocd-lib016-hastings-source-accountability-v1",
        "profile_id": "lib016-hastings-five-member-whole-work-v1",
        "aggregate_bytes": offset,
        "aggregate_sha256": AGGREGATE_SHA256,
        "member_count": 5,
        "omitted_members": 0,
        "duplicated_members": 0,
        "invented_separator_bytes": 0,
        "members": records,
    }


def _convert(source_manifest: HastingsSourceManifest) -> Mapping[str, bytes]:
    members = inspect_source_root(source_manifest.source_root)
    provenance = {
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
    unresolved = [
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
    return {
        "content.tei.xml": _build_tei(members),
        "source-accountability.json": _canonical(_accountability(members)),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": source_manifest.authority_path(
            "source-readme"
        ).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(
    source_manifest: HastingsSourceManifest, destination: str | Path
) -> CandidatePackage:
    return reconstruct(source_manifest, destination, _convert)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = load_source_manifest(
        args.manifest,
        repository_root=args.repository_root,
        source_root=args.source_root,
    )
    candidate = build_candidate(manifest, args.output)
    print(
        json.dumps(
            {
                "candidate_sha256": candidate.sha256,
                "output": str(candidate.path),
                "status": candidate.manifest["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
