"""Complete Anne Askew's accepted first TCP text as a private offline release."""

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
WORK = Path("library/works/anne-askew-first-examinacyon")
EDITION = WORK / "forms/anne-askew-first-examinacyon-tcp-retained/editions/anne-askew-first-examinacyon-tcp-electronic"
OUT = ROOT / "reports/_logs/anne-askew-first-private-release-20261002-v1"
SOURCE = Path("raw/tcp/high-range/A22076/A22076.xml")
DATA_NOTICE = Path("data/prose/anne-askew-first-examinacyon/README.md")
SOURCE_NOTICE = Path("sources/prose/anne-askew-first-examinacyon/README.source.md")
SOURCE_CREDIT = WORK / "SOURCE_CREDIT.md"
COORDINATOR_SOURCE = Path("reports/_logs/anne-first-coordinator-source-review-20261002-v1/review.json")
SOURCE_SHA = "211a2c0d5029ca1dc6622b419fea356a0bba0ee28a363bd8c4e28331b3b6f92a"
MASTER_SHA = "e3012ca8c173057f609ae3a20645ed76ac6c17cd44dcfeca3b4cfcb074e0c446"
ACCEPTANCE_SHA = "8303c0900082c4711ffc1939d6e89f8e73ea6021f03c4cc01d81125379067869"
WORK_SHA = "e06fef5468358bf89752753352e848391039747409fd95015b41c511c88b44fd"
SOURCE_CONTEXT_SHA = "e9335890d84ab37fe37252ee6056a4430e86889c7b0ba3f37ab5ca275196f855"
PROJECTION_PROOF_SHA = "180523f96cce44dcac5362aaca11a50eb7f4955c972c9abb20cdd69207c4ad77"
HISTORICAL_RECON_SHA = "a77c6d1f9503c254248d65ef3a80d69df4405e4a2e148503a10bcff55470a214"
COORDINATOR_SOURCE_SHA = "d69b6b5602f60d476f5b1c687a367632d49cf98d1163304e126215e45b1446b4"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    if (OUT / "release").exists() or (OUT / "completion.json").exists() or (ROOT / WORK / "publication/completion.json").exists():
        raise FileExistsError("Anne first release or completion exists; inspect before rerun")
    authority = {
        ROOT / SOURCE: SOURCE_SHA,
        ROOT / EDITION / "master.tei.xml": MASTER_SHA,
        ROOT / EDITION / "acceptance.json": ACCEPTANCE_SHA,
        ROOT / WORK / "work.json": WORK_SHA,
        OUT / "source-context.json": SOURCE_CONTEXT_SHA,
        OUT / "actual-master-projection-proof.json": PROJECTION_PROOF_SHA,
        OUT / "historical-release-reconciliation.json": HISTORICAL_RECON_SHA,
        ROOT / COORDINATOR_SOURCE: COORDINATOR_SOURCE_SHA,
    }
    for path, expected in authority.items():
        if digest(path) != expected:
            raise ValueError(f"Anne first release authority drifted: {path}")
    acceptance = ROOT / EDITION / "acceptance.json"
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    notice = (ROOT / DATA_NOTICE).read_text(encoding="utf-8")
    notice_binding = {"source_path": SOURCE_NOTICE.as_posix(), "source_sha256": digest(ROOT / SOURCE_NOTICE), "notice_path": DATA_NOTICE.as_posix(), "notice_sha256": digest(ROOT / DATA_NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "anne-askew-first-private-offline-20261002-v1", "items": [{"item_id": "anne-askew-first-examinacyon", "category": "prose", "acceptance_path": (EDITION / "acceptance.json").as_posix(), "public_notices": [notice_binding]}]}
    if notice_texts_for_item(ROOT, selection["items"][0], acceptance) != [notice]:
        raise ValueError("Anne first exact source-directed notice differs")
    OUT.mkdir(parents=True, exist_ok=True)
    save(OUT / "selection.json", selection)
    save(ROOT / WORK / "publication/selection.json", selection)
    save(OUT / "notice-gate.json", {"status": "pass", "binding": notice_binding, "source_text_rights": "TCP Phase I CC0 1.0 Universal", "page_images": "not-assessed", "public_publication_authorized": False})
    before = {WORK.as_posix() + "/" + path: sha for path, sha in _files(ROOT / WORK).items() if path != "publication/selection.json"}
    extra = [SOURCE, DATA_NOTICE, SOURCE_NOTICE, SOURCE_CREDIT, COORDINATOR_SOURCE,
             Path("ocd_kernel/projection/categories/prose.py"), Path("ocd_kernel/projection/categories/native_documents.py"),
             Path("ocd_kernel/release/assemble.py"), Path("ocd_kernel/release/verify.py"), Path("ocd_kernel/release/notices.py"),
             Path("schemas/v2/categories/prose.schema.json"), Path("schemas/v2/public-row.schema.json"),
             Path("build/tools/complete_anne_first_private_release.py")]
    before.update({path.as_posix(): digest(ROOT / path) for path in extra})
    before.update({"reports/_logs/anne-askew-first-private-release-20261002-v1/source-context.json": SOURCE_CONTEXT_SHA,
                   "reports/_logs/anne-askew-first-private-release-20261002-v1/actual-master-projection-proof.json": PROJECTION_PROOF_SHA,
                   "reports/_logs/anne-askew-first-private-release-20261002-v1/historical-release-reconciliation.json": HISTORICAL_RECON_SHA})
    save(OUT / "authority-before.json", before)
    release = OUT / "release"
    assembled = assemble_release_v2(ROOT, release, selection=selection)
    save(OUT / "assembly.json", assembled)
    if assembled["status"] != "pass":
        raise ValueError(f"Anne first release assembly failed: {assembled}")
    print("assembly: PASS", flush=True)
    for name, operation in (("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)), ("statistics", lambda: release_statistics(ROOT, release, selection)), ("readers", lambda: check_reader(ROOT, release, selection))):
        result = operation()
        save(OUT / f"{name}.json", result)
        if result["status"] != "pass":
            raise ValueError(f"Anne first private release {name} failed: {result}")
        print(f"{name}: PASS", flush=True)
    if notice.rstrip() not in (release / "public/README.md").read_text(encoding="utf-8"):
        raise ValueError("Anne first release omits visible source/rights notice")
    save(OUT / "released-notice-check.json", {"status": "pass", "notice_sha256": digest(ROOT / DATA_NOTICE), "public_readme_sha256": digest(release / "public/README.md"), "exact_notice_included": True})
    for label, expected in before.items():
        if digest(ROOT / label) != expected:
            raise ValueError(f"Anne first release input drifted: {label}")
    release_files = {path.relative_to(release).as_posix(): digest(path) for path in release.rglob("*") if path.is_file()}
    save(OUT / "release-file-hashes.json", release_files)
    stats = json.loads((OUT / "statistics.json").read_text(encoding="utf-8"))
    if stats["total"]["records"] != 7:
        raise ValueError("Anne first private statistics row count differs")
    completion = {"contract": "ocd-anne-first-private-offline-completion-v1", "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "anne-askew-first-examinacyon", "source_sha256": SOURCE_SHA, "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": ACCEPTANCE_SHA, "selection_sha256": digest(OUT / "selection.json"), "rows": 7, "text_characters": stats["total"]["text_characters"], "release_path": str(release), "private_offline": True, "publication_performed": False, "human_decision": "not-recorded", "rights_context": "TCP Phase I electronic text CC0; page images not assessed", "input_bindings": before, "release_file_bindings": release_files, "notice_sha256": digest(ROOT / DATA_NOTICE), "coordinator_source_review_sha256": COORDINATOR_SOURCE_SHA}
    save(OUT / "completion.json", completion)
    save(ROOT / WORK / "publication/completion.json", completion)
    print(json.dumps({"status": "pass", "completion_sha256": digest(OUT / "completion.json"), "rows": 7, "release_file_count": len(release_files)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
