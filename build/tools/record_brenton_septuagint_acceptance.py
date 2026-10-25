"""Record the approved Brenton v3 technical acceptance in a fresh bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.tei.acceptance import (
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(
    "reports/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint/"
    "acceptance-handoff-20260930-v3"
)
WORK = Path("library/works/brenton-septuagint")
EDITION = WORK / "forms/brenton-septuagint-retained-en/editions/brenton-septuagint-electronic"
ACCEPTANCE = EDITION / "acceptance.json"
CANDIDATE = WORK / "integration/brenton-electronic-whole-work-v1/candidate.tei.xml"
RECEIPT = Path("BRENTON_HANDOFF_RECEIPT.json")
SOURCE_RECEIPT_SHA = "11836169116d40bf3d7a2979033789bd3c433c90c269126432f6444c1bbfd8e5"
SOURCE_ACCEPTANCE_SHA = "e12061fe6852c42a96d1ecabcc12967229c6047115152f434397a7fe14389cff"
CANDIDATE_SHA = "c80f8ec3035bac35a668ef97e3031baaa14688310cd284c277cb75d295a172a4"


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _load(path: Path) -> dict:
    value = json.loads(io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"expected JSON object: {path}")
    return value


def record(root: Path, destination: Path) -> Path:
    root = root.resolve(strict=True)
    source = resolve_repo_path(root, SOURCE.as_posix()).resolve(strict=True)
    destination = destination.resolve(strict=False)
    if destination.exists() or destination == source or source in destination.parents:
        raise PipelineError("accepted Brenton destination must be fresh and separate")
    if not destination.parent.is_dir():
        raise PipelineError("accepted Brenton destination parent must exist")
    if (
        _sha(source / RECEIPT) != SOURCE_RECEIPT_SHA
        or _sha(source / ACCEPTANCE) != SOURCE_ACCEPTANCE_SHA
        or _sha(source / CANDIDATE) != CANDIDATE_SHA
    ):
        raise PipelineError("approved Brenton v3 bundle changed")
    source_record = validate_acceptance(source / ACCEPTANCE, root=source)
    if (
        source_record["decision"]["agent_assessment"]["status"] != "unassessed"
        or source_record["decision"]["human_decision"]["status"] != "not-recorded"
        or source_record["promotion"]["status"] != "pending"
    ):
        raise PipelineError("approved Brenton v3 bundle is not the pending review input")

    shutil.copytree(io_path(source), io_path(destination))
    acceptance_path = destination / ACCEPTANCE
    record_value = _load(acceptance_path)
    assessed_at = _utc_now()
    record_value["decision"]["source_local_disposition"] = (
        "Evidence-backed technical agent acceptance for the complete corrected "
        "Brenton electronic USFM edition. Human review, rights clearance, release, "
        "and publication remain unrecorded and separate."
    )
    assessment = record_value["decision"]["agent_assessment"]
    assessment["status"] = "accepted"
    assessment["assessed_at"] = assessed_at
    assessment["unresolved_claims"] = []
    write_acceptance(acceptance_path, record_value)
    validated = validate_acceptance(acceptance_path, root=destination)
    if (
        validated["decision"]["agent_assessment"]["status"] != "accepted"
        or validated["decision"]["human_decision"]["status"] != "not-recorded"
        or validated["promotion"]["status"] != "pending"
    ):
        raise PipelineError("recorded Brenton acceptance did not validate as pending promotion")

    receipt_path = destination / RECEIPT
    receipt = _load(receipt_path)
    receipt["contract"] = "ocd-brenton-frozen-agent-acceptance-v1"
    receipt["status"] = "frozen-agent-accepted-pending-promotion"
    receipt["accepted_from"] = {
        "root": SOURCE.as_posix(),
        "receipt_sha256": SOURCE_RECEIPT_SHA,
        "acceptance_sha256": SOURCE_ACCEPTANCE_SHA,
        "candidate_sha256": CANDIDATE_SHA,
    }
    receipt["acceptance_recorded"] = True
    receipt["accepted_at"] = assessed_at
    receipt["acceptance"] = make_file_binding(destination, acceptance_path)
    acceptance_relative = ACCEPTANCE.relative_to(WORK).as_posix()
    receipt["staged_work"][acceptance_relative] = receipt["acceptance"]["sha256"]
    receipt["next_actions"] = [
        "Promote this exact accepted bundle through promote_accepted_master into a fresh root.",
        "Validate the promoted acceptance, master, and state bindings.",
        "Serialize install_accepted_work for brenton-septuagint and verify the installed generation.",
        "Keep human review, rights, release, and publication separate.",
    ]
    io_path(receipt_path).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return acceptance_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(record(ROOT, args.destination))


if __name__ == "__main__":
    main()
