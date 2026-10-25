"""Record exact prior release selections for Anne's first examination."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/_logs/anne-askew-first-private-release-20261002-v1"
WORK_ID = "anne-askew-first-examinacyon"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    selection_paths = [
        ROOT / "exports/whole-library-offline-rehearsal-20260925/internal/release-selection.json",
        ROOT / "exports/whole-library-offline-rehearsal-20260925-r2/internal/release-selection.json",
        ROOT / "exports/.whole-library-offline-rehearsal-20260926-35-ax5y6oec/internal/release-selection.json",
    ]
    selection_paths.extend(sorted((ROOT / "exports/releases").glob("*/internal/release-selection.json")))
    if len(selection_paths) != 12:
        raise ValueError(f"Anne historical release selection count differs: {len(selection_paths)}")
    surveyed = []
    for path in selection_paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        items = value["items"]
        matching = [item for item in items if item.get("work_id") == WORK_ID or item.get("item_id") == WORK_ID or WORK_ID in item.get("acceptance_path", "")]
        if matching:
            raise ValueError(f"Previously selected Anne first work found; reconcile before new release: {path}")
        surveyed.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "items": len(items), "first_work_selected": False, "global_work_coverage_mentions_first": WORK_ID in value.get("work_coverage", [])})
    # The sibling report release has a sandbox-readable, host-denied ACL. Its
    # exact one-item identity and digest were read separately in the sandbox.
    surveyed.append({"path": "reports/_logs/anne-askew-lattre-examinacyon-offline-20261001/release/internal/release-selection.json", "sha256": "571fb9c9a21c8625c75fae3dd20cdb19ee75448178beaa148eed5a1e71931d35", "items": 1, "first_work_selected": False, "selected_item_id": "anne-askew-lattre-examinacyon", "access_context": "sandbox-read-verified; host path denied"})
    if (ROOT / "library/works/anne-askew-first-examinacyon/publication/completion.json").exists():
        raise ValueError("Anne first canonical completion appeared during historical reconciliation")
    report = {
        "contract": "ocd-anne-first-prior-release-reconciliation-v1",
        "status": "no-exact-selected-first-work-release-found",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": WORK_ID,
        "surveys": surveyed,
        "selection_count": len(surveyed),
        "global_coverage_is_not_selected_item": True,
        "later_examination_distinct_work_id": "anne-askew-lattre-examinacyon",
        "canonical_completion_present": False,
        "qualification": "This exact retained-selection survey does not claim every historical report absent; the installed first work has no selected item or completion in these known release homes.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "historical-release-reconciliation.json"
    with path.open("xb") as stream:
        stream.write((json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps({"status": report["status"], "selection_count": len(surveyed), "receipt_sha256": digest(path)}))


if __name__ == "__main__":
    main()
