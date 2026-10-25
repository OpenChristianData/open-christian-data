"""Build the sealed review package for the structured Maclaren cohort v3."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.tei.maclaren_expositions_structured_oracle_v3 import _oracle
from build.tei.maclaren_expositions_structured_v3 import MAP, MAP_SHA, render
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct, validate


CONVERTER_ID = "ocd-lib073-maclaren-expositions-structured-cohort-v3"
CONVERTER_VERSION = "3"
MANIFEST = ROOT / "sources/sermons/maclaren-expositions/full-cohort-v3/source-manifest.json"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _thaw(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    root = source_manifest.repository_root
    map_data = (root / MAP).read_bytes()
    if _sha(map_data) != MAP_SHA:
        raise ValueError("Maclaren structured v3 map changed")
    mapping = json.loads(map_data)
    content = render(root)
    members = [
        {
            key: item[key]
            for key in ("pg_id", "path", "bytes", "sha256", "physical_line_count")
        }
        for item in mapping["members"]
    ]
    accountability = {
        "contract": "ocd-maclaren-expositions-source-accountability-v3",
        "work_id": "maclaren-expositions",
        "edition_id": "maclaren-expositions-pg-fifteen-volume-cohort",
        "source_manifest_sha256": source_manifest.sha256,
        "source_map_sha256": MAP_SHA,
        "source_members": members,
        "source_member_count": 15,
        "source_part_count": 26,
        "physical_line_count": 339526,
        "represented_line_count": 339526,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "mapped_marker_count": 1444,
        "exposition_head_count": 1386,
        "book_section_head_count": 43,
        "internal_subsection_count": 14,
        "verse_column_label_count": 1,
        "nonexact_toc_title_cases_with_adjacent_epigraphs": 28,
        "candidate_tei_sha256": _sha(content),
    }
    provenance = {
        "contract": "ocd-maclaren-expositions-candidate-provenance-v3",
        "status": "nonaccepted",
        "work_id": "maclaren-expositions",
        "ticket_id": "LIB-073",
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_map_sha256": MAP_SHA,
        "candidate_tei_sha256": _sha(content),
        "scope": {
            "member_count": 15,
            "source_part_count": 26,
            "physical_line_count": 339526,
            "mapped_marker_count": 1444,
        },
        "identity_status": {
            "work": "one catalog work and one TEI",
            "electronic_member_order": "established",
            "certain_print_edition_lineage": "unresolved",
        },
        "visual_review_status": "required-for-this-exact-package",
        "acceptance_status": "not-accepted",
        "rights_status": "not-cleared",
        "release_status": "not-selected",
        "publication_status": "not-authorized",
    }
    unresolved = [
        {
            "id": "maclaren-v3-certain-print-lineage",
            "kind": "edition-lineage",
            "status": "unresolved",
            "detail": "The exact electronic member order and structure are established; a single uniform print-edition lineage is not.",
        },
        {
            "id": "maclaren-v3-visual-review",
            "kind": "visual-review",
            "status": "unresolved",
            "detail": "The exact v3 package requires affected structural loci to be viewed before technical acceptance is reconsidered.",
        },
        {
            "id": "maclaren-v3-rights-and-publication",
            "kind": "rights-and-publication",
            "status": "unresolved",
            "detail": "Validation does not establish rights clearance, public selection, or publication authorization.",
        },
    ]
    readme = (root / "sources/sermons/maclaren-expositions/full-cohort-v3/README.source.md").read_bytes()
    return {
        "content.tei.xml": content,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build(destination: Path) -> dict[str, object]:
    destination = destination.resolve(strict=False)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError(f"candidate destination must be absent or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = reconstruct(source, destination / "package", _convert)
    report = validate(source, package, _oracle)
    record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": _thaw(report.attestation),
        "findings": list(report.findings),
        "report_sha256": report.sha256,
    }
    validation = destination / "validation.json"
    validation.write_bytes(_canonical(record))
    return {
        "candidate_root": destination.as_posix(),
        "package_sha256": package.sha256,
        "tei_sha256": _sha(package.member_bytes("content.tei.xml")),
        "validation_sha256": _sha(validation.read_bytes()),
        "report_sha256": report.sha256,
        "status": report.status,
        "findings": list(report.findings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.destination), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
