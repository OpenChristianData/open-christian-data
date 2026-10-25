"""Faithful retained-line TEI candidates for six exact LIB-015 witnesses."""

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


CONVERTER_ID = "ocd-lib015-gutenberg-theology-to-tei"
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
    volume: str | None


WORKS = {
    "dabney-systematic-theology": WorkSpec("syllabusnotesof00dabn_djvu.txt", 2_440_828, "2db4ddb5b9684e64797a2a963c55fef5b859affbd140291a758c464e24d4658a", 36_714, "Syllabus and Notes of the Course of Systematic and Polemic Theology", "Robert Lewis Dabney", None),
    "miley-systematic-theology-vol-1": WorkSpec("systematictheolo01mile_djvu.txt", 1_684_078, "ae20e73d6895a4f88d207e2f9991107252bc59875166c6eb7435e862abbd22f3", 28_411, "Systematic Theology", "John Miley", "1"),
    "miley-systematic-theology-vol-2": WorkSpec("systematictheolo02mile_djvu.txt", 1_658_840, "c6d86e0e335345d358b97c961ec660f3a8c7c06c4e53ca218802e159945416f0", 30_722, "Systematic Theology", "John Miley", "2"),
    "shedd-dogmatic-theology-vol-1": WorkSpec("dogmatictheology01sheduoft_djvu.txt", 1_309_299, "bb27e8a8bd3b3eb603bd822982786dc83817cca574b79c97ef10d00c129ce58a", 22_524, "Dogmatic Theology", "William G. T. Shedd", "1"),
    "shedd-dogmatic-theology-vol-2": WorkSpec("dogmatictheology02sheduoft_djvu.txt", 1_989_151, "18a47d3f1dc36cbada22bb9ad017414af33762af65e2d253c773654c2764c534", 35_767, "Dogmatic Theology", "William G. T. Shedd", "2"),
    "shedd-dogmatic-theology-vol-3": WorkSpec("dogmatictheology03shed_0_djvu.txt", 1_103_532, "3fa48483098ff8372c30d4e96b1dca986bd745ae1f4f309f124b750290f7b62a", 22_818, "Dogmatic Theology", "William G. T. Shedd", "3"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict_object(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key}")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class Witness:
    content: bytes
    lines: tuple[bytes, ...]
    byte_count: int
    sha256: str


def inspect_witness(work_id: str, path: str | Path) -> Witness:
    if work_id not in WORKS:
        raise ValueError(f"work is outside LIB-015 exact-source scope: {work_id}")
    spec = WORKS[work_id]
    content = Path(path).read_bytes()
    digest = _sha(content)
    if len(content) != spec.byte_count or digest != spec.sha256:
        raise ValueError(f"{work_id} retained witness identity drift")
    if content.startswith(b"\xef\xbb\xbf") or not content.endswith(b"\n") or b"\r" in content:
        raise ValueError(f"{work_id} retained witness framing drift")
    content.decode("utf-8", errors="strict")
    lines = tuple(content.split(b"\n")[:-1])
    if len(lines) != spec.line_count:
        raise ValueError(f"{work_id} retained witness line census drift")
    return Witness(content, lines, len(content), digest)


@dataclass(frozen=True, slots=True)
class SourceManifest:
    path: Path
    repository_root: Path
    witness_path: Path
    sha256: str
    record: Mapping[str, object]

    def authority_path(self, name: str) -> Path:
        authorities = self.record.get("authorities")
        if not isinstance(authorities, tuple):
            raise ValueError("source manifest authorities are invalid")
        for authority in authorities:
            if isinstance(authority, Mapping) and authority.get("name") == name:
                if authority.get("role") == "primary-source":
                    return self.witness_path
                logical = authority.get("path")
                if not isinstance(logical, str) or Path(logical).is_absolute() or ".." in Path(logical).parts:
                    raise ValueError(f"{name} authority path is invalid")
                return (self.repository_root / logical).resolve(strict=True)
        raise ValueError(f"source manifest has no {name!r} authority")

    def verify(self) -> None:
        if _sha(self.path.read_bytes()) != self.sha256:
            raise ValueError("source manifest bytes drifted")
        authorities = self.record.get("authorities")
        if not isinstance(authorities, tuple) or not authorities:
            raise ValueError("source manifest authority inventory is invalid")
        names: set[str] = set()
        for authority in authorities:
            if not isinstance(authority, Mapping) or not isinstance(authority.get("name"), str) or authority["name"] in names:
                raise ValueError("source manifest authority record is invalid")
            names.add(str(authority["name"]))
            content = self.authority_path(str(authority["name"])).read_bytes()
            if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(content):
                raise ValueError(f"{authority['name']} authority bytes drifted")
        for binding_name in ("converter", "validator"):
            binding = self.record.get(binding_name)
            if not isinstance(binding, Mapping) or not isinstance(binding.get("implementation_path"), str):
                raise ValueError(f"{binding_name} binding is invalid")
            implementation = (self.repository_root / str(binding["implementation_path"])).resolve(strict=True)
            if binding.get("implementation_sha256") != _sha(implementation.read_bytes()):
                raise ValueError(f"{binding_name} implementation authority drifted")


def load_source_manifest(path: str | Path, *, repository_root: str | Path, witness_path: str | Path) -> SourceManifest:
    root = Path(repository_root).resolve(strict=True)
    manifest_path = Path(path).resolve(strict=True)
    manifest_path.relative_to(root)
    content = manifest_path.read_bytes()
    record = _strict_object(content, "source manifest")
    if record.get("contract") != "ocd-source-manifest-v1" or record.get("ticket") != "LIB-015" or record.get("work_id") not in WORKS:
        raise ValueError("source manifest contract or scope mismatch")
    manifest = SourceManifest(manifest_path, root, Path(witness_path).resolve(strict=True), _sha(content), _freeze(record))  # type: ignore[arg-type]
    manifest.verify()
    inspect_witness(str(record["work_id"]), manifest.witness_path)
    return manifest


def _records(work_id: str, witness: Witness) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(witness.lines, 1):
        physical = line + b"\n"
        end = offset + len(physical)
        line_id = f"{work_id}-line-{number:05d}"
        text = line.decode("utf-8", errors="strict")
        records.append({"id": line_id, "line": number, "byte_start": offset, "byte_end": end, "record_sha256": _sha(physical), "text_sha256": _sha(text.encode("utf-8")), "disposition": "represented", "target": f"#{line_id}"})
        offset = end
    if offset != witness.byte_count:
        raise ValueError("source byte accounting does not close")
    return records


def _node(parent: etree._Element, name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    child = etree.SubElement(parent, f"{{{TEI_NS}}}{name}")
    for key, value in (attrs or {}).items():
        child.set(f"{{{XML_NS}}}id" if key == "xml:id" else key, value)
    child.text = text
    return child


def _tei(work_id: str, witness: Witness, profile: Mapping[str, object]) -> bytes:
    spec = WORKS[work_id]
    volume = f"; volume {spec.volume}" if spec.volume else ""
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", f"{work_id}-candidate")
    header = _node(root, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(title_stmt, "title", text=f"{spec.title}{volume}: faithful retained-source candidate")
    _node(title_stmt, "author", text=spec.creator)
    resp = _node(title_stmt, "respStmt")
    _node(resp, "resp", text="Exact OCR physical-line transcription")
    _node(resp, "name", text="Open Christian Data")
    publication = _node(file_desc, "publicationStmt")
    _node(publication, "publisher", text="Open Christian Data")
    _node(_node(publication, "availability", {"status": "restricted"}), "p", text="Nonaccepted candidate; publication is not authorized; human identity, edition, rights, textual, and editorial review remain separate.")
    bibl = _node(_node(file_desc, "sourceDesc"), "bibl", {"xml:id": f"{work_id}-retained-source"})
    _node(bibl, "title", text=spec.title)
    _node(bibl, "author", text=spec.creator)
    if spec.volume:
        _node(bibl, "biblScope", {"unit": "volume"}, spec.volume)
    _node(bibl, "idno", {"type": "local-path"}, f"raw/gutenberg/{spec.filename}")
    _node(bibl, "idno", {"type": "SHA-256"}, spec.sha256)
    _node(bibl, "extent", text=f"{spec.byte_count} bytes; {spec.line_count} UTF-8 LF-terminated OCR physical lines")
    project = _node(_node(header, "encodingDesc"), "projectDesc")
    _node(project, "p", text="Every retained OCR physical line is represented exactly once, verbatim after LF transport framing removal, and in source order.")
    _node(project, "p", text="OCR uncertainty is preserved rather than silently corrected; every line remains marked as an unreviewed OCR reading.")
    _node(_node(header, "revisionDesc"), "change", {"status": "draft"}, "Deterministic nonaccepted LIB-015 candidate generated from the pinned witness.")
    division = _node(_node(_node(root, "text"), "body"), "div", {"xml:id": f"{work_id}-retained-lines", "type": "theology", "subtype": "retained-ocr-transcription"})
    for number, line in enumerate(witness.lines, 1):
        _node(division, "ab", {"xml:id": f"{work_id}-line-{number:05d}", "n": str(number), "ana": "#source-line #ocr-source #unreviewed-reading"}, line.decode("utf-8", errors="strict"))
    if profile.get("work_id") != work_id:
        raise ValueError("profile work binding drift")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    work_id = str(source_manifest.record["work_id"])
    spec = WORKS[work_id]
    witness = inspect_witness(work_id, source_manifest.authority_path("retained-source"))
    profile = _strict_object(source_manifest.authority_path("reconstruction-profile").read_bytes(), "reconstruction profile")
    policy = _strict_object(source_manifest.authority_path("validation-policy").read_bytes(), "validation policy")
    if policy != {"candidate_status": "nonaccepted", "contract": "ocd-lib015-validation-policy-v1", "human_acceptance_required": True, "publication_authorized": False, "ticket": "LIB-015"}:
        raise ValueError("validation policy drift")
    records = _records(work_id, witness)
    census = [{"path": f"raw/gutenberg/{spec.filename}", "bytes": spec.byte_count, "sha256": spec.sha256, "included": True, "reason": "Exact frozen LIB-015 direct-file witness."}]
    accountability = {"contract": "ocd-lib015-source-accountability-v1", "ticket": "LIB-015", "work_id": work_id, "source_sha256": spec.sha256, "source_bytes": spec.byte_count, "physical_lines": spec.line_count, "represented_lines": spec.line_count, "omitted_lines": 0, "duplicated_lines": 0, "member_census": census, "excluded_members": [], "crosswalk_sha256": _sha(_canonical(records)), "crosswalk": records}
    provenance = {"contract": "ocd-lib015-provenance-v1", "ticket": "LIB-015", "work_id": work_id, "title": spec.title, "creator": spec.creator, "volume": spec.volume, "source_format": "retained UTF-8 LF-terminated OCR text", "source_logical_path": f"raw/gutenberg/{spec.filename}", "source_sha256": spec.sha256, "candidate_status": "nonaccepted", "publication_authorized": False, "technical_validation_is_human_acceptance": False, "rights": {"edition": "unresolved", "worldwide": "unresolved", "publication": "not authorized"}}
    unresolved = [
        {"id": f"{work_id}-identity-edition", "kind": "identity-edition", "status": "human-review-required", "scope": "whole retained witness", "detail": "Title, creator, volume, edition, and witness identity remain unaccepted."},
        {"id": f"{work_id}-ocr-readings", "kind": "ocr-reading", "status": "human-review-required", "scope": f"all {spec.line_count} retained OCR physical lines", "detail": "No OCR correction or substantive reading was silently accepted."},
        {"id": f"{work_id}-rights", "kind": "rights", "status": "human-review-required", "scope": "retained witness and candidate", "detail": "Rights and publication permission remain unresolved."},
        {"id": f"{work_id}-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance or publication authorization."},
    ]
    return {"content.tei.xml": _tei(work_id, witness, profile), "source-accountability.json": _canonical(accountability), "provenance.json": _canonical(provenance), "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved), "README.source.md": source_manifest.authority_path("source-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(source_manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(source_manifest, destination, _convert)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--witness", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    manifest = load_source_manifest(args.manifest, repository_root=args.repository_root, witness_path=args.witness)
    candidate = build_candidate(manifest, args.output)
    print(json.dumps({"candidate_sha256": candidate.sha256, "status": candidate.manifest["status"], "work_id": manifest.record["work_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
