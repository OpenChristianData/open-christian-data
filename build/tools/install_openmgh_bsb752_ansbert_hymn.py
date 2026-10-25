"""Guarded Ansbert hymn installer; default action is read-only preflight."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.openmgh_bsb752_ansbert_hymn_oracle import check
from build.tools import prepare_openmgh_bsb752_nested as source
from build.tools import stage_openmgh_bsb752_ansbert_hymn as staging
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "ymnus-de-sancto-ansberto"
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-ansbert-hymn-stage-20260928-v3")
STAGE_RECEIPT_SHA = "463a3d5af5955997b9b3dc15b1e2de6c2ce8255c1d5b1496c10cf70b510ba19f"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def preflight() -> dict:
    receipt_path = STAGE / "stage-receipt.json"
    if _sha(receipt_path) != STAGE_RECEIPT_SHA:
        raise PipelineError("Ansbert reviewed stage receipt differs")
    record = _read(receipt_path)
    if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
            or record.get("work_id") != WORK_ID or record.get("installation") != "not-performed"
            or record.get("category") != "poetry" or record.get("language") != "la"
            or record.get("projection_rows") != 1 or record.get("source_work_div_index") != 19
            or record.get("source_part_indexes") != [2]
            or record.get("direct_receipt_sha256") != staging.DIRECT_SHA
            or Path(record.get("canonical_root", "")).resolve(strict=True) != ROOT.resolve(strict=True)
            or Path(record.get("stage_root", "")).resolve(strict=True) != STAGE.resolve(strict=True)):
        raise PipelineError("Ansbert exact stage scope differs")
    if ROOT.resolve(strict=True) in STAGE.resolve(strict=True).parents:
        raise PipelineError("Ansbert stage overlaps checkout")
    for relative, digest in ((source.SOURCE, source.SOURCE_SHA), (source.PACKAGE, source.PACKAGE_SHA),
                             (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)):
        if _sha(ROOT / relative) != digest or _sha(STAGE / relative) != digest:
            raise PipelineError(f"Ansbert source/package/receipt differs: {relative}")
    work = Path("library/works") / WORK_ID
    before, after = _files(ROOT / work), _files(STAGE / work)
    if before != record["before"] or after != record["after"] or len(before) != 3:
        raise PipelineError("Ansbert canonical or staged work generation differs")
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if (relative in {"work.json", "state.json", "SOURCE_CREDIT.md"}
                or relative.startswith("forms/") and relative.endswith(
                    ("/master.tei.xml", "/acceptance.json", "/README.source.md"))
                or relative.startswith("integration/" + staging.EVIDENCE + "/") and relative not in before):
            continue
        raise PipelineError(f"Ansbert unrelated work path differs: {relative}")
    old_work, new_work = _read(ROOT / work / "work.json"), _read(STAGE / work / "work.json")
    expected = json.loads(json.dumps(old_work))
    editions = expected.get("textual_forms", [{}])[0].get("editions", [])
    if len(expected.get("textual_forms", [])) != 1 or len(editions) != 1:
        raise PipelineError("Ansbert work has ambiguous edition")
    edition_expected = editions[0]
    if edition_expected.get("language") or edition_expected.get("category"):
        raise PipelineError("Ansbert native fields already assigned")
    edition_expected.update(language="la", category="poetry")
    if expected != new_work:
        raise PipelineError("Ansbert identity changed beyond native fields")
    validate_identity_update(old_work, new_work)
    load_work(_io_path(STAGE / work / "work.json"))
    acquisition_rel = next(Path(name) for name in before if name.endswith(".json")
                           and name not in {"work.json", "state.json"})
    acquisition = _read(ROOT / work / acquisition_rel)
    if (_sha(STAGE / work / acquisition_rel) != before[acquisition_rel.as_posix()]
            or acquisition.get("source_path") != source.SOURCE.as_posix()
            or acquisition.get("source_sha256") != source.SOURCE_SHA
            or {item["path"] for item in acquisition.get("retained_files", [])}
               != {source.SOURCE.as_posix(), source.PACKAGE.as_posix()}):
        raise PipelineError("Ansbert acquisition/source binding differs")
    if _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA:
        raise PipelineError("Ansbert direct receipt differs")
    direct = _read(staging.DIRECT / "receipt.json")
    if direct.get("work_id") != WORK_ID or direct.get("excluded_carrier_parts") != [0, 1]:
        raise PipelineError("Ansbert direct part ownership differs")
    if (_sha(Path(direct["candidate_path"])) != direct["candidate_sha256"]
            or _sha(staging.REPRO / "candidate.tei.xml") != direct["candidate_sha256"]):
        raise PipelineError("Ansbert direct candidate reproduction differs")
    source_bytes, _, _ = source._source()
    candidate = _io_path(Path(direct["candidate_path"])).read_bytes()
    oracle = check(source_bytes, candidate, old_work, acquisition)
    if (oracle != direct["oracle"] or oracle["source_part_c14n_sha256"]
            != record["source_part_c14n_sha256"]):
        raise PipelineError("Ansbert independent part oracle differs")
    form = new_work["textual_forms"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / form["editions"][0]["edition_id"]
    acceptance_path, master_path = edition / "acceptance.json", edition / "master.tei.xml"
    if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
        raise PipelineError("Ansbert canonical accepted master already exists")
    accepted = validate_acceptance(_io_path(STAGE / acceptance_path), root=_io_path(STAGE))
    validate_state(_io_path(STAGE / work / "state.json"), root=_io_path(STAGE))
    master = _io_path(STAGE / master_path).read_bytes()
    if (_sha(STAGE / master_path) != record["accepted_master_sha256"]
            or _sha(STAGE / acceptance_path) != record["acceptance_sha256"]
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != candidate.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("Ansbert accepted master changed source body")
    if errors := validate_file(_io_path(STAGE / master_path)):
        raise PipelineError(f"Ansbert master P5 failed: {errors[:3]}")
    credit = _io_path(STAGE / work / "SOURCE_CREDIT.md").read_bytes()
    if (b"Monumenta Germaniae Historica" not in credit
            or _io_path(STAGE / edition / "README.source.md").read_bytes() != credit):
        raise PipelineError("Ansbert source-directed credit differs")
    projected = project_accepted_document(_io_path(STAGE),
                                          acceptance_path=_io_path(STAGE / acceptance_path), category="poetry")
    errors = verify_accepted_document(_io_path(STAGE), acceptance_path=_io_path(STAGE / acceptance_path),
                                      rows=projected["rows"], receipt=projected["receipt"], category="poetry")
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"Ansbert native poetry row differs: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": WORK_ID, "before_files": len(before),
            "after_files": len(after), "projection_rows": 1, "installation": "not-performed"}


def install(*, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight()
    record = _read(STAGE / "stage-receipt.json")
    work = Path("library/works") / WORK_ID
    target = ROOT / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(STAGE / "stage-receipt.json") != STAGE_RECEIPT_SHA:
            raise PipelineError("Ansbert stage receipt changed under lock")
        preflight()
        return _commit_generation(
            ROOT, target, STAGE / work, work_id=WORK_ID,
            before=record["before"], after=record["after"], existed=True, replacement=False,
            operation_kind="openmgh-bsb752-ansbert-hymn-install", result_status="installed-and-validated",
            accepted_editions=1, fail_at=fail_at,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
