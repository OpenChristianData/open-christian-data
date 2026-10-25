"""Preflight or guarded-install only the bsb754 Vita abbatum edition.

The default is read-only. Application uses the stock durable work-generation
transaction after a pinned, work-local source and acceptance preflight.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.openmgh_bsb754_vita_abbatum_oracle import check_candidate
from build.tools import freeze_openmgh_bsb754_vita_abbatum as freezing
from build.tools import prepare_openmgh_bsb754_vita_abbatum as source
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
FREEZE_SHA256 = "268916f2c8742973f1d029509c2008c9213cdd1a41250a7acc237b4ce73deccf"
RECEIPT_SHA256 = "6079d756bd7cd6851a9802f09db5aa6904a957bb15af88da4b031386ed400df3"
DIRECT_SHA256 = freezing.DIRECT_SHA



def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _receipt(work_id: str) -> tuple[Path, str]:
    if work_id != source.WORK_ID or _sha(freezing.FREEZE) != FREEZE_SHA256:
        raise PipelineError("work or reviewed bsb754 freeze changed")
    if _sha(freezing.RECEIPT) != RECEIPT_SHA256:
        raise PipelineError("reviewed bsb754 stage receipt changed")
    return freezing.RECEIPT, RECEIPT_SHA256


def preflight(receipt: Path, *, expected_receipt_sha256: str) -> dict:
    receipt = receipt.resolve(strict=True)
    if (receipt != freezing.RECEIPT.resolve(strict=True)
            or expected_receipt_sha256 != RECEIPT_SHA256
            or _sha(receipt) != expected_receipt_sha256
            or _sha(freezing.FREEZE) != FREEZE_SHA256):
        raise PipelineError("exact stage receipt hash changed")
    record = _read(receipt)
    work_id = record.get("work_id")
    if (work_id != source.WORK_ID
            or record.get("contract") != "ocd-openmgh-bsb754-vita-abbatum-acceptance-stage-v1"
            or record.get("status") != "staged-only"
            or record.get("edition_id") != source.EDITION_ID
            or record.get("category") != "prose"
            or record.get("language") != "la"
            or record.get("projection_rows") != 1
            or record.get("installation") != "not-performed"):
        raise PipelineError("unrecognized bsb754 Vita abbatum stage")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if (root != ROOT.resolve(strict=True) or stage != freezing.STAGE.resolve(strict=True)
            or root == stage or root in stage.parents or stage in root.parents):
        raise PipelineError("bsb754 stage or canonical root differs")
    frozen = _read(freezing.FREEZE)
    if (frozen.get("contract") != freezing.CONTRACT
            or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("canonical_install") != "not-performed"
            or frozen.get("work_id") != work_id
            or frozen.get("edition_id") != source.EDITION_ID
            or frozen.get("other_edition_id") != source.OTHER_EDITION_ID
            or frozen.get("stage_receipt_sha256") != RECEIPT_SHA256
            or frozen.get("before") != record["before"] or frozen.get("after") != record["after"]
            or frozen.get("accepted_master_sha256") != record["accepted_master_sha256"]
            or frozen.get("acceptance_sha256") != record["acceptance_sha256"]
            or _files(stage) != frozen["stage_files"]):
        raise PipelineError("reviewed bsb754 freeze or complete stage changed")
    for relative, digest in (
        (source.SOURCE, source.SOURCE_SHA256), (source.PACKAGE, source.PACKAGE_SHA256),
        (source.RECEIPT, source.RECEIPT_SHA256),
        (source.OTHER_SOURCE, source.OTHER_SOURCE_SHA256),
        (source.OTHER_PACKAGE, source.OTHER_PACKAGE_SHA256),
        (source.OTHER_RECEIPT, source.OTHER_RECEIPT_SHA256),
    ):
        if _sha(root / relative) != digest or _sha(stage / relative) != digest:
            raise PipelineError(f"retained source dependency changed: {relative}")
    if (record.get("source_path") != source.SOURCE.as_posix()
            or record.get("source_sha256") != source.SOURCE_SHA256
            or record.get("other_source_path") != source.OTHER_SOURCE.as_posix()
            or record.get("other_source_sha256") != source.OTHER_SOURCE_SHA256):
        raise PipelineError("selected or preserved edition source pin changed")
    direct_receipt = Path(record["direct_receipt"])
    if (_sha(direct_receipt) != DIRECT_SHA256
            or record.get("direct_receipt_sha256") != DIRECT_SHA256):
        raise PipelineError("direct bsb754 candidate receipt changed")
    direct = _read(direct_receipt)
    if (direct.get("contract") != "ocd-openmgh-bsb754-vita-abbatum-direct-v1"
            or direct.get("work_id") != work_id
            or direct.get("edition_id") != source.EDITION_ID
            or frozen["direct_receipt_sha256"] != DIRECT_SHA256):
        raise PipelineError("direct bsb754 edition scope changed")
    item = direct
    work = Path("library/works") / work_id
    if _files(root / work) != record["before"] or _files(stage / work) != record["after"]:
        raise PipelineError("canonical or staged work generation changed")
    live_work, acquired, work_path, acquisition_path, other_path = source._work(root)
    if (_sha(root / work_path) != item["work_sha256"]
            or _sha(root / acquisition_path) != item["acquisition_sha256"]
            or _sha(stage / acquisition_path) != item["acquisition_sha256"]
            or _sha(root / other_path) != source.OTHER_ACQUISITION_SHA256
            or _sha(stage / other_path) != source.OTHER_ACQUISITION_SHA256):
        raise PipelineError("work identity or acquisition changed")
    future_work = _read(stage / work_path)
    validate_identity_update(live_work, future_work)
    load_work(stage / work_path)
    if future_work["textual_forms"][0]["editions"][0] != live_work["textual_forms"][0]["editions"][0]:
        raise PipelineError("bsb750 edition metadata changed")
    future_edition = future_work["textual_forms"][0]["editions"][1]
    if future_edition.get("category") != "prose" or future_edition.get("language") != "la":
        raise PipelineError("stage edition metadata changed")
    if _sha(Path(item["candidate_path"])) != item["candidate_sha256"]:
        raise PipelineError("source-derived candidate changed")
    direct_candidate = Path(_io_path(Path(item["candidate_path"]))).read_bytes()
    source_bytes = Path(_io_path(root / source.SOURCE)).read_bytes()
    oracle = check_candidate(source_bytes, direct_candidate, live_work, acquired)
    if oracle != item["independent_oracle"]:
        raise PipelineError("independent source oracle changed")
    edition = work / "forms" / source.FORM_ID / "editions" / source.EDITION_ID
    other_edition = work / "forms" / source.FORM_ID / "editions" / source.OTHER_EDITION_ID
    if _files(root / other_edition) != _files(stage / other_edition):
        raise PipelineError("bsb750 edition files changed")
    if (_read(root / work / "state.json")["targets"][:2]
            != _read(stage / work / "state.json")["targets"][:2]):
        raise PipelineError("bsb750 edition state targets changed")
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
            operation_kind="openmgh-bsb754-vita-abbatum-edition-install",
            result_status="installed-and-validated",
            accepted_editions=1, fail_at=fail_at,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=[source.WORK_ID])
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
