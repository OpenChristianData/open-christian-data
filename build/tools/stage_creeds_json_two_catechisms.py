"""Stage two complete LIB062 Creeds.json catechism electronic witnesses.

This source-specific stage preserves the existing retained-electronic-witness
identities and LIB062 leaf-accountability contract. It never installs a work.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

from lxml import etree

from build.tools import stage_creeds_json_acceptance as base
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.creeds_json_two_catechisms import shape
from ocd_kernel.projection.categories.creeds_json_two_catechisms_profile import PROFILE, project, verify
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.reconstruction.decision import load_verified_review
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = base.ROOT
CONTRACT = "ocd-creeds-json-two-catechisms-stage-v1"
ROUTES = json.loads((ROOT / "build/tools/creeds_json_two_catechisms_routes.json").read_text(encoding="utf-8"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def prepare(work_id: str, *, stage: Path, library: Path) -> dict[str, object]:
    if work_id not in ROUTES:
        raise PipelineError(f"work is outside the two exact catechism routes: {work_id}")
    route = ROUTES[work_id]
    stage = stage.absolute()
    if _io_path(stage).exists() or ROOT in stage.parents or stage == ROOT or library in stage.parents:
        raise PipelineError("catechism stage must be fresh and outside repository/candidate library")
    if not _io_path(stage.parent).is_dir():
        raise PipelineError("catechism stage parent does not exist")
    candidate_root = library / route["candidate"]
    manifest_path = ROOT / route["manifest"]
    manifest = SourceManifest.load(manifest_path, repository_root=ROOT)
    review = load_verified_review(
        manifest, candidate_path=candidate_root / "package", validation_path=candidate_root / "validation.json",
    )
    if (review.candidate_sha256 != route["package_sha256"]
            or _sha(_io_path(candidate_root / "validation.json").read_bytes()) != route["validation_sha256"]
            or review.validation.status != "pass" or review.validation.findings):
        raise PipelineError("LIB062 candidate or independent oracle differs from pinned pass")
    if _sha(_io_path(ROOT / route["review"]).read_bytes()) != route["review_sha256"]:
        raise PipelineError("entry-local LIB062 review differs")
    work = Path("library/works") / work_id
    form_id = f"{work_id}-retained-electronic"
    edition_id = route["edition_id"]
    acquisition_id = route["acquisition_id"]
    edition = work / "forms" / form_id / "editions" / edition_id
    acquisition_path = edition / "acquisitions" / f"{acquisition_id}.json"
    master = edition / "master.tei.xml"
    acceptance = edition / "acceptance.json"
    evidence = work / "integration/creeds-json-electronic-v1"
    metadata_evidence = work / "integration/creeds-json-metadata-rebind-v1/metadata-evidence.json"
    before = _files(ROOT / work)
    if _io_path(ROOT / master).exists() or _io_path(ROOT / acceptance).exists() or _io_path(ROOT / evidence).exists():
        raise PipelineError("canonical catechism already has an acceptance or integration")
    acquisition = validate_acquisition(_io_path(ROOT / acquisition_path), root=_io_path(ROOT))
    members = acquisition["retained_files"]
    if (len(members) != 1 or members[0]["path"] != route["source_path"]
            or members[0]["sha256"] != route["source_sha256"]):
        raise PipelineError("existing catechism acquisition is not the exact retained member")
    source_path = Path(route["source_path"])
    source_bytes = _io_path(ROOT / source_path).read_bytes()
    if _sha(source_bytes) != route["source_sha256"] or len(source_bytes) != members[0]["bytes"]:
        raise PipelineError("retained catechism bytes differ")
    source = json.loads(source_bytes)
    shape(work_id, source)
    package_accounting = _read(candidate_root / "package/source-accountability.json")
    if (package_accounting.get("contract") != "ocd-lib062-source-accountability-v1"
            or package_accounting.get("work_id") != work_id
            or package_accounting.get("omitted_leaf_count") != 0
            or package_accounting.get("duplicate_leaf_count") != 0
            or package_accounting.get("data_record_count") != route["row_count"]):
        raise PipelineError("LIB062 leaf-level source accounting differs")
    original = review.member_bytes("content.tei.xml")
    if _sha(original) != route["candidate_content_sha256"]:
        raise PipelineError("LIB062 candidate TEI differs")
    _io_path(stage / work).mkdir(parents=True)
    for relative in before:
        target = stage / work / relative
        _io_path(target.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(ROOT / work / relative), _io_path(target))
    dependencies = [source_path, Path(route["manifest"]), Path(route["review"]), Path("raw/Creeds.json/README.md"),
                    Path("metadata/source-evidence/catalog") / f"{work_id}.json"]
    for authority in manifest.record["authorities"]:
        authority_path = Path(authority["path"])
        if authority_path not in dependencies:
            dependencies.append(authority_path)
    for relative in dependencies:
        _write(stage, relative, _io_path(ROOT / relative).read_bytes())
    for name in review.member_names:
        _write(stage, evidence / "inputs/package" / name, review.member_bytes(name))
    _write(stage, evidence / "inputs/package/manifest.json", _io_path(candidate_root / "package/manifest.json").read_bytes())
    _write(stage, evidence / "inputs/validation.json", _io_path(candidate_root / "validation.json").read_bytes())
    identity = {
        "work_id": work_id, "textual_form_id": form_id,
        "edition_id": edition_id, "acquisition_id": acquisition_id,
    }
    source_binding = {
        "source_path": source_path.as_posix(), "source_sha256": route["source_sha256"],
        "source_bytes": len(source_bytes), "source_scope": members[0]["scope"],
    }
    revision = {
        "id": f"{work_id}-creeds-json-electronic-v1",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "note": "Accept the complete exact retained Creeds.json electronic member as this edition's reconstructed text.",
    }
    original_tree = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    historical_description = {
        "pointers": original_tree.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:ptr/@target", namespaces=ns),
        "sha256": original_tree.xpath("./tei:teiHeader//tei:idno[@type='sha256']/text()", namespaces=ns),
    }
    bound = bind_reviewed_header(
        original, expected_sha256=_sha(original), identity=identity, source=source_binding,
        source_url=acquisition["url"], declared_scope=members[0]["scope"],
        revision=revision, historical_source_description=historical_description,
    )
    if bound.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("reviewed header binding changed catechism body")
    candidate = _write(stage, evidence / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise PipelineError(f"header-bound catechism TEI fails XSD: {errors[:3]}")
    current_work = _read(ROOT / work / "work.json")
    updated_work = _read(stage / work / "work.json")
    selected = updated_work["textual_forms"][0]["editions"][0]
    if (selected.get("edition_id") != edition_id or selected.get("language") != "en"
            or "category" in selected):
        raise PipelineError("existing catechism edition identity/classification differs")
    selected["category"] = "catechisms"
    validate_identity_update(current_work, updated_work)
    _json(stage, work / "work.json", updated_work)
    load_work(_io_path(stage / work / "work.json"))
    metadata = source["Metadata"]
    if metadata.get("CreedFormat") != "Catechism" or metadata.get("OriginalLanguage") != "English":
        raise PipelineError("retained catechism metadata classification differs")
    _json(stage, metadata_evidence, {
        "contract": "ocd-creeds-json-source-metadata-evidence-v1", "work_id": work_id,
        "source_path": source_path.as_posix(), "source_sha256": route["source_sha256"],
        "source_bytes": len(source_bytes), "category": "catechisms", "language": "en",
        "document_kind": "catechism", "kind_basis": {"json_pointer": "/Metadata/CreedFormat", "source_value": "Catechism"},
        "language_basis": {"json_pointer": "/Data/0/Question", "body_clause": source["Data"][0]["Question"],
                           "accepted_tei_root_xml_lang": "en", "original_language_metadata": "English"},
    })
    expected = [{"path": source_path.as_posix(), "position": 1}]
    included = [expected[0] | {"bytes": len(source_bytes), "sha256": route["source_sha256"], "scope": members[0]["scope"]}]
    scope = {"kind": "edition", "declared": members[0]["scope"], "expected_members": expected,
             "included_members": included, "excluded_members": []}
    common = {
        "identity": identity, "source": source_binding, "candidate": make_file_binding(stage, candidate),
        "scope": members[0]["scope"], "accepted_scope": {"kind": "edition", "declared": members[0]["scope"]},
        "expected_members": expected, "included_members": included, "excluded_members": [],
        "missing_members": [], "unknown_members": [],
    }
    account = _json(stage, evidence / "source-accounting.json", common | {
        "source_sha256": route["source_sha256"], "source_bytes": len(source_bytes),
        "source_accountability_contract": package_accounting["contract"],
        "package_accountability_sha256": _sha(_io_path(stage / evidence / "inputs/package/source-accountability.json").read_bytes()),
        "represented_leaf_count": package_accounting["represented_leaf_count"],
        "omitted_leaf_count": 0, "duplicate_leaf_count": 0,
        "candidate_package_sha256": review.candidate_sha256,
        "oracle_report_sha256": review.validation.sha256,
        "projection_profile": PROFILE, "document_kind": "catechism",
        "metadata_evidence": make_file_binding(stage, stage / metadata_evidence),
    })
    bindings = {
        "source_manifest": make_file_binding(stage, stage / route["manifest"]),
        "package_manifest": make_file_binding(stage, stage / evidence / "inputs/package/manifest.json"),
        "validation": make_file_binding(stage, stage / evidence / "inputs/validation.json"),
        "entry_review": make_file_binding(stage, stage / route["review"]),
    }
    command = "py -3 -m build.tools.stage_creeds_json_two_catechisms"
    descriptions = {
        "validation": "Exact LIB062 independent source oracle passed for the complete retained member.",
        "accounting": "LIB062 leaf crosswalk represents every source leaf with zero omissions or duplicates.",
        "fidelity": "Source Q&A and proof values retain exact TEI and native row correspondence.",
        "reproducibility": "Entry-local reviewed package and copied TEI body are hash-bound.",
        "schema": "Source-oracle and reviewed-header TEI pass the vendored TEI P5 XSD.",
        "closure": "Retained member, acquisition, manifest, package, validation, and review are hash-bound.",
    }
    technical: dict[str, object] = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": ["Producer and oracle share the work-local retained member and LIB062 structural model."],
        "independent_corroboration": "Source-bound mutation probes and the complete LIB062 leaf crosswalk constrain the exact electronic witness.",
    }
    for name, description in descriptions.items():
        proof = _json(stage, evidence / f"{name}.json", common | {
            "status": "pass", "command": command, "exit_code": 0, "description": description,
            "inputs": bindings, "oracle_report_sha256": review.validation.sha256,
        })
        technical[name] = {"path": _io_path(proof), "status": "pass", "command": command, "exit_code": 0}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    loci = ["retained JSON/Metadata including typed nulls", "candidate TEI/first and final numbered Q&A"]
    residual = ["historical print-witness collation", "human review", "rights clearance", "publication"]
    visual = {
        "reviewer": f"agent:{work_id}-creeds-json-electronic-review", "reviewed_at": now,
        "coverage": {"status": "partial", "declared": members[0]["scope"],
                     "reached": ["retained JSON", "candidate TEI"], "inspected": loci, "unreviewed": residual},
        "source_quality_uncertainty": ["No independent print witness has been collated."],
        "discrepancies": [], "unreviewed_residuals": residual,
    }
    report = _json(stage, evidence / "review.json", common | visual | {
        "inputs": bindings, "visually_compared_loci": loci,
        "unassessed": ["human acceptance", "print lineage", "rights clearance", "publication"],
    })
    decision = {
        "source_local_disposition": "Agent acceptance of this exact retained electronic member only.",
        "blockers": [],
        "agent_assessment": {"status": "accepted", "actor": visual["reviewer"], "assessed_at": now,
                             "supported_scope": members[0]["scope"], "unresolved_claims": [],
                             "unassessed_stronger_claims": residual},
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        _io_path(stage), identity=identity, candidate_path=_io_path(candidate),
        source_accounting_path=_io_path(account), scope=scope, technical=technical,
        review=visual | {"report_path": _io_path(report)},
        representation_revision=revision, decision=decision,
    )
    write_acceptance(_io_path(stage / acceptance), record)
    validate_acceptance(_io_path(stage / acceptance), root=_io_path(stage))
    _write(stage, master, bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, stage / master))
    write_acceptance(_io_path(stage / acceptance), record)
    state = _read(stage / work / "state.json")
    targets = [item for item in state["targets"] if item["target_id"] == edition_id and item["target_type"] == "edition"]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("catechism edition is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master.as_posix(), acceptance.as_posix()])
    _json(stage, work / "state.json", state)
    validate_acceptance(_io_path(stage / acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    projection = project(_io_path(stage), acceptance_path=_io_path(stage / acceptance))
    errors = verify(_io_path(stage), acceptance_path=_io_path(stage / acceptance),
                    rows=projection["rows"], receipt=projection["receipt"])
    if (errors or len(projection["rows"]) != route["row_count"]
            or projection["receipt"]["proof_count"] != route["proof_count"]
            or projection["receipt"]["reference_count"] != route["reference_count"]):
        raise PipelineError(f"native LIB062 catechism projection differs: {errors[:3]}")
    after = _files(stage / work)
    provider_readme = _io_path(stage / "raw/Creeds.json/README.md").read_text(encoding="utf-8")
    section = provider_readme.split("## Copyrights\n", 1)
    if len(section) != 2 or "\n## " not in section[1]:
        raise PipelineError("provider README copyright section is missing")
    exceptions = sorted(set(re.findall(r"\(creeds/([^)/]+\.json)\)", section[1].split("\n## ", 1)[0])))
    if len(exceptions) != 8:
        raise PipelineError("provider exception list changed")
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": work_id,
        "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
        "before": before, "after": after,
        "changed_paths": sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path)),
        "source_sha256": route["source_sha256"], "candidate_sha256": route["package_sha256"],
        "validation_sha256": route["validation_sha256"], "review_sha256": route["review_sha256"],
        "acceptance_sha256": _sha(_io_path(stage / acceptance).read_bytes()),
        "master_sha256": _sha(_io_path(stage / master).read_bytes()),
        "projection_profile": PROFILE, "projection_rows": len(projection["rows"]),
        "projection_proofs": projection["receipt"]["proof_count"],
        "projection_references": projection["receipt"]["reference_count"],
        "projection_independent_verifier_errors": errors,
        "provider_rights": {
            "provider_readme": "raw/Creeds.json/README.md", "provider_readme_sha256": _sha(_io_path(stage / "raw/Creeds.json/README.md").read_bytes()),
            "copyright_section_exception_members": exceptions, "listed_copyright_exception": source_path.name in exceptions,
            "member_source_attribution": metadata.get("SourceAttribution"),
            "residuals": ["Provider exception list and member attribution are source assertions, not rights clearance.",
                          "Print lineage, translation provenance, and publication review remain open."],
        },
        "bounded_source_tei_review": {
            "entry_review_sha256": route["review_sha256"], "retained_source_sha256": route["source_sha256"],
            "candidate_content_sha256": route["candidate_content_sha256"], "scope": loci,
            "limit": "Current technical source/TEI loci are bound. No new CVW capture or full historical visual collation was performed.",
        },
        "limits": ["exact retained electronic witness", "bounded visual evidence", "human, print, rights, and publication separate"],
    }
    _json(stage, Path("final-stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, choices=sorted(ROUTES))
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--candidate-library", type=Path, default=Path("D:/Library/Open Christian Data/candidate-reviews/creeds-catechism-preflight-20260926"))
    args = parser.parse_args()
    result = prepare(args.work, stage=args.stage, library=args.candidate_library)
    print(json.dumps({key: result[key] for key in ("work_id", "status", "stage_root", "projection_rows", "changed_paths")}, sort_keys=True))


if __name__ == "__main__":
    main()
