"""Stage the exact bsb720 Heribert hymn pair; never install."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from build.tools import prepare_openmgh_bsb720_heribert_hymns as source
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.poetry import project_accepted_poetry, verify_accepted_poetry
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "ocd-openmgh-bsb720-heribert-hymns-acceptance-stage-v1"
EVIDENCE = "openmgh-bsb720-heribert-hymns-v1"
IDS = frozenset(work_id for work_id, _ in source.WORKS)


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: object) -> bytes:
    return source._json(value)


def _read(path: Path) -> dict:
    return source._read(path)


def _put(root: Path, relative: Path, data: bytes) -> Path:
    target = root / relative
    io_target = Path(_io_path(target))
    io_target.parent.mkdir(parents=True, exist_ok=True)
    io_target.write_bytes(data)
    return target


def _put_json(root: Path, relative: Path, value: object) -> Path:
    return _put(root, relative, _json(value))


def _copy(root: Path, stage: Path, relative: Path) -> None:
    source_path = Path(_io_path(root / relative))
    target = Path(_io_path(stage / relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)


def prepare(root: Path, direct_receipt: Path, work_id: str,
            stage: Path, receipt: Path) -> dict:
    if work_id not in IDS:
        raise ValueError(f"work outside Heribert hymn scope: {work_id}")
    root = root.resolve(strict=True)
    direct_receipt = direct_receipt.resolve(strict=True)
    stage, receipt = stage.absolute(), receipt.absolute()
    if (root == stage or root in stage.parents or stage in root.parents
            or Path(_io_path(stage)).exists() or Path(_io_path(receipt)).exists()):
        raise ValueError("fresh external stage and receipt required")
    if not Path(_io_path(stage.parent)).is_dir() or not Path(_io_path(receipt.parent)).is_dir():
        raise ValueError("stage or receipt parent missing")
    direct = _read(direct_receipt)
    if (direct.get("contract") != "ocd-openmgh-bsb720-heribert-hymns-direct-candidates-v1"
            or direct.get("status") != "nonaccepted"
            or direct.get("source_sha256") != source.SOURCE_SHA256
            or len(direct.get("works", [])) != 2):
        raise ValueError("two-work direct receipt changed")
    matching = [item for item in direct["works"] if item["work_id"] == work_id]
    if len(matching) != 1:
        raise ValueError("work absent or repeated in direct receipt")
    item = matching[0]
    source_bytes, _source_tree = source._source(root)
    work_record, acquisition, work_path, acquisition_path = source._work(root, work_id)
    if (_sha(root / work_path) != item["work_sha256"]
            or _sha(root / acquisition_path) != item["acquisition_sha256"]
            or _sha(Path(item["candidate_path"])) != item["candidate_sha256"]):
        raise ValueError("work, acquisition, or candidate preimage changed")
    # A separate process must reproduce the complete candidate batch.
    with TemporaryDirectory(prefix="bsb720-heribert-repro-", dir=stage.parent) as temporary:
        reproducible = Path(temporary) / "candidate"
        process = subprocess.run(
            [sys.executable, "-m", "build.tools.prepare_openmgh_bsb720_heribert_hymns",
             "--destination", str(reproducible)],
            cwd=root, check=True, capture_output=True, text=True,
        )
        if not process.stdout.strip() or _sha(reproducible / work_id / "candidate.tei.xml") != item["candidate_sha256"]:
            raise ValueError("clean-process candidate reproduction differs")
    work = Path("library/works") / work_id
    before = _files(root / work)
    shutil.copytree(_io_path(root / work), _io_path(stage / work))
    if _files(stage / work) != before:
        raise ValueError("copied work generation differs")
    for relative in (source.SOURCE, source.PACKAGE, source.RECEIPT):
        _copy(root, stage, relative)
    edition = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic"
    acceptance_rel = edition / "acceptance.json"
    master_rel = edition / "master.tei.xml"
    if Path(_io_path(root / acceptance_rel)).exists() or Path(_io_path(root / master_rel)).exists():
        raise ValueError("work already has a canonical acceptance or master")
    revised = _read(stage / work / "work.json")
    edition_record = revised["textual_forms"][0]["editions"][0]
    if edition_record.get("category") or edition_record.get("language"):
        raise ValueError("edition category or language already set")
    edition_record.update(category="poetry", language="la")
    validate_identity_update(work_record, revised)
    _put_json(stage, work / "work.json", revised)
    load_work(Path(_io_path(stage / work / "work.json")))
    evidence = work / "integration" / EVIDENCE
    original = Path(_io_path(Path(item["candidate_path"]))).read_bytes()
    _put(stage, evidence / "inputs/candidate.tei.xml", original)
    revision = {"id": f"{work_id}-bsb720-electronic-v1",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Accept the complete numbered Heribert hymn with its internal page break in the extracted openMGH electronic witness."}
    identity = {"work_id": work_id,
                "textual_form_id": revised["textual_forms"][0]["textual_form_id"],
                "edition_id": edition_record["edition_id"],
                "acquisition_id": edition_record["acquisition_ids"][0]}
    scope_text = (
        f"The complete numbered Heribert hymn {item['number']} in the flat Carmina block "
        f"of extracted openMGH bsb00000720, from {item['source_heading_id']} "
        f"through {item['source_last_line_id']}. The shared Carmina heading and "
        f"adjacent works remain source-owned. Its internal page break "
        f"{item['independent_oracle']['internal_page_break']} remains in the hymn; "
        f"the next heading is {item['independent_oracle']['following_heading_id']}. "
        "The page break following hymn 4 is not part of either hymn."
    )
    source_binding = {
        "source_path": source.SOURCE.as_posix(),
        "source_sha256": source.SOURCE_SHA256,
        "source_bytes": len(source_bytes),
        "source_scope": scope_text,
    }
    derived = bind_reviewed_header(
        original, expected_sha256=item["candidate_sha256"],
        identity=identity, source=source_binding, source_url=acquisition["url"],
        declared_scope=scope_text, revision=revision,
    )
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("accepted header binding changed source body")
    candidate = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(candidate):
        raise ValueError(f"accepted TEI XSD failed: {errors[:3]}")
    expected = [{"path": source.PACKAGE.as_posix(), "position": 1},
                {"path": source.SOURCE.as_posix(), "position": 2}]
    included = [{"path": source.SOURCE.as_posix(), "position": 2,
                 "bytes": len(source_bytes), "sha256": source.SOURCE_SHA256,
                 "scope": scope_text}]
    excluded = [{"path": source.PACKAGE.as_posix(), "position": 1,
                 "reason": "Original download ZIP is the package; extracted XML is the text source."}]
    scope = {"kind": "selection", "declared": scope_text,
             "expected_members": expected, "included_members": included,
             "excluded_members": excluded}
    acquired_binding = {"source_path": acquisition["source_path"],
                        "source_sha256": acquisition["source_sha256"],
                        "source_bytes": acquisition["source_bytes"],
                        "source_scope": acquisition["source_scope"]}
    common = {"identity": identity, "source": acquired_binding,
              "candidate": make_file_binding(stage, candidate),
              "scope": scope_text,
              "accepted_scope": {"kind": "selection", "declared": scope_text},
              "expected_members": expected, "included_members": included,
              "excluded_members": excluded, "missing_members": [], "unknown_members": []}
    account = _put_json(stage, evidence / "source-accounting.json", common | {
        "scope": acquisition["source_scope"],
        "source_sha256": source.SOURCE_SHA256,
        "source_bytes": len(source_bytes),
        "source_heading_id": item["source_heading_id"],
        "source_last_line_id": item["source_last_line_id"],
        "line_count": item["line_count"], "source_child_start": item["independent_oracle"]["source_child_start"],
        "source_child_end": item["independent_oracle"]["source_child_end"],
        "shared_collection_heading": direct["shared_collection_heading"],
        "internal_page_breaks": direct["internal_page_breaks"],
        "direct_receipt_sha256": _sha(direct_receipt),
        "original_candidate_sha256": item["candidate_sha256"],
        "accepted_body_unchanged": True,
    })
    command = "py -3 -m build.tools.stage_openmgh_bsb720_heribert_hymns_acceptance"
    proof_data = common | {"status": "pass", "command": command, "exit_code": 0,
                           "source_oracle": item["independent_oracle"],
                           "original_candidate_sha256": item["candidate_sha256"],
                           "direct_receipt_sha256": _sha(direct_receipt),
                           "clean_process_reproduction": "pass",
                           "tei_xsd": "pass", "accepted_body_unchanged": True}
    technical = {
        "producer": {"id": "ocd-openmgh-bsb720-heribert-hymns-direct-candidates-v1"},
        "checker": {"id": "ocd-openmgh-bsb720-heribert-hymns-source-oracle-v1"},
        "shared_assumptions": [
            "Producer and checker both parse the same extracted TEI; the checker separately derives numbered headings and checks every selected line and internal page-break node and the enclosing source envelope."
        ],
        "independent_corroboration": (
            "Source-order heading and neighboring-boundary inspection, exact source-tree oracle, "
            "clean-process reproduction, TEI XSD, and independently verified native poetry row agree."
        ),
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, evidence / f"{name}.json", proof_data | {"claim": name})
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {
        "reviewer": f"agent:{work_id}-bsb720-source-review",
        "reviewed_at": reviewed_at,
        "coverage": {"status": "unavailable", "declared": scope_text,
                     "reached": ["retained XML numbered poem span", "exact candidate TEI"],
                     "inspected": ["retained XML numbered poem span/heading-terminal-next-heading-page",
                                   "exact candidate TEI/full source-child comparison"],
                     "unreviewed": ["close CVW visual source/TEI comparison"]},
        "source_quality_uncertainty": ["No print witness was collated."],
        "discrepancies": [],
        "unreviewed_residuals": ["Visual and human review remain unrecorded."],
    }
    review_path = _put_json(stage, evidence / "review.json", common | review)
    decision = {
        "source_local_disposition": "Agent acceptance of this complete numbered electronic hymn only.",
        "blockers": [],
        "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                             "assessed_at": reviewed_at, "supported_scope": scope_text,
                             "unresolved_claims": [],
                             "unassessed_stronger_claims": ["close visual review", "human acceptance",
                                                            "print collation", "rights clearance", "publication"]},
        "human_decision": {"status": "not-recorded"},
    }
    acceptance = build_acceptance_record(
        stage, identity=identity, candidate_path=candidate,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision,
    )
    write_acceptance(Path(_io_path(stage / acceptance_rel)), acceptance)
    validate_acceptance(stage / acceptance_rel, root=stage)
    _put(stage, master_rel, derived)
    acceptance["promotion"] = dict(acceptance["promotion"])
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, stage / master_rel))
    write_acceptance(Path(_io_path(stage / acceptance_rel)), acceptance)
    state = _read(stage / work / "state.json")
    targets = [target for target in state["targets"]
               if target["target_type"] == "edition" and target["target_id"] == edition.name]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("edition target is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    targets[0]["evidence"].extend([master_rel.as_posix(), acceptance_rel.as_posix()])
    _put_json(stage, work / "state.json", state)
    validated = validate_acceptance(stage / acceptance_rel, root=stage)
    validate_state(stage / work / "state.json", root=stage)
    projected = project_accepted_poetry(Path(_io_path(stage)),
                                        acceptance_path=Path(_io_path(stage / acceptance_rel)))
    errors = verify_accepted_poetry(Path(_io_path(stage)),
                                    acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                    rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"accepted native poetry projection failed: {errors[:3]}")
    # A data-path notice must travel with the accepted work, beside the master.
    notice = (f"# Source and attribution for {work_id}\n\n"
              "Text witness: extracted openMGH bsb00000720 TEI XML. "
              "The Monumenta Germaniae Historica and Bavarian State Library, Munich, "
              "request attribution for copies or derivatives of the electronic file. "
              "Its publication statement labels digital annotations CC BY 4.0 and "
              "describes the underlying text as believed public domain. "
              "See the retained TEI header for the exact statement.\n")
    _put(stage, edition / "README.source.md", notice.encode())
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": work_id,
        "canonical_root": root.as_posix(), "stage_root": stage.as_posix(),
        "direct_receipt": direct_receipt.as_posix(),
        "direct_receipt_sha256": _sha(direct_receipt),
        "source_path": source.SOURCE.as_posix(), "source_sha256": source.SOURCE_SHA256,
        "before": before, "after": _files(stage / work),
        "accepted_master_sha256": validated["promotion"]["master"]["sha256"],
        "acceptance_sha256": _sha(stage / acceptance_rel),
        "category": "poetry", "language": "la", "projection_rows": 1,
        "projection_status": "independent-check-pass",
        "installation": "not-performed",
    }
    Path(_io_path(receipt)).write_bytes(_json(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(IDS))
    parser.add_argument("--direct-receipt", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = prepare(args.root, args.direct_receipt, args.work_id, args.stage, args.receipt)
    print(json.dumps({"work_id": result["work_id"],
                      "master_sha256": result["accepted_master_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
