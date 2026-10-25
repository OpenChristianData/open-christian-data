"""Complete Easton's installed electronic witness as a private offline release."""

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
WORK = Path("library/works/eastons-bible-dictionary")
EDITION = WORK / "forms/eastons-bible-dictionary-retained-electronic/editions/eastons-bible-dictionary-retained-electronic-witness"
OUT = ROOT / "reports/_logs/eastons-bible-dictionary-private-release-20261002-v1"
SOURCE = Path("raw/bible_dictionaries/eastons.jsonl")
DATA_NOTICE = Path("data/reference_entries/eastons-bible-dictionary/README.md")
SOURCE_CREDIT = WORK / "SOURCE_CREDIT.md"
SOURCE_NOTICE = Path("sources/reference-entries/eastons-bible-dictionary/README.source.md")
MASTER_SHA = "11e86481620c1edea9bdf6a291ef4cd7bb83bbc4324838a78ed1062722feb257"
ACCEPTANCE_SHA = "fd18e567c63a57bccbfbb4d0778abcedab8afd89d64c72c026196c86ce218f83"
SOURCE_SHA = "978e09fdb66e9c6b722085f868c0cc84030df9e15c6188a06390f3822888082a"
INSTALL_SHA = "ca78c8f90d66e4f36a317f038b4a23ff548860eff774f8b2d0d6c70dda82d436"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    if OUT.exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise FileExistsError("Easton private release output or completion exists; inspect before rerun")
    install = ROOT / "reports/_logs/eastons-bible-dictionary-current-reconciliation-20261002-v1/canonical-install-result.json"
    if digest(install) != INSTALL_SHA:
        raise ValueError("Easton guarded install receipt drifted")
    installed = json.loads(install.read_text(encoding="utf-8"))
    if installed["status"] != "installed-and-validated" or _files(ROOT / WORK) != installed["canonical_generation"]:
        raise ValueError("Easton installed work generation drifted")
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    if digest(master) != MASTER_SHA or digest(acceptance) != ACCEPTANCE_SHA or digest(ROOT / SOURCE) != SOURCE_SHA:
        raise ValueError("Easton installed master/acceptance or retained source drifted")
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": digest(ROOT / SOURCE_NOTICE), "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": digest(ROOT / DATA_NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "eastons-bible-dictionary-private-offline-20261002-v1", "items": [{"item_id": "eastons-bible-dictionary", "category": "reference_entries", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": [notice_binding]}]}
    if notice_texts_for_item(ROOT, selection["items"][0], acceptance) != [notice]:
        raise ValueError("Easton exact visible source/rights notice gate differs")
    OUT.mkdir(parents=True)
    save(OUT / "selection.json", selection)
    save(ROOT / WORK / "publication/selection.json", selection)
    save(OUT / "notice-gate.json", {"status": "pass", "binding": notice_binding, "exact_source_directed_notice": True, "modern_structured_source_rights": "unresolved", "publication_authorized": False})
    before = {WORK.as_posix() + "/" + path: sha for path, sha in installed["canonical_generation"].items()}
    before.update({SOURCE.as_posix(): SOURCE_SHA, DATA_NOTICE.as_posix(): digest(ROOT / DATA_NOTICE), SOURCE_CREDIT.as_posix(): digest(ROOT / SOURCE_CREDIT), SOURCE_NOTICE.as_posix(): digest(ROOT / SOURCE_NOTICE), "ocd_kernel/projection/categories/reference_entries.py": digest(ROOT / "ocd_kernel/projection/categories/reference_entries.py"), "schemas/v2/categories/reference-entries.schema.json": digest(ROOT / "schemas/v2/categories/reference-entries.schema.json"), "schemas/v2/public-row.schema.json": digest(ROOT / "schemas/v2/public-row.schema.json"), "ocd_kernel/release/assemble.py": digest(ROOT / "ocd_kernel/release/assemble.py"), "ocd_kernel/release/verify.py": digest(ROOT / "ocd_kernel/release/verify.py"), "ocd_kernel/release/notices.py": digest(ROOT / "ocd_kernel/release/notices.py"), "build/tools/complete_easton_private_release.py": digest(ROOT / "build/tools/complete_easton_private_release.py")})
    save(OUT / "authority-before.json", before)
    release = OUT / "release"
    assembled = assemble_release_v2(ROOT, release, selection=selection)
    save(OUT / "assembly.json", assembled)
    if assembled["status"] != "pass":
        raise ValueError(f"Easton release assembly failed: {assembled}")
    print("assembly: PASS", flush=True)
    for name, operation in (("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)), ("statistics", lambda: release_statistics(ROOT, release, selection)), ("readers", lambda: check_reader(ROOT, release, selection))):
        result = operation()
        save(OUT / f"{name}.json", result)
        if result["status"] != "pass":
            raise ValueError(f"Easton private release {name} failed: {result}")
        print(f"{name}: PASS", flush=True)
    public_readme = (release / "public/README.md").read_text(encoding="utf-8")
    if notice.rstrip() not in public_readme:
        raise ValueError("Easton release omits visible source/rights notice")
    save(OUT / "released-notice-check.json", {"status": "pass", "notice_sha256": digest(ROOT / DATA_NOTICE), "public_readme_sha256": digest(release / "public/README.md"), "exact_notice_included": True})
    for path, expected in before.items():
        if digest(ROOT / path) != expected:
            raise ValueError(f"Easton release input drifted: {path}")
    release_files = {path.relative_to(release).as_posix(): digest(path) for path in release.rglob("*") if path.is_file()}
    save(OUT / "release-file-hashes.json", release_files)
    stats = json.loads((OUT / "statistics.json").read_text(encoding="utf-8"))
    completion = {"contract": "ocd-easton-private-offline-completion-v1", "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "eastons-bible-dictionary", "source_sha256": SOURCE_SHA, "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": ACCEPTANCE_SHA, "installed_receipt_sha256": INSTALL_SHA, "selection_sha256": digest(OUT / "selection.json"), "rows": 3963, "definition_blocks": 7464, "text_characters": stats["total"]["text_characters"], "release_path": str(release), "private_offline": True, "publication_performed": False, "human_decision": "not-recorded", "rights_clearance": "unresolved", "input_bindings": before, "release_file_bindings": release_files, "notice_sha256": digest(ROOT / DATA_NOTICE)}
    save(OUT / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", completion)
    print(json.dumps({"status": "pass", "completion_sha256": digest(OUT / "completion.json"), "rows": 3963, "release_file_count": len(release_files)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
