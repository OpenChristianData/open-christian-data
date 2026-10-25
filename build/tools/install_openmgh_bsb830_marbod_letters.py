"""Preflight or guarded-install one exact bsb830 Marbod letter stage.

The default is read-only. Application uses the stock durable work-generation
transaction after a pinned, work-local source and acceptance preflight.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.openmgh_bsb830_marbod_letters_oracle import check_candidate
from build.tools import prepare_openmgh_bsb830_marbod_letters as source
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
STAGE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews")
PINS = {
    "marbod-letter-to-ingilgerio": (
        "openmgh-bsb830-marbod-letters-stage-20260928-v1/marbod-letter-to-ingilgerio-receipt.json",
        "6eff22a32734064d94f7e95583abc1db89931edaee773c20894ebd5063ed7bd3",
    ),
    "marbod-letter-to-ingungerio": (
        "openmgh-bsb830-marbod-letters-stage-20260928-v1/marbod-letter-to-ingungerio-receipt.json",
        "b4446e1137b52c958df329c8f7c35ad70c3b6c1d2b73216b00f715e41b6c764a",
    ),
}
DIRECT_SHA256 = "9ad98d35851a988b7dc2640d6f5b7fac1178e92e1ff26aacf015f9e429bd9e38"



def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in PINS:
        raise PipelineError(f"work outside exact bsb830 install allowlist: {work_id}")
    name, digest = PINS[work_id]
    path = STAGE_HOME / name
    if _sha(path) != digest:
        raise PipelineError(f"reviewed bsb830 stage receipt changed: {work_id}")
    return path, digest


def preflight(receipt: Path, *, expected_receipt_sha256: str) -> dict:
    receipt = receipt.resolve(strict=True)
    if _sha(receipt) != expected_receipt_sha256:
        raise PipelineError("exact stage receipt hash changed")
    record = _read(receipt)
    work_id = record.get("work_id")
    if (work_id not in PINS
            or record.get("contract") != "ocd-openmgh-bsb830-marbod-letters-acceptance-stage-v1"
            or record.get("status") != "staged-only"
            or record.get("category") != "prose"
            or record.get("language") != "la"
            or record.get("projection_rows") != 1
            or record.get("installation") != "not-performed"):
        raise PipelineError("unrecognized bsb830 stage")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root != ROOT.resolve(strict=True) or root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("bsb830 stage or canonical root differs")
    if (record.get("source_path") != source.SOURCE.as_posix()
            or record.get("source_sha256") != source.SOURCE_SHA256
            or _sha(root / source.SOURCE) != source.SOURCE_SHA256
            or _sha(stage / source.SOURCE) != source.SOURCE_SHA256
            or _sha(root / source.PACKAGE) != source.PACKAGE_SHA256
            or _sha(stage / source.PACKAGE) != source.PACKAGE_SHA256
            or _sha(root / source.RECEIPT) != source.RECEIPT_SHA256):
        raise PipelineError("extracted source or package pin changed")
    direct_receipt = Path(record["direct_receipt"])
    if (_sha(direct_receipt) != DIRECT_SHA256
            or record.get("direct_receipt_sha256") != DIRECT_SHA256):
        raise PipelineError("direct Marbod letter candidate receipt changed")
    direct = _read(direct_receipt)
    entries = [item for item in direct["works"] if item["work_id"] == work_id]
    if len(entries) != 1:
        raise PipelineError("stage work missing from direct source receipt")
    item = entries[0]
    work = Path("library/works") / work_id
    if _files(root / work) != record["before"] or _files(stage / work) != record["after"]:
        raise PipelineError("canonical or staged work generation changed")
    live_work, acquired, work_path, acquisition_path = source._work(root, work_id)
    if (_sha(root / work_path) != item["work_sha256"]
            or _sha(root / acquisition_path) != item["acquisition_sha256"]
            or _sha(stage / acquisition_path) != item["acquisition_sha256"]):
        raise PipelineError("work identity or acquisition changed")
    future_work = _read(stage / work_path)
    validate_identity_update(live_work, future_work)
    load_work(stage / work_path)
    future_edition = future_work["textual_forms"][0]["editions"][0]
    if future_edition.get("category") != "prose" or future_edition.get("language") != "la":
        raise PipelineError("stage edition metadata changed")
    if _sha(Path(item["candidate_path"])) != item["candidate_sha256"]:
        raise PipelineError("source-derived candidate changed")
    direct_candidate = Path(_io_path(Path(item["candidate_path"]))).read_bytes()
    source_bytes = Path(_io_path(root / source.SOURCE)).read_bytes()
    oracle = check_candidate(source_bytes, direct_candidate, live_work, acquired,
                             number=item["number"])
    if oracle != item["independent_oracle"]:
        raise PipelineError("independent source oracle changed")
    edition = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic"
    if Path(_io_path(root / edition / "acceptance.json")).exists() or Path(_io_path(root / edition / "master.tei.xml")).exists():
        raise PipelineError("work already has a canonical accepted master")
    accepted = validate_acceptance(stage / edition / "acceptance.json", root=stage)
    validate_state(stage / work / "state.json", root=stage)
    master = stage / edition / "master.tei.xml"
    if (_sha(master) != record["accepted_master_sha256"]
            or _sha(stage / edition / "acceptance.json") != record["acceptance_sha256"]
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or Path(_io_path(master)).read_bytes().split(b"</teiHeader>", 1)[1]
               != direct_candidate.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("accepted master differs from reviewed source body")
    if errors := validate_file(Path(_io_path(master))):
        raise PipelineError(f"accepted TEI schema failed: {errors[:3]}")
    notice = stage / edition / "README.source.md"
    if not Path(_io_path(notice)).is_file() or b"Monumenta Germaniae Historica" not in Path(_io_path(notice)).read_bytes():
        raise PipelineError("human-visible source notice missing")
    projected = project_accepted_prose(Path(_io_path(stage)),
                                        acceptance_path=Path(_io_path(stage / edition / "acceptance.json")))
    errors = verify_accepted_prose(Path(_io_path(stage)),
                                    acceptance_path=Path(_io_path(stage / edition / "acceptance.json")),
                                    rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"staged native prose row changed: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": work_id,
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": 1, "installation": "not-performed"}


def install(work_id: str, *, fail_at: Callable[[str], None] | None = None) -> dict:
    receipt, digest = _receipt(work_id)
    preflight(receipt, expected_receipt_sha256=digest)
    record = _read(receipt)
    root = ROOT.resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    work = Path("library/works") / work_id
    target = root / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(receipt) != digest:
            raise PipelineError("reviewed stage receipt changed under work lock")
        preflight(receipt, expected_receipt_sha256=digest)
        result = _commit_generation(
            root, target, stage / work, work_id=work_id,
            before=record["before"], after=record["after"],
            existed=True, replacement=False,
            operation_kind="openmgh-bsb830-initial-install",
            result_status="installed-and-validated",
            accepted_editions=1, fail_at=fail_at,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(PINS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(args.work_id)
    else:
        receipt, digest = _receipt(args.work_id)
        result = preflight(receipt, expected_receipt_sha256=digest)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
