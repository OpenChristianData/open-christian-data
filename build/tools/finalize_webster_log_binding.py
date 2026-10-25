"""Reconcile only the caller's growing output log after all private gates pass."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from build.tools.release_webster_private import ROOT, PUB, OUT, digest, read, save
from build.tools.prepare_webster_current import WORK, EDITION, SOURCE, SOURCE_SHA, WORK_ID, LOG, DATA_NOTICE, SCOPE
from ocd_kernel.library._common import io_glob, io_path
from ocd_kernel.tei.install_accepted import _files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver-exit-code", type=int, required=True)
    args = parser.parse_args()
    if args.driver_exit_code != 1:
        raise ValueError("Expected the preserved terminal caller-log binding failure")
    if io_path(ROOT / PUB / "completion.json").exists():
        raise FileExistsError("Reconcile existing completion before writing")
    log_path = (LOG / "private-release.log").as_posix()
    log_bytes = io_path(ROOT / log_path).read_bytes()
    if b"ValueError: Final binding drift " + log_path.encode() not in log_bytes:
        raise ValueError("Terminal failure is not the scoped output-log binding defect")
    authority_before = read(OUT / "authority-before.json")
    frozen = read(OUT / "schema-implementation-before.json")
    actual = {p: digest(ROOT / p) for p in authority_before}
    drift = [p for p in authority_before if actual[p] != authority_before[p]]
    if drift != [log_path]:
        raise ValueError("Input drift exceeds the caller's output log: " + str(drift))
    for path, expected in frozen.items():
        if digest(ROOT / path) != expected:
            raise ValueError("Runtime/schema drift: " + path)
    stage = read(ROOT / LOG / "stage-pin.json")
    installed = read(ROOT / "reports/_logs/webster-install-20261002-v1/canonical/installed-audit.json")["all_hashes"]
    current = {p: h for p, h in _files(ROOT / WORK).items() if not p.startswith("publication/")}
    if current != installed or digest(ROOT / SOURCE) != SOURCE_SHA:
        raise ValueError("Installed authority/source drift")
    master_sha = stage["master_sha256"]
    if digest(ROOT / EDITION / "master.tei.xml") != master_sha:
        raise ValueError("Full accepted master differs")
    for name in ("notice-gate", "assembly", "independent-verification", "statistics", "readers", "released-notice-check"):
        if read(OUT / (name + ".json"))["status"] != "pass":
            raise ValueError("Incomplete private gate: " + name)
    command = read(OUT / "independent-projection-command.json")
    linkage = read(OUT / "independent-projection-linkage.json")
    if (command["exit_code"] != 0 or linkage["status"] != "pass" or not linkage["producer_disabled"]
            or len(linkage["cases"]) != 3 or any(c["status"] != "rejected" or c["required_diagnostic"] not in c["errors"] for c in linkage["cases"])):
        raise ValueError("Independent saved-output proof is incomplete")
    projected = read(OUT / "actual-master-projection.json")
    source = read(ROOT / SOURCE)
    expected_rows = [(b["name"], c["chapter"], v["verse"], v["text"]) for b in source["books"] for c in b["chapters"] for v in c["verses"]]
    observed_rows = [(r["locator"]["book"], r["locator"]["chapter"], r["locator"]["verse"], r["text"]) for r in projected["rows"]]
    if expected_rows != observed_rows or len(observed_rows) != 31102 or any(not r[3] for r in observed_rows):
        raise ValueError("Complete source/public tuple closure differs")
    if projected["receipt"]["authority"]["master"]["sha256"] != master_sha or projected["receipt"]["master_sha256"] != master_sha:
        raise ValueError("Projection full accepted-master binding differs")
    release = OUT / "release"
    notice = io_path(ROOT / DATA_NOTICE).read_bytes()
    visible = io_path(release / "public/README.md").read_bytes()
    if notice.rstrip() not in visible:
        raise ValueError("Full human-visible permission notice missing")
    statistics = read(OUT / "statistics.json")
    if statistics["total"]["text_characters"] != 4124143:
        raise ValueError("Private statistics differ from complete retained source")
    reconciled = {p: h for p, h in authority_before.items() if p != log_path}
    finalizer_path = Path(__file__).relative_to(ROOT).as_posix()
    frozen[finalizer_path] = digest(Path(__file__))
    reconciliation = dict(
        status="pass", checked_at=datetime.now(timezone.utc).isoformat(), original_driver_exit_code=args.driver_exit_code,
        original_authority_before_sha256=digest(OUT / "authority-before.json"),
        operational_output_log=dict(path=log_path, before_sha256=authority_before[log_path], terminal_sha256=actual[log_path]),
        only_excluded_input=log_path, all_other_input_hashes_equal=True, all_original_runtime_schema_hashes_equal=True,
        reason="The caller redirected its own growing stdout into an input directory. This operational output is not source or runtime authority. Original map, script, terminal failure, and passed outputs remain unchanged.",
        passed_pipeline_gates_reused=True, no_reprojection_reassembly_or_test_rerun=True,
        finalizer=dict(path=finalizer_path, sha256=frozen[finalizer_path]),
    )
    save(OUT / "caller-log-binding-reconciliation.json", reconciliation)
    save(OUT / "authority-inputs-reconciled.json", reconciled)
    save(OUT / "authority-after.json", reconciled)
    save(OUT / "schema-implementation-after.json", frozen)
    files = {p.relative_to(release).as_posix(): digest(p) for p in io_glob(release, "**/*") if io_path(p).is_file()}
    save(OUT / "release-file-hashes.json", files)
    evidence = {p.relative_to(OUT).as_posix(): digest(p) for p in OUT.glob("*.json")}
    completion = dict(
        status="pass", checked_at=datetime.now(timezone.utc).isoformat(), work_id=WORK_ID, scope=SCOPE,
        books=66, chapters=1189, rows=31102, empty_source_slots=0, text_characters=4124143,
        accepted_master_sha256=master_sha, projection_document_sha256=projected["receipt"]["master_sha256"],
        synthetic_projection_document_used=False, source_sha256=SOURCE_SHA, source_path=SOURCE.as_posix(),
        release_path=release.as_posix(), private_offline=True, publication_performed=False,
        authority_bindings=reconciled, schema_implementation_bindings=frozen,
        release_file_bindings=files, release_evidence_bindings=evidence,
        source_body="Unchanged historical mapper reproduced a complete source-derived d83 baseline because the disposable historical candidate is unavailable; exact header/66-label inverse restores that fresh baseline. Independent complete source oracle and coordinator comparison bound. No old-package byte reproduction claim.",
        guarded_installation="Journaled category-only prerequisite and shared guarded initial install; isolated after-new-live rollback proof bound.",
        independent_projection_producer_disabled=True, statistics_and_normal_streaming_readers="pass",
        visible_repository_license_and_translation_qualification=True,
        caller_output_log_reconciliation=reconciliation,
        remaining=["Human textual/visual acceptance not recorded", "Print identity/date/revision/annotation coverage not collated", "Underlying translation rights/jurisdiction clearance unassessed", "Public publication not authorized or performed"],
    )
    save(OUT / "completion.json", completion)
    save(ROOT / PUB / "completion.json", completion)
    print(dict(status="pass", rows=31102, text_characters=4124143, completion_sha256=digest(ROOT / PUB / "completion.json"), excluded_output_log=log_path))


if __name__ == "__main__":
    main()
