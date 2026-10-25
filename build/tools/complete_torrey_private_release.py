"""Complete Torrey's accepted electronic witness as a private offline release."""

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
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/torreys-topical-textbook")
EDITION = WORK / "forms/torreys-topical-textbook-retained-electronic/editions/torreys-topical-textbook-retained-electronic-witness"
OUT = ROOT / "reports/_logs/torreys-topical-textbook-private-release-20261002-v1"
INSTALL = ROOT / "reports/_logs/torrey-current-reconciliation-20261002-v1/canonical-install-result.json"
SOURCE = Path("raw/bible_dictionaries/torreys.jsonl")
DATA_NOTICE = Path("data/topical_indexes/torreys-topical-textbook/README.md")
SOURCE_NOTICE = Path("sources/topical-indexes/torreys-topical-textbook/README.source.md")
SOURCE_CREDIT = WORK / "SOURCE_CREDIT.md"
MASTER_SHA = "06817b56c133dddd431309a0ec7b4659d4d8b66a78501953db75d9101cbb3c95"
ACCEPTANCE_SHA = "c4264703a2a8629e66f8e8bedf2a770e2ed7540ae180a7f5c3ed01e633ef2a7a"
SOURCE_SHA = "8211c20290e951f60e21187e3bdaea639c8cf59343675b6518c6c17423906a1c"
INSTALL_SHA = "aecce4d9dadc9f1b972c91e0f354dad82cd40ad1e2403eeae3facf0c533bbcde"
ADAPTER_SHA = "350431664aa1c29c9dd8e22eb0b47bd2f8bb40d1f866e7f4659d2b13d3be4261"
NOTICE_SHA = "62ae5417d1abeb81d3a04246f7ae76012fdbd25071389bfdaa4985782a026478"
SOURCE_NOTICE_SHA = "2b73f04e875475133a1663c780ae60fa5308b699035af60d753d7e49e9229017"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    if OUT.exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise FileExistsError("Torrey private release output or completion exists; inspect before rerun")
    if digest(INSTALL) != INSTALL_SHA:
        raise ValueError("Torrey guarded install receipt drifted")
    installed = json.loads(INSTALL.read_text(encoding="utf-8"))
    if installed["status"] != "installed-and-validated" or installed["journal_phase"] != "complete" or _files(ROOT / WORK) != installed["canonical_generation"]:
        raise ValueError("Torrey installed generation or completed journal differs")
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    if (digest(master) != MASTER_SHA or digest(acceptance) != ACCEPTANCE_SHA
            or digest(ROOT / SOURCE) != SOURCE_SHA
            or digest(ROOT / "ocd_kernel/projection/categories/topical_indexes.py") != ADAPTER_SHA
            or digest(ROOT / DATA_NOTICE) != NOTICE_SHA
            or digest(ROOT / SOURCE_NOTICE) != SOURCE_NOTICE_SHA):
        raise ValueError("Torrey release inputs drifted")
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": SOURCE_NOTICE_SHA, "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": NOTICE_SHA}
    selection = {"schema_version": "2.0", "release_id": "torreys-topical-textbook-private-offline-20261002-v1", "items": [{"item_id": "torreys-topical-textbook", "category": "topical_indexes", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": [notice_binding]}]}
    if notice_texts_for_item(ROOT, selection["items"][0], acceptance) != [notice]:
        raise ValueError("Torrey exact visible source/rights notice gate differs")
    OUT.mkdir(parents=True)
    save(OUT / "selection.json", selection)
    save(ROOT / WORK / "publication/selection.json", selection)
    save(OUT / "notice-gate.json", {"status": "pass", "binding": notice_binding, "exact_source_directed_notice": True, "modern_structured_source_rights": "unresolved", "publication_authorized": False})
    before = {WORK.as_posix() + "/" + path: checksum for path, checksum in installed["canonical_generation"].items()}
    before.update({SOURCE.as_posix(): SOURCE_SHA, DATA_NOTICE.as_posix(): NOTICE_SHA, SOURCE_NOTICE.as_posix(): SOURCE_NOTICE_SHA, SOURCE_CREDIT.as_posix(): digest(ROOT / SOURCE_CREDIT), "ocd_kernel/projection/categories/topical_indexes.py": ADAPTER_SHA, "schemas/v2/categories/topical-indexes.schema.json": digest(ROOT / "schemas/v2/categories/topical-indexes.schema.json"), "schemas/v2/public-row.schema.json": digest(ROOT / "schemas/v2/public-row.schema.json"), "ocd_kernel/release/assemble.py": digest(ROOT / "ocd_kernel/release/assemble.py"), "ocd_kernel/release/verify.py": digest(ROOT / "ocd_kernel/release/verify.py"), "ocd_kernel/release/notices.py": digest(ROOT / "ocd_kernel/release/notices.py"), "build/tools/complete_torrey_private_release.py": digest(ROOT / "build/tools/complete_torrey_private_release.py")})
    save(OUT / "authority-before.json", before)
    release = OUT / "release"
    assembled = assemble_release_v2(ROOT, release, selection=selection)
    save(OUT / "assembly.json", assembled)
    if assembled["status"] != "pass":
        raise ValueError(f"Torrey release assembly failed: {assembled}")
    print("assembly: PASS", flush=True)
    for name, operation in (("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)), ("statistics", lambda: release_statistics(ROOT, release, selection)), ("readers", lambda: check_reader(ROOT, release, selection))):
        result = operation()
        save(OUT / f"{name}.json", result)
        if result["status"] != "pass":
            raise ValueError(f"Torrey private release {name} failed: {result}")
        print(f"{name}: PASS", flush=True)
    public_readme = (release / "public/README.md").read_text(encoding="utf-8")
    if notice.rstrip() not in public_readme:
        raise ValueError("Torrey release omits visible source/rights notice")
    save(OUT / "released-notice-check.json", {"status": "pass", "notice_sha256": NOTICE_SHA, "public_readme_sha256": digest(release / "public/README.md"), "exact_notice_included": True})
    for path, expected in before.items():
        if path == (WORK / "publication/selection.json").as_posix():
            continue
        if digest(ROOT / path) != expected:
            raise ValueError(f"Torrey release input drifted: {path}")
    release_files = {path.relative_to(release).as_posix(): digest(path) for path in release.rglob("*") if path.is_file()}
    save(OUT / "release-file-hashes.json", release_files)
    stats = json.loads((OUT / "statistics.json").read_text(encoding="utf-8"))
    completion = {"contract": "ocd-torrey-private-offline-completion-v1", "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "torreys-topical-textbook", "source_sha256": SOURCE_SHA, "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": ACCEPTANCE_SHA, "installed_receipt_sha256": INSTALL_SHA, "selection_sha256": digest(OUT / "selection.json"), "rows": 623, "definition_blocks": 23549, "text_characters": stats["total"]["text_characters"], "release_path": str(release), "private_offline": True, "publication_performed": False, "human_decision": "not-recorded", "rights_clearance": "unresolved", "input_bindings": before, "release_file_bindings": release_files, "notice_sha256": NOTICE_SHA}
    save(OUT / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", completion)
    print(json.dumps({"status": "pass", "completion_sha256": digest(OUT / "completion.json"), "rows": 623, "release_file_count": len(release_files)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
