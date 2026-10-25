"""Stage Westminster's source-nested confession with exact proofs for review.

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
from ocd_kernel.projection.categories.creeds_json_westminster_proofs import shape
from ocd_kernel.projection.categories.creeds_json_carrier import PROFILE
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.tei.acceptance import validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = initial.ROOT
CONTRACT = "ocd-creeds-json-westminster-proofs-stage-v1"
ROUTES = json.loads((ROOT / "build/tools/creeds_json_westminster_proofs_route.json").read_text(encoding="utf-8"))


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
    source_path = Path(route["source_path"])
    source = _read(stage / source_path)
    if _sha(stage / historical_content) != route["candidate_content_sha256"]:
        raise PipelineError("current candidate content differs from declared source-bound package")
    metadata = source.get("Metadata")
    if not isinstance(metadata, dict) or metadata.get("CreedFormat") != route["format"] or metadata.get("OriginalLanguage") != route["original_language"]:
        raise PipelineError("retained document classification differs")
    data = source.get("Data")
    shape(work_id, source)
    if not isinstance(data, list) or len(data) != route["chapter_count"]:
        raise PipelineError("Confession chapter envelope differs")
    content = data[0]["Sections"][0]["Content"]
    pointer = "/Data/0/Sections/0/Content"
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
    source_units = [
        (chapter_index, section_index, chapter, section)
        for chapter_index, chapter in enumerate(data)
        for section_index, section in enumerate(chapter["Sections"])
    ]
    if any(
        row["number"] != section["Section"]
        or row["locator"]["divisions"][0]["number"] != chapter["Chapter"]
        or row["locator"]["unit_path"] != ["Data", str(chapter_index), "Sections", str(section_index)]
        or row["content_with_proofs"] != section["ContentWithProofs"]
        or [proof["id"] for proof in row["proofs"]] != [proof["Id"] for proof in section["Proofs"]]
        for row, (chapter_index, section_index, chapter, section) in zip(projected["rows"], source_units, strict=True)
    ):
        raise PipelineError("native doctrinal rows lost Westminster hierarchy or proofs")
    if (sum(len(row["proofs"]) for row in projected["rows"]) != route["proof_count"]
            or sum(len(proof["references"]) for row in projected["rows"] for proof in row["proofs"]) != route["reference_count"]):
        raise PipelineError("native doctrinal rows lost Westminster proof/reference census")
    after = _files(stage / work)
    provider_readme = _io_path(stage / "raw/Creeds.json/README.md").read_text(encoding="utf-8")
    section = provider_readme.split("## Copyrights\n", 1)
    if len(section) != 2 or "\n## " not in section[1]:
        raise PipelineError("provider README copyright section is missing")
    listed_exceptions = sorted(set(re.findall(r"\(creeds/([^)/]+\.json)\)", section[1].split("\n## ", 1)[0])))
    if len(listed_exceptions) != 8:
        raise PipelineError("provider exception list changed")
    rights = {
        "provider_readme": "raw/Creeds.json/README.md",
        "provider_readme_sha256": _sha(stage / "raw/Creeds.json/README.md"),
        "copyright_section_exception_members": listed_exceptions,
        "listed_copyright_exception": source_path.name in listed_exceptions,
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
        "bounded_source_tei_review": {
            "entry_review_sha256": route["review_sha256"],
            "retained_source_sha256": route["source_sha256"],
            "candidate_content_sha256": route["candidate_content_sha256"],
            "scope": route["visual_loci"],
            "limit": "Current technical source/TEI opening and closing loci are bound; consult the entry review for any historical CVW credit. No new CVW capture or full visual collation was performed.",
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
