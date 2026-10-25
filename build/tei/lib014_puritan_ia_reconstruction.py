"""Faithful retained-line TEI candidates for the four LIB-014 IA witnesses."""

from __future__ import annotations

import ast
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, reconstruct


CONVERTER_ID = "ocd-lib014-puritan-ia-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"


@dataclass(frozen=True, slots=True)
class WorkSpec:
    filename: str
    byte_count: int
    sha256: str
    line_count: int
    title: str
    creator: str
    source_url: str
    edition_evidence: str
    contributor_evidence: str
    wrapper_end_line: int = 0


WORKS = {
    "brooks-precious-remedies": WorkSpec(
        "brooks_precious_remedies.txt",
        360_630,
        "dd9e5a0bd0b875939b3dc2bd5f848b84988a99c53ce8451f3222c34c58547cdb",
        8_526,
        "Precious Remedies Against Satan's Devices",
        "Thomas Brooks",
        "https://archive.org/download/preciousremedies00broo/preciousremedies00broo_djvu.txt",
        "Retained title page states First American Edition, New Haven, Nathan Whiting, 1832.",
        "Retained title page states abridged by W. Smelle and edited by Staunton Stevens Burdott.",
    ),
    "burroughs-rare-jewel-contentment": WorkSpec(
        "burroughs_rare_jewel.txt",
        454_509,
        "fed949f533923e8d4291df1b7eb04644fbe59f743cb732e67dbc8768f26c59d6",
        8_212,
        "The Rare Jewel of Christian Contentment",
        "Jeremiah Burroughs",
        "https://archive.org/download/JerimiahBurroughsTheRareJewelOfChristianContentment/Jerimiah%20Burroughs%20The%20Rare%20Jewel%20of%20Christian%20Contentment_djvu.txt",
        "The retained text identifies the work and creator but does not establish a scan edition date.",
        "No contributor role is asserted as accepted metadata.",
    ),
    "gurnall-complete-armour": WorkSpec(
        "gurnall_complete_armour.txt",
        4_672_135,
        "aa145a5411d1f87b35cde03407e9c4db4cc0a003a550821c3a9c73d54be2c4fa",
        57_974,
        "The Christian in Complete Armour",
        "William Gurnall",
        "https://archive.org/download/christianincom00gurn/christianincom00gurn_djvu.txt",
        "Retained title page states London, Thomas Tegg, MDCCCXLV (1845).",
        "Retained title page states carefully revised and corrected by Rev. John Campbell, D.D.",
    ),
    "sibbes-bruised-reed": WorkSpec(
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
            raise ValueError("LIB-014 import closure escapes repository")
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
            raise ValueError("LIB-014 import closure escapes repository") from exc
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name)
                and node.func.id in _DYNAMIC_IMPORT_CALLS
                or isinstance(node.func, ast.Attribute)
                and node.func.attr in _DYNAMIC_IMPORT_CALLS
            ):
                raise ValueError("LIB-014 import closure contains dynamic execution")
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
        raise ValueError("LIB-014 import closure omitted shared contract")
    if matches[0]["sha256"] != _SHARED_CONTRACT_SHA256:
        raise ValueError("LIB-014 shared contract closure drifted")


@dataclass(frozen=True, slots=True)
class Witness:
    content: bytes
    byte_count: int
    sha256: str
    line_count: int

    @property
    def records(self) -> tuple[bytes, ...]:
        return tuple(self.content.splitlines(keepends=True))


def inspect_witness(work_id: str, path: str | Path) -> Witness:
    if work_id not in WORKS:
        raise ValueError(f"work is outside LIB-014 scope: {work_id}")
    spec = WORKS[work_id]
    content = Path(path).read_bytes()
    content.decode("utf-8", errors="strict")
    records = tuple(content.splitlines(keepends=True))
    if (
        len(content),
        _sha(content),
        len(records),
        content.count(b"\n"),
        content.count(b"\r"),
    ) != (spec.byte_count, spec.sha256, spec.line_count, spec.line_count, 0):
        raise ValueError(f"{work_id} retained witness identity or LF framing drift")
    if not content.endswith(b"\n") or any(
        not record.endswith(b"\n") for record in records
    ):
        raise ValueError(
            f"{work_id} retained witness has incomplete physical-line framing"
        )
    return Witness(content, len(content), spec.sha256, len(records))


@dataclass(frozen=True, slots=True)
class PuritanSourceManifest:
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
                if (
                    not isinstance(logical, str)
                    or Path(logical).is_absolute()
                    or ".." in Path(logical).parts
                ):
                    raise ValueError(f"{name} authority path is invalid")
                return (self.repository_root / logical).resolve(strict=True)
        raise ValueError(f"source manifest has no {name!r} authority")

    def verify(self) -> None:
        if _sha(self.path.read_bytes()) != self.sha256:
            raise ValueError("source manifest bytes drifted")
        authorities = self._record.get("authorities")
        if not isinstance(authorities, tuple) or not authorities:
            raise ValueError("source manifest authority inventory is invalid")
        names: set[str] = set()
        for authority in authorities:
            if (
                not isinstance(authority, Mapping)
                or not isinstance(authority.get("name"), str)
                or authority["name"] in names
            ):
                raise ValueError("source manifest authority record is invalid")
            names.add(str(authority["name"]))
            content = self.authority_path(str(authority["name"])).read_bytes()
            if authority.get("bytes") != len(content) or authority.get(
                "sha256"
            ) != _sha(content):
                raise ValueError(f"{authority['name']} authority bytes drifted")
        for binding_name in ("converter", "validator"):
            binding = self._record.get(binding_name)
            if not isinstance(binding, Mapping) or not isinstance(
                binding.get("implementation_path"), str
            ):
                raise ValueError(f"{binding_name} binding is invalid")
            implementation = (
                self.repository_root / str(binding["implementation_path"])
            ).resolve(strict=True)
            if binding.get("implementation_sha256") != _sha(
                implementation.read_bytes()
            ):
                raise ValueError(f"{binding_name} implementation authority drifted")
        package_schema = self._record.get("package_schema")
        if not isinstance(package_schema, Mapping) or not isinstance(
            package_schema.get("path"), str
        ):
            raise ValueError("candidate package schema binding is invalid")
        if package_schema.get("sha256") != _sha(
            (self.repository_root / str(package_schema["path"]))
            .resolve(strict=True)
            .read_bytes()
        ):
            raise ValueError("candidate package schema authority drifted")


def _verify_closure(source_manifest: PuritanSourceManifest) -> str:
    converter = source_manifest.record.get("converter")
    if not isinstance(converter, Mapping):
        raise ValueError("LIB-014 converter binding is invalid")
    implementation_path = converter.get("implementation_path")
    if not isinstance(implementation_path, str):
        raise ValueError("LIB-014 converter implementation path is invalid")
    closure_records = _closure(
        source_manifest.repository_root,
        source_manifest.repository_root / implementation_path,
    )
    _verify_contract_binding(closure_records)
    closure = _sha(_canonical(closure_records))
    if closure != source_manifest.record.get("producer_import_closure_sha256"):
        raise ValueError("LIB-014 producer import closure drifted")
    return closure


def load_source_manifest(
    path: str | Path, *, repository_root: str | Path, witness_path: str | Path
) -> PuritanSourceManifest:
    root = Path(repository_root).resolve(strict=True)
    manifest_path = Path(path).resolve(strict=True)
    manifest_path.relative_to(root)
    content = manifest_path.read_bytes()
    record = json.loads(content.decode("utf-8"))
    if (
        not isinstance(record, dict)
        or record.get("contract") != "ocd-source-manifest-v1"
        or record.get("work_id") not in WORKS
    ):
        raise ValueError("source manifest contract or scope mismatch")
    manifest = PuritanSourceManifest(
        manifest_path,
        root,
        Path(witness_path).resolve(strict=True),
        _sha(content),
        _freeze(record),
    )  # type: ignore[arg-type]
    manifest.verify()
    inspect_witness(str(record["work_id"]), manifest.witness_path)
    return manifest


def _category(spec: WorkSpec, line_number: int) -> str:
    return (
        "digitization-wrapper"
        if spec.wrapper_end_line and line_number <= spec.wrapper_end_line
        else "retained-ocr-line"
    )


def _records(work_id: str, witness: Witness) -> list[dict[str, object]]:
    spec = WORKS[work_id]
    result: list[dict[str, object]] = []
    offset = 0
    for number, record in enumerate(witness.records, 1):
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
                "category": _category(spec, number),
                "disposition": "represented",
                "target": f"#{line_id}",
            }
        )
        offset = end
    if offset != witness.byte_count:
        raise ValueError("source byte accounting does not close")
    return result


def _node(
    parent: etree._Element,
    name: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    child = etree.SubElement(parent, f"{{{TEI_NS}}}{name}")
    for key, value in (attrs or {}).items():
        child.set(f"{{{XML_NS}}}id" if key == "xml:id" else key, value)
    child.text = text
    return child


def _tei(work_id: str, witness: Witness) -> bytes:
    spec = WORKS[work_id]
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", f"{work_id}-candidate")
    header = _node(root, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(title_stmt, "title", text=f"{spec.title}: faithful retained-source candidate")
    _node(title_stmt, "author", text=spec.creator)
    resp = _node(title_stmt, "respStmt")
    _node(resp, "resp", text="Exact physical-line transcription")
    _node(resp, "name", text="Open Christian Data")
    publication = _node(file_desc, "publicationStmt")
    _node(publication, "publisher", text="Open Christian Data")
    _node(
        _node(publication, "availability", {"status": "restricted"}),
        "p",
        text="Nonaccepted candidate; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate.",
    )
    bibl = _node(
        _node(file_desc, "sourceDesc"), "bibl", {"xml:id": f"{work_id}-retained-source"}
    )
    _node(bibl, "title", text=spec.title)
    _node(bibl, "author", text=spec.creator)
    _node(bibl, "note", {"type": "edition-evidence"}, spec.edition_evidence)
    _node(bibl, "note", {"type": "contributor-evidence"}, spec.contributor_evidence)
    _node(bibl, "idno", {"type": "URI"}, spec.source_url)
    _node(bibl, "idno", {"type": "SHA-256"}, spec.sha256)
    _node(
        bibl,
        "extent",
        text=f"{spec.byte_count} bytes; {spec.line_count} UTF-8 LF physical lines",
    )
    project = _node(_node(header, "encodingDesc"), "projectDesc")
    _node(
        project,
        "p",
        text="Every retained physical line is represented exactly once, in source order, verbatim after the single LF transport byte is removed.",
    )
    _node(
        project,
        "p",
        text="OCR uncertainty, scan artifacts, marginalia, wrappers, and blank lines remain source evidence; no silent correction or normalization is performed.",
    )
    _node(
        _node(header, "revisionDesc"),
        "change",
        {"status": "draft"},
        "Deterministic nonaccepted LIB-014 candidate generated from the pinned witness.",
    )
    division = _node(
        _node(_node(root, "text"), "body"),
        "div",
        {
            "xml:id": f"{work_id}-retained-lines",
            "type": "treatise",
            "subtype": "ia-ocr-source-transcription",
        },
    )
    for number, record in enumerate(witness.records, 1):
        _node(
            division,
            "ab",
            {
                "xml:id": f"{work_id}-line-{number:05d}",
                "n": str(number),
                "ana": f"#source-line #{_category(spec, number)}",
            },
            record[:-1].decode("utf-8", errors="strict"),
        )
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _convert(source_manifest: PuritanSourceManifest) -> Mapping[str, bytes]:
    _verify_closure(source_manifest)
    work_id = str(source_manifest.record["work_id"])
    if work_id not in WORKS:
        raise ValueError("source manifest work is outside LIB-014")
    spec = WORKS[work_id]
    witness = inspect_witness(
        work_id, source_manifest.authority_path("retained-source")
    )
    crosswalk = _records(work_id, witness)
    accountability = {
        "contract": "ocd-lib014-source-accountability-v1",
        "work_id": work_id,
        "source_sha256": spec.sha256,
        "source_bytes": spec.byte_count,
        "physical_lines": spec.line_count,
        "represented_lines": spec.line_count,
        "omitted_lines": 0,
        "duplicated_lines": 0,
        "member_census": [
            {
                "path": f"raw/ia/{spec.filename}",
                "bytes": spec.byte_count,
                "sha256": spec.sha256,
                "included": True,
                "reason": "The frozen LIB-014 source map assigns this sole exact retained direct-file member to this work.",
            }
        ],
        "excluded_members": [],
        "crosswalk_sha256": _sha(_canonical(crosswalk)),
        "crosswalk": crosswalk,
    }
    profile = json.loads(
        source_manifest.authority_path("complete-source-feature-profile").read_bytes()
    )
    provenance = {
        "contract": "ocd-lib014-provenance-v1",
        "work_id": work_id,
        "title": spec.title,
        "creator": spec.creator,
        "source_format": "Internet Archive retained UTF-8 OCR/plain-text export with LF framing",
        "source_url": spec.source_url,
        "source_sha256": spec.sha256,
        "edition_evidence": spec.edition_evidence,
        "contributor_evidence": spec.contributor_evidence,
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "technical_validation_is_human_acceptance": False,
        "rights": profile["rights"],
    }
    unresolved = [
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
            "scope": f"all {spec.line_count} retained physical lines",
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
    return {
        "content.tei.xml": _tei(work_id, witness),
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
    source_manifest: PuritanSourceManifest, destination: str | Path
) -> CandidatePackage:
    return reconstruct(source_manifest, destination, _convert)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--witness", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = load_source_manifest(
        args.manifest, repository_root=args.repository_root, witness_path=args.witness
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
