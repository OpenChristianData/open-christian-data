"""Stage one inspected openMGH child work as an electronic-witness acceptance.

Preparation is a fresh, separate work generation.  Applying a receipt swaps
that whole generation with rollback; the default command only checks it.
The per-work declaration is mandatory.  A volume scan cannot accept a work.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from build.tei.openmgh_exclusive_oracle import _oracle
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    validate,
)
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "ocd-openmgh-inspected-complete-generation-v1"
DECLARATION_CONTRACT = "ocd-openmgh-inspected-acceptance-declaration-v1"
EVIDENCE_NAME = "openmgh-inspected-electronic-v1"
PINNED_INSPECTED_BATCHES = {
    Path("plans/2026-09-22-source-preflight/openmgh-bsb752-inspected-batch-20260926.json"):
        "d1c92151e7d938325af05ec01644c7ce626fa81899bba1d87105116726511845",
    Path("plans/2026-09-22-source-preflight/openmgh-bsb752-remaining-six-20260926.json"):
        "18991e43e5767084fc6ff4ab1d56f314bbf1a23fe2a318223e20a1e6c6e14f1c",
    Path("plans/2026-09-22-source-preflight/openmgh-bsb828-inspected-batch-20260926.json"):
        "ba95cedd83c68336bb2b46948af8ba6d3310034269489b6c36886b21708fc478",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


def _relative(value: str, *, prefix: str) -> Path:
    path = Path(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.parts[0] != prefix
    ):
        raise PipelineError(f"invalid {prefix} relative path: {value}")
    return path


def _put(root: Path, relative: Path, data: bytes) -> Path:
    target = root / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(data)
    return target


def _put_json(root: Path, relative: Path, value: object) -> Path:
    return _put(
        root,
        relative,
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode(),
    )


def _copy_tree(source: Path, destination: Path) -> dict[str, str]:
    if _io_path(destination).exists():
        raise PipelineError(f"destination must be fresh: {destination}")
    files = _files(source)
    if not files:
        raise PipelineError(f"empty work generation: {source}")
    _io_path(destination).mkdir(parents=True)
    for relative in files:
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(source / relative), target)
    if _files(destination) != files:
        raise PipelineError("copied work generation differs")
    return files


def _normalize_entry(
    batch: dict[str, object], item: dict[str, object]
) -> dict[str, object]:
    """Unify only the five receipted openMGH candidate batches."""
    if batch.get("contract") not in {
        "ocd-openmgh-exclusive-pilot-v1",
        "ocd-openmgh-bsb830-inspected-batch-v1",
        "ocd-openmgh-bsb00000750-child-batch-v1",
        "ocd-openmgh-bsb752-inspected-batch-v1",
        "ocd-openmgh-bsb752-remaining-six-v1",
        "ocd-openmgh-bsb828-inspected-batch-v1",
    }:
        raise PipelineError("unrecognized inspected openMGH candidate batch")
    status = item.get("acceptance_status", item.get("status"))
    if status not in {"nonaccepted", "validated-nonaccepted"}:
        raise PipelineError("batch entry is not a nonaccepted validated candidate")
    if item.get("validation_status", "pass") != "pass":
        raise PipelineError("batch entry validation failed")
    result = dict(item)
    aliases = {
        "boundary_review_path": ("boundary_review_path", "boundary_path"),
        "boundary_review_sha256": ("boundary_review_sha256", "boundary_sha256"),
        "candidate_sha256": (
            "candidate_sha256",
            "candidate_digest",
            "candidate_manifest_sha256",
        ),
        "work_div_n": ("work_div_n", "source_work_div_n"),
        "work_div_ordinal": ("work_div_ordinal", "source_work_div_ordinal"),
    }
    for target, names in aliases.items():
        values = {item[name] for name in names if name in item}
        if len(values) != 1:
            raise PipelineError(f"candidate batch aliases disagree at {target}")
        result[target] = values.pop()
    result["source_path"] = item.get("source_path", batch.get("source_path"))
    result["source_sha256"] = item.get("source_sha256", batch.get("source_sha256"))
    if not result["source_path"] or not result["source_sha256"]:
        raise PipelineError("batch does not bind extracted source XML")
    return result


@dataclass(frozen=True)
class Route:
    root: Path
    declaration_path: Path
    declaration: dict[str, object]
    batch_path: Path
    batch_entry: dict[str, object]
    work_id: str
    work: Path
    edition_id: str
    form_id: str
    acquisition_id: str
    edition: Path
    acquisition: Path
    source: Path
    archive: Path
    acquisition_receipt: Path
    manifest: Path
    profile: Path
    boundary: Path
    policy: Path
    evidence: Path
    acceptance: Path
    master: Path
    candidate_root: Path
    identity: dict[str, str]
    scope: str
    category: str
    source_sha: str
    source_div_sha: str


def _route(root: Path, declaration_path: Path, batch_path: Path) -> Route:
    root = root.resolve(strict=True)
    declaration_path = _relative(declaration_path.as_posix(), prefix="sources")
    batch_path = _relative(batch_path.as_posix(), prefix="plans")
    declaration = _read(root / declaration_path)
    batch = _read(root / batch_path)
    if batch.get("contract") in {
        "ocd-openmgh-bsb752-inspected-batch-v1",
        "ocd-openmgh-bsb752-remaining-six-v1",
        "ocd-openmgh-bsb828-inspected-batch-v1",
    } and _sha(root / batch_path) != PINNED_INSPECTED_BATCHES.get(batch_path):
        raise PipelineError("inspected batch is not the exact durable receipt")
    if declaration.get("contract") != DECLARATION_CONTRACT:
        raise PipelineError("explicit inspected acceptance declaration is required")
    work_id = declaration.get("work_id")
    if not isinstance(work_id, str) or not work_id or "/" in work_id or "\\" in work_id:
        raise PipelineError("invalid declared work identity")
    if (
        declaration_path
        != Path("sources/openmgh-exclusive") / work_id / "acceptance-declaration.json"
    ):
        raise PipelineError("declaration must be the exact work-local sidecar")
    entries = [e for e in batch.get("works", []) if e.get("work_id") == work_id]
    if len(entries) != 1:
        raise PipelineError("work must occur exactly once in inspected batch")
    entry = _normalize_entry(batch, entries[0])
    work = Path("library/works") / work_id
    acquisition = _relative(str(entry["acquisition_path"]), prefix="library")
    if not acquisition.is_relative_to(work):
        raise PipelineError("acquisition does not belong to declared work")
    edition = acquisition.parent.parent
    edition_id = edition.name
    form_id = edition.parent.parent.name
    acquisition_id = acquisition.stem
    identity = {
        "work_id": work_id,
        "textual_form_id": form_id,
        "edition_id": edition_id,
        "acquisition_id": acquisition_id,
    }
    source = _relative(str(entry["source_path"]), prefix="raw")
    if source.suffix.lower() != ".xml" or str(source).lower().endswith(".zip"):
        raise PipelineError("source must be extracted XML")
    if entry["boundary_review_sha256"] != declaration.get("boundary_review_sha256"):
        raise PipelineError("declared reviewed boundary differs from batch")
    scope = declaration.get("scope")
    category = declaration.get("category")
    if not isinstance(scope, str) or len(scope) < 80:
        raise PipelineError("explicit complete-work accepted scope is required")
    if not isinstance(category, str) or not declaration.get("category_basis"):
        raise PipelineError("category needs an explicit per-work decision and basis")
    if declaration.get("source_div_c14n_sha256") is None:
        raise PipelineError("declaration must bind the selected source div")
    candidate_root = Path(str(entry["candidate_root"]))
    if not candidate_root.is_absolute():
        raise PipelineError("candidate root must be absolute")
    source_accounting = _read(candidate_root / "package/source-accountability.json")
    if (
        source_accounting.get("source_div_c14n_sha256")
        != declaration["source_div_c14n_sha256"]
    ):
        raise PipelineError("declared source div does not match candidate accounting")
    for key in (
        "work_id",
        "work_div_ordinal",
        "work_div_n",
        "start_xml_id",
        "end_xml_id",
    ):
        if source_accounting.get(key) != entry.get(key):
            raise PipelineError(f"candidate source accounting differs at {key}")
    if source_accounting.get("source_path") != source.as_posix():
        raise PipelineError("candidate does not use extracted source XML")
    boundary = _relative(str(entry["boundary_review_path"]), prefix="sources")
    reviewed = _read(root / boundary)
    if _sha(root / boundary) != entry["boundary_review_sha256"]:
        raise PipelineError("inspected boundary bytes changed")
    if (
        reviewed.get("review_status") != "agent-inspected-source-boundary"
        or reviewed.get("scope_assertion") != "whole-work-div"
    ):
        raise PipelineError("work boundary was not individually inspected")
    for key in ("work_id", "work_div_n", "start_xml_id", "end_xml_id"):
        if reviewed.get(key) != entry.get(key):
            raise PipelineError(f"reviewed boundary differs at {key}")
    if (
        "work_div_ordinal" in reviewed
        and reviewed["work_div_ordinal"] != entry["work_div_ordinal"]
    ):
        raise PipelineError("reviewed boundary ordinal differs")
    acquisition_record = _read(root / acquisition)
    retained = acquisition_record.get("retained_files", [])
    if (
        len(retained) != 2
        or retained[0].get("path", "").lower().endswith(".zip") is False
    ):
        raise PipelineError("expected one package archive and one extracted XML member")
    if retained[1].get("path") != source.as_posix():
        raise PipelineError("extracted XML member is missing or out of order")
    archive = _relative(str(retained[0]["path"]), prefix="raw")
    if acquisition_record.get("source_path") != source.as_posix():
        raise PipelineError("ZIP package cannot be source authority")
    acquisition_receipt = source.parent.parent / "acquisition-receipt.json"
    manifest = _relative(str(entry["manifest_path"]), prefix="sources")
    profile = _relative(str(entry["profile_path"]), prefix="sources")
    policy = Path("sources/openmgh-exclusive/validation-policy.json")
    evidence = work / "integration" / EVIDENCE_NAME
    return Route(
        root,
        declaration_path,
        declaration,
        batch_path,
        entry,
        work_id,
        work,
        edition_id,
        form_id,
        acquisition_id,
        edition,
        acquisition,
        source,
        archive,
        acquisition_receipt,
        manifest,
        profile,
        boundary,
        policy,
        evidence,
        edition / "acceptance.json",
        edition / "master.tei.xml",
        candidate_root,
        identity,
        scope,
        category,
        str(entry["source_sha256"]),
        str(declaration["source_div_c14n_sha256"]),
    )


def _edition_record(
    work: dict[str, object], identity: dict[str, str]
) -> dict[str, object]:
    forms = [
        f
        for f in work["textual_forms"]
        if f["textual_form_id"] == identity["textual_form_id"]
    ]
    if len(forms) != 1:
        raise PipelineError("textual form is not unique")
    editions = [
        e for e in forms[0]["editions"] if e["edition_id"] == identity["edition_id"]
    ]
    if len(editions) != 1:
        raise PipelineError("edition is not unique")
    return editions[0]


def prepare(
    root: Path, declaration_path: Path, batch_path: Path, stage: Path, receipt: Path
) -> dict[str, object]:
    route = _route(root, declaration_path, batch_path)
    root = route.root
    stage = stage.absolute()
    receipt = receipt.absolute()
    if _io_path(stage).exists() or _io_path(receipt).exists():
        raise PipelineError("stage and receipt must be fresh")
    if not _io_path(stage.parent).is_dir() or _io_path(stage.parent).is_symlink():
        raise PipelineError("stage parent must exist and not be a reparse point")
    if (
        root == stage
        or root in stage.parents
        or route.candidate_root == stage
        or route.candidate_root in stage.parents
    ):
        raise PipelineError("stage overlaps protected input")
    manifest = SourceManifest.load(root / route.manifest, repository_root=root)
    package = CandidatePackage.load(route.candidate_root / "package")
    entry = route.batch_entry
    if (
        manifest.sha256 != entry["manifest_sha256"]
        or package.sha256 != entry["candidate_sha256"]
        or package.manifest.get("status") != "nonaccepted"
    ):
        raise PipelineError("candidate or source manifest differs from inspected batch")
    original = package.member_bytes("content.tei.xml")
    if hashlib.sha256(original).hexdigest() != entry["candidate_tei_sha256"]:
        raise PipelineError("candidate TEI differs from inspected batch")
    report = validate(manifest, package, _oracle)
    prior = _read(route.candidate_root / "validation.json")
    if (
        report.status != "pass"
        or report.findings
        or prior.get("report_sha256") != report.sha256
        or prior.get("candidate_sha256") != package.sha256
        or _sha(route.candidate_root / "validation.json") != entry["validation_sha256"]
    ):
        raise PipelineError("independent source oracle differs from inspected batch")
    if _sha(root / route.source) != route.source_sha:
        raise PipelineError("extracted XML changed")
    acquisition = validate_acquisition(
        _io_path(root / route.acquisition), root=_io_path(root)
    )
    if (
        _sha(root / route.acquisition) != entry["acquisition_sha256"]
        or acquisition["source_path"] != route.source.as_posix()
        or acquisition["source_sha256"] != route.source_sha
    ):
        raise PipelineError("acquisition does not bind the exact extracted XML")
    before = _files(root / route.work)
    acceptance_rel = route.acceptance.relative_to(route.work).as_posix()
    master_rel = route.master.relative_to(route.work).as_posix()
    if (
        acceptance_rel in before
        or master_rel in before
        or _io_path(root / route.evidence).exists()
    ):
        raise PipelineError(
            "master, acceptance, or integration evidence already installed"
        )
    _copy_tree(root / route.work, stage / route.work)
    for relative in (
        route.source,
        route.archive,
        route.acquisition_receipt,
        route.manifest,
        route.profile,
        route.boundary,
        route.policy,
        route.batch_path,
        route.declaration_path,
    ):
        _put(stage, relative, _io_path(root / relative).read_bytes())
    work = _read(stage / route.work / "work.json")
    edition = _edition_record(work, route.identity)
    if "category" in edition and edition["category"] != route.category:
        raise PipelineError("declared category conflicts with installed edition")
    edition["category"] = route.category
    _put_json(stage, route.work / "work.json", work)
    load_work(_io_path(stage / route.work / "work.json"))
    retained_scope = (
        "The complete extracted XML remains retained; this edition selects only "
        f"the individually inspected work div at ordinal {entry['work_div_ordinal']} "
        f"of {entry['volume_work_count']}; the other work divs and volume shell are outside the accepted text."
    )
    acquisition["source_scope"] = route.scope
    acquisition["retained_files"][1]["scope"] = retained_scope
    _put_json(stage, route.acquisition, acquisition)
    validate_acquisition(_io_path(stage / route.acquisition), root=_io_path(stage))
    for name in package.member_names:
        _put(
            stage, route.evidence / "inputs/package" / name, package.member_bytes(name)
        )
    for relative in (Path("package/manifest.json"), Path("validation.json")):
        _put(
            stage,
            route.evidence / "inputs" / relative,
            _io_path(route.candidate_root / relative).read_bytes(),
        )
    reproduced = stage / route.evidence / "inputs/reproduced"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            route.manifest.as_posix(),
            "--destination",
            str(reproduced),
            "--repository-root",
            str(root),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    reproduction_summary = json.loads(process.stdout)
    candidate_files = _files(route.candidate_root)
    reproduced_files = _files(reproduced)
    if len(candidate_files) != 7 or reproduced_files != candidate_files:
        raise PipelineError(
            "fresh-process reconstruction differs from inspected candidate"
        )
    _put_json(
        stage,
        route.evidence / "reproduction.json",
        {
            "status": "pass",
            "command": "py -3 -m build.tools.reconstruct_candidate",
            "exit_code": process.returncode,
            "candidate_files": candidate_files,
            "reproduced_files": reproduced_files,
            "summary": reproduction_summary,
        },
    )
    source_binding = {
        "source_path": route.source.as_posix(),
        "source_sha256": route.source_sha,
        "source_bytes": acquisition["source_bytes"],
        "source_scope": route.scope,
    }
    revision = {
        "id": f"{route.work_id}-openmgh-electronic-v1",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "note": f"Accept the inspected complete {route.work_id} work division of the extracted openMGH electronic witness.",
    }
    derived = bind_reviewed_header(
        original,
        expected_sha256=entry["candidate_tei_sha256"],
        identity=route.identity,
        source=source_binding,
        source_url=acquisition["url"],
        declared_scope=route.scope,
        revision=revision,
    )
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("acceptance header binding changed candidate body")
    candidate = _put(stage, route.evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise PipelineError(f"acceptance TEI XSD failed: {errors[:3]}")
    expected = [
        {"path": route.archive.as_posix(), "position": 1},
        {"path": route.source.as_posix(), "position": 2},
    ]
    excluded = [
        {
            **expected[0],
            "reason": "Retained download package only; the extracted XML is the source of text.",
        }
    ]
    included = [
        {
            **expected[1],
            "bytes": acquisition["retained_files"][1]["bytes"],
            "sha256": route.source_sha,
            "scope": retained_scope,
        }
    ]
    scope = {
        "kind": "selection",
        "declared": route.scope,
        "expected_members": expected,
        "included_members": included,
        "excluded_members": excluded,
    }
    common = {
        "identity": route.identity,
        "source": source_binding,
        "candidate": make_file_binding(stage, candidate),
        "scope": route.scope,
        "accepted_scope": {"kind": "selection", "declared": route.scope},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": excluded,
        "missing_members": [],
        "unknown_members": [],
    }
    accounting = _put_json(
        stage,
        route.evidence / "source-accounting.json",
        common
        | {
            "source_sha256": route.source_sha,
            "source_bytes": acquisition["source_bytes"],
            "selected_work_div": entry["work_div_n"],
            "source_work_div_ordinal": entry["work_div_ordinal"],
            "volume_work_div_count": entry["volume_work_count"],
            "source_div_c14n_sha256": route.source_div_sha,
            "unselected_sibling_work_divs": entry["volume_work_count"] - 1,
            "source_manifest_sha256": manifest.sha256,
            "candidate_package_sha256": package.sha256,
            "oracle_report_sha256": report.sha256,
        },
    )
    inputs = {
        "source_manifest": make_file_binding(stage, stage / route.manifest),
        "package_manifest": make_file_binding(
            stage, stage / route.evidence / "inputs/package/manifest.json"
        ),
        "validation": make_file_binding(
            stage, stage / route.evidence / "inputs/validation.json"
        ),
        "boundary": make_file_binding(stage, stage / route.boundary),
        "batch": make_file_binding(stage, stage / route.batch_path),
        "declaration": make_file_binding(stage, stage / route.declaration_path),
        "reproduction": make_file_binding(
            stage, stage / route.evidence / "reproduction.json"
        ),
    }
    descriptions = {
        "validation": "Independent oracle passes for the exact nonaccepted package and extracted source XML.",
        "accounting": f"One inspected complete work division is selected; {entry['volume_work_count'] - 1} siblings and the volume shell remain in the retained XML.",
        "fidelity": "Every selected element, attribute, text node, line break, page break, and order equals the exact source work div.",
        "reproducibility": "All seven candidate and validation files reproduced byte for byte in a fresh process; this stage changes only the TEI header.",
        "schema": "Original and acceptance-header TEI pass vendored TEI P5 XSD.",
        "closure": "Extracted XML, acquisition, inspected boundary, declaration, package, oracle result, and candidate are hash-bound.",
    }
    technical = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": [
            "Producer and oracle share the two-locator whole-work selection; an individual source-boundary declaration and adjacent sibling inspection constrain that choice."
        ],
        "independent_corroboration": "Full-div source oracle and inspected boundary agree with source IDs, ordinal, adjacent siblings, and candidate accounting.",
    }
    command = "py -3 -m build.tools.stage_openmgh_inspected_acceptance --prepare"
    for name, description in descriptions.items():
        path = _put_json(
            stage,
            route.evidence / f"{name}.json",
            common
            | {
                "status": "pass",
                "command": command,
                "exit_code": 0,
                "description": description,
                "inputs": inputs,
                "oracle_report_sha256": report.sha256,
            },
        )
        technical[name] = {
            "path": _io_path(path),
            "status": "pass",
            "command": command,
            "exit_code": 0,
        }
    reviewed_at = _now()
    review = {
        "reviewer": f"agent:{route.work_id}-openmgh-electronic-evidence-review",
        "reviewed_at": reviewed_at,
        "coverage": {
            "status": "unavailable",
            "declared": route.scope,
            "reached": ["retained XML work div", "exact nonaccepted candidate TEI"],
            "inspected": [
                "retained XML work div/boundary and adjacent siblings",
                "exact nonaccepted candidate TEI/complete source-candidate element, attribute, and text comparison",
            ],
            "unreviewed": ["visual source/TEI comparison loci"],
        },
        "source_quality_uncertainty": [
            "No independent print witness has been collated."
        ],
        "discrepancies": [],
        "unreviewed_residuals": ["No visual source/TEI comparison was performed."],
    }
    review_path = _put_json(
        stage,
        route.evidence / "review.json",
        common
        | review
        | {
            "inputs": inputs,
            "unassessed": [
                "visual review",
                "human review",
                "print collation",
                "rights clearance",
                "publication",
            ],
        },
    )
    decision = {
        "source_local_disposition": "Agent acceptance of this complete electronic work division only.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": review["reviewer"],
            "assessed_at": reviewed_at,
            "supported_scope": route.scope,
            "unresolved_claims": [],
            "unassessed_stronger_claims": [
                "visual text review",
                "independently collated print witness",
                "human acceptance",
                "rights clearance",
                "publication",
            ],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        _io_path(stage),
        identity=route.identity,
        candidate_path=_io_path(candidate),
        source_accounting_path=_io_path(accounting),
        scope=scope,
        technical=technical,
        review=review | {"report_path": _io_path(review_path)},
        representation_revision=revision,
        decision=decision,
    )
    write_acceptance(_io_path(stage / route.acceptance), record)
    validate_acceptance(_io_path(stage / route.acceptance), root=_io_path(stage))
    _put(stage, route.master, derived)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(
        status="promoted",
        promoted_at=_now(),
        master=make_file_binding(stage, stage / route.master),
    )
    write_acceptance(_io_path(stage / route.acceptance), record)
    state = _read(stage / route.work / "state.json")
    targets = [
        x
        for x in state["targets"]
        if x["target_id"] == route.edition_id and x["target_type"] == "edition"
    ]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("edition target is not uniquely acquired")
    targets[0].update(
        stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now()
    )
    targets[0]["evidence"].extend(
        [route.master.as_posix(), route.acceptance.as_posix()]
    )
    _put_json(stage, route.work / "state.json", state)
    validate_acceptance(_io_path(stage / route.acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / route.work / "state.json"), root=_io_path(stage))
    after = _files(stage / route.work)
    external = {
        p: h
        for p, h in _files(stage).items()
        if not p.startswith(route.work.as_posix() + "/")
    }
    for path, digest in external.items():
        if _sha(root / path) != digest:
            raise PipelineError(f"external source evidence changed: {path}")
    result = {
        "contract": CONTRACT,
        "status": "staged-only",
        "prepared_at": _now(),
        "canonical_root": root.as_posix(),
        "stage_root": stage.as_posix(),
        "declaration_path": route.declaration_path.as_posix(),
        "declaration_sha256": _sha(root / route.declaration_path),
        "batch_path": route.batch_path.as_posix(),
        "work_id": route.work_id,
        "before": before,
        "after": after,
        "external_dependencies": external,
        "changed_paths": sorted(
            p for p in set(before) | set(after) if before.get(p) != after.get(p)
        ),
        "source_path": route.source.as_posix(),
        "source_sha256": route.source_sha,
        "category": route.category,
        "limits": [
            "one inspected complete electronic work div",
            "visual review unperformed",
            "human, print, rights and publication separate",
        ],
    }
    _write_json_durable(receipt, result)
    return result


def preflight(receipt: Path) -> tuple[dict[str, object], Route, Path]:
    record = _read(receipt.resolve(strict=True))
    if record.get("contract") != CONTRACT or record.get("status") != "staged-only":
        raise PipelineError("inspected openMGH stage receipt contract differs")
    root = Path(str(record["canonical_root"])).resolve(strict=True)
    stage = Path(str(record["stage_root"])).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage/canonical roots overlap")
    route = _route(
        root, Path(str(record["declaration_path"])), Path(str(record["batch_path"]))
    )
    if (
        route.work_id != record["work_id"]
        or _sha(root / route.declaration_path) != record["declaration_sha256"]
    ):
        raise PipelineError("declared work or category changed")
    before, after = _files(root / route.work), _files(stage / route.work)
    if before != record["before"] or after != record["after"]:
        raise PipelineError("complete work generation changed")
    allowed = {
        "work.json",
        "state.json",
        route.acquisition.relative_to(route.work).as_posix(),
        route.acceptance.relative_to(route.work).as_posix(),
        route.master.relative_to(route.work).as_posix(),
    }
    prefix = route.evidence.relative_to(route.work).as_posix() + "/"
    for path in set(before) | set(after):
        if (
            before.get(path) != after.get(path)
            and path not in allowed
            and not (path.startswith(prefix) and path not in before)
        ):
            raise PipelineError(f"unrelated canonical work file differs: {path}")
    old_work, new_work = (
        _read(root / route.work / "work.json"),
        _read(stage / route.work / "work.json"),
    )
    _edition_record(old_work, route.identity)["category"] = route.category
    if old_work != new_work:
        raise PipelineError("staged work changes more than category")
    old_acquisition, new_acquisition = (
        _read(root / route.acquisition),
        _read(stage / route.acquisition),
    )
    old_acquisition["source_scope"] = route.scope
    old_acquisition["retained_files"][1]["scope"] = (
        "The complete extracted XML remains retained; this edition selects only "
        f"the individually inspected work div at ordinal {route.batch_entry['work_div_ordinal']} "
        f"of {route.batch_entry['volume_work_count']}; the other work divs and volume shell are outside the accepted text."
    )
    if old_acquisition != new_acquisition:
        raise PipelineError("staged acquisition changes more than source scope")
    old_state, new_state = (
        _read(root / route.work / "state.json"),
        _read(stage / route.work / "state.json"),
    )
    old_target = [
        x
        for x in old_state["targets"]
        if x["target_id"] == route.edition_id and x["target_type"] == "edition"
    ]
    new_target = [
        x
        for x in new_state["targets"]
        if x["target_id"] == route.edition_id and x["target_type"] == "edition"
    ]
    if (
        len(old_target) != 1
        or len(new_target) != 1
        or old_target[0]["stage"] != "acquired"
    ):
        raise PipelineError("edition state transition is not unique")
    old_target[0].update(
        stage="accepted",
        reason=PROMOTED_MASTER_REASON,
        updated_at=new_target[0]["updated_at"],
    )
    old_target[0]["evidence"].extend(
        [route.master.as_posix(), route.acceptance.as_posix()]
    )
    if old_state != new_state:
        raise PipelineError("staged state changes beyond edition acceptance")
    if (
        route.acceptance.relative_to(route.work).as_posix() in before
        or route.master.relative_to(route.work).as_posix() in before
    ):
        raise PipelineError("acceptance/master already installed")
    for path, digest in record["external_dependencies"].items():
        if _sha(root / path) != digest or _sha(stage / path) != digest:
            raise PipelineError(f"external evidence changed: {path}")
    accepted = validate_acceptance(
        _io_path(stage / route.acceptance), root=_io_path(stage)
    )
    validate_state(_io_path(stage / route.work / "state.json"), root=_io_path(stage))
    if (
        accepted["promotion"]["status"] != "promoted"
        or accepted["decision"]["agent_assessment"]["status"] != "accepted"
        or accepted["decision"]["human_decision"]["status"] != "not-recorded"
        or accepted["identity"] != route.identity
        or accepted["scope"]["kind"] != "selection"
        or accepted["scope"]["declared"] != route.scope
        or accepted["review"]["coverage"]["status"] != "unavailable"
    ):
        raise PipelineError("promoted acceptance claim differs")
    if (
        after[route.master.relative_to(route.work).as_posix()]
        != after[
            (route.evidence / "candidate.tei.xml").relative_to(route.work).as_posix()
        ]
    ):
        raise PipelineError("master differs from header-bound candidate")
    if (
        sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        != record["changed_paths"]
    ):
        raise PipelineError("changed-file inventory differs")
    return record, route, stage


def install(
    receipt: Path, *, fail_at: Callable[[str], None] | None = None
) -> dict[str, object]:
    record, route, stage = preflight(receipt)
    root, target = route.root, route.root / route.work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight(receipt)
        operation = (
            root / "library/.sidecar-operations" / ("openmgh-" + uuid.uuid4().hex[:16])
        )
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (
            operation / name for name in ("incoming", "previous", "failed-new")
        )
        journal = operation / "operation.json"
        state = {
            "contract": CONTRACT,
            "work_id": route.work_id,
            "receipt": receipt.resolve().as_posix(),
            "before": record["before"],
            "after": record["after"],
            "phase": "created",
            "updated_at": _now(),
        }
        _write_json_durable(journal, state)
        moved = live = False
        try:
            _copy_tree(stage / route.work, incoming)
            if (
                _files(incoming) != record["after"]
                or _files(target) != record["before"]
            ):
                raise PipelineError("incoming or canonical generation changed")
            state.update(phase="prepared", updated_at=_now())
            _write_json_durable(journal, state)
            if fail_at:
                fail_at("after-copy")
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            state.update(phase="previous-moved", updated_at=_now())
            _write_json_durable(journal, state)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            state.update(phase="new-live", updated_at=_now())
            _write_json_durable(journal, state)
            if fail_at:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("installed generation differs")
            validate_acceptance(_io_path(root / route.acceptance), root=_io_path(root))
            validate_state(
                _io_path(root / route.work / "state.json"), root=_io_path(root)
            )
            if fail_at:
                fail_at("after-validation")
            state.update(phase="complete", updated_at=_now())
            _write_json_durable(journal, state)
            return {
                "status": "installed-and-validated",
                "operation": operation.as_posix(),
                "before_count": len(record["before"]),
                "after_count": len(record["after"]),
            }
        except BaseException:
            try:
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError("live generation changed before rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if (
                        _io_path(target).exists()
                        or _files(previous) != record["before"]
                    ):
                        raise PipelineError(
                            "previous generation changed before rollback"
                        )
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("rollback restored unexpected bytes")
                state.update(
                    phase="rolled-back" if moved else "failed-before-swap",
                    updated_at=_now(),
                )
                _write_json_durable(journal, state)
            except BaseException as error:
                state.update(
                    phase="recovery-required",
                    rollback_error=str(error),
                    updated_at=_now(),
                )
                _write_json_durable(journal, state)
                raise PipelineError(
                    f"rollback requires recovery: {operation}"
                ) from error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.prepare and args.apply:
        parser.error("--prepare and --apply are mutually exclusive")
    if args.prepare:
        if not all((args.declaration, args.batch, args.stage)):
            parser.error("--prepare requires --declaration, --batch and --stage")
        result = prepare(
            args.root, args.declaration, args.batch, args.stage, args.receipt
        )
    elif args.apply:
        result = install(args.receipt)
    else:
        record, _route_data, _stage = preflight(args.receipt)
        result = {
            "status": "ready",
            "before_count": len(record["before"]),
            "after_count": len(record["after"]),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
