"""Prepare a frozen, external Bay Psalm Book technical acceptance generation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.bay_psalm_book_1640_oracle import _oracle
from build.tools.reconstruct_candidate import run as reconstruct_candidate
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
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


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "bay-psalm-book-1640"
FORM_ID = "bay-psalm-book-1640-tcp-retained"
EDITION_ID = "bay-psalm-book-1640-tcp-electronic"
ACQUISITION_ID = "bay-psalm-book-1640-tcp-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/tcp/high-range/N00001/N00001.xml")
MANIFEST = (
    Path("sources/structured-text/bay-psalm-book-1640")
    / "bay-psalm-book-1640.source-manifest.json"
)
EVIDENCE = WORK / "integration/bay-psalm-n00001-electronic-acceptance-v1"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": FORM_ID,
    "edition_id": EDITION_ID,
    "acquisition_id": ACQUISITION_ID,
}
CONTRACT = "ocd-bay-psalm-n00001-electronic-stage-v2"
SOURCE_SHA256 = "3016f74bcce71ffa67f7b87e55db64ffcd54a28ad29899251582d2e784a6df7e"
SOURCE_MANIFEST_SHA256 = "b95d74621ebd6c0fc97dd8e41b083f48fc034f1e6fcea687323444a9df241e99"
CANDIDATE_PACKAGE_SHA256 = "e39705b774bc4be5a1e9843a426bd64c7e5626cb7a53a5af3f2f2487d3a84ad5"
VALIDATION_REPORT_SHA256 = "29ed7042c22534d29e3240aba364a1191232712bc47015bbe3aa60525cd2fa6d"
VALIDATION_SIDECAR_SHA256 = "f32d56c87857c98a3b3f4c14e32dd014b34798bbe6e40e22f08b77ffca643aa0"
BEFORE = {
    "SOURCE_NOTICE.md": "b555a9f57145326096f1998c7c31c9417da7368aff4947bc85f7d1b3a5a4a784",
    "state.json": "8c1678a9583f6d7fedb86948af826bf558e5c2e3d57cb27bdd8e5a8be5ba76b0",
    "work.json": "eeb325dce77719b2bededf85ef44d2f4182a4d54e2db8e4327759a911c336fef",
    (
        "forms/bay-psalm-book-1640-tcp-retained/editions/"
        "bay-psalm-book-1640-tcp-electronic/acquisitions/"
        "bay-psalm-book-1640-tcp-acquired.json"
    ): "073a82aa1ab124fcc7185b5f19f044095b66dc1d5b5095829b3a9a4895f16043",
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Bay Psalm Book source or stage input drifted: {path}")
    return content


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"Bay Psalm Book JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    content = (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return _put(stage, relative, content)


def _copy(stage: Path, relative: Path) -> None:
    source = _io_path(ROOT / relative)
    target = _io_path(stage / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    resolved_root = ROOT.resolve(strict=True)
    resolved_stage = stage.resolve(strict=False)
    if (
        _io_path(stage).exists()
        or not _io_path(stage.parent).is_dir()
        or resolved_stage == resolved_root
        or resolved_root in resolved_stage.parents
    ):
        raise ValueError("Bay Psalm Book stage must be a fresh external directory")
    original = _read(ROOT / SOURCE, SOURCE_SHA256)
    if len(original) != 938122 or _files(ROOT / WORK) != BEFORE:
        raise ValueError("Bay Psalm Book retained source or complete work preimage differs")
    acquisition = _json(ROOT / ACQUISITION)
    retained = acquisition.get("retained_files", [])
    if (
        acquisition.get("source_path") != SOURCE.as_posix()
        or acquisition.get("source_sha256") != SOURCE_SHA256
        or acquisition.get("source_bytes") != len(original)
        or len(retained) != 1
        or retained[0].get("path") != SOURCE.as_posix()
        or retained[0].get("sha256") != SOURCE_SHA256
        or retained[0].get("scope") != acquisition.get("source_scope")
    ):
        raise ValueError("Bay Psalm Book acquisition is not the complete retained XML member")

    before_work = _json(ROOT / WORK / "work.json")
    before_state = _json(ROOT / WORK / "state.json")
    form = before_work.get("textual_forms", [])[0]
    edition = form.get("editions", [])[0]
    if (
        len(before_work.get("textual_forms", [])) != 1
        or len(form.get("editions", [])) != 1
        or edition.get("edition_id") != EDITION_ID
        or _io_path(ROOT / EDITION / "acceptance.json").exists()
        or _io_path(ROOT / EDITION / "master.tei.xml").exists()
    ):
        raise ValueError("Bay Psalm Book work or edition boundary differs")
    targets = [
        item
        for item in before_state.get("targets", [])
        if item.get("target_type") == "edition" and item.get("target_id") == EDITION_ID
    ]
    if len(targets) != 1 or targets[0].get("stage") != "review":
        raise ValueError("Bay Psalm Book edition is not uniquely in review")

    for relative, checksum in BEFORE.items():
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, checksum))
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    if manifest.sha256 != SOURCE_MANIFEST_SHA256:
        raise ValueError("Bay Psalm Book source manifest digest differs")
    dependencies = {SOURCE, MANIFEST}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    dependencies.update(
        Path(manifest.record[name]["implementation_path"])
        for name in ("converter", "validator")
    )
    inherited = set(before_work.get("evidence", [])) | {
        evidence
        for target in before_state.get("targets", [])
        for evidence in target.get("evidence", [])
    }
    for reference in inherited:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Bay Psalm Book evidence: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _copy(stage, relative)

    # Keep this runner-owned path short enough for Windows staging members.
    candidate_root = stage / "_c"
    _io_path(candidate_root.parent).mkdir(parents=True, exist_ok=True)
    summary = reconstruct_candidate(
        manifest=MANIFEST.as_posix(),
        destination=str(candidate_root),
        repository_root=str(ROOT),
    )
    package = CandidatePackage.load(candidate_root / "package")
    report = validate(manifest, package, _oracle)
    if (
        summary.get("status") != "pass"
        or package.sha256 != CANDIDATE_PACKAGE_SHA256
        or report.sha256 != VALIDATION_REPORT_SHA256
        or _sha(candidate_root / "validation.json") != VALIDATION_SIDECAR_SHA256
        or report.findings
        or package.member_bytes("content.tei.xml") != original
    ):
        raise ValueError("Bay Psalm Book maintained candidate or validation closure differs")

    staged_work = _json(stage / WORK / "work.json")
    staged_form = staged_work["textual_forms"][0]
    staged_edition = staged_form["editions"][0]
    if staged_form.get("language") is not None or any(
        staged_edition.get(name) is not None for name in ("language", "category")
    ):
        raise ValueError("Bay Psalm Book language or category preimage differs")
    staged_form["language"] = "en"
    staged_edition["language"] = "en"
    staged_edition["category"] = "poetry"
    validate_identity_update(before_work, staged_work)
    _put_json(stage, WORK / "work.json", staged_work)
    load_work(_io_path(stage / WORK / "work.json"))

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = {
        "id": "bay-psalm-n00001-electronic-agent-v1",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "note": (
            "Bind the complete retained TCP N00001 electronic witness; "
            "source front, body, back, gaps, page markers, and text remain unchanged."
        ),
    }
    source_binding = {
        "source_path": SOURCE.as_posix(),
        "source_bytes": len(original),
        "source_sha256": SOURCE_SHA256,
        "source_scope": acquisition["source_scope"],
    }
    bound = bind_reviewed_header(
        original,
        expected_sha256=SOURCE_SHA256,
        identity=IDENTITY,
        source=source_binding,
        source_url=acquisition["url"],
        declared_scope=acquisition["source_scope"],
        revision=revision,
    )
    if bound.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Bay Psalm Book reviewed header changed retained text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Bay Psalm Book accepted TEI P5 errors: {errors[:3]}")

    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [
        {
            "path": SOURCE.as_posix(),
            "position": 1,
            "bytes": len(original),
            "sha256": SOURCE_SHA256,
            "scope": acquisition["source_scope"],
        }
    ]
    scope = {
        "kind": "edition",
        "declared": acquisition["source_scope"],
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
    }
    common = {
        "identity": IDENTITY,
        "source": source_binding,
        "candidate": make_file_binding(stage, candidate),
        "scope": acquisition["source_scope"],
        "accepted_scope": {"kind": "edition", "declared": acquisition["source_scope"]},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
    }
    accounting = _put_json(
        stage,
        EVIDENCE / "source-accounting.json",
        common
        | {
            "source_sha256": SOURCE_SHA256,
            "source_bytes": len(original),
            "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
            "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
            "validation_report_sha256": VALIDATION_REPORT_SHA256,
            "source_element_count": 16488,
            "source_gap_count": 1032,
            "source_page_break_count": 294,
            "source_line_count": 8043,
            "basis": (
                "Complete retained XML and maintained candidate are byte-identical; "
                "the independent whole-member oracle and TEI P5 validation pass."
            ),
        },
    )
    command = (
        "py -3 -m build.tools.stage_bay_psalm_book_1640_acceptance "
        "--stage <fresh-external-root>"
    )
    technical = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": [
            "Producer and oracle both parse the same retained TEI with lxml; exact source/candidate byte equality separately establishes whole-member conservation."
        ],
        "independent_corroboration": (
            "Exact source/candidate bytes, independent complete census and feature checks, "
            "TEI P5 XSD, mutation rejection, two fresh maintained-runner reproductions, "
            "and actual-master source-fidelity checks. Public poetry projection was "
            "attempted separately and is recorded as a Step 3 hold."
        ),
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        evidence_path = _put_json(
            stage,
            EVIDENCE / f"{name}.json",
            common
            | {
                "status": "pass",
                "command": command,
                "exit_code": 0,
                "claim": name,
                "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
                "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
                "validation_report_sha256": VALIDATION_REPORT_SHA256,
                "validation_sidecar_sha256": VALIDATION_SIDECAR_SHA256,
                "original_source_bytes_unchanged": True,
            },
        )
        technical[name] = {
            "path": evidence_path,
            "status": "pass",
            "command": command,
            "exit_code": 0,
        }
    review = {
        "reviewer": "agent:bay-psalm-n00001-technical-stage",
        "reviewed_at": now,
        "coverage": {
            "status": "partial",
            "declared": acquisition["source_scope"],
            "reached": [
                f"{SOURCE.as_posix()}#full-byte-source",
                "front/title-page-and-preface",
                "body/five-books-and-150-psalms",
                "back/admonition-and-errata",
                "complete source/candidate byte equality",
                "whole XML census and source-feature profile",
                "all 1032 gaps and 294 page-marker sequence identities",
            ],
            "inspected": [
                "complete source/candidate byte equality",
                "whole XML census and source-feature profile",
                "all 1032 gaps and 294 page-marker sequence identities",
            ],
            "unreviewed": [
                f"{SOURCE.as_posix()}#print-image-collation",
                "current whole-work CVW pixel comparison",
            ],
        },
        "source_quality_uncertainty": [
            "The TCP Phase I keyboarded text was not collated here with its Readex page images; source-coded gaps remain intentional witness features."
        ],
        "discrepancies": [],
        "unreviewed_residuals": [
            "Human visual review, rights assessment, and publication decision are not recorded."
        ],
    }
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review)
    decision = {
        "source_local_disposition": (
            "Proposed agent acceptance of the exact complete TCP N00001 electronic witness only; "
            "canonical promotion is pending coordinator review of this frozen stage."
        ),
        "blockers": [],
        "human_decision": {"status": "not-recorded"},
        "agent_assessment": {
            "status": "accepted",
            "actor": review["reviewer"],
            "assessed_at": now,
            "supported_scope": acquisition["source_scope"],
            "unresolved_claims": [],
            "unassessed_stronger_claims": [
                "print-image collation",
                "CVW visual review",
                "human review",
                "rights clearance",
                "publication",
                "successful public poetry projection",
            ],
        },
    }
    acceptance_path = stage / EDITION / "acceptance.json"
    acceptance = build_acceptance_record(
        stage,
        identity=IDENTITY,
        candidate_path=candidate,
        source_accounting_path=accounting,
        scope=scope,
        technical=technical,
        review=review | {"report_path": review_path},
        representation_revision=revision,
        decision=decision,
    )
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master_path = _put(stage, EDITION / "master.tei.xml", bound)
    acceptance["promotion"].update(
        status="promoted",
        promoted_at=now,
        master=make_file_binding(stage, master_path),
    )
    write_acceptance(_io_path(acceptance_path), acceptance)
    _put(stage, EDITION / "README.source.md", _read(ROOT / WORK / "SOURCE_NOTICE.md"))
    staged_state = _json(stage / WORK / "state.json")
    staged_target = next(
        item
        for item in staged_state["targets"]
        if item["target_type"] == "edition" and item["target_id"] == EDITION_ID
    )
    staged_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    staged_target["evidence"].extend(
        [(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()]
    )
    _put_json(stage, WORK / "state.json", staged_state)
    validated = validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projection_error = "unsupported native glyph reference or content"
    try:
        projected = project_accepted_document(
            _io_path(stage), acceptance_path=_io_path(acceptance_path), category="poetry"
        )
    except PipelineError as exc:
        if str(exc) != projection_error:
            raise
        projection_rows = 0
        projection_status = "blocked-shared-projector"
        projection_issue = _put_json(
            stage,
            EVIDENCE / "step-3-projection-hold.json",
            {
                "contract": "ocd-bay-psalm-n00001-projection-hold-v1",
                "status": "blocked",
                "step": 3,
                "category": "poetry",
                "error_type": "PipelineError",
                "error": projection_error,
                "source_glyph_references": {
                    "char:EOLhyphen": 52,
                    "char:EOLunhyphen": 6,
                    "char:cmbAbbrStroke": 31,
                    "char:punc": 114,
                },
                "scope": (
                    "Public poetry projection only. Source accounting, source-faithful "
                    "accepted TEI master, TEI P5 validation, and acceptance authority remain valid."
                ),
                "shared_projection_changed": False,
            },
        )
    else:
        errors = verify_accepted_document(
            _io_path(stage),
            acceptance_path=_io_path(acceptance_path),
            rows=projected["rows"],
            receipt=projected["receipt"],
            category="poetry",
        )
        if errors or not projected["rows"]:
            raise ValueError(
                f"Bay Psalm Book actual-master native poetry projection failed: {errors[:3]}"
            )
        projection_rows = len(projected["rows"])
        projection_status = "independent-check-pass"
        projection_issue = None
    receipt = {
        "contract": CONTRACT,
        "status": "staged-only-pending-review",
        "canonical_root": ROOT.as_posix(),
        "stage_root": stage.as_posix(),
        "work_id": WORK_ID,
        "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA256,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "candidate_package_sha256": CANDIDATE_PACKAGE_SHA256,
        "candidate_tei_sha256": SOURCE_SHA256,
        "validation_report_sha256": VALIDATION_REPORT_SHA256,
        "validation_sidecar_sha256": VALIDATION_SIDECAR_SHA256,
        "before": BEFORE,
        "after": _files(stage / WORK),
        "accepted_master_sha256": validated["promotion"]["master"]["sha256"],
        "acceptance_sha256": _sha(acceptance_path),
        "category": "poetry",
        "language": "en",
        "projection_rows": projection_rows,
        "projection_status": projection_status,
        "projection_issue": (
            None if projection_issue is None else projection_issue.relative_to(stage).as_posix()
        ),
        "projection_error": None if projection_issue is None else projection_error,
        "rights": "unassessed-source-notice-prepared",
        "human_visual_review": "not-recorded",
        "installation": "not-performed",
    }
    _put_json(stage, Path("bay-psalm-book-1640-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(
        json.dumps(
            {
                "status": result["status"],
                "stage_root": result["stage_root"],
                "master_sha256": result["accepted_master_sha256"],
                "projection_rows": result["projection_rows"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
