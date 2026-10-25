"""Lossless A. A. Hodge *Outlines of Theology* TEI candidate writer."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, reconstruct


EXPECTED_SOURCE_BYTES = 1_976_207
EXPECTED_SOURCE_SHA256 = (
    "a81808d5a9d2037d3c1d0706de960fb13c175d3581dd131c7d505493df51fee5"
)
EXPECTED_SOURCE_LINES = 37_553
CONVERTER_ID = "ocd-aa-hodge-outlines-lossless-ocr-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
QUESTION_CANDIDATE_RE = re.compile(rb"^[\t ]*([0-9]+)\.[\t ]+")
CHAPTER_CANDIDATE_RE = re.compile(rb"^[\t ]*CHAPTER[\t ]+", re.IGNORECASE)


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


@dataclass(frozen=True, slots=True)
class Witness:
    content: bytes
    byte_count: int
    sha256: str
    line_count: int
    terminal_lf: bool

    @property
    def lines(self) -> tuple[bytes, ...]:
        return tuple(self.content.split(b"\n")[:-1])


def inspect_witness(path: str | Path) -> Witness:
    """Read and fail closed unless *path* is the exact retained UTF-8 witness."""

    content = Path(path).read_bytes()
    digest = _sha(content)
    terminal_lf = content.endswith(b"\n")
    line_count = content.count(b"\n") + int(bool(content) and not terminal_lf)
    content.decode("utf-8", errors="strict")
    if (
        len(content) != EXPECTED_SOURCE_BYTES
        or digest != EXPECTED_SOURCE_SHA256
        or line_count != EXPECTED_SOURCE_LINES
        or not terminal_lf
    ):
        raise ValueError("A. A. Hodge retained witness identity drift")
    return Witness(content, len(content), digest, line_count, terminal_lf)


@dataclass(frozen=True, slots=True)
class HodgeSourceManifest:
    """Source manifest whose primary authority is an explicit external witness."""

    path: Path
    repository_root: Path
    witness_path: Path
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
                    return self.witness_path
                logical = authority.get("path")
                if not isinstance(logical, str) or Path(logical).is_absolute():
                    raise ValueError(f"{name} authority path is invalid")
                return (self.repository_root / logical).resolve(strict=True)
        raise ValueError(f"source manifest has no {name!r} authority")

    def verify(self) -> None:
        if _sha(self.path.read_bytes()) != self.sha256:
            raise ValueError("source manifest bytes drifted")
        if self._record.get("contract") != "ocd-source-manifest-v1":
            raise ValueError("source manifest contract mismatch")
        authorities = self._record.get("authorities")
        if not isinstance(authorities, tuple) or not authorities:
            raise ValueError("source manifest authorities are invalid")
        names: set[str] = set()
        primary_count = 0
        for authority in authorities:
            if not isinstance(authority, Mapping):
                raise ValueError("source manifest authority is invalid")
            name = authority.get("name")
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("source manifest authority names are invalid")
            names.add(name)
            path = self.authority_path(name)
            content = path.read_bytes()
            if authority.get("role") == "primary-source":
                primary_count += 1
                inspect_witness(path)
            if authority.get("bytes") != len(content) or authority.get(
                "sha256"
            ) != _sha(content):
                raise ValueError(f"{name} authority bytes drifted")
        if primary_count != 1:
            raise ValueError("source manifest requires one primary source")
        for binding_name in ("converter", "validator"):
            binding = self._record.get(binding_name)
            if not isinstance(binding, Mapping):
                raise ValueError(f"source manifest {binding_name} binding is invalid")
            logical = binding.get("implementation_path")
            if not isinstance(logical, str):
                raise ValueError(f"source manifest {binding_name} path is invalid")
            implementation = (self.repository_root / logical).resolve(strict=True)
            if binding.get("implementation_sha256") != _sha(
                implementation.read_bytes()
            ):
                raise ValueError(f"{binding_name} implementation authority drifted")
        package_schema = self._record.get("package_schema")
        if not isinstance(package_schema, Mapping):
            raise ValueError("source manifest package schema binding is invalid")
        schema_path = self.repository_root / str(package_schema.get("path"))
        if package_schema.get("sha256") != _sha(schema_path.read_bytes()):
            raise ValueError("candidate package schema authority drifted")


def load_source_manifest(
    path: str | Path,
    *,
    repository_root: str | Path,
    witness_path: str | Path | None = None,
) -> HodgeSourceManifest:
    root = Path(repository_root).resolve(strict=True)
    manifest_path = Path(path).resolve(strict=True)
    manifest_path.relative_to(root)
    content = manifest_path.read_bytes()
    record = json.loads(content.decode("utf-8"))
    if not isinstance(record, dict):
        raise ValueError("source manifest must be an object")
    selected_witness = Path(
        witness_path
        or "D:/Library/Open Christian Data/raw/gutenberg/outlinesoftheolo1879hodg_djvu.txt"
    ).resolve(strict=True)
    manifest = HodgeSourceManifest(
        manifest_path,
        root,
        selected_witness,
        _sha(content),
        _freeze(record),  # type: ignore[arg-type]
    )
    manifest.verify()
    return manifest


def _line_role(line: bytes) -> str:
    if CHAPTER_CANDIDATE_RE.match(line):
        return "chapter-candidate"
    if QUESTION_CANDIDATE_RE.match(line):
        return "question-candidate"
    return "source-line"


def _line_records(witness: Witness) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(witness.lines, start=1):
        source_bytes = line + b"\n"
        line_id = f"hodge-line-{number:06d}"
        end = offset + len(source_bytes)
        records.append(
            {
                "id": line_id,
                "line_number": number,
                "byte_start": offset,
                "byte_end": end,
                "bytes": len(source_bytes),
                "sha256": _sha(source_bytes),
                "role": _line_role(line),
                "status": "represented",
                "target": f"#{line_id}",
            }
        )
        offset = end
    if offset != witness.byte_count:
        raise ValueError("source line byte accounting does not close")
    return records


def _node(
    parent: etree._Element,
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    child = etree.SubElement(parent, f"{{{TEI_NS}}}{name}", **dict(attributes or {}))
    child.text = text
    return child


def _build_tei(witness: Witness) -> bytes:
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", "aa-hodge-outlines-candidate")
    header = _node(root, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(
        title_stmt,
        "title",
        text="Outlines of Theology: faithful OCR transcription candidate",
    )
    _node(title_stmt, "author", text="A. A. Hodge")
    responsibility = _node(title_stmt, "respStmt")
    _node(responsibility, "resp", text="Exact source-line transcription")
    _node(responsibility, "name", text="Open Christian Data")
    publication = _node(file_desc, "publicationStmt")
    _node(publication, "publisher", text="Open Christian Data")
    availability = _node(publication, "availability", {"status": "restricted"})
    _node(
        availability,
        "p",
        text="Nonaccepted candidate; publication is not authorized; human rights review is required.",
    )
    source_desc = _node(file_desc, "sourceDesc")
    bibl = _node(source_desc, "bibl", {f"{{{XML_NS}}}id": "hodge-retained-source"})
    _node(bibl, "title", text="Outlines of Theology")
    _node(bibl, "author", text="A. A. Hodge")
    _node(
        bibl,
        "edition",
        text="Robert Carter & Bros., New York, 1879; Internet Archive DjVuTXT OCR witness",
    )
    _node(
        bibl,
        "idno",
        {"type": "URI"},
        "https://archive.org/download/outlinesoftheolo1879hodg/outlinesoftheolo1879hodg_djvu.txt",
    )
    _node(bibl, "idno", {"type": "SHA-256"}, EXPECTED_SOURCE_SHA256)
    _node(
        bibl,
        "extent",
        text=f"{EXPECTED_SOURCE_BYTES} bytes; {EXPECTED_SOURCE_LINES} LF-terminated physical lines",
    )
    _node(
        bibl,
        "note",
        {"type": "source-format"},
        "DjVuTXT (OCR); UTF-8; no normalization or OCR cleanup",
    )
    _node(
        bibl,
        "note",
        {"type": "edition-status"},
        "Edition and textual identity require human review.",
    )
    encoding = _node(header, "encodingDesc")
    project = _node(encoding, "projectDesc")
    _node(
        project,
        "p",
        text="Every retained OCR source line is represented once, verbatim, and in source order.",
    )
    _node(
        project,
        "p",
        text="catechism_qa structure is carried only as noneditorial question and chapter candidate annotations.",
    )
    profile = _node(header, "profileDesc")
    classification = _node(profile, "textClass")
    keywords = _node(classification, "keywords")
    _node(keywords, "term", text="catechism_qa")
    _node(keywords, "term", text="OCR transcription")
    revision = _node(header, "revisionDesc")
    _node(
        revision,
        "change",
        {"status": "draft"},
        "Deterministic nonaccepted candidate generated from the pinned witness.",
    )
    text = _node(root, "text")
    body = _node(text, "body")
    division = _node(
        body,
        "div",
        {
            f"{{{XML_NS}}}id": "hodge-verbatim-ocr",
            "type": "catechism_qa",
            "subtype": "ocr-source-transcription",
        },
    )
    for number, line in enumerate(witness.lines, start=1):
        role = _line_role(line)
        annotations = "#source-line"
        if role != "source-line":
            annotations += f" #{role}"
        _node(
            division,
            "ab",
            {
                f"{{{XML_NS}}}id": f"hodge-line-{number:06d}",
                "n": str(number),
                "ana": annotations,
            },
            line.decode("utf-8"),
        )
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _handoff(witness: Witness) -> tuple[dict[str, object], dict[str, object]]:
    request_core: dict[str, object] = {
        "contract": "ocd-ezraocr-request-v1",
        "work_id": "aa-hodge-outlines",
        "source_manifest_id": "aa-hodge-outlines-whole-work-v1",
        "source_members": [
            {
                "id": "outlinesoftheolo1879hodg-djvutxt",
                "bytes": witness.byte_count,
                "sha256": witness.sha256,
                "physical_lines": witness.line_count,
                "order": 1,
            }
        ],
        "page_census": {
            "status": "unavailable",
            "ordered_page_ids": [],
            "reason": "The retained DjVuTXT witness has no retained page-boundary markers.",
        },
        "requested_operation": "byte-identical pass-through; no OCR correction authorized",
    }
    request = {**request_core, "request_digest": _sha(_canonical(request_core))}
    result_core: dict[str, object] = {
        "contract": "ocd-ezraocr-result-v1",
        "request_digest": request["request_digest"],
        "status": "pass-through",
        "ocr_correction_status": "not-performed",
        "corrected_text_sha256": witness.sha256,
        "corrected_text_bytes": witness.byte_count,
        "returned_physical_lines": witness.line_count,
        "returned_page_census": request_core["page_census"],
        "unresolved_readings": {
            "scope": f"all {witness.line_count} retained OCR source lines",
            "status": "human-review-required",
        },
    }
    result = {**result_core, "result_digest": _sha(_canonical(result_core))}
    return request, result


def _convert(source_manifest: HodgeSourceManifest) -> Mapping[str, bytes]:
    witness = inspect_witness(source_manifest.authority_path("retained-djvutxt"))
    records = _line_records(witness)
    counts = {
        "source_bytes": witness.byte_count,
        "physical_lines": witness.line_count,
        "represented_lines": len(records),
        "question_candidates": sum(
            item["role"] == "question-candidate" for item in records
        ),
        "chapter_candidates": sum(
            item["role"] == "chapter-candidate" for item in records
        ),
        "omitted_lines": 0,
        "duplicated_lines": 0,
    }
    accountability = {
        "contract": "ocd-aa-hodge-outlines-source-accountability-v1",
        "profile_id": "aa-hodge-outlines-whole-work-v1",
        "source_sha256": witness.sha256,
        "counts": counts,
        "crosswalk_sha256": _sha(_canonical(records)),
        "crosswalk": records,
    }
    request, result = _handoff(witness)
    provenance = {
        "contract": "ocd-aa-hodge-outlines-provenance-v1",
        "work_id": "aa-hodge-outlines",
        "title": "Outlines of Theology",
        "author": "A. A. Hodge",
        "source_edition": "Robert Carter & Bros., New York, 1879. IA:outlinesoftheolo1879hodg.",
        "source_format": "DjVuTXT (OCR)",
        "source_url": "https://archive.org/download/outlinesoftheolo1879hodg/outlinesoftheolo1879hodg_djvu.txt",
        "source_sha256": witness.sha256,
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "rights": {
            "united_states": "1879 publication supports a public-domain claim; human confirmation remains required for publication",
            "worldwide": "unresolved",
            "scan_and_ocr_layer_terms": "unresolved",
        },
        "handoff_request": request,
        "handoff_result": result,
    }
    unresolved = [
        {
            "id": "hodge-ocr-readings",
            "kind": "substantive-reading",
            "status": "human-review-required",
            "scope": f"all {witness.line_count} retained OCR source lines",
            "detail": "No OCR cleanup or silent normalization was performed.",
        },
        {
            "id": "hodge-edition-identity",
            "kind": "edition-witness",
            "status": "human-review-required",
            "scope": "whole work",
            "detail": "The retained scan/OCR witness is not an accepted critical or authorial edition.",
        },
        {
            "id": "hodge-rights",
            "kind": "rights",
            "status": "human-review-required",
            "scope": "worldwide and scan/OCR-layer terms",
            "detail": "Publication remains unauthorized pending human rights review.",
        },
        {
            "id": "hodge-acceptance",
            "kind": "acceptance-publication",
            "status": "human-review-required",
            "scope": "whole candidate",
            "detail": "Technical validation is not textual acceptance or publication authorization.",
        },
    ]
    return {
        "content.tei.xml": _build_tei(witness),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": source_manifest.authority_path(
            "source-readme"
        ).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(
    source_manifest: HodgeSourceManifest, destination: str | Path
) -> CandidatePackage:
    return reconstruct(source_manifest, destination, _convert)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--witness", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    source_manifest = load_source_manifest(
        args.manifest,
        repository_root=args.repository_root,
        witness_path=args.witness,
    )
    candidate = build_candidate(source_manifest, args.output)
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
