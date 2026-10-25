"""Release Equiano's installed two-volume ECCO witness privately with visible credit."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library.state import validate_state
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/equiano-interesting-narrative-1789")
EDITION = WORK / "forms/equiano-english/editions/ecco-second-edition"
MEMBERS = WORK / "integration/reviewed-equiano-v1/source-member-set.json"
SOURCE_NOTICE = Path("sources/publication-equiano/equiano-interesting-narrative-1789/README.source.md")
DATA_NOTICE = Path("data/prose/equiano-interesting-narrative-1789/README.md")
OLD = Path("exports/releases/native-seven-works-20260911-03")
OUT = ROOT / "reports/_logs/equiano-private-release-20261002-v1"
EXPECTED = {
    (WORK / "work.json").as_posix(): "88ea712da6b876b2e545b0d27fe22f7225ccd41587fac42c9f8fb32e7f61669a",
    (WORK / "state.json").as_posix(): "12c8744cb051a5a671ec9c3e4c7efd1fe0ba8bef083d2e7d9f949dccc3023101",
    (EDITION / "master.tei.xml").as_posix(): "b6e7272ada2ccd203b54b6c446b2a8dd254a5a459f9811d515dd2c9e5e4bcaaa",
    (EDITION / "acceptance.json").as_posix(): "e7034a3d3b630a935ade9baaf689ae9eec59618ee24d0534e99e64b38376dae4",
    (EDITION / "acquisitions/ecco-two-volumes.json").as_posix(): "a8f062a950e8823813f688d4b7b0fd3e6703126271c8cc50aedea04a2ca08dc0",
    MEMBERS.as_posix(): "fcb4bb4c6096482dc0d26683469b2e6f2289bc32beb67ee9a3889ee9738425d0",
    "raw/clean-ready-acquisition-to-tei/master-2/15/equiano-interesting-narrative-1789-part-1/K053415.001.xml": "5c56b75866f4ad20acee1308c92c1fd8e87e89acd29f897ed402a21b6b62010f",
    "raw/clean-ready-acquisition-to-tei/master-2/15/equiano-interesting-narrative-1789-part-2/K053415.002.xml": "f8898fcc3e788196168593f3c6bdd12e3ef9cbcba9328091917073ffa305c5ed",
    SOURCE_NOTICE.as_posix(): "aff442f5cd78b0ad8099a1a26a41cc38f146b39fef9bb27780be570b75f344f7",
    DATA_NOTICE.as_posix(): "2706e1886f0069d52cccaa447c785d57e713b4fee14b1bafaa16589caabb7536",
    (OLD / "internal/release-selection.json").as_posix(): "7f98e3aacd14bc482d6cfbd5157b819eba7ffbfb1f1646b43efd8b6bce35619e",
    (OLD / "internal/release-report.json").as_posix(): "fd2eab871c6f6aa5d4166fc5f2f233a056ee0eb40a1c7f27aad0af165f2be8fc",
    (OLD / "internal/projection-receipts/equiano-interesting-narrative-1789.json").as_posix(): "e7decd7b0207bfa006b6d430b762d0a2b8805bccf1644f7ff36a28e7a1327999",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    if OUT.exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise FileExistsError("Equiano release output or completion exists; inspect before rerun")
    for relative, expected in EXPECTED.items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Equiano accepted authority, source, notice or historical release changed: {relative}")
    acceptance = ROOT / EDITION / "acceptance.json"
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    old_selection = json.loads((ROOT / OLD / "internal/release-selection.json").read_text(encoding="utf-8"))
    old_report = json.loads((ROOT / OLD / "internal/release-report.json").read_text(encoding="utf-8"))
    old_items = [item for item in old_selection["items"] if item["item_id"] == WORK.name]
    old_results = [item for item in old_report["items"] if item["item_id"] == WORK.name]
    if (len(old_items) != 1 or len(old_results) != 1 or old_results[0]["row_count"] != 23
            or old_results[0]["status"] != "warned" or old_report["status"] != "pass"):
        raise ValueError("Historical Equiano seven-work item differs")
    old_receipt = json.loads((ROOT / OLD / "internal/projection-receipts/equiano-interesting-narrative-1789.json").read_text(encoding="utf-8"))
    if old_receipt["row_count"] != 23 or any(
        digest(ROOT / bound["path"]) != bound["sha256"] for bound in old_receipt["authority"].values()
    ):
        raise ValueError("Historical Equiano projection receipt no longer binds accepted authority")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": EXPECTED[SOURCE_NOTICE.as_posix()],
                      "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": EXPECTED[DATA_NOTICE.as_posix()]}
    selection = {"schema_version": "2.0", "release_id": "equiano-private-offline-20261002-v1",
                 "items": [{"item_id": WORK.name, "category": "prose",
                            "acceptance_path": (EDITION / "acceptance.json").as_posix(),
                            "public_notices": [notice_binding]}]}
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    if notice_texts_for_item(ROOT, selection["items"][0], acceptance) != [notice]:
        raise ValueError("Equiano source-directed public notice differs")
    if not all(value in notice for value in ("Text Creation Partnership", "University of Michigan Library",
                                             "CC0 1.0 Universal", "older distribution-permission", "rights clearance")):
        raise ValueError("Equiano notice omits attribution or unresolved terms")
    inputs = dict(EXPECTED)
    for relative in (
        "build/tools/complete_equiano_private_release.py",
        "ocd_kernel/projection/categories/prose.py",
        "ocd_kernel/projection/native_content.py",
        "ocd_kernel/projection/native_content_check.py",
        "ocd_kernel/release/assemble.py",
        "ocd_kernel/release/verify.py",
        "ocd_kernel/release/notices.py",
        "ocd_kernel/tei/acceptance.py",
        "schemas/v2/categories/prose.schema.json",
        "schemas/v2/public-row.schema.json",
        "schemas/v2/release-selection.schema.json",
    ):
        inputs[relative] = digest(ROOT / relative)
    OUT.mkdir(parents=True)
    save(OUT / "selection.json", selection)
    save(OUT / "authority-before.json", inputs)
    save(OUT / "historical-release-context.json", {
        "status": "historical-technical-release-byte-bound",
        "selection_sha256": EXPECTED[(OLD / "internal/release-selection.json").as_posix()],
        "report_sha256": EXPECTED[(OLD / "internal/release-report.json").as_posix()],
        "equiano_receipt_sha256": EXPECTED[(OLD / "internal/projection-receipts/equiano-interesting-narrative-1789.json").as_posix()],
        "equiano_rows": 23,
        "reason_for_current_release": "Historical group release omitted the source-directed Equiano public notice.",
    })
    release = OUT / "release"
    assembly = assemble_release_v2(ROOT, release, selection=selection)
    save(OUT / "assembly.json", assembly)
    if (assembly["status"] != "pass" or len(assembly["items"]) != 1
            or assembly["items"][0]["item_id"] != WORK.name
            or assembly["items"][0]["category"] != "prose"
            or assembly["items"][0]["row_count"] != 23
            or assembly["items"][0]["status"] not in {"included", "warned"}):
        raise ValueError("Equiano one-work assembly differs from accepted scope")
    print("assembly: PASS", flush=True)
    for name, operation in (
        ("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)),
        ("statistics", lambda: release_statistics(ROOT, release, selection)),
        ("readers", lambda: check_reader(ROOT, release, selection)),
    ):
        result = operation()
        save(OUT / f"{name}.json", result)
        if result["status"] != "pass":
            raise ValueError(f"Equiano private release {name} failed")
        print(f"{name}: PASS", flush=True)
    if notice.rstrip() not in (release / "public/README.md").read_text(encoding="utf-8"):
        raise ValueError("Equiano release omitted visible TCP/Michigan source credit")
    for relative, expected in inputs.items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Equiano release input drifted: {relative}")
    files = {path.relative_to(release).as_posix(): digest(path) for path in release.rglob("*") if path.is_file()}
    save(OUT / "release-file-hashes.json", files)
    stats = json.loads((OUT / "statistics.json").read_text(encoding="utf-8"))
    completion = {"contract": "ocd-equiano-private-offline-completion-v1", "status": "pass",
                  "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": WORK.name,
                  "accepted_master_sha256": EXPECTED[(EDITION / "master.tei.xml").as_posix()],
                  "acceptance_sha256": EXPECTED[(EDITION / "acceptance.json").as_posix()],
                  "ordered_member_set_sha256": EXPECTED[MEMBERS.as_posix()],
                  "selection_sha256": digest(OUT / "selection.json"),
                  "rows": 23, "text_characters": stats["total"]["text_characters"],
                  "source_notice_sha256": EXPECTED[SOURCE_NOTICE.as_posix()],
                  "public_notice_sha256": EXPECTED[DATA_NOTICE.as_posix()],
                  "historical_group_report_sha256": EXPECTED[(OLD / "internal/release-report.json").as_posix()],
                  "release_path": str(release), "private_offline": True,
                  "publication_performed": False, "human_decision": "not-recorded",
                  "rights_clearance": "unresolved", "print_image_collation": "not-asserted",
                  "input_bindings": inputs, "release_file_bindings": files}
    save(OUT / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", completion)
    print(json.dumps({"status": "pass", "rows": 23,
                      "completion_sha256": digest(OUT / "completion.json"),
                      "release_file_count": len(files)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
