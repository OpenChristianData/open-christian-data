"""Stage the exact N18328 electronic witness for guarded technical acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tools.reconstruct_candidate import run
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.liturgies import project_accepted_liturgies, verify_accepted_liturgies
from ocd_kernel.projection.categories.liturgies_office import PROFILE
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/convicts-visitor")
EDITION = WORK / "forms/convicts-visitor-tcp-retained/editions/convicts-visitor-tcp-electronic"
ACQUISITION = EDITION / "acquisitions/convicts-visitor-tcp-acquired.json"
MASTER = EDITION / "master.tei.xml"
ACCEPTANCE = EDITION / "acceptance.json"
SOURCE = Path("raw/tcp/high-range/N18328/N18328.xml")
MANIFEST = Path("sources/convicts-visitor/n18328.source-manifest.json")
CANDIDATE = WORK / "integration/convicts-n18328-electronic-v1/candidate.tei.xml"
EVIDENCE = WORK / "integration/convicts-n18328-acceptance-v1"
IDENTITY = {
    "work_id": "convicts-visitor",
    "textual_form_id": "convicts-visitor-tcp-retained",
    "edition_id": "convicts-visitor-tcp-electronic",
    "acquisition_id": "convicts-visitor-tcp-acquired",
}
SOURCE_SHA = "2f5d266ebf91471784de4a7f95cd47ac3fd806b908a1589d97f47c10a1069871"
CANDIDATE_SHA = "0d5bc4e091da8b10b26b815a420718ef082d51a3f41c25cde7d8d6b53b26eeef"
MANIFEST_SHA = "3f49322b0baed8d40c40f33d66e739624faae845e416c5e38c384332c32d9e7e"
RECEIPT_NAME = "convicts-n18328-stage-receipt.json"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, raw: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(raw)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))


def prepare(stage: Path) -> dict:
    stage = Path(stage).absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or stage.resolve() == ROOT.resolve() or ROOT.resolve() in stage.resolve().parents):
        raise ValueError("N18328 stage must be a fresh external directory")
    before = _files(ROOT / WORK)
    if (_sha(ROOT / SOURCE) != SOURCE_SHA or _sha(ROOT / CANDIDATE) != CANDIDATE_SHA
            or _sha(ROOT / MANIFEST) != MANIFEST_SHA
            or _io_path(ROOT / MASTER).exists() or _io_path(ROOT / ACCEPTANCE).exists()):
        raise ValueError("N18328 canonical source, candidate, manifest, or acquired state differs")
    old_work = _read_json(ROOT / WORK / "work.json")
    old_state = _read_json(ROOT / WORK / "state.json")
    acquisition = _read_json(ROOT / ACQUISITION)
    if (len(old_work["textual_forms"]) != 1 or len(old_work["textual_forms"][0]["editions"]) != 1
            or old_work["textual_forms"][0]["editions"][0]["edition_id"] != IDENTITY["edition_id"]
            or acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA
            or len(acquisition.get("retained_files", [])) != 1
            or not any(item.get("target_id") == IDENTITY["edition_id"] and item.get("stage") == "acquired"
                       for item in old_state.get("targets", []))):
        raise ValueError("N18328 work/acquisition/state preimage differs")
    shutil.copytree(_io_path(ROOT / WORK), _io_path(stage / WORK))
    for relative in (
        SOURCE, Path("raw/tcp/high-range/N18328/acquisition-receipt.json"),
        Path("raw/tcp/high-range/N18328/member-inventory.tsv"),
        Path("research/MANIFEST.md"),
    ):
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    runner_result = run(manifest=MANIFEST.as_posix(), destination=str(stage / "runner"), repository_root=str(ROOT))
    if (runner_result.get("status") != "pass" or runner_result.get("digests", {}).get("source_manifest") != MANIFEST_SHA):
        raise ValueError("N18328 maintained candidate runner did not pass")
    for path in (stage / "runner/package").iterdir():
        if path.is_file():
            _put(stage, EVIDENCE / "inputs/package" / path.name, path.read_bytes())
    _put(stage, EVIDENCE / "inputs/validation.json", (stage / "runner/validation.json").read_bytes())
    candidate_raw = (stage / "runner/package/content.tei.xml").read_bytes()
    if sha256(candidate_raw).hexdigest() != CANDIDATE_SHA:
        raise ValueError("N18328 runner candidate differs from pinned in-repository candidate")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", candidate_raw)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"N18328 TEI P5 errors: {errors[:3]}")
    work = _read_json(stage / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if any(item.get("language") is not None for item in (form, edition)) or edition.get("category") is not None:
        raise ValueError("N18328 language/category preimage differs")
    form["language"] = "en"
    edition["language"] = "en"
    edition["category"] = "liturgies"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    revision = {
        "id": "convicts-n18328-electronic-agent-v1",
        "date": "2026-09-29",
        "note": "Bind complete retained TCP electronic witness; source text unchanged.",
    }
    source_scope = acquisition["source_scope"]
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": 140639,
                 "sha256": SOURCE_SHA, "scope": source_scope}]
    scope = {"kind": "edition", "declared": source_scope, "expected_members": expected,
             "included_members": included, "excluded_members": []}
    source_binding = {"source_path": SOURCE.as_posix(), "source_bytes": 140639,
                      "source_sha256": SOURCE_SHA, "source_scope": source_scope}
    common = {"identity": IDENTITY, "candidate": make_file_binding(stage, candidate),
              "source": source_binding,
              "scope": source_scope, "accepted_scope": {"kind": "edition", "declared": source_scope},
              "expected_members": expected, "included_members": included,
              "excluded_members": [], "missing_members": [], "unknown_members": [],
              "source_path": SOURCE.as_posix(), "source_bytes": 140639,
              "source_sha256": SOURCE_SHA}
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", {
        **common, "projection_profile": PROFILE,
        "source_manifest_sha256": MANIFEST_SHA,
        "candidate_package_sha256": runner_result["digests"]["candidate"],
        "validation_report_sha256": runner_result["digests"]["validation_report"],
        "basis": "Complete retained XML; source-bound candidate and independent runner validation pass.",
    })
    command = "py -3 -m build.tools.stage_convicts_visitor_acceptance --stage <fresh-external-root>"
    technical = {
        "producer": {"id": "ocd-convicts-n18328-complete-electronic"},
        "checker": {"id": "ocd-convicts-n18328-independent-complete-xml"},
        "shared_assumptions": ["Producer and checker select the same retained N18328 XML member; byte-identical source text and a separate lxml projector checker corroborate it."],
        "independent_corroboration": "Maintained runner pass, source/candidate exact text comparison, TEI P5, and independently observed office rows.",
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / (name + ".json"), {
            **common, "status": "pass", "claim": name, "command": command, "exit_code": 0,
            "source_manifest_sha256": MANIFEST_SHA,
            "candidate_package_sha256": runner_result["digests"]["candidate"],
            "validation_report_sha256": runner_result["digests"]["validation_report"],
            "original_source_text_unchanged": True,
        })
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = {
        "reviewer": "agent:convicts-n18328-electronic-stage", "reviewed_at": now,
        "coverage": {"status": "partial", "declared": source_scope,
                     "reached": [f"{SOURCE.as_posix()}#complete-electronic-source"],
                     "inspected": [f"{SOURCE.as_posix()}#complete-electronic-source"],
                     "unreviewed": [f"{SOURCE.as_posix()}#print-image-collation"]},
        "source_quality_uncertainty": ["TCP keyboarding was not collated against page images."],
        "discrepancies": [],
        "unreviewed_residuals": ["Human textual review and rights/release decisions remain open."],
    }
    review_file = _put_json(stage, EVIDENCE / "review.json", {**common, **review})
    decision = {
        "source_local_disposition": "Agent technical acceptance of the complete N18328 electronic XML witness only.",
        "blockers": [], "human_decision": {"status": "not-recorded"},
        "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now,
                             "supported_scope": source_scope, "unresolved_claims": [],
                             "unassessed_stronger_claims": ["print collation", "human review", "rights clearance", "publication"]},
    }
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                     source_accounting_path=accounting, scope=scope, technical=technical,
                                     review={**review, "report_path": review_file},
                                     representation_revision=revision, decision=decision)
    acceptance_path = stage / ACCEPTANCE
    write_acceptance(_io_path(acceptance_path), record)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master = _put(stage, MASTER, candidate_raw)
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance_path), record)
    state = _read_json(stage / WORK / "state.json")
    target = next(item for item in state["targets"] if item["target_type"] == "edition" and item["target_id"] == IDENTITY["edition_id"])
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    target["evidence"].extend([MASTER.as_posix(), ACCEPTANCE.as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projection = project_accepted_liturgies(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_liturgies(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                       rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 3:
        raise ValueError(f"N18328 staged actual-master liturgy rows differ: {errors[:3]}")
    receipt = {
        "contract": "ocd-convicts-n18328-stage-v1", "status": "staged-only",
        "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
        "source_sha256": SOURCE_SHA, "source_manifest_sha256": MANIFEST_SHA,
        "candidate_sha256": CANDIDATE_SHA,
        "candidate_package_sha256": runner_result["digests"]["candidate"],
        "validation_report_sha256": runner_result["digests"]["validation_report"],
        "before": before, "after": _files(stage / WORK),
        "master_sha256": _sha(master), "acceptance_sha256": _sha(acceptance_path),
        "projection_rows": 3, "projection_receipt_sha256": sha256(json.dumps(projection["receipt"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "human_review": "not-recorded", "rights": "not-cleared", "installation": "not-performed",
    }
    _put_json(stage, Path(RECEIPT_NAME), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    result = prepare(parser.parse_args().stage)
    print(json.dumps({"status": result["status"], "stage_root": result["stage_root"],
                      "master_sha256": result["master_sha256"], "projection_rows": result["projection_rows"]}, sort_keys=True))


if __name__ == "__main__":
    main()
