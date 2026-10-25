"""Privately release the already installed Baltimore Catechism No. 2 witness."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.catechisms import _validate_rows, project_accepted_catechisms
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/baltimore-catechism-no-2")
EDITION = WORK / "forms/baltimore-catechism-no-2-retained-electronic/editions/baltimore-catechism-no-2-retained-electronic-witness"
SOURCE = Path("raw/gutenberg/pg14552.txt")
SOURCE_NOTICE = Path("sources/publication-pg14552/baltimore-catechism-no-2/README.source.md")
DATA_NOTICE = Path("data/catechisms/baltimore-catechism-no-2/README.md")
OUT = ROOT / "reports/_logs/baltimore-catechism-no-2-private-release-20261002-v1"
SOURCE_SHA = "3d4b556fdb094ab8e22a53df85f60ba3310b49c9c65a24281aeecb9119f9746c"
MASTER_SHA = "4fc5e90d05ff20d9c19576b64fcdac87585de711927e393afad3ac81b99d7226"
ACCEPTANCE_SHA = "d2627965dbba37fa5f9076170e38f43f7aee40fc6052d07fed55fb06149384c9"
SOURCE_NOTICE_SHA = "afc24a516a290fb8ff3fc3a1abcc21b554e048b61b471170c8b8d5552d177960"
DATA_NOTICE_SHA = "e8fdd084cf2153dd477297e75d0b6190996e5aa0b1333a11ffda469e6a665c01"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


INDEPENDENT_CHECK = r"""
import hashlib, json, sys
from pathlib import Path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import catechisms
from ocd_kernel.projection import native_content

def unavailable(*args, **kwargs):
    raise AssertionError('Catechism producer invoked by independent checker')

catechisms.project_accepted_catechisms = unavailable
catechisms.project_catechism_document = unavailable
catechisms._project_native_accepted_catechism = unavailable
native_content.project_content = unavailable
native_content.readable_content = unavailable
root, acceptance, projected = map(Path, sys.argv[1:])
raw = projected.read_bytes()
value = json.loads(raw)
with cached_edition_lookups():
    errors = catechisms.verify_accepted_catechisms(root, acceptance_path=acceptance, rows=value['rows'], receipt=value['receipt'])
print(json.dumps({'status': 'fail' if errors else 'pass', 'errors': errors, 'producer_disabled': True, 'saved_projection_sha256': hashlib.sha256(raw).hexdigest()}))
raise SystemExit(bool(errors))
"""


def main() -> None:
    if OUT.exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise FileExistsError("Baltimore No. 2 release output or completion exists; inspect before rerun")
    master = ROOT / EDITION / "master.tei.xml"
    acceptance = ROOT / EDITION / "acceptance.json"
    expected = {
        SOURCE.as_posix(): SOURCE_SHA,
        (EDITION / "master.tei.xml").as_posix(): MASTER_SHA,
        (EDITION / "acceptance.json").as_posix(): ACCEPTANCE_SHA,
        SOURCE_NOTICE.as_posix(): SOURCE_NOTICE_SHA,
        DATA_NOTICE.as_posix(): DATA_NOTICE_SHA,
    }
    for path, sha in expected.items():
        if digest(ROOT / path) != sha:
            raise ValueError(f"Baltimore No. 2 source, master, acceptance or notice drifted: {path}")
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": SOURCE_NOTICE_SHA,
                      "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": DATA_NOTICE_SHA}
    selection = {"schema_version": "2.0", "release_id": "baltimore-catechism-no-2-private-offline-20261002-v1",
                 "items": [{"item_id": "baltimore-catechism-no-2", "category": "catechisms",
                            "acceptance_path": (EDITION / "acceptance.json").as_posix(),
                            "public_notices": [notice_binding]}]}
    if notice_texts_for_item(ROOT, selection["items"][0], acceptance) != [notice]:
        raise ValueError("Exact source-directed Baltimore No. 2 notice gate differs")
    if not all(token in notice for token in ("Dennis McCarthy", "J. De Concilio", "Bellarmino",
                                             "START: FULL LICENSE", "rights clearance")):
        raise ValueError("Baltimore No. 2 notice lacks a required source credit or qualification")
    OUT.mkdir(parents=True)
    save(OUT / "selection.json", selection)
    save(ROOT / WORK / "publication/selection.json", selection)
    save(OUT / "notice-gate.json", {"status": "pass", "binding": notice_binding,
                                     "source_directed_full_retained_license": True,
                                     "rights_clearance": "unresolved", "publication_authorized": False})
    inputs = {
        **expected,
        (WORK / "work.json").as_posix(): digest(ROOT / WORK / "work.json"),
        (WORK / "state.json").as_posix(): digest(ROOT / WORK / "state.json"),
        (EDITION / "acquisitions/baltimore-catechism-no-2-retained-source.json").as_posix(): digest(ROOT / EDITION / "acquisitions/baltimore-catechism-no-2-retained-source.json"),
    }
    for relative in (
        "build/tools/complete_baltimore2_private_release.py",
        "build/tools/prepare_baltimore2_private_notices.py",
        "ocd_kernel/projection/categories/catechisms.py",
        "ocd_kernel/projection/native_content.py",
        "ocd_kernel/projection/native_content_check.py",
        "ocd_kernel/release/assemble.py",
        "ocd_kernel/release/verify.py",
        "ocd_kernel/release/notices.py",
        "ocd_kernel/tei/acceptance.py",
        "schemas/v2/categories/catechisms.schema.json",
        "schemas/v2/public-row.schema.json",
        "schemas/v2/release-selection.schema.json",
    ):
        inputs[relative] = digest(ROOT / relative)
    save(OUT / "authority-before.json", inputs)
    with cached_edition_lookups():
        projection = project_accepted_catechisms(ROOT, acceptance_path=acceptance)
    _validate_rows(projection["rows"])
    if len(projection["rows"]) != 1 or projection["receipt"]["master_sha256"] != MASTER_SHA:
        raise ValueError("Baltimore No. 2 complete actual-master projection differs")
    row = projection["rows"][0]
    if row["source_line_count"] != 3675 or len(row["question_answers"]) != 421:
        raise ValueError("Baltimore No. 2 complete source/QA census differs")
    save(OUT / "actual-master-projection.json", projection)
    process = subprocess.run([sys.executable, "-B", "-c", INDEPENDENT_CHECK, str(ROOT), str(acceptance),
                              str(OUT / "actual-master-projection.json")], cwd=ROOT, check=True,
                             capture_output=True, text=True, encoding="utf-8")
    independent = json.loads(process.stdout)
    if independent["status"] != "pass" or not independent["producer_disabled"]:
        raise ValueError("Baltimore No. 2 independent projection differs")
    save(OUT / "independent-projection.json", independent)
    print("actual-master-projection: PASS", flush=True)
    release = OUT / "release"
    assembled = assemble_release_v2(ROOT, release, selection=selection)
    save(OUT / "assembly.json", assembled)
    if assembled["status"] != "pass":
        raise ValueError("Baltimore No. 2 private assembly failed")
    print("assembly: PASS", flush=True)
    for name, operation in (
        ("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)),
        ("statistics", lambda: release_statistics(ROOT, release, selection)),
        ("readers", lambda: check_reader(ROOT, release, selection)),
    ):
        result = operation()
        save(OUT / f"{name}.json", result)
        if result["status"] != "pass":
            raise ValueError(f"Baltimore No. 2 private release {name} failed")
        print(f"{name}: PASS", flush=True)
    if notice.rstrip() not in (release / "public/README.md").read_text(encoding="utf-8"):
        raise ValueError("Baltimore No. 2 release omits the complete visible notice")
    for path, sha in inputs.items():
        if digest(ROOT / path) != sha:
            raise ValueError(f"Baltimore No. 2 release input drifted: {path}")
    files = {path.relative_to(release).as_posix(): digest(path) for path in release.rglob("*") if path.is_file()}
    save(OUT / "release-file-hashes.json", files)
    stats = json.loads((OUT / "statistics.json").read_text(encoding="utf-8"))
    completion = {"contract": "ocd-baltimore2-private-offline-completion-v1", "status": "pass",
                  "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "baltimore-catechism-no-2",
                  "source_sha256": SOURCE_SHA, "accepted_master_sha256": MASTER_SHA,
                  "acceptance_sha256": ACCEPTANCE_SHA, "selection_sha256": digest(OUT / "selection.json"),
                  "saved_projection_sha256": digest(OUT / "actual-master-projection.json"),
                  "independent_projection_sha256": digest(OUT / "independent-projection.json"),
                  "rows": 1, "source_lines": 3675, "question_answer_groups": 421,
                  "text_characters": stats["total"]["text_characters"], "release_path": str(release),
                  "private_offline": True, "publication_performed": False, "human_decision": "not-recorded",
                  "rights_clearance": "unresolved", "notice_sha256": DATA_NOTICE_SHA,
                  "input_bindings": inputs, "release_file_bindings": files}
    save(OUT / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", completion)
    print(json.dumps({"status": "pass", "completion_sha256": digest(OUT / "completion.json"),
                      "rows": 1, "release_file_count": len(files)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
