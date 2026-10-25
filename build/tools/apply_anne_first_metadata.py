"""Apply the reviewed Anne first category/language fields with exact guards."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/anne-askew-first-examinacyon/work.json"
LOG = ROOT / "reports/_logs/anne-askew-first-private-release-20261002-v1"
BEFORE = "cf78e6942703699cb020bbcc5908436693f0112b94eee488d2c82f088e281ae4"
AFTER = "e06fef5468358bf89752753352e848391039747409fd95015b41c511c88b44fd"
PROPOSAL_SHA = "f1b5691e40355e31d6e2245b19bd78e03ddfc48fe90f86c8b5d88f05d6e939af"
SOURCE_CONTEXT_SHA = "e9335890d84ab37fe37252ee6056a4430e86889c7b0ba3f37ab5ca275196f855"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    current = WORK.read_bytes()
    proposed = (LOG / "work-metadata-successor.json").read_bytes()
    if sha(current) != BEFORE or sha(proposed) != AFTER or sha((LOG / "work-metadata-proposal.json").read_bytes()) != PROPOSAL_SHA:
        raise ValueError("Anne metadata reviewed preimage/proposal/successor drifted")
    if sha((LOG / "source-context.json").read_bytes()) != SOURCE_CONTEXT_SHA:
        raise ValueError("Anne current source comparison drifted")
    before = json.loads(current)
    after = json.loads(proposed)
    form = before["textual_forms"][0]
    edition = form["editions"][0]
    form["language"] = "en"
    edition["language"] = "en"
    edition["category"] = "prose"
    if before != after:
        raise ValueError("Anne proposed successor changes another field")
    clearance = {
        "contract": "ocd-anne-first-metadata-apply-clearance-v1",
        "status": "approved-exact-metadata-delta",
        "coordinator_review_chunk": "d6e3aa",
        "coordinator_review_exit_code": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "work_path": WORK.relative_to(ROOT).as_posix(),
        "before_sha256": BEFORE,
        "after_sha256": AFTER,
        "proposal_sha256": PROPOSAL_SHA,
        "source_context_sha256": SOURCE_CONTEXT_SHA,
        "scope": "form and edition language=en; edition category=prose only",
    }
    clearance_path = LOG / "coordinator-metadata-clearance.json"
    with clearance_path.open("xb") as stream:
        stream.write((json.dumps(clearance, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    temporary = WORK.with_name("work.anne-metadata.tmp")
    with temporary.open("xb") as stream:
        stream.write(proposed)
    os.replace(temporary, WORK)
    if sha(WORK.read_bytes()) != AFTER:
        raise ValueError("Anne metadata readback differs")
    print(json.dumps({"status": "applied-readback-pass", "work_sha256": AFTER, "clearance_sha256": sha(clearance_path.read_bytes())}))


if __name__ == "__main__":
    main()
