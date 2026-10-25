"""Prove current accepted Anne first prose projection and visible notice."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.projection.categories import prose
from ocd_kernel.release.notices import notice_texts_for_item


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/anne-askew-first-examinacyon"
EDITION = WORK / "forms/anne-askew-first-examinacyon-tcp-retained/editions/anne-askew-first-examinacyon-tcp-electronic"
OUT = ROOT / "reports/_logs/anne-askew-first-private-release-20261002-v1"
MASTER_SHA = "e3012ca8c173057f609ae3a20645ed76ac6c17cd44dcfeca3b4cfcb074e0c446"
ACCEPTANCE_SHA = "8303c0900082c4711ffc1939d6e89f8e73ea6021f03c4cc01d81125379067869"
WORK_SHA = "e06fef5468358bf89752753352e848391039747409fd95015b41c511c88b44fd"
SOURCE_CONTEXT_SHA = "e9335890d84ab37fe37252ee6056a4430e86889c7b0ba3f37ab5ca275196f855"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    acceptance = EDITION / "acceptance.json"
    if (digest(EDITION / "master.tei.xml") != MASTER_SHA or digest(acceptance) != ACCEPTANCE_SHA
            or digest(WORK / "work.json") != WORK_SHA or digest(OUT / "source-context.json") != SOURCE_CONTEXT_SHA):
        raise ValueError("Anne projection current authority drifted")
    notice_path = ROOT / "data/prose/anne-askew-first-examinacyon/README.md"
    source_path = ROOT / "sources/prose/anne-askew-first-examinacyon/README.source.md"
    notice_binding = {"source_path": source_path.relative_to(ROOT).as_posix(), "source_sha256": digest(source_path), "notice_path": notice_path.relative_to(ROOT).as_posix(), "notice_sha256": digest(notice_path)}
    item = {"item_id": "anne-askew-first-examinacyon", "category": "prose", "acceptance_path": acceptance.relative_to(ROOT).as_posix(), "public_notices": [notice_binding]}
    notice = notice_path.read_text(encoding="utf-8")
    if notice_texts_for_item(ROOT, item, acceptance) != [notice]:
        raise ValueError("Anne source-directed public notice differs")
    projection = prose.project_accepted_prose(ROOT, acceptance_path=acceptance)
    rows = projection["rows"]
    receipt = projection["receipt"]
    if not rows or not isinstance(receipt, dict) or any(row.get("work_id") != "anne-askew-first-examinacyon" for row in rows):
        raise ValueError("Anne first projection rows/receipt differ")

    def disabled(*args: object, **kwargs: object) -> None:
        raise AssertionError("Producer called during independent accepted prose check")

    prose.project_accepted_prose = disabled
    errors = prose.verify_accepted_prose(ROOT, acceptance_path=acceptance, rows=rows, receipt=receipt)
    if errors:
        raise ValueError(f"Anne independent native prose checker failed: {errors[:5]}")
    save(OUT / "actual-master-projection.json", projection)
    save(OUT / "actual-master-projection-receipt.json", receipt)
    proof = {
        "contract": "ocd-anne-first-actual-master-projection-v1",
        "status": "pass",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": "anne-askew-first-examinacyon",
        "master_sha256": MASTER_SHA,
        "acceptance_sha256": ACCEPTANCE_SHA,
        "source_context_sha256": SOURCE_CONTEXT_SHA,
        "work_metadata_sha256": WORK_SHA,
        "rows": len(rows),
        "text_characters": sum(len(row.get("text", "")) for row in rows),
        "receipt_inventory_count": len(receipt.get("inventory", [])),
        "warnings": receipt.get("warnings", []),
        "projection_sha256": digest(OUT / "actual-master-projection.json"),
        "receipt_sha256": digest(OUT / "actual-master-projection-receipt.json"),
        "independent_checker": "pass with accepted prose producer disabled",
        "notice_sha256": digest(notice_path),
        "source_notice_sha256": digest(source_path),
        "source_reconstruction_performed": False,
    }
    save(OUT / "actual-master-projection-proof.json", proof)
    print(json.dumps({"status": "pass", "rows": proof["rows"], "inventory": proof["receipt_inventory_count"], "proof_sha256": digest(OUT / "actual-master-projection-proof.json")}))


if __name__ == "__main__":
    main()
