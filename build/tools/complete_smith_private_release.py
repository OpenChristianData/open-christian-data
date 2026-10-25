"""Build and verify Smith's installed electronic witness as a private offline release."""

from __future__ import annotations

import argparse
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
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/smiths-bible-dictionary")
EDITION = WORK / "forms/smiths-bible-dictionary-retained-electronic/editions/smiths-bible-dictionary-retained-electronic-witness"
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-private-release-20261002-v1"
LOG = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"
SOURCE = Path("raw/bible_dictionaries/smiths.jsonl")
DATA_NOTICE = Path("data/reference_entries/smiths-bible-dictionary/README.md")
SOURCE_CREDIT = WORK / "SOURCE_CREDIT.md"
SOURCE_NOTICE = Path("sources/reference-entries/smiths-bible-dictionary/README.source.md")
MASTER_SHA = "c4f3ff3a981f30dd816e6904af014e7eceb619d419f0f4f478fb1dcb34d43d8e"
SOURCE_SHA = "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main(installed_receipt_sha256: str) -> None:
    if OUT.exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise FileExistsError("Smith private release output or completion exists; inspect before rerun")
    install_path = LOG / "canonical-install-result.json"
    if digest(install_path) != installed_receipt_sha256:
        raise ValueError("Smith installed receipt differs from exact reviewed hash")
    installed = json.loads(install_path.read_text(encoding="utf-8"))
    if installed["status"] != "installed-and-validated" or _files(ROOT / WORK) != installed["canonical_generation"]:
        raise ValueError("Smith installed work generation drifted")
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    if digest(master) != MASTER_SHA or digest(acceptance) != installed["acceptance_sha256"] or digest(ROOT / SOURCE) != SOURCE_SHA:
        raise ValueError("Smith installed master/acceptance or retained source drifted")
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": digest(ROOT / SOURCE_NOTICE), "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": digest(ROOT / DATA_NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "smiths-bible-dictionary-private-offline-20261002-v1", "items": [{"item_id": "smiths-bible-dictionary", "category": "reference_entries", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": [notice_binding]}]}
    if notice_texts_for_item(ROOT, selection["items"][0], acceptance) != [notice]:
        raise ValueError("Smith exact visible source/rights notice gate differs")
    OUT.mkdir(parents=True)
    save(OUT / "selection.json", selection)
    save(ROOT / WORK / "publication/selection.json", selection)
    save(OUT / "notice-gate.json", {"status": "pass", "binding": notice_binding, "exact_source_directed_notice": True, "modern_structured_source_rights": "unresolved", "publication_authorized": False})
    before = {WORK.as_posix() + "/" + path: sha for path, sha in installed["canonical_generation"].items()}
    before.update({SOURCE.as_posix(): SOURCE_SHA, DATA_NOTICE.as_posix(): digest(ROOT / DATA_NOTICE), SOURCE_CREDIT.as_posix(): digest(ROOT / SOURCE_CREDIT), SOURCE_NOTICE.as_posix(): digest(ROOT / SOURCE_NOTICE), "ocd_kernel/projection/categories/reference_entries.py": digest(ROOT / "ocd_kernel/projection/categories/reference_entries.py"), "schemas/v2/categories/reference-entries.schema.json": digest(ROOT / "schemas/v2/categories/reference-entries.schema.json"), "schemas/v2/public-row.schema.json": digest(ROOT / "schemas/v2/public-row.schema.json"), "ocd_kernel/release/assemble.py": digest(ROOT / "ocd_kernel/release/assemble.py"), "ocd_kernel/release/verify.py": digest(ROOT / "ocd_kernel/release/verify.py"), "ocd_kernel/release/notices.py": digest(ROOT / "ocd_kernel/release/notices.py"), "build/tools/complete_smith_private_release.py": digest(ROOT / "build/tools/complete_smith_private_release.py")})
    save(OUT / "authority-before.json", before)
    release = OUT / "release"
    assembled = assemble_release_v2(ROOT, release, selection=selection)
    save(OUT / "assembly.json", assembled)
    if assembled["status"] != "pass":
        raise ValueError(f"Smith release assembly failed: {assembled}")
    print("assembly: PASS", flush=True)
    for name, operation in (("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)), ("statistics", lambda: release_statistics(ROOT, release, selection)), ("readers", lambda: check_reader(ROOT, release, selection))):
        result = operation()
        save(OUT / f"{name}.json", result)
        if result["status"] != "pass":
            raise ValueError(f"Smith private release {name} failed: {result}")
        print(f"{name}: PASS", flush=True)
    public_readme = (release / "public/README.md").read_text(encoding="utf-8")
    if notice.rstrip() not in public_readme:
        raise ValueError("Smith release omits visible source/rights notice")
    save(OUT / "released-notice-check.json", {"status": "pass", "notice_sha256": digest(ROOT / DATA_NOTICE), "public_readme_sha256": digest(release / "public/README.md"), "exact_notice_included": True})
    for path, expected in before.items():
        if digest(ROOT / path) != expected:
            raise ValueError(f"Smith release input drifted: {path}")
    release_files = {path.relative_to(release).as_posix(): digest(path) for path in release.rglob("*") if path.is_file()}
    save(OUT / "release-file-hashes.json", release_files)
    stats = json.loads((OUT / "statistics.json").read_text(encoding="utf-8"))
    if stats["total"]["records"] != 4560:
        raise ValueError("Smith private statistics row count differs")
    completion = {"contract": "ocd-smith-private-offline-completion-v1", "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "smiths-bible-dictionary", "source_sha256": SOURCE_SHA, "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": installed["acceptance_sha256"], "installed_receipt_sha256": installed_receipt_sha256, "selection_sha256": digest(OUT / "selection.json"), "rows": 4560, "definition_blocks": 5362, "text_characters": stats["total"]["text_characters"], "release_path": str(release), "private_offline": True, "publication_performed": False, "human_decision": "not-recorded", "rights_clearance": "unresolved", "input_bindings": before, "release_file_bindings": release_files, "notice_sha256": digest(ROOT / DATA_NOTICE)}
    save(OUT / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", completion)
    print(json.dumps({"status": "pass", "completion_sha256": digest(OUT / "completion.json"), "rows": 4560, "release_file_count": len(release_files)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-receipt-sha256", required=True)
    arguments = parser.parse_args()
    main(arguments.installed_receipt_sha256)
