"""Stage two exact Creeds.json electronic witnesses for guarded review.

The initial acceptance derivation is reused unchanged. This module adds the
source-evidenced doctrinal declaration to the *stage*, then checks native rows.
It never changes the canonical work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from lxml import etree

from build.tools import stage_creeds_json_acceptance as initial
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.creeds_json_carrier import PROFILE
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.tei.acceptance import validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = initial.ROOT
CONTRACT = "ocd-creeds-json-next-electronic-stage-v1"
ROUTES = {
    "abstract-of-principles": {
        "manifest": "sources/doctrinal-documents/lib063-creeds-json/abstract-of-principles/abstract-of-principles.source-manifest.json",
        "candidate": "37c-003-abstract-of-principles-20260920-v2",
        "package_sha256": "1d6eb939b88cff0dd29f260944abd4376c8f95d60e0af0847122735f622e118b",
        "validation_sha256": "3eb3bc9dcaad5319092e855b76a822de143fa8ae4b3d580515141b696cee50c8",
        "review": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-003.md",
        "review_sha256": "383d6693a919f4f4fecc30a7f72349000758f9dd3f559aeb243c36e8ebeef676",
        "visual_loci": ["historical /Metadata", "historical /Data/0 Article 1", "historical /Data/10 Article 11", "historical /Data/19 Article 20"],
        "unreviewed": ["current-package CVW visual capture and full-document visual collation; historical four-locus source/content bytes match"],
        "source_sha256": "3fcb6447826ccbbf3b8b2c23bacc769f6ad0df8b5449f2a0c7925623afed242c",
        "historical_visual_content_sha256": "0d4cf1e3b8dcf9cf5b5c40ad97c57dfc334060edcdc1118272aaecd8792bdcd4",
        "format": "Canon", "kind": "canon", "original_language": "English",
        "body_clause": "The Scriptures of the Old and New Testaments were given by inspiration of God",
        "row_count": 20,
    },
    "apostles-creed": {
        "manifest": "sources/doctrinal-documents/lib063-creeds-json/apostles-creed/apostles-creed.source-manifest.json",
        "candidate": "37c-005-apostles-creed-20260920-v2",
        "package_sha256": "31c44761bd3de1cd503eabf03a25acc6ee0e25fac5ae9c3ff7c913d5e6d064ff",
        "validation_sha256": "23a05956ba6b9b28b3ab97ab78aacf6d57ea0e47d5521a260fb663b38412f7d9",
        "review": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-005.md",
        "review_sha256": "a957bbf54bc4d334ef793c39fd5d9267a2ceb6d3d23ab4e7f3e50380379944b1",
        "visual_loci": ["historical /Metadata", "historical /Metadata/Title", "historical /Data", "historical /Data/Content"],
        "unreviewed": ["current-package CVW visual capture and independent print-witness collation; historical four-locus source/content bytes match"],
        "source_sha256": "a715f169670133b2eb31e93408fe294d60886c51a9e39351a8be2caac5670ee9",
        "historical_visual_content_sha256": "86ee43f0b4f31867ae81b366d8a299ea0310afab2618dbabb27c47ca898e563b",
        "format": "Creed", "kind": "creed", "original_language": "Latin",
        "body_clause": "I believe in God, the Father almighty, creator of heaven and earth.",
        "row_count": 1,
    },
}


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(path: Path, value: object) -> None:
    target = _io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def prepare(work_id: str, *, stage: Path, library: Path) -> dict[str, object]:
    if work_id not in ROUTES:
        raise PipelineError(f"work is outside the individually declared tranche: {work_id}")
    route = ROUTES[work_id]
    if work_id in initial.ROUTES:
        raise PipelineError("tranche route overlaps an existing acceptance route")
    initial.ROUTES[work_id] = route
    try:
        first = initial.prepare(work_id, stage=stage, library=library)
    finally:
        del initial.ROUTES[work_id]
    stage = stage.absolute()
    work = Path("library/works") / work_id
    edition = work / "forms" / f"{work_id}-retained-electronic" / "editions" / f"{work_id}-creeds-json"
    acceptance = edition / "acceptance.json"
    master = edition / "master.tei.xml"
    accounting = work / "integration/creeds-json-electronic-v1/source-accounting.json"
    historical_content = work / "integration/creeds-json-electronic-v1/inputs/package/content.tei.xml"
    evidence = work / "integration/creeds-json-metadata-rebind-v1/metadata-evidence.json"
    source_path = Path("raw/Creeds.json/creeds") / (work_id.replace("-", "_") + ".json")
    source = _read(stage / source_path)
    if _sha(stage / historical_content) != route["historical_visual_content_sha256"]:
        raise PipelineError("current candidate content differs from historical visual pair")
    metadata = source.get("Metadata")
    if not isinstance(metadata, dict) or metadata.get("CreedFormat") != route["format"] or metadata.get("OriginalLanguage") != route["original_language"]:
        raise PipelineError("retained document classification differs")
    data = source.get("Data")
    if work_id == "abstract-of-principles":
        if not isinstance(data, list) or len(data) != 20 or any(not isinstance(item, dict) for item in data):
            raise PipelineError("Abstract article envelope differs")
        content = data[0].get("Content")
        pointer = "/Data/0/Content"
    else:
        if not isinstance(data, dict):
            raise PipelineError("Apostles content envelope differs")
        content = data.get("Content")
        pointer = "/Data/Content"
    if not isinstance(content, str) or route["body_clause"] not in content or _sha(stage / source_path) != route["source_sha256"]:
        raise PipelineError("retained English content or source hash differs")
    tree = etree.parse(str(_io_path(stage / master)), etree.XMLParser(resolve_entities=False, no_network=True))
    if tree.getroot().get("{http://www.w3.org/XML/1998/namespace}lang") != "en":
        raise PipelineError("staged TEI has no English representation language")
    current_work = _read(ROOT / work / "work.json")
    updated_work = _read(stage / work / "work.json")
    forms = updated_work.get("textual_forms")
    if not isinstance(forms, list) or len(forms) != 1 or len(forms[0].get("editions", [])) != 1:
        raise PipelineError("work has an unexpected edition envelope")
    selected = forms[0]["editions"][0]
    if selected.get("edition_id") != f"{work_id}-creeds-json" or "category" in selected or "language" in selected:
        raise PipelineError("edition identity or classification precondition differs")
    selected.update(category="doctrinal-documents", language="en")
    validate_identity_update(current_work, updated_work)
    _write(stage / work / "work.json", updated_work)
    load_work(_io_path(stage / work / "work.json"))
    metadata_evidence = {
        "contract": "ocd-creeds-json-source-metadata-evidence-v1", "work_id": work_id,
        "source_path": source_path.as_posix(), "source_sha256": route["source_sha256"],
        "source_bytes": _io_path(stage / source_path).stat().st_size,
        "category": "doctrinal-documents", "language": "en", "document_kind": route["kind"],
        "kind_basis": {"json_pointer": "/Metadata/CreedFormat", "source_value": route["format"]},
        "language_basis": {"json_pointer": pointer, "body_clause": route["body_clause"],
                           "accepted_tei_root_xml_lang": "en", "original_language_metadata": route["original_language"],
                           "original_language_is_not_this_electronic_text_language": True},
    }
    _write(stage / evidence, metadata_evidence)
    account = _read(stage / accounting)
    if "document_kind" in account or "projection_profile" in account:
        raise PipelineError("source accounting already has a projection declaration")
    account.update(document_kind=route["kind"], projection_profile=PROFILE,
                   metadata_evidence={"path": evidence.as_posix(), "bytes": _io_path(stage / evidence).stat().st_size,
                                      "sha256": _sha(stage / evidence)})
    _write(stage / accounting, account)
    accepted = _read(stage / acceptance)
    accepted["source"]["accounting"].update(bytes=_io_path(stage / accounting).stat().st_size,
                                              sha256=_sha(stage / accounting))
    write_acceptance(_io_path(stage / acceptance), accepted)
    validate_acceptance(_io_path(stage / acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    projected = project_accepted_doctrinal_documents(_io_path(stage), acceptance_path=_io_path(stage / acceptance))
    errors = verify_accepted_doctrinal_documents(_io_path(stage), acceptance_path=_io_path(stage / acceptance),
                                                 rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != route["row_count"] or projected["receipt"].get("unsupported"):
        raise PipelineError(f"native doctrinal projection differs: {errors[:3]}")
    after = _files(stage / work)
    provider_readme = _io_path(stage / "raw/Creeds.json/README.md").read_text(encoding="utf-8")
    section = provider_readme.split("## Copyrights\n", 1)
    if len(section) != 2 or "\n## " not in section[1]:
        raise PipelineError("provider README copyright section is missing")
    listed_exceptions = sorted(set(re.findall(r"\(creeds/([^)/]+\.json)\)", section[1].split("\n## ", 1)[0])))
    if len(listed_exceptions) != 8 or source_path.name in listed_exceptions:
        raise PipelineError("retained member is a named provider copyright exception or exception list changed")
    rights = {
        "provider_readme": "raw/Creeds.json/README.md",
        "provider_readme_sha256": _sha(stage / "raw/Creeds.json/README.md"),
        "copyright_section_exception_members": listed_exceptions,
        "listed_copyright_exception": False,
        "member_source_attribution": metadata.get("SourceAttribution"),
        "residuals": ["Provider exception list and member attribution are source assertions, not rights clearance.",
                      "Print lineage, translation provenance, and publication review remain open."],
    }
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": work_id,
        "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
        "before": first["before"], "after": after,
        "changed_paths": sorted(path for path in set(first["before"]) | set(after) if first["before"].get(path) != after.get(path)),
        "source_sha256": route["source_sha256"], "candidate_sha256": route["package_sha256"],
        "validation_sha256": route["validation_sha256"], "review_sha256": route["review_sha256"],
        "first_stage_receipt_sha256": _sha(stage / "stage-receipt.json"),
        "acceptance_sha256": _sha(stage / acceptance), "master_sha256": _sha(stage / master),
        "projection_profile": PROFILE, "projection_rows": len(projected["rows"]),
        "projection_independent_verifier_errors": errors, "provider_rights": rights,
        "historical_visual_transfer": {
            "entry_review_sha256": route["review_sha256"],
            "retained_source_sha256": route["source_sha256"],
            "candidate_content_sha256": route["historical_visual_content_sha256"],
            "scope": route["visual_loci"],
            "limit": "Historical four-locus captures bind byte-identical source and TEI content; no new current-package CVW capture was performed.",
        },
        "limits": ["exact retained electronic witness", "bounded visual evidence", "human, print, rights, and publication separate"],
    }
    _write(stage / "final-stage-receipt.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, choices=sorted(ROUTES))
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--candidate-library", type=Path, default=Path("D:/Library/Open Christian Data/candidate-reviews"))
    args = parser.parse_args()
    result = prepare(args.work, stage=args.stage, library=args.candidate_library)
    print(json.dumps({key: result[key] for key in ("work_id", "status", "stage_root", "projection_rows", "changed_paths")}, sort_keys=True))


if __name__ == "__main__":
    main()
